"""재가공된 콘텐츠를 워드프레스 REST API로 발행한다."""
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

WP_BASE_URL = "https://yahaho1004.mycafe24.com"


def publish_post(title: str, content_html: str, status: str = "draft") -> dict:
    response = requests.post(
        f"{WP_BASE_URL}/wp-json/wp/v2/posts",
        auth=(os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"]),
        json={"title": title, "content": content_html, "status": status},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main():
    from scripts.gemini_reprocessor import ReprocessedContent, TableRow
    from scripts.html_assembler import assemble_html

    sample_content = ReprocessedContent(
        title="[테스트] 성경 속에 초승달의 흔적이? 고대 근동의 달 신앙과 우리의 착각",
        summary_lines=[
            "고대 근동 세계에서 달은 단순한 야경이 아니라 왕권과 세계의 질서를 상징하는 최고의 남신이었습니다.",
            "농경보다 유목과 이동이 중요했던 시절, 달은 밤길의 이정표이자 28일 주기의 명확한 기준이 되어주었습니다.",
        ],
        table_rows=[
            TableRow(항목="달의 상징성", 현재="왕권과 질서를 상징하는 최고신", 리스크="현대의 통념(해=양, 달=음)과 정반대"),
        ],
        body_html=(
            "<h3>1-7 워드프레스 연동 테스트 포스트입니다.</h3>"
            "<p>이 글은 status=draft로 생성되어 실제 방문자에게는 보이지 않습니다.</p>"
        ),
    )
    sample_video = {"video_id": "m67LrN1J-fg"}

    content_html = assemble_html(sample_content, sample_video)
    result = publish_post(sample_content.title, content_html, status="draft")
    print(f"post id: {result['id']}")
    print(f"status: {result['status']}")
    print(f"link: {result['link']}")


if __name__ == "__main__":
    main()
