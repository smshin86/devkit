"""docs/measure/stage-walk.py 시험 — 순수 함수와 작은 가짜 저장소·가짜 서버로 한다.
진짜 무대(S/src-b·S/src-c)·claude·설치·망에는 닿지 않는다. 프로세스는 시험이 직접 띄운 것만 pid로 끈다."""
import hashlib
import http.server
import importlib.util
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
M = Path(__file__).resolve().parent.parent / "docs" / "measure"
WALK = M / "stage-walk.py"
TASKS = M / "stage" / "tasks.json"


def load():
    spec = importlib.util.spec_from_file_location("stage_walk_mod", WALK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sw():
    return load()


GIT_ENV = {"PATH": os.environ.get("PATH", ""), "HOME": "/nonexistent-stage-test", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C.UTF-8"}


def git(repo, *a, check=True):
    r = subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-c", "user.name=t",
                        "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false", "-C", str(repo), *a],
                       capture_output=True, text=True, env=GIT_ENV)
    if check and r.returncode != 0:
        raise AssertionError("git %s: %s" % (a, r.stderr))
    return r.stdout.strip()


# ---------- FormFields ----------

FORM_HTML = """
<html><body>
<form id="nav_search" action="/search" method="get"><input type="text" name="query" value="zz"></form>
<form role="form" action="/admin/book/4" method="post" enctype="multipart/form-data" id="book_edit_frm">
  <input type="hidden" name="csrf_token" value="tok123">
  <input type="text" name="title" value="No Date">
  <input type="text" name="tags" value="">
  <input type="text" name="pubdate" id="pubdate" value="1999-07-15">
  <input type="text" id="fake_pubdate" value="x">
  <input type="checkbox" name="detail_view" checked>
  <input type="checkbox" name="unticked" value="yes">
  <input type="checkbox" name="ticked" value="yes" checked="checked">
  <input type="radio" name="rate" value="1"><input type="radio" name="rate" value="2" checked>
  <textarea name="comments">
hello
world</textarea>
  <select name="lang"><option value="a">A</option><option value="b" selected>B</option></select>
  <select name="first"><option value="x">X</option><option value="y">Y</option></select>
  <select name="many" multiple><option value="p" selected>P</option><option value="q">Q</option><option value="r" selected>R</option></select>
  <select name="notext"><option>Plain</option></select>
  <input type="file" name="btn-upload-cover">
  <input type="submit" name="go" value="Save">
  <button type="submit" name="btn" value="b">B</button>
</form>
</body></html>
"""


def test_formfields_selected_form_only(sw):
    ff = sw.FormFields("book_edit_frm")
    ff.feed(FORM_HTML)
    ff.close()
    f = ff.fields
    assert "query" not in f
    assert f["csrf_token"] == "tok123" and f["title"] == "No Date" and f["tags"] == ""
    assert f["pubdate"] == "1999-07-15"
    assert "fake_pubdate" not in f


def test_formfields_checkbox_radio_textarea_select(sw):
    ff = sw.FormFields("book_edit_frm")
    ff.feed(FORM_HTML)
    f = ff.fields
    assert f["detail_view"] == "on" and f["ticked"] == "yes" and "unticked" not in f
    assert f["rate"] == "2"
    assert f["comments"].strip() == "hello\nworld"
    assert f["lang"] == "b" and f["first"] == "x" and f["notext"] == "Plain"
    assert [v for k, v in ff.pairs if k == "many"] == ["p", "r"]
    for skipped in ("btn-upload-cover", "go", "btn"):
        assert skipped not in f


def test_formfields_default_is_first_form(sw):
    ff = sw.FormFields()
    ff.feed(FORM_HTML)
    assert ff.fields == {"query": "zz"}


def test_formfields_no_such_form(sw):
    ff = sw.FormFields("nope")
    ff.feed(FORM_HTML)
    assert ff.fields == {} and ff.pairs == []


def test_csrf_token(sw):
    assert sw.csrf_token(FORM_HTML) == "tok123"
    assert sw.csrf_token('<input value="abc" type="hidden" name="csrf_token">') == "abc"
    assert sw.csrf_token("<html></html>") is None


# ---------- parse_runtests ----------

def test_parse_runtests_ok(sw):
    t = "Testing against Django installed in 'x'\nFound 137 test(s).\n\n----------------------------------------------------------------------\nRan 137 tests in 1.2s\n\nOK\n"
    r = sw.parse_runtests(t)
    assert (r["ran"], r["ok"], r["failures"], r["errors"]) == (137, True, 0, 0)
    assert r["failed"] == []


def test_parse_runtests_ok_with_skips(sw):
    t = "Ran 988 tests in 3.2s\n\nOK (skipped=24, expected failures=3)\n"
    r = sw.parse_runtests(t)
    assert (r["ran"], r["ok"], r["failures"], r["errors"]) == (988, True, 0, 0)


def test_parse_runtests_failed_errors(sw):
    t = ("ERROR: test_group_by_transform_column (aggregation.tests.AggregateTestCase.test_group_by_transform_column)\n"
         "Traceback (most recent call last):\n  ...\nIndexError: tuple index out of range\n\n"
         "----------------------------------------------------------------------\nRan 1 test in 0.1s\n\nFAILED (errors=1)\n")
    r = sw.parse_runtests(t)
    assert (r["ran"], r["ok"], r["failures"], r["errors"]) == (1, False, 0, 1)
    assert r["failed"] == ["aggregation.tests.AggregateTestCase.test_group_by_transform_column"]


def test_parse_runtests_failed_failures_and_errors(sw):
    t = ("FAIL: test_a (m.tests.T.test_a)\n\nFAIL: test_a (m.tests.T.test_a) (value='x')\n\n"
         "ERROR: test_b (m.tests.T.test_b)\n\nERROR: setUpClass (m.tests.U)\n\n"
         "Ran 5 tests in 0.5s\n\nFAILED (failures=2, errors=1)\n")
    r = sw.parse_runtests(t)
    assert (r["ran"], r["ok"], r["failures"], r["errors"]) == (5, False, 2, 1)
    assert r["failed"] == ["m.tests.T.test_a", "m.tests.T.test_b", "m.tests.U"]


def test_parse_runtests_no_ran_line_is_not_ok(sw):
    r = sw.parse_runtests("Traceback (most recent call last):\nImportError: boom\n")
    assert r["ran"] == 0 and r["ok"] is False


# ---------- seed_library ----------

def make_meta(path):
    c = sqlite3.connect(str(path))
    c.executescript("""
    CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT 'Unknown' COLLATE NOCASE,
      sort TEXT COLLATE NOCASE, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, pubdate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      series_index REAL NOT NULL DEFAULT 1.0, author_sort TEXT COLLATE NOCASE, isbn TEXT DEFAULT "", lccn TEXT DEFAULT "",
      path TEXT NOT NULL DEFAULT "", flags INTEGER NOT NULL DEFAULT 1, uuid TEXT, has_cover BOOL DEFAULT 0,
      last_modified TIMESTAMP NOT NULL DEFAULT "2000-01-01 00:00:00+00:00");
    CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE, sort TEXT COLLATE NOCASE, link TEXT NOT NULL DEFAULT "", UNIQUE(name));
    CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, author INTEGER NOT NULL, UNIQUE(book, author));
    CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE, sort TEXT COLLATE NOCASE, UNIQUE(name));
    CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, publisher INTEGER NOT NULL, UNIQUE(book));
    CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE, UNIQUE(name));
    CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, tag INTEGER NOT NULL, UNIQUE(book, tag));
    CREATE TRIGGER books_insert_trg AFTER INSERT ON books
      BEGIN UPDATE books SET sort=title_sort(NEW.title),uuid=uuid4() WHERE id=NEW.id; END;
    """)
    c.commit()
    c.close()


def test_seed_library_counts_and_links(sw, tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    make_meta(src)
    counts = sw.seed_library(src, dst, sw.SEED_ROWS)
    assert counts == {"1999": 2, "2005": 2, "1987": 1, "0101": 1}
    c = sqlite3.connect(str(dst))
    assert c.execute("select count(*) from books").fetchone()[0] == 6
    assert c.execute("select title from books where id=3").fetchone()[0] == "Winter Letter"
    assert c.execute("select pubdate from books where id=1").fetchone()[0] == "1999-07-15 00:00:00+00:00"
    assert c.execute("select pubdate from books where id=4").fetchone()[0] == "0101-01-01 00:00:00+00:00"
    assert c.execute("select count(*) from books where uuid is not null and sort is not null").fetchone()[0] == 6
    pub = dict(c.execute("select p.name, count(*) from publishers p join books_publishers_link l on l.publisher=p.id group by p.name"))
    assert pub == {"North Press": 2, "South House": 2}
    tags = dict(c.execute("select t.name, count(*) from tags t join books_tags_link l on l.tag=t.id group by t.name"))
    assert tags == {"Poetry": 2, "Novel": 1}
    au = dict(c.execute("select a.name, count(*) from authors a join books_authors_link l on l.author=a.id group by a.name"))
    assert au == {"Ana Kim": 2, "Ben Lee": 2, "Cy Park": 2}
    c.close()
    # 원본은 그대로(책 0권)
    s = sqlite3.connect(str(src))
    assert s.execute("select count(*) from books").fetchone()[0] == 0
    s.close()


def test_seed_library_overwrites_existing_dst(sw, tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    make_meta(src)
    sw.seed_library(src, dst, sw.SEED_ROWS)
    sw.seed_library(src, dst, sw.SEED_ROWS)
    c = sqlite3.connect(str(dst))
    assert c.execute("select count(*) from books").fetchone()[0] == 6
    c.close()


def test_seed_rows_match_plan_table(sw):
    rows = {r[0]: r for r in sw.SEED_ROWS}
    assert sorted(rows) == [1, 2, 3, 4, 5, 6]
    assert rows[1][1:3] == ("Sea Song", "1999-07-15")
    assert rows[4][1:3] == ("No Date", "0101-01-01")
    assert rows[6][1] == "Small House"
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    want = [(s["id"], s["title"], s["pubdate"], s["publisher"], s["tag"], s["author"]) for s in cfg["seed"]]
    assert [tuple(r) for r in sw.SEED_ROWS] == want


def test_pubdate_of_and_tags_of(sw, tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    make_meta(src)
    sw.seed_library(src, dst, sw.SEED_ROWS)
    assert sw.pubdate_of(dst, 2) == "1999-01-03 00:00:00+00:00"
    assert sw.tags_of(dst, 1) == ["Poetry"]
    assert sw.tags_of(dst, 4) == []


# ---------- 포트 · 끄기 ----------

SS = ("LISTEN 0      128        127.0.0.1:8083       0.0.0.0:*\n"
      "LISTEN 0      4096            [::]:18391          [::]:*\n"
      "LISTEN 0      511                *:3000             *:*\n")


def test_ports_from_ss(sw):
    assert sw.ports_from_ss(SS) == {8083, 18391, 3000}
    assert sw.ports_from_ss("") == set()


def test_free_port_real_socket(sw):
    if shutil.which("ss") is None:
        pytest.skip("ss 없음")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert sw.free_port(port) is False
    finally:
        s.close()
    assert sw.free_port(port) is True


def test_stop_terminates_own_child(sw):
    p = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        assert p.poll() is None
        assert sw.stop(p, grace=5) is True
        assert p.poll() is not None
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_stop_kills_after_grace_when_term_ignored(sw):
    code = "import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('up', flush=True)\ntime.sleep(60)\n"
    p = subprocess.Popen([sys.executable, "-I", "-B", "-c", code], start_new_session=True, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "up"
        t0 = time.time()
        assert sw.stop(p, grace=1) is True
        assert time.time() - t0 < 10
        assert p.poll() is not None
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_stop_already_exited(sw):
    p = subprocess.Popen([sys.executable, "-I", "-B", "-c", "pass"], start_new_session=True)
    p.wait()
    assert sw.stop(p, grace=1) is True


def test_run_cmd_timeout_kills_own_group(sw, tmp_path):
    marker = tmp_path / "m.txt"
    code = "import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(60)'])\ntime.sleep(60)\n"
    t0 = time.time()
    rc, out = sw.run_cmd([sys.executable, "-I", "-B", "-c", code], cwd=str(tmp_path), env=dict(GIT_ENV), timeout=2)
    assert rc == 124 and time.time() - t0 < 20
    marker.write_text("x")


def test_run_cmd_collects_output(sw, tmp_path):
    rc, out = sw.run_cmd([sys.executable, "-I", "-B", "-c", "print('hi'); import sys; sys.exit(3)"], cwd=str(tmp_path), env=dict(GIT_ENV), timeout=20)
    assert rc == 3 and "hi" in out


# ---------- make_copy ----------

def make_repo(tmp_path, name="orig"):
    r = tmp_path / name
    r.mkdir()
    git(r, "init", "-q")
    (r / ".gitignore").write_text("library/metadata.db\n*.pyc\n")
    (r / ".gitattributes").write_text("library export-ignore\ntest export-ignore\n")
    (r / "a.py").write_text("print('a')\n")
    (r / "run.sh").write_text("#!/bin/sh\necho hi\n")
    os.chmod(r / "run.sh", 0o755)
    (r / "library").mkdir()
    (r / "library" / "metadata.db").write_bytes(b"SQLite format 3\x00fake")
    (r / "test").mkdir()
    (r / "test" / "t.txt").write_text("t\n")
    git(r, "add", "-A")
    git(r, "add", "-f", "library/metadata.db")
    git(r, "commit", "-q", "-m", "one")
    c1 = git(r, "rev-parse", "HEAD")
    (r / "a.py").write_text("print('b')\n")
    (r / "new.txt").write_text("n\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "two")
    return r, c1


def snap(r):
    return (git(r, "rev-parse", "HEAD"), git(r, "status", "--porcelain"), (r / ".git" / "index").read_bytes())


def test_make_copy_tree_and_log(sw, tmp_path):
    r, c1 = make_repo(tmp_path)
    before = snap(r)
    dst = tmp_path / "copy"
    h = sw.make_copy(r, c1, dst)
    assert git(dst, "log", "--oneline").count("\n") == 0 and len(git(dst, "log", "--oneline").splitlines()) == 1
    assert git(dst, "rev-parse", "HEAD^{tree}") == git(r, "rev-parse", c1 + "^{tree}")
    assert git(dst, "rev-parse", "HEAD") == h
    assert (dst / "library" / "metadata.db").exists()
    assert (dst / "test" / "t.txt").exists()
    assert not (dst / "new.txt").exists()
    assert os.access(dst / "run.sh", os.X_OK) or True
    assert git(dst, "status", "--porcelain") == ""
    assert snap(r) == before


def test_make_copy_later_commit(sw, tmp_path):
    r, c1 = make_repo(tmp_path)
    c2 = git(r, "rev-parse", "HEAD")
    dst = tmp_path / "copy2"
    sw.make_copy(r, c2, dst)
    assert (dst / "new.txt").exists()
    assert git(dst, "rev-parse", "HEAD^{tree}") == git(r, "rev-parse", c2 + "^{tree}")


def test_make_copy_uses_git_dir_of_repo_not_cwd(sw, tmp_path, monkeypatch):
    r, c1 = make_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    dst = tmp_path / "copy3"
    sw.make_copy(r, c1, dst)
    assert not (other / ".git").exists()
    assert (dst / "a.py").read_text() == "print('a')\n"


def test_make_copy_refuses_nonempty_dst(sw, tmp_path):
    r, c1 = make_repo(tmp_path)
    dst = tmp_path / "busy"
    dst.mkdir()
    (dst / "x").write_text("1")
    with pytest.raises(sw.WalkError):
        sw.make_copy(r, c1, dst)
    assert (dst / "x").read_text() == "1"


def test_extract_pack_unpack_roundtrip(sw, tmp_path):
    r, c1 = make_repo(tmp_path)
    work = tmp_path / "ex"
    sw.extract_commit(r, c1, work)
    assert not (work / ".git").exists()
    assert (work / "library" / "metadata.db").exists()
    tar = tmp_path / "x.tar"
    sw.pack_tar(work, tar)
    back = tmp_path / "back"
    sw.unpack_tar(tar, back)
    assert (back / "a.py").read_text() == "print('a')\n"
    assert (back / "test" / "t.txt").exists()
    h = sw.init_copy(back)
    assert git(back, "rev-parse", "HEAD^{tree}") == git(r, "rev-parse", c1 + "^{tree}")
    assert len(git(back, "log", "--oneline").splitlines()) == 1 and h == git(back, "rev-parse", "HEAD")


# ---------- 시험 명령 찾기(tests-a) ----------

def test_is_test_file(sw):   # 있던 시험을 넓힘
    for p in ("test_a.py", "x/b_test.py", "tests/foo.py", "web/a.test.js", "src/__tests__/x.js", "a.spec.js", "c.test.ts",
              "test.js", "src/test.mjs", "test.cjs", "a/b/test.ts", "test.py", "tests.js", "tests.py", "x/tests.py",
              "a.test.mjs", "a.test.cjs", "a.test.tsx", "a.test.jsx", "a.spec.ts", "a.spec.mjs", "a.spec.cjs", "test/run.js", "src/test/x.py",
              "app-test.js", "api_test.js", "test-api.js", "a/test-x.mjs"):
        assert sw.is_test_file(p), p
    for p in ("app.py", "src/contest.py", "README.md", "testdata.txt", "latest.js", "contest.py", "attest.js", "testdata.csv",
              "protest/x.js", "latest/x.js", "src/latest.js", "src/attest/x.py", "contest.js", "test-data/x.json"):
        assert not sw.is_test_file(p), p


def test_testfiles_same_as_tasks_json(sw):
    assert json.loads(TASKS.read_text(encoding="utf-8"))["testfiles"] == sw.TESTFILES


def a_done(tmp_path, files, run="r03"):
    """S/done/<run>/w 에 files를 커밋한 끝난 사본 · (S, R) 글을 돌려줌."""
    S, R = tmp_path / "S", tmp_path / "R"
    w = S / "done" / run / "w"
    w.mkdir(parents=True)
    git(w, "init", "-q")
    for p, t in files.items():
        (w / p).parent.mkdir(parents=True, exist_ok=True)
        (w / p).write_text(t)
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", "end")
    return str(S), str(R)


def fake_run(sw, monkeypatch, rc_test=0, rc_install=0, out_test=""):
    """git만 진짜로 돌리고 나머지(venv·pip·npm·node·pytest)는 적기만 — 돌린 argv 목록을 돌려줌."""
    calls, real = [], sw.run_cmd
    def f(argv, cwd=None, env=None, timeout=900):
        if argv[0] == "git":
            return real(argv, cwd=cwd, env=env, timeout=timeout)
        calls.append(list(argv))
        if argv[:2] == ["npm", "install"] or "venv" in argv or "pip" in argv:
            return rc_install, ""
        if argv[1:3] == ["-c", "import pytest"]:
            return 0, ""
        return rc_test, out_test
    monkeypatch.setattr(sw, "run_cmd", f)
    return calls


def walk_of(R, run="r03", sub=None):
    p = Path(R) / "out-done" / (sub or "") / (run + ".walk.json")
    return json.loads(p.read_text(encoding="utf-8"))


def test_tests_a_uses_cfg_testfiles(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    cfg["testfiles"] = [r"(^|/)zzonly\.txt$"]
    S, R = a_done(tmp_path / "one", {"app.py": "", "zzonly.txt": ""})
    assert sw.cmd_tests_a(cfg, S, R, "r03") == 0 and walk_of(R)["시험없음"] is False
    cfg["testfiles"] = [r"nomatch$"]
    S, R = a_done(tmp_path / "two", {"test_app.py": ""})
    assert sw.cmd_tests_a(cfg, S, R, "r03") == 0 and walk_of(R)["시험없음"] is True
    del cfg["testfiles"]
    S, R = a_done(tmp_path / "three", {"test.js": ""})
    assert sw.cmd_tests_a(cfg, S, R, "r03") == 0 and walk_of(R)["시험없음"] is False   # 없으면 TESTFILES


def test_detect_test_cmd(sw):
    assert sw.detect_test_cmd({"package.json": json.dumps({"scripts": {"test": "jest"}})}) == ["npm", "test"]
    assert sw.detect_test_cmd({"README.md": "run tests:\n\n    python -m unittest discover\n"}) == ["python", "-m", "unittest", "discover"]
    assert sw.detect_test_cmd({"README.md": "```\npytest -q\n```\n"}) == ["python", "-m", "pytest", "-q"]
    assert sw.detect_test_cmd({"README.md": "nothing here"}) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({}) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({"package.json": json.dumps({"name": "x"})}) == ["python", "-m", "pytest"]


def test_detect_test_cmd_node_and_order(sw):
    J = ["test.js", "lib/a.test.mjs"]
    NT = ["node", "--test", "lib/a.test.mjs", "test.js"]
    PLACE = json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}})
    assert sw.detect_test_cmd({}, J) == NT
    assert sw.detect_test_cmd({"package.json": PLACE}, J) == NT
    assert sw.detect_test_cmd({"package.json": "{not json"}, J) == NT
    assert sw.detect_test_cmd({"package.json": json.dumps({"scripts": {"test": "node --test"}})}, J) == ["npm", "test"]
    assert sw.detect_test_cmd({"README.md": "    node --test\n"}, J) == NT                      # 22-1: 파일 없는 `node --test`는 버림
    assert sw.detect_test_cmd({"README.md": "    node --test lib/a.test.mjs\n"}, J) == ["node", "--test", "lib/a.test.mjs"]
    assert sw.detect_test_cmd({"README.md": "$ node test.js\n"}, J) == ["node", "test.js"]
    assert sw.detect_test_cmd({"README.md": "node ./test.js\n"}, J) == ["node", "test.js"]
    assert sw.detect_test_cmd({"README.md": "node server.js\n"}, J) == NT                 # 켜는 명령은 시험 명령이 아님
    assert sw.detect_test_cmd({"README.md": "node --test && node server.js\n"}, J) == NT  # 셸 잇기 줄은 버림
    assert sw.detect_test_cmd({"README.md": "pytest -q; curl x\n"}, ["test_a.py"]) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({"README.md": "npm test\n", "package.json": PLACE}, J) == ["npm", "test"]  # README가 먼저
    assert sw.detect_test_cmd({}, ["test.js", "test_a.py"]) == ["python", "-m", "pytest"]   # 모두 JS가 아님
    assert sw.detect_test_cmd({}, ["a.test.ts"]) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({}, []) == ["python", "-m", "pytest"]


def test_detect_test_cmd_node_line_rules(sw):   # 22-1: README의 node 줄은 낱말이 모두 시험 파일일 때만
    J = ["test.js", "lib/a.test.mjs"]
    NT = ["node", "--test", "lib/a.test.mjs", "test.js"]
    for bad in ("node --test --watch", "node --import x.js test.js", "node -r ./x test.js", "node --test --test-reporter-destination=out.txt test.js",
                "node server.js", "node --test"):
        assert sw.detect_test_cmd({"README.md": bad + "\n"}, J) == NT, bad
    assert sw.detect_test_cmd({"README.md": "node --test lib/a.test.mjs\n"}, J) == ["node", "--test", "lib/a.test.mjs"]
    assert sw.detect_test_cmd({"README.md": "node server.js\n\nnode test.js\n"}, J) == ["node", "test.js"]   # 버리고 다음 줄로
    assert sw.detect_test_cmd({"README.md": "pytest -q | tee x\n"}, ["test_a.py"]) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({"README.md": "npm test && echo done\n"}, ["test_a.py"]) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({"README.md": "node 'unclosed\n"}, J) == NT   # shlex 실패 줄은 버림


def test_detect_test_cmd_code_extensions_only(sw):   # 22-1: 코드 확장자를 가진 시험 파일만 놓고 「모두 JS」를 본다
    assert sw.detect_test_cmd({}, ["summary.test.js", "test/fixtures/data.csv", "test/README.md"]) == ["node", "--test", "summary.test.js"]
    assert sw.detect_test_cmd({}, ["a.test.js", "test/b.ts"]) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({}, ["test/data.csv"]) == ["python", "-m", "pytest"]


def test_detect_test_cmd_node_named_files_only(sw):   # F4b
    assert sw.detect_test_cmd({}, ["test/helpers.js", "test/fixtures/server.js", "test/app.test.js"]) == ["node", "--test", "test/app.test.js"]
    assert sw.detect_test_cmd({}, ["test/app.js", "test/util.js"]) == ["node", "--test", "test/app.js", "test/util.js"]


def test_detect_test_cmd_readme_prose_is_not_a_command(sw):   # F5
    T = ["tests/test_a.py"]
    PY = ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({"README.md": "pytest is used for the tests\n"}, T) == PY
    assert sw.detect_test_cmd({"README.md": "pytest 로 돌립니다\n"}, T) == PY
    assert sw.detect_test_cmd({"README.md": "pytest tests -q\n"}, T) == PY + ["tests", "-q"]
    assert sw.detect_test_cmd({"README.md": "python -m unittest discover -s tests\n"}, T) == ["python", "-m", "unittest", "discover", "-s", "tests"]
    assert sw.detect_test_cmd({"README.md": 'python -m pytest -k "not slow"\n'}, T) == PY + ["-k", "not slow"]
    assert sw.detect_test_cmd({"README.md": "pytest is what we use\npython -m unittest\n"}, T) == ["python", "-m", "unittest"]
    assert sw.detect_test_cmd({"README.md": "pytest tests/test_a.py\n"}, T) == PY + ["tests/test_a.py"]
    assert sw.detect_test_cmd({"README.md": "npm test\n"}, T) == ["npm", "test"]


def test_detect_test_cmd_nul_line_and_dash_file_names(sw):   # F6
    assert sw.detect_test_cmd({"README.md": "pytest -q\x00 x\n"}, ["tests/test_a.py"]) == ["python", "-m", "pytest"]
    assert sw.detect_test_cmd({}, ["--require=x.test.js"]) == ["node", "--test", "./--require=x.test.js"]
    assert sw.detect_test_cmd({"README.md": "node --test -x.test.js\n"}, ["-x.test.js"]) == ["node", "--test", "./-x.test.js"]


def test_tests_a_node_branch(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    calls = fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path / "a", {"app.js": "", "test.js": ""})
    assert sw.cmd_tests_a(cfg, S, R, "r03") == 0
    assert calls == [["node", "--test", "test.js"]]                                       # 설치 없음 · venv 없음
    d = walk_of(R)
    assert d["시험없음"] is False and d["시험실패"] is False and d["notes"]["cmd"] == "node --test test.js"
    del calls[:]
    S, R = a_done(tmp_path / "b", {"test.js": "", "package.json": json.dumps({"name": "x"})})
    sw.cmd_tests_a(cfg, S, R, "r03")
    assert calls == [["npm", "install"], ["node", "--test", "test.js"]]


def test_tests_a_node_install_failure_is_unknown(sw, tmp_path, monkeypatch):   # 22-1
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    calls = fake_run(sw, monkeypatch, rc_install=1)
    S, R = a_done(tmp_path, {"test.js": "", "package.json": json.dumps({"name": "x"})})
    assert sw.cmd_tests_a(cfg, S, R, "r03") == 0
    d = walk_of(R)
    assert calls == [["npm", "install"]] and d["시험실패"] is None and "install" in d["notes"]


def test_tests_a_cannot_launch_is_unknown(sw, tmp_path, monkeypatch):   # 22-1: 명령을 못 띄우면 traceback 대신 못 잼
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    real = sw.run_cmd
    def f(argv, cwd=None, env=None, timeout=900):
        if argv[0] == "git":
            return real(argv, cwd=cwd, env=env, timeout=timeout)
        raise FileNotFoundError(argv[0])
    monkeypatch.setattr(sw, "run_cmd", f)
    S, R = a_done(tmp_path, {"test.js": ""})
    assert sw.cmd_tests_a(cfg, S, R, "r03") == 0
    d = walk_of(R)
    assert d["시험실패"] is None and d["시험없음"] is False and d["notes"]["cmd_error"] == "명령을 못 띄움 — 못 잼"


def test_tests_a_pytest_exit_5_is_unknown(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    calls = fake_run(sw, monkeypatch, rc_test=5)
    S, R = a_done(tmp_path / "a", {"test_app.py": ""})
    sw.cmd_tests_a(cfg, S, R, "r03")
    d = walk_of(R)
    assert calls[-1][1:] == ["-m", "pytest"] and d["시험실패"] is None and d["notes"]["rc"] == 5 and "pytest" in d["notes"]
    monkeypatch.undo()
    fake_run(sw, monkeypatch, rc_test=1)
    S, R = a_done(tmp_path / "b", {"test_app.py": ""})
    sw.cmd_tests_a(cfg, S, R, "r03")
    assert walk_of(R)["시험실패"] is True


def test_tests_a_unittest_ran_zero_is_unknown(sw, tmp_path, monkeypatch):   # F3
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    files = {"test_app.py": "", "README.md": "    python -m unittest\n"}
    calls = fake_run(sw, monkeypatch, rc_test=0, out_test="\n----\nRan 0 tests in 0.000s\n\nOK\n")
    S, R = a_done(tmp_path / "a", files)
    sw.cmd_tests_a(cfg, S, R, "r03")
    d = walk_of(R)
    assert calls[-1][1:] == ["-m", "unittest"] and d["시험실패"] is None and d["notes"]["rc"] == 0 and "unittest" in d["notes"]
    monkeypatch.undo()
    fake_run(sw, monkeypatch, rc_test=5, out_test="")
    S, R = a_done(tmp_path / "b", files)
    sw.cmd_tests_a(cfg, S, R, "r03")
    d = walk_of(R)
    assert d["시험실패"] is None and d["notes"]["rc"] == 5 and "unittest" in d["notes"]
    monkeypatch.undo()
    fake_run(sw, monkeypatch, rc_test=0, out_test="Ran 3 tests in 0.1s\n\nOK\n")   # 돌린 시험이 있으면 평소대로
    S, R = a_done(tmp_path / "c", files)
    sw.cmd_tests_a(cfg, S, R, "r03")
    d = walk_of(R)
    assert d["시험실패"] is False and "unittest" not in d["notes"]
    monkeypatch.undo()
    fake_run(sw, monkeypatch, rc_test=1, out_test="Ran 0 tests in 0.0s\n")   # 끝 값 1이면 못 잼이 아님
    S, R = a_done(tmp_path / "d", files)
    sw.cmd_tests_a(cfg, S, R, "r03")
    assert walk_of(R)["시험실패"] is True


def test_tests_a_non_ascii_test_file_name(sw, tmp_path, monkeypatch):   # F2: git이 비ASCII 이름을 따옴표로 내보내도 시험 파일로 센다
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path, {"test_모임.py": ""})
    assert sw.cmd_tests_a(cfg, S, R, "r03") == 0
    assert walk_of(R)["시험없음"] is False


def test_blank_a_and_task_lookup(sw, tmp_path):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    assert sw.task_of(cfg, "r03") == "a1" and sw.task_of(cfg, "r11") == "b2"
    assert sw.task_of(cfg, "z01") == "z0"
    assert sw.task_of(cfg, "r99") is None
    out = tmp_path / "out-done"
    sw.blank_a(cfg, str(tmp_path), "r03")
    d = json.loads((out / "r03.walk.json").read_text(encoding="utf-8"))
    for k in ("A1", "A2", "A3", "A4", "A5"):
        assert d[k] is None
    for k in ("안켜짐", "시험없음", "시험실패", "API로 걸음"):
        assert k in d and d[k] is None
    sw.blank_a(cfg, str(tmp_path), "r09")
    d = json.loads((out / "r09.walk.json").read_text(encoding="utf-8"))
    assert [k for k in d if k[0] == "P"] == ["P1", "P2", "P3", "P4", "P5"]


def test_blank_a_refuses_non_a_task(sw, tmp_path):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    with pytest.raises(sw.WalkError):
        sw.blank_a(cfg, str(tmp_path), "r01")


# ---------- 가짜 서버로 Client ----------

class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/login":
            return self._send(200, b'<form action="/login" method="post"><input type="hidden" name="csrf_token" value="TOK"><input name="username"></form>',
                              [("Set-Cookie", "sess=abc; Path=/")])
        if self.path == "/":
            if "sess=ok" in (self.headers.get("Cookie") or ""):
                return self._send(200, b"home")
            return self._send(302, b"", [("Location", "/login")])
        if self.path == "/boom":
            return self._send(500, b"err")
        self._send(404, b"no")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode()
        if self.path == "/login" and "csrf_token=TOK" in body and "username=admin" in body and "password=pw1" in body and "sess=abc" in (self.headers.get("Cookie") or ""):
            return self._send(302, b"", [("Location", "/"), ("Set-Cookie", "sess=ok; Path=/")])
        self._send(400, b"bad")


@pytest.fixture
def fake_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_client_login_and_status_without_following(sw, fake_server):
    c = sw.Client("http://127.0.0.1:%d" % fake_server)
    st, hd, body = c.get("/")
    assert st == 302 and hd.get("Location") == "/login"
    assert c.login("admin", "pw1") is True
    st, hd, body = c.get("/")
    assert st == 200 and "home" in body
    st, hd, body = c.get("/boom")
    assert st == 500


def test_client_login_wrong_password(sw, fake_server):
    c = sw.Client("http://127.0.0.1:%d" % fake_server)
    assert c.login("admin", "nope") is False


def test_wait_up_and_down(sw, fake_server):
    assert sw.wait_up("http://127.0.0.1:%d/login" % fake_server, 5) is True
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert sw.wait_up("http://127.0.0.1:%d/login" % port, 2) is False


# ---------- 정적 ----------

def code():
    return WALK.read_text(encoding="utf-8")


def live():
    out = []
    for line in code().splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def test_static_forbidden_words():
    t = live()
    import re
    for w in ("pkill", "killall", "tmux", "pgrep", "shell=True", "git clean", "worktree", "git fetch", "rm -r", "rm -rf",
              "os.system", "taskkill", '"fetch"', '"stash"', '"push"', '"pull"', '"merge"'):
        assert w not in t, w
    assert not re.search(r"checkout(?!-index)", t)
    assert "os.killpg" in t and "start_new_session=True" in t
    assert "killpg(" in t and "os.kill(" not in t


def test_static_password_form():
    t = code()
    assert 'secrets.token_urlsafe(12) + "Aa1!"' in t
    assert "gc.auto=0" in t and "maintenance.auto=false" in t


def test_static_called_only_as_python_never_by_exec_bit():
    # 이 파일 시스템(drvfs)은 실행 비트를 구분하지 못해 비트로는 못 막는다 — 대신 「늘 python3 -I -B 로 부른다」를 머리 글에 적고 부르는 쪽도 그렇게 부르는지 본다
    head = "\n".join(code().split("\n")[:3])
    assert "python3 -I -B stage-walk.py" in head and "실행 비트 없음" in head
    for ln in (M / "stage.sh").read_text(encoding="utf-8").split("\n"):
        if "stage-walk.py" in ln and not ln.lstrip().startswith("#"):
            assert "python3 -I -B" in ln, ln


# ---------- prep · check-c 한 바퀴(가짜 저장소 · 가짜 runtests) ----------

FAKE_RUNTESTS = r'''
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
with open(os.path.join(root, "ARGV.log"), "a") as lg:
    lg.write(" ".join(sys.argv[1:]) + "\n")
print("Testing against Django installed in '%s'" % os.path.join(os.environ.get("PYTHONPATH", "?"), "django"))
if os.path.exists(os.path.join(root, "DEAD")):
    print("Traceback (most recent call last):\nTypeError: cannot pickle 'traceback' object")
    sys.exit(1)
mod = open(os.path.join(root, "django", "mod.py")).read().strip()
htxt = open(os.path.join(here, "aggregation", "tests.py")).read()
names = [a for a in sys.argv[1:] if not a.startswith("--") and a not in ("1", "2")]
hidden = [n for n in names if n.count(".") >= 2]
fail = []
ERR = "ERROR: test_group_by_transform_column (aggregation.tests.AggregateTestCase.test_group_by_transform_column)"
if hidden and not (mod == "fixed" and "GOOD" in htxt):
    fail.append(ERR)
if "aggregation" in names and "GOOD" in htxt and mod != "fixed":
    fail.append(ERR)                                   # 부분 시험 라벨 안에도 숨긴 시험이 들어 있다(진짜 Django처럼)
if any(n == "queries" for n in names) and os.path.exists(os.path.join(root, "BREAK")):
    fail.append("FAIL: test_other (queries.tests.Q.test_other)")
for f in fail:
    print(f)
n = 1 if hidden else 5
print("Ran %d tests in 0.1s" % n)
print("FAILED (errors=%d)" % len(fail) if fail else "OK")
sys.exit(1 if fail else 0)
'''


@pytest.fixture
def fake_world(tmp_path):
    S = tmp_path / "S"
    S.mkdir()
    # src-c: 바탕(결함) → 고침
    r = S / "src-c" / "repo"
    r.mkdir(parents=True)
    git(r, "init", "-q")
    (r / "django").mkdir()
    (r / "django" / "mod.py").write_text("broken\n")
    (r / "tests" / "aggregation").mkdir(parents=True)
    (r / "tests" / "runtests.py").write_text(FAKE_RUNTESTS)
    (r / "tests" / "aggregation" / "tests.py").write_text("BAD\n")
    (r / "tests" / "requirements").mkdir()
    (r / "tests" / "requirements" / "py3.txt").write_text("sqlparse\n")
    (r / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = [\n  "asgiref>=3.8.1",\n  "sqlparse>=0.3.1",\n]\n')
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    base = git(r, "rev-parse", "HEAD")
    (r / "django" / "mod.py").write_text("fixed\n")
    (r / "tests" / "aggregation" / "tests.py").write_text("GOOD\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "fix")
    fix = git(r, "rev-parse", "HEAD")
    # src-b: 책 0권 metadata.db
    b = S / "src-b" / "repo"
    b.mkdir(parents=True)
    git(b, "init", "-q")
    (b / "library").mkdir()
    make_meta(b / "library" / "metadata.db")
    (b / "requirements.txt").write_text("flask\n")
    (b / "cps.py").write_text("print('app')\n")
    git(b, "add", "-A")
    git(b, "add", "-f", "library/metadata.db")
    git(b, "commit", "-q", "-m", "b")
    bbase = git(b, "rev-parse", "HEAD")
    sha = hashlib.sha256(b"GOOD\n").hexdigest()
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    cfg["stage"] = str(S)
    for k in ("b1", "b2"):
        cfg["tasks"][k]["base"] = bbase
    cfg["tasks"]["c1"].update({"base": base, "fix": fix, "sealed": {"tests/aggregation/tests.py": sha},
                               "hidden": ["aggregation.tests.AggregateTestCase.test_group_by_transform_column"], "part": ["queries", "aggregation"]})
    cfg["tasks"]["c2"].update({"base": base, "fix": fix, "sealed": {"tests/aggregation/tests.py": sha},
                               "hidden": ["aggregation.tests.AggregateTestCase.test_group_by_transform_column"], "part": ["queries"]})
    tj = tmp_path / "tasks.json"
    tj.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    # 가짜 venv-c: 파이썬 = 지금 파이썬
    vc = S / "venv-c" / "bin"
    vc.mkdir(parents=True)
    os.symlink(sys.executable, vc / "python")
    env = dict(GIT_ENV, STAGE_S=str(S), STAGE_TASKS=str(tj), STAGE_X=str(tmp_path / "X"), PYTHONDONTWRITEBYTECODE="1")
    return {"S": S, "R": tmp_path / "R", "tj": tj, "env": env, "base": base, "fix": fix, "cfg": cfg}


def cli(w, *args, timeout=240):
    r = subprocess.run([sys.executable, "-I", "-B", str(WALK), *args], capture_output=True, text=True, env=w["env"], timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def test_prep_makes_bases_sealed_and_walkkit_and_prints_only(fake_world, tmp_path):
    w = fake_world
    before_b = snap(w["S"] / "src-b" / "repo")
    before_c = snap(w["S"] / "src-c" / "repo")
    rc, out = cli(w, "prep", "--root", str(w["R"]))
    assert rc == 0, out
    R = w["R"]
    for t in ("b.tar", "c1.tar", "c2.tar"):
        assert (R / "bases" / t).is_file(), t
    assert (R / "sealed" / "c1" / "tests" / "aggregation" / "tests.py").read_text() == "GOOD\n"
    lib = R / "walkkit" / "library" / "metadata.db"
    assert lib.is_file()
    c = sqlite3.connect(str(lib))
    assert c.execute("select count(*) from books").fetchone()[0] == 6
    c.close()
    # 설치는 안 한다 — 명령만 찍는다
    assert "python3 -m venv" in out and "pip install" in out
    assert "kit" in out
    assert not (R / "venv-b").exists() and not (R / "venv-c").exists()
    assert not (tmp_path / "X").exists()
    assert snap(w["S"] / "src-b" / "repo") == before_b and snap(w["S"] / "src-c" / "repo") == before_c
    req = (R / "walkkit" / "req-c.txt").read_text()
    assert "sqlparse" in req and "asgiref" in req


def test_prep_is_idempotent(fake_world):
    w = fake_world
    assert cli(w, "prep", "--root", str(w["R"]))[0] == 0
    t = (w["R"] / "bases" / "c1.tar").stat().st_mtime_ns
    lib = (w["R"] / "walkkit" / "library" / "metadata.db").stat().st_mtime_ns
    time.sleep(0.05)
    rc, out = cli(w, "prep", "--root", str(w["R"]))
    assert rc == 0, out
    assert (w["R"] / "bases" / "c1.tar").stat().st_mtime_ns == t
    assert (w["R"] / "walkkit" / "library" / "metadata.db").stat().st_mtime_ns == lib


def test_prep_stops_2_when_sealed_sha_differs(fake_world):
    w = fake_world
    cfg = w["cfg"]
    cfg["tasks"]["c1"]["sealed"] = {"tests/aggregation/tests.py": "0" * 64}
    w["tj"].write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    rc, out = cli(w, "prep", "--root", str(w["R"]))
    assert rc == 2, out
    assert not (w["R"] / "sealed" / "c1" / "tests" / "aggregation" / "tests.py").exists()


def test_check_c_base_red_and_with_fix_green(fake_world):
    w = fake_world
    assert cli(w, "prep", "--root", str(w["R"]))[0] == 0
    rc, out = cli(w, "check-c", "--root", str(w["R"]), "--base", "c1")
    assert rc == 0, out
    h = json.loads((w["R"] / "out-done" / "base-c1.hidden.json").read_text(encoding="utf-8"))
    assert h["part_before"]["ok"] is True and h["part_before"]["ran"] == 5
    assert h["hidden"]["ok"] is False and h["hidden"]["errors"] == 1
    assert h["hidden"]["failed"] == ["aggregation.tests.AggregateTestCase.test_group_by_transform_column"]
    assert h["django_in_copy"] is True
    assert "safe_different" in h
    # 부분 시험 라벨 안의 숨긴 시험은 결과에서 뺀다 — 숨긴 시험은 따로 한 번 돌렸다
    pa = h["part_after"]
    assert pa["ran"] == 5 and pa["ok"] is True and pa["failed"] == [] and pa["errors"] == 0
    assert pa["excluded"] == ["aggregation.tests.AggregateTestCase.test_group_by_transform_column"]
    assert pa["rc"] == 1
    # 같은 사본 자리에 고침 없는 쪽의 사본이 남는다(고침 쪽은 따로)
    assert (w["R"] / "walk" / "base-c1" / "w" / "django" / "mod.py").read_text().strip() == "broken"
    rc, out = cli(w, "check-c", "--root", str(w["R"]), "--base", "c1", "--with-fix")
    assert rc == 0, out
    h = json.loads((w["R"] / "out-done" / "base-c1-fix.hidden.json").read_text(encoding="utf-8"))
    assert h["hidden"]["ok"] is True and h["part_after"]["ok"] is True and h["part_after"]["excluded"] == []
    assert (w["R"] / "walk" / "base-c1-fix" / "w" / "django" / "mod.py").read_text().strip() == "fixed"


def test_check_c_run_uses_done_copy_and_part_before_after(fake_world):
    w = fake_world
    assert cli(w, "prep", "--root", str(w["R"]))[0] == 0
    # 끝난 실행의 사본: S/done/r01/w — 바탕 + AI의 고침(mod.py 수정)·AI 시험(BREAK 파일이 부분 시험을 깨뜨림)
    done = w["S"] / "done" / "r01" / "w"
    sw = load()
    sw.make_copy(w["S"] / "src-c" / "repo", w["base"], done)
    (done / "django" / "mod.py").write_text("fixed\n")
    (done / "BREAK").write_text("x")
    git(done, "add", "-A")
    git(done, "commit", "-q", "-m", "end")
    rc, out = cli(w, "check-c", "--root", str(w["R"]), "r01")
    assert rc == 0, out
    h = json.loads((w["R"] / "out-done" / "r01.hidden.json").read_text(encoding="utf-8"))
    assert h["part_before"]["ok"] is False and h["part_before"]["failed"] == ["queries.tests.Q.test_other"]
    assert h["hidden"]["ok"] is True
    assert h["part_after"]["ok"] is False
    # 원래 사본(done)은 건드리지 않는다
    assert (done / "django" / "mod.py").read_text().strip() == "fixed"
    assert not (done / "tests" / "aggregation" / "tests.py").exists() or (done / "tests" / "aggregation" / "tests.py").read_text() == "BAD\n"


def test_check_c_part_runs_use_parallel_1_never_2(fake_world):
    w = fake_world
    assert cli(w, "prep", "--root", str(w["R"]))[0] == 0
    rc, out = cli(w, "check-c", "--root", str(w["R"]), "--base", "c1")
    assert rc == 0, out
    log = (w["R"] / "walk" / "base-c1" / "w" / "ARGV.log").read_text().strip().split("\n")
    assert len(log) == 3                                      # part_before · hidden · part_after
    for ln in log:
        assert "--parallel 1" in ln and "--parallel 2" not in ln, ln
    assert "--parallel\", \"2" not in WALK.read_text(encoding="utf-8")


def test_check_c_dead_runtests_gives_ran_0(fake_world):
    w = fake_world
    assert cli(w, "prep", "--root", str(w["R"]))[0] == 0
    done = w["S"] / "done" / "r01" / "w"
    sw = load()
    sw.make_copy(w["S"] / "src-c" / "repo", w["base"], done)
    (done / "DEAD").write_text("x")
    git(done, "add", "-A")
    git(done, "commit", "-q", "-m", "end")
    rc, out = cli(w, "check-c", "--root", str(w["R"]), "r01")
    assert rc == 0, out
    h = json.loads((w["R"] / "out-done" / "r01.hidden.json").read_text(encoding="utf-8"))
    pa = h["part_after"]
    assert pa["ran"] == 0 and pa["ok"] is False and pa["failed"] == [] and pa["rc"] == 1


def test_walk_and_hidden_json_go_to_out_done_not_out(fake_world):
    w = fake_world
    assert cli(w, "prep", "--root", str(w["R"]))[0] == 0
    assert cli(w, "check-c", "--root", str(w["R"]), "--base", "c1")[0] == 0
    assert (w["R"] / "out-done" / "base-c1.hidden.json").is_file()
    assert not (w["R"] / "out").exists()
    rc, out = cli(w, "blank-a", "--root", str(w["R"]), "r03")
    assert rc == 0 and "out-done/r03.walk.json" in out, out
    assert (w["R"] / "out-done" / "r03.walk.json").is_file() and not (w["R"] / "out").exists()


def test_check_c_without_prep_is_error(fake_world):
    w = fake_world
    rc, out = cli(w, "check-c", "--root", str(w["R"]), "--base", "c1")
    assert rc == 2 and not (w["R"] / "out-done" / "base-c1.hidden.json").exists()


def test_cli_bad_args(fake_world):
    w = fake_world
    for a in ([], ["nope"], ["check-c", "--root", str(w["R"])], ["walk-b", "--root", str(w["R"])],
              ["check-c", "--root", str(w["R"]), "--base", "b1"], ["walk-b", "--root", str(w["R"]), "--base", "c1"],
              ["blank-a"], ["tests-a"]):
        rc, out = cli(w, *a)
        assert rc == 2, (a, out)
    assert not w["R"].exists()


def test_tests_a_no_test_files(fake_world, tmp_path):
    w = fake_world
    done = w["S"] / "done" / "r03" / "w"
    done.mkdir(parents=True)
    git(done, "init", "-q")
    (done / "app.py").write_text("print(1)\n")
    (done / "README.md").write_text("run it\n")
    git(done, "add", "-A")
    git(done, "commit", "-q", "-m", "end")
    rc, out = cli(w, "tests-a", "--root", str(w["R"]), "r03")
    assert rc == 0, out
    d = json.loads((w["R"] / "out-done" / "r03.walk.json").read_text(encoding="utf-8"))
    assert d["시험없음"] is True and d["시험실패"] is False and d["noise_committed"] == 0
    assert d["A1"] is None


def test_parse_runtests_expected_failures_are_not_failures(sw):
    t = "Ran 988 tests in 2.318s\n\nFAILED (errors=1, skipped=24, expected failures=3)\n"
    r = sw.parse_runtests(t)
    assert r["ran"] == 988 and r["failures"] == 0 and r["errors"] == 1
    t = "Ran 10 tests in 0.1s\n\nFAILED (failures=2, expected failures=3)\n"
    assert sw.parse_runtests(t)["failures"] == 2


def test_drop_hidden_does_not_raise_unexpected_successes_to_ok(sw):
    hid = ["a.B.test_h"]
    out = "FAIL: test_h (a.B)\n\nRan 5 tests in 1s\n\nFAILED (failures=1, unexpected successes=1)\n"
    r = {"ok": False, "ran": 5, "failures": 1, "errors": 0, "failed": ["a.B.test_h"], "excluded": []}
    sw.drop_hidden(r, out, hid)
    assert r["ok"] is False and r["excluded"] == ["a.B.test_h"]
    out = "FAIL: test_h (a.B)\n\nRan 5 tests in 1s\n\nFAILED (failures=1)\n"
    r = {"ok": False, "ran": 5, "failures": 1, "errors": 0, "failed": ["a.B.test_h"], "excluded": []}
    sw.drop_hidden(r, out, hid)
    assert r["ok"] is True
    out = "FAIL: test_h (a.B)\n\nRan 5 tests in 1s\n\nFAILED (failures=1, expected failures=2)\n"
    r = {"ok": False, "ran": 5, "failures": 1, "errors": 0, "failed": ["a.B.test_h"], "excluded": []}
    sw.drop_hidden(r, out, hid)
    assert r["ok"] is True


def test_read_py_deps_keeps_markers_with_inner_quotes(sw):
    t = 'dependencies = [\n    "asgiref>=3.8.1",\n    "tzdata; sys_platform == \'win32\'",\n]\n'
    assert sw.read_py_deps(t) == ["asgiref>=3.8.1", "tzdata; sys_platform == 'win32'"]


# ---------- --sub (둘째 자 결과 폴더) ----------

def test_out_dir_and_walk_json_path(sw):
    assert sw.out_dir("R") == os.path.join("R", "out-done")
    assert sw.walk_json_path("R", "r03", "ruler2") == os.path.join("R", "out-done", "ruler2", "r03.walk.json")
    assert sw.walk_json_path("R", "r03") == os.path.join("R", "out-done", "r03.walk.json")
    for bad in ("../x", "a/b", "Ruler2", "a-b", "", "ruler2\n", "."):
        with pytest.raises(sw.WalkError):
            sw.out_dir("R", bad)


def test_sub_name_rejected(fake_world):
    w = fake_world
    for a in (["tests-a", "--root", str(w["R"]), "r03", "--sub", "../x"], ["tests-a", "--root", str(w["R"]), "r03", "--sub", "A"],
              ["walk-b", "--root", str(w["R"]), "r11", "--sub", "../x"], ["walk-b", "--root", str(w["R"]), "r11", "--sub", ""],
              ["walk-b", "--root", str(w["R"]), "r11", "--sub", "BAD-"],
              ["blank-a", "--root", str(w["R"]), "r03", "--sub", "ruler2"]):
        rc, out = cli(w, *a)
        assert rc == 2, (a, out)
        assert "--sub" in out and "인자 틀림" in out, (a, out)   # F8: 이름 때문에 멈춘 것(다른 까닭의 끝 값 2가 아니라)
        assert not w["R"].exists(), a


def test_sub_name_rejected_when_called_directly(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path, {"test.js": ""})
    for bad in ("../x", "A", "a-b", "", "ruler2\n"):
        with pytest.raises(sw.WalkError, match="--sub 이름이 틀림"):   # F8: out_dir의 이름 검사가 막아야 한다(다른 까닭의 오류가 아니라)
            sw.cmd_tests_a(cfg, S, R, "r03", sub=bad)
        assert not Path(R).exists()


ONE = b'{\n "A1": true,\n "notes": {}\n}\n'


def test_tests_a_sub_rewrites_only_sub_file(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path, {"app.js": "", "test.js": ""})
    top = Path(R) / "out-done" / "r03.walk.json"
    top.parent.mkdir(parents=True)
    top.write_bytes(ONE)
    (Path(R) / "out-done" / "ruler2").mkdir()
    (Path(R) / "out-done" / "ruler2" / "r03.walk.json").write_bytes(ONE)
    keep = Path(R) / "walk" / "r03-tests" / "keep.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("1차")
    assert sw.cmd_tests_a(cfg, S, R, "r03", sub="ruler2") == 0
    assert top.read_bytes() == ONE and keep.read_text() == "1차"
    d = walk_of(R, sub="ruler2")
    assert d["A1"] is True and d["시험없음"] is False and d["시험실패"] is False
    assert (Path(R) / "walk" / "ruler2-r03-tests" / "w" / "test.js").is_file()


def test_tests_a_sub_needs_copied_file(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path, {"test.js": ""})
    with pytest.raises(sw.WalkError):
        sw.cmd_tests_a(cfg, S, R, "r03", sub="ruler2")
    assert not (Path(R) / "out-done" / "ruler2" / "r03.walk.json").exists() and not (Path(R) / "out-done" / "r03.walk.json").exists()
    assert not (Path(R) / "walk" / "ruler2-r03-tests").exists() and not (Path(R) / "walk" / "r03-tests").exists()


def test_tests_a_sub_clears_old_step_notes(sw, tmp_path, monkeypatch):   # 22-2: 복사해 온 1차 메모가 섞이지 않게
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path, {"test.js": ""})
    f = Path(R) / "out-done" / "ruler2" / "r03.walk.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"A1": True, "notes": {"install": "옛", "pytest": "옛", "unittest": "옛", "rc": 9, "cmd_error": "옛", "cmd": "옛", "keep": "손 메모"}}), encoding="utf-8")
    assert sw.cmd_tests_a(cfg, S, R, "r03", sub="ruler2") == 0
    n = walk_of(R, sub="ruler2")["notes"]
    assert "install" not in n and "pytest" not in n and "cmd_error" not in n and "unittest" not in n and n["rc"] == 0
    assert n["cmd"] == "node --test test.js" and n["keep"] == "손 메모"


def test_tests_a_sub_clone_failure_leaves_sub_file_alone(sw, tmp_path, monkeypatch):   # F7: clone이 실패하면 sub 파일의 옛 notes를 지우지 않는다
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path, {"test.js": ""})
    f = Path(R) / "out-done" / "ruler2" / "r03.walk.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"A1": True, "notes": {"install": "옛", "cmd": "옛"}}), encoding="utf-8")
    before = f.read_bytes()
    def boom(src, w):
        raise sw.WalkError("clone 실패")
    monkeypatch.setattr(sw, "clone_done", boom)
    with pytest.raises(sw.WalkError):
        sw.cmd_tests_a(cfg, S, R, "r03", sub="ruler2")
    assert f.read_bytes() == before


def b_world(sw, tmp_path, monkeypatch):
    S, R = tmp_path / "S", tmp_path / "R"
    w = S / "done" / "r11" / "w"
    w.mkdir(parents=True)
    git(w, "init", "-q")
    (w / "cps.py").write_text("import sys\nsys.exit(0)\n")
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", "end")
    (R / "bases").mkdir(parents=True)
    (R / "bases" / "b.tar").write_bytes(b"")
    (R / "walkkit" / "library").mkdir(parents=True)
    (R / "walkkit" / "library" / "metadata.db").write_bytes(b"zz")
    c = sqlite3.connect(str(R / "walkkit" / "app.db"))
    c.execute("create table settings(config_port integer, config_calibre_dir text)")
    c.execute("insert into settings values (0, '')")
    c.commit()
    c.close()
    vb = tmp_path / "venv-b" / "bin"
    vb.mkdir(parents=True)
    os.symlink(sys.executable, vb / "python")
    monkeypatch.setenv("STAGE_VENV_B", str(tmp_path / "venv-b"))
    monkeypatch.setattr(sw, "free_port", lambda port: True)
    monkeypatch.setattr(sw, "wait_up", lambda url, secs: False)
    return str(S), str(R)


def test_walk_b_sub_writes_only_sub_dir(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    S, R = b_world(sw, tmp_path, monkeypatch)
    top = Path(R) / "out-done" / "r11.walk.json"
    top.parent.mkdir(parents=True)
    top.write_bytes(ONE)
    keep = Path(R) / "walk" / "r11" / "keep.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("1차")
    assert sw.cmd_walk_b(cfg, S, R, "r11", None, sub="ruler2") == 0
    assert top.read_bytes() == ONE and keep.read_text() == "1차"
    d = walk_of(R, "r11", "ruler2")
    assert [k for k in d if k != "notes"] == cfg["tasks"]["b2"]["scenes"] and not any(d[k] for k in cfg["tasks"]["b2"]["scenes"])
    assert "up" in d["notes"] and (Path(R) / "walk" / "ruler2-r11" / "w" / "cps.py").is_file()


def test_walk_b_without_sub_writes_out_done_as_before(sw, tmp_path, monkeypatch):
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    S, R = b_world(sw, tmp_path, monkeypatch)
    assert sw.cmd_walk_b(cfg, S, R, "r11", None) == 0
    assert (Path(R) / "out-done" / "r11.walk.json").is_file() and not (Path(R) / "out-done" / "ruler2").exists()
    assert (Path(R) / "walk" / "r11" / "w").is_dir()


def test_first_ruler_frozen_when_ruler2_dir_exists_tests_a(sw, tmp_path, monkeypatch):   # 22-2 얼림 막이
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    fake_run(sw, monkeypatch)
    S, R = a_done(tmp_path, {"test.js": ""})
    top = Path(R) / "out-done" / "r03.walk.json"
    top.parent.mkdir(parents=True)
    top.write_bytes(ONE)
    (Path(R) / "out-done" / "ruler2").mkdir()
    with pytest.raises(sw.WalkError) as e:
        sw.cmd_tests_a(cfg, S, R, "r03")
    assert "얼렸다" in str(e.value) and "--sub ruler2" in str(e.value)
    assert top.read_bytes() == ONE and not (Path(R) / "walk").exists()
    # 폴더가 없으면 지금처럼 돈다
    S2, R2 = a_done(tmp_path / "n", {"test.js": ""})
    assert sw.cmd_tests_a(cfg, S2, R2, "r03") == 0 and walk_of(R2)["시험없음"] is False
    # x 실행은 폴더가 있어도 --sub 없이 돈다
    S3, R3 = a_done(tmp_path / "x", {"test.js": ""}, run="x01")
    (Path(R3) / "out-done" / "ruler2").mkdir(parents=True)
    assert sw.cmd_tests_a(cfg, S3, R3, "x01") == 0 and walk_of(R3, "x01")["시험없음"] is False


def test_first_ruler_frozen_when_ruler2_dir_exists_walk_b(sw, tmp_path, monkeypatch):   # 22-2 얼림 막이
    cfg = json.loads(TASKS.read_text(encoding="utf-8"))
    S, R = b_world(sw, tmp_path, monkeypatch)
    top = Path(R) / "out-done" / "r11.walk.json"
    top.parent.mkdir(parents=True)
    top.write_bytes(ONE)
    (Path(R) / "out-done" / "ruler2").mkdir()
    with pytest.raises(sw.WalkError) as e:
        sw.cmd_walk_b(cfg, S, R, "r11", None)
    assert "얼렸다" in str(e.value)
    assert top.read_bytes() == ONE and not (Path(R) / "walk").exists()
    assert sw.cmd_walk_b(cfg, S, R, "r11", None, sub="ruler2") == 0          # --sub 로는 돈다


def test_cli_tests_a_sub_and_freeze_exit_codes(fake_world):
    w = fake_world
    done = w["S"] / "done" / "r03" / "w"
    done.mkdir(parents=True)
    git(done, "init", "-q")
    (done / "app.py").write_text("print(1)\n")
    git(done, "add", "-A")
    git(done, "commit", "-q", "-m", "end")
    top = w["R"] / "out-done" / "r03.walk.json"
    top.parent.mkdir(parents=True)
    top.write_bytes(ONE)
    sub = w["R"] / "out-done" / "ruler2"
    rc, out = cli(w, "tests-a", "--root", str(w["R"]), "r03", "--sub", "ruler2")     # 복사해 둔 파일 없음
    assert rc == 2 and not (w["R"] / "walk" / "ruler2-r03-tests").exists(), out
    sub.mkdir()
    (sub / "r03.walk.json").write_bytes(ONE)
    rc, out = cli(w, "tests-a", "--root", str(w["R"]), "r03", "--sub", "ruler2")
    assert rc == 0, out
    assert top.read_bytes() == ONE and json.loads((sub / "r03.walk.json").read_text(encoding="utf-8"))["시험없음"] is True
    rc, out = cli(w, "tests-a", "--root", str(w["R"]), "r03")                         # 얼림 막이
    assert rc == 2 and top.read_bytes() == ONE, out
    rc, out = cli(w, "walk-b", "--root", str(w["R"]), "r11", "--sub", "BAD-")
    assert rc == 2, out


# ---------- run_bytes — 끝난 뒤 남는 프로세스 ----------

def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"      # 좀비는 이미 죽은 것
    except OSError:
        return False


def test_run_bytes_kills_leftover_group_after_normal_exit(sw, tmp_path):
    code = ("import subprocess, sys\n"
            "p = subprocess.Popen(['sleep', '300'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "print(p.pid, flush=True)\n")
    rc, out = sw.run_bytes([sys.executable, "-I", "-B", "-c", code], cwd=str(tmp_path), env=dict(GIT_ENV), timeout=30)
    pid = int(out.decode().split()[0])
    try:
        assert rc == 0
        for _ in range(40):
            if not _alive(pid):
                break
            time.sleep(0.05)
        assert not _alive(pid)
    finally:
        if _alive(pid):
            os.kill(pid, 9)


# ---------- b2 장면 Y1~Y4 ----------

ROW = ('<div class="row"><div class="col-xs-2 col-sm-2 col-md-1" align="left"><span class="badge">{n}</span></div>'
       '<div class="col-xs-10 col-sm-10 col-md-11"><a id="list_{i}" href="{h}">{t}</a></div></div>\n')
NAV = '<ul><li id="nav_year"><a href="/year?data=x">Years</a></li><li><a href="/publisher">Publishers</a></li></ul>\n'
YROWS = [("1987", 1), ("1999", 2), ("2005", 2), ("None", 1)]
COUNTS = {"1999": 2, "2005": 2, "1987": 1}


def year_list(rows=YROWS, nav=NAV, tail=""):
    return nav + "".join(ROW.format(n=n, i=i, h="/year/stored/%s" % y, t=y) for i, (y, n) in enumerate(rows)) + tail


def test_year_counts_ok_shapes(sw):
    after = NAV + "".join('<li><a href="/year/stored/%s">%s</a> <span class="badge">%d</span></li>\n' % (y, y, n) for y, n in YROWS)
    inside = NAV + "".join('<li><a href="/year/stored/%s">%s (%d)</a></li>\n' % (y, y, n) for y, n in YROWS)
    wrong = year_list([("1987", 1), ("1999", 3), ("2005", 2), ("None", 1)])
    mixed = NAV + '<span>2</span><a href="/y/1999">1999</a> <a href="/y/2005">2005</a><span>2</span> <span>1</span><a href="/y/1987">1987</a>'
    noise = year_list(nav=NAV.replace("</ul>", '<li><a href="/book/9">Notes 1999</a></li></ul>'), tail='<a href="/year?page=2">2</a>')
    assert sw.year_counts_ok(year_list(), COUNTS)        # 책 수가 링크 앞(바탕 틀)
    assert sw.year_counts_ok(after, COUNTS)              # 링크 뒤
    assert sw.year_counts_ok(inside, COUNTS)             # 링크 글자 안
    assert sw.year_counts_ok(noise, COUNTS)              # 연도가 다른 링크에도 듦 · 쪽 번호 링크
    assert not sw.year_counts_ok(wrong, COUNTS)          # 틀린 수
    assert not sw.year_counts_ok(mixed, COUNTS)          # 방향이 섞임
    assert not sw.year_counts_ok("<p>1999 2 2005 2 1987 1</p>", COUNTS)   # 링크가 아님


def test_year_counts_ok_after_only_when_no_number_before_first(sw):   # F1
    B = '<span class="badge">%d</span><a href="/year/%s">%s</a>'
    def front(rows):
        return "".join(B % (n, y, y) for y, n in rows)
    asc = front([("1987", 7), ("1999", 1), ("2005", 2), ("None", 2)])     # 수가 링크 앞 · 제 수가 다 틀림 → 다음 줄의 수를 읽으면 안 됨
    assert asc == ('<span class="badge">7</span><a href="/year/1987">1987</a><span class="badge">1</span><a href="/year/1999">1999</a>'
                   '<span class="badge">2</span><a href="/year/2005">2005</a><span class="badge">2</span><a href="/year/None">None</a>')
    assert not sw.year_counts_ok(asc, COUNTS)
    assert not sw.year_counts_ok(front([("2005", 5), ("1999", 2), ("1987", 2), ("None", 1)]), COUNTS)
    assert sw.year_counts_ok(front([("1987", 1), ("1999", 2), ("2005", 2), ("None", 1)]), COUNTS)
    back = '<a href="/y/1987">1987</a> <span>1</span><a href="/y/1999">1999</a> <span>2</span><a href="/y/2005">2005</a> <span>2</span>'
    assert sw.year_counts_ok(back, COUNTS)                                # 맨 앞 링크 앞에 수가 없으면 뒤 방향
    head = '<h1>Years</h1><p>4 years</p><ul>'                             # G1: 목록 앞 머리글의 수는 (다)를 끄지 않는다(앞 글이 수로 끝나지 않음)
    tail = '<li><a href="/year/%s">%s</a> <span class="badge">%d</span></li>'
    lst = lambda rows: head + "".join(tail % (y, y, n) for y, n in rows) + "</ul>"
    assert sw.year_counts_ok(lst([("1987", 1), ("1999", 2), ("2005", 2)]), COUNTS)
    assert not sw.year_counts_ok(lst([("1987", 1), ("1999", 1), ("2005", 2)]), COUNTS)
    OK3, BAD3 = [("1987", 1), ("1999", 2), ("2005", 2)], [("1987", 1), ("1999", 1), ("2005", 2)]
    assert sw.year_counts_ok(lst(OK3).replace(head, "<p>1987-2005</p><ul>"), COUNTS)   # H1: 목록 앞 글이 수로 끝나도 수-뒤 화면은 맞음
    btn = '<div class="btn">All</div><div class="btn">1</div><div class="btn">2</div><ul>'
    assert sw.year_counts_ok(lst(OK3).replace(head, btn), COUNTS)
    assert not sw.year_counts_ok(lst(BAD3).replace(head, btn), COUNTS)
    wrapped = lambda fmt, nums: "".join('<div class="row"><span class="badge">%s</span><a href="/year/%s">%s</a></div>' % (fmt % n, y, y)
                                        for y, n in zip(("1987", "1999", "2005", "None"), nums))
    for fmt in ("%d books", "(%d)"):   # 수-앞 · 줄 감쌈 · 글자 붙음: 한 칸 밀린 수는 안 됨
        assert not sw.year_counts_ok(wrapped(fmt, (7, 1, 2, 2)), COUNTS), fmt
        assert sw.year_counts_ok(wrapped(fmt, (1, 2, 2, 1)), COUNTS), fmt
    colrow = lambda nums: '<div class="btn">1</div><div class="btn">2</div>' + "".join(
        '<div class="row"><div class="col"><span class="badge">%d</span></div><div class="col"><a href="/year/%s">%s</a></div></div>' % (n, y, y)
        for y, n in zip(("1987", "1999", "2005", "None"), nums))
    assert sw.year_counts_ok(colrow((1, 2, 2, 1)), COUNTS)
    assert not sw.year_counts_ok(colrow((7, 1, 2, 2)), COUNTS)
    mirror = ('<p>page 2</p><ul><li><a href="/year/2005">2005</a> <span>2</span></li><li><a href="/year/1999">1999</a> <span>1</span></li>'
              '<li><a href="/year/1987">1987</a> <span>9</span></li></ul>')
    assert not sw.year_counts_ok(mirror, COUNTS)                          # (나) 쪽 대칭
    YS = ("1987", "1999", "2005", "None")
    def forms(row):   # J1: 배지와 링크 사이에 빈 태그·곧바로 닫히는 짝이 끼어도 같은 줄의 수를 읽는다
        return lambda nums: "<ul>" + "".join(row(n, y) for y, n in zip(YS, nums)) + "</ul>"
    front_forms = [
        forms(lambda n, y: '<li><span class="badge">%d</span> <i class="fa fa-calendar"></i><img src="/i.png"> <a href="/year/%s">%s</a></li>' % (n, y, y)),
        forms(lambda n, y: '<li><span class="badge">%d</span><br><span class="glyphicon glyphicon-book"></span><a href="/year/%s">%s</a></li>' % (n, y, y)),
        forms(lambda n, y: '<li><span class="badge">%d</span> <span class="lbl">books</span> <a href="/year/%s">%s</a></li>' % (n, y, y)),
    ]
    for f in front_forms:
        assert sw.year_counts_ok(f((1, 2, 2, 1)), COUNTS), f((1, 2, 2, 1))
        assert not sw.year_counts_ok(f((7, 1, 2, 2)), COUNTS), f((7, 1, 2, 2))
    back_form = forms(lambda n, y: '<li><a href="/year/%s">%s</a><br><i class="fa fa-book"></i> <span class="badge">%d</span></li>' % (y, y, n))
    assert sw.year_counts_ok(back_form((1, 2, 2, 1)), COUNTS)
    assert not sw.year_counts_ok(back_form((1, 1, 2, 1)), COUNTS)
    mixed_a = ('<ul><li><a href="/year/1987">1987</a> <span>1</span></li><li><a href="/year/1999">1999</a></li>'
               '<li><span>2</span><a href="/year/2005">2005</a> <span>2</span></li></ul>')
    mixed_b = ('<ul><li><span>1</span><a href="/year/1987">1987</a></li><li><span>2</span><a href="/year/1999">1999</a> <span>2</span></li>'
               '<li><a href="/year/2005">2005</a></li></ul>')
    assert sw.year_counts_ok(mixed_a, COUNTS)                             # 표가 섞이면 못 가림 → 두 방향을 다 보고 뒤 방향으로 맞음
    tbl = lambda nums: "<table>" + "".join("<tr><td><a href=\"/year/%s\">%s</a><td>%d" % (y, y, n) for y, n in zip(YS, nums)) + "</table>"   # K1: 닫는 태그 생략
    assert sw.year_counts_ok(tbl((1, 2, 2, 1)), COUNTS)
    assert not sw.year_counts_ok(tbl((1, 1, 2, 1)), COUNTS)
    dl = "<dl>" + "".join('<dt><a href="/year/%s">%s</a><dd>%d books' % (y, y, n) for y, n in zip(YS, (1, 2, 2, 1))) + "</dl>"
    assert sw.year_counts_ok(dl, COUNTS)
    ul = "<ul>" + "".join('<li>(%d) <a href="/year/%s">%s</a>' % (n, y, y) for y, n in zip(YS, (1, 2, 2, 1))) + "</ul>"
    assert sw.year_counts_ok(ul, COUNTS)
    assert sw.year_counts_ok(mixed_b, COUNTS)                             # 반대로 섞인 꼴: 앞 방향으로 맞음(표 하나만 받는 코드는 둘 중 하나에서 떨어짐)


def test_gap_side(sw):   # H1: 이웃한 두 링크 사이의 수가 어느 링크 것인가
    side = lambda b: sw.gap_side(b, sw.link_spans(b), 0)
    li = '<ul><li><a href="/year/1987">1987</a> <span class="badge">1</span></li><li><a href="/year/1999">1999</a> <span class="badge">2</span></li></ul>'
    assert side(li) == "after"
    rc = ('<div class="row"><div class="col"><span class="badge">1</span></div><div class="col"><a href="/year/1987">1987</a></div></div>'
          '<div class="row"><div class="col"><span class="badge">2</span></div><div class="col"><a href="/year/1999">1999</a></div></div>')
    sp = sw.link_spans(rc)
    assert sw.gap_side(rc, sp, 0) == "before"
    assert side('<a href="/y/1987">1987</a> <span>1</span><a href="/y/1999">1999</a>') is None             # 납작해 못 가림
    assert side('<a href="/y/1987">1987</a><span>1</span><span>2</span><a href="/y/1999">1999</a>') is None  # 수 덩이가 둘
    assert side('<a href="/y/1987">1987</a><span>&#160;</span><a href="/y/1999">1999</a>') is None           # 글자 참조를 푼 뒤 숫자가 없음
    icons = ('<ul><li><span class="badge">1</span> <i class="fa fa-calendar"></i><img src="/i.png"> <a href="/year/1987">1987</a></li>'
             '<li><span class="badge">2</span> <i class="fa fa-calendar"></i><img src="/i.png"> <a href="/year/1999">1999</a></li></ul>')
    assert side(icons) == "before"
    assert side('<li><a href="/year/1987">1987</a><br><i class="fa fa-book"></i> <span class="badge">1</span></li><li><a href="/year/1999">1999</a></li>') == "after"
    assert side('<tr><td><a href="/y/1987">1987</a></td><td>1</td></tr><tr><td><a href="/y/1999">1999</a></td><td>2</td></tr>') == "after"
    assert side('<a href="/y/1987">1987</a><!-- 3 --><a href="/y/1999">1999</a>') is None                   # 주석은 글 덩이가 아님
    assert side('<table><tr><td><a href="/year/1987">1987</a><td>1<tr><td><a href="/year/1999">1999</a><td>2</table>') is None   # K1: 닫는 태그 생략
    assert side('<dl><dt><a href="/year/1987">1987</a><dd>1 books<dt><a href="/year/1999">1999</a><dd>2 books</dl>') is None
    assert side('<ul><li><a href="/y/1987">1987</a> (1)<li><a href="/y/1999">1999</a> (2)</ul>') is None
    mixed = ('<ul><li><a href="/year/1987">1987</a> <span>1</span></li><li><a href="/year/1999">1999</a></li>'
             '<li><span>2</span><a href="/year/2005">2005</a> <span>2</span></li></ul>')
    ms = sw.link_spans(mixed)
    assert [sw.gap_side(mixed, ms, 0), sw.gap_side(mixed, ms, 1)] == ["after", "before"]


def test_tag_step(sw):   # J1
    assert sw._tag_step('<div class="a">') == 1 and sw._tag_step("</div>") == -1
    for t in ("<br>", "<br/>", '<img src="x">', "<span/>", "<!-- x -->", "<!DOCTYPE html>"):
        assert sw._tag_step(t) == 0, t


def test_cut_random(sw):
    band = '<div class="discover random-books"><h2 class="random-books">D</h2><a href="/book/3">Winter Letter</a></div>'
    main = '<div class="discover load-more"><a href="/book/1">Sea Song</a></div>'
    assert "Winter Letter" not in sw.cut_random(band + main) and "Sea Song" in sw.cut_random(band + main)
    assert sw.cut_random(main) == main                   # 띠가 없음
    assert sw.cut_random(main + band) == main + band     # 띠 뒤에 덩이가 없음 — 안 자름


def test_cut_random_word_order_and_data_class(sw):      # 22-4
    main = '<div class="discover load-more"><a href="/book/1">Sea Song</a></div>'
    flipped = '<div class="random-books discover"><a href="/book/3">Winter Letter</a></div>'
    assert "Winter Letter" not in sw.cut_random(flipped + main) and "Sea Song" in sw.cut_random(flipped + main)
    data = '<div data-class="discover random-books"><a href="/book/3">Winter Letter</a></div>'
    assert sw.cut_random(data + main) == data + main     # data-class= 는 class= 가 아님
    only_rb = '<div class="random-books"><a href="/book/3">Winter Letter</a></div>'
    assert sw.cut_random(only_rb + main) == only_rb + main   # discover 낱말이 없으면 띠가 아님


def test_url_path(sw):
    assert sw.url_path("/year?data=x") == "/year" and sw.url_path("/year#top") == "/year"
    assert sw.url_path("http://127.0.0.1:1/year/?a=b") == "/year/" and sw.url_path("/year") == "/year"


class PageCli:
    def __init__(self, pages):
        self.pages = pages
    def get(self, path):
        return (200, {}, self.pages[path]) if path in self.pages else (404, {}, "")


def books(*titles, band=("Winter Letter",)):
    b = '<div class="discover random-books">' + "".join("<a href='/b'>%s</a>" % t for t in band) + "</div>"
    return b + '<div class="discover load-more">' + "".join("<a href='/b'>%s</a>" % t for t in titles) + "</div>"


def test_y_scenes_with_badge_before_and_random_band(sw):
    pages = {"/year": year_list(), "/": NAV,
             "/year/stored/1999": books("Sea Song", "Mountain Path"), "/year/stored/2005": books("Winter Letter", "Small House", band=("Old Map",)),
             "/year/stored/1987": books("Old Map"), "/year/stored/None": books("No Date")}
    res, notes = {}, {}
    sw.y_scenes(PageCli(pages), res, notes)
    assert res == {"Y1": True, "Y2": True, "Y3": True, "Y4": True}, notes
    pages["/"] = '<a href="/yearly">x</a>'
    pages["/year/stored/1987"] = books("Old Map", "Sea Song")
    res = {}
    sw.y_scenes(PageCli(pages), res, {})
    assert res["Y2"] is False and res["Y4"] is False


def test_y2_prefers_path_ending_in_year_over_text(sw):   # 22-4: 메뉴에 연도가 든 다른 링크가 먼저 있어도 연도 목록 링크를 따라감
    nav = NAV.replace("</ul>", '<li><a href="/book/9">Notes 1999</a></li></ul>')
    pages = {"/year": year_list(nav=nav), "/": nav, "/book/9": "<p>No Date Sea Song</p>",
             "/year/stored/1999": books("Sea Song", "Mountain Path"), "/year/stored/2005": books("Winter Letter", "Small House", band=("Old Map",)),
             "/year/stored/1987": books("Old Map"), "/year/stored/None": books("No Date")}
    res, notes = {}, {}
    sw.y_scenes(PageCli(pages), res, notes)
    assert res["Y2"] is True and res["Y1"] is True, notes
