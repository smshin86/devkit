# gcmd.py — 각 부탁에서 실제로 돌린 검사 명령(시험·코드 모양 검사)을 기록에서 뽑아 가른다.
import json
import re
W = '/home/ssmge/zzz-devkit-exist'
for arm in ('gw', 'gp'):
    for n in [1, 2, 3, 5, 6, 7, 8, 4]:
        segs = []
        for line in open('%s/out/g.%s.%d.jsonl' % (W, arm, n), encoding='utf-8'):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get('type') != 'assistant':
                continue
            for c in e.get('message', {}).get('content', []):
                if c.get('type') == 'tool_use' and c.get('name') == 'Bash':
                    cmd = c.get('input', {}).get('command', '')
                    for s in re.split(r';|&&|\|\||\||\(|\)|\n', cmd):
                        s = ' '.join(s.split())
                        if re.search(r'\bpytest\b|\bruff\b', s) and not s.startswith(('which', 'ls', 'grep', 'import', 'from', '#', 'echo')):
                            segs.append(s)
        full = [s for s in segs if 'pytest' in s and ' -k ' not in s and '::' not in s and '_test.py' not in s]
        part = [s for s in segs if 'pytest' in s and s not in full]
        chk_all = [s for s in segs if 'ruff check' in s and '.py' not in s]
        chk_some = [s for s in segs if 'ruff check' in s and '.py' in s]
        fmt = [s for s in segs if 'ruff format' in s]
        print('%s.%d 전체 시험 %d번 · 일부 시험 %d번 · 코드 검사(전체) %d · 코드 검사(고친 파일만) %d · 서식 검사 %d' % (
            arm, n, len(full), len(part), len(chk_all), len(chk_some), len(fmt)))
