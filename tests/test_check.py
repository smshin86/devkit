import re
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / "kit"
CHECK = KIT / "skills/check/SKILL.md"
HEADS = ["## 크기 맞추기", "## 켜도 되는지", "## 1. 켜 본다", "## 2. 시험을 돌린다",
         "## 3. 있던 것으로 들어가 본다", "## 4. 부탁에 없는 것을 덜어 낸다", "## 보고"]
STEPS = ["켜 본다", "시험을 돌린다", "있던 것으로 들어가 본다", "부탁에 없는 것을 덜어 낸다"]
BED_WORDS = ("ihatemoney", "bill", "settle", "person", "weight", "password", "currency", "reminder", "지출", "정산", "환율", "참여자")


def text():
    return CHECK.read_text(encoding="utf-8")


def section(head):
    # `## ` 제목 줄부터 다음 `## ` 제목 줄 앞까지
    out, on = [], False
    for l in text().splitlines():
        if l.startswith("## "):
            if on:
                break
            on = (l == head)
            continue
        if on:
            out.append(l)
    assert on or out, head
    return "\n".join(out)


def test_check_front():
    L = text().splitlines()
    assert L[0] == "---" and L[1] == "name: check"
    assert L[2].startswith("description: 파일을 고친 일을 끝 보고 전에 읽는다(작은 일도)")
    assert L[3] == "---"
    assert len(L) <= 60


def test_check_heads_exact():
    L = text().splitlines()
    assert [l for l in L if l.startswith("## ")] == HEADS
    assert len([l for l in L if l.startswith("# ")]) == 1


def test_check_step_names():
    assert re.findall(r"^## [1-4]\. (.+)$", text(), re.M) == STEPS


def test_check_report_words():
    s = section("## 보고")
    for k in ("끝내기 전 점검:", "`됨`", "`안 됨`", "`읽어서는 이어짐`", "`확인 못 함`", "하지 않는 걸음도 줄은 적는다"):
        assert k in s, k


def test_check_key_phrases():
    s1 = section("## 1. 켜 본다")
    for k in ("이름으로 죽이지 않는다", "꺼졌는지", "끄지 못했으면"):
        assert k in s1, k
    assert "켜 보지 못했다 — " in section("## 켜도 되는지")
    assert "부탁에 없지만 넣은 것" in section("## 4. 부탁에 없는 것을 덜어 낸다")
    assert "4와 보고만" in section("## 크기 맞추기")


def test_check_refs():
    t = text()
    known = {p.name for p in (KIT / "skills").iterdir() if (p / "SKILL.md").is_file()}
    assert set(re.findall(r"devkit:([a-z-]+)", t)) <= known
    assert re.findall(r"([A-Za-z_]+)\.py\b", t) == []


def test_check_no_testbed_words():
    t = text().lower()
    for w in BED_WORDS:
        assert w not in t, w


def test_check_bytes_clean():
    raw = CHECK.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n")
