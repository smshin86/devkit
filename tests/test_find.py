import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"   # 다른 시험 파일과 같은 꼴
FIND = KIT / "skills/find/SKILL.md"
GUIDE = KIT / "skills/find/first-guide.md"
TABLE = KIT / "skills/find/screen-table.md"
README = KIT / "README.md"
OLD_GUIDE = ROOT / "old/kit-0.2.0/skills/find/first-guide.md"
KNOWN = {p.name for p in (KIT / "skills").iterdir() if (p / "SKILL.md").is_file()}
FIND_END = "큰 일의 길에서 온 것이면 `devkit:start`의 길로 돌아가 만든다."
MDS = {"first-guide", "SKILL", "AGENTS", "CLAUDE", "DESIGN", "guide", "copilot-instructions", "screens", "screen-table"}
FRAME = ["# 길 안내", "## 어디에 무엇이", "## 대표 예 하나 — 화면에서 DB까지", "## 공통 부품", "## 스타일", "## 바깥과 닿는 곳", "## 조심할 곳", "## 돌리는 법", "## 못 본 것"]
TABLE_FRAME = ["# 화면 표", "",
               "- 쓴 때: <YYYY-MM-DD> · 화면 <n>개: `<화면 파일을 센 명령>` · 주소 <m>개: `<주소를 센 명령>`",
               "- 통째로 읽지 않고 화면 이름·주소로 검색한다. `?`는 못 찾은 칸이다.", "",
               "| 화면 | 화면 파일 | 주소 | 받는 코드 |", "|---|---|---|---|",
               "| <무슨 화면인지 한 마디> | `<경로>` | `<주소>` | `<경로:줄>` |"]
MAP_WORDS = ("screenmap", "lookup", "used-by", "check.py", "run-ok", "~/.devkit", ".devkit/rules", "앞 시험", "look.md", "나눠 살피기")
BED_WORDS = ("ihatemoney", "bill", "settle", "person", "weight", "password", "currency", "reminder", "지출", "정산", "환율", "참여자")
SKILL_FILES = [FIND, GUIDE, TABLE]
SKILL_IDS = ["SKILL", "first-guide", "screen-table"]


def text(p):
    return p.read_text(encoding="utf-8")


def frame_block(t):
    i = t.index("\n## 틀\n"); s = t.index("```\n", i) + 4; e = t.index("\n```", s)
    return t[s:e]


def section(b, head):
    return b.split(head + "\n", 1)[1].split("\n## ", 1)[0]


def test_find_front():
    L = text(FIND).splitlines()
    assert L[0] == "---" and L[1] == "name: find" and L[3] == "---"
    assert L[2].startswith("description: 한 장이 큰 일이라고 한 뒤에만") and ".devkit/guide.md" in L[2]
    assert L[4] == "`devkit:start`를 아직 안 읽었으면 먼저 읽는다."
    assert L[-1] == FIND_END


def test_find_lines():
    assert len(text(FIND).splitlines()) <= 90
    assert len(text(GUIDE).splitlines()) <= 100
    assert len(text(TABLE).splitlines()) <= 40


def test_find_keeps():
    L = text(FIND).splitlines()
    for h in ("## 언제 하나", "## 먼저 읽는 것", "## 자리", "## 살펴보는 법", "## 보고"):
        assert h in L, h
    assert "## 밖에서도 본다" not in L   # 이번 판은 프로젝트를 켜지 않는다
    assert "이번 판은 프로젝트를 켜지 않는다 — 화면 파일을 읽어 쓴다." in section(text(FIND), "## 살펴보는 법")
    t = text(FIND)
    assert "work.py init" in t and "[열어서 봄]" in t and "[파일만 읽음]" in t and "이번에 건드릴 곳만" in t
    G = text(GUIDE).splitlines()
    for h in ("## 언제 읽는가", "## 쓰는 자리", "## 보는 차례", "## 읽지 않는 것", "## 틀", "## 쓰는 법", "## 고칠 때"):
        assert h in G, h


def test_find_refs_known():
    for p in SKILL_FILES:
        t = text(p)
        assert set(re.findall(r"devkit:([a-z-]+)", t)) <= KNOWN, p.name
        pys = set(re.findall(r"([A-Za-z_]+)\.py\b", t)); assert pys <= {"work"}, p.name
        assert set(re.findall(r"([A-Za-z_-]+)\.md\b", t)) <= MDS, p.name
    assert "first-guide.md" in text(FIND) and (KIT / "scripts/work.py").is_file()


@pytest.mark.parametrize("p", SKILL_FILES, ids=SKILL_IDS)
def test_find_no_map_words(p):
    t = text(p)
    for w in MAP_WORDS:
        assert w not in t, (p.name, w)


@pytest.mark.parametrize("p", SKILL_FILES, ids=SKILL_IDS)
def test_find_no_testbed_words(p):
    t = text(p).lower()
    for w in BED_WORDS:
        assert w not in t, (p.name, w)


def test_guide_frame_fixed():
    b = frame_block(text(GUIDE))
    assert [l for l in b.splitlines() if l.startswith("# ") or l.startswith("## ")] == FRAME
    assert "내용을 옮겨 적지 않고 어디를 보면 되는지 적는다" in b
    assert "[열어서 봄]" in b and "[파일만 읽음]" in b
    for head in ("## 대표 예 하나 — 화면에서 DB까지", "## 공통 부품", "## 스타일"):
        items = [l for l in section(b, head).splitlines() if l.strip()]
        assert items and all(l.rstrip().endswith(("[열어서 봄]", "[파일만 읽음]")) for l in items), head
    for k in ("본 범위:", "- 새 화면을 어디에 두나:", "- 공통 스타일:", "불러오는 곳:"):
        assert k in b, k


def test_guide_keeps_secret_list():
    assert text(OLD_GUIDE).splitlines()[19] in text(GUIDE).splitlines()   # 옛 20줄 글자 그대로


@pytest.mark.parametrize("p", SKILL_FILES, ids=SKILL_IDS)
def test_find_bytes_clean(p):
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n")


def test_skills_total_lines():
    assert sum(len(text(p).splitlines()) for p in (KIT / "skills").rglob("*.md")) <= 1182


# --- 0.7.0 화면 표 (설계 docs/superpowers/specs/2026-11-20-devkit-screen-table-design.md) ---

def test_table_frame_fixed():
    t = text(TABLE)
    assert t.splitlines()[0] == "# 화면 표 쓰기"
    L = t.splitlines()
    for h in ("## 언제 읽는가", "## 쓰는 자리", "## 틀", "## 규칙"):
        assert h in L, h
    b = frame_block(t)
    assert b.splitlines() == TABLE_FRAME
    head = [c.strip() for c in TABLE_FRAME[5].strip("|").split("|")]
    assert head == ["화면", "화면 파일", "주소", "받는 코드"]


def test_table_rules():
    r = section(text(TABLE), "## 규칙")
    for k in ("검색 명령으로 모두 뽑", "하나하나 열지 않", "골라 적지 않", "없는 파일은 적지 않는다",
              "표의 화면 줄 수가 같아야 한다", "\"조각\"", "`경로:줄`", "\"앱 안\"", "`—`", "`?`",
              "짐작하지 않", "프로젝트 맨 위에서부터", "옮기지 않는다", "이름과 자리만",
              "종류만 골라서", "끌어오지 않는다", "다 못 적으면", "계정·열쇠·토큰",
              "통째로 검색하지 않는다", "머리의 수는 부품 수다", "링크나 문서의 줄이 아니다",
              "수만 세고", "줄을 찍지 않고", "부품을 세는 명령",
              "대소문자 없이", "주소를 적는 꼴로만"):
        assert k in r, k
    assert r.count("\"읽지 않는 것\"") == 2   # 검색할 때 · 옮겨 적을 때


def test_table_when():
    t = text(TABLE)
    w = section(t, "## 언제 읽는가")
    assert "살펴(분석해) 달라는 부탁일 때만" in w and "큰 일의 길" in w and "읽지 않는다" in w
    assert "`.devkit/screens.md`" in section(t, "## 쓰는 자리")


def test_guide_points_to_table():
    t = text(GUIDE)
    where = section(frame_block(t), "## 어디에 무엇이").splitlines()
    assert any(l.startswith("- 화면 하나하나: `.devkit/screens.md`") for l in where)
    assert any(l.startswith("- 프로젝트 문서: ") and "없음" in l for l in where)
    steps = section(t, "## 보는 차례").splitlines()
    s8 = [l for l in steps if l.startswith("8. ")]; s9 = [l for l in steps if l.startswith("9. ")]
    assert len(s8) == 1 and "파일 이름만" in s8[0] and "옮기지도 않는다" in s8[0] and "적지 않는다" in s8[0]
    assert len(s9) == 1 and "살펴 달라는 부탁일 때만" in s9[0] and "`screen-table.md`" in s9[0] and "큰 일의 길" in s9[0]
    fix = section(t, "## 고칠 때")
    assert "살펴 달라는 부탁인데" in fix and "화면 표가 없으면" in fix and "`screen-table.md`" in fix
    assert "`화면 하나하나`" in fix and "`프로젝트 문서`" in fix


def test_skill_points_to_table():
    t = text(FIND)
    assert "- 쓴 파일: `.devkit/guide.md`, `.devkit/screens.md`" in section(t, "## 보고").splitlines()
    assert "`screen-table.md`" in section(t, "## 자리") and "살펴 달라는 부탁이면" in section(t, "## 자리")


def test_readme_promise():
    t = text(README)
    assert "업무 말" not in t and "어떤 순서로 지나는지" not in t
    use = [l for l in section(t, "## 쓰는 법").splitlines() if l.startswith('"이 프로젝트 분석해 줘"')]
    assert len(use) == 1 and "`.devkit/guide.md`" in use[0] and "`.devkit/screens.md`" in use[0]
    assert "저절로 고쳐지지 않는다" in use[0]
    assert "`.devkit/screens.md`" in t.splitlines()[3]
