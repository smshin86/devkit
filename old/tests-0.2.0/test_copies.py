"""copies.py 시험 — 임시 폴더에 새로 만든 git 저장소에서만 돈다.

시험이 TMPDIR·HOME을 임시 폴더로 돌려, 사본이 진짜 /tmp로 새지 않고 진짜 홈을 읽지 않는다.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "kit" / "scripts" / "copies.py"

_GIT_ENV = {k: v for k, v in os.environ.items()
            if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_")) and k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
_GIT_ENV.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)


def env(tmp, extra=None):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_")) and k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    home = tmp / "home"
    t = tmp / "t"
    home.mkdir(exist_ok=True)
    t.mkdir(exist_ok=True)
    e.update(HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / ".config"),
             GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(home / ".gitconfig"),
             TMPDIR=str(t), TEMP=str(t), TMP=str(t))
    if extra:
        e.update(extra)
    return e


def run(tmp, *args, extra=None):
    p = subprocess.run([sys.executable, str(SCRIPT), *args], env=env(tmp, extra), capture_output=True)
    data = json.loads(p.stdout.decode("utf-8"))
    t = (tmp / "t").resolve()
    for c in data.get("copies", []):
        assert t in Path(c["path"]).resolve().parents, c["path"]
    return p.returncode, data, p.stderr


def g(repo, *args):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo), *args],
                       env=_GIT_ENV, capture_output=True)
    assert p.returncode == 0, (args, p.stderr)
    return p.stdout.decode("utf-8").strip()


def make_repo(tmp, rel="proj"):
    repo = tmp / rel
    repo.mkdir(parents=True)
    g(repo, "init", "-b", "main")
    (repo / ".gitignore").write_bytes(b".devkit/\nignored.log\n")
    (repo / "a.txt").write_bytes(b"one\n")
    (repo / "b.txt").write_bytes(b"keep\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-m", "init")
    return repo


def user_state(repo):
    with open(str(repo / "a.txt"), "ab") as f:
        f.write(b"user\n")
    (repo / "new.txt").write_bytes(b"n\n")
    (repo / "ignored.log").write_bytes(b"ig\n")
    (repo / ".devkit" / "work").mkdir(parents=True)
    (repo / ".devkit" / "work" / "r.md").write_bytes(b"rec\n")
    with open(str(repo / "b.txt"), "ab") as f:
        f.write(b"st\n")
    g(repo, "add", "b.txt")


def files(repo):
    out = {}
    for dp, dn, fn in os.walk(str(repo)):
        dn[:] = [d for d in dn if d != ".git"]
        for f in fn:
            p = Path(dp) / f
            out[str(p.relative_to(repo)).replace(os.sep, "/")] = p.read_bytes()
    return out


def KEEP(repo, tmp, head, cached):           # Review Focus 2 — 한 회차가 끝난 뒤 언제나
    assert g(repo, "rev-parse", "HEAD") == head
    assert g(repo, "symbolic-ref", "--short", "HEAD") == "main"
    assert g(repo, "diff", "--cached", "--name-only") == cached          # 사용자의 스테이지 그대로
    assert g(repo, "for-each-ref", "--format=%(refname)", "refs/heads") == "refs/heads/main"
    assert g(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert g(repo, "rev-list", "--all", "--count") == "1"                 # 남은 커밋 없음
    assert not list((tmp / "t").glob("devkit-copies-*"))


def snapshot_of(repo):
    return g(repo, "rev-parse", "HEAD"), g(repo, "diff", "--cached", "--name-only")


def load_module():
    spec = importlib.util.spec_from_file_location("copies_under_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_start_copies_current_state_outside_project(tmp_path):   # 2조각
    repo = make_repo(tmp_path)
    user_state(repo)
    before = files(repo)
    head, cached = snapshot_of(repo)
    rc, d, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 0 and d["ok"] is True
    assert len(d["copies"]) == 2
    assert [c["piece"] for c in d["copies"]] == ["P1", "P2"]
    assert re.fullmatch("[0-9a-f]{8}", d["id"])
    for i, c in enumerate(d["copies"], 1):
        assert c["branch"] == "devkit-tmp/%s/p%d" % (d["id"], i)
        p = Path(c["path"])
        assert repo not in p.parents
        assert (p / "a.txt").read_bytes() == b"one\nuser\n"
        assert (p / "new.txt").read_bytes() == b"n\n"
        assert (p / "b.txt").read_bytes() == b"keep\nst\n"
        assert not (p / "ignored.log").exists()
        assert not (p / ".devkit").exists()
    assert files(repo) == before
    rc, _, _ = run(tmp_path, "clean", str(repo), d["id"])
    assert rc == 0
    KEEP(repo, tmp_path, head, cached)


def test_round_keeps_user_branch_head_and_changes(tmp_path):      # 3조각
    repo = make_repo(tmp_path)
    user_state(repo)
    head, cached = snapshot_of(repo)
    rc, d, _ = run(tmp_path, "start", str(repo), "3")
    assert rc == 0
    p1, p2, p3 = [Path(c["path"]) for c in d["copies"]]
    with open(str(p1 / "a.txt"), "ab") as f:
        f.write(b"p1\n")
    (p1 / "p1.txt").write_bytes(b"x\n")
    (p2 / "b.txt").unlink()
    rc, m, _ = run(tmp_path, "merge", str(repo), d["id"])
    assert rc == 0
    assert m["merged"] == ["P1", "P2"] and m["unchanged"] == ["P3"] and m["conflicts"] == []
    rc, a, _ = run(tmp_path, "apply", str(repo), d["id"])
    assert rc == 0 and a["changed"] == ["a.txt", "b.txt", "p1.txt"]
    rc, _, _ = run(tmp_path, "clean", str(repo), d["id"])
    assert rc == 0
    assert (repo / "a.txt").read_bytes() == b"one\nuser\np1\n"
    assert (repo / "p1.txt").read_bytes() == b"x\n"
    assert not (repo / "b.txt").exists()
    assert (repo / "new.txt").read_bytes() == b"n\n"
    assert (repo / "ignored.log").read_bytes() == b"ig\n"
    assert (repo / ".devkit" / "work" / "r.md").read_bytes() == b"rec\n"
    assert "?? p1.txt" in g(repo, "status", "--porcelain")
    KEEP(repo, tmp_path, head, cached)


def test_conflict_stops_and_original_untouched(tmp_path):
    repo = make_repo(tmp_path)
    user_state(repo)
    head, cached = snapshot_of(repo)
    rc, d, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 0
    before = files(repo)
    status = g(repo, "status", "--porcelain")
    p1, p2 = [Path(c["path"]) for c in d["copies"]]
    (p1 / "a.txt").write_bytes(b"one\nP1\n")
    (p2 / "a.txt").write_bytes(b"one\nP2\n")
    rc, m, _ = run(tmp_path, "merge", str(repo), d["id"])
    assert rc == 3 and m["ok"] is False
    assert m["conflicts"] == [{"piece": "P2", "files": ["a.txt"]}]
    assert m["merged"] == ["P1"]
    assert files(repo) == before
    assert g(repo, "status", "--porcelain") == status
    rc, _, _ = run(tmp_path, "clean", str(repo), d["id"])
    assert rc == 0
    KEEP(repo, tmp_path, head, cached)


def test_apply_refuses_when_original_changed_after_start(tmp_path):
    repo = make_repo(tmp_path)
    user_state(repo)
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 0
    with open(str(Path(d["copies"][0]["path"]) / "a.txt"), "ab") as f:
        f.write(b"p1\n")
    rc, m, _ = run(tmp_path, "merge", str(repo), d["id"])
    assert rc == 0
    (repo / "new.txt").write_bytes(b"later\n")
    rc, a, _ = run(tmp_path, "apply", str(repo), d["id"])
    assert rc == 4 and a["ok"] is False
    assert "new.txt" in a["files"]
    assert (repo / "new.txt").read_bytes() == b"later\n"
    assert (repo / "a.txt").read_bytes() == b"one\nuser\n"
    rc, _, _ = run(tmp_path, "clean", str(repo), d["id"])
    assert rc == 0


def test_refuses_not_git(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "x.txt").write_bytes(b"x\n")
    rc, d, _ = run(tmp_path, "start", str(plain), "2")
    assert rc == 2 and d["message"].startswith("차례로 하라: ")
    assert not list((tmp_path / "t").glob("devkit-copies-*"))


def test_refuses_repo_without_commit(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    g(repo, "init", "-b", "main")
    rc, d, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 2 and d["message"].startswith("차례로 하라: ")


def test_refuses_when_git_missing(tmp_path):
    repo = make_repo(tmp_path)
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    rc, d, _ = run(tmp_path, "start", str(repo), "2", extra={"PATH": str(nogit)})
    assert rc == 2 and d["message"].startswith("차례로 하라: ")


def test_refuses_leftover_round_until_clean(tmp_path):
    repo = make_repo(tmp_path)
    rc, d, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 0
    rc, d2, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 2 and d["id"] in d2["message"] and "clean" in d2["message"]
    rc, _, _ = run(tmp_path, "clean", str(repo), d["id"])
    assert rc == 0
    rc, d3, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 0
    rc, _, _ = run(tmp_path, "clean", str(repo), d3["id"])
    assert rc == 0


def test_clean_after_crash(tmp_path):
    repo = make_repo(tmp_path)
    user_state(repo)
    head, cached = snapshot_of(repo)
    rc, d, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 0
    shutil.rmtree(d["copies"][0]["path"])                 # 멈춘 흉내
    rc, lst, _ = run(tmp_path, "list", str(repo))
    assert rc == 0 and lst["rounds"][0]["id"] == d["id"]
    assert datetime.fromisoformat(lst["rounds"][0]["made"])
    rc, c, _ = run(tmp_path, "clean", str(repo))
    assert rc == 0 and len(c["removed"]["branches"]) == 3
    KEEP(repo, tmp_path, head, cached)
    rc, c2, _ = run(tmp_path, "clean", str(repo))
    assert rc == 0 and c2["removed"] == {"copies": [], "branches": []}


def test_user_hooks_do_not_run(tmp_path):
    repo = make_repo(tmp_path)
    user_state(repo)
    head, cached = snapshot_of(repo)
    hooks = repo / ".git" / "hooks"
    (hooks / "pre-commit").write_bytes(b"#!/bin/sh\nexit 1\n")
    (hooks / "post-checkout").write_bytes(("#!/bin/sh\ntouch '%s'\n" % (tmp_path / "hooked")).encode("utf-8"))
    for h in ("pre-commit", "post-checkout"):
        os.chmod(str(hooks / h), 0o755)
    rc, d, _ = run(tmp_path, "start", str(repo), "2")
    assert rc == 0
    with open(str(Path(d["copies"][0]["path"]) / "a.txt"), "ab") as f:
        f.write(b"p1\n")
    assert run(tmp_path, "merge", str(repo), d["id"])[0] == 0
    assert run(tmp_path, "apply", str(repo), d["id"])[0] == 0
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0
    assert not (tmp_path / "hooked").exists()
    KEEP(repo, tmp_path, head, cached)


def test_korean_path_and_crlf_bytes(tmp_path):
    repo = tmp_path / "한글 폴더" / "프로젝트"
    repo.mkdir(parents=True)
    g(repo, "init", "-b", "main")
    (repo / "화면").mkdir()
    (repo / "화면" / "목록.txt").write_bytes(b"a\r\nb\r\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-m", "init")
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 0
    (Path(d["copies"][0]["path"]) / "화면" / "목록.txt").write_bytes(b"a\r\nb\r\nc\r\n")
    assert run(tmp_path, "merge", str(repo), d["id"])[0] == 0
    rc, a, _ = run(tmp_path, "apply", str(repo), d["id"])
    assert rc == 0 and a["changed"] == ["화면/목록.txt"]
    assert (repo / "화면" / "목록.txt").read_bytes() == b"a\r\nb\r\nc\r\n"
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0


def test_project_in_subfolder_limits_to_it(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    g(root, "init", "-b", "main")
    (root / "out.txt").write_bytes(b"out\n")
    (root / "app").mkdir()
    (root / "app" / "x.txt").write_bytes(b"x\n")
    g(root, "add", "-A")
    g(root, "commit", "-m", "init")
    (root / "out_new.txt").write_bytes(b"new\n")
    rc, d, _ = run(tmp_path, "start", str(root / "app"), "1")
    assert rc == 0
    path = Path(d["copies"][0]["path"])
    assert str(path).endswith("app")
    assert not (path.parent / "out_new.txt").exists()          # 저장점에는 앱 폴더만 지금 상태
    (path / "x.txt").write_bytes(b"x\nmore\n")
    assert run(tmp_path, "merge", str(root / "app"), d["id"])[0] == 0
    rc, a, _ = run(tmp_path, "apply", str(root / "app"), d["id"])
    assert rc == 0 and a["changed"] == ["x.txt"]
    assert (root / "app" / "x.txt").read_bytes() == b"x\nmore\n"
    assert (root / "out_new.txt").read_bytes() == b"new\n"
    assert run(tmp_path, "clean", str(root / "app"), d["id"])[0] == 0


def test_mark_and_since_tell_my_changes_from_users(tmp_path):   # 머리말 18
    repo = make_repo(tmp_path)
    user_state(repo)
    head, cached = snapshot_of(repo)
    rc, mk, _ = run(tmp_path, "mark", str(repo))
    assert rc == 0 and mk["ok"] is True
    assert mk["dirty"] == ["a.txt", "b.txt", "new.txt"]
    assert mk["head"] == head
    KEEP(repo, tmp_path, head, cached)
    with open(str(repo / "a.txt"), "ab") as f:
        f.write(b"mine\n")
    (repo / "mine.txt").write_bytes(b"m\n")
    (repo / "new.txt").unlink()
    rc, s, _ = run(tmp_path, "since", str(repo), mk["tree"])
    assert rc == 0
    assert s["changed"] == ["a.txt"] and s["added"] == ["mine.txt"] and s["deleted"] == ["new.txt"]
    assert "b.txt" not in s["changed"] + s["added"] + s["deleted"]       # 사용자가 시작 전에 고친 것
    diff = g(repo, "diff", mk["tree"], "--", "a.txt")
    assert "+mine" in diff and "+user" not in diff


def test_mark_refuses_not_git_and_since_bad_tree(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, d, _ = run(tmp_path, "mark", str(plain))
    assert rc == 2 and d["message"].startswith("차례로 하라: ")
    repo = make_repo(tmp_path)
    rc, d, _ = run(tmp_path, "since", str(repo), "0123456789abcdef0123456789abcdef01234567")
    assert rc == 5 and d["ok"] is False


def test_round_with_autocrlf_true(tmp_path):                   # 위험 검토 2
    repo = make_repo(tmp_path)
    g(repo, "config", "core.autocrlf", "true")
    (repo / "w.txt").write_bytes(b"a\r\nb\r\n")
    g(repo, "add", "w.txt")
    g(repo, "commit", "-m", "w")
    # make_repo의 첫 커밋 하나에 둘째 커밋이 생겼으니 KEEP의 개수 단언을 위해 하나로 합친다
    g(repo, "reset", "--soft", "HEAD~1")
    g(repo, "commit", "--amend", "-m", "init")
    user_state(repo)
    head, cached = snapshot_of(repo)
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 0
    (Path(d["copies"][0]["path"]) / "w.txt").write_bytes(b"a\r\nb\r\nc\r\n")
    assert run(tmp_path, "merge", str(repo), d["id"])[0] == 0
    assert run(tmp_path, "apply", str(repo), d["id"])[0] == 0
    assert (repo / "w.txt").read_bytes() == b"a\r\nb\r\nc\r\n"
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0
    KEEP(repo, tmp_path, head, cached)


def test_start_refuses_big_untracked(tmp_path):                # 머리말 23 ①
    mod = load_module()
    repo = make_repo(tmp_path)
    with open(str(repo / "big.bin"), "wb") as f:
        f.truncate(mod.BIG_FILE + 1)
    head, cached = snapshot_of(repo)
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 2 and d["message"].startswith("차례로 하라: ") and "big.bin" in d["message"]
    assert not list((tmp_path / "t").glob("devkit-copies-*"))
    assert g(repo, "for-each-ref", "--format=%(refname)", "refs/heads") == "refs/heads/main"
    with open(str(repo / ".gitignore"), "ab") as f:
        f.write(b"big.bin\n")
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 0
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0


def test_start_refuses_huge_outer_repo(tmp_path):              # 머리말 23 ②
    mod = load_module()
    root = tmp_path / "root"
    root.mkdir()
    g(root, "init", "-b", "main")
    (root / "out").mkdir()
    for i in range(mod.OUTER_MAX + 1):
        (root / "out" / ("f%04d.txt" % i)).write_bytes(b"o\n")
    (root / "app").mkdir()
    (root / "app" / "x.txt").write_bytes(b"x\n")
    g(root, "add", "-A")
    g(root, "commit", "-m", "init")
    rc, d, _ = run(tmp_path, "start", str(root / "app"), "1")
    assert rc == 2 and d["message"].startswith("차례로 하라: ")
    assert not list((tmp_path / "t").glob("devkit-copies-*"))
    rc, d, _ = run(tmp_path, "start", str(root), "1")
    assert rc == 0
    assert run(tmp_path, "clean", str(root), d["id"])[0] == 0


def test_cp949_console_does_not_crash(tmp_path):
    repo = tmp_path / "한글 폴더" / "프로젝트"
    repo.mkdir(parents=True)
    g(repo, "init", "-b", "main")
    (repo / "화면").mkdir()
    (repo / "화면" / "목록.txt").write_bytes("가\n나\n".encode("utf-8"))
    g(repo, "add", "-A")
    g(repo, "commit", "-m", "init")
    cp = {"PYTHONIOENCODING": "cp949"}
    rc, d, err = run(tmp_path, "start", str(repo), "2", extra=cp)
    assert rc == 0
    p1, p2 = [Path(c["path"]) for c in d["copies"]]
    (p1 / "화면" / "목록.txt").write_bytes("가\n하나\n".encode("utf-8"))
    (p2 / "화면" / "목록.txt").write_bytes("가\n둘\n".encode("utf-8"))
    rc, m, err = run(tmp_path, "merge", str(repo), d["id"], extra=cp)
    assert rc == 3 and m["conflicts"] == [{"piece": "P2", "files": ["화면/목록.txt"]}]
    assert b"UnicodeEncodeError" not in err
    assert run(tmp_path, "clean", str(repo), d["id"], extra=cp)[0] == 0


def dir_size(path):
    total = 0
    for dp, dn, fn in os.walk(str(path)):
        for f in fn:
            try:
                total += os.lstat(os.path.join(dp, f)).st_size
            except OSError:
                pass
    return total


def test_apply_blocked_is_not_folder_changed(tmp_path):        # 고침 1
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_bytes(b".devkit/\nignored.log\nlocal.cfg\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-m", "ignore cfg")
    (repo / "local.cfg").write_bytes(b"mine\n")
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 0
    p1 = Path(d["copies"][0]["path"])
    (p1 / ".gitignore").write_bytes(b"")
    (p1 / "local.cfg").write_bytes(b"piece\n")
    rc, m, _ = run(tmp_path, "merge", str(repo), d["id"])
    assert rc == 0
    rc, a, _ = run(tmp_path, "apply", str(repo), d["id"])
    assert rc == 6 and a["ok"] is False and a["blocked"] is True
    assert a["files"] == ["local.cfg"]
    assert "already exists" in a["message"]
    assert (repo / "local.cfg").read_bytes() == b"mine\n"
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0


def test_clean_leaves_other_repos_copies(tmp_path):            # 고침 2
    x = make_repo(tmp_path, "x")
    y = make_repo(tmp_path, "y")
    rc, d, _ = run(tmp_path, "start", str(x), "1")
    assert rc == 0
    rdir = Path(d["copies"][0]["path"]).parent
    rc, c, _ = run(tmp_path, "clean", str(y), d["id"])
    assert rc == 0 and c["ok"] is True and c["removed"] == {"copies": [], "branches": []}
    assert rdir.is_dir()
    rc, c, _ = run(tmp_path, "clean", str(x), d["id"])
    assert rc == 0 and len(c["removed"]["branches"]) == 2
    assert not rdir.exists()


def test_start_failure_removes_own_round_folder(tmp_path, monkeypatch):   # 고침 2 (start 실패 뒤처리)
    import tempfile
    mod = load_module()
    repo = make_repo(tmp_path)
    (tmp_path / "t").mkdir(exist_ok=True)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "t"))
    monkeypatch.setattr(tempfile, "tempdir", None)

    def boom(top, prefix):
        raise mod.Stop("일부러")
    monkeypatch.setattr(mod, "current_tree", boom)
    with pytest.raises(mod.Refuse):
        mod.start(repo, 1)
    assert not list((tmp_path / "t").glob("devkit-copies-*"))


def test_planted_shared_nohooks_dir_never_runs(tmp_path):      # 고침 3
    repo = make_repo(tmp_path)
    planted = tmp_path / "t" / "devkit-nohooks"
    planted.mkdir(parents=True)
    for h in ("post-checkout", "post-merge"):
        (planted / h).write_bytes(("#!/bin/sh\ntouch '%s'\n" % (tmp_path / "marker")).encode("utf-8"))
        os.chmod(str(planted / h), 0o755)
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 0
    with open(str(Path(d["copies"][0]["path"]) / "a.txt"), "ab") as f:
        f.write(b"p1\n")
    assert run(tmp_path, "merge", str(repo), d["id"])[0] == 0
    assert not (tmp_path / "marker").exists()
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0
    assert not list((tmp_path / "t").glob("devkit-nohooks-*"))   # 끝나면 치운다


def test_mark_since_apply_refuse_big_untracked(tmp_path):      # 고침 4
    mod = load_module()
    repo = make_repo(tmp_path)
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    assert rc == 0
    with open(str(Path(d["copies"][0]["path"]) / "a.txt"), "ab") as f:
        f.write(b"p1\n")
    assert run(tmp_path, "merge", str(repo), d["id"])[0] == 0
    head, tree = g(repo, "rev-parse", "HEAD"), g(repo, "rev-parse", "HEAD^{tree}")
    with open(str(repo / "big.bin"), "wb") as f:
        f.write(os.urandom(mod.BIG_FILE + 1024 * 1024))
    before = dir_size(repo / ".git")
    rc, m, _ = run(tmp_path, "mark", str(repo))
    assert rc == 2 and m["message"].startswith("차례로 하라: ") and "big.bin" in m["message"]
    rc, s, _ = run(tmp_path, "since", str(repo), tree)
    assert rc == 2 and "big.bin" in s["message"]
    rc, a, _ = run(tmp_path, "apply", str(repo), d["id"])
    assert rc == 4 and a["ok"] is False and a["files"] == [] and "big.bin" in a["message"]
    assert dir_size(repo / ".git") - before < 1024 * 1024
    assert (repo / "a.txt").read_bytes() == b"one\n"
    os.remove(str(repo / "big.bin"))
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0


def test_merge_reports_changes_outside_project(tmp_path):      # 고침 5
    root = tmp_path / "root"
    root.mkdir()
    g(root, "init", "-b", "main")
    (root / "common").mkdir()
    (root / "common" / "c.js").write_bytes(b"c\n")
    (root / "app").mkdir()
    (root / "app" / "x.txt").write_bytes(b"x\n")
    g(root, "add", "-A")
    g(root, "commit", "-m", "init")
    rc, d, _ = run(tmp_path, "start", str(root / "app"), "2")
    assert rc == 0
    p1, p2 = [Path(c["path"]) for c in d["copies"]]
    (p1.parent / "common" / "c.js").write_bytes(b"c\nmore\n")
    (p1.parent / "common" / "new.js").write_bytes(b"n\n")
    (p2 / "x.txt").write_bytes(b"x\nmore\n")
    rc, m, _ = run(tmp_path, "merge", str(root / "app"), d["id"])
    assert rc == 0
    assert m["merged"] == ["P2"] and m["unchanged"] == ["P1"]
    assert m["outside"] == [{"piece": "P1", "files": ["common/c.js", "common/new.js"]}]
    assert run(tmp_path, "clean", str(root / "app"), d["id"])[0] == 0
    # 맨 위 프로젝트는 늘 빈 목록
    repo = make_repo(tmp_path, "top")
    rc, d, _ = run(tmp_path, "start", str(repo), "1")
    rc, m, _ = run(tmp_path, "merge", str(repo), d["id"])
    assert rc == 0 and m["outside"] == []
    assert run(tmp_path, "clean", str(repo), d["id"])[0] == 0
