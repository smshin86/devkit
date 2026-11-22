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
SCRIPT = KIT / "scripts" / "mask.py"
README = KIT / "README.md"

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("devkit_mask", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

# test_guard.py와 같은 목록
PY39 = [r"\b(list|dict|tuple|set)\[", r"functools import cache\b", r"\w\s*\|\s*None", r"\.removeprefix\(", r"\.removesuffix\(",
        r"is_relative_to\(", r"^\s*match\s.+:\s*$"]

F = "zzFAKEvalue9"            # 한눈에 가짜인 값 — 진짜처럼 생긴 토큰은 글자 그대로 적지 않고 아래처럼 이어 붙인다
L = F * 2
MARK = "<devkit이 가린 값>"
D = True                      # 설정 파일에서 읽은 줄
HEAD = "-----BEGIN " + "RSA PRIVATE KEY-----"
TAIL = "-----END " + "RSA PRIVATE KEY-----"
BODY = ("MIIfake0" + "Ab1+/" * 12 + "\n") * 3
TOK = {
    "aws": "AK" + "IA" + "X" * 16,
    "ghp": "gh" + "p_" + "a1" * 18,
    "gho": "gh" + "o_" + "a1" * 18,
    "ghs": "gh" + "s_" + "a1" * 18,
    "pat": "github" + "_pat_" + "a1" * 20,
    "xoxb": "xo" + "xb-" + "a1" * 6,
    "xoxp": "xo" + "xp-" + "a1" * 6,
    "sk": "s" + "k-" + "a1" * 12,
    "aiza": "AI" + "za" + "a" * 35,
    "jwt": "ey" + "J" + "a" * 12 + ".ey" + "J" + "b" * 12 + "." + "c" * 8,
    "sklive": "sk" + "_live_" + "a1" * 12,
    "rktest": "rk" + "_test_" + "a1" * 12,
    "glpat": "gl" + "pat-" + "a1" * 10,
}

# (줄, 설정 파일에서 읽은 줄인가) — 가려야 하는 줄
MASKED = [
    ('DB_PASSWORD = "%s"' % F, 0), ('"password" => "%s"' % F, 0),
    ('  "apiKey": "%s",' % F, 0),
    ("SECRET_KEY=%s" % F, 0), ("export API_TOKEN=%s" % F, 0), ("      - POSTGRES_PASSWORD=%s" % F, D),
    ("  password: %s" % F, D), ("db.password=%s" % F, D),
    ('<property name="db.password" value="%s"/>' % F, 0), ("<password>%s</password>" % F, 0),
    ('<entry key="db.password">%s</entry>' % F, 0),
    ('os.environ.get("SECRET_KEY", "%s")' % F, 0), ('return System.getProperty("db.password", "%s");' % F, 0),
    ('ENV.fetch("SECRET_KEY", "%s")' % F, 0),
    ("postgres://app:%s@db:5432/app" % F, 0), ("jdbc:mysql://db/app?user=app&password=%s" % F, 0),
    ('config/settings.py:12:SECRET_KEY = "%s"' % F, 0),
    (HEAD + "\n" + BODY + TAIL, 0),
    ("APP_KEY=base64:%s" % L, 0), ("ENCRYPTION_KEY: %s" % L, D), ('FERNET_KEY = "%s"' % L, 0),
    ("SIGNING_KEY=" + "0f" * 16, 0), ("jwt.signing-key=%s" % L, D),
    # 검토에서 더한 줄
    ('app.config["SECRET_KEY"] = "%s"' % F, 0), ('os.environ["DB_PASSWORD"] = "%s"' % F, 0),
    ('$config["db_password"] = "%s";' % F, 0),
    ("SECRET_KEY=%s\r" % F, 0), ("  password: %s\r" % F, D), ('DB_PASSWORD = "%s"\r' % F, 0),
    ("SECRET_KEY=%s # 운영 값" % F, 0), ("SECRET_KEY=%s#x1" % F, 0),
    ("define('DB_PASSWORD', '%s');" % F, 0),
    ("https://h/cb?token=%s" % F, 0), ("a=1&amp;api_key=%s" % F, 0), ("x;secret=%s" % F, 0),
    ('password = b"%s"' % F, 0), ("password = r'%s'" % F, 0),
    ("config/settings.py-12-SECRET_KEY = '%s'" % F, 0),
    (".env:3:DB_PASSWORD=%s" % F, 0), ("conf/x.yml:3:  password: %s" % F, 0),
    ("ENV DB_PASSWORD=%s" % F, D), ("ARG NPM_TOKEN=%s" % F, D),
    ('os.getenv("DB_PASSWORD", "%s")' % F, 0), ('cfg.setdefault("api_key", "%s")' % F, 0),
    ('config.get("password", "%s")' % F, 0),
    ("src/app.py:DB_PASSWORD=%s" % F, 0),
    # 리뷰에서 더한 줄 — 빈 사용자 이름 주소 · `\"`가 든 값 · 비밀 낱말로 끝나는 물음 칸 이름
    ("redis://:%s@cache:6379/0" % F, 0), ("REDIS_URL=redis://:%s@cache:6379" % F, D),
    ('"password": "ab\\"%s"' % F, 0), ('"password": "%s\\"cd", "user": "u"' % F, 0),
    ("'password': 'ab\\'%s'" % F, 0), ('os.environ.get("SECRET_KEY", "ab\\"%s")' % F, 0),
    ('"password": "%s\\\\"' % F, 0), ('{"path": "C:\\\\dir\\\\", "password": "%s"}' % F, 0),
    ('"path": "C:\\dir\\", "password": "%s"' % F, 0),
    ("https://h/cb?access_token=%s" % F, 0), ("https://h/o?x=1&client_secret=%s&y=2" % F, 0),
    ("a=1&amp;client_secret=%s" % F, 0), ("https://h/s3?X-Amz-Security-Token=%s" % F, 0),
    # 다시 리뷰에서 더한 줄 — 비밀 낱말로 끝나는 물음 칸 이름 전부 · `#` 뒤 칸 · 주석으로 막아 둔 줄 · `\`로 끝나는 값
    ("https://h/x?secret_key=%s" % F, 0), ("https://h/x?private_key=%s&a=1" % F, 0),
    ("https://h/x?aws_secret_access_key=%s" % F, 0), ("https://h/x?x-api-key=%s" % F, 0),
    ("https://h/x?Api-Key=%s" % F, 0), ("https://app/cb#access_token=%s&token_type=bearer" % F, 0),
    ("# password: %s" % F, D), ("#DB_PASSWORD=%s" % F, D), ("#DB_PASSWORD=%s" % F, 0), ("#db.password=%s" % F, D),
    ("  # - POSTGRES_PASSWORD=%s" % F, D), ("conf/x.yml:3:# password: %s" % F, 0), ("## DB_PASSWORD=%s  # 옛 값" % F, D),
    ('PASSWORD="%s\\"' % F, 0), ('$password = "%s\\"; $user = "bob"' % F, 0), ("'password': '%s\\', 'u': 'x'" % F, 0),
    # 세 번째 리뷰에서 더한 줄 — 비밀 아닌 칸 뒤·안에 겹친 비밀 칸 · `(`·`[`·`{`로 시작하는 진짜 값 · `\`로 끝나는 값 뒤 구분 글자
    ("https://h/login?next=/cb?password=%s" % F, 0), ("https://h/a?redirect_uri=https://b/c?api_key=%s" % F, 0),
    ("https://h/a?x=1?password=%s" % F, 0), ("https://app/cb?state=xyz#access_token=%s" % F, 0),
    ("https://h/cb?code=1#id_token=%s" % F, 0),
    ("postgres://h/db?user=u&password=(%s" % F, 0), ("https://h/x?password=[%s" % F, 0), ("https://h/x?token={%s" % F, 0),
    ("{'password': '%s\\', 'user': 'bob'}" % F, 0),
    ("https://h/x?token={tok}%s" % F, 0), ("https://h/x?password=${t}/%s" % F, 0),
    ("SQL: WHERE password='%s\\'AND name='bob smith'" % F, 0),
    # 네 번째 리뷰에서 더한 줄 — 틀 글 뒤에 붙은 값 · 닫히지 않은 `{이름(`
    ("https://h/x?token={a}/%s" % F, 0), ("https://h/x?token={a}{b}%s" % F, 0), ("https://h/x?token={tok(%s" % F, 0),
    ("https://h/x?token={a(b)}%s" % F, 0), ("https://h/x?token={d[k]}%s" % F, 0), ("https://h/x?token=[[:alnum:]]%s" % F, 0),
    # 통합 리뷰에서 더한 줄 — diff 줄 머리(`+`·`-`·`>`·`<`) · `default=` · `:=` · `${이름}` 뒤에 붙은 값 · 따옴표 안의 `{a(b)}값`
    ("+DB_PASSWORD=%s" % F, 0), ("+  password: %s" % F, 0), ("> DB_PASSWORD=%s" % F, 0), ("< DB_PASSWORD=%s" % F, 0),
    ("-DB_PASSWORD=%s" % F, 0), ("+export API_TOKEN=%s" % F, 0), ("+\tDB_PASSWORD=%s" % F, 0), ("a.env:3:+DB_PASSWORD=%s" % F, 0),
    ('x = env("SECRET_KEY", default="%s")' % F, 0), ('SECRET_KEY = env("SECRET_KEY", default="django-insecure-%s")' % F, 0),
    ("os.environ.get(\"DB_PASSWORD\", default = '%s')" % F, 0),
    ('password := "%s"' % F, 0), ('if password := "%s"; ok {' % F, 0), ("DB_PASSWORD := %s" % F, 0), ("export DB_PASSWORD := %s" % F, 0),
    ("https://h/x?token=${%s" % F, 0), ("https://h/x?token=${a}%s" % F, 0),
    ('u = "https://h/x?token={a(b)}%s"' % F, 0),
] + [(v, 0) for v in TOK.values()] + [("token = '%s'" % TOK["ghp"], 0), ('curl -H "x: %s" h' % TOK["sk"], 0)]

# 두어야 하는 줄 — 값이 아닌 것·가리킴·본보기·이미 가린 글
KEPT = [
    ('password = ""', 0),
    ("password: ${DB_PASSWORD}", D), ('"password": "{{ vault_pw }}"', 0), ("db.password=ENC(abc)", D), ("PASSWORD=$DB_PASS", 0),
    ('"password": "Enter your password"', 0), ("password=비밀번호", D), ("login.password=\\ube44\\ubc00", D),
    ('"password": "Password"', 0), ('foo("password", "Password")', 0),
    ("password = settings.DB_PASSWORD", 0), ("password = get_password()", 0), ("api_key=abcd", 0),
    ("PWD=/home/u/app", 0), ("OLDPWD=/tmp", 0), ("token_type: bearer", D), ('password_confirmation = "%s"' % F, 0),
    ('tests/test_login.py:3:password = "%s"' % F, 0), ("password: required", D),
    ('password = "%s"' % MARK, 0),
    ('raise ValueError("password", "short")', 0), ('parser.add_argument("--password", "-p")', 0),
    ("sk" + "_live_" + "a" * 19, 0), ("pk" + "_live_" + "a1" * 12, 0), ("gl" + "pat-" + "a" * 19, 0),
    ("SORT_KEY=created_at_desc_order_2", 0), ("PRIMARY_KEY = 'id'", 0), ('cache_key = "user_profile_v2_2024"', 0),
    ("monkey: %s" % L, D),
    # 검토에서 더한 줄
    ('"name": "risk-assessment-service-backend"', 0), ("image: registry/disk-usage-monitor-service:1.2", D),
    ("cd /srv/desk-booking-application-frontend", 0), ("class risk_test_CalculationResultsV2:", 0),
    ('if pem.startswith("%s"):' % HEAD, 0), ("# 키는 %s 로 시작한다\n다음 줄\n또 다음 줄 a = 1" % HEAD, 0),
    ('target("password", "pwInput1")', 0), ('widget("token", "Btn1")', 0),
    ('const STORAGE_KEY = "myApp_UserPreferences_v1";', 0), ('LOCALE_KEY = "Menu_Settings_Title_2"', 0),
    ('export const CACHE_KEY = "AppCache_Version_2024"', 0),
    ("postgres://u:${PW}@h", 0), ('os.environ.get("SECRET_KEY", "")', 0),
    (HEAD + "\n" + MARK + "\n" + TAIL, 0), ("token: null", D), ("password: List[str]", 0),
    ("password: |", D), ("password: >-", D),
    ("tests/test_x.py-3-password = '%s'" % F, 0),
    ("password: str", 0), ("token = get_token()", 0), ('"password": request.form["password"]', 0),
    ('secret_key=os.environ["SECRET_KEY"]', 0), ("password VARCHAR(255)", 0),
    ('<input name="password" value="">', 0), ('"password": "비밀번호"', 0),
    ("conn = \"password='%s'\" % pw", 0), ('url = "jdbc:mysql://h/db?user=%s&password=%s"', 0),
    ('"token": "{token}"', 0), ('"password": "{}".format(pw)', 0), ("postgres://u:%s@h/db", 0),
    # 리뷰에서 더한 줄
    ("https://h/list?max_tokens=100&page=2", 0), ("http://:8080/app", 0), ('"label": "a\\"b"', 0),
    ("if (a&&b.token==c) {", 0), ("x=1;this.token=b.token;", 0), ('re.compile(r"\\d+\\.\\d+")', 0),
    ("https://h/cb?token=%s&x=1", 0),
    # 다시 리뷰에서 더한 줄 — `\'`가 든 라벨은 반만 가리지 않는다 · 코드의 `==`·정규식·끼워 넣는 글 · 주석의 글
    ("password: 'Can\\'t be blank',", 0), ('"password": "x\\"y z\\""', 0), ("'password': 'don\\'t tell'", 0),
    ("os.environ.get('password', 'Can\\'t be blank')", 0),
    ("if (ok&&token==c) {", 0), ('re.compile(r"\\?access_token=([^&]+)")', 0), ('f"{b}?access_token={tok!r}"', 0),
    ("https://h/x?token_type=bearer&max_tokens=5", 0), ("https://h/doc#password", 0), ("#include <token.h>", 0),
    ("# token: see docs", D), ("# password: required", D), ("## password", D), ("# set the password=<your password>", D),
    # 세 번째 리뷰에서 더한 줄 — 셸의 `${이름#글=}` · 끼워 넣는 글 뒤 백틱 · 정규식·틀 글
    ('PASS="${1#--password=}"', 0), ("tok=${line#TOKEN=}", 0), ('v="${arg#--api-key=}"', 0),
    ("location.hash = `#access_token=${tok}`", 0), ("fetch(`https://h/?token=${t}`)", 0),
    ('re.compile(r"\\?token=(?P<tok>[^&]+)")', 0), ('"?token={}".format(t)', 0), ("https://h/x?token={{ token }}", 0),
    # 네 번째 리뷰에서 더한 줄 — 끼워 넣는 식(f-string) · 이어진 `{이름}` · POSIX 글자 묶음
    ('f"https://api.h/v1/x?api_key={os.environ[\'API_KEY\']}"', 0), ('requests.get(f"{BASE}/q?token={cfg[\'token\']}&q={q}")', 0),
    ('f"?access_token={creds.get(\'token\')}"', 0), ('f"?password={quote(pw, safe=\'\')}"', 0),
    ('f"?token={tok or \'\'}"', 0), ('f"?token={tok:>10}"', 0),
    ('u = "https://h/x?token={a}{b}"', 0), ('u = "https://h/x?token={a}/{b}"', 0), ('u = "https://h/x?token={a}-{b}"', 0),
    ('grep -E "\\?token=[[:alnum:]]+" f', 0), ('grep -E "[?&]api_key=[[:alnum:]_-]{8,}" f', 0),
    # 통합 리뷰에서 더한 줄 — diff 머리 뒤의 평범한 줄 · `default=`의 비밀 아닌 이름 · `:=` 코드 줄 · `${…}` 틀 글 · XML 속도 상한(200자)
    ("+x=1", 0), ("+++ b/.env", 0), ("--- a/.env", 0), ("> quoted text with password: hunter2x", 0), ("<<<<<<< HEAD", 0),
    ('t.get("x", default="y")', 0), ('env("SECRET_KEY", default=None)', 0),
    ("x := 5", 0), ('a := "b"', 0), ("password := cfg.Password", 0), ("token := strings.TrimSpace(x)", 0), ("SECRET_KEY := ", 0),
    ("password:=", 0),
    ("const u = `${base}?token=${obj['t']}`;", 0), ("url: https://h/x?token=${{ secrets.X }}", 0), ("u=`https://h/x?token=${t}`", 0),
    ("https://h/x?token=${f(a, b)}", 0), ("https://h/x?token=${a}/${b}", 0),
    ('<property name="db.password" ' + "x" * 260 + ' value="%s"/>' % F, 0),
]

# 못 가리는 것 — 가림 0을 단정한다. 꼬리표마다 README "못 가리는 것:" 아래에 같은 글자가 있다
MASK_GAPS = [
    ("비밀 낱말로 끝나지 않는", [('DB_PASS = "%s"' % F, 0)]),
    ("여러 줄", [('password = (\n    "%s"\n)' % F, 0)]),
    ("base64", [('DB_PASSWORD = base64.b64decode("enpG")', 0)]),
    ("4000자", [("x" * 4001 + ' password = "%s"' % F, 0)]),
    ("목록에 없는 토큰 꼴", [("SG." + "a" * 22 + "." + "b" * 43, 0)]),
    ("get류가 아닌 함수", [('settings.value("db.password", "%s")' % F, 0)]),
    ("명령 줄·덤프에 적힌 값", [
        ("export A=1 DB_PASSWORD=%s B=2" % F, 0), ("PGPASSWORD=%s psql -h db" % F, 0),
        ("docker run -e DB_PASSWORD=%s img" % F, 0), ("curl -u admin:%s https://h" % F, 0),
        ("mysql -u root -p%s" % F, 0), ("tool --password=%s" % F, 0), ("Authorization: Bearer %s" % F, 0),
        ('      "DB_PASSWORD=%s",' % F, 0),
        ("set DB_PASSWORD=%s" % F, 0), ("DB_PASSWORD ?= %s" % F, 0), ("DB_PASSWORD += %s" % F, 0),
    ]),
    ("띄어쓰기나 한글이 든 값", [('DB_PASSWORD = "my %s pw"' % F, 0)]),
    ("이름이나 비밀 낱말과 같은 값", [("POSTGRES_PASSWORD=secret", D)]),
    ("값이 이름보다 앞선 XML", [('<property value="%s" name="db.password"/>' % F, 0)]),
    ("글 속에 한 번 더 감싼 JSON", [('"{\\"password\\": \\"%s\\"}"' % F, 0)]),
    ("틀 글로 보이는 주소 칸", [
        ("https://h/x?token={{%s" % F, 0), ("https://h/x?token=[x]%s" % F, 0), ("https://h/x?password={%s}" % F, 0),
        ("https://h/x?token=$%s" % F, 0), ("https://h/x?token=${{%s" % F, 0),
        ("https://h/x?user[password]=%s" % F, 0), ("https://h/x?user.password=%s" % F, 0),
    ]),
    ("세미콜론 뒤 주소 칸", [("https://h/x;client_secret=%s" % F, 0), ("https://h/x;access_token=%s" % F, 0)]),
    ("퍼센트로 감싼 주소", [("https://h/a?next=https%3A%2F%2Fh%2Fb%3Fapi_key%3D" + F, 0)]),
    ("타입을 적은 선언", [('password: str = "%s"' % F, 0), ('const password: string = "%s";' % F, 0)]),
    ("백틱으로 감싼 값", [("const token = `%s`;" % F, 0)]),
]
# 도구 입력으로 보는 것 (꼬리표, 도구, 입력, 결과 글)
MASK_GAPS_TOOLS = [
    ("시험 파일", "Read", {"file_path": "/p/tests/test_db.py"}, 'password = "%s"' % F),
    ("글 속에 한 번 더 감싼 JSON", "REPL", {"code": "x"}, json.dumps({"tests": "ok\nDB_PASSWORD=%s\n" % F})),
]
# 돌려서 다시 만들 수 없는 것 — README에 적혀 있는지만 본다
MASK_GAPS_TEXT = ["0이 아닌 값으로 끝난 명령", "결과를 바꿔 찍는 명령"]
# 잘못 가리는 것 — 가림 >= 1을 단정한다. 꼬리표마다 README "잘못 가리는 것:" 줄에 같은 글자가 있다
MASK_OVER = [
    ("본보기 값", [("SECRET_KEY=changeme123", D)]),
    ("입력칸의 값", [('<input type="hidden" name="password" value="dummy1">', 0), ('<input type="text" name="password" value="dummy1">', 0)]),
    ("공개 키", [("PUBLIC_KEY=%s" % L, 0)]),
    ("꺼내는 호출의 둘째 글", [
        ('t.get("password", "label2")', 0), ('form.get_field("password", "text2")', 0),
        ('t.get("password", default="label2")', 0),
    ]),
    ("주소 속 넘김 토큰", [("https://h/list?next_page_token=CAEQAA", 0), ("https://h/f?csrf_token=abc123", 0)]),
    ("숫자 설정값", [("MAX_TOKEN = 4096", 0), ("ERRORTOKEN = 60", 0)]),
    ("주소 뒤 닫는 괄호", [("[go](https://h/p#token=abc123)", 0)]),
    ("Go 코드 줄", [("token := 5", 0), ("token := <-ch", 0)]),
]

# 결과 꼴까지 본다 — 가린 뒤 줄이 깨지지 않아야 한다(세 번째 리뷰). (줄, 설정 파일에서 읽은 줄인가, 기대 결과)
EXACT = [
    ("'password': '%s\\', 'u': 'x'" % F, 0, "'password': '%s', 'u': 'x'" % MARK),
    ("{'password': '%s\\', 'user': 'bob'}" % F, 0, "{'password': '%s', 'user': 'bob'}" % MARK),
    ('PASSWORD="%s\\"' % F, 0, 'PASSWORD="%s"' % MARK),
    ('$password = "%s\\"; $user = "bob"' % F, 0, '$password = "%s"; $user = "bob"' % MARK),
    ("https://h/login?next=/cb?password=%s" % F, 0, "https://h/login?next=/cb?password=" + MARK),
    ("https://app/cb?state=xyz#access_token=%s&token_type=bearer" % F, 0,
     "https://app/cb?state=xyz#access_token=%s&token_type=bearer" % MARK),
    ("postgres://h/db?user=u&password=(%s" % F, 0, "postgres://h/db?user=u&password=" + MARK),
    ("https://h/x?a=%s&password=%s&b=2" % (F, F), 0, "https://h/x?a=%s&password=%s&b=2" % (F, MARK)),
    ("SQL: WHERE password='%s\\'AND name='bob smith'" % F, 0, "SQL: WHERE password='%s'AND name='bob smith'" % MARK),
    # 앞 칸을 두고 뒤 칸만 가려도, 한 번 더 가렸을 때 앞 칸이 달라지지 않는다
    ("x;password=${t}?pwd=%s}" % F, 0, "x;password=${t}?pwd=" + MARK),
    ("https://h/x?token={x?password=%s}" % F, 0, "https://h/x?token=" + MARK),
    ("fetch(`https://h/?token=${t}&api_key=%s`)" % F, 0, "fetch(`https://h/?token=${t}&api_key=%s`)" % MARK),
    # 끼워 넣는 식은 두고 그 뒤 칸만 가린다 · 식이 다음 칸 머리 앞에서 닫히지 않으면 가린다(네 번째 리뷰)
    ('f"{B}/q?token={cfg[\'token\']}&password=%s"' % F, 0, 'f"{B}/q?token={cfg[\'token\']}&password=%s"' % MARK),
    ("https://h/x?token={tok or ?password=%s}" % F, 0, "https://h/x?token=%s or ?password=%s" % (MARK, MARK)),
    ("https://h/x?token={tok(%s;a=}" % F, 0, "https://h/x?token=%s;a=}" % MARK),
    ("https://h/x?token=[[:alnum:]?password=%s]+" % F, 0, "https://h/x?token=" + MARK),
    ("x?password=[[:a:]?password=[[:a:]?password=[[:a:]", 0, "x?password=" + MARK),
    # 통합 리뷰에서 더한 줄
    ("+DB_PASSWORD=%s" % F, 0, "+DB_PASSWORD=" + MARK), ("+  password: %s  # c" % F, 0, "+  password: %s  # c" % MARK),
    ("password:=%s" % F, 0, "password:=" + MARK), ("DB_PASSWORD := %s" % F, 0, "DB_PASSWORD := " + MARK),
    ('x = env("SECRET_KEY", default="%s")' % F, 0, 'x = env("SECRET_KEY", default="%s")' % MARK),
    ('if password := "%s"; ok {' % F, 0, 'if password := "%s"; ok {' % MARK),
    ("[go](https://h/p#token=%s)" % F, 0, "[go](https://h/p#token=" + MARK),
]

# (도구, 입력, cwd) → (이름으로 찾는 가림을 할 것인가, 설정 파일만 읽었는가)
KF = [
    (("Read", {"file_path": "/p/tests/test_db.py"}, "/p"), (False, False)),
    (("Read", {"file_path": "/p/tests/../config/settings.py"}, "/p"), (True, False)),
    (("Read", {"file_path": "/home/u/test/app/config/settings.py"}, "/home/u/test/app"), (True, False)),
    (("Read", {"file_path": "/home/u/test/app/config/settings.py"}, ""), (True, False)),
    (("Read", {"file_path": "/p/src/latest.py"}, "/p"), (True, False)),
    (("Read", {"file_path": "/p/conf/contest.yml"}, "/p"), (True, True)),
    (("Read", {"file_path": "/p/.env"}, "/p"), (True, True)),
    (("Grep", {"path": "tests/"}, "/p"), (False, False)),
    (("Grep", {"path": "tests"}, "/p"), (False, False)),
    (("Grep", {}, "/p"), (True, False)),
    (("Edit", {"file_path": "/p/tests/test_db.py"}, "/p"), (False, False)),
    (("Write", {"file_path": "/p/src/UserServiceTest.java"}, "/p"), (False, False)),
    (("Edit", {"file_path": "/p/app/settings.py"}, "/p"), (True, False)),
    (("Bash", {"command": "cat tests/test_a.py; cat $(ls conf)"}, "/p"), (True, False)),
    (("Bash", {"command": "cat app/settings.py"}, "/p"), (True, False)),
    (("NotebookEdit", {"notebook_path": "/p/a.ipynb"}, "/p"), (True, False)),
    (("Bash", 5, "/p"), (True, False)),
    # 리뷰에서 더한 줄 — 명령은 시험 파일만 읽어도 이름으로 찾는 가림을 끄지 않는다
    (("Bash", {"command": "cat tests/test_a.py"}, "/p"), (True, False)),
    (("Bash", {"command": "cat tests/conftest.py .env"}, "/p"), (True, False)),
    (("Bash", {"command": "pytest tests/test_db.py -x; printenv"}, "/p"), (True, False)),
    (("Bash", {"command": "docker compose -f tests/docker-compose.yml config"}, "/p"), (True, True)),
    # 새 실행 방식(REPL) — 명령처럼 다룬다: 이름 가림은 끄지 않고, 코드 글의 파일 이름이 다 설정 파일이면 설정 꼴로 본다
    (("REPL", {"code": "await $`cat config/app.yml`.text()"}, "/p"), (True, True)),
    (("REPL", {"code": "await $`cat tests/test_a.py`.text()"}, "/p"), (True, False)),
    (("REPL", {"code": "x"}, "/p"), (True, False)),
    (("REPL", 5, "/p"), (True, False)),
]

# 느려지는 입력 — 각각 8줄(30 KB 안팎)
SLOW = [
    "a" * 3999 + "=", "a." * 1999 + ":", "a://" + "b" * 3990 + ":", "<" + "a" * 3990 + ">", 'name="a"' * 499,
    'password="' + "x" * 3980, " " * 3990 + "x y=", "\t" * 3995 + "=", " " * 3995 + "<", " " * 3995 + "(",
    '("a", ' * 660, HEAD + ("A" * 60 + "\n") * 60, '"' * 3999 + "=", "=" * 3999, "-" * 3990 + "BEGIN", "a:" * 1999,
    "get(" * 990 + '"password", "',
    # 리뷰에서 더한 줄
    "&" + "a" * 3990, "&" + "token" * 790, "?&" * 1990, "&amp;" * 790, ("&" + "a" * 60 + "=") * 60,
    "\\" * 3990, 'password="' + "\\x" * 1980, 'password="' + '\\"' * 1980, '"a\\' * 1300, '("a", "\\' * 500,
    "a://:" + "b" * 3980, "a://" + ":" * 3980, 'n="\\' * 990,
    "#" * 3990, "# " * 1990, "#:" * 1990, "?" + "a" * 3990, ("#" + "a" * 60 + "=") * 60,
    "?a" * 1990, "password='a\\'b " * 260, 'p="\\"x' * 650, "get('password', 'a\\'b " * 170,
    # 세 번째 리뷰에서 더한 줄
    "?a=" * 1330, "#a=" * 1330, "?next=" * 660, "?password=" * 390, "?password=(" * 360, "'password': 'a\\', " * 190,
    "?password=한" * 360, "?password=a" * 350 + "\\u12ab", "?password=${" * 320 + "}", "?password={" * 360,
    "?password=[" * 360, "?password=a" * 360,
    # 네 번째 리뷰에서 더한 줄
    "?password={a " * 300 + "}", "?password=" + "{a}" * 1300 + "Z", "?password={a[" * 300, "?password={a:>" * 280,
    "?password={a " + "b" * 3900, "?password=[[:" * 300, "?password=[[:a:]" * 240, "?password={a(}" * 280,
    "?password={a b}" * 260 + "Z",
    # 통합 리뷰에서 더한 줄
    "+" + " " * 3990 + "x y=", "+" + "a" * 3990 + "=", ":=" * 1990, "a :=" * 990, "password:=" * 390,
    '("a", default=' * 280, 'get("password", default = ' * 150, "default=" * 490,
    "?password=${{" * 300, "?password=${a(" * 280, "?password=${a " * 280 + "}", "?password=" + "${a}" * 990 + "Z",
    "?password=$" * 360,
    ('name="a" ' + "x" * 250) * 15, 'key="a" ' * 499,
]

BAD = [b"", b"not json", b"[]", b"{}", b'{"tool_name":"Bash"}', b'{"tool_name":"Bash","tool_input":{"command":5}}',
       b'{"tool_name":"Read","tool_input":{"file_path":null}}', b"\xff\xfe\x00{", b'{"tool_response": 5}']

SECTION = "## 비밀값 파일 한 번 더 거르기"


def run(raw, home, cwd):
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    return subprocess.run([sys.executable, str(SCRIPT)], input=data, cwd=str(cwd),
                          env={"PATH": os.environ["PATH"], "HOME": str(home)}, capture_output=True, timeout=30)


def payload(tool, tool_input, resp, cwd):
    return json.dumps({"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": tool_input,
                       "tool_response": resp, "cwd": str(cwd)})


def snap(d):
    d = Path(d)
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts}


def section():
    lines = README.read_text(encoding="utf-8").splitlines()
    assert SECTION in lines
    start = lines.index(SECTION)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def _read(content):
    return ("Read", {"file_path": "/p/a.py"},
            {"type": "text", "file": {"filePath": "/p/a.py", "content": content, "numLines": 2, "startLine": 1, "totalLines": 2}})


def _bash(stdout):
    return ("Bash", {"command": "cat app/settings.py"},
            {"stdout": stdout, "stderr": "", "interrupted": False, "isImage": False, "noOutputExpected": False,
             "staleReadFileStateHint": "Note: file a.py was modified"})


def _grep(content, count_key):
    return ("Grep", {"pattern": "x", "path": "/p"},
            {"mode": "content", "numFiles": 1, "filenames": ["a.py"], "content": content, count_key: 1})


def _edit(original):
    return ("Edit", {"file_path": "/p/a.py", "old_string": "A = 1", "new_string": "B = 2"},
            {"filePath": "/p/a.py", "oldString": "A = 1", "newString": "B = 2", "originalFile": original,
             "structuredPatch": [{"oldStart": 1, "oldLines": 2, "newStart": 1, "newLines": 2,
                                  "lines": ["-A = 1", "+B = 2", ' DB_PASSWORD = "%s"' % F if F in original else " C = 3"]}],
             "userModified": False, "replaceAll": False, "contentNotInModelContext": False})


WITH_VALUE = [  # (도구 꼴, 가린 개수)
    (_read('import os\nDB_PASSWORD = "%s"\n' % F), 1),
    (_bash('DB_PASSWORD = "%s"\nPORT = 8080\n' % F), 1),
    (_grep('a.py:1:DB_PASSWORD = "%s"' % F, "numLines"), 1),
    (_grep('a.py:1:DB_PASSWORD = "%s"' % F, "numMatches"), 1),
    (_edit('A = 1\nDB_PASSWORD = "%s"\n' % F), 2),
]
WITHOUT_VALUE = [
    _read("import os\nPORT = 8080\n"), _bash("PORT = 8080\n"), _grep("a.py:1:PORT = 8080", "numLines"),
    _grep("a.py:1:PORT = 8080", "numMatches"), _edit("A = 1\nC = 3\n"),
    ("Write", {"file_path": "/p/a.py", "content": "A = 1\n"}, {"filePath": "/p/a.py", "type": "create"}),
]

CODE = "await $`cat app/settings.py`.text()"
PIC = {"type": "base64", "media_type": "image/png", "data": TOK["aiza"]}


def _repl(drop=(), **kw):
    """새 실행 방식(REPL)의 결과 꼴 — 문서의 열쇠(code·result·stdout·stderr·toolsUsed)에 kw를 덮고 drop의 열쇠를 뺀다."""
    resp = {"code": CODE, "result": None, "stdout": "", "stderr": "", "toolsUsed": ["Bash"]}
    resp.update(kw)
    for k in drop:
        del resp[k]
    return ("REPL", {"code": resp["code"]}, resp)


REPL_WITH_VALUE = [  # (꼴, 가린 개수)
    (_repl(result='DB_PASSWORD = "%s"\nPORT = 8080\n' % F), 1),
    (_repl(stdout='DB_PASSWORD = "%s"\n' % F), 1),
    (_repl(stderr="Error: postgres://app:%s@db/app" % F), 1),
    (_repl(error='Error: password="%s"' % F), 1),                # 코드가 실패했을 때만 오는 error
    (_repl(drop=("result",), stdout='DB_PASSWORD = "%s"\n' % F), 1),  # result가 없다
    (_repl(code='const password = "%s"; password' % F, result="ok"), 1),  # 코드 글에 값이 글자로 들었다
    (_repl(result={"out": "SECRET_KEY=%s" % F}), 1),            # 글이 아닌 result — 꼴은 그대로, 안의 글만
]
REPL_WITHOUT_VALUE = [
    _repl(result="ok"), _repl(), _repl(drop=("result",), stdout="PORT=1\n"), _repl(result=5),
    _repl(result="ok", images=[{"type": "image", "source": dict(PIC)}]),
    _repl(result="ok", documents=[{"type": "document", "source": dict(PIC, media_type="application/pdf")}]),
]


def _walk(old, new, changed, path=()):
    """같은 꼴(열쇠 차례·타입)로 되돌렸는지 보며, 값이 달라진 글 칸의 자리를 모은다."""
    assert type(old) is type(new), path
    if isinstance(old, dict):
        assert list(old) == list(new), path
        for k in old:
            _walk(old[k], new[k], changed, path + (k,))
    elif isinstance(old, list):
        assert len(old) == len(new), path
        for i, (a, b) in enumerate(zip(old, new)):
            _walk(a, b, changed, path + (i,))
    elif old != new:
        assert isinstance(old, str), path
        changed.append(path)


def _lines(rows):
    return [(line, data) for _, ls in rows for line, data in ls]


@pytest.mark.parametrize("line,data", MASKED, ids=[str(i) for i in range(len(MASKED))])
def test_masked(line, data):
    out, n = M.mask_text(line, True, bool(data))
    assert n >= 1
    assert MARK in out
    assert F not in out.replace(MARK, "") and not any(t in out for t in TOK.values())
    assert out.count("\n") == line.count("\n")
    assert M.mask_text(out, True, bool(data)) == (out, 0)       # 한 번 더 넣어도 같은 글


@pytest.mark.parametrize("line,data", KEPT, ids=[str(i) for i in range(len(KEPT))])
def test_kept(line, data):
    assert M.mask_text(line, True, bool(data)) == (line, 0)


@pytest.mark.parametrize("line,data,want", EXACT, ids=[str(i) for i in range(len(EXACT))])
def test_exact(line, data, want):
    assert M.mask_text(line, True, bool(data))[0] == want
    assert M.mask_text(want, True, bool(data))[0] == want       # 그 결과를 한 번 더 가려도 같은 글


@pytest.mark.parametrize("args,want", KF, ids=[str(i) for i in range(len(KF))])
def test_keyed_for(args, want):
    assert M.keyed_for(*args) == want


@pytest.mark.parametrize("line", SLOW, ids=[str(i) for i in range(len(SLOW))])
def test_not_slow(line):
    text = "\n".join([line] * 8)
    start = time.perf_counter()
    M.mask_text(text, True, True)
    assert time.perf_counter() - start < 1


def test_not_slow_indent():
    text = "\n".join([" " * 2000 + "x y z"] * 60)
    start = time.perf_counter()
    M.mask_text(text, True, True)
    assert time.perf_counter() - start < 1


@pytest.mark.parametrize("shape,n", WITH_VALUE, ids=["read", "bash", "grep-numLines", "grep-numMatches", "edit"])
def test_shape_kept(tmp_path, shape, n):
    tool, tool_input, resp = shape
    assert F in json.dumps(resp)
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b""
    text = r.stdout.decode("ascii")
    assert text.endswith("\n") and text.count("\n") == 1
    out = json.loads(text)
    assert list(out) == ["hookSpecificOutput"]
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    assert list(hso) == ["hookEventName", "updatedToolOutput", "additionalContext"]
    changed = []
    _walk(resp, hso["updatedToolOutput"], changed)
    assert changed                                             # 바뀐 칸은 글 칸뿐이고 하나 이상이다
    assert F not in json.dumps(hso["updatedToolOutput"])
    assert hso["additionalContext"] == M.NOTE % (n, MARK)


@pytest.mark.parametrize("shape", WITHOUT_VALUE, ids=["read", "bash", "grep-numLines", "grep-numMatches", "edit", "write"])
def test_nothing_to_mask_silent(tmp_path, shape):
    tool, tool_input, resp = shape
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


@pytest.mark.parametrize("tool,tool_input,resp", [
    ("Read", {"file_path": "/p/a.png"}, {"type": "image", "file": {"base64": TOK["aiza"]}}),
    ("Bash", {"command": "cat a.png"}, {"stdout": TOK["aiza"], "stderr": "", "interrupted": False, "isImage": True,
                                         "noOutputExpected": False}),
    ("Bash", {"command": "echo x"}, {"stdout": "data:image/png;base64," + TOK["aiza"], "stderr": ""}),
], ids=["base64-key", "bash-isImage", "data-image"])
def test_image_untouched(tmp_path, tool, tool_input, resp):
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


@pytest.mark.parametrize("tool", ["NotebookEdit", "MultiEdit"])
def test_unknown_tool(tmp_path, tool):
    r = run(payload(tool, {"notebook_path": "/p/a.ipynb"}, {"new_source": "PORT = 8080"}, tmp_path), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    resp = {"new_source": 'DB_PASSWORD = "%s"' % F, "cell_id": "c1"}
    r = run(payload(tool, {"notebook_path": "/p/a.ipynb"}, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b""
    hso = json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]
    assert list(hso["updatedToolOutput"]) == ["new_source", "cell_id"] and F not in json.dumps(hso)
    assert hso["updatedToolOutput"]["cell_id"] == "c1" and hso["additionalContext"] == M.NOTE % (1, MARK)


@pytest.mark.parametrize("as_dir", [False, True], ids=["file", "dir"])
def test_off_marker(tmp_path, as_dir):
    home = tmp_path / "home"
    home.mkdir()
    marker = home / M.MARKER
    if as_dir:
        marker.mkdir()
    else:
        marker.write_bytes(b"")
    tool, tool_input, resp = WITH_VALUE[0][0]
    r = run(payload(tool, tool_input, resp, tmp_path), home, tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


@pytest.mark.parametrize("raw", BAD, ids=[str(i) for i in range(len(BAD))])
def test_bad_input_quiet(tmp_path, raw):
    r = run(raw, tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_crash_is_visible(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(M, "mask_any", boom)
    tool, tool_input, resp = WITH_VALUE[0][0]
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload(tool, tool_input, resp, tmp_path).encode())))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert M.main() == 1
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err.endswith("\n") and cap.err.count("\n") == 1
    assert cap.err.isascii() and cap.err.startswith("devkit mask: ")
    assert F not in cap.err and "DB_PASSWORD" not in cap.err


def test_test_files_skipped(tmp_path):
    cwd = str(tmp_path)
    body = 'password = "%s"\n' % F
    for path in (cwd + "/tests/test_db.py",):
        r = run(payload("Read", {"file_path": path}, {"type": "text", "file": {"filePath": path, "content": body}}, cwd),
                tmp_path / "home", tmp_path)
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    # 시험 파일이어도 토큰 꼴은 가린다
    path = cwd + "/tests/test_db.py"
    resp = {"type": "text", "file": {"filePath": path, "content": body + "key = '%s'\n" % TOK["ghp"]}}
    r = run(payload("Read", {"file_path": path}, resp, cwd), tmp_path / "home", tmp_path)
    assert r.returncode == 0
    hso = json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]
    content = hso["updatedToolOutput"]["file"]["content"]
    assert TOK["ghp"] not in content and MARK in content and F in content
    # `..`로 시험 폴더를 지나 나온 길은 시험 파일이 아니다
    for path in ("tests/../config/settings.py", cwd + "/tests/../config/settings.py"):
        r = run(payload("Read", {"file_path": path}, {"type": "text", "file": {"filePath": path, "content": body}}, cwd),
                tmp_path / "home", tmp_path)
        assert r.returncode == 0 and r.stderr == b""
        content = json.loads(r.stdout.decode("ascii"))["hookSpecificOutput"]["updatedToolOutput"]["file"]["content"]
        assert F not in content and MARK in content


def test_bash_output_not_skipped():
    # 명령(Bash)은 시험 파일만 읽어도 이름으로 찾는 가림을 끄지 않는다
    for cmd in ("cat tests/conftest.py .env", "pytest tests/test_db.py -x; printenv", "cat tests/test_a.py"):
        keyed, data = M.keyed_for("Bash", {"command": cmd}, "/p")
        new, n = M.mask_any({"stdout": "DB_PASSWORD=%s\n" % F, "stderr": ""}, keyed, data, "/p")
        assert n == 1 and F not in json.dumps(new), cmd
    # 검색 결과 줄은 앞에 시험 파일 이름이 붙은 줄만 건너뛴다
    keyed, data = M.keyed_for("Bash", {"command": "grep -rn password ."}, "/p")
    text = 'tests/test_x.py:3:password = "%s"\napp/s.py:3:password = "%s"' % (F, F)
    new, n = M.mask_any(text, keyed, data, "/p")
    assert n == 1 and new.count(F) == 1 and new.startswith('tests/test_x.py:3:password = "%s"' % F), new


def test_answer_is_ascii(tmp_path):
    tool, tool_input, resp = WITH_VALUE[0][0]
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.stdout and all(b < 0x80 for b in r.stdout)


def test_creates_nothing(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("PORT=1\n", encoding="utf-8")
    before = (snap(tmp_path), snap(KIT))
    for shape, _ in WITH_VALUE:
        tool, tool_input, resp = shape
        run(payload(tool, tool_input, resp, proj), tmp_path / "home", proj)
    for tool, tool_input, resp in WITHOUT_VALUE:
        run(payload(tool, tool_input, resp, proj), tmp_path / "home", proj)
    assert (snap(tmp_path), snap(KIT)) == before


def test_imports_only_stdlib():
    found = set()
    for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
    assert found <= {"json", "os", "posixpath", "re", "sys"}


def test_mask_is_python38():
    src = SCRIPT.read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 8))
    for pat in PY39:
        assert not re.search(pat, src, re.M), pat


def test_note_rules():
    assert M.NOTE.startswith("devkit: ") and "\n" not in M.NOTE
    assert "막아 준다" not in M.NOTE and "devkit-guard-off" not in M.NOTE and "AI에게" not in M.NOTE


@pytest.mark.parametrize("tag,line,data", [(t, l, d) for t, rows in MASK_GAPS for l, d in rows],
                         ids=[str(i) for i in range(len(_lines(MASK_GAPS)))])
def test_mask_gaps(tag, line, data):
    assert M.mask_text(line, True, bool(data)) == (line, 0)


@pytest.mark.parametrize("tag,tool,tool_input,text", MASK_GAPS_TOOLS, ids=[t for t, _, _, _ in MASK_GAPS_TOOLS])
def test_mask_gaps_tools(tag, tool, tool_input, text):
    keyed, data = M.keyed_for(tool, tool_input, "/p")
    assert M.mask_any(text, keyed, data, "/p") == (text, 0)


@pytest.mark.parametrize("tag,line,data", [(t, l, d) for t, rows in MASK_OVER for l, d in rows],
                         ids=[str(i) for i in range(len(_lines(MASK_OVER)))])
def test_overmask(tag, line, data):
    assert M.mask_text(line, True, bool(data))[1] >= 1


def test_mask_gaps_in_readme():
    lines = section()
    start = next(i for i, x in enumerate(lines) if "**못 가리는 것:**" in x)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("- ")), len(lines))
    block = "\n".join(lines[start:end])
    for tag in [t for t, _ in MASK_GAPS] + [t for t, _, _, _ in MASK_GAPS_TOOLS] + MASK_GAPS_TEXT:
        assert "`%s`" % tag in block, tag


def test_overmask_in_readme():
    line = next(x for x in section() if "**잘못 가리는 것:**" in x)
    for tag in {t for t, _ in MASK_OVER}:
        assert "`%s`" % tag in line, tag


def test_readme_mask():
    lines = section()
    sec = "\n".join(lines)
    for s in ("`%s`" % MARK, "파일에는 진짜 값이 그대로", "원래 결과가 그대로 간다", "Codex", "성공한 호출의 결과만"):
        assert s in sec, s
    for label in ("**가린다:**", "**못 가리는 것:**", "**잘못 가리는 것:**", "**거절한다:**"):
        assert sum(label in x for x in lines) == 1, label
    text = README.read_text(encoding="utf-8")
    for bad in ("다 가린다", "모두 가린다", "막아 준다"):
        assert bad not in text, bad


def _imports(path):
    found = set()
    for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
    return found


def test_mark_same_as_guard():
    spec = importlib.util.spec_from_file_location("devkit_guard_for_mask", KIT / "scripts/guard.py")
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    assert M.MARK == G.MARK == "<devkit이 가린 값>"
    assert M.MARKER == G.MARKER
    assert "guard" not in _imports(SCRIPT) and "mask" not in _imports(KIT / "scripts/guard.py")


def _hook_command():
    data = json.loads((KIT / "hooks/hooks.json").read_text(encoding="utf-8"))
    return data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]


def _hook_run(root, tmp_path, tool, tool_input, resp):
    stdin = payload(tool, tool_input, resp, tmp_path)
    return subprocess.run(["sh", "-c", _hook_command()], input=stdin.encode("utf-8"), cwd=str(tmp_path),
                          env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "CLAUDE_PLUGIN_ROOT": str(root)},
                          capture_output=True, timeout=30)


def test_hook_command_from_hooks_json(tmp_path):
    (tmp_path / "empty").mkdir()
    tool, tool_input, resp = WITH_VALUE[0][0]
    r = _hook_run(KIT, tmp_path, tool, tool_input, resp)
    assert r.returncode == 0 and r.stderr == b""
    hso = json.loads(r.stdout)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse" and F not in json.dumps(hso["updatedToolOutput"])
    tool, tool_input, resp = WITHOUT_VALUE[0]
    r = _hook_run(KIT, tmp_path, tool, tool_input, resp)
    assert (r.returncode, r.stdout) == (0, b"")
    tool, tool_input, resp = WITH_VALUE[0][0]
    r = _hook_run(tmp_path / "empty", tmp_path, tool, tool_input, resp)
    assert r.returncode == 1 and r.stdout == b""
    for name in ("runpy.py", "json.py"):
        (tmp_path / name).write_text('import os; os.write(1, b"PLANTED"); os._exit(7)\n', encoding="utf-8")
    r = _hook_run(KIT, tmp_path, tool, tool_input, resp)
    assert r.returncode == 0 and b"PLANTED" not in r.stdout
    assert F not in json.dumps(json.loads(r.stdout)["hookSpecificOutput"]["updatedToolOutput"])


@pytest.mark.parametrize("shape,n", REPL_WITH_VALUE,
                         ids=["result", "stdout", "stderr", "error", "no-result", "code", "dict-result"])
def test_repl_shape_kept(tmp_path, shape, n):
    tool, tool_input, resp = shape
    assert F in json.dumps(resp)
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b""
    text = r.stdout.decode("ascii")
    assert text.endswith("\n") and text.count("\n") == 1
    out = json.loads(text)
    assert list(out) == ["hookSpecificOutput"]
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    assert list(hso) == ["hookEventName", "updatedToolOutput", "additionalContext"]
    new = hso["updatedToolOutput"]
    changed = []
    _walk(resp, new, changed)
    assert changed
    assert F not in json.dumps(new)
    assert hso["additionalContext"] == M.NOTE % (n, MARK)
    for k in ("code", "stdout", "stderr"):
        assert isinstance(new[k], str), k
    if "error" in resp:
        assert isinstance(new["error"], str)
    else:
        assert "error" not in new
    assert new["toolsUsed"] == resp["toolsUsed"]
    assert ("result" in new) == ("result" in resp)


@pytest.mark.parametrize("shape", REPL_WITHOUT_VALUE, ids=["ok", "null", "no-result", "number", "images", "documents"])
def test_repl_silent(tmp_path, shape):
    tool, tool_input, resp = shape
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_repl_images_untouched(tmp_path):
    tool, tool_input, resp = _repl(result='DB_PASSWORD = "%s"' % F, images=[{"type": "image", "source": dict(PIC)}],
                                   documents=[{"type": "document", "source": dict(PIC)}])
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b"" and r.stdout
    hso = json.loads(r.stdout)["hookSpecificOutput"]
    new = hso["updatedToolOutput"]
    assert new["images"] == resp["images"] and new["documents"] == resp["documents"]
    assert MARK in new["result"] and F not in new["result"]
    assert hso["additionalContext"] == M.NOTE % (1, MARK)


def test_repl_data_file(tmp_path):
    code = "await $`cat config/app.yml`.text()"
    resp = {"code": code, "result": "signing_key: %s\nport: 1" % L, "stdout": "", "stderr": "", "toolsUsed": ["Bash"]}
    r = run(payload("REPL", {"code": code}, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b""
    assert json.loads(r.stdout)["hookSpecificOutput"]["updatedToolOutput"]["result"] == "signing_key: " + MARK + "\nport: 1"


def test_hook_command_repl(tmp_path):
    tool, tool_input, resp = REPL_WITH_VALUE[0][0]
    r = _hook_run(KIT, tmp_path, tool, tool_input, resp)
    assert r.returncode == 0 and r.stderr == b""
    hso = json.loads(r.stdout)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse" and F not in json.dumps(hso["updatedToolOutput"])
    tool, tool_input, resp = REPL_WITHOUT_VALUE[0]
    r = _hook_run(KIT, tmp_path, tool, tool_input, resp)
    assert (r.returncode, r.stdout) == (0, b"")


def test_other_tool_images_masked(tmp_path):
    resp = {"stdout": "", "stderr": "", "images": ['DB_PASSWORD="%s"' % F]}
    r = run(payload("Bash", {"command": "cat a"}, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b"" and r.stdout
    hso = json.loads(r.stdout)["hookSpecificOutput"]
    assert F not in json.dumps(hso["updatedToolOutput"])
    assert hso["additionalContext"] == M.NOTE % (1, MARK)
    assert M.mask_any({"images": [{"type": "base64", "data": 'DB_PASSWORD="%s"' % F}]})[1] == 1   # REPL이 아니면 data도 가린다
    resp = {"stdout": "", "stderr": "", "images": [{"type": "base64", "data": 'DB_PASSWORD="%s"' % F}]}
    r = run(payload("Bash", {"command": "cat a"}, resp, tmp_path), tmp_path / "home", tmp_path)   # 훅을 지나도 같다
    assert r.returncode == 0 and r.stdout and F not in r.stdout.decode()


@pytest.mark.parametrize("extra", [
    {"documents": [{"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "DB_PASSWORD=%s" % F}}]},
    {"documents": [{"type": "document", "title": 'password="%s"' % F, "source": dict(PIC, media_type="application/pdf")}]},
    {"images": [{"type": "image", "source": {"type": "url", "url": "https://u:%s@h/x.png" % F}}]},
    {"images": [{"type": "image", "source": dict(PIC, note='password="%s"' % F)}]},
    {"result": {"type": "base64", "data": 'DB_PASSWORD="%s"' % F}},
    {"result": {"files": [{"type": "base64", "data": "SECRET_KEY=%s" % F, "name": "x"}]}},
    {"result": {"images": [{"type": "base64", "data": 'DB_PASSWORD="%s"' % F}]}},
    {"images": {"type": "base64", "data": 'DB_PASSWORD="%s"' % F}},
    {"result": [{"type": "base64", "data": 'DB_PASSWORD="%s"' % F}]},
    {"images": [{"type": "base64", "data": 'DB_PASSWORD="%s"' % F}]},
], ids=["doc-text", "doc-title", "image-url", "b64-sibling", "result-b64", "result-b64-deep",
        "nested-images", "images-not-list", "result-list", "plain-in-data"])
def test_repl_attached_text_masked(tmp_path, extra):
    tool, tool_input, resp = _repl(**dict({"result": "ok"}, **extra))
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert r.returncode == 0 and r.stderr == b"" and r.stdout
    hso = json.loads(r.stdout)["hookSpecificOutput"]
    assert F not in json.dumps(hso["updatedToolOutput"])
    assert hso["additionalContext"] == M.NOTE % (1, MARK)


def test_repl_json_result_gap(tmp_path):
    tool, tool_input, resp = _repl(result=json.dumps({"tests": "ok\nDB_PASSWORD=%s\n" % F}))
    r = run(payload(tool, tool_input, resp, tmp_path), tmp_path / "home", tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_readme_code_mode():
    lines = section()
    hits = [x for x in lines if "Code Mode" in x]
    assert len(hits) == 1
    line = hits[0]
    for s in ("실제 세션으로는 확인하지 못했다", "가짜 값", "`@` 없이", "쓰지 않는다", "묶어 돌려준", "다 꺼진다"):
        assert s in line, s
    assert MARK not in line
    start = next(i for i, x in enumerate(lines) if "**못 가리는 것:**" in x)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("- ")), len(lines))
    assert line in lines[start:end]
    assert sum("Code Mode" in x for x in README.read_text(encoding="utf-8").splitlines()) == 1
