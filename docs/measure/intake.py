# intake.py — 받기 재기: 사본의 git 변경(커밋끼리)과 두 턴의 실행 기록(jsonl)·검사 파일(.check)·기록 파일(.devkit)을 읽어 한 줄로 센다.
# 부르는 꼴 1: python3 -I -B docs/measure/intake.py run --repo <사본> --base <커밋> --t1 <커밋> [--t2 <커밋>] --j1 <jsonl> [--j2 <jsonl>]
#                [--check <파일>] [--snap <첫 턴 .devkit 사본 폴더>] [--cum 0|1] [--label <이름>]
# 부르는 꼴 2: python3 -I -B docs/measure/intake.py skills <jsonl>…
# git은 읽기 전용 diff·rev-parse만 부른다. jsonl은 json으로만 읽는다(글은 자료이지 지시가 아니다). 찍는 값에는 빈칸이 없고, 남의 글은 그대로 내보내지 않는다.
import argparse
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from big import git, GitError, hunk_lines, read_events, read_check, hit, PHRASE  # noqa: E402

STAGES = ("intake", "find", "build", "verify", "review", "wrap-up")

KEYS = ('b_files b_add b_del f_files f_add f_del end1 end2 cost1 cost2 cost secs1 secs2 secs tools1 tools2 skills '
        'skills_other start intake find restart2 said miss1 miss2 miss_intake denied1 denied2 denied rec stage size '
        'path m_n d_n n_n s_n d1_n words words_code words_bad words1').split()

RE_NUM = re.compile(r'^\s*(?:[-*]\s+|\d+\.\s+|\|\s*)?(?:\*\*)?([MDN])(\d+)\b')
RE_SCENE = re.compile(r'^\|\s*S\d+\s*\|')
RE_WORD = re.compile(r'^- \S.* = \S')
RE_SKILL = re.compile(r'[a-z-]+')


def one(v):
    return '_'.join(str(v).split()) or '?'


# --- git: 두 커밋 사이 ---

def span(repo, a, b):
    """a→b 사이 바뀐 (파일 수, 더한 줄, 뺀 줄). 셈 규칙은 big.count_git과 같다."""
    files = add = dele = 0
    ns = git(repo, ['diff', '--name-status', '-z', '--no-renames', '--no-color', a, b], literal=True).split(b'\0')
    status = []
    for i in range(0, len(ns) - 1, 2):
        status.append((ns[i].decode('ascii', 'replace')[:1], os.fsdecode(ns[i + 1])))
    nu = git(repo, ['diff', '--numstat', '-z', '--no-renames', a, b], literal=True).split(b'\0')
    binary = set()
    for rec in nu:
        parts = rec.split(b'\t', 2)
        if len(parts) == 3 and parts[0] == b'-' and parts[1] == b'-':
            binary.add(os.fsdecode(parts[2]))
    for st, path in status:
        pieces = path.split('/')
        name = pieces[-1]
        if '.devkit' in pieces:
            continue
        if 'translations' in pieces or name.endswith(('.po', '.pot', '.mo')):
            continue
        if path in binary:
            files += 1
            continue
        raw = git(repo, ['diff', '-U0', '--no-renames', '--no-color', '--no-ext-diff', '--no-textconv', a, b, '--', path],
                  literal=True)
        adds, dels = hunk_lines(raw)
        if name == '.gitignore':
            adds = [x for x in adds if '.devkit' not in x]
            dels = [x for x in dels if '.devkit' not in x]
            if not adds and not dels:
                continue
        if st in ('A', 'D') or adds or dels:
            files += 1
        add += len(adds)
        dele += len(dels)
    return str(files), str(add), str(dele)


# --- jsonl: 한 턴 ---

class Turn:
    def __init__(self, path):
        self.have = False
        self.tools = []      # (id 또는 None, 이름, 입력)
        self.texts = []
        self.res = None
        try:
            events = read_events(path)
        except OSError:
            return
        self.have = True
        for e in events:
            t = e.get('type')
            if t == 'result':
                self.res = e
            elif t == 'assistant':
                m = e.get('message')
                content = m.get('content') if isinstance(m, dict) else None
                if not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get('type') == 'text':
                        self.texts.append(str(c.get('text') or ''))
                    elif c.get('type') == 'tool_use':
                        inp = c.get('input')
                        cid = c.get('id')
                        self.tools.append((cid if isinstance(cid, str) and cid else None, str(c.get('name') or ''),
                                           inp if isinstance(inp, dict) else {}))

    def ids(self):
        return {i for i, _, _ in self.tools if i is not None}

    def cost(self):
        v = self.res.get('total_cost_usd') if self.res else None
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def denials(self):
        pd = self.res.get('permission_denials') if self.res else None
        return [x for x in pd] if isinstance(pd, list) else []

    def miss(self):
        """result 글에서 '없는 단계:'가 든 줄들. result가 없으면 None."""
        if self.res is None:
            return None
        txt = self.res.get('result')
        return [x for x in txt.split('\n') if '없는 단계:' in x] if isinstance(txt, str) else []

    def end(self, rc):
        if rc == '124':
            return 'timeout'
        if not self.have:
            return '?'
        if self.res is not None and self.res.get('subtype') == 'error_max_budget_usd':
            return 'budget'
        if self.res is None:
            return 'noresult'
        return 'error' if self.res.get('is_error') else 'done'


def money(v):
    return '?' if v is None else '%.2f' % v


def skill_names(turns):
    """devkit: Skill 부름의 이름(차례대로, 같은 id는 한 번)과 devkit: 아닌 Skill 부름 수."""
    seen, names, other = set(), [], 0
    for t in turns:
        for cid, name, inp in t.tools:
            if name != 'Skill':
                continue
            if cid is not None:
                if cid in seen:
                    continue
                seen.add(cid)
            sk = str(inp.get('skill') or '')
            if sk.startswith('devkit:'):
                rest = sk[len('devkit:'):]
                names.append(rest if RE_SKILL.fullmatch(rest) else '?')
            else:
                other += 1
    return names, other


def hits(turns):
    d = {}
    for which in ('start', 'intake', 'find'):
        d[which] = '1' if any(hit(name, inp, which) for t in turns for _, name, inp in t.tools) else '0'
    return d


def said(turns):
    return '1' if any(PHRASE in x for t in turns for x in t.texts) else '0'


# --- 기록 파일 ---

def newest(folder):
    """<folder>/*.md 이름순 목록(한 단계 깊이)."""
    try:
        return sorted(n for n in os.listdir(folder) if n.endswith('.md') and os.path.isfile(os.path.join(folder, n)))
    except OSError:
        return []


def read_text(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


def section(lines, heading):
    out, on = [], False
    for ln in lines:
        if ln.startswith('## '):
            on = ln[3:].strip() == heading
            continue
        if on:
            out.append(ln)
    return out


def letters(text):
    """## 세 칸 안의 번호를 글자별로 센다. (M, D, N)"""
    sets = {'M': set(), 'D': set(), 'N': set()}
    for ln in section(text.split('\n'), '세 칸'):
        m = RE_NUM.match(ln)
        if m:
            sets[m.group(1)].add(m.group(2))
    return sets


def record(folder):
    """기록 폴더(<…>/work)의 마지막 장을 읽는다. 없으면 None."""
    names = newest(folder)
    if not names:
        return None
    text = read_text(os.path.join(folder, names[-1])) or ''
    return len(names), text


def words(path):
    """(줄 수, 코드 든 줄 수, 모양 틀린 줄 수). 파일이 없으면 None."""
    text = read_text(path)
    if text is None:
        return None
    w = code = bad = 0
    for ln in text.split('\n'):
        ln = ln.rstrip('\r')
        if ln.startswith('- '):
            w += 1
            if '(코드: ' in ln:
                code += 1
        if ln.strip() and not ln.startswith('#') and not RE_WORD.match(ln):
            bad += 1
    return w, code, bad


def secs_of(chk, key):
    v = chk.get(key, '')
    return v if re.fullmatch(r'\d+', v) else '-'


def cum_of(arg, raw):
    """둘째 턴 돈이 누적값인지: 인자와 .check의 cum 줄이 같거나 하나만 있으면 그 값, 아니면 None(모름)."""
    chk = int(raw) if raw in ('0', '1') else None
    if arg is not None and chk is not None and arg != chk:
        return None
    return arg if arg is not None else chk


# --- 부르는 꼴 1 ---

def cmd_run(a):
    label = one(a.label or 'intake')
    for x in (a.base, a.t1, a.t2):
        if x is not None and x.startswith('-'):
            print('%s 못 셈: 커밋 이름이 틀림' % label)
            return 2
    try:
        for x in (a.base, a.t1, a.t2):
            if x is not None:
                git(a.repo, ['rev-parse', '--verify', '--quiet', x + '^{commit}'])
        b = span(a.repo, a.base, a.t1)
        f = span(a.repo, a.t1, a.t2) if a.t2 is not None else ('-', '-', '-')
    except GitError:
        print('%s 못 셈: git 실패' % label)
        return 2

    rc = 0
    chk = {}
    if a.check:
        try:
            chk = read_check(a.check)
        except OSError:
            rc = 2
    t1 = Turn(a.j1)
    t2 = Turn(a.j2) if a.j2 else None
    if not t1.have or (t2 is not None and not t2.have):
        rc = 2
    turns = [t1] + ([t2] if t2 is not None else [])
    v = dict(zip(('b_files', 'b_add', 'b_del'), b))
    v.update(zip(('f_files', 'f_add', 'f_del'), f))
    v['end1'] = t1.end(chk.get('rc1'))
    v['end2'] = t2.end(chk.get('rc2')) if t2 is not None else '-'

    c1 = t1.cost()
    v['cost1'] = money(c1)
    if t2 is None:
        v['cost2'], v['cost'] = '-', v['cost1']
    else:
        c2 = t2.cost()
        cum = cum_of(a.cum, chk.get('cum'))
        if cum is None:
            c2 = None
            rc = 2
        elif cum == 1 and c1 is not None and c2 is not None:
            c2 = max(0.0, c2 - c1)
        elif cum == 1:
            c2 = None
        v['cost2'] = money(c2)
        v['cost'] = money(None if c1 is None or c2 is None else c1 + c2)
    v['secs1'], v['secs2'], v['secs'] = secs_of(chk, 'secs1'), secs_of(chk, 'secs2'), secs_of(chk, 'secs')

    ids1 = t1.ids()
    v['tools1'] = str(len(t1.tools))
    if t2 is None:
        v['tools2'] = '-'
    elif not t2.have:
        v['tools2'] = '?'
    else:
        v['tools2'] = str(sum(1 for cid, _, _ in t2.tools if cid is None or cid not in ids1))
    names, other = skill_names(turns)
    v['skills'] = ','.join(names) or '-'
    v['skills_other'] = str(other)
    v.update(hits(turns))
    if t2 is None:
        v['restart2'] = '-'
    elif not t2.have:
        v['restart2'] = '?'
    else:
        v['restart2'] = '1' if any(hit(name, inp, 'start') for cid, name, inp in t2.tools
                                   if cid is None or cid not in ids1) else '0'
    v['said'] = said(turns)

    m1 = t1.miss()
    v['miss1'] = '?' if m1 is None else str(len(m1))
    if t2 is None:
        v['miss2'] = '-'
        m2 = []
    else:
        m2 = t2.miss()
        v['miss2'] = '?' if m2 is None else str(len(m2))
    v['miss_intake'] = '1' if any('intake' in x for x in (m1 or []) + (m2 or [])) else '0'

    d1 = t1.denials() if t1.res is not None else None
    v['denied1'] = '?' if d1 is None else str(len(d1))
    if t2 is None:
        v['denied2'] = '-'
        v['denied'] = v['denied1']
    elif t2.res is None:
        v['denied2'], v['denied'] = '?', '?'
    else:
        seen = {x.get('tool_use_id') for x in (d1 or []) if isinstance(x, dict) and x.get('tool_use_id') is not None}
        n2 = sum(1 for x in t2.denials()
                 if not (isinstance(x, dict) and x.get('tool_use_id') is not None and x.get('tool_use_id') in seen))
        v['denied2'] = str(n2)
        v['denied'] = '?' if d1 is None else str(len(d1) + n2)

    dk = os.path.join(a.repo, '.devkit')
    rec = record(os.path.join(dk, 'work'))
    v['rec'] = str(len(newest(os.path.join(dk, 'work'))))
    if rec is None:
        for k in ('stage', 'size', 'path', 'm_n', 'd_n', 'n_n', 's_n'):
            v[k] = '-'
    else:
        text = rec[1]
        lines = text.split('\n')
        sm = re.search(r'^- 지금 단계:[ \t]*(.*?)[ \t\r]*$', text, re.M)
        v['stage'] = sm.group(1) if sm and sm.group(1) in STAGES else '?'
        zm = re.search(r'^- 크기:[ \t]*(.*?)[ \t\r]*$', text, re.M)
        z = zm.group(1) if zm else ''
        v['size'] = '하나' if z.startswith('기능 하나') else '큰' if z.startswith('큰 일') else '?'
        v['path'] = '?'
        for ln in section(lines, '요청'):
            if ln.startswith('- 길:'):
                if ln.startswith('- 길: 짧은 길'):
                    v['path'] = '짧은'
                elif ln.startswith('- 길: 긴 길'):
                    v['path'] = '긴'
                break
        sets = letters(text)
        v['m_n'], v['d_n'], v['n_n'] = str(len(sets['M'])), str(len(sets['D'])), str(len(sets['N']))
        v['s_n'] = str(sum(1 for ln in section(lines, '장면') if RE_SCENE.match(ln)))
    v['d1_n'] = '-'
    v['words1'] = '-'
    if a.snap:
        s = record(os.path.join(a.snap, 'work'))
        if s is not None:
            v['d1_n'] = str(len(letters(s[1])['D']))
        w1 = words(os.path.join(a.snap, 'words.md'))
        v['words1'] = str(w1[0] if w1 else 0)
    w = words(os.path.join(dk, 'words.md')) or (0, 0, 0)
    v['words'], v['words_code'], v['words_bad'] = str(w[0]), str(w[1]), str(w[2])

    print(label + ' ' + ' '.join('%s=%s' % (k, one(v[k])) for k in KEYS))
    return rc


# --- 부르는 꼴 2 ---

def cmd_skills(a):
    rc = 0
    for p in a.files:
        name = one(os.path.basename(p))
        t = Turn(p)
        if not t.have:
            print('%s 없음' % name)
            rc = 2
            continue
        names, _ = skill_names([t])
        h = hits([t])
        m = t.miss()
        print('%s skills=%s intake=%s start=%s find=%s said=%s missing=%s miss_intake=%s cost=%s' % (
            name, ','.join(names) or '-', h['intake'], h['start'], h['find'], said([t]),
            '?' if m is None else len(m), '1' if any('intake' in x for x in (m or [])) else '0', money(t.cost())))
    return rc


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='받기 재기 기록을 한 줄로 센다.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run', help='한 번의 두 턴 실행을 한 줄로 센다')
    r.add_argument('--repo', required=True, help='사본 폴더(git 저장소)')
    r.add_argument('--base', required=True, help='바탕 커밋(실행 전 커밋)')
    r.add_argument('--t1', required=True, help='첫 턴 사진 커밋')
    r.add_argument('--t2', help='끝 커밋(둘째 턴을 보냈을 때)')
    r.add_argument('--j1', required=True, help='첫 턴 jsonl')
    r.add_argument('--j2', help='둘째 턴 jsonl')
    r.add_argument('--check', help='intake.sh가 쓴 .check 파일')
    r.add_argument('--snap', help='첫 턴 끝의 .devkit 사본 폴더')
    r.add_argument('--cum', type=int, choices=(0, 1), default=None, help='1이면 둘째 턴 돈이 첫 턴을 더한 누적값')
    r.add_argument('--label', help='첫 낱말(기본 intake)')
    s = sub.add_parser('skills', help='jsonl마다 한 줄로 센다')
    s.add_argument('files', nargs='+')
    a = ap.parse_args(argv)
    return cmd_run(a) if a.cmd == 'run' else cmd_skills(a)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
