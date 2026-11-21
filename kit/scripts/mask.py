#!/usr/bin/env python3
"""도구가 읽어 온 글에서 비밀값 꼴만 가려 AI에게 넘긴다 (PostToolUse 훅, python3 표준 라이브러리만).

stdin의 JSON(도구 이름·입력·결과)을 읽어, 결과 안의 글에서 비밀값 꼴을 찾으면 그 값만 가린 결과를 내놓는다.
가릴 것이 없으면 아무것도 찍지 않는다(같은 결과를 되돌려 쓰지 않는다). 파일을 읽지도 만들지도 않고, 하위 프로세스를 부르지 않는다.
고장 나면 원래 결과가 그대로 간다 — 다 가리는 장치가 아니다.
"""
import sys
sys.dont_write_bytecode = True

import json
import os
import posixpath
import re

MARK = "<devkit이 가린 값>"
MARKER = ".devkit-guard-off"
NOTE = ("devkit: 이 결과에서 비밀값으로 보이는 값 %d개를 가렸다(%s). 파일에는 진짜 값이 그대로 있다. "
        "가려진 줄은 고쳐 쓰지 않는다 — 파일을 통째로 다시 쓰지 말고 다른 줄만 고친다. "
        "값이 꼭 필요하면 사용자에게 묻는다.")
ENDS = ("password", "passwd", "pwd", "secret", "token", "apikey", "secretkey", "privatekey", "accesskey", "secretkeybase")
NOT_KEYS = {"pwd", "oldpwd"}
# 이름 = "값" · "이름": "값" · 이름="값"(XML 속성) · 이름표["이름"] = "값" · 이름 := "값"(Go)
_NAME = r"""(["']?)(?<![\w.\-])([\w.\-]+)\1(\]?\s*(?:=>|:=|=|:)\s*[bru]?)"""
_VALUE = r"""(["'])((?:(?!\4).)+)\4"""
_VALUE_ESC = r"""(["'])((?:\\.|(?!\4)[^\\])+)\4"""       # `\"`가 든 값 — `\` 다음 글자는 값의 끝이 아니다
QUOTED = re.compile(_NAME + _VALUE)
QUOTED_ESC = re.compile(_NAME + _VALUE_ESC)
# 한 줄이 통째로 `이름=값` / `이름: 값` 인 꼴(따옴표 없음) — .env · properties · yml.
# 앞의 diff 머리(`+`·`>`·`<`)·`파일:`·줄 번호·`#`(주석으로 막아 둔 줄)·`- `·`export`(Dockerfile의 `ENV`·`ARG`)는 건너뛰고, 뒤의 `# 주석`·줄 끝 `\r`은 그대로 둔다.
# 앞 공백은 한 묶음으로만 받는다(공백이 긴 줄에서 느려지지 않게).
PLAIN = re.compile(r"""^([+<>]?[ \t]*(?:[^\s:=]+:[ \t]*)?(?:\d+[:\-\t][ \t]*)?(?:#+[ \t]*)?(?:-[ \t]+)?(?:(?:export|ENV|ARG)[ \t]+)?)([\w.\-]+)([ \t]*(?::=|=|:(?!=))[ \t]*)([^\s'"#]\S*)((?:[ \t]+#.*)?[ \t\r]*)$""")
# <property name="…password" value="값"/>
XML_VALUE = re.compile(r"""(?i)((?:name|key)\s*=\s*["'])([^"'<>]+)(["'][^<>]{0,200}?\bvalue\s*=\s*)(["'])((?:(?!\4).)+)\4""")
# <password>값</password> · <entry key="db.password">값</entry>
XML_TEXT = re.compile(r"""(?i)(<([\w.\-:]+)(?![\w.\-:])(?:\s+(?:key|name)\s*=\s*["']([^"'<>]+)["'])?[^<>]*>)([^<>\s][^<>]*)(</)""")
# os.environ.get("SECRET_KEY", "값") · getenv("DB_PASSWORD", "값") · define('DB_PASSWORD', '값') · env("SECRET_KEY", default="값") — 값을 꺼내거나 정하는 호출의 둘째 글
_ARG = r"""(\(\s*(["'])([\w.\-]+)\2\s*,\s*(?:default\s*=\s*)?)"""
DEFAULT = re.compile(_ARG + _VALUE)
DEFAULT_ESC = re.compile(_ARG + _VALUE_ESC)
CALLEE = re.compile(r"([A-Za-z_]\w*)\s*$")
CALL_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")       # getProperty → get · Property
CALL_WORDS = {"get", "getenv", "env", "fetch", "property", "default", "setdefault", "define"}
# scheme://user:값@host · scheme://:값@host
URL = re.compile(r"""(?<![a-zA-Z0-9+.\-])([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@'"<>]*:)([^\s@/'"<>]+)(@)""")
# ?password=값&… · ?x-api-key=값 · #access_token=값 · &amp;client_secret=값 — 칸 이름이 비밀 낱말로 끝날 때(`;` 뒤는 낱말 그대로일 때만).
# 칸 머리(`?이름=`)와 값을 따로 본다 — 비밀이 아닌 칸은 값을 삼키지 않아, 그 뒤·안에 겹친 비밀 칸(`?next=/cb?password=값`)도 본다.
# `=`·`}`로 시작하는 값은 코드로 보고 둔다(`&&token==c` · 셸의 `${1#--password=}`). 백틱은 값에 넣지 않는다(`?token=${t}` 뒤의 닫는 백틱).
PARAM = re.compile(r"""(?i)(?:[?&#](?:amp;)?([\w\-]+)|;(?:password|passwd|pwd|secret|token|api_?key))=""")
PARAM_RUN = re.compile(r"""[^&;\s'"<>`]*""")
# 정규식·틀 글인 값(`([^&]+)` · `(?P<…` · `[^&]+` · `[[:alnum:]]+` · `{tok!r}` · `{a}/{b}` · `{{ … }}`)은 코드로 보고 둔다.
# `(값`·`[값`·`{값`·`{tok}값`·`{a}/값`·`[[:alnum:]]값`은 가린다.
_END = r"""(?![^&;\s'"<>`])"""
_BRACE_NAME = r"""[^{}&;\s'"<>`?#=]*\}[/\-._:,+~|@]*"""            # `{이름}`의 `{` 뒤 + 구분 글자
PARAM_CODE = re.compile(r"""\((?:[?\[\\.(]|%s)|\[(?:[\^\\]|[\w\-]*\]|\[:[a-z]+:\][^\]&;\s'"<>`?#=]*\](?:[+*?]|\{\d|%s)|%s)|\{(?:\{|(?:%s\{)*%s(?![^&;\s'"<>`?#])|%s)"""
                        % (_END, _END, _END, _BRACE_NAME, _BRACE_NAME, _END))
# 끼워 넣는 식(`{os.environ['K']}` · `{cfg["t"]}` · `{f(a, b)}` · `{tok or ''}` · `{tok:>10}`) — 다음 칸 머리 앞에 닫는 `}`가 있고
# 값 덩어리가 그 `}` 전에 따옴표·백틱·빈칸·`<`·`>`에서 끊길 때만 식으로 본다. 끊기지 않는 `{a(b)}값`은 위 `{이름}값`과 같이 가린다.
PARAM_EXPR = re.compile(r"""\{[A-Za-z_][\w.]*(?:[\[(\s]|:[<>^])[^{}]*\}""")
SHAPES = re.compile(
    r"(?<![A-Za-z0-9_\-])(?:"                              # 낱말 중간(`risk-…`·`disk-…`)은 토큰이 아니다
    r"AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{36,}"
    r"|github_pat_[A-Za-z0-9_]{40,}"
    r"|xox[abprs]-[A-Za-z0-9\-]{10,}"
    r"|sk-[A-Za-z0-9_\-]{20,}"
    r"|AIza[0-9A-Za-z_\-]{35}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"
    r"|[sr]k_(?:live|test)_[0-9A-Za-z]{20,}"
    r"|glpat-[0-9A-Za-z_\-]{20,}"
    r")"
)
# 개인 키 덩어리 — 머리 줄 뒤에 열쇠 글자(base64 · 줄 앞의 `파일:줄:` · 머리말)만 이어질 때, 그 안에 길고 뒤섞인 글이 있을 때만
PEM = re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)((?:(?!-----)[A-Za-z0-9+/=\s\\:,\-._])*)(-----END [A-Z ]*PRIVATE KEY-----)?")
PEM_RUN = re.compile(r"[A-Za-z0-9+/=]{40,}")
REF = re.compile(r"""^(?:\$\{.*\}|\$\(.*\)|\{\{.*\}\}|%\(.*\)s|<.*>|\$[A-Za-z_]\w*|ENC\(.*\)|%[sdr]|\{[\w.]*\})$""")
WORDS_ONLY = {"true", "false", "null", "none", "nil", "yes", "no", "on", "off", "undefined", "required", "optional"}
BLOCKS = {"|", ">", "|-", ">-", "|+", ">+"}                 # yml의 여러 줄 값 표시 — 값은 다음 줄에 있다(못 가린다)
IDENT = re.compile(r"^[A-Za-z_][A-Za-z_.]*$")
# 이름이 `…_KEY`·`….key`·`…-key`로 끝나고 값이 길고 뒤섞인 글일 때(APP_KEY · ENCRYPTION_KEY · signing-key)
KEY_NAME = re.compile(r"(?i)(?:^|[_.\-])key$")
KEY_VALUE = re.compile(r"^(?:base64:)?(?:(?=[^0-9]*[0-9])(?=[^A-Z]*[A-Z])(?=[^a-z]*[a-z])[A-Za-z0-9+/=_\-]{20,}|[0-9a-fA-F]{32,})$")
TEST_DIR = re.compile(r"(?i)(?:^|/)(?:tests?|__tests__|specs?|fixtures?|testdata|mocks?|e2e|cypress)/")
TEST_FILE = re.compile(r"(?:^|/)(?:(?i:test_[^/]*|[^/]*[._\-](?:tests?|spec)|tests?|conftest)|[^/]*[a-z0-9](?:Tests?|Spec))\.\w+$")
LINE_FILE = re.compile(r"^([^\s:]*\.\w+)[:\-]\d+[:\-]")       # 검색 결과 줄 앞의 `파일:줄:`
DATAISH = re.compile(r"(?i)(?:\.(?:ya?ml|env|properties|ini|cfg|conf|toml)|(?:^|/)\.env[^/]*|(?:^|/)Dockerfile[^/]*)$")
FILE_TOKEN = re.compile(r"[\w./\-]*[\w\-]\.[A-Za-z]\w*")


def secret_key(name):
    """이름이 비밀값을 담는 이름 꼴인가 — 끝이 비밀 낱말로 끝날 때만(`token_type`·`password_confirmation`은 아니다)."""
    n = re.sub(r"[^a-z0-9]", "", str(name).lower())
    return n not in NOT_KEYS and n.endswith(ENDS)


def long_key(name, value, data, upper=False):
    """이름이 `key`로 끝나고(낱말 경계) 값이 길고 뒤섞인 글인가 — 설정 파일(data)이거나 대문자 이름(upper)일 때만.
    코드의 대문자 상수는 더 좁게: `_`·`-`가 든 값은 32자 이상일 때만(`STORAGE_KEY = "myApp_UserPreferences_v1"`은 둔다)."""
    v = str(value).strip().rstrip(",;")
    if not (data or upper) or not KEY_NAME.search(str(name)) or not KEY_VALUE.match(v):
        return False
    return bool(data or len(v) >= 32 or not ("_" in v or "-" in v))


def _norm(path):
    return posixpath.normpath(str(path).replace("\\", "/"))


def testish(path, cwd=""):
    """시험 파일 꼴인가. 폴더 이름(`tests/` …)은 프로젝트 폴더(cwd) 안쪽 경로에서만 본다 —
    프로젝트가 `/home/u/test/app` 아래에 있다고 그 안의 파일이 다 시험 파일이 되지는 않는다."""
    p = _norm(path)
    c = _norm(cwd).rstrip("/") if cwd else ""
    if c and p.startswith(c + "/"):
        p = p[len(c) + 1:]
    elif p.startswith(("/", "../")) or p == ".." or re.match(r"^[A-Za-z]:/", p):
        return bool(TEST_FILE.search(p))                     # 프로젝트 밖 경로: 파일 이름만 본다
    return bool(TEST_DIR.search(p + "/") or TEST_FILE.search(p))


def keep_value(v, name=""):
    """값이 아니라 문장·자리표·가리킴·라벨이면 True(가리지 않는다)."""
    v = v.strip()
    if not v or v == MARK or REF.match(v):
        return True
    if not v.isascii() or len(v.split()) != 1:   # 띄어쓴 글·한글 라벨은 값이 아니다
        return True
    if re.search(r"\\u[0-9a-fA-F]{4}", v):                # properties의 \uXXXX 라벨
        return True
    flat = re.sub(r"[^a-z0-9]", "", v.lower())
    if flat and (flat == re.sub(r"[^a-z0-9]", "", str(name).lower()) or flat in ENDS):   # "password": "Password"
        return True
    return False


def keep_plain(v, name="", loose=False):
    """따옴표 없는 값이 코드(이름·호출·가리킴)면 True(가리지 않는다). loose면 이름 꼴 값도 값으로 본다(설정 파일 · `대문자_이름=값`)."""
    v = v.strip().rstrip(",;")
    if keep_value(v, name) or v.lower() in WORDS_ONLY or v in BLOCKS:
        return True
    if (not loose and IDENT.match(v)) or any(c in v for c in "()[]{}"):  # 다른 이름을 가리키는 코드 · 타입 표시
        return True
    return False


TAIL_WORD = re.compile(r"(?i)(?:t|s|re|ll|ve|d|m)(?![A-Za-z0-9_])")   # can\'t · it\'s · you\'re · we\'ll · I\'ve · I\'d · I\'m


def cut_label(m, esc, name):
    r"""`\'`가 든 라벨(`'Can\'t be blank'`)에서 `\`까지만 잘린 앞부분인가 — 닫는 따옴표 바로 뒤에 글자가 이어지고(`'`는 줄임말 꼬리 `t`·`s`·`re`…만), 통째로 보면 라벨일 때만 True.
    `\`가 escape가 아닌 말의 값(`"C:\x\"; …` · `'값\'AND name='a b'`)은 False — 잘린 값을 그대로 가린다."""
    v, end = m.group(5), m.end()
    if (len(v) - len(v.rstrip("\\"))) % 2 == 0:
        return False
    if not (TAIL_WORD.match(m.string, end) if m.group(4) == "'" else m.string[end:end + 1].isalnum()):
        return False
    full = esc.match(m.string, m.start())
    return bool(full) and keep_value(full.group(5), name)


def sep_tail(m):
    r"""`'값\', '다음'`처럼 `\` 뒤 따옴표가 사실은 닫는 따옴표인가 — 그 뒤가 구분 글자와 빈칸뿐(`, `)이면 True.
    이때는 다음 따옴표까지 통째로 가리지 않고(줄이 깨진다) 뒤 단계가 `\`까지만 가리게 둔다."""
    v = m.group(5)
    i = v.rfind("\\" + m.group(4))
    tail = v[i + 2:] if i >= 0 else ""
    return any(c.isspace() for c in tail) and not any(c.isalnum() for c in tail)


def mask_params(line, count):
    """주소 칸(`?이름=값` · `#이름=값` · `;password=값`) — 이름이 비밀 낱말로 끝나는 칸의 값만 가린다."""
    heads = list(PARAM.finditer(line))
    out, pos, run = [], 0, 0                               # run: 지금 값 덩어리가 끝나는 자리(덩어리마다 한 번만 잰다)
    for i, h in enumerate(heads):
        name, at = h.group(1), h.end()                     # `;` 꼴이면 이름이 None(낱말 그대로만 받았다)
        if h.start() < pos or (name and not re.sub(r"[^a-z0-9]", "", name.lower()).endswith(ENDS)):
            continue
        code = at + line.startswith("${", at)              # `${이름}`·`${{ … }}`(JS·셸·CI 틀 글)은 `$` 뒤부터 본다
        if line[at:at + 1] in ("=", "}") or PARAM_CODE.match(line, code):
            continue
        if at >= run:
            run = PARAM_RUN.match(line, at).end()
        nxt = heads[i + 1].start() if i + 1 < len(heads) else len(line)
        expr = PARAM_EXPR.match(line, code, nxt)
        if expr and run < expr.end() and line[run] not in "&;":
            continue
        # 둘지 말지는 다음 칸 머리 앞까지만 보고 정한다 — 뒤 칸을 가려도 이 판단이 바뀌지 않는다(두 번 가려도 같다). 가릴 때는 덩어리 끝까지.
        short = line[at:min(run, nxt)]
        if keep_value(short):
            continue
        count[0] += 1
        out += [line[pos:at], MARK]
        pos = run
    return "".join(out) + line[pos:] if out else line


def mask_line(line, count, data=False):
    def quoted(m):
        name, value = m.group(2), m.group(5)
        if (keep_value(value, name) or not (secret_key(name) or long_key(name, value, data, name.upper() == name))
                or cut_label(m, QUOTED_ESC, name)):
            return m.group()
        count[0] += 1
        return m.group(1) + name + m.group(1) + m.group(3) + m.group(4) + MARK + m.group(4)

    def xml_value(m):
        if not secret_key(m.group(2)) or keep_value(m.group(5)):
            return m.group()
        count[0] += 1
        return m.group(1) + m.group(2) + m.group(3) + m.group(4) + MARK + m.group(4)

    def plain(m):
        name, value = m.group(2), m.group(4)
        upper = m.group(3) == "=" and name.upper() == name
        if keep_plain(value, name, data or upper) or not (secret_key(name) or long_key(name, value, data, upper)):
            return m.group()
        count[0] += 1
        return m.group(1) + name + m.group(3) + MARK + m.group(5)

    def xml_text(m):
        if not (secret_key(m.group(2)) or (m.group(3) and secret_key(m.group(3)))) or keep_value(m.group(4)):
            return m.group()
        count[0] += 1
        return m.group(1) + MARK + m.group(5)

    def middle(m):
        if keep_value(m.group(2)):
            return m.group()
        count[0] += 1
        return m.group(1) + MARK + m.group(3)

    def default(m):
        if not secret_key(m.group(3)) or keep_value(m.group(5), m.group(3)) or cut_label(m, DEFAULT_ESC, m.group(3)):
            return m.group()
        callee = CALLEE.search(m.string, max(0, m.start() - 60), m.start())
        if not callee or not any(w.lower() in CALL_WORDS for w in CALL_WORD.findall(callee.group(1))):
            return m.group()                               # raise ValueError("password", "short") 같은 것은 둔다
        count[0] += 1
        return m.group(1) + m.group(4) + MARK + m.group(4)

    out = XML_VALUE.sub(xml_value, line)
    if "\\" in out:                                        # `\"`가 든 값은 먼저 통째로 가린다
        out = DEFAULT_ESC.sub(lambda m: m.group() if sep_tail(m) else default(m), out)
        out = QUOTED_ESC.sub(lambda m: m.group() if sep_tail(m) else quoted(m), out)
    out = DEFAULT.sub(default, out)
    out = QUOTED.sub(quoted, out)
    out = PLAIN.sub(plain, out)
    out = XML_TEXT.sub(xml_text, out)
    out = URL.sub(middle, out)
    out = mask_params(out, count)
    return out


def mask_text(text, keyed=True, data=False, cwd=""):
    """(가린 글, 가린 개수). keyed=False면 이름으로 찾는 가림은 하지 않고 틀림없는 꼴(열쇠 덩어리·알려진 토큰 꼴)만 가린다.

    검색 결과처럼 줄 앞에 `파일:줄:`이 붙은 줄은 그 파일이 시험 파일이면 이름으로 찾는 가림을 건너뛴다."""
    count = [0]

    def shape(m):
        count[0] += 1
        return MARK

    def pem(m):
        body = m.group(2)
        if not any(re.search(r"[0-9]", r) and re.search(r"[A-Z]", r) and re.search(r"[a-z]", r)
                   for r in PEM_RUN.findall(body)):
            return m.group()                               # 머리 줄만 적은 코드·설명 글은 둔다
        count[0] += 1
        n = body.count("\n")                               # 줄 수는 그대로 둔다
        if n >= 2:
            new = "\n" + MARK + "\n" * (n - 1)
        elif n == 1:
            new = "\n" + MARK if body.startswith("\n") else MARK + "\n"
        else:
            new = MARK
        return m.group(1) + new + (m.group(3) or "")

    out = PEM.sub(pem, text)
    out = SHAPES.sub(shape, out)
    if keyed:
        lines = out.split("\n")
        for i, line in enumerate(lines):
            if len(line) > 4000 or not any(c in line for c in "=:<("):
                continue
            f = LINE_FILE.match(line)
            if not f:
                lines[i] = mask_line(line, count, data)
            elif not testish(f.group(1), cwd):             # 앞머리(`파일:줄:`·`파일-줄-`)는 떼고 본다
                lines[i] = f.group() + mask_line(line[f.end():], count, data or bool(DATAISH.search(f.group(1))))
        out = "\n".join(lines)
    return out, count[0]


def keyed_for(tool, tool_input, cwd=""):
    """(이름으로 찾는 가림을 할 것인가, 설정 파일만 읽었는가) — 시험 파일만 읽은 호출이면 앞이 False.
    명령(Bash)은 건너뛰지 않는다 — 명령 글만으로는 무엇을 찍었는지 다 알 수 없다(`cat tests/a.py .env`)."""
    names = []
    if isinstance(tool_input, dict):
        if tool in ("Read", "Edit", "Write"):
            names = [str(tool_input.get("file_path") or "")]
        elif tool == "Grep":
            names = [str(tool_input.get("path") or "")]
        elif tool == "Bash":
            names = FILE_TOKEN.findall(str(tool_input.get("command") or ""))
    names = [n for n in names if n]
    if not names:
        return True, False
    return tool == "Bash" or not all(testish(n, cwd) for n in names), all(DATAISH.search(n) for n in names)


def mask_any(obj, keyed=True, data=False, cwd=""):
    """결과(글·사전·목록)를 같은 꼴로 되돌리되 글만 가린다 — (새 결과, 가린 개수). 재귀 없이.

    그림은 건드리지 않는다: 열쇠 `base64`의 글, `isImage`가 참인 사전의 `stdout`, `data:image/`로 시작하는 글."""
    total = 0
    if isinstance(obj, str):
        return mask_text(obj, keyed, data, cwd)
    if not isinstance(obj, (dict, list)):
        return obj, 0
    root = json.loads(json.dumps(obj))       # 깊은 사본
    stack = [root]
    while stack:
        cur = stack.pop()
        is_dict = isinstance(cur, dict)
        image = is_dict and cur.get("isImage") is True
        for k, v in list(cur.items() if is_dict else enumerate(cur)):
            if isinstance(v, str):
                if (is_dict and (k == "base64" or (image and k == "stdout"))) or v.startswith("data:image/"):
                    continue
                new, n = mask_text(v, keyed, data, cwd)
                if n:
                    cur[k] = new
                    total += n
            elif isinstance(v, (dict, list)):
                stack.append(v)
    return root, total


def _complain(exc):
    """고장을 한 줄로 알린다(ASCII — 값도 줄 내용도 싣지 않는다). 원래 결과가 그대로 간다."""
    try:
        text = "devkit mask: internal error (%s)\n" % type(exc).__name__
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
        if os.path.exists(os.path.join(os.path.expanduser("~"), MARKER)):
            return 0
        cwd = data.get("cwd")
        cwd = cwd if isinstance(cwd, str) else ""
        keyed, dataish = keyed_for(data.get("tool_name"), data.get("tool_input"), cwd)
        new, n = mask_any(data.get("tool_response"), keyed, dataish, cwd)
        if not n:
            return 0
        out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new,
                                      "additionalContext": NOTE % (n, MARK)}}
        sys.stdout.buffer.write((json.dumps(out) + "\n").encode("ascii"))
        sys.stdout.buffer.flush()
        return 0
    except Exception as e:                    # 고장 나면 원래 결과가 그대로 간다
        return _complain(e)


if __name__ == "__main__":
    sys.exit(main())
