"""시험 묶음 전체가 진짜 무대 뿌리를 건드리지 않았는지 지킨다(읽기만 한다).

시작(첫 시험 앞)에 `run.lock` 있음 여부와 `out` 바로 아래 이름·크기·고친 시각을 적어 두고, 끝(마지막 시험 뒤)에 견준다.
다르면 끝 정리에서 실패로 드러난다. `sealed`·`src-*`·`bases` 같은 봉한 폴더는 열지 않는다. 뿌리가 없는 기계에서는 '없음'끼리 견주어 통과한다.
"""
import os

import pytest

REAL_ROOT = "/home/ssmge/zzz-devkit-stage"


def _snapshot():
    lock = os.path.lexists(os.path.join(REAL_ROOT, "run.lock"))
    try:
        with os.scandir(os.path.join(REAL_ROOT, "out")) as it:
            ents = []
            for e in it:
                st = os.lstat(e.path)
                ents.append((e.name, st.st_size, st.st_mtime_ns))
            ents.sort()
    except OSError:
        ents = "없음"
    return lock, ents


@pytest.fixture(scope="session", autouse=True)
def _real_stage_root_untouched():
    before = _snapshot()
    yield
    after = _snapshot()
    if after != before:
        pytest.fail("시험 묶음이 진짜 무대 뿌리를 바꿨다: 시작 %r → 끝 %r" % (before, after), pytrace=False)
