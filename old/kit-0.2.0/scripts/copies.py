#!/usr/bin/env python3
"""devkit 동시에 만들기 도우미 (python3 표준 라이브러리만, git 2.17 이상).

  copies.py start <프로젝트> <조각 수>     지금 상태(커밋 안 한 고침·새 파일 포함)로 임시 저장점을 뜨고 조각마다 사본 하나
  copies.py merge <프로젝트> <회차>        사본마다 바뀐 것을 임시 가지에 모으고 통합 사본에서 P1부터 차례로 합친다
  copies.py apply <프로젝트> <회차>        통합 사본의 결과를 본래 폴더에 커밋 안 한 고침으로 얹는다
  copies.py clean <프로젝트> [<회차>]      사본·임시 가지를 지운다 (회차를 안 주면 남은 것 전부)
  copies.py list <프로젝트>                남아 있는 회차와 사본 자리, 만든 때
  copies.py mark <프로젝트>                지금 상태의 나무 번호를 찍는다 (가지도 사본도 만들지 않는다)
  copies.py since <프로젝트> <나무>         그 나무 뒤로 바뀐 파일 (이번 일이 바꾼 것)

끝 번호: 0 됨 / 1 쓰는 법 틀림 / 2 차례로 하라 / 3 합치다 부딪힘 / 4 사본을 뜬 뒤 본래 폴더가 바뀜 / 5 그 밖의 git 실패 /
6 본래 폴더에 얹을 수 없음(같은 이름의 파일이 이미 있는 등).
찍는 것은 언제나 JSON 한 덩이(stdout). 사용자의 가지·색인·하던 고침은 건드리지 않는다.
본래 폴더에 쓰는 것은 apply의 작업 폴더 변경 하나뿐이다.
"""
import argparse
import atexit
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BIG_FILE = 10 * 1024 * 1024
BIG_TOTAL = 50 * 1024 * 1024
OUTER_MAX = 2000

ID_RE = re.compile(r"^[0-9a-f]{8}$")
BRANCH_RE = re.compile(r"^devkit-tmp/([0-9a-f]{8})/([a-z0-9]+)$")
PIECE_RE = re.compile(r"^p([0-9]+)$")


class Refuse(Exception):
    """차례로 하라 (끝 번호 2)."""

    def __init__(self, msg: str) -> None:
        super().__init__("차례로 하라: " + msg)


class Stop(Exception):
    """그 밖의 git 실패로 멈춤 (끝 번호 5)."""


class Usage(Exception):
    """쓰는 법 틀림 (끝 번호 1)."""


# ---------------------------------------------------------------- git 도우미

_NOHOOKS = None  # type: Optional[str]


def _drop_nohooks() -> None:
    if _NOHOOKS:
        shutil.rmtree(_NOHOOKS, ignore_errors=True)


def nohooks_dir() -> str:
    """훅을 끄는 빈 폴더 — 이 실행만 쓰는 새 폴더(남이 미리 둔 폴더를 쓰지 않는다). 끝날 때 지운다."""
    global _NOHOOKS
    if _NOHOOKS is None or not os.path.isdir(_NOHOOKS):
        _NOHOOKS = tempfile.mkdtemp(prefix="devkit-nohooks-")
        atexit.register(_drop_nohooks)
    return _NOHOOKS


def git(args, cwd, check=True, input=None, index=None, raw=False):
    """모든 git 호출이 지나는 한 곳. 사용자의 훅·서명·한글 이름 따옴표가 끼지 않게 늘 같은 -c를 붙인다."""
    cmd = ["git", "-c", "core.hooksPath=" + nohooks_dir(), "-c", "commit.gpgsign=false",
           "-c", "core.quotepath=false"] + list(args)
    e = dict(os.environ)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR"):
        e.pop(k, None)
    e.update(GIT_AUTHOR_NAME="devkit", GIT_AUTHOR_EMAIL="devkit@localhost",
             GIT_COMMITTER_NAME="devkit", GIT_COMMITTER_EMAIL="devkit@localhost",
             GIT_TERMINAL_PROMPT="0", GIT_LITERAL_PATHSPECS="1")
    if index is not None:
        e["GIT_INDEX_FILE"] = str(index)
    kw = {}  # type: Dict[str, object]
    if not raw:
        kw["encoding"] = "utf-8"
        kw["errors"] = "replace"
    if input is None:
        kw["stdin"] = subprocess.DEVNULL
    try:
        p = subprocess.run(cmd, cwd=str(cwd), env=e, input=input,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    except FileNotFoundError:
        raise Refuse("git을 찾을 수 없다")
    if check and p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace") if raw else p.stderr
        raise Stop("git %s 실패: %s" % (args[0], err.strip()[:300]))
    return p


def spec(prefix: str) -> str:
    """`--` 뒤에 쓸 경로 가리개. 저장소 맨 위 프로젝트는 prefix가 빈 글자라 그대로 쓰면 git이 죽는다."""
    return prefix or "."


def names(text: str, prefix: str) -> List[str]:
    """`-z` 출력의 파일 이름 목록 — 프로젝트 기준 상대 경로, `/` 구분, 정렬."""
    out = []
    for n in text.split("\0"):
        if not n:
            continue
        if prefix and n.startswith(prefix):
            n = n[len(prefix):]
        out.append(n)
    return sorted(out)


def _rmtree(path) -> None:
    def onerr(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            raise
    shutil.rmtree(str(path), onerror=onerr)


def round_dir(rid: str) -> Path:
    return Path(tempfile.gettempdir()) / ("devkit-copies-" + rid)


def proj_path(root, prefix: str) -> str:
    return str(Path(str(root)) / prefix) if prefix else str(root)


# ---------------------------------------------------------------- 저장소 보기

def repo_info(project) -> Dict[str, object]:
    p = git(["rev-parse", "--show-toplevel"], project, check=False)
    if p.returncode != 0:
        raise Refuse("이 폴더는 git 저장소가 아니다")
    top = Path(p.stdout.rstrip("\n"))
    prefix = git(["rev-parse", "--show-prefix"], project, check=False).stdout.rstrip("\n")
    if git(["rev-parse", "--verify", "HEAD"], project, check=False).returncode != 0:
        raise Refuse("저장소에 커밋이 아직 없다")
    return {"top": top, "prefix": prefix}


def refuse_big_new(top, prefix: str) -> None:
    """큰 새 파일이 사용자의 .git에 남지 않게 — 나무를 뜨기 전에 늘 지난다."""
    new = git(["ls-files", "--others", "--exclude-standard", "-z", "--", spec(prefix)], top).stdout
    total = 0
    for rel in [x for x in new.split("\0") if x]:
        try:
            size = os.lstat(str(Path(top) / rel)).st_size
        except OSError:
            continue
        if size > BIG_FILE:
            raise Refuse("git이 모르는 큰 새 파일이 있다: %s (%d MB). 사본을 뜨면 이 파일이 저장소에 남는다"
                         % (rel, size // (1024 * 1024)))
        total += size
    if total > BIG_TOTAL:
        raise Refuse("git이 모르는 새 파일이 모두 %d MB다. 사본을 뜨면 저장소에 남는다" % (total // (1024 * 1024)))


def current_tree(top, prefix: str) -> str:
    """지금 작업 폴더 상태(커밋 안 한 고침·새 파일 포함, git이 무시하는 것 제외)의 나무.
    임시 색인으로만 만들어 사용자의 색인은 열지 않는다."""
    refuse_big_new(top, prefix)
    tmp = tempfile.mkdtemp(prefix="devkit-idx-")
    idx = os.path.join(tmp, "index")
    try:
        git(["read-tree", "HEAD"], top, index=idx)
        git(["add", "-A", "--", spec(prefix)], top, index=idx)
        return git(["write-tree"], top, index=idx).stdout.strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def worktrees(top) -> List[Tuple[str, Optional[str]]]:
    """[(자리, 가지 또는 None)]"""
    out = []  # type: List[Tuple[str, Optional[str]]]
    path = None  # type: Optional[str]
    branch = None  # type: Optional[str]
    for line in git(["worktree", "list", "--porcelain"], top).stdout.split("\n"):
        if line.startswith("worktree "):
            if path is not None:
                out.append((path, branch))
            path, branch = line[len("worktree "):], None
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):]
    if path is not None:
        out.append((path, branch))
    return out


def round_branches(top, rid: Optional[str] = None) -> List[str]:
    out = git(["for-each-ref", "--format=%(refname)", "refs/heads/devkit-tmp/"], top).stdout
    res = []
    for ref in out.split("\n"):
        if not ref.startswith("refs/heads/"):
            continue
        b = ref[len("refs/heads/"):]
        m = BRANCH_RE.match(b)
        if m and (rid is None or m.group(1) == rid):
            res.append(b)
    return sorted(res)


def rounds(top) -> List[str]:
    ids = set()
    for b in round_branches(top):
        ids.add(BRANCH_RE.match(b).group(1))
    for _, b in worktrees(top):
        m = BRANCH_RE.match(b or "")
        if m:
            ids.add(m.group(1))
    return sorted(ids)


def round_worktrees(top, rid: str) -> List[Tuple[str, str]]:
    res = []
    for path, b in worktrees(top):
        m = BRANCH_RE.match(b or "")
        if m and m.group(1) == rid:
            res.append((path, b))
    return res


def piece_order(b: str) -> Tuple[int, str]:
    m = PIECE_RE.match(BRANCH_RE.match(b).group(2))
    return (int(m.group(1)), b) if m else (10 ** 9, b)


def need_round(top, rid: str) -> None:
    if not ID_RE.match(rid or ""):
        raise Usage("회차는 16진 8자다: %s" % rid)
    if "devkit-tmp/%s/snap" % rid not in round_branches(top, rid):
        raise Usage("그런 회차가 없다: %s (copies.py list로 본다)" % rid)


# ---------------------------------------------------------------- 명령

def start(project, n: int) -> Dict[str, object]:
    if n < 1:
        raise Usage("조각 수는 1 이상이다")
    info = repo_info(project)
    top, prefix = info["top"], info["prefix"]
    left = rounds(top)
    if left:
        raise Refuse("아직 치우지 않은 임시 사본 회차가 남아 있다(%s). 다른 창에서 만드는 중이 아니면 "
                     "`clean %s`로 치운 뒤 다시 하고, 아니면 차례로 한다" % (", ".join(left), left[0]))
    # 사본마다 바깥 저장소 전체가 펼쳐지지 않게
    if prefix:
        tracked = [x for x in git(["ls-files", "-z"], top).stdout.split("\0") if x]
        outer = len([x for x in tracked if not x.startswith(prefix)])
        if outer > OUTER_MAX:
            raise Refuse("이 폴더 밖의 저장소 파일이 %d개다(%d개까지). 사본마다 저장소 전체가 펼쳐진다" % (outer, OUTER_MAX))
    rid = uuid.uuid4().hex[:8]
    rdir = round_dir(rid)
    copies = []  # type: List[Dict[str, str]]
    try:
        rdir.mkdir(parents=True)     # 이미 있으면 남의 것이다 — 아래 치우기로 가지 않게 여기서 멈춘다
    except OSError as e:
        raise Refuse("임시 사본 폴더를 만들지 못했다 — %s" % e)
    try:
        tree = current_tree(top, prefix)
        sha = git(["commit-tree", tree, "-p", "HEAD", "-m", "devkit snap"], top).stdout.strip()
        git(["branch", "devkit-tmp/%s/snap" % rid, sha], top)
        for i in range(1, n + 1):
            br = "devkit-tmp/%s/p%d" % (rid, i)
            where = rdir / ("p%d" % i)
            git(["worktree", "add", "-q", "-b", br, str(where), sha], top)
            copies.append({"piece": "P%d" % i, "path": proj_path(where, prefix), "branch": br})
    except (Stop, OSError, Refuse) as e:
        try:
            clean(project, rid)
        except Exception:
            pass
        if rdir.exists():          # 이 폴더는 start가 방금 만든 것이다
            shutil.rmtree(str(rdir), ignore_errors=True)
        if isinstance(e, Refuse):
            raise
        raise Refuse("임시 저장점이나 사본을 만들지 못했다 — %s" % e)
    return {"ok": True, "id": rid, "snap": sha, "copies": copies}


def outside_changes(wt, prefix: str) -> List[str]:
    """사본에서 프로젝트 폴더 밖(저장소 기준)에 바뀐 파일 — 합치지 않으므로 알린다."""
    toks = git(["status", "--porcelain", "-z", "--untracked-files=all"], wt).stdout.split("\0")
    res = set()
    k = 0
    while k < len(toks):
        t = toks[k]
        k += 1
        if len(t) < 4:
            continue
        paths = [t[3:]]
        if t[0] in "RC" or t[1] in "RC":      # 이름 바꿈·복사는 뒤따르는 토큰이 원래 이름
            if k < len(toks):
                paths.append(toks[k])
            k += 1
        for x in paths:
            if x and not x.startswith(prefix):
                res.add(x)
    return sorted(res)


def merge(project, rid: str) -> Dict[str, object]:
    info = repo_info(project)
    top, prefix = info["top"], info["prefix"]
    need_round(top, rid)
    snap_branch = "devkit-tmp/%s/snap" % rid
    snap = git(["rev-parse", snap_branch], top).stdout.strip()
    wts = dict((b, p) for p, b in round_worktrees(top, rid))
    pieces = sorted([b for b in round_branches(top, rid) if PIECE_RE.match(b.split("/")[2])], key=piece_order)
    merged = []  # type: List[str]
    unchanged = []  # type: List[str]
    changed = []  # type: List[Tuple[str, str]]
    outside = []  # type: List[Dict[str, object]]
    for b in pieces:
        label = "P" + PIECE_RE.match(b.split("/")[2]).group(1)
        wt = wts.get(b)
        if wt is None or not os.path.isdir(wt):
            raise Stop("사본이 없다: %s" % label)
        if prefix:
            out = outside_changes(wt, prefix)
            if out:
                outside.append({"piece": label, "files": out})
        git(["add", "-A", "--", spec(prefix)], wt)
        if git(["diff", "--cached", "--quiet"], wt, check=False).returncode == 1:
            git(["commit", "--no-verify", "-q", "-m", "devkit " + label], wt)
        if git(["diff", "--quiet", snap, b], top, check=False).returncode == 0:
            unchanged.append(label)
        else:
            changed.append((label, b))
    # 통합 사본은 늘 저장점에서 새로 만든다 (다시 돌려도 같은 결과)
    int_branch = "devkit-tmp/%s/int" % rid
    int_path = round_dir(rid) / "int"
    if int_branch in wts or int_path.exists():
        git(["worktree", "remove", "--force", str(wts.get(int_branch, int_path))], top, check=False)
        if int_path.exists():
            _rmtree(int_path)
        git(["worktree", "prune"], top)
    if int_branch in round_branches(top, rid):
        git(["branch", "-D", int_branch], top)
    git(["worktree", "add", "-q", "-b", int_branch, str(int_path), snap], top)
    conflicts = []  # type: List[Dict[str, object]]
    for label, b in changed:
        p = git(["merge", "--no-ff", "--no-edit", b], int_path, check=False)
        if p.returncode == 0:
            merged.append(label)
            continue
        files = names(git(["diff", "--name-only", "--diff-filter=U", "-z"], int_path, check=False).stdout, prefix)
        git(["merge", "--abort"], int_path, check=False)
        if not files:
            raise Stop("git merge 실패: %s" % (p.stderr or p.stdout).strip()[:300])
        conflicts.append({"piece": label, "files": files})
    return {"ok": not conflicts, "id": rid, "int": proj_path(int_path, prefix),
            "merged": merged, "unchanged": unchanged, "conflicts": conflicts, "outside": outside}


def apply(project, rid: str) -> Dict[str, object]:
    info = repo_info(project)
    top, prefix = info["top"], info["prefix"]
    need_round(top, rid)
    snap = "devkit-tmp/%s/snap" % rid
    int_branch = "devkit-tmp/%s/int" % rid
    if int_branch not in round_branches(top, rid):
        raise Usage("합친 결과가 없다. merge를 먼저 한다: %s" % rid)
    snap_tree = git(["rev-parse", snap + "^{tree}"], top).stdout.strip()
    try:
        now = current_tree(top, prefix)
    except Refuse as e:
        return {"ok": False, "files": [],
                "message": "사본을 뜬 뒤 본래 폴더가 바뀌었다. 합친 결과는 통합 사본에 남아 있다 (%s)" % e}
    moved = names(git(["diff", "--name-only", "-z", "--no-renames", snap_tree, now, "--", spec(prefix)], top).stdout, prefix)
    if moved:
        return {"ok": False, "message": "사본을 뜬 뒤 본래 폴더가 바뀌었다. 합친 결과는 통합 사본에 남아 있다", "files": moved}
    base = ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames"]
    changed = names(git(base + ["--name-only", "-z", snap, int_branch, "--", spec(prefix)], top).stdout, prefix)
    if not changed:
        return {"ok": True, "changed": []}
    patch = git(base + ["--binary", snap, int_branch, "--", spec(prefix)], top, raw=True).stdout
    chk = git(["apply", "--check", "--whitespace=nowarn", "-"], top, input=patch, raw=True, check=False)
    if chk.returncode != 0:
        err = chk.stderr.decode("utf-8", "replace")
        bad = []
        for line in err.split("\n"):
            if not line.startswith("error: "):
                continue
            rest = line[len("error: "):].strip()
            if rest.startswith("patch failed: "):
                rest = rest[len("patch failed: "):].rsplit(":", 1)[0]
            elif ": " in rest:
                rest = rest.split(": ", 1)[0]
            else:
                continue
            bad.append(rest)
        return {"ok": False, "blocked": True,
                "message": "고침을 본래 폴더에 얹을 수 없다: " + err.strip()[:300],
                "files": names("\0".join(bad), prefix)}
    git(["apply", "--whitespace=nowarn", "-"], top, input=patch, raw=True)
    return {"ok": True, "changed": changed}


def clean(project, rid: Optional[str] = None) -> Dict[str, object]:
    info = repo_info(project)
    top = info["top"]
    if rid is not None and not ID_RE.match(rid):
        raise Usage("회차는 16진 8자다: %s" % rid)
    ids = [rid] if rid else rounds(top)
    removed_c = []  # type: List[str]
    removed_b = []  # type: List[str]
    for i in ids:
        rdir = round_dir(i)
        wts = round_worktrees(top, i)
        brs = round_branches(top, i)
        if not wts and not brs:      # 이 저장소의 회차가 아니면 그 폴더는 남의 것이다
            continue
        for path, _ in wts:
            git(["worktree", "remove", "--force", path], top, check=False)
            removed_c.append(path)
        try:
            if rdir.exists():
                _rmtree(rdir)
        except OSError as e:
            raise Stop("사본을 지우지 못했다(%s): %s. 켜 둔 것이 있으면 끄고 다시 한다" % (rdir, e))
        git(["worktree", "prune"], top)
        for b in round_branches(top, i):
            git(["branch", "-D", b], top)
            removed_b.append(b)
    return {"ok": True, "removed": {"copies": sorted(removed_c), "branches": sorted(removed_b)}}


def list_rounds(project) -> Dict[str, object]:
    info = repo_info(project)
    top, prefix = info["top"], info["prefix"]
    res = []
    for i in rounds(top):
        made = git(["log", "-1", "--format=%cI", "refs/heads/devkit-tmp/%s/snap" % i], top, check=False).stdout.strip()
        cps = []
        for path, b in sorted(round_worktrees(top, i), key=lambda x: piece_order(x[1])):
            tail = b.split("/")[2]
            cps.append({"piece": "int" if tail == "int" else tail.upper(), "path": proj_path(path, prefix), "branch": b})
        res.append({"id": i, "made": made, "copies": cps})
    return {"ok": True, "rounds": res}


def mark(project) -> Dict[str, object]:
    info = repo_info(project)
    top, prefix = info["top"], info["prefix"]
    head = git(["rev-parse", "HEAD"], top).stdout.strip()
    tree = current_tree(top, prefix)
    dirty = names(git(["diff", "--name-only", "-z", "--no-renames", "HEAD", tree, "--", spec(prefix)], top).stdout, prefix)
    return {"ok": True, "head": head, "tree": tree, "dirty": dirty}


def since(project, tree: str) -> Dict[str, object]:
    info = repo_info(project)
    top, prefix = info["top"], info["prefix"]
    if tree.startswith("-") or git(["cat-file", "-e", tree + "^{tree}"], top, check=False).returncode != 0:
        raise Stop("그 나무를 찾을 수 없다(오래돼 git이 치웠을 수 있다). 시작점 줄의 파일 이름으로 가린다: %s" % tree)
    now = current_tree(top, prefix)
    toks = git(["diff", "--name-status", "-z", "--no-renames", tree, now, "--", spec(prefix)], top).stdout.split("\0")
    kinds = {"M": [], "A": [], "D": []}  # type: Dict[str, List[str]]
    k = 0
    while k + 1 < len(toks):
        status, path = toks[k], toks[k + 1]
        k += 2
        if not status:
            continue
        kinds["A" if status[0] == "A" else "D" if status[0] == "D" else "M"].append(path)
    return {"ok": True, "changed": names("\0".join(kinds["M"]), prefix),
            "added": names("\0".join(kinds["A"]), prefix), "deleted": names("\0".join(kinds["D"]), prefix)}


# ---------------------------------------------------------------- 명령줄

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = _Parser(prog="copies.py", description="devkit 동시에 만들기 도우미")
    sub = ap.add_subparsers(dest="cmd")
    for name, extra in (("start", "n"), ("merge", "rid"), ("apply", "rid"), ("clean", "rid?"),
                        ("list", None), ("mark", None), ("since", "tree")):
        sp = sub.add_parser(name)
        sp.add_argument("project")
        if extra == "n":
            sp.add_argument("n", type=int)
        elif extra == "rid":
            sp.add_argument("rid")
        elif extra == "rid?":
            sp.add_argument("rid", nargs="?")
        elif extra == "tree":
            sp.add_argument("tree")
    try:
        args = ap.parse_args(argv)
        if not args.cmd:
            raise Usage("명령을 준다: start merge apply clean list mark since")
        project = Path(args.project)
        if not project.is_dir():
            raise Usage("프로젝트 폴더가 없다: %s" % args.project)
        if args.cmd == "start":
            res = start(project, args.n)
        elif args.cmd == "merge":
            res = merge(project, args.rid)
        elif args.cmd == "apply":
            res = apply(project, args.rid)
        elif args.cmd == "clean":
            res = clean(project, args.rid)
        elif args.cmd == "list":
            res = list_rounds(project)
        elif args.cmd == "mark":
            res = mark(project)
        else:
            res = since(project, args.tree)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Usage as e:
        emit({"ok": False, "message": "쓰는 법 틀림: %s" % e})
        return 1
    except Refuse as e:
        emit({"ok": False, "message": str(e)})
        return 2
    except Stop as e:
        emit({"ok": False, "message": str(e)})
        return 5
    except OSError as e:
        emit({"ok": False, "message": "파일 작업 실패: %s" % e})
        return 5
    emit(res)
    if res.get("ok"):
        return 0
    if args.cmd == "apply" and res.get("blocked"):
        return 6
    return {"merge": 3, "apply": 4}.get(args.cmd, 5)


if __name__ == "__main__":
    sys.exit(main())
