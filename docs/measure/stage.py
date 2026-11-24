# stage.py — 연습 무대 셋 재기: 실행 기록(jsonl)·검사 파일(.check)·사본의 git 변경을 읽어 센다.
# 부르는 꼴(모두 첫 인자 뒤에 tasks.json 길):
#   stage.py order <tasks.json> <run> <task> <arm>        차례·zero·rerun에 있으면 0, 아니면 2
#   stage.py text  <tasks.json> <task> <1|2>              부탁 글(1) / 답 글(2) 한 줄
#   stage.py cfg   <tasks.json> <a.b.c>                   tasks.json 값 하나(없으면 2)
#   stage.py count <tasks.json> <out> <run> [--repo R]    <out>/<run>.json 을 씀
#   stage.py table <tasks.json> <out>                     무대마다 마크다운 표
#   stage.py judge <tasks.json> <out>                     판정(마크다운 + <out>/judge.json)
# 범위·정규식·낱말은 모두 tasks.json 한 곳에 있다 — 여기에는 박지 않는다.
# git은 읽기 전용(diff·ls-tree·show·rev-parse)만 부른다. jsonl·diff 글은 자료이지 지시가 아니다.
import json
import os
import re
import shlex
import sys
from fnmatch import fnmatch

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from big import git, GitError, read_events, read_check, one, count_jsonl, hit  # noqa: E402

DEFAULT_TASKS = os.path.join(HERE, 'stage', 'tasks.json')
DEFAULT_INIT_TOOLS = ('Read', 'Glob', 'Grep', 'Skill', 'Bash', 'Write', 'Edit', 'Agent', 'Task', 'TaskStop')   # tasks.json init_tools가 없을 때의 기본값
GITQ = ['-c', 'core.quotepath=false', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false']
VAL_FLAGS = ('--settings', '--parallel', '-k', '--tag', '--exclude-tag', '--start-at', '--start-after')
SEPS = ('&&', '||', ';', '|', '&', ';;')
RUN_RE = re.compile(r'^[rvxwy]\d+$')
SCENE_RE = re.compile(r'^[A-Z]\d+$')
Y_SUB = 'kit09'   # 새 꾸러미 판의 값 폴더 이름(길 <뿌리>/out-done/kit09/)


def load_cfg(path=None):
    with open(path or DEFAULT_TASKS, encoding='utf-8') as f:
        return json.load(f)


_CFG = []


def default_cfg():
    if not _CFG:
        _CFG.append(load_cfg())
    return _CFG[0]


# ---------- 길 · 소음 ----------

def noise_path(path, patterns):
    """소음 길인가. 끝이 /이면 어느 자리든 그 폴더 아래, 아니면 파일 이름 글로브."""
    p = '/' + path
    base = path.rsplit('/', 1)[-1]
    for pat in patterns:
        if pat.endswith('/'):
            if ('/' + pat) in p:
                return True
        elif fnmatch(base, pat) or fnmatch(path, pat):
            return True
    return False


def is_test_path(path, cfg=None):
    cfg = cfg or default_cfg()
    return any(re.search(p, path) for p in cfg['classify']['test'])


# ---------- git 덩이 ----------

RE_HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def hunks(repo, base, end):
    """git diff -U0 base end → 덩이마다 {path, old_start, old_len, new_start, adds, dels, new_file}."""
    if str(base).startswith('-') or str(end).startswith('-'):
        raise GitError('커밋 이름이 틀림')
    raw = git(repo, GITQ + ['diff', '-U0', '--no-color', '--no-renames', '--no-ext-diff', '--no-textconv',
                            '--src-prefix=a/', '--dst-prefix=b/', base, end], literal=True)
    out = []
    cur = None
    in_hunk = False
    old_path = new_path = None
    new_file = False
    for ln in raw.decode('utf-8', 'replace').split('\n'):
        if not in_hunk or ln.startswith('diff --git '):
            if ln.startswith('diff --git '):
                in_hunk = False
                cur = None
                old_path = new_path = None
                new_file = False
                continue
            if ln.startswith('--- '):
                v = ln[4:].split('\t')[0]
                if v == '/dev/null':
                    new_file = True
                else:
                    old_path = v[2:] if v.startswith('a/') else v
                continue
            if ln.startswith('+++ '):
                v = ln[4:].split('\t')[0]
                new_path = None if v == '/dev/null' else (v[2:] if v.startswith('b/') else v)
                continue
        m = RE_HUNK.match(ln)
        if m:
            in_hunk = True
            cur = {'path': new_path or old_path or '', 'old_start': int(m.group(1)),
                   'old_len': int(m.group(2)) if m.group(2) is not None else 1,
                   'new_start': int(m.group(3)), 'adds': [], 'dels': [], 'new_file': new_file}
            out.append(cur)
            continue
        if cur is None or not in_hunk:
            continue
        if ln.startswith('+'):
            cur['adds'].append(ln[1:])
        elif ln.startswith('-'):
            cur['dels'].append(ln[1:])
    return out


def changed_files(repo, base, end):
    raw = git(repo, GITQ + ['diff', '--name-only', '-z', '--no-renames', base, end], literal=True)
    return [os.fsdecode(x) for x in raw.split(b'\0') if x]


def _overlap(h, ranges):
    lo = h['old_start']
    hi = h['old_start'] + max(h['old_len'], 1) - 1
    return any(lo <= b and a <= hi for a, b in ranges)


def classify(h, scope, cfg=None):
    cfg = cfg or default_cfg()
    if h['new_file']:
        return 'new'
    if is_test_path(h['path'], cfg):
        return 'test'
    if h['path'] in scope and _overlap(h, scope[h['path']]):
        return 'scope'
    if not h['dels']:
        first = next((x for x in h['adds'] if x.strip()), None)
        if first is not None and re.match(cfg['classify']['newdef'], first):
            return 'newdef'
    return 'outside'


def in_place(hs, place):
    return any(h['path'] in place and _overlap(h, place[h['path']]) for h in hs)


# ---------- 후보 줄 ----------

def _added_lines(hs, cfg):
    """(path, 줄 번호, 글, 덩이) — 시험·소음 길 밖의 더한 줄."""
    for h in hs:
        if noise_path(h['path'], cfg['noise']) or is_test_path(h['path'], cfg):
            continue
        for i, t in enumerate(h['adds']):
            yield h['path'], h['new_start'] + i, t, h


def bad_candidates(hs, bad, cfg=None):
    cfg = cfg or default_cfg()
    res = []
    seen = set()
    by_h = {}
    for path, no, text, h in _added_lines(hs, cfg):
        by_h.setdefault(id(h), (h, []))[1].append((path, no, text))
    for h, lines in by_h.values():
        for bid, spec in bad.items():
            if isinstance(spec, str):
                spec = {'re': spec}
            rx = re.compile(spec['re'])
            neg = re.compile(spec['not']) if spec.get('not') else None
            window = spec.get('window')
            hits = [(p, n, t) for p, n, t in lines if rx.search(t)]
            if len(hits) < spec.get('min', 1):
                continue
            for p, n, t in hits:
                if neg:
                    near = [x for x in lines if window is None or abs(x[1] - n) <= window]
                    if any(neg.search(x[2]) for x in near):
                        continue
                if (p, n, bid) not in seen:
                    seen.add((p, n, bid))
                    res.append([p, n, t, bid])
    return res


def helper_candidates(hs, helpers, key_absent=None, cfg=None):
    cfg = cfg or default_cfg()
    lines = list(_added_lines(hs, cfg))
    res = []
    for name, rx in helpers.items():
        if key_absent and name in key_absent and any(name in t for _, _, t, _ in lines):
            continue
        r = re.compile(rx)
        for p, n, t, _ in lines:
            if r.search(t):
                res.append([p, n, t, name])
    return res


def secret_candidates(repo, end, cfg=None):
    cfg = cfg or default_cfg()
    rxs = [re.compile(x) for x in cfg['secret']]
    names = [os.fsdecode(x) for x in git(repo, GITQ + ['ls-tree', '-r', '-z', '--name-only', end], literal=True).split(b'\0') if x]
    res = []
    for path in sorted(names):
        if noise_path(path, cfg['noise']) or is_test_path(path, cfg):
            continue
        try:
            body = git(repo, GITQ + ['show', '%s:%s' % (end, path)], literal=True)
        except GitError:
            continue
        if len(body) > 1000000 or b'\0' in body:
            continue
        for i, t in enumerate(body.decode('utf-8', 'replace').split('\n'), 1):
            if any(r.search(t) for r in rxs):
                res.append([path, i, t.strip()[:200]])
    return res


# ---------- 도구 입력 ----------

def tool_uses(events):
    for e in events:
        if not isinstance(e, dict) or e.get('type') != 'assistant':
            continue
        m = e.get('message')
        c = m.get('content') if isinstance(m, dict) else None
        if not isinstance(c, list):
            continue
        for x in c:
            if isinstance(x, dict) and x.get('type') == 'tool_use':
                inp = x.get('input')
                cid = x.get('id')
                yield (cid if isinstance(cid, str) and cid else None, str(x.get('name') or ''),
                       inp if isinstance(inp, dict) else {})


def tool_results(events):
    out = {}
    for e in events:
        if not isinstance(e, dict) or e.get('type') != 'user':
            continue
        m = e.get('message')
        c = m.get('content') if isinstance(m, dict) else None
        if not isinstance(c, list):
            continue
        for x in c:
            if isinstance(x, dict) and x.get('type') == 'tool_result' and isinstance(x.get('tool_use_id'), str):
                v = x.get('content')
                if isinstance(v, list):
                    v = ' '.join(str(y.get('text') or '') for y in v if isinstance(y, dict))
                out[x['tool_use_id']] = str(v or '')
    return out


def call_texts(name, inp):
    """찾는 글 후보. Read·Glob·Grep은 경로와 무늬를 이어 붙여, Bash는 명령 전체. 그 밖(Write·Edit …)은 안 본다."""
    if name == 'Bash':
        return [str(inp.get('command') or '')]
    if name in ('Read', 'Glob', 'Grep'):
        parts = [str(inp.get(k) or '') for k in ('file_path', 'path', 'pattern', 'glob')]
        return [''.join(parts), '/'.join(p for p in parts if p)]
    return []


def peek_count(events, words, own=''):
    n = 0
    for _, name, inp in tool_uses(events):
        txt = call_texts(name, inp)
        if any(w in t for w in words for t in txt):
            n += 1
    return n


def _home():
    return os.path.normpath(os.environ.get('HOME') or os.path.expanduser('~'))


def _roots(cfg, own, arm):
    """AI가 못 보는 길들(막은 길)과 AI의 사본 자리. 환경 STAGE_S·STAGE_X가 있으면 그 뿌리."""
    S = os.path.normpath(os.environ.get('STAGE_S', cfg['stage']))
    X = os.path.normpath(os.environ.get('STAGE_X', cfg['work']))
    blocked = [S, '/mnt/e/claude_dev']
    if arm == 'q':
        blocked.append(os.path.join(X, 'env', 'kit'))
    return S, X, blocked, os.path.join(X, 'run', own or '-', 'w')


def _inside(p, root):
    return p == root or p.startswith(root.rstrip('/') + '/')


def _claude_projects():
    return os.path.join(_home(), '.claude', 'projects')


def _blocked_path(p, cfg, own, arm):
    """풀어 쓴 절대 길 p가 막은 길의 안이거나 조상이면 참 — 남의 run 폴더와 그 조상(X/run·X·홈·/)도 막는다.
    ~/.claude는 통째로 막지 않는다: projects 자체와 그 조상(훑기)이거나, projects 아래에서 남의 대시 폴더(-zzz-w-run-<남의 own> · -mnt-e-claude-dev)일 때만."""
    S, X, blocked, _ = _roots(cfg, own, arm)
    for b in blocked:
        if _inside(p, b) or _inside(b, p):
            return True
    proj = _claude_projects()
    if _inside(proj, p):
        return True
    if _inside(p, proj):
        return _dash_hit(p, cfg, own)
    runs = os.path.join(X, 'run')
    if _inside(runs, p):                                  # X/run 자신과 그 조상
        return True
    if _inside(p, runs) and p != runs:
        mine = os.path.join(runs, own) if own else None
        if not (mine and _inside(p, mine)):
            return True
    return False


def _resolve(p, cwd):
    if p.startswith('~'):
        p = os.path.expanduser(p)
    return os.path.normpath(p if p.startswith('/') else os.path.join(cwd, p))


def _glob_base(pattern):
    """무늬의 글자 그대로인 앞 길(첫 글롭 글자 앞의 마지막 / 까지). 글롭이 없으면 무늬 전체."""
    m = re.search(r'[*?\[{]', pattern)
    if not m:
        return pattern
    head = pattern[:m.start()]
    return head[:head.rfind('/') + 1]


def _call_paths(name, inp, cwd):
    """Read·Glob·Grep이 건드리는 폴더·파일 길(풀어 쓴 절대 길들)."""
    out = []
    if name == 'Read':
        v = inp.get('file_path')
        if isinstance(v, str) and v:
            out.append(_resolve(v, cwd))
    elif name in ('Glob', 'Grep'):
        base = inp.get('path')
        base = _resolve(base, cwd) if isinstance(base, str) and base else cwd
        out.append(base)
        if name == 'Glob':
            pat = inp.get('pattern')
            if isinstance(pat, str) and pat:
                out.append(_resolve(_glob_base(pat) or '.', base))
    return out


def _cmd_segments(cmd):
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        toks = list(lx)
    except ValueError:
        toks = cmd.split()
    segs, cur = [], []
    for t in toks:
        if t in SEPS or t in ('(', ')', '\n'):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _expand(tok):
    """$HOME · ${HOME} · 앞의 ~ 를 홈으로 푼다."""
    home = _home()
    tok = tok.replace('${HOME}', home)
    tok = re.sub(r'\$HOME(?![A-Za-z0-9_])', lambda m: home, tok)
    if tok == '~' or tok.startswith('~/'):
        tok = home + tok[1:]
    return tok


SHELLS = ('bash', 'sh', 'dash', 'zsh', 'ksh')
PLAIN_WRAP = ('nohup', 'setsid', 'time', 'exec', 'builtin')
XARGS_ARG = ('-n', '-I', '-P', '-L', '-d', '-E', '-s', '-a', '-l')


def _peel(seg, i):
    """앞 껍데기(command · timeout · env · nice · xargs …)를 벗긴 첫 낱말 자리. 실행이 아닌 꼴이면 None."""
    n = len(seg)
    while True:
        while i < n and re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', seg[i]):
            i += 1
        if i >= n:
            return None
        prog = os.path.basename(seg[i])
        if prog == 'command':
            i += 1
            while i < n and seg[i].startswith('-'):
                if seg[i] in ('-v', '-V'):
                    return None
                i += 1
        elif prog == 'timeout':
            i += 1
            while i < n and seg[i].startswith('-'):
                i += 2 if seg[i] in ('-s', '-k', '--signal', '--kill-after') else 1
            i += 1                                                  # 시간
        elif prog == 'env':
            i += 1
            while i < n and (seg[i].startswith('-') or re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', seg[i])):
                i += 2 if seg[i] in ('-u', '-C', '-S', '--unset', '--chdir') else 1
        elif prog == 'nice':
            i += 1
            while i < n and seg[i].startswith('-'):
                i += 2 if seg[i] in ('-n', '--adjustment') else 1
        elif prog == 'xargs':
            i += 1
            while i < n and seg[i].startswith('-'):
                i += 2 if seg[i] in XARGS_ARG else 1
        elif prog in PLAIN_WRAP:
            i += 1
        else:
            return i


def _scan_seg(seg, cfg, cwd, out, depth):
    """한 줄 조각을 보고 훑는 길을 out에 보탠다. cd가 있으면 새 cwd를 돌려준다."""
    scan = cfg.get('peek_scan') or {}
    seg = [_expand(t) for t in seg]
    i = _peel(seg, 0)
    if i is None:
        return cwd
    prog = os.path.basename(seg[i])
    args = seg[i + 1:]
    if prog == 'cd':
        tgt = [a for a in args if a not in ('-L', '-P', '--')]
        return _resolve(tgt[0], cwd) if tgt and tgt[0] != '-' else (_home() if not tgt else cwd)
    if prog in SHELLS:
        for k, a in enumerate(args):
            if a.startswith('-') and not a.startswith('--') and 'c' in a[1:]:
                if k + 1 < len(args) and depth < 4:
                    out.extend(_scan_paths(args[k + 1], cfg, cwd, depth + 1))
                break
        return cwd
    short = ''.join(a[1:] for a in args if a.startswith('-') and not a.startswith('--'))
    longs = [a for a in args if a.startswith('--')]
    if prog == 'ln':
        if 's' in short or '--symbolic' in longs:
            ops = [a for a in args if not a.startswith('-')]
            if ops:
                if len(ops) == 1:
                    base, tg = cwd, ops
                elif len(ops) == 2 and not ops[1].endswith('/'):
                    base, tg = os.path.dirname(_resolve(ops[1], cwd)), ops[:1]
                else:
                    base, tg = _resolve(ops[-1], cwd), ops[:-1]
                out.extend(_resolve(a, base) for a in tg)
        return cwd
    if prog == 'chmod':
        ops = [a for a in args if not a.startswith('-')][1:]            # 첫 낱말은 모드
        for a in ops:
            out.append(_resolve(_glob_base(a) or '.', cwd) if re.search(r'[*?\[{]', a) else _resolve(a, cwd))
        return cwd
    if prog not in scan:
        return cwd
    flags = scan[prog]
    rec = not flags or any((f in longs) if f.startswith('--') else (f in short) for f in flags)
    if not rec:
        return cwd
    if prog == 'find':
        paths = []
        for a in args:
            if a in ('-H', '-L', '-P'):
                continue
            if a.startswith('-') or a in ('!', '('):
                break
            paths.append(a)
        if not paths:
            paths = ['.']
    else:
        pos = [a for a in args if not a.startswith('-')]
        has_pat = any(a in ('-e', '-f', '--regexp', '--file') or a.startswith('--regexp=') or a.startswith('--file=') for a in args)
        paths = pos if (prog == 'ls' or has_pat) else pos[1:]
        if not paths:
            paths = ['.']
    out.extend(_resolve(a, cwd) for a in paths)
    return cwd


def _scan_paths(cmd, cfg, cwd, depth=0):
    """grep -r · find · rg · ls -R 꼴이 훑는 길들과 ln -s의 대상 · chmod의 길(풀어 쓴 절대 길). cd를 따라가고 $HOME·~를 풀고 앞 껍데기를 벗긴다."""
    out = []
    for seg in _cmd_segments(cmd):
        cwd = _scan_seg(seg, cfg, cwd, out, depth)
    return out


def _dash_hit(t, cfg, own):
    """대시꼴 길 이름(claude가 대화 폴더 이름으로 쓰는 꼴)이 든 글인가. -run- 꼴은 자기 사본 것만 빼 준다."""
    for w in cfg.get('peek_dash') or []:
        for m in re.finditer(re.escape(w), t):
            if w.endswith('-run-') and own and t[m.end():].startswith(own):
                continue
            return True
    return False


def _fix_hit(t, cfg, task):
    """고침 해시가 든 글인가: 16진 덩어리(앞뒤가 16진 글자가 아닌 열 글자 이상) 가운데 하나가 고침 해시의 앞부분이면 참."""
    fix = cfg['tasks'].get(task, {}).get('fix')
    if not fix:
        return False
    n = int(cfg.get('fix_len', 10))
    for m in re.finditer(r'(?<![0-9a-fA-F])[0-9a-fA-F]{%d,40}(?![0-9a-fA-F])' % n, t):
        if fix.startswith(m.group(0).lower()):
            return True
    return False


def claude_home(events, own=''):
    """~/.claude 아래를 건드린 도구 호출의 수(무효 아님 — 참고). 길을 풀어 본 것과 글에 ~/.claude · $HOME/.claude가 든 것."""
    home = _home()
    mark = os.path.join(home, '.claude')
    cwd = os.path.join(os.environ.get('STAGE_X', '/'), 'run', own or '-', 'w')
    n = 0
    for _, name, inp in tool_uses(events):
        hit = False
        for t in call_texts(name, inp):
            u = t.replace('${HOME}', home).replace('$HOME', home)
            if mark in u or '~/.claude' in u:
                hit = True
        if not hit:
            paths = _call_paths(name, inp, cwd)
            hit = any(_inside(p, mark) for p in paths)
        if hit:
            n += 1
    return n


def peek_hits(events, cfg, task, arm, own):
    words = list(cfg['peek']) + list(cfg['tasks'].get(task, {}).get('leak', []))
    _, _, _, cwd = _roots(cfg, own, arm)
    n = 0
    for _, name, inp in tool_uses(events):
        txts = call_texts(name, inp)
        hit = any(w in t for w in words for t in txts) or any(_fix_hit(t, cfg, task) for t in txts)
        for t in txts:
            if arm == 'q' and cfg['peek_kit'] in t:
                hit = True
            for m in re.finditer(re.escape(cfg['peek_run']), t):
                if not (own and t[m.end():].startswith(own)):
                    hit = True
            if _dash_hit(t, cfg, own):
                hit = True
        paths = _call_paths(name, inp, cwd)
        if name == 'Bash':
            paths = _scan_paths(str(inp.get('command') or ''), cfg, cwd)
        if any(_blocked_path(p, cfg, own, arm) for p in paths):
            hit = True
        if hit:
            n += 1
    return n


def peek_result(events, cfg, task, own=''):
    """도구 결과 글에 봉한 폴더 아래 길(S/<봉한 이름>/ · S/try-) · 고침 해시(열 글자 이상, 16진 경계) · 대시꼴 길 이름이 든 결과의 수.
    S 자체와 /mnt/e/claude_dev 글자는 세지 않는다(오류 글에 늘 섞여 나온다). 숨긴 시험 이름은 무효가 아니다(testname_result로만)."""
    S = os.path.normpath(os.environ.get('STAGE_S', cfg['stage']))
    words = [S + '/' + n + '/' for n in cfg.get('sealed_dirs', [])] + [S + '/try-']
    return sum(1 for t in tool_results(events).values()
               if any(w in t for w in words) or _fix_hit(t, cfg, task) or _dash_hit(t, cfg, own))


def testname_seen(events, hidden):
    names = [h.split('.')[-1] for h in hidden]
    n = 0
    for _, name, inp in tool_uses(events):
        if any(w in t for w in names for t in call_texts(name, inp)):
            n += 1
    return n


def testname_result(events, hidden):
    """숨긴 시험 이름이 든 도구 결과 글의 수(표시만 — 무효가 아니다)."""
    names = [h.split('.')[-1] for h in hidden]
    return sum(1 for t in tool_results(events).values() if any(w in t for w in names))


def _result_flags(events):
    """tool_use id → 그 tool_result의 is_error가 참인가(짝이 없으면 키가 없다)."""
    out = {}
    for e in events:
        if not isinstance(e, dict) or e.get('type') != 'user':
            continue
        m = e.get('message')
        c = m.get('content') if isinstance(m, dict) else None
        if not isinstance(c, list):
            continue
        for x in c:
            if isinstance(x, dict) and x.get('type') == 'tool_result' and isinstance(x.get('tool_use_id'), str):
                out[x['tool_use_id']] = x.get('is_error') is True
    return out


def net_count(events, pkg_hosts=()):
    net = pkg = 0
    flags = _result_flags(events)
    for cid, name, inp in tool_uses(events):
        if name in ('WebFetch', 'WebSearch'):
            if not flags.get(cid, False):                       # 오류로 끝난 것은 안 센다
                net += 1
            continue
        if name in ('Agent', 'Task'):
            if inp.get('subagent_type') == 'web-fetch':
                net += 1
            continue
        if name != 'Bash':
            continue
        for m in re.finditer(r'https?://([^/\s:\'"?#]+)', str(inp.get('command') or '')):
            host = m.group(1).lower()
            if host in ('localhost', '127.0.0.1'):
                continue
            if any(host == h or host.endswith('.' + h) for h in pkg_hosts):
                pkg += 1
            else:
                net += 1
    return net, pkg


def init_seen(events, allowed):
    """system/init 사건들의 (mcp_servers 항목 수 합, allowed 밖 도구 이름 수 — 두 턴 합집합에서 서로 다른 이름).
    그 필드(list)가 든 init이 하나도 없으면 그 값은 '?'(무효 아님 — 참고). 이름은 담지 않고 수만 센다."""
    mcp, out = 0, set()
    have_mcp = have_tools = False
    for e in events:
        if not isinstance(e, dict) or e.get('type') != 'system' or e.get('subtype') != 'init':
            continue
        m = e.get('mcp_servers')
        if isinstance(m, list):
            have_mcp = True
            mcp += len(m)
        t = e.get('tools')
        if isinstance(t, list):
            have_tools = True
            out.update(str(x) for x in t if str(x) not in allowed)
    return (mcp if have_mcp else '?', len(out) if have_tools else '?')


def outside_used(events, allowed):
    """(allowed 밖 내장 도구 tool_use 수, mcp__ 도구 tool_use 수) — 짝이 되는 tool_result가 있고 is_error가 참이 아닌 것만
    (서브에이전트 안 사건도 센다)."""
    flags = _result_flags(events)
    out = mcp = 0
    for cid, name, _ in tool_uses(events):
        if cid is None or cid not in flags or flags[cid]:
            continue
        if name.startswith('mcp__'):
            mcp += 1
        elif name not in allowed:
            out += 1
    return out, mcp


RISKY_WORDS = ('cc-socks', '.claude/sessions', 'nc -U', 'socat', 'AF_UNIX', 'crontab', 'systemd-run', 'systemctl', 'claude-code')
RISKY_CLAUDE = re.compile(r'(^|[^\w.-])claude([^\w.-]|$)')


def risky_count(events):
    """Bash tool_use 가운데 명령 글에 소켓 길·다른 세션·claude 다시 띄우기·예약 작업 낱말이 하나라도 든 것의 수(무효 아님 — 참고)."""
    n = 0
    for _, name, inp in tool_uses(events):
        if name != 'Bash':
            continue
        cmd = str(inp.get('command') or '')
        if any(w in cmd for w in RISKY_WORDS) or RISKY_CLAUDE.search(cmd):
            n += 1
    return n


def kitleak(events):
    return int(count_jsonl(events)[0]['tools_kit'])


def _split_cmd(cmd):
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return cmd.split()


def _fullrun_cmd(cmd):
    toks = _split_cmd(cmd)
    i = 0
    while i < len(toks):
        if toks[i].endswith('runtests.py'):
            j = i + 1
            mods = False
            while j < len(toks):
                u = toks[j]
                if u in SEPS:
                    break
                if u.isdigit() and j + 1 < len(toks) and toks[j + 1][:1] in '<>':
                    j += 1
                    continue
                if u[:1] in '<>' and not u.isalnum():
                    j += 2
                    continue
                if u in VAL_FLAGS:
                    j += 2
                    continue
                if u.startswith('-'):
                    j += 1
                    continue
                mods = True
                j += 1
            if not mods:
                return True
            i = j
        else:
            i += 1
    return False


def fullrun_ids(events):
    """모듈 이름 없이 runtests.py를 부른 Bash 부름(id는 없을 수 있음)."""
    return [cid for cid, name, inp in tool_uses(events)
            if name == 'Bash' and _fullrun_cmd(str(inp.get('command') or ''))]


def fullrun(events):
    return len(fullrun_ids(events))


# ---------- 돈 · 끝 ----------

def money(v):
    return '-' if v is None else '%.2f' % v


def result_of(events):
    res = None
    for e in events:
        if isinstance(e, dict) and e.get('type') == 'result':
            res = e
    return res


def cost_of(res):
    v = res.get('total_cost_usd') if res else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def end_of(res):
    if res is None:
        return 'noresult'
    st = res.get('subtype')
    if isinstance(st, str) and st:
        return st
    return 'error' if res.get('is_error') else '?'


# ---------- count ----------

def read_turn(path):
    try:
        return read_events(path)
    except OSError:
        return None


def kit_agents_file(repo, end, cfg):
    try:
        body = git(repo, GITQ + ['show', '%s:AGENTS.md' % end]).decode('utf-8', 'replace')
    except GitError:
        return False
    first = next((x for x in body.split('\n') if x.strip()), '')
    return first.strip() == cfg['kit_agents_title']


def link_out(repo, cfg, own='', arm=''):
    """끝 사본 안에서 막은 길(S·/mnt/e/claude_dev·(q) 꾸러미 사본·남의 run 폴더)의 안이거나 그 조상을 가리키는 심볼릭 링크의 수
    (소음 폴더·.git 아래는 안 본다 · 사본 안이나 시스템 길을 가리키면 안 센다). 사본이 없으면 ?."""
    root = os.path.normpath(os.path.abspath(repo))
    if not os.path.isdir(root):
        return '?'
    n = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != '.git']
        for name in list(dns) + list(fns):
            full = os.path.join(dp, name)
            if not os.path.islink(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            if noise_path(rel, cfg['noise']) or noise_path(rel + '/', cfg['noise']):
                continue
            try:
                tg = os.readlink(full)
            except OSError:
                continue
            res = os.path.normpath(tg if os.path.isabs(tg) else os.path.join(dp, tg))
            if _blocked_path(res, cfg, own, arm):
                n += 1
        dns[:] = [d for d in dns if not os.path.islink(os.path.join(dp, d))]
    return n


def count_run(cfg, out, run, repo=None):
    chk = read_check(os.path.join(out, run + '.check'))
    task = chk.get('task', '')
    t = cfg['tasks'].get(task)
    if t is None:
        raise GitError('일감을 모름 %s' % one(task))
    arm = chk.get('arm', '')
    own = chk.get('own', '')
    base = chk.get('base')
    if not base:
        try:
            base = open(os.path.join(out, run + '.base'), encoding='utf-8').read().strip()
        except OSError:
            base = ''
    end = chk.get('end_commit', '')
    if repo is None:
        work = os.environ.get('STAGE_X', cfg['work'])
        stage = os.environ.get('STAGE_S', cfg['stage'])
        repo = os.path.join(work, 'run', own, 'w')
        if not own or not os.path.isdir(repo):
            repo = os.path.join(stage, 'done', run, 'w')
    ev1 = read_turn(os.path.join(out, run + '.t1.jsonl'))
    ev2 = read_turn(os.path.join(out, run + '.t2.jsonl'))
    d = {'run': run, 'task': task, 'arm': arm}
    res1 = result_of(ev1) if ev1 is not None else None
    res2 = result_of(ev2) if ev2 is not None else None
    c1 = cost_of(res1) if ev1 is not None else None
    c2raw = cost_of(res2) if ev2 is not None else None
    cum = chk.get('cum')
    if ev1 is None:
        d['cost1'] = '-'
    else:
        d['cost1'] = money(c1) if c1 is not None else '?'
    if ev2 is None:
        d['cost2'] = '-'
    elif c2raw is None:
        d['cost2'] = '?'
    elif cum == '1':
        d['cost2'] = money(c2raw - c1) if c1 is not None else '?'
    elif cum == '0':
        d['cost2'] = money(c2raw)
    else:
        d['cost2'] = '?'
    try:
        d['cost'] = money(float(d['cost1']) + float(d['cost2'])) if ev2 is not None else d['cost1']
    except ValueError:
        d['cost'] = '?'
    for k in ('secs1', 'secs2', 'secs'):
        d[k] = chk.get(k, '-')
    d['end1'] = end_of(res1) if ev1 is not None else '-'
    d['end2'] = end_of(res2) if ev2 is not None else '-'
    k1 = count_jsonl(ev1)[0] if ev1 is not None else None
    k2 = count_jsonl(ev2)[0] if ev2 is not None else None

    def num(v):
        return int(v) if isinstance(v, str) and v.isdigit() else (v if v is not None else '-')
    d['tools1'] = num(k1['tools']) if k1 else '-'
    d['tools2'] = num(k2['tools']) if k2 else '-'
    d['denied1'] = num(k1['denied']) if k1 else '-'
    d['denied2'] = num(k2['denied']) if k2 else '-'
    d['tools_kit'] = sum(int(k['tools_kit']) for k in (k1, k2) if k)
    allev = (ev1 or []) + (ev2 or [])
    d['peek'] = peek_hits(allev, cfg, task, arm, own)
    d['peek_result'] = peek_result(allev, cfg, task, own)
    d['link_out'] = link_out(repo, cfg, own, arm)
    d['testname_seen'] = testname_seen(allev, t['hidden']) if t.get('hidden') else 0
    d['testname_result'] = testname_result(allev, t['hidden']) if t.get('hidden') else 0
    d['claude_home'] = claude_home(allev, own)
    d['kitleak'] = kitleak(allev) if arm == 'q' else 0
    allowed = tuple(cfg.get('init_tools') or DEFAULT_INIT_TOOLS)
    d['init_mcp'], d['init_tools_out'] = init_seen(allev, allowed)
    d['tools_out_used'], d['mcp_used'] = outside_used(allev, allowed)
    d['risky'] = risky_count(allev)
    hosts = cfg['pkg_hosts'] if t.get('stage') == 'a' else []
    d['net'], d['net_pkg'] = net_count(allev, hosts)
    d['rc1'] = chk.get('rc1', '-')
    d['rc2'] = chk.get('rc2', '-')
    d['rc'] = chk.get('rc', '-')
    d['t2'] = chk.get('t2', '-')
    d['상한못끝냄'] = 1 if ('error_max_budget_usd' in (d['end1'], d['end2']) or '124' in (d['rc1'], d['rc2'])) else 0
    fr = fullrun_ids(allev)
    d['전체시험'] = len(fr)
    results = tool_results(allev)
    slow = any('timed out' in results.get(i, '').lower() for i in fr if i)
    d['전체시험다씀'] = 1 if d['전체시험'] >= 1 and (slow or d['상한못끝냄']) else 0
    fail = None
    try:
        if not base or not end:
            raise GitError('바탕·끝 커밋이 없음')
        agents = kit_agents_file(repo, end, cfg)
        hs = [h for h in hunks(repo, base, end)
              if not noise_path(h['path'], cfg['noise']) and not (agents and h['path'] == 'AGENTS.md')]
        names = [p for p in changed_files(repo, base, end)
                 if not noise_path(p, cfg['noise']) and not (agents and p == 'AGENTS.md')]
        d['files'] = len(names)
        d['add'] = sum(len(h['adds']) for h in hs)
        d['del'] = sum(len(h['dels']) for h in hs)
        scope = t.get('scope')
        d['outside'] = sum(len(h['adds']) + len(h['dels']) for h in hs if classify(h, scope, cfg) == 'outside') if scope else 0
        if t.get('place'):
            right = in_place(hs, t['place'])
            wrong = any(h['path'].startswith('django/') and not is_test_path(h['path'], cfg) and not h['new_file'] for h in hs)
            d['맞는자리'] = 1 if right else 0
            d['엉뚱한자리'] = 1 if (wrong and not right) else 0
        tree = [os.fsdecode(x) for x in git(repo, GITQ + ['ls-tree', '-r', '-z', '--name-only', end], literal=True).split(b'\0') if x]
        d['kitfiles'] = sum(1 for p in tree if noise_path(p, cfg['kitfiles'])) + (1 if agents else 0)
        d['bad_cand'] = bad_candidates(hs, t['bad'], cfg) if t.get('bad') else []
        d['helper_cand'] = helper_candidates(hs, t['helpers'], t.get('helpers_absent'), cfg) if t.get('helpers') else []
        d['secret_cand'] = secret_candidates(repo, end, cfg) if t.get('stage') == 'a' else []
    except GitError as e:
        fail = ' '.join(str(e).split()) or 'git 실패'
        for k in ('files', 'add', 'del', 'outside', 'kitfiles'):
            d.setdefault(k, '?')
        for k in ('bad_cand', 'helper_cand', 'secret_cand'):
            d.setdefault(k, [])
        if t.get('place'):
            d.setdefault('맞는자리', '?')
            d.setdefault('엉뚱한자리', '?')
    with open(os.path.join(out, run + '.json'), 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return d, fail


# ---------- 눈 · 무효 · 종류 ----------

def apply_eye(kinds, eye, key):
    for task, letters in (eye or {}).items():
        for letter, vals in (letters or {}).items():
            run = ((key or {}).get(task) or {}).get(letter)
            if not run or run not in kinds or not isinstance(vals, dict):
                continue
            for k, v in vals.items():
                if k != 'notes':
                    kinds[run][k] = v


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def void_reason(d, chk, task, cfg):
    run = chk.get('run') or d.get('run')
    if run in (cfg.get('void') or {}):
        return cfg['void'][run]
    ex = chk.get('exit', '')
    if ex.isdigit() and int(ex) in cfg['void_exits']:
        return 'exit%d' % int(ex)
    if _int(d.get('peek')) >= 1:
        return 'peek'
    if _int(d.get('peek_result')) >= 1:
        return 'peek_result'
    if _int(d.get('link_out')) >= 1:
        return 'link_out'
    if chk.get('seal_broken') == '1':
        return 'seal_broken'
    if cfg['tasks'].get(task, {}).get('stage') == 'c' and _int(d.get('net')) >= 1:
        return 'net'
    if _int(d.get('mcp_used')) >= 1:
        return 'mcp_used'
    if _int(d.get('tools_out_used')) >= 1:
        return 'tools_out'
    if chk.get('kitsha') == 'changed':
        return 'kitsha'
    return None


def _flag(v):
    if v is True:
        return 1
    if v is False:
        return 0
    if isinstance(v, bool) or v is None:
        return '?'
    return v if isinstance(v, int) else '?'


def machine_kinds(cfg, task, d, walk, hidden):
    t = cfg['tasks'][task]
    stage = t['stage']
    k = {}
    for name in cfg['kinds'].get(stage, []):
        k[name] = '?'
    if not t.get('helpers'):
        k.pop('또만듦', None)
    w = walk or {}
    scenes = {a: v for a, v in w.items() if SCENE_RE.match(a)}
    if walk is not None:
        sc = {a: v for a, v in scenes.items() if not a.startswith('E')}
        if sc and (any(v is False for v in sc.values()) or all(v is not None for v in sc.values())):
            k['장면안됨'] = sum(1 for v in sc.values() if v is False)
        ee = {a: v for a, v in scenes.items() if a.startswith('E')}
        if '있던화면깨짐' in k and ee and (any(v is False for v in ee.values()) or all(v is not None for v in ee.values())):
            k['있던화면깨짐'] = sum(1 for v in ee.values() if v is False)
        for name in ('안켜짐', '시험없음', '시험실패'):
            if name in k and name in w:
                k[name] = _flag(w[name])
    for name in ('엉뚱한자리', '상한못끝냄', '전체시험다씀'):
        if name in k and name in d:
            k[name] = d[name]
    if stage == 'c' and hidden:
        names = [h.split('.')[-1] for h in t.get('hidden', [])]
        hd = hidden.get('hidden')
        if isinstance(hd, dict) and 'ok' in hd:
            hran = hd.get('ran')
            if (isinstance(hran, int) and not isinstance(hran, bool) and hran == 0) or hd.get('rc') == 124:
                k['숨긴시험실패'] = '?'                       # 하나도 안 돌았거나 시간이 다 됐다 — 죽은 실행
            elif hd.get('ok'):
                k['숨긴시험실패'] = 0
            else:
                k['숨긴시험실패'] = 0 if hidden.get('safe_different') else 1
        pa = hidden.get('part_after')
        if isinstance(pa, dict) and 'ok' in pa:
            failed = pa.get('failed')
            ran = pa.get('ran')
            if isinstance(ran, int) and not isinstance(ran, bool) and ran == 0:
                k['부분시험실패'] = '?'                       # 하나도 안 돌았다 — 통과도 실패도 아니다
            elif pa.get('ok'):
                k['부분시험실패'] = 0
            elif isinstance(failed, list) and failed:
                k['부분시험실패'] = 1 if any(str(x).split('.')[-1].split(' ')[0] not in names and
                                            not any(n in str(x) for n in names) for x in failed) else 0
            else:
                k['부분시험실패'] = '?'                       # 끝값이 틀린데 실패한 이름이 없다 — 죽은 실행
    return k


def _jload(path):
    try:
        with open(path, encoding='utf-8') as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def run_names(out):
    try:
        names = os.listdir(out)
    except OSError:
        return []
    runs = sorted({n[:-5] for n in names if n.endswith('.json') and RUN_RE.match(n[:-5])})
    return sorted(runs, key=lambda r: ('rvxwy'.index(r[0]), int(r[1:])))


def load_rows(cfg, out):
    rows, kinds, extra = [], {}, {}
    for run in run_names(out):
        d = _jload(os.path.join(out, run + '.json')) or {}
        task = d.get('task', '')
        if task not in cfg['tasks']:
            continue
        try:
            chk = read_check(os.path.join(out, run + '.check'))
        except OSError:
            chk = {}
        chk.setdefault('run', run)
        walk = _jload(os.path.join(out, run + '.walk.json'))
        hidden = _jload(os.path.join(out, run + '.hidden.json'))
        kinds[run] = machine_kinds(cfg, task, d, walk, hidden)
        reason = void_reason(d, chk, task, cfg)
        extra[run] = {'d': d, 'void_reason': reason, 'safe_different': bool(hidden and hidden.get('safe_different'))}
        rows.append({'run': run, 'task': task, 'arm': d.get('arm', ''), 'void': bool(reason), 'kinds': kinds[run],
                     'marks': {k: d.get(k) for k in ('testname_seen', 'testname_result')}})
    apply_eye(kinds, _jload(os.path.join(out, 'eye.json')), _jload(os.path.join(out, 'eye-key.json')))
    return rows, extra


# ---------- judge ----------

def _broke(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 1


def judge(rows, cfg):
    res = {}
    for task in sorted({r['task'] for r in rows}, key=lambda x: cfg['tasks'].get(x, {}).get('line', 99)):
        t = cfg['tasks'].get(task)
        if t is None or t['stage'] == 'z':
            continue
        names = [n for n in cfg['kinds'].get(t['stage'], []) if n != '또만듦' or t.get('helpers')]
        mine = [r for r in rows if r['task'] == task]
        main = [r for r in mine if r['run'][0] in 'rv']
        okp = [r for r in main if r['arm'] == 'p' and not r['void']]
        okq = [r for r in main if r['arm'] == 'q' and not r['void']]
        out = {'후보': [], '막은것': [], '두번': [], '한번': [], '둘다됨': False, '짝없음': False, '확인못함': [], '근거': {},
               '이름본것': [r['run'] for r in okp + okq if any(_int(v) >= 1 for v in (r.get('marks') or {}).values())]}
        if not okp or not okq:
            out['짝없음'] = True
            res[task] = out
            continue

        def val(rs, n):
            vs = [r['kinds'].get(n) for r in rs if n in r['kinds']]
            if any(_broke(v) for v in vs):
                return max(v for v in vs if _broke(v))
            if vs and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vs):
                return 0
            return '?' if vs else 0
        both = True
        for n in names:
            vp, vq = val(okp, n), val(okq, n)
            if vp == '?' or vq == '?':
                out['확인못함'].append(n)
            if vp == '?' or vq == '?':
                both = False                              # 모르는 값이 있으면 둘다됨이 아니다
            if _broke(vp):
                out['후보'].append(n)
                both = False
            elif _broke(vq):
                out['막은것'].append(n)
                both = False
            if _broke(vq):
                both = False
            out['근거'][n] = {'p': [(r['run'], r['kinds'].get(n)) for r in okp if n in r['kinds']],
                              'q': [(r['run'], r['kinds'].get(n)) for r in okq if n in r['kinds']]}
        out['둘다됨'] = both
        xs = [r for r in mine if r['run'][0] == 'x' and r['arm'] == 'p' and not r['void']]
        if xs and out['후보']:
            for n in out['후보']:
                (out['두번'] if any(_broke(r['kinds'].get(n)) for r in xs) else out['한번']).append(n)
        res[task] = out
    return res


# ---------- table · judge 글 ----------

TABLE_ROWS = ['cost', 'secs', 'end1', 'end2', 'tools1', 'tools2', 'denied1', 'denied2', 'tools_kit', 'files', 'add', 'del',
              'peek', 'testname_seen', 'testname_result', 'claude_home', 'kitleak', 'init_mcp', 'init_tools_out', 'tools_out_used', 'mcp_used',
              'risky', 'kitfiles', 'net', 'net_pkg', 'rc', 't2']


def table_text(cfg, out):
    rows, extra = load_rows(cfg, out)
    lines = []
    for stage in ('a', 'b', 'c'):
        rs = [r for r in rows if cfg['tasks'][r['task']]['stage'] == stage]
        if not rs:
            continue
        lines.append('### 무대 %s' % stage)
        lines.append('')
        lines.append('| 이름 | ' + ' | '.join('%s %s %s' % (r['run'], r['task'], r['arm']) for r in rs) + ' |')
        lines.append('|---|' + '---|' * len(rs))

        def line(name, getter):
            lines.append('| %s | ' % name + ' | '.join(str(getter(r)) for r in rs) + ' |')
        line('무효', lambda r: extra[r['run']]['void_reason'] or '-')
        for n in TABLE_ROWS:
            line(n, lambda r, n=n: extra[r['run']]['d'].get(n, '?'))
        if stage == 'b':
            line('outside', lambda r: extra[r['run']]['d'].get('outside', '?'))
        if stage == 'c':
            line('맞는자리', lambda r: extra[r['run']]['d'].get('맞는자리', '?'))
            line('전체시험', lambda r: extra[r['run']]['d'].get('전체시험', '?'))
            line('안전하나꼴다름', lambda r: 1 if extra[r['run']]['safe_different'] else 0)
        names = []
        for r in rs:
            for n in r['kinds']:
                if n in cfg['kinds'][stage] and n not in names:
                    names.append(n)
        for n in [x for x in cfg['kinds'][stage] if x in names]:
            line(n, lambda r, n=n: r['kinds'].get(n, '-'))
        lines.append('')
    return '\n'.join(lines) + ('\n' if lines else '')


def judge_text(cfg, j):
    lines = []
    for task, v in j.items():
        lines.append('## %s' % task)
        if v['짝없음']:
            lines.append('- 짝없음: 한 팔이 무효이거나 없다 — 후보·막은 것 판정 안 함')
            if v.get('이름본것'):
                lines.append('- 이름본것(숨긴 시험 이름이 부탁·결과에 나옴 — 무효 아님, 참고): %s' % ', '.join(v['이름본것']))
            lines.append('')
            continue
        lines.append('- 후보: %s' % (', '.join(v['후보']) or '없음'))
        lines.append('- 막은것: %s' % (', '.join(v['막은것']) or '없음'))
        if v['두번'] or v['한번']:
            lines.append('- 두번: %s' % (', '.join(v['두번']) or '없음'))
            lines.append('- 한번: %s' % (', '.join(v['한번']) or '없음'))
        lines.append('- 둘다됨: %s' % ('예' if v['둘다됨'] else '아니오'))
        if v['확인못함']:
            lines.append('- 확인못함: %s' % ', '.join(v['확인못함']))
        if v.get('이름본것'):
            lines.append('- 이름본것(숨긴 시험 이름이 부탁·결과에 나옴 — 무효 아님, 참고): %s' % ', '.join(v['이름본것']))
        for n in v['후보'] + v['막은것']:
            g = v['근거'].get(n, {})
            lines.append('  - 근거 %s: p=%s q=%s' % (n, g.get('p'), g.get('q')))
        lines.append('')
    return '\n'.join(lines) + ('\n' if lines else '')


# ---------- after (귀띔 뒤에 한 일) ----------

HOOK_Y = {'type': 'system', 'start': 'hook_started', 'response': 'hook_response', 'event_key': 'hook_event',
          'event': 'Stop', 'out_keys': ['stdout', 'output'], 'decision': 'block'}
AFTER_WHAT = {'Bash': 'command', 'Edit': 'file_path', 'Write': 'file_path', 'NotebookEdit': 'notebook_path',
              'Read': 'file_path', 'Skill': 'skill'}


def hook_cfg(cfg):
    h = dict(HOOK_Y)
    extra = cfg.get('hook_y') if isinstance(cfg, dict) else None
    if isinstance(extra, dict):
        h.update(extra)
    return h


def y_dir_ok(out):
    return os.path.basename(os.path.normpath(str(out))) == Y_SUB


def _is_block(e, h):
    for k in h['out_keys']:
        v = e.get(k)
        if not isinstance(v, str):
            continue
        try:
            d = json.loads(v.strip())
        except ValueError:
            continue
        if isinstance(d, dict) and d.get('decision') == h['decision']:
            return True
    return False


def _reply_text(events):
    r = result_of(events)
    v = r.get('result') if r else None
    return v if isinstance(v, str) else ''


def after_of(cfg, ev1, ev2):
    h = hook_cfg(cfg)
    started = responses = inter = 0
    seen, tools, after = {}, [], []
    n = 0
    for turn, events in (('t1', ev1), ('t2', ev2)):
        cur = None
        for e in events:
            if not isinstance(e, dict):
                continue
            if e.get('type') == h['type'] and e.get('subtype') in (h['start'], h['response']):
                key = '%s:%s' % (e.get('subtype'), e.get(h['event_key']))
                seen[key] = seen.get(key, 0) + 1
                if e.get(h['event_key']) == h['event']:
                    if e.get('subtype') == h['start']:
                        started += 1
                    else:
                        responses += 1
                        if _is_block(e, h):
                            inter += 1
                            cur = {'turn': turn, 'after_n': n, 'next': []}
                            after.append(cur)
                continue
            for _id, name, inp in tool_uses([e]):
                n += 1
                w = inp.get(AFTER_WHAT.get(name, ''), '')
                t = {'n': n, 'turn': turn, 'name': name, 'what': w if isinstance(w, str) else ''}
                if e.get('parent_tool_use_id'):
                    t['sub'] = True                      # 딸린 에이전트가 쓴 도구(훅 빠짐 정의는 그대로 · 읽는 사람이 가리라고 표시만)
                tools.append(t)
                if cur is not None:
                    cur['next'].append(n)
    check_read = any(hit(t_name, t_inp, 'check')
                     for events in (ev1, ev2) for _i, t_name, t_inp in tool_uses(events))
    line = {t: '끝내기 전 점검:' in _reply_text(ev) for t, ev in (('t1', ev1), ('t2', ev2))}
    missing = sum(1 for ev in (ev1, ev2) if '없는 단계' in _reply_text(ev))
    return {'run': '', 'hook': {'started': started, 'responses': responses, 'interjections': inter},
            'events_seen': seen, 'check_read': check_read, 'check_line': line, 'missing_stage': missing,
            'tools': tools, 'after': after}


def cmd_after(cfg, out, run):
    if not y_dir_ok(out):
        print('%s 폴더에만 씀' % Y_SUB)
        return 2
    if not RUN_RE.match(run) or '\n' in run:
        print('실행 이름이 틀림')
        return 2
    ev1 = read_turn(os.path.join(out, run + '.t1.jsonl'))
    if ev1 is None:
        print('기록 없음')
        return 2
    ev2 = read_turn(os.path.join(out, run + '.t2.jsonl')) or []
    a = after_of(cfg, ev1, ev2)
    a['run'] = run
    with open(os.path.join(out, run + '.after.json'), 'w', encoding='utf-8') as f:
        json.dump(a, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('%s 끼어듦=%d 시작=%d 점검읽음=%d 점검줄=%d/%d 없는단계=%d 도구=%d'
          % (run, a['hook']['interjections'], a['hook']['started'], int(a['check_read']),
             int(a['check_line']['t1']), int(a['check_line']['t2']), a['missing_stage'], len(a['tools'])))
    return 0


# ---------- compare (앞·뒤 견주기와 판정) ----------

Y_OLD = {'T1': [3, 3], 'T2': [1, 2], 'T3': [4, 4], 'T4': [False, False]}      # 앞(옛 꾸러미) 두 번의 값
Y_LINE = {'T1': 2, 'T2': 0, 'T3': 3}                                           # 나아짐 선: 새 값 <= 선
G1_MAX = {'관계없는줄': 2, '나쁜베낌': 1}
Y_T = {'T1': ('a1', '덧붙임'), 'T2': ('a2', '덧붙임'), 'T3': ('b2', '장면안됨'), 'T4': ('a1', None)}
Y_H = {'H1': ('a3', '덧붙임'), 'H2': ('b3', '장면안됨'), 'H3': ('a3', None)}
ROUND_Y_RUN = re.compile(r'^[wy]\d{2}$')
EDIT_TOOLS = ('Edit', 'Write', 'NotebookEdit')


def _num(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _fnum(v):
    try:
        return float(v) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else None
    except ValueError:
        return None


def _tbl(old, new, result):
    return {'old': old, 'new': new, 'result': result}


def _three(ok):
    return '나아짐' if all(ok) else ('흔들림' if any(ok) else '안나아짐')


def _run_key(r):
    return ('rvxwy'.index(r[0]), int(r[1:]))


def _round_y(cfg):
    rr = cfg.get('round_y')
    if not isinstance(rr, list) or not rr:
        raise ValueError('round_y가 없음')
    rows = {}
    for r in rr:
        if not (isinstance(r, (list, tuple)) and len(r) in (3, 4) and all(isinstance(x, str) for x in r) and ROUND_Y_RUN.match(r[0])):
            raise ValueError('round_y가 틀림')
        rows[r[0]] = list(r)
    redo = cfg.get('redo_y') or {}
    if not isinstance(redo, dict):
        raise ValueError('redo_y가 틀림')
    for old, new in redo.items():
        if (old not in rows or new not in rows or old == new or new in redo
                or rows[old][1] != rows[new][1] or rows[old][2] != rows[new][2]):
            raise ValueError('redo_y가 틀림')
    return rows, redo


def _scene_ok(walk, scene):
    v = walk.get(scene) if isinstance(walk, dict) and isinstance(scene, str) else None
    return v if isinstance(v, bool) else None


def _under_devkit(path):
    return '.devkit' in str(path).split('/')


def compare(cfg, out):
    rows_y, redo = _round_y(cfg)
    used = sorted((r for r in rows_y if rows_y[r][1] != 'z0' and r not in redo), key=_run_key)
    rows, extra = load_rows(cfg, out)
    kinds = {r['run']: r['kinds'] for r in rows}
    yb = cfg.get('y_before') if isinstance(cfg.get('y_before'), dict) else {}
    ran = _jload(os.path.join(out, 'ran.json')) or {}
    walks, afters, chks = {}, {}, {}
    for r in set(used) | set(redo):
        walks[r] = _jload(os.path.join(out, r + '.walk.json'))
        afters[r] = _jload(os.path.join(out, r + '.after.json'))
        try:
            chks[r] = read_check(os.path.join(out, r + '.check'))
        except OSError:
            chks[r] = None

    def by(letter, task):
        return [r for r in used if r[0] == letter and rows_y[r][1] == task]

    def vals(runs, kind):
        return [kinds.get(r, {}).get(kind) for r in runs]

    def ranv(r):
        v = ran.get(r)
        v = v.get('켜봄') if isinstance(v, dict) else None
        return v if isinstance(v, bool) else None

    eye = _jload(os.path.join(out, 'eye.json')) or {}
    eye_key = _jload(os.path.join(out, 'eye-key.json')) or {}

    def eye_below(task, kind, ok):                      # 섞어 넣은 앞 실행(round_y 밖)을 눈이 이번에 선 아래로 셌는가 · 견줄 것이 없으면 None
        km, em = eye_key.get(task), eye.get(task)
        km, em = km if isinstance(km, dict) else {}, em if isinstance(em, dict) else {}
        seen = False
        for letter, run in km.items():
            if run in rows_y:
                continue
            e = em.get(letter)
            v = _num(e.get(kind)) if isinstance(e, dict) else None
            if v is None:
                continue
            seen = True
            if ok(v):
                return True
        return False if seen else None

    c = {}
    for name in ('T1', 'T2', 'T3'):
        task, kind = Y_T[name]
        runs = by('y', task)
        new = vals(runs, kind)
        if len(runs) != 2 or any(_num(v) is None for v in new):
            c[name] = _tbl(Y_OLD[name], new, '모름')
            continue
        line = Y_LINE[name]
        ok = [v <= line for v in new]
        if name == 'T3':
            sc = [_scene_ok(walks[r], yb.get('t3_scene')) for r in runs]
            if any(s is None for s in sc):
                c[name] = _tbl(Y_OLD[name], new, '모름')
                continue
            ok = [o and s for o, s in zip(ok, sc)]
        res = _three(ok)
        if name in ('T1', 'T2'):
            below = eye_below(task, kind, lambda v, line=line: v <= line)
            if below:
                res = '안나아짐(눈)'
            elif below is None and res != '안나아짐':
                res = '모름'                              # 보호 장치를 못 봤으면 나아짐으로 치지 않는다
        c[name] = _tbl(Y_OLD[name], new, res)
    runs = by('y', Y_T['T4'][0])
    new = [ranv(r) for r in runs]
    c['T4'] = _tbl(Y_OLD['T4'], new, '모름' if len(runs) != 2 or any(v is None for v in new) else _three([v is True for v in new]))
    yall = [r for r in used if r[0] == 'y']
    ms = [(afters[r] or {}).get('missing_stage') for r in yall]
    if not yall or any(_num(v) is None for v in ms):
        c['T5'] = _tbl([], ms, '모름')
    else:
        c['T5'] = _tbl([], ms, '통과' if all(v == 0 for v in ms) else '실패')
    for name in ('H1', 'H2'):
        task, kind = Y_H[name]
        yr, wr = by('y', task), by('w', task)
        new, old = vals(yr, kind), vals(wr, kind)
        sc = [_scene_ok(walks[r], yb.get('h2_scene')) for r in yr] if name == 'H2' else [True] * len(yr)
        if len(yr) != 2 or len(wr) != 2 or any(_num(v) is None for v in new + old) or any(s is None for s in sc):
            c[name] = _tbl(old, new, '모름')
        elif all(v == 0 for v in old):
            c[name] = _tbl(old, new, '뺌')
        elif sum(new) < sum(old) and max(new) <= max(old) and all(sc):
            c[name] = _tbl(old, new, '나아짐')
        elif sum(new) > sum(old):
            c[name] = _tbl(old, new, '나빠짐')
        else:
            c[name] = _tbl(old, new, '그대로')
    yr, wr = by('y', Y_H['H3'][0]), by('w', Y_H['H3'][0])
    new, old = [ranv(r) for r in yr], [ranv(r) for r in wr]
    if len(yr) != 2 or len(wr) != 2 or any(v is None for v in new + old):
        c['H3'] = _tbl(old, new, '모름')
    elif all(old):
        c['H3'] = _tbl(old, new, '뺌')
    else:
        c['H3'] = _tbl(old, new, '나아짐' if all(new) else '안나아짐')
    # G1
    helpers = bool((cfg['tasks'].get('b1') or {}).get('helpers'))
    bn = [n for n in cfg['kinds'].get('b', []) if n != '또만듦' or helpers]
    runs = by('y', 'b1')
    new = [{n: kinds.get(r, {}).get(n) for n in bn} for r in runs]
    if len(runs) != 2 or any(_num(v) is None for d in new for v in d.values()):
        c['G1'] = _tbl([], new, '모름')
    else:
        c['G1'] = _tbl([], new, '통과' if all(v <= G1_MAX.get(n, 0) for d in new for n, v in d.items()) else '실패')
    # G2
    new = {n: c[n]['new'] for n in ('T1', 'T2', 'T3')}
    old = {n: max(Y_OLD[n]) for n in new}
    if any(len(v) != 2 or any(_num(x) is None for x in v) for v in new.values()):
        c['G2'] = _tbl(old, new, '모름')
    else:
        c['G2'] = _tbl(old, new, '통과' if all(x <= old[n] for n, v in new.items() for x in v) else '실패')
    # G3
    exits = [str(x) for x in (cfg.get('g3_exits_y') or ['0'])]
    bad = []
    for r in used:
        chk = chks[r] or {}
        if r not in extra:
            bad.append('%s:행없음' % r)
        elif extra[r]['void_reason']:
            bad.append('%s:무효 %s' % (r, extra[r]['void_reason']))
        elif chk.get('exit') not in exits:
            bad.append('%s:끝 값 %s' % (r, chk.get('exit')))
        elif chk.get('t2') != 'sent':
            bad.append('%s:t2 %s' % (r, chk.get('t2')))
    c['G3'] = _tbl(exits, bad, '실패' if bad else '통과')
    # G4
    g4 = yb.get('g4') if isinstance(yb.get('g4'), dict) else {}
    new, lim = [], {}
    unknown = False
    fail = False
    for task in ('c1', 'c2'):
        runs = by('y', task)
        lim[task] = dict(g4.get(task) or {})
        has = bool((cfg['tasks'].get(task) or {}).get('helpers'))
        cn = [n for n in cfg['kinds'].get('c', []) if n != '또만듦' or has]
        if not runs:
            unknown = True
        for r in runs:
            d = {n: kinds.get(r, {}).get(n) for n in cn}
            new.append({'run': r, 'values': d})
            for n, v in d.items():
                if _num(v) is None:
                    unknown = True
                elif v > (_num(lim[task].get(n)) or 0):
                    fail = True
    c['G4'] = _tbl(lim, new, '모름' if unknown else ('실패' if fail else '통과'))
    # 훅 빠짐
    none = []
    for r in yall:
        a = afters[r]
        if not isinstance(a, dict) or (a.get('hook') or {}).get('interjections') != 0:
            continue
        cl = a.get('check_line') if isinstance(a.get('check_line'), dict) else {}
        tl = a.get('tools') if isinstance(a.get('tools'), list) else []
        if any(any(isinstance(t, dict) and t.get('turn') == turn and t.get('name') in EDIT_TOOLS
                   and not _under_devkit(t.get('what', '')) for t in tl) and cl.get(turn) is False
               for turn in ('t1', 't2')):
            none.append(r)
    c['hook_none'] = none
    # 돈 · 곁 표
    cost = {r: _fnum(extra[r]['d'].get('cost')) for r in used if r in extra}

    def expect(r):
        task = rows_y[r][1]
        if task in ('a3', 'b3'):
            ws = [cost.get(w) for w in by('w', task)]
            return sum(ws) / len(ws) if ws and all(v is not None for v in ws) else None
        return _fnum((yb.get('cost') or {}).get(task)) if isinstance(yb.get('cost'), dict) else None
    exp = {r: expect(r) for r in used}
    notes = []
    ratio = None
    if yall and all(cost.get(r) is not None and exp[r] for r in yall):
        ratio = sum(cost[r] for r in yall) / sum(exp[r] for r in yall)
        if ratio > 2:
            notes.append('가볍게 하기')
    elif yall:
        notes.append('돈을 못 견줌(값이 빠짐)')
    c['cost_ratio'] = ratio
    side = []
    for r in used:
        a = afters[r] if isinstance(afters[r], dict) else None
        chk = chks[r] or {}
        task = rows_y[r][1]
        x = cost.get(r) / exp[r] if cost.get(r) is not None and exp[r] else None
        rv = ran.get(r)
        side.append({'run': r, 'task': task, 'kit': 'old' if r[0] == 'w' else 'new', 'exit': chk.get('exit'),
                     'left': chk.get('exit') == '11', 't2': chk.get('t2'),
                     'interjections': (a.get('hook') or {}).get('interjections') if a else None,
                     'check_read': a.get('check_read') if a else None, 'check_line': a.get('check_line') if a else None,
                     'cost': cost.get(r), 'secs': chk.get('secs'), 'cost_x': x,
                     'ran': rv.get('켜봄') if isinstance(rv, dict) else None,
                     '나쁜베낌': kinds.get(r, {}).get('나쁜베낌') if (cfg['tasks'].get(task) or {}).get('stage') == 'b' else None})
    c['side'] = side
    c['replaced'] = [{'old': o, 'new': redo[o], 'exit': (chks[o] or {}).get('exit')} for o in sorted(redo, key=_run_key)]
    c['left_runs'] = [r for r in used if (chks[r] or {}).get('exit') == '11']
    # 판정
    tn = sum(1 for n in ('T1', 'T2', 'T3', 'T4') if c[n]['result'] == '나아짐')
    hn = sum(1 for n in ('H1', 'H2', 'H3') if c[n]['result'] == '나아짐')
    worse = any(c[n]['result'] == '나빠짐' for n in ('H1', 'H2'))
    g_ok = all(c[n]['result'] == '통과' for n in ('G1', 'G2', 'G3', 'G4'))
    if c['G3']['result'] == '실패':
        j = '미룸(G3)'
    elif len(none) >= 4:
        j = '미룸(훅)'
    elif any(c[n]['result'] == '모름' for n in ('T1', 'T2', 'T3', 'T4', 'T5', 'H1', 'H2', 'H3', 'G1', 'G2', 'G4')):
        j = '미룸(모름)'
    elif tn == 0 or c['G1']['result'] == '실패' or c['G4']['result'] == '실패' or worse:
        j = '뺀다'
    elif c['H1']['result'] == '뺌' and c['H2']['result'] == '뺌':
        j = '그 사이'
        notes.append('처음 보는 일감으로는 가리지 못했다')
    elif tn >= 2 and hn == 0:
        j = '이 무대에만'
    elif tn >= 2 and hn >= 1 and g_ok:
        j = '남긴다'
    else:
        j = '그 사이'
    c['judgment'] = j
    c['d1'] = '남긴다' if c['T5']['result'] == '통과' else '판정을 따른다'
    c['notes'] = notes
    return c


def compare_text(c):
    lines = ['## 견주기']
    for n in ('T1', 'T2', 'T3', 'T4', 'T5', 'H1', 'H2', 'H3', 'G1', 'G2', 'G3', 'G4'):
        t = c[n]
        lines.append('- %s 앞=%s 뒤=%s → %s' % (n, json.dumps(t['old'], ensure_ascii=False), json.dumps(t['new'], ensure_ascii=False), t['result']))
    lines.append('- 훅 빠짐: %s' % (', '.join(c['hook_none']) or '없음'))
    lines.append('- 끝 값 11로 끝난 실행: %s' % (', '.join(c['left_runs']) or '없음'))
    if c['replaced']:
        lines.append('- 대신 돈 실행: %s' % ', '.join('%s → %s(끝 값 %s)' % (r['old'], r['new'], r['exit']) for r in c['replaced']))
    lines.append('- 돈: %s' % ('모름' if c['cost_ratio'] is None else '앞 기대의 %.2f배' % c['cost_ratio']))
    lines.append('- 판정: %s' % c['judgment'])
    lines.append('- d1: %s' % c['d1'])
    for n in c['notes']:
        lines.append('- 덧붙임: %s' % n)
    lines.append('')
    lines.append('### 곁 표')
    lines.append('')
    cols = ('run', 'task', 'kit', 'exit', 'left', 't2', 'interjections', 'check_read', 'check_line', 'cost', 'secs', 'cost_x', 'ran', '나쁜베낌')
    lines.append('| ' + ' | '.join(cols) + ' |')
    lines.append('|' + '---|' * len(cols))
    for s in c['side']:
        lines.append('| ' + ' | '.join(json.dumps(s[k], ensure_ascii=False) if isinstance(s[k], (dict, float)) else str(s[k]) for k in cols) + ' |')
    return '\n'.join(lines) + '\n'


def cmd_compare(cfg, out):
    if not y_dir_ok(out):
        print('%s 폴더에만 씀' % Y_SUB)
        return 2
    try:
        c = compare(cfg, out)
    except ValueError as e:
        print('「%s」' % one(str(e)))
        return 2
    with open(os.path.join(out, 'compare.json'), 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
        f.write('\n')
    sys.stdout.write(compare_text(c))
    return 0


# ---------- order · text · cfg ----------

def cmd_order(cfg, run, task, arm):
    for r in cfg['order']:
        if list(r) == [run, task, arm]:
            return 0
    for r in cfg['zero']:
        if list(r[:3]) == [run, task, arm]:
            return 0
    for r in cfg['rerun']:
        if list(r[:3]) == [run, task, arm]:
            return 0
    for r in cfg.get('round_y', []):
        if list(r[:3]) == [run, task, arm]:
            return 0
    print('차례에 없는 짝: %s %s %s' % (one(run), one(task), one(arm)))
    return 2


def cmd_text(path, cfg, task, turn):
    t = cfg['tasks'].get(task)
    if t is None or turn not in ('1', '2'):
        print('일감이나 턴이 틀림')
        return 2
    name = 'stage-prompts.txt' if turn == '1' else 'stage-replies.txt'
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), name)
    try:
        lines = open(f, encoding='utf-8').read().split('\n')
    except OSError:
        print('글 파일이 없음')
        return 2
    n = t['line']
    if n < 1 or n > len(lines) or not lines[n - 1].strip():
        print('그 줄이 비었음')
        return 2
    print(lines[n - 1])
    return 0


def cmd_cfg(cfg, dotted):
    v = cfg
    for part in dotted.split('.'):
        if not isinstance(v, dict) or part not in v:
            print('열쇠가 없음')
            return 2
        v = v[part]
    print(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    if len(argv) < 2:
        print('쓰는 법: stage.py order|text|cfg|count|table|judge|after|compare <tasks.json> …')
        return 2
    cmd, tpath, rest = argv[0], argv[1], argv[2:]
    try:
        cfg = load_cfg(tpath)
    except (OSError, ValueError):
        print('tasks.json을 못 읽음')
        return 2
    if cmd == 'order' and len(rest) == 3:
        return cmd_order(cfg, *rest)
    if cmd == 'text' and len(rest) == 2:
        return cmd_text(tpath, cfg, *rest)
    if cmd == 'cfg' and len(rest) == 1:
        return cmd_cfg(cfg, rest[0])
    if cmd == 'count' and len(rest) in (2, 4):
        repo = None
        if len(rest) == 4:
            if rest[2] != '--repo':
                print('인자가 틀림')
                return 2
            repo = rest[3]
        try:
            d, fail = count_run(cfg, rest[0], rest[1], repo)
        except (OSError, GitError) as e:
            print('%s 못 셈: %s' % (one(rest[1]), one(str(e))))
            return 2
        print('%s task=%s arm=%s files=%s add=%s del=%s peek=%s init_mcp=%s init_tools_out=%s tools_out_used=%s mcp_used=%s risky=%s'
              % (one(d['run']), one(d['task']), one(d['arm']), d['files'], d['add'], d['del'], d['peek'],
                 d['init_mcp'], d['init_tools_out'], d['tools_out_used'], d['mcp_used'], d['risky']))
        if fail:
            print('git 못 셈: %s' % fail)
            return 2
        return 0
    if cmd == 'after' and len(rest) == 2:
        return cmd_after(cfg, *rest)
    if cmd == 'compare' and len(rest) == 1:
        return cmd_compare(cfg, rest[0])
    if cmd == 'table' and len(rest) == 1:
        sys.stdout.write(table_text(cfg, rest[0]))
        return 0
    if cmd == 'judge' and len(rest) == 1:
        rows, _ = load_rows(cfg, rest[0])
        j = judge(rows, cfg)
        with open(os.path.join(rest[0], 'judge.json'), 'w', encoding='utf-8') as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
            f.write('\n')
        sys.stdout.write(judge_text(cfg, j))
        return 0
    print('인자가 틀림')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
