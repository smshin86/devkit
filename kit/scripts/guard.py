#!/usr/bin/env python3
"""파일을 열거나 검색하기 직전(훅)에 비밀값이 딸려 나올 꼴을 한 번 더 거른다 (python3 표준 라이브러리만).

stdin의 JSON(도구 이름·입력)을 읽어, 비밀값 파일 꼴이면 묻고(ask) 비밀 낱말로 찾은 줄을 그대로 찍는 검색이면 막는다(deny).
걸릴 때 말고는 아무것도 찍지 않는다. 입력을 못 읽으면 조용히 0, 판정 중 예외는 stderr에 ASCII 한 줄과 1.
파일은 읽기만 한다(프로젝트 목록 한 장). 파일을 만들지 않고, 하위 프로세스를 부르지 않는다.
"""
import sys
sys.dont_write_bytecode = True           # 꾸러미 폴더에 __pycache__를 만들지 않는다 (들여오기 전에)

import fnmatch
import json
import os
import re
import shlex

NAMES = [".env*", "credentials.*", "*secret*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
         "id_rsa*", ".npmrc", ".pypirc", ".netrc", "serviceAccountKey.json"]
EXAMPLE_PARTS = {"example", "sample", "template", "dist", "pub"}
DATA_EXT = {"", "json", "yml", "yaml", "txt", "properties", "xml", "ini", "cfg", "conf", "toml", "env"}
WORDS = ["password", "passwd", "secret", "api_key", "apikey", "api-key", "token", "private_key", "database_ur", "jdbc"]
READERS = {"cat", "head", "tail", "less", "more", "nl", "tac", "sed", "awk", "cut", "sort", "strings", "xxd", "od",
           "base64", "source", "diff", "jq"}
GREPS = {"grep", "egrep", "fgrep", "rg", "ag", "ack"}
DOCS = {"cat", "tee", "git", "gh"}
SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
HEREDOC = re.compile(r"""(?<!<)<<(?!<)-?\s*(?:'([^']+)'|"([^"]+)"|\\?([^\s'"\\|;&<>()`]+))""")
INNER = re.compile(r"""(?:\$\(|`)\s*([^\s'"$()`]*)""")
PART = re.compile(r"[^|;&]+")
QUOTED = re.compile(r"""(?<!<)<<-?\s*(?:'[^']*'|"[^"]*")|"[^"]*"|'[^']*'""")
FIRST = re.compile(r"""\s*(\w+="?\$\(\s*)?([^\s'"$()`=<>]+)""")
COMMENT = re.compile(r"(?:^|\s)#")
BREAKS = "|&;()\n`"
LIST_SHORT = "lcLq"
LIST_LONG = {"--count", "--files-with-matches", "--files-without-match", "--quiet", "--silent", "--files",
             "--count-matches"}
VALUE_SHORT = "ABCDdfmgtM"
VALUE_LONG = {"--include", "--exclude", "--exclude-dir", "--exclude-from", "--max-count", "--context",
              "--before-context", "--after-context", "--file", "--glob", "--iglob", "--type", "--type-not",
              "--label", "--binary-files", "--devices", "--directories", "--max-depth", "--depth", "--sort", "--sortr",
              "--max-columns"}
GLOB_OPTS = {"-g", "--glob", "--include"}
MARKER = ".devkit-guard-off"
LIST_PATH = (".devkit", "secret-names")
LIST_MAX_LINES = 50
LIST_MAX_BYTES = 4096
MESSAGES = {
    "ask": "devkit: 이 파일은 이름이 비밀값 파일 꼴이다({name}). 열면 내용이 대화 기록에 남는다. "
           "값이 꼭 필요할 때만 허용하고, 값 없이 할 수 있는 일이면 열지 않고 진행한다.",
    "deny": "devkit: 비밀번호·키 같은 낱말로 찾은 줄을 그대로 찍는 검색은 막는다(값이 기록에 남는다). "
            "파일 이름만(-l) 또는 개수만(-c) 나오게 바꿔 다시 찾고, 필요한 코드 파일은 그 뒤에 연다. 일은 멈추지 않는다.",
}


def secret_name(path, extra=()):
    """이름(마지막 `/` 뒤)이 비밀값 파일 꼴이면 True. 본보기 이름은 False, `*secret*`만 맞으면 자료 확장자일 때만."""
    base = str(path).replace("\\", "/").rstrip("/").split("/")[-1].lower()
    if not base:
        return False
    if EXAMPLE_PARTS & set(base.split(".")[1:]):
        return False
    for pat in extra:
        if fnmatch.fnmatchcase(base, str(pat).lower()):
            return True
    hits = [pat for pat in NAMES if fnmatch.fnmatchcase(base, pat.lower())]
    if not hits:
        return False
    if hits != ["*secret*"]:
        return True
    ext = base.rsplit(".", 1)[1] if "." in base else ""
    return ext in DATA_EXT


def has_word(text):
    low = str(text).lower()
    return any(w in low for w in WORDS)


def _mask(m):
    """따옴표 안의 글자일 뿐인 `<<`(커밋 제목 따위)는 heredoc이 아니다 — 같은 길이의 빈칸으로 가린다.

    `$(`·백틱이 든 큰따옴표 글은 속 명령이 있을 수 있어 남기되, 그 안의 `<<`는 heredoc으로 보지 않는다."""
    s = m.group()
    if s[0] == "<":
        return s
    if s[0] == '"' and ("$(" in s or "`" in s):
        return s.replace("<<", "  ")
    return " " * len(s)


def _only_text(line):
    """이 줄의 `<<표`마다 (끝 줄 낱말, 글을 빼도 되는가, 글 속 `$(`·백틱이 셸에서 풀리는가).

    빼도 되는 것은 글을 돌리지 않는 명령(`cat`·`tee`·`git`·`gh`)이 받는 글뿐이다 — 모르는 명령이 받는 글은
    명령으로 본다(`bash`·`ssh`·`sudo -i`처럼 그 글을 돌리는 명령을 다 알 수 없다). 아래 중 하나라도 있으면
    누가 글을 받는지 알 수 없어 빼지 않는다: 그 `<<` 뒤의 `|`, `<(`·`>(`·`\\`·`((`·`$[`, `#` 주석,
    끝 줄 낱말 바로 뒤에 붙은 글자, `$(`·백틱 안의 `cat`·`tee`·`git`·`gh`가 아닌 명령.
    `$(`·백틱이 `<<` 앞에 있으면 `git`·`gh`가 받거나 `이름=$(…`로 담을 때만 뺀다(`cat $(cat <<…`의 글은 인자가 된다)."""
    out, piped = [], line.rfind("|")
    plain = not any(x in line for x in ("<(", ">(", "\\", "((", "$["))
    seen = QUOTED.sub(_mask, line)                     # 제목 속 `&`·`<<`에 속지 않게 — 파이프(`piped`)만은 가리지 않은 줄에서 본다
    hash_at = COMMENT.search(seen)
    hash_at = hash_at.start() if hash_at else len(line)
    nested = bad = len(line)                           # 줄에서 처음 나오는 속 명령 자리 · 그 가운데 `cat`·`tee`·`git`·`gh`가 아닌 것의 자리
    for w in INNER.finditer(line):
        nested = min(nested, w.start())
        if _last(w.group(1)) not in DOCS:
            bad = min(bad, w.start())
    for part in PART.finditer(seen):
        first = FIRST.match(part.group())              # `이름=$(cat <<…` 의 `cat`까지 본다
        word = _last(first.group(2)) if first else ""
        safe = plain and word in DOCS
        for m in HEREDOC.finditer(seen, part.start(), part.end()):
            tail = seen[m.end():m.end() + 1]
            safe = (safe and piped < m.end() and hash_at > m.start() and bad > m.start()
                    and (tail == "" or tail in " \t|;&<>()")
                    and (nested > m.start() or bool(first.group(1)) or word in ("git", "gh")))
            expands = m.group(3) is not None and "\\" not in m.group()
            out.append((m.group(1) or m.group(2) or m.group(3), safe, expands))
    return out


def drop_heredocs(cmd):
    """돌리지 않는 heredoc 글(커밋 메시지·파일에 써 넣는 글)은 명령이 아니다 — 끝 줄이 있을 때만 뺀다."""
    lines = cmd.split("\n")
    last = {line.strip(): k for k, line in enumerate(lines)}
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        if "<<" not in line:
            continue
        for end, only_text, expands in _only_text(line):
            if last.get(end, -1) < i:
                break
            stop = next(k for k in range(i, len(lines)) if lines[k].strip() == end)
            if expands and any("$(" in b or "`" in b for b in lines[i:stop]):
                only_text = False                      # 따옴표 없는 끝 줄 낱말: 글 속 `$(`·백틱을 셸이 돌린다
            if not only_text:
                out.extend(lines[i:stop + 1])
            i = stop + 1
    return "\n".join(out)


def segments(cmd):
    """명령 글자를 파이프·`;`·`&`·괄호·줄바꿈 경계로 쪼갠다 — [(파이프 줄 번호, 토큰들)].

    `|`·괄호로만 갈린 조각은 번호가 같다. 따옴표가 안 맞으면 거칠게 쪼개고 번호는 모두 0이다."""
    joined = re.sub(r"\|[ \t]*\n", "| ", cmd)        # 줄 끝의 `|`는 다음 줄로 이어진다
    lex = shlex.shlex(joined.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""                  # `#`는 주석이 아니다 — AI가 첫 줄에 단 주석 뒤의 명령도 봐야 한다
    out, seg, pipe = [], [], 0
    try:
        for tok in lex:
            if tok and all(c in "|&;()" for c in tok):
                if seg:
                    out.append((pipe, seg))
                seg = []
                if ";" in tok or "&&" in tok or tok == "&":
                    pipe += 1
            else:
                seg.append(tok)
    except ValueError:
        rough = cmd
        for c in BREAKS:
            rough = rough.replace(c, "\n")
        return [(0, [t.strip("'\"") for t in line.split()]) for line in rough.split("\n") if line.split()]
    if seg:
        out.append((pipe, seg))
    return out


def _last(text):
    return text.split("/")[-1]


def grep_verdict(args, extra, rg=False, more=()):
    pats, pos, globs, listonly = [], [], [], False
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        i += 1
        if a == "--":
            pos.extend(args[i:])
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if name in LIST_LONG:
                listonly = True
            elif name == "--regexp":
                if eq:
                    pats.append(val)
                elif i < n:
                    pats.append(args[i])
                    i += 1
            elif name in VALUE_LONG:
                if eq:
                    got = val
                elif i < n:
                    got = args[i]
                    i += 1
                else:
                    got = None
                if got is not None and name in GLOB_OPTS:
                    globs.append(got)
        elif a.startswith("-") and len(a) >= 2:
            j = 1
            while j < len(a):
                c = a[j]
                j += 1
                if c in LIST_SHORT and not (rg and c == "L"):
                    listonly = True
                elif c == "e":
                    rest = a[j:]
                    if rest:
                        pats.append(rest)
                    elif i < n:
                        pats.append(args[i])
                        i += 1
                    break
                elif c in VALUE_SHORT:
                    got = a[j:]
                    if not got and i < n:
                        got = args[i]
                        i += 1
                    if c == "g" and got:
                        globs.append(got)
                    break
        else:
            pos.append(a)
    if pats:
        files = pos
    else:
        pats, files = pos[:1], pos[1:]
    if listonly:
        return None
    for f in files + globs + list(more):
        if secret_name(f, extra):
            return ("ask", _last(f))
    if any(has_word(p) for p in pats):
        return ("deny", "")
    return None


def _first_name(tokens, extra):
    return next((t for t in tokens if not t.startswith("-") and secret_name(t, extra)), None)


def earlier_name(segs, n, extra, before):
    """같은 파이프 줄에서 n번째 조각보다 앞선 조각들에 처음 나오는 비밀값 파일 이름 — before는 줄마다 한 번만 채운다."""
    if not before:
        got = None
        for s in segs:
            before.append(got)
            got = got or _first_name(s, extra)
    return before[n]


def segment_verdict(seg, extra, earlier):
    """earlier() — 같은 파이프 줄의 앞 조각들에 처음 나오는 비밀값 파일 이름(`xargs`·`find -exec … {}`가 넘겨받는 이름)."""
    args, i = [], 0
    while i < len(seg):
        tok = seg[i]
        if tok and all(c in "<>&" for c in tok):
            if "<" in tok and i + 1 < len(seg) and secret_name(seg[i + 1], extra):
                return ("ask", _last(seg[i + 1]))
            i += 2
            continue
        args.append(tok)
        i += 1
    passed = "{}" in args or any(_last(t) == "xargs" for t in args)
    read = False
    for j, tok in enumerate(args):
        cmd = _last(tok)
        if cmd in GREPS:
            # 넘겨받는 이름은 앞 조각들과 이 조각의 검색 명령 앞에서만 찾는다 — 검색 낱말(`grep -n '.env'`)은 파일 이름이 아니다
            hit = (earlier() or _first_name(args[:j], extra)) if passed else None
            return grep_verdict(args[j + 1:], extra, cmd == "rg", [hit] if hit else [])
        if not read and (cmd in READERS or (j == 0 and cmd == ".")):
            # 첫 읽는 명령 한 번만, 그 뒤에서만 이름을 찾는다 — 앞의 것(`ssh -i 키파일`, `docker --env-file .env`)은 읽는 파일이 아니다
            read = True
            hit = _first_name(args[j + 1:], extra)
            if not hit and passed:
                hit = earlier() or _first_name(args[:j], extra)
            if hit:
                return ("ask", _last(hit))
    return None


def _str(value):
    return value if isinstance(value, str) else ""


def judge(tool, tool_input, extra_names=()):
    if not isinstance(tool_input, dict):
        return None
    if tool == "Read":
        path = _str(tool_input.get("file_path"))
        return ("ask", _last(path)) if secret_name(path, extra_names) else None
    if tool == "Grep":
        if tool_input.get("output_mode") != "content":
            return None
        for key in ("path", "glob"):
            got = _str(tool_input.get(key))
            if secret_name(got, extra_names):
                return ("ask", _last(got))
        return ("deny", "") if has_word(_str(tool_input.get("pattern"))) else None
    if tool == "Bash":
        cmd = drop_heredocs(_str(tool_input.get("command")).replace("\\\n", " "))
        cmd = cmd.replace("\\;", " | ")   # find의 `-exec … \;` 끝 — 조각은 가르되 같은 파이프 줄로 둔다
        texts = [cmd] + [m.group(1) or m.group(2) or "" for m in SUBST.finditer(cmd)]
        lines = {}
        for k, text in enumerate(texts):
            for p, s in segments(text):
                lines.setdefault((k, p), []).append(s)
        found = []
        for segs in lines.values():
            before = []
            for n, s in enumerate(segs):
                v = segment_verdict(s, extra_names, lambda n=n: earlier_name(segs, n, extra_names, before))
                if v is not None:
                    found.append(v)
        for v in found:
            if v[0] == "deny":
                return v
        return found[0] if found else None
    return None


def turned_off():
    return os.path.exists(os.path.join(os.path.expanduser("~"), MARKER))


def answer(kind, name=""):
    reason = MESSAGES[kind].format(name=name)
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": kind,
                                              "permissionDecisionReason": reason}}) + "\n"


def project_names(data):
    """프로젝트 폴더(위로 올라가며 찾지 않는다)의 `.devkit/secret-names`에서 더 적은 이름 꼴. 못 읽으면 ()."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        root = data.get("cwd")
    if not isinstance(root, str) or not root:
        return ()
    try:
        path = os.path.join(root, *LIST_PATH)
        if not os.path.isfile(path):
            return ()
        with open(path, "rb") as f:
            raw = f.read(LIST_MAX_BYTES)
    except (OSError, ValueError):
        return ()
    lines = raw.decode("utf-8-sig", errors="replace").splitlines()[:LIST_MAX_LINES]
    lines = [x.strip() for x in lines]
    lines = [x.replace("\\", "/").split("/")[-1] for x in lines if x and not x.startswith("#")]
    return tuple(x for x in lines if x)


def _complain(exc):
    try:
        text = "devkit guard: internal error (%s)\n" % type(exc).__name__
        sys.stderr.write(text.encode("ascii", "replace").decode("ascii"))
        sys.stderr.flush()
    except Exception:
        pass
    return 1


def main():
    try:
        raw = sys.stdin.buffer.read()
    except Exception as e:
        return _complain(e)
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, RecursionError):
        return 0
    if not isinstance(data, dict):
        return 0
    try:
        if turned_off():
            return 0
        extra = project_names(data)
        verdict = judge(data.get("tool_name"), data.get("tool_input"), extra)
        if verdict is None:
            return 0
        sys.stdout.buffer.write(answer(verdict[0], verdict[1]).encode("ascii"))
        sys.stdout.buffer.flush()
        return 0
    except Exception as e:
        return _complain(e)


if __name__ == "__main__":
    sys.exit(main())
