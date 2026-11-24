# stage-walk.py — 연습 무대의 준비(prep) · ② 걸어 보기(walk-b) · ③ 숨긴 시험(check-c) · ① 장면 빈칸(blank-a) · ① 시험 세기(tests-a).
# 쓰는 법: python3 -I -B stage-walk.py <prep|walk-b|check-c|blank-a|tests-a> [--root R] [--sub <이름>(walk-b·tests-a·check-c·blank-a만)] …   (실행 비트 없음 · 잠금 아래에서 부른다)
# 뿌리 S는 환경 STAGE_S(없으면 tasks.json의 stage). 원본 저장소 S/src-b/repo·S/src-c/repo는 읽기만 한다
# (log·show·diff·ls-files, 그리고 임시 색인으로 바탕 트리를 꺼내는 read-tree·checkout-index — 원본의 HEAD·색인·작업 트리는 그대로).
# 띄우는 프로세스는 모두 start_new_session=True · 걸음마다 상한 · 끝낼 때 자기가 받은 pgid로만 killpg. 설치는 하지 않는다(prep은 명령을 찍기만).
import argparse
import hashlib
import html
import http.cookiejar
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.join(HERE, "stage-walk.py")


class WalkError(Exception):
    pass


# ---------- 설정 · 뿌리 ----------

def load_cfg():
    path = os.environ.get("STAGE_TASKS") or os.path.join(HERE, "stage", "tasks.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def stage_root(cfg):
    return os.environ.get("STAGE_S") or cfg["stage"]


def work_root(cfg):
    return os.environ.get("STAGE_X") or cfg["work"]


def task_of(cfg, run):
    for key in ("order", "zero", "rerun", "round_y"):
        for row in cfg.get(key, []):
            if row and row[0] == run:
                return row[1]
    return None


# ---------- 프로세스 ----------

def _kill_group(p, sig):
    """자기가 띄운 프로세스의 그룹에만 신호를 보낸다(새 세션의 우두머리일 때만 killpg)."""
    try:
        pg = os.getpgid(p.pid)
    except (ProcessLookupError, PermissionError):
        return
    if pg == p.pid:
        try:
            os.killpg(pg, sig)
        except (ProcessLookupError, PermissionError):
            pass
    else:
        try:
            p.send_signal(sig)
        except (ProcessLookupError, PermissionError):
            pass


def stop(p, grace=10):
    """자기가 띄운 Popen을 끈다: TERM → grace초 뒤 KILL. 끝났으면 True."""
    if p.poll() is not None:
        return True
    _kill_group(p, signal.SIGTERM)
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        _kill_group(p, signal.SIGKILL)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    return p.poll() is not None


def run_bytes(argv, cwd=None, env=None, timeout=900, input_bytes=None):
    """(rc, 출력 바이트). 시간이 넘으면 자기 그룹을 KILL하고 124 · 정상으로 끝나도 그 그룹에 남은 것은 KILL."""
    p = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
                         stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        out, _ = p.communicate(input=input_bytes, timeout=timeout)
        try:  # 끝난 뒤에도 그 그룹(새 세션 · pgid = p.pid)에 남은 자식을 끈다
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return p.returncode, out
    except subprocess.TimeoutExpired:
        _kill_group(p, signal.SIGKILL)
        try:
            out, _ = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out = b""
        return 124, out or b""


def run_cmd(argv, cwd=None, env=None, timeout=900):
    rc, out = run_bytes(argv, cwd=cwd, env=env, timeout=timeout)
    return rc, out.decode("utf-8", "replace")


def free_port(port):
    rc, out = run_cmd(["ss", "-ltnH"], timeout=20)
    if rc != 0:
        raise WalkError("ss를 못 돌림 — 포트를 못 봄")
    return int(port) not in ports_from_ss(out)


def ports_from_ss(text):
    ports = set()
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 4:
            m = re.search(r":(\d+)$", f[3])
            if m:
                ports.add(int(m.group(1)))
    return ports


def wait_up(url, secs):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(int(secs)):
        try:
            with op.open(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    return False


def wait_port(port, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = socket.socket()
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", int(port)))
            return True
        except OSError:
            time.sleep(0.5)
        finally:
            s.close()
    return False


# ---------- 파일 ----------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def rm_tree(path, under):
    """under 아래에 있는 폴더만 지운다(그 자체나 밖이면 멈춤)."""
    rp, ru = os.path.realpath(path), os.path.realpath(under)
    if not rp.startswith(ru + os.sep):
        raise WalkError("지우려는 자리가 %s 밖: %s" % (under, path))
    if os.path.lexists(path):
        if os.path.islink(path):
            os.unlink(path)
        else:
            shutil.rmtree(path)


# ---------- git (원본은 읽기만) ----------

GITBASE = ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-c", "core.hooksPath=/dev/null"]
IDENT = ["-c", "user.name=stage", "-c", "user.email=stage@invalid", "-c", "commit.gpgsign=false"]


def git_env(extra=None):
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent-stage-walk", "GIT_CONFIG_GLOBAL": "/dev/null",
         "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"}
    if extra:
        e.update(extra)
    return e


def git_dir_of(repo):
    g = os.path.join(repo, ".git")
    return g if os.path.isdir(g) else str(repo)


def git_in(w, *args, check=True, input_bytes=None):
    """사본(w) 안의 git. 출력 글을 돌려줌."""
    rc, out = run_bytes(GITBASE + IDENT + ["-C", str(w)] + list(args), env=git_env(), timeout=300, input_bytes=input_bytes)
    txt = out.decode("utf-8", "replace")
    if check and rc != 0:
        raise WalkError("git %s 실패(%d): %s" % (" ".join(args[:2]), rc, txt.strip()[:300]))
    return txt.strip()


def git_show_bytes(repo, commit, path):
    rc, out = run_bytes(GITBASE + ["--git-dir", git_dir_of(repo), "show", "%s:%s" % (commit, path)], env=git_env(), timeout=120)
    if rc != 0:
        raise WalkError("git show %s:%s 실패: %s" % (commit[:8], path, out.decode("utf-8", "replace").strip()[:200]))
    return out


def extract_commit(repo, commit, dst):
    """커밋의 트리를 임시 색인으로 dst에 꺼낸다 — 원본의 HEAD·색인·작업 트리는 안 바뀐다."""
    if os.path.isdir(dst) and os.listdir(dst):
        raise WalkError("꺼낼 자리가 비어 있지 않음: %s" % dst)
    os.makedirs(dst, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="idx-")
    try:
        env = git_env({"GIT_INDEX_FILE": os.path.join(tmp, "index")})
        gd = git_dir_of(repo)
        for sub in (["read-tree", commit], ["checkout-index", "-a", "-f"]):
            rc, out = run_bytes(GITBASE + ["--git-dir", gd, "--work-tree", str(dst)] + sub, cwd=tmp, env=env, timeout=600)
            if rc != 0:
                raise WalkError("git %s 실패(%d): %s" % (sub[0], rc, out.decode("utf-8", "replace").strip()[:300]))
    finally:
        rm_tree(tmp, tempfile.gettempdir())


def init_copy(dst):
    """풀어 둔 바탕 위에 새 저장소 + 바탕 커밋 하나(무시 규칙에 걸린 파일도 넣는다). 커밋 해시를 돌려줌."""
    git_in(dst, "init", "-q")
    git_in(dst, "add", "-A", "-f")
    git_in(dst, "commit", "-q", "--no-verify", "--allow-empty", "-m", "base")
    return git_in(dst, "rev-parse", "HEAD")


def make_copy(repo, commit, dst):
    extract_commit(repo, commit, dst)
    return init_copy(dst)


def pack_tar(src, tar):
    tar = str(tar)
    os.makedirs(os.path.dirname(tar), exist_ok=True)
    part = tar + ".part"
    rc, out = run_cmd(["tar", "-c", "-f", part, "-C", str(src), "."], env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C.UTF-8"}, timeout=600)
    if rc != 0:
        raise WalkError("tar 묶기 실패: %s" % out.strip()[:200])
    os.replace(part, tar)


def unpack_tar(tar, dst):
    os.makedirs(dst, exist_ok=True)
    rc, out = run_cmd(["tar", "-x", "-f", str(tar), "-C", str(dst)], env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C.UTF-8"}, timeout=600)
    if rc != 0:
        raise WalkError("tar 풀기 실패: %s" % out.strip()[:200])


def clone_done(src, dst):
    rc, out = run_cmd(GITBASE + ["clone", "-q", "--no-hardlinks", str(src), str(dst)], env=git_env(), timeout=600)
    if rc != 0:
        raise WalkError("clone 실패: %s" % out.strip()[:200])


# ---------- 양식 · HTTP ----------

class FormFields(HTMLParser):
    """한 양식(form_id, 없으면 첫 양식)의 값: input·textarea·select 기본값 · 체크 칸은 켜진 것만."""
    SKIP = {"submit", "button", "image", "reset", "file"}

    def __init__(self, form_id=None):
        super().__init__(convert_charrefs=True)
        self.form_id = form_id
        self.pairs = []
        self._in = False
        self._done = False
        self._ta = None
        self._buf = []
        self._sel = None
        self._opt = None

    @property
    def fields(self):
        return dict(self.pairs)

    def _close_opt(self):
        if self._opt is not None and self._sel is not None:
            v = self._opt["value"] if self._opt["value"] is not None else self._opt["text"].strip()
            self._sel["opts"].append((v, self._opt["selected"]))
        self._opt = None

    def _close_sel(self):
        self._close_opt()
        s = self._sel
        self._sel = None
        if not s or not s["name"] or not s["opts"]:
            return
        if s["multiple"]:
            for v, on in s["opts"]:
                if on:
                    self.pairs.append((s["name"], v))
        else:
            pick = [v for v, on in s["opts"] if on]
            self.pairs.append((s["name"], pick[0] if pick else s["opts"][0][0]))

    def handle_starttag(self, tag, attrs):
        raw = dict(attrs)
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "form":
            if not self._done and not self._in and (self.form_id is None or a.get("id") == self.form_id):
                self._in = True
            return
        if not self._in:
            return
        if tag == "input":
            name = a.get("name")
            if not name:
                return
            typ = a.get("type", "text").lower()
            if typ in self.SKIP:
                return
            if typ in ("checkbox", "radio"):
                if "checked" in raw:
                    self.pairs.append((name, a.get("value") or "on"))
            else:
                self.pairs.append((name, a.get("value", "")))
        elif tag == "textarea":
            self._ta = a.get("name")
            self._buf = []
        elif tag == "select":
            self._sel = {"name": a.get("name"), "multiple": "multiple" in raw, "opts": []}
        elif tag == "option" and self._sel is not None:
            self._close_opt()
            self._opt = {"value": a.get("value") if "value" in raw else None, "selected": "selected" in raw, "text": ""}

    def handle_data(self, data):
        if self._ta is not None:
            self._buf.append(data)
        elif self._opt is not None:
            self._opt["text"] += data

    def handle_endtag(self, tag):
        if tag == "form":
            if self._in:
                self._in = False
                self._done = True
        elif tag == "textarea" and self._ta is not None:
            text = "".join(self._buf)
            if text.startswith("\n"):
                text = text[1:]
            if self._ta:
                self.pairs.append((self._ta, text))
            self._ta = None
        elif tag == "option":
            self._close_opt()
        elif tag == "select":
            self._close_sel()


def form_pairs(body, form_id=None):
    ff = FormFields(form_id)
    ff.feed(body)
    ff.close()
    return ff.pairs


class _FormHead(HTMLParser):
    """첫 양식 하나의 머리(action·method)와, 그 안 input·textarea·select의 이름들."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.action = ""
        self.method = "get"
        self.names = set()
        self._in = False
        self._done = False

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "form":
            if not self._done and not self._in:
                self._in = True
                self.action = a.get("action", "")
                self.method = (a.get("method") or "get").strip().lower()
        elif self._in and tag in ("input", "textarea", "select") and a.get("name"):
            self.names.add(a["name"])

    def handle_endtag(self, tag):
        if tag == "form" and self._in:
            self._in = False
            self._done = True


def pick_form(body, field, method="post"):
    """화면의 양식 가운데 method가 맞고 name이 field인 칸이 든 첫 양식 → {"action", "method", "pairs"} · 없으면 None."""
    want = (method or "get").lower()
    starts = [m.start() for m in re.finditer(r"<form\b", body, re.I)]
    for i, st in enumerate(starts):
        seg = body[st:(starts[i + 1] if i + 1 < len(starts) else len(body))]
        head = _FormHead()
        head.feed(seg)
        head.close()
        if head.method == want and field in head.names:
            return {"action": head.action, "method": head.method, "pairs": form_pairs(seg)}
    return None


def override(pairs, changes):
    out, placed = [], set()
    for k, v in pairs:
        if k in changes:
            if k not in placed:
                out.append((k, changes[k]))
                placed.add(k)
        else:
            out.append((k, v))
    for k, v in changes.items():
        if k not in placed:
            out.append((k, v))
    return out


def csrf_token(body):
    for m in re.finditer(r"<input\b[^>]*>", body):
        tag = m.group(0)
        if re.search(r"""name=["']csrf_token["']""", tag):
            v = re.search(r"""value=["']([^"']*)["']""", tag)
            if v:
                return html.unescape(v.group(1))
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Client:
    """쿠키를 쥐고 리다이렉트를 따라가지 않는 작은 HTTP 손."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.pw = None
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(), urllib.request.HTTPCookieProcessor(self.jar))

    def _do(self, req):
        try:
            with self.op.open(req, timeout=30) as r:
                return r.status, r.headers, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")
            except OSError:
                body = ""
            return e.code, e.headers, body

    def get(self, path):
        return self._do(urllib.request.Request(self.base + path))

    def post(self, path, pairs):
        data = urllib.parse.urlencode(pairs).encode()
        return self._do(urllib.request.Request(self.base + path, data=data, method="POST"))

    def login(self, user, pw):
        st, _, body = self.get("/login")
        if st != 200:
            return False
        pairs = [("csrf_token", csrf_token(body) or ""), ("username", user), ("password", pw), ("remember_me", "on"), ("next", "")]
        st, hd, _ = self.post("/login", pairs)
        return st == 302


# ---------- 숨긴 시험 결과 읽기 ----------

def parse_runtests(text):
    m = re.findall(r"^Ran (\d+) tests? in", text, re.M)
    ran = int(m[-1]) if m else 0
    ok = ran > 0 and bool(re.search(r"^OK\b", text, re.M))
    failures = errors = 0
    f = re.search(r"^FAILED \(([^)]*)\)", text, re.M)
    if f:
        mf = re.search(r"(?<!expected )failures=(\d+)", f.group(1))
        me = re.search(r"errors=(\d+)", f.group(1))
        failures = int(mf.group(1)) if mf else 0
        errors = int(me.group(1)) if me else 0
        ok = False
    failed = []
    for fm in re.finditer(r"^(?:FAIL|ERROR): (\S+) \(([\w.]+)\)", text, re.M):
        name, paren = fm.group(1), fm.group(2)
        if name.startswith("test") and not paren.endswith("." + name):
            paren = paren + "." + name
        if paren not in failed:
            failed.append(paren)
    return {"ran": ran, "ok": ok, "failures": failures, "errors": errors, "failed": failed}


# ---------- 씨앗 서재 ----------

SEED_ROWS = [
    (1, "Sea Song", "1999-07-15", "North Press", "Poetry", "Ana Kim"),
    (2, "Mountain Path", "1999-01-03", "North Press", None, "Ben Lee"),
    (3, "Winter Letter", "2005-11-30", "South House", "Novel", "Ana Kim"),
    (4, "No Date", "0101-01-01", None, None, "Cy Park"),
    (5, "Old Map", "1987-05-05", "South House", None, "Ben Lee"),
    (6, "Small House", "2005-02-01", None, "Poetry", "Cy Park"),
]


def _title_sort(t):
    t = t or ""
    for art in ("A ", "An ", "The "):
        if t.startswith(art):
            return t[len(art):] + ", " + art.strip()
    return t


def _author_sort(name):
    parts = name.split()
    return "%s, %s" % (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else name


def seed_library(src_db, dst_db, rows):
    """src_db(책 0권)를 dst_db로 복사해 rows를 넣는다. 연도별 책 수({'1999': 2, …})를 돌려줌."""
    src_db, dst_db = str(src_db), str(dst_db)
    os.makedirs(os.path.dirname(dst_db), exist_ok=True)
    if os.path.exists(dst_db):
        os.unlink(dst_db)
    shutil.copyfile(src_db, dst_db)
    con = sqlite3.connect(dst_db)
    try:
        con.create_function("title_sort", 1, _title_sort)
        con.create_function("uuid4", 0, lambda: str(uuid.uuid4()))
        cur = con.cursor()

        def ident(table, col, value, extra=None):
            r = cur.execute("select id from %s where %s=?" % (table, col), (value,)).fetchone()
            if r:
                return r[0]
            if extra:
                cur.execute("insert into %s(%s, %s) values (?, ?)" % (table, col, extra[0]), (value, extra[1](value)))
            else:
                cur.execute("insert into %s(%s) values (?)" % (table, col), (value,))
            return cur.lastrowid

        years = {}
        for bid, title, pub, publisher, tag, author in rows:
            date = pub + " 00:00:00+00:00"
            aid = ident("authors", "name", author, ("sort", _author_sort))
            cur.execute("insert into books(id, title, timestamp, pubdate, author_sort, path, has_cover, last_modified) values (?,?,?,?,?,?,0,?)",
                        (bid, title, date, date, _author_sort(author), "%s/%s (%d)" % (author, title, bid), date))
            cur.execute("insert into books_authors_link(book, author) values (?, ?)", (bid, aid))
            if publisher:
                pid = ident("publishers", "name", publisher, ("sort", lambda v: v))
                cur.execute("insert into books_publishers_link(book, publisher) values (?, ?)", (bid, pid))
            if tag:
                tid = ident("tags", "name", tag)
                cur.execute("insert into books_tags_link(book, tag) values (?, ?)", (bid, tid))
            years[pub[:4]] = years.get(pub[:4], 0) + 1
        con.commit()
        return years
    finally:
        con.close()


def seed_ok(db):
    try:
        con = sqlite3.connect(str(db))
        try:
            got = [r[0] for r in con.execute("select title from books order by id")]
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return got == [r[1] for r in SEED_ROWS]


def pubdate_of(db, book_id):
    con = sqlite3.connect(str(db))
    try:
        r = con.execute("select pubdate from books where id=?", (book_id,)).fetchone()
        return r[0] if r else None
    finally:
        con.close()


def tags_of(db, book_id):
    con = sqlite3.connect(str(db))
    try:
        return sorted(r[0] for r in con.execute(
            "select t.name from tags t join books_tags_link l on l.tag=t.id where l.book=?", (book_id,)))
    finally:
        con.close()


# ---------- 시험 파일 · 시험 명령(tests-a) ----------

TESTFILES = [r"(^|/)test_[^/]*\.py$", r"_test\.py$", r"(^|/)tests/", r"\.test\.js$", r"\.spec\.js$", r"\.test\.ts$", r"(^|/)__tests__/",
             r"(^|/)test\.(js|mjs|cjs|ts|py)$", r"(^|/)tests\.(js|py)$", r"\.test\.(mjs|cjs|tsx|jsx)$", r"\.spec\.(ts|mjs|cjs)$", r"(^|/)test/",
             r"[-_]test\.(js|mjs|cjs|ts)$", r"(^|/)test-[^/]*\.(js|mjs|cjs|ts)$"]


def is_test_file(path, pats=None):
    return any(re.search(p, path) for p in (pats or TESTFILES))


_README_CMD = re.compile(r"^\s*(?:\$\s*)?((?:python3?\s+-m\s+(?:unittest|pytest)|pytest|npm\s+(?:run\s+)?test|npm\s+t)\b.*?|node\s+\S.*?)\s*$")
_SHELL_BITS = re.compile(r"[;&|<>`]|\$\(")
_CODE_EXT = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py")
_JS_EXT = (".js", ".mjs", ".cjs")


def _tail_ok(tail, tests):
    """README의 `pytest`·`python -m …` 줄 꼬리 낱말이 모두 옵션·옵션 값·길 꼴·discover·시험 파일(폴더) 이름일 때만 참."""
    prev = ""
    for t in tail:
        ok = (t.startswith("-") or prev.startswith("-") or any(c in t for c in "/._:=[]*") or t == "discover"
              or any(x == t or x.startswith(t + "/") for x in tests))
        if not ok:
            return False
        prev = t
    return True


def _node_arg(x):
    return "./" + x if x.startswith("-") else x


def detect_test_cmd(files, tests=()):
    """files: {이름: 글} · tests: 시험 파일 길(git ls-files 꼴). 닫힌 차례(처음 걸린 것):
    ① README류의 시험 명령 줄(셸 잇기 글자·NUL이 든 줄·시험 파일이 아닌 `node <낱말>`·명령 뒤에 옵션/길이 아닌 낱말이 이어지는 설명 문장은 버림)
    ② package.json의 scripts.test(자리표 제외) → npm test
    ③ 코드 확장자 시험 파일이 모두 JS면 node --test <이름이 시험 꼴인 파일들(없으면 그 JS 전부)> ④ python -m pytest."""
    tests = list(tests)
    tset = set(tests)
    for name in ("README.md", "README", "readme.md", "README.txt"):
        for line in files.get(name, "").splitlines():
            if "\x00" in line:
                continue
            line = line.strip().strip("`").strip()
            m = _README_CMD.match(line)
            if not m or _SHELL_BITS.search(m.group(1)):
                continue
            try:
                toks = shlex.split(m.group(1), comments=True)
            except ValueError:
                continue
            if not toks:
                continue
            if toks[0] in ("python", "python3"):
                if not _tail_ok(toks[3:], tests):
                    continue
                return ["python"] + toks[1:]
            if toks[0] == "pytest":
                if not _tail_ok(toks[1:], tests):
                    continue
                return ["python", "-m", "pytest"] + toks[1:]
            if toks[0] == "npm":
                return ["npm", "test"]
            if toks[0] == "node":
                head, rest = ["node"], toks[1:]
                if rest and rest[0] == "--test":
                    head, rest = ["node", "--test"], rest[1:]
                rest = [x[2:] if x.startswith("./") else x for x in rest]
                if rest and all(x in tset for x in rest):
                    return head + [_node_arg(x) for x in rest]
    pj = files.get("package.json")
    if pj is not None:
        try:
            obj = json.loads(pj)
        except ValueError:
            obj = None
        scripts = obj.get("scripts") if isinstance(obj, dict) else None
        s = scripts.get("test") if isinstance(scripts, dict) else None
        if isinstance(s, str) and s.strip() and "no test specified" not in s:
            return ["npm", "test"]
    code = [x for x in tests if os.path.splitext(x)[1] in _CODE_EXT]
    if code and all(os.path.splitext(x)[1] in _JS_EXT for x in code):
        named = [x for x in code if is_test_file(x.rsplit("/", 1)[-1])]
        return ["node", "--test"] + [_node_arg(x) for x in sorted(named or code)]
    return ["python", "-m", "pytest"]


NOISE_DIRS = (".venv", "venv", "node_modules", "__pycache__")


# ---------- 장면 ----------

def sidestep(fn, notes, key):
    try:
        return bool(fn())
    except Exception as e:  # 장면 하나가 터져도 다음 장면은 간다 — 터진 장면은 안 됨으로 적는다
        notes[key] = ("%s: %s" % (type(e).__name__, e))[:200]
        return False


def save_book(cli, book_id, changes):
    st, _, body = cli.get("/admin/book/%d" % book_id)
    if st != 200:
        raise WalkError("편집 양식 GET %d" % st)
    pairs = form_pairs(body, "book_edit_frm")
    if not pairs:
        raise WalkError("편집 양식(book_edit_frm) 없음")
    st, _, _ = cli.post("/admin/book/%d" % book_id, override(pairs, changes))
    return st


def _text(body):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


def _links(body):
    out = []
    for m in re.finditer(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", body, re.S | re.I):
        out.append((html.unescape(m.group(1)), _text(m.group(2)).strip()))
    return out


def link_spans(body):
    """_links와 같은 풀이 + 본문 안 자리: [(시작, 끝, href, 글자)]."""
    out = []
    for m in re.finditer(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", body, re.S | re.I):
        out.append((m.start(), m.end(), html.unescape(m.group(1)), _text(m.group(2)).strip()))
    return out


def gap_before_text(body, spans, i):
    """i째 링크 앞 사이 글: 앞 링크 끝(없으면 본문 처음)부터 이 링크 시작까지의 태그 뗀 글의 끝 300글자."""
    lo = spans[i - 1][1] if i > 0 else 0
    return _text(body[lo:spans[i][0]])[-300:]


def gap_num(body, spans, i, side):
    """i째 링크 앞(before)·뒤(after) 이웃 링크와의 사이 글(태그 뗀 글 · 300글자)에서 가장 가까운 수. 없으면 None."""
    if side == "before":
        found = re.findall(r"\d+", gap_before_text(body, spans, i))
        return int(found[-1]) if found else None
    hi = spans[i + 1][0] if i + 1 < len(spans) else len(body)
    m = re.search(r"\d+", _text(body[spans[i][1]:hi])[:300])
    return int(m.group(0)) if m else None


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


ROW_TAGS = {"li", "td", "th", "tr", "dt", "dd", "p", "option"}   # 닫는 태그를 생략할 수 있는 줄 태그


def _tag_info(tag):
    """(깊이 바뀜, 소문자 이름): 여는 태그 +1 · 닫는 태그 -1 · 빈 태그(<br>·<img>… · `/>`로 끝남)·주석·선언 0."""
    m = re.match(r"<\s*(/?)\s*([A-Za-z][A-Za-z0-9-]*)", tag)
    if not m or tag.rstrip().endswith("/>") or m.group(2).lower() in VOID_TAGS:
        return 0, ""
    return (-1 if m.group(1) else 1), m.group(2).lower()


def _tag_step(tag):
    """태그 하나가 깊이를 얼마나 바꾸는가: 여는 태그 +1 · 닫는 태그 -1 · 빈 태그(<br>·<img>… · `/>`로 끝남)·주석·선언 0."""
    return _tag_info(tag)[0]


def gap_side(body, spans, i):
    """이웃한 i째·i+1째 링크 사이의 수가 어느 링크 것인가: 'after'(i째) · 'before'(i+1째) · None(못 가림).
    사이 글을 태그로 쪼개 수가 든 글 덩이가 꼭 하나일 때만, 그 덩이에서 각 링크와 함께 든 가장 안쪽 틀까지 올라가는 층 수를 견줘 적은 쪽."""
    parts = re.split(r"(<[^>]*>)", body[spans[i][1]:spans[i + 1][0]])
    net = {}
    for t in parts[1::2]:
        st, name = _tag_info(t)
        if name in ROW_TAGS:
            net[name] = net.get(name, 0) + st
    if any(net.values()):   # 줄 태그의 여는 수와 닫는 수가 다름(닫는 태그 생략) → 못 가림
        return None
    nums = [k for k, p in enumerate(parts) if k % 2 == 0 and re.search(r"\d", html.unescape(p))]
    if len(nums) != 1:
        return None
    k = nums[0]
    d = lo = 0
    for t in parts[1:k:2]:
        d += _tag_step(t)
        lo = min(lo, d)
    up_a = d - lo            # 수에서 앞 링크와 함께 든 틀까지
    d = lo = 0
    for t in parts[k + 1::2]:
        d += _tag_step(t)
        lo = min(lo, d)
    up_b = -lo               # 수에서 뒤 링크와 함께 든 틀까지
    return "after" if up_a < up_b else "before" if up_b < up_a else None


def year_counts_ok(body, counts):
    """counts: {연도: 책 수}. 연도가 든 링크마다 책 수가 (가) 링크 글자 안 (나) 링크 앞 (다) 링크 뒤 — 세 연도에 같은 방향 하나만."""
    spans = link_spans(body)
    cand = {}
    for y in counts:
        cand[y] = [i for i, sp in enumerate(spans) if re.search(r"(?<!\d)%s(?!\d)" % re.escape(y), sp[3])]
        if not cand[y]:
            return False

    def inside(i, y, n):
        rest = re.sub(r"(?<!\d)%s(?!\d)" % re.escape(y), " ", spans[i][3], count=1)
        return re.search(r"(?<!\d)%d(?!\d)" % n, rest) is not None

    if all(any(inside(i, y, n) for i in cand[y]) for y, n in counts.items()):
        return True
    first = min(i for y in cand for i in cand[y])
    allc = sorted({i for y in cand for i in cand[y]})
    votes = {gap_side(body, spans, i) for i in allc if i + 1 in allc} - {None}
    if len(votes) == 1:
        sides = (votes.pop(),)            # 이웃한 연도 링크 사이의 수가 어느 줄에 붙었는지로 방향을 가림
    elif re.search(r"\d\s*$", gap_before_text(body, spans, first)):
        sides = ("before",)               # 못 가림 + 맨 앞 링크 바로 앞이 수 → 책 수가 링크 앞에 붙는 화면
    else:
        sides = ("before", "after")
    for side in sides:
        if all(any(gap_num(body, spans, i, side) == n for i in cand[y]) for y, n in counts.items()):
            return True
    return False


def cut_random(body):
    """무작위 책 띠(class에 discover와 random-books가 든 div)부터 그다음 discover div 앞까지를 뺀다. 띠나 뒤 덩이가 없으면 그대로."""
    divs = []
    for m in re.finditer(r"<div\b[^>]*?(?<![\w-])class=[\"']([^\"']*)[\"']", body, re.I):
        words = m.group(1).split()
        if "discover" in words:
            divs.append((m.start(), "random-books" in words))
    for k, (start, band) in enumerate(divs):
        if band and k + 1 < len(divs):
            return body[:start] + body[divs[k + 1][0]:]
    return body


def url_path(href):
    return urllib.parse.urlsplit(href).path


def e_scenes(cli, libdb, res, notes):
    titles = [r[1] for r in SEED_ROWS]

    def e1():
        return cli.login("admin", cli.pw) and cli.get("/")[0] == 200

    res["E1"] = sidestep(e1, notes, "E1")
    if not res["E1"]:
        for k in ("E2", "E3", "E4", "E5", "E6", "E7"):
            res[k] = False
        notes["E"] = "로그인이 안 돼 E2~E7을 못 걸음"
        return

    def has(path, *words):
        st, _, body = cli.get(path)
        return st == 200 and all(w in body for w in words)

    res["E2"] = sidestep(lambda: has("/", *titles), notes, "E2")
    res["E3"] = sidestep(lambda: has("/book/3", "Winter Letter"), notes, "E3")
    res["E4"] = sidestep(lambda: has("/publisher", "North Press", "South House"), notes, "E4")
    res["E5"] = sidestep(lambda: has("/category", "Poetry"), notes, "E5")
    res["E6"] = sidestep(lambda: has("/admin/book/4", 'name="title"'), notes, "E6")

    def e7():
        if save_book(cli, 4, {"tags": "Essay"}) >= 500:
            return False
        for _ in range(6):
            if "Essay" in tags_of(libdb, 4):
                return True
            time.sleep(0.5)
        return False

    res["E7"] = sidestep(e7, notes, "E7")


def s_scenes(cli, libdb, res, notes):
    def saves(book, value, expect):
        def f():
            st = save_book(cli, book, {"pubdate": value})
            if st >= 500:
                return False
            for _ in range(4):
                if (pubdate_of(libdb, book) or "").startswith(expect):
                    return True
                time.sleep(0.5)
            return False
        return f

    res["S1"] = sidestep(saves(1, "1999", "1999-01-01"), notes, "S1")
    res["S2"] = sidestep(saves(2, "1999-07", "1999-07-01"), notes, "S2")
    res["S3"] = sidestep(saves(3, "2001-02-03", "2001-02-03"), notes, "S3")

    def s4():
        if save_book(cli, 5, {"pubdate": "abc"}) >= 500:
            return False
        return cli.get("/book/5")[0] == 200

    res["S4"] = sidestep(s4, notes, "S4")
    res["S5"] = sidestep(saves(6, "", "0101-01-01"), notes, "S5")


def y_scenes(cli, res, notes):
    by_year = {}
    for _, title, pub, *_rest in SEED_ROWS:
        by_year.setdefault(pub[:4], []).append(title)
    counts = {"1999": 2, "2005": 2, "1987": 1}
    all_titles = [r[1] for r in SEED_ROWS]

    def y1():
        st, _, body = cli.get("/year")
        return st == 200 and year_counts_ok(body, counts)

    def follow(pick):
        st, _, body = cli.get("/year")
        if st != 200:
            return None
        href = pick(_links(body))
        if href is None:
            return None
        p = urllib.parse.urlsplit(href)
        return cli.get(p.path + ("?" + p.query if p.query else ""))

    def pick_year(y):
        def pick(links):
            for h, _t in links:
                if url_path(h).rstrip("/").endswith(y):
                    return h
            for h, t in links:
                if y in t:
                    return h
            return None
        return pick

    def pick_none(links):
        for h, t in links:
            if "None" in t or "없음" in t:
                return h
        return None

    def y2():
        for y, want in ((k, by_year[k]) for k in counts):
            r = follow(pick_year(y))
            if r is None or r[0] != 200:
                return False
            body = cut_random(r[2])
            if not all(t in body for t in want) or any(t in body for t in all_titles if t not in want):
                return False
        return True

    def y3():
        st, _, body = cli.get("/year")
        if st != 200 or "0101" in _text(body):
            return False
        r = follow(pick_none)
        if r is None or r[0] != 200:
            return False
        body = cut_random(r[2])
        return "No Date" in body and not any(t in body for t in all_titles if t != "No Date")

    def y4():
        st, _, body = cli.get("/")
        return st == 200 and any(re.search(r"/year/?$", url_path(h)) for h, _ in _links(body))

    res["Y1"] = sidestep(y1, notes, "Y1")
    res["Y2"] = sidestep(y2, notes, "Y2")
    res["Y3"] = sidestep(y3, notes, "Y3")
    res["Y4"] = sidestep(y4, notes, "Y4")


class _FormInputs(HTMLParser):
    """한 양식 조각 안의 이름 있는 칸들: [(이름, 태그, type)] (input의 type은 소문자 · 없으면 text)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("input", "textarea", "select"):
            return
        a = {k: (v if v is not None else "") for k, v in attrs}
        if a.get("name"):
            self.items.append((a["name"], tag, a.get("type", "text").strip().lower() if tag == "input" else ""))


U_OLD_FIELDS = {"name", "email", "kindle_mail", "locale", "default_language"}
U_NOT_INPUT = {"hidden", "submit", "button", "checkbox", "radio", "file", "password"}
U_SEEDS = [r[1] for r in SEED_ROWS]


def me_form(body):
    """/me 화면에서 name="email" 칸이 든 POST 양식 → (pick_form 결과, 새 칸 이름). 새 칸을 하나로 못 좁히면 WalkError."""
    starts = [m.start() for m in re.finditer(r"<form\b", body, re.I)]
    for i, st_ in enumerate(starts):
        seg = body[st_:(starts[i + 1] if i + 1 < len(starts) else len(body))]
        end = re.search(r"</form\s*>", seg, re.I)
        if end:
            seg = seg[:end.end()]                    # 양식이 닫힌 뒤의 칸은 그 양식의 칸이 아니다
        form = pick_form(seg, "email")
        if form is None:
            continue
        fi = _FormInputs()
        fi.feed(seg)
        fi.close()
        cands = []
        for name, tag, typ in fi.items:
            if name in U_OLD_FIELDS or name in cands:
                continue
            if tag == "input" and typ in U_NOT_INPUT:
                continue
            cands.append(name)
        if len(cands) > 1:
            cands = [n for n in cands if "page" in n.lower()]
        if len(cands) != 1:
            raise WalkError("/me 양식의 새 칸을 하나로 못 고름(후보 %d)" % len(cands))
        return form, cands[0]
    raise WalkError("/me 화면에 email 칸이 든 POST 양식이 없음")


def u_scenes(cli, libdb, res, notes):
    field = []

    def u1():
        st, _, body = cli.get("/me")
        if st != 200:
            raise WalkError("GET /me %s" % st)
        field.append(me_form(body)[1])
        return True

    def save(value):
        st, _, body = cli.get("/me")
        if st != 200:
            raise WalkError("저장 앞 GET /me %s" % st)
        form, name = me_form(body)
        if name != field[0]:
            raise WalkError("저장 앞 화면의 새 칸이 달라짐")
        st, _, _ = cli.post("/me", override(form["pairs"], {name: value}))
        if st >= 500:
            raise WalkError("저장 응답 %s" % st)

    def home():
        st, _, body = cli.get("/")
        if st != 200:
            raise WalkError("GET / %s" % st)
        return body

    def seen(body):
        band_off = cut_random(body)
        return [t for t in U_SEEDS if t in band_off]

    def u2():
        save("2")
        body = home()
        got = seen(body)
        if len(got) != 2:
            raise WalkError("씨앗 제목 %d개" % len(got))
        if not any(url_path(h).endswith("/page/2") for h, _t in _links(body)):
            raise WalkError("/page/2 링크 없음")
        return True

    def u3():
        save("")
        got = seen(home())
        if len(got) != len(U_SEEDS):
            raise WalkError("씨앗 제목 %d개" % len(got))
        return True

    def u4():
        save("1")
        st, _, body = cli.get("/publisher")
        if st != 200:
            raise WalkError("GET /publisher %s" % st)
        href = next((h for h, t in _links(body) if "North Press" in t), None)
        if href is None:
            raise WalkError("North Press 링크 없음")
        p = urllib.parse.urlsplit(href)
        st, _, page = cli.get(p.path + ("?" + p.query if p.query else ""))
        if st != 200:
            raise WalkError("출판사 쪽 %s" % st)
        got = [t for t in ("Sea Song", "Mountain Path") if t in cut_random(page)]
        if len(got) != 1:
            raise WalkError("두 책 가운데 %d개" % len(got))
        return True

    res["U1"] = sidestep(u1, notes, "U1")
    if not res["U1"]:
        for k in ("U2", "U3", "U4"):
            res[k] = False
        notes["U"] = "U1이 안 돼 U2~U4를 못 걸음"
        return
    res["U2"] = sidestep(u2, notes, "U2")
    res["U3"] = sidestep(u3, notes, "U3")
    res["U4"] = sidestep(u4, notes, "U4")


# ---------- prep ----------

def src_repo(S, task):
    return os.path.join(S, task["src"], "repo")


def read_py_deps(pyproject_text):
    m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", pyproject_text, re.S | re.M)
    return [a or b for a, b in re.findall(r""""([^"]+)"|'([^']+)'""", m.group(1))] if m else []


def cmd_prep(cfg, S, R):
    X = work_root(cfg)
    tasks = cfg["tasks"]
    for name in ("src-b", "src-c"):
        if not os.path.isdir(os.path.join(S, name, "repo")):
            raise WalkError("원본 저장소 없음: %s" % os.path.join(S, name, "repo"))
    # 1 바탕 묶음(일감마다 그 일감의 바탕 커밋을 임시 색인으로 꺼내 tar로)
    want = {}
    for tname, t in tasks.items():
        if t.get("tar"):
            key = t["tar"]
            if key in want and want[key][1] != t["base"]:
                raise WalkError("같은 묶음 %s에 바탕 커밋이 둘" % key)
            want[key] = (t, t["base"])
    for rel, (t, base) in sorted(want.items()):
        tar = os.path.join(R, rel)
        mark = tar + ".base"
        if os.path.isfile(tar) and (open(mark).read().strip() if os.path.isfile(mark) else "") == base:
            print("있음: %s" % rel)
            continue
        tmp = os.path.join(R, "bases", ".tmp-" + os.path.basename(rel))
        if os.path.lexists(tmp):
            rm_tree(tmp, os.path.join(R, "bases"))
        extract_commit(src_repo(S, t), base, tmp)
        pack_tar(tmp, tar)
        rm_tree(tmp, os.path.join(R, "bases"))
        write_bytes(mark, (base + "\n").encode())
        print("만듦: %s (%s)" % (rel, base[:8]))
    # 2 숨긴 시험 파일(고침 커밋에서 통째) — sha가 tasks.json과 다르면 멈춤
    for tname in sorted(tasks):
        t = tasks[tname]
        for path, want_sha in (t.get("sealed") or {}).items():
            dst = os.path.join(R, "sealed", tname, path)
            if os.path.isfile(dst) and sha256_file(dst) == want_sha:
                print("있음: sealed/%s/%s" % (tname, path))
                continue
            data = git_show_bytes(src_repo(S, t), t["fix"], path)
            got = hashlib.sha256(data).hexdigest()
            if got != want_sha:
                raise WalkError("숨긴 시험 파일 sha가 tasks.json과 다름(%s %s): %s != %s" % (tname, path, got, want_sha))
            write_bytes(dst, data)
            print("만듦: sealed/%s/%s" % (tname, path))
    # 3 씨앗 서재 · 요구 사항 글
    b = tasks["b1"]
    wk = os.path.join(R, "walkkit")
    lib = os.path.join(wk, "library", "metadata.db")
    if os.path.isfile(lib) and seed_ok(lib):
        print("있음: walkkit/library/metadata.db")
    else:
        raw = os.path.join(wk, ".seed-src.db")
        write_bytes(raw, git_show_bytes(src_repo(S, b), b["base"], "library/metadata.db"))
        years = seed_library(raw, lib, SEED_ROWS)
        os.unlink(raw)
        print("만듦: walkkit/library/metadata.db 연도별 %s" % json.dumps(years, sort_keys=True))
    write_bytes(os.path.join(wk, "req-b.txt"), git_show_bytes(src_repo(S, b), b["base"], "requirements.txt"))
    reqs = []
    for cname in ("c1", "c2"):
        t = tasks[cname]
        lines = git_show_bytes(src_repo(S, t), t["base"], "tests/requirements/py3.txt").decode("utf-8", "replace").splitlines()
        lines += read_py_deps(git_show_bytes(src_repo(S, t), t["base"], "pyproject.toml").decode("utf-8", "replace"))
        for ln in lines:
            ln = ln.strip()
            if ln and not ln.startswith("#") and ln not in reqs:
                reqs.append(ln)
    write_bytes(os.path.join(wk, "req-c.txt"), ("\n".join(reqs) + "\n").encode())
    # 4 설정 db(바탕 코드로 한 번 켜서 만든 뒤 서재 자리만 바꿈)
    venv_b = os.environ.get("STAGE_VENV_B") or os.path.join(S, "venv-b")
    appdb = os.path.join(wk, "app.db")
    if os.path.isfile(appdb):
        print("있음: walkkit/app.db")
    elif not os.path.isfile(os.path.join(venv_b, "bin", "python")):
        print("건너뜀: walkkit/app.db — %s 없음(설치를 한 뒤 prep을 다시)" % venv_b)
    else:
        make_app_db(cfg, R, venv_b, appdb, lib)
        print("만듦: walkkit/app.db")
    # 5 설치 명령 — 찍기만 한다
    D = HERE
    kit = cfg["kit"]
    print("")
    print("# 아래는 메인이 돌린다(이 스크립트는 설치하지 않는다)")
    print("python3 -m venv %s/env/b" % X)
    print("%s/env/b/bin/pip install --only-binary=:all: -r %s/walkkit/req-b.txt" % (X, R))
    print("python3 -m venv %s/env/c" % X)
    print("%s/env/c/bin/pip install --only-binary=:all: -r %s/walkkit/req-c.txt" % (X, R))
    print("mkdir -p %s/env/kit && cp -a %s/. %s/env/kit/" % (X, kit, X))
    print("mkdir -p %s/out-done && { echo \"kit $(bash %s/stage.sh kitsha %s)\"; echo \"copy $(bash %s/stage.sh kitsha %s/env/kit)\"; } > %s/out-done/kit.sha" % (S, D, kit, D, X, S))
    return 0


def app_env(home, extra=None):
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "LC_ALL": "C.UTF-8", "TMPDIR": home,
         "PYTHONDONTWRITEBYTECODE": "1"}
    if extra:
        e.update(extra)
    return e


def make_app_db(cfg, R, venv_b, appdb, lib):
    py = os.path.join(venv_b, "bin", "python")
    src = os.path.join(R, "walkkit", "app-src")
    if os.path.lexists(src):
        rm_tree(src, os.path.join(R, "walkkit"))
    unpack_tar(os.path.join(R, cfg["tasks"]["b1"]["tar"]), src)
    port = cfg["ports"]["walk_base"] + cfg["ports"]["walk_range"] - 1
    if not free_port(port):
        raise WalkError("포트 %d가 이미 열려 있음 — app.db를 못 만듦" % port)
    log = os.path.join(R, "walkkit", "app-first.log")
    home = os.path.join(R, "walkkit", "home")
    os.makedirs(home, exist_ok=True)
    out = open(os.path.join(R, "walkkit", "app-first.out"), "wb")
    p = subprocess.Popen([py, "-B", "cps.py", "-p", appdb, "-o", log, "-i", "127.0.0.1"], cwd=src, env=app_env(home, {"CALIBRE_PORT": str(port)}),
                         start_new_session=True, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    try:
        up = wait_port(port, cfg["walk"]["up_wait"])
    finally:
        done = stop(p, 10)
        out.close()
    if not done:
        raise WalkError("app.db 만들던 앱(pid %d)이 안 꺼짐" % p.pid)
    if not up or not os.path.isfile(appdb):
        raise WalkError("app.db 만들던 앱이 %d초 안에 안 켜짐(로그: %s)" % (cfg["walk"]["up_wait"], log))
    con = sqlite3.connect(appdb)
    try:
        n = con.execute("select count(*) from user").fetchone()[0]
        if n < 1:
            raise WalkError("app.db에 사용자가 없음")
        con.execute("update settings set config_calibre_dir=?", (os.path.dirname(lib),))
        con.commit()
    finally:
        con.close()


# ---------- walk-b ----------

def walk_port(cfg, run, base):
    pc = cfg["ports"]
    if base:
        return pc["base"][base]
    m = re.match(r"^([rxvzwy])(\d+)$", run)
    if not m:
        raise WalkError("걸어 보기 포트를 못 정함: %s" % run)
    if m.group(1) == "y" and not 0 <= int(m.group(2)) <= 19:
        raise WalkError("포트 범위 밖: %s" % run)
    if m.group(1) == "w" and not 1 <= int(m.group(2)) <= 15:
        raise WalkError("포트 범위 밖: %s" % run)
    off = {"r": 0, "z": 60, "x": 20, "v": 40, "y": 70, "w": 24}[m.group(1)]
    p = pc["walk_base"] + off + int(m.group(2))
    if p >= pc["walk_base"] + pc["walk_range"]:
        raise WalkError("포트 범위 밖: %d" % p)
    return p


def cmd_walk_b(cfg, S, R, run, base, sub=None):
    task = base or task_of(cfg, run)
    if task not in ("b1", "b2", "b3"):
        raise WalkError("b 일감이 아님: %s" % (run or base))
    key = "base-" + base if base else run
    result_path = walk_json_path(R, key, sub)
    check_y_sub(run, base, sub)
    if not base:
        check_first_ruler_open(R, run, sub)
    port = walk_port(cfg, run, base)
    for need in (os.path.join(R, "bases", "b.tar"), os.path.join(R, "walkkit", "app.db"), os.path.join(R, "walkkit", "library", "metadata.db")):
        if not os.path.isfile(need):
            raise WalkError("준비가 안 됨(prep 먼저): %s" % need)
    venv_b = os.environ.get("STAGE_VENV_B") or os.path.join(S, "venv-b")
    py = os.path.join(venv_b, "bin", "python")
    if not os.path.isfile(py):
        raise WalkError("venv-b 없음: %s" % py)
    if not free_port(port):
        raise WalkError("포트 %d가 이미 열려 있음 — 걷지 않음" % port)
    seed_lib = os.path.join(R, "walkkit", "library", "metadata.db")
    seed_sha = sha256_file(seed_lib)
    root = os.path.join(R, "walk")
    d = os.path.join(root, (sub + "-" if sub is not None else "") + key)
    if os.path.lexists(d):
        rm_tree(d, root)
    os.makedirs(d)
    w = os.path.join(d, "w")
    if base:
        unpack_tar(os.path.join(R, "bases", "b.tar"), w)
        init_copy(w)
    else:
        src = os.path.join(S, "done", run, "w")
        if not os.path.isdir(src):
            raise WalkError("끝난 사본 없음: %s" % src)
        clone_done(src, w)
    lib_dir = os.path.join(d, "lib")
    shutil.copytree(os.path.join(R, "walkkit", "library"), lib_dir)
    appdb = os.path.join(d, "app.db")
    shutil.copyfile(os.path.join(R, "walkkit", "app.db"), appdb)
    con = sqlite3.connect(appdb)
    try:
        con.execute("update settings set config_port=?, config_calibre_dir=?", (port, lib_dir))
        con.commit()
    finally:
        con.close()
    libdb = os.path.join(lib_dir, "metadata.db")
    pw = secrets.token_urlsafe(12) + "Aa1!"
    home = os.path.join(d, "home")
    os.makedirs(home)
    env = app_env(home)
    log = os.path.join(d, "cw.log")
    step = cfg["walk"]["step_cap"]
    rc, out = run_cmd([py, "-B", "cps.py", "-p", appdb, "-o", log, "-s", "admin:" + pw], cwd=w, env=env, timeout=step)
    res, notes = {}, {}
    scenes = cfg["tasks"][task]["scenes"]
    if rc != 0:
        notes["password"] = "-s 단계가 %d로 끝남" % rc
        up = False
    else:
        outf = open(os.path.join(d, "app.out"), "wb")
        p = subprocess.Popen([py, "-B", "cps.py", "-p", appdb, "-o", log, "-i", "127.0.0.1"], cwd=w, env=env, start_new_session=True,
                             stdout=outf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        try:
            up = wait_up("http://127.0.0.1:%d/login" % port, cfg["walk"]["up_wait"])
            if up:
                cli = Client("http://127.0.0.1:%d" % port)
                cli.pw = pw
                e_scenes(cli, libdb, res, notes)
                if task == "b1":
                    s_scenes(cli, libdb, res, notes)
                elif task == "b3":
                    u_scenes(cli, libdb, res, notes)
                else:
                    y_scenes(cli, res, notes)
        finally:
            stopped = stop(p, 10)
            outf.close()
        if not stopped:
            raise WalkError("앱(pid %d)이 안 꺼짐" % p.pid)
    if not up:
        notes.setdefault("up", "서버가 %d초 안에 안 켜짐" % cfg["walk"]["up_wait"])
    for s in scenes:
        res.setdefault(s, False)
    for _ in range(30):
        if free_port(port):
            break
        time.sleep(0.5)
    else:
        raise WalkError("앱을 끈 뒤에도 포트 %d가 안 비워짐" % port)
    if sha256_file(seed_lib) != seed_sha:
        raise WalkError("씨앗 서재(walkkit/library/metadata.db)가 걷는 사이 바뀜 — 이 걸음은 무효")
    out_obj = {s: res[s] for s in scenes}
    out_obj["notes"] = notes
    write_json(result_path, out_obj)
    for s in scenes:
        print("%s %s" % (s, "true" if out_obj[s] else "false"))
    for k, v in notes.items():
        print("메모 %s: %s" % (k, v))
    return 0


# ---------- check-c ----------

def run_runtests(py, copy, names, env_extra, cap, logpath, exclude=None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.path.join(os.path.dirname(copy), "home"), "LC_ALL": "C.UTF-8",
           "PYTHONPATH": str(copy), "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": os.path.join(os.path.dirname(copy), "home")}
    env.update(env_extra or {})
    os.makedirs(env["HOME"], exist_ok=True)
    rc, out = run_cmd([py, "runtests.py"] + list(names) + ["--parallel", "1"], cwd=os.path.join(copy, "tests"), env=env, timeout=cap)
    with open(logpath, "w", encoding="utf-8") as f:
        f.write(out)
    r = parse_runtests(out)
    r["rc"] = rc
    r["excluded"] = []
    if exclude:
        drop_hidden(r, out, exclude)
    return r, out


def drop_hidden(r, out, hidden):
    """부분 시험 결과에서 숨긴 시험의 실패를 뺀다(Django runtests는 이름으로 뺄 수 없어 결과에서 뺀다 — 숨긴 시험은 따로 한 번 돌린다).
    남은 실패가 없고 FAILED 줄의 수가 뺀 수와 맞으면 ok. 하나도 안 돌았으면(ran 0) 그대로 둔다."""
    keys = {h.split(".")[-1]: h for h in hidden}
    nf = ne = 0
    for fm in re.finditer(r"^(FAIL|ERROR): (\S+) \(([\w.]+)\)", out, re.M):
        name, paren = fm.group(2), fm.group(3)
        full = paren if paren.endswith("." + name) else paren + "." + name
        if full in hidden or (name in keys and full == keys[name]):
            if fm.group(1) == "FAIL":
                nf += 1
            else:
                ne += 1
            if full in r["failed"]:
                r["failed"].remove(full)
            if full not in r["excluded"]:
                r["excluded"].append(full)
    r["failures"] = max(0, r["failures"] - nf)
    r["errors"] = max(0, r["errors"] - ne)
    if "unexpected successes=" in out:
        return                                              # FAILED 괄호에 뜻밖의 성공이 있으면 ok로 올리지 않는다
    if r["ran"] > 0 and not r["ok"] and r["failures"] == 0 and r["errors"] == 0 and (nf or ne) and not r["failed"]:
        r["ok"] = True


SAFE_SCRIPT = r'''
import json, sys
import django
from django.conf import settings
settings.configure(USE_I18N=False)
django.setup()
from django.db import models
from django.contrib.admin.utils import display_for_field
from django.utils.html import escape
res = []
for v in json.loads(sys.argv[1]):
    r = str(display_for_field(v, models.URLField(), "-"))
    res.append("<a" not in r.lower() and escape(v) in r)
print("SAFE_RESULT " + json.dumps(res))
'''


def safe_check(py, copy, values, cap):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.path.join(os.path.dirname(copy), "home"), "LC_ALL": "C.UTF-8",
           "PYTHONPATH": str(copy), "PYTHONDONTWRITEBYTECODE": "1"}
    rc, out = run_cmd([py, "-c", SAFE_SCRIPT, json.dumps(values)], cwd=str(copy), env=env, timeout=min(cap, 300))
    m = re.search(r"^SAFE_RESULT (\[.*\])\s*$", out, re.M)
    if rc != 0 or not m:
        return False, out.strip()[-200:]
    got = json.loads(m.group(1))
    return bool(got) and all(got), ""


def cmd_check_c(cfg, S, R, run, base, with_fix, sub=None):
    check_y_sub(run, base, sub)
    task = base or task_of(cfg, run)
    if task not in ("c1", "c2"):
        raise WalkError("c 일감이 아님: %s" % (run or base))
    t = cfg["tasks"][task]
    key = ("base-%s%s" % (task, "-fix" if with_fix else "")) if base else run
    tar = os.path.join(R, t["tar"])
    sealed = {p: os.path.join(R, "sealed", task, p) for p in (t.get("sealed") or {})}
    for need in [tar] + list(sealed.values()):
        if not os.path.isfile(need):
            raise WalkError("준비가 안 됨(prep 먼저): %s" % need)
    venv_c = os.environ.get("STAGE_VENV_C") or os.path.join(S, "venv-c")
    py = os.path.join(venv_c, "bin", "python")
    if not os.path.isfile(py):
        raise WalkError("venv-c 없음: %s" % py)
    root = os.path.join(R, "walk")
    d = os.path.join(root, (sub + "-" if sub is not None else "") + key)
    if os.path.lexists(d):
        rm_tree(d, root)
    os.makedirs(d)
    copy = os.path.join(d, "w")
    if base:
        unpack_tar(tar, copy)
        init_copy(copy)
        if with_fix:
            rc, patch = run_bytes(GITBASE + ["--git-dir", git_dir_of(src_repo(S, t)), "diff", t["base"], t["fix"], "--", "django/"], env=git_env(), timeout=120)
            if rc != 0 or not patch.strip():
                raise WalkError("고침 패치를 못 뽑음")
            git_in(copy, "apply", "--whitespace=nowarn", "-", input_bytes=patch)
    else:
        src = os.path.join(S, "done", run, "w")
        if not os.path.isdir(src):
            raise WalkError("끝난 사본 없음: %s" % src)
        clone_done(src, copy)
    cap = cfg["walk"]["step_cap"]
    logs = os.path.join(d, "runtests-%s.log")
    before, out1 = run_runtests(py, copy, t["part"], None, cap, logs % "part-before")
    for rel, srcf in sealed.items():
        shutil.copyfile(srcf, os.path.join(copy, rel))
    hidden, out2 = run_runtests(py, copy, t["hidden"], None, cap, logs % "hidden")
    after, out3 = run_runtests(py, copy, t["part"], None, cap, logs % "part-after", t["hidden"])
    m = re.search(r"Django installed in '([^']+)'", out2) or re.search(r"Django installed in '([^']+)'", out1)
    in_copy = None
    if m:
        in_copy = os.path.realpath(m.group(1)).startswith(os.path.realpath(copy) + os.sep)
    obj = {"part_before": before, "hidden": hidden, "part_after": after, "safe_different": False, "django_in_copy": in_copy}
    if t.get("safe_values") and not hidden["ok"]:
        ok, note = safe_check(py, copy, t["safe_values"], cap)
        obj["safe_different"] = ok
        if note:
            obj["safe_note"] = note
    write_json(os.path.join(out_dir(R, sub), key + ".hidden.json"), obj)
    for step in ("part_before", "hidden", "part_after"):
        r = obj[step]
        print("%s ran=%d ok=%s failures=%d errors=%d failed=%s" % (step, r["ran"], r["ok"], r["failures"], r["errors"], r["failed"][:5]))
    print("django_in_copy=%s safe_different=%s" % (in_copy, obj["safe_different"]))
    return 0


# ---------- blank-a · tests-a ----------

A_SCENES = {"a1": ["A1", "A2", "A3", "A4", "A5"], "a2": ["P1", "P2", "P3", "P4", "P5"], "a3": ["L1", "L2", "L3", "L4", "L5"]}
A_FLAGS = ["안켜짐", "시험없음", "시험실패", "API로 걸음", "안내파일없음", "noise_committed"]


def a_scenes(cfg, task):
    if task in A_SCENES:
        return A_SCENES[task]
    t = cfg["tasks"].get(task) if task else None
    if t and t.get("stage") == "a":
        return list(t.get("scenes") or [])
    raise WalkError("a 일감이 아님: %s" % task)


def blank_a(cfg, R, run, sub=None):
    check_y_sub(run, None, sub)
    task = task_of(cfg, run)
    scenes = a_scenes(cfg, task)
    path = walk_json_path(R, run, sub) if sub is not None else os.path.join(R, "out-done", run + ".walk.json")
    if os.path.exists(path):
        return False
    obj = {s: None for s in scenes}
    for k in A_FLAGS:
        obj[k] = None
    obj["notes"] = {}
    if sub is not None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, obj)
    return True


SUB_RE = re.compile(r"[a-z0-9]+")


def out_dir(R, sub=None):
    if sub is None:
        return os.path.join(R, "out-done")
    if not SUB_RE.fullmatch(sub):
        raise WalkError("--sub 이름이 틀림: %r" % sub)
    return os.path.join(R, "out-done", sub)


def walk_json_path(R, run, sub=None):
    return os.path.join(out_dir(R, sub), run + ".walk.json")


def check_first_ruler_open(R, run, sub):
    """--sub 없이 r 걸음을 부르는데 둘째 자 폴더가 이미 있으면, 첫째 자 값을 덮지 않게 아무것도 쓰기 전에 멈춘다."""
    if sub is None and run and run.startswith("r") and os.path.isdir(os.path.join(R, "out-done", "ruler2")):
        raise WalkError("첫째 자 값은 얼렸다 — --sub ruler2 로 부른다")


Y_SUB = "kit09"


def check_y_sub(run, base, sub):
    """w·y 실행과 b3 바탕은 값 폴더 kit09 로만 부른다 — 어기면 아무것도 쓰기 전에 멈춘다."""
    if (run and re.match(r"^[wy]\d+$", run)) or base == "b3":
        if sub != Y_SUB:
            raise WalkError("w·y 실행과 b3 바탕은 --sub %s 로 부른다" % Y_SUB)


def update_walk(R, run, updates, notes=None, sub=None):
    path = walk_json_path(R, run, sub)
    obj = read_json(path) or {"notes": {}}
    obj.update(updates)
    if notes:
        obj.setdefault("notes", {}).update(notes)
    write_json(path, obj)


def cmd_tests_a(cfg, S, R, run, sub=None):
    task = task_of(cfg, run)
    a_scenes(cfg, task)
    wpath = walk_json_path(R, run, sub)
    if sub is not None and not os.path.isfile(wpath):
        raise WalkError("둘째 자 폴더에 walk.json이 없음 — 1차 파일을 먼저 복사: %s" % wpath)
    check_y_sub(run, None, sub)
    check_first_ruler_open(R, run, sub)
    src = os.path.join(S, "done", run, "w")
    if not os.path.isdir(src):
        raise WalkError("끝난 사본 없음: %s" % src)
    if sub is None:
        blank_a(cfg, R, run)
    root = os.path.join(R, "walk")
    d = os.path.join(root, (sub + "-" if sub is not None else "") + run + "-tests")
    if os.path.lexists(d):
        rm_tree(d, root)
    os.makedirs(d)
    w = os.path.join(d, "w")
    clone_done(src, w)
    if sub is not None:  # 복사해 온 1차 메모가 이 걸음의 메모와 섞이지 않게(clone이 된 뒤에야 sub 파일을 건드림)
        obj = read_json(wpath)
        if isinstance(obj, dict) and isinstance(obj.get("notes"), dict):
            for k in ("cmd", "rc", "install", "pytest", "unittest", "cmd_error"):
                obj["notes"].pop(k, None)
            write_json(wpath, obj)
    tracked = [p for p in git_in(w, "ls-files", "-z").split("\0") if p]
    noisy = [p for p in tracked if any(("/%s/" % n) in ("/" + p) for n in NOISE_DIRS)]
    for dirpath, dirs, _files in os.walk(w):
        if ".git" in dirs:
            dirs.remove(".git")
        for n in list(dirs):
            if n in NOISE_DIRS:
                rm_tree(os.path.join(dirpath, n), w)
                dirs.remove(n)
    files = [p for p in git_in(w, "ls-files", "-z").split("\0") if p and os.path.isfile(os.path.join(w, p))]
    updates, notes = {"noise_committed": len(noisy)}, {}
    pats = cfg.get("testfiles") or TESTFILES
    tests = [p for p in files if is_test_file(p, pats)]
    if not tests:
        updates.update({"시험없음": True, "시험실패": False})
        update_walk(R, run, updates, notes, sub)
        print("시험없음=true 시험실패=false noise_committed=%d" % len(noisy))
        return 0
    updates["시험없음"] = False
    texts = {}
    for n in ("README.md", "README", "readme.md", "README.txt", "package.json", "pyproject.toml"):
        p = os.path.join(w, n)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                texts[n] = f.read()
    cmd = detect_test_cmd(texts, tests)
    notes["cmd"] = " ".join(cmd)
    home = os.path.join(d, "home")
    os.makedirs(home)
    env = app_env(home, {"PIP_ONLY_BINARY": ":all:", "PIP_REQUIRE_VIRTUALENV": "1", "npm_config_ignore_scripts": "true", "npm_config_audit": "false",
                         "npm_config_fund": "false", "npm_config_update_notifier": "false"})
    inst, step = cfg["walk"]["install_cap"], cfg["walk"]["step_cap"]
    failed_install = False
    try:
        if cmd[0] == "node":
            if os.path.isfile(os.path.join(w, "package.json")):
                rc, out = run_cmd(["npm", "install"], cwd=w, env=env, timeout=inst)
                failed_install = rc != 0
        elif cmd[0] == "npm":
            rc, out = run_cmd(["npm", "install"], cwd=w, env=env, timeout=inst)
            failed_install = rc != 0
        else:
            venv = os.path.join(d, "venv")
            rc, out = run_cmd(["python3", "-m", "venv", venv], cwd=w, env=env, timeout=inst)
            vpy = os.path.join(venv, "bin", "python")
            failed_install = rc != 0
            if not failed_install and os.path.isfile(os.path.join(w, "requirements.txt")):
                rc, out = run_cmd([vpy, "-m", "pip", "install", "-r", "requirements.txt"], cwd=w, env=env, timeout=inst)
                failed_install = rc != 0
            if not failed_install and "pytest" in cmd:
                rc, out = run_cmd([vpy, "-c", "import pytest"], cwd=w, env=env, timeout=60)
                if rc != 0:
                    rc, out = run_cmd([vpy, "-m", "pip", "install", "pytest"], cwd=w, env=env, timeout=inst)
                    failed_install = rc != 0
            cmd = [vpy] + cmd[1:]
        if failed_install:
            updates["시험실패"] = None
            notes["install"] = "설치가 실패해 시험을 못 돌림 — 손으로 판정"
        else:
            rc, out = run_cmd(cmd, cwd=w, env=env, timeout=step)
            if cmd[1:3] == ["-m", "pytest"] and rc == 5:
                updates["시험실패"] = None
                notes["pytest"] = "모은 시험 0(끝 값 5) — 못 잼"
            elif cmd[1:3] == ["-m", "unittest"] and (rc == 5 or (rc == 0 and re.search(r"(?m)^Ran 0 tests", out))):
                updates["시험실패"] = None
                notes["unittest"] = "돌린 시험 0 — 못 잼"
            else:
                updates["시험실패"] = rc != 0
            notes["rc"] = rc
    except OSError:
        updates["시험실패"] = None
        notes["cmd_error"] = "명령을 못 띄움 — 못 잼"
    update_walk(R, run, updates, notes, sub)
    print("시험없음=false 시험실패=%s noise_committed=%d cmd=%s" % (updates["시험실패"], len(noisy), notes["cmd"]))
    return 0


# ---------- 진입 ----------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("인자 틀림: %s\n" % message)
        sys.exit(2)


def build_parser():
    ap = _Parser(prog="stage-walk.py")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True

    def common(p):
        p.add_argument("--root", default=None, help="무대 뿌리(기본 S)")

    p = sub.add_parser("prep")
    common(p)
    p = sub.add_parser("walk-b")
    common(p)
    p.add_argument("run", nargs="?")
    p.add_argument("--base", choices=["b1", "b2", "b3"])
    p.add_argument("--sub", default=None)
    p = sub.add_parser("check-c")
    common(p)
    p.add_argument("run", nargs="?")
    p.add_argument("--base", choices=["c1", "c2"])
    p.add_argument("--with-fix", action="store_true")
    p.add_argument("--sub", default=None)
    for n in ("blank-a", "tests-a"):
        p = sub.add_parser(n)
        common(p)
        p.add_argument("run")
        p.add_argument("--sub", default=None)
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if getattr(a, "sub", None) is not None and not SUB_RE.fullmatch(a.sub):
        ap.error("--sub는 [a-z0-9]+만")
    if a.cmd in ("blank-a", "check-c") and getattr(a, "sub", None) not in (None, Y_SUB):
        ap.error("%s의 --sub는 %s만" % (a.cmd, Y_SUB))
    if a.cmd in ("walk-b", "check-c"):
        if bool(a.run) == bool(a.base):
            ap.error("%s는 <run> 또는 --base 중 하나만" % a.cmd)
        if a.cmd == "check-c" and a.with_fix and not a.base:
            ap.error("--with-fix는 --base와 함께만")
    try:
        cfg = load_cfg()
        S = stage_root(cfg)
        R = a.root or S
        if a.cmd == "prep":
            return cmd_prep(cfg, S, R)
        if a.cmd == "walk-b":
            return cmd_walk_b(cfg, S, R, a.run, a.base, sub=a.sub)
        if a.cmd == "check-c":
            return cmd_check_c(cfg, S, R, a.run, a.base, a.with_fix, sub=a.sub)
        if a.cmd == "blank-a":
            made = blank_a(cfg, R, a.run, sub=a.sub)
            print("만듦: %s" % (walk_json_path(R, a.run, a.sub) if a.sub is not None else "%s/out-done/%s.walk.json" % (R, a.run)) if made else "이미 있음 — 그대로 둠")
            return 0
        if a.cmd == "tests-a":
            return cmd_tests_a(cfg, S, R, a.run, sub=a.sub)
    except WalkError as e:
        sys.stderr.write("멈춤: %s\n" % e)
        return 3 if any(w in str(e) for w in ("안 비워짐", "안 꺼짐", "무효", "이미 열려")) else 2
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
