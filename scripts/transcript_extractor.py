"""유튜브 영상의 자막(transcript)을 추출한다."""
import os
import sys

from youtube_transcript_api import YouTubeTranscriptApi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.sources import SOURCES


def get_transcript(video_id: str, languages=("ko", "en")) -> str:
    ytt_api = YouTubeTranscriptApi()
    transcript = ytt_api.fetch(video_id, languages=list(languages))
    return " ".join(snippet.text for snippet in transcript)


def main():
    from scripts.rss_collector import fetch_feed

    source = SOURCES[0]
    entries = fetch_feed(source["rss_url"])
    video = entries[0]
    print(f"[{source['name']}] {video['title']} ({video['video_id']})")
    try:
        transcript = get_transcript(video["video_id"])
        print(f"자막 길이: {len(transcript)}자")
        print(transcript[:300])
    except Exception as e:
        print(f"자막 추출 실패: {type(e).__name__}: {e}")
        print(f"설명으로 폴백 가능: {(video['description'] or '')[:300]}")


if __name__ == "__main__":
    main()
