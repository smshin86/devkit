#!/bin/bash
# intake.sh <이름> <new|old> <k> — 받기 재기 한 번. intake-prompts.txt의 k번째 줄(1~3)을 새 사본에서 첫 턴으로 보내고,
# 같은 대화를 이어 intake-replies.txt의 k번째 줄을 둘째 턴으로 보낸다. 뒤에 시험·코드 모양 검사를 돈다.
# 팔: new = 지금 꾸러미, old = 옛 꾸러미. 사본 $M/runs/<이름>-i<k>는 걸어 보기용으로 남기고 되돌리지 않는다. 돈 줄은 스스로 $O/intake.cost에 적는다. 세는 것은 intake.py와 big.py가 한다.
# 환경 변수 다섯은 다 같이 주거나 다 같이 안 준다(하나만 있거나 꼴이 틀리면 끝 값 9): IK_KIT=꾸러미 절대 경로 · IK_ARM=팔 이름표(둘째 인자와 같게) · IK_COST=장부 이름 <이름>.cost(기본 intake.cost) · IK_NEED=한 번에 더 드는 돈(기본 2.50) · IK_STOP=합 상한(기본 8.00).
# 변수를 안 주면 팔은 new/old, 장부는 intake.cost, 돈 선은 2.50/8.00 그대로다.
W=/home/ssmge/zzz-devkit-exist
M=/home/ssmge/zzz-devkit-measure; O=$M/out; LOG=$O/g.log
R=/mnt/e/claude_dev/devkit/docs/measure/원본
P=/mnt/e/claude_dev/devkit/docs/measure/intake-prompts.txt
A=/mnt/e/claude_dev/devkit/docs/measure/intake-replies.txt
CUM=1
BASE=2bc1b8b
NAME=${1-}; ARM=${2-}; N=${3-}
[ $# -eq 3 ] || { echo "인자 틀림: <이름> <new|old> <k> 셋이 있어야 함(받은 수 $#)"; exit 9; }
case "$NAME" in ''|*[!A-Za-z0-9_-]*) echo "인자 틀림: 이름은 영문·숫자·_·- 만"; exit 9 ;; esac
if [ -n "${IK_KIT+x}${IK_ARM+x}${IK_COST+x}${IK_NEED+x}${IK_STOP+x}" ]; then
  [ "${IK_KIT+x}${IK_ARM+x}${IK_COST+x}${IK_NEED+x}${IK_STOP+x}" = xxxxx ] || { echo "인자 틀림: IK_KIT IK_ARM IK_COST IK_NEED IK_STOP은 다섯 다 주거나 다 안 줌"; exit 9; }
  case "$IK_KIT" in /*) ;; *) echo "인자 틀림: IK_KIT는 절대 경로"; exit 9 ;; esac
  case "$IK_KIT" in */../*|*/..) echo "인자 틀림: IK_KIT에 .. 없어야 함"; exit 9 ;; esac
  [ -f "$IK_KIT/.claude-plugin/plugin.json" ] || { echo "인자 틀림: IK_KIT에 .claude-plugin/plugin.json 없음"; exit 9; }
  [[ $IK_ARM =~ ^[a-z][a-z0-9]{0,7}$ ]] || { echo "인자 틀림: IK_ARM은 소문자로 시작하는 영소문자·숫자 8자 이내"; exit 9; }
  case "$IK_ARM" in new|old) echo "인자 틀림: IK_ARM은 new·old가 아니어야 함"; exit 9 ;; esac
  [ "$IK_ARM" = "$ARM" ] || { echo "인자 틀림: IK_ARM과 둘째 인자가 같아야 함"; exit 9; }
  K=$IK_KIT
else
case "$ARM" in new) K=/mnt/e/claude_dev/devkit/kit ;; old) K=/mnt/e/claude_dev/devkit/old/kit-0.3.0 ;; *) echo "인자 틀림: 둘째는 new 또는 old"; exit 9 ;; esac
fi
case "$N" in 1|2|3) ;; *) echo "인자 틀림: k는 1~3"; exit 9 ;; esac
LEDGER_NAME=${IK_COST-intake.cost}
NEED=${IK_NEED-2.50}
STOP=${IK_STOP-8.00}
[[ $LEDGER_NAME =~ ^[A-Za-z0-9_-]+\.cost$ ]] || { echo "인자 틀림: IK_COST는 <이름>.cost 꼴"; exit 9; }
[[ $NEED =~ ^[0-9]{1,2}\.[0-9]{2}$ ]] || { echo "인자 틀림: IK_NEED는 n.nn 꼴"; exit 9; }
[[ $STOP =~ ^[0-9]{1,2}\.[0-9]{2}$ ]] || { echo "인자 틀림: IK_STOP은 n.nn 꼴"; exit 9; }
awk -v n="$NEED" 'BEGIN{exit !(n>0)}' || { echo "인자 틀림: IK_NEED는 0보다 커야 함"; exit 9; }
awk -v n="$NEED" -v t="$STOP" 'BEGIN{exit !(t>n)}' || { echo "인자 틀림: IK_STOP은 IK_NEED보다 커야 함"; exit 9; }
LEDGER=$O/$LEDGER_NAME
unset IK_KIT IK_ARM IK_COST IK_NEED IK_STOP
[ -e "$HOME/.devkit" ] && { echo "~/.devkit 이 이미 있음 — 멈춤"; exit 8; }
[ -e "$HOME/.devkit-guard-off" ] && { echo "~/.devkit-guard-off 이 있음 — 훅이 꺼진 채라 재지 않음, 멈춤"; exit 8; }
[ -f "$P" ] || { echo "부탁 파일 없음"; exit 9; }
[ -f "$A" ] || { echo "답 파일 없음"; exit 9; }
PROMPT=$(sed -n "${N}p" "$P")
[ -n "$PROMPT" ] || { echo "부탁 없음"; exit 9; }
REPLY=$(sed -n "${N}p" "$A")
[ -n "$REPLY" ] || { echo "답 없음"; exit 9; }
OP=$O/intake.$NAME.$N
D=$M/runs/$NAME-i$N
[ -e "$OP.t1.jsonl" ] && { echo "이미 돌림: $NAME $N"; exit 9; }
[ -e "$D" ] && { echo "사본이 이미 있음: $D — 확인 뒤 지우고 다시"; exit 9; }
spent=0.00
[ -f "$LEDGER" ] && spent=$(awk '{s+=$1} END{printf "%.2f", s+0}' "$LEDGER")
if awk -v s="$spent" -v n="$NEED" -v t="$STOP" 'BEGIN{exit !(s+n>t)}'; then
  echo "돈 멈춤: 합 $spent + $NEED > $STOP"; exit 4
fi
mkdir -p "$M/runs" "$O" "$M/tmp"; export TMPDIR=$M/tmp
if awk -v s="$spent" 'BEGIN{exit !(s>=6)}'; then
  echo "intake.$NAME.$N 돈 알림 합=$spent" >> "$LOG"
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
# 기계 감시: 한 번 부를 때마다 로그에 한 줄을 남기고, 멈출 일이면 3을 돌려준다
memok() {
  local commit buddy free cok
commit=$(cd /mnt/c && timeout 60 powershell.exe -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
  case "$commit" in ''|*[!0-9]*)
    echo "intake.$NAME.$N.$1 mem win_commit_gb 못 읽음(값 [$commit]) — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "커밋 값을 못 읽음 — 멈춤"; return 3 ;;
  esac
  if [ "$commit" -lt 4 ]; then
    echo "intake.$NAME.$N.$1 mem win_commit_gb=${commit:-?} 4 아래 — 압축 안 함, 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "메모리 부족 — 멈춤"; return 3
  fi
  buddy=$(o7)
  if [ "${buddy:-0}" -le 0 ]; then
    free=$(awk '/^MemFree:/{print $2}' /proc/meminfo)
    cok=0
    case "$free" in ''|*[!0-9]*) ;; *) [ "$free" -le 1572864 ] && cok=1 ;; esac
    if [ "$cok" = 1 ]; then
      python3 "$R/compact.py" 4 >> "$LOG" 2>&1
      buddy=$(o7)
    else
      echo "intake.$NAME.$N.$1 mem buddy_o7+=0 memfree_kb=$free 압축 안 함 — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
      echo "메모리 부족(빈 쪽이 넉넉해 압축 안 함) — 멈춤"; return 3
    fi
  fi
  echo "intake.$NAME.$N.$1 mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
  if [ "${buddy:-0}" -le 0 ]; then echo "메모리 부족 — 멈춤"; return 3; fi
  return 0
}
memok t1 || exit 3

export UV_CACHE_DIR=$W/uvcache UV_PYTHON_DOWNLOADS=never PATH=$W/tools/bin:$PATH
# claude 자식에게만 준다: Windows 실행 파일 폴더(/mnt/<드라이브>/)를 뺀 PATH, 빈 tmux 소켓 폴더
CLEAN=$(printf '%s' "$PATH" | tr ':' '\n' | command grep -v -E '^/mnt/[a-z]/' | paste -sd:)
mkdir -p "$M/notmux"
git clone -q "$W/base" "$D" || exit 7
git -C "$D" checkout -q -b work "$BASE" || exit 7
( cd "$D" && uv sync -q --extra dev --python /usr/bin/python3 ) > "$OP.sync" 2>&1 || { echo "설치 실패"; exit 7; }
cp "$W/seed.db" "$M/runs/$NAME-i$N.db"
printf 'SQLALCHEMY_DATABASE_URI = "sqlite:///%s"\nSESSION_COOKIE_SECURE = False\n' "$M/runs/$NAME-i$N.db" > "$M/runs/$NAME-i$N.cfg"
export IHATEMONEY_SETTINGS_FILE_PATH=$M/runs/$NAME-i$N.cfg

cd "$D" || exit 9
# 설치가 추적 파일을 바꿨으면 실행 전 커밋으로 뺀다 — 세는 바탕($OP.base)은 이 커밋이다
if [ -n "$(git status --porcelain)" ]; then
  git add -A >/dev/null 2>&1
  git -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false commit -q --no-verify -m "intake pre $NAME $N" >/dev/null 2>&1 || {
    echo "intake.$NAME.$N 실행 전 커밋 실패 $(date +%H:%M:%S)" >> "$LOG"; echo "실행 전 커밋 실패"; exit 6; }
fi
git rev-parse HEAD > "$OP.base"

# 대화 번호: 첫 턴에 정해 주고, 둘째 턴이 같은 대화를 잇는다. 나중에 대화 파일을 정확한 경로로 지우려고 먼저 적어 둔다
SID=$(cat /proc/sys/kernel/random/uuid)
[[ "$SID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || { echo "대화 번호 못 만듦"; exit 9; }
echo "$SID $D" >> "$O/intake.sessions"

# 대화 파일에서 읽는 조각 둘. 글은 자료이므로 json으로만 읽고, 대화 번호는 uuid 꼴일 때만 내보낸다
initsid() {
  python3 -I -c '
import json, re, sys
U = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
try:
    for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if isinstance(e, dict) and e.get("type") == "system" and e.get("subtype") == "init":
            s = e.get("session_id")
            if isinstance(s, str) and U.match(s):
                print(s)
            break
except OSError:
    pass' "$1"
}
t1check() {
  python3 -I -c '
import json, re, sys
U = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
sid = sys.argv[2]
init = res = None
try:
    for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("type") == "system" and e.get("subtype") == "init" and init is None:
            init = e
        elif e.get("type") == "result":
            res = e
except OSError:
    pass
s = init.get("session_id") if init else None
if not (isinstance(s, str) and U.match(s)):
    print("skip:nosid")
elif s != sid:
    print("skip:differ")
elif res is None:
    print("skip:noresult")
elif res.get("subtype") == "error_max_budget_usd":
    print("skip:budget")
elif res.get("session_id") != sid:
    print("skip:differ")
else:
    print("ok")' "$1" "$2"
}

# 신호(TERM·INT·HUP)로 끊기면 claude를 끄고 돈 줄을 적은 뒤 143으로 끝낸다. 잠금은 만지지 않는다
CP=; TURN=t1; cost1=0
on_sig() {
  trap '' TERM INT HUP
  if [ -n "$CP" ]; then
    kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
    c=$(costof "$OP.$TURN.jsonl")
    if [ "$TURN" = t2 ] && [ "$CUM" = 1 ] && [ "$c" != "?" ]; then
      c=$(awk -v a="$c" -v b="$cost1" 'BEGIN{d=a-b; if (d<0) d=0; printf "%.2f", d}')
    fi
    [ "$c" = "?" ] && c=2.50
    echo "$c intake.$NAME.$N.$TURN" >> "$LEDGER"
    rm -f "$OP.pid"
    echo "intake.$NAME.$N 신호로 끊김 turn=$TURN cost=$c $(date +%H:%M:%S)" >> "$LOG"
  fi
  exit 143
}
trap on_sig TERM INT HUP

# 끝난 뒤 사본에 남은 프로세스와 ~/.devkit을 본다. LEFT·HOMEDK는 두 턴에 걸쳐 쌓인다
LEFT=0; HOMEDK=0
after() {
  for p in /proc/[0-9]*; do
    pid=${p#/proc/}; cwd=$(readlink "$p/cwd" 2>/dev/null) || continue
    case "$cwd" in "$D"|"$D"/*)
      [ "$pid" = "$$" ] && continue
      echo "left: $pid $(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-80)" >> "$LOG"
      LEFT=1 ;;
    esac
  done
  if [ -e "$HOME/.devkit" ]; then
    echo "intake.$NAME.$N.$1: home .devkit appeared" >> "$LOG"; HOMEDK=1
  fi
}

# --- 첫 턴 ---
TURN=t1; t0=$(date +%s)
PD=(--plugin-dir "$K")
timeout 2400 env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$M/notmux" PATH="$CLEAN" claude -p "$PROMPT" --session-id "$SID" "${PD[@]}" \
  --setting-sources project \
  --model sonnet \
  --max-budget-usd 2.50 \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$OP.t1.jsonl" 2> "$OP.t1.err" &
CP=$!; echo "$CP" > "$OP.pid"; wait "$CP"; rc1=$?
rm -f "$OP.pid"
trap '' TERM INT HUP
cost1=$(costof "$OP.t1.jsonl")
if [ "$cost1" = "?" ]; then cost1=2.50; fi
echo "$cost1 intake.$NAME.$N.t1" >> "$LEDGER"
CP=
trap on_sig TERM INT HUP
after t1
secs1=$(( $(date +%s) - t0 ))
if [ -e .devkit ]; then cp -a .devkit "$OP.t1.devkit"; fi
git status --short > "$OP.t1.status" 2>&1
# 사진: 커밋하지 않는다. 사본 밖 임시 인덱스로 트리만 만들어 어느 가지에도 걸지 않는 커밋을 하나 만든다
committed=ok
IX=$M/tmp/intake.$NAME.$N.idx
rm -f "$IX"
if GIT_INDEX_FILE="$IX" git read-tree "$(cat "$OP.base")" &&
   GIT_INDEX_FILE="$IX" git add -A &&
   tree=$(GIT_INDEX_FILE="$IX" git write-tree) &&
   snap=$(git -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false commit-tree "$tree" -p "$(cat "$OP.base")" -m snap < /dev/null) &&
   [ -n "$snap" ] &&
   echo "$snap" > "$OP.t1"; then
  :
else
  committed=bad
  rm -f "$OP.t1"
fi
rm -f "$IX"

# --- 둘째 턴을 보낼지 ---
T2=sent
if [ "$rc1" = 124 ]; then T2=skip:timeout; fi
if [ "$T2" = sent ]; then
  v=$(t1check "$OP.t1.jsonl" "$SID")
  case "$v" in skip:nosid|skip:differ|skip:noresult|skip:budget) T2=$v ;; esac
fi
if [ "$T2" = sent ] && [ "$rc1" != 0 ]; then T2=skip:rc; fi
if [ "$T2" = sent ] && { [ "$LEFT" != 0 ] || [ "$HOMEDK" != 0 ]; }; then T2=skip:left; fi
if [ "$T2" = sent ]; then
  spent=$(awk '{s+=$1} END{printf "%.2f", s+0}' "$LEDGER")
  if awk -v s="$spent" -v n="$NEED" -v t="$STOP" 'BEGIN{exit !(s+n>t)}'; then T2=skip:money; fi
fi
if [ "$T2" = sent ]; then memok t2 || T2=skip:mem; fi

# --- 둘째 턴 ---
rc2=-; secs2=-; T2DIFF=0
if [ "$T2" = sent ]; then
  TURN=t2; t2s=$(date +%s)
  timeout 2400 env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$M/notmux" PATH="$CLEAN" claude -p "$REPLY" --resume "$SID" "${PD[@]}" \
  --setting-sources project \
  --model sonnet \
  --max-budget-usd 2.50 \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent" \
  --disallowedTools "Bash(npm *)" "Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$OP.t2.jsonl" 2> "$OP.t2.err" &
  CP=$!; echo "$CP" > "$OP.pid"; wait "$CP"; rc2=$?
  rm -f "$OP.pid"
  trap '' TERM INT HUP
  cost2=$(costof "$OP.t2.jsonl")
  if [ "$CUM" = 1 ] && [ "$cost2" != "?" ]; then
    cost2=$(awk -v a="$cost2" -v b="$cost1" 'BEGIN{d=a-b; if (d<0) d=0; printf "%.2f", d}')
  fi
  if [ "$cost2" = "?" ]; then cost2=2.50; fi
  echo "$cost2 intake.$NAME.$N.t2" >> "$LEDGER"
  CP=
  trap on_sig TERM INT HUP
  after t2
  secs2=$(( $(date +%s) - t2s ))
  sid2=$(initsid "$OP.t2.jsonl")
  if [ -n "$sid2" ] && [ "$sid2" != "$SID" ]; then
    echo "$sid2 $D" >> "$O/intake.sessions"; T2DIFF=1
  fi
fi

# --- 끝 커밋: 보냈든 안 보냈든 한 번 ---
git status --short > "$OP.end.status" 2>&1
git add -A >/dev/null 2>&1
endok=1
git -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false commit -q --no-verify --allow-empty -m t2 >/dev/null 2>&1 || { committed=bad; endok=0; }
[ -z "$(git status --porcelain)" ] || committed=bad
if [ "$endok" = 1 ] && [ "$T2" = sent ]; then git rev-parse HEAD > "$OP.t2"; fi
secs=$(( $(date +%s) - t0 ))
if [ "$T2" = sent ]; then rc=$rc2; else rc=$rc1; fi
# 끝난 뒤: 프로젝트 자체 시험과 코드 모양 검사
tests=$(env -u IHATEMONEY_SETTINGS_FILE_PATH timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider . 2>&1 | tail -1)
lint=$(.venv/bin/python -m ruff check ihatemoney 2>&1 | tail -1)
fmt=$(.venv/bin/python -m ruff format --check ihatemoney 2>&1 | tail -1)
git status --short | command grep -v '^??' > "$OP.after-tests" 2>&1
printf 'arm=%s\nrc1=%s\nrc2=%s\nsecs1=%s\nsecs2=%s\nsecs=%s\nt2=%s\nrc=%s\ntests=%s\nlint=%s\nfmt=%s\ncommitted=%s\ncum=%s\n' "$ARM" "$rc1" "$rc2" "$secs1" "$secs2" "$secs" "$T2" "$rc" "$tests" "$lint" "$fmt" "$committed" "$CUM" > "$OP.check"
long=$(journalctl -k --since "@$t0" 2>/dev/null | command grep -c "abnormally long accept")
echo "intake.$NAME.$N arm=$ARM rc1=$rc1 rc2=$rc2 t2=$T2 secs=$secs committed=$committed tests=[$tests] lint=[$lint] fmt=[$fmt] long_accept=$long $(date +%H:%M:%S)" >> "$LOG"
echo "intake.$NAME.$N arm=$ARM rc1=$rc1 rc2=$rc2 t2=$T2 secs=$secs committed=$committed tests=[$tests] lint=[$lint] fmt=[$fmt]"
# 끝 값 차례
[ "$HOMEDK" = 0 ] || exit 10
[ "$LEFT" = 0 ] || exit 11
[ "$committed" = ok ] || exit 6
[ "$T2DIFF" = 0 ] || exit 13
[ "$T2" = sent ] || exit 12
[ "$rc" = 0 ] || exit 5
