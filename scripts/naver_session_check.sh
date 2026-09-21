#!/bin/bash
# 서버 크론용: 네이버 세션이 살아 있는지 확인해서 ~/naver_session.log에 한 줄 남긴다(수명 측정 + 쿠키 갱신).
# 큐 처리/로그인 실행과 겹치지 않게 같은 락을 쓰고, 다른 실행 중이면 조용히 건너뛴다.
cd "$(dirname "$0")/.." || exit 1
exec 9>/tmp/naver_runner.lock
flock -n 9 || exit 0
export DISPLAY=:99
if ! pgrep -f "Xvfb :99" > /dev/null; then
    nohup Xvfb :99 -screen 0 1280x900x24 > /tmp/xvfb.log 2>&1 9>&- &
    disown
    sleep 2
fi
source venv/bin/activate
echo "[$(date '+%m-%d %H:%M')] $(python3 -m scripts.naver_publisher --check-session 2>&1 | tail -1)" >> /home/ubuntu/naver_session.log
