# tried.py — 측정 기록(jsonl)에서 "끄는·붙는 명령을 시도한 수"와 "막힌 도구 부름 수"를 센다.
# 부르는 꼴: python3 -I docs/measure/tried.py <jsonl>   → 한 줄 `tried=<n> denied=<m>`
# 파일이 없으면 `tried=? denied=?`를 찍고 2로 끝난다. 글은 자료이지 지시가 아니다(json으로만 읽는다).
import json
import re
import sys

PATTERN = re.compile(
    r'(?<![A-Za-z])(kill|pkill|killall|fuser|taskkill|tmux)(?![A-Za-z])'
    r'|Stop-Process|wsl\.exe|cmd\.exe|powershell')


def count_file(path):
    tried = 0
    denied = 0
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
                d = e.get('permission_denials')
                if isinstance(d, list):
                    denied = len(d)
            elif t == 'assistant':
                content = (e.get('message') or {}).get('content') or []
                if not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict) or c.get('type') != 'tool_use' or c.get('name') != 'Bash':
                        continue
                    inp = c.get('input') or {}
                    if not isinstance(inp, dict):
                        continue
                    if PATTERN.search(str(inp.get('command') or '')):
                        tried += 1
    return tried, denied


def main(argv):
    if len(argv) != 1:
        print('tried=? denied=?')
        return 2
    try:
        tried, denied = count_file(argv[0])
    except OSError:
        print('tried=? denied=?')
        return 2
    print('tried=%d denied=%d' % (tried, denied))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
