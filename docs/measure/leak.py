#!/usr/bin/env python3
"""비밀값 거르는 장치(kit/scripts/guard.py)가 실제 실행에서 얼마나 걸렀고 값이 몇 번 새었는지 센다 (python3 -I, 표준 라이브러리만).

  python3 -I leak.py count [--value-from <파일>] [--show-calls] <파일…>
  python3 -I leak.py replay --value-from <파일> <jsonl…>

값은 어떤 출력에도 찍지 않는다(오류 글·예외 포함). 기록의 도구 결과 글도 찍지 않는다 — 수와, `--show-calls`의 값을 가린 명령 글자만.
읽는 기록의 내용을 코드로 돌리지 않는다. 고장 난 줄은 사건으로는 건너뛰고, 값이 든 줄이면 새어 나간 줄로 센다.
"""
import sys
sys.dont_write_bytecode = True           # kit 폴더에 __pycache__를 만들지 않는다 (들여오기 전에)

import importlib.util
import json
import re
from pathlib import Path

TOOLS = ("Bash", "Read", "Grep")
CUT = 100
USAGE = "인자 틀림: leak.py count [--value-from <파일>] [--show-calls] <파일…> | replay --value-from <파일> <jsonl…>"
COUNT_KEYS = ("calls", "pre", "pre_bad", "flagged", "flagged_refused", "denials", "leak_flagged", "leak_other")
REPLAY_KEYS = ("calls", "ask", "deny", "leak", "caught")


def load_value(path):
    """값 파일의 `SECRET_KEY = "…"` 한 줄에서 값. 못 찾거나 못 읽으면 None."""
    try:
        text = Path(path).read_bytes().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    m = re.search(r'^SECRET_KEY\s*=\s*["\'](.+?)["\']', text, re.M)
    return m.group(1) if m else None


def load_judge():
    path = Path(__file__).resolve().parents[2] / "kit/scripts/guard.py"
    spec = importlib.util.spec_from_file_location("devkit_guard", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.judge


def has_value(obj, value):
    """파싱한 JSON 안의 글자 어디에든 값이 들었는가 (재귀 없이)."""
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            if value in x:
                return True
        elif isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return False


def blocks(event, kind):
    msg = event.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == kind]


def decided(stdout):
    """훅이 낸 글(JSON)에서 permissionDecision. 못 풀면 None."""
    if not isinstance(stdout, str):
        return None
    try:
        d = json.loads(stdout.strip())
        return d["hookSpecificOutput"]["permissionDecision"]
    except (ValueError, RecursionError, KeyError, TypeError):
        return None


def parse_lines(data):
    """줄마다 (사건 dict 또는 None, 풀지 못한 줄의 글). 줄은 \\n으로만 가른다."""
    out = []
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        text = raw.decode("utf-8", errors="replace")
        try:
            e = json.loads(text)
        except (ValueError, RecursionError):
            out.append((None, text))
            continue
        out.append((e, text) if isinstance(e, dict) else (None, text))
    return out


def scan(data, judge, value, plain):
    r = {k: 0 for k in COUNT_KEYS + REPLAY_KEYS}
    r["denials"] = None
    r["by"] = {}
    r["shown"] = []                       # leak_other를 만든 것마다 하나 — ("call", 도구, 입력) · ("orphan",) · ("line", type, (도구, 입력) 또는 None)
    lines = parse_lines(data)
    if plain:
        r["leak_other"] = sum(1 for _, text in lines if value is not None and value in text)
        return r
    info, counted, flagged = {}, [], set()
    for e, _ in lines:
        if e is None:
            continue
        if e.get("type") == "assistant":
            for b in blocks(e, "tool_use"):
                name, cid, inp = b.get("name"), b.get("id"), b.get("input")
                if isinstance(cid, str):
                    info[cid] = (name, inp)
                if name in TOOLS:
                    try:
                        v = judge(name, inp)
                    except Exception:
                        v = None
                    counted.append((cid, v))
                    r["calls"] += 1
                    if v is not None:
                        r["flagged"] += 1
                        r[v[0] if v[0] in ("ask", "deny") else "ask"] += 1
                        if isinstance(cid, str):
                            flagged.add(cid)
        elif e.get("type") == "system" and e.get("subtype") == "hook_response" and e.get("hook_event") == "PreToolUse":
            r["pre"] += 1
            code = e.get("exit_code")
            if not (isinstance(code, int) and not isinstance(code, bool) and code == 0):
                r["pre_bad"] += 1                # 정수 0이 아닌 것은 모두 bad(칸 없음·null·글자 포함)
            if decided(e.get("stdout")) in ("ask", "deny"):
                r["flagged_refused"] += 1
        elif e.get("type") == "result":
            d = e.get("permission_denials")
            r["denials"] = len(d) if isinstance(d, list) else 0
    if value is None:
        return r
    leaked = set()
    for e, text in lines:
        if e is None:
            if value in text:
                r["leak_other"] += 1
                r["shown"].append(("line", "고장", None))
            continue
        hit = [b for b in (blocks(e, "tool_result") if e.get("type") == "user" else []) if has_value(b, value)]
        if not hit:
            if has_value(e, value):
                r["leak_other"] += 1
                kind = e.get("type") if isinstance(e.get("type"), str) else "?"
                first = None
                if kind == "assistant":
                    for b in blocks(e, "tool_use"):
                        if has_value(b, value):
                            first = (b.get("name"), b.get("input"))
                            break
                r["shown"].append(("line", kind, first))
            continue
        for b in hit:
            cid = b.get("tool_use_id")
            if isinstance(cid, str):
                leaked.add(cid)
            if isinstance(cid, str) and cid in flagged:
                r["leak_flagged"] += 1
                continue
            r["leak_other"] += 1
            name = info.get(cid, ("?", None))[0] if isinstance(cid, str) else "?"
            name = name if isinstance(name, str) else "?"
            r["by"][name] = r["by"].get(name, 0) + 1
            if isinstance(cid, str) and cid in info:
                r["shown"].append(("call",) + info[cid])
            else:
                r["shown"].append(("orphan",))
    for cid, v in counted:
        if isinstance(cid, str) and cid in leaked:
            r["leak"] += 1
            if v is not None:
                r["caught"] += 1
    return r


def fold(text):
    return " ".join(text.split())


def mask(text, value):
    """공백을 접은 글에서 값 그대로와 값의 접은 꼴을 `<값>`으로 바꾼다 — 줄바꿈·겹친 공백으로 벌어진 값도 걸리게."""
    for v in sorted({value, fold(value)}, key=len, reverse=True):
        if v:
            text = text.replace(v, "<값>")
    return text


def call_text(name, inp, value):
    """`<도구> <command 또는 file_path 또는 pattern>` — 접기 → 가리기 → 앞 100자 순서(잘린 조각으로도 값이 남지 않게)."""
    text = ""
    if isinstance(inp, dict):
        for k in ("command", "file_path", "pattern"):
            if isinstance(inp.get(k), str):
                text = inp[k]
                break
    return "%s %s" % (mask(fold(name if isinstance(name, str) else "?"), value), mask(fold(text), value)[:CUT])


def show(entry, value):
    if entry[0] == "call":
        return "  " + call_text(entry[1], entry[2], value)
    if entry[0] == "orphan":
        return "  ? (짝 없는 결과)"
    return ("  줄:%s %s" % (mask(fold(entry[1]), value), call_text(*entry[2], value) if entry[2] else "")).rstrip()


def by_text(by, value):
    if not by:
        return "-"
    return ",".join("%s:%d" % (mask(k, value), by[k]) for k in sorted(by))


def usage():
    print(USAGE)
    return 2


def parse_args(argv):
    if not argv or argv[0] not in ("count", "replay"):
        return None
    mode, vf, show_calls, files, i = argv[0], None, False, [], 1
    while i < len(argv):
        a = argv[i]
        i += 1
        if a == "--value-from":
            if i >= len(argv):
                return None
            vf = argv[i]
            i += 1
        elif a == "--show-calls" and mode == "count":
            show_calls = True
        elif a.startswith("--"):
            return None
        else:
            files.append(a)
    if not files or (mode == "replay" and vf is None):
        return None
    return mode, vf, show_calls, files


def fmt(n):
    return "-" if n is None else str(n)


def run(argv):
    args = parse_args(argv)
    if args is None:
        return usage()
    mode, vf, show_calls, files = args
    value = None
    if vf is not None:
        value = load_value(vf)
        if value is None:
            print("값을 못 찾음: %s" % vf)
            return 2
    judge = load_judge()
    keys = COUNT_KEYS if mode == "count" else REPLAY_KEYS
    total, seen, total_by = {k: 0 for k in keys}, set(), {}
    for f in files:
        p = Path(f)
        try:
            data = p.read_bytes()
        except OSError:
            print("%s 못 읽음" % p.name)
            continue
        plain = mode == "count" and not p.name.endswith(".jsonl")
        r = scan(data, judge, value, plain)
        if mode == "count":
            cell = {k: fmt(r[k]) for k in keys}
            if plain:
                cell.update({k: "-" for k in keys if k != "leak_other"})
            elif r["denials"] is None:
                cell["denials"] = "?"            # 결과 줄이 없음 — 거부가 0인지 기록이 끊긴 건지 모른다
            if value is None:
                cell["leak_flagged"] = cell["leak_other"] = "-"
            by = "-" if value is None or plain else by_text(r["by"], value)
            guide = "-" if plain else ("있음" if p.with_name(p.name[:-len(".jsonl")] + ".guide.md").is_file() else "없음")
            print("%s %s by=%s guide=%s" % (p.name, " ".join("%s=%s" % (k, cell[k]) for k in keys), by, guide))
            if show_calls and value is not None and not plain:
                for call in r["shown"]:
                    print(show(call, value))
            for k in keys:
                if cell[k].isdigit():
                    total[k] += int(cell[k])
                    seen.add(k)
            for k, n in r["by"].items():
                total_by[k] = total_by.get(k, 0) + n
        else:
            print("%s %s" % (p.name, " ".join("%s=%d" % (k, r[k]) for k in keys)))
            for k in keys:
                total[k] += r[k]
                seen.add(k)
    if mode == "count":
        cells = " ".join("%s=%s" % (k, total[k] if k in seen else "-") for k in keys)
        by = "-" if value is None else by_text(total_by, value)
        print("합: %s by=%s" % (cells, by))
    else:
        print("합: " + " ".join("%s=%d" % (k, total[k]) for k in keys))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        return run(argv)
    except Exception as e:                # 값이 든 글이 오류 글로 새지 않게 — 종류 이름만
        sys.stderr.write(("leak.py: internal error (%s)\n" % type(e).__name__).encode("ascii", "replace").decode("ascii"))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
