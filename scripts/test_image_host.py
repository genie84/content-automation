"""이미지 저장소(GitHub + jsDelivr) 연결 시험 — 작은 시험 이미지 1장을 올리고 실제로 열리는지 확인한다.

GitHub Actions의 'Test Image Host' 워크플로우(수동 실행)에서 돈다. Gemini 등 유료 API는 쓰지 않는다.
성공하면 종료코드 0, 실패하면 1(워크플로우가 빨간 X로 표시됨).
"""
import io
import sys
import time

import requests
from PIL import Image, ImageDraw

from scripts import image_host


def main() -> int:
    if not image_host.is_configured():
        print("실패: IMAGE_HOST_TOKEN 시크릿이 비어 있습니다(저장소 Settings > Secrets > Actions 확인).")
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    im = Image.new("RGB", (480, 270), (19, 42, 70))
    ImageDraw.Draw(im).text((24, 120), f"lampgenie image host test {stamp}", fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=85)

    try:
        url = image_host.upload_image(buf.getvalue(), f"test-{stamp}.webp")
    except Exception as e:
        print(f"실패: 이미지 저장소 업로드 오류 — {type(e).__name__}: {e}")
        return 1
    print(f"업로드 완료: {url}")

    response = requests.get(url, timeout=30)
    content_type = response.headers.get("content-type", "")
    print(f"jsDelivr 응답: HTTP {response.status_code}, {content_type}, {len(response.content)}바이트")
    if response.status_code != 200 or not content_type.startswith("image/"):
        print("실패: jsDelivr가 이미지를 내주지 않습니다.")
        return 1
    print("성공: 업로드와 jsDelivr 서빙 모두 정상입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
