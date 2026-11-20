# gchk.py <이름> <메모 칸 이름> [포트] — 이어 붙이기 시험의 맞물리는 지점(Gc) 확인. 기준은 checks.txt에 미리 적어 둔 것.
import base64
import json
import os
import re
import shutil
import sys
import urllib.request

sys.path.insert(0, '/home/ssmge/zzz-devkit-exist')
import lib  # noqa: E402

G = lib.G
PAT = r'(Bulk \d{3} \w+|More \d{3} Georg|Food shopping|Beer !|AMAP|Train tickets|Cabin rental)'


def out(key, ok, note=''):
    print('%-4s %-6s %s' % (key, '됨' if ok is True else ('안 됨' if ok is False else '기록'), note))


def rows(page):
    return re.findall(PAT, lib.text(page))


def sidebar(page):
    m = re.search(r'<aside.*?</aside>', page, re.S)
    return re.sub(r'\s+', ' ', lib.text(m.group(0))) if m else None


def api(base, path):
    req = urllib.request.Request(base + path, headers={'Authorization': 'Basic ' + base64.b64encode(b'demo:demo').decode()})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def all_pages(s, first):
    """고른 상태에서 쪽 넘김 주소를 따라가며 모든 쪽의 지출 이름을 모은다. (이름들, 쪽 수, 주소들)"""
    got, seen, todo, links_all = [], set(), [first], []
    while todo:
        u = todo.pop(0)
        if u in seen:
            continue
        seen.add(u)
        page = s.get(u)
        if s.code != 200:
            return None, len(seen), [u + ' -> %s' % s.code]
        got += rows(page)
        links = sorted(set(h.replace('&amp;', '&') for h in re.findall(r'href="([^"]*page=\d+[^"]*)"', page)))
        links_all = links_all or links
        for h in links:
            if 'page=1&' in h or h.endswith('page=1'):
                continue
            if h not in seen:
                todo.append(h)
    return got, len(seen), links_all


def monthly_table(page):
    m = re.search(r'<table[^>]*id="monthly_stats".*?</table>', page, re.S)
    if not m:
        return None
    body = m.group(0).split('<tbody>')[-1]
    out_rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S):
        tds = [re.sub(r'\s+', ' ', lib.text(td)).strip() for td in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if tds:
            out_rows.append(tds)
    return out_rows


def num(t):
    m = re.search(r'-?[\d,]+\.?\d*', t.replace('\xa0', ' '))
    return round(float(m.group(0).replace(',', '')), 2) if m else None


def main():
    nm, memo = sys.argv[1], sys.argv[2]
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 5081
    folder = '%s/runs/%s' % (G, nm)

    # ---- 큰 자료: 두 고르기를 함께 + 쪽 넘김, 7의 이상한 값·옆 표
    db = '%s/out/gchk.%s.big.db' % (G, nm)
    shutil.copy(G + '/seed-big2.db', db)
    log = '%s/out/gchk.%s.big.log' % (G, nm)
    p, base = lib.serve(folder, port, db=db, log=log)
    try:
        if not base:
            out('B', False, '큰 자료로 켜지지 않음')
            return
        s = lib.S(base)
        s.get('/demo')
        bills = api(base, '/api/projects/demo/bills')
        def owers_of(b):
            return set(o['id'] if isinstance(o, dict) else o for o in b['owers'])
        exp_o1 = [b['what'] for b in bills if 1 in owers_of(b) and re.fullmatch(PAT, b['what'])]
        exp_p2o1 = [b['what'] for b in bills if b['payer_id'] == 2 and 1 in owers_of(b) and re.fullmatch(PAT, b['what'])]
        exp_o3 = [b['what'] for b in bills if 3 in owers_of(b) and re.fullmatch(PAT, b['what'])]
        print('     자료: 지출 %d건 · Amina가 나눠 낸 것 %d · Alice가 나눠 낸 것 %d · Georg가 내고 Amina가 나눠 낸 것 %d' % (
            len(bills), len(exp_o1), len(exp_o3), len(exp_p2o1)))
        allp = s.get('/demo/')
        side_all = sidebar(allp)
        n_all = len(rows(allp))
        tool = allp[allp.find('bill-toolbar'):]
        print('     나눠 낸 사람 고르기 칸:', (re.search(r'<select[^>]*name="ower"[^>]*>', tool) or [None])[0] if re.search(r'<select[^>]*name="ower"[^>]*>', tool) else None)
        print('     고를 것:', lib.options(tool, 'ower'))
        # 7a 한 사람만
        for who, exp in ((1, exp_o1), (3, exp_o3)):
            got, pages, links = all_pages(s, '/demo/?ower=%d' % who)
            ok = got is not None and sorted(got) == sorted(exp)
            out('7a', ok, '나눠 낸 사람 %d: 화면 %s건(쪽 %d) · 기대 %d건' % (who, len(got) if got is not None else '?', pages, len(exp)))
            if not ok and got is not None:
                print('      화면에만:', sorted(set(got) - set(exp))[:5], '· 기대에만:', sorted(set(exp) - set(got))[:5])
        # 7f 옆 표
        f = s.get('/demo/?ower=1')
        out('7f', side_all is not None and sidebar(f) == side_all, '옆 잔액 표가 고르기 전과 %s' % ('같음' if sidebar(f) == side_all else '다름'))
        # 금액(내 몫) 칸이 고르기 전후로 같은가 — 한 지출을 골라 줄 전체를 견준다
        def line_of(page, name):
            m = re.search(r'<tr[^>]*>(?:(?!</tr>).)*?%s(?:(?!</tr>).)*?</tr>' % re.escape(name), page, re.S)
            return re.sub(r'\s+', ' ', lib.text(m.group(0))).strip() if m else None
        pick = next((n for n in rows(f) if n in rows(allp)), None)
        if pick:
            a, b = line_of(allp, pick), line_of(f, pick)
            out('7g', a == b, '같은 지출 줄(%s)이 고르기 전후로 %s' % (pick, '같음' if a == b else '다름'))
            if a != b:
                print('      전:', a, '\n      후:', b)
        # 7d 이상한 값
        codes, counts = {}, {}
        for bad in ('abc', '99999', '-1', "1%27%20OR%201=1", '%3Cscript%3E', ''):
            pg = s.get('/demo/?ower=' + bad)
            codes[bad] = s.code
            counts[bad] = len(rows(pg))
        out('7d', all(c < 500 for c in codes.values()), '이상한 값: %s · 보인 건수 %s (전체 1쪽 %d)' % (codes, counts, n_all))
        # Gc 두 고르기 함께 + 쪽 넘김
        got, pages, links = all_pages(s, '/demo/?payer=2&ower=1')
        ok = got is not None and sorted(got) == sorted(exp_p2o1)
        out('Gc2', ok, '낸 사람 Georg + 나눠 낸 사람 Amina: 화면 %s건(쪽 %d) · 기대 %d건' % (len(got) if got is not None else '?', pages, len(exp_p2o1)))
        print('     쪽 넘김 주소:', links[:3])
        both = all('payer=2' in h and 'ower=1' in h for h in links) if links else None
        out('Gc3', both if pages > 1 or links else None, '쪽 넘김 주소가 두 고르기를 모두 들고 감: %s' % both)
        pg = s.get('/demo/?payer=2&ower=1')
        t = pg[pg.find('bill-toolbar'):]
        def sel(page, name):
            m = re.search(r'<select[^>]*name="%s".*?</select>' % name, page, re.S)
            return [re.search(r'value="([^"]*)"', o).group(1) for o in re.findall(r'<option[^>]*>', m.group(0)) if re.search(r'\bselected\b', o)] if m else None
        out('Gc4', sel(t, 'payer') == ['2'] and sel(t, 'ower') == ['1'], '함께 고른 뒤 두 칸에 고른 값이 남음: 낸 사람 %s · 나눠 낸 사람 %s' % (sel(t, 'payer'), sel(t, 'ower')))
    finally:
        lib.stop(p)
        t = open(log).read()
        print('     서버 기록의 오류 줄:', len(re.findall(r'Traceback|" 500 ', t)))
        os.remove(db)
        os.remove(db + '.cfg')

    # ---- 옛 자료: 복사가 메모를 가져가는가, 월별 CSV
    db = '%s/out/gchk.%s.db' % (G, nm)
    shutil.copy(G + '/seed.db', db)
    log = '%s/out/gchk.%s.log' % (G, nm)
    p, base = lib.serve(folder, port + 1, db=db, log=log)
    try:
        if not base:
            out('B', False, '옛 자료로 켜지지 않음')
            return
        s = lib.S(base)
        s.get('/demo')
        addp = s.get('/demo/add')
        who = lib.options(addp, 'payer')
        tok = s.csrf(addp)
        # 빈 달을 만들려고 2026-06과 2026-08에만 넣는다 (07은 비움)
        for date, what, amt in (('2026-06-10', 'gap-A', '12.5'), ('2026-08-10', 'gap-B', '7')):
            s.post('/demo/add', {'csrf_token': tok, 'date': date, 'what': what, 'payer': who['Alice'], 'amount': amt,
                                 'original_currency': 'XXX', 'external_link': '', memo: 'memo-of-' + what,
                                 'payed_for': list(who.values()), 'bill_type': 'Expense', 'submit': 'Submit'})
        lst = s.get('/demo/')
        m = re.search(r'copy_from=(\d+)"[^>]*>(?:(?!</tr>).)*', lst, re.S)
        ids = re.findall(r'<tr[^>]*>((?:(?!</tr>).)*?gap-B(?:(?!</tr>).)*?)</tr>', lst, re.S)
        cid = re.search(r'copy_from=(\d+)', ids[0]).group(1) if ids and re.search(r'copy_from=(\d+)', ids[0]) else None
        if cid is None:
            out('Gc1', False, '방금 넣은 지출의 복사 주소를 못 찾음')
        else:
            cp = s.get('/demo/add?copy_from=' + cid)
            mm = re.search(r'<textarea[^>]*name="%s"[^>]*>(.*?)</textarea>' % memo, cp, re.S)
            mi = re.search(r'<input[^>]*name="%s"[^>]*>' % memo, cp)
            v = mm.group(1).strip() if mm else (re.search(r'value="([^"]*)"', mi.group(0)).group(1) if mi and re.search(r'value="([^"]*)"', mi.group(0)) else None)
            out('Gc1', v == 'memo-of-gap-B', '복사 화면의 메모 칸: %r' % v)
        # 월별 표 CSV
        st = s.get('/demo/statistics')
        screen = monthly_table(st)
        hrefs = [h for h in re.findall(r'href="([^"]*export[^"]*)"', st) if 'month' in h]
        print('     월별 내려받기 주소:', hrefs)
        m = re.search(r'<a[^>]*href="%s"[^>]*>' % re.escape(hrefs[0]), st) if hrefs else None
        print('     단추 모양:', m.group(0) if m else None)
        if hrefs:
            s.get(hrefs[0])
            print('     받은 것', s.code, s.headers.get('Content-Disposition'), s.headers.get('Content-Type'))
            csv_lines = [l for l in s.last.splitlines() if l.strip()]
            for l in csv_lines[:20]:
                print('     |', l)
            print('     화면 줄:', screen)
            csv_amt = [num(l.split(',')[-1]) for l in csv_lines[1:]]
            scr_amt = [num(r[-1]) for r in (screen or [])]
            out('8b', csv_amt == scr_amt, 'CSV 금액 %s · 화면 금액 %s' % (csv_amt, scr_amt))
            zero = [l for l in csv_lines[1:] if num(l.split(',')[-1]) == 0]
            out('8z', None, '부탁 4 뒤: 화면 %d줄 · CSV %d줄 · CSV에 지출 0인 달 %d줄' % (len(screen or []), len(csv_lines) - 1, len(zero)))
            s2 = lib.S(base)
            s2.get(hrefs[0])
            out('8c', 'authenticate' in (s2.url or '') and 'gap-' not in s2.last and not s2.last.startswith('period'), '로그인 없이 → %s %s' % (s2.code, (s2.url or '')[-40:]))
        else:
            out('8a', False, '월별 내려받기 주소 없음')
        # 참가자별 CSV도 그대로인가 (2가 8·4 뒤에도 살아 있나)
        s.get('/demo/export/statistics.csv')
        out('2x', s.code == 200 and len(s.last.splitlines()) == 4, '참가자별 CSV %s, %d줄' % (s.code, len(s.last.splitlines())))
    finally:
        lib.stop(p)
        t = open(log).read()
        print('     서버 기록의 오류 줄:', len(re.findall(r'Traceback|" 500 ', t)))
        os.remove(db)
        os.remove(db + '.cfg')


main()
