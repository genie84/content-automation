"""RSS 수집 → 재가공 → HTML 조립 → 워드프레스 발행까지 소스별로 순회 실행한다(영상
트랙, `python main.py`). 주제 자동선정 트랙(`python main.py --topics`)은 완전히 별도
GitHub Actions 스케줄(09:00 KST)로 실행되며 여기서는 호출하지 않는다 — 예전에는 영상
트랙 실행 안에서 하루 1회만 끼워 돌렸는데, 2026-09-09부터 독립 스케줄로 분리됨."""
import sys

from config.sources import SOURCES
from scripts.gemini_reprocessor import (
    get_client,
    resolve_flash_model,
    reprocess_content,
    reprocess_content_naver,
    reprocess_topic,
    reprocess_topic_naver,
)
from scripts.html_assembler import assemble_html
from scripts.kakao_notifier import send_kakao_notification
from scripts.naver_publisher import queue_naver_draft
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


def _queue_naver_version(naver_content, topic: str, category_label: str, image_bytes: bytes | None) -> None:
    """지니(워드프레스) 발행 뒤에 같은 소스로 서현이 아빠(네이버) 버전을 만들어 로컬
    발행 대기 큐에 넣는다. 네이버 자체 발행은 여전히 로컬 수동 실행(원칙 유지).
    image_bytes는 지니용으로 이미 만든 16:9 인포그래픽을 그대로 재사용한 것 —
    채널별로 따로 만들면 이미지 생성 비용이 2배가 돼서, 2026-09-10에 지니용 한 장만
    만들고 네이버에도 재사용하기로 확정함(네이버용 2:1 별도 규격은 이번엔 적용 안 함,
    에디터가 알아서 리사이징하는 건 감수하기로 함)."""
    queue_naver_draft(
        title=naver_content.title,
        summary_lines=naver_content.summary_lines,
        table_rows=[r.model_dump() for r in naver_content.table_rows],
        body_html=naver_content.body_html,
        topic=topic,
        category_label=category_label,
        image_bytes=image_bytes,
    )
    print(f"  - 네이버용(서현이 아빠) 버전 큐에 저장됨: {naver_content.title}")


def run_video_track(client, model_name):
    seen_videos = load_seen_videos()

    for source in SOURCES:
        seen_ids = set(seen_videos.get(source["id"], []))
        new_videos = collect_new_videos(source, seen_ids)
        print(f"[{source['name']}] 신규 영상 {len(new_videos)}건")

        for video in new_videos:
            try:
                content = reprocess_content(video, source, model_name, client)
                content_html, has_infographic, featured_media_id, infographic_bytes = assemble_html(content, video)
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

                try:
                    naver_content = reprocess_content_naver(video, source, model_name, client)
                    _queue_naver_version(
                        naver_content, topic=video["title"], category_label=source["name"], image_bytes=infographic_bytes
                    )
                except Exception as e:
                    print(f"  - 네이버용 버전 생성 실패(워드프레스 발행은 정상): {type(e).__name__}: {e}")

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
    content_html, has_infographic, featured_media_id, infographic_bytes = assemble_html(content, video)
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

    try:
        # source_text 재사용 — verify_facts(그라운딩, 유료)를 또 호출하지 않는다.
        naver_content = reprocess_topic_naver(candidate.topic, category["label"], source_text, model_name, client)
        _queue_naver_version(
            naver_content, topic=candidate.topic, category_label=category["label"], image_bytes=infographic_bytes
        )
    except Exception as e:
        print(f"  - 네이버용 버전 생성 실패(워드프레스 발행은 정상): {type(e).__name__}: {e}")

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
