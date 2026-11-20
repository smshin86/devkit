#!/bin/bash
# survey.sh <이름> <new|old> <k> — 살펴보기 한 번. 부탁은 고정 「이 프로젝트를 분석해 줘.」. new = `kit/`, old = `$M/kit-0.4.0`.
# `SRC`가 있으면 시험대 대신 그 폴더를 복사한다(③). 사본·출력은 `$M` 아래만. 잠금 `$M/run.lock`, 돈 기록 `$M/out/$COST_FILE`(기본 p2.cost). 신호로 끊기면 claude를 끄고 돈 줄을 적은 뒤 잠금을 푼다(143).
# 환경 변수: `COST_FILE`(돈 기록 파일 이름, 기본 p2.cost) · `WARN`(알림 선, 기본 8). `~/.devkit-guard-off`가 있으면 훅이 꺼진 채라 재지 않고 8로 멈춘다(실행 뒤에 생겼으면 10).
W=/home/ssmge/zzz-devkit-exist
M=/home/ssmge/zzz-devkit-measure; O=$M/out; LOG=$O/g.log
R=/mnt/e/claude_dev/devkit/docs/measure/원본
BASE=2bc1b8b
NAME=${1-}; V=${2-}; N=${3-}
BUDGET=${BUDGET-1.50}; SECS=${SECS-1800}; P2_STOP=${P2_STOP-15}
COST_FILE=${COST_FILE-p2.cost}; WARN=${WARN-8}
case "$NAME" in ''|*[!A-Za-z0-9_-]*) echo "인자 틀림: 이름은 영문·숫자·_·- 만"; exit 9 ;; esac
case "$V" in new|old) ;; *) echo "인자 틀림: 둘째는 new 또는 old"; exit 9 ;; esac
case "$N" in [1-9]) ;; *) echo "인자 틀림: k는 1~9"; exit 9 ;; esac
case "$COST_FILE" in ''|.*|*[!A-Za-z0-9_.-]*) echo "인자 틀림: COST_FILE은 파일 이름만(받은 값 [$COST_FILE])"; exit 9 ;; esac
for v in BUDGET SECS P2_STOP WARN; do
  eval "x=\$$v"
  case "$x" in ''|*[!0-9.]*) echo "인자 틀림: $v 는 숫자만(받은 값 [$x])"; exit 9 ;; esac
done
[ -e "$HOME/.devkit" ] && { echo "~/.devkit 이 이미 있음 — 멈춤"; exit 8; }
[ -e "$HOME/.devkit-guard-off" ] && { echo "~/.devkit-guard-off 이 있음 — 훅이 꺼진 채라 재지 않음, 멈춤"; exit 8; }
if [ "$V" = new ]; then K=/mnt/e/claude_dev/devkit/kit; else K=$M/kit-0.4.0; fi
if [ "$V" = old ]; then
  command grep -q '"version": "0.4.0"' "$K/.claude-plugin/plugin.json" || { echo "0.4.0 사본이 아님: $K"; exit 9; }
fi
PROMPT="이 프로젝트를 분석해 줘."
D=$M/runs/survey-$NAME-$V-$N
OP=$O/survey.$NAME.$V.$N
[ -e "$OP.jsonl" ] && { echo "이미 돌림: $NAME $V $N"; exit 9; }
[ -e "$D" ] && { echo "사본이 이미 있음: $D — 확인 뒤 지우고 다시"; exit 9; }
if [ -n "$SRC" ]; then [ -d "$SRC" ] || { echo "SRC 폴더가 아님: $SRC"; exit 9; }; fi
mkdir -p "$M/runs" "$O" "$M/tmp" "$M/notmux"; export TMPDIR=$M/tmp

mkdir "$M/run.lock" 2>/dev/null || { echo "다른 실행이 잠금을 잡고 있음($M/run.lock) — 멈춤"; exit 7; }
CP=
on_sig() {
  trap '' TERM INT HUP
  if [ -n "$CP" ]; then
    kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
    c=$(costof "$OP.jsonl"); [ "$c" = "?" ] && c=$BUDGET
    echo "$c survey.$NAME.$V.$N" >> "$O/$COST_FILE"
    echo "survey.$NAME.$V.$N 신호로 끊김 cost=$c $(date +%H:%M:%S)" >> "$LOG"
  fi
  exit 143
}
trap 'rmdir "$M/run.lock"' EXIT
trap on_sig TERM INT HUP
spent=0
[ -f "$O/$COST_FILE" ] && spent=$(awk '{s+=$1} END{print s+0}' "$O/$COST_FILE")
if awk -v s="$spent" -v b="$BUDGET" -v m="$P2_STOP" 'BEGIN{exit !(s+b>m)}'; then
  echo "돈 선: 지금까지 $spent + 뚜껑 $BUDGET > 멈춤 선 $P2_STOP — 시작하지 않음"; exit 6
fi
if awk -v s="$spent" -v w="$WARN" 'BEGIN{exit !(s>=w)}'; then
  echo "알림: $COST_FILE 합 $spent ($WARN 넘음) $(date +%H:%M:%S)" >> "$LOG"
  echo "알림: $COST_FILE 합 $spent ($WARN 넘음)"
fi

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
    echo "survey.$NAME.$V.$N mem win_commit_gb 못 읽음(값 [$commit]) — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "커밋 값을 못 읽음 — 멈춤"; exit 3 ;;
  esac
  if [ "$commit" -lt 4 ]; then
    echo "survey.$NAME.$V.$N mem win_commit_gb=${commit:-?} 4 아래 — 압축 안 함, 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "메모리 부족 — 멈춤"; exit 3
  fi
  buddy=$(o7)
  if [ "${buddy:-0}" -le 0 ]; then
    python3 "$R/compact.py" 4 >> "$LOG" 2>&1
    buddy=$(o7)
  fi
  echo "survey.$NAME.$V.$N mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
  if [ "${buddy:-0}" -le 0 ]; then echo "메모리 부족 — 멈춤"; exit 3; fi
}

CL=$(command -v claude) || { echo "claude 없음"; exit 9; }
memchk
# claude 자식에게만 준다: Windows 실행 파일 폴더(/mnt/<드라이브>/)를 뺀 PATH, 빈 소켓 폴더
CLEAN=$(printf '%s' "$PATH" | tr ':' '\n' | command grep -v -E '^/mnt/[a-z]/' | command grep -v -x -F -e "$HOME/.local/bin" -e "$W/tools/bin" | paste -sd:)
if [ -z "$SRC" ]; then
  git clone -q "$W/base" "$D" || exit 7
  git -C "$D" checkout -q -b work "$BASE" || exit 7
else
  cp -a "$SRC" "$D" || exit 7
  if [ -e "$D/.claude" ] || [ -e "$D/.mcp.json" ]; then echo "사본에 .claude 또는 .mcp.json이 있음 — 멈춤: $D"; exit 9; fi
  if [ -f "$D/.git" ]; then echo "사본의 .git이 파일임 — 멈춤: $D"; exit 9; fi
  ( cd "$D" && find . -type f ! -path './.git/*' ! -path './.svn/*' ! -path './.devkit/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum ) > "$OP.before"
fi
memchk

cd "$D" || exit 9
t0=$(date +%s)
timeout "$SECS" env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$M/notmux" PATH="$CLEAN" "$CL" -p "$PROMPT" \
  --setting-sources project --plugin-dir "$K" \
  --no-session-persistence --model sonnet \
  --max-budget-usd "$BUDGET" \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" "Bash(*flask run*)" "Bash(*make serve*)" "Bash(*runserver*)" "Bash(*gunicorn*)" "Bash(*uv run*)" "Bash(*uv sync*)" "Bash(*uv add*)" "Bash(*pip *)" "Bash(*catalina*)" "Bash(*startup.sh*)" "Bash(*mvn*)" "Bash(*gradle*)" "Bash(*java -jar*)" "Bash(*tomcat*)" "Bash(*pip3*)" "Bash(*uvx*)" "Bash(*uv tool*)" "Bash(*make *)" "Bash(*uvicorn*)" "Bash(*ego-browser*)" "Bash(*.exe*)" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$OP.jsonl" 2> "$OP.err" &
CP=$!; echo "$CP" > "$OP.pid"; wait "$CP"; rc=$?
rm -f "$OP.pid"
LEFT=0; HOMEDK=0
for p in /proc/[0-9]*; do
  pid=${p#/proc/}; cwd=$(readlink "$p/cwd" 2>/dev/null) || continue
  case "$cwd" in "$D"|"$D"/*)
    [ "$pid" = "$$" ] && continue
    echo "left: $pid $(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-80)" >> "$LOG"
    LEFT=1 ;;
  esac
done
if [ -e "$HOME/.devkit" ]; then
  echo "survey.$NAME.$V.$N: home .devkit appeared" >> "$LOG"; HOMEDK=1
fi
if [ -e "$HOME/.devkit-guard-off" ]; then
  echo "survey.$NAME.$V.$N: home .devkit-guard-off appeared" >> "$LOG"; HOMEDK=1
fi
secs=$(( $(date +%s) - t0 ))
guide=없음
if [ -f "$D/.devkit/guide.md" ]; then cp "$D/.devkit/guide.md" "$OP.guide.md"; guide=있음; fi
records=$(ls "$D"/.devkit/work/*.md 2>/dev/null | wc -l)
if [ -z "$SRC" ]; then
  changed=$(git -C "$D" status --porcelain | wc -l)
else
  ( cd "$D" && find . -type f ! -path './.git/*' ! -path './.svn/*' ! -path './.devkit/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum ) > "$OP.after"
  changed=$(diff "$OP.before" "$OP.after" | command grep -c '^[<>]')
fi
long=$(journalctl -k --since "@$t0" 2>/dev/null | command grep -c "abnormally long accept")
tried=$(python3 -I /mnt/e/claude_dev/devkit/docs/measure/tried.py "$OP.jsonl")
trap '' TERM INT HUP
cost=$(costof "$OP.jsonl")
if [ "$cost" = "?" ]; then echo "$BUDGET survey.$NAME.$V.$N" >> "$O/$COST_FILE"; else echo "$cost survey.$NAME.$V.$N" >> "$O/$COST_FILE"; fi
line="survey.$NAME.$V.$N rc=$rc secs=$secs cost=$cost guide=$guide records=$records changed=$changed long_accept=$long $(date +%H:%M:%S) $tried"
echo "$line" >> "$LOG"
echo "$line"
[ "$HOMEDK" = 0 ] || exit 10
[ "$LEFT" = 0 ] || exit 11
# 예산이 끝나 0이 아닌 값이 나오는 것은 예상한 일이다 — jsonl이 있으면 다음 판정으로 간다.
[ "$rc" = 0 ] || exit 5
