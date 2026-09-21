#!/bin/bash
# x11vnc -afteraccept 훅 — 폰이 접속(비밀번호 인증 완료)할 때마다 호출된다.
# 큐 상태나 시각과 상관없이, 접속하면 네이버 로그인 화면이 뜨게 한다(2026-09-21: 큐가 비어 있는 아침에
# 접속하면 로그인 창이 안 떠서 빈 화면만 보이던 문제). 이미 떠 있으면 아무것도 안 한다.
# 브라우저가 뜨기까지 20~30초 걸리므로, 그동안 빈 검은 화면 대신 안내 화면(xterm — xmessage는 한글이 깨짐)을 보여준다.
LOCK=/tmp/naver_ondemand.lock
APP=/home/ubuntu/content-automation
LOG="$APP/data/standby_login.log"

exec 9>"$LOCK"
flock -n 9 || exit 0

# 이미 대기 로그인이 떠 있으면(사람이 로그인 중이거나 화면이 열려 있음) 그대로 둔다.
if pgrep -f "[n]aver_publisher --standby-login" > /dev/null; then
    exit 0
fi

# 락 fd(9)를 오래 사는 자식이 물려받지 않도록 9>&- 로 닫는다.
(DISPLAY=:98 setsid xterm -geometry 40x30+0+0 -fa "Noto Sans CJK KR" -fs 16 -bg "#03C75A" -fg white \
    -e "echo; echo '  네이버 로그인 화면 연결 중...'; echo; echo '  20~30초만 기다려주세요.'; sleep 45" \
    > /dev/null 2>&1 < /dev/null 9>&- &)

cd "$APP" || exit 0
(
    source venv/bin/activate
    export DISPLAY=:99   # login_and_explore가 폰 전용 화면(:98)으로 바꿔서 띄운다
    setsid nohup python3 -u -m scripts.naver_publisher --standby-login >> "$LOG" 2>&1 < /dev/null 9>&- &
)
exit 0
