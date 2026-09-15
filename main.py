"""RSS 수집 → 재가공 → HTML 조립 → 워드프레스 발행까지 소스별로 순회 실행한다(영상
트랙, `python main.py`). 주제 자동선정 트랙(`python main.py --topics`)은 완전히 별도
GitHub Actions 스케줄(09:00 KST)로 실행되며 여기서는 호출하지 않는다 — 예전에는 영상
트랙 실행 안에서 하루 1회만 끼워 돌렸는데, 2026-09-09부터 독립 스케줄로 분리됨.

2026-09-15부터 네이버-램프지니 크로스 프로모션(B안) 추가: 지니(워드프레스) 글이
이제 draft가 아니라 자동 공개(publish)되므로(방문자가 바로 볼 수 있음), 그 링크를
모아 서현이 아빠 블로그에서 "모음글" 형태로 소개한다 — 개별 글마다 외부 링크를
반복 삽입하면 광고성/저품질 판정 리스크가 있어서, 모음글 안에서만 링크를 건다.
- 콘텐츠 B(카테고리 모음): 카테고리 자동선정 트랙(09:00 KST) 실행 끝에 바로 이어서
  생성 — 이미 만들어진 서현이 아빠 버전 본문을 재활용하므로 추가 Gemini 호출 없음.
- 콘텐츠 A(삼프로 모음): 영상 트랙이 하루 여러 번(07:45~19:00 KST) 돌면서 쌓아둔
  기록(data/today_video_posts.json)을, 마지막 영상 트랙 실행 이후인 19:20 KST
  별도 GitHub Actions 스케줄에서 `python main.py --sampro-digest`로 모아 발행한다."""
import html
import json
import os
import re
import sys
from datetime import datetime

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
    KST,
    facts_to_source_text,
    mark_topic_track_ran_today,
    record_topic_history,
    research_all_categories,
    should_run_topic_track_today,
    verify_facts,
)
from scripts.wordpress_publisher import publish_post, resolve_tag_ids

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
VIDEO_DIGEST_PATH = os.path.join(DATA_DIR, "today_video_posts.json")

# 모음글 안에서 링크 문구를 매번 똑같이 반복하지 않도록 순환시킨다(광고성으로 안
# 보이게 하기 위한 요구사항, B안 지시문 "공통 원칙" 참고).
DIGEST_LINK_PHRASES = [
    "자세히 보기 👉", "더 궁금하시면 여기 👉", "관련 내용은 이 글에서 👉",
    "이어서 읽어보시려면 👉", "전체 내용은 여기서 확인하세요 👉",
]


def _extract_teaser(body_html: str, max_len: int = 140) -> str:
    """본문 첫 <p> 문단에서 태그를 지운 평문 일부를 모음글용 티저로 뽑는다."""
    match = re.search(r"<p>(.*?)</p>", body_html, re.S)
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return text[: max_len].rstrip() + ("…" if len(text) > max_len else "")


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


def _record_video_post_for_digest(title: str, link: str, body_html: str) -> None:
    """콘텐츠 A(삼프로 모음, 19:20 KST 별도 워크플로우)가 나중에 읽어 쓸 수 있도록,
    오늘 자동공개된 영상 트랙 글의 제목/링크/티저를 날짜와 함께 누적 기록한다.
    날짜가 바뀌면 어제 이전 항목은 자연히 걸러진다."""
    today_str = datetime.now(KST).date().isoformat()
    entries = []
    if os.path.exists(VIDEO_DIGEST_PATH):
        try:
            with open(VIDEO_DIGEST_PATH, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []
    entries = [e for e in entries if e.get("date") == today_str]
    entries.append({"date": today_str, "title": title, "link": link, "teaser": _extract_teaser(body_html)})
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(VIDEO_DIGEST_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


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
                    status="publish",
                    excerpt=content.meta_description,
                    slug=content.slug,
                    tags=tag_ids,
                    featured_media=featured_media_id,
                )
                print(f"  - 발행됨(자동공개): {content.title} → {result['link']}")
                _record_video_post_for_digest(content.title, result["link"], content.body_html)

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


def _publish_topic_post(category: dict, candidate, client, model_name: str) -> dict | None:
    """리서치된 주제 후보 1개를 사실관계 확인 → 재가공 → 발행까지 처리한다.
    카테고리 4개를 각각 독립적으로 처리하므로, 하나가 실패해도 나머지에 영향 없도록
    호출하는 쪽(run_topic_track)에서 개별적으로 감싼다.
    반환값은 콘텐츠 B(카테고리 모음) 큐잉에 쓸 {category_label, body_html, link} —
    네이버용 재가공까지 실패하면 None(그래도 지니 발행/이력 기록은 이미 끝난 상태)."""
    facts = verify_facts(candidate, category, client, model_name)
    source_text = facts_to_source_text(facts)
    content = reprocess_topic(candidate.topic, category["label"], source_text, model_name, client)

    video = {"video_id": content.slug or "topic"}
    content_html, has_infographic, featured_media_id, infographic_bytes = assemble_html(content, video)
    tag_ids = resolve_tag_ids(content.tags)
    result = publish_post(
        content.title,
        content_html,
        status="publish",
        categories=[category["wp_category_id"]],
        excerpt=content.meta_description,
        slug=content.slug,
        tags=tag_ids,
        featured_media=featured_media_id,
    )
    print(f"  - 발행됨(자동공개, 주제선정/{category['label']}): {content.title} → {result['link']}")

    try:
        send_kakao_notification(content.title, result["link"], has_infographic)
    except Exception as e:
        print(f"  - 카카오 알림 실패(발행은 정상): {type(e).__name__}: {e}")

    record_topic_history(candidate.topic, category["id"])

    try:
        # source_text 재사용 — verify_facts(그라운딩, 유료)를 또 호출하지 않는다.
        naver_content = reprocess_topic_naver(candidate.topic, category["label"], source_text, model_name, client)
        _queue_naver_version(
            naver_content, topic=candidate.topic, category_label=category["label"], image_bytes=infographic_bytes
        )
        return {"category_label": category["label"], "body_html": naver_content.body_html, "link": result["link"]}
    except Exception as e:
        print(f"  - 네이버용 버전 생성 실패(워드프레스 발행은 정상, 콘텐츠 B 모음에서 이 카테고리는 빠짐): {type(e).__name__}: {e}")
        return None


def _queue_digest_b(entries: list[dict]) -> None:
    """콘텐츠 B(카테고리별 데일리 이슈 모음) — 카테고리마다 이미 만들어둔 서현이 아빠
    버전 본문의 첫 문단을 티저로 뽑아, 지니(워드프레스) 글 링크와 함께 모음글 하나로
    큐에 넣는다. 이미 생성된 콘텐츠를 재활용하는 것이라 추가 Gemini 호출은 없다."""
    today_label = datetime.now(KST).strftime("%m월 %d일")
    parts = [
        f"<p>안녕하세요, 서현이 아빠입니다 🙌 오늘({today_label}) 분야별로 눈여겨볼 만한 "
        "경제 이슈들을 한데 모아봤어요.</p>"
    ]
    for i, entry in enumerate(entries):
        teaser = _extract_teaser(entry["body_html"])
        phrase = DIGEST_LINK_PHRASES[i % len(DIGEST_LINK_PHRASES)]
        parts.append(f"<h2>{html.escape(entry['category_label'])}</h2>")
        if teaser:
            parts.append(f"<p>{html.escape(teaser)}</p>")
        parts.append(f'<p><a href="{entry["link"]}">{phrase}</a></p>')
    parts.append("<p>오늘도 읽어주셔서 감사합니다 😊.</p>")

    title = f"{today_label} 경제 이슈 브리핑 모음"
    queue_naver_draft(
        title=title,
        summary_lines=[e["category_label"] for e in entries],
        table_rows=[],
        body_html="\n".join(parts),
        topic="카테고리 모음(콘텐츠 B)",
        category_label="모음",
        image_bytes=None,
    )
    print(f"  - 콘텐츠 B(카테고리 모음) 큐에 저장됨: {title} ({len(entries)}개 항목)")


def run_topic_track(client, model_name):
    """카테고리 4개(주식/부동산/생활경제/경제상식)를 전부 리서치해서 각각 별도 글로
    발행한다(2026-09-09부터 — 예전에는 점수 최고 1개만 쓰고 나머지는 버렸음). 하루 1회만
    실행되도록 게이팅(영상 트랙과 별개로 독립 스케줄에서 호출됨, main.py의
    `--topics` 옵션 참고). 2026-09-15부터 끝에 콘텐츠 B(카테고리 모음) 큐잉도 이어붙임."""
    if not should_run_topic_track_today():
        print("[주제선정] 오늘 이미 실행함 — 건너뜀")
        return

    candidates = research_all_categories(client, model_name)
    if not candidates:
        print("[주제선정] 모든 카테고리에서 리서치 실패 또는 전부 중복 — 오늘은 발행 없음")
        return

    digest_entries = []
    for category, candidate in candidates:
        print(f"[주제선정] {category['label']} - {candidate.topic} (점수 {candidate.score})")
        try:
            entry = _publish_topic_post(category, candidate, client, model_name)
            if entry:
                digest_entries.append(entry)
        except Exception as e:
            print(f"  - '{category['label']}' 발행 실패: {type(e).__name__}: {e}")
            continue

    if digest_entries:
        try:
            _queue_digest_b(digest_entries)
        except Exception as e:
            print(f"  - 콘텐츠 B(카테고리 모음) 큐잉 실패: {type(e).__name__}: {e}")
    else:
        print("[주제선정] 콘텐츠 B용 항목이 하나도 없어서 모음글 생성 건너뜀")

    mark_topic_track_ran_today()


def run_sampro_digest() -> None:
    """콘텐츠 A(삼프로TV 콘텐츠 모음) — 그날 자동공개된 영상 트랙 글들
    (data/today_video_posts.json)을 모아 서현이 아빠 모음글 하나로 큐에 넣는다.
    새 GitHub Actions 스케줄(19:20 KST, 마지막 영상 트랙 실행 이후)에서
    `python main.py --sampro-digest`로 호출된다."""
    today_str = datetime.now(KST).date().isoformat()
    entries = []
    if os.path.exists(VIDEO_DIGEST_PATH):
        try:
            with open(VIDEO_DIGEST_PATH, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []
    entries = [e for e in entries if e.get("date") == today_str]
    if not entries:
        print("[삼프로 모음] 오늘 발행된 영상 트랙 글이 없어서 모음글 생성 건너뜀")
        return

    today_label = datetime.now(KST).strftime("%m월 %d일")
    parts = [
        f"<p>안녕하세요, 서현이 아빠입니다 🙌 오늘({today_label}) 삼프로TV 관련해서 "
        "지니가 정리한 글들을 모아봤어요.</p>"
    ]
    for i, entry in enumerate(entries):
        phrase = DIGEST_LINK_PHRASES[i % len(DIGEST_LINK_PHRASES)]
        parts.append(f"<h2>{html.escape(entry['title'])}</h2>")
        if entry.get("teaser"):
            parts.append(f"<p>{html.escape(entry['teaser'])}</p>")
        parts.append(f'<p><a href="{entry["link"]}">{phrase}</a></p>')
    parts.append("<p>오늘도 읽어주셔서 감사합니다 😊.</p>")

    title = f"{today_label} 삼프로TV 경제 콘텐츠 모음"
    queue_naver_draft(
        title=title,
        summary_lines=[e["title"] for e in entries],
        table_rows=[],
        body_html="\n".join(parts),
        topic="삼프로TV 모음(콘텐츠 A)",
        category_label="모음",
        image_bytes=None,
    )
    print(f"  - 콘텐츠 A(삼프로 모음) 큐에 저장됨: {title} ({len(entries)}건)")

    # 다음날 중복 누적 방지 — 오늘 치는 소진 처리(내일부터 새로 쌓임).
    with open(VIDEO_DIGEST_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)


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
    elif "--sampro-digest" in sys.argv:
        run_sampro_digest()
    else:
        run()
