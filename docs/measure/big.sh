#!/bin/bash
# big.sh <이름> <on|off> <k> — 여러 화면 기능 재기 한 번. big-prompts.txt의 k번째 줄(1~2)을 새 사본에서 끝까지 짓게 하고, 뒤에 시험·코드 모양 검사를 돈다.
# 팔: on = 꾸러미를 켬, off = 끔. 사본 $M/runs/<이름>-b<k>는 걸어 보기용으로 남기고 되돌리지 않는다. 돈 줄은 스스로 $O/big.cost에 적는다. 세는 것은 big.py가 한다.
W=/home/ssmge/zzz-devkit-exist
M=/home/ssmge/zzz-devkit-measure; O=$M/out; LOG=$O/g.log
R=/mnt/e/claude_dev/devkit/docs/measure/원본
P=/mnt/e/claude_dev/devkit/docs/measure/big-prompts.txt
K=/mnt/e/claude_dev/devkit/kit
BASE=2bc1b8b
NAME=${1-}; ARM=${2-}; N=${3-}
[ $# -eq 3 ] || { echo "인자 틀림: <이름> <on|off> <k> 셋이 있어야 함(받은 수 $#)"; exit 9; }
case "$NAME" in ''|*[!A-Za-z0-9_-]*) echo "인자 틀림: 이름은 영문·숫자·_·- 만"; exit 9 ;; esac
case "$ARM" in on|off) ;; *) echo "인자 틀림: 둘째는 on 또는 off"; exit 9 ;; esac
case "$N" in 1|2) ;; *) echo "인자 틀림: k는 1 또는 2"; exit 9 ;; esac
[ -e "$HOME/.devkit" ] && { echo "~/.devkit 이 이미 있음 — 멈춤"; exit 8; }
[ -e "$HOME/.devkit-guard-off" ] && { echo "~/.devkit-guard-off 이 있음 — 훅이 꺼진 채라 재지 않음, 멈춤"; exit 8; }
[ -f "$P" ] || { echo "부탁 파일 없음"; exit 9; }
PROMPT=$(sed -n "${N}p" "$P")
[ -n "$PROMPT" ] || { echo "부탁 없음"; exit 9; }
OP=$O/big.$NAME.$N
D=$M/runs/$NAME-b$N
[ -e "$OP.jsonl" ] && { echo "이미 돌림: $NAME $N"; exit 9; }
[ -e "$D" ] && { echo "사본이 이미 있음: $D — 확인 뒤 지우고 다시"; exit 9; }
mkdir -p "$M/runs" "$O" "$M/tmp"; export TMPDIR=$M/tmp

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
commit=$(cd /mnt/c && timeout 60 powershell.exe -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
case "$commit" in ''|*[!0-9]*)
  echo "big.$NAME.$N mem win_commit_gb 못 읽음(값 [$commit]) — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
  echo "커밋 값을 못 읽음 — 멈춤"; exit 3 ;;
esac
if [ "$commit" -lt 4 ]; then
  echo "big.$NAME.$N mem win_commit_gb=${commit:-?} 4 아래 — 압축 안 함, 멈춤 $(date +%H:%M:%S)" >> "$LOG"
  echo "메모리 부족 — 멈춤"; exit 3
fi
buddy=$(o7)
if [ "${buddy:-0}" -le 0 ]; then
  python3 "$R/compact.py" 4 >> "$LOG" 2>&1
  buddy=$(o7)
fi
echo "big.$NAME.$N mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
if [ "${buddy:-0}" -le 0 ]; then echo "메모리 부족 — 멈춤"; exit 3; fi

export UV_CACHE_DIR=$W/uvcache UV_PYTHON_DOWNLOADS=never PATH=$W/tools/bin:$PATH
# claude 자식에게만 준다: Windows 실행 파일 폴더(/mnt/<드라이브>/)를 뺀 PATH, 빈 tmux 소켓 폴더
CLEAN=$(printf '%s' "$PATH" | tr ':' '\n' | command grep -v -E '^/mnt/[a-z]/' | paste -sd:)
mkdir -p "$M/notmux"
git clone -q "$W/base" "$D" || exit 7
git -C "$D" checkout -q -b work "$BASE" || exit 7
( cd "$D" && uv sync -q --extra dev --python /usr/bin/python3 ) > "$OP.sync" 2>&1 || { echo "설치 실패"; exit 7; }
cp "$W/seed.db" "$M/runs/$NAME-b$N.db"
printf 'SQLALCHEMY_DATABASE_URI = "sqlite:///%s"\nSESSION_COOKIE_SECURE = False\n' "$M/runs/$NAME-b$N.db" > "$M/runs/$NAME-b$N.cfg"
export IHATEMONEY_SETTINGS_FILE_PATH=$M/runs/$NAME-b$N.cfg

cd "$D" || exit 9
# 설치가 추적 파일을 바꿨으면 실행 전 커밋으로 뺀다 — 세는 바탕($OP.base)은 이 커밋이다
if [ -n "$(git status --porcelain)" ]; then
  git add -A >/dev/null 2>&1
  git -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false commit -q --no-verify -m "big pre $NAME $N" >/dev/null 2>&1 || {
    echo "big.$NAME.$N 실행 전 커밋 실패 $(date +%H:%M:%S)" >> "$LOG"; echo "실행 전 커밋 실패"; exit 6; }
fi
git rev-parse HEAD > "$OP.base"
t0=$(date +%s)
# 신호(TERM·INT·HUP)로 끊기면 claude를 끄고 돈 줄을 적은 뒤 143으로 끝낸다. 잠금은 만지지 않는다
CP=
on_sig() {
  trap '' TERM INT HUP
  if [ -n "$CP" ]; then
    kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
    c=$(costof "$OP.jsonl"); [ "$c" = "?" ] && c=2.50
    echo "$c big.$NAME.$N" >> "$O/big.cost"
    rm -f "$OP.pid"
    echo "big.$NAME.$N 신호로 끊김 cost=$c $(date +%H:%M:%S)" >> "$LOG"
  fi
  exit 143
}
trap on_sig TERM INT HUP
PD=()
[ "$ARM" = on ] && PD=(--plugin-dir "$K")
timeout 2400 env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$M/notmux" PATH="$CLEAN" claude -p "$PROMPT" "${PD[@]}" \
  --setting-sources project \
  --no-session-persistence --model sonnet \
  --max-budget-usd 2.50 \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$OP.jsonl" 2> "$OP.err" &
CP=$!; echo "$CP" > "$OP.pid"; wait "$CP"; rc=$?
rm -f "$OP.pid"
trap '' TERM INT HUP
cost=$(costof "$OP.jsonl")
if [ "$cost" = "?" ]; then echo "2.50 big.$NAME.$N" >> "$O/big.cost"; else echo "$cost big.$NAME.$N" >> "$O/big.cost"; fi
CP=
trap on_sig TERM INT HUP
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
  echo "big.$NAME.$N: home .devkit appeared" >> "$LOG"; HOMEDK=1
fi
secs=$(( $(date +%s) - t0 ))
git status --short > "$OP.status" 2>&1
git add -A >/dev/null 2>&1
committed=ok
git -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false commit -q --no-verify --allow-empty -m "big $NAME $N" >/dev/null 2>&1 || committed=bad
[ -z "$(git status --porcelain)" ] || committed=bad
# 끝난 뒤: 프로젝트 자체 시험과 코드 모양 검사
tests=$(env -u IHATEMONEY_SETTINGS_FILE_PATH timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider . 2>&1 | tail -1)
lint=$(.venv/bin/python -m ruff check ihatemoney 2>&1 | tail -1)
fmt=$(.venv/bin/python -m ruff format --check ihatemoney 2>&1 | tail -1)
git status --short | command grep -v '^??' > "$OP.after-tests" 2>&1
printf 'arm=%s\nrc=%s\nsecs=%s\ntests=%s\nlint=%s\nfmt=%s\ncommitted=%s\n' "$ARM" "$rc" "$secs" "$tests" "$lint" "$fmt" "$committed" > "$OP.check"
long=$(journalctl -k --since "@$t0" 2>/dev/null | command grep -c "abnormally long accept")
tried=$(python3 -I /mnt/e/claude_dev/devkit/docs/measure/tried.py "$OP.jsonl")
echo "big.$NAME.$N arm=$ARM rc=$rc secs=$secs committed=$committed tests=[$tests] lint=[$lint] fmt=[$fmt] long_accept=$long $(date +%H:%M:%S) $tried" >> "$LOG"
echo "big.$NAME.$N arm=$ARM rc=$rc secs=$secs committed=$committed tests=[$tests] lint=[$lint] fmt=[$fmt] $tried"
[ "$HOMEDK" = 0 ] || exit 10
[ "$LEFT" = 0 ] || exit 11
[ "$committed" = ok ] || exit 6
# 예산이 끝나 0이 아닌 값이 나오는 것은 큰 부탁에서 예상한 일이다 — jsonl이 있으면 big.py로 세고 다음으로 간다.
[ "$rc" = 0 ] || exit 5
