import importlib.util, os, subprocess, sys, types
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "kit" / "scripts" / "check.py"
spec = importlib.util.spec_from_file_location("check", CHECK); ck = importlib.util.module_from_spec(spec); spec.loader.exec_module(ck)
NAME = "2026-11-18-date-search.md"
SIM = "| 만들 것 | 닮은 것 | 이어지는 길 | 따를 것 |\n|---|---|---|---|\n%s\n\n- 닿는 곳: `src/none/x.css` → used-by 확실 1"
TAIL = '점검 끝: 걸린 것 %d개 — 막지 않습니다. 채우거나 "못 함"이라고 적으세요'
def record(project, name=NAME, stage="review", state="open", scenes=(("S1", "목록에서 날짜로 찾는다", "됨"),),
           similar=None, drop=(), nl="\n"):
    if similar is None: similar = SIM % "| M1 | `src/board/list.jsp` | `board/list.jsp` → `/board/list.do` | 스타일: `list_st1` |"
    lines = ["# date-search", ""]
    if "stage" not in drop: lines.append("- 지금 단계: " + stage)
    if "state" not in drop: lines.append("- 상태: " + state)
    lines += ["- 크기: 기능 하나", ""]
    body = {"요청": "날짜로 찾게 해 주세요",
            "장면": "| 번호 | 장면 | 결과 | 본 것 |\n|---|---|---|---|" + "".join("\n| %s | %s | %s | |" % s for s in scenes),
            "세 칸": "### 만들 것\n\n### 요청에 없지만 정해야 하는 것\n\n### 안 만들 것",
            "닮은 것과 꺼낸 규칙": similar, "조각": "", "확인": "", "검토": ""}
    for h in ck.work.HEADINGS:
        if h not in drop: lines += ["## " + h, "", body[h], ""]
    p = project / ".devkit" / "work" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(nl.join("\n".join(lines).split("\n")).encode("utf-8"))
    return p
def write_map(project):
    mp = project / ".devkit" / "screenmap.json"; mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text("{}", encoding="utf-8"); return mp
@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"; (p / "src" / "board").mkdir(parents=True)
    (p / "src" / "board" / "list.jsp").write_text("<p>목록</p>", encoding="utf-8"); return p
@pytest.fixture
def fake_map(monkeypatch):
    calls = []
    def use(result=(), exc=None, has=True):
        m = types.ModuleType("screenmap")
        def stale(root, map_path):
            calls.append((root, map_path))
            if exc: raise exc
            return list(result)
        if has: m.stale = stale
        monkeypatch.setitem(sys.modules, "screenmap", m); return calls
    return use
# ---- 기록 하나 ----
def test_clean_record(project):
    assert ck.check_record(project, record(project)) == {"name": NAME, "stage": "review", "problems": [], "all_unverified": False}
def test_missing_heading(project):
    assert ck.check_record(project, record(project, drop=("검토",)))["problems"] == ["제목 줄 없음: ## 검토"]
def test_missing_stage_and_state_lines(project):
    assert ck.check_record(project, record(project, drop=("stage", "state")))["problems"] == ["머리 줄 없음: 지금 단계", "머리 줄 없음: 상태"]
def test_bad_stage_value(project):
    probs = ck.check_record(project, record(project, stage="done"))["problems"]
    assert len(probs) == 1 and probs[0].startswith("머리 줄") and "지금 단계" in probs[0]
def test_scene_results_after_verify(project):
    sc = (("S1", "a", ""), ("S2", "b", "됐음"), ("S3", "c", "됨"))
    assert ck.check_record(project, record(project, scenes=sc))["problems"] == [
        "장면 S1: 결과 칸이 비었음", '장면 S2: 결과 칸이 네 말 중 하나가 아님 ("됐음")']
@pytest.mark.parametrize("stage,state,n", [("build", "open", 0), ("verify", "open", 0), ("build", "closed", 1), ("wrap-up", "open", 1)])
def test_when_scenes_are_checked(project, stage, state, n):
    p = record(project, stage=stage, state=state, scenes=(("S1", "a", ""),))
    assert len(ck.check_record(project, p)["problems"]) == n
def test_no_scenes_after_verify(project):
    assert ck.check_record(project, record(project, stage="wrap-up", scenes=()))["problems"] == ["장면이 하나도 없음"]
def test_all_unverified_on_top(project):
    record(project, scenes=(("S1", "a", "확인 못 함"), ("S2", "b", "확인 못 함")))
    lines = ck.report(project)
    assert lines[0] == '! 모든 장면이 "확인 못 함"입니다: ' + NAME and lines[1] == "devkit 점검: proj"
def test_similar_files_must_exist(project):
    rows = ("| M1 | `src/board/list.jsp` | `web/none/a.jsp` → `/a.do` | 스타일: `css/none.css` |\n"
            "| M2 | `src/gone.jsp:12` | | |\n| M3 | 없음 — 새로 만든다 | | |\n| M4 | `https://a.b/c` `${ctx}/a.js` `ls -al` `list.jsp` | | |")
    assert ck.check_record(project, record(project, similar=SIM % rows))["problems"] == ["없는 파일: `src/gone.jsp` (닮은 것과 꺼낸 규칙)"]
def test_broken_record_does_not_crash(project):
    p = project / ".devkit" / "work" / NAME; p.parent.mkdir(parents=True); p.write_bytes(b"\xff\xfe\x00 junk")
    probs = ck.check_record(project, p)["problems"]
    assert "머리 줄 없음: 지금 단계" in probs and "제목 줄 없음: ## 요청" in probs
def test_korean_path_crlf_record(tmp_path):
    p = tmp_path / "한글 프로젝트"; (p / "src" / "board").mkdir(parents=True)
    (p / "src" / "board" / "list.jsp").write_text("x", encoding="utf-8")
    assert ck.check_record(p, record(p, nl="\r\n"))["problems"] == []
# ---- 경로 고르기와 규칙 ----
def test_path_refs():
    text = "a `x/y.jsp` b `z.py` `/abs/p.js` `a b/c` `d/e.css:3-9`\n`f/*.jsp` `./g/h.js`"
    assert ck.path_refs(text) == [("x/y.jsp", 1), ("d/e.css", 1), ("g/h.js", 2)]
def test_rules_example_files(project):
    d = project / ".devkit" / "rules"; d.mkdir(parents=True)
    (d / "look.md").write_bytes(("# 화면 모양\r\n\r\n- 목록은 표 하나 — 예: `src/board/list.jsp` · 4/5곳 · 센 명령: `grep -rl list_st1 src/none | wc -l`\r\n"
        "- 버튼은 `btn/base.css`를 쓴다 — 예: `src/old/btn.jsp` · 3/3곳 · 센 명령: `grep -rl btn src/old | wc -l`\r\n").encode("utf-8"))
    (d / "index.md").write_text("# 규칙 목록\n\n- `look.md` — 화면 모양\n", encoding="utf-8")
    (d / "x.md").write_bytes(b"- \xff\xfe " + "— 예: `src/none.jsp` · 1/1곳".encode("utf-8"))
    assert ck.check_rules(project) == ["없는 파일: `src/old/btn.jsp` (rules/look.md 4줄)", "없는 파일: `src/none.jsp` (rules/x.md 1줄)"]
# ---- 화면 지도 ----
def test_map_missing_is_note(project):
    (project / ".devkit").mkdir()
    assert ck.check_map(project) == {"problems": [], "notes": ["화면 지도 없음 — 낡았는지 보지 않았습니다"]}
def test_map_stale(project, fake_map):
    mp = write_map(project); calls = fake_map([{"path": "web/a.jsp", "why": "지도에 없음"}, {"path": "web/b.jsp", "why": "지워짐"}])
    assert ck.check_map(project) == {"problems": ["화면 지도가 낡음: 화면 파일 2개가 지도와 다름 (web/a.jsp 지도에 없음, web/b.jsp 지워짐)"], "notes": []}
    assert calls == [(project, mp)]
def test_map_stale_long_list_is_cut(project, fake_map):
    write_map(project); fake_map([{"path": "p%d" % i, "why": "지도보다 새로움"} for i in range(1, 8)])
    assert ck.check_map(project)["problems"] == ["화면 지도가 낡음: 화면 파일 7개가 지도와 다름 (p1 지도보다 새로움, p2 지도보다 새로움, p3 지도보다 새로움, p4 지도보다 새로움, p5 지도보다 새로움 외 2개)"]
def test_map_unreadable(project, fake_map):
    write_map(project); fake_map([{"path": "", "why": "지도를 읽지 못함"}])
    assert ck.check_map(project) == {"problems": ["화면 지도를 읽지 못함 — 다시 만들어야 합니다"], "notes": []}
def test_map_fresh(project, fake_map):
    write_map(project); fake_map([])
    assert ck.check_map(project) == {"problems": [], "notes": []}
@pytest.mark.parametrize("kind,note", [("none", "screenmap.py를 불러오지 못함"), ("nostale", "screenmap.py에 stale이 없음"), ("raise", "ValueError"), ("shape", "TypeError")])
def test_map_check_cannot_run(project, fake_map, monkeypatch, kind, note):
    write_map(project)
    if kind == "none": monkeypatch.setitem(sys.modules, "screenmap", None)
    elif kind == "nostale": fake_map(has=False)
    elif kind == "shape": fake_map(["web/a.jsp"])
    else: fake_map(exc=ValueError("x"))
    assert ck.check_map(project) == {"problems": [], "notes": ["화면 지도 낡음 검사 못 함: " + note]}
# ---- 모아 찍기와 명령 ----
def test_report_layout(project):
    record(project, drop=("검토",))
    assert ck.report(project) == ["devkit 점검: proj", "기록 %s (지금 단계: review)" % NAME, "  - 제목 줄 없음: ## 검토",
        "규칙", "  · 규칙 폴더 없음 — 보지 않았습니다", "화면 지도", "  · 화면 지도 없음 — 낡았는지 보지 않았습니다", TAIL % 1 + " · 보지 못한 것 2개"]
def test_report_clean(project):
    record(project); lines = ck.report(project)
    assert lines[2] == "  걸린 것 없음" and lines[-1] == "점검 끝: 걸린 것 없음 · 보지 못한 것 2개"
    assert lines[-1].startswith("점검 끝: 걸린 것 없음")
def test_report_last_line_without_notes_is_unchanged(project, fake_map):
    record(project); (project / ".devkit" / "rules").mkdir(); write_map(project); fake_map([])
    assert ck.report(project)[-1] == "점검 끝: 걸린 것 없음"
def test_report_counts_map_notes(project, fake_map):
    record(project); (project / ".devkit" / "rules").mkdir(); write_map(project); fake_map(exc=ValueError("x"))
    assert ck.report(project)[-1] == "점검 끝: 걸린 것 없음 · 보지 못한 것 1개"
def test_report_problems_and_notes_both_counted(project, fake_map):
    record(project, drop=("검토",)); (project / ".devkit" / "rules").mkdir(); write_map(project); fake_map(has=False)
    assert ck.report(project)[-1] == TAIL % 1 + " · 보지 못한 것 1개"
def test_default_checks_open_records_only(project):
    record(project); record(project, name="2026-11-17-old.md", state="closed", stage="wrap-up")
    assert [l for l in ck.report(project) if l.startswith("기록 ")] == ["기록 %s (지금 단계: review)" % NAME]
def test_no_open_records(project):
    record(project, state="closed", stage="wrap-up")
    assert "열린 작업 기록 없음" in ck.report(project)
def test_record_option_reads_closed_record(project, capsys):
    record(project, name="2026-11-17-old.md", state="closed", stage="wrap-up")
    assert ck.main([str(project), "--record", "2026-11-17-old.md"]) == 0
    assert "기록 2026-11-17-old.md (지금 단계: wrap-up)" in capsys.readouterr().out
@pytest.mark.parametrize("name", ["../x.md", "2026-11-18-none.md", "Date.md"])
def test_record_option_bad_name_is_usage_error(project, name, capsys):
    record(project)
    assert ck.main([str(project), "--record", name]) == 2 and "기록" in capsys.readouterr().err
def test_not_a_folder(tmp_path):
    assert ck.main([str(tmp_path / "없음")]) == 2
def test_no_devkit_folder_touches_nothing(project, capsys):
    before = sorted(project.rglob("*"))
    assert ck.main([str(project)]) == 0
    assert "`.devkit` 폴더 없음 — 점검할 것이 없습니다" in capsys.readouterr().out
    assert sorted(project.rglob("*")) == before and not (project / ".devkit").exists()
def test_check_writes_nothing(project):
    (project / ".svn").mkdir(); record(project); write_map(project)
    snap = lambda: sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in project.rglob("*"))
    before = snap(); ck.report(project); assert snap() == before
def test_unexpected_error_still_exits_zero(project, monkeypatch, capsys):
    record(project)
    def boom(_): raise RuntimeError("x")
    monkeypatch.setattr(ck, "check_rules", boom)
    assert ck.main([str(project)]) == 0 and "점검을 끝내지 못함: RuntimeError" in capsys.readouterr().out
def test_cli_on_ascii_console(project):
    record(project)
    out = subprocess.run([sys.executable, str(CHECK), str(project)], capture_output=True, env=dict(os.environ, PYTHONIOENCODING="ascii"))
    assert out.returncode == 0 and out.stdout.decode("utf-8").splitlines()[-1] == "점검 끝: 걸린 것 없음 · 보지 못한 것 2개"
# ---- 이름을 댄 점검과 열린 채 남은 다른 기록 ----
OLD = "2026-11-17-old.md"
def test_record_option_names_other_open_records(project):
    record(project); record(project, name=OLD, stage="build")
    assert ck.report(project, NAME) == ["devkit 점검: proj", "기록 %s (지금 단계: review)" % NAME, "  걸린 것 없음",
        "다른 열린 기록 — 이번 점검이 보지 않았습니다", "  · %s (지금 단계: build)" % OLD,
        "규칙", "  · 규칙 폴더 없음 — 보지 않았습니다", "화면 지도", "  · 화면 지도 없음 — 낡았는지 보지 않았습니다",
        "점검 끝: 걸린 것 없음 · 보지 못한 것 2개 · 열린 채 남은 다른 기록 1개"]
def test_other_open_records_tail_without_notes(project, fake_map):
    record(project, stage="build", state="closed"); record(project, name=OLD, stage="find")
    (project / ".devkit" / "rules").mkdir(); write_map(project); fake_map([])
    assert ck.report(project, NAME)[-1] == "점검 끝: 걸린 것 없음 · 열린 채 남은 다른 기록 1개"
def test_other_open_records_with_problems(project):
    record(project, drop=("검토",)); record(project, name=OLD, stage="find"); record(project, name="2026-11-16-older.md", stage="verify")
    lines = ck.report(project, NAME)
    assert [l for l in lines if l.startswith("  · 2026")] == ["  · 2026-11-16-older.md (지금 단계: verify)", "  · %s (지금 단계: find)" % OLD]
    assert lines[-1] == TAIL % 1 + " · 보지 못한 것 2개 · 열린 채 남은 다른 기록 2개"
def test_closed_others_and_default_mode_are_unchanged(project):
    record(project); record(project, name=OLD, state="closed", stage="wrap-up")
    assert ck.report(project, NAME) == ck.report(project)
    record(project, name="2026-11-16-older.md", stage="build")
    lines = ck.report(project)
    assert "다른 열린 기록 — 이번 점검이 보지 않았습니다" not in lines and lines[-1] == "점검 끝: 걸린 것 없음 · 보지 못한 것 2개"
def test_cli_record_option_names_other_open_records(project, capsys):
    record(project); record(project, name=OLD, stage="build")
    assert ck.main([str(project), "--record", NAME]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "  · %s (지금 단계: build)" % OLD in out and out[-1].endswith(" · 열린 채 남은 다른 기록 1개")
# ---- 긴 길인데 검토가 빈 기록 ----
LONG = "긴 길인데 `## 검토`가 비었음 — 확인·검토·보안 훑기를 안 했으면 기록을 다시 열고 안 한 단계(`devkit:verify`·`devkit:review`)부터 읽는다"
def with_path(p, path, review=""):
    t = p.read_text(encoding="utf-8").replace("## 요청\n\n", "## 요청\n\n- 길: %s\n\n" % path, 1)
    p.write_text(t.rstrip("\n") + ("\n\n" + review if review else "") + "\n", encoding="utf-8")
@pytest.mark.parametrize("stage,state,path,review,hit", [
    ("wrap-up", "open", "긴 길 — 파일 올리고 내리기", "", True), ("build", "closed", "긴 길 — 큰 일", "", True),
    ("review", "open", "긴 길 — 로그인", "", False), ("build", "open", "긴 길 — 로그인", "", False),
    ("wrap-up", "closed", "짧은 길", "", False), ("build", "closed", "짧은 길", "", False),
    ("wrap-up", "closed", "긴 길 — 돈", "- 본 눈: 새 눈", False)])
def test_long_path_needs_review(project, stage, state, path, review, hit):
    with_path(record(project, stage=stage, state=state), path, review)
    assert (LONG in ck.check_record(project, project / ".devkit" / "work" / NAME)["problems"]) is hit
def test_record_without_path_line_is_not_flagged(project):
    record(project, stage="wrap-up", state="closed")
    assert ck.check_record(project, project / ".devkit" / "work" / NAME)["problems"] == []
def test_long_path_without_review_in_report(project):
    with_path(record(project, stage="wrap-up", state="closed"), "긴 길 — 파일 올리고 내리기")
    lines = ck.report(project, NAME)
    assert "  - " + LONG in lines and lines[-1] == TAIL % 1 + " · 보지 못한 것 2개"
def test_path_words_inside_a_line_are_not_the_path_line(project):
    p = record(project, stage="wrap-up", state="closed")
    p.write_text(p.read_text(encoding="utf-8").replace("날짜로 찾게", "기록에 - 길: 긴 길 이라고 적고 날짜로 찾게", 1), encoding="utf-8")
    assert ck.check_record(project, p)["problems"] == []
