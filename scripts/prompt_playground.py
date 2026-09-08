"""config/prompts.py를 반복 튜닝하기 위한 테스트 실행기.

seen_videos.json은 건드리지 않고, 매번 최신 영상을 다시 재가공해서
같은 테스트 draft 포스트 하나를 덮어쓴다(새 draft가 쌓이지 않음).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.sources import SOURCES
from scripts.gemini_reprocessor import get_client, reprocess_content, resolve_flash_model
from scripts.html_assembler import assemble_html
from scripts.rss_collector import fetch_feed
from scripts.wordpress_publisher import publish_post, update_post

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PLAYGROUND_ID_PATH = os.path.join(DATA_DIR, "playground_post_id.txt")


def get_saved_post_id() -> int | None:
    if not os.path.exists(PLAYGROUND_ID_PATH):
        return None
    with open(PLAYGROUND_ID_PATH, "r", encoding="utf-8") as f:
        text = f.read().strip()
    return int(text) if text else None


def save_post_id(post_id: int) -> None:
    with open(PLAYGROUND_ID_PATH, "w", encoding="utf-8") as f:
        f.write(str(post_id))


def main():
    source = SOURCES[0]
    video = fetch_feed(source["rss_url"])[0]
    print(f"[{source['name']}] {video['title']} ({video['video_id']})")

    client = get_client()
    model_name = resolve_flash_model(client)
    content = reprocess_content(video, source, model_name, client)
    content_html, _has_infographic, _featured_media_id = assemble_html(content, video)

    post_id = get_saved_post_id()
    if post_id:
        try:
            result = update_post(post_id, f"[플레이그라운드] {content.title}", content_html, status="draft")
            print(f"업데이트됨: {result['link']}")
        except Exception as e:
            # 캐시된 post_id가 삭제 등으로 더 이상 유효하지 않으면 새로 만든다.
            print(f"기존 테스트 draft(post {post_id}) 접근 실패({type(e).__name__}), 새로 생성합니다: {e}")
            result = publish_post(f"[플레이그라운드] {content.title}", content_html, status="draft")
            save_post_id(result["id"])
            print(f"새로 생성됨: {result['link']}")
    else:
        result = publish_post(f"[플레이그라운드] {content.title}", content_html, status="draft")
        save_post_id(result["id"])
        print(f"새로 생성됨: {result['link']}")

    print(f"\n제목: {content.title}")
    print(f"요약: {content.summary_lines}")
    print(f"표 행 수: {len(content.table_rows)}")
    print(f"본문 길이: {len(content.body_html)}자")
    print(content.body_html[:800])


if __name__ == "__main__":
    main()
