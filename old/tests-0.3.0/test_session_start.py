import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "kit"
SCRIPT = KIT / "scripts" / "session_start.py"
RULES = KIT / "rules.md"

PY39 = [r"\b(list|dict|tuple|set)\[", r"functools import cache\b", r"\w\s*\|\s*None", r"\.removeprefix\(", r"\.removesuffix\(",
        r"is_relative_to\(", r"^\s*match\s.+:\s*$"]

HOOK = {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_start.py"',
        "commandWindows": 'python "${CLAUDE_PLUGIN_ROOT}/scripts/session_start.py"'}


def run(stdin, cwd=None, env=None, script=SCRIPT):
    data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    return subprocess.run([sys.executable, str(script)], input=data, cwd=None if cwd is None else str(cwd), env=env,
                          capture_output=True, timeout=30)


def snap(d):
    d = Path(d)
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts}


def test_prints_rules_bytes():
    r = run("{}")
    assert (r.returncode, r.stdout, r.stderr) == (0, RULES.read_bytes(), b"")


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"cwd": 5}', b"\x00\xff", "x" * 100000])
def test_odd_stdin_same(stdin):
    r = run(stdin)
    assert (r.returncode, r.stdout, r.stderr) == (0, RULES.read_bytes(), b"")


def test_no_rules_quiet(tmp_path):
    (tmp_path / "alone" / "scripts").mkdir(parents=True)
    alone = tmp_path / "alone" / "scripts" / "session_start.py"
    shutil.copy(str(SCRIPT), str(alone))
    r = run("{}", script=alone)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_prints_the_file_beside_it(tmp_path):
    k = tmp_path / "k"
    shutil.copytree(str(KIT), str(k), ignore=shutil.ignore_patterns("__pycache__"))
    (k / "rules.md").write_bytes("# other\n- 하나\n".encode("utf-8"))
    r = run("{}", script=k / "scripts" / "session_start.py")
    assert (r.returncode, r.stdout, r.stderr) == (0, "# other\n- 하나\n".encode("utf-8"), b"")


def test_closed_stdout_quiet():
    r = subprocess.run(["sh", "-c", 'exec "$0" "$1" >&-', sys.executable, str(SCRIPT)],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    assert r.returncode == 0 and r.stderr == b""


def test_cp949_console():
    r = run("{}", env=dict(os.environ, PYTHONIOENCODING="cp949"))
    assert r.returncode == 0 and r.stdout == RULES.read_bytes()


def test_creates_nothing(tmp_path):
    p = tmp_path / "p"; p.mkdir()
    before = snap(KIT)
    r = run("{}", cwd=p)
    assert r.returncode == 0
    assert list(p.iterdir()) == []
    assert snap(KIT) == before


def test_imports_only_stdlib():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= {"os", "sys", "pathlib"}


def test_session_start_is_python38():
    src = SCRIPT.read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for pat in PY39:
        assert not re.search(pat, src, re.M), pat


def test_hooks_json():
    raw = (KIT / "hooks/hooks.json").read_text(encoding="utf-8"); data = json.loads(raw)
    assert list(data) == ["hooks"] and list(data["hooks"]) == ["SessionStart"]
    (group,) = data["hooks"]["SessionStart"]; assert "matcher" not in group
    (hook,) = group["hooks"]
    assert hook == HOOK
    for bad in ("||", "&&", ";", "`", "$("): assert bad not in raw


def test_rules_headings():
    heads = [x for x in RULES.read_text(encoding="utf-8").splitlines() if x.startswith("## ")]
    assert len(heads) == 3
    for n, head in zip("123", heads):
        assert head.startswith("## " + n + ".")


def test_rules_short():
    # 한 장이 다시 불어나는 것을 막는 장치 — 상한을 올리려면 사용자 승인
    assert len(RULES.read_text(encoding="utf-8").splitlines()) <= 40


def test_rules_bytes_clean():
    raw = RULES.read_bytes()
    text = raw.decode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert not any(x.startswith("<!-- devkit:") for x in text.splitlines())
