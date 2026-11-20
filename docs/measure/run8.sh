#!/bin/bash
# run8.sh <이름> <new|old> <부탁 번호> — 이어 붙이기 시험. 같은 폴더(runs/<이름>)에 부탁을 하나 더 쌓는다.
# 폴더가 없으면 고르기 전(base) 지점에서 새로 만들고, 있으면 그 위에 이어서 한다. 부탁마다 새 대화.
W=/home/ssmge/zzz-devkit-exist
M=/home/ssmge/zzz-devkit-measure; O=$M/out; LOG=$O/g.log
R=/mnt/e/claude_dev/devkit/docs/measure/원본
BASE=2bc1b8b
NAME=${1?이름}; ARM=${2:?new|old}; N=${3:?부탁 번호}
case "$NAME" in ''|*[!A-Za-z0-9_-]*) echo "이름은 영문·숫자·_·- 만"; exit 9 ;; esac
D=$M/runs/$NAME
[ -e "$O/g.$NAME.$N.jsonl" ] && { echo "이미 돌림: $NAME $N"; exit 9; }
[ -e "$HOME/.devkit" ] && { echo "~/.devkit 이 이미 있음 — 멈춤"; exit 8; }
[ -f "$R/reqs/$N.txt" ] || { echo "부탁 없음"; exit 9; }
case "$ARM" in
  new) K=/mnt/e/claude_dev/devkit/kit ;;
  old) K=/mnt/e/claude_dev/devkit/old/kit-0.3.0 ;;
  *) echo "new|old"; exit 9 ;;
esac
mkdir -p "$M/runs" "$O" "$M/tmp"; export TMPDIR=$M/tmp

o7() { awk '/Normal/{s=0; for(i=12;i<=NF;i++) s+=$i; print s}' /proc/buddyinfo; }
commit=$(cd /mnt/c && powershell.exe -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
case "$commit" in ''|*[!0-9]*)
  echo "$NAME.$N mem win_commit_gb 못 읽음(값 [$commit]) — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
  echo "커밋 값을 못 읽음 — 멈춤"; exit 3 ;;
esac
if [ "$commit" -lt 4 ]; then
  echo "$NAME.$N mem win_commit_gb=${commit:-?} 4 아래 — 압축 안 함, 멈춤 $(date +%H:%M:%S)" >> "$LOG"
  echo "메모리 부족 — 멈춤"; exit 3
fi
buddy=$(o7)
if [ "${buddy:-0}" -le 0 ]; then
  python3 "$R/compact.py" 4 >> "$LOG" 2>&1
  buddy=$(o7)
fi
echo "$NAME.$N mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
if [ "${buddy:-0}" -le 0 ]; then echo "메모리 부족 — 멈춤"; exit 3; fi

export UV_CACHE_DIR=$W/uvcache UV_PYTHON_DOWNLOADS=never PATH=$W/tools/bin:$PATH
# claude 자식에게만 준다: Windows 실행 파일 폴더(/mnt/<드라이브>/)를 뺀 PATH, 빈 tmux 소켓 폴더
CLEAN=$(printf '%s' "$PATH" | tr ':' '\n' | command grep -v -E '^/mnt/[a-z]/' | paste -sd:)
mkdir -p "$M/notmux"
if [ -e "$D" ] && [ ! -e "$O/$NAME.ready" ]; then
  echo "사본이 덜 만들어짐: $D — 확인 뒤 지우고 다시"; exit 7
fi
if [ ! -e "$D" ]; then
  git clone -q "$W/base" "$D" || exit 7
  git -C "$D" checkout -q -b work "$BASE" || exit 7
  ( cd "$D" && uv sync -q --extra dev --python /usr/bin/python3 ) > "$O/g.$NAME.sync" 2>&1 || { echo "설치 실패"; exit 7; }
  cp "$W/seed.db" "$M/runs/$NAME.db"
  printf 'SQLALCHEMY_DATABASE_URI = "sqlite:///%s"\nSESSION_COOKIE_SECURE = False\n' "$M/runs/$NAME.db" > "$M/runs/$NAME.cfg"
  touch "$O/$NAME.ready"
fi
export IHATEMONEY_SETTINGS_FILE_PATH=$M/runs/$NAME.cfg

cd "$D" || exit 9
t0=$(date +%s)
timeout 1200 env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$M/notmux" PATH="$CLEAN" claude -p "$(cat "$R/reqs/$N.txt")" \
  --setting-sources project --plugin-dir "$K" \
  --no-session-persistence --model sonnet \
  --max-budget-usd 1.50 \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$O/g.$NAME.$N.jsonl" 2> "$O/g.$NAME.$N.err" &
CP=$!; echo "$CP" > "$O/g.$NAME.$N.pid"; wait "$CP"; rc=$?
rm -f "$O/g.$NAME.$N.pid"
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
  echo "$NAME.$N: home .devkit appeared" >> "$LOG"; HOMEDK=1
fi
secs=$(( $(date +%s) - t0 ))
git status --short > "$O/g.$NAME.$N.status" 2>&1
git add -A >/dev/null 2>&1
git -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m "g $NAME $N" >/dev/null 2>&1
# 부탁 하나가 끝날 때마다: 프로젝트 자체 시험과 코드 모양 검사 (Ga)
tests=$(env -u IHATEMONEY_SETTINGS_FILE_PATH timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider . 2>&1 | tail -1)
lint=$(.venv/bin/python -m ruff check ihatemoney 2>&1 | tail -1)
fmt=$(.venv/bin/python -m ruff format --check ihatemoney 2>&1 | tail -1)
git status --short | command grep -v '^??' > "$O/g.$NAME.$N.after-tests" 2>&1
git checkout -q -- . 2>/dev/null
long=$(journalctl -k --since "-10 min" 2>/dev/null | command grep -c "abnormally long accept")
tried=$(python3 -I /mnt/e/claude_dev/devkit/docs/measure/tried.py "$O/g.$NAME.$N.jsonl")
echo "$NAME.$N rc=$rc secs=$secs tests=[$tests] lint=[$lint] fmt=[$fmt] long_accept_10m=$long $(date +%H:%M:%S) $tried" >> "$LOG"
echo "$NAME.$N rc=$rc secs=$secs tests=[$tests] lint=[$lint] $tried"
[ "$HOMEDK" = 0 ] || exit 10
[ "$LEFT" = 0 ] || exit 11
[ "$rc" = 0 ] || exit 5
