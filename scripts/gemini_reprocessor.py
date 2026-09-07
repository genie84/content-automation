"""Gemini API로 영상 자막/설명을 블로그 원고로 재가공한다."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from config.prompts import SYSTEM_INSTRUCTION, build_user_prompt, build_user_prompt_from_topic
from config.prompts_naver import SYSTEM_INSTRUCTION_NAVER, build_user_prompt_from_topic_naver
from config.sources import SOURCES
from scripts.gemini_retry import call_with_retry
from scripts.rss_collector import fetch_feed
from scripts.transcript_extractor import get_transcript

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
MODEL_CACHE_PATH = os.path.join(DATA_DIR, "resolved_model.json")
MODEL_CACHE_TTL = timedelta(hours=24)


class TableRow(BaseModel):
    항목: str
    현재: str
    리스크: str


class ReprocessedContent(BaseModel):
    title: str
    summary_lines: list[str]
    table_rows: list[TableRow]
    body_html: str
    focus_keyword: str
    meta_description: str
    slug: str
    tags: list[str]


class NaverContent(BaseModel):
    """네이버(서현이 아빠) 재가공 결과. SEO 필드는 없음(네이버는 자체 검색 로직)."""

    title: str
    summary_lines: list[str]
    table_rows: list[TableRow]
    body_html: str


GEMINI_TIMEOUT_MS = 120_000  # SDK 기본값은 무한대기라서 명시적으로 걸어둠. 이 값 자체가
# Google 서버에 X-Server-Timeout 헤더로 전달되어, 그 안에 못 끝내면 504
# DEADLINE_EXCEEDED로 돌아옴(실측 확인함) — 너무 짧게 잡으면 자기 자신이 원인이 되는
# 오탐성 타임아웃이 생기므로, GitHub Actions의 상대적으로 느린 네트워크 경로도
# 감안해서 90초보다 여유 있게 잡음.


def get_client() -> genai.Client:
    return genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )


# "-latest" 별칭을 우선 시도해 날짜 붙은 구체 모델명을 추측/하드코딩하지 않는다.
# client.models.list()는 이 키로는 쓸 수 없어서, 실제 generateContent를 핑 삼아 호출해
# 응답하는 첫 모델을 채택한다. 다만 이 핑 호출도 하루 쿼터를 소모하므로(무료 티어 일일
# 20건), 결과를 24시간 캐싱해서 매 실행마다 반복하지 않는다 — 모델이 바뀌어도(예:
# gemini-2.5-flash 서비스 종료 사례) 캐시가 하루 안에 자연스럽게 갱신되며 다시 잡힌다.
FLASH_MODEL_CANDIDATES = [
    "gemini-flash-latest",
    "gemini-3.6-flash",
]


def _load_cached_model() -> str | None:
    if not os.path.exists(MODEL_CACHE_PATH):
        return None
    try:
        with open(MODEL_CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        resolved_at = datetime.fromisoformat(cache["resolved_at"])
        if datetime.now(timezone.utc) - resolved_at > MODEL_CACHE_TTL:
            return None
        return cache["model_name"]
    except Exception:
        return None


def _save_model_cache(model_name: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MODEL_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"model_name": model_name, "resolved_at": datetime.now(timezone.utc).isoformat()},
            f,
            ensure_ascii=False,
            indent=2,
        )


def resolve_flash_model(client: genai.Client) -> str:
    cached = _load_cached_model()
    if cached:
        return cached

    errors = {}
    for name in FLASH_MODEL_CANDIDATES:
        try:
            call_with_retry(client.models.generate_content, model=name, contents="ping")
            _save_model_cache(name)
            return name
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {e}"
    raise RuntimeError(f"사용 가능한 Gemini Flash 모델을 찾지 못했습니다: {errors}")


def get_source_text(video: dict) -> tuple[str, str]:
    try:
        return get_transcript(video["video_id"]), "transcript"
    except Exception:
        return (video.get("description") or ""), "description"


def reprocess_content(
    video: dict, source: dict, model_name: str, client: genai.Client
) -> ReprocessedContent:
    source_text, source_type = get_source_text(video)
    prompt = build_user_prompt(video, source, source_text, source_type)
    response = call_with_retry(
        client.models.generate_content,
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ReprocessedContent,
        ),
    )
    result = ReprocessedContent.model_validate_json(response.text)

    from scripts.diagram_renderer import replace_diagram_markers

    result.body_html = replace_diagram_markers(
        result.body_html, video["video_id"], client, model_name, focus_keyword=result.focus_keyword
    )
    return result


def reprocess_topic(topic: str, category_label: str, source_text: str, model_name: str, client: genai.Client) -> ReprocessedContent:
    """리서치로 확인된 사실관계(source_text)를 소재로 지니 페르소나 글을 만든다.

    영상 재가공(reprocess_content)과 페르소나/스키마는 동일하고, 소스가 영상 자막이
    아니라 주제 리서치 결과라는 점만 다르다.
    """
    prompt = build_user_prompt_from_topic(topic, category_label, source_text)
    response = call_with_retry(
        client.models.generate_content,
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ReprocessedContent,
        ),
    )
    result = ReprocessedContent.model_validate_json(response.text)

    from scripts.diagram_renderer import replace_diagram_markers

    synthetic_id = result.slug or "topic"
    result.body_html = replace_diagram_markers(
        result.body_html, synthetic_id, client, model_name, focus_keyword=result.focus_keyword
    )
    return result


def reprocess_topic_naver(topic: str, category_label: str, source_text: str, model_name: str, client: genai.Client) -> NaverContent:
    """같은 리서치 결과(source_text)로 서현이 아빠 페르소나 글을 만든다(reprocess_topic의
    네이버용 자매 함수 — 스키마와 SYSTEM_INSTRUCTION만 다르다)."""
    prompt = build_user_prompt_from_topic_naver(topic, category_label, source_text)
    response = call_with_retry(
        client.models.generate_content,
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION_NAVER,
            response_mime_type="application/json",
            response_schema=NaverContent,
        ),
    )
    result = NaverContent.model_validate_json(response.text)

    from scripts.diagram_renderer import replace_diagram_markers

    synthetic_id = f"naver-{abs(hash(topic)) % 10**8}"
    result.body_html = replace_diagram_markers(result.body_html, synthetic_id, client, model_name)
    return result


def main():
    client = get_client()
    model_name = resolve_flash_model(client)
    print(f"사용 모델: {model_name}")

    source = SOURCES[0]
    entries = fetch_feed(source["rss_url"])
    video = entries[0]
    print(f"[{source['name']}] {video['title']} ({video['video_id']})")

    result = reprocess_content(video, source, model_name, client)
    print(f"재가공 제목: {result.title}")
    print(f"요약: {result.summary_lines}")
    print(f"표 행 수: {len(result.table_rows)}")
    print(f"본문 길이: {len(result.body_html)}자")


if __name__ == "__main__":
    main()
