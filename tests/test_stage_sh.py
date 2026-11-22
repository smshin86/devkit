import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "docs" / "measure"
SH = M / "stage.sh"
TOOLS9 = "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent,TaskStop"
DIS_NEW11 = ["Bash(*cc-socks*)", "Bash(*.claude/sessions*)", "Bash(*nc -U*)", "Bash(*socat*)", "Bash(*AF_UNIX*)", "Bash(claude *)",
             "Bash(* claude *)", "Bash(*/claude *)", "Bash(*crontab*)", "Bash(*systemd-run*)", "Bash(*systemctl*)"]
LK = M / "stage-locked.sh"
BASE_PATH = "/usr/bin:/bin"


def sh(args, home, env=None, path=BASE_PATH, cwd=None, script=SH):
    p = subprocess.run(["bash", str(script), *args], capture_output=True, text=True, cwd=cwd,
                       env={"PATH": path, "HOME": str(home), **(env or {})})
    return p.returncode, p.stdout + p.stderr


def code():
    return SH.read_text(encoding="utf-8")


def lines():
    return code().split("\n")


def live(txt):
    """주석 줄과 큰따옴표로 묶인 막을 낱말을 뺀 글 — 명령 자리만 남긴다."""
    out = []
    for ln in txt.split("\n"):
        if ln.lstrip().startswith("#"):
            continue
        out.append(re.sub(r'"Bash\((?:[^"\\]|\\.)*\)"', '""', ln))
    return "\n".join(out)


def first_line(pattern, flags=0):
    for i, ln in enumerate(lines()):
        if ln.lstrip().startswith("#"):
            continue
        if re.search(pattern, ln, flags):
            return i
    return None


# ---------- 시험이 띄운 프로세스를 고아로 남기지 않는다 ----------

def _ancestors():
    out, p = {os.getpid()}, os.getppid()
    while p > 1 and p not in out:
        out.add(p)
        try:
            tail = Path("/proc/%d/stat" % p).read_text().rsplit(")", 1)[1].split()
            p = int(tail[1])
        except (OSError, IndexError, ValueError):
            break
    return out


def pids_mentioning(root):
    """환경에 root(이 시험 하나의 tmp 길)가 든 내 프로세스의 pid들 — 시험 하나가 띄운 것(감시·가짜 claude·남은 sleep)만 겨눈다."""
    skip, needle, mine = _ancestors(), str(root).encode(), os.getuid()
    found = []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in skip:
            continue
        try:
            if os.stat("/proc/" + d).st_uid != mine:
                continue
            with open("/proc/%s/environ" % d, "rb") as f:
                if needle in f.read():
                    found.append(int(d))
        except OSError:
            continue
    return found


def reap_tree(root):
    """TERM → 잠깐 기다림 → 남은 것만 KILL. 늘 pid로만."""
    for sig, wait in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 2.0)):
        pids = pids_mentioning(root)
        for pid in pids:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        end = time.time() + wait
        while pids and time.time() < end:
            time.sleep(0.1)
            pids = pids_mentioning(root)
        if not pids:
            return


@pytest.fixture(autouse=True)
def _no_orphans(tmp_path):
    yield
    reap_tree(tmp_path)


def end_proc(p):
    """start_new_session으로 띄운 p를 끝낸다: 그룹에 TERM → 기다림 → 남았으면 KILL. 나머지(가짜 claude 따위)는 _no_orphans가 pid로 거둔다."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if p.poll() is not None:
            break
        try:
            os.killpg(p.pid, sig)
        except OSError:
            pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    if p.stdout:
        p.stdout.close()


def seed_ledger(S, text, name="stage.cost"):
    """장부와 그 미러(out-done)를 같은 글로 둔다 — 시작할 때 둘이 같아야 한다."""
    (S / "out").mkdir(parents=True, exist_ok=True)
    (S / "out-done").mkdir(parents=True, exist_ok=True)
    (S / "out" / name).write_text(text)
    (S / "out-done" / (name + ".mirror")).write_text(text)


# ---------- 인자·앞 검사: 진짜 무대에 닿지 않는다 ----------

@pytest.fixture
def roots(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    yield home, tmp_path / "S", tmp_path / "X"
    unseal_tree(tmp_path)


def env_of(S, X, **kw):
    return {"STAGE_S": str(S), "STAGE_X": str(X), **kw}


@pytest.mark.parametrize("args", [
    [], ["r01"], ["r01", "c1"], ["r1", "c1", "p"], ["r99x", "c1", "p"], ["q01", "c1", "p"], ["R01", "c1", "p"],
    ["r01", "zz", "p"], ["r01", "c1", "r"], ["r01", "c1", "p", "extra"], ["unseal", "x"], ["kitsha", "a", "b"],
])
def test_bad_args_exit_9_and_nothing_made(roots, args):
    home, S, X = roots
    rc, out = sh(args, home, env_of(S, X))
    assert rc == 9, out
    assert not S.exists() and not X.exists()


@pytest.mark.parametrize("name", [".devkit", ".devkit-guard-off"])
def test_home_devkit_exit_8_before_order_and_mkdir(roots, name):
    home, S, X = roots
    (home / name).mkdir()
    rc, out = sh(["r01", "c1", "p"], home, env_of(S, X))
    assert rc == 8, out
    rc, out = sh(["r01", "b1", "p"], home, env_of(S, X))  # 차례에 없는 짝이어도 8이 먼저
    assert rc == 8, out
    assert not S.exists() and not X.exists()


def test_order_pair_not_in_table_exit_9_without_touching_roots(roots):
    home, S, X = roots
    rc, out = sh(["r01", "b1", "p"], home, env_of(S, X))
    assert rc == 9, out
    assert "차례" in out
    assert not S.exists() and not X.exists()
    rc, out = sh(["r01", "c1", "q"], home, env_of(S, X))  # 팔을 바꾼 짝
    assert rc == 9, out
    assert not S.exists() and not X.exists()


def test_bash_syntax_ok():
    for f in (SH, LK):
        p = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr


def test_called_only_as_bash_never_by_exec_bit():
    # drvfs(/mnt/e)는 실행 비트를 구분하지 못한다 — 비트 대신 「늘 bash <파일>로 부른다」를 머리 글에 적고, 이 쪽에서 부르는 법도 그렇게 본다
    for f, call in ((SH, "bash stage.sh"), (LK, "bash stage-locked.sh")):
        head = "\n".join(f.read_text(encoding="utf-8").split("\n")[:6])
        assert f.read_text(encoding="utf-8").startswith("#!/bin/bash")            # 셔뱅이 있어도
        assert "부르는 꼴" in head and call in head and "실행 비트" in head, f
    for ln in code().split("\n"):
        if ln.lstrip().startswith("#"):
            continue
        if re.search(r"stage\.py|stage-walk\.py", ln):
            assert "python3 -I -B" in ln, ln


# ---------- 정적 ----------

def test_static_claude_lines_and_flags():
    t = code()
    assert len(re.findall(r'claude -p "\$PROMPT" --session-id "\$SID" "\$\{PD\[@\]\}"', t)) == 1
    assert len(re.findall(r'claude -p "\$REPLY" --resume "\$SID" "\$\{PD\[@\]\}"', t)) == 1
    assert len(re.findall(r"^\s*(?!#).*\bclaude -p ", t, re.M)) == 2
    for w in ("--model sonnet", "--setting-sources project", "--include-hook-events", "timeout 2400",
              "env -u TMUX -u TMUX_PANE", "--output-format stream-json --verbose",
              '--allowedTools "%s"' % TOOLS9, '--tools "%s"' % TOOLS9, "--strict-mcp-config", "--max-budget-usd"):
        assert t.count(w) == 2, w
    assert "--no-session-persistence" not in t


def test_static_mcp_and_tool_locks():
    t = code()
    ls = lines()
    cenv = [ln for ln in ls if ln.startswith("CENV=(")]
    assert len(cenv) == 1 and "ENABLE_CLAUDEAI_MCP_SERVERS=false" in cenv[0] and "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1" in cenv[0]
    assert live(t).count("ENABLE_CLAUDEAI_MCP_SERVERS") == 1 and live(t).count("CLAUDE_CODE_DISABLE_AUTO_MEMORY") == 1
    assert "--mcp-config" not in t.replace("--strict-mcp-config", "")
    allowed = re.findall(r'--allowedTools "([^"]*)"', t)
    tools = re.findall(r'--tools "([^"]*)"', t)
    assert allowed == tools == [TOOLS9, TOOLS9]
    init_tools = json.loads((M / "stage" / "tasks.json").read_text(encoding="utf-8"))["init_tools"]
    assert set(tools[0].split(",")) <= set(init_tools) and len(init_tools) == 10 and "Task" in init_tools
    # 두 호출 모두: --allowedTools 줄 → 바로 다음 줄 --tools → --strict-mcp-config → --disallowedTools
    idx = [i for i, ln in enumerate(ls) if ln.lstrip().startswith("--allowedTools")]
    assert len(idx) == 2
    for i in idx:
        assert ls[i + 1].strip() == '--tools "%s" \\' % TOOLS9, ls[i + 1]
        assert ls[i + 2].strip() == "--strict-mcp-config \\", ls[i + 2]
        assert ls[i + 3].lstrip().startswith("--disallowedTools"), ls[i + 3]
        assert ls[i + 1].startswith("  --tools") and ls[i + 2].startswith("  --strict-mcp-config")


def test_static_dis0_has_the_eleven_new_words():
    ls = lines()
    dis0 = [ln for ln in ls if ln.startswith("DIS0=(")]
    assert len(dis0) == 1
    got = re.findall(r'"Bash\((?:[^"\\]|\\.)*\)"', dis0[0])
    for w in DIS_NEW11:
        assert '"%s"' % w in got, w
        assert code().count('"%s"' % w) == 1, w
    assert len(got) == 31


def test_static_claude_vars_are_unset_except_two_and_env_order():
    t = code()
    ls = lines()
    assert any(ln.startswith("UNCL=(") for ln in ls)
    assert "compgen -e | command grep '^CLAUDE'" in t
    block = t[t.index("UNCL=("):t.index("UNCL=(") + 400]
    assert "CLAUDE_CODE_OAUTH_TOKEN" in block and "CLAUDE_CONFIG_DIR" in block
    envl = [ln for ln in ls if ln.startswith("timeout 2400 env") or ln.startswith("  timeout 2400 env")]
    assert len(envl) == 2
    for ln in envl:
        assert re.search(r'"\$\{UNST\[@\]\}" "\$\{UNCL\[@\]\}" PATH=', ln), ln
        assert ln.index('"${UNCL[@]}"') < ln.index('"${CENV[@]}"')
    # 값은 어디에도 찍지 않는다: UNCL 만드는 자리에 echo·printf·printenv가 없다
    seg = t[t.index("UNCL=("):t.index("UNCL=(") + 400].split("\n\n")[0]
    assert not re.search(r"\b(echo|printf|printenv)\b", seg), seg


def test_static_sched_and_sess_extra_are_read_only():
    t = code()
    assert "schedsha()" in t and "SCHED0=$(schedsha)" in t
    body = t[t.index("schedsha() {"):]
    body = body[:body.index("\n}\n")]
    assert "timeout 10 crontab -l" in body and "timeout 10 systemctl --user list-timers --all --no-legend --plain" in body
    assert "crontab -r" not in t and "crontab -e" not in t and "systemctl --user start" not in t and "systemctl --user stop" not in t
    sx = t[t.index("sess_extra_count() {"):]
    sx = sx[:sx.index("\n}\n")]
    assert 'for f in "$HOME/.claude/projects/$name"/*.jsonl "$HOME/.claude/projects/$name-"*/*.jsonl' in sx and "name=${R//[^A-Za-z0-9]/-}" in sx and "find" not in sx and "rm " not in sx and "mv " not in sx
    assert "sched=%s" in t and "sess_extra=%s" in t


def test_static_count_sched_sess_sets_both_only_after_counting():
    t = code()
    body = t[t.index("count_sched_sess() {"):]
    body = body[:body.index("\n}\n")]
    assigns = [i for i, ln in enumerate(body.split("\n")) if re.match(r"\s*(SCHED|SESSX)=", ln)]
    assert len(assigns) == 1, body                                    # 둘 다 한 줄에서, 셈이 다 끝난 뒤 한 번에 넣는다
    last = body.split("\n")[assigns[0]]
    assert re.fullmatch(r"\s*SCHED=\$\w+; SESSX=\$\w+", last), last
    assert all("schedsha" not in ln and "sess_extra_count" not in ln for ln in body.split("\n")[assigns[0]:])
    assert "SCHED=same" not in body and "SCHED=changed" not in body


def test_static_disallowed_words_21_and_added():
    src = (M / "intake.sh").read_text(encoding="utf-8")
    line = [ln for ln in src.split("\n") if "--disallowedTools" in ln][0]
    words = re.findall(r'"Bash\((?:[^"\\]|\\.)*\)"', line)
    assert len(words) == 21
    t = code()
    for w in words:
        assert w in t, w
    assert t.count('"Bash(npm *)"') == 1
    ls = lines()
    cases = {ln.strip()[:2]: ln for ln in ls if re.match(r"^\s*[abc]\) DIS=", ln)}
    assert set(cases) == {"a)", "b)", "c)"}
    assert "DIS_NPM" not in cases["a)"] and "DIS_NPM" in cases["b)"] and "DIS_NPM" in cases["c)"]
    for w in ('"Bash(*zzz-devkit-stage/sealed*)"', '"Bash(*zzz-devkit-stage/src-*)"', '"Bash(*zzz-devkit-stage/bases*)"',
              '"Bash(*zzz-devkit-stage/walkkit*)"', '"Bash(*devkit/docs*)"', '"Bash(gh *)"', '"Bash(* gh *)"',
              '"Bash(*pip *)"', '"Bash(*pip3 *)"', '"Bash(*uv *)"', '"Bash(*conda *)"', '"Bash(*curl*)"', '"Bash(*wget*)"',
              '"Bash(*git fetch*)"', '"Bash(*git clone*)"', '"Bash(*git pull*)"'):
        assert t.count(w) == 1, w
    # b의 넷은 b·c 모두 · c만의 다섯은 DIS_C에서만
    assert "DIS_B" in cases["b)"] and "DIS_C" in cases["c)"] and "DIS_B" not in cases["a)"] and "DIS_C" not in cases["a)"]


def test_static_pd_only_in_p_branch_and_pythonpath_only_in_c():
    ls = lines()
    pd = [ln for ln in ls if "PD=(" in ln]
    assert len(pd) == 2
    assert [ln for ln in pd if "--plugin-dir" in ln] == ['  p) PD=(--plugin-dir "$X/env/kit") ;;']
    assert [ln.strip() for ln in pd if "--plugin-dir" not in ln] == ["q) PD=() ;;"]
    assert code().count("--plugin-dir") == 1
    py = [ln for ln in ls if 'PYTHONPATH="$W"' in ln]
    assert len(py) == 1 and re.match(r"^\s*c\) ", py[0])


def test_static_money_before_first_claude_and_order_before_memok_before_mkdir():
    claude = first_line(r"\bclaude -p ")
    order = first_line(r'stage\.py" order')
    memok = first_line(r"^memok t1")
    mk = first_line(r'^mkdir "\$R"')
    over12 = first_line(r"STAGE_OVER12")
    stop4 = first_line(r"돈 멈춤")
    ledger = first_line(r"^if spent=\$\(sumof\)")
    devkit = first_line(r"\.devkit-guard-off")
    ports = first_line(r"ss -ltnH")
    fp = first_line(r"\.venv0")
    for v in (claude, order, memok, mk, over12, stop4, ledger, devkit, ports, fp):
        assert v is not None
    assert devkit < order < memok < mk < claude
    assert memok < ledger < over12 < ports < fp < mk
    assert stop4 < claude and over12 < claude
    assert code().count("STAGE_PAST_ALERT") == 0


def test_static_no_forbidden_commands():
    t = live(code())
    for w in ("pkill", "killall", "tmux", "pgrep", "sed -n", "taskkill", "rm -r", "rm -rf", "git clean", "checkout ."):
        assert w not in t, w
    assert not re.search(r"^\s*(source|\.)\s", t, re.M)
    assert "intake.sh" not in t


def test_static_reads_texts_via_stage_py_and_has_env():
    t = code()
    assert 'stage.py" text' in t or '"$PY" text' in t
    for w in ('GH_TOKEN=', 'GIT_CONFIG_GLOBAL="$R/gitconfig"', 'UV_PYTHON_DOWNLOADS=never', "PIP_ONLY_BINARY=:all:",
              "npm_config_ignore_scripts=true", 'TMPDIR="$R/tmp"', 'UV_CACHE_DIR="$R/uv"', 'GH_CONFIG_DIR="$R/gh"',
              'npm_config_userconfig="$R/npmrc"', "DJANGO_TEST_PROCESSES=2", "PIP_REQUIRE_VIRTUALENV=1", "PIP_USER=0"):
        assert w in t, w
    assert "chmod 000" in t and 'chmod "$(safemode "$m")"' in t and "echo 700" in t       # 풀 때는 봉하기 전 모드(검사한 뒤, 아니면 700)
    assert re.search(r"^trap .*unseal", t, re.M)
    for w in ("exit 143", "exit 15", "exit 4", "exit 3", "exit 9", "exit 8", "EX=16", "EX=10", "EX=11", "EX=14", "EX=6", "EX=13", "EX=12", "EX=5", 'exit "$EX"'):
        assert w in t, w


def test_locked_static():
    t = LK.read_text(encoding="utf-8")
    ls = t.split("\n")
    assert ls.count("L=${STAGE_S:-/home/ssmge/zzz-devkit-stage}/run.lock") == 1
    assert "export STAGE_LOCKED=" in t and "flock -n" in t
    src = (M / "locked.sh").read_text(encoding="utf-8")
    for w in ("trap on_sig TERM INT HUP", "exit 143", "exit 7", "exit 9", 'mkdir "$L"'):
        assert w in t, w
    assert "trap '[ \"$KEEP\" = 1 ] || rmdir \"$L\"' EXIT" in t
    assert src.count("trap on_sig TERM INT HUP") == 1
    assert "pkill" not in t and "killall" not in t and "pgrep" not in t


def test_locked_no_args_exit_9_real(tmp_path):
    rc, out = sh([], tmp_path, {"STAGE_S": str(tmp_path / "S")}, script=LK)       # 진짜 뿌리에 닿지 않게 가짜 STAGE_S
    assert rc == 9, out
    assert "인자" in out


def locked_copy(tmp_path):
    S = tmp_path / "S"
    S.mkdir(exist_ok=True)
    return LK, S / "run.lock", {"STAGE_S": str(S)}


def test_locked_copy_runs_exit_codes_and_lock(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    rc, _ = sh(["true"], tmp_path, env, script=f)
    assert rc == 0 and not lock.exists()
    rc, _ = sh(["bash", "-c", "exit 5"], tmp_path, env, script=f)
    assert rc == 5 and not lock.exists()
    lock.mkdir()
    rc, out = sh(["true"], tmp_path, env, script=f)
    assert rc == 7 and lock.exists(), out


def test_locked_copy_exports_marker_and_holds_flock(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    rc, out = sh(["bash", "-c", 'echo "[$STAGE_LOCKED]"; flock -n 9 && echo got || echo held'], tmp_path, env, script=f)
    assert rc == 0 and "[%s]" % lock in out, out
    assert "held" in out or "got" in out
    # 도는 동안 따로 부른 seal·unseal은 flock을 못 잡아 9
    marker = tmp_path / "go"
    cmd = "S=%s; bash %s seal; echo seal=$? > %s" % (shlex.quote(env["STAGE_S"]), shlex.quote(str(SH)), shlex.quote(str(marker)))
    rc, out = sh(["bash", "-c", cmd], tmp_path, env, script=f)
    assert "seal=9" in marker.read_text(), out
    cmd = "bash %s unseal; echo unseal=$? > %s" % (shlex.quote(str(SH)), shlex.quote(str(marker)))
    rc, out = sh(["bash", "-c", cmd], tmp_path, env, script=f)
    assert "unseal=9" in marker.read_text(), out


def test_locked_copy_signal_keeps_lock_143(tmp_path):
    f, lock, lenv = locked_copy(tmp_path)
    marker = tmp_path / "pid"
    p = subprocess.Popen(["bash", str(f), "bash", "-c", "echo $$ > %s; exec sleep 60" % marker],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
                         env={"PATH": BASE_PATH, "HOME": str(tmp_path), **lenv})
    try:
        end = time.time() + 20
        while not marker.exists() and time.time() < end:
            time.sleep(0.1)
        assert marker.exists()
        child = int(marker.read_text().strip())
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=20)
        said = p.stdout.read()
        assert rc == 143
        assert lock.exists()
        assert "장부에 상한 줄이 적혔는지 확인하고" in said and "돈을 손으로 적고" not in said, said
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        end_proc(p)
        if marker.exists():
            try:
                os.kill(int(marker.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


# ---------- seal · unseal · kitsha 따로 부르기 ----------

def test_seal_unseal_standalone_only_listed_dirs(roots):
    home, S, X = roots
    for n in ("sealed", "src-b", "bases", "try-impl", "out", "walkkit", "walk", "out-done", "done"):
        (S / n).mkdir(parents=True)
    (S / "run.lock").mkdir()
    env = env_of(S, X)
    rc, out = sh(["seal"], home, env)
    assert rc == 0, out
    mode = lambda n: oct((S / n).stat().st_mode & 0o777)
    sealed = ("sealed", "src-b", "bases", "try-impl", "walkkit", "walk", "out-done", "done")
    assert [mode(n) for n in sealed] == ["0o0"] * len(sealed)
    assert mode("out") == "0o755" or mode("out") == "0o775"
    assert mode("run.lock") != "0o0"
    rc, out = sh(["unseal"], home, env)
    assert rc == 0, out
    assert [mode(n) for n in sealed] == ["0o755"] * len(sealed)         # 봉하기 전 모드로 돌아간다


def test_standalone_seal_unseal_refuse_while_flock_held_exit_9(roots):
    home, S, X = roots
    (S / "sealed").mkdir(parents=True)
    (S / "run.lock").mkdir()
    env = env_of(S, X)
    holder = subprocess.Popen(["bash", "-c", "exec 9< %s; flock -n 9 && echo ok && exec sleep 30" % shlex.quote(str(S / "run.lock"))],
                              stdout=subprocess.PIPE, text=True, start_new_session=True)
    try:
        assert holder.stdout.readline().strip() == "ok"
        for sub in ("seal", "unseal"):
            rc, out = sh([sub], home, env)
            assert rc == 9 and "도는 실행" in out, (sub, out)
        assert oct((S / "sealed").stat().st_mode & 0o777) != "0o0"
    finally:
        end_proc(holder)
    assert sh(["seal"], home, env)[0] == 0                                # 잡은 쪽이 없으면(잠금 폴더만 남음) 된다
    assert sh(["unseal"], home, env)[0] == 0


def test_unseal_modes_file_accepts_only_three_octal_digits_and_never_000_or_world_writable(roots):
    home, S, X = roots
    names = ("sealed", "src-b", "src-c", "bases", "walkkit", "walk", "venv-b", "venv-c")
    for n in names:
        (S / n).mkdir(parents=True)
        (S / n).chmod(0)
    (S / "out").mkdir()
    (S / "out" / "seal.modes").write_text("sealed 750\nsrc-b 000\nsrc-c 777\nbases 7500\nwalkkit 7x0\nwalk 722\nvenv-b 755\n", encoding="utf-8")
    assert sh(["unseal"], home, env_of(S, X))[0] == 0
    m = lambda n: oct((S / n).stat().st_mode & 0o777)
    assert [m(n) for n in names] == ["0o750", "0o700", "0o700", "0o700", "0o700", "0o700", "0o755", "0o700"]


def test_seal_records_original_modes_and_unseal_restores_them(roots):
    home, S, X = roots
    for n, m in (("sealed", 0o750), ("bases", 0o700), ("walk", 0o711)):
        (S / n).mkdir(parents=True)
        (S / n).chmod(m)
    env = env_of(S, X)
    mode = lambda n: oct((S / n).stat().st_mode & 0o777)
    assert sh(["seal"], home, env)[0] == 0
    rec = dict(ln.split() for ln in (S / "out" / "seal.modes").read_text().split("\n") if ln)
    assert rec == {"sealed": "750", "bases": "700", "walk": "711"}
    assert sh(["seal"], home, env)[0] == 0                              # 이미 000인 걸 또 봉해도 기록이 000으로 덮이지 않는다
    assert dict(ln.split() for ln in (S / "out" / "seal.modes").read_text().split("\n") if ln)["sealed"] == "750"
    assert sh(["unseal"], home, env)[0] == 0
    assert [mode(n) for n in ("sealed", "bases", "walk")] == ["0o750", "0o700", "0o711"]


def test_unseal_without_modes_file_gives_700(roots):
    home, S, X = roots
    for n in ("sealed", "walk"):
        (S / n).mkdir(parents=True)
        (S / n).chmod(0)
    assert sh(["unseal"], home, env_of(S, X))[0] == 0
    assert [oct((S / n).stat().st_mode & 0o777) for n in ("sealed", "walk")] == ["0o700", "0o700"]


def test_kitsha_subcommand(tmp_path):
    d = tmp_path / "k"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("one")
    (d / "sub" / "b.txt").write_text("two")
    home = tmp_path / "h"
    home.mkdir()
    fake = {"STAGE_S": str(tmp_path / "S"), "STAGE_X": str(tmp_path / "X")}
    rc1, o1 = sh(["kitsha", str(d)], home, fake)
    assert rc1 == 0 and re.fullmatch(r"[0-9a-f]{64}\n?", o1), o1
    (d / "a.txt").write_text("changed")
    rc2, o2 = sh(["kitsha", str(d)], home, fake)
    assert rc2 == 0 and o2 != o1
    rc3, o3 = sh(["kitsha", str(tmp_path / "none")], home, fake)
    assert rc3 == 0 and o3.strip() == "-"


# ---------- 가짜 claude로 틀을 한 바퀴 (진짜 claude·진짜 무대 없음) ----------

FAKE = r'''#!/bin/bash
sid=; mode=
while [ $# -gt 0 ]; do
  case "$1" in
    --session-id) sid=$2; mode=t1; shift ;;
    --resume) sid=$2; mode=t2; shift ;;
    --plugin-dir) echo "$2" > "$PWD/plugindir.$mode" ;;
    --tools) echo "$2" > "$PWD/tools.$mode"; shift ;;
    --strict-mcp-config) : > "$PWD/strict.$mode" ;;
  esac
  shift
done
echo "$mode" >> "$PWD/modes.txt"
printenv PATH TMPDIR GH_TOKEN GIT_CONFIG_GLOBAL PIP_ONLY_BINARY npm_config_ignore_scripts UV_CACHE_DIR > "$PWD/env.$mode"
printenv ENABLE_CLAUDEAI_MCP_SERVERS > "$PWD/mcpenv.$mode"
printenv CLAUDE_CODE_DISABLE_AUTO_MEMORY > "$PWD/automem.$mode"
env | cut -d= -f1 | grep '^CLAUDE' | sort > "$PWD/claudenames.$mode"
if [ -n "${FAKE_SESS-}" ]; then
  sd="$HOME/.claude/projects/$(printf '%s' "$PWD" | sed 's/[^A-Za-z0-9]/-/g')"; mkdir -p "$sd"; : > "$sd/$sid.jsonl"
  for i in $(seq 1 "$FAKE_SESS"); do : > "$sd/extra$i.jsonl"; done
fi
for it in ${FAKE_SESS_FILES-}; do
  d=${it%%:*}; nm=${it#*:}
  d=${d//%R%/$(printf '%s' "${PWD%/w}" | sed 's/[^A-Za-z0-9]/-/g')}
  mkdir -p "$HOME/.claude/projects/$d"; : > "$HOME/.claude/projects/$d/$nm.jsonl"
done
osid=$sid; [ "$mode" = t2 ] && [ -n "${FAKE_SID2-}" ] && osid=$FAKE_SID2
[ -n "${FAKE_CRON-}" ] && [ "$mode" = t1 ] && echo "* * * * * x" >> "$FAKE_CRONFILE"
stat -c %a "$FAKE_S/sealed" > "$PWD/sealmode.$mode"
stat -c %z "$FAKE_S/sealed" > "$PWD/ctime.$mode"
env | grep '^STAGE_' > "$PWD/stageenv.$mode"
tamper() {
  case "$1" in
    ledger) echo "0.01 forged" >> "$FAKE_S/out/stage.cost" ;;
    xledger) echo "0.01 forged" >> "$FAKE_S/out/stage-x.cost" ;;
    modes) echo "sealed 777" >> "$FAKE_S/out/seal.modes" ;;
    chmod) chmod 700 "$FAKE_S/sealed" ;;
    chmodtry) chmod 755 "$FAKE_S/try-impl" ;;
    rechmod) chmod 755 "$FAKE_S/sealed" && chmod 000 "$FAKE_S/sealed" ;;
    chmodledger) chmod 666 "$FAKE_S/out/stage.cost" ;;
  esac
}
[ -n "${FAKE_TAMP-}" ] && [ "${FAKE_TAMP_ON-t1}" = "$mode" ] && tamper "$FAKE_TAMP"
[ -n "$FAKE_MARK" ] && echo "$$" > "$FAKE_MARK"
if [ "$mode" = t1 ]; then
  case "${FAKE_SPAWN-}" in t1|both)
    if [ -n "${FAKE_SETSID-}" ]; then setsid sleep 300 < /dev/null > /dev/null 2>&1 & else sleep 300 < /dev/null > /dev/null 2>&1 & fi
    echo $! >> "$FAKE_PIDS" ;; esac
  case "${FAKE_COPYLOOP-}" in in|out)
    GOT="$PWD/got"; mkdir -p "$GOT"; export GOT
    LOOP='echo $$ >> "$FAKE_PIDS"; while :; do cp -r "$FAKE_S/sealed/." "$GOT/" 2>/dev/null; done'
    if [ "$FAKE_COPYLOOP" = out ]; then ( cd / && setsid bash -c "$LOOP" < /dev/null > /dev/null 2>&1 & )
    else setsid bash -c "$LOOP" < /dev/null > /dev/null 2>&1 & fi
    sleep 0.3 ;; esac
  if [ -n "${FAKE_ENVMARK-}" ]; then ( cd / && { setsid sleep 300 < /dev/null > /dev/null 2>&1 & echo $! >> "$FAKE_PIDS"; } ); fi
  [ -n "${FAKE_LOW-}" ] && : > "$FAKE_LOW"
  [ -n "${FAKE_HOMEDK-}" ] && mkdir -p "$HOME/.devkit"
  [ -n "${FAKE_DOT-}" ] && echo x > "$HOME/.npmrc"
  [ -n "${FAKE_KIT-}" ] && echo x >> "$FAKE_X/env/kit/a.txt"
  [ -n "${FAKE_BADLEDGER-}" ] && echo "garbage line" >> "$FAKE_S/out/stage.cost"
  if [ -n "${FAKE_LOWMEM-}" ]; then
    for i in $(seq 1 100); do
      for wf in "$FAKE_S"/out/*.watch; do [ -e "$wf" ] && [ "$(wc -l < "$wf")" -ge 2 ] && break 2; done
      sleep 0.1
    done
    : > "$FAKE_LOWMEM"
  fi
  cost=${FAKE_COST1-0.40}; sub=${FAKE_SUB1-success}; rc=${FAKE_RC1-0}
else
  case "${FAKE_SPAWN-}" in both) sleep 300 < /dev/null > /dev/null 2>&1 & echo $! >> "$FAKE_PIDS" ;; esac
  cost=${FAKE_CUM2-0.90}; sub=success; rc=${FAKE_RC2-0}
fi
echo "note $mode" >> "$PWD/notes.txt"
[ -n "${FAKE_HANG-}" ] && exec sleep 60
echo "{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"$osid\"}"
echo "{\"type\":\"result\",\"subtype\":\"$sub\",\"session_id\":\"$sid\",\"total_cost_usd\":$cost,\"is_error\":false}"
exit $rc
'''


@pytest.fixture
def world(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    S = tmp_path / "S"
    X = tmp_path / "X"
    for n in ("sealed", "src-b", "src-c", "bases", "walkkit", "venv-b", "venv-c", "try-impl"):
        (S / n).mkdir(parents=True)
        (S / n).chmod(0o700)
    (X / "env" / "kit" / ".claude-plugin").mkdir(parents=True)
    (X / "env" / "kit" / ".claude-plugin" / "plugin.json").write_text("{}")
    (X / "env" / "kit" / "a.txt").write_text("kit")
    b = tmp_path / "bin"
    b.mkdir()
    (b / "powershell.exe").write_text("#!/bin/bash\necho 20\n")
    (b / "fake-claude").write_text(FAKE)
    for n in ("powershell.exe", "fake-claude"):
        (b / n).chmod(0o755)
    pids = tmp_path / "pids"
    pids.write_text("")
    (S / "run.lock").mkdir()
    env = env_of(S, X, STAGE_CLAUDE=str(b / "fake-claude"), FAKE_PIDS=str(pids), STAGE_CUM="1", STAGE_LOCKED=str(S / "run.lock"),
                 FAKE_S=str(S), FAKE_X=str(X))
    w = {"home": home, "S": S, "X": X, "bin": b, "env": env, "pids": pids, "path": BASE_PATH + ":" + str(b)}
    yield w
    unseal_tree(tmp_path)
    for ln in pids.read_text().split():
        try:
            os.kill(int(ln), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass


def run_flow(w, run, task, arm, extra=None, timeout=240):
    env = {**w["env"], **(extra or {})}
    p = subprocess.run(["bash", str(SH), run, task, arm], capture_output=True, text=True, timeout=timeout,
                       env={"PATH": w["path"], "HOME": str(w["home"]), **env})
    if p.returncode == 3:
        pytest.skip("메모리 검사가 멈춤(이 기계의 지금 상태): " + (p.stdout + p.stderr)[-200:])
    return p.returncode, p.stdout + p.stderr


def done_dir(w, run):
    d = w["S"] / "done" / run / "w"
    assert d.is_dir(), list((w["S"]).iterdir())
    return d


def check_of(w, run):
    f = w["S"] / "out-done" / (run + ".check")
    assert f.is_file(), sorted(p.name for p in (w["S"] / "out-done").iterdir()) if (w["S"] / "out-done").exists() else "no out-done"
    return dict(ln.split("=", 1) for ln in f.read_text().split("\n") if "=" in ln)


def ledger(w, name="stage.cost"):
    f = w["S"] / "out" / name
    return f.read_text().split("\n")[:-1] if f.exists() else []


def modes(w):
    return {n: oct((w["S"] / n).stat().st_mode & 0o777) for n in ("sealed", "src-b", "bases", "walkkit", "try-impl")}


def test_flow_happy_path_p(world):
    w = world
    rc, out = run_flow(w, "r09", "a2", "p")
    assert rc == 0, out
    assert ledger(w) == ["0.40 stage.r09.t1", "0.50 stage.r09.t2"]
    chk = check_of(w, "r09")
    for k in ("run", "task", "arm", "own", "rc1", "rc2", "secs1", "secs2", "secs", "t2", "rc", "committed", "cum", "base",
              "end_commit", "exit", "kitsha", "tests", "lint", "fmt"):
        assert k in chk, k
    assert (chk["run"], chk["task"], chk["arm"], chk["t2"], chk["exit"], chk["kitsha"], chk["cum"], chk["committed"]) == \
        ("r09", "a2", "p", "sent", "0", "same", "1", "ok")
    assert re.fullmatch(r"[0-9a-z]{8}", chk["own"])
    d = done_dir(w, "r09")
    log = subprocess.run(["git", "-C", str(d), "log", "--format=%H"], capture_output=True, text=True,
                         env={"PATH": BASE_PATH, "HOME": str(w["home"]), "GIT_CONFIG_GLOBAL": "/dev/null"}).stdout.split()
    assert len(log) == 2 and log[-1] == chk["base"] and log[0] == chk["end_commit"]
    # 봉한 폴더는 턴 동안 000이었고 끝나면 700
    assert (d / "sealmode.t1").read_text().strip() == "0" and (d / "sealmode.t2").read_text().strip() == "0"
    assert set(modes(w).values()) == {"0o700"}
    # 환경
    e1 = (d / "env.t1").read_text().split("\n")
    assert "/mnt/" not in e1[0]
    assert e1[1].endswith("/tmp") and str(w["X"] / "run" / chk["own"]) in e1[1]
    assert e1[2] == "" and e1[3].endswith("gitconfig") and e1[4] == ":all:" and e1[5] == "true"
    assert (d / "plugindir.t1").read_text().strip() == str(w["X"] / "env" / "kit")
    assert (d / "plugindir.t2").read_text().strip() == str(w["X"] / "env" / "kit")
    # 끝난 실행은 옮겨졌다 · 장부는 남음
    assert not list((w["S"] / "out").glob("r09.*"))
    assert (w["S"] / "out-done" / "r09.t1.jsonl").exists() and (w["S"] / "out-done" / "r09.json").exists()
    assert not (w["X"] / "run" / chk["own"]).exists()
    names = (w["S"] / "out-done" / "names.tsv").read_text().split("\n")
    assert "%s\tr09" % chk["own"] in names
    j = json.loads((w["S"] / "out-done" / "r09.json").read_text())
    assert j["run"] == "r09" and j["task"] == "a2" and j["arm"] == "p" and j["cost1"] == "0.40" and j["cost2"] == "0.50"
    assert (w["S"] / "out" / "r09.watch").exists() or (w["S"] / "out-done" / "r09.watch").exists()


def test_flow_q_arm_has_no_plugin_dir(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    d = done_dir(w, "r10")
    assert not (d / "plugindir.t1").exists() and not (d / "plugindir.t2").exists()


def test_flow_run_twice_exit_9(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 9, out
    assert len(ledger(w)) == 2


def test_flow_p_needs_kit_copy(world):
    w = world
    shutil.rmtree(w["X"] / "env" / "kit")
    rc, out = run_flow(w, "r09", "a2", "p")
    assert rc == 9, out
    assert ledger(w) == []


def test_flow_money_alarm_and_stop(world):
    w = world
    (w["S"] / "out").mkdir()
    seed_ledger(w["S"], "12.00 stage.old\n")
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 4, out
    assert not (w["X"] / "run").exists() or not list((w["X"] / "run").iterdir())
    rc, out = run_flow(w, "r10", "a2", "q", {"STAGE_OVER12": "yes"})
    assert rc == 12, out                                  # 시작은 허락됐고(첫 턴 0.40), 합 12.40 + 2.50이 14.50을 넘어 둘째 턴만 안 간다
    assert check_of(w, "r10")["t2"] == "skip:money" and ledger(w) == ["12.00 stage.old", "0.40 stage.r10.t1"]
    seed_ledger(w["S"], "12.60 stage.old\n")
    rc, out = run_flow(w, "r09", "a2", "p", {"STAGE_OVER12": "yes"})
    assert rc == 4, out  # 12.60 + 2.50 > 15.00


def test_flow_money_second_turn_skipped_exit_12(world):
    w = world
    (w["S"] / "out").mkdir()
    seed_ledger(w["S"], "11.90 stage.old\n")
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_COST1": "1.50"}, timeout=240)
    assert rc == 12, out
    chk = check_of(w, "r10")
    assert chk["t2"] == "skip:money" and chk["exit"] == "12"
    assert ledger(w) == ["11.90 stage.old", "1.50 stage.r10.t1"]


def test_flow_budget_stop_skips_turn_two(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SUB1": "error_max_budget_usd", "FAKE_RC1": "1"})
    assert rc == 12, out
    chk = check_of(w, "r10")
    assert chk["t2"] in ("skip:budget", "skip:rc") and chk["rc2"] == "-"


def test_flow_turn_two_rc_exit_5(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_RC2": "3"})
    assert rc == 5, out
    assert check_of(w, "r10")["rc"] == "3"


def test_flow_left_process_killed_by_pid_and_counted(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SPAWN": "t1"})
    assert rc == 0, out  # 첫 턴 뒤 남은 것은 끄고 둘째 턴을 보낸다(skip:left 없음)
    chk = check_of(w, "r10")
    assert chk["t2"] == "sent" and chk["left1"] == "1" and chk["left"] == "0"
    left1 = (w["S"] / "out-done" / "r10.left1").read_text()
    assert "sleep" in left1
    pid = int(w["pids"].read_text().split()[0])
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_flow_left_at_end_exit_11(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SPAWN": "both"})
    assert rc == 11, out
    chk = check_of(w, "r10")
    assert chk["left"] == "1" and chk["exit"] == "11"


def test_flow_home_devkit_exit_10(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_HOMEDK": "1"})
    assert rc == 10, out
    assert check_of(w, "r10")["t2"].startswith("skip:")


def test_flow_dotfile_change_exit_16(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_DOT": "1"})
    assert rc == 16, out
    assert check_of(w, "r10")["exit"] == "16"


def test_flow_kit_copy_changed_is_recorded_not_exit(world):
    w = world
    rc, out = run_flow(w, "r09", "a2", "p", {"FAKE_KIT": "1"})
    assert rc == 0, out
    assert check_of(w, "r09")["kitsha"] == "changed"


def test_flow_signal_records_turn_cap_unseals_and_143(world):
    w = world
    mark = w["S"].parent / "mark"
    env = {"PATH": w["path"], "HOME": str(w["home"]), **w["env"], "FAKE_HANG": "1", "FAKE_MARK": str(mark)}
    p = subprocess.Popen(["bash", str(SH), "r10", "a2", "q"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                         start_new_session=True)
    try:
        end = time.time() + 60
        while not mark.exists() and time.time() < end and p.poll() is None:
            time.sleep(0.1)
        if p.poll() == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert mark.exists(), "가짜 claude가 안 뜸"
        assert set(modes(w).values()) == {"0o0"}
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=60)
        out = p.stdout.read()
        assert rc == 143, out
        assert ledger(w) == ["2.50 stage.r10.t1"]
        assert set(modes(w).values()) == {"0o700"}
        # 신호로 끝난 실행도 끝난 실행처럼 옮겨진다: .check는 out-done에 · out에는 그 실행의 것이 안 남는다
        assert "exit=143" in (w["S"] / "out-done" / "r10.check").read_text()
        assert not list((w["S"] / "out").glob("r10.*"))
        assert (w["S"] / "done" / "r10" / "w").is_dir()
        assert not list((w["X"] / "run").iterdir())
    finally:
        end_proc(p)
        if mark.exists():
            try:
                os.kill(int(mark.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


def test_flow_signal_kills_leftover_processes_by_pid(world):
    w = world
    mark = w["S"].parent / "mark"
    env = {"PATH": w["path"], "HOME": str(w["home"]), **w["env"], "FAKE_HANG": "1", "FAKE_MARK": str(mark), "FAKE_SPAWN": "t1", "FAKE_SETSID": "1"}
    p = subprocess.Popen(["bash", str(SH), "r10", "a2", "q"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                         start_new_session=True)
    try:
        end = time.time() + 60
        while not mark.exists() and time.time() < end and p.poll() is None:
            time.sleep(0.1)
        if p.poll() == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert mark.exists()
        time.sleep(0.3)
        pid = int(w["pids"].read_text().split()[0])
        os.kill(pid, 0)                                   # 아직 살아 있다
        os.kill(p.pid, signal.SIGTERM)
        assert p.wait(timeout=60) == 143
        time.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert "sleep" in (w["S"] / "out-done" / "r10.left1").read_text()
        assert (w["S"] / "done" / "r10").is_dir()
    finally:
        end_proc(p)
        if mark.exists():
            try:
                os.kill(int(mark.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


def test_flow_low_flag_exit_143_second_turn_skipped_and_moved(world):
    w = world
    low = w["S"] / "out" / "r10.low"
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_LOW": str(low)})
    assert rc == 143, out
    chk = check_of(w, "r10")
    assert chk["exit"] == "143" and chk["t2"] == "skip:mem"
    assert not list((w["S"] / "out").glob("r10.*"))
    assert (w["S"] / "out-done" / "r10.low").exists()
    assert (w["S"] / "done" / "r10" / "w").is_dir()


def test_flow_rerun_needs_money_rerun_key_and_own_ledger(world, tmp_path):
    w = world
    cfgdir = tmp_path / "cfg"
    (cfgdir / "stage").mkdir(parents=True)
    for n in ("stage-prompts.txt", "stage-replies.txt"):
        shutil.copy(M / n, cfgdir / n)
    cfg = json.loads((M / "stage" / "tasks.json").read_text(encoding="utf-8"))
    cfg["rerun"] = [["x01", "a1", "q"]]
    tj = cfgdir / "stage" / "tasks.json"
    tj.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    rc, out = run_flow(w, "x01", "a1", "q", {"STAGE_TASKS": str(tj)})
    assert rc == 9, out
    assert not (w["S"] / "out").exists() or not list((w["S"] / "out").iterdir())
    cfg["money_rerun"] = {"need": "1.00", "alarm": "3.00", "stop": "4.00"}
    tj.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    rc, out = run_flow(w, "x01", "a1", "q", {"STAGE_TASKS": str(tj)})
    assert rc == 0, out
    assert ledger(w, "stage-x.cost") == ["0.40 stage.x01.t1", "0.50 stage.x01.t2"]
    assert ledger(w) == []
    seed_ledger(w["S"], "3.10 stage.old\n", "stage-x.cost")
    cfg["rerun"].append(["x02", "a1", "p"])
    tj.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    rc, out = run_flow(w, "x02", "a1", "p", {"STAGE_TASKS": str(tj)})
    assert rc == 4, out  # 알림 선 3.00을 넘음


def test_flow_port_and_venv_checks_for_b(world):
    w = world
    rc, out = run_flow(w, "r05", "b1", "p")
    if rc == 15:
        pytest.skip("이 기계에서 8083 또는 18300~18399가 지금 열려 있음")
    assert rc == 9, out  # 가상 환경 없음 — 앞 검사에서 멈춤, 사본 안 만듦
    assert not (w["X"] / "run").exists() or not list((w["X"] / "run").iterdir())
    assert ledger(w) == []


# ---------- 고침 1차: 장부 · 돈 선 · 남은 것 · 꾸러미 합 값 ----------

@pytest.mark.parametrize("content", ["abc\n", "0.40\n", "0.4 stage.x\n", "1.20 stage.ok\nnot-a-number stage.x\n", "1.20 stage.ok\n\n",
                                     "-1.00 stage.x\n", "1.2e1 stage.x\n", "1.20stage.x\n"])
def test_flow_broken_ledger_line_exit_4_and_nothing_made(world, content):
    w = world
    (w["S"] / "out").mkdir()
    seed_ledger(w["S"], content)
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 4, out
    assert not (w["X"] / "run").exists() or not list((w["X"] / "run").iterdir())
    assert (w["S"] / "out" / "stage.cost").read_text() == content


def test_flow_unreadable_ledger_exit_4(world):
    w = world
    seed_ledger(w["S"], "1.00 stage.old\n")
    f = w["S"] / "out" / "stage.cost"
    f.chmod(0)
    try:
        if os.access(f, os.R_OK):
            pytest.skip("이 계정은 000 파일도 읽을 수 있음")
        rc, out = run_flow(w, "r10", "a2", "q")
        assert rc == 4, out
        assert not (w["X"] / "run").exists() or not list((w["X"] / "run").iterdir())
    finally:
        f.chmod(0o644)


def test_flow_ledger_is_a_directory_exit_4(world):
    w = world
    (w["S"] / "out" / "stage.cost").mkdir(parents=True)
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 4, out


def test_flow_missing_or_empty_ledger_is_zero(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    seed_ledger(w["S"], "")
    rc, out = run_flow(w, "r09", "a2", "p")
    assert rc == 0, out
    assert ledger(w) == ["0.40 stage.r09.t1", "0.50 stage.r09.t2"]


def test_flow_ledger_going_bad_between_turns_skips_t2_and_ends_4(world):
    w = world
    (w["S"] / "out").mkdir()
    # 첫 턴이 끝난 뒤 장부에 틀린 줄이 생겼다 — 가짜 claude가 그 줄을 적는다
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_BADLEDGER": "1"})
    assert rc == 4, out
    chk = check_of(w, "r10")
    assert chk["t2"] == "skip:ctrl" and chk["exit"] == "4"       # 이제 통제 파일이 바뀐 것으로 먼저 잡힌다


def test_flow_money_margin_applies_to_stop_line(world):
    w = world
    (w["S"] / "out").mkdir()
    seed_ledger(w["S"], "12.10 stage.old\n")
    rc, out = run_flow(w, "r10", "a2", "q", {"STAGE_OVER12": "yes"})
    assert rc == 4, out                                   # 12.10 + 2.50 = 14.60 > 15.00 - 0.50
    assert "0.50" in out
    seed_ledger(w["S"], "11.90 stage.old\n")
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 12, out                                  # 11.90 + 2.50 = 14.40 <= 14.50 이라 시작은 한다 · 둘째 턴은 합 12.30 + 2.50 > 14.50
    assert ledger(w)[-1] == "0.40 stage.r10.t1"


def test_flow_money_margin_second_turn(world):
    w = world
    (w["S"] / "out").mkdir()
    seed_ledger(w["S"], "11.50 stage.old\n")
    # 첫 턴 0.40 → 합 11.90 → 11.90 + 2.50 = 14.40 <= 14.50 이라 둘째 턴이 간다
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    seed_ledger(w["S"], "11.50 stage.old\n")
    # 첫 턴 0.80 → 합 12.30 → 12.30 + 2.50 = 14.80 > 14.50 이라 둘째 턴이 안 간다
    rc, out = run_flow(w, "r09", "a2", "p", {"FAKE_COST1": "0.80"})
    assert rc == 12, out
    assert check_of(w, "r09")["t2"] == "skip:money"


def rerun_cfg(tmp_path, stop="4.00"):
    cfgdir = tmp_path / "cfg"
    (cfgdir / "stage").mkdir(parents=True)
    for n in ("stage-prompts.txt", "stage-replies.txt"):
        shutil.copy(M / n, cfgdir / n)
    cfg = json.loads((M / "stage" / "tasks.json").read_text(encoding="utf-8"))
    cfg["rerun"] = [["x01", "a1", "q"]]
    cfg["money_rerun"] = {"need": "1.00", "alarm": "3.00", "stop": stop}
    tj = cfgdir / "stage" / "tasks.json"
    tj.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return tj


def test_flow_money_margin_for_x_ledger(world, tmp_path):
    w = world
    tj = rerun_cfg(tmp_path)
    (w["S"] / "out").mkdir()
    seed_ledger(w["S"], "1.10 stage.old\n", "stage-x.cost")
    rc, out = run_flow(w, "x01", "a1", "q", {"STAGE_TASKS": str(tj)})
    assert rc == 4, out                                   # 1.10 + 2.50 = 3.60 > 4.00 - 0.50
    seed_ledger(w["S"], "0.90 stage.old\n", "stage-x.cost")
    rc, out = run_flow(w, "x01", "a1", "q", {"STAGE_TASKS": str(tj)})
    assert rc == 12, out                                  # 0.90 + 2.50 = 3.40 <= 3.50 이라 시작은 한다


def test_flow_margin_key_missing_exit_9(world, tmp_path):
    w = world
    cfg = json.loads((M / "stage" / "tasks.json").read_text(encoding="utf-8"))
    del cfg["money"]["margin"]
    cfgdir = tmp_path / "cfg2"
    (cfgdir / "stage").mkdir(parents=True)
    for n in ("stage-prompts.txt", "stage-replies.txt"):
        shutil.copy(M / n, cfgdir / n)
    tj = cfgdir / "stage" / "tasks.json"
    tj.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    rc, out = run_flow(w, "r10", "a2", "q", {"STAGE_TASKS": str(tj)})
    assert rc == 9, out
    assert not (w["X"] / "run").exists()


def test_flow_leftover_run_folder_refuses_start_exit_9(world):
    w = world
    (w["X"] / "run" / "deadbeef" / "w").mkdir(parents=True)
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 9, out
    assert "deadbeef" in out
    assert ledger(w) == [] and not (w["S"] / "done" / "r10").exists()
    assert [p.name for p in (w["X"] / "run").iterdir()] == ["deadbeef"]


@pytest.mark.parametrize("name", ["r03.t1.jsonl", "r03.check", "z01.low", "x02.json", "v01.base"])
def test_flow_leftover_out_file_refuses_start_exit_9(world, name):
    w = world
    (w["S"] / "out").mkdir()
    (w["S"] / "out" / name).write_text("x")
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 9, out
    assert name in out
    assert ledger(w) == []


def test_flow_ledger_log_lock_files_are_not_leftovers(world):
    w = world
    (w["S"] / "out").mkdir()
    for n, c in (("stage.cost", "1.00 stage.old\n"), ("stage-x.cost", "1.00 stage.old\n")):
        seed_ledger(w["S"], c, n)
    for n, c in (("stage.log", "x\n"), ("stage.sessions", "x\n"), ("seal.modes", "sealed 700\n")):
        (w["S"] / "out" / n).write_text(c)
    (w["S"] / "run.lock").mkdir(exist_ok=True)
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out


def test_flow_sealed_000_left_over_is_unsealed_with_one_notice(world):
    w = world
    for n in ("sealed", "bases", "try-impl"):
        (w["S"] / n).chmod(0)
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    notices = [ln for ln in out.split("\n") if "000" in ln and "풀" in ln]
    assert len(notices) == 1, out
    assert set(modes(w).values()) == {"0o700"}


def test_flow_no_sealed_leftover_no_notice(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    assert not [ln for ln in out.split("\n") if "000" in ln and "풀" in ln]


def test_flow_cum_needed_for_non_z_exit_9(world):
    w = world
    env = {k: v for k, v in w["env"].items() if k != "STAGE_CUM"}
    p = subprocess.run(["bash", str(SH), "r10", "a2", "q"], capture_output=True, text=True,
                       env={"PATH": w["path"], "HOME": str(w["home"]), **env})
    assert p.returncode == 9, p.stdout + p.stderr
    assert "STAGE_CUM" in p.stdout + p.stderr
    assert not (w["X"] / "run").exists() and ledger(w) == []
    for bad in ("2", "", "yes", "01"):
        rc, out = run_flow(w, "r10", "a2", "q", {"STAGE_CUM": bad})
        assert rc == 9, (bad, out)


def test_flow_cum_0_and_1_decide_cost2(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"STAGE_CUM": "1"})
    assert rc == 0, out
    assert ledger(w) == ["0.40 stage.r10.t1", "0.50 stage.r10.t2"] and check_of(w, "r10")["cum"] == "1"
    rc, out = run_flow(w, "r09", "a2", "p", {"STAGE_CUM": "0"})
    assert rc == 0, out
    assert ledger(w)[-2:] == ["0.40 stage.r09.t1", "0.90 stage.r09.t2"] and check_of(w, "r09")["cum"] == "0"


def test_flow_z_run_needs_no_cum_and_records_raw_costs(world):
    w = world
    env = {k: v for k, v in w["env"].items() if k != "STAGE_CUM"}
    p = subprocess.run(["bash", str(SH), "z03", "z0", "p"], capture_output=True, text=True, timeout=240,
                       env={"PATH": w["path"], "HOME": str(w["home"]), **env})
    if p.returncode == 3:
        pytest.skip("메모리 검사가 멈춤")
    assert p.returncode == 0, p.stdout + p.stderr
    chk = check_of(w, "z03")
    assert chk["cost_raw1"] == "0.4" or chk["cost_raw1"] == "0.40"
    assert chk["cost_raw2"] in ("0.9", "0.90")
    assert chk["cum"] == "?"
    assert ledger(w) == ["0.40 stage.z03.t1", "0.90 stage.z03.t2"]            # 누적인지 모르니 둘째는 받은 그대로(넉넉한 쪽)


def test_flow_non_z_check_has_raw_costs_too(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    chk = check_of(w, "r10")
    assert "cost_raw1" in chk and "cost_raw2" in chk


def test_static_destructive_paths_use_colon_question():
    t = live(code())
    assert 'mv "${R:?}" "${S:?}/done/$RUN"' in t
    assert 'mv "$f" "${S:?}/out-done/"' in t
    for ln in t.split("\n"):
        if re.match(r"^\s*(mv|chmod|rm)\b", ln) or re.search(r"[;&|]\s*(mv|chmod|rm)\b", ln):
            assert not re.search(r'"\$(R|S|X)\b', ln), ln
    assert "d=${S:?}/$n" in t
    assert 'mkdir -p "${X:?}/run"' in t


# ---------- 고침 2차 ----------

def unseal_tree(root):
    """봉한 채 남은 시험 폴더를 pytest가 못 지우는 일을 막는다: 위에서 아래로 디렉터리만 700으로."""
    for dp, dns, fns in os.walk(str(root)):
        try:
            os.chmod(dp, 0o700)
        except OSError:
            pass
        for d in dns:
            try:
                os.chmod(os.path.join(dp, d), 0o700)
            except OSError:
                pass


def test_unseal_tree_helper_restores_sealed_dirs(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f").write_text("x")
    (tmp_path / "a" / "b").chmod(0)
    (tmp_path / "a").chmod(0)
    unseal_tree(tmp_path)
    assert (tmp_path / "a" / "b" / "f").read_text() == "x"


def test_flow_without_lock_marker_exit_9_and_nothing_made(world):
    w = world
    env = {k: v for k, v in w["env"].items() if k != "STAGE_LOCKED"}
    p = subprocess.run(["bash", str(SH), "r10", "a2", "q"], capture_output=True, text=True,
                       env={"PATH": w["path"], "HOME": str(w["home"]), **env})
    assert p.returncode == 9, p.stdout + p.stderr
    assert "stage-locked" in p.stdout + p.stderr
    assert not (w["X"] / "run").exists() or not list((w["X"] / "run").iterdir())
    assert set(modes(w).values()) == {"0o700"}


def test_flow_lock_marker_must_equal_run_lock_path_and_exist(world, tmp_path):
    w = world
    for val in (str(tmp_path / "other.lock"), "", str(w["S"] / "run.lock") + "/"):
        env = {**w["env"], "STAGE_LOCKED": val}
        p = subprocess.run(["bash", str(SH), "r10", "a2", "q"], capture_output=True, text=True,
                           env={"PATH": w["path"], "HOME": str(w["home"]), **env})
        assert p.returncode == 9, (val, p.stdout + p.stderr)
    (w["S"] / "run.lock").rmdir()                                       # 표시는 맞는데 잠금이 없다
    p = subprocess.run(["bash", str(SH), "r10", "a2", "q"], capture_output=True, text=True,
                       env={"PATH": w["path"], "HOME": str(w["home"]), **w["env"]})
    assert p.returncode == 9, p.stdout + p.stderr


def test_flow_kitsha_seal_unseal_need_no_marker(world):
    w = world
    env = {k: v for k, v in w["env"].items() if k != "STAGE_LOCKED"}
    for args in (["kitsha"], ["seal"], ["unseal"]):
        p = subprocess.run(["bash", str(SH), *args], capture_output=True, text=True, env={"PATH": w["path"], "HOME": str(w["home"]), **env})
        assert p.returncode == 0, (args, p.stdout + p.stderr)


def test_flow_claude_sees_no_stage_variables(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"STAGE_VENV_B": "/x", "STAGE_VENV_C": "/y", "STAGE_EXTRA_NEW": "z"})
    assert rc == 0, out
    d = done_dir(w, "r10")
    for t in ("t1", "t2"):
        assert (d / ("stageenv." + t)).read_text() == "", (t, (d / ("stageenv." + t)).read_text())
    assert "STAGE_" in (SH.read_text(encoding="utf-8"))


FAKEV = "zzFAKEvalue9"


def test_flow_both_turns_get_tool_list_and_mcp_locks(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"ENABLE_CLAUDEAI_MCP_SERVERS": "true"})
    assert rc == 0, out
    d = done_dir(w, "r10")
    for m in ("t1", "t2"):
        assert (d / ("tools." + m)).read_text().strip() == TOOLS9
        assert (d / ("strict." + m)).exists() and (d / ("mcpenv." + m)).read_text().strip() == "false"
    j = json.loads((w["S"] / "out-done" / "r10.json").read_text())
    assert j["init_mcp"] == "?" and j["init_tools_out"] == "?"          # 가짜 claude의 init에는 두 필드가 없다
    assert j["tools_out_used"] == 0 and j["mcp_used"] == 0 and j["risky"] == 0


def test_flow_p_arm_also_gets_the_locks(world):
    w = world
    rc, out = run_flow(w, "r09", "a2", "p")
    assert rc == 0, out
    d = done_dir(w, "r09")
    for m in ("t1", "t2"):
        assert (d / ("tools." + m)).read_text().strip() == TOOLS9 and (d / ("strict." + m)).exists()


def test_flow_claude_account_variables_are_unset_but_two_stay(world):
    w = world
    extra = {"CLAUDE_CODE_MESSAGING_SOCKET": FAKEV, "CLAUDE_CODE_SESSION_ID": FAKEV, "CLAUDE_CODE_OAUTH_TOKEN": FAKEV,
             "CLAUDE_CONFIG_DIR": FAKEV, "CLAUDECODE": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0", "ENABLE_CLAUDEAI_MCP_SERVERS": "true"}
    rc, out = run_flow(w, "r10", "a2", "q", extra)
    assert rc == 0, out
    d = done_dir(w, "r10")
    for m in ("t1", "t2"):
        names = (d / ("claudenames." + m)).read_text().split()
        assert "CLAUDE_CODE_MESSAGING_SOCKET" not in names and "CLAUDE_CODE_SESSION_ID" not in names and "CLAUDECODE" not in names
        assert "CLAUDE_CODE_OAUTH_TOKEN" in names and "CLAUDE_CONFIG_DIR" in names
        assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" in names
        assert (d / ("automem." + m)).read_text().strip() == "1"            # 밖에서 0을 줘도 1로 덮인다
        assert (d / ("mcpenv." + m)).read_text().strip() == "false"
    assert FAKEV not in out


def fake_sched_bin(w, timers=""):
    """PATH 앞에 둘 가짜 crontab·systemctl(진짜 예약 작업은 읽지도 바꾸지도 않는다). crontab -l은 FAKE_CRONFILE 글을 낸다."""
    f = w["bin"] / "front"
    f.mkdir(exist_ok=True)
    (f / "crontab").write_text('#!/bin/bash\n[ "$1" = -l ] && cat "$FAKE_CRONFILE" 2> /dev/null\nexit 0\n')
    (f / "systemctl").write_text("#!/bin/bash\ncat <<'EOT'\n%sEOT\n" % timers)
    for n in ("crontab", "systemctl"):
        (f / n).chmod(0o755)
    cron = w["bin"] / "cronfile"
    cron.write_text("0 3 * * * backup\n")
    return {"PATH": str(f) + ":" + w["path"], "FAKE_CRONFILE": str(cron)}, cron


def test_flow_sched_same_and_sess_extra_zero(world):
    w = world
    env, _ = fake_sched_bin(w, "Mon 2026-11-23 00:00:00 KST 1h left n/a n/a logrotate.timer logrotate.service\n")
    rc, out = run_flow(w, "r10", "a2", "q", env)
    assert rc == 0, out
    chk = check_of(w, "r10")
    assert chk["sched"] == "same" and chk["sess_extra"] == "0", chk


def test_flow_sched_changed_when_crontab_text_changes(world):
    w = world
    env, cron = fake_sched_bin(w)
    rc, out = run_flow(w, "r10", "a2", "q", {**env, "FAKE_CRON": "1"})
    assert rc == 0, out                                              # 끝 값은 그대로(다른 작업이 바꿀 수 있다 — 무효 아님)
    chk = check_of(w, "r10")
    assert chk["sched"] == "changed" and chk["exit"] == "0", chk
    assert "* * * * * x" in cron.read_text()


def test_flow_sched_commands_that_fail_127_count_as_empty_and_same(world):
    w = world
    f = w["bin"] / "front"
    f.mkdir(exist_ok=True)
    for n in ("crontab", "systemctl"):                               # 아무것도 안 찍고 127로 끝난다(명령이 없는 것과 같다)
        (f / n).write_text("#!/bin/bash\nexit 127\n")
        (f / n).chmod(0o755)
    rc, out = run_flow(w, "r10", "a2", "q", {"PATH": str(f) + ":" + w["path"]})
    assert rc == 0, out
    chk = check_of(w, "r10")
    assert chk["sched"] == "same" and chk["exit"] == "0", chk


def test_flow_sess_extra_counts_other_conversations_only(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SESS": "0"})                 # 이 실행 대화 파일만
    assert rc == 0, out
    assert check_of(w, "r10")["sess_extra"] == "0"
    rc, out = run_flow(w, "r09", "a2", "p", {"FAKE_SESS": "2"})                 # 다른 대화 파일 둘
    assert rc == 0, out
    assert check_of(w, "r09")["sess_extra"] == "2"
    d = w["home"] / ".claude" / "projects"
    assert d.is_dir() and any(d.iterdir())


UUID2 = "11111111-2222-4333-8444-555555555555"


def test_flow_sess_extra_counts_every_folder_headed_by_the_run_dir(world):
    w = world
    items = ["%R%-w-sub:aa", "%R%-tmp:bb", "%R%-tmp:cc", "%R%-w:dd"]                  # (가) 하위·임시·사본 꼭대기 폴더 → 4
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SESS_FILES": " ".join(items)})
    assert rc == 0, out
    assert check_of(w, "r10")["sess_extra"] == "4"


def test_flow_sess_extra_skips_second_turn_id_when_it_differs(world):
    w = world
    items = ["%R%-w:" + UUID2, "%R%-tmp:" + UUID2, "%R%-tmp:ee"]                       # (나) 둘째 턴 대화 번호와 같은 이름은 안 센다
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SESS_FILES": " ".join(items), "FAKE_SID2": UUID2})
    assert rc == 13, out                                             # 둘째 턴 번호가 다르면 끝 값 13(설계대로) — 세기는 그대로 된다
    assert check_of(w, "r10")["sess_extra"] == "1"


def test_flow_sess_extra_ignores_folders_with_another_head(world):
    w = world
    items = ["other-run-xyz:ff", "other-run-xyz-w:gg", "%R%-w:hh"]                     # (다) 머리가 다른 폴더는 안 센다
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SESS_FILES": " ".join(items)})
    assert rc == 0, out
    assert check_of(w, "r10")["sess_extra"] == "1"


def test_flow_sess_extra_counts_the_run_dir_folder_itself(world):
    w = world
    items = ["%R%:aa", "%R%:bb", "%R%-w:cc"]                                           # (가) 실행 폴더 자체를 cwd로 띄운 대화(끝 - 없음) → 3
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SESS_FILES": " ".join(items)})
    assert rc == 0, out
    assert check_of(w, "r10")["sess_extra"] == "3"


def test_flow_sess_extra_ignores_a_neighbour_folder_glued_to_the_run_name(world):
    w = world
    items = ["%R%0-w:dd", "%R%0:ee", "%R%:ff"]                                         # (나) R 이름 뒤에 글자가 바로 이어지는 남의 폴더는 안 센다
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_SESS_FILES": " ".join(items)})
    assert rc == 0, out
    assert check_of(w, "r10")["sess_extra"] == "1"


def test_flow_survivors_17_still_counts_sched_and_sess_extra(world):
    w = world
    p = popen_flow(w, "r10", "a2", "q", {"FAKE_SPAWN": "t1", "BASH_FUNC_kill%%": KILL_NOOP, "FAKE_SESS_FILES": "%R%-tmp:ii"})
    try:
        out = p.communicate(timeout=180)[0]
        if p.returncode == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert p.returncode == 17, out
        chk = dict(ln.split("=", 1) for ln in (w["S"] / "out" / "r10.check").read_text().split("\n") if "=" in ln)
        assert chk["exit"] == "17" and chk["sched"] in ("same", "changed") and chk["sess_extra"].isdigit() and chk["sess_extra"] == "1", chk
    finally:
        end_proc(p)


@pytest.mark.parametrize("tamper,which", [("ledger", "stage.cost"), ("modes", "seal.modes")])
def test_flow_control_file_changed_in_t1_exit_4_t2_not_sent(world, tamper, which):
    w = world
    (w["S"] / "out").mkdir()
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": tamper})
    assert rc == 4, out
    chk = check_of(w, "r10")
    assert chk["t2"] == "skip:ctrl" and chk["exit"] == "4"
    assert not (done_dir(w, "r10") / "modes.txt").read_text().count("t2")
    assert set(modes(w).values()) == {"0o700"}                              # 풀기는 변수에서 — 파일의 777을 믿지 않았다


def test_flow_x_ledger_changed_in_t1_exit_4(world):
    w = world
    (w["S"] / "out").mkdir()
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": "xledger"})
    assert rc == 4, out
    assert check_of(w, "r10")["t2"] == "skip:ctrl"


def test_flow_control_file_changed_in_t2_exit_4(world):
    w = world
    (w["S"] / "out").mkdir()
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": "ledger", "FAKE_TAMP_ON": "t2"})
    assert rc == 4, out
    assert check_of(w, "r10")["t2"] == "sent"


def test_flow_seal_modes_forged_does_not_open_the_dirs_wide(world):
    w = world
    (w["S"] / "sealed").chmod(0o750)
    (w["S"] / "out").mkdir()
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": "modes"})
    assert rc == 4, out
    m = modes(w)
    assert m["sealed"] == "0o750" and m["bases"] == "0o700"                # 쓴 모드는 이 프로세스의 변수에서 돌아온다


@pytest.mark.parametrize("tamper", ["chmod", "chmodtry"])
def test_flow_seal_broken_during_turn_exit_17(world, tamper):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": tamper})
    assert rc == 17, out
    chk = check_of(w, "r10")
    assert chk["seal_broken"] == "1" and chk["exit"] == "17" and chk["t2"].startswith("skip:")
    assert set(modes(w).values()) == {"0o700"}


def test_flow_seal_broken_during_t2_exit_17(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": "chmod", "FAKE_TAMP_ON": "t2"})
    assert rc == 17, out
    chk = check_of(w, "r10")
    assert chk["seal_broken"] == "1" and chk["t2"] == "sent"


def test_flow_seal_broken_is_zero_on_a_clean_run(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    assert check_of(w, "r10")["seal_broken"] == "0"


def test_flow_second_turn_memory_stop_exit_3(world):
    w = world
    low = w["S"].parent / "lowmem"
    (w["bin"] / "powershell.exe").write_text('#!/bin/bash\n[ -e "%s" ] && echo 2 || echo 20\n' % low)
    env = {**w["env"], "FAKE_LOWMEM": str(low)}
    p = subprocess.run(["bash", str(SH), "r10", "a2", "q"], capture_output=True, text=True, timeout=240,
                       env={"PATH": w["path"], "HOME": str(w["home"]), **env})
    out = p.stdout + p.stderr
    if p.returncode == 3 and not (w["S"] / "out-done" / "r10.check").exists():
        pytest.skip("첫 턴 앞 메모리 검사가 멈춤(이 기계): " + out[-200:])
    assert p.returncode == 3, out
    chk = check_of(w, "r10")
    assert chk["t2"] == "skip:mem" and chk["exit"] == "3"
    assert chk["rc1"] == "0"


# ---------- 고침 3차 ----------

def popen_flow(w, run, task, arm, extra=None):
    env = {"PATH": w["path"], "HOME": str(w["home"]), **w["env"], **(extra or {})}
    return subprocess.Popen(["bash", str(SH), run, task, arm], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                            start_new_session=True)


def seal_answer(w):
    (w["S"] / "sealed" / "answer.txt").write_text("ANSWER-TEXT")


def test_flow_seal_is_held_through_both_turns_no_unseal_between(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    d = done_dir(w, "r10")
    c1, c2 = (d / "ctime.t1").read_text(), (d / "ctime.t2").read_text()
    assert c1 == c2 and c1.strip(), (c1, c2)                 # 사이에 풀었다 다시 봉했다면 봉한 폴더의 ctime이 달라진다
    assert set(modes(w).values()) == {"0o700"}


@pytest.mark.parametrize("where", ["in", "out"])
def test_flow_background_copy_loop_gets_no_answer_between_turns(world, where):
    w = world
    seal_answer(w)
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_COPYLOOP": where})
    assert rc == 0, out
    d = done_dir(w, "r10")
    assert (d / "got").is_dir()
    assert not (d / "got" / "answer.txt").exists(), list((d / "got").iterdir())
    assert check_of(w, "r10")["left1"] != "0"
    for pid in w["pids"].read_text().split():
        time.sleep(0.05)
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid), 0)


def test_flow_leftover_found_by_env_marker_when_cwd_is_outside_the_copy(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_ENVMARK": "1"})
    assert rc == 0, out
    assert check_of(w, "r10")["left1"] == "1"
    pid = int(w["pids"].read_text().split()[0])
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


KILL_NOOP = '() { [ -n "${2-}" ] && grep -qxF -- "$2" "$FAKE_PIDS" 2>/dev/null && return 0; builtin kill "$@"; }'


def test_flow_survivor_keeps_seal_exit_17_and_lists_pids(world):
    w = world
    p = popen_flow(w, "r10", "a2", "q", {"FAKE_SPAWN": "t1", "BASH_FUNC_kill%%": KILL_NOOP})
    try:
        out = p.communicate(timeout=180)[0]
        if p.returncode == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert p.returncode == 17, out
        pid = w["pids"].read_text().split()[0]
        assert pid in out, out                                          # 안내에 남은 pid가 있다
        assert set(modes(w).values()) == {"0o0"}                        # 풀지 않았다
        assert len(list((w["X"] / "run").iterdir())) == 1                # 사본은 옮기지 않고 남겼다(done은 봉해져 못 봄)
        assert "exit=17" in (w["S"] / "out" / "r10.check").read_text()
        copy = next((w["X"] / "run").iterdir())
        assert "t2" not in (copy / "w" / "modes.txt").read_text()         # 남은 것이 있으면 둘째 턴도 안 보낸다
        os.kill(int(pid), 0)                                            # 아직 살아 있다(이 시험이 끝에서 pid로 끈다)
    finally:
        end_proc(p)


def test_flow_dir_ctime_changed_in_a_turn_is_seal_broken_even_if_mode_is_000_again(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": "rechmod"})
    assert rc == 17, out
    chk = check_of(w, "r10")
    assert chk["seal_broken"] == "1" and chk["t2"].startswith("skip:")
    assert set(modes(w).values()) == {"0o700"}


def test_flow_ctl_file_mode_change_exit_4_and_t2_not_sent(world):
    w = world
    seed_ledger(w["S"], "1.00 stage.old\n")
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": "chmodledger"})
    assert rc == 4, out
    assert check_of(w, "r10")["t2"] == "skip:ctrl"


def test_flow_every_ledger_line_is_mirrored_in_out_done(world, tmp_path):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    mir = w["S"] / "out-done" / "stage.cost.mirror"
    assert mir.read_text() == (w["S"] / "out" / "stage.cost").read_text() == "0.40 stage.r10.t1\n0.50 stage.r10.t2\n"
    tj = rerun_cfg(tmp_path)
    rc, out = run_flow(w, "x01", "a1", "q", {"STAGE_TASKS": str(tj)})
    assert rc == 0, out
    assert (w["S"] / "out-done" / "stage-x.cost.mirror").read_text() == (w["S"] / "out" / "stage-x.cost").read_text()
    assert ledger(w, "stage-x.cost") == ["0.40 stage.x01.t1", "0.50 stage.x01.t2"]
    assert not (w["S"] / "out-done" / "STOP").exists()


def test_flow_signal_path_mirrors_the_ledger_line_too(world):
    w = world
    mark = w["S"].parent / "mark"
    p = popen_flow(w, "r10", "a2", "q", {"FAKE_HANG": "1", "FAKE_MARK": str(mark)})
    try:
        end = time.time() + 60
        while not mark.exists() and time.time() < end and p.poll() is None:
            time.sleep(0.1)
        if p.poll() == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert mark.exists()
        os.kill(p.pid, signal.SIGTERM)
        assert p.wait(timeout=60) == 143
        assert (w["S"] / "out-done" / "stage.cost.mirror").read_text() == "2.50 stage.r10.t1\n"
    finally:
        end_proc(p)


def test_flow_ledger_differs_from_mirror_at_start_exit_4_and_leaves_stop(world):
    w = world
    seed_ledger(w["S"], "1.00 stage.old\n")
    (w["S"] / "out-done" / "stage.cost.mirror").write_text("0.10 stage.old\n")
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 4, out
    assert "미러" in out
    assert (w["S"] / "out-done" / "STOP").exists()
    assert not (w["X"] / "run").exists() or not list((w["X"] / "run").iterdir())
    assert (w["S"] / "out" / "stage.cost").read_text() == "1.00 stage.old\n"


def test_flow_stop_marker_makes_every_next_run_exit_4_until_a_human_deletes_it(world):
    w = world
    (w["S"] / "out-done").mkdir(exist_ok=True)
    (w["S"] / "out-done" / "STOP").write_text("")
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 4, out
    assert "STOP" in out and "사람" in out
    assert not (w["X"] / "run").exists() or not list((w["X"] / "run").iterdir())
    (w["S"] / "out-done" / "STOP").unlink()
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out


def test_flow_ctl_tamper_exit_4_leaves_stop_and_blocks_the_next_run(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_TAMP": "ledger"})
    assert rc == 4, out
    assert (w["S"] / "out-done" / "STOP").exists()
    rc, out = run_flow(w, "r09", "a2", "p")
    assert rc == 4 and "STOP" in out, out


def test_flow_plain_money_stop_does_not_leave_a_stop_marker(world):
    w = world
    seed_ledger(w["S"], "12.00 stage.old\n")
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 4, out
    assert not (w["S"] / "out-done" / "STOP").exists()                  # 돈 선은 사람이 STAGE_OVER12로 허락하는 길이 따로 있다


def test_flow_ledger_not_growing_by_exactly_one_exit_4(world):
    w = world
    noprint = '() { case "$*" in *stage.r10.t1*) return 0 ;; esac; builtin printf "$@"; }'
    rc, out = run_flow(w, "r10", "a2", "q", {"BASH_FUNC_printf%%": noprint})
    assert rc == 4, out
    chk = check_of(w, "r10")
    assert chk["exit"] == "4" and chk["t2"].startswith("skip:")
    assert (w["S"] / "out-done" / "STOP").exists()


def test_flow_group_writable_dir_comes_back_700(world):
    w = world
    (w["S"] / "sealed").chmod(0o770)
    (w["S"] / "bases").chmod(0o750)
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    m = modes(w)
    assert m["sealed"] == "0o700" and m["bases"] == "0o750"


def test_unseal_modes_file_group_write_also_becomes_700(roots):
    home, S, X = roots
    names = ("sealed", "src-b", "bases", "walk", "walkkit")
    for n in names:
        (S / n).mkdir(parents=True)
        (S / n).chmod(0)
    (S / "out").mkdir()
    (S / "out" / "seal.modes").write_text("sealed 770\nsrc-b 720\nbases 760\nwalk 750\nwalkkit 710\n", encoding="utf-8")
    assert sh(["unseal"], home, env_of(S, X))[0] == 0
    assert [oct((S / n).stat().st_mode & 0o777) for n in names] == ["0o700", "0o700", "0o700", "0o750", "0o710"]


def _stage_sh_pids(root):
    out = []
    for pid in pids_mentioning(root):
        try:
            if b"stage.sh" in Path("/proc/%d/cmdline" % pid).read_bytes():
                out.append(pid)
        except OSError:
            pass
    return out


def test_flow_watch_loop_exits_when_stage_sh_is_killed(world):
    w = world
    mark = w["S"].parent / "mark"
    p = popen_flow(w, "r10", "a2", "q", {"FAKE_HANG": "1", "FAKE_MARK": str(mark)})
    try:
        end = time.time() + 60
        while not (mark.exists() and (w["S"] / "out" / "r10.watch").exists()) and time.time() < end and p.poll() is None:
            time.sleep(0.1)
        if p.poll() == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert mark.exists()
        assert len(_stage_sh_pids(w["S"])) >= 2                         # 본 프로세스와 감시
        os.kill(p.pid, signal.SIGKILL)
        p.wait(timeout=10)
        end = time.time() + 20
        while _stage_sh_pids(w["S"]) and time.time() < end:
            time.sleep(0.3)
        assert _stage_sh_pids(w["S"]) == [], "감시가 고아로 남았음"
    finally:
        end_proc(p)
        if mark.exists():
            try:
                os.kill(int(mark.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


@pytest.mark.parametrize("rc", [137, 143, 129])
def test_locked_keeps_the_lock_when_the_child_exits_over_128(tmp_path, rc):
    f, lock, env = locked_copy(tmp_path)
    got, out = sh(["bash", "-c", "exit %d" % rc], tmp_path, env, script=f)
    assert got == rc and lock.is_dir(), out
    assert "장부에 상한 줄이 적혔는지 확인하고" in out


def test_locked_removes_the_lock_when_the_child_exits_128_or_less(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    for rc in (0, 1, 5, 128):
        got, out = sh(["bash", "-c", "exit %d" % rc], tmp_path, env, script=f)
        assert got == rc and not lock.exists(), (rc, out)


def test_standalone_unseal_exit_9_while_a_run_process_is_alive_even_without_lock_dir(roots):
    home, S, X = roots
    (S / "sealed").mkdir(parents=True)
    (S / "sealed").chmod(0)
    (S / "out").mkdir()
    (S / "out" / "r10.t1.jsonl").write_text("x")                        # 끊긴 실행이 남긴 파일
    own = X / "run" / "abcd1234"
    (own / "w").mkdir(parents=True)
    child = subprocess.Popen(["env", "TMPDIR=%s/tmp" % own, "sleep", "30"], start_new_session=True,
                             cwd="/", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # cwd는 사본 밖 — 환경 표시로만 찾을 수 있다
    try:
        time.sleep(0.3)
        rc, out = sh(["unseal"], home, env_of(S, X))
        assert rc == 9, out
        assert str(child.pid) in out
        assert oct((S / "sealed").stat().st_mode & 0o777) == "0o0"
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    rc, out = sh(["unseal"], home, env_of(S, X))
    assert rc == 0, out
    assert oct((S / "sealed").stat().st_mode & 0o777) == "0o700"


def test_standalone_unseal_without_leftover_run_files_ignores_live_processes(roots):
    home, S, X = roots
    (S / "sealed").mkdir(parents=True)
    (S / "sealed").chmod(0)
    own = X / "run" / "abcd1234"
    (own / "w").mkdir(parents=True)
    child = subprocess.Popen(["env", "TMPDIR=%s/tmp" % own, "sleep", "30"], start_new_session=True, cwd="/",
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        assert sh(["unseal"], home, env_of(S, X))[0] == 0
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


# ---------- 고침 4차 ----------

def test_flow_signal_between_turns_leaves_no_stop_and_marks_t2_skip_sig(world):
    """첫 턴 장부 줄이 붙은 뒤 memok t2가 도는 동안 TERM — 통제 파일이 바뀐 게 아니다."""
    w = world
    ps = w["S"].parent / "psmark"
    (w["bin"] / "powershell.exe").write_text(
        '#!/bin/bash\nif [ -s "$FAKE_S/out/stage.cost" ]; then echo $$ > "%s"; sleep 6; fi\necho 20\n' % ps)
    p = popen_flow(w, "r10", "a2", "q")
    try:
        end = time.time() + 90
        while not ps.exists() and time.time() < end and p.poll() is None:
            time.sleep(0.1)
        if p.poll() == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert ps.exists(), "둘째 턴 앞 메모리 검사에 못 닿음"
        os.kill(p.pid, signal.SIGTERM)
        assert p.wait(timeout=60) == 143
        out = p.stdout.read()
        assert not (w["S"] / "out-done" / "STOP").exists(), out
        assert ledger(w) == ["0.40 stage.r10.t1"]
        assert (w["S"] / "out-done" / "stage.cost.mirror").read_text() == (w["S"] / "out" / "stage.cost").read_text()
        chk = check_of(w, "r10")
        assert chk["t2"] == "skip:sig" and chk["exit"] == "143", chk
        assert set(modes(w).values()) == {"0o700"}
    finally:
        end_proc(p)


def test_flow_signal_during_turn_one_also_marks_t2_skip_sig(world):
    w = world
    mark = w["S"].parent / "mark"
    p = popen_flow(w, "r10", "a2", "q", {"FAKE_HANG": "1", "FAKE_MARK": str(mark)})
    try:
        end = time.time() + 60
        while not mark.exists() and time.time() < end and p.poll() is None:
            time.sleep(0.1)
        if p.poll() == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert mark.exists()
        os.kill(p.pid, signal.SIGTERM)
        assert p.wait(timeout=60) == 143
        chk = check_of(w, "r10")
        assert chk["t2"] == "skip:sig"
        assert not (w["S"] / "out-done" / "STOP").exists()
        assert (w["S"] / "out-done" / "r10.json").is_file()                # 신호로 끝나도 센 글이 생긴다
        assert (w["S"] / "run.lock" / "why").read_text().strip() == "signal"
        assert not list((w["S"] / "out").glob("r10.*"))
    finally:
        end_proc(p)
        if mark.exists():
            try:
                os.kill(int(mark.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


def test_flow_low_flag_leaves_why_low_mem_and_a_json(world):
    w = world
    low = w["S"] / "out" / "r10.low"
    rc, out = run_flow(w, "r10", "a2", "q", {"FAKE_LOW": str(low)})
    assert rc == 143, out
    assert (w["S"] / "run.lock" / "why").read_text().strip() == "low-mem"
    assert (w["S"] / "out-done" / "r10.json").is_file()


def test_flow_survivors_17_writes_why_pending_mirror_line_and_json(world):
    w = world
    p = popen_flow(w, "r10", "a2", "q", {"FAKE_SPAWN": "t1", "BASH_FUNC_kill%%": KILL_NOOP})
    try:
        out = p.communicate(timeout=180)[0]
        if p.returncode == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert p.returncode == 17, out
        assert (w["S"] / "run.lock" / "why").read_text().strip() == "survivors"
        pend = w["S"] / "out" / "r10.mirror-pending"
        assert pend.read_text() == "0.40 stage.r10.t1\n"
        assert str(pend) in out
        js = json.loads((w["S"] / "out" / "r10.json").read_text())
        assert js["run"] == "r10"
        assert "exit=17" in (w["S"] / "out" / "r10.check").read_text()
        # 다음 실행은 9: 안내에 그 줄과 옮기는 법이 있다
        rc, out2 = run_flow(w, "r09", "a2", "p")
        assert rc == 9, out2
        assert "r10.mirror-pending" in out2 and "0.40 stage.r10.t1" in out2
        assert "지우지 말고" in out2 and "out-done" in out2 and "거울" in out2
    finally:
        end_proc(p)


def test_flow_signal_with_survivors_143_keeps_seal_writes_pending_json_and_why(world):
    w = world
    mark = w["S"].parent / "mark"
    p = popen_flow(w, "r10", "a2", "q", {"FAKE_HANG": "1", "FAKE_MARK": str(mark), "FAKE_SPAWN": "t1", "FAKE_SETSID": "1", "BASH_FUNC_kill%%": KILL_NOOP})
    try:
        end = time.time() + 60
        while not mark.exists() and time.time() < end and p.poll() is None:
            time.sleep(0.1)
        if p.poll() == 3:
            pytest.skip("메모리 검사가 멈춤")
        assert mark.exists()
        time.sleep(0.5)
        os.kill(p.pid, signal.SIGTERM)
        assert p.wait(timeout=90) == 143
        assert set(modes(w).values()) == {"0o0"}
        assert (w["S"] / "run.lock" / "why").read_text().strip() == "survivors"
        assert (w["S"] / "out" / "r10.mirror-pending").read_text() == "2.50 stage.r10.t1\n"
        assert (w["S"] / "out" / "r10.json").is_file()
    finally:
        end_proc(p)
        if mark.exists():
            try:
                os.kill(int(mark.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass


def test_flow_signal_without_survivors_leaves_no_pending_file(world):
    w = world
    rc, out = run_flow(w, "r10", "a2", "q")
    assert rc == 0, out
    assert not list((w["S"] / "out-done").glob("*.mirror-pending")) and not list((w["S"] / "out").glob("*.mirror-pending"))
    assert not (w["S"] / "run.lock" / "why").exists()


def test_locked_writes_exit_n_why_when_the_child_gave_none(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    got, out = sh(["bash", "-c", "exit 137"], tmp_path, env, script=f)
    assert got == 137 and (lock / "why").read_text().strip() == "exit-137", out
    assert "exit-137" in out


def test_locked_keeps_the_why_the_child_wrote(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    got, out = sh(["bash", "-c", 'echo low-mem > "$STAGE_LOCKED/why"; exit 143'], tmp_path, env, script=f)
    assert got == 143 and (lock / "why").read_text().strip() == "low-mem", out
    assert "low-mem" in out


def test_locked_keeps_the_lock_when_the_child_left_a_why_even_with_a_small_exit(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    got, out = sh(["bash", "-c", 'echo survivors > "$STAGE_LOCKED/why"; exit 17'], tmp_path, env, script=f)
    assert got == 17 and lock.is_dir(), out
    assert (lock / "why").read_text().strip() == "survivors"


def test_locked_refusal_prints_why_and_how_to_clear_when_nobody_holds_the_lock(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    sh(["bash", "-c", "exit 137"], tmp_path, env, script=f)
    got, out = sh(["true"], tmp_path, env, script=f)
    assert got == 7, out
    assert "다른 실행이 잠금을 잡고 있음" in out
    assert "도는 실행 없음 — 까닭: exit-137 — 확인 뒤 `rm %s/why && rmdir %s`" % (lock, lock) in out, out


def test_locked_refusal_does_not_say_nobody_runs_while_a_holder_is_alive(tmp_path):
    f, lock, env = locked_copy(tmp_path)
    marker = tmp_path / "pid"
    p = subprocess.Popen(["bash", str(f), "bash", "-c", "echo $$ > %s; exec sleep 30" % marker],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env={"PATH": BASE_PATH, "HOME": str(tmp_path), **env})
    try:
        end = time.time() + 20
        while not marker.exists() and time.time() < end:
            time.sleep(0.1)
        assert marker.exists()
        got, out = sh(["true"], tmp_path, env, script=f)
        assert got == 7, out
        assert "도는 실행 없음" not in out, out
    finally:
        end_proc(p)
        if marker.exists():
            try:
                os.kill(int(marker.read_text().strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
