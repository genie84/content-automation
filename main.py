"""RSS 수집 → 재가공 → HTML 조립 → 워드프레스 발행까지 소스별로 순회 실행한다."""
from config.sources import SOURCES
from scripts.gemini_reprocessor import get_client, resolve_flash_model, reprocess_content
from scripts.html_assembler import assemble_html
from scripts.kakao_notifier import send_kakao_notification
from scripts.rss_collector import collect_new_videos, load_seen_videos, save_seen_videos
from scripts.wordpress_publisher import publish_post


def run():
    seen_videos = load_seen_videos()
    client = get_client()
    model_name = resolve_flash_model(client)
    print(f"사용 모델: {model_name}")

    for source in SOURCES:
        seen_ids = set(seen_videos.get(source["id"], []))
        new_videos = collect_new_videos(source, seen_ids)
        print(f"[{source['name']}] 신규 영상 {len(new_videos)}건")

        for video in new_videos:
            try:
                content = reprocess_content(video, source, model_name, client)
                content_html, has_infographic = assemble_html(content, video)
                result = publish_post(content.title, content_html, status="draft")
                print(f"  - 발행됨(draft): {content.title} → {result['link']}")

                try:
                    send_kakao_notification(content.title, result["link"], has_infographic)
                except Exception as e:
                    print(f"  - 카카오 알림 실패(발행은 정상): {type(e).__name__}: {e}")

                seen_ids.add(video["video_id"])
                seen_videos[source["id"]] = sorted(seen_ids)
                save_seen_videos(seen_videos)
            except Exception as e:
                print(f"  - 실패: {video['title']} ({video['video_id']}) — {type(e).__name__}: {e}")
                continue


if __name__ == "__main__":
    run()
