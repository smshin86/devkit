import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "docs" / "measure"

KEYS = ("b_files b_add b_del f_files f_add f_del end1 end2 cost1 cost2 cost secs1 secs2 secs tools1 tools2 skills "
        "skills_other start intake find restart2 said miss1 miss2 miss_intake denied1 denied2 denied rec stage size "
        "path m_n d_n n_n s_n d1_n words words_code words_bad words1").split()


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


def tool_id(name, id, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": id, "name": name, "input": inp}]}}


def result(**kw):
    return {"type": "result", "total_cost_usd": 0.5, "is_error": False, **kw}


def fields(line):
    return dict(w.split("=", 1) for w in line.split()[1:] if "=" in w)


def sh(script, *args, home="/nonexistent-devkit-test", env=None, cwd=None):
    p = subprocess.run(["bash", str(M / script), *args], capture_output=True, text=True, cwd=cwd,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(home), **(env or {})})
    return p.returncode, p.stdout + p.stderr


# --- 작은 저장소: 시험이 tmp_path 안에서만 만든다 ---

def genv(home):
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(r, *args, env=None):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                        "-C", str(r), *args], capture_output=True, text=True, encoding="utf-8",
                       env={**genv(r.parent), **(env or {})})
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
    put(r, "app/templates/old.html", "<p>old</p>\n")
    put(r, ".gitignore", "*.pyc\n")
    commit(r)
    return git(r, "rev-parse", "HEAD").strip()


def head(r):
    return git(r, "rev-parse", "HEAD").strip()


def snapshot(r, base):
    """커밋하지 않는 사진: 임시 인덱스로 트리를 만들고 부모=base인 커밋만 만든다(가지에 걸리지 않는다)."""
    ix = {"GIT_INDEX_FILE": str(r.parent / (r.name + ".idx"))}
    git(r, "read-tree", base, env=ix)
    git(r, "add", "-A", env=ix)
    tree = git(r, "write-tree", env=ix).strip()
    snap = git(r, "commit-tree", tree, "-p", base, "-m", "snap", env=ix).strip()
    (r.parent / (r.name + ".idx")).unlink()
    return snap


def two(tmp_path):
    """base, t1(새 파일 3줄을 커밋), t2(그 파일 1줄 고침)을 만든다."""
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/n.py", "a = 1\nb = 2\nc = 3\n")
    commit(r)
    t1 = head(r)
    put(r, "app/n.py", "a = 1\nb = 9\nc = 3\n")
    commit(r)
    return base, t1, head(r), r


def ir(tmp_path, base, t1, t2=None, ev1=None, ev2=None, check=None, snap=None, cum=None, label=None, repo=None):
    args = ["run", "--repo", repo or tmp_path / "r", "--base=" + str(base), "--t1=" + str(t1)]
    j1 = tmp_path / "1.jsonl"
    j1.unlink(missing_ok=True)
    if ev1 != "none":
        write(j1, ev1 if ev1 is not None else [asst("안녕"), result()])
    args += ["--j1", j1]
    if t2 is not None:
        args += ["--t2=" + str(t2)]
    if ev2 is not None:
        j2 = tmp_path / "2.jsonl"
        j2.unlink(missing_ok=True)
        if ev2 != "none":
            write(j2, ev2)
        args += ["--j2", j2]
    if check is not None:
        c = tmp_path / "a.check"
        c.write_text(check, encoding="utf-8")
        args += ["--check", c]
    if snap is not None:
        args += ["--snap", snap]
    if cum is None:
        cum = "0"
    if cum != "omit":
        args += ["--cum", cum]
    if label is not None:
        args += ["--label", label]
    return run("intake.py", *args, home=tmp_path)


def has(out, want):
    d = fields(out.splitlines()[0])
    w = dict(x.split("=", 1) for x in want.split())
    assert {k: d.get(k) for k in w} == w, out


def lines_with(path, needle):
    return [x for x in path.read_text(encoding="utf-8").splitlines() if needle in x]


def text(name):
    return (M / name).read_text(encoding="utf-8")


def tuple_const(path, name):
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError(name)


# --- intake.sh: 인자가 틀리거나 ~/.devkit가 있으면 아무것도 하기 전에 멈춘다 ---

def test_intake_sh_bad_args():
    for args in ((), ("a/b", "new", "1"), ("ok", "mid", "1"), ("ok", "on", "1"), ("ok", "new", "0"), ("ok", "new", "4"),
                 ("ok", "new", "1", "x")):
        rc, out = sh("intake.sh", *args)
        assert rc == 9 and "인자 틀림" in out, args


def test_intake_sh_good_args_stop_at_home_devkit(tmp_path):
    (tmp_path / ".devkit").mkdir()
    for arm in ("new", "old"):
        rc, out = sh("intake.sh", "ok", arm, "2", home=tmp_path)
        assert rc == 8 and "~/.devkit" in out and "인자 틀림" not in out, arm


def test_intake_sh_guard_off_stops(tmp_path):
    (tmp_path / ".devkit-guard-off").write_text("")
    rc, out = sh("intake.sh", "ok", "new", "2", home=tmp_path)
    assert rc == 8 and ".devkit-guard-off" in out and "인자 틀림" not in out


def test_intake_sh_same_flags_as_big():
    for needle in ("--setting-sources project", "--allowedTools", "--disallowedTools",
                   "--output-format stream-json --verbose --include-hook-events"):
        a, b = lines_with(M / "intake.sh", needle), lines_with(M / "big.sh", needle)
        assert len(a) == 2 and len(b) == 1, needle
        assert all(x.strip() == b[0].strip() for x in a), needle
    model = [x for x in lines_with(M / "intake.sh", "--model sonnet") if x.strip() == "--model sonnet \\"]
    assert len(model) == 2
    assert "--no-session-persistence" not in text("intake.sh")


def test_intake_sh_two_turns():
    t = text("intake.sh")
    L = t.splitlines()
    assert len(lines_with(M / "intake.sh", 'claude -p "$PROMPT" --session-id "$SID" "${PD[@]}"')) == 1
    assert len(lines_with(M / "intake.sh", 'claude -p "$REPLY" --resume "$SID" "${PD[@]}"')) == 1
    assert t.count("timeout 2400 ") == 2 and t.count("--max-budget-usd 2.50") == 2
    budget = lines_with(M / "intake.sh", "--max-budget-usd")
    assert len(budget) == 2 and all(x.strip() == "--max-budget-usd 2.50 \\" for x in budget)
    assert "/proc/sys/kernel/random/uuid" in t
    first_sess = next(i for i, x in enumerate(L) if "intake.sessions" in x)
    first_claude = next(i for i, x in enumerate(L) if "claude -p" in x)
    assert first_sess < first_claude
    for need in ("intake-prompts.txt", "intake-replies.txt", "intake.cost", '"$OP.t1.jsonl"', '"$OP.t2.jsonl"',
                 '"$OP.t1.devkit"', '"$OP.base"', '"$OP.check"', '--since "@$t0"'):
        assert need in t, need
    for bad in ("0.60", "timeout 1200", "checkout -- .", "big.cost", "BCUM"):
        assert bad not in t, bad


def test_intake_sh_t1_snapshot():
    t = text("intake.sh")
    for need in ("GIT_INDEX_FILE=", "read-tree", "write-tree", "commit-tree", '> "$OP.t1"', 'rm -f "$IX"'):
        assert need in t, need
    cq = lines_with(M / "intake.sh", "commit -q")
    assert len(cq) == 2 and "$NAME" in cq[0] and "$NAME" not in cq[1]


def test_intake_sh_memory_guard():
    t = text("intake.sh")
    L = t.splitlines()
    for need in ("/^MemFree:/", "1572864", "압축 안 함", "return 3"):
        assert need in t, need
    comp = [i for i, x in enumerate(L) if "compact.py" in x]
    assert len(comp) == 1 and any("1572864" in x for x in L[:comp[0]])
    mk = next(i for i, x in enumerate(L) if "mkdir -p" in x)
    m1 = next(i for i, x in enumerate(L) if "memok t1" in x)
    clone = next(i for i, x in enumerate(L) if "git clone" in x)
    assert mk < m1 < clone
    assert "memok t2" in t


def test_intake_sh_arms():
    t = text("intake.sh")
    assert t.count("--plugin-dir") == 1
    assert [x.strip() for x in lines_with(M / "intake.sh", "--plugin-dir")] == ['PD=(--plugin-dir "$K")']
    assert "/mnt/e/claude_dev/devkit/kit ;;" in t and "/mnt/e/claude_dev/devkit/old/kit-0.3.0 ;;" in t


def test_intake_sh_checks_before_mkdir():
    L = text("intake.sh").splitlines()

    def first(needle):
        return next(i for i, x in enumerate(L) if needle in x and not x.lstrip().startswith("#"))
    mk = first("mkdir -p")
    for needle in ('[ -e "$HOME/.devkit" ]', '[ -e "$HOME/.devkit-guard-off" ]', "부탁 파일 없음", "답 파일 없음",
                   "이미 돌림", "사본이 이미 있음", "돈 멈춤", "IK_KIT", "IK_COST", "IK_NEED"):
        assert first(needle) < mk, needle


def test_intake_sh_money_rule():
    t = text("intake.sh")
    for need in ('[ -f "$LEDGER" ]', "BEGIN{exit !(s+n>t)}", "NEED=${IK_NEED-2.50}", "STOP=${IK_STOP-8.00}", "exit 4",
                 "돈 알림", "s>=6"):
        assert need in t, need
    assert "-ge 6" not in t


# --- intake.sh: 환경 변수 다섯(꾸러미·이름표·장부·돈 선 둘). 다 같이 주거나 다 같이 안 준다 ---

def kit_env(kit, arm="ask", **kw):
    e = {"IK_KIT": str(kit), "IK_ARM": arm, "IK_COST": "ask2.cost", "IK_NEED": "1.00", "IK_STOP": "5.50"}
    e.update(kw)
    return e


def test_intake_sh_env_bad(tmp_path):
    (tmp_path / ".devkit").mkdir()
    pj = tmp_path / "k" / ".claude-plugin"
    pj.mkdir(parents=True)
    (pj / "plugin.json").write_text("{}")
    (tmp_path / "e").mkdir()
    k = tmp_path / "k"
    good = kit_env(k)
    ok = ("ok", "ask", "1")
    cases = [("only kit", ok, {"IK_KIT": str(k)}, None), ("only arm", ok, {"IK_ARM": "ask"}, None),
             ("kit+arm only", ok, {"IK_KIT": str(k), "IK_ARM": "ask"}, None),
             ("empty kit only", ok, {"IK_KIT": ""}, None),
             ("relative kit", ok, kit_env("k"), tmp_path),
             ("no plugin.json", ok, kit_env(tmp_path / "e"), None),
             ("dotdot middle", ok, kit_env(f"{tmp_path}/k/../k"), None),
             ("dotdot end", ok, kit_env(f"{tmp_path}/k/.claude-plugin/.."), None),
             ("arm vs arg2", ("ok", "lines", "1"), good, None)]
    for drop in good:
        cases.append(("four of five, no " + drop, ok, {a: b for a, b in good.items() if a != drop}, None))
    for arm in ("Ask", "a-b", "new", "old", "abcdefghi", ""):
        cases.append(("arm " + repr(arm), ("ok", arm, "1"), kit_env(k, arm), None))
    for key, vals in (("IK_COST", ("a/b.cost", "x.txt", "", ".cost")), ("IK_NEED", ("1", "x", "0.00", "")),
                      ("IK_STOP", ("5.5", "x", "", "1.00"))):
        for v in vals:
            cases.append((key + "=" + repr(v), ok, kit_env(k, **{key: v}), None))
    cases.append(("need>stop", ok, kit_env(k, IK_NEED="3.00", IK_STOP="2.00"), None))
    for label, args, env, cwd in cases:
        rc, out = sh("intake.sh", *args, home=tmp_path, env=env, cwd=cwd)
        assert rc == 9 and "인자 틀림" in out, (label, rc, out)


def test_intake_sh_env_good_stop_at_home_devkit(tmp_path):
    (tmp_path / ".devkit").mkdir()
    pj = tmp_path / "k" / ".claude-plugin"
    pj.mkdir(parents=True)
    (pj / "plugin.json").write_text("{}")
    cases = [(("ok", "ask", "1"), kit_env(tmp_path / "k", IK_COST="intake.cost", IK_NEED="2.50", IK_STOP="8.00")),
             (("ok", "ask", "1"), kit_env(tmp_path / "k")),
             (("ok", "k1", "3"), kit_env(tmp_path / "k", "k1")),
             (("ok", "k0", "2"), kit_env(tmp_path / "k", "k0", IK_COST="p10.cost", IK_NEED="0.50", IK_STOP="12.00")),
             (("ok", "base", "2"), kit_env(ROOT / "kit", "base"))]
    for args, env in cases:
        rc, out = sh("intake.sh", *args, home=tmp_path, env=env)
        assert rc == 8 and "~/.devkit" in out and "인자 틀림" not in out, (args, env, out)


def test_intake_sh_no_env_keeps_arms(tmp_path):
    for arm in ("ask", "base"):
        rc, out = sh("intake.sh", "ok", arm, "1", home=tmp_path)
        assert rc == 9 and "인자 틀림" in out, arm
    (tmp_path / ".devkit").mkdir()
    for arm in ("new", "old"):
        rc, out = sh("intake.sh", "ok", arm, "1", home=tmp_path)
        assert rc == 8 and "~/.devkit" in out and "인자 틀림" not in out, arm


def test_intake_sh_ledger_one_name():
    t = text("intake.sh")
    L = t.splitlines()
    assert '"$O/intake.cost"' not in t and t.count('"$LEDGER"') == 6
    assert len([x for x in L if '>> "$LEDGER"' in x]) == 3
    assert len([x for x in L if x == "LEDGER_NAME=${IK_COST-intake.cost}"]) == 1
    assert len([x for x in L if x == "LEDGER=$O/$LEDGER_NAME"]) == 1


def test_intake_sh_money_vars():
    t = text("intake.sh")
    L = t.splitlines()
    rule = [x for x in L if "BEGIN{exit !(s+n>t)}" in x]
    assert len(rule) == 2 and all('-v n="$NEED" -v t="$STOP"' in x for x in rule)
    assert "2.50>8.00" not in t
    assert '돈 멈춤: 합 $spent + $NEED > $STOP' in t
    assert "skip:money" in rule[1]


def test_intake_sh_env_unset_before_claude():
    t = text("intake.sh")
    L = t.splitlines()
    un = [i for i, x in enumerate(L) if "unset IK_KIT IK_ARM IK_COST IK_NEED IK_STOP" in x]
    assert len(un) == 1
    first_claude = next(i for i, x in enumerate(L) if "claude -p" in x)
    ledger = next(i for i, x in enumerate(L) if x == "LEDGER=$O/$LEDGER_NAME")
    assert ledger < un[0] < first_claude
    assert "K=$IK_KIT" in t
    assert [x.strip() for x in lines_with(M / "intake.sh", "--plugin-dir")] == ['PD=(--plugin-dir "$K")']


def test_intake_sh_signal_trap():
    t = text("intake.sh")
    for need in ("on_sig", "exit 143", "trap on_sig TERM INT HUP", "TURN=t1", "TURN=t2", '"$OP.$TURN.jsonl"'):
        assert need in t, need
    L = t.splitlines()
    a = next(i for i, x in enumerate(L) if "on_sig()" in x)
    b = next(i for i, x in enumerate(L) if i > a and "exit 143" in x)
    body = L[a:b + 1]
    cum = next(i for i, x in enumerate(body) if "CUM" in x)
    money = next(i for i, x in enumerate(body) if "2.50" in x)
    assert cum < money


def test_intake_sh_powershell_timeout():
    ps = lines_with(M / "intake.sh", "powershell.exe")
    assert ps and all("timeout 60 " in x for x in ps)


def test_intake_sh_cum_constants():
    L = text("intake.sh").splitlines()
    assert len([x for x in L if re.fullmatch(r"CUM=[01]", x)]) == 1
    assert "BCUM" not in text("intake.sh")
    chk = [x for x in L if x.startswith("printf ") and '> "$OP.check"' in x]
    assert len(chk) == 1 and "cum=%s" in chk[0] and '"$CUM"' in chk[0]


def test_intake_sh_t2_skip_reasons():
    t = text("intake.sh")
    assert "skip:" in t
    for r in ("timeout", "nosid", "noresult", "budget", "differ", "rc", "left", "money", "mem"):
        assert "skip:" + r in t, r
    L = t.splitlines()
    marks = [i for i, x in enumerate(L) if "# 끝 값 차례" in x]
    assert len(marks) == 1
    below = "\n".join(L[marks[0] + 1:])
    pos = [below.index("exit " + n) for n in ("10", "11", "6", "13", "12", "5")]
    assert pos == sorted(pos)


def test_intake_sh_after_lines_from_big():
    for needle in ("tests=$(", "lint=$(", "fmt=$("):
        a, b = lines_with(M / "intake.sh", needle), lines_with(M / "big.sh", needle)
        assert len(a) == 1 and len(b) == 1, needle
        assert a[0].strip() == b[0].strip(), needle


# --- 글 파일 ---

def test_intake_prompt_files():
    want_p = ["안 쓰는 참여자를 한꺼번에 정리할 수 있게 해 줘. 고르는 화면 다음에 확인 화면이 나오게.",
              "지출 목록을 인쇄하기 좋게 볼 수 있게 해 줘. 기간을 고르는 화면 다음에 인쇄용 화면이 나오게.",
              (M / "big-prompts.txt").read_bytes().decode("utf-8").split("\n")[1]]
    want_r = ["안 쓰는 참여자는 지출에 한 번도 안 나온 사람을 말한 거예요. 정리는 그 사람들을 지우는 거예요. "
              "지출에 나온 사람은 고르는 화면에 아예 안 나오게 해 주세요. 그 밖에 물어보신 것은 권하신 답대로 해 주세요.",
              "기간은 지출 날짜 기준이에요. 인쇄용 화면에는 그 기간의 지출 목록과 맨 아래 합계만 넣어 주세요. "
              "그 밖에 물어보신 것은 권하신 답대로 해 주세요.",
              "추천대로 해 주세요."]
    for name, want in (("intake-prompts.txt", want_p), ("intake-replies.txt", want_r)):
        raw = (M / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n"), name
        lines = raw.decode("utf-8").split("\n")[:-1]
        assert len(lines) == 3 and lines == want, name
    assert want_p[2].startswith("프로젝트 식별자를 잊은 사람이")


# --- intake.py ---

def test_intake_py_line_shape(tmp_path):
    base, t1, t2, r = two(tmp_path)
    rc, out = ir(tmp_path, base, t1, t2, ev2=[asst("안녕"), result()])
    L = out.splitlines()
    toks = L[0].split()
    assert rc == 0 and len(L) == 1 and toks[0] == "intake"
    assert all("=" in w and w.split("=", 1)[1] for w in toks[1:])
    assert [w.split("=", 1)[0] for w in toks[1:]] == KEYS and len(KEYS) == 42


def test_intake_py_spans(tmp_path):
    base, t1, t2, r = two(tmp_path)
    rc, out = ir(tmp_path, base, t1, t2)
    assert rc == 0
    has(out, "b_files=1 b_add=3 b_del=0 f_files=1 f_add=1 f_del=1")
    # 사진 커밋은 가지에 걸리지 않고, 끝 커밋은 base 위의 가지 커밋이다
    base2 = mkrepo(tmp_path, "r2")
    r2 = tmp_path / "r2"
    put(r2, "app/n.py", "a = 1\nb = 2\nc = 3\n")
    snap = snapshot(r2, base2)
    put(r2, "app/n.py", "a = 1\nb = 9\nc = 3\n")
    commit(r2)
    rc, out = ir(tmp_path, base2, snap, head(r2), repo=r2)
    assert rc == 0
    has(out, "b_files=1 b_add=3 b_del=0 f_files=1 f_add=1 f_del=1")


def test_intake_py_span_skips_devkit(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, ".devkit/work/a.md", "a\n")
    commit(r)
    rc, out = ir(tmp_path, base, head(r))
    assert rc == 0
    has(out, "b_files=0 b_add=0")
    put(r, ".gitignore", ".devkit/\n", "a")
    commit(r)
    has(ir(tmp_path, base, head(r))[1], "b_files=0 b_add=0")


def test_intake_py_binary(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, "app/static/a.png", b"\x89PNG\x00\x01")
    commit(r)
    rc, out = ir(tmp_path, base, head(r))
    assert rc == 0
    has(out, "b_files=1 b_add=0")


def test_intake_py_no_t2(tmp_path):
    base, t1, t2, r = two(tmp_path)
    rc, out = ir(tmp_path, base, t1, ev1=[asst("안녕"), tool("Read", file_path="/x"), result(total_cost_usd=0.4)])
    assert rc == 0
    has(out, "f_files=- f_add=- f_del=- end2=- cost1=0.40 cost2=- cost=0.40 secs2=- tools1=1 tools2=- miss2=- denied2=-")
    has(out, "restart2=-")


def test_intake_py_end_kinds(tmp_path):
    base, t1, t2, r = two(tmp_path)
    has(ir(tmp_path, base, t1, t2, ev2=[asst("x"), result()])[1], "end1=done end2=done")
    has(ir(tmp_path, base, t1, ev1=[asst("x"), result(is_error=True)])[1], "end1=error")
    has(ir(tmp_path, base, t1, ev1=[asst("x"), result(is_error=True, subtype="error_max_budget_usd")])[1],
        "end1=budget")
    out = ir(tmp_path, base, t1, ev1=[asst("x")])[1]
    has(out, "end1=noresult cost1=? denied1=? miss1=?")
    has(ir(tmp_path, base, t1, ev1="none")[1], "end1=?")
    has(ir(tmp_path, base, t1, t2, ev2="none")[1], "end1=done end2=?")
    has(ir(tmp_path, base, t1, check="rc1=124\n")[1], "end1=timeout")
    has(ir(tmp_path, base, t1, t2, ev2=[asst("x"), result()], check="rc1=0\nrc2=124\n")[1], "end1=done end2=timeout")


def test_intake_py_cost_cum(tmp_path):
    base, t1, t2, r = two(tmp_path)
    ev1 = [asst("a"), result(total_cost_usd=0.4)]
    ev2 = [asst("b"), result(total_cost_usd=0.9)]
    rc, out = ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2, cum="1")
    assert rc == 0
    has(out, "cost1=0.40 cost2=0.50 cost=0.90")
    rc, out = ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2, cum="0")
    assert rc == 0
    has(out, "cost1=0.40 cost2=0.90 cost=1.30")
    rc, out = ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2)
    has(out, "cost2=0.90 cost=1.30")
    has(ir(tmp_path, base, t1, t2, ev1=ev1, ev2=[asst("b")], cum="1")[1], "cost1=0.40 cost2=? cost=?")
    chk = "secs1=70\nsecs2=-\nsecs=71\n"
    has(ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2, check=chk)[1], "secs1=70 secs2=- secs=71")


def test_intake_py_cost_cum_from_check(tmp_path):
    base, t1, t2, r = two(tmp_path)
    ev1 = [asst("a"), result(total_cost_usd=0.4)]
    ev2 = [asst("b"), result(total_cost_usd=0.9)]

    def go(check, cum="omit", **kw):
        return ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2, check=check, cum=cum, **kw)

    rc, out = go("cum=1\n")
    assert rc == 0
    has(out, "cost1=0.40 cost2=0.50 cost=0.90")
    rc, out = go("cum=0\n")
    assert rc == 0
    has(out, "cost2=0.90 cost=1.30")
    rc, out = go("rc1=0\n")
    assert rc == 2
    has(out, "cost1=0.40 cost2=? cost=?")
    rc, out = go("cum=1\n", cum="0")
    assert rc == 2
    has(out, "cost2=? cost=?")
    rc, out = go("cum=x\n")
    assert rc == 2
    has(out, "cost2=? cost=?")
    rc, out = go("cum=1\n", cum="1")
    assert rc == 0
    has(out, "cost2=0.50 cost=0.90")
    # 둘째 턴이 없으면 cum은 쓰이지 않는다
    rc, out = ir(tmp_path, base, t1, ev1=ev1, check="rc1=0\n", cum="omit")
    assert rc == 0
    has(out, "cost1=0.40 cost2=- cost=0.40")
    rc, out = ir(tmp_path, base, t1, ev1=ev1, cum="omit")
    assert rc == 0


def test_intake_py_t2_replay_dedup(tmp_path):
    base, t1, t2, r = two(tmp_path)
    a = tool_id("Read", "ta", file_path="/x/a")
    b = tool_id("Read", "tb", file_path="/x/b")
    c = tool_id("Read", "tc", file_path="/x/c")
    ev1 = [a, b, result(permission_denials=[{"tool_use_id": "ta", "tool_name": "Bash"}])]
    ev2 = [a, b, c, result(permission_denials=[{"tool_use_id": "ta", "tool_name": "Bash"}])]
    rc, out = ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2)
    assert rc == 0
    has(out, "tools1=2 tools2=1 denied1=1 denied2=0 denied=1")
    ev2 = [a, b, c, result(permission_denials=[{"tool_use_id": "ta"}, {"tool_use_id": "td"}])]
    has(ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2)[1], "denied1=1 denied2=1 denied=2")


def test_intake_py_skills_list(tmp_path):
    base, t1, t2, r = two(tmp_path)
    ev1 = [tool_id("Skill", "s1", skill="devkit:start"), tool_id("Skill", "s2", skill="devkit:intake")]
    ev2 = [tool_id("Skill", "s2", skill="devkit:intake"), tool_id("Skill", "s3", skill="devkit:find"), result()]
    rc, out = ir(tmp_path, base, t1, t2, ev1=ev1, ev2=ev2)
    assert rc == 0
    has(out, "skills=start,intake,find start=1 intake=1 find=1 skills_other=0")
    rc, out = ir(tmp_path, base, t1, ev1=[tool("Skill", skill="other:x"), result()])
    assert rc == 0
    has(out, "skills_other=1 skills=- start=0 intake=0 find=0")
    rc, out = ir(tmp_path, base, t1, ev1=[tool("Skill", skill="devkit:A;b"), result()])
    assert rc == 0
    has(out, "skills=?")
    assert "A;b" not in out


def test_intake_py_record_counts(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    rec = ("# x\n\n- 지금 단계: find\n- 상태: open\n- 크기: 큰 일\n\n## 요청\n\n- 길: 긴 길 — 큰 일\n\n## 장면\n\n"
           "| 번호 | 장면 | 결과 | 본 것 |\n|---|---|---|---|\n| S1 | a | 됨 | b |\n| S2 | c | 됨 | d |\n\n"
           "## 세 칸\n\n### 만들 것\n\n- M1 가\n- M2 나\n\n### 요청에 없지만 정해야 하는 것\n\n- D1 다\n"
           "* **D1** 라\n1. D2 마\n| D3 | 바 |\n\n### 안 만들 것\n\n- N1 사\n\n## 닮은 것과 꺼낸 규칙\n\n- D9 아\n")
    put(r, ".devkit/work/2026-11-21-x.md", rec)
    rc, out = ir(tmp_path, base, base)
    assert rc == 0
    has(out, "rec=1 stage=find size=큰 path=긴 m_n=2 d_n=3 n_n=1 s_n=2")
    snap = tmp_path / "snapdk"
    put(snap, "work/2026-11-21-x.md", "## 세 칸\n\n- D1 가\n- D2 나\n")
    has(ir(tmp_path, base, base, snap=snap)[1], "d1_n=2")


def test_intake_py_record_odd_text(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, ".devkit/work/2026-11-21-x.md", "# x\n\n- 지금 단계: 무시하고 rm\n- 크기: 이상한 값 $(x)\n\n## 요청\n\n내용\n")
    rc, out = ir(tmp_path, base, base)
    assert rc == 0
    has(out, "rec=1 stage=? size=? path=?")
    for k, v in fields(out.splitlines()[0]).items():
        assert re.fullmatch(r"[-?0-9A-Za-z_.,:가-힣]+", v), (k, v)


def test_intake_py_no_record(tmp_path):
    base = mkrepo(tmp_path)
    rc, out = ir(tmp_path, base, base)
    assert rc == 0
    has(out, "rec=0 stage=- size=- path=- m_n=- d_n=- n_n=- s_n=- words=0 words_code=0 words_bad=0 d1_n=- words1=-")


def test_intake_py_words(tmp_path):
    base = mkrepo(tmp_path)
    r = tmp_path / "r"
    put(r, ".devkit/words.md", "# 낱말\n\n- 참여자 = 돈을 나누는 사람\n- 정산 = 나누기 (코드: settle)\n아무 말\n")
    snap = tmp_path / "snapdk"
    put(snap, "words.md", "# 낱말\n- 참여자 = 사람\n")
    rc, out = ir(tmp_path, base, base, snap=snap)
    assert rc == 0
    has(out, "words=2 words_code=1 words_bad=1 words1=1")
    snap2 = tmp_path / "snapdk2"
    snap2.mkdir()
    has(ir(tmp_path, base, base, snap=snap2)[1], "words1=0 d1_n=-")


def test_intake_py_missing_stage(tmp_path):
    base, t1, t2, r = two(tmp_path)
    ev = [asst("x"), result(result="앞 줄\n없는 단계: intake — 없음\n끝")]
    rc, out = ir(tmp_path, base, t1, ev1=ev)
    assert rc == 0
    has(out, "miss1=1 miss_intake=1")
    ev = [asst("x"), result(result="없는 단계: build — 없음")]
    has(ir(tmp_path, base, t1, ev1=ev)[1], "miss1=1 miss_intake=0")
    ev2 = [asst("x"), result(result="없는 단계: a\n없는 단계: intake")]
    has(ir(tmp_path, base, t1, t2, ev1=ev, ev2=ev2)[1], "miss1=1 miss2=2 miss_intake=1")


def test_intake_py_said(tmp_path):
    base, t1, t2, r = two(tmp_path)
    has(ir(tmp_path, base, t1, ev1=[asst("큰 일로 봅니다 — 여러 화면"), result()])[1], "said=1")
    has(ir(tmp_path, base, t1, ev1=[{"type": "system", "stdout": "큰 일로 봅니다"}, asst("안녕"), result()])[1], "said=0")


def test_intake_py_restart2(tmp_path):
    base, t1, t2, r = two(tmp_path)
    s1 = tool_id("Skill", "s1", skill="devkit:start")
    rc, out = ir(tmp_path, base, t1, t2, ev1=[s1, result()], ev2=[tool_id("Skill", "s9", skill="devkit:start"), result()])
    assert rc == 0
    has(out, "restart2=1")
    has(ir(tmp_path, base, t1, t2, ev1=[s1, result()], ev2=[s1, result()])[1], "restart2=0")
    has(ir(tmp_path, base, t1, ev1=[s1, result()])[1], "restart2=-")


def test_intake_py_bad_inputs(tmp_path):
    base, t1, t2, r = two(tmp_path)
    rc, out = ir(tmp_path, "-x", t1)
    assert rc == 2 and "못 셈" in out and len(out.splitlines()) == 1
    (tmp_path / "nogit").mkdir()
    rc, out = ir(tmp_path, base, t1, repo=tmp_path / "nogit")
    assert rc == 2 and "못 셈" in out
    rc, out = ir(tmp_path, base, "0" * 40)
    assert rc == 2 and "못 셈" in out
    rc, out = ir(tmp_path, base, t1, "zzzz")
    assert rc == 2 and "못 셈" in out
    rc, out = ir(tmp_path, base, "-x")
    assert rc == 2 and "못 셈" in out
    rc, out = ir(tmp_path, base, t1, label="zz1")
    assert rc == 0 and out.split()[0] == "zz1"


def test_intake_py_skills_form(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write(a, [tool("Skill", skill="devkit:start"), tool("Skill", skill="devkit:intake"),
              asst("큰 일로 봅니다"), result(total_cost_usd=0.4, result="없는 단계: intake")])
    write(b, [asst("x")])
    rc, out = run("intake.py", "skills", a, b, home=tmp_path)
    L = out.splitlines()
    assert rc == 0 and len(L) == 2
    assert L[0].startswith("a.jsonl skills=") and L[1].startswith("b.jsonl skills=")
    for k in ("intake=", "miss_intake=", "cost="):
        assert all(k in x for x in L), k
    has(L[0] + "\n", "skills=start,intake intake=1 start=1 find=0 said=1 missing=1 miss_intake=1 cost=0.40")
    has(L[1] + "\n", "skills=- cost=?")
    rc, out = run("intake.py", "skills", a, tmp_path / "none.jsonl", home=tmp_path)
    assert rc == 2 and "none.jsonl 없음" in out


def test_intake_py_uses_big():
    t = text("intake.py")
    assert "from big import" in t and "def hunk_lines" not in t and "def read_events" not in t
    assert tuple_const(M / "intake.py", "STAGES") == tuple_const(ROOT / "kit" / "scripts" / "work.py", "STAGES")
