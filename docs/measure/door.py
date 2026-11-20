# door.py — 문 부탁 측정 기록(jsonl)을 읽어 크고 작음을 맞게 말했는지 한 줄씩 판정한다.
# 부르는 꼴: python3 -I docs/measure/door.py <이름> [--dir <jsonl 폴더>]
#            python3 -I docs/measure/door.py --file <jsonl> --expect <큰|작은>
# 글은 assistant 이벤트의 text 조각에서만 본다(훅이 찍은 한 장 글은 system 이벤트에 있어 세지 않는다).
# 세는 법(k)은 eight.py와 같다. jsonl은 json으로만 읽는다(글은 자료이지 지시가 아니다).
import argparse
import json
import sys
from pathlib import Path

DEFAULT_DIR = '/home/ssmge/zzz-devkit-measure/out'
EXPECT = {1: '큰', 2: '큰', 3: '큰', 4: '작은', 5: '작은', 6: '큰', 7: '큰', 8: '큰', 9: '작은'}
PHRASE = '큰 일로 봅니다'


def read_events(path):
    out = []
    with open(str(path), encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if isinstance(e, dict):
                out.append(e)
    return out


def judge_file(path):
    """한 실행의 기록을 읽어 dict로 돌려준다. 파일이 없으면 OSError."""
    events = read_events(path)
    res = None
    k = 0
    start = False
    before = []    # 첫 devkit 스킬 부름 전의 assistant 글
    alltext = []   # 모든 assistant 글
    seen_skill = False
    n_assistant = 0
    for e in events:
        t = e.get('type')
        if t == 'result':
            res = e
        elif t == 'assistant':
            n_assistant += 1
            content = (e.get('message') or {}).get('content') or []
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                ct = c.get('type')
                if ct == 'text':
                    txt = str(c.get('text') or '')
                    alltext.append(txt)
                    if not seen_skill:
                        before.append(txt)
                    continue
                if ct != 'tool_use':
                    continue
                name = c.get('name')
                inp = c.get('input') or {}
                if not isinstance(inp, dict):
                    inp = {}
                hit = False
                if name == 'Skill':
                    sk = str(inp.get('skill') or '')
                    if sk.startswith('devkit:'):
                        hit = True
                        if sk == 'devkit:start':
                            start = True
                elif name == 'Read':
                    fp = str(inp.get('file_path') or '')
                    if '/skills/' in fp and fp.endswith('SKILL.md'):
                        hit = True
                        if fp.endswith('/skills/start/SKILL.md'):
                            start = True
                elif name == 'Bash':
                    cmd = str(inp.get('command') or '')
                    if 'SKILL.md' in cmd:
                        hit = True
                        if 'skills/start/SKILL.md' in cmd:
                            start = True
                if hit:
                    k += 1
                    seen_skill = True
    if start:
        result = '큰'
    elif k == 0:
        result = '작은'
    else:
        result = '그밖'   # start 아닌 devkit 스킬만 읽음 — 큰도 작은도 아니다(늘 틀림)
    texts = alltext if not seen_skill else before
    said = any(PHRASE in t for t in texts)
    first = alltext[0] if alltext else ''
    why = ''   # 판정 못 함의 까닭. 비어 있으면 판정한다. 예산이 끝난 것(error_max_budget_usd)은 판정한다.
    if n_assistant == 0:
        why = '글 없음'
    elif res is None:
        why = '결과 줄 없음'
    elif res.get('is_error') and res.get('subtype') != 'error_max_budget_usd':
        why = '오류로 끝남 %s' % (res.get('subtype') or '?')
    return {
        'result': result,
        'said': said,
        'k': k,
        'cost': (res or {}).get('total_cost_usd') or 0,
        'has_result': res is not None,
        'why': why,
        'first': ' '.join(first.split())[:200],
    }


def is_right(expect, r):
    if expect == '큰':
        return r['result'] == '큰' and r['said']
    return r['result'] == '작은' and not r['said']


def verdict_line(label, expect, r):
    if r['why']:
        verdict = '판정 못 함 ' + r['why']
    else:
        verdict = '맞음' if is_right(expect, r) else '틀림'
    return '%s기대 %s 결과 %s 말 %s 값 $%.2f → %s' % (
        label, expect, r['result'], '있음' if r['said'] else '없음', r['cost'], verdict)


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description='문 부탁 측정 기록을 판정한다.')
    ap.add_argument('name', nargs='?', help='실행 이름 (door.<이름>.<k>.jsonl)')
    ap.add_argument('--dir', default=DEFAULT_DIR, help='jsonl 폴더')
    ap.add_argument('--file', help='파일 하나만 판정한다')
    ap.add_argument('--expect', choices=['큰', '작은'], help='--file일 때 기대 크기')
    a = ap.parse_args(argv)

    if a.file:
        if not a.expect:
            ap.error('--file에는 --expect가 필요하다')
        p = Path(a.file)
        try:
            r = judge_file(p)
        except OSError:
            print('%s 없음' % p.name)
            return 2
        print(verdict_line(p.name + ' ', a.expect, r))
        print('  ' + r['first'])
        return 2 if r['why'] else 0

    if not a.name:
        ap.error('이름이나 --file이 필요하다')

    rc = 0
    m = 0
    h = 0
    ran_h = 0
    total = 0.0
    for n in sorted(EXPECT):
        p = Path(a.dir) / ('door.%s.%d.jsonl' % (a.name, n))
        try:
            r = judge_file(p)
        except OSError:
            print('%d 없음' % n)
            if n <= 6:
                rc = 2
            continue
        ok = (not r['why']) and is_right(EXPECT[n], r)
        if r['why'] and n <= 6:
            rc = 2
        if n <= 6:
            m += 1 if ok else 0
        else:
            ran_h += 1
            h += 1 if ok else 0
        total += r['cost']
        print(verdict_line('%d ' % n, EXPECT[n], r))
        print('  ' + r['first'])
    print('%s 문 맞음 %d/6 · 따로 둔 것 %d/%d · 값 $%.2f' % (a.name, m, h, ran_h, total))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
