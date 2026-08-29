"""재가공된 콘텐츠와 유튜브 임베드를 워드프레스 발행용 HTML 하나로 조립한다."""
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.gemini_reprocessor import ReprocessedContent, TableRow


def build_summary_box(summary_lines: list[str]) -> str:
    items = "".join(f"<li>{html.escape(line)}</li>" for line in summary_lines)
    return (
        '<div style="border:1px solid #ddd; border-radius:8px; padding:16px; margin:16px 0;">'
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
        '<table style="border-collapse:collapse; width:100%; margin:16px 0;" border="1">'
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


def assemble_html(content: ReprocessedContent, video: dict) -> str:
    return (
        build_summary_box(content.summary_lines)
        + build_table(content.table_rows)
        + content.body_html
        + build_youtube_embed(video["video_id"])
    )


def main():
    sample_content = ReprocessedContent(
        title="성경 속에 초승달의 흔적이? 고대 근동의 달 신앙과 우리의 착각",
        summary_lines=[
            "고대 근동 세계에서 달은 단순한 야경이 아니라 왕권과 세계의 질서를 상징하는 최고의 남신이었습니다.",
            "농경보다 유목과 이동이 중요했던 시절, 달은 밤길의 이정표이자 28일 주기의 명확한 기준이 되어주었습니다.",
            "구약 성경의 절기나 역사 속에서도 '초하루(초승달)'를 특별히 여겼던 문화적 흔적을 곳곳에서 발견할 수 있습니다.",
        ],
        table_rows=[
            TableRow(항목="달의 상징성", 현재="왕권과 질서를 상징하는 최고신", 리스크="현대의 통념(해=양, 달=음)과 정반대"),
            TableRow(항목="실용적 기능", 현재="유목민의 밤길 이정표, 28일 주기 달력", 리스크="농경 중심 해석만으로는 설명 안 됨"),
            TableRow(항목="성경 속 흔적", 현재="초하루(초승달)를 특별히 여긴 절기 문화", 리스크="단편적 언급이라 맥락 없이는 놓치기 쉬움"),
        ],
        body_html=(
            "<h3>햇님 달님? 고대인들에겐 달이 '최고의 형님'이었다!</h3>"
            "<p>안녕하세요! 딸바보 40대 아빠 '서현이 아빠'입니다. (이하 본문은 1-5에서 실제 Gemini가 생성한 내용)</p>"
        ),
    )
    sample_video = {"video_id": "m67LrN1J-fg"}

    result_html = assemble_html(sample_content, sample_video)

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "preview.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"<meta charset='utf-8'><body style='max-width:700px; margin:40px auto; font-family:sans-serif;'>{result_html}</body>")
    print(f"조립된 HTML 길이: {len(result_html)}자")
    print(f"미리보기 저장: {out_path}")


if __name__ == "__main__":
    main()
