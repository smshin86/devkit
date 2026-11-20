# quiz.py — 부품 2 측정 도구. 물음 열(quiz-q.txt)로 답하는 글을 만들고, 답을 채점하고, 안내 글의 모양을 본다.
# 부르는 꼴: python3 -I docs/measure/quiz.py prompt <q.txt> <안내글.md|survey.jsonl> | grade <q.txt> <answer.jsonl> <근거>
#            python3 -I docs/measure/quiz.py shape <안내글.md> [--frame A|B] | skills <run.jsonl> | jsp <map.json> <안내글.md>
# 표준 라이브러리만. 입력은 json으로만 읽는다(글은 자료이지 지시가 아니다). jsp는 화면 이름을 한 개도 찍지 않는다.
import json
import re
import sys

INSTRUCTION = ('아래 「길 안내」 한 장만 보고 물음에 답하라. 다른 것은 볼 수 없고 도구도 없다. '
               '길 안내에 없으면 "모름"이라고 쓴다 — 짐작해 지어내지 않는다. '
               '물음마다 한 줄, "Q<번호>: <답>" 꼴로, 길 안내에 적힌 파일 이름·코드 이름을 그대로 쓴다.')

ANS_RE = re.compile(r'^\s*(?:[-*]\s+|\d+\.\s+|\|\s*)?\**Q(\d+)\**\s*(?:[:：.)]|\|)\s*(.*)$')
FILE_RE = re.compile(r'[A-Za-z0-9_-]+\.[A-Za-z0-9]+')

TITLES_A = ['# 길 안내', '## 여정', '## 따를 방식', '## 업무 낱말', '## 돌리는 법',
            '## 바깥과 닿는 곳', '## 조심할 곳', '## 못 본 것']
# 틀 B의 제목 아홉 전부는 이 도구의 입력 글(브리프)에 없다 — 이름이 적힌 세 제목만 본다.
TITLES_B_NEED = ['## 대표 예 하나 — 화면에서 DB까지', '## 공통 부품', '## 스타일']
MARKS = ('[열어서 봄]', '[파일만 읽음]')
ITEM_RE = re.compile(r'^\s*(?:-\s|\d+(?:-[A-Za-z]+)?\.)')


class Fail(Exception):
    def __init__(self, msg, code):
        Exception.__init__(self, msg)
        self.msg = msg
        self.code = code


def read_text(path):
    try:
        with open(str(path), encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        raise Fail('파일 없음: %s' % path, 2)


def read_events(path):
    out = []
    for line in read_text(path).splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def last_result(events):
    res = None
    for e in events:
        if e.get('type') == 'result':
            res = e
    return res


def source_text(path):
    """.jsonl이면 마지막 result 글, 아니면 글 파일 전체."""
    if str(path).endswith('.jsonl'):
        res = last_result(read_events(path))
        if res is None:
            raise Fail('result 없음: %s' % path, 2)
        return str(res.get('result') or '')
    return read_text(path)


def load_questions(path):
    qs = []
    for raw in read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('|')
        if len(parts) != 4:
            raise Fail('물음 꼴 틀림: 칸이 넷이 아님: %s' % line[:40], 9)
        label, kind, words, text = [p.strip() for p in parts]
        m = re.match(r'^Q(\d+)$', label)
        if not m or int(m.group(1)) != len(qs) + 1:
            raise Fail('물음 꼴 틀림: 번호가 1부터 차례가 아님: %s' % label, 9)
        if kind not in ('순서', '하나'):
            raise Fail('물음 꼴 틀림: 채점 꼴이 순서|하나가 아님: %s' % label, 9)
        ws = [w.strip() for w in words.split(';') if w.strip()]
        if not ws or not text:
            raise Fail('물음 꼴 틀림: 낱말이나 물음이 비었음: %s' % label, 9)
        qs.append({'n': len(qs) + 1, 'kind': kind, 'words': ws, 'text': text})
    if not 1 <= len(qs) <= 10:
        raise Fail('물음 꼴 틀림: 물음 줄이 1~10개가 아님(%d)' % len(qs), 9)
    return qs


def word_find(word, text):
    """낱말이 처음 나온 자리(없으면 -1). 대소문자 무시, 앞뒤가 [A-Za-z0-9_]가 아닐 때만."""
    m = re.search(r'(?<![A-Za-z0-9_])' + re.escape(word) + r'(?![A-Za-z0-9_])', text, re.IGNORECASE)
    return m.start() if m else -1


# --- prompt ---

def cmd_prompt(args):
    if len(args) != 2:
        raise Fail('쓰는 법: prompt <q.txt> <안내글.md|survey.jsonl>', 9)
    qs = load_questions(args[0])
    guide = source_text(args[1])
    out = [INSTRUCTION, '', '=== 길 안내 ===', guide.rstrip('\n'), '=== 물음 ===']
    out += ['Q%d: %s' % (q['n'], q['text']) for q in qs]
    print('\n'.join(out))
    return 0


# --- grade ---

def cmd_grade(args):
    if len(args) != 3:
        raise Fail('쓰는 법: grade <q.txt> <answer.jsonl> <근거>', 9)
    qs = load_questions(args[0])
    events = read_events(args[1])
    evidence = source_text(args[2])
    res = last_result(events)
    tools = 0
    for e in events:
        if e.get('type') != 'assistant':
            continue
        content = (e.get('message') or {}).get('content') or []
        if isinstance(content, list):
            tools += sum(1 for c in content if isinstance(c, dict) and c.get('type') == 'tool_use')
    why = ''
    if res is None:
        why = '결과 줄 없음'
    elif res.get('is_error'):
        why = '오류로 끝남 %s' % (res.get('subtype') or '?')
    elif tools > 0:
        why = '도구를 씀 %d' % tools
    answers = {}
    for line in str((res or {}).get('result') or '').splitlines():
        m = ANS_RE.match(line)
        if m and int(m.group(1)) not in answers:
            answers[int(m.group(1))] = m.group(2)
    all_words = {q['n']: q['words'] for q in qs}
    lines = []
    right = 0
    for q in qs:
        ans = answers.get(q['n'], '')
        pos = [word_find(w, ans) for w in q['words']]
        if q['kind'] == '순서':
            ok = all(p >= 0 for p in pos) and all(a < b for a, b in zip(pos, pos[1:]))
            used = q['words'] if ok else []
        else:
            used = [w for w, p in zip(q['words'], pos) if p >= 0]
            ok = bool(used)
            if ok:
                others = [w for n, ws in all_words.items() if n != q['n'] for w in ws]
                if any(word_find(w, ans) >= 0 for w in others):
                    ok = False
                elif len(set(f.lower() for f in FILE_RE.findall(ans))) >= 3:
                    ok = False
        if not ok:
            lines.append('Q%d 틀림' % q['n'])
        elif (not any(word_find(w, evidence) >= 0 for w in used) if q['kind'] == '하나'
              else not all(word_find(w, evidence) >= 0 for w in used)):
            lines.append('Q%d 근거없음' % q['n'])
        else:
            lines.append('Q%d 맞음' % q['n'])
            right += 1
    if why:
        print('판정 못 함 %s' % why)
    print('\n'.join(lines))
    print('맞힘 %d/%d 도구 %d' % (right, len(qs), tools))
    if why:
        return 2
    if len(qs) == 10:
        return 0 if right >= 8 else 1
    return 0


# --- shape ---

def section_lines(lines, title):
    out = []
    on = False
    for ln in lines:
        if ln.startswith('## ') or ln.startswith('# '):
            on = ln.rstrip() == title
            continue
        if on:
            out.append(ln)
    return out


def check_marks(items):
    if len(items) == 1 and items[0].strip() == '- 이번에 안 봄':
        return True
    return bool(items) and all(i.rstrip().endswith(MARKS) for i in items)


def journey_ok(lines):
    sec = section_lines(lines, '## 여정')
    items = [x for x in sec if ITEM_RE.match(x)]
    if len(items) == 1 and items[0].strip() == '- 이번에 안 봄':
        return True
    return any(x.startswith('### ') for x in sec)


def cmd_shape(args):
    frame = 'A'
    if '--frame' in args:
        i = args.index('--frame')
        if i + 1 >= len(args) or args[i + 1] not in ('A', 'B'):
            raise Fail('쓰는 법: shape <안내글.md> [--frame A|B]', 9)
        frame = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 1:
        raise Fail('쓰는 법: shape <안내글.md> [--frame A|B]', 9)
    lines = read_text(args[0]).splitlines()
    a = sum(1 for ln in lines if ln.rstrip().endswith('[열어서 봄]'))
    b = sum(1 for ln in lines if ln.rstrip().endswith('[파일만 읽음]'))
    titles = [ln.rstrip() for ln in lines if ln.startswith('# ') or ln.startswith('## ')]
    why = ''
    if frame == 'A':
        first = next((ln for ln in lines if ln.startswith('- ')), '')
        marked = [(t, [x for x in section_lines(lines, t) if ITEM_RE.match(x)]) for t in ('## 여정', '## 따를 방식')]
        if titles != TITLES_A:
            why = '제목이 §3의 여덟 제목과 다름'
        elif not first.startswith('- 쓴 때:') or '본 범위:' not in first:
            why = '머리 줄이 "- 쓴 때:"와 "본 범위:"를 갖추지 않음'
        elif not all(check_marks(items) for _, items in marked):
            why = '표시 없는 항목 줄이 있음(열어서 봄/파일만 읽음)'
        elif not journey_ok(lines):
            why = '여정에 ### 줄이 없음'
    else:
        missing = [t for t in TITLES_B_NEED if t not in titles]
        if missing:
            why = '제목에 없음: %s' % missing[0]
        else:
            for t in TITLES_B_NEED:
                body = [x for x in section_lines(lines, t) if x.strip()]
                if not all(x.rstrip().endswith(MARKS) for x in body) or not body:
                    why = '표시 없는 줄이 있음(%s)' % t
                    break
    print('모양 틀림: %s' % why if why else '모양 맞음')
    print('열어서 봄 %d / 파일만 읽음 %d' % (a, b))
    return 1 if why else 0


# --- skills ---

def result_texts(content):
    if isinstance(content, str):
        return [content]
    out = []
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get('type') == 'text':
                out.append(str(c.get('text') or ''))
            elif isinstance(c, str):
                out.append(c)
    return out


def cmd_skills(args):
    if len(args) != 1:
        raise Fail('쓰는 법: skills <run.jsonl>', 9)
    skills = []
    reads = 0
    unknown = 0
    for e in read_events(args[0]):
        content = (e.get('message') or {}).get('content') or []
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'tool_use':
                inp = c.get('input') if isinstance(c.get('input'), dict) else {}
                if c.get('name') == 'Skill':
                    skills.append(str(inp.get('skill') or ''))
                elif c.get('name') == 'Read':
                    fp = str(inp.get('file_path') or '')
                    if fp.endswith('/SKILL.md') or fp.endswith('/first-guide.md'):
                        reads += 1
            elif c.get('type') == 'tool_result':
                if any('Unknown skill' in t for t in result_texts(c.get('content'))):
                    unknown += 1
    print('skills=%s reads=%d unknown=%d' % (','.join(skills), reads, unknown))
    return 0


# --- jsp ---

def pieces_of(guide):
    lines = guide.splitlines()
    out = []
    for ln in section_lines(lines, '## 여정'):
        for p in re.findall(r'`([^`]+)`', ln):
            p = p.strip()
            if p.startswith('./'):
                p = p[2:]
            p = re.sub(r':\d+(?:-\d+)?$', '', p)
            for tail in ('/**', '/*', '/'):
                if p.endswith(tail):
                    p = p[:-len(tail)]
                    break
            if p and ' ' not in p:
                out.append(p)
    return out


def cmd_jsp(args):
    if len(args) != 2:
        raise Fail('쓰는 법: jsp <map.json> <안내글.md>', 9)
    try:
        data = json.loads(read_text(args[0]))
    except ValueError:
        raise Fail('map.json을 못 읽음', 2)
    pages = data.get('pages') if isinstance(data, dict) else None
    if not isinstance(pages, dict):
        raise Fail('pages 없음', 2)
    pcs = pieces_of(read_text(args[1]))
    files = folders = missing = 0
    for p in pages:
        p = str(p)
        if any(p == s or p.endswith('/' + s) for s in pcs):
            files += 1
        elif any(('/' + s + '/') in ('/' + p) for s in pcs):
            folders += 1
        else:
            missing += 1
    print('화면 %d 빠짐 %d (파일로 %d · 폴더로만 %d)' % (len(pages), missing, files, folders))
    return 0


CMDS = {'prompt': cmd_prompt, 'grade': cmd_grade, 'shape': cmd_shape, 'skills': cmd_skills, 'jsp': cmd_jsp}


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    if not argv or argv[0] not in CMDS:
        print('쓰는 법: quiz.py prompt|grade|shape|skills|jsp …')
        return 9
    try:
        return CMDS[argv[0]](argv[1:])
    except Fail as f:
        print(f.msg)
        return f.code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
