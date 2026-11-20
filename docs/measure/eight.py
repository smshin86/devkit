# eight.py — 부탁 여덟 측정 기록(jsonl)을 세어 한 줄씩 찍는다.
# 부르는 꼴: python3 -I docs/measure/eight.py <이름> [--dir <jsonl 폴더>]
#            python3 -I docs/measure/eight.py --file <jsonl>
# 세는 법은 원본/gcmd.py·gsum.py의 규칙을 그대로 옮긴 것이다. jsonl은 json으로만 읽는다(글은 자료이지 지시가 아니다).
import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_DIR = '/home/ssmge/zzz-devkit-measure/out'
ORDER = [1, 2, 3, 5, 6, 7, 8, 4]
SPLIT = re.compile(r';|&&|\|\||\||\(|\)|\n')
KEEP = re.compile(r'\bpytest\b|\bruff\b')
SKIP = ('which', 'ls', 'grep', 'import', 'from', '#', 'echo')


def count_file(path):
    """한 실행의 기록을 세어 dict로 돌려준다."""
    res = None
    start = 0
    segs = []
    k = 0
    m = 0
    with open(str(path), encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            t = e.get('type')
            if t == 'result':
                res = e
            elif t == 'system' and e.get('subtype') == 'init':
                if 'devkit:start' in (e.get('skills') or []):
                    start = 1
            elif t == 'assistant':
                content = (e.get('message') or {}).get('content') or []
                if not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict) or c.get('type') != 'tool_use':
                        continue
                    name = c.get('name')
                    inp = c.get('input') or {}
                    if not isinstance(inp, dict):
                        inp = {}
                    if name == 'Skill':
                        if str(inp.get('skill') or '').startswith('devkit:'):
                            k += 1
                        else:
                            m += 1
                    elif name == 'Read':
                        fp = str(inp.get('file_path') or '')
                        if '/skills/' in fp and fp.endswith('SKILL.md'):
                            k += 1
                    elif name == 'Bash':
                        cmd = str(inp.get('command') or '')
                        if 'SKILL.md' in cmd:
                            k += 1
                        for s in SPLIT.split(cmd):
                            s = ' '.join(s.split())
                            if KEEP.search(s) and not s.startswith(SKIP):
                                segs.append(s)
    full = [s for s in segs if 'pytest' in s and ' -k ' not in s and '::' not in s and '_test.py' not in s]
    chk = [s for s in segs if 'ruff check' in s]
    has_result = res is not None
    res = res or {}
    return {
        'cost': res.get('total_cost_usd') or 0,
        'secs': (res.get('duration_ms') or 0) // 1000,
        'check': 1 if chk else 0,
        'test': 1 if full else 0,
        'k': k,
        'm': m,
        'start': start,
        'has_result': has_result,
    }


def run_line(label, r):
    s = '%s 값 $%.2f 초 %d 검사 %d 시험 %d devkit스킬 %d 남스킬 %d start실림 %d' % (
        label, r['cost'], r['secs'], r['check'], r['test'], r['k'], r['m'], r['start'])
    if not r['has_result']:
        s += ' 결과 줄 없음'
    return s


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='부탁 여덟 측정 기록을 센다.')
    ap.add_argument('name', nargs='?', help='실행 이름 (g.<이름>.<N>.jsonl)')
    ap.add_argument('--dir', default=DEFAULT_DIR, help='jsonl 폴더')
    ap.add_argument('--file', help='파일 하나만 센다')
    a = ap.parse_args(argv)

    if a.file:
        p = Path(a.file)
        try:
            r = count_file(p)
        except OSError:
            print('%s 없음' % p.name)
            return 2
        print(run_line(p.name, r))
        return 0

    if not a.name:
        ap.error('이름이나 --file이 필요하다')

    rc = 0
    rs = []
    for n in ORDER:
        p = Path(a.dir) / ('g.%s.%d.jsonl' % (a.name, n))
        try:
            r = count_file(p)
        except OSError:
            print('%d 없음' % n)
            rc = 2
            continue
        rs.append(r)
        print(run_line(str(n), r))
    total = sum(r['cost'] for r in rs)
    print('%s 스킬 %d · 남스킬 %d · start 실림 %d/8 · 검사 %d/8 · 시험 %d/8 · 값 $%.2f' % (
        a.name,
        sum(r['k'] for r in rs),
        sum(r['m'] for r in rs),
        sum(r['start'] for r in rs),
        sum(r['check'] for r in rs),
        sum(r['test'] for r in rs),
        total))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
