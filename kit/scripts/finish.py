#!/usr/bin/env python3
"""AI가 일을 끝내려 할 때 한 번 끼어들어 끝내기 전 점검을 귀띔한다 (Stop 훅, python3 표준 라이브러리만).

stdin의 JSON(기록 파일 길 · 마지막 말 · 작업 폴더)을 읽어, 셋이 다 참일 때만 막으며(block) 귀띔 글을 낸다:
이미 한 번 끼어든 뒤가 아니고 · 마지막 말에 점검 보고 줄이 없고 · 이번 차례(마지막 사용자 말, 또는 점검 줄로 끝낸 뒤 온 알림 줄 뒤)에
프로젝트 폴더(환경 변수 CLAUDE_PROJECT_DIR, 없으면 작업 폴더) 안의 파일을 고치기 도구로 고쳤거나, 명령·맡김 도구를 쓴 뒤
그 폴더 안 파일의 고친 시각이 이번 차례의 시작보다 새로울 때(숨김 이름·빌드 폴더 따위는 거르고, 파일이 많거나 느리면 보지 않고 조용하다).
기록 파일은 읽기만 하고(파일을 만들지 않는다) 하위 프로세스를 부르지 않는다. 고장 나면 아무것도 찍지 않고 0으로 끝난다(끝내기를 막지 않는다).
"""
import sys
sys.dont_write_bytecode = True           # 꾸러미 폴더에 __pycache__를 만들지 않는다 (들여오기 전에)

import json
import os
import time
from datetime import datetime

# 기록 파일은 뒤에서부터 이만큼만 읽는다 — 긴 대화의 기록은 수백 MB가 될 수 있고, 마지막 사용자 말 뒤의 일은 거의 늘 이 안에 든다.
TAIL = 4 * 1024 * 1024
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
# 고친 시각 살핌 — 본 항목이 WALK_MAX개를 넘거나 WALK_SECS초가 지나면 그만두고 조용하다. 미래 시각은 FUTURE_SLACK초까지만 봐준다.
WALK_MAX = 30000
WALK_SECS = 1.5
FUTURE_SLACK = 2.0
SKIP_DIRS = ("node_modules", "__pycache__", "venv", "env", "dist", "build", "target", "out", "coverage", "htmlcov",
             "vendor", "_build", "test-results", "playwright-report")
SKIP_ENDS = (".pyc", ".pyo", ".log", ".tmp", ".swp", ".db", ".sqlite", ".sqlite3", "-wal", "-shm", "-journal",
             ".tsbuildinfo")
SHELL_TOOLS = ("bash", "powershell", "repl")
AGENT_TOOLS = ("Agent", "Task")
MCP_HEAD = "mcp__"
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


def project_root(cwd):
    """프로젝트 뿌리 — 환경 변수 CLAUDE_PROJECT_DIR가 빈 글이 아닌 글이면 그것, 아니면 받은 cwd. 부를 때마다 읽는다."""
    v = os.environ.get("CLAUDE_PROJECT_DIR")
    return v if isinstance(v, str) and v else cwd


def is_notification(obj):
    """백그라운드 일이 끝났다고 알리는 줄(맨 위 origin의 kind가 task-notification인 user 줄)인가."""
    if not isinstance(obj, dict) or not _plain(obj, "user"):
        return False
    origin = obj.get("origin")
    return isinstance(origin, dict) and origin.get("kind") == "task-notification"


def says_mark(obj):
    """그 줄(assistant)의 글에 MARK가 들어 있는가."""
    if not isinstance(obj, dict) or not _plain(obj, "assistant"):
        return False
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return MARK in content
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str) and MARK in b["text"]
                   for b in content)
    return False


def is_user_said(obj):
    """사용자가 한 말인 줄인가 — 글이거나, 도구 결과가 아닌 묶음이 하나라도 든 user 줄. 알림 줄은 아니다."""
    if not isinstance(obj, dict) or not _plain(obj, "user") or is_notification(obj):
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


def parse_time(s):
    """대화 기록의 timestamp 글을 1970 기준 초(float)로 — 시간대(Z 또는 +HH:MM)가 없거나 읽을 수 없으면 None."""
    if not isinstance(s, str):
        return None
    if s[-1:] in ("Z", "z"):
        body, zone = s[:-1], "+00:00"
    elif len(s) > 6 and s[-6] in "+-" and s[-3] == ":":
        body, zone = s[:-6], s[-6:]
    else:
        return None
    main, dot, frac = body.partition(".")
    digits = "0123456789"
    if len(main) != 19 or main[10] != "T":
        return None
    if dot:
        if not 1 <= len(frac) <= 9 or any(c not in digits for c in frac):
            return None
        main = main + "." + frac[:6].ljust(6, "0")
    try:
        return datetime.fromisoformat(main + zone).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def changing_tool(name):
    """파일을 바꿀 수 있는 도구 이름인가 — 명령 도구 · 맡김 도구 · mcp__로 시작하는 도구."""
    if not isinstance(name, str):
        return False
    return name.lower() in SHELL_TOOLS or name in AGENT_TOOLS or name.startswith(MCP_HEAD)


def may_have_changed(lines):
    """줄들(assistant) 안에 파일을 바꿀 수 있는 도구 쓰임이 하나라도 있는가."""
    for o in lines:
        if not isinstance(o, dict) or not _plain(o, "assistant"):
            continue
        msg = o.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use" and changing_tool(b.get("name")):
                return True
    return False


def skip_root(root):
    """파일 시스템의 맨 위이거나 홈 폴더인가 — 글자 셈만 한다."""
    n = os.path.normpath(root)
    return os.path.dirname(n) == n or n == os.path.normpath(os.path.expanduser("~"))


def changed_since(root, since, limit=None, secs=None, clock=None, now=None):
    """root 아래 보통 파일의 고친 시각이 since보다 새로운(그리고 지금+FUTURE_SLACK 이내인) 것이 있는가.
    항목마다 세고 · 수 상한 · 시계 상한을 본 뒤에 가린다. 상한을 넘으면 그만두고 False. 읽기만 한다."""
    if limit is None:
        limit = WALK_MAX
    if secs is None:
        secs = WALK_SECS
    if clock is None:
        clock = time.monotonic
    if now is None:
        now = time.time()
    ceiling = now + FUTURE_SLACK
    start = clock()
    seen = 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    seen += 1
                    if seen > limit:
                        return False
                    if clock() - start > secs:
                        return False
                    try:
                        name = e.name
                        if e.is_dir(follow_symlinks=False):
                            if not (name.startswith(".") or name in SKIP_DIRS):
                                stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            if name.startswith(".") or name.endswith(SKIP_ENDS):
                                continue
                            m = e.stat(follow_symlinks=False).st_mtime
                            if since < m <= ceiling:
                                return True
                    except OSError:
                        continue
        except OSError:
            continue
    return False


def base_index(lines):
    """이번 차례가 시작되는 줄(기준 줄)의 자리, 없으면 None.
    마지막 사용자 말이 기본이고, 그 뒤의 알림 줄 가운데 바로 앞 assistant 줄에 MARK가 있는(점검 줄로 닫힌) 것이 있으면 그 마지막 것."""
    u = -1
    for i, o in enumerate(lines):
        if is_user_said(o):
            u = i
    best = u if u >= 0 else None
    for i in range(u + 1, len(lines)):
        if not is_notification(lines[i]):
            continue
        for j in range(i - 1, u, -1):
            o = lines[j]
            if isinstance(o, dict) and _plain(o, "assistant"):
                if says_mark(o):
                    best = i
                break
    return best


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
    b = base_index(lines)
    since = None
    if b is not None:
        since = parse_time(lines[b].get("timestamp"))
        lines = lines[b + 1:]                              # 읽은 범위에 기준 줄이 없으면 범위 전체를 본다
    root = project_root(cwd)
    for o in lines:
        for p in edited_paths(o):
            rest = _below(p, root)                             # 뿌리 아래면 뿌리 뒤쪽 조각, 아니면 cwd 아래의 뒤쪽 조각
            if rest is None:
                rest = _below(p, cwd)
            if rest is not None and not under_devkit(rest):    # `.devkit`은 뒤쪽 조각에서만 본다
                return True
    if since is None or not may_have_changed(lines) or skip_root(root):
        return False
    return changed_since(root, since)


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
