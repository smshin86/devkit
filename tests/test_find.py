import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"   # 다른 시험 파일과 같은 꼴
FIND = KIT / "skills/find/SKILL.md"
GUIDE = KIT / "skills/find/first-guide.md"
OLD_GUIDE = ROOT / "old/kit-0.2.0/skills/find/first-guide.md"
KNOWN = {"start", "intake", "find", "build", "verify", "review", "wrap-up"}
MDS = {"first-guide", "SKILL", "AGENTS", "CLAUDE", "DESIGN", "guide", "copilot-instructions"}
FRAME = ["# 길 안내", "## 어디에 무엇이", "## 대표 예 하나 — 화면에서 DB까지", "## 공통 부품", "## 스타일", "## 바깥과 닿는 곳", "## 조심할 곳", "## 돌리는 법", "## 못 본 것"]
MAP_WORDS = ("screenmap", "lookup", "used-by", "check.py", "run-ok", "~/.devkit", ".devkit/rules", "앞 시험", "look.md", "나눠 살피기")
BED_WORDS = ("ihatemoney", "bill", "settle", "person", "weight", "password", "currency", "reminder", "지출", "정산", "환율", "참여자")


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
    assert L[-1] == "다음: devkit:build"


def test_find_lines():
    assert len(text(FIND).splitlines()) <= 90
    assert len(text(GUIDE).splitlines()) <= 100


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
    for p in (FIND, GUIDE):
        t = text(p)
        assert set(re.findall(r"devkit:([a-z-]+)", t)) <= KNOWN, p.name
        pys = set(re.findall(r"([A-Za-z_]+)\.py\b", t)); assert pys <= {"work"}, p.name
        assert set(re.findall(r"([A-Za-z_-]+)\.md\b", t)) <= MDS, p.name
    assert "first-guide.md" in text(FIND) and (KIT / "scripts/work.py").is_file()


@pytest.mark.parametrize("p", [FIND, GUIDE], ids=["SKILL", "first-guide"])
def test_find_no_map_words(p):
    t = text(p)
    for w in MAP_WORDS:
        assert w not in t, (p.name, w)


@pytest.mark.parametrize("p", [FIND, GUIDE], ids=["SKILL", "first-guide"])
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


@pytest.mark.parametrize("p", [FIND, GUIDE], ids=["SKILL", "first-guide"])
def test_find_bytes_clean(p):
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n")


def test_skills_total_lines():
    assert sum(len(text(p).splitlines()) for p in (KIT / "skills").rglob("*.md")) <= 1182
