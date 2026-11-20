# mkseed.py — 고르기 전(base) 코드로 "이미 쓰던 자료"를 만든다: 시범 프로젝트 + 다른 달의 지출 둘.
import datetime
import os
import shutil
import sys

sys.path.insert(0, '/home/ssmge/zzz-devkit-exist')
import lib  # noqa: E402

G = lib.G
db = G + '/seed.work.db'
if os.path.exists(db):
    os.remove(db)
p, base = lib.serve(G + '/base', 5057, db=db, log=G + '/out/mkseed.log')
try:
    assert base, '켜지지 않음'
    s = lib.S(base)
    s.get('/demo')
    page = s.get('/demo/add')
    who = lib.options(page, 'payer')
    today = datetime.date.today()

    def month_ago(n):
        y, m = today.year, today.month - n
        while m <= 0:
            y, m = y - 1, m + 12
        return datetime.date(y, m, 10).isoformat()

    for when, what, payer, amount in ((month_ago(2), 'Train tickets', 'Georg', '90'),
                                      (month_ago(4), 'Cabin rental', 'Alice', '300')):
        page = s.get('/demo/add')
        s.post('/demo/add', {'csrf_token': s.csrf(page), 'date': when, 'what': what, 'payer': who[payer],
                             'amount': amount, 'original_currency': 'XXX', 'external_link': '',
                             'payed_for': list(who.values()), 'bill_type': 'Expense', 'submit': 'Submit'})
        print(when, what, s.code, s.url)
    t = lib.text(s.get('/demo/'))
    print([w for w in ('Food shopping', 'Beer !', 'AMAP', 'Train tickets', 'Cabin rental') if w in t])
    print(lib.text(s.get('/demo/statistics'))[-420:])
finally:
    lib.stop(p)
shutil.copy(db, G + '/seed.db')
os.remove(db)
os.remove(db + '.cfg')
print('seed.db', os.path.getsize(G + '/seed.db'))
