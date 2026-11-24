#!/usr/bin/env python3
"""AI가 일을 끝내려 할 때 한 번 끼어들어 끝내기 전 점검을 귀띔한다 (Stop 훅, python3 표준 라이브러리만).

stdin의 JSON(기록 파일 길 · 마지막 말 · 작업 폴더)을 읽어, 셋이 다 참일 때만 막으며(block) 귀띔 글을 낸다:
이미 한 번 끼어든 뒤가 아니고 · 마지막 사용자 말 뒤에 작업 폴더 안의 파일을 고쳤고 · 마지막 말에 점검 보고 줄이 없을 때.
기록 파일은 읽기만 하고(파일을 만들지 않는다) 하위 프로세스를 부르지 않는다. 고장 나면 아무것도 찍지 않고 0으로 끝난다(끝내기를 막지 않는다).
"""
import sys
sys.dont_write_bytecode = True           # 꾸러미 폴더에 __pycache__를 만들지 않는다 (들여오기 전에)

import json
import os

# 기록 파일은 뒤에서부터 이만큼만 읽는다 — 긴 대화의 기록은 수백 MB가 될 수 있고, 마지막 사용자 말 뒤의 일은 거의 늘 이 안에 든다.
TAIL = 4 * 1024 * 1024
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
STEPS = ("켜 본다", "시험을 돌린다", "있던 것으로 들어가 본다", "부탁에 없는 것을 덜어 낸다")
MARK = "끝내기 전 점검:"
REASON = ("이번에 파일을 고쳤다. 끝 보고를 하기 전에 `devkit:check`를 읽고 그 글대로 아래 걸음을 지난다.\n"
          + " · ".join(STEPS) + "\n"
          "이미 했으면 `" + MARK + "` 줄로 그렇게 적고 끝낸다.\n"
          "사용자의 답을 기다리는 중이면 아무것도 더 하지 말고 그대로 멈춘다.")


def read_tail(path, size=None):
    """기록 파일 끝에서 size 바이트(없으면 지금의 TAIL)만 읽어 JSON 사전인 줄만 목록으로 — 못 읽으면 예외."""
    if size is None:
        size = TAIL
    with open(path, "rb") as f:
        total = os.fstat(f.fileno()).st_size
        start = max(0, total - size)
        if start:
            f.seek(start)
        raw = f.read(size)
    lines = raw.split(b"\n")
    if start:
        lines = lines[1:]                                  # 잘린 첫 줄(조각)은 버린다
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _plain(obj, kind):
    """맨 위 type이 kind이고 곁가지(isSidechain)·메타(isMeta) 줄이 아닌가."""
    return obj.get("type") == kind and not obj.get("isSidechain") and not obj.get("isMeta")


def is_user_said(obj):
    """사용자가 한 말인 줄인가 — 글이거나, 도구 결과가 아닌 묶음이 하나라도 든 user 줄."""
    if not isinstance(obj, dict) or not _plain(obj, "user"):
        return False
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") != "tool_result" for b in content)
    return False


def edited_paths(obj):
    """그 줄(assistant)에서 파일을 고친 도구 쓰임의 길(글) 목록."""
    if not isinstance(obj, dict) or not _plain(obj, "assistant"):
        return []
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    out = []
    for b in content:
        if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS):
            continue
        inp = b.get("input")
        if not isinstance(inp, dict):
            continue
        keys = ("file_path", "notebook_path") if b.get("name") == "NotebookEdit" else ("file_path",)
        for k in keys:
            p = inp.get(k)
            if isinstance(p, str) and p:
                out.append(p)
    return out


def under_devkit(path):
    """길을 `/`·`\\`로 나눈 조각 가운데 `.devkit`이 통째로 하나 있는가."""
    return ".devkit" in path.replace("\\", "/").split("/")


def _below(path, cwd):
    """cwd 아래이면 cwd 뒤쪽 조각(상대 길은 길 전체)을, 아니면 None — 글자 셈만 한다(파일 시스템을 보지 않는다).
    `~`로 시작하는 길과 `..` 조각이 있는 길은 아래가 아니다. 드라이브 글자(`C:`)끼리는 그 글자의 대소문자만 무시한다."""
    p = path.replace("\\", "/")
    c = cwd.replace("\\", "/")
    if p == "~" or p.startswith("~/") or ".." in p.split("/"):
        return None
    drive = len(p) >= 2 and p[1] == ":" and p[0].isalpha()
    if not p.startswith("/") and not drive:
        return p
    head = c.rstrip("/") + "/"
    if drive and len(head) >= 2 and head[1] == ":":
        p = p[0].lower() + p[1:]
        head = head[0].lower() + head[1:]
    return p[len(head):] if p.startswith(head) else None


def under_cwd(path, cwd):
    """글자 셈만으로 cwd 아래인가. 상대 길은 아래로 본다."""
    return _below(path, cwd) is not None


def should_speak(data):
    if data.get("stop_hook_active") is not False:
        return False
    last = data.get("last_assistant_message")
    cwd = data.get("cwd")
    tx = data.get("transcript_path")
    if not (isinstance(last, str) and MARK not in last and isinstance(cwd, str) and cwd and isinstance(tx, str) and tx):
        return False
    if not os.path.isfile(tx):
        return False
    try:
        lines = read_tail(tx)
    except (OSError, ValueError):
        return False
    said = [i for i, o in enumerate(lines) if is_user_said(o)]
    if said:
        lines = lines[said[-1] + 1:]                       # 읽은 범위에 사용자 말이 없으면 범위 전체를 본다
    for o in lines:
        for p in edited_paths(o):
            rest = _below(p, cwd)                              # `.devkit`은 cwd 뒤쪽 조각에서만 본다
            if rest is not None and not under_devkit(rest):
                return True
    return False


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        if not isinstance(data, dict) or not should_speak(data):
            return 0
        out = json.dumps({"decision": "block", "reason": REASON}) + "\n"
        sys.stdout.buffer.write(out.encode("ascii"))
        sys.stdout.buffer.flush()
    except Exception:                         # 고장 나면 조용히 끝낸다 — 끝내기를 막지 않는다
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
