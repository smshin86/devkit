import re
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "kit"   # 다른 두 시험 파일과 같은 꼴
START = KIT / "skills/start/SKILL.md"
KNOWN = {p.name for p in (KIT / "skills").iterdir() if (p / "SKILL.md").is_file()}
START_END = "큰 일의 길: (길 안내가 없을 때만 `devkit:find`) → 만든다 → `devkit:check` → 보고."


def section(t, head):
    return t.split(head + "\n", 1)[1].split("\n## ", 1)[0]


def test_start_front():
    L = START.read_text(encoding="utf-8").splitlines()
    assert L[0] == "---" and L[1] == "name: start" and L[3] == "---"
    assert L[2].startswith("description: 한 장이 큰 일이라고 한 뒤에만")
    assert len(L) <= 90

def test_start_keeps():
    t = START.read_text(encoding="utf-8")
    for h in ("## 이어 하는 일", "## 살펴만 달라는 부탁", "## 한 단계만 해 달라는 부탁", "## 두 길",
              "## 어느 단계에서나 지키는 것", "## 묻는 법", "## 작업 기록 여는 법", "## 맡기는 법"):
        assert h in t.splitlines(), h

def test_start_refs_known():
    t = START.read_text(encoding="utf-8")
    assert set(re.findall(r"devkit:([a-z-]+)", t)) <= KNOWN
    pys = set(re.findall(r"([A-Za-z_]+)\.py\b", t)); assert pys <= {"work"}
    assert all((KIT / "scripts" / (x + ".py")).is_file() for x in pys)
    assert "없는 단계:" in t
    assert "앞 시험" not in t          # 사연은 걷어낸다(7-7)

def test_start_bytes_clean():
    raw = START.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n")

def test_start_guard_search_line():
    t = START.read_text(encoding="utf-8")
    sec = t.split("## 어느 단계에서나 지키는 것\n", 1)[1].split("\n## ", 1)[0]
    keep = [l for l in sec.splitlines()
            if l.startswith("- 비밀번호·토큰 같은 낱말이") and "`-l`" in l and "한 줄에 묶지 않는다" in l]
    assert len(keep) == 1
    assert "한 번에 하나" in t and "받기 안내가 없으면" in t
    assert t.splitlines()[-1] == START_END


def test_start_one_path():
    t = START.read_text(encoding="utf-8")
    sec = section(t, "## 두 길")
    assert "`devkit:check`" in sec
    assert "처음 보는 눈의 검토는 아직 꾸러미에 없다 — 사람이 한 번 봐 달라" in sec
    assert "parallel.md" not in t and "다음: devkit:" not in t
    L = t.splitlines()
    assert all("devkit:<" not in l for i, l in enumerate(L) if i != 10)


def test_start_one_stage_lines():
    t = START.read_text(encoding="utf-8")
    sec = section(t, "## 한 단계만 해 달라는 부탁")
    L = sec.splitlines()
    assert "- 확인만 → `devkit:check`" in L
    hit = [l for l in L if "검토만" in l and "내보내기 전 점검만" in l]
    assert len(hit) == 1 and "한 장대로" in hit[0]


def test_start_ask_line_excludes_new():
    t = START.read_text(encoding="utf-8")
    L = t.splitlines()
    i = L.index("**먼저 묻는다**")
    assert "이번에 내가 새로 만든 것은 빼고" in L[i + 1]
    assert "시험해도 된다고 한 적 없는 DB·바깥 서비스에 쓰기" in t


def test_start_keeps_missing_stage_net():
    L = START.read_text(encoding="utf-8").splitlines()
    assert L[10].startswith("이 글이 가리키는 `devkit:<이름>` 안내가 꾸러미에 없으면")
    assert "없는 단계: <이름> — 한 장대로 했다" in L[10]
