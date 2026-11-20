#!/usr/bin/env python3
"""devkit 점검 (python3 표준 라이브러리만). 찍기만 한다 — 고치지도 막지도 않는다.
  check.py <프로젝트> [--record <기록 파일 이름>]   작업 기록·규칙의 예시 파일·화면 지도 낡음을 본다.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import work

NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*\.md$", re.ASCII)
MAP_NOTE = "화면 지도 낡음 검사 못 함: "


def path_refs(text):
    """줄마다 백틱 안 글자 가운데 프로젝트 기준 경로로 보이는 것만 `[(경로, 줄 번호)]`로 건진다."""
    out = []
    for no, line in enumerate(text.split("\n"), 1):
        for ref in re.findall(r"`([^`]+)`", line):
            if re.search(r"\s|://|[*$<>{}]", ref):
                continue
            if ref.startswith("./"):
                ref = ref[2:]
            if ref.startswith("/"):
                continue
            ref = re.sub(r":\d+(-\d+)?$", "", ref)
            if "/" in ref:
                out.append((ref, no))
    return out


def _gone(project, text, where):
    """text 안 경로 가운데 project 아래에 없는 것마다 지적 한 줄. where는 `(규칙 파일 줄)`을 만든다."""
    return ["없는 파일: `%s` (%s)" % (p, where(no)) for p, no in path_refs(text) if not (project / p).exists()]


def check_record(project, path):
    rec = work.read_record(path)
    probs = []
    for label, key, allowed in (("지금 단계", "stage", work.STAGES), ("상태", "state", work.STATES)):
        if not rec[key]:
            probs.append("머리 줄 없음: " + label)
        elif rec[key] not in allowed:
            probs.append('머리 줄 값이 틀림: %s ("%s")' % (label, rec[key]))
    probs += ["제목 줄 없음: ## " + h for h in work.HEADINGS if h not in rec["sections"]]
    results = [(s["id"], (s["result"] or "").strip()) for s in rec["scenes"]]
    if rec["stage"] in ("review", "wrap-up") or rec["state"] == "closed":
        if not results:
            probs.append("장면이 하나도 없음")
        for sid, res in results:
            if not res:
                probs.append("장면 %s: 결과 칸이 비었음" % sid)
            elif res not in work.RESULTS:
                probs.append('장면 %s: 결과 칸이 네 말 중 하나가 아님 ("%s")' % (sid, res))
    done = rec["stage"] == "wrap-up" or rec["state"] == "closed"   # 검토를 지난 자리
    if done and re.search(r"^- 길: 긴 길", rec["sections"].get("요청", ""), re.M) and not rec["sections"].get("검토", "").strip():
        probs.append("긴 길인데 `## 검토`가 비었음 — 확인·검토·보안 훑기를 안 했으면 기록을 다시 열고 안 한 단계(`devkit:verify`·`devkit:review`)부터 읽는다")
    for line in rec["sections"].get("닮은 것과 꺼낸 규칙", "").split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.strip().startswith("|") and len(cells) > 1 and not re.match(r"^[:\- ]+$", cells[1]):
            probs += _gone(project, cells[1], lambda no: "닮은 것과 꺼낸 규칙")
    return {"name": Path(path).name, "stage": rec["stage"], "problems": probs,
            "all_unverified": bool(results) and all(r == "확인 못 함" for _, r in results)}


def check_rules(project):
    probs = []
    d = work.devkit_dir(project) / "rules"
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        for no, line in enumerate(f.read_bytes().decode("utf-8", "replace").split("\n"), 1):
            for ref in re.findall(r"예: (`[^`]+`)", line):
                probs += _gone(project, ref, lambda _n, f=f, no=no: "rules/%s %d줄" % (f.name, no))
    return probs


def check_map(project):
    mp = work.devkit_dir(project) / "screenmap.json"
    if not mp.exists():
        return {"problems": [], "notes": ["화면 지도 없음 — 낡았는지 보지 않았습니다"]}
    try:
        import screenmap
    except Exception:
        return {"problems": [], "notes": [MAP_NOTE + "screenmap.py를 불러오지 못함"]}
    if not hasattr(screenmap, "stale"):
        return {"problems": [], "notes": [MAP_NOTE + "screenmap.py에 stale이 없음"]}
    try:
        items = [(x["path"], x["why"]) for x in screenmap.stale(project, mp)]
    except Exception as e:
        return {"problems": [], "notes": [MAP_NOTE + type(e).__name__]}
    if any(not p for p, _ in items):
        return {"problems": ["화면 지도를 읽지 못함 — 다시 만들어야 합니다"], "notes": []}
    if not items:
        return {"problems": [], "notes": []}
    shown = ", ".join("%s %s" % i for i in items[:5]) + (" 외 %d개" % (len(items) - 5) if len(items) > 5 else "")
    return {"problems": ["화면 지도가 낡음: 화면 파일 %d개가 지도와 다름 (%s)" % (len(items), shown)], "notes": []}


def _section(title, probs, notes):
    lines = [title] + ["  - " + p for p in probs] + ["  · " + n for n in notes]
    return lines + (["  걸린 것 없음"] if not probs and not notes else [])


def report(project, record=None):
    project = Path(project)
    head = "devkit 점검: " + (project.resolve().name or str(project))
    base = work.devkit_dir(project)
    if not base.is_dir():
        return [head, "`.devkit` 폴더 없음 — 점검할 것이 없습니다", "점검 끝: 걸린 것 없음"]
    opened = work.open_records(project)
    names = [record] if record else [n for n, _ in opened]
    others = [o for o in opened if record and o[0] != record]   # 이름을 댄 점검이 보지 않는 열린 기록
    recs = [check_record(project, base / "work" / n) for n in names]
    lines = ['! 모든 장면이 "확인 못 함"입니다: ' + r["name"] for r in recs if r["all_unverified"]] + [head]
    for r in recs:
        lines.append("기록 %s (지금 단계: %s)" % (r["name"], r["stage"] or "?"))
        lines += ["  - " + p for p in r["problems"]] or ["  걸린 것 없음"]
    lines += [] if recs else ["열린 작업 기록 없음"]
    lines += (["다른 열린 기록 — 이번 점검이 보지 않았습니다"] + ["  · %s (지금 단계: %s)" % o for o in others]) if others else []
    rules = check_rules(project)
    rule_notes = [] if (base / "rules").is_dir() else ["규칙 폴더 없음 — 보지 않았습니다"]
    cmap = check_map(project)
    lines += _section("규칙", rules, rule_notes) + _section("화면 지도", cmap["problems"], cmap["notes"])
    n = sum(len(r["problems"]) for r in recs) + len(rules) + len(cmap["problems"])
    unseen = len(rule_notes) + len(cmap["notes"])         # 보지 못한 것이 있으면 끝 줄에서 "없음"으로만 읽히지 않게
    tail = '점검 끝: 걸린 것 %d개 — 막지 않습니다. 채우거나 "못 함"이라고 적으세요' % n if n else "점검 끝: 걸린 것 없음"
    left = " · 열린 채 남은 다른 기록 %d개" % len(others) if others else ""   # 끝 줄이 "걸린 것 없음"으로만 읽히지 않게
    return lines + [tail + (" · 보지 못한 것 %d개" % unseen if unseen else "") + left]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="check.py", description="devkit 점검 — 찍기만 합니다")
    ap.add_argument("project")
    ap.add_argument("--record", help="점검할 작업 기록 파일 이름 (없으면 열린 것 전부)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    project = Path(args.project)
    if not project.is_dir():
        sys.stderr.write("check.py: 프로젝트 폴더가 아닙니다: %s\n" % args.project)
        return 2
    rec = args.record
    if rec is not None and not (NAME_RE.fullmatch(rec) and (work.devkit_dir(project) / "work" / rec).is_file()):
        sys.stderr.write("기록 파일을 찾지 못함 (.devkit/work/ 안의 파일 이름만 쓸 수 있습니다): %s\n" % rec)
        return 2
    try:
        print("\n".join(report(project, rec)))
    except Exception as e:
        print("점검을 끝내지 못함: %s — 이 줄을 보고에 그대로 붙이세요" % type(e).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
