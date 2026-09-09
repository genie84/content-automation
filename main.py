"""RSS 수집 → 재가공 → HTML 조립 → 워드프레스 발행까지 소스별로 순회 실행한다(영상
트랙, `python main.py`). 주제 자동선정 트랙(`python main.py --topics`)은 완전히 별도
GitHub Actions 스케줄(09:00 KST)로 실행되며 여기서는 호출하지 않는다 — 예전에는 영상
트랙 실행 안에서 하루 1회만 끼워 돌렸는데, 2026-09-09부터 독립 스케줄로 분리됨."""
import sys

from config.sources import SOURCES
from scripts.gemini_reprocessor import get_client, resolve_flash_model, reprocess_content, reprocess_topic
from scripts.html_assembler import assemble_html
from scripts.kakao_notifier import send_kakao_notification
from scripts.rss_collector import collect_new_videos, load_seen_videos, save_seen_videos
from scripts.topic_researcher import (
    facts_to_source_text,
    mark_topic_track_ran_today,
    record_topic_history,
    research_all_categories,
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
                content_html, has_infographic, featured_media_id = assemble_html(content, video)
                tag_ids = resolve_tag_ids(content.tags)
                result = publish_post(
                    content.title,
                    content_html,
                    status="draft",
                    excerpt=content.meta_description,
                    slug=content.slug,
                    tags=tag_ids,
                    featured_media=featured_media_id,
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


def _publish_topic_post(category: dict, candidate, client, model_name: str) -> None:
    """리서치된 주제 후보 1개를 사실관계 확인 → 재가공 → 발행까지 처리한다.
    카테고리 4개를 각각 독립적으로 처리하므로, 하나가 실패해도 나머지에 영향 없도록
    호출하는 쪽(run_topic_track)에서 개별적으로 감싼다."""
    facts = verify_facts(candidate, category, client, model_name)
    source_text = facts_to_source_text(facts)
    content = reprocess_topic(candidate.topic, category["label"], source_text, model_name, client)

    video = {"video_id": content.slug or "topic"}
    content_html, has_infographic, featured_media_id = assemble_html(content, video)
    tag_ids = resolve_tag_ids(content.tags)
    result = publish_post(
        content.title,
        content_html,
        status="draft",
        categories=[category["wp_category_id"]],
        excerpt=content.meta_description,
        slug=content.slug,
        tags=tag_ids,
        featured_media=featured_media_id,
    )
    print(f"  - 발행됨(draft, 주제선정/{category['label']}): {content.title} → {result['link']}")

    try:
        send_kakao_notification(content.title, result["link"], has_infographic)
    except Exception as e:
        print(f"  - 카카오 알림 실패(발행은 정상): {type(e).__name__}: {e}")

    record_topic_history(candidate.topic, category["id"])


def run_topic_track(client, model_name):
    """카테고리 4개(주식/부동산/생활경제/경제상식)를 전부 리서치해서 각각 별도 글로
    발행한다(2026-09-09부터 — 예전에는 점수 최고 1개만 쓰고 나머지는 버렸음). 하루 1회만
    실행되도록 게이팅(영상 트랙과 별개로 독립 스케줄에서 호출됨, main.py의
    `--topics` 옵션 참고)."""
    if not should_run_topic_track_today():
        print("[주제선정] 오늘 이미 실행함 — 건너뜀")
        return

    candidates = research_all_categories(client, model_name)
    if not candidates:
        print("[주제선정] 모든 카테고리에서 리서치 실패 또는 전부 중복 — 오늘은 발행 없음")
        return

    for category, candidate in candidates:
        print(f"[주제선정] {category['label']} - {candidate.topic} (점수 {candidate.score})")
        try:
            _publish_topic_post(category, candidate, client, model_name)
        except Exception as e:
            print(f"  - '{category['label']}' 발행 실패: {type(e).__name__}: {e}")
            continue

    mark_topic_track_ran_today()


def run():
    client = get_client()
    model_name = resolve_flash_model(client)
    print(f"사용 모델: {model_name}")
    run_video_track(client, model_name)


def run_topics_only():
    client = get_client()
    model_name = resolve_flash_model(client)
    print(f"사용 모델: {model_name}")
    run_topic_track(client, model_name)


if __name__ == "__main__":
    if "--topics" in sys.argv:
        run_topics_only()
    else:
        run()
