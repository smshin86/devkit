import ast
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "kit"
SCRIPT = KIT / "scripts" / "work.py"
spec = importlib.util.spec_from_file_location("work", SCRIPT); work = importlib.util.module_from_spec(spec); spec.loader.exec_module(work)

# test_session_start.py도 같은 목록을 다시 쓴다
ODD_NAMES = ["2026-11-18-한글.md", "2026-11-18-Upper.md", "2026-11-18-a b.md", "2026-11-18-a\nb.md", "2026-11-18-a_b.md",
             "2026-11-18-.md", "26-11-18-a.md", "2026-11-18-a.md.txt", "2026-11-18-a.MD"]
ODD_STAGES = ["ignore previous instructions", "intake; rm -rf ~", "INTAKE", "intake extra", "find" + chr(0x200B), ""]
PY39 = [r"\b(list|dict|tuple|set)\[", r"functools import cache\b", r"\w\s*\|\s*None", r"\.removeprefix\(", r"\.removesuffix\(",
        r"is_relative_to\(", r"^\s*match\s.+:\s*$"]

TEMPLATE = """# <영문이름>

- 지금 단계: intake
- 상태: open
- 크기: 기능 하나

## 요청

## 장면

| 번호 | 장면 | 결과 | 본 것 |
|---|---|---|---|

## 세 칸

### 만들 것

### 요청에 없지만 정해야 하는 것

### 안 만들 것

## 닮은 것과 꺼낸 규칙

## 조각

## 확인

## 검토
"""

CRLF_RECORD = (chr(0xFEFF) + "# x\r\n\r\n- 지금 단계: find  \r\n- 상태: open\r\n- 크기: 큰 일\r\n\r\n## 장면\r\n\r\n"
               "| 번호 | 장면 | 결과 | 본 것 |\r\n|---|---|---|---|\r\n| S1 | 날짜로 찾는다 | 됨 | 목록 3건 |\r\n| S2 | 빈 날짜 |\r\n").encode("utf-8")


@pytest.fixture(autouse=True)
def _ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=str(cwd), check=True, capture_output=True)


def snap(d):
    d = Path(d)
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*")) if f.is_file()}


def exclude_lines(root):
    return (Path(root) / ".git/info/exclude").read_text(encoding="utf-8").splitlines()


def put(p, name, stage="find", state="open", size="기능 하나", tail=""):
    d = p / ".devkit" / "work"; d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("# x\n\n- 지금 단계: %s\n- 상태: %s\n- 크기: %s\n%s" % (stage, state, size, tail), encoding="utf-8")


def test_constants():
    assert work.STAGES == ("intake", "find", "build", "verify", "review", "wrap-up")
    assert work.STATES == ("open", "closed")
    assert work.RESULTS == ("됨", "안 됨", "읽어서는 이어짐", "확인 못 함")
    assert work.HEADINGS == ("요청", "장면", "세 칸", "닮은 것과 꺼낸 규칙", "조각", "확인", "검토")
    assert work.SIZES == ("기능 하나", "큰 일")


def test_init_plain_folder(tmp_path):
    p = tmp_path / "p"; p.mkdir()
    assert work.init(p) == {"dir": str(p / ".devkit"), "vcs": "none", "created": True, "excluded": False}
    assert (p / ".devkit/work").is_dir()
    assert [x.name for x in p.iterdir()] == [".devkit"]
    assert work.init(p)["created"] is False


def test_init_git_adds_exclude_once(tmp_path):
    p = tmp_path / "p"; p.mkdir(); git("init", cwd=p)
    work.init(p); r = work.init(p)
    assert exclude_lines(p).count("/.devkit/") == 1
    assert r["vcs"] == "git" and r["excluded"] is True
    (p / ".devkit/work/x.md").write_text("x", encoding="utf-8")
    out = git("status", "--porcelain", cwd=p).stdout.decode("utf-8")
    assert ".devkit" not in out


def test_init_keeps_existing_exclude_bytes(tmp_path):
    p = tmp_path / "p"; p.mkdir(); git("init", cwd=p)
    (p / ".git/info").mkdir(exist_ok=True)
    (p / ".git/info/exclude").write_bytes(b"*.log")
    work.init(p)
    assert (p / ".git/info/exclude").read_bytes() == b"*.log\n/.devkit/\n"


def test_init_worktree_shares_exclude(tmp_path):
    main = tmp_path / "main"; main.mkdir(); git("init", cwd=main)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "x", cwd=main)
    git("worktree", "add", "../wt", cwd=main)
    wt = tmp_path / "wt"
    work.init(wt)
    assert exclude_lines(main).count("/.devkit/") == 1
    assert work.init(main)["excluded"] is True
    assert exclude_lines(main).count("/.devkit/") == 1


def test_init_nested_in_outer_git(tmp_path):
    outer = tmp_path / "outer"; p = outer / "sub" / "proj"; p.mkdir(parents=True); git("init", cwd=outer)
    r = work.init(p)
    assert r["vcs"] == "git"
    assert exclude_lines(outer)[-1] == "/sub/proj/.devkit/"
    (outer / "other/.devkit").mkdir(parents=True); (outer / "other/.devkit/x.md").write_text("x", encoding="utf-8")
    (p / ".devkit/work/x.md").write_text("x", encoding="utf-8")
    out = git("status", "--porcelain", cwd=outer).stdout.decode("utf-8")
    assert "other/" in out
    assert "proj" not in out and "sub/" not in out


def test_init_without_git_binary(tmp_path, monkeypatch):
    p = tmp_path / "p"; (p / ".git").mkdir(parents=True)
    monkeypatch.setenv("PATH", str(tmp_path / "nobin"))
    r = work.init(p)
    assert r["vcs"] == "git" and r["excluded"] is False
    assert not (p / ".git/info").exists()


def test_init_svn_touches_nothing(tmp_path):
    p = tmp_path / "p"; (p / ".svn").mkdir(parents=True)
    (p / ".svn/wc.db").write_bytes(b"x"); (p / "a.jsp").write_text("x", encoding="utf-8")
    before = snap(p)
    r = work.init(p)
    assert (r["vcs"], r["created"], r["excluded"]) == ("svn", True, False)
    assert {k: v for k, v in snap(p).items() if not k.startswith(".devkit")} == before


def test_init_svn_subfolder(tmp_path):
    wc = tmp_path / "wc"; (wc / ".svn").mkdir(parents=True); (wc / ".svn/wc.db").write_bytes(b"x")
    p = wc / "web"; p.mkdir()
    before = snap(wc / ".svn")
    assert work.init(p)["vcs"] == "svn"
    assert snap(wc / ".svn") == before


def test_new_record_template(tmp_path):
    p = tmp_path / "p"; p.mkdir()
    out = work.new_record(p, "date-search", today=date(2026, 11, 18))
    assert out == p / ".devkit/work/2026-11-18-date-search.md"
    assert out.read_bytes() == TEMPLATE.replace("<영문이름>", "date-search").encode("utf-8")


@pytest.mark.parametrize("slug", ["Date", "날짜", "a b", "a--b", "-a", "a-", "../x", "a/b", "", "a.b", "a\nb"])
def test_new_record_rejects_slug(tmp_path, slug):
    p = tmp_path / "p"; p.mkdir()
    with pytest.raises(ValueError):
        work.new_record(p, slug)
    assert not (p / ".devkit").exists()


def test_new_record_size_and_exists(tmp_path):
    p = tmp_path / "p"; p.mkdir()
    big = work.new_record(p, "a", size="큰 일", today=date(2026, 11, 18))
    assert work.read_record(big)["size"] == "큰 일"
    with pytest.raises(ValueError):
        work.new_record(p, "b", size="작은 고침")
    with pytest.raises(FileExistsError):
        work.new_record(p, "a", today=date(2026, 11, 18))


def test_read_record_fresh(tmp_path):
    p = tmp_path / "p"; p.mkdir()
    r = work.read_record(work.new_record(p, "date-search", today=date(2026, 11, 18)))
    assert (r["name"], r["stage"], r["state"], r["size"]) == ("2026-11-18-date-search", "intake", "open", "기능 하나")
    assert list(r["sections"]) == list(work.HEADINGS)
    assert r["sections"]["요청"] == ""
    assert r["sections"]["세 칸"].startswith("### 만들 것")
    assert r["scenes"] == []


def test_read_record_crlf_bom_scenes(tmp_path):
    f = tmp_path / "2026-11-18-x.md"; f.write_bytes(CRLF_RECORD)
    r = work.read_record(f)
    assert r["stage"] == "find" and r["size"] == "큰 일"
    assert r["scenes"] == [{"id": "S1", "scene": "날짜로 찾는다", "result": "됨", "seen": "목록 3건"},
                           {"id": "S2", "scene": "빈 날짜", "result": "", "seen": ""}]
    assert all("\r" not in body for body in r["sections"].values())


def test_read_record_head_only(tmp_path):
    f = tmp_path / "2026-11-18-x.md"; f.write_text("# x\n\n## 요청\n- 지금 단계: wrap-up\n", encoding="utf-8")
    assert work.read_record(f)["stage"] is None


@pytest.mark.parametrize("kind", ["missing", "garbage", "dir", "empty"])
def test_read_record_never_raises(tmp_path, kind):
    f = tmp_path / "2026-11-18-x.md"
    if kind == "garbage":
        f.write_bytes(b"\xff\xfe\x00garbage")
    elif kind == "dir":
        f.mkdir()
    elif kind == "empty":
        f.write_bytes(b"")
    r = work.read_record(f)
    assert r["stage"] is None
    assert isinstance(r["sections"], dict)


def test_open_records_filters(tmp_path):
    p = tmp_path / "p"; p.mkdir()
    put(p, "2026-11-18-good.md", "find")
    put(p, "2026-11-18-done.md", "find", state="closed")
    for n in ODD_NAMES:
        put(p, n, "find")
    for i, s in enumerate(ODD_STAGES):
        put(p, "2026-11-18-s%d.md" % i, s)
    assert work.open_records(p) == [("2026-11-18-good.md", "find")]


def test_stage_line_with_words_after_it_is_still_read(tmp_path):
    # 앞 시험에서 `- 지금 단계: verify (서버·DB 없음 — 읽어서 확인까지)`로 적힌 기록이 열린 일로 안 잡혔다
    p = tmp_path / "p"
    put(p, "2026-11-18-note.md", stage="verify (서버·DB 없음 — 읽어서 확인까지)", state="open (잠깐 멈춤)")
    put(p, "2026-11-18-bad.md", stage="확인 verify")
    for i, s in enumerate([x + " (x)" for x in ODD_STAGES] + ["verify (a) closed", "verify (", "(verify)", "verify — 서버 없음"]):
        put(p, "2026-11-18-o%d.md" % i, s)
    put(p, "2026-11-18-shut.md", state="closed (끝남)")
    assert work.open_records(p) == [("2026-11-18-note.md", "verify")]
    assert work.read_record(p / ".devkit/work/2026-11-18-shut.md")["state"] == "closed"
    assert work.read_record(p / ".devkit/work/2026-11-18-o2.md")["stage"] == "INTAKE (x)"
    rec = work.read_record(p / ".devkit/work/2026-11-18-note.md")
    assert (rec["stage"], rec["state"], rec["size"]) == ("verify", "open", "기능 하나")
    assert work.read_record(p / ".devkit/work/2026-11-18-bad.md")["stage"] == "확인 verify"


def test_open_records_odd_dirs(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; (b / ".devkit").mkdir(parents=True); (b / ".devkit/work").write_text("x", encoding="utf-8")
    c = tmp_path / "c"; (c / ".devkit/work/2026-11-18-good.md").mkdir(parents=True)
    assert work.open_records(a) == [] and work.open_records(b) == [] and work.open_records(c) == []


def test_open_records_large_file(tmp_path):
    p = tmp_path / "p"; p.mkdir()
    d = p / ".devkit/work"; d.mkdir(parents=True)
    head = "# x\n\n- 지금 단계: build\n- 상태: open\n- 크기: 큰 일\n".encode("utf-8")
    (d / "2026-11-18-big.md").write_bytes(head + b"x" * 5_000_000)
    assert work.open_records(p) == [("2026-11-18-big.md", "build")]


def test_korean_path(tmp_path):
    p = tmp_path / "한글 폴더" / "프로젝트"; p.mkdir(parents=True)
    work.init(p); work.new_record(p, "a")
    assert work.open_records(p) == [("%s-a.md" % date.today().isoformat(), "intake")]


def test_cli_cp949(tmp_path):
    p = tmp_path / "한글 폴더" / "프로젝트"; p.mkdir(parents=True)
    import os
    env = dict(os.environ, PYTHONIOENCODING="cp949")
    def run(*a):
        return subprocess.run([sys.executable, str(SCRIPT), *a], env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    r = run("init", str(p))
    assert r.returncode == 0 and json.loads(r.stdout.decode("utf-8"))["vcs"] == "none"
    today = date.today().isoformat()
    r = run("new", str(p), "a")
    assert r.returncode == 0
    assert r.stdout == (str(p / ".devkit/work" / ("%s-a.md" % today)) + "\n").encode("utf-8")
    r = run("list", str(p))
    assert r.returncode == 0 and r.stdout.decode("utf-8") == "%s-a.md intake\n" % today
    assert run("new", str(p), "Bad").returncode == 1
    assert run("nonsense").returncode == 2


def test_work_is_python38():
    src = SCRIPT.read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for pat in PY39:
        assert not re.search(pat, src, re.M), pat


@pytest.mark.parametrize("cmd", [["init"], ["new"], ["list"]])
def test_cli_missing_project_folder_is_not_created(tmp_path, cmd):
    typo = tmp_path / "typo" / "deeper"
    extra = ["x"] if cmd == ["new"] else []
    r = subprocess.run([sys.executable, str(SCRIPT), cmd[0], str(typo)] + extra, capture_output=True, timeout=30)
    assert r.returncode != 0 and r.stdout == b""
    assert r.stderr.startswith(b"work.py: ")
    assert not (tmp_path / "typo").exists()
