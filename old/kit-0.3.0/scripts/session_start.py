#!/usr/bin/env python3
"""대화가 시작될 때(훅) 옆의 rules.md를 한 글자도 바꾸지 않고 그대로 찍는다 (python3 표준 라이브러리만).

어떤 경우에도 조용히 0으로 끝난다. 파일·폴더를 만들지 않는다.
"""
import os
import sys
from pathlib import Path


def main() -> int:
    try:
        rules = Path(__file__).resolve().parent.parent / "rules.md"
        sys.stdout.buffer.write(rules.read_bytes())
        sys.stdout.buffer.flush()
    except BaseException:
        os._exit(0)                      # 파일이 없거나 출력이 닫힌 경우 등 무엇이든 조용히 끝낸다
    return 0


if __name__ == "__main__":
    sys.exit(main())
