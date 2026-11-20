#!/usr/bin/env python3
"""화면 지도: 화면을 감싸는 틀과 그 틀이 불러오는 파일을 한 번 훑어 적어 두고, 화면 하나에 대해 찾아 준다.

    screenmap.py build <프로젝트> [--out 파일]
    screenmap.py lookup <프로젝트> <화면> [--file 글자] [--map 파일]

표준 라이브러리만 쓴다. 기술에 묶인 것(확장자, 끼워 넣기 문법, 읽기 전 다듬기)은 아래 표 세 개에만 둔다.
"""
import argparse
import datetime
import json
import os
import posixpath
import re
import sys
from pathlib import Path

# ---- 기술에 묶인 표 세 개 (지금은 JSP 것) ----

MARKUP_EXT = {".jsp", ".jspf", ".tag", ".html", ".htm"}
SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", ".devkit"}

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


def build(root: Path) -> dict:
    root = Path(root)
    pages = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if Path(name).suffix.lower() not in MARKUP_EXT:
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            pages[rel] = scan_markup(read_text(full))
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


# ---- 명령줄 ----

def default_map_path(project) -> Path:
    return Path(project) / ".devkit" / "screenmap.json"


def cmd_build(args) -> int:
    root = Path(args.project)
    if not root.is_dir():
        print(f"프로젝트 폴더가 없습니다: {root}")
        return 1
    m = build(root)
    out = Path(args.out) if args.out else default_map_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    wrappers = sum(1 for p in m["pages"] if is_wrapper(m, p))
    print(f"화면 파일 {len(m['pages'])}개를 적었습니다 (다른 화면을 끼워 넣는 틀 {wrappers}개): {out}")
    return 0


def cmd_lookup(args) -> int:
    mp = Path(args.map) if args.map else default_map_path(args.project)
    if not mp.is_file():
        print("지도가 없습니다. 먼저: screenmap.py build <프로젝트>")
        return 1
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["pages"], m["built_at"]
    except (ValueError, KeyError, TypeError):
        print("지도 파일을 읽지 못했습니다. build를 다시 하세요.")
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
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
