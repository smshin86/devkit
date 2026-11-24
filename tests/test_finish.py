import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
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


def run(raw, home, cwd):
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    return subprocess.run([sys.executable, "-I", "-S", str(SCRIPT)], input=data, cwd=str(cwd),
                          env={"PATH": os.environ["PATH"], "HOME": str(home)}, capture_output=True, timeout=30)


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
    assert found <= {"json", "os", "sys"}


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
