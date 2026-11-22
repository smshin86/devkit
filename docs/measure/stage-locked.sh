#!/bin/bash
# 부르는 꼴: bash stage-locked.sh <명령…> — 셔뱅은 있어도 실행 비트는 없고(drvfs는 비트를 못 가림) 늘 bash로 부른다.
# stage-locked.sh <명령…> — $L(연습 무대 잠금)을 잡고 명령을 돌린 뒤 푼다. 이미 잡혀 있으면 7, 아니면 명령의 종료 값 그대로. 신호(TERM·INT·HUP)로 끊기면 자식을 끄고 잠금을 남긴다(143). 자식이 128 넘게 끝나도(137 따위) 잠금을 남긴다.
# locked.sh와 같은 꼴이고 잠금 자리만 다르다(STAGE_S가 있으면 그 뿌리). 인자가 없으면 잠금을 잡기 전에 9로 끝난다.
# 잠금 폴더에 flock을 잡은 채(fd 9, 자식이 이어받음) 돌고, 표시 STAGE_LOCKED=<잠금 길>을 내보낸다 — stage.sh는 이 표시가 없으면 9로 안 돈다.
# stage.sh seal·unseal은 그 flock을 못 잡으면(도는 실행이 있음) 9로 끝난다.
L=${STAGE_S:-/home/ssmge/zzz-devkit-stage}/run.lock
[ $# -ge 1 ] || { echo "인자 틀림: 돌릴 명령이 없음"; exit 9; }
if ! mkdir "$L" 2> /dev/null; then
  echo "다른 실행이 잠금을 잡고 있음($L) — 멈춤"
  W=; [ -f "$L/why" ] && W=$(head -n 1 "$L/why" 2> /dev/null | cut -c1-200)
  # 잠금 폴더에 flock을 쥔 프로세스가 없으면 도는 실행이 없는 것 — 까닭을 보고 치운다
  if ( exec 9< "$L" && flock -n 9 ) 2> /dev/null; then
    echo "도는 실행 없음 — 까닭: ${W:-모름} — 확인 뒤 \`rm $L/why && rmdir $L\`"
  elif [ -n "$W" ]; then
    echo "남긴 까닭: $W"
  fi
  exit 7
fi
KEEP=0; CP=
on_sig() {
  trap '' TERM INT HUP
  KEEP=1
  if [ -n "$CP" ]; then kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null; fi
  [ -e "$L/why" ] || echo signal > "$L/why" 2> /dev/null
  echo "신호로 끊김(까닭: $(head -n 1 "$L/why" 2> /dev/null)) — 잠금을 남김($L): 도는 실행이 없는지 본 뒤 남은 실행이 없으면 장부에 상한 줄이 적혔는지 확인하고 rm $L/why && rmdir $L"
  exit 143
}
trap '[ "$KEEP" = 1 ] || rmdir "$L"' EXIT
trap on_sig TERM INT HUP
exec 9< "$L" && flock -n 9
export STAGE_LOCKED="$L"
"$@" & CP=$!; wait "$CP"; rc=$?
# 128 넘는 종료(신호로 죽음 · 137 포함)는 안 풀린 상태일 수 있다 — 잠금을 남긴다
if [ "$rc" -gt 128 ] && [ ! -e "$L/why" ]; then echo "exit-$rc" > "$L/why" 2> /dev/null; fi
# 까닭 파일이 있으면(stage.sh가 적음: low-mem · signal · survivors) 종료 값이 작아도 남긴다
if [ "$rc" -gt 128 ] || [ -e "$L/why" ]; then
  KEEP=1
  echo "종료 값 $rc — 잠금을 남김($L, 까닭: $(head -n 1 "$L/why" 2> /dev/null)): 도는 실행이 없는지 본 뒤 남은 실행이 없으면 장부에 상한 줄이 적혔는지 확인하고 rm $L/why && rmdir $L"
fi
exit "$rc"
