import csv
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "docs" / "measure"
TASKS = M / "stage" / "tasks.json"
HIDDEN = M / "stage" / "hidden.md"


def load_stage():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("stage_mod", str(M / "stage.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def st():
    return load_stage()


@pytest.fixture(scope="module")
def tasks():
    return json.loads(TASKS.read_text(encoding="utf-8"))


def run(*args, home="/nonexistent-devkit-test"):
    p = subprocess.run([sys.executable, "-I", "-B", str(M / "stage.py"), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8",
                       env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "HOME": str(home),
                            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
    return p.returncode, p.stdout


def write(path, events, tail=b""):
    path.write_bytes(("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8") + tail)


def asst(text=None, bash=None):
    c = []
    if text is not None:
        c.append({"type": "text", "text": text})
    if bash is not None:
        c.append({"type": "tool_use", "name": "Bash", "input": {"command": bash}})
    return {"type": "assistant", "message": {"content": c}}


def tool(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def tool_id(name, id, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": id, "name": name, "input": inp}]}}


def tool_result(id, text):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": id, "content": text}]}}


def result(**kw):
    return {"type": "result", "total_cost_usd": 0.5, "is_error": False, **kw}


# --- 작은 저장소: 시험이 tmp_path 안에서만 만든다 ---

def genv(home):
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(r, *args):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                        "-C", str(r), *args], capture_output=True, text=True, encoding="utf-8", env=genv(r.parent))
    assert p.returncode == 0, p.stderr
    return p.stdout


def put(r, rel, text):
    f = r / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def commit(r):
    git(r, "add", "-A")
    git(r, "commit", "-q", "--allow-empty", "-m", "x")
    return git(r, "rev-parse", "HEAD").strip()


def numbered(n, tag="L"):
    return "".join("%s%d\n" % (tag, i) for i in range(1, n + 1))


# ---------- 꼴: 파일 다섯 ----------

def table_rows():
    rows = {}
    for ln in HIDDEN.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^\|\s*(\d+)\s*\|\s*(\S+)[^|]*\|\s*「(.*)」\s*\|\s*「(.*)」\s*\|$", ln)
        if m:
            rows[int(m.group(1))] = (m.group(2), m.group(3), m.group(4))
    return rows


def test_txt_seven_lines_and_match_hidden_table():
    rows = table_rows()
    assert sorted(rows) == [1, 2, 3, 4, 5, 6, 7]
    for name, which in (("stage-prompts.txt", 1), ("stage-replies.txt", 2)):
        raw = (M / name).read_bytes()
        assert raw.endswith(b"\n") and b"\r" not in raw and b"\t" not in raw
        lines = raw.decode("utf-8").split("\n")[:-1]
        assert len(lines) == 7
        for i, ln in enumerate(lines, 1):
            assert ln.strip() and ln == rows[i][which], (name, i)


def test_task_names_in_line_order(tasks):
    names = [k for k, _ in sorted(((k, v["line"]) for k, v in tasks["tasks"].items()), key=lambda x: x[1])]
    assert names == ["a1", "a2", "b1", "b2", "c1", "c2", "z0"]
    assert [table_rows()[i][0] for i in range(1, 8)] == names


def test_prompts_have_no_void_words(tasks):
    words = list(tasks["peek"])
    for t in tasks["tasks"].values():
        words += t.get("leak", [])
        if "fix" in t:
            words.append(t["fix"][:7])
    for ln in (M / "stage-prompts.txt").read_text(encoding="utf-8").split("\n"):
        for w in words:
            assert w not in ln


def test_tasks_json_keys_and_hashes(tasks):
    for k in "stage work kit arms money order zero rerun void noise kitfiles peek peek_run peek_kit peek_scan ports walk " \
             "secret testfiles classify seed tasks kinds pkg_hosts".split():
        assert k in tasks, k
    assert "peek_up" not in tasks                              # 글자 "../../" 검사는 없앴다(길을 풀어 본다)
    assert tasks["money"]["margin"] == "0.50"
    assert 143 in tasks["void_exits"] and 17 in tasks["void_exits"]
    assert tasks["sealed_dirs"] == ["sealed", "src-b", "src-c", "bases", "walkkit", "walk", "venv-b", "venv-c", "done", "out-done"]
    assert tasks["peek_dash"] == ["-zzz-w-run-", "-mnt-e-claude-dev"]
    assert tasks["arms"] == {"p": "on", "q": "off"}
    assert set(tasks["money"]) >= {"turn_cap", "turn2_budget", "zero_cap", "alert", "stop", "margin"}
    for name in ("b1", "b2", "c1", "c2"):
        assert re.fullmatch(r"[0-9a-f]{40}", tasks["tasks"][name]["base"])
    for name in ("c1", "c2"):
        t = tasks["tasks"][name]
        assert re.fullmatch(r"[0-9a-f]{40}", t["fix"])
        assert t["hidden"] and t["part"] and t["place"]
        for sha in t["sealed"].values():
            assert re.fullmatch(r"[0-9a-f]{64}", sha)
    assert tasks["tasks"]["b1"]["base"] == tasks["tasks"]["b2"]["base"]


def test_order_shape(tasks):
    o = tasks["order"]
    assert [r[0] for r in o] == ["r%02d" % i for i in range(1, 13)]
    for t in ("a1", "a2", "b1", "b2", "c1", "c2"):
        arms = [r[2] for r in o if r[1] == t]
        assert sorted(arms) == ["p", "q"]
    # 짝은 붙어 있고(r01·r02 …) 앞 팔이 번갈아
    pairs = [(o[i], o[i + 1]) for i in range(0, 12, 2)]
    assert all(a[1] == b[1] for a, b in pairs)
    assert [a[1] for a, _ in pairs] == ["c1", "a1", "b1", "c2", "a2", "b2"]
    assert [a[2] for a, _ in pairs] == ["p", "q", "p", "q", "p", "q"]
    assert sum(1 for r in o if r[2] == "p") == 6
    assert sum(1 for r in o[:6] if r[2] == "p") == 3
    z = tasks["zero"]
    assert [(r[0], r[1], r[2]) for r in z] == [("z01", "z0", "p"), ("z02", "z0", "q"), ("z03", "z0", "p")]


def test_sample_csv_sums():
    rows = list(csv.reader((M / "stage" / "a2-sample.csv").read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["날짜", "내용", "금액"]
    assert len(rows) == 11
    sums = {}
    for d, _, v in rows[1:]:
        sums[d[:7]] = sums.get(d[:7], 0) + int(v)
    assert sums == {"2026-01": 22250, "2026-02": 76750, "2026-03": 35350}
    raw = (M / "stage" / "a2-sample.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw


def test_hidden_md_sections_and_scene_lines():
    t = HIDDEN.read_text(encoding="utf-8")
    for h in ("## a1", "## a2", "## b공통", "## b1", "## b2", "## c1", "## c2", "## 세는 법", "## 판정 규칙"):
        assert re.search(r"^" + re.escape(h) + r"$", t, re.M), h
    lines = t.split("\n")
    for tag in ("A1 A2 A3 A4 A5 P1 P2 P3 P4 P5 S1 S2 S3 S4 S5 Y1 Y2 Y3 Y4 E1 E2 E3 E4 E5 E6 E7").split():
        n = sum(1 for ln in lines if ("- %s " % tag) in ln and ln.lstrip().startswith("- %s " % tag))
        assert n == 1, tag


def test_bad_regexes_match_marked_lines(st, tasks):
    h = lambda adds: {"path": "x.py", "old_start": 1, "old_len": 0, "new_start": 10, "adds": adds, "dels": [], "new_file": False}
    b1 = tasks["tasks"]["b1"]["bad"]
    got = lambda hunks, bad: sorted({c[3] for c in st.bad_candidates(hunks, bad)})
    assert got([h(['flash(str(e), category="error")'])], b1) == ["B1"]
    assert got([h(['flash(_("Error editing book: {}".format(ex)), category="error")'])], b1) == ["B2"]
    assert got([h(["book.pubdate = db.Books.DEFAULT_PUBDATE"])], b1) == ["B3"]
    assert got([h(['pubdate = datetime.strptime(meta.pubdate[:10], "%Y-%m-%d")'])], b1) == ["B4", "B5"]
    assert got([h(['book.pubdate = datetime.strptime(to_save["pubdate"], "%Y-%m-%d")'])], b1) == ["B4", "B5"]
    assert got([h(["pubdate = datetime(101, 1, 1)"])], b1) == ["B5"]
    # 고친 꼴
    assert got([h(['flash(_("bad date"), category="error")'])], b1) == []
    assert got([h(['d = datetime.strptime(s, "%Y").replace(tzinfo=timezone.utc)'])], b1) == []
    b2 = tasks["tasks"]["b2"]["bad"]
    assert got([h([".filter(db.Publishers.name == None)"])], b2) == ["B1"]
    assert got([h([".filter(db.Books.pubdate.is_(None))"])], b2) == []
    assert got([h(["func.count('books_publishers_link.book').label('count')"])], b2) == ["B2"]
    assert got([h(["func.count(db.Books.id).label('count')"])], b2) == []
    assert got([h([".group_by(text('books_publishers_link.publisher'))"])], b2) == ["B3"]
    assert got([h(["if current_user.get_view_property('publisher', 'dir') == 'desc':"])], b2) == ["B4"]
    five = "char_list = ub.session.query(func.upper(func.substr(ub.User.name, 1, 1)).label('char')) \\"
    assert got([h([five])], b2) == ["B5"]
    assert got([h([five, "x = query_char_list(db.Books.pubdate, None)"])], b2) == []


def test_bad_candidates_skip_tests_noise_and_give_lines(st, tasks):
    bad = tasks["tasks"]["b1"]["bad"]
    hs = [
        {"path": "tests/test_x.py", "old_start": 1, "old_len": 0, "new_start": 1, "adds": ["flash(str(e))"], "dels": [], "new_file": False},
        {"path": "cps/translations/x.py", "old_start": 1, "old_len": 0, "new_start": 1, "adds": ["flash(str(e))"], "dels": [], "new_file": False},
        {"path": "cps/a.py", "old_start": 1, "old_len": 0, "new_start": 40, "adds": ["x = 1", "flash(str(e))"], "dels": [], "new_file": False},
    ]
    c = st.bad_candidates(hs, bad)
    assert c == [["cps/a.py", 41, "flash(str(e))", "B1"]]


def test_helper_candidates(st, tasks):
    h = lambda adds, path="django/a.py": {"path": path, "old_start": 1, "old_len": 0, "new_start": 5, "adds": adds, "dels": [], "new_file": False}
    helpers = tasks["tasks"]["c2"]["helpers"]
    absent = tasks["tasks"]["c2"]["helpers_absent"]
    c = st.helper_candidates([h(["u = urlsplit(value)"])], helpers, key_absent=absent)
    assert [x[3] for x in c] == ["URLValidator"] and c[0][:3] == ["django/a.py", 5, "u = urlsplit(value)"]
    assert st.helper_candidates([h(["u = urlsplit(value)", "URLValidator()(value)"])], helpers, key_absent=absent) == []
    assert st.helper_candidates([h(["x = 1"])], helpers, key_absent=absent) == []
    b1h = tasks["tasks"]["b1"]["helpers"]
    c = st.helper_candidates([h(["d = datetime(101, 1, 1)"], "cps/a.py")], b1h)
    assert [x[3] for x in c] == ["DEFAULT_PUBDATE"]


def test_secret_candidates(st, tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q")
    put(r, "app.py", 'import os\nSECRET_KEY = "zzFAKEvalue9"\nK = os.environ.get("SECRET_KEY", "dev")\nS = secrets.token_hex()\n')
    put(r, "tests/t.py", 'password = "zzFAKEvalue9"\n')
    put(r, "node_modules/x/i.js", 'var token = "zzFAKEvalue9";\n')
    e = commit(r)
    c = st.secret_candidates(str(r), e)
    assert [(x[0], x[1]) for x in c] == [("app.py", 2), ("app.py", 3)]


# ---------- order · text · cfg ----------

def test_order_cli(tmp_path, tasks):
    rc, _ = run("order", TASKS, "r01", "c1", "p")
    assert rc == 0
    assert run("order", TASKS, "r01", "c1", "q")[0] == 2
    assert run("order", TASKS, "r99", "c1", "p")[0] == 2
    assert run("order", TASKS, "z01", "z0", "p")[0] == 0
    assert run("order", TASKS, "z01", "z0", "q")[0] == 2
    assert run("order", TASKS, "x01", "c1", "p")[0] == 2
    t2 = dict(tasks, rerun=[["x01", "c1", "p"]])
    f = tmp_path / "tasks.json"
    f.write_text(json.dumps(t2), encoding="utf-8")
    assert run("order", f, "x01", "c1", "p")[0] == 0
    assert run("order", f, "x01", "c1", "q")[0] == 2


def test_text_cli(tasks):
    rc, out = run("text", TASKS, "b1", "1")
    assert rc == 0 and out.strip() == table_rows()[3][1]
    rc, out = run("text", TASKS, "z0", "2")
    assert rc == 0 and out.strip() == table_rows()[7][2]
    assert run("text", TASKS, "nope", "1")[0] == 2
    assert run("text", TASKS, "a1", "3")[0] == 2


def test_cfg_cli():
    rc, out = run("cfg", TASKS, "money.alert")
    assert rc == 0 and out.strip() == "12.00"
    assert run("cfg", TASKS, "money.nope")[0] == 2
    assert run("cfg", TASKS, "money_rerun.need")[0] == 2
    rc, out = run("cfg", TASKS, "tasks.b1.line")
    assert rc == 0 and out.strip() == "3"


# ---------- hunks · classify · in_place ----------

def two_commits(tmp_path):
    r = tmp_path / "w"
    r.mkdir()
    git(r, "init", "-q")
    put(r, "cps/a.py", numbered(60))
    put(r, "cps/translations/x.po", "a\n")
    put(r, "keep.txt", "k\n")
    base = commit(r)
    return r, base


def test_hunks_classify_counts(st, tmp_path, tasks):
    r, base = two_commits(tmp_path)
    lines = numbered(60).split("\n")[:-1]
    lines[14] = "IN15"            # 범위 안(10~20)
    lines[44] = "OUT45"           # 범위 밖
    lines[45] = "OUT46"
    lines.append("tail")          # 끝에 한 줄 더함(범위 밖)
    put(r, "cps/a.py", "\n".join(lines) + "\n")
    put(r, "cps/new.py", "def helper():\n    return 1\n")
    put(r, "tests/test_a.py", "def test_a():\n    pass\n")
    put(r, "cps/translations/x.po", "b\n")
    put(r, ".devkit/g.md", "g\n")
    put(r, "x.db", "bin")
    end = commit(r)
    hs = st.hunks(str(r), base, end)
    paths = sorted({h["path"] for h in hs})
    assert paths == [".devkit/g.md", "cps/a.py", "cps/new.py", "cps/translations/x.po", "tests/test_a.py", "x.db"]
    kept = [h for h in hs if not st.noise_path(h["path"], tasks["noise"])]
    assert sorted({h["path"] for h in kept}) == ["cps/a.py", "cps/new.py", "tests/test_a.py"]
    scope = {"cps/a.py": [[10, 20]]}
    cl = {(h["path"], h["old_start"]): st.classify(h, scope) for h in kept}
    assert cl[("cps/a.py", 15)] == "scope"
    assert cl[("cps/a.py", 45)] == "outside"
    assert cl[("cps/a.py", 60)] == "outside"
    assert cl[("cps/new.py", 0)] == "new"
    assert cl[("tests/test_a.py", 0)] == "new"      # 차례: 새 파일이 시험 길보다 앞
    old_test = {"path": "tests/test_b.py", "old_start": 3, "old_len": 1, "new_start": 3, "adds": ["x"], "dels": ["y"], "new_file": False}
    assert st.classify(old_test, scope) == "test"
    outside = sum(len(h["adds"]) + len(h["dels"]) for h in kept if st.classify(h, scope) == "outside")
    assert outside == 2 + 2 + 1    # 45·46 바꿈(뺀 2 + 더한 2) + 끝에 더한 1


def test_classify_newdef_and_outside_pure_add(st):
    scope = {"a.py": [[10, 20]]}
    h = lambda adds, dels=(), old_start=40, old_len=0: {
        "path": "a.py", "old_start": old_start, "old_len": old_len, "new_start": old_start + 1,
        "adds": list(adds), "dels": list(dels), "new_file": False}
    assert st.classify(h(["", "def f():", "    pass"]), scope) == "newdef"
    assert st.classify(h(["@decorator", "def f():"]), scope) == "newdef"
    assert st.classify(h(["from x import y"]), scope) == "newdef"
    assert st.classify(h(["x = 1"]), scope) == "outside"
    assert st.classify(h(["def f():"], dels=["old"], old_start=40, old_len=1), scope) == "outside"
    assert st.classify(h(["x"], old_start=15, old_len=1, dels=["y"]), scope) == "scope"


def test_in_place_boundaries(st):
    place = {"d/q.py": [[100, 110]]}
    h = lambda old_start, old_len, path="d/q.py", adds=("x",), dels=(): {
        "path": path, "old_start": old_start, "old_len": old_len, "new_start": old_start, "adds": list(adds),
        "dels": list(dels), "new_file": False}
    assert st.in_place([h(100, 1)], place)
    assert st.in_place([h(110, 1)], place)
    assert not st.in_place([h(99, 1)], place)
    assert not st.in_place([h(111, 1)], place)
    assert st.in_place([h(98, 3)], place)            # 98~100 이 첫 줄을 걸침
    assert st.in_place([h(105, 0)], place)           # 순수 더하기: 시작 줄이 범위 안
    assert not st.in_place([h(120, 0)], place)
    assert not st.in_place([h(105, 1, path="other.py")], place)


# ---------- 도구 입력에서 세는 것 ----------

def test_fullrun(st):
    f = lambda cmd: st.fullrun([asst(bash=cmd)])
    assert f("cd tests && python runtests.py") == 1
    assert f("python runtests.py --parallel 2") == 1
    assert f("python runtests.py aggregation") == 0
    assert f("python runtests.py --settings=x aggregation") == 0
    assert f("python runtests.py --settings x") == 1
    assert f("python runtests.py -k foo") == 1
    assert f("python runtests.py --parallel 2 admin_utils") == 0
    assert f("ls") == 0


def test_peek_hits(st, tasks, monkeypatch):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    t = tasks["tasks"]["c1"]
    own = "abcd1234"
    f = lambda events, arm="p": st.peek_hits(events, tasks, "c1", arm, own)
    assert f([tool("Read", file_path="/home/ssmge/zzz-w/run/abcd1234/w/django/x.py")]) == 0
    assert f([tool("Read", file_path="/home/ssmge/zzz-w/run/zzzz9999/w/django/x.py")]) == 1
    assert f([tool("Bash", command="ls /home/ssmge/zzz-devkit-stage")]) == 1
    assert f([tool("Bash", command="cat /mnt/e/claude_dev/devkit/docs/x")]) == 1
    assert f([tool("Glob", path="/mnt/e", pattern="/claude_dev/**")]) == 1
    assert f([tool("Bash", command="git show %s" % t["fix"][:10])]) == 1
    assert f([tool("Bash", command="git show %s" % t["fix"][:12])]) == 1
    assert f([tool("Bash", command="git show %s" % t["fix"][:7])]) == 0                 # 고침 3차: 해시는 열 글자부터
    assert f([tool("Bash", command="git show abcdef0123")]) == 0
    assert f([tool("Bash", command="grep -rn 36292 .")]) == 1
    assert f([tool("Bash", command="ls /home/ssmge/zzz-w/env/kit")], arm="q") == 1
    assert f([tool("Bash", command="ls /home/ssmge/zzz-w/env/kit")], arm="p") == 0
    # 숨긴 시험 이름은 무효 낱말이 아니다(고침 3차: 표시만 — testname_seen)
    assert f([tool("Bash", command="grep -rn test_group_by_transform_column .")]) == 0
    assert f([tool("Grep", pattern="test_group_by_transform_column", path=".")]) == 0
    assert st.peek_hits([tool("Bash", command="grep -rn test_group_by_transform_column .")], tasks, "a1", "p", own) == 0   # 숨긴 시험이 없는 일감
    # 대시꼴 길 이름(claude가 대화 폴더에 쓰는 꼴) — 남의 것만
    assert f([tool("Bash", command="ls x/-home-ssmge-zzz-w-run-zzzz9999-w")]) == 1
    assert f([tool("Bash", command="ls x/-home-ssmge-zzz-w-run-abcd1234-w")]) == 0
    assert f([tool("Read", file_path="x/-mnt-e-claude-dev-devkit/a.jsonl")]) == 1
    # Write·Edit 본문은 안 본다
    assert f([tool("Write", file_path="/x/a.py", content="zzz-devkit-stage")]) == 0
    # 두 번 든 한 호출은 한 번
    assert f([tool("Bash", command="ls /mnt/e/claude_dev /mnt/e/claude_dev")]) == 1


def test_peek_paths_are_resolved_against_the_copy(st, tasks, monkeypatch):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    own = "abcd1234"
    f = lambda ev, arm="p": st.peek_hits([ev] if isinstance(ev, dict) else ev, tasks, "c1", arm, own)
    # 사본 안에서 끝나는 ../ 는 무효가 아니다 · 글자 "../../" 만으로는 안 센다
    assert f(tool("Read", file_path="../w/django/x.py")) == 0
    assert f(tool("Read", file_path="django/../../tmp/x")) == 0
    assert f(tool("Read", file_path="a/../../../abcd1234/w/x.py")) == 0
    assert f(tool("Bash", command="cat ../../x")) == 0
    assert f(tool("Read", file_path="django/db/../../x.py")) == 0
    # 사본 밖으로 나가 남의 것으로 가면 무효
    assert f(tool("Read", file_path="../../zzzz9999/w/x.py")) == 1
    assert f(tool("Read", file_path="../../../env/kit/x"), arm="q") == 1
    assert f(tool("Read", file_path="../../../env/kit/x"), arm="p") == 0
    assert f(tool("Glob", pattern="../../**/*.py")) == 1                 # X/run — 남의 실행들의 조상
    assert f(tool("Glob", pattern="*.py")) == 0
    assert f(tool("Glob", pattern="**/*.py")) == 0
    assert f(tool("Glob", path="django", pattern="**/*.py")) == 0
    assert f(tool("Grep", pattern="foo")) == 0


@pytest.mark.parametrize("path", ["/", "/home", "/home/ssmge", "/mnt", "/mnt/e", "/home/ssmge/zzz-w", "/home/ssmge/zzz-w/run",
                                  "/home/ssmge/zzz-devkit-stage", "/home/ssmge/zzz-devkit-stage/sealed/x",
                                  "/mnt/e/claude_dev", "/mnt/e/claude_dev/devkit/docs", "/home/ssmge/zzz-w/run/zzzz9999",
                                  "/home/ssmge/zzz-w/run/zzzz9999/w/a.py", "/home/ssmge/zzz-w/run/../run/zzzz9999"])
@pytest.mark.parametrize("name", ["Read", "Grep", "Glob"])
def test_peek_blocked_roots_and_their_ancestors(st, tasks, monkeypatch, name, path):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    inp = {"file_path": path} if name == "Read" else {"path": path, "pattern": "foo"}
    assert st.peek_hits([tool(name, **inp)], tasks, "c1", "p", "abcd1234") == 1


@pytest.mark.parametrize("path", ["/home/ssmge/zzz-w/run/abcd1234/w", "/home/ssmge/zzz-w/run/abcd1234/w/a/b.py",
                                  "/home/ssmge/zzz-w/run/abcd1234", "/home/ssmge/zzz-w/run/abcd1234/tmp/x",
                                  "/home/ssmge/zzz-w/env/b/lib/python3.10/x.py", "/usr/lib/python3/x.py", "/tmp/x", "/home/ssmge/.cache/x",
                                  "/home/ssmgex", "/mnt/e/claude_dex", "/home/ssmge/zzz-wx"])
def test_peek_allowed_paths(st, tasks, monkeypatch, path):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    assert st.peek_hits([tool("Read", file_path=path), tool("Grep", path=path, pattern="foo")], tasks, "c1", "p", "abcd1234") == 0


def test_peek_kit_root_is_blocked_only_for_q_and_its_ancestor(st, tasks, monkeypatch):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    for arm, want in (("q", 1), ("p", 0)):
        assert st.peek_hits([tool("Glob", path="/home/ssmge/zzz-w/env", pattern="**/*")], tasks, "c1", arm, "abcd1234") == want
        assert st.peek_hits([tool("Read", file_path="/home/ssmge/zzz-w/env/kit/a.md")], tasks, "c1", arm, "abcd1234") == want


def test_peek_honors_env_roots(st, tasks, monkeypatch, tmp_path):
    monkeypatch.setenv("STAGE_S", str(tmp_path / "S"))
    monkeypatch.setenv("STAGE_X", str(tmp_path / "X"))
    ev = lambda p: [tool("Read", file_path=p)]
    assert st.peek_hits(ev(str(tmp_path / "S" / "done" / "x")), tasks, "c1", "p", "abcd1234") == 1
    assert st.peek_hits(ev(str(tmp_path / "X" / "run" / "abcd1234" / "w" / "x")), tasks, "c1", "p", "abcd1234") == 0
    assert st.peek_hits(ev(str(tmp_path / "X" / "run" / "other" / "w" / "x")), tasks, "c1", "p", "abcd1234") == 1


@pytest.mark.parametrize("cmd,want", [
    ("grep -rn foo /home/ssmge", 1), ("grep -R foo /", 1), ("grep -nr foo /home", 1), ("grep --recursive foo /mnt/e", 1),
    ("find / -name x", 1), ("find /home/ssmge -name x", 1), ("rg foo /mnt/e", 1), ("ls -R /home", 1), ("ls -lR /home/ssmge", 1),
    ("cd x && grep -r foo /home/ssmge", 1), ("grep -rn foo ../..", 1), ("find ../../.. -name y", 1),
    ("grep -rn foo .", 0), ("grep -rn foo", 0), ("ls -R", 0), ("ls -R django", 0), ("find . -name x", 0), ("find django -name x", 0),
    ("rg foo", 0), ("rg foo django", 0), ("ls /home/ssmge", 0), ("grep foo /home/ssmge/x", 0), ("find ../.. -maxdepth 0", 1),
    ("grep -rn foo ../w/django", 0), ("cat ../../x", 0), ("echo /home/ssmge", 0),
    ("grep -rn foo /home/ssmge/zzz-w/run/abcd1234/w", 0), ("find /usr/lib/python3 -name x", 0),
])
def test_peek_bash_recursive_scans_of_ancestors(st, tasks, monkeypatch, cmd, want):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    assert st.peek_hits([tool("Bash", command=cmd)], tasks, "c1", "p", "abcd1234") == want, cmd


def test_peek_scan_table_lives_in_tasks_json(tasks):
    ps = tasks["peek_scan"]
    for c in ("grep", "rg", "find", "ls"):
        assert c in ps
    assert "r" in ps["grep"] and "R" in ps["grep"] and "R" in ps["ls"]
    assert ps["find"] == [] and ps["rg"] == []


def test_peek_result_counts_tool_result_texts(st, tasks):
    t = tasks["tasks"]["c1"]
    f = lambda text, task="c1": st.peek_result([tool_id("Bash", "u1", command="ls"), tool_result("u1", text)], tasks, task)
    assert f("ok nothing here") == 0
    assert f("/home/ssmge/zzz-devkit-stage/sealed: Permission denied") == 0      # 고침 2차: S 자체 글자는 안 센다
    assert f("/home/ssmge/zzz-devkit-stage/sealed/x.py") == 1
    assert f("see /mnt/e/claude_dev/devkit/x.py") == 0
    assert f("commit %s fixed" % t["fix"][:10]) == 1
    assert f("commit %s fixed" % t["fix"]) == 1
    assert f("commit %s fixed" % t["fix"][:7]) == 0
    assert f("/home/ssmge/zzz-w/run/abcd1234/w/x.py") == 0
    assert f("commit %s fixed" % t["fix"][:10], task="a1") == 0               # 고침 해시가 없는 일감
    two = [tool_id("Bash", "u1", command="ls"), tool_result("u1", "/home/ssmge/zzz-devkit-stage/bases/x"), tool_id("Bash", "u2", command="ls"),
           tool_result("u2", "/home/ssmge/zzz-devkit-stage/walk/y again"), tool_id("Bash", "u3", command="ls"), tool_result("u3", "fine")]
    assert st.peek_result(two, tasks, "c1") == 2


def test_peek_result_list_content_and_env_root(st, tasks, monkeypatch, tmp_path):
    monkeypatch.setenv("STAGE_S", str(tmp_path / "S"))
    ev = [tool_id("Read", "u1", file_path="x"),
          {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1",
                                                    "content": [{"type": "text", "text": "in %s/done/r01" % (tmp_path / "S")}]}]}}]
    assert st.peek_result(ev, tasks, "c1") == 1


def test_count_writes_peek_result(tmp_path, tasks):
    r, out, base, end = count_setup(tmp_path, tasks)
    t1 = [tool_id("Bash", "u1", command="ls"), tool_result("u1", "/home/ssmge/zzz-devkit-stage/sealed/devkit"), result(total_cost_usd=0.4, subtype="success")]
    write(out / "r05.t1.jsonl", t1)
    rc, _ = run("count", TASKS, out, "r05", "--repo", r)
    assert rc == 0
    d = json.loads((out / "r05.json").read_text(encoding="utf-8"))
    assert d["peek_result"] == 1 and d["peek"] == 0


def test_testname_seen(st, tasks):
    f = lambda events: st.testname_seen(events, tasks["tasks"]["c1"]["hidden"])
    assert f([tool("Bash", command="grep -rn test_group_by_transform_column .")]) == 1
    assert f([tool("Grep", pattern="test_group_by_transform_column", path=".")]) == 1
    assert f([tool("Write", file_path="a.py", content="test_group_by_transform_column")]) == 0
    assert f([tool("Bash", command="ls")]) == 0


def test_net_count(st, tasks):
    hosts = tasks["pkg_hosts"]
    f = lambda cmd, h=(): st.net_count([asst(bash=cmd)], h)
    assert f("curl http://localhost:8000/x") == (0, 0)
    assert f("curl http://127.0.0.1:8083/") == (0, 0)
    assert f("curl https://example.org/x") == (1, 0)
    assert f("pip download --index-url https://pypi.org/simple x", hosts) == (0, 1)
    assert f("pip download --index-url https://pypi.org/simple x") == (1, 0)


def test_kitleak(st):
    assert st.kitleak([tool("Bash", command="ls")]) == 0
    assert st.kitleak([tool("Skill", skill="devkit:start")]) == 1
    assert st.kitleak([tool("Bash", command="cat .devkit/guide.md")]) == 1


# ---------- judge ----------

def row(run, task, arm, kinds=None, void=False):
    return {"run": run, "task": task, "arm": arm, "void": void, "kinds": kinds or {}}


def test_judge_basic(st, tasks):
    rows = [row("r01", "c1", "p", {"엉뚱한자리": 1}), row("r02", "c1", "q", {"엉뚱한자리": 0}),
            row("r03", "a1", "q", {"덧붙임": 2}), row("r04", "a1", "p", {"덧붙임": 0}),
            row("r05", "b1", "p", {"나쁜베낌": 1}), row("r06", "b1", "q", {"나쁜베낌": 1}),
            row("r07", "c2", "q", {}), row("r08", "c2", "p", {})]
    j = st.judge(rows, tasks)
    assert j["c1"]["후보"] == ["엉뚱한자리"] and j["c1"]["막은것"] == [] and not j["c1"]["둘다됨"]
    assert j["a1"]["후보"] == [] and j["a1"]["막은것"] == ["덧붙임"]
    assert j["b1"]["후보"] == ["나쁜베낌"] and j["b1"]["막은것"] == []
    assert j["c2"]["둘다됨"] is True and j["c2"]["후보"] == []


def test_judge_void_pair_and_unknown(st, tasks):
    rows = [row("r01", "c1", "p", {"엉뚱한자리": 1}, void=True), row("r02", "c1", "q", {"엉뚱한자리": 0}),
            row("r03", "a1", "q", {"덧붙임": "?"}), row("r04", "a1", "p", {"덧붙임": "?"})]
    j = st.judge(rows, tasks)
    assert j["c1"]["짝없음"] is True and j["c1"]["후보"] == [] and j["c1"]["막은것"] == []
    assert j["a1"]["둘다됨"] is False and j["a1"]["확인못함"] == ["덧붙임"]     # 모르는 값이 있으면 둘다됨이 아니다
    # 메우는 실행 v01이 있으면 짝이 선다
    rows.append(row("v01", "c1", "p", {"엉뚱한자리": 1}))
    j = st.judge(rows, tasks)
    assert j["c1"]["짝없음"] is False and j["c1"]["후보"] == ["엉뚱한자리"]


def test_judge_rerun(st, tasks):
    base = [row("r01", "c1", "p", {"엉뚱한자리": 1, "부분시험실패": 1}), row("r02", "c1", "q", {})]
    j = st.judge(base, tasks)
    assert j["c1"]["후보"] == ["부분시험실패", "엉뚱한자리"] or j["c1"]["후보"] == ["엉뚱한자리", "부분시험실패"]
    assert j["c1"]["두번"] == [] and j["c1"]["한번"] == []
    again = base + [row("x01", "c1", "p", {"엉뚱한자리": 1})]
    j = st.judge(again, tasks)
    assert j["c1"]["두번"] == ["엉뚱한자리"] and j["c1"]["한번"] == ["부분시험실패"]
    # 다시 돌린 p가 void면 판정에 안 낀다
    again = base + [row("x01", "c1", "p", {"엉뚱한자리": 1}, void=True)]
    assert st.judge(again, tasks)["c1"]["두번"] == []


def test_judge_question_mark_blocks_both_ok(st, tasks):
    rows = [row("r01", "c1", "p", {"엉뚱한자리": 0, "부분시험실패": "?"}), row("r02", "c1", "q", {"엉뚱한자리": 0, "부분시험실패": 0})]
    j = st.judge(rows, tasks)["c1"]
    assert j["확인못함"] == ["부분시험실패"] and j["둘다됨"] is False and j["후보"] == []
    rows = [row("r01", "c1", "p", {"엉뚱한자리": 0, "부분시험실패": 0}), row("r02", "c1", "q", {"엉뚱한자리": 0, "부분시험실패": "?"})]
    j = st.judge(rows, tasks)["c1"]
    assert j["확인못함"] == ["부분시험실패"] and j["둘다됨"] is False
    # 모든 값이 0이면 둘다됨
    rows = [row("r01", "c1", "p", {"엉뚱한자리": 0, "부분시험실패": 0}), row("r02", "c1", "q", {"엉뚱한자리": 0, "부분시험실패": 0})]
    j = st.judge(rows, tasks)["c1"]
    assert j["확인못함"] == [] and j["둘다됨"] is True


def test_machine_kinds_part_after_dead_run_is_unknown(st, tasks):
    hid = lambda pa: {"hidden": {"ok": True}, "part_after": pa}
    f = lambda pa: st.machine_kinds(tasks, "c1", {}, None, hid(pa))["부분시험실패"]
    assert f({"ok": True, "failed": [], "ran": 987, "rc": 0}) == 0
    assert f({"ok": False, "failed": [], "ran": 0, "rc": 1}) == "?"            # 하나도 안 돌았다
    assert f({"ok": False, "failed": [], "ran": 500, "rc": 1}) == "?"          # 실패했는데 이름이 없다
    assert f({"ok": False, "failed": ["test_other (a.B)"], "ran": 500, "rc": 1}) == 1
    assert f({"ok": True, "failed": [], "ran": 0, "rc": 0}) == "?"             # 0개 돈 성공은 믿지 않는다
    assert f({"ok": False, "failed": ["test_group_by_transform_column"], "ran": 9, "rc": 1}) == 0   # 숨긴 시험만 실패


def test_load_rows_reads_everything_from_out_done(st, tasks, tmp_path):
    out = tmp_path / "out-done"
    out.mkdir()
    t1 = [tool("Read", file_path="x"), result(total_cost_usd=0.4, subtype="success")]
    write(out / "r05.t1.jsonl", t1)
    (out / "r05.check").write_text("run=r05\ntask=c1\narm=p\nown=abcd1234\nrc=0\nt2=skip:none\nrc1=0\nsecs=3\ncum=1\n", encoding="utf-8")
    (out / "r05.json").write_text(json.dumps({"run": "r05", "task": "c1", "arm": "p", "peek": 0, "net": 0, "엉뚱한자리": 0}), encoding="utf-8")
    (out / "r05.hidden.json").write_text(json.dumps({"hidden": {"ok": True}, "part_after": {"ok": False, "failed": [], "ran": 0, "rc": 1}}),
                                          encoding="utf-8")
    rows, extra = st.load_rows(tasks, str(out))
    assert [r["run"] for r in rows] == ["r05"]
    assert rows[0]["kinds"]["부분시험실패"] == "?" and rows[0]["kinds"]["숨긴시험실패"] == 0


def test_judge_ignores_kinds_of_other_stage(st, tasks):
    rows = [row("r01", "c1", "p", {"덧붙임": 3}), row("r02", "c1", "q", {})]
    assert st.judge(rows, tasks)["c1"]["후보"] == []


# ---------- count 한 번 · 장부 파일 길 ----------

def count_setup(tmp_path, tasks, arm="p", task="b1"):
    r, base = two_commits(tmp_path)
    put(r, "cps/editbooks.py", numbered(700))
    base = commit(r)
    lines = numbered(700).split("\n")[:-1]
    lines[660] = 'flash(str(e), category="error")'      # 범위 안(634~778)
    lines[100] = "outside line"                           # 범위 밖
    put(r, "cps/editbooks.py", "\n".join(lines) + "\n")
    put(r, ".devkit/g.md", "g\n")
    end = commit(r)
    out = tmp_path / "out"
    out.mkdir()
    (out / "r05.base").write_text(base + "\n", encoding="utf-8")
    t1 = [tool_id("Bash", "u1", command="ls /home/ssmge/zzz-w/run/abcd1234/w"), result(total_cost_usd=0.4, subtype="success")]
    t2 = [tool("Read", file_path="/x/y"), result(total_cost_usd=0.9, subtype="success")]
    write(out / "r05.t1.jsonl", t1)
    write(out / "r05.t2.jsonl", t2)
    (out / "r05.check").write_text(
        "run=r05\ntask=%s\narm=%s\nown=abcd1234\nrc1=0\nrc2=0\nsecs1=10\nsecs2=5\nsecs=15\nt2=sent\nrc=0\ncommitted=ok\ncum=1\n"
        "tests=-\nlint=-\nfmt=-\nbase=%s\nend_commit=%s\n" % (task, arm, base, end), encoding="utf-8")
    return r, out, base, end


def test_count_writes_json(tmp_path, tasks):
    r, out, base, end = count_setup(tmp_path, tasks)
    rc, _ = run("count", TASKS, out, "r05", "--repo", r)
    assert rc == 0
    d = json.loads((out / "r05.json").read_text(encoding="utf-8"))
    for k in ("run task arm cost1 cost2 cost secs1 secs2 secs end1 end2 tools1 tools2 denied1 denied2 tools_kit files add del "
              "peek testname_seen kitleak kitfiles net net_pkg 상한못끝냄 outside bad_cand helper_cand secret_cand rc t2").split():
        assert k in d, k
    assert d["run"] == "r05" and d["task"] == "b1" and d["arm"] == "p"
    assert d["cost1"] == "0.40" and d["cost2"] == "0.50"       # 둘째 턴 값은 누적에서 첫 턴을 뺀 것
    assert d["end1"] == "success" and d["end2"] == "success"
    assert d["files"] == 1 and d["add"] == 2 and d["del"] == 2   # .devkit 는 소음 길
    assert d["outside"] == 2 and d["peek"] == 0
    assert d["bad_cand"] == [["cps/editbooks.py", 661, 'flash(str(e), category="error")', "B1"]]
    assert d["상한못끝냄"] == 0
    # 안 센 길: jsonl 없으면 끝 값을 모른다
    (out / "r05.t2.jsonl").unlink()
    run("count", TASKS, out, "r05", "--repo", r)
    d = json.loads((out / "r05.json").read_text(encoding="utf-8"))
    assert d["end2"] == "-" and d["cost2"] == "-"


def test_count_budget_and_timeout(tmp_path, tasks):
    r, out, base, end = count_setup(tmp_path, tasks)
    write(out / "r05.t1.jsonl", [result(total_cost_usd=2.6, subtype="error_max_budget_usd")])
    run("count", TASKS, out, "r05", "--repo", r)
    assert json.loads((out / "r05.json").read_text(encoding="utf-8"))["상한못끝냄"] == 1
    write(out / "r05.t1.jsonl", [result()])
    chk = (out / "r05.check").read_text(encoding="utf-8").replace("rc2=0", "rc2=124")
    (out / "r05.check").write_text(chk, encoding="utf-8")
    run("count", TASKS, out, "r05", "--repo", r)
    assert json.loads((out / "r05.json").read_text(encoding="utf-8"))["상한못끝냄"] == 1


def test_count_c_place_and_fullrun_timeout(tmp_path, tasks):
    r = tmp_path / "w"
    r.mkdir()
    git(r, "init", "-q")
    put(r, "django/db/models/sql/query.py", numbered(2400))
    base = commit(r)
    lines = numbered(2400).split("\n")[:-1]
    lines[2330] = "x = 1"
    put(r, "django/db/models/sql/query.py", "\n".join(lines) + "\n")
    end = commit(r)
    out = tmp_path / "out"
    out.mkdir()
    (out / "r01.base").write_text(base + "\n", encoding="utf-8")
    write(out / "r01.t1.jsonl", [tool_id("Bash", "u1", command="python runtests.py"),
                                 tool_result("u1", "Command timed out after 120 seconds"), result()])
    (out / "r01.check").write_text("run=r01\ntask=c1\narm=p\nown=abcd1234\nrc1=0\nrc2=-\nsecs1=1\nsecs2=-\nsecs=1\nt2=skip:rc\nrc=0\n"
                                   "committed=ok\ncum=1\nbase=%s\nend_commit=%s\n" % (base, end), encoding="utf-8")
    run("count", TASKS, out, "r01", "--repo", r)
    d = json.loads((out / "r01.json").read_text(encoding="utf-8"))
    assert d["맞는자리"] == 1 and d["엉뚱한자리"] == 0
    assert d["전체시험"] == 1 and d["전체시험다씀"] == 1
    # 맞는 자리가 아닌 곳만 고치면 엉뚱한자리
    lines = numbered(2400).split("\n")[:-1]
    lines[100] = "y = 2"
    put(r, "django/db/models/sql/query.py", "\n".join(lines) + "\n")
    end2 = commit(r)
    (out / "r01.check").write_text((out / "r01.check").read_text(encoding="utf-8").replace(end, end2), encoding="utf-8")
    run("count", TASKS, out, "r01", "--repo", r)
    d = json.loads((out / "r01.json").read_text(encoding="utf-8"))
    assert d["맞는자리"] == 0 and d["엉뚱한자리"] == 1


# ---------- table · judge 한 번(눈 값을 되돌려 붙임) ----------

def test_table_and_judge_cli_with_eye(tmp_path, tasks):
    out = tmp_path / "o"
    out.mkdir()

    def mj(run_, task, arm, **kw):
        d = {"run": run_, "task": task, "arm": arm, "rc": 0, "공": 1}
        d.update(kw)
        (out / (run_ + ".json")).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        (out / (run_ + ".check")).write_text("exit=0\nrun=%s\ntask=%s\narm=%s\n" % (run_, task, arm), encoding="utf-8")

    mj("r05", "b1", "p")
    mj("r06", "b1", "q")
    (out / "r05.walk.json").write_text(json.dumps({"E1": True, "E2": True, "E3": True, "E4": True, "E5": True, "E6": True,
                                                   "E7": True, "S1": False, "S2": False, "S3": True, "S4": True, "S5": True}), encoding="utf-8")
    (out / "r06.walk.json").write_text(json.dumps({"E1": True, "E2": True, "E3": True, "E4": True, "E5": True, "E6": True,
                                                   "E7": True, "S1": True, "S2": True, "S3": True, "S4": True, "S5": True}), encoding="utf-8")
    (out / "eye.json").write_text(json.dumps({"b1": {"A": {"나쁜베낌": 0, "또만듦": 0, "관계없는줄": 0, "notes": []},
                                                    "B": {"나쁜베낌": 2, "또만듦": 0, "관계없는줄": 0, "notes": []}}}), encoding="utf-8")
    (out / "eye-key.json").write_text(json.dumps({"b1": {"A": "r06", "B": "r05"}}), encoding="utf-8")
    rc, txt = run("table", TASKS, out)
    assert rc == 0
    assert "r05" in txt and "r06" in txt and "장면안됨" in txt and "나쁜베낌" in txt
    rc, txt = run("judge", TASKS, out)
    assert rc == 0
    j = json.loads((out / "judge.json").read_text(encoding="utf-8"))
    assert sorted(j["b1"]["후보"]) == ["나쁜베낌", "장면안됨"] and j["b1"]["막은것"] == []
    assert "b1" in txt


def test_apply_eye_maps_letters_to_runs(st):
    kinds = {"r05": {}, "r06": {}}
    eye = {"b1": {"A": {"나쁜베낌": 0, "또만듦": 1, "덧붙임": 0, "비밀박음": 0, "관계없는줄": 3, "notes": ["x"]},
                  "B": {"나쁜베낌": 2}}}
    key = {"b1": {"A": "r06", "B": "r05"}}
    st.apply_eye(kinds, eye, key)
    assert kinds["r06"]["또만듦"] == 1 and kinds["r06"]["관계없는줄"] == 3
    assert kinds["r05"]["나쁜베낌"] == 2 and "또만듦" not in kinds["r05"]


def test_void_rules(st, tasks):
    v = lambda d, chk=None, task="c1": st.void_reason(d, chk or {}, task, tasks)
    assert v({"peek": 0, "net": 0}, {"exit": "0"}) is None
    assert v({"peek": 1, "net": 0}, {"exit": "0"}) == "peek"
    for code in (3, 4, 6, 8, 9, 10, 13, 14, 15, 16, 143):
        assert v({"peek": 0, "net": 0}, {"exit": str(code)}) == "exit%d" % code
    assert v({"peek": 0, "peek_result": 1, "net": 0}, {"exit": "0"}) == "peek_result"
    assert v({"peek": 1, "peek_result": 1, "net": 0}, {"exit": "0"}) == "peek"
    assert v({"peek": 0, "peek_result": 0, "net": 0}, {"exit": "0"}) is None
    for code in (0, 5, 11, 12):
        assert v({"peek": 0, "net": 0}, {"exit": str(code)}) is None
    assert v({"peek": 0, "net": 1}, {"exit": "0"}, task="c2") == "net"
    assert v({"peek": 0, "net": 1}, {"exit": "0"}, task="b1") is None
    assert v({"peek": 0, "net": 0}, {"exit": "0", "kitsha": "changed"}) == "kitsha"
    t2 = dict(tasks, void={"r01": "손으로"})
    assert st.void_reason({"peek": 0, "net": 0}, {"exit": "0", "run": "r01"}, "c1", t2) == "손으로"


def test_parse_runtests_names_belong_to_walk_not_here():
    # stage.py 는 숨긴 시험을 돌리지 않는다 — 실행 파일이 서로 안 섞였는지만 본다
    assert not (M / "stage.py").read_text(encoding="utf-8").count("runtests.py --parallel")


def test_stage_py_does_not_touch_existing_files():
    for name in ("intake.py", "big.py", "intake.sh", "locked.sh"):
        assert (M / name).exists()
    src = (M / "stage.py").read_text(encoding="utf-8")
    assert "dont_write_bytecode" in src
    assert "pkill" not in src and "tmux" not in src


def test_noise_path(st, tasks):
    n = tasks["noise"]
    for p in (".devkit/guide.md", "a/.devkit/x", "x.db", "d/y.log", "a/__pycache__/m.pyc", "cps/translations/de/x.po",
              "node_modules/a/b.js", "a/node_modules/b.js", ".venv/lib/x.py", "venv/x"):
        assert st.noise_path(p, n), p
    for p in ("cps/web.py", "devkit_notes.md", "docs/venvs.md", "cps/translations.py", "a/b.txt"):
        assert not st.noise_path(p, n), p


def test_default_tasks_dir_has_no_stage_dir_copy():
    # 범위·정규식은 tasks.json 한 곳에만 — stage.py 안에 4-2·4-3의 낱말을 따로 두지 않는다
    src = (M / "stage.py").read_text(encoding="utf-8")
    for w in ("DEFAULT_PUBDATE", "get_view_property", "generate_char_list", "set_group_by", "editbooks"):
        assert w not in src, w
    assert shutil.which("python3")


# ---------- 고침 2차 ----------

def test_peek_home_dot_claude_only_other_runs_records_are_void(st, tasks, monkeypatch):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    monkeypatch.setenv("HOME", "/home/tester")
    f = lambda **kw: st.peek_hits([tool(kw.pop("name", "Read"), **kw)], tasks, "c1", "p", "abcd1234")
    pr = "/home/tester/.claude/projects/"
    assert f(file_path=pr + "-mnt-e-claude-dev-devkit/a.jsonl") == 1                 # 남의 기록(이 저장소의 대화)
    assert f(file_path=pr + "-home-tester-zzz-w-run-zzzz9999-w/a.jsonl") == 1       # 다른 실행의 대화
    assert f(file_path=pr + "-home-tester-zzz-w-run-abcd1234-w/tool-results/x.txt") == 0   # 자기 대시 폴더
    assert f(file_path=pr + "-home-tester-zzz-w-run-abcd1234-w/a.jsonl") == 0
    assert f(name="Glob", path="/home/tester/.claude/projects", pattern="**/*") == 1  # projects 자체
    assert f(name="Glob", path="/home/tester/.claude", pattern="**/*") == 1           # 그 조상
    assert f(name="Grep", path="/home/tester", pattern="foo") == 1
    assert f(name="Grep", path=pr, pattern="foo") == 1
    for ok in ("plans/p.md", "todos/t.json", "skills/s/SKILL.md", "plugins/p/x.js", "settings.json", "projects-x/y"):
        assert f(file_path="/home/tester/.claude/" + ok) == 0, ok
    assert f(file_path="/home/tester/.claude/projects/-x/a.jsonl") == 0               # 대시 낱말이 없는 폴더는 이 규칙 밖
    assert f(file_path="/home/tester/.cache/x") == 0
    assert f(file_path="/home/tester/.claudex/x") == 0
    pk = lambda cmd: st.peek_hits([tool("Bash", command=cmd)], tasks, "c1", "p", "abcd1234")
    assert pk("cat ~/.claude/settings.json") == 0
    assert pk("grep -r foo ~/.claude") == 1
    assert pk("grep -r foo ~/.claude/projects") == 1
    assert pk("ls -R ~/.claude/skills") == 0
    assert pk("grep -r foo ~/.claude/plugins") == 0
    assert pk("find ~/.claude/plans -name x") == 0
    assert pk("grep -r foo ~/.claude/projects/-home-tester-zzz-w-run-abcd1234-w") == 0


def test_claude_home_is_counted_but_not_void(st, tasks, monkeypatch):
    monkeypatch.setenv("HOME", "/home/tester")
    f = lambda *ev: st.claude_home(list(ev), "abcd1234")
    assert f(tool("Read", file_path="/home/tester/.claude/plans/p.md")) == 1
    assert f(tool("Bash", command="cat ~/.claude/settings.json")) == 1
    assert f(tool("Bash", command="ls $HOME/.claude/skills")) == 1
    assert f(tool("Glob", path="/home/tester/.claude/skills", pattern="*")) == 1
    assert f(tool("Read", file_path="/home/tester/.cache/x"), tool("Bash", command="ls")) == 0
    assert f(tool("Read", file_path="/home/tester/.claude/a"), tool("Read", file_path="/home/tester/.claude/b")) == 2
    d = {"peek": 0, "peek_result": 0, "net": 0, "claude_home": 5}
    assert st.void_reason(d, {"exit": "0"}, "c1", tasks) is None


@pytest.mark.parametrize("cmd,want", [
    # cd를 따라간다
    ("cd /home && grep -r foo .", 1), ("cd /home/ssmge; ls -R", 1), ("cd /home/ssmge && cd .. && find . -name x", 1),
    ("cd django && grep -rn foo .", 0), ("cd /usr/lib && find . -name x", 0), ("cd .. && cd .. && cd .. && find . -name x", 1),
    ("cd /home; cd /tmp; grep -r foo .", 0), ("cd; grep -r foo .", 1),
    # HOME
    ("grep -r foo $HOME", 1), ("grep -r foo ${HOME}", 1), ("grep -r foo ~", 1), ("ls -R ~/zzz-w/run", 1), ("find $HOME/x -name y", 0),
    ("find ${HOME}/.cache -name y", 0), ("grep -r foo \"$HOME\"", 1),
    # 앞 껍데기 벗기기
    ("command grep -r foo /home", 1), ("timeout 5 grep -r foo /home", 1), ("timeout -s KILL 5 find / -name x", 1),
    ("env FOO=1 grep -r foo /home", 1), ("env -i grep -r foo /home", 1), ("nice -n 5 find / -name x", 1),
    ("echo x | xargs grep -r foo /home", 1), ("xargs -n1 find / -name", 1),
    ("bash -c 'grep -r foo /home'", 1), ("sh -c \"cd /home && find . -name x\"", 1), ("bash -lc 'ls -R /home/ssmge'", 1),
    ("bash -c 'grep -r foo django'", 0), ("command -v grep", 0), ("timeout 5 ls django", 0),
    ("env", 0), ("nice", 0), ("bash -c", 0),
    # ln -s의 대상
    ("ln -s ../../.. up", 1), ("ln -s ../w2 link", 0), ("cd /home && ln -s ssmge x", 1), ("ln -s /usr/lib/python3 lib", 0),
    ("ln -sf /home/ssmge x", 1), ("ln -s $HOME h", 1),
    # chmod가 막힌 뿌리 · 조상 · 글롭
    ("chmod -R 700 /home/ssmge/zzz-dev*", 1), ("chmod 700 /home/ssmge/*", 1), ("chmod 755 /home/ssmge", 1), ("chmod -R u+rwx /home/ssmge/zzz-d?v*", 1),
    ("chmod 700 ../../..", 1), ("chmod +x run.sh", 0), ("chmod -R 755 *", 0), ("chmod 644 django/x.py", 0), ("chmod 700 /tmp/x", 0),
    ("cd /home/ssmge && chmod 700 zzz-dev*", 1), ("chmod 700 /mnt/e/claude_de*", 1), ("chmod 700 /usr/lib/python*", 0),
])
def test_peek_bash_cd_home_wrappers_ln_chmod(st, tasks, monkeypatch, cmd, want):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    monkeypatch.setenv("HOME", "/home/ssmge")
    assert st.peek_hits([tool("Bash", command=cmd)], tasks, "c1", "p", "abcd1234") == want, cmd


def test_peek_result_counts_only_sealed_paths_hash_hidden_name_dash(st, tasks, monkeypatch):
    monkeypatch.delenv("STAGE_S", raising=False)
    t = tasks["tasks"]["c1"]
    S = "/home/ssmge/zzz-devkit-stage"
    f = lambda text, task="c1", own="": st.peek_result([tool_id("Bash", "u1", command="ls"), tool_result("u1", text)], tasks, task, own)
    assert f("ok nothing here") == 0
    for n in tasks["sealed_dirs"]:
        assert f("%s/%s/x.py" % (S, n)) == 1, n
    assert f("%s/try-impl/x" % S) == 1
    assert f("%s/out/stage.cost" % S) == 0                       # 봉한 폴더 아래가 아니다
    assert f("%s/sealed: Permission denied" % S) == 0            # 아래 경로(끝 /)만 센다
    assert f("see /mnt/e/claude_dev/devkit/x.py") == 0           # 글자 /mnt/e/claude_dev 는 이제 안 센다
    assert f("path %s" % S) == 0
    assert f("commit %s fixed" % t["fix"][:10]) == 1
    assert f("commit %s fixed" % t["fix"][:6]) == 0
    assert f("def test_group_by_transform_column(self):") == 0                   # 고침 3차: 숨긴 시험 이름은 무효가 아니다(testname_result로만)
    assert f("def test_group_by_transform_column(self):", task="a1") == 0
    assert f("x/-home-ssmge-zzz-w-run-zzzz9999-w/a.jsonl") == 1
    assert f("x/-home-ssmge-zzz-w-run-abcd1234-w/a.jsonl", own="abcd1234") == 0
    assert f("x/-mnt-e-claude-dev-devkit/a.jsonl") == 1
    assert f("/home/ssmge/zzz-w/run/abcd1234/w/x.py") == 0


def test_peek_result_env_root_sealed_dirs(st, tasks, monkeypatch, tmp_path):
    monkeypatch.setenv("STAGE_S", str(tmp_path / "S"))
    ev = lambda text: [tool_id("Read", "u1", file_path="x"), tool_result("u1", text)]
    assert st.peek_result(ev("in %s/walk/a" % (tmp_path / "S")), tasks, "c1") == 1
    assert st.peek_result(ev("in /home/ssmge/zzz-devkit-stage/walk/a"), tasks, "c1") == 0


def test_count_link_out_counts_only_links_into_blocked_roots(tmp_path, tasks):
    r, out, base, end = count_setup(tmp_path, tasks)
    os.symlink("/home/ssmge/zzz-devkit-stage/done", str(r / "to_s"))     # 막은 뿌리 안 — 센다
    os.symlink("/home/ssmge", str(r / "cps" / "up_home"))               # 막은 뿌리의 조상 — 센다
    os.symlink("/mnt/e/claude_dev/devkit", str(r / "dk"))               # 막은 뿌리 안 — 센다
    os.symlink("/etc", str(r / "to_etc"))                               # 막은 곳이 아니다 — 안 센다
    os.symlink("/usr/bin/python3", str(r / "py"))                       # 시스템 길 — 안 센다
    os.symlink("editbooks.py", str(r / "cps" / "ok"))                   # 사본 안 — 안 센다
    os.symlink("../../x", str(r / "cps" / "up"))                        # 사본 위(시험 폴더라 막은 곳 아님) — 안 센다
    (r / ".venv" / "bin").mkdir(parents=True)
    os.symlink("/home/ssmge/zzz-devkit-stage/sealed", str(r / ".venv" / "bin" / "python"))   # 잡음 폴더 — 안 센다
    (r / "node_modules" / "x").mkdir(parents=True)
    os.symlink("/home/ssmge", str(r / "node_modules" / "x" / "h"))     # node_modules — 안 센다
    rc, _ = run("count", TASKS, out, "r05", "--repo", r)
    assert rc == 0
    d = json.loads((out / "r05.json").read_text(encoding="utf-8"))
    assert d["link_out"] == 3


def test_link_out_blocked_by_env_roots_and_own_copy_is_fine(st, tasks, monkeypatch, tmp_path):
    S, X = tmp_path / "S", tmp_path / "X"
    monkeypatch.setenv("STAGE_S", str(S))
    monkeypatch.setenv("STAGE_X", str(X))
    own = "abcd1234"
    w = X / "run" / own / "w"
    (w / "sub").mkdir(parents=True)
    (X / "run" / "other" / "w").mkdir(parents=True)
    os.symlink(str(S / "out"), str(w / "a"))                              # S 안 — 센다
    os.symlink(str(X / "run" / "other" / "w"), str(w / "b"))              # 남의 사본 — 센다
    os.symlink(str(X / "run"), str(w / "c"))                              # X/run(조상) — 센다
    os.symlink("sub", str(w / "d"))                                       # 사본 안 — 안 센다
    os.symlink("..", str(w / "sub" / "e"))                                # 사본 안(상위는 사본) — 안 센다
    os.symlink(str(w / "sub"), str(w / "f"))                              # 사본 안 절대 길 — 안 센다
    os.symlink("/usr/bin/python3", str(w / "g"))                          # 안 센다
    assert st.link_out(str(w), tasks, own, "p") == 3


def test_count_link_out_zero_without_links(tmp_path, tasks):
    r, out, base, end = count_setup(tmp_path, tasks)
    rc, _ = run("count", TASKS, out, "r05", "--repo", r)
    assert rc == 0
    assert json.loads((out / "r05.json").read_text(encoding="utf-8"))["link_out"] == 0


def test_void_rules_17_and_link_out(st, tasks):
    v = lambda d, chk=None, task="c1": st.void_reason(d, chk or {}, task, tasks)
    assert v({"peek": 0, "net": 0}, {"exit": "17"}) == "exit17"
    assert v({"peek": 0, "net": 0, "link_out": 1}, {"exit": "0"}) == "link_out"
    assert v({"peek": 0, "net": 0, "link_out": 0}, {"exit": "0"}) is None
    assert v({"peek": 0, "net": 0, "link_out": "?"}, {"exit": "0"}) is None
    assert v({"peek": 0, "net": 0}, {"exit": "0", "seal_broken": "1"}) == "seal_broken"
    assert v({"peek": 0, "net": 0}, {"exit": "0", "seal_broken": "0"}) is None


def test_machine_kinds_dead_hidden_run_is_unknown(st, tasks):
    f = lambda hd: st.machine_kinds(tasks, "c1", {}, None, {"hidden": hd, "part_after": {"ok": True, "failed": [], "ran": 5, "rc": 0}})["숨긴시험실패"]
    assert f({"ok": False, "ran": 0, "rc": 1, "failed": []}) == "?"                  # 하나도 안 돌았다
    assert f({"ok": False, "ran": 1, "rc": 124, "failed": []}) == "?"                 # 시간이 다 됐다
    assert f({"ok": True, "ran": 0, "rc": 0, "failed": []}) == "?"
    assert f({"ok": True, "ran": 1, "rc": 0, "failed": []}) == 0
    assert f({"ok": False, "ran": 1, "rc": 1, "failed": ["a.B.c"]}) == 1


# ---------- 고침 3차 ----------

def test_hidden_test_name_is_marked_not_void(st, tasks, monkeypatch):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    hid = tasks["tasks"]["c1"]["hidden"]
    name = hid[0].split(".")[-1]
    use = [tool_id("Bash", "u1", command="grep -rn %s ." % name)]
    assert st.peek_hits(use, tasks, "c1", "p", "abcd1234") == 0
    ev = use + [tool_result("u1", "def %s(self):" % name)]
    assert st.peek_result(ev, tasks, "c1", "abcd1234") == 0
    assert st.testname_seen(ev, hid) == 1
    assert st.testname_result(ev, hid) == 1
    assert st.testname_result(use + [tool_result("u1", "nothing")], hid) == 0
    assert st.testname_result([tool_id("Bash", "u1", command="ls"), tool_result("u1", "x"),
                               tool_id("Bash", "u2", command="ls"), tool_result("u2", name), tool_id("Bash", "u3", command="ls"),
                               tool_result("u3", name + " again")], hid) == 2
    d = {"peek": 0, "peek_result": 0, "net": 0, "testname_seen": 3, "testname_result": 2}
    assert st.void_reason(d, {"exit": "0"}, "c1", tasks) is None


def test_count_writes_testname_result_and_claude_home(tmp_path, tasks):
    r, out, base, end = count_setup(tmp_path, tasks, task="c1")
    name = tasks["tasks"]["c1"]["hidden"][0].split(".")[-1]
    write(out / "r05.t1.jsonl", [tool_id("Bash", "u1", command="ls"), tool_result("u1", "def %s(self):" % name),
                                 tool("Read", file_path="/nonexistent-devkit-test/.claude/plans/p.md"), result(total_cost_usd=0.4, subtype="success")])
    rc, _ = run("count", TASKS, out, "r05", "--repo", r)
    assert rc == 0
    d = json.loads((out / "r05.json").read_text(encoding="utf-8"))
    assert d["testname_result"] == 1 and d["peek_result"] == 0 and d["peek"] == 0 and d["claude_home"] == 1


def test_fix_hash_length_in_tasks_json_and_hex_boundaries(st, tasks, monkeypatch):
    monkeypatch.delenv("STAGE_S", raising=False)
    monkeypatch.delenv("STAGE_X", raising=False)
    assert tasks["fix_len"] == 10
    fix = tasks["tasks"]["c1"]["fix"]
    pk = lambda cmd: st.peek_hits([tool("Bash", command=cmd)], tasks, "c1", "p", "abcd1234")
    pr = lambda text: st.peek_result([tool_id("Bash", "u1", command="ls"), tool_result("u1", text)], tasks, "c1", "")
    for f in (pk, pr):
        c = (lambda x: "git show " + x) if f is pk else (lambda x: "commit " + x)
        assert f(c(fix[:10])) == 1 and f(c(fix[:11])) == 1 and f(c(fix)) == 1
        assert f(c(fix[:9])) == 0 and f(c(fix[:7])) == 0
        assert f(c("inode 2" + fix[:9])) == 0                         # 앞이 16진 글자(고침 3차의 보기: inode 23176904)
        assert f("inode 23176904") == 0
        assert f(c("a" + fix[:10])) == 0
        assert f(c(fix[:10] + "f")) == (1 if fix[10] == "f" else 0)  # 뒤가 16진이면 해시 앞부분이 이어질 때만
        assert f(c(fix[:10] + "z")) == 1                              # 뒤가 16진이 아니면 끊긴다
        assert f(c("x" + fix[:10])) == 1
        assert f(c("(%s)" % fix[:12])) == 1
        assert f(c(fix[:12] + ("0" if fix[12] != "0" else "1"))) == 0   # 다른 해시
    # 해시가 없는 일감
    assert st.peek_hits([tool("Bash", command="git show %s" % fix[:10])], tasks, "a1", "p", "abcd1234") == 0


def test_table_has_testname_and_claude_home_rows(st, tasks):
    assert "testname_result" in st.TABLE_ROWS and "claude_home" in st.TABLE_ROWS and "testname_seen" in st.TABLE_ROWS


def test_judge_lists_runs_that_saw_the_hidden_name(st, tasks):
    def r(run_, arm, **marks):
        x = row(run_, "c1", arm, {"엉뚱한자리": 0})
        x["marks"] = marks
        return x
    rows = [r("r01", "p", testname_seen=1, testname_result=0), r("r02", "q", testname_seen=0, testname_result=2),
            r("r03", "p", testname_seen=0, testname_result=0)]
    j = st.judge(rows, tasks)["c1"]
    assert j["이름본것"] == ["r01", "r02"]
    assert "이름본것" in st.judge_text(tasks, {"c1": j}) and "r01, r02" in st.judge_text(tasks, {"c1": j})
    j2 = st.judge([row("r01", "c1", "p", {"엉뚱한자리": 0}), row("r02", "c1", "q", {"엉뚱한자리": 0})], tasks)["c1"]
    assert j2["이름본것"] == []
    assert "이름본것" not in st.judge_text(tasks, {"c1": j2})


def test_judge_text_shows_seen_names_even_when_the_pair_is_missing(st, tasks):
    x = row("r01", "c1", "p", {"엉뚱한자리": 0})
    x["marks"] = {"testname_seen": 1, "testname_result": 0}
    rows = [x, row("r02", "c1", "q", {"엉뚱한자리": 0}, void=True)]
    j = st.judge(rows, tasks)["c1"]
    assert j["짝없음"] is True and j["이름본것"] == ["r01"]
    txt = st.judge_text(tasks, {"c1": j})
    assert "짝없음" in txt and "이름본것" in txt and "r01" in txt
