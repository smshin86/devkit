#!/bin/bash
# locked.sh <명령…> — $M/run.lock을 잡고 명령을 돌린 뒤 푼다. 이미 잡혀 있으면 7, 아니면 명령의 종료 값 그대로. 신호(TERM·INT·HUP)로 끊기면 자식을 끄고 잠금을 남긴다(143).
M=/home/ssmge/zzz-devkit-measure
[ $# -ge 1 ] || { echo "인자 틀림: 돌릴 명령이 없음"; exit 9; }
mkdir "$M/run.lock" 2>/dev/null || { echo "다른 실행이 잠금을 잡고 있음($M/run.lock) — 멈춤"; exit 7; }
KEEP=0; CP=
on_sig() {
  trap '' TERM INT HUP
  KEEP=1
  if [ -n "$CP" ]; then kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null; fi
  echo "신호로 끊김 — 잠금을 남김($M/run.lock): 남은 실행이 없는지 보고 돈을 손으로 적은 뒤 rmdir"
  exit 143
}
trap '[ "$KEEP" = 1 ] || rmdir "$M/run.lock"' EXIT
trap on_sig TERM INT HUP
"$@" & CP=$!; wait "$CP"; rc=$?; exit "$rc"
