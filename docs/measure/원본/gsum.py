# gsum.py — 이어 붙이기 시험의 부탁별 비용·시간·턴과, 끝에 한 말(끝 보고)을 뽑는다.
import json
import sys

W = '/home/ssmge/zzz-devkit-exist'
ORDER = [1, 2, 3, 5, 6, 7, 8, 4]
show_report = len(sys.argv) > 1
for arm in ('gw', 'gp'):
    tot = 0.0
    for n in ORDER:
        res, tools, hook = None, 0, 0
        try:
            for line in open('%s/out/g.%s.%d.jsonl' % (W, arm, n), encoding='utf-8'):
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get('type') == 'result':
                    res = e
                elif e.get('type') == 'assistant':
                    for c in e.get('message', {}).get('content', []):
                        if c.get('type') == 'tool_use':
                            tools += 1
                elif e.get('type') == 'system' and 'hook' in str(e.get('subtype', '')):
                    hook += 1
        except OSError:
            print(arm, n, '기록 없음')
            continue
        if not res:
            print(arm, n, '결과 줄 없음')
            continue
        cost = res.get('total_cost_usd') or 0
        tot += cost
        print('%s.%d  $%.2f  %3ds  턴 %2s  도구 %2d  훅줄 %d  err=%s' % (
            arm, n, cost, (res.get('duration_ms') or 0) // 1000, res.get('num_turns'), tools, hook, res.get('is_error')))
        if show_report:
            print('    끝 보고: ' + (res.get('result') or '').replace('\n', '\n      '))
    print('%s 합계 $%.2f' % (arm, tot))
