# lib.py — 켜 둔 앱에 쿠키를 이어 가며 화면을 부르는 작은 도우미 (표준 라이브러리만).
import http.cookiejar
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

G = '/home/ssmge/zzz-devkit-exist'
ENV = dict(os.environ,
           UV_CACHE_DIR=G + '/uvcache', UV_PYTHON_DOWNLOADS='never',
           PATH=G + '/tools/bin:' + os.environ.get('PATH', ''))


class S:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.last, self.code, self.url, self.headers = '', None, None, {}

    def _do(self, req):
        try:
            r = self.op.open(req, timeout=30)
            self.code, body, self.url, self.headers = r.getcode(), r.read(), r.geturl(), dict(r.headers)
        except urllib.error.HTTPError as e:
            self.code, body, self.url, self.headers = e.code, e.read(), e.geturl(), dict(e.headers)
        self.raw = body
        self.last = body.decode('utf-8', 'replace')
        return self.last

    def get(self, path):
        return self._do(self.base + path if path.startswith('/') else path)

    def post(self, path, data):
        body = urllib.parse.urlencode(data, doseq=True).encode()
        return self._do(urllib.request.Request(self.base + path if path.startswith('/') else path, data=body))

    def csrf(self, page=None):
        page = self.last if page is None else page
        m = re.search(r'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"', page) or \
            re.search(r'<input[^>]*value="([^"]+)"[^>]*name="csrf_token"', page)
        return m.group(1) if m else ''


def names(page):
    """화면의 입력 칸 이름들 (input/select/textarea)."""
    return sorted(set(re.findall(r'<(?:input|select|textarea)[^>]*\bname="([^"]+)"', page)))


def options(page, select_name):
    m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % re.escape(select_name), page, re.S)
    if not m:
        return {}
    return {re.sub(r'\s+', ' ', t).strip(): v
            for v, t in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', m.group(1))}


def text(page):
    page = re.sub(r'<(script|style)\b.*?</\1>', ' ', page, flags=re.S)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', page))


def serve(folder, port, db=None, log=None):
    """folder의 앱을 켠다. db를 주면 그 sqlite 파일을 쓰게 설정 파일을 만들어 넘긴다. (proc, 주소)"""
    env = dict(ENV, FLASK_APP='ihatemoney.wsgi')
    if db:
        cfg = db + '.cfg'
        with open(cfg, 'w') as f:
            f.write('SQLALCHEMY_DATABASE_URI = "sqlite:///%s"\n' % db)
            f.write('SESSION_COOKIE_SECURE = False\n')  # http로 부르는 내 확인에서만
        env['IHATEMONEY_SETTINGS_FILE_PATH'] = cfg
    out = open(log or os.devnull, 'w')
    p = subprocess.Popen([folder + '/.venv/bin/python', '-m', 'flask', 'run', '--port', str(port)],
                         cwd=folder, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    base = 'http://127.0.0.1:%d' % port
    for _ in range(40):
        if p.poll() is not None:
            break
        try:
            urllib.request.urlopen(base + '/healthcheck', timeout=2)
            return p, base
        except Exception:
            time.sleep(0.5)
    return p, None


def stop(p):
    if p.poll() is None:
        os.kill(p.pid, signal.SIGTERM)
        try:
            p.wait(10)
        except Exception:
            os.kill(p.pid, signal.SIGKILL)
