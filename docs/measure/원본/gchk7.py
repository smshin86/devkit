# gchk7.py <이름> [포트] — 나눠 낸 사람이 일부뿐인 지출이 섞인 옛 자료(seed.db)에서 "나눠 낸 사람 고르기"가 맞게 거르는지.
import base64, json, os, re, shutil, sys, urllib.request
sys.path.insert(0, '/home/ssmge/zzz-devkit-exist')
import lib  # noqa: E402
G = lib.G
nm = sys.argv[1]; port = int(sys.argv[2]) if len(sys.argv) > 2 else 5087
db = '%s/out/gchk7.%s.db' % (G, nm); shutil.copy(G + '/seed.db', db)
log = '%s/out/gchk7.%s.log' % (G, nm)
p, base = lib.serve('%s/runs/%s' % (G, nm), port, db=db, log=log)
try:
    s = lib.S(base); s.get('/demo')
    req = urllib.request.Request(base + '/api/projects/demo/bills', headers={'Authorization': 'Basic ' + base64.b64encode(b'demo:demo').decode()})
    bills = json.loads(urllib.request.urlopen(req, timeout=30).read())
    ow = lambda b: set(o['id'] if isinstance(o, dict) else o for o in b['owers'])
    for b in bills:
        print('     지출 %-14s 낸 사람 %s · 나눠 낸 사람 %s' % (b['what'], b['payer_id'], sorted(ow(b))))
    ok_all = True
    for who in (1, 2, 3):
        exp = sorted(b['what'] for b in bills if who in ow(b))
        t = lib.text(s.get('/demo/?ower=%d' % who))
        got = sorted(b['what'] for b in bills if b['what'] in t)
        ok = got == exp and s.code == 200
        ok_all &= ok
        print('7a   %s  나눠 낸 사람 %d: 화면 %s · 기대 %s' % ('됨' if ok else '안 됨', who, got, exp))
    for pay, who in ((3, 1), (2, 3), (1, 2)):
        exp = sorted(b['what'] for b in bills if who in ow(b) and b['payer_id'] == pay)
        t = lib.text(s.get('/demo/?payer=%d&ower=%d' % (pay, who)))
        got = sorted(b['what'] for b in bills if b['what'] in t)
        print('Gc2  %s  낸 사람 %d + 나눠 낸 사람 %d: 화면 %s · 기대 %s' % ('됨' if got == exp else '안 됨', pay, who, got, exp))
finally:
    lib.stop(p)
    print('     서버 기록의 오류 줄:', len(re.findall(r'Traceback|" 500 ', open(log).read())))
    os.remove(db); os.remove(db + '.cfg')
