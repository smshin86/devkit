#!/bin/bash
# door.sh <이름> <k> — 문 부탁 시험. door-prompts.txt의 k번째 줄(1~9)을 부탁마다 새 사본에서 한 번 돌린다.
# 사본은 고르기 전(base) 지점에서 새로 만든다. 사본 안 커밋·뒤 시험·검사는 하지 않는다. 판정은 door.py가 한다.
W=/home/ssmge/zzz-devkit-exist
M=/home/ssmge/zzz-devkit-measure; O=$M/out; LOG=$O/g.log
R=/mnt/e/claude_dev/devkit/docs/measure/원본
P=/mnt/e/claude_dev/devkit/docs/measure/door-prompts.txt
K=/mnt/e/claude_dev/devkit/kit
BASE=2bc1b8b
NAME=${1?이름}; N=${2:?k(1~9)}
case "$NAME" in ''|*[!A-Za-z0-9_-]*) echo "이름은 영문·숫자·_·- 만"; exit 9 ;; esac
case "$N" in [1-9]) ;; *) echo "k는 1~9"; exit 9 ;; esac
D=$M/runs/$NAME-d$N
[ -e "$O/door.$NAME.$N.jsonl" ] && { echo "이미 돌림: $NAME $N"; exit 9; }
[ -e "$D" ] && { echo "사본이 이미 있음: $D — 확인 뒤 지우고 다시"; exit 9; }
[ -e "$HOME/.devkit" ] && { echo "~/.devkit 이 이미 있음 — 멈춤"; exit 8; }
[ -f "$P" ] || { echo "부탁 파일 없음"; exit 9; }
PROMPT=$(sed -n "${N}p" "$P")
[ -n "$PROMPT" ] || { echo "부탁 없음"; exit 9; }
mkdir -p "$M/runs" "$O" "$M/tmp"; export TMPDIR=$M/tmp

o7() { awk '/Normal/{s=0; for(i=12;i<=NF;i++) s+=$i; print s}' /proc/buddyinfo; }
commit=$(cd /mnt/c && powershell.exe -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
case "$commit" in ''|*[!0-9]*)
  echo "door.$NAME.$N mem win_commit_gb 못 읽음(값 [$commit]) — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
  echo "커밋 값을 못 읽음 — 멈춤"; exit 3 ;;
esac
if [ "$commit" -lt 4 ]; then
  echo "door.$NAME.$N mem win_commit_gb=${commit:-?} 4 아래 — 압축 안 함, 멈춤 $(date +%H:%M:%S)" >> "$LOG"
  echo "메모리 부족 — 멈춤"; exit 3
fi
buddy=$(o7)
if [ "${buddy:-0}" -le 0 ]; then
  python3 "$R/compact.py" 4 >> "$LOG" 2>&1
  buddy=$(o7)
fi
echo "door.$NAME.$N mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
if [ "${buddy:-0}" -le 0 ]; then echo "메모리 부족 — 멈춤"; exit 3; fi

export UV_CACHE_DIR=$W/uvcache UV_PYTHON_DOWNLOADS=never PATH=$W/tools/bin:$PATH
# claude 자식에게만 준다: Windows 실행 파일 폴더(/mnt/<드라이브>/)를 뺀 PATH, 빈 tmux 소켓 폴더
CLEAN=$(printf '%s' "$PATH" | tr ':' '\n' | command grep -v -E '^/mnt/[a-z]/' | paste -sd:)
mkdir -p "$M/notmux"
git clone -q "$W/base" "$D" || exit 7
git -C "$D" checkout -q -b work "$BASE" || exit 7
( cd "$D" && uv sync -q --extra dev --python /usr/bin/python3 ) > "$O/door.$NAME.$N.sync" 2>&1 || { echo "설치 실패"; exit 7; }
cp "$W/seed.db" "$M/runs/$NAME-d$N.db"
printf 'SQLALCHEMY_DATABASE_URI = "sqlite:///%s"\nSESSION_COOKIE_SECURE = False\n' "$M/runs/$NAME-d$N.db" > "$M/runs/$NAME-d$N.cfg"
export IHATEMONEY_SETTINGS_FILE_PATH=$M/runs/$NAME-d$N.cfg

cd "$D" || exit 9
t0=$(date +%s)
timeout 1200 env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$M/notmux" PATH="$CLEAN" claude -p "$PROMPT" \
  --setting-sources project --plugin-dir "$K" \
  --no-session-persistence --model sonnet \
  --max-budget-usd 0.60 \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$O/door.$NAME.$N.jsonl" 2> "$O/door.$NAME.$N.err" &
CP=$!; echo "$CP" > "$O/door.$NAME.$N.pid"; wait "$CP"; rc=$?
rm -f "$O/door.$NAME.$N.pid"
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
  echo "door.$NAME.$N: home .devkit appeared" >> "$LOG"; HOMEDK=1
fi
secs=$(( $(date +%s) - t0 ))
long=$(journalctl -k --since "-10 min" 2>/dev/null | command grep -c "abnormally long accept")
tried=$(python3 -I /mnt/e/claude_dev/devkit/docs/measure/tried.py "$O/door.$NAME.$N.jsonl")
echo "door.$NAME.$N rc=$rc secs=$secs long_accept_10m=$long $(date +%H:%M:%S) $tried" >> "$LOG"
echo "door.$NAME.$N rc=$rc secs=$secs $tried"
[ "$HOMEDK" = 0 ] || exit 10
[ "$LEFT" = 0 ] || exit 11
# 예산이 끝나 0이 아닌 값이 나오는 것은 큰 부탁에서 예상한 일이다 — jsonl이 있으면 door.py로 판정하고 다음으로 간다.
[ "$rc" = 0 ] || exit 5
