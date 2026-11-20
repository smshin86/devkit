import re
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "kit"   # 다른 두 시험 파일과 같은 꼴
START = KIT / "skills/start/SKILL.md"
KNOWN = {"start", "intake", "find", "build", "verify", "review", "wrap-up"}

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
