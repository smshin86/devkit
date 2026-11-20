import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "kit" / "scripts" / "screenmap.py"
spec = importlib.util.spec_from_file_location("screenmap", SCRIPT); sm = importlib.util.module_from_spec(spec); spec.loader.exec_module(sm)
FIX = ROOT / "tests" / "fixtures" / "site"
J = "web/WEB-INF/jsp/"          # 지도 안 경로의 앞부분


# ---- 과제 1: 파일 한 개를 읽어 낸다 ----

def scan(rel): return sm.scan_markup(sm.read_text(FIX / J / rel))

def test_scan_layout_with_own_head():
    m = scan("la/a/subLayout.jsp")
    assert m["head"] is True
    assert m["loads"] == ["/css/common.css", "/css/board.css", "/js/a/jquery.min.js", "/js/confirm.js", "/css/web/${ctx}/layout.css"]
    assert m["includes"] == [{"target": "header.jsp", "dynamic": False}, {"target": "/WEB-INF/jsp/${content}", "dynamic": True}]

def test_scan_head_file_multiline_tag_and_c_url():
    m = scan("la/common/meta.jsp")
    assert m["head"] is True
    assert m["loads"] == ["/css/common.css", "/js/b/jquery.min.js", "/js/form.js"]

def test_scan_fragment_keeps_unfollowable_includes_but_not_external():
    m = scan("bk/list.jsp")
    assert m == {"head": False, "loads": [], "includes": [
        {"target": "part.jsp", "dynamic": False}, {"target": "/common/fileUpload.do", "dynamic": False}]}

def test_read_text_survives_non_utf8():
    assert scan("bk/euckr.jsp")["loads"] == ["/js/part.js"]


# ---- 과제 2: 프로젝트 전체를 훑어 지도를 만든다 ----

def test_build_shape_and_skip():
    m = sm.build(FIX)
    assert set(m) == {"version", "built_at", "pages"}
    assert J + "bk/list.jsp" in m["pages"] and not any("node_modules" in p for p in m["pages"])
    incs = m["pages"][J + "bk/list.jsp"]["includes"]
    assert [i["file"] for i in incs] == [J + "bk/part.jsp", None]

def test_closure_loads_head_follow_includes_and_survive_cycles():
    m = sm.build(FIX)
    assert sm.loads_of(m, J + "bk/list.jsp") == ["/js/part.js"]
    assert sm.loads_of(m, J + "la/a/subLayout.jsp")[-1] == "/js/menu.js"      # header.jsp ↔ subLayout.jsp 순환
    b = J + "la/b/subLayout.jsp"
    assert m["pages"][b]["head"] is False and sm.has_head(m, b) is True
    assert sm.loads_of(m, b) == ["/css/web/${ctx}/layout.css", "/css/common.css", "/js/b/jquery.min.js", "/js/form.js"]

def test_is_wrapper():
    m = sm.build(FIX)
    # header.jsp는 subLayout.jsp를 그대로 끼워 넣으므로(순환) 그것도 틀이다
    assert [p[len(J):] for p in sorted(m["pages"]) if sm.is_wrapper(m, p)] == [
        "la/a/header.jsp", "la/a/subLayout.jsp", "la/b/subLayout.jsp", "la/c/mainLayout.jsp"]

def test_cli_build_writes_map(tmp_path):
    out = tmp_path / "map.json"
    r = subprocess.run([sys.executable, str(SCRIPT), "build", str(FIX), "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(out.read_text(encoding="utf-8"))["version"] == 1
    assert "화면 파일 9개를 적었습니다 (다른 화면을 끼워 넣는 틀 4개)" in r.stdout


# ---- 과제 3: 화면 하나를 찾아본다 ----

EXPECTED_LIST_LOOKUP = """화면: web/WEB-INF/jsp/bk/list.jsp
종류: 조각 — 스스로 <head>가 없다. 실행 중에 틀 안에 끼워져서 보인다.
이 화면이 불러오는 파일 (그대로 끼워 넣은 조각 것 포함):
  /js/part.js
따라가지 못한 끼워 넣기 (이 안에서 무엇을 불러오는지는 지도에 없다):
  /common/fileUpload.do
이 화면을 그대로 끼워 넣는 파일: 없음
다른 화면을 실행 중에 끼워 넣는 틀: 3묶음
  [web/WEB-INF/jsp/la/*/subLayout.jsp] 2개 — 끼워 넣는 대상: /WEB-INF/jsp/${content}
    2/2  /css/common.css
    2/2  jquery.min.js (경로 2가지)
    2/2  /css/web/${ctx}/layout.css
    1/2  /css/board.css
    1/2  /js/confirm.js
    1/2  /js/form.js
    1/2  /js/menu.js
  [web/WEB-INF/jsp/la/*/header.jsp] 1개 — 끼워 넣는 대상: /WEB-INF/jsp/${content}
    1/1  /css/board.css
    1/1  /css/common.css
    1/1  /js/confirm.js
    1/1  /js/a/jquery.min.js
    1/1  /css/web/${ctx}/layout.css
    1/1  /js/menu.js
  [web/WEB-INF/jsp/la/*/mainLayout.jsp] 1개 — 끼워 넣는 대상: /WEB-INF/jsp/la/${ctx}/main.jsp
    1/1  /css/main.css
읽는 법: "1/2"는 그 묶음의 틀 2개 중 1개가 불러온다는 뜻이다. 경로가 달라도 파일 이름이 같으면 한 줄로 합쳤다.
어느 묶음이 이 화면을 감싸는지는 지도에 없다. 이 화면을 돌려주는 서버 코드에서 틀 이름을 확인한다.
틀 전부가 불러오지는 않는 파일에 기대게 되면, 같은 모양의 이웃 화면이 어떻게 하는지 따르고 그 사실을 보고에 적는다.
조건이 붙은 불러오기(특정 경우에만)와 스크립트가 실행 중에 불러오는 것은 구분하지 못한다."""

def test_lookup_fragment_exact_text():
    out = sm.lookup(sm.build(FIX), J + "bk/list.jsp")
    assert out.splitlines()[:-1] == EXPECTED_LIST_LOOKUP.splitlines()
    assert out.splitlines()[-1].startswith("지도를 만든 때: ")

def test_lookup_wrapper_has_no_group_section():
    out = sm.lookup(sm.build(FIX), J + "la/a/subLayout.jsp")
    assert "종류: 틀 — " in out and "묶음" not in out and "/js/menu.js" in out

def test_lookup_head_file_kind_and_includers():
    out = sm.lookup(sm.build(FIX), J + "la/common/meta.jsp")
    assert "종류: 스스로 <head>가 있는 파일" in out and "  " + J + "la/b/subLayout.jsp" in out and "3묶음" in out

def test_lookup_file_filter():
    m = sm.build(FIX)
    out = sm.lookup(m, J + "bk/list.jsp", file_filter="JQUERY")
    assert "    1/2  /js/a/jquery.min.js" in out and "    1/2  /js/b/jquery.min.js" in out
    assert "    0/1  JQUERY — 불러오는 틀 없음" in out          # mainLayout 묶음
    assert "    0/2  fileDownload — 불러오는 틀 없음" in sm.lookup(m, J + "bk/list.jsp", file_filter="fileDownload")

def test_find_page_forms():
    m = sm.build(FIX)
    assert sm.find_page(m, "bk/list.jsp") == [J + "bk/list.jsp"]
    assert sm.find_page(m, str(FIX / J / "bk/list.jsp"), FIX) == [J + "bk/list.jsp"]
    assert sm.find_page(m, "subLayout.jsp") == [J + "la/a/subLayout.jsp", J + "la/b/subLayout.jsp"]
    assert sm.find_page(m, "ist.jsp") == []          # 칸 경계에서만 맞춘다

def test_cli_lookup_and_errors(tmp_path):
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, text=True)
    mp = str(tmp_path / "m.json")
    r = run("lookup", str(FIX), "bk/list.jsp", "--map", mp)
    assert r.returncode == 1 and "지도가 없습니다" in r.stdout
    run("build", str(FIX), "--out", mp)
    assert run("lookup", str(FIX), "bk/list.jsp", "--map", mp).returncode == 0
    assert run("lookup", str(FIX), "nope.jsp", "--map", mp).returncode == 1
    r = run("lookup", str(FIX), "subLayout.jsp", "--map", mp)
    assert r.returncode == 1 and "여러 개가 걸립니다" in r.stdout


# ---- 검토에서 나온 구멍: 소리 없이 빠뜨리던 꼴들 ----

def test_scan_tags_with_gt_inside_attribute_values():
    text = """<script src="<%=request.getContextPath()%>/js/a.js"></script>
<script src="/js/b.js?v=<%=ver%>"></script>
<link href="<c:out value='${ctx}'/>/css/c.css">
<script src="<spring:url value="/js/d.js"/>"></script>
<c:url value='/a.do' var="u"/>
<script src='/js/z.js'></script>
<script src=/js/f.js></script>
<SCRIPT SRC=" /JS/G.JS "></SCRIPT>"""
    assert sm.scan_markup(text)["loads"] == [
        "${request.getContextPath()}/js/a.js", "/js/b.js", "${ctx}/css/c.css", "/js/d.js", "/js/z.js", "/js/f.js", "/JS/G.JS"]

def test_scan_includes_in_any_attribute_order():
    text = """<jsp:include flush="true" page="x.jsp"/>
<c:import var="v" url="/WEB-INF/${content}"/>
<jsp:directive.include file="z.jsp"/>
<jsp:include page="<%=path%>"/>"""
    assert sm.scan_markup(text)["includes"] == [
        {"target": "x.jsp", "dynamic": False}, {"target": "/WEB-INF/${content}", "dynamic": True},
        {"target": "z.jsp", "dynamic": False}, {"target": "${path}", "dynamic": True}]

def _site(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return sm.build(tmp_path)

def test_wrapper_whose_slot_lives_in_a_static_fragment(tmp_path):
    m = _site(tmp_path, {
        "la/x/layout.jsp": '<head></head><%@ include file="body.jsp" %>',
        "la/x/body.jsp": '<c:import url="/WEB-INF/${content}"/>'})
    assert sm.is_wrapper(m, "la/x/layout.jsp") and not sm.is_wrapper(m, "la/x/body.jsp")
    assert sm.wrapper_groups(m)[0]["slots"] == ["/WEB-INF/${content}"]

def test_two_part_paths_group_together(tmp_path):
    page = '<head></head><jsp:include page="${c}"/>'
    m = _site(tmp_path, {"a/layout.jsp": page, "b/layout.jsp": page, "top.jsp": page})
    assert [(g["pattern"], len(g["files"])) for g in sm.wrapper_groups(m)] == [("*/layout.jsp", 2), ("top.jsp", 1)]

def test_cli_refuses_missing_project_and_broken_map(tmp_path):
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, text=True)
    r = run("build", str(tmp_path / "nope"))
    assert r.returncode == 1 and "프로젝트 폴더가 없습니다" in r.stdout and not (tmp_path / "nope").exists()
    bad = tmp_path / "bad.json"; bad.write_text("{", encoding="utf-8")
    r = run("lookup", str(FIX), "bk/list.jsp", "--map", str(bad))
    assert r.returncode == 1 and "지도 파일을 읽지 못했습니다" in r.stdout


# ---- P2: .claude 건너뛰기, 한글 경로·CRLF·cp949 ----

def test_build_skips_claude_but_not_folders_holding_git(tmp_path):
    m = _site(tmp_path, {"web/a.jsp": "<p>", ".claude/worktrees/w1/web/a.jsp": "<p>", "sub/.claude/b.jsp": "<p>",
                         "vendor/lib/.git/HEAD": "ref", "vendor/lib/c.jsp": "<p>"})
    assert list(m["pages"]) == ["vendor/lib/c.jsp", "web/a.jsp"]      # Spec 13: .git을 품은 폴더는 버리지 않는다

def _korean(tmp_path):
    (tmp_path / "화면").mkdir()
    (tmp_path / "화면/목록.jsp").write_bytes(
        '<%@ include\r\n file="조각.jsp" %>\r\n<link\r\n href="/css/한.css"\r\n rel="stylesheet">\r\n'.encode("utf-8"))
    (tmp_path / "화면/조각.jsp").write_bytes('<!-- 조각 --><script src="/js/part.js"></script>\r\n'.encode("cp949"))
    return sm.build(tmp_path)

def test_korean_path_crlf_and_cp949_file(tmp_path):
    m = _korean(tmp_path)
    assert list(m["pages"]) == ["화면/목록.jsp", "화면/조각.jsp"]
    assert m["pages"]["화면/목록.jsp"]["loads"] == ["/css/한.css"]
    assert m["pages"]["화면/목록.jsp"]["includes"] == [{"target": "조각.jsp", "dynamic": False, "file": "화면/조각.jsp"}]
    assert m["pages"]["화면/조각.jsp"]["loads"] == ["/js/part.js"]


# ---- P2: 스타일·스크립트 주소와 파일 경로의 "이름이 맞는다" ----

NAME_CASES = [
    ("/css/common.css", "web/css/common.css", {"matched": 2, "cut": False, "front": False}),
    ("/js/a/jquery.min.js", "web/js/a/jquery.min.js", {"matched": 3, "cut": False, "front": False}),
    ("/js/a/jquery.min.js", "web/js/b/jquery.min.js", None),          # 폴더가 다르면 이름이 같아도 아니다
    ("/gb/css/common.css", "src/main/webapp/css/common.css", {"matched": 2, "cut": False, "front": True}),
    ("/x/y/common.css", "web/css/common.css", None),                  # 앞 칸이 둘 남으면 아니다
    ("/a/common.css", "web/css/common.css", None),                    # 한 칸 남는데 맞은 것이 이름뿐이면 아니다
    ("/css/web/${ctx}/layout.css", "web/css/web/a/layout.css", {"matched": 1, "cut": True, "front": False}),
    ("${ctx}/css/Common.CSS", "web/css/common.css", {"matched": 2, "cut": True, "front": False}),
    ("../css/common.css", "web/css/common.css", {"matched": 2, "cut": True, "front": False}),
    ("/js/${name}.js", "web/js/a.js", None),
    ("https://cdn.example.com/css/common.css", "web/css/common.css", None),
    ("//cdn.example.com/css/common.css", "web/css/common.css", None),
    ("/css/common.css", "web\\css\\common.css", {"matched": 2, "cut": False, "front": False}),
    ("/css/한글/목록.css", "웹/css/한글/목록.css", {"matched": 3, "cut": False, "front": False}),
]

def test_name_match_rule():
    for load, target, want in NAME_CASES:
        assert sm.name_match(load, target) == want, (load, target)


# ---- P2: used-by (거꾸로 찾기) ----

USED = {
    "web/WEB-INF/jsp/la/sub/subLayout.jsp": '<html><head><link href="${ctx}/css/common.css" rel="stylesheet"></head>'
                                            '<body><jsp:include page="/WEB-INF/jsp/${content}"/></body></html>',
    "web/WEB-INF/jsp/la/main/subLayout.jsp": '<head><%@ include file="/WEB-INF/jsp/inc/meta.jsp" %></head>'
                                             '<jsp:include page="/WEB-INF/jsp/${content}"/>',
    "web/WEB-INF/jsp/inc/meta.jsp": '<link href="/css/common.css">\n<script src="/js/a/jquery.min.js"></script>',
    "web/WEB-INF/jsp/bbs/row.jsp": '<td class="list_st1">x</td><script src="/js/bbs/row.js"></script>',
    "web/WEB-INF/jsp/bbs/table.jsp": '<%@ include file="row.jsp" %>',
    "web/WEB-INF/jsp/bbs/list.jsp": '<%@ include file="table.jsp" %>',
    "web/WEB-INF/jsp/bbs/old.jsp": '<link href="/gb/css/common.css">',
    "web/WEB-INF/jsp/etc/other.jsp": '<script src="/js/b/jquery.min.js"></script>',
}
def _used(tmp_path):
    m = _site(tmp_path, USED); m["built_at"] = "T"; return m
B = "web/WEB-INF/jsp/"
NOSEE = "지도가 못 보는 길: 스타일 안의 @import, 스크립트가 실행 중에 불러오는 것, 조건이 붙은 불러오기, 이름에 변수가 든 주소, 서버 코드가 고르는 틀"

EXPECTED_COMMON = "\n".join([
    "파일: web/css/common.css",
    "찾은 길: 화면이 불러오는 주소의 끝과 이 파일 경로의 끝을 맞춰 골랐다 — 이름이 맞아서 고른 것이다. 주소가 정말 이 파일을 가리키는지는 그 화면을 열어 확인한다.",
    "주소가 맞은 화면 3개:",
    f"  {B}bbs/old.jsp  ← /gb/css/common.css  (맨 앞 한 칸은 사이트 주소로 보고 뺐다)",
    f"  {B}inc/meta.jsp  ← /css/common.css",
    f"  {B}la/sub/subLayout.jsp  ← ${{ctx}}/css/common.css  (주소 앞부분에 변수·상대 경로가 있어 뒤 2칸만 맞췄다)",
    "그 화면을 그대로 끼워 넣어 함께 쓰는 화면 1개 (이름이 맞아서 고른 것에서 이어짐):",
    f"  {B}la/main/subLayout.jsp  (1칸 위)",
    "틀에서 멈춤 2개 — 이 틀이 실행 중에 끼워 넣는 화면은 지도에 없어 더 따라가지 못했다. 그 틀 이름을 돌려주는 서버 코드에서 화면을 찾는다:",
    f"  {B}la/main/subLayout.jsp  [{B}la/*/subLayout.jsp 묶음 2개 중 2개]",
    f"  {B}la/sub/subLayout.jsp  [{B}la/*/subLayout.jsp 묶음 2개 중 2개]",
    NOSEE, "지도를 만든 때: T"])

EXPECTED_ROW = "\n".join([
    f"파일: {B}bbs/row.jsp",
    "찾은 길: 그대로 끼워 넣기를 거슬러 올라갔다 — 확실히 이어진 것이다.",
    "이 파일을 쓰는 화면 2개:", f"  {B}bbs/table.jsp  (1칸 위)", f"  {B}bbs/list.jsp  (2칸 위)",
    "틀에서 멈춤: 없음", NOSEE, "지도를 만든 때: T"])

def test_used_by_style_is_name_matched_and_stops_at_wrappers(tmp_path):
    m = _used(tmp_path); r = sm.used_by(m, "web/css/common.css")
    assert r["kind"] == "asset" and [s["page"] for s in r["seeds"]] == [B + "bbs/old.jsp", B + "inc/meta.jsp", B + "la/sub/subLayout.jsp"]
    out = sm.render_used_by(m, r)
    assert out == EXPECTED_COMMON
    assert "확실히" not in out and "0개" not in out                    # Focus 5: 짐작을 확실로, 멈춤을 0으로 보이지 않는다

def test_used_by_fragment_follows_many_steps_and_is_sure(tmp_path):
    m = _used(tmp_path); r = sm.used_by(m, "bbs/row.jsp")
    assert r["kind"] == "page" and r["pages"] == [{"page": B + "bbs/table.jsp", "steps": 1}, {"page": B + "bbs/list.jsp", "steps": 2}]
    assert sm.render_used_by(m, r) == EXPECTED_ROW

def test_used_by_script_other_folder_same_name_is_not_picked(tmp_path):
    m = _used(tmp_path); r = sm.used_by(m, "web/js/a/jquery.min.js")
    assert [s["page"] for s in r["seeds"]] == [B + "inc/meta.jsp"] and r["wrappers"] == [B + "la/main/subLayout.jsp"]
    assert "묶음 2개 중 1개" in sm.render_used_by(m, r)
    r = sm.used_by(m, "web/js/bbs/row.js")
    assert [p["page"] for p in r["pages"]] == [B + "bbs/table.jsp", B + "bbs/list.jsp"]
    assert "이름이 맞아서 고른 것에서 이어짐" in sm.render_used_by(m, r)

def test_used_by_zero_never_says_unused(tmp_path):
    m = _used(tmp_path)
    for t in ("web/js/none.js", "bbs/list.jsp"):                      # 틀에 실행 중에 끼워지는 화면도 0으로 나온다
        out = sm.render_used_by(m, sm.used_by(m, t))
        assert "지도에서 이어진 화면 0개 — 쓰는 곳이 없다는 뜻이 아니다." in out and NOSEE in out
        assert "쓰는 화면 없음" not in out and "틀에서 멈춤" not in out
    assert sm.used_by(m, "readme.txt")["kind"] == "none"
    r = sm.used_by(m, "subLayout.jsp"); assert r["kind"] == "many" and len(r["hits"]) == 2

def test_used_by_lists_every_includer_without_cut(tmp_path):
    files = {"frag.jsp": "<p>"}; files.update({f"p{i:02d}.jsp": '<%@ include file="frag.jsp" %>' for i in range(25)})
    m = _site(tmp_path, files); r = sm.used_by(m, "frag.jsp")
    assert [p["page"] for p in r["pages"]] == [f"p{i:02d}.jsp" for i in range(25)]
    out = sm.render_used_by(m, r); assert out.count("(1칸 위)") == 25 and "그 밖" not in out

def test_cli_used_by_korean_path_on_cp949_console(tmp_path):
    _korean(tmp_path); mp = tmp_path / "지도.json"
    env = dict(os.environ, PYTHONIOENCODING="cp949")
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, env=env)
    assert run("build", str(tmp_path), "--out", str(mp)).returncode == 0
    r = run("used-by", str(tmp_path), "화면/조각.jsp", "--map", str(mp))
    assert r.returncode == 0 and "화면/목록.jsp  (1칸 위)" in r.stdout.decode("utf-8") and r.stderr == b""
    r = run("used-by", str(tmp_path), "web/css/한.css", "--map", str(mp))
    assert r.returncode == 0 and "이름이 맞아서 고른 것" in r.stdout.decode("utf-8")
    assert run("used-by", str(tmp_path), "x.txt", "--map", str(mp)).returncode == 1
    assert run("used-by", str(tmp_path), "화면/조각.jsp", "--map", str(tmp_path / "no.json")).returncode == 1


# ---- P2: stale (지도가 낡았는가) ----

def test_stale_new_newer_deleted_and_missing_map(tmp_path):
    m = _site(tmp_path, {"a.jsp": "<p>", "b.jsp": "<p>", "c.jsp": "<p>"})
    mp = tmp_path / ".devkit" / "screenmap.json"; mp.parent.mkdir(); mp.write_text(json.dumps(m), encoding="utf-8")
    old, mid, new = 1_000_000_000, 1_000_000_100, 1_000_000_200
    for n in ("a.jsp", "b.jsp", "c.jsp"): os.utime(tmp_path / n, (old, old))
    os.utime(mp, (mid, mid))
    assert sm.stale(tmp_path, mp) == []
    os.utime(tmp_path / "b.jsp", (new, new)); (tmp_path / "c.jsp").unlink()
    (tmp_path / "d.jsp").write_text("<p>", encoding="utf-8"); os.utime(tmp_path / "d.jsp", (old, old))
    (tmp_path / "x.css").write_text("a{}", encoding="utf-8")                       # 화면 파일이 아니면 안 본다
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude/e.jsp").write_text("<p>", encoding="utf-8")
    assert sm.stale(tmp_path, mp) == [{"path": "b.jsp", "why": "지도보다 새로움"}, {"path": "c.jsp", "why": "지워짐"},
                                      {"path": "d.jsp", "why": "지도에 없음"}]
    assert sm.stale(tmp_path, tmp_path / "none.json") == [{"path": "", "why": "지도 없음"}]
    bad = tmp_path / "bad.json"; bad.write_text("{", encoding="utf-8")
    assert sm.stale(tmp_path, bad) == [{"path": "", "why": "지도를 읽지 못함"}]

def test_stale_korean_path(tmp_path):
    m = _korean(tmp_path); mp = tmp_path / "m.json"; mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    os.utime(mp, (2_000_000_000, 2_000_000_000)); assert sm.stale(tmp_path, mp) == []
    (tmp_path / "화면/새.jsp").write_text("<p>", encoding="utf-8"); os.utime(tmp_path / "화면/새.jsp", (1, 1))
    assert sm.stale(tmp_path, mp) == [{"path": "화면/새.jsp", "why": "지도에 없음"}]


# ---- 리뷰 고침: 이상한 파일, 망가진 지도 ----

def _odd_site(tmp_path):
    site = tmp_path / "site"; site.mkdir()
    (site / "a.jsp").write_text("<p>", encoding="utf-8")
    (site / "real.jsp").write_text("<p>", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("<p>", encoding="utf-8")
    os.symlink(str(site / "nowhere"), str(site / "broken.jsp"))
    os.symlink(str(tmp_path / "outside.txt"), str(site / "out.jsp"))
    os.symlink(str(site / "real.jsp"), str(site / "inside.jsp"))
    os.mkfifo(str(site / "pipe.jsp"))
    return site

def test_build_survives_odd_files(tmp_path):
    site = _odd_site(tmp_path)
    out = tmp_path / "map.json"
    r = subprocess.run([sys.executable, str(SCRIPT), "build", str(site), "--out", str(out)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stderr == ""
    assert sorted(json.loads(out.read_text(encoding="utf-8"))["pages"]) == ["a.jsp", "inside.jsp", "real.jsp"]
    assert "읽지 못해 건너뛴 파일 3개" in r.stdout

def test_build_without_odd_files_has_no_skipped_note(tmp_path):
    (tmp_path / "a.jsp").write_text("<p>", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "build", str(tmp_path), "--out", str(tmp_path / "m.json")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "건너뛴" not in r.stdout

def test_build_skips_big_and_unreadable(tmp_path):
    (tmp_path / "ok.jsp").write_text("<p>", encoding="utf-8")
    with open(str(tmp_path / "big.jsp"), "wb") as f: f.truncate(sm.MAX_FILE + 1)
    sk = []; m = sm.build(tmp_path, sk)
    assert list(m["pages"]) == ["ok.jsp"] and sk == ["big.jsp"] and "skipped" not in m
    (tmp_path / "locked.jsp").write_text("<p>", encoding="utf-8"); os.chmod(str(tmp_path / "locked.jsp"), 0)
    try:
        if os.access(str(tmp_path / "locked.jsp"), os.R_OK): return          # root면 막히지 않는다
        sk = []; m = sm.build(tmp_path, sk)
        assert list(m["pages"]) == ["ok.jsp"] and sk == ["big.jsp", "locked.jsp"]
    finally:
        os.chmod(str(tmp_path / "locked.jsp"), 0o644)

@pytest.mark.parametrize("page", [{"head": True, "loads": []}, {"head": True, "includes": []}, {"loads": [], "includes": []},
                                  {"head": True, "loads": "x", "includes": []}, {"head": True, "loads": [], "includes": [{"target": "x"}]},
                                  [], "x"])
def test_malformed_map_is_read_error_not_traceback(tmp_path, page):
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps({"version": 1, "built_at": "t", "pages": {"a.jsp": page}}), encoding="utf-8")
    for cmd in (("lookup", str(tmp_path), "a.jsp"), ("used-by", str(tmp_path), "a.jsp")):
        r = subprocess.run([sys.executable, str(SCRIPT), cmd[0], *cmd[1:], "--map", str(mp)], capture_output=True, text=True)
        assert r.returncode == 1 and "지도 파일을 읽지 못했습니다" in r.stdout and r.stderr == "", (cmd, r.stderr)
    mp.write_text(json.dumps({"version": 1, "built_at": "t", "pages": []}), encoding="utf-8")
    assert sm._read_map(mp)[0] is None

def test_build_does_not_hang_on_fifo(tmp_path):
    (tmp_path / "a.jsp").write_text("<p>", encoding="utf-8")
    os.mkfifo(str(tmp_path / "pipe.jsp"))
    r = subprocess.run([sys.executable, str(SCRIPT), "build", str(tmp_path), "--out", str(tmp_path / "m.json")],
                       capture_output=True, text=True, timeout=15)
    assert r.returncode == 0 and list(json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))["pages"]) == ["a.jsp"]
