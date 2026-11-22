import ast
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "kit"
SCRIPT = KIT / "scripts" / "guard.py"
README = KIT / "README.md"
FIRST_GUIDE = KIT / "skills" / "find" / "first-guide.md"

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("devkit_guard", KIT / "scripts/guard.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

# test_session_start.py와 같은 목록
PY39 = [r"\b(list|dict|tuple|set)\[", r"functools import cache\b", r"\w\s*\|\s*None", r"\.removeprefix\(", r"\.removesuffix\(",
        r"is_relative_to\(", r"^\s*match\s.+:\s*$"]

HIT = [  # (도구, 입력, 답) — 7-3 시험 목록: 1번(.env Read)·9번(cat .env)·18번(.env를 겨눈 내용 검색)
 ("Read", {"file_path": "/p/.env"}, "ask"), ("Read", {"file_path": "/p/config/.env.local"}, "ask"),
 ("Read", {"file_path": "C:\\p\\.env"}, "ask"), ("Read", {"file_path": "/p/certs/server.pem"}, "ask"),
 ("Read", {"file_path": "/home/u/.ssh/id_rsa"}, "ask"), ("Read", {"file_path": "/p/credentials.json"}, "ask"),
 ("Read", {"file_path": "/p/config/client_secret.json"}, "ask"), ("Read", {"file_path": "/p/ServiceAccountKey.json"}, "ask"),
 ("Bash", {"command": "cat .env"}, "ask"), ("Bash", {"command": "head -5 config/.env.production"}, "ask"),
 ("Bash", {"command": "cd app && cat .env | grep PORT"}, "ask"), ("Bash", {"command": "grep -n PORT .env"}, "ask"),
 ("Bash", {"command": "grep PORT < .env"}, "ask"), ("Bash", {"command": "sudo cat /etc/app/.env"}, "ask"),
 ("Bash", {"command": "sed -n 1,5p ~/.npmrc"}, "ask"), ("Bash", {"command": "rg -n PORT -g '.env*'"}, "ask"), ("Bash", {"command": "grep -rn PORT --include=.env ."}, "ask"),  # 판정 T4 (앞 줄 rg -g 와 함께)
 ("Grep", {"pattern": "PORT", "path": "/p/.env", "output_mode": "content"}, "ask"),
 ("Grep", {"pattern": "DB_", "glob": ".env*", "output_mode": "content"}, "ask"),
 ("Grep", {"pattern": "password", "path": "/p/.env", "output_mode": "content"}, "ask"),  # 차례: 파일 쪽이 먼저
 ("Bash", {"command": 'grep -n "SECRET_KEY\\|SQLALCHEMY_DATABASE_URI\\|ADMIN_PASSWORD" default_settings.py | cut -c1-70'}, "deny"),
 ("Bash", {"command": "sed -n 1,60p run.py | grep -i password"}, "deny"), ("Bash", {"command": "grep -rn --include=*.py password ."}, "deny"),
 ("Bash", {"command": 'grep --include "*.py" -rn token .'}, "deny"), ("Bash", {"command": "git grep -n api_key"}, "deny"),
 ("Bash", {"command": 'find . -name "*.xml" | xargs grep -n -i jdbc'}, "deny"),
 ("Bash", {"command": 'cat src/main/resources/egovframework/spring/com/*.xml | grep -n -iE "dbcp|hsql|mysql|maria|postgres|jdbc" | cut -c1-90 | head'}, "deny"),
 ("Bash", {"command": "rg -i private_key src/"}, "deny"), ("Bash", {"command": "grep -ne DATABASE_URL settings.py"}, "deny"),
 ("Bash", {"command": "grep -n --regexp=passwd auth.py"}, "deny"), ("Bash", {"command": "echo $(grep -n password config.py)"}, "deny"),
 ("Bash", {"command": "cat .env; grep -n password x.py"}, "deny"), ("Bash", {"command": "grep -o 'SECRET_KEY.*' config.py"}, "deny"), ("Bash", {"command": "find . -exec grep -n password {} \\;"}, "deny"),  # 판정 T3
 ("Grep", {"pattern": "password", "output_mode": "content"}, "deny"), ("Grep", {"pattern": "SECRET_KEY|DATABASE_URI", "path": "/p/app", "output_mode": "content", "-i": True}, "deny"),
 # 고침 1회차 — 주석·감싸는 명령·속 명령·find/xargs·짝이 안 맞는 따옴표에서 판정이 건너뛰어지던 꼴: 묻기
 ("Bash", {"command": "# show config\ncat .env"}, "ask"), ("Bash", {"command": "grep -n PORT x.py  # check\ncat .env"}, "ask"),
 ("Bash", {"command": "echo a#b; cat .env"}, "ask"), ("Bash", {"command": "# don't print\ncat .env"}, "ask"),
 ("Bash", {"command": "if cat .env; then :; fi"}, "ask"), ("Bash", {"command": "{ cat .env; }"}, "ask"),
 ("Bash", {"command": "echo `cat .env`"}, "ask"), ("Bash", {"command": 'echo "$(cat .env)"'}, "ask"),
 ("Bash", {"command": "find . -name .env -exec cat {} \\;"}, "ask"), ("Bash", {"command": "find . -name '.env*' | xargs cat"}, "ask"),
 ("Bash", {"command": "find . -name '*.pem' -print0 | xargs -0 head -3"}, "ask"), ("Bash", {"command": "timeout 5 cat .env"}, "ask"),
 ("Bash", {"command": "docker exec app cat /app/.env"}, "ask"), ("Bash", {"command": "diff .env .env.example"}, "ask"),
 ("Bash", {"command": "jq . credentials.json"}, "ask"), ("Bash", {"command": "git diff .env"}, "ask"),
 ("Bash", {"command": "find . -name .env -exec grep -n PORT {} \\;"}, "ask"), ("Bash", {"command": "find . -name '.env*' | xargs grep -n PORT"}, "ask"),
 ("Bash", {"command": "rg -L PORT -g '.env*'"}, "ask"), ("Bash", {"command": "set -a; . .env; set +a"}, "ask"),
 ("Bash", {"command": "source .env"}, "ask"), ("Bash", {"command": 'echo "it\'s; cat .env'}, "ask"),
 # 같은 줄들 — 막기
 ("Bash", {"command": "! grep -n password x.py"}, "deny"), ("Bash", {"command": "git --no-pager grep -n password"}, "deny"),
 ("Bash", {"command": "git -C app grep -n api_key"}, "deny"), ("Bash", {"command": "nice -n 5 grep -rn token src/"}, "deny"),
 ("Bash", {"command": "rg -L password src/"}, "deny"), ("Bash", {"command": "timeout 30 grep -rn secret ."}, "deny"),
 # GAPS에서 옮겨 온 줄 — 이제 걸린다
 ("Bash", {"command": 'grep -n "password x.py'}, "deny"), ("Bash", {"command": "grep -n \\\npassword x.py"}, "deny"),
 ("Bash", {"command": 'echo "$(grep -n password x.py)"'}, "deny"), ("Bash", {"command": "diff <(grep -n password a.py) b.py"}, "deny"),
 ("Bash", {"command": "sudo -u app cat /etc/app/.env"}, "ask"),
 # 묻기 — find의 괄호·여러 -exec, 경로로 부른 xargs
 ("Bash", {"command": "find . \\( -name .env -o -name '*.pem' \\) -exec cat {} \\;"}, "ask"),
 ("Bash", {"command": "find . -name .env -exec echo {} \\; -exec cat {} \\;"}, "ask"),
 ("Bash", {"command": "find . -name .env -exec grep -l x {} \\; -exec cat {} \\;"}, "ask"),
 ("Bash", {"command": "find . -type f \\( -name .env \\) -exec grep -n PORT {} \\;"}, "ask"),
 ("Bash", {"command": "find . -name .env -print0 | /usr/bin/xargs -0 cat"}, "ask"),
 # 묻기 — 셸에 넘기는 heredoc은 명령으로 본다, heredoc 뒤의 명령도 본다
 ("Bash", {"command": "bash <<'EOF'\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "cat <<EOF | bash\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "git commit -F - <<'EOF'\nmsg\nEOF\ncat .env"}, "ask"),
 ("Bash", {"command": 'echo "a << b"\ncat .env'}, "ask"),
 # 묻기 — 읽는 명령 뒤에 온 이름은 여전히 본다
 ("Bash", {"command": "ssh -i k.pem host cat .env"}, "ask"),
 ("Bash", {"command": "docker run --env-file .env app cat credentials.json"}, "ask"),
 # 막기
 ("Bash", {"command": "ssh prod bash -s <<'EOF'\ngrep -n password /srv/app/settings.py\nEOF"}, "deny"),
 ("Bash", {"command": "cat <<EOF\nhello\nEOF\ngrep -n password x.py"}, "deny"),
 ("Bash", {"command": "find . \\( -name '*.py' -o -name '*.js' \\) -exec grep -n password {} \\;"}, "deny"),
 ("Bash", {"command": "rg --max-depth 3 password ."}, "deny"),
 ("Bash", {"command": "rg --sort path password src/"}, "deny"),
 ("Bash", {"command": "rg -M 200 password src/"}, "deny"),
 ("Bash", {"command": "ag --depth 2 password"}, "deny"),
 # 묻기 — 글을 돌리는 명령이 받는 heredoc은 명령으로 본다(이름이 붙어 있어도, 목록에 없는 명령이어도)
 ("Bash", {"command": "bash<<'EOF'\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "cat <<'EOF'|bash\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "{ bash; } <<'EOF'\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "sudo -i <<'EOF'\ncat /root/.env\nEOF"}, "ask"),
 ("Bash", {"command": "su - app <<'EOF'\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "source /dev/stdin <<'EOF'\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "x=$(bash <<'EOF'\ncat .env\nEOF\n)"}, "ask"),
 ("Bash", {"command": "cat <<'EOF' > >(bash)\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "eval \"$(cat <<'EOF'\ncat .env\nEOF\n)\""}, "ask"),
 ("Bash", {"command": "(cat <<'EOF'\ncat .env\nEOF\n) | bash"}, "ask"),
 ("Bash", {"command": "tee /tmp/x.sh <<'EOF' | bash\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "git commit -m 'a & b' ; bash <<'EOF'\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "cat \\\" ; bash \"\" <<'EOF'\ncat .env\nEOF"}, "ask"),
 # 묻기 — 줄 이음(`\`+줄바꿈, 줄 끝의 `|`)
 ("Bash", {"command": "cat <<'EOF' |\nbash\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "cat <<'EOF' \\\n | bash\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "find . -name .env |\n  xargs cat"}, "ask"),
 ("Bash", {"command": "find . -name .env -print0 |\nxargs -0 cat"}, "ask"),
 # 묻기 — heredoc이 아닌 `<<`에 속지 않는다
 ("Bash", {"command": "# see <<EOF\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "echo $((1<<n))\ncat .env\nn"}, "ask"),
 ("Bash", {"command": "cat <<EOF.x\nhi\nEOF.x\ncat .env\nEOF"}, "ask"),
 ("Bash", {"command": "git commit -m \"guard: handle <<EOF bodies\"\ncat .env\ncat > n.txt <<'EOF'\nx\nEOF"}, "ask"),
 ("Bash", {"command": "echo '<<EOF'\ncat .env\nEOF"}, "ask"),
 # 묻기 — 앞 조각에서 넘겨받는 이름
 ("Bash", {"command": "git ls-files | grep .env | xargs cat"}, "ask"),
 # 막기
 ("Bash", {"command": "sh<<EOF\ngrep -n password x.py\nEOF"}, "deny"),
 ("Bash", {"command": "ssh -i k.pem \\\n  ec2-user@prod <<'EOF'\ngrep -n password /srv/app/settings.py\nEOF"}, "deny"),
 ("Bash", {"command": "tee >(sh) <<'EOF'\ngrep -n password x.py\nEOF"}, "deny"),
 ("Bash", {"command": "cat <<'EOF' | sh -s\ngrep -n password x.py\nEOF"}, "deny"),
]
PASS = [  # 7-3: .env.example(1번), 이름에 env가 든 보통 코드 파일(4·5·28·29번)
 ("Read", {"file_path": "/p/.env.example"}), ("Read", {"file_path": "/p/.env.sample"}),
 ("Read", {"file_path": "/p/config/.env.template"}), ("Read", {"file_path": "/p/src/env.py"}),
 ("Read", {"file_path": "/p/src/environment.ts"}), ("Read", {"file_path": "/home/u/.ssh/id_rsa.pub"}),
 ("Read", {"file_path": "/p/keyboard.py"}), ("Read", {"file_path": "/p/docs/key-points.md"}),
 ("Read", {"file_path": "/p/src/SecretService.java"}), ("Read", {"file_path": "/p/tests/test_secret.py"}),  # 판정 K
 ("Bash", {"command": "cat .env.example"}), ("Bash", {"command": "ls -la .env"}),
 ("Bash", {"command": "test -f .env && echo yes"}), ("Bash", {"command": "grep -l password -r ."}),
 ("Bash", {"command": "grep -c SECRET_KEY default_settings.py"}), ("Bash", {"command": "grep -rln --include=*.py token ."}),
 ("Bash", {"command": "grep -q password x.py && echo found"}), ("Bash", {"command": "grep -c -n password x.py"}),
 ("Bash", {"command": "grep -n PORT config.py"}), ("Bash", {"command": 'grep -n "def login" auth.py'}),
 ("Bash", {"command": 'grep -rn "csrf" templates/'}), ("Bash", {"command": 'echo "grep -n password x" > notes.txt'}),
 ("Bash", {"command": "git log --oneline -5"}), ("Bash", {"command": "python -m pytest -q"}),
 ("Bash", {"command": "find . -name .env"}), ("Bash", {"command": 'find . -name "*.pem" -print'}), ("Bash", {"command": 'find . -iname "*secret*"'}),  # 판정 T3
 ("Bash", {"command": "cat env.py"}), ("Bash", {"command": "grep -n PORT environment.ts"}), ("Bash", {"command": "grep PORT .env.example"}),
 ("Grep", {"pattern": "password"}), ("Grep", {"pattern": "password", "output_mode": "count"}),
 ("Grep", {"pattern": "PORT", "path": "/p/config.py", "output_mode": "content"}),
 ("Write", {"file_path": "/p/.env", "content": "PORT=8080\n"}), ("Edit", {"file_path": "/p/.env", "old_string": "a", "new_string": "b"}), ("Glob", {"pattern": "**/.env*"}),
 # 고침 1회차 — 넓어진 판정이 잘못 걸지 않아야 하는 꼴
 ("Bash", {"command": "git commit -m 'fix cat .env handling'"}), ("Bash", {"command": "cp .env.example .env"}),
 ("Bash", {"command": "touch .env"}), ("Bash", {"command": "chmod 600 .env && cat app.py"}),
 ("Bash", {"command": "python -m pytest -q -k password"}), ("Bash", {"command": "git log --oneline --grep password"}),
 ("Bash", {"command": "grep -L password -r ."}), ("Bash", {"command": "find . -name '.env*' | xargs grep -l PORT"}),
 ("Bash", {"command": "find . -name '*.py' | xargs grep -ln password"}), ("Bash", {"command": "git diff"}),
 ("Bash", {"command": "jq . package.json"}), ("Bash", {"command": "source venv/bin/activate"}),
 ("Bash", {"command": "cat x.py; ls .env"}), ("Bash", {"command": "# list only\ngrep -rl password ."}),
 # 셸에 넘기지 않는 heredoc 글 — 커밋·PR 메시지, 파일에 써 넣는 글
 ("Bash", {"command": "git commit -m \"$(cat <<'EOF'\nguard: grep -n token handling\n\nadd jq check for credentials.json loader\nEOF\n)\""}),
 ("Bash", {"command": "gh pr create --title x --body \"$(cat <<'EOF'\n- cat .env no longer printed\nEOF\n)\""}),
 ("Bash", {"command": "git commit -F - <<'EOF'\nguard: grep token lines\nEOF"}),
 ("Bash", {"command": "cat > t.sh <<'EOF'\ngrep -n password x.py\nEOF"}),
 # 읽는 명령 앞에 온 이름 — 접속 열쇠·환경 파일을 넘길 뿐 읽지 않는다
 ("Bash", {"command": "ssh -i ~/.ssh/aws.pem ec2-user@host tail -n 100 /var/log/app.log"}),
 ("Bash", {"command": "ssh -i deploy.key host sudo cat /var/log/nginx/error.log"}),
 ("Bash", {"command": "docker run --rm --env-file .env app cat /etc/os-release"}),
 ("Bash", {"command": "docker compose --env-file .env.prod run web head -5 manage.py"}),
 ("Bash", {"command": "ssh -i key.pem host grep -n ERROR /var/log/x"}),
 # xargs가 넘겨받는 이름은 같은 파이프 줄에서만 찾는다
 ("Bash", {"command": "find . -name '*.py' | xargs grep -n TODO; ls .env"}),
 ("Bash", {"command": "find . -name '*.py' | xargs head -1; git status .env"}),
 ("Bash", {"command": "find . \\( -name '*.py' \\) -exec grep -l password {} \\;"}),
 # 넘겨받는 이름은 앞 조각에서만 찾는다 — 뒤 조각·자기 인자에 적힌 이름은 넘겨받은 것이 아니다
 ("Bash", {"command": "find . -name '*.ts' -exec grep -n '.env' {} +"}),
 ("Bash", {"command": "find src -type f -exec grep -n .env.local {} \\;"}),
 ("Bash", {"command": "find docs -name '*.md' -exec cat {} + | grep -v .env"}),
 ("Bash", {"command": "find . -name '*.py' -exec sed -n 1p {} \\; -print | grep -v id_rsa"}),
 ("Bash", {"command": "git ls-files | xargs grep -n '.env'"}),
 ("Bash", {"command": "find . -name '*.md' | xargs cat | grep -v credentials.json"}),
 # 돌리지 않는 heredoc 글 — 제목에 `ssh`·`bash`·`&`·`<<`가 있어도 커밋·PR 글은 글이다
 ("Bash", {"command": "gh pr create --title \"fix ssh timeout\" --body \"$(cat <<'EOF'\n- grep -n token no longer printed\nEOF\n)\""}),
 ("Bash", {"command": "git commit -m \"$(cat <<'EOF'\nfix bash completion; grep -n password no longer shown\nEOF\n)\""}),
 ("Bash", {"command": "gh pr create --title \"docs & tests\" --body \"$(cat <<'EOF'\n- grep -n token blocked\nEOF\n)\""}),
 ("Bash", {"command": "x=$(cat <<'EOF'\ngrep -n password notes\nEOF\n)"}),
 ("Bash", {"command": "git commit -m 'handle <<EOF bodies' -F - <<'MSG'\ngrep -n token\nMSG"}),
 ("Bash", {"command": "sudo tee /etc/app.conf <<EOF\nport=1\nEOF"}),
 ("Bash", {"command": "cat <<-'EOF' > f\n\tgrep -n password x\n\tEOF\necho ok"}),
 # 명령으로 읽어도 걸릴 것이 없는 heredoc
 ("Bash", {"command": "ssh host <<'EOF'\ncd /srv && git pull && systemctl restart app\nEOF"}),
 ("Bash", {"command": "psql <<EOF\nselect token from users;\nEOF"}),
 ("Bash", {"command": "python3 - <<'PY'\nimport json\nprint(sorted(json.load(open('package.json'))))\nPY"}),
]
GAPS = [  # (꼬리표, 도구, 입력) — 못 막는 길, 지금은 지나간다. 꼬리표마다 README "못 막는 길"에 같은 글자가 있다
 ("평범한 이름의 설정 파일", "Read", {"file_path": "/p/ihatemoney/default_settings.py"}),
 ("평범한 이름의 설정 파일", "Bash", {"command": "sed -n 1,50p ihatemoney/default_settings.py"}),
 ("평범한 이름의 설정 파일", "Bash", {"command": "cat ihatemoney/default_settings.py | head -30"}),
 ("secrets.py", "Read", {"file_path": "/p/src/secrets.py"}),
 ("작은 프로그램", "Bash", {"command": "python3 -c \"print(open('.env').read())\""}),
 ("awk", "Bash", {"command": "awk '/password/' settings.py"}), ("sed -n '/낱말/p'", "Bash", {"command": "sed -n '/password/p' settings.py"}),
 ("git show", "Bash", {"command": "git show HEAD:config.py"}),
 ("폴더째", "Bash", {"command": 'grep -rn "DB_" .'}),
 ("bash -c", "Bash", {"command": 'bash -c "grep -n password x.py"'}),
 ("grep -f", "Bash", {"command": "grep -f words.txt config.py"}),
 ("셸이 만드는 이름", "Bash", {"command": "for f in .env; do cat $f; done"}), ("셸이 만드는 이름", "Bash", {"command": "cat .e*"}),
 ("셸이 만드는 이름", "Bash", {"command": "cat $(echo .env)"}), ("넓은 꼴", "Bash", {"command": "grep -rn PORT --include='*env*' ."}),
 ("옮긴 뒤", "Bash", {"command": "cp .env /tmp/x"}), ("줄인 낱말", "Bash", {"command": "grep -n 'pass' x.py"}),
 ("줄인 낱말", "Bash", {"command": "grep -n pwd x.py"}), ("bash -c", "Bash", {"command": "bash -c 'cat .env'"}),
 ("ssh 호스트", "Bash", {"command": "ssh prod 'cat /srv/app/.env'"}),
 ("docker exec", "Bash", {"command": "docker exec app sh -c 'cat /app/.env'"}),
 ("eval", "Bash", {"command": 'eval "cat .env"'}),
 ("파일에 써 넣은 뒤 돌리기", "Bash", {"command": "cat > t.sh <<'EOF'\ncat .env\nEOF\nbash t.sh"}),
 ("겹친 속 명령", "Bash", {"command": 'echo "$(echo `cat .env`)"'}),
 ("드문 검색 옵션", "Bash", {"command": "rg -T js password src/"}),
 ("드문 검색 옵션", "Bash", {"command": "ag -G py password"}),
 ("목록에 없는 이름", "Bash", {"command": "cat prod.env"}),
 ("목록에 없는 이름", "Bash", {"command": "cat ~/.aws/credentials"}),
 ("목록에 없는 이름", "Bash", {"command": "cat ~/.ssh/id_ed25519"}),
 ("파일에 써 넣은 뒤 돌리기", "Bash", {"command": "cat <<'EOF' > a.txt && bash a.txt\ncat .env\nEOF"}),
 ("파일에 적어 두었다가 넘기기", "Bash", {"command": "find . -name .env > /tmp/l; xargs cat < /tmp/l"}),
 ("따옴표 안에 통째로 든 명령", "Bash", {"command": "find . -name .env | xargs -I{} sh -c 'cat {}'"}),
 ("작은 프로그램", "Bash", {"command": "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['cat', '.env'])\nPY"}),
 ("명령으로 써 넣기", "Bash", {"command": "sed -i 's/=.*/=<devkit이 가린 값>/' app.cfg"}),
 ("Write·Edit 밖의 쓰기 도구", "NotebookEdit", {"notebook_path": "/p/a.ipynb", "new_source": "<devkit이 가린 값>"}),
]
OVER = [  # (꼬리표, 명령, 답) — 잘못 걸리는 것으로 알고 두는 꼴. 꼬리표마다 README "잘못 걸리는 것:" 줄에 같은 글자가 있다
 ("tokenize", "grep -n tokenize src/", "deny"),
 ("echo cat .env", "echo cat .env", "ask"),
 ("빼라고 적은 이름", "git diff -- . ':!*.pem'", "ask"),
 ("grep -v .env", "ls | grep -v .env | xargs cat", "ask"),
 ("여러 줄 글", "psql app <<'SQL'\n-- cat .env first\nselect 1;\nSQL", "ask"),
]
WRITE_OVER = [  # (꼬리표, 도구, 입력) — 잘못 걸리는 것으로 알고 두는 쓰기. 꼬리표마다 README "잘못 걸리는 것:" 줄에 같은 글자가 있다
 ("표시 글을 미리 적어 둔 파일", "Write", {"file_path": "/p/app.cfg", "content": "password=<devkit이 가린 값>\nport=1\n"}),
 ("표시 글 자체를 적는 글", "Write", {"file_path": "/p/notes.md", "content": "가려진 값은 `<devkit이 가린 값>`으로 보인다.\n"}),
]
MARK = "<devkit이 가린 값>"


# (명령, 답) — 긴 명령도 판정이 2초 안에 끝나야 한다(훅 제한 10초를 넘기면 판정 없이 지나간다)
SLOW = [
 ("cat " * 2000, None),
 ("sort cut " * 500 + "grep -n password x.py", "deny"),
 ("' " + "cat " * 1000, None),
 ("find . " + "-exec grep -l x {} \\; " * 2000, None),
 ("cat " + "<<E " * 2000 + "\nE\n" * 2000, None),
 ("cat " + "<<E " * 25000 + "\nE", None),
 ("bash " + "<<E " * 25000 + "\nE", None),
 ("a <<E | " * 12000 + "\nE", None),
 ("$(cat <<E " * 9000, None),
 ("".join("bash <<A%d\nx\nA%d\n" % (i, i) for i in range(6000)), None),
 ('" <<E ' * 15000 + "\nE", None),
 ("xargs cat " + "a " * 50000, None),
]


def read_env(cwd):
    return payload("Read", {"file_path": "/p/.env"}, cwd)


def grep_pw(cwd):
    return payload("Bash", {"command": "grep -n password x.py"}, cwd)


def list_pw(cwd):
    return payload("Bash", {"command": "grep -l password -r ."}, cwd)


BAD = [b"", b"not json", b"[]", b"{}", b'{"tool_name":"Bash"}', b'{"tool_name":"Bash","tool_input":{"command":5}}',
       b'{"tool_name":"Read","tool_input":{"file_path":null}}', b"\xff\xfe\x00{"]

ASK_TEXT = ("devkit: 이 파일은 이름이 비밀값 파일 꼴이다({name}). 열면 내용이 대화 기록에 남는다. "
            "값이 꼭 필요할 때만 허용하고, 값 없이 할 수 있는 일이면 열지 않고 진행한다.")
DENY_TEXT = ("devkit: 비밀번호·키 같은 낱말로 찾은 줄을 그대로 찍는 검색은 막는다(값이 기록에 남는다). "
             "파일 이름만(-l) 또는 개수만(-c) 나오게 바꿔 다시 찾고, 필요한 코드 파일은 그 뒤에 연다. 일은 멈추지 않는다.")
SECTION = "## 비밀값 파일 한 번 더 거르기"


def run(inp, home, cwd, env=None):
    data = inp.encode("utf-8") if isinstance(inp, str) else inp
    try:
        sent = json.loads(data.decode("utf-8", errors="replace"))
    except ValueError:
        sent = None
    if isinstance(sent, dict) and "cwd" in sent:      # 훅이 받는 cwd도 이 시험의 임시 자리 아래여야 한다 (진짜 폴더를 열지 않는다)
        root = Path(home).parent.parts
        assert Path(str(sent["cwd"])).parts[:len(root)] == root, sent["cwd"]
    return subprocess.run([sys.executable, str(SCRIPT)], input=data, cwd=str(cwd),
                          env={"PATH": os.environ["PATH"], "HOME": str(home), **(env or {})},
                          capture_output=True, timeout=30)


def snap(d):
    d = Path(d)
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts}


def payload(tool, tool_input, cwd):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)})


def section():
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert SECTION in lines
    start = lines.index(SECTION)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


@pytest.mark.parametrize("tool,inp,kind", HIT, ids=[str(i) for i in range(len(HIT))])
def test_hits(tool, inp, kind):
    r = G.judge(tool, inp)
    assert r is not None and r[0] == kind


@pytest.mark.parametrize("tool,inp", PASS, ids=[str(i) for i in range(len(PASS))])
def test_passes(tool, inp):
    assert G.judge(tool, inp) is None


@pytest.mark.parametrize("tag,tool,inp", GAPS, ids=[str(i) for i in range(len(GAPS))])
def test_known_gaps(tag, tool, inp):
    assert G.judge(tool, inp) is None


@pytest.mark.parametrize("tag,cmd,kind", OVER, ids=[str(i) for i in range(len(OVER))])
def test_known_overblocks(tag, cmd, kind):
    r = G.judge("Bash", {"command": cmd})
    assert r is not None and r[0] == kind


@pytest.mark.parametrize("cmd,kind", SLOW, ids=[str(i) for i in range(len(SLOW))])
def test_long_command_is_fast(cmd, kind):
    start = time.perf_counter()
    r = G.judge("Bash", {"command": cmd})
    assert time.perf_counter() - start < 2
    assert (r[0] if r else None) == kind


def test_names_match_first_guide():
    L = FIRST_GUIDE.read_text(encoding="utf-8").splitlines()
    line = L[L.index("## 읽지 않는 것") + 1]   # 보는 차례가 늘어도 그 절의 첫 줄
    names = re.findall(r"`([^`]+)`", re.search(r"이름이 (.+?)인 파일", line).group(1))
    assert len(names) == 14 and names == G.NAMES


def test_words_exact():
    assert G.WORDS == ["password", "passwd", "secret", "api_key", "apikey", "api-key", "token", "private_key",
                       "database_ur", "jdbc"]


@pytest.mark.parametrize("make,kind", [(read_env, "ask"), (grep_pw, "deny")], ids=["ask", "deny"])
def test_hook_answers(tmp_path, make, kind):
    r = run(make(tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b""
    out = r.stdout.decode("ascii")
    assert out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": kind,
                                                     "permissionDecisionReason": G.MESSAGES[kind].format(name=".env")}}


def test_hook_silent_on_pass(tmp_path):
    r = run(list_pw(tmp_path), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


@pytest.mark.parametrize("make,as_dir", [(read_env, False), (grep_pw, False), (grep_pw, True)],
                         ids=["READ_ENV-file", "GREP_PW-file", "GREP_PW-dir"])
def test_off_marker(tmp_path, make, as_dir):
    home = tmp_path / "home"
    home.mkdir()
    marker = home / G.MARKER
    if as_dir:
        marker.mkdir()
    else:
        marker.write_bytes(b"")
    r = run(make(tmp_path), home, tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


@pytest.mark.parametrize("raw", BAD, ids=[str(i) for i in range(len(BAD))])
def test_bad_input_quiet(tmp_path, raw):
    r = run(raw, tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_crash_is_visible(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(G, "judge", boom)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(grep_pw(tmp_path).encode())))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert G.main() == 1
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.endswith("\n") and cap.err.count("\n") == 1
    assert cap.err.isascii() and cap.err.startswith("devkit guard: ")


def test_answer_is_ascii(tmp_path):
    for make in (read_env, grep_pw):
        r = run(make(tmp_path), tmp_path / "home", tmp_path)
        assert r.stdout and all(b < 0x80 for b in r.stdout)


def test_creates_nothing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("PORT=1\n", encoding="utf-8")
    before = (snap(tmp_path), snap(KIT))
    for make in (read_env, grep_pw, list_pw):
        run(make(proj), tmp_path / "home", proj)
    assert (snap(tmp_path), snap(KIT)) == before


def test_imports_only_stdlib():
    found = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
    assert found <= {"fnmatch", "json", "os", "re", "shlex", "sys"}


def test_guard_is_python38():
    src = SCRIPT.read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for pat in PY39:
        assert not re.search(pat, src, re.M), pat


def test_messages_exact():
    assert G.MESSAGES == {"ask": ASK_TEXT, "deny": DENY_TEXT}


def test_messages_rules():
    for text in G.MESSAGES.values():
        assert G.MARKER not in text and "devkit-guard-off" not in text and "AI에게" not in text
        assert text.startswith("devkit: ") and "\n" not in text and "막아 준다" not in text
    assert "-l" in G.MESSAGES["deny"]


def test_readme_section():
    sec = "\n".join(section())
    for item in G.NAMES + G.WORDS:
        assert "`%s`" % item in sec, item
    assert ".devkit-guard-off" in sec and ".devkit/secret-names" in sec
    text = README.read_text(encoding="utf-8")
    assert "막아 준다" not in text and "Read(./.env)" not in text


def test_gaps_in_readme():
    lines = section()
    start = next(i for i, x in enumerate(lines) if "**못 막는 길:**" in x)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("- ")), len(lines))
    block = "\n".join(lines[start:end])
    for tag in {t for t, _, _ in GAPS}:
        assert tag in block, tag


def test_overblocks_in_readme():
    lines = section()
    line = next(x for x in lines if "**잘못 걸리는 것:**" in x)
    for tag in {t for t, _, _ in OVER}:
        assert tag in line, tag


def _project(tmp_path, list_text):
    proj = tmp_path / "proj"
    (proj / ".devkit").mkdir(parents=True)
    path = proj / ".devkit" / "secret-names"
    if isinstance(list_text, bytes):
        path.write_bytes(list_text)
    else:
        path.write_text(list_text, encoding="utf-8")
    return proj


def _asks(r, name):
    assert r.returncode == 0 and r.stderr == b""
    out = json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask" and name in out["permissionDecisionReason"]


@pytest.mark.parametrize("mode", ["env", "cwd"])
def test_project_list_asks(tmp_path, mode):
    proj = _project(tmp_path, "globals.properties\n")
    other = tmp_path / "other"
    other.mkdir()
    target = {"file_path": str(proj / "src/main/resources/globals.properties")}
    if mode == "env":
        r = run(payload("Read", target, other), tmp_path / "home", tmp_path, env={"CLAUDE_PROJECT_DIR": str(proj)})
    else:
        r = run(payload("Read", target, proj), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b""
    out = json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask" and "globals.properties" in out["permissionDecisionReason"]


@pytest.mark.parametrize("mode", ["none", "unreadable"])
def test_project_list_absent(tmp_path, mode):
    proj = tmp_path / "proj"
    proj.mkdir()
    if mode == "unreadable":
        (proj / ".devkit" / "secret-names").mkdir(parents=True)
    r = run(payload("Read", {"file_path": str(proj / "globals.properties")}, proj), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    r = run(payload("Read", {"file_path": "/p/.env"}, proj), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_project_list_comments(tmp_path):
    proj = _project(tmp_path, "# globals.properties\n\n  local.properties  \n")
    r = run(payload("Read", {"file_path": "/x/globals.properties"}, proj), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    r = run(payload("Read", {"file_path": "/x/local.properties"}, proj), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_project_list_50_lines(tmp_path):
    proj = _project(tmp_path, "".join("filler-%d\n" % i for i in range(50)) + "globals.properties\n")
    r = run(payload("Read", {"file_path": "/x/globals.properties"}, proj), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_project_list_bom(tmp_path):
    proj = _project(tmp_path, b"\xef\xbb\xbfglobals.properties\n")
    r = run(payload("Read", {"file_path": "/x/globals.properties"}, proj), tmp_path / "home", tmp_path)
    _asks(r, "globals.properties")


def test_project_list_path_line(tmp_path):
    proj = _project(tmp_path, "src/main/resources/globals.properties\nconf\\local.properties\n")
    for name in ("globals.properties", "local.properties"):
        r = run(payload("Read", {"file_path": "/x/" + name}, proj), tmp_path / "home", tmp_path)
        _asks(r, name)


def test_project_list_comment_with_slash(tmp_path):
    proj = _project(tmp_path, "# see src/other.properties\n")
    r = run(payload("Read", {"file_path": "/x/other.properties"}, proj), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_project_list_fifo(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".devkit").mkdir(parents=True)
    try:
        os.mkfifo(str(proj / ".devkit" / "secret-names"))
    except (AttributeError, OSError):
        pytest.skip("mkfifo not available")
    home = tmp_path / "home"
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(tmp_path), capture_output=True, timeout=10,
                       input=payload("Read", {"file_path": "/x/globals.properties"}, proj).encode("utf-8"),
                       env={"PATH": os.environ["PATH"], "HOME": str(home)})
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(tmp_path), capture_output=True, timeout=10,
                       input=payload("Read", {"file_path": "/x/.env"}, proj).encode("utf-8"),
                       env={"PATH": os.environ["PATH"], "HOME": str(home)})
    _asks(r, ".env")


def test_no_real_cwd():
    src = Path(__file__).read_text(encoding="utf-8")
    assert not re.search(r"cwd\s*=\s*[\"']/p[\"']|[\"']cwd[\"']\s*:\s*[\"']/p[\"']", src)


WRITE_MARK = [
    ("Write", {"file_path": "/p/a.py", "content": 'DB_PASSWORD = "<devkit이 가린 값>"\n'}),
    ("Edit", {"file_path": "/p/a.py", "old_string": "A = 1", "new_string": 'DB_PASSWORD = "<devkit이 가린 값>"'}),
]
WRITE_PLAIN = [
    ("Write", {"file_path": "/p/a.py", "content": "A = 1\n"}),
    ("Edit", {"file_path": "/p/a.py", "old_string": "A = 1", "new_string": "A = 2"}),
    ("Edit", {"file_path": "/p/a.py", "old_string": 'DB_PASSWORD = "<devkit이 가린 값>"', "new_string": "A = 2"}),
]


@pytest.mark.parametrize("tool,inp", WRITE_MARK, ids=["write", "edit"])
def test_write_with_mark_denied(tmp_path, tool, inp):
    assert G.judge(tool, inp) == ("mask", "")
    r = run(payload(tool, inp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b""
    out = r.stdout.decode("ascii")
    assert out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": G.MASK_TEXT}}


@pytest.mark.parametrize("tool,inp", WRITE_PLAIN, ids=["write", "edit", "edit-mark-only-in-old"])
def test_write_without_mark_silent(tmp_path, tool, inp):
    assert G.judge(tool, inp) is None
    r = run(payload(tool, inp, tmp_path), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


@pytest.mark.parametrize("tool,inp", WRITE_MARK, ids=["write", "edit"])
def test_write_mark_off_marker(tmp_path, tool, inp):
    home = tmp_path / "home"
    home.mkdir()
    (home / G.MARKER).write_bytes(b"")
    r = run(payload(tool, inp, tmp_path), home, tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_prefilled_file():
    edit = lambda old, new: ("Edit", {"file_path": "/p/a.py", "old_string": old, "new_string": new})
    # 표시 글이 이미 든 파일 — 다른 줄을 고치는 Edit는 지나간다
    assert G.judge("Edit", {"file_path": "/p/a.py", "old_string": "A = 1", "new_string": "A = 2"}) is None
    assert G.judge(*edit("p = <devkit이 가린 값>\nA = 1", "p = <devkit이 가린 값>\nA = 2")) is None
    # 표시 글이 는 Edit는 거절
    assert G.judge(*edit("p = <devkit이 가린 값>", "p = <devkit이 가린 값>\nq = <devkit이 가린 값>")) == ("mask", "")
    assert G.judge("Edit", {"file_path": "/p/a.py", "new_string": "x = <devkit이 가린 값>"}) == ("mask", "")
    assert G.judge("Edit", {"file_path": "/p/a.py", "old_string": 5, "new_string": "x = <devkit이 가린 값>"}) == ("mask", "")
    # 통째로 다시 쓰는 Write는 표시 글이 있으면 거절
    assert G.judge("Write", {"file_path": "/p/a.py", "content": "p = <devkit이 가린 값>\nA = 2\n"}) == ("mask", "")
    assert G.judge("Write", {"file_path": "/p/a.py", "content": "A = 2\n"}) is None
    assert G.judge("Write", {"file_path": "/p/a.py", "content": 5}) is None


def test_mask_text_rules():
    text = G.MASK_TEXT
    assert text.startswith("devkit: ") and "\n" not in text
    assert MARK in text and "사용자에게 묻는다" in text
    assert "막아 준다" not in text and "devkit-guard-off" not in text and "AI에게" not in text
    assert G.MARK == MARK


@pytest.mark.parametrize("tag,tool,inp", WRITE_OVER, ids=[str(i) for i in range(len(WRITE_OVER))])
def test_write_over(tag, tool, inp):
    assert G.judge(tool, inp) == ("mask", "")


def test_write_over_in_readme():
    line = next(x for x in section() if "**잘못 걸리는 것:**" in x)
    for tag in {t for t, _, _ in WRITE_OVER}:
        assert tag in line, tag


# 새 실행 방식(Code Mode)에서는 폴더 안 명령이 `cd '폴더' && 명령` 꼴로 온다 — 평소와 같게 판정한다
CD_FORMS = [  # (명령, judge 결과)
 ("grep -n password settings.py", ("deny", "")),
 ("cd 'app' && grep -n password settings.py", ("deny", "")),
 ('cd "my app" && grep -rn secret .', ("deny", "")),
 ("cat .env", ("ask", ".env")),
 ("cd 'app' && cat .env", ("ask", ".env")),
 ("cd 'config' && cat credentials.json", ("ask", "credentials.json")),
 ("cd 'app'; cat .env", ("ask", ".env")),
 ("(cd 'app' && cat .env)", ("ask", ".env")),
 ("pushd app >/dev/null && cat .env", ("ask", ".env")),
 ("cd 'app' && git push", None),
 ("cd 'app' && grep -rl password .", None),
 ("cd 'app' && python3 -m pytest -q", None),
 ("cd '/p/app' && cat .env", ("ask", ".env")),
 ("cd 'it'\\''s' && cat .env", ("ask", ".env")),
]
CD_SAME = [  # (폴더에 들어가는 꼴, 같은 명령의 맨 꼴)
 ("cd 'app' && grep -n password settings.py", "grep -n password settings.py"),
 ('cd "my app" && grep -rn secret .', "grep -rn secret ."),
 ("cd 'app' && cat .env", "cat .env"), ("cd 'config' && cat credentials.json", "cat credentials.json"),
 ("cd 'app'; cat .env", "cat .env"), ("(cd 'app' && cat .env)", "cat .env"),
 ("pushd app >/dev/null && cat .env", "cat .env"), ("cd 'app' && git push", "git push"),
 ("cd 'app' && grep -rl password .", "grep -rl password ."), ("cd 'app' && python3 -m pytest -q", "python3 -m pytest -q"),
 ("cd '/p/app' && cat .env", "cat .env"), ("cd 'it'\\''s' && cat .env", "cat .env"),
]


@pytest.mark.parametrize("cmd,want", CD_FORMS, ids=[str(i) for i in range(len(CD_FORMS))])
def test_cd_forms(cmd, want):
    assert G.judge("Bash", {"command": cmd}) == want


@pytest.mark.parametrize("cd,bare", CD_SAME, ids=[str(i) for i in range(len(CD_SAME))])
def test_cd_same_as_bare(cd, bare):
    assert G.judge("Bash", {"command": cd}) == G.judge("Bash", {"command": bare})


def test_cd_form_hook_same(tmp_path):
    for i, loud in ((0, True), (2, True), (7, False)):
        cd, bare = CD_SAME[i]
        a = run(payload("Bash", {"command": cd}, tmp_path), tmp_path / "home", tmp_path)
        b = run(payload("Bash", {"command": bare}, tmp_path), tmp_path / "home", tmp_path)
        assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)
        assert bool(a.stdout) == loud
