import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "kit"
OLD = KIT.parent / "old" / "kit-0.1.0"
SCRIPT = KIT / "install.py"
spec = importlib.util.spec_from_file_location("install", SCRIPT); install = importlib.util.module_from_spec(spec); spec.loader.exec_module(install)

PY39 = [r"\b(list|dict|tuple|set)\[", r"functools import cache\b", r"\w\s*\|\s*None", r"\.removeprefix\(", r"\.removesuffix\(",
        r"is_relative_to\(", r"^\s*match\s.+:\s*$"]
LINE1 = ("devkit: when asked to build, change or fix something in a project, or to analyze how a project is built, "
         "read the devkit:start skill first, before reading or editing code. When continuing earlier work, read devkit:start first too.")
NOTE = install.NOTE_BEGIN + "\n" + LINE1 + "\n" + install.NOTE_END + "\n"
DESC = ("요청한 것만, 프로젝트의 방식대로 만들고 실제로 써 보며 확인하게 돕는 스킬 묶음: "
        "문(start)과 여섯 단계(받기·찾기·만들기·확인·검토·마무리)")


def make_env(tmp_path, tools=("claude", "codex"), rc=0):
    """가짜 HOME·CODEX_HOME과 가짜 claude·codex(/bin/sh 스크립트). 진짜 홈에는 닿지 않는다."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in tools:
        exe = bin_dir / tool
        exe.write_text('#!/bin/sh\nprintf \'%s %s\\n\' "$(basename "$0")" "$*" >> "$FAKE_LOG"\nexit $FAKE_RC\n', encoding="utf-8")
        exe.chmod(0o755)
    e = {"HOME": str(tmp_path / "home"), "CODEX_HOME": str(tmp_path / "codex"),
         "PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_LOG": str(tmp_path / "log"), "FAKE_RC": str(rc)}
    assert Path(e["HOME"]) != Path.home() and Path(e["CODEX_HOME"]) != Path.home() / ".codex"
    return e


def inst(*args, env):
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def log_lines(tmp_path):
    return (tmp_path / "log").read_text(encoding="utf-8").splitlines()


def agents_path(tmp_path):
    return tmp_path / "codex" / "AGENTS.md"


def test_install_runs_both_in_order(tmp_path):
    r = inst(env=make_env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert log_lines(tmp_path) == [
        "claude plugin uninstall devkit@devkit", "claude plugin marketplace remove devkit",
        f"claude plugin marketplace add {KIT}", "claude plugin install devkit@devkit",
        "codex plugin remove devkit@devkit", "codex plugin marketplace remove devkit",
        f"codex plugin marketplace add {KIT}", "codex plugin add devkit@devkit"]
    assert "Claude Code: 깔았습니다." in r.stdout and "Codex: 깔았습니다." in r.stdout and "--codex-note" in r.stdout
    assert not agents_path(tmp_path).exists()


def test_codex_note_adds_three_lines_once(tmp_path):
    e = make_env(tmp_path)
    assert inst("--codex-note", env=e).returncode == 0
    assert inst("--codex-note", env=e).returncode == 0
    assert agents_path(tmp_path).read_text(encoding="utf-8") == NOTE


def test_codex_note_keeps_crlf_korean(tmp_path):
    e = make_env(tmp_path)
    orig = "# 내 규칙\r\n- one\r\n".encode("utf-8")
    agents_path(tmp_path).parent.mkdir()
    agents_path(tmp_path).write_bytes(orig)
    assert inst("--codex-note", env=e).returncode == 0
    assert agents_path(tmp_path).read_bytes() == orig + NOTE.replace("\n", "\r\n").encode()
    assert inst("--remove", env=e).returncode == 0
    assert agents_path(tmp_path).read_bytes() == orig


def test_codex_note_appends_newline(tmp_path):
    e = make_env(tmp_path)
    agents_path(tmp_path).parent.mkdir()
    agents_path(tmp_path).write_bytes(b"x")
    assert inst("--codex-note", env=e).returncode == 0
    assert agents_path(tmp_path).read_bytes() == b"x\n" + NOTE.encode()
    assert inst("--remove", env=e).returncode == 0
    assert agents_path(tmp_path).read_bytes() == b"x\n"


def test_remove_only_marked_lines(tmp_path):
    e = make_env(tmp_path)
    agents_path(tmp_path).parent.mkdir()
    agents_path(tmp_path).write_bytes(("a\n- devkit is great\n" + NOTE + "b\n").encode("utf-8"))
    assert inst("--remove", env=e).returncode == 0
    assert agents_path(tmp_path).read_text(encoding="utf-8") == "a\n- devkit is great\nb\n"


@pytest.mark.parametrize("flag", ["--remove", "--codex-note"])
def test_broken_marker_untouched(tmp_path, flag):
    e = make_env(tmp_path)
    agents_path(tmp_path).parent.mkdir()
    raw = (install.NOTE_BEGIN + "\n").encode("utf-8")
    agents_path(tmp_path).write_bytes(raw)
    r = inst(flag, env=e)
    assert agents_path(tmp_path).read_bytes() == raw
    assert r.returncode == 1 and "AGENTS.md" in r.stdout


@pytest.mark.parametrize("flag", ["--remove", "--codex-note"])
def test_edited_block_untouched(tmp_path, flag):
    e = make_env(tmp_path)
    agents_path(tmp_path).parent.mkdir()
    raw = (install.NOTE_BEGIN + "\n" + LINE1 + "\n- my own line\n" + install.NOTE_END + "\n").encode("utf-8")
    agents_path(tmp_path).write_bytes(raw)
    r = inst(flag, env=e)
    assert agents_path(tmp_path).read_bytes() == raw
    assert r.returncode == 1 and "AGENTS.md" in r.stdout


@pytest.mark.parametrize("codex_home_value", [None, ""])
def test_codex_home_default(tmp_path, codex_home_value):
    e = make_env(tmp_path)
    if codex_home_value is None:
        del e["CODEX_HOME"]
    else:
        e["CODEX_HOME"] = codex_home_value
    assert inst("--codex-note", env=e).returncode == 0
    assert (tmp_path / "home" / ".codex" / "AGENTS.md").read_text(encoding="utf-8") == NOTE


def test_codex_note_without_codex(tmp_path):
    r = inst("--codex-note", env=make_env(tmp_path, tools=("claude",)))
    assert r.returncode == 0 and "Codex" in r.stdout
    assert not (tmp_path / "codex").exists()


def test_note_skipped_when_codex_install_fails(tmp_path):
    r = inst("--codex-note", env=make_env(tmp_path, rc=1))
    assert r.returncode == 1
    assert not agents_path(tmp_path).exists()


@pytest.mark.parametrize("args", [["--codex-note", "--remove"], ["-x"], ["--remove", "--remove"]])
def test_bad_args(tmp_path, args):
    r = inst(*args, env=make_env(tmp_path))
    assert r.returncode == 1 and "--codex-note" in r.stdout
    assert not (tmp_path / "log").exists()


def test_install_failure_reported(tmp_path):
    r = inst(env=make_env(tmp_path, rc=1))
    assert r.returncode == 1 and "깔지 못했습니다" in r.stdout


def test_remove_runs_remove_commands_only(tmp_path):
    r = inst("--remove", env=make_env(tmp_path))
    assert r.returncode == 0
    assert log_lines(tmp_path) == [
        "claude plugin uninstall devkit@devkit", "claude plugin marketplace remove devkit",
        "codex plugin remove devkit@devkit", "codex plugin marketplace remove devkit"]
    assert not (tmp_path / "codex").exists()


def test_never_asks():
    assert "input(" not in SCRIPT.read_text(encoding="utf-8")


def test_note_matches_hook_line():
    assert install.NOTE_TEXT == LINE1
    hooks = json.loads((KIT / "hooks/hooks.json").read_text(encoding="utf-8"))
    assert LINE1 in hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_install_is_python38():
    src = SCRIPT.read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for pat in PY39:
        assert not re.search(pat, src, re.M), pat


def test_manifests():
    def m(base, p):
        return json.loads((base / p).read_text(encoding="utf-8"))
    mk, cp, xp = m(KIT, ".claude-plugin/marketplace.json"), m(KIT, ".claude-plugin/plugin.json"), m(KIT, ".codex-plugin/plugin.json")
    assert mk["plugins"][0]["version"] == cp["version"] == xp["version"] == "0.2.0"
    assert mk["plugins"][0]["description"] == cp["description"] == xp["description"] == DESC
    assert xp["interface"]["shortDescription"] == "요청대로, 프로젝트 방식대로 만들고 확인하기" and "hooks" not in xp
    assert mk["owner"] == {"name": "devkit"}
    assert m(KIT, ".agents/plugins/marketplace.json") == m(OLD, ".agents/plugins/marketplace.json")
