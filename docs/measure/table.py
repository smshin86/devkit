#!/usr/bin/env python3
"""화면 표 한 장을 프로젝트 폴더와 맞대어 본다 — 수만 찍는다 (python3 -I, 표준 라이브러리만).

  python3 -I table.py <표.md> <프로젝트 폴더> [--pages <화면목록.json>]

표의 줄(화면 · 화면 파일 · 주소 · 받는 코드)이 프로젝트 안 파일·줄과 맞는지 센다.
화면 파일 칸이 빈 표시(—)인 줄은 자료 줄(api_rows)로 센다 — 화면 칸에 이름이 있어도.
수만 찍고 이름·경로·주소·값은 어떤 출력에도 찍지 않는다. 아무 파일도 만들지 않는다. 표준 라이브러리만 쓴다.
한 줄 끝의 두 칸: uniq = file_ok로 센 화면 줄들의 서로 다른 (경로, 줄 번호) 수 — 같은 줄을 베낀 표를 드러낸다.
self = near로 센 화면 줄 가운데 화면 파일 칸과 받는 코드 칸의 경로가 같은 줄의 수 — 화면이 자기 자신을 받는 코드로 적은 줄을 드러낸다.
"""
import sys
sys.dont_write_bytecode = True           # 들여오기 전에 — __pycache__를 만들지 않는다

import json
import os
import re

USAGE = "인자 틀림: table.py <표.md> <프로젝트 폴더> [--pages <화면목록.json>]"
LIMIT = 8 * 1024 * 1024
SKIP_DIRS = (".git", ".svn", ".devkit", "node_modules")
DASH = {"", "—", "–", "-", "―"}
METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
RULE = re.compile(r"^:?-+:?$")
PLACE = re.compile(r"([^\s:]+):(\d+)")
AFTER_BAD = re.compile(r"[A-Za-z0-9_./{}:-]")
BEFORE_BAD = re.compile(r"[A-Za-z0-9_./}-]")


def read_text(path):
    """바이트를 8 MiB까지만 읽어 utf-8(replace)로. 못 읽으면 OSError."""
    with open(path, "rb") as f:
        return f.read(LIMIT).decode("utf-8", errors="replace")


def split_cells(line):
    """표 줄을 칸으로 나눈다 — 한 글자씩. `\\|`는 세로줄 글자 하나, 백틱 안 세로줄은 나누지 않는다(백틱이 홀수면 백틱 무시)."""
    use_code = line.count("`") % 2 == 0
    pieces, cur, in_code, i, n = [], [], False, 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\" and i + 1 < n and line[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "`":
            if use_code:
                in_code = not in_code
            cur.append(c)
        elif c == "|" and not in_code:
            pieces.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    pieces.append("".join(cur))
    cells = [p.strip() for p in pieces][1:]
    if cells and cells[-1] == "":
        cells.pop()
    return cells


def tidy(cell):
    s = cell.replace("`", "").strip()
    if len(s) >= 4 and s.startswith("**") and s.endswith("**"):
        s = s[2:-2].strip()
    return s


def parse_rows(text):
    """(화면 줄 목록, odd 수). 줄은 앞 네 칸을 다듬은 값 넷.

    구분 줄 바로 앞 물리 줄이 표 줄이고 그 앞 줄은 표 줄이 아니면 그 줄이 머리 줄이다 — 이미 센 것을 물린다."""
    rows, odd, fence = [], 0, False
    kinds = []                            # 물리 줄마다: None(표 줄 아님) · "rule" · "row" · "odd" · "head"
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("```"):
            fence = not fence
            kinds.append(None)
            continue
        if fence or not line.startswith("|"):
            kinds.append(None)
            continue
        cells = split_cells(line)
        filled = [c for c in cells if c != ""]
        if filled and all(RULE.match(c) for c in filled):
            if kinds and kinds[-1] in ("row", "odd") and (len(kinds) < 2 or kinds[-2] is None):
                if kinds[-1] == "row":
                    rows.pop()
                else:
                    odd -= 1
                kinds[-1] = "head"
            kinds.append("rule")
            continue
        if len(cells) < 4:
            odd += 1
            kinds.append("odd")
            continue
        t = [tidy(c) for c in cells[:4]]
        if t[0] == "화면" and t[1] == "화면 파일":
            kinds.append("head")
            continue
        rows.append(t)
        kinds.append("row")
    return rows, odd


class Project(object):
    def __init__(self, root):
        self.root = root
        self.prefix = root if root.endswith(os.sep) else root + os.sep
        self.files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
            for f in filenames:
                self.files.append(f if rel == "." else rel + "/" + f)
        self.lines_cache = {}
        self.find_cache = {}

    def inside(self, path):
        """realpath가 root 안이고 파일인가. ValueError면 아니다."""
        try:
            rp = os.path.realpath(path)
            return (rp == self.root or rp.startswith(self.prefix)) and os.path.isfile(rp)
        except ValueError:
            return False

    def find(self, rel):
        if not rel:
            return []
        if rel in self.find_cache:
            return self.find_cache[rel]
        direct = self.root + "/" + rel
        if self.inside(direct):
            found = [direct]
        elif rel.startswith("../") or "/../" in rel:
            found = []
        else:
            tail = "/" + rel
            found = [self.root + "/" + f for f in self.files if f.endswith(tail) and self.inside(self.root + "/" + f)]
        self.find_cache[rel] = found
        return found

    def lines(self, path):
        """파일의 줄 목록(끝 줄바꿈 뒤 빈 조각은 줄이 아니다). 못 읽으면 None."""
        if path not in self.lines_cache:
            try:
                ls = read_text(path).split("\n")
                if ls and ls[-1] == "":
                    ls.pop()
            except OSError:
                ls = None
            self.lines_cache[path] = ls
        return self.lines_cache[path]

    def place(self, cell):
        """자리 칸 -> (다듬은 경로, 줄 또는 None) 또는 None. 건너뛰는 폴더 아래 경로·9자리 넘는 줄 번호는 None."""
        if cell in DASH or cell == "?":
            return None
        m = PLACE.search(cell)
        if m:
            path, ln = m.group(1), m.group(2)
            if len(ln) > 9:
                return None
            ln = int(ln)
        else:
            path, ln = cell.split()[0], None
        try:
            path = path.replace("\\", "/")
            for lead in ("…/", ".../"):
                if path.startswith(lead):
                    path = path[len(lead):]
                    break
            if path.startswith("/"):
                rp = os.path.realpath(path)
                if rp == self.root or rp.startswith(self.prefix):
                    path = rp[len(self.root):].replace(os.sep, "/").lstrip("/")
                else:
                    path = path.lstrip("/")
            while path.startswith("./"):
                path = path[2:]
        except ValueError:
            return None
        if any(part in SKIP_DIRS for part in path.split("/")):
            return None
        return path, ln


def address(cell):
    if cell in DASH or cell == "?" or cell.startswith("앱 안"):
        return None
    chosen = None
    for piece in [p for p in re.split(r"[\s,]+", cell) if p]:
        if not piece.startswith("/"):
            parts = [x for x in re.split(r"[/·]", piece) if x]
            if all(x.upper() in METHODS for x in parts):
                continue
        chosen = piece
        break
    if chosen is None:
        return None
    a = chosen.split("?", 1)[0]
    a = a.rstrip("/") or a
    return a or None


def strict_hit(w, a):
    start = 0
    while True:
        p = w.find(a, start)
        if p < 0:
            return False
        q = p + len(a)
        before = w[p - 1] if p > 0 else ""
        after = w[q] if q < len(w) else ""
        if (after == "" or not AFTER_BAD.match(after)) and (before == "" or not BEFORE_BAD.match(before)):
            return True
        start = p + 1


def loose_hit(w, a):
    cands = [a]
    for i in range(2, len(a)):
        if a[i] == "/":
            body = a[i + 1:]
            if len(body) >= 2 and body[0] not in "{:<[*":
                cands.append(a[i:])
    for c in cands:
        start = 0
        while True:
            p = w.find(c, start)
            if p < 0:
                break
            q = p + len(c)
            if q >= len(w) or not AFTER_BAD.match(w[q]):
                return True
            start = p + 1
    return False


def norm_key(k):
    k = k.replace("\\", "/")
    while k.startswith("./"):
        k = k[2:]
    return k


def run(argv):
    args = list(argv)
    pages_arg = None
    if "--pages" in args:
        i = args.index("--pages")
        if i + 1 >= len(args):
            print(USAGE)
            sys.exit(9)
        pages_arg = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        print(USAGE)
        sys.exit(9)
    table_path, proj_path = args

    try:
        text = read_text(table_path)
    except OSError:
        print("표를 못 읽음")
        sys.exit(2)
    if text.startswith("﻿"):
        text = text[1:]
    if not os.path.isdir(proj_path):
        print("프로젝트 폴더 없음")
        sys.exit(2)
    keys = None
    if pages_arg is not None:
        try:
            data = json.loads(read_text(pages_arg))
            if not isinstance(data, dict) or not isinstance(data.get("pages"), dict):
                raise ValueError("shape")
            keys = list(data["pages"].keys())
        except (OSError, ValueError, RecursionError):
            print("화면 목록을 못 읽음")
            sys.exit(2)

    proj = Project(os.path.realpath(proj_path))
    rows, odd = parse_rows(text)
    screen_rows = api_rows = file_ok = filled = near = loose = self_n = 0
    addrs, near_addrs, shown, uniq = set(), set(), set(), set()
    for name, file_cell, addr_cell, code_cell in rows:
        is_screen = file_cell not in DASH
        fp = None
        if is_screen:
            screen_rows += 1
            fp = proj.place(file_cell)
            if fp is not None:
                ok = False
                for f in proj.find(fp[0]):
                    ls = proj.lines(f)
                    if ls is not None and (fp[1] is None or 1 <= fp[1] <= len(ls)):
                        ok = True
                        break
                if ok:
                    file_ok += 1
                    shown.add(fp[0])
                    uniq.add(fp)
        else:
            api_rows += 1
        addr = address(addr_cell)
        if addr is not None:
            addrs.add(addr)
        cp = proj.place(code_cell)
        if addr is None or cp is None or cp[1] is None:
            continue
        filled += 1
        s_hit = l_hit = False
        for f in proj.find(cp[0]):
            ls = proj.lines(f)
            if ls is None or not 1 <= cp[1] <= len(ls):
                continue
            w = "\n".join(ls[max(1, cp[1] - 2) - 1:min(len(ls), cp[1] + 2)])
            s_hit = s_hit or strict_hit(w, addr)
            l_hit = l_hit or loose_hit(w, addr)
        if s_hit:
            near += 1
            near_addrs.add(addr)
            if fp is not None and fp[0] == cp[0]:
                self_n += 1
        if l_hit:
            loose += 1

    pages = "-"
    if keys is not None:
        norm = [(k, norm_key(k)) for k in keys]
        matched = set()
        for s in shown:
            hits = [k for k, nk in norm if s == nk or nk.endswith("/" + s) or s.endswith("/" + nk)]
            if len(hits) == 1:
                matched.add(hits[0])
        pages = "%d/%d" % (len(matched), len(keys))
    print("screen_rows=%d api_rows=%d file_ok=%d filled=%d near=%d loose=%d addrs=%d near_addrs=%d pages=%s odd=%d uniq=%d self=%d"
          % (screen_rows, api_rows, file_ok, filled, near, loose, len(addrs), len(near_addrs), pages, odd,
             len(uniq), self_n))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        return run(argv)
    except Exception as e:                # 이름·값이 든 글이 오류 글로 새지 않게 — 종류 이름만
        sys.stderr.write(("table.py: internal error (%s)\n" % type(e).__name__).encode("ascii", "replace").decode("ascii"))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
