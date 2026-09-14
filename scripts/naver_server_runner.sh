#!/bin/bash
# Oracle Cloud 서버에서 cron으로 주기 실행되는 래퍼.
# 네이버 발행 큐(data/naver_queue/)는 git으로 로컬 PC/클라우드(GitHub Actions)와
# 이 서버 사이를 오가므로, 처리 전에 최신 큐를 받고 처리 후 변경사항(처리된 항목 삭제)을
# 다시 올려서 동기화를 유지한다. 실패해도(git 충돌 등) 다음 cron 실행 때 재시도된다.
set -uo pipefail

cd "$(dirname "$0")/.."
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S %Z')]"

echo "$LOG_PREFIX 큐 동기화 시작"
if ! git pull --rebase origin main; then
    echo "$LOG_PREFIX git pull 실패 — rebase 되돌리고 이번 실행은 건너뜀"
    git rebase --abort 2>/dev/null || true
    exit 1
fi

source venv/bin/activate
python3 scripts/naver_publisher.py

git add -u data/naver_queue/
if ! git diff --cached --quiet; then
    git commit -m "$(cat <<'EOF'
chore: 네이버 발행 큐 처리 (서버 자동실행)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
    git push origin main
    echo "$LOG_PREFIX 처리된 항목 커밋/푸시 완료"
else
    echo "$LOG_PREFIX 처리할 변경사항 없음 — 커밋 생략"
fi
echo "$LOG_PREFIX 완료"
