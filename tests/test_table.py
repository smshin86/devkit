import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

M = Path(__file__).resolve().parents[1] / "docs" / "measure"
TOOL = M / "table.py"
ENV = {"PYTHONDONTWRITEBYTECODE": "1"}


def run(*args):
    p = subprocess.run([sys.executable, "-I", str(TOOL), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout


def fields(out):
    return dict(w.split("=", 1) for w in out.split())


CTL = ["class Ctl {", "", '  @RequestMapping("/a/list.do")', "  list() {}", "",
       "  // edit", '  @RequestMapping("/a/edit.do")', "", "  edit() {}", '  @GetMapping("/api/items")', "}"]
APP = ["import x", "", "", "", "function Home() {}", "function Side() {}"]
RT = ['r("/v/items/{id}", a)', "", "", "", 'r("/v/items", b)', "", "", "", 'r("/v/item", c).r("/x/v/items2", d)']


def proj(tmp_path):
    r = tmp_path / "p"
    for rel, lines in (("web/a/list.jsp", ["<h1>목록</h1>"]), ("web/a/edit.jsp", ["<h1>고치기</h1>"]),
                       ("web/inc/head.jsp", ["<head/>"]), ("src/Ctl.java", CTL), ("src/App.js", APP),
                       ("src/Rt.txt", RT)):
        f = r / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return r


HEAD = "# 화면 표\n\n- 쓴 때: 2026-11-20 · 화면 5개: `x` · 주소 3개: `y`\n\n| 화면 | 화면 파일 | 주소 | 받는 코드 |\n|---|---|---|---|\n"
BASIC = HEAD + "\n".join([
    "| 목록 | `web/a/list.jsp` | `/a/list.do` | `src/Ctl.java:3` |",
    "| 고치기 | web/a/edit.jsp | /a/edit.do | src/Ctl.java:9 |",
    "| 머리 조각 | `./web/inc/head.jsp` | ? | ? |",
    "| 없는 화면 | `web/a/gone.jsp` | `/a/gone.do` | `src/Ctl.java:30` |",
    "| 첫 화면 | `src/App.js:5` | 앱 안 | `src/App.js:5` |",
    "| — | — | `GET /api/items` | `src/Ctl.java:10` |",
]) + "\n"


def table(tmp_path, body):
    t = tmp_path / "screens.md"
    t.write_text(body, encoding="utf-8")
    return t


def test_table_counts(tmp_path):
    rc, out = run(table(tmp_path, BASIC), proj(tmp_path))
    assert rc == 0 and out.count("\n") == 1
    assert out == "screen_rows=5 api_rows=1 file_ok=4 filled=4 near=3 loose=3 addrs=4 near_addrs=3 pages=- odd=0 uniq=4 self=0\n"


def test_table_lenient_paths(tmp_path):
    r = proj(tmp_path)
    body = HEAD + "\n".join([
        "| a | `a/list.jsp` | ? | ? |",
        "| b | `…/a/edit.jsp` | ? | ? |",
        "| c | `web\\inc\\head.jsp` | ? | ? |",
        "| d | `/web/a/list.jsp` | ? | ? |",
        "| e | `%s` | ? | ? |" % (r / "src/App.js"),
        "| f | `src/App.js:6` | 앱 안 | ? |",
        "| g | `src/App.js:7` | 앱 안 | ? |",
        "| h | `?` | ? | ? |",
        "| i | `../outside.jsp` | ? | ? |",
        "| j | `web/a/li\x00st.jsp` | ? | ? |",
    ]) + "\n"
    (tmp_path / "outside.jsp").write_text("x\n", encoding="utf-8")
    rc, out = run(table(tmp_path, body), r)
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == "10" and d["file_ok"] == "6" and d["filled"] == "0"


def test_table_outside_link(tmp_path):
    r = proj(tmp_path)
    (tmp_path / "out.jsp").write_text("x\n", encoding="utf-8")
    try:
        os.symlink(tmp_path / "out.jsp", r / "web/a/link.jsp")
    except OSError:
        pytest.skip("바로가기를 못 만드는 곳")
    body = HEAD + "| a | `web/a/link.jsp` | ? | ? |\n| b | `a/link.jsp` | `/a/x.do` | `a/link.jsp:1` |\n"
    rc, out = run(table(tmp_path, body), r)
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == "2" and d["file_ok"] == "0" and d["filled"] == "1" and d["loose"] == "0"


def test_table_near_window(tmp_path):
    r = proj(tmp_path)
    body = HEAD + "\n".join([
        "| x | — | `/a/list.do` | `src/Ctl.java:1` |",
        "| x | — | `/a/list.do` | `src/Ctl.java:5` |",
        "| x | — | `/a/list.do` | `src/Ctl.java:6` |",
        "| x | — | `/zz/a/list.do?id=1` | `src/Ctl.java:3` |",
        "| x | — | `/zz/edit.do` | `src/Ctl.java:7` |",
        "| x | — | `/zz/{id}` | `src/Ctl.java:7` |",
        "| x | — | `/a/list.do` | `Ctl.java:3` |",
    ]) + "\n"
    rc, out = run(table(tmp_path, body), r)
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == "0" and d["api_rows"] == "7" and d["filled"] == "7"
    assert d["near"] == "3" and d["loose"] == "5" and d["addrs"] == "4" and d["near_addrs"] == "1"


def test_table_near_boundary(tmp_path):
    r = proj(tmp_path)
    body = HEAD + "\n".join([
        "| — | — | `/v/items` | `src/Rt.txt:1` |",
        "| — | — | `/v/items` | `src/Rt.txt:5` |",
        "| — | — | `/v/item` | `src/Rt.txt:5` |",
        "| — | — | `/v/item` | `src/Rt.txt:9` |",
        "| — | — | `/v/items2` | `src/Rt.txt:9` |",
        "| — | — | `GET /v/items` | `src/Rt.txt:5` |",
        "| — | — | `POST /v/items, PUT /v/items` | `src/Rt.txt:5` |",
        "| — | — | `GET/POST /v/items/` | `src/Rt.txt:5` |",
    ]) + "\n"
    rc, out = run(table(tmp_path, body), r)
    assert rc == 0 and out == "screen_rows=0 api_rows=8 file_ok=0 filled=8 near=5 loose=6 addrs=3 near_addrs=2 pages=- odd=0 uniq=0 self=0\n"


def test_table_cell_split(tmp_path):
    r = proj(tmp_path)
    body = HEAD + "\n".join([
        "| 가\\|나 | `web/a/list.jsp` | `/a/list.do` | `src/Ctl.java:3` |",
        "| 다 | `web/a/edit.jsp` | `/a/edit.do (a|b)` | `src/Ctl.java:7` |",
        "| 라 | `web/inc/head.jsp | ? | ? |",
        "| 마 | `src/App.js:5` | 앱 안 (탭 바꿈) | `src/App.js:5` |",
    ]) + "\n"
    rc, out = run(table(tmp_path, body), r)
    assert rc == 0 and out == "screen_rows=4 api_rows=0 file_ok=4 filled=2 near=2 loose=2 addrs=2 near_addrs=2 pages=- odd=0 uniq=4 self=0\n"


def test_table_api_rows(tmp_path):
    r = proj(tmp_path)
    body = HEAD + "| — | — | `/api/items` | `src/Ctl.java:10` |\n|  |  | `/api/items` | `src/Ctl.java:10` |\n| - | – | ? | ? |\n"
    rc, out = run(table(tmp_path, body), r)
    assert rc == 0 and out == "screen_rows=0 api_rows=3 file_ok=0 filled=2 near=2 loose=2 addrs=1 near_addrs=1 pages=- odd=0 uniq=0 self=0\n"


def test_table_named_row_without_file_is_api_row(tmp_path):
    body = HEAD + "\n".join([
        "| 목록 | `web/a/list.jsp` | `/a/list.do` | `src/Ctl.java:3` |",
        "| 목록 자료 | — | `/a/list.do` | `src/Ctl.java:3` |",
        "| 지우기 처리 | - | ? | ? |",
        "| 모르는 화면 | ? | ? | ? |",
        "| — | `web/a/list.jsp` | ? | ? |",
    ]) + "\n"
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == "3" and d["api_rows"] == "2"
    assert d["file_ok"] == "2" and d["uniq"] == "1" and d["filled"] == "2" and d["near"] == "2"


def test_table_pages(tmp_path):
    r = proj(tmp_path)
    m = tmp_path / "map.json"
    m.write_text(json.dumps({"pages": {"web/a/list.jsp": {}, "web/a/edit.jsp": {}, "x/web/inc/head.jsp": {},
                                       "web/b/other.jsp": {}}}), encoding="utf-8")
    body = HEAD + "| 목록 | `web/a/list.jsp` | ? | ? |\n| 고치기 | `a/edit.jsp` | ? | ? |\n| 머리 | `web/inc/head.jsp` | ? | ? |\n| — | — | `web/b/other.jsp` | ? |\n"
    rc, out = run(table(tmp_path, body), r, "--pages", m)
    assert rc == 0 and fields(out)["pages"] == "3/4"
    for w in ("list.jsp", "edit.jsp", "head.jsp", "other.jsp", "목록", "web/"):
        assert w not in out


def test_table_pages_strict(tmp_path):
    r = proj(tmp_path)
    m = tmp_path / "map.json"
    m.write_text(json.dumps({"pages": {"web/a/list.jsp": {}, "web/b/list.jsp": {}, "web/a/gone.jsp": {},
                                       "web/a/edit.jsp": {}}}), encoding="utf-8")
    body = HEAD + "| 목록 | `list.jsp` | ? | ? |\n| 없는 | `web/a/gone.jsp` | ? | ? |\n| 고치기 | `./web/a/edit.jsp:1` | ? | ? |\n| 또 | `web/a/edit.jsp` | ? | ? |\n"
    rc, out = run(table(tmp_path, body), r, "--pages", m)
    d = fields(out)
    assert rc == 0 and d["file_ok"] == "3" and d["pages"] == "1/4"


def test_table_prints_no_names(tmp_path):
    rc, out = run(table(tmp_path, BASIC), proj(tmp_path))
    assert rc == 0 and out.startswith("screen_rows=")
    for w in ("목록", "고치기", "list", "/a/", "Ctl", "App", "/api", "items"):
        assert w not in out, w


def test_table_skips_fence_and_odd(tmp_path):
    body = "```\n| 화면 | 화면 파일 | 주소 | 받는 코드 |\n| a | `web/a/list.jsp` | ? | ? |\n```\n" + HEAD + "| a | b |\n| 목록 | `web/a/list.jsp` | ? | ? |\n"
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    assert rc == 0 and out == "screen_rows=1 api_rows=0 file_ok=1 filled=0 near=0 loose=0 addrs=0 near_addrs=0 pages=- odd=1 uniq=1 self=0\n"


def test_table_bad_input(tmp_path):
    r = proj(tmp_path)
    t = table(tmp_path, BASIC)
    for args in ((), (t,), (t, r, "--pages"), (t, r, "x")):
        rc, out = run(*args)
        assert rc == 9 and out.startswith("인자 틀림"), args
    rc, out = run(tmp_path / "none.md", r); assert rc == 2 and out == "표를 못 읽음\n"
    rc, out = run(r, r); assert rc == 2 and out == "표를 못 읽음\n"
    rc, out = run(t, tmp_path / "nodir"); assert rc == 2 and out == "프로젝트 폴더 없음\n"
    bad = tmp_path / "bad.json"; bad.write_text("[1]", encoding="utf-8")
    rc, out = run(t, r, "--pages", bad); assert rc == 2 and out == "화면 목록을 못 읽음\n"
    rc, out = run(t, r, "--pages", tmp_path / "none.json"); assert rc == 2 and out == "화면 목록을 못 읽음\n"
    deep = tmp_path / "deep.json"; deep.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    rc, out = run(t, r, "--pages", deep); assert rc == 2 and out == "화면 목록을 못 읽음\n"


def test_table_internal_error(tmp_path):
    r = proj(tmp_path); t = table(tmp_path, BASIC)
    code = ("import os, runpy, sys\n"
            "def boom(*a, **k):\n    raise RuntimeError(sys.argv[2])\n"
            "os.walk = boom\n"
            "tool = sys.argv[1]; sys.argv = sys.argv[1:]\n"
            "runpy.run_path(tool, run_name='__main__')\n")
    p = subprocess.run([sys.executable, "-I", "-c", code, str(TOOL), str(t), str(r)],
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    assert p.returncode == 1 and p.stdout == ""
    assert p.stderr == "table.py: internal error (RuntimeError)\n"


def test_table_creates_nothing(tmp_path):
    r = proj(tmp_path); t = table(tmp_path, BASIC)
    snap = lambda: sorted(str(p) for p in tmp_path.rglob("*"))
    before = snap()
    rc, out = run(t, r)
    assert rc == 0 and snap() == before and not (M / "__pycache__").exists()


def test_table_stdlib_py38():
    src = TOOL.read_text(encoding="utf-8")
    tree = ast.parse(src, feature_version=(3, 8))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    assert mods <= {"json", "os", "re", "sys"}


def run3(*args):
    p = subprocess.run([sys.executable, "-I", str(TOOL), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout, p.stderr


def test_table_skip_dirs_are_not_evidence(tmp_path):
    r = proj(tmp_path)
    (r / "node_modules/x").mkdir(parents=True)
    (r / "node_modules/x/a.js").write_text("x\n", encoding="utf-8")
    (r / ".devkit").mkdir()
    body = HEAD + "| 가 | — | `/a/list.do` | `.devkit/screens.md:7` |\n"
    assert "/a/list.do" in body.split("\n")[6]          # 7째 줄이 표 자신의 이 줄이다
    (r / ".devkit/screens.md").write_text(body, encoding="utf-8")
    rc, out = run(r / ".devkit/screens.md", r)
    d = fields(out)
    assert rc == 0 and d["filled"] == "0" and d["near"] == "0" and d["loose"] == "0"
    for d_ in (".git", ".svn", ".devkit", "node_modules"):
        (r / d_ / "x").mkdir(parents=True, exist_ok=True)
        (r / d_ / "x/a.js").write_text("x\n", encoding="utf-8")
        rc, out = run(table(tmp_path, HEAD + "| 가 | `%s/x/a.js` | ? | ? |\n" % d_), r)
        assert rc == 0 and fields(out)["screen_rows"] == "1" and fields(out)["file_ok"] == "0", d_


@pytest.mark.parametrize("body,screens,odd", [
    ("| 화면 | 파일 | 주소 | 받는 코드 |\n|---|---|---|---|\n| 목록 | `web/a/list.jsp` | ? | ? |\n", 1, 0),
    ("글\n| 화면 | 파일 | 주소 | 받는 코드 |\n|---|---|---|---|\n| 목록 | `web/a/list.jsp` | ? | ? |\n", 1, 0),
    ("```\nx\n```\n| 화면 | 파일 | 주소 | 받는 코드 |\n|---|---|---|---|\n| 목록 | `web/a/list.jsp` | ? | ? |\n", 1, 0),
    (HEAD + "| 목록 | `web/a/list.jsp` | ? | ? |\n\n| 주소 | 메서드 | 받는 코드 |\n|---|---|---|\n| /a/x | GET | y |\n", 1, 1),
    (HEAD + "| 목록 | `web/a/list.jsp` | ? | ? |\n\n| 주소 | 메서드 |\n|---|---|\n", 1, 0),
    # 표 가운데(앞 줄도 표 줄)의 구분 줄은 앞 줄을 물리지 않는다
    (HEAD + "| a | `web/a/list.jsp` | ? | ? |\n| b | `web/a/edit.jsp` | ? | ? |\n|---|---|---|---|\n| c | `src/App.js:1` | ? | ? |\n", 3, 0),
])
def test_table_header_is_line_before_rule(tmp_path, body, screens, odd):
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == str(screens) and d["odd"] == str(odd), out


def test_table_huge_line_number(tmp_path):
    body = HEAD + "| — | — | `/a/list.do` | `src/Ctl.java:%s` |\n" % ("1" * 5000)
    rc, out, err = run3(table(tmp_path, body), proj(tmp_path))
    assert rc == 0 and err == "" and fields(out)["filled"] == "0"


def test_table_uniq_and_self(tmp_path):
    r = proj(tmp_path)
    body = HEAD + "| 첫 | `src/App.js:1` | ? | ? |\n" * 21
    rc, out = run(table(tmp_path, body), r)
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == "21" and d["file_ok"] == "21" and d["uniq"] == "1" and d["self"] == "0"
    body = HEAD + "\n".join([
        "| 목록 | src/Ctl.java | /a/list.do | src/Ctl.java:3 |",
        "| 고치기 | web/a/edit.jsp | /a/edit.do | src/Ctl.java:7 |",
        "| — | — | /a/list.do | src/Ctl.java:3 |",
        "| 같은 | src/Ctl.java | /a/gone.do | src/Ctl.java:3 |",
    ]) + "\n"
    rc, out = run(table(tmp_path, body), r)
    assert rc == 0 and out == ("screen_rows=3 api_rows=1 file_ok=3 filled=4 near=3 loose=3 addrs=3 near_addrs=2 "
                               "pages=- odd=0 uniq=2 self=1\n")


def test_table_uniq_splits_by_line_number(tmp_path):
    body = HEAD + "| 가 | `src/App.js:1` | ? | ? |\n| 나 | `src/App.js:5` | ? | ? |\n"
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    d = fields(out)
    assert rc == 0 and d["file_ok"] == "2" and d["uniq"] == "2"


def test_table_line_number_digit_limit(tmp_path):
    r = proj(tmp_path)
    row = "| — | — | `/a/list.do` | `src/Ctl.java:%s` |\n"
    rc, out = run(table(tmp_path, HEAD + row % "000000003"), r)     # 9자리, 값 3
    d = fields(out)
    assert rc == 0 and d["filled"] == "1" and d["near"] == "1"
    rc, out = run(table(tmp_path, HEAD + row % "0000000003"), r)    # 10자리
    assert rc == 0 and fields(out)["filled"] == "0"


# ---- C. 도구를 틀리게 바꿔도 통과하던 곳 ----

@pytest.mark.parametrize("d", [".git", ".svn", ".devkit", "node_modules"])
def test_table_skip_dir_files_are_no_tail_candidates(tmp_path, d):
    r = proj(tmp_path)
    f = r / d / "web/a/only.jsp"
    f.parent.mkdir(parents=True)
    f.write_text("/z/only\n", encoding="utf-8")
    body = HEAD + "| 가 | `web/a/only.jsp` | ? | ? |\n| — | — | `/z/only` | `web/a/only.jsp:1` |\n"
    rc, out = run(table(tmp_path, body), r)
    d_ = fields(out)
    assert rc == 0 and d_["file_ok"] == "0" and d_["filled"] == "1" and d_["near"] == "0"


def test_table_bom_is_dropped(tmp_path):
    body = "﻿| 목록 | `web/a/list.jsp` | ? | ? |\n| 고치기 | `web/a/edit.jsp` | ? | ? |\n"
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    assert rc == 0 and fields(out)["screen_rows"] == "2" and fields(out)["file_ok"] == "2"


def test_table_bold_cells(tmp_path):
    body = HEAD + "| **목록** | **web/a/list.jsp** | ? | ? |\n| — | — | **/a/list.do** | **src/Ctl.java:3** |\n"
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == "1" and d["api_rows"] == "1" and d["file_ok"] == "1" and d["near"] == "1"


def test_table_rule_line_with_colons(tmp_path):
    r = proj(tmp_path)
    body = ("| 화면 | 화면 파일 | 주소 | 받는 코드 |\n|:---|:---:|---:|---|\n"
            "| 목록 | `web/a/list.jsp` | ? | ? |\n")
    rc, out = run(table(tmp_path, body), r)
    assert rc == 0 and fields(out)["screen_rows"] == "1" and fields(out)["odd"] == "0"
    body = "| a | b | c |\n| a | b | c |\n|:---|:---:|---:|\n"
    rc, out = run(table(tmp_path, body), r)
    assert rc == 0 and fields(out)["screen_rows"] == "0" and fields(out)["odd"] == "2"


@pytest.mark.parametrize("lead", [".../", "…/"])
def test_table_ellipsis_lead(tmp_path, lead):
    body = HEAD + "| 목록 | `%sa/list.jsp` | ? | ? |\n" % lead
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    assert rc == 0 and fields(out)["file_ok"] == "1"


def test_table_horizontal_bar_is_empty_value(tmp_path):
    body = HEAD + "| ― | ― | `/api/items` | `src/Ctl.java:10` |\n"
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    d = fields(out)
    assert rc == 0 and d["screen_rows"] == "0" and d["api_rows"] == "1" and d["near"] == "1"


def test_table_method_separator_dot(tmp_path):
    body = HEAD + "| — | — | `GET·POST /a/list.do` | `src/Ctl.java:3` |\n"
    rc, out = run(table(tmp_path, body), proj(tmp_path))
    d = fields(out)
    assert rc == 0 and d["near"] == "1" and d["addrs"] == "1" and d["near_addrs"] == "1"


def test_table_dotdot_paths_are_not_found(tmp_path):
    r = proj(tmp_path)
    body = HEAD + "| 가 | `../x/web/a/list.jsp` | ? | ? |\n| — | — | `/a/list.do` | `../x/src/Ctl.java:3` |\n"
    rc, out = run(table(tmp_path, body), r)
    d = fields(out)
    assert rc == 0 and d["file_ok"] == "0" and d["near"] == "0"


def test_table_read_limit(tmp_path):
    r = proj(tmp_path)
    big = ["pad"] * 200                      # 줄마다 4바이트 -> 800바이트
    big[2], big[149] = "/q/early", "/q/late"
    (r / "src/big.txt").write_text("\n".join(big) + "\n", encoding="utf-8")
    body = ("| s | src/big.txt:150 | ? | ? |\n| — | — | /q/early | src/big.txt:3 |\n"
            "| — | — | /q/late | src/big.txt:150 |\n")
    assert len(body.encode("utf-8")) < 400
    code = ("import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('table_under_test', sys.argv[1])\n"
            "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
            "assert mod.LIMIT == 8 * 1024 * 1024\n"
            "mod.LIMIT = int(sys.argv[2])\n"
            "sys.exit(mod.main(sys.argv[3:]))\n")
    p = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(TOOL), "400", str(table(tmp_path, body)), str(r)],
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    d = fields(p.stdout)
    assert p.returncode == 0 and d["screen_rows"] == "1" and d["api_rows"] == "2"
    assert d["file_ok"] == "0" and d["filled"] == "2" and d["near"] == "1"
