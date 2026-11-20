#!/usr/bin/env python3
"""대화가 시작될 때(훅) 하던 일이 있으면 한 줄로 귀띔한다 (python3 표준 라이브러리만).

열려 있는 작업 기록의 파일 이름과 지금 단계만 찍는다. 기록의 본문은 찍지 않는다 —
남이 준 프로젝트에 든 글이 대화 시작 때 지시처럼 들어가지 않게 하려는 것이다.
영문·숫자·기호만 찍고, 어떤 경우에도 조용히 0으로 끝난다. 파일·폴더를 만들지 않는다.
"""
import json
import os
import sys
from pathlib import Path

MAX_LINES = 5
MAX_NAME = 60


def project_from(text) -> Path:
    """훅이 stdin으로 준 JSON의 cwd. 없거나 이상하면 이 프로세스의 현재 폴더."""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("cwd"), str) and data["cwd"]:
            return Path(data["cwd"])
    except Exception:
        pass
    return Path(os.getcwd())


def lines(project) -> list:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path[:1]:
        sys.path.insert(0, here)         # 이 스크립트 옆의 work.py. 현재 폴더의 것을 불러오지 않는다
    import work
    records = work.open_records(project)
    out = []
    for name, stage in records[:MAX_LINES]:
        if len(name) > MAX_NAME:         # 긴 이름은 문장처럼 읽힐 수 있어 이름을 찍지 않는다
            out.append("devkit: unfinished work record in .devkit/work/ (stage: %s). "
                       "To continue it, read devkit:start first, then devkit:%s." % (stage, stage))
            continue
        out.append("devkit: unfinished work record .devkit/work/%s (stage: %s). "
                   "To continue it, read devkit:start first, then devkit:%s." % (name, stage, stage))
    if len(records) > MAX_LINES:
        out.append("devkit: and %d more open records in .devkit/work/." % (len(records) - MAX_LINES))
    return [x for x in out if x.isascii()]


def main() -> int:
    try:
        text = ""
        if sys.stdin is not None and not sys.stdin.isatty():
            text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        out = lines(project_from(text))
        if out:
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
    except BaseException:
        os._exit(0)                      # 닫힌 출력 등 무엇이든 조용히 끝낸다
    return 0


if __name__ == "__main__":
    sys.exit(main())
