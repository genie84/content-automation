"""RSS 수집 → 재가공 → HTML 조립 → 워드프레스 발행까지 소스별로 순회 실행하고,
이어서 하루 1회 주제 자동선정 트랙을 실행한다."""
from config.sources import SOURCES
from scripts.gemini_reprocessor import get_client, resolve_flash_model, reprocess_content, reprocess_topic
from scripts.html_assembler import assemble_html
from scripts.kakao_notifier import send_kakao_notification
from scripts.rss_collector import collect_new_videos, load_seen_videos, save_seen_videos
from scripts.topic_researcher import (
    facts_to_source_text,
    mark_topic_track_ran_today,
    record_topic_history,
    research_and_select_topic,
    should_run_topic_track_today,
    verify_facts,
)
from scripts.wordpress_publisher import publish_post, resolve_tag_ids


def run_video_track(client, model_name):
    seen_videos = load_seen_videos()

    for source in SOURCES:
        seen_ids = set(seen_videos.get(source["id"], []))
        new_videos = collect_new_videos(source, seen_ids)
        print(f"[{source['name']}] 신규 영상 {len(new_videos)}건")

        for video in new_videos:
            try:
                content = reprocess_content(video, source, model_name, client)
                content_html, has_infographic = assemble_html(content, video)
                tag_ids = resolve_tag_ids(content.tags)
                result = publish_post(
                    content.title,
                    content_html,
                    status="draft",
                    excerpt=content.meta_description,
                    slug=content.slug,
                    tags=tag_ids,
                )
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


def run_topic_track(client, model_name):
    if not should_run_topic_track_today():
        print("[주제선정] 오늘 이미 실행함 — 건너뜀")
        return

    try:
        category, candidate = research_and_select_topic(client, model_name)
        print(f"[주제선정] {category['label']} - {candidate.topic} (점수 {candidate.score})")

        facts = verify_facts(candidate, category, client, model_name)
        source_text = facts_to_source_text(facts)
        content = reprocess_topic(candidate.topic, category["label"], source_text, model_name, client)

        video = {"video_id": content.slug or "topic"}
        content_html, has_infographic = assemble_html(content, video)
        tag_ids = resolve_tag_ids(content.tags)
        result = publish_post(
            content.title,
            content_html,
            status="draft",
            categories=[category["wp_category_id"]],
            excerpt=content.meta_description,
            slug=content.slug,
            tags=tag_ids,
        )
        print(f"  - 발행됨(draft, 주제선정): {content.title} → {result['link']}")

        try:
            send_kakao_notification(content.title, result["link"], has_infographic)
        except Exception as e:
            print(f"  - 카카오 알림 실패(발행은 정상): {type(e).__name__}: {e}")

        record_topic_history(candidate.topic, category["id"])
        mark_topic_track_ran_today()
    except Exception as e:
        print(f"  - 주제선정 트랙 실패: {type(e).__name__}: {e}")


def run():
    client = get_client()
    model_name = resolve_flash_model(client)
    print(f"사용 모델: {model_name}")

    run_video_track(client, model_name)
    run_topic_track(client, model_name)


if __name__ == "__main__":
    run()
