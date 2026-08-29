"""RSS 피드에서 소스별 신규 영상을 수집한다."""
import json
import os
import sys
import xml.etree.ElementTree as ET

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.sources import SOURCES

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SEEN_VIDEOS_PATH = os.path.join(DATA_DIR, "seen_videos.json")

ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"
MEDIA_NS = "http://search.yahoo.com/mrss/"
NS = {"atom": ATOM_NS, "yt": YT_NS, "media": MEDIA_NS}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; content-automation-bot/1.0)"}


def fetch_feed(rss_url: str) -> list[dict]:
    response = requests.get(rss_url, headers=HEADERS, timeout=15)
    response.raise_for_status()
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


def collect_new_videos(source: dict, seen_ids: set) -> list[dict]:
    entries = fetch_feed(source["rss_url"])
    return [e for e in entries if e["video_id"] not in seen_ids]


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
