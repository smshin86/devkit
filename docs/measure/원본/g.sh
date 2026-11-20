#!/bin/bash
# g.sh <이름> <one|plain> <부탁 번호> — 이어 붙이기 시험. 같은 폴더(runs/<이름>)에 부탁을 하나 더 쌓는다.
# 폴더가 없으면 고르기 전(base) 지점에서 새로 만들고, 있으면 그 위에 이어서 한다. 부탁마다 새 대화.
S=/tmp/claude-1000/-mnt-e-claude-dev-devkit/526c50c9-e222-4b46-949b-0fd20e0a8859/scratchpad
K=/mnt/e/claude_dev/devkit/kit
W=/home/ssmge/zzz-devkit-exist; O=$W/out; LOG=$O/g.log
BASE=2bc1b8b
NAME=${1:?이름}; ARM=${2:?one|plain}; N=${3:?부탁 번호}
D=$W/runs/$NAME
[ -e "$O/g.$NAME.$N.jsonl" ] && { echo "이미 돌림: $NAME $N"; exit 9; }
[ -e "$HOME/.devkit" ] && { echo "~/.devkit 이 이미 있음 — 멈춤"; exit 8; }
[ -f "$W/reqs/$N.txt" ] || { echo "부탁 없음"; exit 9; }
case "$ARM" in one|plain) ;; *) echo "one|plain"; exit 9;; esac
mkdir -p "$W/runs" "$O" "$S/exist/tmp"; export TMPDIR=$S/exist/tmp

o7() { awk '/Normal/{s=0; for(i=12;i<=NF;i++) s+=$i; print s}' /proc/buddyinfo; }
buddy=$(o7)
if [ "${buddy:-0}" -le 0 ]; then
  python3 "$W/compact.py" 4 >> "$LOG" 2>&1
  buddy=$(o7)
fi
commit=$(cd /mnt/c && powershell.exe -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
echo "$NAME.$N mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
if [ "${buddy:-0}" -le 0 ] || [ "${commit:-0}" -lt 4 ]; then echo "메모리 부족 — 멈춤"; exit 3; fi

export UV_CACHE_DIR=$W/uvcache UV_PYTHON_DOWNLOADS=never PATH=$W/tools/bin:$PATH
if [ ! -e "$D" ]; then
  git clone -q "$W/base" "$D" || exit 7
  git -C "$D" checkout -q -b work "$BASE" || exit 7
  ( cd "$D" && uv sync -q --extra dev --python /usr/bin/python3 ) > "$O/g.$NAME.sync" 2>&1 || { echo "설치 실패"; exit 7; }
  cp "$W/seed.db" "$W/runs/$NAME.db"
  printf 'SQLALCHEMY_DATABASE_URI = "sqlite:///%s"\nSESSION_COOKIE_SECURE = False\n' "$W/runs/$NAME.db" > "$W/runs/$NAME.cfg"
fi
export IHATEMONEY_SETTINGS_FILE_PATH=$W/runs/$NAME.cfg

PLUG=()
if [ "$ARM" = one ]; then PLUG=(--plugin-dir "$K"); fi

cd "$D" || exit 9
t0=$(date +%s)
timeout 3000 claude -p "$(cat "$W/reqs/$N.txt")" \
  --setting-sources project "${PLUG[@]}" \
  --no-session-persistence --model sonnet \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$O/g.$NAME.$N.jsonl" 2> "$O/g.$NAME.$N.err"
rc=$?
for p in /proc/[0-9]*; do
  pid=${p#/proc/}; cwd=$(readlink "$p/cwd" 2>/dev/null) || continue
  case "$cwd" in "$D"|"$D"/*)
    [ "$pid" = "$$" ] && continue
    echo "left: kill $pid ($(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-80))" >> "$LOG"
    kill "$pid" 2>/dev/null ;;
  esac
done
if [ -e "$HOME/.devkit" ]; then
  mv "$HOME/.devkit" "$O/g.$NAME.$N.home-devkit.$(date +%s)"; echo "$NAME.$N: home .devkit moved to out" >> "$LOG"
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
echo "$NAME.$N rc=$rc secs=$secs tests=[$tests] lint=[$lint] fmt=[$fmt] long_accept_10m=$long $(date +%H:%M:%S)" >> "$LOG"
echo "$NAME.$N rc=$rc secs=$secs tests=[$tests] lint=[$lint]"
[ "$rc" = 0 ] || exit 5
