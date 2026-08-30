"""카드뉴스 카드 한 장을 PNG 이미지로 렌더링한다."""
import io
import os

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "NotoSansKR-Variable.ttf")
EMOJI_FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "NotoColorEmoji.ttf")

CARD_WIDTH = 1080
MARGIN = 90
HEADLINE_LINE_HEIGHT = 84
BODY_LINE_HEIGHT = 58
TOP_BLOCK_HEIGHT = 140  # 액센트 바 다음, 이모지 배지 시작 y좌표
BADGE_DIAMETER = 200
BADGE_GAP = 50  # 배지 아래 ~ 헤드라인
HEADLINE_BODY_GAP = 24
FOOTER_HEIGHT = 130

ACCENT_COLOR = (43, 108, 176)  # #2b6cb0
TEXT_COLOR = (26, 32, 44)
MUTED_COLOR = (100, 110, 130)
BADGE_COLOR = (255, 255, 255)

# 카드 순서에 따라 순환하는 파스텔 배경 (진한 텍스트가 항상 잘 읽히도록 밝은 톤으로만 구성)
PALETTE = [
    (255, 247, 230),  # cream
    (232, 245, 240),  # mint
    (231, 240, 254),  # sky
    (253, 235, 240),  # pink
    (241, 235, 254),  # lavender
]


def _font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(FONT_PATH, size)
    font.set_variation_by_axes([weight])
    return font


def _wrap_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
                continue
            if current:
                lines.append(current)
            if draw.textlength(word, font=font) <= max_width:
                current = word
                continue
            # 단어 하나가 너무 길면 글자 단위로 쪼갠다
            current = ""
            for ch in word:
                trial_ch = current + ch
                if draw.textlength(trial_ch, font=font) <= max_width:
                    current = trial_ch
                else:
                    lines.append(current)
                    current = ch
        lines.append(current)
    return lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    y: int,
    line_height: int,
    color: tuple,
) -> int:
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((CARD_WIDTH - w) / 2, y), line, font=font, fill=color)
        y += line_height
    return y


def render_card(icon_emoji: str, headline: str, body: str, index: int, total: int) -> bytes:
    bg_color = PALETTE[(index - 1) % len(PALETTE)]
    content_width = CARD_WIDTH - 2 * MARGIN
    headline_font = _font(66, 700)
    body_font = _font(40, 500)
    page_font = _font(28, 500)
    footer_font = _font(26, 500)
    emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, 109)

    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    headline_lines = _wrap_to_width(measurer, headline, headline_font, content_width)
    body_lines = _wrap_to_width(measurer, body, body_font, content_width)

    content_bottom = (
        TOP_BLOCK_HEIGHT
        + BADGE_DIAMETER
        + BADGE_GAP
        + len(headline_lines) * HEADLINE_LINE_HEIGHT
        + HEADLINE_BODY_GAP
        + len(body_lines) * BODY_LINE_HEIGHT
    )
    card_height = content_bottom + FOOTER_HEIGHT

    img = Image.new("RGB", (CARD_WIDTH, card_height), bg_color)
    draw = ImageDraw.Draw(img)

    # 상단 액센트 바 + 페이지 표시
    draw.rectangle([0, 0, CARD_WIDTH, 16], fill=ACCENT_COLOR)
    draw.text((MARGIN, 50), f"{index}/{total}", font=page_font, fill=MUTED_COLOR)

    # 이모지 배지 (흰 원 위에 컬러 이모지, 가로 중앙)
    badge_x = (CARD_WIDTH - BADGE_DIAMETER) / 2
    badge_y = TOP_BLOCK_HEIGHT
    draw.ellipse(
        [badge_x, badge_y, badge_x + BADGE_DIAMETER, badge_y + BADGE_DIAMETER], fill=BADGE_COLOR
    )
    emoji_bbox = draw.textbbox((0, 0), icon_emoji, font=emoji_font)
    emoji_w = emoji_bbox[2] - emoji_bbox[0]
    emoji_h = emoji_bbox[3] - emoji_bbox[1]
    ex = badge_x + (BADGE_DIAMETER - emoji_w) / 2 - emoji_bbox[0]
    ey = badge_y + (BADGE_DIAMETER - emoji_h) / 2 - emoji_bbox[1]
    draw.text((ex, ey), icon_emoji, font=emoji_font, embedded_color=True)

    # 헤드라인 + 본문 (가로 중앙 정렬)
    y = badge_y + BADGE_DIAMETER + BADGE_GAP
    y = _draw_centered_lines(draw, headline_lines, headline_font, y, HEADLINE_LINE_HEIGHT, TEXT_COLOR)
    y += HEADLINE_BODY_GAP
    _draw_centered_lines(draw, body_lines, body_font, y, BODY_LINE_HEIGHT, TEXT_COLOR)

    # 하단 브랜드 표시 (중앙 정렬)
    footer_text = "서현이 아빠의 경제공부"
    fw = draw.textlength(footer_text, font=footer_font)
    draw.text(((CARD_WIDTH - fw) / 2, card_height - 70), footer_text, font=footer_font, fill=MUTED_COLOR)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main():
    samples = [
        ("🌙", "고대인들은 왜 태양보다 달을 사랑했을까?", "달은 최고의 길잡이이자 달력이었습니다.", 1, 3),
        ("👑", "달이 최고의 신이었다고?", "메소포타미아에선 달이 왕권의 상징이었어요.", 2, 3),
        ("💡", "서현아빠 생각", "작은 초승달처럼 시작해도 괜찮습니다!", 3, 3),
    ]
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    for icon, headline, body, i, total in samples:
        png_bytes = render_card(icon, headline, body, i, total)
        out_path = os.path.join(out_dir, f"card_preview_{i}.png")
        with open(out_path, "wb") as f:
            f.write(png_bytes)
        print(f"저장됨: {out_path} ({len(png_bytes)} bytes)")


if __name__ == "__main__":
    main()
