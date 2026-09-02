"""Gemini API로 영상 자막/설명을 블로그 원고로 재가공한다."""
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from config.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from config.sources import SOURCES
from scripts.rss_collector import fetch_feed
from scripts.transcript_extractor import get_transcript


class TableRow(BaseModel):
    항목: str
    현재: str
    리스크: str


class ReprocessedContent(BaseModel):
    title: str
    summary_lines: list[str]
    table_rows: list[TableRow]
    body_html: str


GEMINI_TIMEOUT_MS = 90_000  # SDK 기본값은 무한대기라서, GitHub Actions에서 네트워크가
# 응답 없이 멈추면 잡을 방법이 없었음(실제로 9분 넘게 hang된 사례 있음) — 명시적으로 걸어둠.


def get_client() -> genai.Client:
    return genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )


# "-latest" 별칭을 우선 시도해 날짜 붙은 구체 모델명을 추측/하드코딩하지 않는다.
# client.models.list()는 이 키로는 쓸 수 없어서, 실제 generateContent를 핑 삼아 호출해
# 응답하는 첫 모델을 채택한다.
FLASH_MODEL_CANDIDATES = [
    "gemini-flash-latest",
    "gemini-3.6-flash",
]


def resolve_flash_model(client: genai.Client) -> str:
    errors = {}
    for name in FLASH_MODEL_CANDIDATES:
        try:
            client.models.generate_content(model=name, contents="ping")
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
    response = client.models.generate_content(
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

    result.body_html = replace_diagram_markers(result.body_html, video["video_id"], client, model_name)
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
