#!/usr/bin/env python3
"""devkit을 Claude Code에 깐다. (Codex에는 --codex-note로 규칙 한 장만 넣는다.)

    python3 install.py                깔기 (다시 치면 새 판으로 바꿔 깐다)
    python3 install.py --codex-note   깔고, Codex의 AGENTS.md에 규칙 한 장을 넣기
    python3 install.py --remove       지우기 (넣어 둔 규칙 한 장도 같이 지운다)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
NAME = "devkit@devkit"
RULES = Path(HERE) / "rules.md"

# 규칙 한 장: 표시 줄 둘 사이에 rules.md의 줄을 그대로 넣는다.
NOTE_BEGIN = "<!-- devkit:begin -->"
NOTE_END = "<!-- devkit:end -->"

CLAUDE_REMOVE = [["plugin", "uninstall", NAME], ["plugin", "marketplace", "remove", "devkit"]]
CLAUDE_INSTALL = [["plugin", "marketplace", "add", HERE], ["plugin", "install", NAME]]


def run(exe, args):
    try:
        done = subprocess.run([exe] + args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def codex_home():
    """Codex 설정 폴더. CODEX_HOME이 비어 있지 않으면 그것, 아니면 ~/.codex."""
    value = os.environ.get("CODEX_HOME", "")
    return Path(value) if value else Path.home() / ".codex"


def rules_lines():
    """rules.md의 줄들(줄 끝을 뗀 bytes). 못 읽으면 OSError."""
    return RULES.read_bytes().splitlines()


def _find_block(data, body):
    """바이트에서 우리 규칙 한 장 블록을 찾는다.
    돌려주는 값: ("none", 0, 0) 표시가 없음 / ("ok", 시작 줄, 끝 줄) 표시 사이가 body 그대로 / ("broken", 0, 0) 손댄 흔적."""
    lines = data.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == NOTE_BEGIN.encode("ascii")]
    ends = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == NOTE_END.encode("ascii")]
    if not begins and not ends:
        return "none", 0, 0
    if len(begins) == 1 and len(ends) == 1 and ends[0] > begins[0]:
        inside = [line.rstrip(b"\r\n") for line in lines[begins[0] + 1:ends[0]]]
        if inside == list(body):
            return "ok", begins[0], ends[0]
    return "broken", 0, 0


def add_note(path, body):
    """규칙 한 장을 파일 끝에 넣는다. "added" | "present"(이미 있음, 그대로) | "broken"(표시 사이가 달라 그대로)."""
    path = Path(path)
    data = path.read_bytes() if path.exists() else b""
    kind, _, _ = _find_block(data, body)
    if kind == "ok":
        return "present"
    if kind == "broken":
        return "broken"
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    if data and not data.endswith(b"\n"):
        data += eol
    note = NOTE_BEGIN.encode("ascii") + eol
    for line in body:
        note += line + eol
    note += NOTE_END.encode("ascii") + eol
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data + note)
    return "added"


def remove_note(path, body):
    """표시 사이가 body와 바이트로 같을 때만 블록을 지운다. "removed" | "absent" | "broken"(그대로)."""
    path = Path(path)
    if not path.is_file():
        return "absent"
    data = path.read_bytes()
    kind, start, end = _find_block(data, body)
    if kind == "none":
        return "absent"
    if kind == "broken":
        return "broken"
    lines = data.splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:start] + lines[end + 1:]))
    return "removed"


def _broken_message(path):
    return f"Codex: {path} 의 devkit 표시 사이 글이 지금 규칙 한 장과 달라 손대지 않았습니다. 직접 확인해 주세요."


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:] if argv is None else list(argv)
    if args not in ([], ["--codex-note"], ["--remove"]):
        print(__doc__)
        return 1
    remove_only = args == ["--remove"]
    want_note = args == ["--codex-note"]
    failed = False
    if not remove_only and not RULES.is_file():
        # 규칙 한 장이 없으면 깔아도 대화 시작 때 아무것도 읽히지 않는다 — 깔았다고 말하지 않는다
        print(f"{RULES} 가 없어 깔지 않았습니다. devkit 폴더를 다시 받아 주세요.")
        return 1
    claude = shutil.which("claude")
    codex = shutil.which("codex")
    claude_ok = False
    note_ok = False
    if claude:
        # 다시 깔 때는 전에 깐 것이 없어 실패하는 것이 정상이라, 지우기 결과는 --remove일 때만 본다
        removed = [run(claude, a) for a in CLAUDE_REMOVE]
        if remove_only:
            if removed[0][0]:
                print("Claude Code: 지웠습니다.")
            else:
                print(f"Claude Code: 지운 것이 없습니다. 깔려 있지 않았거나 지우지 못했습니다.\n{removed[0][1]}")
        else:
            for a in CLAUDE_INSTALL:
                ok, out = run(claude, a)
                if not ok:
                    failed = True
                    print(f"Claude Code: 깔지 못했습니다. (claude {' '.join(a)})\n{out}")
                    break
            else:
                print("Claude Code: 깔았습니다.")
                claude_ok = True
    else:
        print("Claude Code: claude 명령을 찾지 못해 건너뜁니다.")
    agents = codex_home() / "AGENTS.md"
    if remove_only or (want_note and codex):
        try:
            body = rules_lines()
        except OSError:
            print("Codex: rules.md를 읽지 못해 AGENTS.md를 건드리지 않았습니다.")
            failed = True
            body = None
        try:
            status = None if body is None else (remove_note(agents, body) if remove_only else add_note(agents, body))
        except OSError as error:
            print(f"Codex: {agents} 를 읽거나 쓰지 못했습니다. ({error})")
            failed = True
            status = None
        if status is not None:
            if remove_only:
                if status == "removed":
                    print(f"Codex: {agents} 에서 devkit 규칙 한 장을 지웠습니다.")
                elif status == "broken":
                    print(_broken_message(agents))
                    failed = True
            else:
                if status == "added":
                    print(f"Codex: {agents} 에 devkit 규칙 한 장을 넣었습니다.")
                    note_ok = True
                elif status == "present":
                    print(f"Codex: {agents} 에 devkit 규칙 한 장이 이미 있습니다.")
                    note_ok = True
                else:
                    print(_broken_message(agents))
                    failed = True
    elif want_note:
        print("Codex: codex 명령을 찾지 못해 AGENTS.md에 넣지 않았습니다.")
    if not claude and not codex and not remove_only:
        print("Claude Code도 Codex도 찾지 못했습니다. 둘 중 하나를 먼저 설치해 주세요.")
        return 1
    if not remove_only and not failed:
        if claude_ok or note_ok:
            print("새 대화를 열면 적용됩니다. 따로 부를 필요 없이 평소처럼 요청하면 됩니다.")
        if args == [] and codex:
            print("Codex에서도 쓰려면 python3 install.py --codex-note 로 규칙 한 장을 Codex의 AGENTS.md에 넣습니다.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
