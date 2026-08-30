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


class Card(BaseModel):
    icon_emoji: str
    headline: str
    body: str


class ReprocessedContent(BaseModel):
    title: str
    intro_text: str
    cards: list[Card]
    outro_text: str


def get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


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
    return ReprocessedContent.model_validate_json(response.text)


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
    print(f"도입: {result.intro_text}")
    print(f"카드 수: {len(result.cards)}")
    for i, card in enumerate(result.cards, 1):
        print(f"  {i}. {card.icon_emoji} {card.headline} — {card.body}")
    print(f"마무리: {result.outro_text}")


if __name__ == "__main__":
    main()
