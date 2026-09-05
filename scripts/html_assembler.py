"""재가공된 콘텐츠를 워드프레스 발행용 HTML 하나로 조립한다."""
import html
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.gemini_reprocessor import ReprocessedContent, TableRow
from scripts.infographic_generator import generate_infographic
from scripts.wordpress_publisher import upload_media

# 자동발행 글에만 적용되는 scoped 스타일 — 사이트 전체 테마는 건드리지 않는다.
# 실제 사이트(lampgenie.co.kr, 2026-09-05)에서 .entry-content 기준 실측한 값:
# p 13.68px, h2 30px(테마 자체 지정값, body 상속이 아님), blockquote 15.048px.
# h2는 "0.9em"으로 쓰면 부모(genie-post div, 13.68px) 기준으로 계산돼 약 12px로
# 되레 본문보다 작아지는 문제가 있어(em은 자기 자신의 기존 크기가 아니라 부모의
# 계산된 크기를 기준으로 함), 테마 실측값(30px)의 90%인 27px로 고정값을 씀.
GENIE_POST_STYLE = """\
<style>
.genie-post p { font-size: calc(1em + 1px); }
.genie-post h2 { font-size: 27px; }
.genie-post blockquote.genie-insight { font-size: calc(1em + 3px); }
.genie-post blockquote.genie-insight strong:first-child { font-size: calc(1em + 5px); }
</style>
"""

INSIGHT_PATTERN = re.compile(r'<blockquote>(\s*<strong>\U0001f4a1\s*지니의 생각</strong>)')


def _mark_insight_blockquote(body_html: str) -> str:
    return INSIGHT_PATTERN.sub(r'<blockquote class="genie-insight">\1', body_html, count=1)


def build_summary_box(summary_lines: list[str]) -> str:
    items = "".join(f"<li>{html.escape(line)}</li>" for line in summary_lines)
    return (
        '<div style="border:1px solid #ddd; border-radius:8px; padding:13px; margin:16px 0; font-size:0.8em;">'
        "<strong>\U0001f4cc 핵심요약</strong>"
        f"<ul>{items}</ul>"
        "</div>"
    )


def build_table(table_rows: list[TableRow]) -> str:
    if not table_rows:
        return ""
    headers = list(table_rows[0].model_dump().keys())
    header_html = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body_html = ""
    for row in table_rows:
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row.model_dump().values())
        body_html += f"<tr>{cells}</tr>"
    return (
        '<table style="border-collapse:collapse; width:80%; margin:16px auto;" border="1">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
    )


def build_youtube_embed(video_id: str) -> str:
    return (
        '<div style="margin:16px 0;">\U0001f3a5 관련 영상 보기</div>'
        '<div style="position:relative; padding-top:56.25%;">'
        f'<iframe src="https://www.youtube-nocookie.com/embed/{video_id}" '
        'style="position:absolute; top:0; left:0; width:100%; height:100%;" '
        'frameborder="0" allowfullscreen></iframe>'
        "</div>"
    )


def build_infographic_html(title: str, body_html: str, video_id: str) -> str:
    png_bytes = generate_infographic(title, body_html)
    if png_bytes is None:
        return ""
    try:
        filename = f"infographic-{video_id}-{uuid.uuid4().hex[:8]}.png"
        media = upload_media(png_bytes, filename)
        return (
            f'<img src="{media["source_url"]}" alt="{html.escape(title)}" '
            'style="max-width:100%; display:block; margin:24px auto;" />'
        )
    except Exception as e:
        print(f"  - 대표 인포그래픽 업로드 실패(이미지 없이 계속 진행): {type(e).__name__}: {e}")
        return ""


def assemble_html(content: ReprocessedContent, video: dict) -> tuple[str, bool]:
    """(발행용 HTML, 대표 인포그래픽 포함 여부)를 반환한다."""
    infographic_html = build_infographic_html(content.title, content.body_html, video["video_id"])
    body_html = _mark_insight_blockquote(content.body_html)
    inner_html = (
        build_summary_box(content.summary_lines)
        + build_table(content.table_rows)
        + body_html
        + infographic_html
    )
    result_html = f'{GENIE_POST_STYLE}<div class="genie-post">{inner_html}</div>'
    return result_html, bool(infographic_html)


def main():
    sample_content = ReprocessedContent(
        title="[테스트] 조립 확인",
        summary_lines=["요약 1", "요약 2"],
        table_rows=[TableRow(항목="항목1", 현재="값1", 리스크="리스크1")],
        body_html="<h3>제목</h3><p>본문입니다.</p>",
    )
    sample_video = {"video_id": "m67LrN1J-fg"}

    result_html, has_infographic = assemble_html(sample_content, sample_video)
    print(f"인포그래픽 포함 여부: {has_infographic}")
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "preview.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"<meta charset='utf-8'><body style='max-width:700px; margin:40px auto; font-family:sans-serif;'>{result_html}</body>")
    print(f"조립된 HTML 길이: {len(result_html)}자")
    print(f"미리보기 저장: {out_path}")


if __name__ == "__main__":
    main()
