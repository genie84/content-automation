"""카드뉴스 이미지와 유튜브 임베드를 워드프레스 발행용 HTML 하나로 조립한다."""
import html
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.card_renderer import render_card
from scripts.gemini_reprocessor import Card, ReprocessedContent
from scripts.wordpress_publisher import upload_media


def build_text_block(text: str) -> str:
    return f"<p>{html.escape(text)}</p>"


def build_youtube_embed(video_id: str) -> str:
    return (
        '<div style="margin:16px 0;">\U0001f3a5 관련 영상 보기</div>'
        '<div style="position:relative; padding-top:56.25%;">'
        f'<iframe src="https://www.youtube-nocookie.com/embed/{video_id}" '
        'style="position:absolute; top:0; left:0; width:100%; height:100%;" '
        'frameborder="0" allowfullscreen></iframe>'
        "</div>"
    )


def build_cards_html(cards: list[Card], video_id: str) -> str:
    total = len(cards)
    img_tags = []
    for i, card in enumerate(cards, 1):
        png_bytes = render_card(card.icon_emoji, card.headline, card.body, i, total)
        filename = f"card-{video_id}-{i}-{uuid.uuid4().hex[:8]}.png"
        media = upload_media(png_bytes, filename)
        img_tags.append(
            f'<img src="{media["source_url"]}" alt="{html.escape(card.headline)}" '
            'style="max-width:100%; display:block; margin:16px auto;" />'
        )
    return "".join(img_tags)


def assemble_html(content: ReprocessedContent, video: dict) -> str:
    return (
        build_text_block(content.intro_text)
        + build_cards_html(content.cards, video["video_id"])
        + build_text_block(content.outro_text)
        + build_youtube_embed(video["video_id"])
    )


def main():
    sample_content = ReprocessedContent(
        title="[테스트] 카드뉴스 조립 확인",
        intro_text="이 글은 html_assembler.py 단독 테스트용입니다.",
        cards=[
            Card(icon_emoji="1️⃣", headline="카드 1", body="첫 번째 카드 본문입니다."),
            Card(icon_emoji="2️⃣", headline="카드 2", body="두 번째 카드 본문입니다."),
        ],
        outro_text="여기까지 테스트였습니다.",
    )
    sample_video = {"video_id": "m67LrN1J-fg"}

    result_html = assemble_html(sample_content, sample_video)
    print(f"조립된 HTML 길이: {len(result_html)}자")


if __name__ == "__main__":
    main()
