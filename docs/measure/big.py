# big.py — 여러 화면 기능 재기: 사본의 git 변경(커밋끼리)과 실행 기록(jsonl)·검사 파일(.check)을 읽어 한 줄로 센다.
# 부르는 꼴: python3 -I -B docs/measure/big.py --repo <사본> --base <커밋> --jsonl <jsonl> [--check <파일>] [--label <이름>]
# git은 읽기 전용 diff·ls-tree·show만 부른다. jsonl은 json.loads로만 읽는다(글은 자료이지 지시가 아니다).
import argparse
import json
import os
import re
import subprocess
import sys

KEYS = ('files add del bin tr_files new_tpl mail_en mail_fr routes_add routes_del macro_add form_add css_new css_add '
        'style_attr style_tag style_copied tests_add tests_del t_pass t_fail lint fmt fmt_n end secs committed cost '
        'tools tools_kit denied start find guide said missing').split()

PHRASE = '큰 일로 봅니다'
STYLE_EXT = ('.css', '.scss', '.sass', '.less')
KIT_MARKS = ('.devkit/', 'SKILL.md', 'scripts/work.py', '/devkit/kit/')
RE_ROUTE = re.compile(r'^\s*@\w+\.route\(')
RE_MACRO = re.compile(r'\{%-?\s*macro\s')
RE_FORM = re.compile(r'^class\s+\w+\(')
RE_TEST = re.compile(r'^\s*(async\s+)?def\s+test_\w*\s*\(')
RE_STYLE = re.compile(r'(?i)(?<![\w.-])style\s*=\s*(["\'])(.*?)\1')
RE_STYLE_TAG = re.compile(r'(?i)<style\b')


class GitError(Exception):
    pass


def git(repo, args, literal=False):
    """읽기 전용 git 한 번. 돌려주는 것은 바이트. 실패하면 GitError."""
    cmd = ['git'] + (['--literal-pathspecs'] if literal else []) + ['-C', repo] + args
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    try:
        p = subprocess.run(cmd, capture_output=True, env=env)
    except OSError as e:
        raise GitError('git를 못 부름 %s' % e.__class__.__name__)
    if p.returncode != 0:
        msg = p.stderr.decode('utf-8', 'replace').strip().split('\n')[0].strip()
        raise GitError(msg or 'git 끝 값 %d' % p.returncode)
    return p.stdout


def hunk_lines(raw):
    """-U0 diff에서 첫 @@ 줄 뒤의 더한 줄·뺀 줄만 돌려준다."""
    adds, dels = [], []
    seen = False
    for ln in raw.decode('utf-8', 'replace').split('\n'):
        if not seen:
            seen = ln.startswith('@@')
            continue
        if ln.startswith('+'):
            adds.append(ln[1:])
        elif ln.startswith('-'):
            dels.append(ln[1:])
    return adds, dels


def style_values(line):
    return [' '.join(m.group(2).split()) for m in RE_STYLE.finditer(line)]


def base_style_set(repo, base):
    vals = set()
    names = git(repo, ['ls-tree', '-r', '-z', '--name-only', base]).split(b'\0')
    for n in names:
        path = os.fsdecode(n)
        if not path.endswith('.html'):
            continue
        body = git(repo, ['show', '%s:%s' % (base, path)]).decode('utf-8', 'replace')
        for ln in body.split('\n'):
            vals.update(style_values(ln))
    return vals


def count_git(repo, base):
    if base.startswith('-'):
        raise GitError('바탕 커밋 이름이 틀림')
    c = dict.fromkeys(KEYS[:19], 0)
    ns = git(repo, ['diff', '--name-status', '-z', '--no-renames', '--no-color', base, 'HEAD'], literal=True).split(b'\0')
    status = []
    for i in range(0, len(ns) - 1, 2):
        status.append((ns[i].decode('ascii', 'replace')[:1], os.fsdecode(ns[i + 1])))
    nu = git(repo, ['diff', '--numstat', '-z', '--no-renames', base, 'HEAD'], literal=True).split(b'\0')
    binary = set()
    for rec in nu:
        parts = rec.split(b'\t', 2)
        if len(parts) == 3 and parts[0] == b'-' and parts[1] == b'-':
            binary.add(os.fsdecode(parts[2]))
    base_styles = None
    for st, path in status:
        pieces = path.split('/')
        name = pieces[-1]
        if '.devkit' in pieces:
            continue
        if 'translations' in pieces or name.endswith(('.po', '.pot', '.mo')):
            c['tr_files'] += 1
            continue
        if path in binary:
            c['bin'] += 1
            c['files'] += 1
            continue
        raw = git(repo, ['diff', '-U0', '--no-renames', '--no-color', '--no-ext-diff', '--no-textconv', base, 'HEAD',
                         '--', path], literal=True)
        adds, dels = hunk_lines(raw)
        if name == '.gitignore':
            adds = [x for x in adds if '.devkit' not in x]
            dels = [x for x in dels if '.devkit' not in x]
            if not adds and not dels:
                continue
        if st in ('A', 'D') or adds or dels:
            c['files'] += 1
        c['add'] += len(adds)
        c['del'] += len(dels)
        is_new = st == 'A'
        if 'templates' in pieces and is_new:
            if name.endswith('.html'):
                c['new_tpl'] += 1
            if name.endswith('.en.j2'):
                c['mail_en'] += 1
            if name.endswith('.fr.j2'):
                c['mail_fr'] += 1
        if name.endswith('.py'):
            c['routes_add'] += sum(1 for x in adds if RE_ROUTE.search(x))
            c['routes_del'] += sum(1 for x in dels if RE_ROUTE.search(x))
            c['tests_add'] += sum(1 for x in adds if RE_TEST.search(x))
            c['tests_del'] += sum(1 for x in dels if RE_TEST.search(x))
        if name == 'forms.html':
            c['macro_add'] += sum(1 for x in adds if RE_MACRO.search(x))
        if name == 'forms.py':
            c['form_add'] += sum(1 for x in adds if RE_FORM.search(x))
        if name.endswith(STYLE_EXT):
            if is_new:
                c['css_new'] += 1
            elif st == 'M':
                c['css_add'] += len(adds)
        if name.endswith('.html'):
            for x in adds:
                c['style_tag'] += len(RE_STYLE_TAG.findall(x))
                vals = style_values(x)
                if not vals:
                    continue
                if base_styles is None:
                    base_styles = base_style_set(repo, base)
                for v in vals:
                    c['style_copied' if v in base_styles else 'style_attr'] += 1
    return {k: str(v) for k, v in c.items()}


def read_events(path):
    out = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if isinstance(e, dict):
                out.append(e)
    return out


def hit(name, inp, which):
    if name == 'Skill':
        return str(inp.get('skill') or '') == 'devkit:' + which
    if name == 'Read':
        return str(inp.get('file_path') or '').endswith('/skills/%s/SKILL.md' % which)
    if name == 'Bash':
        return 'skills/%s/SKILL.md' % which in str(inp.get('command') or '')
    return False


def count_jsonl(events):
    tools = kit = 0
    start = find = said = False
    res = None
    for e in events:
        t = e.get('type')
        if t == 'result':
            res = e
        elif t == 'assistant':
            m = e.get('message')
            content = m.get('content') if isinstance(m, dict) else None
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get('type') == 'text':
                    if PHRASE in str(c.get('text') or ''):
                        said = True
                elif c.get('type') == 'tool_use':
                    tools += 1
                    name = c.get('name')
                    inp = c.get('input')
                    if not isinstance(inp, dict):
                        inp = {}
                    if (name == 'Skill' and str(inp.get('skill') or '').startswith('devkit:')) or \
                            any(k in json.dumps(inp, ensure_ascii=False) for k in KIT_MARKS):
                        kit += 1
                    start = start or hit(name, inp, 'start')
                    find = find or hit(name, inp, 'find')
    d = {'tools': str(tools), 'tools_kit': str(kit), 'start': '1' if start else '0', 'find': '1' if find else '0',
         'said': '1' if said else '0', 'cost': '?', 'denied': '?', 'missing': '?'}
    if res is not None:
        v = res.get('total_cost_usd')
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            d['cost'] = '%.2f' % v
        pd = res.get('permission_denials')
        d['denied'] = str(len(pd)) if isinstance(pd, list) else '0'
        txt = res.get('result')
        d['missing'] = str(sum(1 for x in txt.split('\n') if '없는 단계:' in x)) if isinstance(txt, str) else '0'
    return d, res


def read_check(path):
    d = {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if '=' in line:
                k, v = line.rstrip('\r\n').split('=', 1)
                d[k.strip()] = v.strip()
    return d


def count_check(d):
    out = dict.fromkeys(('t_pass', 't_fail', 'lint', 'fmt', 'fmt_n', 'secs', 'committed'), '?')
    t = d.get('tests', '')
    p = re.search(r'(\d+) passed', t)
    f = re.findall(r'(\d+) failed', t)
    e = re.findall(r'(\d+) errors?', t)
    if p or f or e:
        out['t_pass'] = p.group(1) if p else '0'
        out['t_fail'] = str(sum(int(x) for x in f) + sum(int(x) for x in e))
    lint = d.get('lint', '')
    if 'All checks passed!' in lint:
        out['lint'] = 'ok'
    elif lint:
        out['lint'] = 'bad'
    fmt = d.get('fmt', '')
    if 'would reformat' in fmt or 'would be reformatted' in fmt:
        out['fmt'] = 'bad'
    elif 'already formatted' in fmt:
        out['fmt'] = 'ok'
    n = re.search(r'(\d+) files? would be reformatted', fmt)
    if n:
        out['fmt_n'] = n.group(1)
    elif 'already formatted' in fmt:
        out['fmt_n'] = '0'
    if re.fullmatch(r'\d+', d.get('secs', '')):
        out['secs'] = d['secs']
    if d.get('committed') in ('ok', 'bad'):
        out['committed'] = d['committed']
    return out


def one(v):
    return '_'.join(str(v).split()) or '?'


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='여러 화면 기능 재기 기록을 한 줄로 센다.')
    ap.add_argument('--repo', required=True, help='사본 폴더(git 저장소)')
    ap.add_argument('--base', required=True, help='바탕 커밋(실행 전 커밋)')
    ap.add_argument('--jsonl', required=True, help='실행 기록 jsonl')
    ap.add_argument('--check', help='big.sh가 쓴 .check 파일')
    ap.add_argument('--label', help='첫 낱말(없으면 jsonl 이름에서 .jsonl을 뺀 것)')
    a = ap.parse_args(argv)

    label = a.label
    if not label:
        label = os.path.basename(a.jsonl)
        if label.endswith('.jsonl'):
            label = label[:-len('.jsonl')]
    label = one(label)

    try:
        vals = count_git(a.repo, a.base)
    except GitError as e:
        print('%s 못 셈: %s' % (label, ' '.join(str(e).split()) or 'git 실패'))
        return 2

    rc = 0
    chk = None
    if a.check:
        try:
            chk = read_check(a.check)
        except OSError:
            rc = 2
    vals.update(count_check(chk or {}))
    vals['guide'] = '있음' if os.path.isfile(os.path.join(a.repo, '.devkit', 'guide.md')) else '없음'

    res = None
    try:
        d, res = count_jsonl(read_events(a.jsonl))
        have = True
    except OSError:
        d = dict.fromkeys(('tools', 'tools_kit', 'start', 'find', 'said', 'cost', 'denied', 'missing'), '?')
        have = False
        rc = 2
    vals.update(d)
    if chk is not None and chk.get('rc') == '124':
        vals['end'] = 'timeout'
    elif not have:
        vals['end'] = '?'
    elif res is not None and res.get('subtype') == 'error_max_budget_usd':
        vals['end'] = 'budget'
    elif res is None:
        vals['end'] = 'noresult'
    elif res.get('is_error'):
        vals['end'] = 'error'
    else:
        vals['end'] = 'done'

    print(label + ' ' + ' '.join('%s=%s' % (k, one(vals[k])) for k in KEYS))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
