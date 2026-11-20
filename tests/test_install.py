import ast
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "kit"
SCRIPT = KIT / "install.py"
spec = importlib.util.spec_from_file_location("install", SCRIPT); install = importlib.util.module_from_spec(spec); spec.loader.exec_module(install)

PY39 = [r"\b(list|dict|tuple|set)\[", r"functools import cache\b", r"\w\s*\|\s*None", r"\.removeprefix\(", r"\.removesuffix\(",
        r"is_relative_to\(", r"^\s*match\s.+:\s*$"]
# 0.2.0의 Codex 안내 세 줄 가운데 가운데 줄. 지금 규칙 한 장과 달라 손대지 않아야 한다.
LINE1 = ("devkit: when asked to build, change or fix something in a project, or to analyze how a project is built, "
         "read the devkit:start skill first, before reading or editing code. When continuing earlier work, read devkit:start first too.")
RULES_TEXT = (KIT / "rules.md").read_text(encoding="utf-8")
NOTE = install.NOTE_BEGIN + "\n" + RULES_TEXT + install.NOTE_END + "\n"
OLD_NOTE = install.NOTE_BEGIN + "\n" + LINE1 + "\n" + install.NOTE_END + "\n"
DESC = "일할 때 지키는 한 장(닮은 것이 하던 대로, 부탁한 것만, 끝에 사실대로)과, 큰 일일 때만 읽는 시작 안내·살펴보기(길 안내 한 장)"
KIT_FILES = {".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "hooks/hooks.json",
             "scripts/session_start.py", "scripts/work.py", "scripts/guard.py", "skills/start/SKILL.md", "skills/find/SKILL.md", "skills/find/first-guide.md", "skills/find/screen-table.md", "rules.md", "install.py", "README.md", "CREDITS.md"}


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


def inst(*args, env, script=SCRIPT):
    return subprocess.run([sys.executable, str(script), *args], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def log_lines(tmp_path):
    return (tmp_path / "log").read_text(encoding="utf-8").splitlines()


def agents_path(tmp_path):
    return tmp_path / "codex" / "AGENTS.md"


def test_install_runs_claude_only(tmp_path):
    r = inst(env=make_env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert log_lines(tmp_path) == [
        "claude plugin uninstall devkit@devkit", "claude plugin marketplace remove devkit",
        f"claude plugin marketplace add {KIT}", "claude plugin install devkit@devkit"]
    assert "Claude Code: 깔았습니다." in r.stdout and "--codex-note" in r.stdout
    assert not agents_path(tmp_path).exists()


@pytest.mark.parametrize("args", [[], ["--codex-note"], ["--remove"]])
def test_codex_never_called(tmp_path, args):
    inst(*args, env=make_env(tmp_path))
    assert not [x for x in log_lines(tmp_path) if x.startswith("codex ")]


def test_codex_note_only_codex(tmp_path):
    r = inst("--codex-note", env=make_env(tmp_path, tools=("codex",)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert agents_path(tmp_path).read_text(encoding="utf-8") == NOTE
    assert not (tmp_path / "log").exists()


def test_codex_note_adds_block_once(tmp_path):
    e = make_env(tmp_path, tools=("codex",))           # claude 없이 — "새 대화" 줄이 블록 덕에만 나오게
    assert inst("--codex-note", env=e).returncode == 0
    r = inst("--codex-note", env=e)
    assert r.returncode == 0 and "이미 있습니다" in r.stdout and "새 대화" in r.stdout
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


def test_remove_only_our_block(tmp_path):
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
    raw = (install.NOTE_BEGIN + "\n" + RULES_TEXT + "- my own line\n" + install.NOTE_END + "\n").encode("utf-8")
    agents_path(tmp_path).write_bytes(raw)
    r = inst(flag, env=e)
    assert agents_path(tmp_path).read_bytes() == raw
    assert r.returncode == 1 and "AGENTS.md" in r.stdout


@pytest.mark.parametrize("flag", ["--remove", "--codex-note"])
def test_old_note_untouched(tmp_path, flag):
    e = make_env(tmp_path)
    agents_path(tmp_path).parent.mkdir()
    raw = OLD_NOTE.encode("utf-8")
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
    assert not (tmp_path / "codex").exists() and not (tmp_path / "home" / ".codex").exists()


@pytest.mark.parametrize("args", [["--codex-note", "--remove"], ["-x"], ["--remove", "--remove"]])
def test_bad_args(tmp_path, args):
    r = inst(*args, env=make_env(tmp_path))
    assert r.returncode == 1 and "--codex-note" in r.stdout
    assert not (tmp_path / "log").exists()


def test_install_failure_reported(tmp_path):
    r = inst(env=make_env(tmp_path, rc=1))
    assert r.returncode == 1 and "깔지 못했습니다" in r.stdout
    assert "새 대화" not in r.stdout and "--codex-note" not in r.stdout


def test_install_without_rules_refused(tmp_path):
    k = tmp_path / "k"
    shutil.copytree(str(KIT), str(k), ignore=shutil.ignore_patterns("__pycache__"))
    (k / "rules.md").unlink()
    r = inst(env=make_env(tmp_path), script=k / "install.py")
    assert r.returncode == 1 and "rules.md" in r.stdout and "깔았습니다" not in r.stdout
    assert not (tmp_path / "log").exists()


def test_no_tools(tmp_path):
    e = make_env(tmp_path, tools=())
    r = inst(env=e)
    assert r.returncode == 1 and "찾지 못했습니다" in r.stdout
    agents_path(tmp_path).parent.mkdir()
    agents_path(tmp_path).write_bytes(("mine\n" + NOTE).encode("utf-8"))
    r = inst("--remove", env=e)
    assert r.returncode == 0 and "설치해 주세요" not in r.stdout
    assert agents_path(tmp_path).read_bytes() == b"mine\n"


def test_crlf_no_final_newline(tmp_path):
    e = make_env(tmp_path)
    agents_path(tmp_path).parent.mkdir()
    agents_path(tmp_path).write_bytes(b"a\r\nb")
    assert inst("--codex-note", env=e).returncode == 0
    assert agents_path(tmp_path).read_bytes() == b"a\r\nb\r\n" + NOTE.replace("\n", "\r\n").encode()


@pytest.mark.parametrize("flag", ["--codex-note", "--remove"])
def test_unwritable_agents_reported(tmp_path, flag):
    e = make_env(tmp_path)
    agents_path(tmp_path).mkdir(parents=True)          # AGENTS.md 자리에 폴더 — 읽기·쓰기가 실패한다
    r = inst(flag, env=e)
    assert "Traceback" not in r.stderr
    if flag == "--codex-note":
        assert r.returncode == 1 and "AGENTS.md" in r.stdout and "새 대화" not in r.stdout
    assert agents_path(tmp_path).is_dir()


def test_remove_runs_claude_remove_only(tmp_path):
    r = inst("--remove", env=make_env(tmp_path))
    assert r.returncode == 0
    assert log_lines(tmp_path) == [
        "claude plugin uninstall devkit@devkit", "claude plugin marketplace remove devkit"]
    assert not (tmp_path / "codex").exists()
    assert "--codex-note" not in r.stdout


def test_codex_note_despite_claude_failure(tmp_path):
    r = inst("--codex-note", env=make_env(tmp_path, rc=1))
    assert r.returncode == 1
    assert agents_path(tmp_path).read_text(encoding="utf-8") == NOTE
    assert "깔지 못했습니다" in r.stdout


def test_install_only_codex(tmp_path):
    r = inst(env=make_env(tmp_path, tools=("codex",)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / "log").exists()
    assert not agents_path(tmp_path).exists()
    assert "--codex-note" in r.stdout and "새 대화" not in r.stdout      # 아무것도 깔지 않았다


@pytest.mark.parametrize("flag", ["--codex-note", "--remove"])
def test_no_rules_reported(tmp_path, flag):
    k = tmp_path / "k"
    shutil.copytree(str(KIT), str(k), ignore=shutil.ignore_patterns("__pycache__"))
    (k / "rules.md").unlink()
    e = make_env(tmp_path)
    agents_path(tmp_path).parent.mkdir()
    agents_path(tmp_path).write_bytes(b"mine\n")
    r = inst(flag, env=e, script=k / "install.py")
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert agents_path(tmp_path).read_bytes() == b"mine\n"


def test_block_read_from_rules(tmp_path):
    assert not hasattr(install, "NOTE_TEXT")
    k = tmp_path / "k"
    shutil.copytree(str(KIT), str(k), ignore=shutil.ignore_patterns("__pycache__"))
    (k / "rules.md").write_text("# other\n\n- one\n", encoding="utf-8")
    r = inst("--codex-note", env=make_env(tmp_path), script=k / "install.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert agents_path(tmp_path).read_text(encoding="utf-8") == (
        install.NOTE_BEGIN + "\n# other\n\n- one\n" + install.NOTE_END + "\n")


def test_never_asks():
    assert "input(" not in SCRIPT.read_text(encoding="utf-8")


def test_install_is_python38():
    src = SCRIPT.read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for pat in PY39:
        assert not re.search(pat, src, re.M), pat


def test_manifests():
    def m(p):
        return json.loads((KIT / p).read_text(encoding="utf-8"))
    mk, cp = m(".claude-plugin/marketplace.json"), m(".claude-plugin/plugin.json")
    assert mk["plugins"][0]["version"] == cp["version"] == "0.7.1"
    assert mk["description"] == mk["plugins"][0]["description"] == cp["description"] == DESC
    assert mk["owner"] == {"name": "devkit"}
    assert set(cp) == {"name", "description", "version"}


def test_kit_files_exact():
    found = [p for p in KIT.rglob("*") if "__pycache__" not in p.parts]
    assert {p.relative_to(KIT).as_posix() for p in found if p.is_file()} == KIT_FILES
    assert {p.relative_to(KIT).as_posix() for p in found if p.is_dir()} == {".claude-plugin", "hooks", "scripts", "skills", "skills/start", "skills/find"}
