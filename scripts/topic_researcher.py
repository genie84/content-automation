"""카테고리별 경제 이슈를 Gemini의 실시간 검색(그라운딩)으로 리서치하고 스코어링해
오늘의 주제 하나를 사람 개입 없이 자동 선정한다.

기존 "영상 재가공형" 트랙(RSS로 들어온 영상을 그대로 재가공)과 별개로, 카테고리
기반으로 지니가 직접 리서치해서 칼럼을 쓰는 두 번째 콘텐츠 소스 트랙이다.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from google.genai import types
from pydantic import BaseModel

from config.topics import TOPIC_CATEGORIES
from scripts.gemini_retry import call_with_retry

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TOPIC_HISTORY_PATH = os.path.join(DATA_DIR, "topic_history.json")
TOPIC_TRACK_STATE_PATH = os.path.join(DATA_DIR, "topic_track_state.json")
HISTORY_RETENTION_DAYS = 14
KST = timezone(timedelta(hours=9))

SEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())


class TopicCandidate(BaseModel):
    topic: str
    reasoning: str
    score: int
    source_urls: list[str]


class VerifiedFact(BaseModel):
    fact: str
    source_url: str


class VerifiedFacts(BaseModel):
    facts: list[VerifiedFact]


def _load_topic_history() -> list[dict]:
    if not os.path.exists(TOPIC_HISTORY_PATH):
        return []
    try:
        with open(TOPIC_HISTORY_PATH, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)
    return [h for h in history if datetime.fromisoformat(h["date"]) > cutoff]


def _save_topic_history(history: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TOPIC_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def record_topic_history(topic: str, category_id: str) -> None:
    history = _load_topic_history()
    history.append({"topic": topic, "category_id": category_id, "date": datetime.now(timezone.utc).isoformat()})
    _save_topic_history(history)


def _is_recent_duplicate(topic: str, recent_topics: list[str]) -> bool:
    """정확 일치/부분 포함 여부만 보는 간단한 휴리스틱 — 1차 방어는 프롬프트에 최근
    주제 목록을 넘겨 모델이 스스로 피하게 하는 것이고, 이건 최종 안전망이다."""
    normalized = topic.replace(" ", "")
    for recent in recent_topics:
        recent_normalized = recent.replace(" ", "")
        if normalized == recent_normalized or normalized in recent_normalized or recent_normalized in normalized:
            return True
    return False


def _research_category(category: dict, recent_topics: list[str], client, model_name: str) -> TopicCandidate:
    avoid_note = (
        f"최근 다룬 주제(참고용, 가능하면 겹치지 않게 새 이슈를 찾고, 겹치면 점수를 낮게 매겨라): "
        + ", ".join(recent_topics)
        if recent_topics
        else "최근 다룬 주제 없음."
    )
    prompt = f"""\
지금(오늘 기준) 대한민국 경제 뉴스 중 "{category['label']}" 카테고리({category['search_hint']})에서
가장 화제성·시의성이 높은 이슈 하나를 검색해서 찾아라.

{avoid_note}

topic은 그 이슈를 한 문장으로 요약하고, reasoning에는 왜 지금 시의성이 있는지 근거를 담아라.
score는 1~10 사이 정수로, 화제성과 시의성이 높을수록 높게 매겨라. source_urls에는 실제로
검색해서 찾은 근거 자료 링크를 넣어라(지어내지 마라, 검색 결과에 없으면 빈 배열로 둬라).
"""
    response = call_with_retry(
        client.models.generate_content,
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[SEARCH_TOOL],
            response_mime_type="application/json",
            response_schema=TopicCandidate,
        ),
    )
    return TopicCandidate.model_validate_json(response.text)


def research_all_categories(client, model_name: str) -> list[tuple[dict, TopicCandidate]]:
    """카테고리 4개를 전부 리서치·스코어링해서 (카테고리, 후보) 목록을 반환한다.
    최근 14일 내 중복으로 걸러진 카테고리나 리서치 자체가 실패한 카테고리는 결과에서
    빠진다(2026-09-09부터: 예전에는 이 중 점수 최고 1개만 쓰고 나머지는 버렸는데, 이제
    4개 카테고리 전부 각각 발행한다 — 아래 research_and_select_topic은 그 이전 방식이
    필요할 때를 위해 남겨둠)."""
    history = _load_topic_history()
    results = []
    for category in TOPIC_CATEGORIES:
        recent_topics = [h["topic"] for h in history if h["category_id"] == category["id"]]
        try:
            candidate = _research_category(category, recent_topics, client, model_name)
            if _is_recent_duplicate(candidate.topic, recent_topics):
                print(f"  - '{category['label']}' 후보가 최근 주제와 중복돼 제외: {candidate.topic}")
                continue
            results.append((category, candidate))
        except Exception as e:
            print(f"  - '{category['label']}' 카테고리 리서치 실패: {type(e).__name__}: {e}")
    return results


def research_and_select_topic(client, model_name: str) -> tuple[dict, TopicCandidate]:
    """카테고리 4개 중 가장 점수 높은 (카테고리, 후보) 1개만 고른다(예전 방식, 현재
    main.py는 안 씀 — research_all_categories로 4개 다 처리함)."""
    results = research_all_categories(client, model_name)
    if not results:
        raise RuntimeError("모든 카테고리에서 주제 리서치에 실패했거나 전부 중복으로 제외되었습니다.")
    return max(results, key=lambda pair: pair[1].score)


def verify_facts(candidate: TopicCandidate, category: dict, client, model_name: str) -> VerifiedFacts:
    prompt = f"""\
아래 경제 이슈에 대해 실제로 검색해서 확인되는 구체적인 수치·통계·발언·날짜를 최대한
많이 찾아라. 검색으로 확인 안 되는 내용은 절대 지어내지 말고 포함하지 마라.

이슈: {candidate.topic}
카테고리: {category['label']}
참고 맥락: {candidate.reasoning}

각 사실(fact)마다 그 사실을 확인한 출처 URL(source_url)을 반드시 함께 담아라.
"""
    response = call_with_retry(
        client.models.generate_content,
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[SEARCH_TOOL],
            response_mime_type="application/json",
            response_schema=VerifiedFacts,
        ),
    )
    return VerifiedFacts.model_validate_json(response.text)


def facts_to_source_text(facts: VerifiedFacts) -> str:
    return "\n".join(f"- {f.fact} (출처: {f.source_url})" for f in facts.facts)


def should_run_topic_track_today() -> bool:
    """주제선정 트랙은 하루 1회만 — 이미 오늘(KST) 실행했으면 건너뛴다."""
    today = datetime.now(KST).date().isoformat()
    if not os.path.exists(TOPIC_TRACK_STATE_PATH):
        return True
    try:
        with open(TOPIC_TRACK_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get("last_run_date") != today
    except Exception:
        return True


def mark_topic_track_ran_today() -> None:
    today = datetime.now(KST).date().isoformat()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TOPIC_TRACK_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"last_run_date": today}, f, ensure_ascii=False, indent=2)
