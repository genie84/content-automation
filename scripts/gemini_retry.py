"""Gemini API 호출 재시도 로직.

5xx(ServerError — 504 DEADLINE_EXCEEDED, 503 UNAVAILABLE 등 일시적 서버 오류)만
재시도한다. 4xx(ClientError — 429 쿼터 초과, 404 등)는 재시도해도 똑같은 결과가
나올 뿐이므로 바로 실패시킨다.
"""
import time

from google.genai.errors import ServerError

RETRY_DELAYS_SEC = [5, 15, 30]


def call_with_retry(fn, *args, **kwargs):
    last_error = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS_SEC):
        if delay:
            print(
                f"  - 서버 일시 오류, {delay}초 후 재시도 "
                f"({attempt}/{len(RETRY_DELAYS_SEC)}차): {type(last_error).__name__}: {last_error}",
                flush=True,  # 출력 버퍼링 때문에 GitHub Actions 로그에 실시간으로 안 찍히는 걸 방지
            )
            time.sleep(delay)
        try:
            return fn(*args, **kwargs)
        except ServerError as e:
            last_error = e
            continue
    raise last_error
