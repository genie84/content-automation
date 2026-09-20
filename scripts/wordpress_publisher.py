"""재가공된 콘텐츠를 워드프레스 REST API로 발행한다."""
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

WP_BASE_URL = "https://lampgenie.co.kr"
DEFAULT_CATEGORY_IDS = [10]  # "경제 브리핑" (slug: briefing)


def _post_payload(
    title: str,
    content_html: str,
    status: str,
    categories: list[int] = None,
    excerpt: str = None,
    slug: str = None,
    tags: list[int] = None,
    featured_media: int = None,
) -> dict:
    payload = {
        "title": title,
        "content": content_html,
        "status": status,
        "categories": categories if categories is not None else DEFAULT_CATEGORY_IDS,
    }
    if excerpt is not None:
        payload["excerpt"] = excerpt
    if slug is not None:
        payload["slug"] = slug
    if tags is not None:
        payload["tags"] = tags
    if featured_media is not None:
        payload["featured_media"] = featured_media
    return payload


def publish_post(
    title: str,
    content_html: str,
    status: str = "draft",
    categories: list[int] = None,
    excerpt: str = None,
    slug: str = None,
    tags: list[int] = None,
    featured_media: int = None,
) -> dict:
    response = requests.post(
        f"{WP_BASE_URL}/wp-json/wp/v2/posts",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        json=_post_payload(title, content_html, status, categories, excerpt, slug, tags, featured_media),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def update_post(
    post_id: int,
    title: str,
    content_html: str,
    status: str = "draft",
    categories: list[int] = None,
    excerpt: str = None,
    slug: str = None,
    tags: list[int] = None,
    featured_media: int = None,
) -> dict:
    response = requests.post(
        f"{WP_BASE_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        json=_post_payload(title, content_html, status, categories, excerpt, slug, tags, featured_media),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_or_create_tag_id(name: str) -> int:
    auth = (os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"])
    search = requests.get(
        f"{WP_BASE_URL}/wp-json/wp/v2/tags", auth=auth, params={"search": name, "per_page": 100}, timeout=15
    )
    search.raise_for_status()
    for tag in search.json():
        if tag["name"] == name:
            return tag["id"]

    create = requests.post(f"{WP_BASE_URL}/wp-json/wp/v2/tags", auth=auth, json={"name": name}, timeout=15)
    if create.status_code == 400:
        # 동시 실행 등으로 그 사이 이미 생성된 경우 — WP가 term_exists 에러에 기존 id를 함께 준다.
        existing_id = create.json().get("data", {}).get("term_id")
        if existing_id:
            return existing_id
    create.raise_for_status()
    return create.json()["id"]


def resolve_tag_ids(tag_names: list[str]) -> list[int]:
    """태그 이름 목록을 워드프레스 태그 ID로 변환한다(없으면 새로 생성).

    태그 하나가 실패해도 나머지는 계속 처리하고, 실패한 태그만 건너뛴다.
    """
    ids = []
    for name in tag_names:
        try:
            ids.append(get_or_create_tag_id(name))
        except Exception as e:
            print(f"  - 태그 처리 실패({name}, 건너뜀): {type(e).__name__}: {e}")
    return ids


def upload_media(image_bytes: bytes, filename: str, content_type: str = "image/png") -> dict:
    response = requests.post(
        f"{WP_BASE_URL}/wp-json/wp/v2/media",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
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
