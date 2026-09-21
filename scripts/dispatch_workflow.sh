#!/bin/bash
# GitHub 예약 실행이 최대 4시간씩 늦어지는 문제(2026-09-19~)를 피하려고, 서버 크론이 정시에 워크플로우를 직접
# 시작시킨다(workflow_dispatch). 서버에 저장된 GitHub 인증 정보(git credential store)를 쓰며 값은 출력하지 않는다.
# 이 토큰에 Actions "Read and write" 권한이 있어야 한다(없으면 HTTP 403). 예약 실행은 백업으로 그대로 둔다.
WF="${1:-}"
[ -n "$WF" ] || { echo "사용법: $0 워크플로우파일.yml"; exit 1; }
cd /home/ubuntu/content-automation || exit 1
TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p')
[ -n "$TOKEN" ] || { echo "$(date '+%F %T') $WF 실패: 저장된 GitHub 인증 정보 없음"; exit 1; }
code=$(curl -s -m 30 -o /dev/null -w "%{http_code}" -X POST \
    -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/genie84/content-automation/actions/workflows/$WF/dispatches" -d '{"ref":"main"}')
echo "$(date '+%F %T') $WF -> HTTP $code (204=시작됨, 403=권한 없음)"
