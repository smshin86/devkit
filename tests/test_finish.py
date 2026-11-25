import ast
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_check import BED_WORDS

KIT = Path(__file__).resolve().parents[1] / "kit"
SCRIPT = KIT / "scripts" / "finish.py"
CHECK = KIT / "skills/check/SKILL.md"
HOOKS = KIT / "hooks/hooks.json"

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("devkit_finish", SCRIPT)
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

# test_mask.py와 같은 목록
PY39 = [r"\b(list|dict|tuple|set)\[", r"functools import cache\b", r"\w\s*\|\s*None", r"\.removeprefix\(", r"\.removesuffix\(",
        r"is_relative_to\(", r"^\s*match\s.+:\s*$"]

GAP = ...   # payload에서 열쇠를 뺀다는 표시


@pytest.fixture(autouse=True)
def _no_project_dir(monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)     # Claude Code 안에서 돌려도 같은 결과


def run(raw, home, cwd, env=None):
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    e = {"PATH": os.environ["PATH"], "HOME": str(home)}
    e.update(env or {})
    return subprocess.run([sys.executable, "-I", "-S", str(SCRIPT)], input=data, cwd=str(cwd),
                          env=e, capture_output=True, timeout=30)


def snap(d):
    d = Path(d)
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts}


def user_text(s, **top):
    return dict({"type": "user", "message": {"role": "user", "content": s}}, **top)


def user_blocks(*blocks):
    return {"type": "user", "message": {"role": "user", "content": list(blocks)}}


def tool_result():
    return user_blocks({"type": "tool_result", "tool_use_id": "t1", "content": "ok"})


def assistant_tool(name, **inp):
    return {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": name, "input": inp}]}}


def write_tx(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines), encoding="utf-8")
    return path


def payload(tx, active=False, last="끝났다", cwd="/p"):
    d = {"hook_event_name": "Stop", "transcript_path": str(tx)}
    if active is not GAP:
        d["stop_hook_active"] = active
    if last is not GAP:
        d["last_assistant_message"] = last
    if cwd is not GAP:
        d["cwd"] = cwd
    return json.dumps(d, ensure_ascii=False)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"; h.mkdir()
    return h


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"; p.mkdir()
    return p


def go(tmp_path, home, proj, lines, **kw):
    tx = write_tx(tmp_path / "tx" / "t.jsonl", lines)
    return run(payload(tx, **kw), home, proj)


def speaks(r):
    assert r.returncode == 0 and r.stderr == b""
    assert r.stdout != b""
    return True


def silent(r):
    assert r.returncode == 0 and r.stdout == b""
    return True


def edit_lines(name, **inp):
    return [user_text("해 줘"), assistant_tool(name, **inp)]


@pytest.mark.parametrize("name,path,cwd,loud", [
    ("Write", "/q/a.py", "/p", False),
    ("Write", "/pp/a.py", "/p", False),
    ("Write", "/p/../q/a.py", "/p", False),
    ("Write", "/home/u/.claude/settings.json", "/p", False),
    ("Write", "src/a.py", "/p", True),
    ("Write", "/p/sub/a.py", "/p", True),
    ("Write", "/p/a.py", "/p/", True),
    ("Write", "C:\\p\\a.py", "C:\\p", True),
])
def test_outside_cwd_is_silent(tmp_path, home, proj, name, path, cwd, loud):
    r = go(tmp_path, home, proj, edit_lines(name, file_path=path), cwd=cwd)
    assert (speaks(r) if loud else silent(r))


@pytest.mark.parametrize("cwd", [None, 7, "", GAP], ids=["none", "number", "empty", "missing"])
def test_cwd_not_text_is_silent(tmp_path, home, proj, cwd):
    r = go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py"), cwd=cwd)
    assert r.stdout == b"" and r.returncode == 0


def test_speaks_when_all_three_true(tmp_path, home, proj):
    r = go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py"))
    assert speaks(r)
    lines = r.stdout.decode("ascii").splitlines()
    assert len(lines) == 1
    out = json.loads(lines[0])
    assert set(out) == {"decision", "reason"} and out["decision"] == "block" and out["reason"] == F.REASON


@pytest.mark.parametrize("c1,c2,c3", [(a, b, c) for a in (True, False) for b in (True, False) for c in (True, False)])
def test_three_conditions_matrix(tmp_path, home, proj, c1, c2, c3):
    # 1: 아직 끼어들지 않았다(stop_hook_active가 False) · 2: 고친 도구 쓰임이 있다 · 3: 마지막 말에 점검 줄이 없다
    tool = assistant_tool("Write", file_path="/p/a.py") if c2 else assistant_tool("Read", file_path="/p/a.py")
    last = "끝났다" if c3 else "끝났다\n끝내기 전 점검:\n- 켜 본다: 됨"
    r = go(tmp_path, home, proj, [user_text("해 줘"), tool], active=not c1, last=last)
    assert r.returncode == 0
    if c1 and c2 and c3:
        assert speaks(r)
    else:
        assert r.stdout == b""


@pytest.mark.parametrize("active", [True, "true", 1, "false", None, GAP], ids=["true", "str-true", "one", "str-false", "none", "missing"])
def test_stop_hook_active_not_exact_false_is_silent(tmp_path, home, proj, active):
    r = go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py"), active=active)
    assert r.stdout == b"" and r.returncode == 0


def test_user_line_mixed_blocks_is_user_said(tmp_path, home, proj):
    mixed = user_blocks({"type": "tool_result", "tool_use_id": "t1", "content": "ok"}, {"type": "text", "text": "그리고 이것도"})
    assert F.is_user_said(mixed) is True
    assert F.is_user_said(tool_result()) is False
    lines = edit_lines("Write", file_path="/p/a.py") + [mixed]
    assert silent(go(tmp_path, home, proj, lines))


def test_tool_result_only_line_is_not_user_said(tmp_path, home, proj):
    lines = edit_lines("Write", file_path="/p/a.py") + [tool_result()]
    assert speaks(go(tmp_path, home, proj, lines))


def test_sidechain_and_meta_lines_skipped(tmp_path, home, proj):
    side = dict(assistant_tool("Write", file_path="/p/a.py"), isSidechain=True)
    assert silent(go(tmp_path, home, proj, [user_text("해 줘"), side]))
    meta = [user_text("해 줘"), assistant_tool("Write", file_path="/p/a.py"), user_text("<system>", isMeta=True)]
    assert speaks(go(tmp_path, home, proj, meta))
    # 곁가지(isSidechain) user 줄은 사용자 말로 치지 않는다 — 그 앞의 고침이 살아 말한다
    side_user = [user_text("해 줘"), assistant_tool("Write", file_path="/p/a.py"), user_text("곁가지 말", isSidechain=True)]
    assert F.is_user_said(side_user[2]) is False
    assert speaks(go(tmp_path, home, proj, side_user))
    # isMeta assistant 줄의 고침은 세지 않는다
    meta_edit = [user_text("해 줘"), dict(assistant_tool("Write", file_path="/p/a.py"), isMeta=True)]
    assert F.edited_paths(meta_edit[1]) == []
    assert silent(go(tmp_path, home, proj, meta_edit))


def test_devkit_path_forms(tmp_path, home, proj):
    quiet = [("Write", {"file_path": "/p/.devkit/work/x.md"}, "/p"),
             ("Write", {"file_path": ".devkit/guide.md"}, "/p"),
             ("Write", {"file_path": "C:\\p\\.devkit\\g.md"}, "C:\\p")]
    for name, inp, cwd in quiet:
        assert silent(go(tmp_path, home, proj, edit_lines(name, **inp), cwd=cwd)), inp
    loud = [("Write", {"file_path": "/p/x.devkit/a.py"}),
            ("NotebookEdit", {"notebook_path": "/p/n.ipynb"}),
            ("Edit", {"file_path": "/p/.devkitx/a"})]
    for name, inp in loud:
        assert speaks(go(tmp_path, home, proj, edit_lines(name, **inp))), inp


@pytest.mark.parametrize("path,cwd,loud", [
    ("~/x.py", "/p", False), ("~\\x.py", "/p", False), ("~", "/p", False),
    ("c:\\p\\a.py", "C:\\p", True), ("C:\\p\\a.py", "c:\\p", True), ("C:\\P\\a.py", "C:\\p", False),
    ("/h/.devkit/proj/a.py", "/h/.devkit/proj", True),
    ("/h/.devkit/proj/.devkit/n.md", "/h/.devkit/proj", False),
    ("C:\\h\\.devkit\\proj\\a.py", "C:\\h\\.devkit\\proj", True),
    ("c:\\h\\.devkit\\proj\\.devkit\\n.md", "C:\\h\\.devkit\\proj", False),
    (".devkit/n.md", "/h/.devkit/proj", False), ("src/a.py", "/h/.devkit/proj", True),
])
def test_home_drive_case_and_devkit_cwd(tmp_path, home, proj, path, cwd, loud):
    r = go(tmp_path, home, proj, edit_lines("Write", file_path=path), cwd=cwd)
    assert (speaks(r) if loud else silent(r))


def test_under_cwd_forms():
    assert not F.under_cwd("~/x", "/p") and not F.under_cwd("~\\x", "/p") and not F.under_cwd("~", "/p")
    assert F.under_cwd("c:\\p\\a.py", "C:\\p") and not F.under_cwd("C:\\P\\a.py", "C:\\p")


def test_only_edit_tools_count(tmp_path, home, proj):
    lines = [user_text("해 줘"), assistant_tool("Read", file_path="/p/a.py"),
             assistant_tool("Bash", command="echo hi > /p/a.py"), assistant_tool("Grep", pattern="x", path="/p")]
    assert silent(go(tmp_path, home, proj, lines))


def test_empty_or_non_text_path_not_counted(tmp_path, home, proj):
    for inp in ({"file_path": ""}, {"file_path": 5}, {"file_path": None}, {}):
        assert silent(go(tmp_path, home, proj, edit_lines("Write", **inp))), inp


@pytest.mark.parametrize("last", ["끝났다\n끝내기 전 점검:\n- 켜 본다: 됨", None, 5, GAP], ids=["mark", "none", "number", "missing"])
def test_mark_in_last_message_is_silent(tmp_path, home, proj, last):
    assert silent(go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py"), last=last))


def test_no_user_line_in_window_uses_whole_window(tmp_path, home, proj):
    assert speaks(go(tmp_path, home, proj, [assistant_tool("Write", file_path="/p/a.py")]))


def test_edit_before_last_user_line_not_counted(tmp_path, home, proj):
    lines = edit_lines("Write", file_path="/p/a.py") + [assistant_tool("Read", file_path="/p/a.py"), user_text("고마워")]
    assert silent(go(tmp_path, home, proj, lines))


def big_sample(tmp_path):
    """TAIL보다 큰 기록: 앞에 큰 쓰레기 줄 · 꼬리 범위 머리에 걸리는 줄(끝이 온전한 사전 꼴) · 깨진 UTF-8 줄 · 끝에 사용자 말 → Write.
    (경로, 꼬리 범위의 온전한 첫 줄에 붙은 표시, 꼬리 범위 안 온전한 JSON 줄 수, 끝 두 줄의 바이트 수)"""
    frag = json.dumps({"type": "user", "n": "fragment"}).encode("utf-8")
    cut = b"cut line, not json " + frag                                 # 이 줄은 JSON이 아니지만 끝조각은 사전으로 읽힌다
    first = json.dumps({"type": "system", "mark": "first"}).encode("utf-8")
    last2 = [json.dumps(user_text("해 줘"), ensure_ascii=False).encode("utf-8"),
             json.dumps(assistant_tool("Write", file_path="/p/a.py")).encode("utf-8")]

    def tail_part(pad):
        return b"\n".join([b"\xff\xfe", first, json.dumps({"type": "system", "pad": pad}).encode("utf-8")] + last2) + b"\n"

    fill = F.TAIL - len(frag) - 1 - len(tail_part(""))               # 꼬리 범위가 `frag` 머리에서 시작하게 맞춘다
    part = tail_part("a" * fill)
    assert len(part) + len(frag) + 1 == F.TAIL
    big = b"x" * (F.TAIL + 1024 * 1024) + b"\n" + cut + b"\n" + part
    tx = tmp_path / "tx" / "big.jsonl"; tx.parent.mkdir(); tx.write_bytes(big)
    assert len(big) > F.TAIL
    return tx, 4, sum(len(l) + 1 for l in last2)


def test_tail_window_partial_line_and_bad_utf8(tmp_path, home, proj):
    tx, intact, last2_bytes = big_sample(tmp_path)
    assert speaks(run(payload(tx), home, proj))
    got = F.read_tail(tx)
    assert len(got) == intact                                            # 꼬리 범위 안 온전한 JSON 줄만(앞의 큰 줄들은 읽지 않았다)
    assert got[0].get("mark") == "first" and all(o.get("n") != "fragment" for o in got)
    assert got[-1]["message"]["content"][0]["name"] == "Write"
    small = F.read_tail(tx, last2_bytes + 5)                             # 작은 size를 직접 — 끝 두 줄만
    assert [o["type"] for o in small] == ["user", "assistant"]


def test_tail_small_value_same_result(tmp_path, monkeypatch):
    junk = [{"type": "system", "pad": "z" * 200} for _ in range(20)]
    tx = write_tx(tmp_path / "t.jsonl", [user_text("옛 말"), assistant_tool("Read", file_path="/p/a.py")] + junk
                  + [user_text("해 줘"), assistant_tool("Write", file_path="/p/a.py")])
    data = json.loads(payload(tx))
    monkeypatch.setattr(F, "TAIL", 700)
    assert F.should_speak(data) is True
    got = F.read_tail(tx)
    assert len(got) < 10 and got[-1]["message"]["content"][0]["name"] == "Write"


def test_read_tail_reads_only_tail_and_drops_first_piece(tmp_path):
    rows = [{"type": "user", "n": i} for i in range(6)]
    tx = write_tx(tmp_path / "t.jsonl", rows)
    lens = [len(json.dumps(r)) + 1 for r in rows]
    assert [r["n"] for r in F.read_tail(tx, 10 ** 6)] == [0, 1, 2, 3, 4, 5]
    assert [r["n"] for r in F.read_tail(tx, lens[5] + lens[4] - 3)] == [5]           # 한가운데서 시작 → 첫 조각 버림
    assert [r["n"] for r in F.read_tail(tx, lens[5] + lens[4])] == [5]               # 줄 머리에서 시작해도 첫 줄은 버림
    (tmp_path / "m.jsonl").write_bytes(b'[1]\n"x"\n{"a": 1}\nnot json\n\n\xff\n')
    assert F.read_tail(tmp_path / "m.jsonl") == [{"a": 1}]


def test_helpers():
    assert F.under_devkit("/p/.devkit/a") and F.under_devkit("C:\\p\\.devkit\\a") and not F.under_devkit("/p/x.devkit/a")
    assert F.under_cwd("a.py", "/p") and F.under_cwd("/p/a.py", "/p/") and not F.under_cwd("/pp/a.py", "/p")
    assert not F.under_cwd("../a.py", "/p") and not F.under_cwd("C:\\q\\a.py", "C:\\p")
    assert F.is_user_said(user_text("x")) and not F.is_user_said(tool_result()) and not F.is_user_said({"type": "assistant"})
    assert F.edited_paths(assistant_tool("NotebookEdit", notebook_path="/p/n.ipynb")) == ["/p/n.ipynb"]
    assert F.edited_paths(assistant_tool("Read", file_path="/p/a")) == [] and F.edited_paths(None) == []


@pytest.fixture
def broken_cases(tmp_path):
    tx = write_tx(tmp_path / "tx" / "t.jsonl", edit_lines("Write", file_path="/p/a.py"))
    d = tmp_path / "tx" / "dir"; d.mkdir()
    locked = write_tx(tmp_path / "tx" / "locked.jsonl", edit_lines("Write", file_path="/p/a.py"))
    cases = [("empty", b""), ("bracket", b"["), ("list", b"[]"), ("null", b"null"), ("bad utf8", b"\xff\xfe{\xff"),
             ("number", b"7"),
             ("no path", json.dumps({"stop_hook_active": False, "last_assistant_message": "x", "cwd": "/p"}).encode()),
             ("missing file", payload(tmp_path / "tx" / "nope.jsonl").encode("utf-8")),
             ("folder", payload(d).encode("utf-8")),
             ("path number", json.dumps({"transcript_path": 5, "stop_hook_active": False, "last_assistant_message": "x",
                                         "cwd": "/p"}).encode()),
             ("path empty", json.dumps({"transcript_path": "", "stop_hook_active": False, "last_assistant_message": "x",
                                        "cwd": "/p"}).encode())]
    restore = False
    if os.geteuid() != 0:
        os.chmod(locked, 0)
        restore = True
        cases.append(("unreadable", payload(locked).encode("utf-8")))
    try:
        yield tx, cases
    finally:
        if restore:
            os.chmod(locked, 0o600)


def test_broken_inputs_silent_zero(tmp_path, home, proj, broken_cases):
    _, cases = broken_cases
    for name, raw in cases:
        r = run(raw, home, proj)
        assert r.stdout == b"" and r.returncode == 0, name


def test_unreadable_case_present_unless_root(broken_cases):
    if os.geteuid() == 0:
        pytest.skip("root는 읽기 권한 0 파일도 읽는다")
    assert "unreadable" in [n for n, _ in broken_cases[1]]


def test_never_exit_2(tmp_path, home, proj, broken_cases):
    tx, cases = broken_cases
    raws = [raw for _, raw in cases] + [payload(tx).encode("utf-8"), payload(tx, active=True).encode("utf-8"),
                                        payload(tx, last=None).encode("utf-8")]
    codes = [run(raw, home, proj).returncode for raw in raws]
    assert 2 not in codes and set(codes) == {0}


def test_reason_text():
    lines = F.REASON.splitlines()
    assert 1 <= len(lines) <= 5
    assert lines[0] == "이번에 파일을 고쳤다. 끝 보고를 하기 전에 `devkit:check`를 읽고 그 글대로 아래 걸음을 지난다."
    for need in ("devkit:check", "끝내기 전 점검:", "답을 기다리"):
        assert need in F.REASON, need
    assert any(all(s in line for s in F.STEPS) for line in lines)
    for w in BED_WORDS:
        assert w not in F.REASON, w


def test_steps_match_check_headings():
    text = CHECK.read_text(encoding="utf-8")
    assert list(F.STEPS) == re.findall(r"^## [1-4]\. (.+)$", text, re.M)
    assert F.MARK == "끝내기 전 점검:"


def test_stdout_is_ascii(tmp_path, home, proj):
    r = go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py"))
    assert speaks(r)
    assert all(b < 0x80 for b in r.stdout) and r.stdout.endswith(b"\n") and r.stdout.count(b"\n") == 1


def test_creates_nothing(tmp_path, home, proj):
    tx = write_tx(tmp_path / "tx" / "t.jsonl", edit_lines("Write", file_path="/p/a.py"))
    (home / "h.txt").write_text("h", encoding="utf-8"); (proj / "p.txt").write_text("p", encoding="utf-8")
    dirs = (home, proj, tx.parent)
    before = [snap(d) for d in dirs]
    assert speaks(run(payload(tx), home, proj))
    assert silent(run(b"[", home, proj))
    assert silent(run(payload(tmp_path / "tx" / "nope.jsonl"), home, proj))
    assert [snap(d) for d in dirs] == before


def test_ignores_guard_off_marker(tmp_path, home, proj):
    (home / ".devkit-guard-off").write_text("", encoding="utf-8")
    assert speaks(go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py")))
    assert "guard-off" not in SCRIPT.read_text(encoding="utf-8")


def test_imports_only_stdlib():
    found = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
    assert found <= {"json", "os", "sys", "time", "datetime"}


def test_finish_is_python38():
    src = SCRIPT.read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for pat in PY39:
        assert not re.search(pat, src, re.M), pat


def stop_command():
    return json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"]


def shell(root, stdin, home, cwd):
    return subprocess.run(["sh", "-c", stop_command()], input=stdin.encode("utf-8"), cwd=str(cwd),
                          env={"PATH": os.environ["PATH"], "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(root)},
                          capture_output=True, timeout=30)


def test_hook_command_via_real_shell(tmp_path, home, proj):
    tx = write_tx(tmp_path / "tx" / "t.jsonl", edit_lines("Write", file_path="/p/a.py"))
    r = shell(KIT, payload(tx), home, proj)
    assert r.returncode == 0 and json.loads(r.stdout)["decision"] == "block"
    (tmp_path / "empty").mkdir()
    r = shell(tmp_path / "empty", payload(tx), home, proj)
    assert r.returncode == 1 and r.stdout == b""


def test_project_root(monkeypatch):
    assert F.project_root("/p/sub") == "/p/sub"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/p")
    assert F.project_root("/p/sub") == "/p"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "")
    assert F.project_root("/p/sub") == "/p/sub"


def test_project_dir_env_is_root(tmp_path, home, proj):
    tx = write_tx(tmp_path / "tx" / "t.jsonl", edit_lines("Write", file_path="/p/other/a.py"))
    assert speaks(run(payload(tx, cwd="/p/sub"), home, proj, env={"CLAUDE_PROJECT_DIR": "/p"}))
    assert silent(run(payload(tx, cwd="/p/sub"), home, proj))                       # 환경 변수가 없으면 cwd 기준
    for path in ("/q/a.py", "/p/.devkit/x.md", "/pp/a.py"):
        tx2 = write_tx(tmp_path / "tx" / "u.jsonl", edit_lines("Write", file_path=path))
        assert silent(run(payload(tx2, cwd="/p/sub"), home, proj, env={"CLAUDE_PROJECT_DIR": "/p"})), path


def test_project_dir_empty_falls_back(tmp_path, home, proj):
    tx = write_tx(tmp_path / "tx" / "t.jsonl", edit_lines("Write", file_path="/p/other/a.py"))
    assert silent(run(payload(tx, cwd="/p/sub"), home, proj, env={"CLAUDE_PROJECT_DIR": ""}))
    tx2 = write_tx(tmp_path / "tx" / "u.jsonl", edit_lines("Write", file_path="/p/sub/a.py"))
    assert speaks(run(payload(tx2, cwd="/p/sub"), home, proj, env={"CLAUDE_PROJECT_DIR": ""}))


def test_project_dir_does_not_replace_bad_cwd(tmp_path, home, proj):
    tx = write_tx(tmp_path / "tx" / "t.jsonl", edit_lines("Write", file_path="/p/a.py"))
    for cwd in (None, "", 7, GAP):
        r = run(payload(tx, cwd=cwd), home, proj, env={"CLAUDE_PROJECT_DIR": "/p"})
        assert r.stdout == b"" and r.returncode == 0, cwd


def test_task_notification_not_user_said(tmp_path, home, proj):
    note = user_text("<task-notification>끝남</task-notification>", origin={"kind": "task-notification"})
    assert F.is_user_said(note) is False
    assert speaks(go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py") + [note]))
    blocks = dict(user_blocks({"type": "text", "text": "끝남"}), origin={"kind": "task-notification"})
    assert F.is_user_said(blocks) is False


def test_other_origin_forms_are_user_said(tmp_path, home, proj):
    for o in ("task-notification", ["task-notification"], {"kind": "human"}, {}, {"kind": None}):
        u = user_text("고마워", origin=o)
        assert F.is_user_said(u) is True, o
        assert silent(go(tmp_path, home, proj, edit_lines("Write", file_path="/p/a.py") + [u])), o


def test_cwd_outside_project_dir_still_counts(tmp_path, home, proj):
    env = {"CLAUDE_PROJECT_DIR": "/p"}
    tx = write_tx(tmp_path / "tx" / "t.jsonl", edit_lines("Write", file_path="/q/a.py"))
    assert speaks(run(payload(tx, cwd="/q"), home, proj, env=env))                  # cwd가 뿌리 밖 — 옛 판처럼 cwd 아래 고침을 센다
    tx2 = write_tx(tmp_path / "tx" / "u.jsonl", edit_lines("Write", file_path="/q/.devkit/x.md"))
    assert silent(run(payload(tx2, cwd="/q"), home, proj, env=env))
    tx3 = write_tx(tmp_path / "tx" / "v.jsonl", edit_lines("Write", file_path="/p/.devkit/work/a.md"))
    assert silent(run(payload(tx3, cwd="/p/.devkit/work"), home, proj, env=env))    # 뿌리 아래면 뿌리 뒤쪽 조각으로 본다


def test_project_dir_not_a_dir_is_quiet(tmp_path, home, proj):
    f = tmp_path / "plain.txt"
    f.write_text("x", encoding="utf-8")
    touch(proj / "a.py", T0 + 100)                                      # cwd 쪽으로 물러나 걸으면 여기가 잡힌다
    tx = write_tx(tmp_path / "tx" / "t.jsonl", shell_lines())          # 시각 있는 사용자 말 + 명령 도구 → 걷기가 시도된다
    for bad in (str(tmp_path / "nope"), str(f)):
        r = run(payload(tx, cwd=str(proj)), home, proj, env={"CLAUDE_PROJECT_DIR": bad})
        assert r.stdout == b"" and r.stderr == b"" and r.returncode == 0, bad


def assistant_text(s):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": s}]}}


DONE = "끝내기 전 점검:\n- 켜 본다: 됨"


def note_line(**top):
    return user_text("<task-notification>끝남</task-notification>", origin={"kind": "task-notification"}, **top)


def test_notification_after_check_line_is_base(tmp_path, home, proj):
    edit = edit_lines("Write", file_path="/p/a.py")
    assert F.is_notification(note_line()) is True and F.is_notification(user_text("고마워")) is False
    assert F.says_mark(assistant_text(DONE)) is True and F.says_mark(assistant_text("다 했다")) is False
    assert F.says_mark(assistant_tool("Bash", command=DONE)) is False
    assert silent(go(tmp_path, home, proj, edit + [assistant_text(DONE), note_line(), assistant_text("백그라운드 일 끝")]))
    assert speaks(go(tmp_path, home, proj, edit + [assistant_text("다 했다"), note_line(), assistant_text("끝")]))   # 점검 줄 없이 끝냄
    assert speaks(go(tmp_path, home, proj, edit + [assistant_text(DONE), note_line(),
                                                   assistant_tool("Write", file_path="/p/b.py")]))              # 알림 뒤 새 고침
    assert speaks(go(tmp_path, home, proj, edit + [assistant_text(DONE), assistant_tool("Bash", command="make"),
                                                   note_line()]))                                               # 바로 앞 assistant 줄이 도구 줄
    assert speaks(go(tmp_path, home, proj, [assistant_text(DONE)] + edit + [note_line()]))                      # 점검 줄이 사용자 말보다 앞
    whole = {"type": "assistant", "message": {"role": "assistant", "content": DONE}}
    assert silent(go(tmp_path, home, proj, edit + [whole, note_line()]))
    side = dict(assistant_text(DONE), isSidechain=True)
    assert speaks(go(tmp_path, home, proj, edit + [side, note_line()]))                                         # 곁가지 줄은 보지 않는다
    assert silent(go(tmp_path, home, proj, edit + [assistant_text(DONE), note_line(), assistant_text("끝"), note_line()]))  # 마지막 닫힌 알림 줄
    assert F.base_index([]) is None and F.base_index([note_line()]) is None
    assert F.base_index(edit + [assistant_text(DONE), note_line()]) == 3 and F.base_index(edit + [note_line()]) == 0


TS = "2026-01-01T00:00:00.000Z"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


def touch(path, t):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (t, t))
    return path


def shell_lines(tool="Bash", ts=TS):
    return [user_text("해 줘", timestamp=ts), assistant_tool(tool, command="make")]


def walk_go(tmp_path, home, proj, lines, **kw):
    return go(tmp_path, home, proj, lines, cwd=str(proj), **kw)          # 살핌은 늘 tmp_path 아래만 걷는다


def test_walk_constants():
    assert F.WALK_MAX == 30000 and F.WALK_SECS == 1.5
    assert F.FUTURE_SLACK == 2.0
    assert F.SKIP_DIRS == ("node_modules", "__pycache__", "venv", "env", "dist", "build", "target", "out", "coverage", "htmlcov",
                           "vendor", "_build", "test-results", "playwright-report")
    assert F.SKIP_ENDS == (".pyc", ".pyo", ".log", ".tmp", ".swp", ".db", ".sqlite", ".sqlite3", "-wal", "-shm", "-journal",
                           ".tsbuildinfo")


def test_shell_change_newer_speaks_older_silent(tmp_path, home, proj):
    touch(proj / "src" / "a.py", T0 - 100)
    assert silent(walk_go(tmp_path, home, proj, shell_lines()))
    touch(proj / "src" / "b.py", T0 + 100)
    r = walk_go(tmp_path, home, proj, shell_lines())
    assert speaks(r) and json.loads(r.stdout)["reason"] == F.REASON


@pytest.mark.parametrize("name,loud", [
    ("Bash", True), ("bash", True), ("BASH", True), ("PowerShell", True), ("powershell", True), ("REPL", True), ("repl", True),
    ("Agent", True), ("Task", True), ("mcp__zz__write", True),
    ("agent", False), ("task", False), ("mcp_zz", False), ("Read", False), ("Grep", False), ("Glob", False),
    ("WebFetch", False), ("Skill", False), ("", False), (None, False), (5, False),
])
def test_changing_tool_names(name, loud):
    assert F.changing_tool(name) is loud


def test_read_only_turn_not_checked(tmp_path, home, proj):
    touch(proj / "a.py", T0 + 100)
    for tool in ("Read", "Grep", "Glob", "WebFetch", "Skill"):
        assert silent(walk_go(tmp_path, home, proj, shell_lines(tool))), tool
    assert speaks(walk_go(tmp_path, home, proj, shell_lines("PowerShell")))
    assert speaks(walk_go(tmp_path, home, proj, shell_lines("mcp__zz__write")))
    assert speaks(walk_go(tmp_path, home, proj, shell_lines("REPL")))


def test_changing_tool_before_last_user_line_not_counted(tmp_path, home, proj):
    touch(proj / "a.py", T0 + 100)
    lines = shell_lines(ts="2025-01-01T00:00:00.000Z") + [user_text("고마워", timestamp=TS),
                                                          assistant_tool("Read", file_path=str(proj / "a.py"))]
    assert silent(walk_go(tmp_path, home, proj, lines))


@pytest.mark.parametrize("ts", [GAP, None, 5, "", "어제", "2026-01-01T00:00:00", "2026-13-01T00:00:00Z"],
                         ids=["missing", "none", "number", "empty", "word", "no-zone", "bad-month"])
def test_unreadable_time_not_checked(tmp_path, home, proj, ts):
    touch(proj / "a.py", T0 + 100)
    u = user_text("해 줘") if ts is GAP else user_text("해 줘", timestamp=ts)
    assert silent(walk_go(tmp_path, home, proj, [u, assistant_tool("Bash", command="make")]))


def test_no_user_line_in_window_not_checked(tmp_path, home, proj):
    touch(proj / "a.py", T0 + 100)
    assert silent(walk_go(tmp_path, home, proj, [assistant_tool("Bash", command="make")]))


def test_parse_time_forms():
    assert F.parse_time("2026-01-01T00:00:00Z") == T0
    assert F.parse_time("2026-01-01T00:00:00.000Z") == T0
    assert abs(F.parse_time("2026-01-01T00:00:00.1Z") - (T0 + 0.1)) < 1e-6
    assert abs(F.parse_time("2026-01-01T00:00:00.123456789Z") - (T0 + 0.123456)) < 1e-5
    assert F.parse_time("2026-01-01T09:00:00+09:00") == T0
    assert F.parse_time("2026-01-01T00:00:00.000z") == T0
    for bad in ("2026-01-01T00:00:00", "", "어제", "2026-13-01T00:00:00Z", None, 5, ["x"]):
        assert F.parse_time(bad) is None, bad


@pytest.mark.parametrize("rel", [
    ".git/x", ".devkit/work/x.md", ".venv/lib/x.py", ".cache/x", "node_modules/a/x.js", "__pycache__/x.py",
    "venv/x.py", "env/x.py", "dist/x.js", "build/x.o", "target/x", "out/x", "coverage/x", "htmlcov/x.html",
    "vendor/x.go", "_build/x.html", "test-results/x.xml", "playwright-report/index.html",
    "src/build/x.py", "src/node_modules/x.js", "src/.hidden/x.py",
    "a.pyc", "a.pyo", "src/run.log", "a.tmp", "src/.a.py.swp", "src/a.py.swp",
    "dev.db", "data/app.sqlite", "app.sqlite3", "app.sqlite3-wal", "app.db-shm", "app.db-journal", "tsconfig.tsbuildinfo",
    ".editorconfig", ".coverage", ".eslintcache", "src/.DS_Store", ".env",
])
def test_skip_dirs_and_ends_silent(tmp_path, home, proj, rel):
    touch(proj / "src" / "old.py", T0 - 100)
    touch(proj / rel, T0 + 100)
    assert silent(walk_go(tmp_path, home, proj, shell_lines())), rel
    touch(proj / "src" / "new.py", T0 + 100)
    assert speaks(walk_go(tmp_path, home, proj, shell_lines())), rel


def test_dot_file_not_counted(tmp_path, home, proj):
    touch(proj / ".editorconfig", T0 + 100)
    assert silent(walk_go(tmp_path, home, proj, shell_lines()))        # 점으로 시작하는 파일은 세지 않는다
    touch(proj / "Build" / "x.py", T0 + 100)                           # 걸러 낼 이름은 대소문자 그대로 견준다
    assert speaks(walk_go(tmp_path, home, proj, shell_lines()))


def test_symlinks_not_followed(tmp_path, home, proj):
    outside = tmp_path / "outside"
    touch(outside / "new.py", T0 + 100)
    os.symlink(str(outside), str(proj / "linkdir"))
    os.symlink(str(outside / "new.py"), str(proj / "linkfile.py"))   # 바로가기 자신의 시각도 새롭다 — 그래도 세지 않는다
    assert silent(walk_go(tmp_path, home, proj, shell_lines()))


def test_unreadable_dir_skipped(tmp_path, home, proj):
    if os.geteuid() == 0:
        pytest.skip("root는 권한 0 폴더도 연다")
    lock = proj / "locked"
    touch(lock / "new.py", T0 + 100)
    os.chmod(lock, 0)
    try:
        r = walk_go(tmp_path, home, proj, shell_lines())
        assert silent(r) and r.stderr == b""
        touch(proj / "ok.py", T0 + 100)
        assert speaks(walk_go(tmp_path, home, proj, shell_lines()))
    finally:
        os.chmod(lock, 0o700)


def test_walk_limits(tmp_path):
    root = tmp_path / "r"
    touch(root / "a.py", T0 + 100)
    assert F.changed_since(str(root), T0) is True
    assert F.changed_since(str(root), T0 + 200) is False
    assert F.changed_since(str(root), T0, limit=0) is False
    assert F.changed_since(str(root), T0, limit=1) is True
    slow = itertools.chain([0.0], itertools.repeat(10.0))
    assert F.changed_since(str(root), T0, clock=lambda: next(slow)) is False
    fast = itertools.chain([0.0], itertools.repeat(1.0))
    assert F.changed_since(str(root), T0, clock=lambda: next(fast)) is True
    late = itertools.chain([0.0], itertools.repeat(10.0))
    assert F.changed_since(str(root), T0, secs=20.0, clock=lambda: next(late)) is True
    assert F.changed_since(str(tmp_path / "nope"), T0) is False
    assert F.changed_since(str(root), T0 + 100) is False               # 같은 시각은 「더 새로움」이 아니다
    assert F.changed_since(str(root), T0, now=T0 + 50) is False        # 지금 + 2초보다 늦은 시각은 세지 않는다
    assert F.changed_since(str(root), T0, now=T0 + 97) is False
    assert F.changed_since(str(root), T0, now=T0 + 98) is True


def test_limit_counts_skipped_entries_first(tmp_path):
    root = tmp_path / "r"
    for i in range(5):
        touch(root / ("z%d.log" % i), T0 - 100)                        # 걸러 내는 항목도 센다
    touch(root / "a.py", T0 + 100)
    assert F.changed_since(str(root), T0) is True
    assert F.changed_since(str(root), T0, limit=6) is True
    seen = [F.changed_since(str(root), T0, limit=n) for n in range(6)]
    assert seen[0] is False and seen == sorted(seen)                   # 상한이 커질수록 False → True (한 번만 바뀐다)


def test_limit_counts_skipped_entries_before_descending(tmp_path):
    root = tmp_path / "r"
    for i in range(6):
        touch(root / ("z%d.log" % i), T0 - 100)                        # 걸러 내는 항목 여섯 + 폴더 하나 = 뿌리에서 일곱
    touch(root / "sub" / "a.py", T0 + 100)                             # 여덟째 항목 (뿌리를 다 본 뒤에야 닿는다)
    assert F.changed_since(str(root), T0, limit=7) is False
    assert F.changed_since(str(root), T0, limit=8) is True


def test_future_mtime_not_counted(tmp_path, home, proj):
    touch(proj / "a.py", time.time() + 3600)
    assert silent(walk_go(tmp_path, home, proj, shell_lines()))
    touch(proj / "b.py", T0 + 100)
    assert speaks(walk_go(tmp_path, home, proj, shell_lines()))


def test_root_or_home_not_walked(tmp_path, home, proj, monkeypatch):
    touch(home / "a.py", T0 + 100)
    assert silent(walk_go(tmp_path, home, home, shell_lines()))        # 프로젝트 뿌리 = 홈 폴더
    monkeypatch.setenv("HOME", str(home))
    assert F.skip_root("/") is True and F.skip_root(str(home)) is True and F.skip_root(str(home) + "/") is True
    assert F.skip_root(str(home / "proj")) is False and F.skip_root(str(proj)) is False


def test_scandir_error_mid_iteration_skips_only_that_dir(tmp_path, monkeypatch):
    root = tmp_path / "r"
    touch(root / "bad" / "x.py", T0 + 100)
    touch(root / "ok" / "y.py", T0 - 100)
    real = os.scandir

    class Broken:
        def __init__(self, it):
            self.it = it

        def __iter__(self):
            return self

        def __next__(self):
            raise OSError("zz")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.it.close()

        def close(self):
            self.it.close()

    monkeypatch.setattr(F.os, "scandir", lambda d: Broken(real(d)) if os.path.basename(str(d)) == "bad" else real(d))
    assert F.changed_since(str(root), T0) is False
    touch(root / "ok" / "z.py", T0 + 100)
    assert F.changed_since(str(root), T0) is True


def test_walk_limit_constants_used_at_call_time(tmp_path, proj, monkeypatch):
    touch(proj / "a.py", T0 + 100)
    data = json.loads(payload(write_tx(tmp_path / "tx" / "t.jsonl", shell_lines()), cwd=str(proj)))
    assert F.should_speak(data) is True
    monkeypatch.setattr(F, "WALK_MAX", 0)
    assert F.should_speak(data) is False
    monkeypatch.setattr(F, "WALK_MAX", 30000)
    monkeypatch.setattr(F, "WALK_SECS", -1.0)
    assert F.should_speak(data) is False


def test_edit_hit_never_walks(tmp_path, proj, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("걸었다")
    monkeypatch.setattr(F, "changed_since", boom)
    tx = write_tx(tmp_path / "tx" / "t.jsonl", shell_lines() + [assistant_tool("Write", file_path=str(proj / "a.py"))])
    assert F.should_speak(json.loads(payload(tx, cwd=str(proj)))) is True
    assert F.should_speak(json.loads(payload(tx, cwd=str(proj), active=True))) is False
    assert F.should_speak(json.loads(payload(tx, cwd=str(proj), last="끝내기 전 점검:\n- 켜 본다: 됨"))) is False


def test_since_is_real_user_line_not_notification(tmp_path, home, proj):
    touch(proj / "a.py", T0 + 100)
    note = user_text("끝남", origin={"kind": "task-notification"}, timestamp="2026-06-01T00:00:00.000Z")
    assert speaks(walk_go(tmp_path, home, proj, shell_lines() + [note]))      # 점검 줄로 닫히지 않은 알림 줄은 기준 줄이 아니다


def test_notification_base_time(tmp_path, home, proj):
    touch(proj / "a.py", T0 + 100)
    closed = shell_lines() + [assistant_text(DONE), note_line(timestamp="2026-01-01T00:03:20.000Z")]      # 기준 시각 = T0 + 200
    assert silent(walk_go(tmp_path, home, proj, closed + [assistant_text("끝")]))                         # 기준 줄 뒤에 바꿀 수 있는 도구 없음
    assert silent(walk_go(tmp_path, home, proj, closed + [assistant_tool("Bash", command="ls")]))         # 도구는 있으나 새 파일 없음
    touch(proj / "b.py", T0 + 300)
    assert speaks(walk_go(tmp_path, home, proj, closed + [assistant_tool("Bash", command="make")]))
    assert silent(walk_go(tmp_path, home, proj, closed + [assistant_text("끝")]))
    notime = shell_lines() + [assistant_text(DONE), note_line(), assistant_tool("Bash", command="make")]
    assert silent(walk_go(tmp_path, home, proj, notime))                                                  # 기준 줄의 시각을 못 읽음


def test_walk_uses_project_dir(tmp_path, home, proj):
    (proj / "sub").mkdir()
    touch(proj / "other" / "a.py", T0 + 100)
    tx = write_tx(tmp_path / "tx" / "t.jsonl", shell_lines())
    assert silent(run(payload(tx, cwd=str(proj / "sub")), home, proj))
    assert speaks(run(payload(tx, cwd=str(proj / "sub")), home, proj, env={"CLAUDE_PROJECT_DIR": str(proj)}))
    touch(proj / "sub" / "b.py", T0 + 100)
    for bad in (str(tmp_path / "nope"), str(tx)):                       # 뿌리가 없는 길·파일 — 걷지 못하면 조용히 0
        r = run(payload(tx, cwd=str(proj / "sub")), home, proj, env={"CLAUDE_PROJECT_DIR": bad})
        assert r.stdout == b"" and r.stderr == b"" and r.returncode == 0, bad


def test_walk_creates_nothing(tmp_path, home, proj):
    touch(proj / "src" / "a.py", T0 + 100)
    touch(proj / ".devkit" / "g.md", T0 + 100)
    dirs = (home, proj)
    before = [snap(d) for d in dirs]
    assert speaks(walk_go(tmp_path, home, proj, shell_lines()))
    assert silent(walk_go(tmp_path, home, proj, shell_lines(), active=True))
    assert [snap(d) for d in dirs] == before


def test_docstring_keeps_promises():
    doc = ast.get_docstring(ast.parse(SCRIPT.read_text(encoding="utf-8")))
    for s in ("하위 프로세스를 부르지 않는다", "파일을 만들지 않는다", "CLAUDE_PROJECT_DIR", "고친 시각"):
        assert s in doc, s
