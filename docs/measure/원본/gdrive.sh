#!/bin/bash
# gdrive.sh — 이어 붙이기 시험을 차례로 돌린다. 한 번에 하나만. 이미 돌린 것은 건너뛴다. 하나라도 멈추면 거기서 선다.
W=/home/ssmge/zzz-devkit-exist
for N in 1 2 3 5 6 7 8 4; do
  for pair in "gw one" "gp plain"; do
    set -- $pair
    [ -e "$W/out/g.$1.$N.jsonl" ] && continue
    bash "$W/g.sh" "$1" "$2" "$N" || { echo "멈춤: $1 $N (rc=$?)"; exit 1; }
  done
done
echo "다 끝남"
