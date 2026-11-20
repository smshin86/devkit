#!/usr/bin/env python3
"""devkit을 Claude Code와 Codex에 한 번에 깐다.

    python3 install.py                깔기 (다시 치면 새 판으로 바꿔 깐다)
    python3 install.py --codex-note   깔고, Codex의 AGENTS.md에 안내 세 줄을 넣기
    python3 install.py --remove       지우기 (넣어 둔 안내 세 줄도 같이 지운다)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
NAME = "devkit@devkit"

# 안내 세 줄: 표시 줄 둘 + 안내 한 줄. 안내 한 줄은 hooks/hooks.json의 첫 훅 글과 같다.
NOTE_BEGIN = "<!-- devkit:begin -->"
NOTE_END = "<!-- devkit:end -->"
NOTE_TEXT = ("devkit: when asked to build, change or fix something in a project, or to analyze how a project is built, "
             "read the devkit:start skill first, before reading or editing code. When continuing earlier work, read devkit:start first too.")

# 도구마다: 지우는 명령들, 까는 명령들
TOOLS = {
    "Claude Code": ("claude",
                    [["plugin", "uninstall", NAME], ["plugin", "marketplace", "remove", "devkit"]],
                    [["plugin", "marketplace", "add", HERE], ["plugin", "install", NAME]]),
    "Codex": ("codex",
              [["plugin", "remove", NAME], ["plugin", "marketplace", "remove", "devkit"]],
              [["plugin", "marketplace", "add", HERE], ["plugin", "add", NAME]]),
}


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


def _find_block(data):
    """바이트에서 우리 안내 세 줄을 찾는다.
    돌려주는 값: ("none", 0, 0) 표시가 없음 / ("ok", 시작 줄, 끝 줄) 우리 글 그대로 / ("broken", 0, 0) 손댄 흔적."""
    lines = data.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == NOTE_BEGIN.encode("ascii")]
    ends = [i for i, line in enumerate(lines) if line.rstrip(b"\r\n") == NOTE_END.encode("ascii")]
    if not begins and not ends:
        return "none", 0, 0
    if len(begins) == 1 and len(ends) == 1 and ends[0] == begins[0] + 2:
        if lines[begins[0] + 1].rstrip(b"\r\n") == NOTE_TEXT.encode("ascii"):
            return "ok", begins[0], ends[0]
    return "broken", 0, 0


def add_note(path):
    """안내 세 줄을 파일 끝에 넣는다. "added" | "present"(이미 있음, 그대로) | "broken"(표시가 달라 그대로)."""
    path = Path(path)
    data = path.read_bytes() if path.exists() else b""
    kind, _, _ = _find_block(data)
    if kind == "ok":
        return "present"
    if kind == "broken":
        return "broken"
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    if data and not data.endswith(b"\n"):
        data += eol
    note = eol.join([NOTE_BEGIN.encode("ascii"), NOTE_TEXT.encode("ascii"), NOTE_END.encode("ascii")]) + eol
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data + note)
    return "added"


def remove_note(path):
    """표시 사이가 우리 글 한 줄과 바이트로 같을 때만 세 줄을 지운다. "removed" | "absent" | "broken"(그대로)."""
    path = Path(path)
    if not path.is_file():
        return "absent"
    data = path.read_bytes()
    kind, start, end = _find_block(data)
    if kind == "none":
        return "absent"
    if kind == "broken":
        return "broken"
    lines = data.splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:start] + lines[end + 1:]))
    return "removed"


def _note_message(status, path):
    if status == "broken":
        return f"Codex: {path} 의 devkit 안내 표시가 우리 글과 달라 손대지 않았습니다. 직접 확인해 주세요."
    return ""


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
    found = False
    codex_ok = False
    for label, (command, remove, install) in TOOLS.items():
        exe = shutil.which(command)
        if not exe:
            print(f"{label}: {command} 명령을 찾지 못해 건너뜁니다.")
            continue
        found = True
        # 다시 깔 때는 전에 깐 것이 없어 실패하는 것이 정상이라, 지우기 결과는 --remove일 때만 본다
        removed = [run(exe, a) for a in remove]
        if remove_only:
            if removed[0][0]:
                print(f"{label}: 지웠습니다.")
            else:
                print(f"{label}: 지운 것이 없습니다. 깔려 있지 않았거나 지우지 못했습니다.\n{removed[0][1]}")
            continue
        for a in install:
            ok, out = run(exe, a)
            if not ok:
                failed = True
                print(f"{label}: 깔지 못했습니다. ({command} {' '.join(a)})\n{out}")
                break
        else:
            print(f"{label}: 깔았습니다.")
            if command == "codex":
                codex_ok = True
    agents = codex_home() / "AGENTS.md"
    if remove_only:
        status = remove_note(agents)
        if status == "removed":
            print(f"Codex: {agents} 에서 devkit 안내 세 줄을 지웠습니다.")
        elif status == "broken":
            print(_note_message(status, agents))
            failed = True
    elif want_note and codex_ok:
        status = add_note(agents)
        if status == "added":
            print(f"Codex: {agents} 에 devkit 안내 세 줄을 넣었습니다.")
        elif status == "present":
            print(f"Codex: {agents} 에 devkit 안내 세 줄이 이미 있습니다.")
        else:
            print(_note_message(status, agents))
            failed = True
    if not found:
        print("Claude Code도 Codex도 찾지 못했습니다. 둘 중 하나를 먼저 설치해 주세요.")
        return 1
    if not remove_only and not failed:
        print("새 대화를 열면 적용됩니다. 따로 부를 필요 없이 평소처럼 요청하면 됩니다.")
        if codex_ok and not want_note:
            print("Codex가 devkit을 스스로 꺼내 쓰지 않으면 python3 install.py --codex-note 로 안내 세 줄을 넣을 수 있습니다.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
