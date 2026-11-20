#!/usr/bin/env python3
"""화면 지도: 화면을 감싸는 틀과 그 틀이 불러오는 파일을 한 번 훑어 적어 두고, 화면 하나에 대해 찾아 준다.

    screenmap.py build <프로젝트> [--out 파일]
    screenmap.py lookup <프로젝트> <화면> [--file 글자] [--map 파일]
    screenmap.py used-by <프로젝트> <파일> [--map 파일]

표준 라이브러리만 쓴다. 기술에 묶인 것(확장자, 끼워 넣기 문법, 읽기 전 다듬기)은 아래 표 세 개에만 둔다.
"""
import argparse
import datetime
import json
import os
import posixpath
import re
import stat
import sys
from pathlib import Path

# ---- 기술에 묶인 표 세 개 (지금은 JSP 것) ----

MARKUP_EXT = {".jsp", ".jspf", ".tag", ".html", ".htm"}
MAX_FILE = 5 * 1024 * 1024        # 이보다 큰 화면 파일은 읽지 않는다
SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", ".devkit", ".claude"}

# 읽기 전에 차례로 적용하는 바꾸기: (찾을 것, 바꿀 것)
PRE_RULES = [
    (re.compile(r"<%--.*?--%>", re.DOTALL), ""),                                        # JSP 주석
    (re.compile(r"<!--.*?-->", re.DOTALL), ""),                                         # HTML 주석
    # <%= 식 %> -> ${식}  (값 안의 '>'와 따옴표가 꼬리표 읽기를 끊지 않게)
    (re.compile(r"<%=(.*?)%>", re.DOTALL), lambda mo: "${" + re.sub(r"""["'<>\s]""", "", mo.group(1)) + "}"),
    # <c:url value="X" .../> -> X   (c:out, spring:url도 같은 꼴)
    (re.compile(r"""<(?:c:url|c:out|spring:url)\s+value\s*=\s*(["'])([^"'<>]*)\1[^<>]*>"""), r"\2"),
    (re.compile(r"\$\{\s*([^{}]*?)\s*\}"), r"${\1}"),                                    # ${ctx } -> ${ctx}
]

# 끼워 넣기 문법: 각각 첫 묶음이 대상 경로
INCLUDE_PATTERNS = [
    re.compile(r"""<%@\s*include\s+file\s*=\s*["']([^"']*)["']"""),
    re.compile(r"""<jsp:directive\.include\b[^>]*?\bfile\s*=\s*["']([^"']*)["']"""),
    re.compile(r"""<jsp:include\b[^>]*?\bpage\s*=\s*["']([^"']*)["']"""),
    re.compile(r"""<c:import\b[^>]*?\burl\s*=\s*["']([^"']*)["']"""),
]

# ---- 파일 한 개 읽기 ----

HEAD_RE = re.compile(r"<head(?=[\s>])", re.IGNORECASE)
# 따옴표 안의 '>'에서 끊기지 않는다
TAG_RE = re.compile(r"""<(link|script)\b((?:"[^"\n]*"|'[^'\n]*'|[^>"'])*)>""", re.IGNORECASE)
ATTR_RE = re.compile(r"""(?<![\w-])(?:href|src)\s*=\s*(?:(["'])(.*?)\1|([^\s"'>]+))""", re.DOTALL | re.IGNORECASE)
LOAD_EXT = {"link": ".css", "script": ".js"}


def read_text(path: Path) -> str:
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _is_dynamic(target: str) -> bool:
    return "${" in target or "<%" in target


def scan_markup(text: str) -> dict:
    for pat, repl in PRE_RULES:
        text = pat.sub(repl, text)
    head = HEAD_RE.search(text) is not None

    loads = []
    for tm in TAG_RE.finditer(text):
        am = ATTR_RE.search(tm.group(2))
        if not am:
            continue
        raw = am.group(2) if am.group(1) else am.group(3)
        value = re.split(r"[?#]", raw.strip(), maxsplit=1)[0]
        if value.lower().endswith(LOAD_EXT[tm.group(1).lower()]) and value not in loads:
            loads.append(value)

    found = []
    for pat in INCLUDE_PATTERNS:
        for im in pat.finditer(text):
            found.append((im.start(), im.group(1)))
    includes = []
    for _, target in sorted(found):
        if re.match(r"(https?:|//)", target, re.IGNORECASE):
            continue
        includes.append({"target": target, "dynamic": _is_dynamic(target)})
    return {"head": head, "loads": loads, "includes": includes}


# ---- 프로젝트 전체 훑기 ----

def resolve(target: str, from_file: str, files: set):
    if _is_dynamic(target):
        return None
    if target.startswith("/"):
        hits = [f for f in files if ("/" + f).endswith(target)]
        return hits[0] if len(hits) == 1 else None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), target))
    return joined if joined in files else None


def _readable(full: Path, root: Path) -> bool:
    """읽어도 되는 일반 파일인가. 심볼릭 링크는 프로젝트 안의 일반 파일을 가리킬 때만."""
    try:
        st = os.lstat(str(full))
        if stat.S_ISLNK(st.st_mode):
            target = os.path.realpath(str(full))
            base = os.path.realpath(str(root))
            if target != base and not target.startswith(base.rstrip(os.sep) + os.sep):
                return False
            st = os.stat(target)
        return stat.S_ISREG(st.st_mode) and st.st_size <= MAX_FILE
    except OSError:
        return False


def walk_markup(root: Path, skipped: list = None) -> list:
    """화면 파일 [(root 기준 경로, 파일 경로)]. 건너뛰는 폴더는 SKIP_DIRS.
    일반 파일이 아니거나 너무 큰 것은 빼고, skipped 목록을 주면 그 경로를 거기 적는다."""
    root = Path(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if Path(name).suffix.lower() not in MARKUP_EXT:
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if not _readable(full, root):
                if skipped is not None:
                    skipped.append(rel)
                continue
            found.append((rel, full))
    return sorted(found, key=lambda rp: rp[0])


def build(root: Path, skipped: list = None) -> dict:
    """skipped 목록을 주면 읽지 못해 건너뛴 파일 경로를 거기 적는다(지도에는 넣지 않는다)."""
    root = Path(root)
    pages = {}
    if skipped is None:
        skipped = []
    for rel, full in walk_markup(root, skipped):
        try:
            pages[rel] = scan_markup(read_text(full))
        except OSError:
            skipped.append(rel)
    files = set(pages)
    for rel in pages:
        for inc in pages[rel]["includes"]:
            inc["file"] = resolve(inc["target"], rel, files)
    return {
        "version": 1,
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": {p: pages[p] for p in sorted(pages)},
    }


def closure(m: dict, page: str) -> list:
    seen = []

    def walk(p):
        if p in seen or p not in m["pages"]:
            return
        seen.append(p)
        for inc in m["pages"][p]["includes"]:
            if inc["file"]:
                walk(inc["file"])

    walk(page)
    return seen


def loads_of(m: dict, page: str) -> list:
    out = []
    for p in closure(m, page):
        for ld in m["pages"][p]["loads"]:
            if ld not in out:
                out.append(ld)
    return out


def has_head(m: dict, page: str) -> bool:
    return any(m["pages"][p]["head"] for p in closure(m, page))


def _slots_of(m: dict, page: str) -> tuple:
    """실행 중에 끼워 넣는 대상. 자기 글에 있으면 그것만, 없으면 그대로 끼워 넣은 조각 것까지 본다."""
    own = {i["target"] for i in m["pages"][page]["includes"] if i["dynamic"]}
    if not own:
        own = {i["target"] for p in closure(m, page) for i in m["pages"][p]["includes"] if i["dynamic"]}
    return tuple(sorted(own))


def is_wrapper(m: dict, page: str) -> bool:
    return page in m["pages"] and has_head(m, page) and bool(_slots_of(m, page))


# ---- 찾아보기 ----

MAX_FILE_GROUPS = 3        # 파일 줄까지 찍는 묶음 수
MAX_HEAD_ONLY_GROUPS = 10  # 머리 줄만 찍는 묶음 수
MAX_LIST = 20              # 후보·끼워 넣는 파일 목록 길이


def find_page(m: dict, screen: str, root: Path = None) -> list:
    screen = screen.replace("\\", "/")
    if screen.startswith("./"):
        screen = screen[2:]
    pages = m["pages"]
    if screen in pages:
        return [screen]
    if root is not None and screen.startswith("/"):
        try:
            rel = Path(screen).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            rel = None
        if rel in pages:
            return [rel]
    return sorted(p for p in pages if ("/" + p).endswith("/" + screen))


def _pattern_of(page: str) -> str:
    parts = page.split("/")
    if len(parts) < 2:
        return page
    parts[-2] = "*"
    return "/".join(parts)


def wrapper_groups(m: dict) -> list:
    groups = {}
    for p in sorted(m["pages"]):
        if is_wrapper(m, p):
            groups.setdefault((_pattern_of(p), _slots_of(m, p)), []).append(p)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][0], kv[0][1]))
    return [{"pattern": k[0], "slots": list(k[1]), "files": sorted(v)} for k, v in ordered]


def _name_lines(m: dict, group: dict, show_all: bool) -> tuple:
    """파일 이름으로 합쳐 센 (줄들, 절반 미만이라 뺀 이름 수)."""
    n = len(group["files"])
    names = {}   # 이름 -> {"paths": set, "frames": 몇 틀}
    for f in group["files"]:
        loaded = loads_of(m, f)
        for name in {ld.rsplit("/", 1)[-1] for ld in loaded}:
            e = names.setdefault(name, {"paths": set(), "frames": 0})
            e["frames"] += 1
            e["paths"].update(ld for ld in loaded if ld.rsplit("/", 1)[-1] == name)
    lines, dropped = [], 0
    for name, e in sorted(names.items(), key=lambda kv: (-kv[1]["frames"], kv[0])):
        if not show_all and 2 * e["frames"] < n:
            dropped += 1
            continue
        label = next(iter(e["paths"])) if len(e["paths"]) == 1 else f"{name} (경로 {len(e['paths'])}가지)"
        lines.append(f"    {e['frames']}/{n}  {label}")
    return lines, dropped


def _filter_lines(m: dict, group: dict, text: str) -> list:
    n = len(group["files"])
    counts = {}
    for f in group["files"]:
        for ld in loads_of(m, f):
            if text.lower() in ld.lower():
                counts[ld] = counts.get(ld, 0) + 1
    if not counts:
        return [f"    0/{n}  {text} — 불러오는 틀 없음"]
    return [f"    {c}/{n}  {p}" for p, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def lookup(m: dict, page: str, file_filter: str = None) -> str:
    pg = m["pages"][page]
    wrapper = is_wrapper(m, page)
    out = [f"화면: {page}"]
    if wrapper:
        out.append("종류: 틀 — 다른 화면을 실행 중에 끼워 넣는다.")
    elif pg["head"]:
        out.append("종류: 스스로 <head>가 있는 파일 — 온전한 페이지이거나, 틀에 끼워지는 머리 조각이다.")
    else:
        out.append("종류: 조각 — 스스로 <head>가 없다. 실행 중에 틀 안에 끼워져서 보인다.")

    loads = loads_of(m, page)
    if loads:
        out.append("이 화면이 불러오는 파일 (그대로 끼워 넣은 조각 것 포함):")
        out.extend(f"  {ld}" for ld in loads)
    else:
        out.append("이 화면이 불러오는 파일 (그대로 끼워 넣은 조각 것 포함): 없음")

    lost = []
    for p in closure(m, page):
        for inc in m["pages"][p]["includes"]:
            if inc["file"] is None and inc["target"] not in lost:
                lost.append(inc["target"])
    if lost:
        out.append("따라가지 못한 끼워 넣기 (이 안에서 무엇을 불러오는지는 지도에 없다):")
        out.extend(f"  {t}" for t in lost)

    includers = sorted(p for p, v in m["pages"].items() if any(i["file"] == page for i in v["includes"]))
    if includers:
        out.append("이 화면을 그대로 끼워 넣는 파일:")
        out.extend(f"  {p}" for p in includers[:MAX_LIST])
        if len(includers) > MAX_LIST:
            out.append(f"  그 밖 {len(includers) - MAX_LIST}개")
    else:
        out.append("이 화면을 그대로 끼워 넣는 파일: 없음")

    if not wrapper:
        groups = wrapper_groups(m)
        if groups:
            out.append(f"다른 화면을 실행 중에 끼워 넣는 틀: {len(groups)}묶음")
            for idx, g in enumerate(groups):
                header = f"  [{g['pattern']}] {len(g['files'])}개 — 끼워 넣는 대상: {', '.join(g['slots'])}"
                if file_filter is not None:
                    out.append(header)
                    out.extend(_filter_lines(m, g, file_filter))
                elif idx < MAX_FILE_GROUPS:
                    out.append(header)
                    lines, dropped = _name_lines(m, g, False)
                    out.extend(lines)
                    if dropped:
                        out.append(f"    그 밖 파일 이름 {dropped}개는 틀의 절반 미만만 불러온다 (--file <이름 일부>로 확인)")
                elif idx < MAX_FILE_GROUPS + MAX_HEAD_ONLY_GROUPS:
                    out.append(header)
            rest = len(groups) - MAX_FILE_GROUPS - MAX_HEAD_ONLY_GROUPS
            if file_filter is None and rest > 0:
                out.append(f"  그 밖 {rest}묶음")
            out.append('읽는 법: "1/2"는 그 묶음의 틀 2개 중 1개가 불러온다는 뜻이다. 경로가 달라도 파일 이름이 같으면 한 줄로 합쳤다.')
            out.append("어느 묶음이 이 화면을 감싸는지는 지도에 없다. 이 화면을 돌려주는 서버 코드에서 틀 이름을 확인한다.")
            out.append("틀 전부가 불러오지는 않는 파일에 기대게 되면, 같은 모양의 이웃 화면이 어떻게 하는지 따르고 그 사실을 보고에 적는다.")
        else:
            out.append("다른 화면을 실행 중에 끼워 넣는 틀: 없음")
        out.append("조건이 붙은 불러오기(특정 경우에만)와 스크립트가 실행 중에 불러오는 것은 구분하지 못한다.")
    out.append(f"지도를 만든 때: {m['built_at']}")
    return "\n".join(out)


# ---- 거꾸로 찾기 ----

def name_match(load: str, target: str):
    """스타일·스크립트 주소(load)가 파일 경로(target)를 가리킨다고 이름으로 짐작할 수 있는가.

    주소 = (사이트 앞머리) + P, 파일 = (웹 뿌리 폴더) + P 이므로 뒤쪽 P를 맞춘다.
    None 이거나 {"matched": 맞은 칸 수, "cut": 변수·상대 경로에서 잘랐는가, "front": 맨 앞 한 칸을 사이트 앞머리로 봤는가}.
    """
    load = load.replace("\\", "/").lower()
    load = re.split(r"[?#]", load, maxsplit=1)[0].strip()
    if load.startswith("//") or "://" in load:
        return None
    addr = [c for c in load.split("/") if c not in ("", ".")]
    cut = False
    for i in range(len(addr) - 1, -1, -1):
        if "${" in addr[i] or "<%" in addr[i] or addr[i] == "..":
            addr = addr[i + 1:]
            cut = True
            break
    if not addr:
        return None
    tail = [c for c in target.replace("\\", "/").lower().split("/") if c not in ("", ".")]
    c = 0
    while c < len(addr) and c < len(tail) and addr[-1 - c] == tail[-1 - c]:
        c += 1
    if c == 0:
        return None
    k = len(addr) - c
    if k == 0:
        return {"matched": c, "cut": cut, "front": False}
    if k == 1 and c >= 2 and not cut:
        return {"matched": c, "cut": cut, "front": True}
    return None


NOT_SEEN = ("지도가 못 보는 길: 스타일 안의 @import, 스크립트가 실행 중에 불러오는 것, 조건이 붙은 불러오기, "
            "이름에 변수가 든 주소, 서버 코드가 고르는 틀")
ZERO = "지도에서 이어진 화면 0개 — 쓰는 곳이 없다는 뜻이 아니다. 아래 길로 쓰일 수 있으니 그 길을 찾아본 뒤에 말한다."
WAY_ASSET = ("찾은 길: 화면이 불러오는 주소의 끝과 이 파일 경로의 끝을 맞춰 골랐다 — 이름이 맞아서 고른 것이다. "
             "주소가 정말 이 파일을 가리키는지는 그 화면을 열어 확인한다.")
WAY_PAGE = "찾은 길: 그대로 끼워 넣기를 거슬러 올라갔다 — 확실히 이어진 것이다."


def _clean_target(target: str, root: Path = None) -> str:
    t = target.replace("\\", "/")
    if t.startswith("./"):
        t = t[2:]
    if root is not None and t.startswith("/"):
        try:
            t = Path(t).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return t


def used_by(m: dict, target: str, root: Path = None) -> dict:
    """화면 조각·스타일·스크립트 하나를 쓰는 화면을 건너건너 찾는다. 틀(실행 중에 끼워 넣는 화면)에서 멈춘다."""
    r = {"target": target, "kind": "none", "hits": [], "seeds": [], "pages": [], "wrappers": []}
    hits = find_page(m, target, root)
    if len(hits) > 1:
        r["kind"] = "many"
        r["hits"] = hits
        return r
    if hits:
        r["kind"] = "page"
        r["target"] = hits[0]
        starts = [hits[0]]
    else:
        clean = _clean_target(target, root)
        if not clean.lower().endswith((".css", ".js")):
            return r
        r["kind"] = "asset"
        r["target"] = clean
        for page in sorted(m["pages"]):
            for ld in m["pages"][page]["loads"]:
                nm = name_match(ld, clean)
                if nm:
                    r["seeds"].append({"page": page, "load": ld, "matched": nm["matched"],
                                       "cut": nm["cut"], "front": nm["front"]})
                    break
        starts = [s["page"] for s in r["seeds"]]

    includers = {}
    for p, v in m["pages"].items():
        for inc in v["includes"]:
            if inc["file"]:
                includers.setdefault(inc["file"], set()).add(p)
    seen = set(starts)
    frontier = list(starts)
    steps = 0
    while frontier:
        steps += 1
        nxt = []
        for node in frontier:
            for p in sorted(includers.get(node, ())):
                if p not in seen:
                    seen.add(p)
                    nxt.append(p)
                    r["pages"].append({"page": p, "steps": steps})
        frontier = nxt
    r["pages"].sort(key=lambda e: (e["steps"], e["page"]))
    cands = set(starts) | {e["page"] for e in r["pages"]}
    r["wrappers"] = sorted(p for p in cands if is_wrapper(m, p))
    return r


def _wrapper_lines(m: dict, wrappers: list) -> list:
    groups = wrapper_groups(m)
    lines = []
    for w in wrappers:
        for g in groups:
            if w in g["files"]:
                k = sum(1 for f in g["files"] if f in wrappers)
                lines.append(f"  {w}  [{g['pattern']} 묶음 {len(g['files'])}개 중 {k}개]")
                break
    return lines


def render_used_by(m: dict, r: dict) -> str:
    if r["kind"] not in ("page", "asset"):
        return ""
    asset = r["kind"] == "asset"
    out = [f"파일: {r['target']}", WAY_ASSET if asset else WAY_PAGE]
    zero = (not r["seeds"]) if asset else (not r["pages"] and not r["wrappers"])
    if zero:
        out.append(ZERO)
        out.append(NOT_SEEN)
        out.append(f"지도를 만든 때: {m['built_at']}")
        return "\n".join(out)
    if asset:
        out.append(f"주소가 맞은 화면 {len(r['seeds'])}개:")
        for s in r["seeds"]:
            line = f"  {s['page']}  ← {s['load']}"
            if s["front"]:
                line += "  (맨 앞 한 칸은 사이트 주소로 보고 뺐다)"
            elif s["cut"]:
                line += f"  (주소 앞부분에 변수·상대 경로가 있어 뒤 {s['matched']}칸만 맞췄다)"
            out.append(line)
        head = f"그 화면을 그대로 끼워 넣어 함께 쓰는 화면 {len(r['pages'])}개 (이름이 맞아서 고른 것에서 이어짐)"
    else:
        head = f"이 파일을 쓰는 화면 {len(r['pages'])}개"
    out.append(head + (":" if r["pages"] else ""))
    out.extend(f"  {e['page']}  ({e['steps']}칸 위)" for e in r["pages"])
    if r["wrappers"]:
        out.append(f"틀에서 멈춤 {len(r['wrappers'])}개 — 이 틀이 실행 중에 끼워 넣는 화면은 지도에 없어 더 따라가지 못했다. "
                   "그 틀 이름을 돌려주는 서버 코드에서 화면을 찾는다:")
        out.extend(_wrapper_lines(m, r["wrappers"]))
    else:
        out.append("틀에서 멈춤: 없음")
    out.append(NOT_SEEN)
    out.append(f"지도를 만든 때: {m['built_at']}")
    return "\n".join(out)


def stale(root: Path, map_path: Path) -> list:
    """지도와 달라진 화면 파일마다 {"path", "why"} 하나(path 순). 빈 목록이면 낡지 않았다.

    why: 지도에 없음 / 지도보다 새로움 / 지워짐 / 지도 없음 / 지도를 읽지 못함(뒤 둘은 path가 빈 글자 하나뿐).
    """
    root = Path(root)
    map_path = Path(map_path)
    if not map_path.is_file():
        return [{"path": "", "why": "지도 없음"}]
    m, err = _read_map(map_path)
    if err or not isinstance(m.get("pages"), dict):
        return [{"path": "", "why": "지도를 읽지 못함"}]
    try:
        map_time = os.stat(str(map_path)).st_mtime
    except OSError:
        return [{"path": "", "why": "지도를 읽지 못함"}]
    out = []
    now = set()
    for rel, full in walk_markup(root):
        now.add(rel)
        if rel not in m["pages"]:
            out.append({"path": rel, "why": "지도에 없음"})
            continue
        try:
            newer = os.stat(str(full)).st_mtime > map_time      # 같은 초면(Windows 2초 해상도) 낡지 않음으로 본다
        except OSError:
            newer = False
        if newer:
            out.append({"path": rel, "why": "지도보다 새로움"})
    for rel in m["pages"]:
        if rel not in now and not (root / rel).is_file():
            out.append({"path": rel, "why": "지워짐"})
    return sorted(out, key=lambda e: e["path"])


# ---- 명령줄 ----

def default_map_path(project) -> Path:
    return Path(project) / ".devkit" / "screenmap.json"


def cmd_build(args) -> int:
    root = Path(args.project)
    if not root.is_dir():
        print(f"프로젝트 폴더가 없습니다: {root}")
        return 1
    skipped = []
    m = build(root, skipped)
    out = Path(args.out) if args.out else default_map_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    wrappers = sum(1 for p in m["pages"] if is_wrapper(m, p))
    print(f"화면 파일 {len(m['pages'])}개를 적었습니다 (다른 화면을 끼워 넣는 틀 {wrappers}개): {out}"
          + (f" · 읽지 못해 건너뛴 파일 {len(skipped)}개" if skipped else ""))
    return 0


def _pages_ok(pages) -> bool:
    """화면마다 코드가 읽는 칸(head·loads·includes와 끼워 넣기의 target·dynamic·file)이 제 꼴인가."""
    if not isinstance(pages, dict):
        return False
    for v in pages.values():
        if not isinstance(v, dict) or "head" not in v:
            return False
        if not isinstance(v.get("loads"), list) or not isinstance(v.get("includes"), list):
            return False
        for inc in v["includes"]:
            if not isinstance(inc, dict) or not all(k in inc for k in ("target", "dynamic", "file")):
                return False
    return True


def _read_map(mp: Path):
    """(지도, 오류 글귀). 오류가 없으면 글귀는 None."""
    if not mp.is_file():
        return None, "지도가 없습니다. 먼저: screenmap.py build <프로젝트>"
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["pages"], m["built_at"]
        if not _pages_ok(m["pages"]):
            raise ValueError("pages")
    except (ValueError, KeyError, TypeError, OSError):
        return None, "지도 파일을 읽지 못했습니다. build를 다시 하세요."
    return m, None


def cmd_lookup(args) -> int:
    mp = Path(args.map) if args.map else default_map_path(args.project)
    m, err = _read_map(mp)
    if err:
        print(err)
        return 1
    hits = find_page(m, args.screen, Path(args.project))
    if not hits:
        print("지도에 없는 화면입니다. 새로 만드는 화면이면 같은 폴더의 이웃 화면으로 찾아보세요. 지도가 오래됐으면 build를 다시 하세요.")
        return 1
    if len(hits) > 1:
        print("여러 개가 걸립니다:")
        for h in hits[:MAX_LIST]:
            print(f"  {h}")
        return 1
    print(lookup(m, hits[0], args.file))
    return 0


def cmd_used_by(args) -> int:
    mp = Path(args.map) if args.map else default_map_path(args.project)
    m, err = _read_map(mp)
    if err:
        print(err)
        return 1
    r = used_by(m, args.file, Path(args.project))
    if r["kind"] == "none":
        print("지도에 없는 파일입니다. 화면 파일이나 .css·.js 파일을 주세요. 지도가 오래됐으면 build를 다시 하세요.")
        return 1
    if r["kind"] == "many":
        print("여러 개가 걸립니다:")
        for h in r["hits"]:
            print(f"  {h}")
        return 1
    print(render_used_by(m, r))
    return 0


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="screenmap.py", description="화면 지도")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="프로젝트를 훑어 지도를 만든다")
    b.add_argument("project")
    b.add_argument("--out")
    b.set_defaults(func=cmd_build)
    lk = sub.add_parser("lookup", help="화면 하나에 대해 찾아본다")
    lk.add_argument("project")
    lk.add_argument("screen")
    lk.add_argument("--file")
    lk.add_argument("--map")
    lk.set_defaults(func=cmd_lookup)
    ub = sub.add_parser("used-by", help="화면 조각·스타일·스크립트 하나를 쓰는 화면을 찾는다")
    ub.add_argument("project")
    ub.add_argument("file")
    ub.add_argument("--map")
    ub.set_defaults(func=cmd_used_by)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
