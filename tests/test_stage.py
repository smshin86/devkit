import copy
import csv
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
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


def init_ev(mcp=None, tools=None):
    e = {"type": "system", "subtype": "init"}
    if mcp is not None:
        e["mcp_servers"] = mcp
    if tools is not None:
        e["tools"] = tools
    return e


def tool_result_err(id, text, err=True):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": id, "content": text, "is_error": err}]}}


def sub_tool(name, id, parent, **inp):
    """서브에이전트 안 사건(parent_tool_use_id가 있다)."""
    e = tool_id(name, id, **inp)
    e["parent_tool_use_id"] = parent
    return e


INIT9 = ["Task", "Bash", "Edit", "Glob", "Grep", "Read", "Skill", "Write", "TaskStop"]
ALLOWED = ["Read", "Glob", "Grep", "Skill", "Bash", "Write", "Edit", "Agent", "Task", "TaskStop"]
PEND = {"name": "n", "status": "pending"}


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


def test_txt_lines_match_hidden_table(tasks):
    N = len(tasks["tasks"])
    rows = table_rows()
    assert sorted(rows) == list(range(1, N + 1))
    for name, which in (("stage-prompts.txt", 1), ("stage-replies.txt", 2)):
        raw = (M / name).read_bytes()
        assert raw.endswith(b"\n") and b"\r" not in raw and b"\t" not in raw
        lines = raw.decode("utf-8").split("\n")[:-1]
        assert len(lines) == N
        for i, ln in enumerate(lines, 1):
            assert ln.strip() and ln == rows[i][which], (name, i)


def test_task_names_in_line_order(tasks):
    names = [k for k, _ in sorted(((k, v["line"]) for k, v in tasks["tasks"].items()), key=lambda x: x[1])]
    assert names[:7] == ["a1", "a2", "b1", "b2", "c1", "c2", "z0"]
    assert set(names[7:]) == {"a3", "b3"}
    assert [table_rows()[i][0] for i in range(1, len(names) + 1)] == names


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
             "secret testfiles classify seed tasks kinds pkg_hosts money_rerun".split():
        assert k in tasks, k
    assert "peek_up" not in tasks                              # 글자 "../../" 검사는 없앴다(길을 풀어 본다)
    assert tasks["money"]["margin"] == "0.50"
    assert tasks["money_rerun"] == {"need": "1.00", "alarm": "1.50", "stop": "4.50"}
    assert [list(r[:3]) for r in tasks["rerun"]] == [["x01", "a1", "p"], ["x02", "a2", "p"], ["x03", "b1", "p"], ["x04", "b2", "p"]]
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
    t = tasks["tasks"]
    assert t["a3"]["stage"] == "a" and t["a3"]["tar"] is None and t["a3"]["line"] == 8
    assert t["b3"]["base"] == t["b1"]["base"] and t["b3"]["tar"] == t["b1"]["tar"] and t["b3"]["stage"] == "b"


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
    assert [(r[0], r[1], r[2]) for r in z] == [("z01", "z0", "p"), ("z02", "z0", "q"), ("z03", "z0", "p"), ("z04", "z0", "p"),
                                              ("z05", "z0", "q"), ("z06", "z0", "p"), ("z07", "z0", "q")]
    assert [r[3] for r in z[3:]] == ["a1", "a1", "a1", "a1"]


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


def test_hidden_md_sections_and_scene_lines(tasks):
    t = HIDDEN.read_text(encoding="utf-8")
    for h in ("## a1", "## a2", "## b공통", "## b1", "## b2", "## c1", "## c2", "## 세는 법", "## 판정 규칙"):
        assert re.search(r"^" + re.escape(h) + r"$", t, re.M), h
    lines = t.split("\n")
    count = lambda tag: sum(1 for ln in lines if ("- %s " % tag) in ln and ln.lstrip().startswith("- %s " % tag))
    for tag in ("A1 A2 A3 A4 A5 P1 P2 P3 P4 P5 S1 S2 S3 S4 S5 Y1 Y2 Y3 Y4").split():
        assert count(tag) == 1, tag
    for tag in ("E1 E2 E3 E4 E5 E6 E7").split():
        assert count(tag) >= 1, tag
    for name, task in tasks["tasks"].items():
        for tag in task.get("scenes", []):
            assert count(tag) >= 1, (name, tag)


def test_hidden_md_ruler2_marks():
    t = HIDDEN.read_text(encoding="utf-8")
    assert re.findall(r"^## .+$", t, re.M)[-1] == "## 고침 기록"
    sec = lambda h: t.split("\n" + h + "\n", 1)[1].split("\n## ", 1)[0]
    for h in ("## a1", "## a2", "## b1", "## b2", "## 세는 법", "## 걸어 보기 규칙"):
        assert "(둘째 자)" in sec(h), h
    for s in ("## a1", "## a2"):
        for w in ("`test.mjs`", "`*.spec.cjs`", "`test/`", "`latest.js`", "no test specified", "`node --test", "끝 값 5",
                  "합의 목록", "`합의로뺀것`", "포트 하나와 저장 자리 하나", "입력을 너그럽게 받기", "첫 턴 마지막 답글 전체", "코드 확장자"):
            assert w in sec(s), (s, w)
        assert "tasks.json" not in sec(s)
    for s in ("## b1", "## b2"):
        for w in ("나쁜 방식마다 1건", "세 줄 넘는 덩이", "도우미 안 씀", "한 벌 더한 것", "그 자리에서 고쳐 쓴 것", "있던 목록 하나가 가진 줄 수까지"):
            assert w in sec(s), (s, w)
    assert "random-books" in sec("## b2") and "물음표" in sec("## b2") and "`if` 사슬" in sec("## b2") and "도우미마다 1" in sec("## b2")
    assert "첫 턴 마지막 답글" in sec("## 걸어 보기 규칙")
    assert "`C`" in sec("## 세는 법") and "c6ad1d9" in sec("## 고침 기록") and "x 못 잼" in sec("## 고침 기록")


# ---------- 꼴: 새 꾸러미 실행(y) 설정 열쇠 ----------
# 꼴 검사 몸통은 _check_…(cfg)로 빼서, 진짜 설정 시험과 메모리 사본 시험이 같이 부른다.

Y_BASES = {"a1", "a2", "b1", "b2", "c1", "c2"}
RUN_RE = r"[wy]\d{2}"
DOLLAR_RE = r"\d{1,2}\.\d{2}"


def _check_round_y(cfg):
    rows = cfg["round_y"]
    assert isinstance(rows, list) and rows
    names = []
    for r in rows:
        assert isinstance(r, list) and len(r) in (3, 4), r
        assert re.fullmatch(RUN_RE, r[0]), r[0]
        assert r[1] in cfg["tasks"], r
        if len(r) == 4:
            assert r[1] == "z0" and r[3] in Y_BASES, r[0]
        assert r[2] == "p", r[0]
        names.append(r[0])
    assert len(set(names)) == len(names)
    other = {x[0] for key in ("order", "zero", "rerun") for x in cfg[key]}
    assert not (set(names) & other)
    for r in rows:
        n = int(r[0][1:])
        if r[0][0] == "w":
            assert 1 <= n <= 15, r[0]
        else:
            assert 0 <= n <= 19, r[0]
    drop = set((cfg.get("redo_y") or {}).values())
    keep = [r for r in rows if r[0] not in drop]
    w = Counter(r[1] for r in keep if r[0][0] == "w")
    y = Counter(r[1] for r in keep if r[0][0] == "y")
    assert w == Counter({"a3": 2, "b3": 2}), sorted(w.items())
    want = Counter({"z0": 1, "a1": 2, "a2": 2, "b1": 2, "b2": 2, "a3": 2, "b3": 2, "c1": 1, "c2": 1})
    assert y == want, sorted(y.items())
    assert sum(y.values()) == 15
    assert [r[1] for r in keep if r[0] == "y00"] == ["z0"]


def _check_money_y(cfg):
    m = cfg["money_y"]
    assert set(m) == {"alert", "stop"}
    for v in m.values():
        assert isinstance(v, str) and re.fullmatch(DOLLAR_RE, v), v
    mo = cfg["money"]
    room = float(m["stop"]) - max(float(mo["turn_cap"]), float(mo["turn2_budget"])) - float(mo["margin"])
    assert float(m["alert"]) <= room + 1e-9


def _check_g3_exits_y(cfg):
    assert cfg["g3_exits_y"] in (["0"], ["0", "11"])


def _check_redo_y(cfg):
    redo = cfg["redo_y"]
    assert isinstance(redo, dict)
    rows = {r[0]: r for r in cfg["round_y"]}
    for k, v in redo.items():
        assert k in rows and v in rows
        assert k != v
        assert rows[k][1:3] == rows[v][1:3]
        assert rows[k][1] != "z0"
    assert len(set(redo.values())) == len(redo)
    assert not (set(redo.values()) & set(redo))


def _check_ports_base_b3(cfg):
    p = cfg["ports"]
    base = p["base"]
    assert base["b3"] == 18392
    wb = p["walk_base"]
    assert not (wb + 70 <= base["b3"] <= wb + 89)
    assert not (wb + 25 <= base["b3"] <= wb + 39)
    assert len(set(base.values())) == len(base)


def _check_y_before(cfg):
    yb = cfg["y_before"]
    assert set(yb) == {"t3_scene", "h2_scene", "g4", "cost"}
    assert yb["h2_scene"] in cfg["tasks"]["b3"]["scenes"]
    assert yb["t3_scene"] in cfg["tasks"]["b2"]["scenes"]
    assert set(yb["g4"]) == {"c1", "c2"}
    assert set(yb["cost"]) == Y_BASES
    for v in yb["cost"].values():
        assert isinstance(v, str) and re.fullmatch(r"\d+\.\d{2}", v), v


def _skip_unless(cfg, key):
    if key not in cfg:
        pytest.skip("메인이 아직 안 채움")


def test_round_y_shape(tasks):
    _skip_unless(tasks, "round_y")
    _check_round_y(tasks)


def test_money_y_shape(tasks):
    _skip_unless(tasks, "money_y")
    _check_money_y(tasks)


def test_g3_exits_y_shape(tasks):
    _skip_unless(tasks, "g3_exits_y")
    _check_g3_exits_y(tasks)


def test_redo_y_shape(tasks):
    _skip_unless(tasks, "redo_y")
    _check_redo_y(tasks)


def test_ports_base_b3(tasks):
    if "b3" not in tasks["ports"]["base"]:
        pytest.skip("메인이 아직 안 채움")
    _check_ports_base_b3(tasks)


def test_y_before_shape(tasks):
    _skip_unless(tasks, "y_before")
    _check_y_before(tasks)


# --- 같은 몸통을 진짜 설정의 메모리 사본에 계획 글 꼴의 값을 넣어 불러 본다 ---

def y_cfg(tasks):
    cfg = copy.deepcopy(tasks)
    rows = [["w01", "a3", "p"], ["w02", "a3", "p"], ["w03", "b3", "p"], ["w04", "b3", "p"], ["y00", "z0", "p", "a1"]]
    for i, t in enumerate(["a1", "a1", "a2", "a2", "b1", "b1", "b2", "b2", "a3", "a3", "b3", "b3", "c1", "c2"], 1):
        rows.append(["y%02d" % i, t, "p"])
    rows.append(["y15", "a1", "p"])                                   # 대신 도는 실행
    cfg["round_y"] = rows
    cfg["redo_y"] = {"y01": "y15"}
    cfg["g3_exits_y"] = ["0", "11"]
    mo = cfg["money"]
    cfg["money_y"] = {"alert": "1.00",
                      "stop": "%.2f" % (1.0 + max(float(mo["turn_cap"]), float(mo["turn2_budget"])) + float(mo["margin"]))}
    cfg["ports"]["base"]["b3"] = 18392
    cfg["y_before"] = {"t3_scene": cfg["tasks"]["b2"]["scenes"][0], "h2_scene": cfg["tasks"]["b3"]["scenes"][0],
                       "g4": {"c1": {"k": 1}, "c2": {"k": 2}},
                       "cost": {k: "1.00" for k in sorted(Y_BASES)}}
    return cfg


def test_y_cfg_copy_good_shapes_pass(tasks):
    cfg = y_cfg(tasks)
    for f in (_check_round_y, _check_money_y, _check_g3_exits_y, _check_redo_y, _check_ports_base_b3, _check_y_before):
        f(cfg)
    cfg["g3_exits_y"] = ["0"]
    _check_g3_exits_y(cfg)
    cfg["redo_y"] = {}
    cfg["round_y"] = [r for r in cfg["round_y"] if r[0] != "y15"]
    _check_round_y(cfg)
    _check_redo_y(cfg)


def _bad_round_y(cfg, how):
    rows = cfg["round_y"]
    pos = lambda n: [i for i, r in enumerate(rows) if r[0] == n][0]
    if how == "fourth_not_z0":
        rows[pos("y03")].append("a1")
    elif how == "fourth_not_base":
        rows[pos("y00")][3] = "z0"
    elif how == "y_rows_short":
        del rows[pos("y14")]
    elif how == "y_rows_extra":
        rows.append(["y16", "c1", "p"])
    elif how == "w_rows_wrong":
        rows[pos("w02")][1] = "b3"
    elif how == "arm_q":
        rows[pos("y05")][2] = "q"
    elif how == "dup_name":
        rows[pos("y06")][0] = "y05"
    elif how == "bad_name":
        rows[pos("y06")][0] = "v06"
    elif how == "w_number":
        rows[pos("w04")][0] = "w16"
    elif how == "y_number":
        rows[pos("y14")][0] = "y20"
    elif how == "row_len":
        rows[pos("y05")].append("x")
        rows[pos("y05")].append("x")


@pytest.mark.parametrize("how", ["fourth_not_z0", "fourth_not_base", "y_rows_short", "y_rows_extra", "w_rows_wrong", "arm_q",
                                 "dup_name", "bad_name", "w_number", "y_number", "row_len"])
def test_check_round_y_catches_bad_shapes(tasks, how):
    cfg = y_cfg(tasks)
    _bad_round_y(cfg, how)
    with pytest.raises(AssertionError):
        _check_round_y(cfg)


def test_check_round_y_catches_name_collision_with_order(tasks):
    cfg = y_cfg(tasks)
    cfg["rerun"] = copy.deepcopy(cfg["rerun"]) + [["y05", "a1", "p"]]
    with pytest.raises(AssertionError):
        _check_round_y(cfg)


def test_check_round_y_without_redo_counts_all_rows(tasks):
    cfg = y_cfg(tasks)
    cfg["redo_y"] = {}                       # 대신 도는 실행을 안 뺐으니 a1이 셋이 되어 걸려야 한다
    with pytest.raises(AssertionError):
        _check_round_y(cfg)


@pytest.mark.parametrize("how", ["extra_key", "missing_key", "not_str", "bad_form", "over_relation"])
def test_check_money_y_catches_bad_shapes(tasks, how):
    cfg = y_cfg(tasks)
    m = cfg["money_y"]
    if how == "extra_key":
        m["note"] = "1.00"
    elif how == "missing_key":
        del m["alert"]
    elif how == "not_str":
        m["alert"] = 1.0
    elif how == "bad_form":
        m["stop"] = "9"
    else:
        m["alert"] = "%.2f" % (float(m["stop"]) + 0.01)               # 관계보다 큼
    with pytest.raises(AssertionError):
        _check_money_y(cfg)


def test_check_money_y_edge_equal_passes(tasks):
    cfg = y_cfg(tasks)
    mo = cfg["money"]
    cfg["money_y"]["alert"] = "%.2f" % (float(cfg["money_y"]["stop"]) - max(float(mo["turn_cap"]), float(mo["turn2_budget"])) - float(mo["margin"]))
    _check_money_y(cfg)


@pytest.mark.parametrize("val", [["0", "12"], ["11"], [], ["0", "11", "12"], "0", [0]])
def test_check_g3_exits_y_catches_bad_shapes(tasks, val):
    cfg = y_cfg(tasks)
    cfg["g3_exits_y"] = val
    with pytest.raises(AssertionError):
        _check_g3_exits_y(cfg)


@pytest.mark.parametrize("how", ["not_dict", "key_unknown", "same", "other_task", "other_arm", "dup_value", "chain", "z0"])
def test_check_redo_y_catches_bad_shapes(tasks, how):
    cfg = y_cfg(tasks)
    cfg["round_y"] += [["y16", "a1", "p"], ["y17", "a2", "q"], ["y18", "z0", "p"], ["y19", "z0", "p"]]
    if how == "not_dict":
        cfg["redo_y"] = [["y01", "y15"]]
    elif how == "key_unknown":
        cfg["redo_y"] = {"y99": "y15"}
    elif how == "same":
        cfg["redo_y"] = {"y15": "y15"}
    elif how == "other_task":
        cfg["redo_y"] = {"y03": "y15"}
    elif how == "other_arm":
        cfg["redo_y"] = {"y01": "y17"}
    elif how == "dup_value":
        cfg["redo_y"] = {"y01": "y15", "y02": "y15"}
    elif how == "chain":
        cfg["redo_y"] = {"y01": "y15", "y15": "y16"}
    else:
        cfg["redo_y"] = {"y18": "y19"}
    with pytest.raises(AssertionError):
        _check_redo_y(cfg)


@pytest.mark.parametrize("how", ["wrong_port", "in_y_slots", "in_w_slots", "overlap"])
def test_check_ports_base_b3_catches_bad_shapes(tasks, how):
    cfg = y_cfg(tasks)
    b = cfg["ports"]["base"]
    wb = cfg["ports"]["walk_base"]
    if how == "wrong_port":
        b["b3"] = 18393
    elif how == "in_y_slots":
        b["b3"] = wb + 75
    elif how == "in_w_slots":
        b["b3"] = wb + 30
    else:
        b["b2"] = 18392
    with pytest.raises(AssertionError):
        _check_ports_base_b3(cfg)


@pytest.mark.parametrize("how", ["extra_key", "missing_key", "h2_not_b3", "t3_not_b2", "g4_keys", "cost_keys", "cost_form"])
def test_check_y_before_catches_bad_shapes(tasks, how):
    cfg = y_cfg(tasks)
    yb = cfg["y_before"]
    if how == "extra_key":
        yb["x"] = 1
    elif how == "missing_key":
        del yb["g4"]
    elif how == "h2_not_b3":
        yb["h2_scene"] = "zzNOSCENE9"
    elif how == "t3_not_b2":
        yb["t3_scene"] = "zzNOSCENE9"
    elif how == "g4_keys":
        yb["g4"] = {"c1": {}}
    elif how == "cost_keys":
        del yb["cost"]["c2"]
    else:
        yb["cost"]["a1"] = "1.0"
    with pytest.raises(AssertionError):
        _check_y_before(cfg)


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
    assert run("order", TASKS, "x01", "a1", "p")[0] == 0
    t2 = dict(tasks, rerun=[["x01", "c1", "p"]])
    f = tmp_path / "tasks.json"
    f.write_text(json.dumps(t2), encoding="utf-8")
    assert run("order", f, "x01", "c1", "p")[0] == 0
    assert run("order", f, "x01", "c1", "q")[0] == 2


def test_run_names_orders_new_letters(st, tmp_path):
    for n in "r02 r01 x01 v01 w02 w01 y10 y00 z01".split():
        (tmp_path / (n + ".json")).write_text("{}", encoding="utf-8")
    assert st.run_names(str(tmp_path)) == ["r01", "r02", "v01", "x01", "w01", "w02", "y00", "y10"]


def test_order_cli_round_y(tmp_path, tasks):
    f = tmp_path / "tasks.json"
    f.write_text(json.dumps(dict(tasks, round_y=[["y01", "a1", "p"], ["y00", "z0", "p", "a1"],
                                                 ["w01", "a3", "p"]])), encoding="utf-8")
    assert run("order", f, "y01", "a1", "p")[0] == 0
    assert run("order", f, "y01", "a1", "q")[0] == 2
    assert run("order", f, "y00", "z0", "p")[0] == 0
    assert run("order", f, "w01", "a3", "p")[0] == 0
    assert run("order", f, "y02", "a1", "p")[0] == 2


def test_order_cli_without_round_y_unchanged(tmp_path, tasks):
    t2 = {k: v for k, v in tasks.items() if k != "round_y"}
    f = tmp_path / "tasks.json"
    f.write_text(json.dumps(t2), encoding="utf-8")
    assert run("order", f, "y01", "a1", "p")[0] == 2
    first = t2["order"][0]
    assert run("order", f, *first)[0] == 0


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
    rc, out = run("cfg", TASKS, "money_rerun.need")
    assert rc == 0 and out.strip() == "1.00"
    assert run("cfg", TASKS, "money_rerun.nope")[0] == 2
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


def test_init_tools_in_tasks_json_ten_names(tasks):
    assert tasks["init_tools"] == ["Read", "Glob", "Grep", "Skill", "Bash", "Write", "Edit", "Agent", "Task", "TaskStop"]
    assert set(INIT9) <= set(tasks["init_tools"]) and set(ALLOWED) == set(tasks["init_tools"])


def test_init_seen_counts_mcp_and_tools_outside_allowed(st):
    a = ALLOWED
    assert st.init_seen([init_ev([], INIT9), init_ev([PEND, PEND], INIT9 + ["WebSearch", "SendMessage"])], a) == (2, 2)
    assert st.init_seen([init_ev([], INIT9), init_ev([], INIT9)], a) == (0, 0)
    assert st.init_seen([init_ev([], INIT9 + ["Agent", "mcp__x__y"]), init_ev([], INIT9 + ["mcp__x__y"])], a) == (0, 1)
    assert st.init_seen([init_ev([], INIT9 + ["TaskStop", "GetTask"])], a) == (0, 1)
    assert st.init_seen([tool("Bash", command="ls"), init_ev()], a) == ("?", "?")
    assert st.init_seen([], a) == ("?", "?")
    assert st.init_seen([init_ev([PEND], None)], a) == (1, "?")
    assert st.init_seen([init_ev(None, INIT9 + ["REPL"])], a) == ("?", 1)
    assert st.init_seen([{"type": "system", "subtype": "hook_started", "mcp_servers": [PEND]}, init_ev([], INIT9)], a) == (0, 0)


def test_outside_used_counts_only_paired_non_error_results(st):
    a = ALLOWED
    f = lambda evs: st.outside_used(evs, a)
    ok = lambda id_: tool_result(id_, "ok")
    assert f([tool_id("Bash", "u1", command="ls"), ok("u1"), tool_id("Task", "u2", prompt="x"), ok("u2")]) == (0, 0)
    assert f([tool_id("WebSearch", "u1", query="x"), ok("u1")]) == (1, 0)
    assert f([tool_id("WebSearch", "u1", query="x"), tool_result_err("u1", "withheld")]) == (0, 0)      # 오류 결과는 안 센다
    assert f([tool_id("WebSearch", "u1", query="x"), tool_result_err("u1", "fine", err=False)]) == (1, 0)
    assert f([tool_id("WebSearch", "u1", query="x")]) == (0, 0)                                          # 짝이 없다
    assert f([tool("WebSearch", query="x")]) == (0, 0)                                                   # id가 없다
    assert f([tool_id("mcp__a__b", "u1"), ok("u1")]) == (0, 1)                                           # mcp__는 따로
    assert f([tool_id("mcp__a__b", "u1"), tool_result_err("u1", "no")]) == (0, 0)
    assert f([tool_id("CronCreate", "u1"), ok("u1"), tool_id("mcp__a__b", "u2"), ok("u2"), tool_id("SendMessage", "u3"), ok("u3")]) == (2, 1)
    # 서브에이전트 안 사건도 센다
    assert f([sub_tool("CronCreate", "u1", "p1"), ok("u1"), sub_tool("mcp__a__b", "u2", "p1"), ok("u2")]) == (1, 1)
    assert f([sub_tool("CronCreate", "u1", "p1"), tool_result_err("u1", "x")]) == (0, 0)
    assert f([]) == (0, 0)


def test_void_reason_new_branches_same_for_both_arms(st, tasks):
    base = {"peek": 0, "peek_result": 0, "link_out": 0, "net": 0}
    for task in ("a1", "b1", "c1"):
        v = lambda d, chk=None: st.void_reason({**base, **d}, chk or {"exit": "0"}, task, tasks)
        assert v({"mcp_used": 1}) == "mcp_used" and v({"tools_out_used": 1}) == "tools_out"
        assert v({"mcp_used": 2, "tools_out_used": 3}) == "mcp_used"
        assert v({"mcp_used": 0, "tools_out_used": 0}) is None and v({"mcp_used": "?", "tools_out_used": "?"}) is None
        assert v({}) is None
        # 무효로 안 치는 것: 참고 값
        assert v({"init_mcp": 4, "init_tools_out": 18, "risky": 3}) is None
        assert v({"init_mcp": 4}, {"exit": "0", "sched": "changed", "sess_extra": "2"}) is None
        # 차례: peek이 앞, kitsha가 뒤
        assert v({"mcp_used": 1, "peek": 1}) == "peek"
        assert v({"mcp_used": 1}, {"exit": "0", "kitsha": "changed"}) == "mcp_used"
        assert v({"tools_out_used": 1}, {"exit": "0", "kitsha": "changed"}) == "tools_out"
    for arm_run in ("r01", "r02"):
        assert st.void_reason({**base, "mcp_used": 1}, {"exit": "0", "run": arm_run}, "c1", tasks) == "mcp_used"


def test_net_count_web_tools_and_web_fetch_subagent(st):
    ok = lambda i: tool_result(i, "ok")
    assert st.net_count([tool_id("WebFetch", "u1", url="x"), ok("u1")]) == (1, 0)
    assert st.net_count([tool_id("WebSearch", "u1", query="x"), ok("u1")]) == (1, 0)
    assert st.net_count([tool_id("WebFetch", "u1", url="x"), tool_result_err("u1", "withheld")]) == (0, 0)
    assert st.net_count([tool_id("Agent", "u1", subagent_type="web-fetch", prompt="x")]) == (1, 0)
    assert st.net_count([tool_id("Task", "u1", subagent_type="web-fetch", prompt="x")]) == (1, 0)
    assert st.net_count([tool_id("Task", "u1", subagent_type="Explore", prompt="x")]) == (0, 0)
    assert st.net_count([sub_tool("WebSearch", "u1", "p", query="x"), ok("u1")]) == (1, 0)
    # 기존 셈은 그대로이고 거기에 더해진다
    assert st.net_count([asst(bash="curl https://example.org/x"), tool_id("WebFetch", "u1", url="x"), ok("u1")]) == (2, 0)


def test_risky_count(st):
    f = lambda cmd: st.risky_count([tool("Bash", command=cmd)])
    for cmd in ("ls /run/user/1000/cc-socks", "cat ~/.claude/sessions/x", "nc -U /x.sock", "socat - UNIX:/x", "python3 -c 'import socket; socket.AF_UNIX'",
                "crontab -l", "systemd-run --user x", "systemctl --user list-timers",
                "claude -p hi", "cd x && claude --resume y", "(claude -p x)", "FOO=1 claude", "/usr/bin/claude -p x", "ls; claude", "echo a | claude",
                '"claude" -p hi', "\\claude -p hi", "$(command -v claude) -p hi", "c=claude; $c -p hi",
                "~/.local/share/claude/versions/9.9.9 -p hi"):
        assert f(cmd) == 1, cmd
    for cmd in ("cat ./claude_notes.md", "ls", "echo claudes", "grep -r foo .", "cat my-claude.md", "python3 -m pytest",
                "ls ~/.claude/", "cat CLAUDE.md", "cat claude.md"):
        assert f(cmd) == 0, cmd
    assert f("npx @anthropic-ai/claude-code -p hi") == 1 and f("node /x/node_modules/claude-code/cli.js -p hi") == 1
    assert st.risky_count([tool("Read", file_path="/run/user/1000/cc-socks/x")]) == 0           # Bash만 본다
    assert st.risky_count([tool("Bash", command="crontab -l"), tool("Bash", command="systemctl status x"), tool("Bash", command="ls")]) == 2


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


def test_count_writes_init_fields_and_log_line(tmp_path, tasks):
    r, out, base, end = count_setup(tmp_path, tasks)
    write(out / "r05.t1.jsonl", [init_ev([], INIT9), result(total_cost_usd=0.4, subtype="success")])
    write(out / "r05.t2.jsonl", [init_ev([PEND], INIT9 + ["CronCreate"]), tool_id("CronCreate", "u1"), tool_result("u1", "ok"),
                                 tool_id("Bash", "u2", command="crontab -l"), tool_result("u2", "ok"), result(total_cost_usd=0.9, subtype="success")])
    rc, txt = run("count", TASKS, out, "r05", "--repo", r)
    d = json.loads((out / "r05.json").read_text(encoding="utf-8"))
    assert rc == 0 and d["init_mcp"] == 1 and d["init_tools_out"] == 1
    assert d["tools_out_used"] == 1 and d["mcp_used"] == 0 and d["risky"] == 1
    first = txt.split("\n")[0]
    assert first.endswith(" init_mcp=1 init_tools_out=1 tools_out_used=1 mcp_used=0 risky=1"), first
    for t in ("t1", "t2"):
        write(out / ("r05.%s.jsonl" % t), [result(total_cost_usd=0.4, subtype="success")])
    rc, txt = run("count", TASKS, out, "r05", "--repo", r)
    d = json.loads((out / "r05.json").read_text(encoding="utf-8"))
    assert d["init_mcp"] == "?" and d["init_tools_out"] == "?" and d["tools_out_used"] == 0 and d["mcp_used"] == 0 and d["risky"] == 0
    assert "init_mcp=? init_tools_out=? tools_out_used=0 mcp_used=0 risky=0" in txt


def test_init_fields_in_table_after_kitleak_and_not_void(st, tasks):
    rows = st.TABLE_ROWS
    i = rows.index("kitleak")
    assert rows[i + 1:i + 6] == ["init_mcp", "init_tools_out", "tools_out_used", "mcp_used", "risky"]
    d = {"peek": 0, "peek_result": 0, "net": 0, "init_mcp": 4, "init_tools_out": 18, "risky": 2}
    assert st.void_reason(d, {"exit": "0"}, "c1", tasks) is None


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


# --- Task 7: after (귀띔 뒤에 한 일) ---

def hook_ev(subtype, event, **out):
    e = {"type": "system", "subtype": subtype, "hook_event": event}
    e.update(out)
    return e


BLOCK_OUT = '{"decision":"block","reason":"x"}'


def test_after_counts_stop_block(st):
    ev1 = [tool("Write", file_path="/w/a.py"),
           hook_ev("hook_started", "Stop"),
           hook_ev("hook_response", "Stop", stdout=BLOCK_OUT),
           tool("Bash", command="ls"),
           tool("Skill", skill="devkit:check"),
           result(result="끝내기 전 점검:\n…")]
    a = st.after_of({}, ev1, [])
    assert a["hook"] == {"started": 1, "responses": 1, "interjections": 1}
    assert a["after"] == [{"turn": "t1", "after_n": 1, "next": [2, 3]}]
    assert a["check_read"] is True
    assert a["check_line"] == {"t1": True, "t2": False}
    assert a["missing_stage"] == 0
    assert a["events_seen"] == {"hook_started:Stop": 1, "hook_response:Stop": 1}


def test_after_ignores_other_events_and_non_block(st):
    ev1 = [hook_ev("hook_response", "PreToolUse", stdout=BLOCK_OUT),
           hook_ev("hook_response", "Stop", stdout=""),
           hook_ev("hook_response", "Stop", stdout="not json"),
           hook_ev("hook_response", "Stop", stdout='{"decision":"approve"}')]
    a = st.after_of({}, ev1, [])
    assert a["hook"]["interjections"] == 0
    assert a["after"] == []
    assert a["events_seen"] == {"hook_response:PreToolUse": 1, "hook_response:Stop": 3}


def test_after_hook_keys_from_config(st):
    cfg = {"hook_y": {"event_key": "hook_name", "event": "Stop:end", "out_keys": ["output"]}}
    ev1 = [{"type": "system", "subtype": "hook_started", "hook_name": "Stop:end"},
           {"type": "system", "subtype": "hook_response", "hook_name": "Stop:end", "output": ' ' + BLOCK_OUT + '\n'},
           {"type": "system", "subtype": "hook_response", "hook_name": "Stop:end", "stdout": BLOCK_OUT},
           hook_ev("hook_response", "Stop", stdout=BLOCK_OUT)]
    a = st.after_of(cfg, ev1, [])
    assert a["hook"] == {"started": 1, "responses": 2, "interjections": 1}
    assert a["events_seen"] == {"hook_started:Stop:end": 1, "hook_response:Stop:end": 2, "hook_response:None": 1}
    assert st.hook_cfg({})["decision"] == "block" and st.hook_cfg(cfg)["event"] == "Stop:end"
    assert st.hook_cfg(cfg)["type"] == "system"


def test_after_tool_numbers_span_turns(st):
    ev1 = [tool("Read", file_path="/w/x"), tool("Edit", file_path="/w/y"), result(result="ok")]
    ev2 = [tool("Bash", command="pytest -q"), result(result="ok")]
    a = st.after_of({}, ev1, ev2)
    assert [(t["n"], t["turn"], t["name"], t["what"]) for t in a["tools"]] == [
        (1, "t1", "Read", "/w/x"), (2, "t1", "Edit", "/w/y"), (3, "t2", "Bash", "pytest -q")]
    b = st.after_of({}, [tool("Skill", skill="devkit:find"), tool("NotebookEdit", notebook_path="/w/n.ipynb"),
                         tool("Glob", pattern="*")], [])
    assert [t["what"] for t in b["tools"]] == ["devkit:find", "/w/n.ipynb", ""]


def test_after_missing_stage_count(st):
    ev1 = [result(result="없는 단계: x — 한 장대로 했다")]
    ev2 = [result(result="끝")]
    assert st.after_of({}, ev1, ev2)["missing_stage"] == 1
    assert st.after_of({}, ev1, ev1)["missing_stage"] == 2
    assert st.after_of({}, [], [])["missing_stage"] == 0


def test_after_cli_writes_only_given_dir(st, tmp_path):
    t1 = [tool("Write", file_path="/w/a.py"), hook_ev("hook_response", "Stop", stdout=BLOCK_OUT),
          tool("Skill", skill="devkit:check"), result(result="끝내기 전 점검:\n…")]
    for d in ("kit09", "out-done/ruler2", "out-done/kit09/..", "other", "out-done"):
        p = tmp_path / d
        p.mkdir(parents=True, exist_ok=True)
    for d in ("kit09", "out-done/ruler2", "other", "out-done"):
        write(tmp_path / d / "y01.t1.jsonl", t1)
    assert st.cmd_after({}, str(tmp_path / "kit09"), "y01") == 0
    got = json.loads((tmp_path / "kit09" / "y01.after.json").read_text(encoding="utf-8"))
    assert got["run"] == "y01" and got["hook"]["interjections"] == 1 and got["check_read"] is True
    assert got["after"] == [{"turn": "t1", "after_n": 1, "next": [2]}]
    (tmp_path / "kit09" / "y01.after.json").unlink()
    assert st.cmd_after({}, str(tmp_path / "kit09") + "/", "y01") == 0
    assert (tmp_path / "kit09" / "y01.after.json").exists()
    (tmp_path / "kit09" / "y01.after.json").unlink()
    for d in ("out-done", "out-done/ruler2", "out-done/kit09/..", "other"):
        assert st.cmd_after({}, str(tmp_path / d), "y01") == 2
    assert not list(tmp_path.rglob("*.after.json"))
    assert st.cmd_after({}, str(tmp_path / "kit09"), "y02") == 2
    assert st.cmd_after({}, str(tmp_path / "kit09"), "../y01") == 2
    assert not list(tmp_path.rglob("*.after.json"))
    # t2가 없어도 되고, 있으면 쓴다
    write(tmp_path / "kit09" / "y03.t1.jsonl", [tool("Bash", command="ls")])
    write(tmp_path / "kit09" / "y03.t2.jsonl", [tool("Bash", command="pwd")])
    assert st.cmd_after({}, str(tmp_path / "kit09"), "y03") == 0
    got = json.loads((tmp_path / "kit09" / "y03.after.json").read_text(encoding="utf-8"))
    assert [t["turn"] for t in got["tools"]] == ["t1", "t2"]


def test_after_cli_line_and_usage(tmp_path):
    d = tmp_path / "kit09"
    d.mkdir()
    write(d / "y01.t1.jsonl", [tool("Skill", skill="devkit:check"), hook_ev("hook_started", "Stop"),
                               hook_ev("hook_response", "Stop", stdout=BLOCK_OUT), result(result="끝내기 전 점검: 됨")])
    rc, out = run("after", M / "stage" / "tasks.json", d, "y01")
    assert rc == 0
    assert out.strip() == "y01 끼어듦=1 시작=1 점검읽음=1 점검줄=1/0 없는단계=0 도구=1"
    rc, out = run("after", M / "stage" / "tasks.json", tmp_path / "other", "y01")
    assert rc == 2 and "kit09 폴더에만 씀" in out


# --- Task 8: compare (앞·뒤 견주기와 판정) ---

def wj(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


Y_ROWS = [["w01", "a3", "q"], ["w02", "a3", "q"], ["w03", "b3", "q"], ["w04", "b3", "q"],
          ["y01", "a1", "q"], ["y02", "a1", "q"], ["y03", "a2", "q"], ["y04", "a2", "q"],
          ["y05", "b1", "q"], ["y06", "b1", "q"], ["y07", "b2", "q"], ["y08", "b2", "q"],
          ["y09", "c1", "q"], ["y10", "c1", "q"], ["y11", "c2", "q"], ["y12", "c2", "q"],
          ["y13", "a3", "q"], ["y14", "a3", "q"], ["y15", "b3", "q"], ["y16", "b3", "q"],
          ["y00", "z0", "q", "a1"]]


def fake_y_cfg(tasks):
    return {"kinds": tasks["kinds"], "void_exits": tasks["void_exits"],
            "tasks": {t: {"stage": t[0], "helpers": dict((tasks["tasks"].get(t) or {}).get("helpers") or {})}
                      for t in ("a1", "a2", "a3", "b1", "b2", "b3", "c1", "c2", "z0")},
            "round_y": [list(r) for r in Y_ROWS],
            "y_before": {"t3_scene": "Q1", "h2_scene": "U9", "g4": {"c1": {}, "c2": {}},
                         "cost": {t: "1.00" for t in ("a1", "a2", "b1", "b2", "c1", "c2")}}}


def _y_kinds(tasks, run, task):
    stage = task[0]
    if stage == "a":
        return {"덧붙임": 2 if run[0] == "w" else (1 if task == "a3" else 0)}
    if stage not in "bc":
        return {}
    k = {n: 0 for n in tasks["kinds"][stage]}
    if not (tasks["tasks"].get(task) or {}).get("helpers"):
        k.pop("또만듦", None)                 # 세는 쪽(machine_kinds)도 도우미가 없는 일감에는 이 종류를 안 쓴다
    if task == "b2":
        k["장면안됨"] = 2
    if task == "b3":
        k["장면안됨"] = 2 if run[0] == "w" else 1
    return k


def y_world(tmp_path, tasks, val=None, chk=None, after=None, walk=None, ran=None, prior=None, cost=None, extra=None, with_ran=True, drop=()):
    """가짜 kit09 폴더. val={실행: {종류: 값}} · chk={실행: {열쇠: 값} 또는 None(.check 없음)} · after={실행: {…}}."""
    val, chk, after, walk, ran, cost = val or {}, chk or {}, after or {}, walk or {}, ran or {}, cost or {}
    cfg = fake_y_cfg(tasks)
    cfg["round_y"] += [list(r) for r in (extra or [])]
    cfg["round_y"] = [r for r in cfg["round_y"] if r[0] not in drop]
    out = tmp_path / "kit09"
    out.mkdir(parents=True)
    eye, key, count, ranfile = {}, {}, {}, {}
    for row in cfg["round_y"]:
        run, task, arm = row[:3]
        wj(out / (run + ".json"), {"run": run, "task": task, "arm": arm, "cost": cost.get(run, "1.00")})
        if chk.get(run, {}) is not None:
            c = {"exit": "0", "run": run, "task": task, "arm": arm, "t2": "sent", "secs": "5"}
            c.update(chk.get(run, {}))
            (out / (run + ".check")).write_text("".join("%s=%s\n" % kv for kv in c.items()), encoding="utf-8")
        if task[0] == "b" and walk.get(run, {}) is not None:
            w = {"Q1": True, "U9": True}
            w.update(walk.get(run, {}))
            wj(out / (run + ".walk.json"), w)
        if run[0] == "y":
            a = {"run": run, "hook": {"started": 1, "responses": 1, "interjections": 1}, "events_seen": {}, "check_read": True,
                 "check_line": {"t1": True, "t2": True}, "missing_stage": 0, "tools": [], "after": []}
            a.update(after.get(run, {}))
            wj(out / (run + ".after.json"), a)
        if task != "z0":
            n = count.get(task, 0)
            count[task] = n + 1
            letter = chr(65 + n)
            kinds = _y_kinds(tasks, run, task)
            kinds.update(val.get(run, {}))
            eye.setdefault(task, {})[letter] = kinds
            key.setdefault(task, {})[letter] = run
        if task in ("a1", "a2", "a3"):
            ranfile[run] = {"켜봄": ran.get(run, run[0] == "y"), "근거": [1]}
    if prior is None:
        prior = {"a1": ("r03", 3), "a2": ("r04", 1)}
    for task, (prun, v) in prior.items():
        eye[task]["P"] = {"덧붙임": v}
        key[task]["P"] = prun
    wj(out / "eye.json", eye)
    wj(out / "eye-key.json", key)
    if with_ran:
        wj(out / "ran.json", ranfile)
    return cfg, out


def test_compare_keep_when_two_t_and_one_h(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks)
    c = st.compare(cfg, str(out))
    assert [c[k]["result"] for k in ("T1", "T2", "T3", "T4")] == ["나아짐"] * 4
    assert c["T1"]["old"] == [3, 3] and c["T1"]["new"] == [0, 0]
    assert [c[k]["result"] for k in ("H1", "H2", "H3")] == ["나아짐"] * 3
    assert c["G1"]["result"] == c["G2"]["result"] == c["G3"]["result"] == c["G4"]["result"] == "통과"
    assert c["T5"]["result"] == "통과" and c["hook_none"] == [] and c["left_runs"] == [] and c["replaced"] == []
    assert c["judgment"] == "남긴다"
    assert st.compare_text(c)


def test_compare_shaky_when_one_of_two(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, val={"y01": {"덧붙임": 2}, "y02": {"덧붙임": 3}})
    c = st.compare(cfg, str(out))
    assert c["T1"]["new"] == [2, 3] and c["T1"]["result"] == "흔들림"
    out2 = y_world(tmp_path / "b", tasks, val={"y01": {"덧붙임": 3}, "y02": {"덧붙임": 4}})
    assert st.compare(*out2)["T1"]["result"] == "안나아짐"


def test_compare_t3_needs_scene_both(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, val={"y07": {"장면안됨": 3}, "y08": {"장면안됨": 3}},
                       walk={"y08": {"Q1": False}})
    c = st.compare(cfg, str(out))
    assert c["T3"]["new"] == [3, 3] and c["T3"]["result"] == "흔들림"
    cfg, out = y_world(tmp_path / "b", tasks, val={"y07": {"장면안됨": 4}, "y08": {"장면안됨": 3}})
    assert st.compare(cfg, str(out))["T3"]["result"] == "흔들림"


def test_compare_eye_override(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, prior={"a1": ("r03", 2), "a2": ("r04", 0)})
    c = st.compare(cfg, str(out))
    assert c["T1"]["result"] == "안나아짐(눈)" and c["T2"]["result"] == "안나아짐(눈)"
    assert c["T3"]["result"] == "나아짐"
    cfg, out = y_world(tmp_path / "b", tasks, prior={"a1": ("r03", 3), "a2": ("r04", 1)})
    c = st.compare(cfg, str(out))
    assert c["T1"]["result"] == "나아짐" and c["T2"]["result"] == "나아짐"


def test_compare_eye_guard_missing_is_unknown(st, tasks, tmp_path):
    # 섞어 넣은 앞 실행이 눈 묶음에 없으면(또는 눈이 못 셌으면) 보호 장치를 못 본 것 — 나아짐으로 치지 않는다
    cfg, out = y_world(tmp_path / "a", tasks, prior={})
    c = st.compare(cfg, str(out))
    assert c["T1"]["result"] == "모름" and c["T2"]["result"] == "모름" and c["judgment"] == "미룸(모름)"
    cfg, out = y_world(tmp_path / "b", tasks, prior={"a1": ("r03", "?"), "a2": ("r04", 1)})
    c = st.compare(cfg, str(out))
    assert c["T1"]["result"] == "모름" and c["T2"]["result"] == "나아짐"
    # 새 값이 이미 선을 못 넘으면 보호 장치와 상관없이 안나아짐
    cfg, out = y_world(tmp_path / "c", tasks, prior={}, val={"y01": {"덧붙임": 3}, "y02": {"덧붙임": 4}})
    assert st.compare(cfg, str(out))["T1"]["result"] == "안나아짐"


def test_compare_cost_unknown_note(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, cost={"y01": "?"})
    c = st.compare(cfg, str(out))
    assert c["cost_ratio"] is None and any("돈" in n and "못" in n for n in c["notes"])


def test_after_marks_subagent_tools(st, tasks):
    def tu(name, inp, parent=None):
        e = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": name, "input": inp}]}}
        if parent:
            e["parent_tool_use_id"] = parent
        return e
    a = st.after_of(tasks, [tu("Edit", {"file_path": "/w/a.py"}), tu("Edit", {"file_path": "/w/b.py"}, parent="toolu_x")], [])
    assert [t.get("sub", False) for t in a["tools"]] == [False, True] and "sub" not in a["tools"][0]


def test_compare_h_dropped_when_old_zero_and_both_dropped_note(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, val={"w01": {"덧붙임": 0}, "w02": {"덧붙임": 0},
                                             "w03": {"장면안됨": 0}, "w04": {"장면안됨": 0}})
    c = st.compare(cfg, str(out))
    assert c["H1"]["result"] == "뺌" and c["H2"]["result"] == "뺌"
    assert c["judgment"] == "그 사이"
    assert "처음 보는 일감으로는 가리지 못했다" in c["notes"]


def test_compare_worse_h_drops(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, val={"y15": {"장면안됨": 3}, "y16": {"장면안됨": 3}})
    c = st.compare(cfg, str(out))
    assert c["H2"]["result"] == "나빠짐" and c["judgment"] == "뺀다"
    cfg, out = y_world(tmp_path / "b", tasks, val={"y13": {"덧붙임": 3}, "y14": {"덧붙임": 2}})
    c = st.compare(cfg, str(out))
    assert c["H1"]["result"] == "나빠짐" and c["judgment"] == "뺀다"


def test_compare_stage_only(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, val={"y13": {"덧붙임": 2}, "y14": {"덧붙임": 2}, "y15": {"장면안됨": 2}, "y16": {"장면안됨": 2}},
                       ran={"y13": False, "y14": False})
    c = st.compare(cfg, str(out))
    assert [c[k]["result"] for k in ("H1", "H2")] == ["그대로", "그대로"] and c["H3"]["result"] == "안나아짐"
    assert c["judgment"] == "이 무대에만"


def test_compare_g3_defer(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path / "a", tasks, chk={"y01": {"exit": "11"}})
    c = st.compare(cfg, str(out))
    assert c["judgment"] == "미룸(G3)" and c["left_runs"] == ["y01"]
    cfg, out = y_world(tmp_path / "b", tasks, chk={"y02": {"t2": "skip:money"}})
    assert st.compare(cfg, str(out))["judgment"] == "미룸(G3)"
    void = [x for x in tasks["void_exits"] if x not in (0, 11)][0]
    cfg, out = y_world(tmp_path / "c", tasks, chk={"y03": {"exit": str(void)}})
    c = st.compare(cfg, str(out))
    assert c["judgment"] == "미룸(G3)" and c["G3"]["result"] == "실패"


def test_compare_g3_exits_y_accepts_11(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path / "a", tasks, chk={"y01": {"exit": "11"}})
    cfg["g3_exits_y"] = ["0", "11"]
    c = st.compare(cfg, str(out))
    assert c["G3"]["result"] == "통과" and c["left_runs"] == ["y01"] and c["judgment"] == "남긴다"
    cfg, out = y_world(tmp_path / "b", tasks, chk={"y01": {"exit": "11", "t2": "skip:surv"}})
    cfg["g3_exits_y"] = ["0", "11"]
    c = st.compare(cfg, str(out))
    assert c["judgment"] == "미룸(G3)" and c["left_runs"] == ["y01"]


def test_compare_g3_ignores_y00(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path / "a", tasks, chk={"y00": None})
    assert not (out / "y00.check").exists()
    c = st.compare(cfg, str(out))
    assert c["G3"]["result"] == "통과" and c["judgment"] == "남긴다"
    assert "y00" not in json.dumps(c, ensure_ascii=False)
    cfg, out = y_world(tmp_path / "b", tasks, chk={"y00": {"exit": "9"}})
    c = st.compare(cfg, str(out))
    assert c["G3"]["result"] == "통과" and "y00" not in json.dumps(c, ensure_ascii=False)


def test_compare_redo_y_replaces(st, tasks, tmp_path):
    void = [x for x in tasks["void_exits"] if x not in (0, 11)][0]
    cfg, out = y_world(tmp_path / "a", tasks, extra=[["y21", "a2", "q"]], chk={"y03": {"exit": str(void)}},
                       val={"y04": {"덧붙임": 0}, "y21": {"덧붙임": 5}})
    cfg["redo_y"] = {"y03": "y21"}
    c = st.compare(cfg, str(out))
    assert c["replaced"] == [{"old": "y03", "new": "y21", "exit": str(void)}]
    assert c["T2"]["new"] == [0, 5] and c["T2"]["result"] == "흔들림"
    assert c["G3"]["result"] == "통과"
    assert "y03" not in json.dumps({k: v for k, v in c.items() if k != "replaced"}, ensure_ascii=False)
    assert [s["run"] for s in c["side"]].count("y21") == 1 and "y03" not in [s["run"] for s in c["side"]]
    for bad in ({"y03": "y99"}, {"y03": "y05"}, {"y99": "y21"}):
        cfg["redo_y"] = bad
        assert st.cmd_compare(cfg, str(out)) == 2
        assert not (out / "compare.json").exists()
    cfg["redo_y"] = {"y03": "y21"}
    assert st.cmd_compare(cfg, str(out)) == 0 and (out / "compare.json").exists()


def test_compare_hook_none_four_defer(st, tasks, tmp_path):
    miss = {"hook": {"started": 1, "responses": 1, "interjections": 0}, "check_line": {"t1": False, "t2": False},
            "tools": [{"n": 1, "turn": "t1", "name": "Write", "what": "/w/a.py"}]}
    cfg, out = y_world(tmp_path / "a", tasks, after={r: miss for r in ("y01", "y02", "y03", "y04")})
    c = st.compare(cfg, str(out))
    assert c["hook_none"] == ["y01", "y02", "y03", "y04"] and c["judgment"] == "미룸(훅)"
    cfg, out = y_world(tmp_path / "b", tasks, after={r: miss for r in ("y01", "y02", "y03")})
    c = st.compare(cfg, str(out))
    assert len(c["hook_none"]) == 3 and c["judgment"] == "남긴다"


def test_compare_hook_none_definition(st, tasks, tmp_path):
    def after(inter, tools, t1, t2):
        return {"hook": {"started": 1, "responses": 1, "interjections": inter}, "check_line": {"t1": t1, "t2": t2},
                "tools": [{"n": i + 1, "turn": tu, "name": nm, "what": w} for i, (tu, nm, w) in enumerate(tools)]}
    cfg, out = y_world(tmp_path, tasks, after={
        "y01": after(0, [("t1", "Write", "/w/a.py")], True, True),               # 점검 줄이 있다
        "y02": after(0, [("t1", "Edit", "/w/.devkit/x.md")], False, False),        # .devkit 아래만
        "y03": after(0, [], False, False),                                         # 고친 도구 없음
        "y04": after(1, [("t1", "Write", "/w/a.py")], False, False),               # 끼어듦 있음
        "y05": after(0, [("t1", "Write", "/w/a.py"), ("t2", "Edit", "/w/b.py")], True, False),   # t2만 줄 없음
        "y06": after(0, [("t1", "Bash", "ls")], False, False),                     # 고치는 도구 아님
        "y07": after(0, [("t2", "NotebookEdit", "/w/.devkit-notes/n.ipynb")], True, False)})   # 조각이 통째로 .devkit이 아님
    c = st.compare(cfg, str(out))
    assert c["hook_none"] == ["y05", "y07"]


def _set_files(out, run_, n):
    p = out / (run_ + ".json")
    d = json.loads(p.read_text(encoding="utf-8"))
    d["files"] = n
    wj(p, d)


def _hook_after(inter, tools, t1, t2):
    return {"hook": {"started": 1, "responses": 1, "interjections": inter}, "check_line": {"t1": t1, "t2": t2},
            "tools": [{"n": i + 1, "turn": tu, "name": nm, "what": w} for i, (tu, nm, w) in enumerate(tools)]}


def test_compare_hook_none_work_dir_and_shell_only(st, tasks, tmp_path, monkeypatch):
    monkeypatch.delenv("STAGE_X", raising=False)
    own = "abcd1234"
    W = str(tmp_path / "X" / "run" / own / "w")
    runs = ("y01", "y02", "y03", "y04", "y05", "y06", "y07", "y08", "y09", "y10", "y11", "y12", "y13", "y14")
    make = ("t1", "Bash", "make")
    cfg, out = y_world(tmp_path, tasks, chk={r: {"own": own} for r in runs}, after={
        "y01": _hook_after(0, [("t1", "Write", W + "/a.py")], False, False),                  # 작업 폴더 아래 → 빠짐
        "y02": _hook_after(0, [("t1", "Write", "/tmp/zz-check.py")], False, False),           # 폴더 밖 임시 파일만 · 바뀐 파일 없음 → 아님
        "y03": _hook_after(0, [("t1", "Write", "/tmp/zz-check.py"), ("t1", "Bash", "make")], False, False),  # 셸로만 · 빠짐
        "y04": _hook_after(0, [make], True, False),                                           # 셸로만 · 셸 쓴 턴에 줄 있음 → 빠짐 아님
        "y05": _hook_after(1, [make], False, False),                                          # 셸로만 · 끼어듦 있음 → 빠짐 아님
        "y06": _hook_after(0, [("t1", "Edit", W + "/.devkit/g.md"), make], False, False),     # .devkit만 + 셸 → 셸로만 · 빠짐
        "y07": _hook_after(0, [("t1", "Write", "src/a.py")], False, False),                   # 상대 길 = 작업 폴더 아래 → 빠짐
        "y08": _hook_after(0, [("t1", "Write", W + "/../w2/a.py")], False, False),            # .. 로 나감 → 아님
        "y09": _hook_after(0, [make], False, False),                                          # 바뀐 파일 수를 모름 → 아님
        "y10": _hook_after(0, [make, ("t2", "Bash", "make")], False, True),                   # 두 턴 다 셸 · 한쪽에 줄 → 세지 않음
        "y11": _hook_after(0, [("t2", "bash", "make")], True, False),                         # 둘째 턴에만 셸 · 그 턴 줄 없음 → 빠짐
        "y12": _hook_after(0, [("t1", "Read", "a.py")], False, False),                        # 바꿀 수 있는 도구 없음 → 세지 않음
        "y13": _hook_after(0, [("t1", "Write", W + "/sub/../a.py")], False, False),           # .. 조각 → 고침 아님
        "y14": _hook_after(0, [("t1", "mcp__zz__write", "x"), ("t2", "Agent", "x")], False, False)})   # 맡김 도구 · 두 턴 다 줄 없음 → 빠짐
    cfg["work"] = str(tmp_path / "X")
    for r_, n in (("y03", 2), ("y04", 1), ("y05", 1), ("y06", 1), ("y08", 0), ("y10", 1), ("y11", 1), ("y12", 1), ("y14", 3)):
        _set_files(out, r_, n)
    _set_files(out, "y09", "?")
    c = st.compare(cfg, str(out))
    assert c["shell_only"] == ["y03", "y04", "y05", "y06", "y10", "y11", "y12", "y14"]
    assert c["hook_none"] == ["y01", "y03", "y06", "y07", "y11", "y14"] and c["judgment"] == "미룸(훅)"
    text = st.compare_text(c)
    assert "- 셸로만 고침: y03, y04, y05, y06, y10, y11, y12, y14" in text
    assert "- 훅 빠짐: y01, y03, y06, y07, y11, y14" in text
    for name, loud in (("Bash", True), ("PowerShell", True), ("REPL", True), ("Agent", True), ("Task", True), ("mcp__zz", True),
                       ("agent", False), ("Read", False), ("Write", False), ("", False), (None, False)):
        assert st._changing_tool(name) is loud, name


def test_compare_work_dir_env_first_and_missing_own(st, tasks, tmp_path, monkeypatch):
    own = "abcd1234"
    monkeypatch.setenv("STAGE_X", str(tmp_path / "E"))
    WE = str(tmp_path / "E" / "run" / own / "w")
    WC = str(tmp_path / "X" / "run" / own / "w")
    cfg, out = y_world(tmp_path, tasks, chk={"y01": {"own": own}, "y02": {"own": own}}, after={
        "y01": _hook_after(0, [("t1", "Write", WE + "/a.py")], False, False),     # 환경의 뿌리 → 빠짐
        "y02": _hook_after(0, [("t1", "Write", WC + "/a.py")], False, False),     # 설정의 뿌리는 환경에 밀림 → 아님
        "y03": _hook_after(0, [("t1", "Write", "/w/a.py")], False, False)})       # own 없음 → 지금의 잣대 → 빠짐
    cfg["work"] = str(tmp_path / "X")
    c = st.compare(cfg, str(out))
    assert c["hook_none"] == ["y01", "y03"] and c["shell_only"] == []
    cfg2, out2 = y_world(tmp_path / "b", tasks)
    c2 = st.compare(cfg2, str(out2))
    assert c2["shell_only"] == [] and "- 셸로만 고침: 없음" in st.compare_text(c2)


def test_compare_side_table(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, val={"y07": {"나쁜베낌": 1}}, cost={"y01": "2.00"},
                       chk={"y02": {"exit": "11"}}, ran={"y03": False})
    c = st.compare(cfg, str(out))
    side = {s["run"]: s for s in c["side"]}
    assert len(c["side"]) == 20 and "y00" not in side
    assert side["w01"]["kit"] == "old" and side["y01"]["kit"] == "new"
    assert side["y03"]["ran"] is False and side["y04"]["ran"] is True and side["y05"]["ran"] is None
    assert side["y07"]["나쁜베낌"] == 1 and side["y05"]["나쁜베낌"] == 0 and side["y01"]["나쁜베낌"] is None
    assert side["y01"]["cost"] == 2.0 and side["y01"]["cost_x"] == 2.0 and side["y04"]["cost_x"] == 1.0
    assert side["w01"]["cost_x"] is None or side["w01"]["cost_x"] == 1.0
    assert side["y02"]["exit"] == "11" and side["y02"]["left"] is True and side["y01"]["left"] is False
    assert side["y01"]["t2"] == "sent" and side["y01"]["interjections"] == 1 and side["y01"]["check_read"] is True
    assert side["y01"]["check_line"] == {"t1": True, "t2": True} and side["w01"]["interjections"] is None
    text = st.compare_text(c)
    assert "곁 표" in text and "y07" in text and "판정" in text


def test_compare_ignores_runs_outside_round_y(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks)
    wj(out / "y44.json", {"run": "y44", "task": "a1", "arm": "q", "cost": "9.00"})
    (out / "y44.check").write_text("exit=11\nrun=y44\ntask=a1\narm=q\nt2=skip:money\n", encoding="utf-8")
    c = st.compare(cfg, str(out))
    assert "y44" not in json.dumps(c, ensure_ascii=False) and c["judgment"] == "남긴다"


def test_compare_unknown_defer(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, with_ran=False)
    c = st.compare(cfg, str(out))
    assert c["T4"]["result"] == "모름" and c["judgment"] == "미룸(모름)"
    cfg, out = y_world(tmp_path / "b", tasks, val={"y01": {"덧붙임": "?"}})
    c = st.compare(cfg, str(out))
    assert c["T1"]["result"] == "모름" and c["judgment"] == "미룸(모름)"
    cfg, out = y_world(tmp_path / "c", tasks)
    (out / "y02.json").unlink()
    c = st.compare(cfg, str(out))
    assert c["T1"]["result"] == "모름"


def test_compare_g1_g4_lines(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path / "a", tasks, val={"y05": {"관계없는줄": 3}})
    c = st.compare(cfg, str(out))
    assert c["G1"]["result"] == "실패" and c["judgment"] == "뺀다"
    cfg, out = y_world(tmp_path / "b", tasks, val={"y05": {"관계없는줄": 2, "나쁜베낌": 1}, "y06": {"관계없는줄": 2}})
    assert st.compare(cfg, str(out))["G1"]["result"] == "통과"
    kind = tasks["kinds"]["c"][0]
    cfg, out = y_world(tmp_path / "c", tasks, val={"y09": {kind: 1}})
    c = st.compare(cfg, str(out))
    assert c["G4"]["result"] == "실패" and c["judgment"] == "뺀다"
    cfg["y_before"]["g4"]["c1"] = {kind: 1}
    assert st.compare(cfg, str(out))["G4"]["result"] == "통과"


def test_compare_g4_one_run_each(st, tasks, tmp_path):
    # 진짜 차례는 큰 무대(c1·c2)를 한 번씩만 돌린다 — 그래도 G4는 판정이 난다
    cfg, out = y_world(tmp_path / "a", tasks, drop=("y10", "y12"))
    c = st.compare(cfg, str(out))
    assert c["G4"]["result"] == "통과" and c["judgment"] == "남긴다"
    kind = tasks["kinds"]["c"][0]
    cfg, out = y_world(tmp_path / "b", tasks, drop=("y10", "y12"), val={"y11": {kind: 1}})
    c = st.compare(cfg, str(out))
    assert c["G4"]["result"] == "실패" and c["judgment"] == "뺀다"
    cfg, out = y_world(tmp_path / "c", tasks, drop=("y09", "y10"))
    assert st.compare(cfg, str(out))["G4"]["result"] == "모름"


def test_compare_d1_and_cost_note(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path / "a", tasks)
    c = st.compare(cfg, str(out))
    assert c["d1"] == "남긴다" and "가볍게 하기" not in " ".join(c["notes"]) and abs(c["cost_ratio"] - 1.0) < 1e-9
    cfg, out = y_world(tmp_path / "b", tasks, after={"y01": {"missing_stage": 1}})
    c = st.compare(cfg, str(out))
    assert c["T5"]["result"] == "실패" and c["d1"] == "판정을 따른다" and c["judgment"] == "남긴다"
    cost = {r[0]: "2.50" for r in Y_ROWS if r[0][0] == "y" and r[1] != "z0"}
    cfg, out = y_world(tmp_path / "c", tasks, cost=cost)
    c = st.compare(cfg, str(out))
    assert abs(c["cost_ratio"] - 2.5) < 1e-9 and any("가볍게 하기" in n for n in c["notes"])


def test_compare_eye_reads_prior_run_from_eye_files_only(st, tasks, tmp_path):
    cfg, out = y_world(tmp_path, tasks, prior={"a1": ("r03", 2), "a2": ("r04", 1)})
    assert not list(out.glob("r03*")) and not list(out.glob("r04*"))
    c = st.compare(cfg, str(out))
    assert c["T1"]["result"] == "안나아짐(눈)" and c["T2"]["result"] == "나아짐"
    assert "r03" not in json.dumps(c, ensure_ascii=False) and "r04" not in json.dumps(c, ensure_ascii=False)


def test_compare_refuses_other_dirs(st, tasks, tmp_path):
    cfg, _ = y_world(tmp_path / "ok", tasks)
    (tmp_path / "bad" / "out-done" / "kit09").mkdir(parents=True)
    (tmp_path / "bad" / "out-done" / "ruler2").mkdir()
    (tmp_path / "bad" / "other").mkdir()
    for d in ("out-done", "out-done/ruler2", "other", "out-done/kit09/.."):
        assert st.cmd_compare(cfg, str(tmp_path / "bad" / d)) == 2
    assert not list((tmp_path / "bad").rglob("compare.json"))
    wj(tmp_path / "cfg.json", cfg)
    rc, txt = run("compare", tmp_path / "cfg.json", tmp_path / "bad" / "other")
    assert rc == 2 and "kit09" in txt
    rc, txt = run("compare", tmp_path / "cfg.json", tmp_path / "ok" / "kit09")
    assert rc == 0 and "남긴다" in txt
    got = json.loads((tmp_path / "ok" / "kit09" / "compare.json").read_text(encoding="utf-8"))
    assert got["judgment"] == "남긴다" and got["T1"]["result"] == "나아짐"


def test_table_and_judge_text_unchanged_for_old_dirs(tmp_path):
    out = tmp_path / "o"
    out.mkdir()

    def mj(run_, task, arm):
        wj(out / (run_ + ".json"), {"run": run_, "task": task, "arm": arm, "rc": 0, "공": 1})
        (out / (run_ + ".check")).write_text("exit=0\nrun=%s\ntask=%s\narm=%s\n" % (run_, task, arm), encoding="utf-8")

    mj("r05", "b1", "p")
    mj("r06", "b1", "q")
    wj(out / "r05.walk.json", {"E1": True, "S1": False, "S2": False})
    wj(out / "r06.walk.json", {"E1": True, "S1": True, "S2": True})
    wj(out / "eye.json", {"b1": {"A": {"나쁜베낌": 0, "또만듦": 0, "관계없는줄": 0, "notes": []},
                                 "B": {"나쁜베낌": 2, "또만듦": 0, "관계없는줄": 0, "notes": []}}})
    wj(out / "eye-key.json", {"b1": {"A": "r06", "B": "r05"}})
    rc, before_txt = run("judge", TASKS, out)
    before = (out / "judge.json").read_text(encoding="utf-8")
    assert rc == 0
    mj("w01", "b1", "p")
    mj("y01", "b1", "q")
    wj(out / "y01.walk.json", {"E1": True, "S1": False})
    rc, after_txt = run("judge", TASKS, out)
    assert rc == 0 and after_txt == before_txt and (out / "judge.json").read_text(encoding="utf-8") == before
