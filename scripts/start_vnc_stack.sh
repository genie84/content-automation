#!/bin/bash
# 폰 접속용 화면 스택을 (없으면) 띄운다 — 서버 재부팅 후 자동 시작(@reboot)과 수동 재시작에 쓴다.
#   가상 화면 :98(420x900, 폰 전용) → x11vnc(:98, 로컬 5901, 접속 시 로그인 화면 훅) → websockify(외부 6080 → 5901)
# 이미 떠 있는 건 건드리지 않는다. --restart-vnc 를 주면 x11vnc만 새 옵션으로 다시 띄운다.
# (큐 처리용 :99 화면은 naver_server_runner.sh가 필요할 때 띄운다.)
APP=/home/ubuntu/content-automation

if ! pgrep -f "[X]vfb :98" > /dev/null; then
    nohup Xvfb :98 -screen 0 420x900x24 > /tmp/xvfb98.log 2>&1 < /dev/null &
    sleep 2
fi

if [ "${1:-}" = "--restart-vnc" ]; then
    pkill -f "[x]11vnc -display :98"
    sleep 1
fi

if ! pgrep -f "[x]11vnc -display :98" > /dev/null; then
    nohup x11vnc -display :98 -rfbauth /home/ubuntu/.vncpasswd -listen localhost -xkb -forever -rfbport 5901 \
        -afteraccept "$APP/scripts/on_vnc_connect.sh" >> /tmp/x11vnc98.log 2>&1 < /dev/null &
fi

if ! pgrep -f "[w]ebsockify --web=/usr/share/novnc/ 6080" > /dev/null; then
    nohup websockify --web=/usr/share/novnc/ 6080 localhost:5901 >> /tmp/websockify.log 2>&1 < /dev/null &
fi
