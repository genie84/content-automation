"""생성한 이미지를 워드프레스(카페24 디스크) 대신 공개 GitHub 저장소에 올리고 jsDelivr 주소를 돌려준다.

워드프레스 디스크가 1.4GB로 고정이라 이미지가 쌓이면 가득 찬다(2026-09-18 실제 발생 — 업로드가
실패하자 글에서도 네이버 모음글에서도 이미지가 사라졌다). 이미지 원본은 이미지 전용 공개 저장소에
커밋하고, 글에는 커밋 SHA로 고정한 jsDelivr 주소만 넣는다. SHA로 고정한 주소는 내용이 영원히 안 바뀌어서
CDN 캐시 지연/오염 문제가 없다(브랜치 주소는 CDN에 최대 12시간 캐시됨).

메인 저장소(content-automation)는 비공개라 jsDelivr가 서빙할 수 없고, 공개로 돌리면 프롬프트·큐·서버
주소까지 노출되므로 별도 저장소(IMAGE_HOST_REPO)를 쓴다. IMAGE_HOST_TOKEN(그 저장소에 Contents 쓰기
권한만 있는 토큰)이 없으면 is_configured()가 False라서 호출하는 쪽이 기존 워드프레스 업로드로 폴백한다.
"""
import base64
import os
import random
import time
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
DEFAULT_REPO = "genie84/lampgenie-images"
GITHUB_API = "https://api.github.com"
MAX_ATTEMPTS = 5


def _repo() -> str:
    return (os.environ.get("IMAGE_HOST_REPO") or DEFAULT_REPO).strip()


def _token() -> str:
    return os.environ.get("IMAGE_HOST_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(_token())


def _wait_until_served(url: str) -> None:
    """방금 커밋한 파일을 CDN이 실제로 내주는지 한 번 요청해 본다(첫 요청이 CDN을 데우기도
    한다). 끝내 200이 안 와도 예외는 던지지 않는다 — 커밋은 이미 끝났고 주소는 곧 살아난다."""
    for _ in range(6):
        try:
            response = requests.get(url, timeout=20, stream=True)
            ok = response.status_code == 200
            response.close()
            if ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    print(f"  - jsDelivr 반영을 확인하지 못했습니다(커밋은 완료, 잠시 후 열릴 수 있음): {url}")


def upload_image(data: bytes, filename: str) -> str:
    """이미지를 images/YYYY-MM/filename 으로 커밋하고 SHA 고정 jsDelivr 주소를 반환한다.
    실패하면 예외를 던진다(호출하는 쪽이 워드프레스 업로드로 폴백)."""
    repo = _repo()
    path = f"images/{datetime.now(KST).strftime('%Y-%m')}/{filename}"
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {"message": f"image: {filename}", "content": base64.b64encode(data).decode("ascii")}

    last_status = None
    for attempt in range(MAX_ATTEMPTS):
        response = requests.put(f"{GITHUB_API}/repos/{repo}/contents/{path}", headers=headers, json=body, timeout=60)
        if response.status_code in (200, 201):
            sha = response.json()["commit"]["sha"]
            url = f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}"
            _wait_until_served(url)
            return url
        last_status = response.status_code
        # 409/422: 다른 워크플로우가 같은 시각에 커밋해 브랜치 끝이 바뀐 경우, 5xx: 일시 오류 — 재시도.
        if response.status_code in (409, 422) or response.status_code >= 500:
            time.sleep(1.5 * (attempt + 1) + random.random())
            continue
        response.raise_for_status()
    raise RuntimeError(f"이미지 저장소 커밋 실패(마지막 응답 {last_status}): {repo}/{path}")
