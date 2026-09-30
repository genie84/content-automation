"""RSS 피드에서 소스별 신규 영상을 수집한다."""
import json
import os
import sys
import xml.etree.ElementTree as ET

import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.sources import SOURCES

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SEEN_VIDEOS_PATH = os.path.join(DATA_DIR, "seen_videos.json")

ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"
MEDIA_NS = "http://search.yahoo.com/mrss/"
NS = {"atom": ATOM_NS, "yt": YT_NS, "media": MEDIA_NS}

# 2026-09-30: GitHub Actions 러너 IP에서 이 주소로 404가 나는 경우를 직접 재현해보니(같은 날 같은
# 채널ID로 다른 실행은 정상), 채널ID나 코드 문제가 아니라 유튜브가 그 러너의 IP 대역을 일시적으로
# 막는 것으로 보인다(집 네트워크에서는 봇 UA든 실제 브라우저 UA든 항상 200). 그래서 봇임을 드러내는
# UA 대신 실제 브라우저 UA를 쓰고, 짧게 몇 번이 아니라 최대 ~4분에 걸쳐 길게 재시도해서 그 사이에
# 차단이 풀리는 경우를 잡는다(python main.py 스텝 제한 25분 중 여유 있게 사용).
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
FETCH_MAX_ATTEMPTS = 7
FETCH_BACKOFF_SEC = [5, 10, 20, 30, 45, 60]  # 누적 약 170초


def fetch_feed(rss_url: str) -> list[dict]:
    last_error = None
    for attempt in range(FETCH_MAX_ATTEMPTS):
        try:
            response = requests.get(rss_url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            break
        except requests.RequestException as e:
            last_error = e
            print(f"  - RSS 조회 실패({attempt + 1}/{FETCH_MAX_ATTEMPTS}): {type(e).__name__}: {e}")
            if attempt < FETCH_MAX_ATTEMPTS - 1:
                time.sleep(FETCH_BACKOFF_SEC[attempt])
    else:
        raise last_error
    root = ET.fromstring(response.content)

    entries = []
    for entry in root.findall("atom:entry", NS):
        video_id = entry.findtext("yt:videoId", namespaces=NS)
        title = entry.findtext("atom:title", namespaces=NS)
        link_el = entry.find("atom:link", NS)
        url = link_el.get("href") if link_el is not None else None
        published = entry.findtext("atom:published", namespaces=NS)
        description = entry.findtext("media:group/media:description", namespaces=NS)
        entries.append(
            {
                "video_id": video_id,
                "title": title,
                "url": url,
                "published": published,
                "description": description,
            }
        )
    return entries


def load_seen_videos() -> dict:
    if not os.path.exists(SEEN_VIDEOS_PATH):
        return {}
    with open(SEEN_VIDEOS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen_videos(seen_videos: dict) -> None:
    with open(SEEN_VIDEOS_PATH, "w", encoding="utf-8") as f:
        json.dump(seen_videos, f, ensure_ascii=False, indent=2)


def matches_program_whitelist(title: str, program_whitelist: list[str]) -> bool:
    normalized_title = title.replace(" ", "")
    return any(program.replace(" ", "") in normalized_title for program in program_whitelist)


def collect_new_videos(source: dict, seen_ids: set) -> list[dict]:
    entries = fetch_feed(source["rss_url"])
    entries = [e for e in entries if e["video_id"] not in seen_ids]

    program_whitelist = source.get("program_whitelist")
    if program_whitelist:
        entries = [e for e in entries if matches_program_whitelist(e["title"], program_whitelist)]

    return entries


def main():
    seen_videos = load_seen_videos()
    for source in SOURCES:
        seen_ids = set(seen_videos.get(source["id"], []))
        new_videos = collect_new_videos(source, seen_ids)
        print(f"[{source['name']}] 신규 영상 {len(new_videos)}건")
        for video in new_videos:
            print(f"  - {video['title']} ({video['video_id']})")


if __name__ == "__main__":
    main()
