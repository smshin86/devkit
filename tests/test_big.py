import json
import subprocess
import sys
from pathlib import Path

M = Path(__file__).resolve().parents[1] / "docs" / "measure"

KEYS = ("files add del bin tr_files new_tpl mail_en mail_fr routes_add routes_del macro_add form_add css_new css_add "
        "style_attr style_tag style_copied tests_add tests_del t_pass t_fail lint fmt fmt_n end secs committed cost "
        "tools tools_kit denied start find guide said missing").split()


def run(script, *args, home="/nonexistent-devkit-test"):
    p = subprocess.run([sys.executable, "-I", "-B", str(M / script), *map(str, args)],
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


def result(**kw):
    return {"type": "result", "total_cost_usd": 0.5, "is_error": False, **kw}


def fields(line):
    return dict(w.split("=", 1) for w in line.split()[1:] if "=" in w)


def sh(script, *args, home="/nonexistent-devkit-test", env=None):
    p = subprocess.run(["bash", str(M / script), *args], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(home), **(env or {})})
    return p.returncode, p.stdout + p.stderr


# --- 작은 저장소: 시험이 tmp_path 안에서만 만든다 ---

def genv(home):
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(r, *args):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                        "-C", str(r), *args], capture_output=True, text=True, encoding="utf-8", env=genv(r.parent))
    assert p.returncode == 0, p.stderr
    return p.stdout


def commit(r):
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "x")


def put(r, rel, text, mode="w"):
    f = r / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        f.write_bytes(text)
    elif mode == "a":
        with open(f, "a", encoding="utf-8") as h:
            h.write(text)
    else:
        f.write_text(text, encoding="utf-8")


def mkrepo(tmp_path, name="r"):
    r = tmp_path / name
    r.mkdir()
    git(r, "init", "-q")
    put(r, "app/web.py", '@main.route("/a")\ndef a():\n    return "a"\n')
    put(r, "app/tests/old_test.py", "def test_old():\n    pass\n")
    put(r, "app/templates/old.html", '<div style="margin: 0">x</div>\n<p>{{ _("Hi") }}</p>\n')
    put(r, "app/templates/forms.html", "{% macro a(x) %}\n{% endmacro %}\n")
    put(r, "app/static/css/main.css", "p { margin: 0 }\n")
    put(r, "app/forms.py", "class AForm(FlaskForm):\n    pass\n")
    put(r, ".gitignore", "*.pyc\n")
    commit(r)
    return git(r, "rev-parse", "HEAD").strip()


def big(tmp_path, base, events=None, check=None, repo=None, extra=()):
    j = tmp_path / "a.jsonl"
    write(j, events if events is not None else [asst("안녕"), result()])
    args = ["--repo", repo or tmp_path / "r", "--base", base, "--jsonl", j, *extra]
    if check is not None:
        c = tmp_path / "a.check"
        c.write_text(check, encoding="utf-8")
        args += ["--check", c]
    return run("big.py", *args, home=tmp_path)


def has(out, want):
    d = fields(out.splitlines()[0])
    w = dict(x.split("=", 1) for x in want.split())
    assert {k: d.get(k) for k in w} == w, out


# --- big.py ---

def test_big_line_shape(tmp_path):
    base = mkrepo(tmp_path)
    rc, out = big(tmp_path, base)
    L = out.splitlines()
    toks = L[0].split()
    assert rc == 0 and len(L) == 1 and toks[0] == "a"
    assert all("=" in w and w.split("=", 1)[1] for w in toks[1:])
    assert [w.split("=", 1)[0] for w in toks[1:]] == KEYS and len(KEYS) == 36


def test_big_counts_basic(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/templates/step1.html", '{% extends "layout.html" %}\n<p>{{ _("Step") }}</p>\n<p>Plain words</p>\n')
    put(r, "app/web.py", '@main.route("/b")\ndef b():\n    return "b"\n', "a")
    put(r, "app/static/css/new.css", "a { top: 0 }\n")
    put(r, "app/tests/old_test.py", "def test_new():\n    pass\n", "a")
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "files=4 add=9 del=0 new_tpl=1 routes_add=1 css_new=1 tests_add=1 guide=없음")


def test_big_odd_names(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/templates/a b.html", "<p>1</p>\n")
    put(r, "app/templates/한글.html", "<p>2</p>\n")
    put(r, "app/templates/x\ny.html", "<p>3</p>\n")
    git(r, "mv", "app/templates/old.html", "app/templates/older.html")
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "files=5 new_tpl=4 add=5 del=2 style_copied=1 style_attr=0")


def test_big_skips_devkit(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, ".devkit/guide.md", "# g\n")
    put(r, ".devkit/work/a.md", "a\n")
    put(r, "app/.devkit/x.md", "x\n")
    put(r, "app/web.py", "# one\n", "a")
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "files=1 add=1 guide=있음")
    base2 = mkrepo(tmp_path, "r2")
    r2 = tmp_path / "r2"
    put(r2, ".devkit/guide.md", "# g\n")
    put(r2, ".git/info/exclude", ".devkit/guide.md\n", "a")
    rc, out = big(tmp_path, base2, repo=r2)
    assert rc == 0
    has(out, "files=0 guide=있음")


def test_big_gitignore_devkit_line(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, ".gitignore", ".devkit/\n", "a")
    commit(r)
    has(big(tmp_path, base)[1], "files=0 add=0")
    put(r, ".gitignore", "*.log\n", "a")
    commit(r)
    has(big(tmp_path, base)[1], "files=1 add=1")


def test_big_binary(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/static/img/a.png", b"\x89PNG\x00\x01")
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "bin=1 files=1 add=0")


def test_big_translations_apart(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/translations/fr/LC_MESSAGES/messages.po", 'msgid "a"\nmsgstr "b"\n\n')
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "tr_files=1 files=0 add=0")


def test_big_style_new_and_copied(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/templates/n.html",
        '<div style="margin: 0">x</div>\n<span style="color: red">y</span>\n<style>p{}</style>\n'
        '<b data-style="q">z</b>\n<i STYLE = "a">w</i>\n'
        '<p style=" margin:  0">a</p><p style=\'top: 1px\'>b</p>\n')
    put(r, "app/templates/m.en.j2", '<p style="x">\n')
    put(r, "app/static/css/main.css", "a { top: 1px }\nb { top: 2px }\n", "a")
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "style_copied=2 style_attr=3 style_tag=1 css_add=2 css_new=0 mail_en=1")


def test_big_commits_not_tree(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/web.py", "# one\n", "a")
    commit(r)
    put(r, "app/web.py", "# two\n# three\n# four\n# five\n# six\n", "a")
    put(r, "app/untracked.py", "x = 1\n")
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "files=1 add=1")


def test_big_removed_lines(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/web.py", 'def a():\n    return "a"\n')
    put(r, "app/tests/old_test.py", "    pass\n")
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "routes_del=1 tests_del=1 routes_add=0")


def test_big_mail_and_macro(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/templates/r.en.j2", "hi\n")
    put(r, "app/templates/r.fr.j2", "salut\n")
    put(r, "app/templates/forms.html", "{% macro b(form) %}\n{% endmacro %}\n", "a")
    put(r, "app/forms.py", "class BForm(FlaskForm):\n    pass\n", "a")
    commit(r)
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "mail_en=1 mail_fr=1 new_tpl=0 macro_add=1 form_add=1")


def test_big_jsonl_fields(tmp_path):
    base = mkrepo(tmp_path)
    ev = [asst("큰 일로 봅니다 — 여러 화면"),
          tool("Skill", skill="devkit:start"),
          tool("Read", file_path="/x/kit/skills/find/SKILL.md"),
          tool("Write", file_path="/r/.devkit/guide.md", content="x"),
          tool("Bash", command="ls"),
          result(total_cost_usd=1.234, result="한 줄\n없는 단계: a\n없는 단계: b\n끝", permission_denials=[{"a": 1}])]
    rc, out = big(tmp_path, base, events=ev)
    assert rc == 0
    has(out, "tools=4 tools_kit=3 start=1 find=1 said=1 missing=2 denied=1 cost=1.23 end=done")
    ev2 = [{"type": "system", "subtype": "hook_response", "stdout": "큰 일로 봅니다"}, asst("안녕"), result()]
    has(big(tmp_path, base, events=ev2)[1], "said=0")


def test_big_end_kinds(tmp_path):
    base = mkrepo(tmp_path)
    has(big(tmp_path, base, events=[asst("x"), result(is_error=True, subtype="error_max_budget_usd")])[1], "end=budget")
    out = big(tmp_path, base, events=[asst("x")])[1]
    has(out, "end=noresult cost=? missing=? denied=?")
    has(big(tmp_path, base, events=[asst("x")], check="rc=124\n")[1], "end=timeout")
    has(big(tmp_path, base, events=[asst("x"), result(is_error=True, subtype="error_during_execution")])[1], "end=error")


def test_big_check_parse(tmp_path):
    base = mkrepo(tmp_path)
    c1 = ("arm=on\nrc=0\nsecs=75\ntests=1 failed, 10 passed in 2.00s\nlint=Found 2 errors.\n"
          "fmt=1 file would be reformatted, 3 files already formatted\ncommitted=bad\n")
    rc, out = big(tmp_path, base, check=c1)
    assert rc == 0
    has(out, "t_pass=10 t_fail=1 lint=bad fmt=bad fmt_n=1 secs=75 committed=bad")
    c2 = ("tests=10 passed, 1 error in 2s\nlint=All checks passed!\nfmt=4 files already formatted\ncommitted=ok\n")
    rc, out = big(tmp_path, base, check=c2)
    assert rc == 0
    has(out, "t_fail=1 lint=ok fmt=ok fmt_n=0 committed=ok")
    rc, out = big(tmp_path, base, check="tests=129 passed, 5 skipped in 25s\n")
    assert rc == 0
    has(out, "t_pass=129 t_fail=0")
    rc, out = big(tmp_path, base)
    assert rc == 0
    has(out, "t_pass=? t_fail=? lint=? fmt=? fmt_n=? secs=? committed=?")


def test_big_bad_inputs(tmp_path):
    base = mkrepo(tmp_path)
    (tmp_path / "nogit").mkdir()
    rc, out = big(tmp_path, base, repo=tmp_path / "nogit")
    assert rc == 2 and out.startswith("a 못 셈:") and len(out.splitlines()) == 1
    rc, out = big(tmp_path, "zzzz")
    assert rc == 2 and out.startswith("a 못 셈:")
    rc, out = run("big.py", "--repo", tmp_path / "r", "--base", base, "--jsonl", tmp_path / "none.jsonl", home=tmp_path)
    d = fields(out.splitlines()[0])
    assert rc == 2 and d["files"].isdigit() and d["cost"] == "?"
    j = tmp_path / "a.jsonl"
    write(j, [asst("안녕"), result()], tail=b'[1, 2]\n{"type":"assistant","x":"\xed\x95')
    rc, out = run("big.py", "--repo", tmp_path / "r", "--base", base, "--jsonl", j, home=tmp_path)
    assert rc == 0 and fields(out.splitlines()[0])["cost"] == "0.50"


# --- big.sh · big-prompts.txt: 인자가 틀리거나 ~/.devkit가 있으면 아무것도 하기 전에 멈춘다 ---

def test_big_sh_bad_args():
    for args in ((), ("a/b", "on", "1"), ("ok", "mid", "1"), ("ok", "on", "0"), ("ok", "on", "3"), ("ok", "on", "1", "x")):
        rc, out = sh("big.sh", *args)
        assert rc == 9 and "인자 틀림" in out, args


def test_big_sh_good_args_stop_at_home_devkit(tmp_path):
    (tmp_path / ".devkit").mkdir()
    rc, out = sh("big.sh", "ok", "off", "2", home=tmp_path)
    assert rc == 8 and "~/.devkit" in out and "인자 틀림" not in out


def test_big_sh_guard_off_stops(tmp_path):
    (tmp_path / ".devkit-guard-off").write_text("")
    rc, out = sh("big.sh", "ok", "off", "2", home=tmp_path)
    assert rc == 8 and ".devkit-guard-off" in out and "인자 틀림" not in out


def lines_with(path, needle):
    return [x for x in path.read_text(encoding="utf-8").splitlines() if needle in x]


def test_big_sh_same_flags_as_door():
    door, big_sh = M / "door.sh", M / "big.sh"
    a, b = lines_with(door, "--setting-sources project"), lines_with(big_sh, "--setting-sources project")
    assert len(a) == 1 and len(b) == 1
    assert a[0].strip().replace(' --plugin-dir "$K"', "") == b[0].strip()
    for needle in ("--allowedTools", "--disallowedTools", "--no-session-persistence --model sonnet",
                   "--output-format stream-json --verbose --include-hook-events"):
        a, b = lines_with(door, needle), lines_with(big_sh, needle)
        assert len(a) == 1 and len(b) == 1 and a[0].strip() == b[0].strip(), needle


def test_big_sh_budget_time_no_checkout():
    t = (M / "big.sh").read_text(encoding="utf-8")
    for need in ("timeout 2400 ", "--max-budget-usd 2.50", "big-prompts.txt", '"$OP.base"', '"$OP.check"', "big.cost",
                 "committed=", '--since "@$t0"'):
        assert need in t, need
    for bad in ("0.60", "checkout -- .", "checkout -q -- .", "timeout 1200"):
        assert bad not in t, bad


def test_big_sh_plugin_dir_only_on():
    t = (M / "big.sh").read_text(encoding="utf-8")
    assert t.count("--plugin-dir") == 1
    assert [x.strip() for x in lines_with(M / "big.sh", "--plugin-dir")] == ['[ "$ARM" = on ] && PD=(--plugin-dir "$K")']
    assert lines_with(M / "big.sh", 'claude -p "$PROMPT" "${PD[@]}"')


def test_big_prompts_file():
    raw = (M / "big-prompts.txt").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n")
    lines = raw.decode("utf-8").split("\n")[:-1]
    door = (M / "door-prompts.txt").read_bytes().decode("utf-8").split("\n")
    assert len(lines) == 2 and lines[0] == door[1]
    assert lines[1] == "프로젝트 식별자를 잊은 사람이 연락처 메일 주소를 넣으면 그 메일로 자기 프로젝트 식별자를 받아 볼 수 있게 해 줘."


# --- 고침 1: 빠진 시험 ---

def test_big_sh_checks_before_mkdir():
    L = (M / "big.sh").read_text(encoding="utf-8").splitlines()

    def first(needle):
        return next(i for i, x in enumerate(L) if needle in x)
    mk = first("mkdir -p")
    for needle in ('[ -e "$HOME/.devkit" ]', '[ -e "$HOME/.devkit-guard-off" ]', "이미 돌림", "사본이 이미 있음"):
        assert first(needle) < mk, needle


def test_big_sh_signal_trap():
    t = (M / "big.sh").read_text(encoding="utf-8")
    assert "on_sig" in t and "trap" in t and "TERM" in t and "exit 143" in t
    assert "trap on_sig TERM INT HUP" in t


def test_big_sh_powershell_timeout():
    ps = lines_with(M / "big.sh", "powershell.exe")
    assert ps and all("timeout 60 " in x for x in ps)


def test_big_tests_line_without_numbers(tmp_path):
    base = mkrepo(tmp_path)
    has(big(tmp_path, base, check="tests=error: unrecognized arguments: -x\n")[1], "t_pass=? t_fail=?")
    has(big(tmp_path, base, check="tests=2 errors in 1s\n")[1], "t_pass=0 t_fail=2")


def test_big_kit_marks(tmp_path):
    base = mkrepo(tmp_path)
    ev = [tool("Write", file_path="/r/ihatemoney/network.py", content="x")]
    has(big(tmp_path, base, events=ev)[1], "tools=1 tools_kit=0")
    ev = [tool("Write", file_path="/r/kit/scripts/work.py", content="x")]
    has(big(tmp_path, base, events=ev)[1], "tools_kit=1")
    ev = [tool("Bash", command="ls /x/devkit/kit/")]
    has(big(tmp_path, base, events=ev)[1], "tools_kit=1")


def test_big_start_find_other_routes(tmp_path):
    base = mkrepo(tmp_path)
    ev = [tool("Bash", command="cat /k/skills/find/SKILL.md"), tool("Read", file_path="/k/skills/start/SKILL.md")]
    has(big(tmp_path, base, events=ev)[1], "start=1 find=1 tools_kit=2")
    has(big(tmp_path, base, events=[tool("Bash", command="cat /k/skills/find/SKILL.md")])[1], "start=0 find=1")
    has(big(tmp_path, base, events=[tool("Read", file_path="/k/skills/start/SKILL.md")])[1], "start=1 find=0")


def test_big_end_without_jsonl(tmp_path):
    base = mkrepo(tmp_path)
    c = tmp_path / "a.check"
    c.write_text("rc=124\n", encoding="utf-8")
    args = ["--repo", tmp_path / "r", "--base", base, "--jsonl", tmp_path / "none.jsonl"]
    rc, out = run("big.py", *args, "--check", c, home=tmp_path)
    assert rc == 2
    has(out, "end=timeout")
    c.write_text("rc=0\n", encoding="utf-8")
    rc, out = run("big.py", *args, "--check", c, home=tmp_path)
    assert rc == 2
    has(out, "end=?")
    rc, out = run("big.py", *args, home=tmp_path)
    assert rc == 2
    has(out, "end=?")


def test_big_new_gitignore_devkit_only(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/.gitignore", ".devkit/\n")
    commit(r)
    has(big(tmp_path, base)[1], "files=0 add=0")


def test_big_base_dash_not_run(tmp_path):
    mkrepo(tmp_path)
    j = tmp_path / "a.jsonl"
    write(j, [asst("안녕"), result()])
    rc, out = run("big.py", "--repo", tmp_path / "r", "--base=--output=x", "--jsonl", j, home=tmp_path)
    assert rc == 2 and out.startswith("a 못 셈:") and len(out.splitlines()) == 1
    assert not (tmp_path / "r" / "x").exists() and not (tmp_path / "x").exists()


def test_big_label(tmp_path):
    base = mkrepo(tmp_path)
    rc, out = big(tmp_path, base, extra=("--label", "zz1"))
    assert rc == 0 and out.split()[0] == "zz1"


def test_big_fmt_bad_without_count(tmp_path):
    base = mkrepo(tmp_path)
    has(big(tmp_path, base, check="fmt=would reformat: a.py\n")[1], "fmt=bad fmt_n=?")
