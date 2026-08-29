"""워드프레스 draft 글이 CLAUDE.md 4번(채널명/AI말투)·5번(창작성) 원칙을 지키는지 점검한다."""
import html
import os
import re
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from scripts.transcript_extractor import get_transcript
from scripts.wordpress_publisher import WP_BASE_URL

CHANNEL_NAMES = ["삼프로TV", "3PROTV", "3protv"]
AI_PHRASES = ["제공해주신", "원고를 작성해 드립니다", "다음은 요청하신", "요청하신 내용"]


def strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def shingles(text: str, n: int = 8) -> set:
    words = text.split()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def fetch_post(post_id: int) -> dict:
    response = requests.get(
        f"{WP_BASE_URL}/wp-json/wp/v2/posts/{post_id}",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        params={"context": "edit"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def audit(post_id: int, video_id: str) -> dict:
    post = fetch_post(post_id)
    body_text = strip_html(post["content"]["raw"])
    full_text = post["title"]["raw"] + " " + body_text

    channel_hits = [n for n in CHANNEL_NAMES if n in full_text]
    ai_phrase_hits = [p for p in AI_PHRASES if p in full_text]

    transcript = get_transcript(video_id)
    overlap = shingles(transcript, 8) & shingles(body_text, 8)

    return {
        "post_id": post_id,
        "title": post["title"]["raw"],
        "channel_name_hits": channel_hits,
        "ai_phrase_hits": ai_phrase_hits,
        "transcript_overlap_count": len(overlap),
        "transcript_overlap_examples": list(overlap)[:5],
    }


def main():
    if len(sys.argv) != 3:
        print("사용법: python -m scripts.copyright_audit <post_id> <video_id>")
        sys.exit(1)
    result = audit(int(sys.argv[1]), sys.argv[2])
    print(f"[post {result['post_id']}] {result['title']}")
    print(f"  채널명 노출: {result['channel_name_hits'] or '없음'}")
    print(f"  AI스러운 문구: {result['ai_phrase_hits'] or '없음'}")
    print(f"  자막과 8단어 이상 겹침: {result['transcript_overlap_count']}건")
    for e in result["transcript_overlap_examples"]:
        print(f"    - {e}")


if __name__ == "__main__":
    main()
