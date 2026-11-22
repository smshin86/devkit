#!/bin/bash
# 부르는 꼴: bash stage.sh <…> — 셔뱅은 있어도 실행 비트는 없고(drvfs는 비트를 못 가림) 늘 bash로 부른다. 안의 stage.py는 늘 python3 -I -B로 부른다.
# stage.sh <run> <task> <arm> — 연습 무대 한 번. 부탁 글(첫 턴)과 답 글(둘째 턴)을 새 사본에서 같은 대화로 보내고, 뒤에 검사·끝 커밋·세기를 한다.
# run: r01~r12(본 차례) · z01~z07(0번 걸음 · z06·z07은 예비) · vNN(무효를 메움) · xNN(다시 돌리기). task: a1 a2 b1 b2 c1 c2 z0. arm: p(켬) · q(끔).
# 따로 부르기: stage.sh seal · stage.sh unseal(봉한 뿌리의 아래 폴더 chmod) · stage.sh kitsha [폴더](꾸러미 트리 sha).
# 뿌리: S(봉한 뿌리 — STAGE_S, 기본 /home/ssmge/zzz-devkit-stage) · X(AI가 보는 뿌리 — STAGE_X, 기본 /home/ssmge/zzz-w).
# 돈은 S/out/stage.cost(x 실행은 stage-x.cost) 한 줄씩 스스로 적는다. 세는 것은 stage.py가 한다. 끝 값 표는 계획 5-8절과 19절.
# 잠금: stage.sh <run> …은 stage-locked.sh가 내보내는 STAGE_LOCKED=<S>/run.lock 표시가 없으면 9. seal·unseal은 그 잠금의 flock이 잡혀 있으면(도는 실행) 9.
# 봉하기는 첫 턴 앞에 한 번, 풀기는 둘째 턴 뒤(또는 둘째 턴을 안 보내기로 한 뒤)에 한 번뿐이다 — 사이에 풀지 않는다. 풀기 전에 남은 프로세스(cwd가 사본 아래이거나 환경에 이번 TMPDIR 표시가 든 것)를 끄고, 그래도 남으면 안 풀고 17.
# 장부(S/out/stage.cost · stage-x.cost)는 S/out-done/<이름>.mirror에 한 줄씩 따로 적는다(턴 동안은 out-done이 봉해져 있어 풀린 뒤에 적음) — 시작할 때 둘이 다르면 4. 통제 파일 이상으로 4가 되면 S/out-done/STOP을 남기고, 그 표시가 있으면 다음 실행은 4(사람이 보고 지운다).
# 환경 변수: STAGE_CUM=0|1(z 아닌 실행에 꼭 — 둘째 턴 돈 값이 누적이면 1, z 실행은 받은 값을 .check cost_raw1·cost_raw2에 적고 누적 여부를 모른 채 둘째 턴 값을 그대로 장부에 적음) · STAGE_OVER12=yes(합이 알림 선 이상일 때 시작 허락) · STAGE_CLAUDE(실행 파일 절대 경로 — 시험용) · STAGE_TASKS(tasks.json 길 — 시험용).
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
T=${STAGE_TASKS:-$HERE/stage/tasks.json}
S=${STAGE_S:-/home/ssmge/zzz-devkit-stage}
X=${STAGE_X:-/home/ssmge/zzz-w}
SHP=$$
DK=$(cd "$HERE/../.." && pwd)
O=$S/out; LOG=$O/stage.log
export STAGE_S=$S STAGE_X=$X PYTHONDONTWRITEBYTECODE=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
SEALED_NOW=0
SEALED=(sealed src-b src-c bases walkkit walk venv-b venv-c done out-done)

# 봉하기 전 모드를 이 프로세스의 변수(MODES)에 적고, 따로 부르는 unseal을 위해 S/out/seal.modes("이름 모드")에도 적는다. 실행 안에서 풀 때는 변수만 믿는다.
# 파일에서 읽는 모드는 세 자리 8진수만, 000이나 남이 쓸 수 있는 꼴(그룹 자리 또는 끝자리가 2·3·6·7)이면 700. 이미 000이면 기록을 덮지 않는다
declare -A MODES=()
SEALLIST=()
safemode() {
  [[ ${1-} =~ ^[0-7]{3}$ ]] || { echo 700; return; }
  case "$1" in 000|?[2367]?|??[2367]) echo 700 ;; *) echo "$1" ;; esac
}
seal_one() {
  local d=$1 n=$2 m
  [ -d "$d" ] && [ ! -L "$d" ] || return 0
  m=$(stat -c %a "$d") || return 0
  if [ "$m" != 0 ]; then
    MODES[$n]=$m
    { [ -f "$O/seal.modes" ] && awk -v n="$n" '$1!=n' "$O/seal.modes"; echo "$n $m"; } > "$O/seal.modes.tmp" && mv "$O/seal.modes.tmp" "$O/seal.modes"
  fi
  SEALLIST+=("$n")
  chmod 000 "$d"
}
unseal_one() {
  local d=$1 n=$2 m=
  [ -d "$d" ] && [ ! -L "$d" ] || return 0
  if [ -n "${MODES[$n]-}" ]; then m=${MODES[$n]}
  elif [ -f "$O/seal.modes" ]; then m=$(awk -v n="$n" '$1==n{m=$2} END{print m}' "$O/seal.modes"); fi
  chmod "$(safemode "$m")" "$d"
}
seal_all() {
  local n d
  SEALLIST=()
  mkdir -p "$O"
  for n in "${SEALED[@]}"; do
    d=${S:?}/$n
    seal_one "$d" "$n"
  done
  for d in "${S:?}"/try-*; do
    seal_one "$d" "${d##*/}"
  done
  return 0
}
unseal_all() {
  local n d
  for n in "${SEALED[@]}"; do
    d=${S:?}/$n
    unseal_one "$d" "$n"
  done
  for d in "${S:?}"/try-*; do
    unseal_one "$d" "${d##*/}"
  done
  return 0
}
# 꾸러미 트리 sha: 폴더 안 파일의 상대 경로와 내용 sha256을 정렬해 다시 sha256. 폴더가 없으면 -
kitsha() {
  local d=$1
  if [ ! -d "$d" ]; then echo "-"; return 0; fi
  (cd "$d" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum | cut -d' ' -f1)
}

# 내 프로세스 가운데 cwd가 $1 아래이거나 환경에 TMPDIR=$1/tmp가 든 것을 LEFTP에 모은다. 자기(와 하위 셸)·부모 줄·감시($WP)는 뺀다
ANC=" "; LEFTP=(); WP=
scan_anc() {
  local p=$$ line rest
  ANC=" "
  while [ "${p:-0}" -gt 1 ]; do
    ANC="$ANC$p "
    read -r line < "/proc/$p/stat" 2> /dev/null || break
    rest=${line##*) }
    set -- $rest
    p=${2-0}
  done
}
scan_run() {
  local r=$1 p pid cwd
  LEFTP=()
  for p in /proc/[0-9]*; do
    pid=${p#/proc/}
    case "$ANC" in *" $pid "*) continue ;; esac
    [ "$pid" = "$BASHPID" ] && continue
    [ -n "$WP" ] && [ "$pid" = "$WP" ] && continue
    [ -O "$p" ] || continue
    cwd=$(readlink "$p/cwd" 2> /dev/null) || cwd=
    case "$cwd" in "$r"|"$r"/*) LEFTP+=("$pid"); continue ;; esac
    command grep -qzxF "TMPDIR=$r/tmp" "$p/environ" 2> /dev/null && LEFTP+=("$pid")
  done
  return 0
}
# 따로 부르는 unseal 앞 검사: S/out에 지난 실행의 <run>.* 파일이 남았고 X/run 아래 사본의 프로세스가 살아 있으면 9(잠금 폴더가 없어도)
standalone_guard() {
  local f r have=0 live=()
  for f in "$O"/[rzxv][0-9][0-9].*; do [ -e "$f" ] && have=1; done
  [ "$have" = 1 ] || return 0
  scan_anc
  for r in "${X:?}"/run/*; do
    [ -d "$r" ] || continue
    scan_run "$r"
    live+=("${LEFTP[@]}")
  done
  [ "${#live[@]}" -eq 0 ] && return 0
  echo "끊긴 실행의 프로세스가 아직 살아 있음 — unseal 안 함. 남은 pid: ${live[*]}"
  echo "pid를 눈으로 확인하고 kill <pid>로 끈 뒤(이름으로 죽이지 말 것) 다시"
  exit 9
}

case "${1-}" in
  seal|unseal)
    [ $# -eq 1 ] || { echo "인자 틀림: $1 은 인자 없이"; exit 9; }
    if [ -d "$S/run.lock" ]; then
      exec 9< "$S/run.lock" && { flock -n 9 || { echo "도는 실행이 있음($S/run.lock 의 flock이 잡혀 있음) — $1 안 함"; exit 9; }; }
    fi
    [ "$1" = unseal ] && standalone_guard
    "${1}_all"; exit 0 ;;
  kitsha)
    [ $# -le 2 ] || { echo "인자 틀림: kitsha [폴더]"; exit 9; }
    kitsha "${2-$X/env/kit}"; exit 0 ;;
esac

RUN=${1-}; TASK=${2-}; ARM=${3-}
[ $# -eq 3 ] || { echo "인자 틀림: <run> <task> <arm> 셋이 있어야 함(받은 수 $#)"; exit 9; }
[[ $RUN =~ ^[rzxv][0-9]{2}$ ]] || { echo "인자 틀림: run은 r·z·x·v 글자와 숫자 둘"; exit 9; }
case "$TASK" in a1|a2|b1|b2|c1|c2|z0) ;; *) echo "인자 틀림: task는 a1 a2 b1 b2 c1 c2 z0"; exit 9 ;; esac
case "$ARM" in p|q) ;; *) echo "인자 틀림: arm은 p 또는 q"; exit 9 ;; esac
[ -e "$HOME/.devkit" ] && { echo "~/.devkit 이 이미 있음 — 멈춤"; exit 8; }
[ -e "$HOME/.devkit-guard-off" ] && { echo "~/.devkit-guard-off 이 있음 — 훅이 꺼진 채라 재지 않음, 멈춤"; exit 8; }
[ -f "$T" ] || { echo "tasks.json 없음"; exit 9; }
python3 -I -B "$HERE/stage.py" order "$T" "$RUN" "$TASK" "$ARM" || exit 9
[ "${STAGE_LOCKED-}" = "$S/run.lock" ] && [ -d "$S/run.lock" ] || { echo "stage-locked.sh 로 부를 것(STAGE_LOCKED 표시가 없거나 $S/run.lock 과 다름) — 멈춤"; exit 9; }
cfgv() { python3 -I -B "$HERE/stage.py" cfg "$T" "$1"; }
PROMPT=$(python3 -I -B "$HERE/stage.py" text "$T" "$TASK" 1) || { echo "부탁 없음"; exit 9; }
REPLY=$(python3 -I -B "$HERE/stage.py" text "$T" "$TASK" 2) || { echo "답 없음"; exit 9; }
# 바탕이 되는 일감(0번 걸음은 zero 표의 넷째 칸)과 무대 글자·바탕 묶음
ENVT=$(python3 -I -B -c '
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
run, task = sys.argv[2], sys.argv[3]
e = task
if task == "z0":
    e = ""
    for r in d.get("zero", []):
        if r[0] == run and len(r) > 3:
            e = r[3]
print(e)' "$T" "$RUN" "$TASK")
case "$ENVT" in a1|a2|b1|b2|c1|c2) ;; *) echo "바탕 일감을 모름"; exit 9 ;; esac
if [ "$TASK" = z0 ]; then CUM='?'
else
  [[ ${STAGE_CUM-} =~ ^[01]$ ]] || { echo "STAGE_CUM이 없거나 틀림(받은 값 [${STAGE_CUM-}]) — 0(둘째 턴 값이 그 턴만) 또는 1(누적)을 0번 걸음 결과대로 줄 것"; exit 9; }
  CUM=$STAGE_CUM
fi
ST=$(cfgv "tasks.$ENVT.stage"); TAR=$(cfgv "tasks.$ENVT.tar")
case "$ST" in a|b|c) ;; *) echo "무대 글자를 모름"; exit 9 ;; esac
# 돈 선: 본 실행은 money, x 실행은 money_rerun(없으면 9)
CAP=$(cfgv money.turn_cap) && CAP2=$(cfgv money.turn2_budget) && MARGIN=$(cfgv money.margin) || { echo "money 열쇠가 없음"; exit 9; }
if [ "$TASK" = z0 ]; then CAP=$(cfgv money.zero_cap) || exit 9; CAP2=$CAP; fi
maxf() { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.2f", (a+0>b+0)?a:b}'; }
if [[ $RUN == x* ]]; then
  XN=$(cfgv money_rerun.need) && ALARM=$(cfgv money_rerun.alarm) && STOP=$(cfgv money_rerun.stop) || { echo "x 실행인데 money_rerun 열쇠가 없음"; exit 9; }
  TC1=$(maxf "$CAP" "$XN"); TC2=$(maxf "$CAP2" "$XN"); LEDGER=$O/stage-x.cost
else
  ALARM=$(cfgv money.alert) && STOP=$(cfgv money.stop) || { echo "money 열쇠가 없음"; exit 9; }
  TC1=$CAP; TC2=$CAP2; LEDGER=$O/stage.cost
fi
for v in "$CAP" "$CAP2" "$ALARM" "$STOP" "$TC1" "$TC2" "$MARGIN"; do
  [[ $v =~ ^[0-9]{1,2}\.[0-9]{2}$ ]] || { echo "돈 값 꼴이 틀림: $v"; exit 9; }
done
mkdir -p "$O" "$S/out-done" "$S/done"
OP=$O/$RUN
stopmark() { : > "$S/out-done/STOP"; }
if [ -e "$S/out-done/STOP" ]; then
  echo "정지 표시가 있음($S/out-done/STOP) — 앞 실행이 장부·통제 파일 이상으로 멈췄음. 사람이 까닭(장부 ↔ 미러 ↔ 통제 파일)을 보고 맞춘 뒤 이 표시를 지우고 다시"; exit 4
fi
# 지난 실행이 남았으면 시작하지 않는다: X/run 아래 폴더 · S/out의 <run>.* 파일(장부·로그·잠금·seal.modes는 아님)
LEFTOVER=()
for f in "${X:?}"/run/*; do [ -e "$f" ] && LEFTOVER+=("$f"); done
for f in "$O"/[rzxv][0-9][0-9].*; do [ -e "$f" ] && LEFTOVER+=("$f"); done
if [ "${#LEFTOVER[@]}" -gt 0 ]; then
  echo "지난 실행이 남아 있음 — 시작 안 함. 남은 것:"
  printf '  %s\n' "${LEFTOVER[@]}"
  for f in "${LEFTOVER[@]}"; do
    case "$f" in *.mirror-pending)
      echo "장부 줄이 미러에 못 적혀 남았음($f) — 내용:"
      awk '{print "    " $0}' "$f" 2> /dev/null
      echo "  이 파일을 지우지 말고 out-done·done으로 옮기고, 거울($S/out-done/*.mirror)에 이 줄을 이을 것" ;;
    esac
  done
  echo "도는 실행이 없는지 본 뒤 사람이 보고 치우고 다시(봉한 폴더가 막혀 있으면 bash stage.sh unseal)"; exit 9
fi
# 봉한 폴더가 000으로 남아 있으면(앞 실행이 어디선가 끊겼음) 스스로 푼다
NEED=
for n in "${SEALED[@]}"; do
  d=$S/$n
  if [ -d "$d" ] && [ ! -L "$d" ] && [ "$(stat -c %a "$d")" = 0 ]; then NEED="$NEED $n"; fi
done
for d in "$S"/try-*; do
  if [ -d "$d" ] && [ ! -L "$d" ] && [ "$(stat -c %a "$d")" = 0 ]; then NEED="$NEED ${d##*/}"; fi
done
if [ -n "$NEED" ]; then
  echo "봉한 폴더가 000으로 남아 있어 풀었음:$NEED"
  unseal_all
fi
compgen -G "$O/$RUN.*" > /dev/null && { echo "이미 돌림: $RUN"; exit 9; }
compgen -G "$S/out-done/$RUN.*" > /dev/null && { echo "이미 돌림: $RUN"; exit 9; }
[ -e "$S/done/$RUN" ] && { echo "이미 돌림: $RUN"; exit 9; }

costof() {
  python3 -I -B -c '
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
freecommit() { (cd /mnt/c 2>/dev/null && timeout 60 powershell.exe -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1); }
# 기계 감시: 한 번 부를 때마다 로그에 한 줄을 남기고, 멈출 일이면 3을 돌려준다
memok() {
  local commit buddy free cok
  commit=$(freecommit)
  case "$commit" in ''|*[!0-9]*)
    echo "stage.$RUN.$1 mem win_commit_gb 못 읽음(값 [$commit]) — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "커밋 값을 못 읽음 — 멈춤"; return 3 ;;
  esac
  if [ "$commit" -lt 4 ]; then
    echo "stage.$RUN.$1 mem win_commit_gb=${commit:-?} 4 아래 — 압축 안 함, 멈춤 $(date +%H:%M:%S)" >> "$LOG"
    echo "메모리 부족 — 멈춤"; return 3
  fi
  buddy=$(o7)
  if [ "${buddy:-0}" -le 0 ]; then
    free=$(awk '/^MemFree:/{print $2}' /proc/meminfo)
    cok=0
    case "$free" in ''|*[!0-9]*) ;; *) [ "$free" -le 1572864 ] && cok=1 ;; esac
    if [ "$cok" = 1 ]; then
      python3 "$HERE/원본/compact.py" 4 >> "$LOG" 2>&1
      buddy=$(o7)
    else
      echo "stage.$RUN.$1 mem buddy_o7+=0 memfree_kb=$free 압축 안 함 — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
      echo "메모리 부족(빈 쪽이 넉넉해 압축 안 함) — 멈춤"; return 3
    fi
  fi
  echo "stage.$RUN.$1 mem buddy_o7+=$buddy win_commit_gb=${commit:-?} $(date +%H:%M:%S)" >> "$LOG"
  if [ "${buddy:-0}" -le 0 ]; then echo "메모리 부족 — 멈춤"; return 3; fi
  return 0
}
memok t1 || exit 3

f2() { awk -v v="$1" 'BEGIN{printf "%.2f", v+0}'; }
# 장부: 없으면 0.00. 있으면 모든 줄이 「숫자.두자리 공백…」이어야 하고 읽혀야 한다 — 아니면 1(합을 모르는 채 돈을 쓰지 않는다)
sumof() {
  [ -e "$LEDGER" ] || { echo 0.00; return 0; }
  [ -f "$LEDGER" ] && [ -r "$LEDGER" ] || return 1
  awk 'BEGIN{b=0} !/^[0-9]+\.[0-9]{2} /{b=1} {s+=$1} END{if (b) exit 3; printf "%.2f", s+0}' "$LEDGER"
}
# 장부와 그 미러(S/out-done/<이름>.mirror)가 같은 글인가(둘 다 없거나 비면 같음). 못 읽으면 다름
ledsame() {
  local l=$1 m=$S/out-done/${1##*/}.mirror a b
  if [ -e "$l" ]; then
    [ -f "$l" ] && [ -r "$l" ] || return 1
    a=$(sha256sum < "$l") || return 1
  else a=$(sha256sum < /dev/null); fi
  if [ -e "$m" ]; then
    [ -f "$m" ] && [ -r "$m" ] || return 1
    b=$(sha256sum < "$m") || return 1
  else b=$(sha256sum < /dev/null); fi
  [ "$a" = "$b" ]
}
# 장부에 한 줄 잇고 줄 수가 정확히 하나 늘었는지 본다(아니면 BADL). 미러에 쓸 줄은 MIRL에 모아 둔다(턴 동안 out-done이 봉해져 있어 풀린 뒤에 적는다)
MIRL=
ledadd() {
  local n0=0 n1=-1
  [ -f "$LEDGER" ] && n0=$(wc -l < "$LEDGER")
  printf '%s\n' "$1" >> "$LEDGER"
  [ -f "$LEDGER" ] && n1=$(wc -l < "$LEDGER")
  [ "$n1" = "$((n0 + 1))" ] || BADL=1
  MIRL+="$1"$'\n'
  CTL0=$(ctlsig)    # 내가 붙인 줄은 통제 파일 바뀜이 아니다 — 신호를 막은 구간 안에서 다시 잡는다(그 사이 신호가 와도 on_sig의 turnaudit가 이 줄을 탓하지 않는다)
}
mirror_flush() {
  [ -n "$MIRL" ] || return 0
  printf '%s' "$MIRL" >> "$S/out-done/${LEDGER##*/}.mirror" && MIRL=
}
fits() { awk -v s="$1" -v n="$2" -v t="$STOP" -v m="$MARGIN" 'BEGIN{exit !(s+n<=t-m+0.0001)}'; }
for lf in "$O/stage.cost" "$O/stage-x.cost"; do
  ledsame "$lf" || { echo "장부와 미러가 다름($lf ↔ $S/out-done/${lf##*/}.mirror) — 장부가 몰래 바뀌었을 수 있음, 멈춤"; stopmark; exit 4; }
done
if spent=$(sumof) && [[ $spent =~ ^[0-9]+\.[0-9]{2}$ ]]; then :
else echo "돈 장부가 틀렸거나 못 읽음($LEDGER) — 합을 모르니 멈춤"; stopmark; exit 4; fi
if ! fits "$spent" "$TC1"; then
  echo "돈 멈춤: 합 $spent + $TC1 > $STOP - $MARGIN"; exit 4
fi
if awk -v s="$spent" -v a="$ALARM" 'BEGIN{exit !(s>=a)}' && [ "${STAGE_OVER12-}" != yes ]; then
  echo "stage.$RUN 돈 알림 합=$spent >= $ALARM — 멈춤 $(date +%H:%M:%S)" >> "$LOG"
  echo "알림 선(합 $spent ≥ $ALARM) — 사용자에게 알리고 허락을 받은 뒤 STAGE_OVER12=yes로"; exit 4
fi

# b 바탕(0번 걸음 포함)은 AI가 켠 앱 포트(8083)와 걸어 보기 포트(18300~18399)가 비어 있어야 한다
if [ "$ST" = b ]; then
  PA=$(cfgv ports.app); PB=$(cfgv ports.walk_base); PN=$(cfgv ports.walk_range)
  command -v ss > /dev/null 2>&1 || { echo "ss 없음 — 포트를 못 봄, 멈춤"; exit 15; }
  if ss -ltnH 2> /dev/null | awk -v a="$PA" -v b="$PB" -v n="$PN" '{k=split($4,x,":"); p=x[k]+0; if (p==a || (p>=b && p<b+n)) f=1} END{exit !f}'; then
    echo "포트가 이미 열려 있음($PA 또는 $PB~)"; exit 15
  fi
fi
# 가상 환경 지문: pip freeze 글과 site-packages의 pth·editable 파일 sha256
fp() {
  local V=$1
  { "$V/bin/python" -I -m pip freeze --all 2>&1
    find "$V"/lib/python*/site-packages -maxdepth 1 \( -name '*.pth' -o -name '__editable__*' \) -print0 2> /dev/null | LC_ALL=C sort -z | xargs -0 -r sha256sum
  } | sha256sum | cut -d' ' -f1
}
if [ "$ST" = b ] || [ "$ST" = c ]; then
  V=$X/env/$ST
  [ -x "$V/bin/python" ] || { echo "AI용 가상 환경 없음: $V"; exit 9; }
  fp "$V" > "$OP.venv0"
fi
if [ "$ARM" = p ]; then
  [ -f "$X/env/kit/.claude-plugin/plugin.json" ] || { echo "꾸러미 사본 없음: $X/env/kit"; exit 9; }
fi
if [ -n "${STAGE_CLAUDE-}" ]; then
  case "$STAGE_CLAUDE" in /*) ;; *) echo "STAGE_CLAUDE는 절대 경로"; exit 9 ;; esac
  [ -x "$STAGE_CLAUDE" ] || { echo "STAGE_CLAUDE를 못 돌림"; exit 9; }
fi

# --- 사본 ---
OWN=$(python3 -I -B -c 'import secrets; print(secrets.token_hex(4))')
[[ $OWN =~ ^[0-9a-f]{8}$ ]] || { echo "무작위 이름을 못 만듦"; exit 9; }
mkdir -p "${X:?}/run"
R=$X/run/$OWN; W=$R/w
mkdir "$R" || { echo "사본 자리를 못 만듦: $R"; exit 9; }
mkdir "$W" "$R/tmp" "$R/gh" "$R/uv" "$R/nosock" "$R/pipcache" "$R/npmcache"
printf '%s\t%s\n' "$OWN" "$RUN" >> "$S/out-done/names.tsv"
printf '[user]\n\tname = stage\n\temail = stage@invalid\n' > "$R/gitconfig"
: > "$R/npmrc"
GC=(-c user.name=stage -c user.email=stage@invalid -c gc.auto=0 -c maintenance.auto=false -c commit.gpgsign=false -c core.hooksPath=/dev/null -c core.fsmonitor=false)
gw() { git -C "$W" "${GC[@]}" "$@"; }
if [ "$TAR" != null ]; then
  tar -x -f "$S/$TAR" -C "$W" || { echo "바탕 묶음을 못 풂"; exit 9; }
  [ -n "$(ls -A "$W")" ] || { echo "바탕 묶음이 비었음"; exit 9; }
fi
git -C "$W" init -q && gw add -A -f > /dev/null 2>&1 && gw commit -q --no-verify --allow-empty -m base > /dev/null 2>&1 || { echo "바탕 커밋 실패"; exit 6; }
BASEC=$(git -C "$W" rev-parse HEAD)
echo "$BASEC" > "$OP.base"
SHIM=
if [ -n "${STAGE_CLAUDE-}" ]; then
  mkdir "$R/shim" && ln -s "$STAGE_CLAUDE" "$R/shim/claude"
  SHIM=$R/shim:
fi

# --- 환경과 막을 낱말 ---
CLEAN=$(printf '%s' "$PATH" | tr ':' '\n' | command grep -v -E '^/mnt/[a-z]/' | paste -sd:)
CENV=(TMUX_TMPDIR="$R/nosock" TMPDIR="$R/tmp" GH_CONFIG_DIR="$R/gh" GH_TOKEN= npm_config_userconfig="$R/npmrc" npm_config_ignore_scripts=true GIT_CONFIG_GLOBAL="$R/gitconfig" UV_CACHE_DIR="$R/uv" UV_PYTHON_DOWNLOADS=never PIP_ONLY_BINARY=:all: ENABLE_CLAUDEAI_MCP_SERVERS=false CLAUDE_CODE_DISABLE_AUTO_MEMORY=1)
case "$ST" in
  a) FRONT=; EXTRA=(PIP_REQUIRE_VIRTUALENV=1 PIP_USER=0 PIP_CACHE_DIR="$R/pipcache" npm_config_prefix="$R/npm-prefix" npm_config_cache="$R/npmcache" npm_config_audit=false npm_config_fund=false npm_config_update_notifier=false) ;;
  b) FRONT="$X/env/b/bin:"; EXTRA=() ;;
  c) FRONT="$X/env/c/bin:"; EXTRA=(DJANGO_TEST_PROCESSES=2 PYTHONPATH="$W") ;;
esac
case "$ARM" in
  p) PD=(--plugin-dir "$X/env/kit") ;;
  q) PD=() ;;
esac
DIS_NPM=("Bash(npm *)")
DIS0=("Bash(npx *)" "Bash(yarn *)" "Bash(pnpm *)" "Bash(bun *)" "Bash(corepack *)" "Bash(kill *)" "Bash(* kill *)" "Bash(* kill)" "Bash(*/kill *)" "Bash(*\"kill *)" "Bash(*'kill *)" "Bash(*pkill*)" "Bash(*killall*)" "Bash(*fuser*)" "Bash(*tmux*)" "Bash(*wsl.exe*)" "Bash(*cmd.exe*)" "Bash(*powershell*)" "Bash(*taskkill*)" "Bash(*Stop-Process*)" "Bash(*cc-socks*)" "Bash(*.claude/sessions*)" "Bash(*nc -U*)" "Bash(*socat*)" "Bash(*AF_UNIX*)" "Bash(claude *)" "Bash(* claude *)" "Bash(*/claude *)" "Bash(*crontab*)" "Bash(*systemd-run*)" "Bash(*systemctl*)")
DIS_ALL=("Bash(*zzz-devkit-stage/sealed*)" "Bash(*zzz-devkit-stage/src-*)" "Bash(*zzz-devkit-stage/bases*)" "Bash(*zzz-devkit-stage/walkkit*)" "Bash(*devkit/docs*)" "Bash(gh *)" "Bash(* gh *)")
DIS_B=("Bash(*pip *)" "Bash(*pip3 *)" "Bash(*uv *)" "Bash(*conda *)")
DIS_C=("Bash(*curl*)" "Bash(*wget*)" "Bash(*git fetch*)" "Bash(*git clone*)" "Bash(*git pull*)")
case "$ST" in
  a) DIS=("${DIS0[@]}" "${DIS_ALL[@]}") ;;
  b) DIS=("${DIS_NPM[@]}" "${DIS0[@]}" "${DIS_ALL[@]}" "${DIS_B[@]}") ;;
  c) DIS=("${DIS_NPM[@]}" "${DIS0[@]}" "${DIS_ALL[@]}" "${DIS_B[@]}" "${DIS_C[@]}") ;;
esac

# 실행 앞 값: 꾸러미 사본 · 홈의 설정 파일 · devkit 작업 트리
dotsha() {
  local f p
  for f in .claude/settings.json .gitconfig .npmrc .bashrc .profile; do
    p=$HOME/$f
    if [ -f "$p" ]; then sha256sum "$p" | cut -d' ' -f1; else echo "-"; fi
  done | paste -sd' '
}
dkstat() { git --no-optional-locks -c gc.auto=0 -C "$DK" status --porcelain 2> /dev/null | sha256sum | cut -d' ' -f1; }
# 예약 작업 지문: crontab -l 글 + user 타이머 목록의 마지막 두 칸(이름)만 정렬한 글의 sha256. 읽기만 한다 — 명령이 없거나 실패하면 빈 글
schedsha() {
  {
    timeout 10 crontab -l 2> /dev/null
    echo "--timers--"
    timeout 10 systemctl --user list-timers --all --no-legend --plain 2> /dev/null | awk 'NF>=2{print $(NF-1), $NF}' | LC_ALL=C sort
  } | sha256sum | cut -d' ' -f1
}
# 이 실행 대화(SID · 둘째 턴 id가 달랐으면 그것도) 말고, 실행 폴더 R 자체 이름의 대화 폴더와 R 이름에 `-`가 이어진 대화 폴더(사본 꼭대기 · 그 하위 · 임시 폴더 따위) 바로 아래 *.jsonl의 수. 읽기만 한다 — 폴더가 없으면 0
sess_extra_count() {
  local LC_ALL=C
  local name=${R//[^A-Za-z0-9]/-} f b n=0
  for f in "$HOME/.claude/projects/$name"/*.jsonl "$HOME/.claude/projects/$name-"*/*.jsonl; do
    [ -e "$f" ] || continue
    b=${f##*/}; b=${b%.jsonl}
    [ "$b" = "$SID" ] && continue
    [ -n "${sid2-}" ] && [ "$b" = "$sid2" ] && continue
    n=$((n + 1))
  done
  echo "$n"
}
# 예약 작업·다른 대화 세기: 세기만 한다(끝 값은 안 바꾼다 — 다른 사람 작업이 바꿀 수 있다). 신호 갈래(143)만 못 세고 남는다
# 판정은 지역 변수로 끝낸 뒤 한 번에 넣는다 — 기다리는 사이 신호가 와도 확인 안 한 값이 .check에 안 적힌다
count_sched_sess() {
  local s=changed x
  [ "$SCHED0" = "$(schedsha)" ] && s=same
  x=$(sess_extra_count)
  SCHED=$s; SESSX=$x
}
KIT0=$(kitsha "$X/env/kit"); DOT0=$(dotsha); DK0=$(dkstat); SCHED0=$(schedsha)

# claude에게는 STAGE_* 가 하나도 안 간다(뿌리 · 장부 · 잠금 표시를 알려 주지 않는다): 알려진 이름 + 지금 환경에 있는 STAGE_ 로 시작하는 모두
UNST=(-u STAGE_S -u STAGE_X -u STAGE_CUM -u STAGE_OVER12 -u STAGE_TASKS -u STAGE_CLAUDE -u STAGE_VENV_B -u STAGE_VENV_C -u STAGE_LOCKED)
for v in $(compgen -e | command grep '^STAGE_'); do UNST+=(-u "$v"); done
# 계정·이 대화 줄기 변수: 환경의 CLAUDE* 이름 모두 지운다(이름만 다룬다). 인증 토큰과 설정 폴더 둘만 남긴다. CENV의 못 박은 값이 이기도록 env 줄에서 UNST 바로 뒤 · PATH= 앞에 둔다
UNCL=()
for v in $(compgen -e | command grep '^CLAUDE'); do
  case "$v" in CLAUDE_CODE_OAUTH_TOKEN|CLAUDE_CONFIG_DIR) ;; *) UNCL+=(-u "$v") ;; esac
done

# 대화 번호: 첫 턴에 정해 주고, 둘째 턴이 같은 대화를 잇는다
SID=$(cat /proc/sys/kernel/random/uuid)
[[ "$SID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || { echo "대화 번호 못 만듦"; exit 9; }
echo "$SID $OWN" >> "$O/stage.sessions"

initsid() {
  python3 -I -B -c '
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
  python3 -I -B -c '
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

# 60초마다(2초씩 끊어 자고, 매번 본 프로세스가 살아 있는지 봄 — 없으면 스스로 끝남) 한 줄: buddyinfo o7+ 합 · Windows 남은 커밋 · abnormally long accept 줄 수. 남은 커밋이 4 GB 아래면 자기가 띄운 claude pid에 TERM
WP=; SP=
watch_loop() {
  local c b l k cpid=$1
  trap 'kill "$SP" 2> /dev/null; exit 0' TERM
  echo "$(date +%H:%M:%S) start turn=$(cat "$OP.turn" 2> /dev/null)" >> "$OP.watch"
  while :; do
    kill -0 "$SHP" 2> /dev/null || exit 0
    c=$(freecommit); b=$(o7)
    l=$(journalctl -k --since "@$T0" 2> /dev/null | command grep -c "abnormally long accept")
    echo "$(date +%H:%M:%S) turn=$(cat "$OP.turn" 2> /dev/null) o7=${b:-?} free_commit_gb=${c:-?} long_accept=${l:-0}" >> "$OP.watch"
    case "$c" in ''|*[!0-9]*) ;; *)
      if [ "$c" -lt 4 ]; then
        echo "free_commit_gb=$c 4 아래 — claude에 TERM" >> "$OP.watch"
        : > "$OP.low"
        [ -n "$cpid" ] && kill "$cpid" 2> /dev/null
      fi ;;
    esac
    for k in $(seq 1 30); do
      kill -0 "$SHP" 2> /dev/null || exit 0
      sleep 2 & SP=$!; wait "$SP"
    done
  done
}
stopwatch() { if [ -n "$WP" ]; then kill "$WP" 2> /dev/null; wait "$WP" 2> /dev/null; WP=; fi; }

# 턴 뒤: 남은 프로세스(cwd가 사본 아래이거나 환경에 이번 TMPDIR 표시가 든 것)를 pid로 찾아 첫 목록을 적고, 없어질 때까지 다시 찾아 TERM(5초까지) → KILL(2초까지) — 이름으로 죽이지 않는다.
# 그래도 남은 pid는 SURV에 담는다(비어 있지 않으면 풀지 않는다). LEFTN은 처음 찾은 수. ~/.devkit이 생겼는지도 본다
LEFTN=0; HOMEDK=0; SURV=()
after() {
  local f=$OP.left${1#t} pid i
  local -a first=()
  SURV=(); scan_anc; scan_run "$R"
  first=("${LEFTP[@]}")
  LEFTN=${#first[@]}
  if [ "$LEFTN" -gt 0 ]; then
    for pid in "${first[@]}"; do
      echo "$pid $(tr '\0' ' ' < "/proc/$pid/cmdline" 2> /dev/null | cut -c1-200)" >> "$f"
    done
    for i in $(seq 1 25); do
      scan_run "$R"
      [ "${#LEFTP[@]}" -eq 0 ] && break
      for pid in "${LEFTP[@]}"; do kill -TERM "$pid" 2> /dev/null; done
      sleep 0.2
    done
    for i in $(seq 1 20); do
      scan_run "$R"
      [ "${#LEFTP[@]}" -eq 0 ] && break
      for pid in "${LEFTP[@]}"; do kill -KILL "$pid" 2> /dev/null; done
      sleep 0.1
    done
    scan_run "$R"
    SURV=("${LEFTP[@]}")
    echo "stage.$RUN.$1 left: $LEFTN 개를 끔(남음 ${#SURV[@]}) $(date +%H:%M:%S)" >> "$LOG"
  fi
  if [ -e "$HOME/.devkit" ]; then
    echo "stage.$RUN.$1: home .devkit appeared" >> "$LOG"; HOMEDK=1
  fi
}
# 잠금을 남기는 끝의 까닭을 잠금 폴더 안 why에 한 줄로(stage-locked.sh가 안내에 찍는다)
why() { [ -d "${STAGE_LOCKED-}" ] && echo "$1" > "$STAGE_LOCKED/why" 2> /dev/null; return 0; }
# 센 글(<run>.json)을 만든다 — 17·143으로 끝나도 표·judge에 무효 줄로 나오게
count_log() { python3 -I -B "$HERE/stage.py" count "$T" "$O" "$RUN" >> "$LOG" 2>&1 || echo "stage.$RUN count 실패 $(date +%H:%M:%S)" >> "$LOG"; }
# 풀지 못하고 끝낼 때의 안내(남은 pid · 아직 미러에 못 적은 장부 줄 — 화면과 $O/<run>.mirror-pending)
survivor_note() {
  echo "남은 프로세스가 있어 봉한 폴더를 풀지 않음(봉한 채 둠). 남은 pid: ${SURV[*]}"
  echo "pid와 명령줄을 눈으로 확인하고 kill <pid>로 끈 뒤(이름으로 죽이지 말 것) 사람이 bash stage.sh unseal 로 풀 것"
  if [ -n "$MIRL" ]; then
    printf '%s' "$MIRL" > "$OP.mirror-pending"
    echo "미러에 못 적은 장부 줄(풀린 뒤 $S/out-done/${LEDGER##*/}.mirror 끝에 그대로 이을 것 — 같은 글을 $OP.mirror-pending 에도 적었음):"
    printf '%s' "$MIRL"
  fi
}

# .check: 센 것을 한 곳에. exit와 kitsha는 끝에서 정한다. sched=-·sess_extra=- 는 "모름"(신호 143 갈래만 못 세고 남는다)
rc1=-; rc2=-; secs1=-; secs2=-; secs=-; T2=-; rc=-; committed=-; ENDC=; LEFT1=0; LEFT=0; KITSTATE=same; craw1=-; craw2=-; SCHED=-; SESSX=-; BADL=0; SEALBAD=0; CTLBAD=0; MEM2=0; CTL0=
# 턴 앞뒤 통제 파일(장부 둘 · seal.modes)의 sha·줄 수·모드. AI가 쓸 수 있는 S/out에 있어서 턴 동안 바뀌었는지 본다
ctlsig() {
  local f
  for f in "$O/stage.cost" "$O/stage-x.cost" "$O/seal.modes"; do
    if [ -e "$f" ]; then printf '%s %s %s\n' "$(sha256sum "$f" 2> /dev/null | cut -d' ' -f1)" "$(wc -l < "$f" 2> /dev/null)" "$(stat -c %a "$f" 2> /dev/null)"; else echo -; fi
  done
}
# 봉한 폴더마다 ctime(풀었다 다시 000으로 만들어도 달라진다)
DSIG=
dsig() {
  local n
  for n in "${SEALLIST[@]}"; do echo "$n $(stat -c %z "$S/$n" 2> /dev/null)"; done
}
# 턴이 끝난 직후(풀기 전): 봉한 폴더가 아직 000이고 ctime이 그대로인지(없어졌거나 링크가 됐어도 깨진 것) · 통제 파일이 그대로인지
turnaudit() {
  local n d
  for n in "${SEALLIST[@]}"; do
    d=$S/$n
    if [ ! -d "$d" ] || [ -L "$d" ] || [ "$(stat -c %a "$d" 2> /dev/null)" != 0 ]; then SEALBAD=1; fi
  done
  [ "$(dsig)" = "$DSIG" ] || SEALBAD=1
  [ "$(ctlsig)" = "$CTL0" ] || CTLBAD=1
}
write_check() {
  printf 'run=%s\ntask=%s\narm=%s\nown=%s\nrc1=%s\nrc2=%s\nsecs1=%s\nsecs2=%s\nsecs=%s\nt2=%s\nrc=%s\ntests=-\nlint=-\nfmt=-\ncommitted=%s\ncum=%s\ncost_raw1=%s\ncost_raw2=%s\nbase=%s\nend_commit=%s\nleft1=%s\nleft=%s\nexit=%s\nkitsha=%s\nseal_broken=%s\nsched=%s\nsess_extra=%s\n' \
    "$RUN" "$TASK" "$ARM" "$OWN" "$rc1" "$rc2" "$secs1" "$secs2" "$secs" "$T2" "$rc" "$committed" "$CUM" "$craw1" "$craw2" "$BASEC" "$ENDC" "$LEFT1" "$LEFT" "$1" "$KITSTATE" "$SEALBAD" "$SCHED" "$SESSX" > "$OP.check"
}

# 끝난 실행은 옮긴다: 사본 → S/done/<run> · S/out/<run>.* → S/out-done/ (장부와 로그는 남김). 봉한 폴더를 먼저 풀어 둔 뒤에 부른다
finish_move() {
  local f
  mv "${R:?}" "${S:?}/done/$RUN"
  for f in "${O:?}/$RUN".*; do
    [ -e "$f" ] && mv "$f" "${S:?}/out-done/"
  done
}
# 신호(TERM·INT·HUP)로 끊기면 claude를 끄고, 돈 줄(모르면 그 턴의 상한)을 적고, 남은 프로세스를 정리한 뒤 — 남은 것이 없을 때만 — 봉한 폴더를 풀고 .check를 적어 옮긴 뒤 143으로 끝낸다
# (남은 것이 있으면 봉한 채 안내만 하고 143: 잠금도 남는다)
CP=; TURN=t1; cost1=0; T0=$(date +%s)
on_sig() {
  trap '' TERM INT HUP
  stopwatch
  if [ -n "$CP" ]; then
    kill "$CP" 2> /dev/null; wait "$CP" 2> /dev/null
  fi
  [ "$SEALED_NOW" = 1 ] && turnaudit
  # 둘째 턴이 시작되기 전에 끊겼으면 안 보낸 것(앞에서 이미 까닭이 정해졌으면 그대로)
  if [ "$TURN" = t1 ]; then case "$T2" in skip:*) ;; *) T2=skip:sig ;; esac; fi
  if [ -n "$CP" ]; then
    c=$(costof "$OP.$TURN.jsonl"); cap=$TC1
    [ "$TURN" = t2 ] && cap=$TC2
    if [ "$TURN" = t2 ]; then craw2=$c; else craw1=$c; fi
    if [ "$TURN" = t2 ] && [ "$CUM" = 1 ] && [ "$c" != "?" ]; then
      c=$(awk -v a="$c" -v b="$cost1" 'BEGIN{d=a-b; if (d<0) d=0; printf "%.2f", d}')
    fi
    [ "$c" = "?" ] && c=$cap
    c=$(f2 "$c")
    ledadd "$c stage.$RUN.$TURN"
    echo "stage.$RUN 신호로 끊김 turn=$TURN cost=$c $(date +%H:%M:%S)" >> "$LOG"
    CP=
  fi
  after "$TURN"
  secs=$(( $(date +%s) - T0 ))
  if [ "${#SURV[@]}" -gt 0 ]; then
    why survivors
    write_check 143
    survivor_note
    count_log
    SEALED_NOW=0
    exit 143
  fi
  why signal
  if [ "$SEALED_NOW" = 1 ]; then unseal_all; SEALED_NOW=0; fi
  mirror_flush || BADL=1
  { [ "$BADL" = 1 ] || [ "$CTLBAD" = 1 ]; } && stopmark
  write_check 143
  count_log
  finish_move
  exit 143
}
trap '[ "$SEALED_NOW" = 1 ] && unseal_all' EXIT
trap on_sig TERM INT HUP
cd "$W" || exit 9

# --- 첫 턴 ---
TURN=t1; echo t1 > "$OP.turn"
SEALED_NOW=1; seal_all; DSIG=$(dsig); CTL0=$(ctlsig)
timeout 2400 env -u TMUX -u TMUX_PANE "${UNST[@]}" "${UNCL[@]}" PATH="$SHIM$FRONT$CLEAN" "${CENV[@]}" "${EXTRA[@]}" claude -p "$PROMPT" --session-id "$SID" "${PD[@]}" \
  --setting-sources project \
  --model sonnet \
  --max-budget-usd "$CAP" \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent,TaskStop" \
  --tools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent,TaskStop" \
  --strict-mcp-config \
  --disallowedTools "${DIS[@]}" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$OP.t1.jsonl" 2> "$OP.t1.err" &
CP=$!
( cd / && watch_loop "$CP" ) &
WP=$!
wait "$CP"; rc1=$?
trap '' TERM INT HUP
stopwatch
turnaudit
cost1=$(costof "$OP.t1.jsonl")
craw1=$cost1
if [ "$cost1" = "?" ]; then cost1=$TC1; fi
cost1=$(f2 "$cost1")
ledadd "$cost1 stage.$RUN.t1"
CP=
trap on_sig TERM INT HUP
after t1
LEFT1=$LEFTN
secs1=$(( $(date +%s) - T0 ))
if [ -e .devkit ]; then cp -a .devkit "$OP.t1.devkit"; fi
gw status --short > "$OP.t1.status" 2>&1
# 사진: 커밋하지 않는다. 사본 밖 임시 인덱스로 트리만 만들어 어느 가지에도 걸지 않는 커밋을 하나 만든다
committed=ok
IX=$O/$RUN.idx
rm -f "$IX"
if GIT_INDEX_FILE="$IX" gw read-tree "$BASEC" &&
   GIT_INDEX_FILE="$IX" gw add -A &&
   tree=$(GIT_INDEX_FILE="$IX" gw write-tree) &&
   snap=$(gw commit-tree "$tree" -p "$BASEC" -m snap < /dev/null) &&
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
if [ "$T2" = sent ] && [ "$SEALBAD" = 1 ]; then T2=skip:seal; fi
if [ "$T2" = sent ] && { [ "$CTLBAD" = 1 ] || [ "$BADL" = 1 ]; }; then T2=skip:ctrl; fi
if [ "$T2" = sent ] && [ "${#SURV[@]}" -gt 0 ]; then T2=skip:surv; fi
if [ "$T2" = sent ]; then
  v=$(t1check "$OP.t1.jsonl" "$SID")
  case "$v" in skip:nosid|skip:differ|skip:noresult|skip:budget) T2=$v ;; esac
fi
if [ "$T2" = sent ] && [ "$rc1" != 0 ]; then T2=skip:rc; fi
if [ "$T2" = sent ] && [ "$HOMEDK" != 0 ]; then T2=skip:home; fi
if [ "$T2" = sent ] && [ -e "$OP.low" ]; then T2=skip:mem; fi
if [ "$T2" = sent ]; then
  if spent=$(sumof) && [[ $spent =~ ^[0-9]+\.[0-9]{2}$ ]]; then
    fits "$spent" "$TC2" || T2=skip:money
  else
    T2=skip:money; BADL=1
  fi
fi
if [ "$T2" = sent ]; then memok t2 || { T2=skip:mem; MEM2=1; }; fi

# --- 둘째 턴 ---
rc2=-; secs2=-; T2DIFF=0; LEFT=$LEFT1
if [ "$T2" = sent ]; then
  TURN=t2; t2s=$(date +%s); echo t2 > "$OP.turn"
  CTL0=$(ctlsig)
  timeout 2400 env -u TMUX -u TMUX_PANE "${UNST[@]}" "${UNCL[@]}" PATH="$SHIM$FRONT$CLEAN" "${CENV[@]}" "${EXTRA[@]}" claude -p "$REPLY" --resume "$SID" "${PD[@]}" \
  --setting-sources project \
  --model sonnet \
  --max-budget-usd "$CAP2" \
  --allowedTools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent,TaskStop" \
  --tools "Read,Glob,Grep,Skill,Bash,Write,Edit,Agent,TaskStop" \
  --strict-mcp-config \
  --disallowedTools "${DIS[@]}" \
  --output-format stream-json --verbose --include-hook-events \
  < /dev/null > "$OP.t2.jsonl" 2> "$OP.t2.err" &
  CP=$!
  ( cd / && watch_loop "$CP" ) &
  WP=$!
  wait "$CP"; rc2=$?
  trap '' TERM INT HUP
  stopwatch
  turnaudit
  cost2=$(costof "$OP.t2.jsonl")
  craw2=$cost2
  if [ "$CUM" = 1 ] && [ "$cost2" != "?" ]; then
    cost2=$(awk -v a="$cost2" -v b="$cost1" 'BEGIN{d=a-b; if (d<0) d=0; printf "%.2f", d}')
  fi
  if [ "$cost2" = "?" ]; then cost2=$TC2; fi
  cost2=$(f2 "$cost2")
  ledadd "$cost2 stage.$RUN.t2"
  CP=
  trap on_sig TERM INT HUP
  after t2
  LEFT=$LEFTN
  secs2=$(( $(date +%s) - t2s ))
  sid2=$(initsid "$OP.t2.jsonl")
  if [ -n "$sid2" ] && [ "$sid2" != "$SID" ]; then
    echo "$sid2 $OWN" >> "$O/stage.sessions"; T2DIFF=1
  fi
fi

# --- 풀기: 둘째 턴 뒤(또는 안 보내기로 한 뒤) 한 번. 남은 프로세스가 있으면 풀지 않고 17 ---
secs=$(( $(date +%s) - T0 ))
if [ "${#SURV[@]}" -gt 0 ]; then
  if [ "$T2" = sent ]; then rc=$rc2; else rc=$rc1; fi
  why survivors
  count_sched_sess
  write_check 17
  survivor_note
  count_log
  SEALED_NOW=0
  exit 17
fi
unseal_all; SEALED_NOW=0
mirror_flush || BADL=1
{ [ "$BADL" = 1 ] || [ "$CTLBAD" = 1 ]; } && stopmark

# --- 끝 커밋: 보냈든 안 보냈든 한 번 ---
gw status --short > "$OP.end.status" 2>&1
gw add -A > /dev/null 2>&1
endok=1
gw commit -q --no-verify --allow-empty -m t2 > /dev/null 2>&1 || { committed=bad; endok=0; }
[ -z "$(gw status --porcelain)" ] || committed=bad
if [ "$endok" = 1 ]; then ENDC=$(git -C "$W" rev-parse HEAD); fi
if [ "$endok" = 1 ] && [ "$T2" = sent ]; then echo "$ENDC" > "$OP.t2"; fi
secs=$(( $(date +%s) - T0 ))
if [ "$T2" = sent ]; then rc=$rc2; else rc=$rc1; fi
cd /

# 끝난 뒤 바뀐 것: 가상 환경 지문 · 꾸러미 사본 · 홈의 설정 파일 · devkit 작업 트리
VENVCHG=0
if [ "$ST" = b ] || [ "$ST" = c ]; then
  fp "$X/env/$ST" > "$OP.venv1"
  cmp -s "$OP.venv0" "$OP.venv1" || VENVCHG=1
fi
KIT1=$(kitsha "$X/env/kit")
PREP=$(awk '$1=="copy"{print $2}' "$S/out-done/kit.sha" 2> /dev/null | head -n 1)
if [ "$KIT0" != "$KIT1" ] || { [ -n "$PREP" ] && [ "$PREP" != "$KIT1" ]; }; then KITSTATE=changed; fi
CH16=0
[ "$DOT0" = "$(dotsha)" ] || CH16=1
[ "$DK0" = "$(dkstat)" ] || CH16=1
count_sched_sess

# 끝 값 차례(여럿이면 앞의 것): 16 → 10 → 11 → 14 → 6 → 13 → 12(둘째 턴 앞 메모리 검사가 멈췄으면 3) → 5. 그 위에 통제 파일 바뀜·장부 틀림 4 → 봉한 폴더 풀림 17 → 낮은 커밋 143
EX=0
if [ "$CH16" = 1 ]; then EX=16
elif [ "$HOMEDK" != 0 ]; then EX=10
elif [ "$LEFT" != 0 ]; then EX=11
elif [ "$VENVCHG" = 1 ]; then EX=14
elif [ "$committed" != ok ]; then EX=6
elif [ "$T2DIFF" != 0 ]; then EX=13
elif [ "$T2" != sent ]; then EX=12; [ "$MEM2" = 1 ] && EX=3
elif [ "$rc" != 0 ]; then EX=5
fi
if [ "$BADL" = 1 ] || [ "$CTLBAD" = 1 ]; then EX=4; fi
if [ "$SEALBAD" = 1 ]; then EX=17; fi
if [ -e "$OP.low" ]; then EX=143; why low-mem; fi
write_check "$EX"
count_log
long=$(journalctl -k --since "@$T0" 2> /dev/null | command grep -c "abnormally long accept")
echo "stage.$RUN task=$TASK arm=$ARM rc1=$rc1 rc2=$rc2 t2=$T2 secs=$secs committed=$committed left1=$LEFT1 left=$LEFT kitsha=$KITSTATE exit=$EX long_accept=$long $(date +%H:%M:%S)" >> "$LOG"
echo "stage.$RUN task=$TASK arm=$ARM rc1=$rc1 rc2=$rc2 t2=$T2 secs=$secs committed=$committed left1=$LEFT1 left=$LEFT kitsha=$KITSTATE exit=$EX"
finish_move
exit "$EX"
