"""body_html 속 <!-- 도식화: ... --> 마커를 실제 이미지로 변환한다.

HTML/CSS 템플릿을 Playwright(헤드리스 크로미움)로 스크린샷 떠서 PNG를 만든다.
변환에 실패하면(파싱 실패, 렌더링 실패, 업로드 실패, Playwright 실행 자체 실패 등)
예외를 삼키고 마커를 조용히 제거한다 — 도식화 하나(또는 전부)가 실패했다고
전체 발행이 막히면 안 되기 때문이다.
"""
import html
import os
import re
import sys
import uuid

from google.genai import types
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

from scripts.wordpress_publisher import upload_media

MARKER_PATTERN = re.compile(r"<!--\s*도식화:\s*(.*?)\s*-->", re.DOTALL)

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
CARD_WIDTH = 1080

NAVY = "#132A46"
BLUE = "#3B82D9"
BAR_TRACK_COLOR = "#E7ECF2"
MUTED_COLOR = "#64708A"


class ChartItem(BaseModel):
    label: str
    value: str


class ChartSpec(BaseModel):
    title: str
    items: list[ChartItem]


EXTRACT_SYSTEM_INSTRUCTION = """\
너는 블로그 글 속 "도식화 지시" 문구를 읽고, 그 안에 이미 있는 항목과 수치만 뽑아
막대 비교용 데이터로 정리하는 역할이다. 지시문에 없는 항목이나 수치를 절대 새로
지어내지 마라. 2~4개 항목으로 정리하고, title은 지시문의 핵심을 12자 내외로
요약하라. value는 지시문에 있는 표현을 그대로 짧게 옮겨라(예: "1%", "8~12%").
"""


def extract_chart_spec(marker_text: str, client, model_name: str) -> ChartSpec:
    response = client.models.generate_content(
        model=model_name,
        contents=f"도식화 지시문: {marker_text}",
        config=types.GenerateContentConfig(
            system_instruction=EXTRACT_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ChartSpec,
        ),
    )
    return ChartSpec.model_validate_json(response.text)


def _numeric_weight(value: str) -> float:
    match = re.search(r"[\d]+(\.\d+)?", value)
    return float(match.group()) if match else 1.0


def build_chart_html(spec: ChartSpec) -> str:
    max_weight = max((_numeric_weight(item.value) for item in spec.items), default=1.0) or 1.0
    rows_html = ""
    for item in spec.items:
        pct = max(_numeric_weight(item.value) / max_weight * 100, 4)
        rows_html += f"""
        <div class="row">
          <div class="label">{html.escape(item.label)}</div>
          <div class="bar-line">
            <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>
            <div class="value">{html.escape(item.value)}</div>
          </div>
        </div>"""

    return f"""\
<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face {{
  font-family: 'Noto Sans KR';
  src: url('file:///{FONT_DIR.replace(os.sep, "/")}/NotoSansKR-Variable.ttf');
  font-weight: 100 900;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Noto Sans KR', sans-serif; }}
#card {{
  width: {CARD_WIDTH}px;
  background: #ffffff;
  border-top: 16px solid {BLUE};
  padding: 56px 90px 50px;
}}
.title {{ font-size: 52px; font-weight: 700; color: {NAVY}; margin-bottom: 44px; }}
.row {{ margin-bottom: 40px; }}
.row:last-child {{ margin-bottom: 0; }}
.label {{ font-size: 34px; font-weight: 500; color: {MUTED_COLOR}; margin-bottom: 14px; }}
.bar-line {{ display: flex; align-items: center; gap: 20px; }}
.bar-track {{
  flex: 1; height: 28px; background: {BAR_TRACK_COLOR}; border-radius: 14px; overflow: hidden;
}}
.bar-fill {{
  height: 100%; border-radius: 14px;
  background: linear-gradient(90deg, {BLUE}, {NAVY});
}}
.value {{ font-size: 38px; font-weight: 700; color: {NAVY}; white-space: nowrap; }}
</style></head>
<body>
<div id="card">
  <div class="title">{html.escape(spec.title)}</div>
  {rows_html}
</div>
</body></html>
"""


def render_chart(spec: ChartSpec, page) -> bytes:
    html_content = build_chart_html(spec)
    page.set_content(html_content)
    element = page.query_selector("#card")
    return element.screenshot(type="png")


def _safe_print(message: str) -> None:
    """콘솔 인코딩이 메시지 속 문자를 못 다뤄도(예: Windows cp949) 로그 출력 자체가
    새 예외를 던져 폴백 로직을 깨뜨리지 않도록 방어적으로 출력한다."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(message.encode(encoding, errors="replace").decode(encoding))


def replace_diagram_markers(body_html: str, video_id: str, client, model_name: str) -> str:
    if not MARKER_PATTERN.search(body_html):
        return body_html

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": CARD_WIDTH + 40, "height": 800})

            def _replace(match: re.Match) -> str:
                marker_text = match.group(1)
                try:
                    spec = extract_chart_spec(marker_text, client, model_name)
                    png_bytes = render_chart(spec, page)
                    filename = f"diagram-{video_id}-{uuid.uuid4().hex[:8]}.png"
                    media = upload_media(png_bytes, filename)
                    return (
                        f'<img src="{media["source_url"]}" alt="{html.escape(spec.title)}" '
                        'style="max-width:100%; display:block; margin:16px auto;" />'
                    )
                except Exception as e:
                    _safe_print(f"  - 도식화 변환 실패(마커 제거하고 계속 진행): {type(e).__name__}: {e}")
                    return ""

            result = MARKER_PATTERN.sub(_replace, body_html)
            browser.close()
            return result
    except Exception as e:
        _safe_print(f"  - Playwright 실행 자체 실패, 모든 도식화 마커 제거하고 계속 진행: {type(e).__name__}: {e}")
        return MARKER_PATTERN.sub("", body_html)
