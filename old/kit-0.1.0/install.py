#!/usr/bin/env python3
"""devkit을 Claude Code와 Codex에 한 번에 깐다.

    python3 install.py            깔기 (다시 치면 새 판으로 바꿔 깐다)
    python3 install.py --remove   지우기
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
NAME = "devkit@devkit"

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


def main():
    args = sys.argv[1:]
    if args not in ([], ["--remove"]):
        print(__doc__)
        return 1
    remove_only = bool(args)
    failed = False
    found = False
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
    if not found:
        print("Claude Code도 Codex도 찾지 못했습니다. 둘 중 하나를 먼저 설치해 주세요.")
        return 1
    if not remove_only and not failed:
        print("새 대화를 열면 적용됩니다. 따로 부를 필요 없이 평소처럼 요청하면 됩니다.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
