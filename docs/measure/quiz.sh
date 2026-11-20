#!/bin/bash
# quiz.sh <이름> <new|old> <k> — 안내 글(또는 0.4.0 팔의 보고)만 받은 새 대화로 물음 열에 답하게 하고 quiz.py로 채점한다.
# 근거 글: GUIDE_FILE > $O/survey.<이름>.<V>.<k>.guide.md > 같은 이름의 .jsonl. 물음 파일은 QFILE(기본 quiz-q.txt).
# 프로젝트가 없는 빈 폴더에서 돌고 --plugin-dir을 주지 않는다. 잠금 `$M/run.lock`, 돈 기록 `$M/out/p2.cost`. 신호로 끊기면 claude를 끄고 돈 줄을 적은 뒤 잠금을 푼다(143).
NAME=${1-}; V=${2-}; N=${3-}
BUDGET=${BUDGET-0.30}; SECS=${SECS-300}; P2_STOP=${P2_STOP-15}
case "$NAME" in ''|*[!A-Za-z0-9_-]*) echo "인자 틀림: 이름은 영문·숫자·_·- 만"; exit 9 ;; esac
case "$V" in new|old) ;; *) echo "인자 틀림: 둘째는 new 또는 old"; exit 9 ;; esac
case "$N" in [1-9]) ;; *) echo "인자 틀림: k는 1~9"; exit 9 ;; esac
for v in BUDGET SECS P2_STOP; do
  eval "x=\$$v"
  case "$x" in ''|*[!0-9.]*) echo "인자 틀림: $v 는 숫자만(받은 값 [$x])"; exit 9 ;; esac
done
W=/home/ssmge/zzz-devkit-exist
M=/home/ssmge/zzz-devkit-measure; O=$M/out; LOG=$O/g.log
R=/mnt/e/claude_dev/devkit/docs/measure/원본
MS=/mnt/e/claude_dev/devkit/docs/measure
Q=${QFILE:-$MS/quiz-q.txt}
OP=$O/survey.$NAME.$V.$N
QP=$O/quiz.$NAME.$V.$N
QT=
if [ -n "$QFILE" ]; then
  QT=.$(basename "$QFILE" .txt)
  QP=$QP$QT
fi
[ -f "$Q" ] || { echo "물음 파일 없음: $Q"; exit 9; }
Q=$(readlink -f "$Q")
if [ -n "$GUIDE_FILE" ]; then
  [ -f "$GUIDE_FILE" ] || { echo "GUIDE_FILE 없음: $GUIDE_FILE"; exit 9; }
  SRCF=$(readlink -f "$GUIDE_FILE"); SRCK=file
elif [ -f "$OP.guide.md" ]; then
  SRCF=$OP.guide.md; SRCK=guide
elif [ -f "$OP.jsonl" ]; then
  SRCF=$OP.jsonl; SRCK=jsonl
else
  echo "근거 글이 없음: $OP.guide.md / $OP.jsonl"; exit 9
fi
[ -e "$QP.jsonl" ] && { echo "이미 돌림: $QP"; exit 9; }
QD=$M/quiz/$NAME-$V-$N$QT
[ -e "$QD" ] && { echo "빈 폴더가 이미 있음: $QD — 확인 뒤 지우고 다시"; exit 9; }
mkdir -p "$M/quiz" "$O" "$M/tmp" "$M/notmux"; export TMPDIR=$M/tmp

mkdir "$M/run.lock" 2>/dev/null || { echo "다른 실행이 잠금을 잡고 있음($M/run.lock) — 멈춤"; exit 7; }
CP=
on_sig() {
  trap '' TERM INT HUP
  if [ -n "$CP" ]; then
    kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
    c=$(costof "$QP.jsonl"); [ "$c" = "?" ] && c=$BUDGET
    echo "$c quiz.$NAME.$V.$N$QT" >> "$O/p2.cost"
    echo "quiz.$NAME.$V.$N$QT 신호로 끊김 cost=$c $(date +%H:%M:%S)" >> "$LOG"
  fi
  exit 143
}
trap 'rmdir "$M/run.lock"' EXIT
trap on_sig TERM INT HUP
spent=0
[ -f "$O/p2.cost" ] && spent=$(awk '{s+=$1} END{print s+0}' "$O/p2.cost")
if awk -v s="$spent" -v b="$BUDGET" -v m="$P2_STOP" 'BEGIN{exit !(s+b>m)}'; then
  echo "돈 선: 지금까지 $spent + 뚜껑 $BUDGET > 멈춤 선 $P2_STOP — 시작하지 않음"; exit 6
fi
if awk -v s="$spent" 'BEGIN{exit !(s>=8)}'; then
  echo "알림: 부품 2 합 $spent (8 넘음) $(date +%H:%M:%S)" >> "$LOG"
  echo "알림: 부품 2 합 $spent (8 넘음)"
fi
mkdir "$QD" || exit 9

costof() {
  python3 -I -c '
import json, sys
c = "?"
try:
    for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if isinstance(e, dict) and e.get("type") == "result" and e.get("total_cost_usd") is not None:
            c = e["total_cost_usd"]
except OSError:
    pass
print(c)' "$1"
}

o7() { awk '/Normal/{s=0; for(i=12;i<=NF;i++) s+=$i; print s}' /proc/buddyinfo; }
memchk() {
  commit=$(cd /mnt/c && powershell.exe -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
  case "$commit" in ''|*[!0-9]*)
    echo "quiz.$NAME.$V.$N$QT mem win_commit_gb 못 읽음(값 [$commit]) — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "커밋 값을 못 읽음 — 멈춤"; exit 3 ;;
  esac
  if [ "$commit" -lt 4 ]; then
    echo "quiz.$NAME.$V.$N$QT mem win_commit_gb=${commit:-?} 4 아래 — 압축 안 함, 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "메모리 부족 — 멈춤"; exit 3
  fi
  buddy=$(o7)
  if [ "${buddy:-0}" -le 0 ]; then
    python3 "$R/compact.py" 4 >> "$LOG" 2>&1
    buddy=$(o7)
  fi
  echo "quiz.$NAME.$V.$N$QT mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
  if [ "${buddy:-0}" -le 0 ]; then echo "메모리 부족 — 멈춤"; exit 3; fi
}

CL=$(command -v claude) || { echo "claude 없음"; exit 9; }
memchk
# claude 자식에게만 준다: Windows 실행 파일 폴더(/mnt/<드라이브>/)를 뺀 PATH, 빈 소켓 폴더
CLEAN=$(printf '%s' "$PATH" | tr ':' '\n' | command grep -v -E '^/mnt/[a-z]/' | command grep -v -x -F -e "$HOME/.local/bin" -e "$W/tools/bin" | paste -sd:)
PROMPT=$(python3 -I "$MS/quiz.py" prompt "$Q" "$SRCF") || { echo "prompt 만들기 실패"; exit 9; }

cd "$QD" || exit 9
t0=$(date +%s)
timeout "$SECS" env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$M/notmux" PATH="$CLEAN" "$CL" -p "$PROMPT" \
  --setting-sources project --strict-mcp-config \
  --no-session-persistence --model sonnet \
  --max-budget-usd "$BUDGET" \
  --tools "" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" \
  --output-format stream-json --verbose \
  < /dev/null > "$QP.jsonl" 2> "$QP.err" &
CP=$!; echo "$CP" > "$QP.pid"; wait "$CP"; rc=$?
rm -f "$QP.pid"
LEFT=0; HOMEDK=0
for p in /proc/[0-9]*; do
  pid=${p#/proc/}; cwd=$(readlink "$p/cwd" 2>/dev/null) || continue
  case "$cwd" in "$QD"|"$QD"/*)
    [ "$pid" = "$$" ] && continue
    echo "left: $pid $(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-80)" >> "$LOG"
    LEFT=1 ;;
  esac
done
if [ -e "$HOME/.devkit" ]; then
  echo "quiz.$NAME.$V.$N$QT: home .devkit appeared" >> "$LOG"; HOMEDK=1
fi
secs=$(( $(date +%s) - t0 ))
python3 -I "$MS/quiz.py" grade "$Q" "$QP.jsonl" "$SRCF" | tee "$QP.grade"; g=${PIPESTATUS[0]}
trap '' TERM INT HUP
cost=$(costof "$QP.jsonl")
if [ "$cost" = "?" ]; then echo "$BUDGET quiz.$NAME.$V.$N$QT" >> "$O/p2.cost"; else echo "$cost quiz.$NAME.$V.$N$QT" >> "$O/p2.cost"; fi
last=$(tail -n 1 "$QP.grade")
echo "quiz.$NAME.$V.$N$QT $last 근거=$SRCK cost=$cost rc=$rc secs=$secs $(date +%H:%M:%S)" >> "$LOG"
[ "$HOMEDK" = 0 ] || exit 10
[ "$LEFT" = 0 ] || exit 11
exit "$g"
