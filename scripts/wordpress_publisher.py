"""재가공된 콘텐츠를 워드프레스 REST API로 발행한다."""
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

WP_BASE_URL = "https://lampgenie.co.kr"
DEFAULT_CATEGORY_IDS = [10]  # "경제 브리핑" (slug: briefing)


def publish_post(title: str, content_html: str, status: str = "draft", categories: list[int] = None) -> dict:
    response = requests.post(
        f"{WP_BASE_URL}/wp-json/wp/v2/posts",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        json={
            "title": title,
            "content": content_html,
            "status": status,
            "categories": categories if categories is not None else DEFAULT_CATEGORY_IDS,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def update_post(post_id: int, title: str, content_html: str, status: str = "draft", categories: list[int] = None) -> dict:
    response = requests.post(
        f"{WP_BASE_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        json={
            "title": title,
            "content": content_html,
            "status": status,
            "categories": categories if categories is not None else DEFAULT_CATEGORY_IDS,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def upload_media(image_bytes: bytes, filename: str) -> dict:
    response = requests.post(
        f"{WP_BASE_URL}/wp-json/wp/v2/media",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/png",
        },
        data=image_bytes,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main():
    result = publish_post(
        "[테스트] 워드프레스 연동 확인",
        "<p>이 글은 status=draft로 생성되어 실제 방문자에게는 보이지 않습니다.</p>",
        status="draft",
    )
    print(f"post id: {result['id']}")
    print(f"status: {result['status']}")
    print(f"link: {result['link']}")


if __name__ == "__main__":
    main()
