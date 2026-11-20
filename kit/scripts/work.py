#!/usr/bin/env python3
"""devkit 작업 기록 도우미 (python3 표준 라이브러리만).

  work.py init <프로젝트>                          .devkit 자리를 만든다 (git이면 이 PC 제외 목록에 한 줄)
  work.py new <프로젝트> <영문이름> [--size "큰 일"]   작업 기록 한 장을 틀대로 만든다
  work.py list <프로젝트>                          열려 있는 작업 기록을 `<파일 이름> <단계>`로 찍는다

작업 기록 형식(머리 세 줄, 번호, 제목 줄)의 주인은 이 파일이다.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

STAGES = ("intake", "find", "build", "verify", "review", "wrap-up")
STATES = ("open", "closed")
RESULTS = ("됨", "안 됨", "읽어서는 이어짐", "확인 못 함")
HEADINGS = ("요청", "장면", "세 칸", "닮은 것과 꺼낸 규칙", "조각", "확인", "검토")
SIZES = ("기능 하나", "큰 일")

NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*\.md$", re.ASCII)
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$", re.ASCII)

HEAD_BYTES = 8192

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


def devkit_dir(project) -> Path:
    return Path(project) / ".devkit"


# ---- 버전 관리 알아보기 ----

def _git(project, *args):
    """git을 돌려 CompletedProcess를 준다. git을 못 돌리면(없음·시간 초과) None."""
    try:
        return subprocess.run(["git", "-C", str(project)] + list(args), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None


def _up_has(project, name) -> bool:
    try:
        here = Path(project).resolve()
    except OSError:
        here = Path(project)
    for d in [here] + list(here.parents):
        try:
            if (d / name).exists():
                return True
        except OSError:
            pass
    return False


def _vcs(project) -> str:
    r = _git(project, "rev-parse", "--is-inside-work-tree")
    if r is None:                      # git 실행 파일이 없다
        if _up_has(project, ".git"):
            return "git"
    elif r.returncode == 0 and r.stdout.strip() == "true":
        return "git"
    if _up_has(project, ".svn"):
        return "svn"
    return "none"


def _ignore_escape(text: str) -> str:
    out = []
    for ch in text:
        if ch in "\\*?[ ":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _exclude(project) -> bool:
    """git의 이 PC용 제외 목록에 `/<프로젝트 자리>/.devkit/` 한 줄이 있게 한다. 값 = 그 뒤 줄이 있는가."""
    r = _git(project, "rev-parse", "--git-path", "info/exclude")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return False
    path = Path(r.stdout.rstrip("\n"))
    if not path.is_absolute():
        path = Path(project) / path
    r2 = _git(project, "rev-parse", "--show-prefix")
    if r2 is None or r2.returncode != 0:
        return False
    line = ("/" + _ignore_escape(r2.stdout.rstrip("\n")) + ".devkit/").encode("utf-8")
    try:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b""
        if line in [x.rstrip(b"\r") for x in data.split(b"\n")]:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), "ab") as f:
            f.write((b"" if not data or data.endswith(b"\n") else b"\n") + line + b"\n")
        return True
    except OSError:
        return False


def init(project) -> dict:
    project = Path(project)
    d = devkit_dir(project)
    created = not d.exists()
    (d / "work").mkdir(parents=True, exist_ok=True)
    vcs = _vcs(project)
    excluded = _exclude(project) if vcs == "git" else False
    return {"dir": str(d), "vcs": vcs, "created": created, "excluded": excluded}


# ---- 작업 기록 ----

def new_record(project, slug, size="기능 하나", today=None) -> Path:
    if not isinstance(slug, str) or not SLUG_RE.match(slug) or "\n" in slug:
        raise ValueError("영문 소문자·숫자·하이픈만 쓸 수 있습니다: %r" % (slug,))
    if size not in SIZES:
        raise ValueError("크기는 %s 중 하나여야 합니다: %r" % (", ".join(SIZES), size))
    init(project)
    path = devkit_dir(project) / "work" / ("%s-%s.md" % ((today or date.today()).isoformat(), slug))
    text = TEMPLATE.replace("<영문이름>", slug).replace("- 크기: 기능 하나", "- 크기: " + size)
    with open(str(path), "x", encoding="utf-8", newline="\n") as f:      # 있으면 FileExistsError
        f.write(text)
    return path


def _norm(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_sections(text):
    """(머리 줄들, {제목: 본문}). 머리 = 첫 `## ` 줄 앞."""
    head, sections, cur, buf = [], {}, None, []
    for ln in text.split("\n"):
        if ln.startswith("## "):
            if cur is not None and cur not in sections:
                sections[cur] = "\n".join(buf).strip("\n")
            cur, buf = ln[3:].strip(), []
        elif cur is None:
            head.append(ln)
        else:
            buf.append(ln)
    if cur is not None and cur not in sections:
        sections[cur] = "\n".join(buf).strip("\n")
    return head, sections


def _head_values(head):
    keys = {"지금 단계": "stage", "상태": "state", "크기": "size"}
    vals = {"stage": None, "state": None, "size": None}
    for ln in head:
        m = re.match(r"^- (지금 단계|상태|크기):(.*)$", ln)
        if m and vals[keys[m.group(1)]] is None:
            v = m.group(2).strip()
            w = re.match(r"([a-z-]+)\s*\([^()]*\)$", v)   # 끝에 붙인 괄호 덧말 하나만 버린다: "verify (서버 없음)"
            vals[keys[m.group(1)]] = w.group(1) if w else v
    return vals


def _scenes(body):
    rows = []
    for ln in body.split("\n"):
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = ln[1:]
        if cells.endswith("|"):
            cells = cells[:-1]
        cells = [c.strip() for c in cells.split("|")]
        if cells[0] == "번호" or all(re.match(r"^:?-+:?$", c) for c in cells if c) and any(cells):
            continue
        if not any(cells):
            continue
        cells = (cells + ["", "", "", ""])[:4]
        rows.append({"id": cells[0], "scene": cells[1], "result": cells[2], "seen": cells[3]})
    return rows


def read_record(path) -> dict:
    """작업 기록을 읽는다. 깨진 파일·없는 파일에도 오류를 내지 않는다."""
    result = {"name": "", "stage": None, "state": None, "size": None, "sections": {}, "scenes": []}
    try:
        p = Path(path)
        result["name"] = p.name[:-3] if p.name.endswith(".md") else p.name
        head, sections = _split_sections(_norm(p.read_bytes()))
        result.update(_head_values(head))
        result["sections"] = sections
        result["scenes"] = _scenes(sections.get("장면", ""))
    except Exception:
        pass
    return result


def open_records(project) -> list:
    """열려 있는 기록 `(파일 이름, 단계)`. 이름·단계가 규칙에 맞는 것만. 예외를 내지 않는다."""
    out = []
    try:
        names = sorted(x.name for x in (devkit_dir(project) / "work").iterdir())
    except Exception:
        return out
    for name in names:
        try:
            if name[-3:] != ".md" or not NAME_RE.fullmatch(name):
                continue
            f = devkit_dir(project) / "work" / name
            if not f.is_file():
                continue
            with open(str(f), "rb") as fh:
                raw = fh.read(HEAD_BYTES)
            vals = _head_values(_split_sections(_norm(raw))[0])
            if vals["state"] == "open" and vals["stage"] in STAGES:
                out.append((name, vals["stage"]))
        except Exception:
            continue
    return out


# ---- 명령줄 ----

def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="work.py", description="devkit 작업 기록 도우미")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help=".devkit 자리를 만든다").add_argument("project")
    pn = sub.add_parser("new", help="작업 기록을 만든다")
    pn.add_argument("project"); pn.add_argument("slug"); pn.add_argument("--size", default=SIZES[0])
    sub.add_parser("list", help="열린 기록을 찍는다").add_argument("project")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    if not Path(args.project).is_dir():      # 폴더 이름을 잘못 쳤을 때 빈 폴더를 만들어 내지 않는다
        sys.stderr.write("work.py: 프로젝트 폴더가 없습니다: %s\n" % (args.project,))
        return 1
    try:
        if args.cmd == "init":
            print(json.dumps(init(args.project), ensure_ascii=False))
        elif args.cmd == "new":
            print(str(new_record(args.project, args.slug, args.size)))
        else:
            for name, stage in open_records(args.project):
                print("%s %s" % (name, stage))
    except (ValueError, FileExistsError, OSError) as e:
        sys.stderr.write("work.py: %s\n" % (e,))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
