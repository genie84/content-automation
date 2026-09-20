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
from typing import Literal

from google.genai import types
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

from scripts import image_host
from scripts.gemini_retry import call_with_retry
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
    chart_type: Literal["bar", "flow", "checklist", "skip"]
    title: str
    items: list[ChartItem]


# "막대그래프를 숫자 비교가 아닌 내용(순서/단계, 전부 같은 결론, 관점 대비)에도 억지로
# 쓰는" 문제(2026-09-06 실제 발행 글에서 발견)를 막기 위해, 렌더링 전에 먼저 이 지시문이
# 어떤 시각화 형태에 맞는지 분류부터 시킨다.
EXTRACT_SYSTEM_INSTRUCTION = """\
너는 블로그 글 속 "도식화 지시" 문구를 읽고, 그 내용에 가장 적합한 시각화 형태를
먼저 판단한 뒤, 그 형태에 맞는 데이터로 정리하는 역할이다.

chart_type을 아래 기준으로 정하라:
- "bar": 항목들이 서로 다른 실제 숫자값을 갖고 있어서 크기 비교가 의미 있는 경우.
  예: 국가별 금리 4.78%, 3.0%, 5.2% / 매출 100억 vs 80억.
- "flow": 항목들이 시간순·단계순으로 이어지는 흐름이나 프로세스인 경우(숫자 비교가
  아님). 예: 철강 생산 → 부품 조달 → 현지 조립 → 판매.
- "checklist": 여러 항목이 전부 같은 결론/상태를 공유하고 숫자 크기 비교가 아닌
  경우. 예: 여러 국가가 전부 "수출 1조 달러 달성", 여러 원인이 전부 "약세 요인".
- "skip": 위 셋 어디에도 안 맞는 경우(예: 이전 관점 vs 현재 관점처럼 단순 대비이거나,
  시각화보다 글로 설명하는 게 더 명확한 경우). 이때 items는 빈 배열로 둬라.

지시문에 없는 항목이나 수치를 절대 새로 지어내지 마라. items는 2~5개(skip 제외).
- bar일 때: value는 지시문에 있는 실제 수치를 그대로(예: "4.78%", "8~12%").
- flow일 때: value는 그 단계를 설명하는 5~10자 짧은 문구.
- checklist일 때: value는 그 항목의 구체적 디테일을 담은 5~10자 짧은 문구(공통
  결론을 반복하지 말고, 항목마다 다른 내용이어야 함).
title은 지시문의 핵심을 12자 내외로 요약하라.
"""


def extract_chart_spec(marker_text: str, client, model_name: str) -> ChartSpec:
    response = call_with_retry(
        client.models.generate_content,
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


def _card_shell(title: str, body: str) -> str:
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
</style></head>
<body>
<div id="card">
  <div class="title">{html.escape(title)}</div>
  {body}
</div>
</body></html>
"""


def _build_bar_body(items: list[ChartItem]) -> str:
    max_weight = max((_numeric_weight(item.value) for item in items), default=1.0) or 1.0
    rows_html = ""
    for item in items:
        pct = max(_numeric_weight(item.value) / max_weight * 100, 4)
        rows_html += f"""
        <div class="row">
          <div class="label">{html.escape(item.label)}</div>
          <div class="bar-line">
            <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>
            <div class="value">{html.escape(item.value)}</div>
          </div>
        </div>"""
    style = f"""\
<style>
.row {{ margin-bottom: 40px; }}
.row:last-child {{ margin-bottom: 0; }}
.label {{ font-size: 34px; font-weight: 500; color: {MUTED_COLOR}; margin-bottom: 14px; }}
.bar-line {{ display: flex; align-items: center; gap: 20px; }}
.bar-track {{
  flex: 1; height: 56px; background: {BAR_TRACK_COLOR}; border-radius: 28px; overflow: hidden;
}}
.bar-fill {{
  height: 100%; border-radius: 28px;
  background: linear-gradient(90deg, {BLUE}, {NAVY});
}}
.value {{ font-size: 38px; font-weight: 700; color: {NAVY}; white-space: nowrap; }}
</style>"""
    return style + rows_html


def _build_flow_body(items: list[ChartItem]) -> str:
    steps_html = ""
    for i, item in enumerate(items):
        if i > 0:
            steps_html += '<div class="flow-arrow">→</div>'
        steps_html += f"""
        <div class="flow-step">
          <div class="flow-box">
            <div class="flow-label">{html.escape(item.label)}</div>
            <div class="flow-caption">{html.escape(item.value)}</div>
          </div>
        </div>"""
    style = f"""\
<style>
.flow-row {{ display: flex; align-items: stretch; }}
.flow-step {{ flex: 1; display: flex; }}
.flow-box {{
  flex: 1; background: {BAR_TRACK_COLOR}; border-radius: 16px; padding: 28px 18px;
  text-align: center; display: flex; flex-direction: column; justify-content: center;
}}
.flow-label {{ font-size: 28px; font-weight: 700; color: {NAVY}; margin-bottom: 10px; }}
.flow-caption {{ font-size: 20px; color: {MUTED_COLOR}; line-height: 1.4; }}
.flow-arrow {{ font-size: 40px; color: {BLUE}; font-weight: 700; display: flex; align-items: center; padding: 0 10px; }}
</style>"""
    return style + f'<div class="flow-row">{steps_html}</div>'


def _build_checklist_body(items: list[ChartItem]) -> str:
    rows_html = ""
    for item in items:
        rows_html += f"""
        <div class="check-row">
          <div class="check-icon">✓</div>
          <div class="check-text">
            <div class="check-label">{html.escape(item.label)}</div>
            <div class="check-caption">{html.escape(item.value)}</div>
          </div>
        </div>"""
    style = f"""\
<style>
.check-row {{ display: flex; align-items: flex-start; gap: 22px; margin-bottom: 30px; }}
.check-row:last-child {{ margin-bottom: 0; }}
.check-icon {{
  width: 46px; height: 46px; border-radius: 50%; background: {BLUE}; color: #ffffff;
  display: flex; align-items: center; justify-content: center; font-size: 26px;
  font-weight: 700; flex-shrink: 0;
}}
.check-label {{ font-size: 32px; font-weight: 700; color: {NAVY}; margin-bottom: 6px; }}
.check-caption {{ font-size: 22px; color: {MUTED_COLOR}; line-height: 1.4; }}
</style>"""
    return style + rows_html


def build_chart_html(spec: ChartSpec) -> str:
    if spec.chart_type == "flow":
        body = _build_flow_body(spec.items)
    elif spec.chart_type == "checklist":
        body = _build_checklist_body(spec.items)
    else:
        body = _build_bar_body(spec.items)
    return _card_shell(spec.title, body)


RENDER_TIMEOUT_MS = 15_000  # 이 값 안에 안 끝나면 TimeoutError를 던짐(무한 hang 방지)


def render_chart(spec: ChartSpec, page) -> bytes:
    html_content = build_chart_html(spec)
    page.set_content(html_content, timeout=RENDER_TIMEOUT_MS)
    element = page.query_selector("#card")
    return element.screenshot(type="png", timeout=RENDER_TIMEOUT_MS)


def _safe_print(message: str) -> None:
    """콘솔 인코딩이 메시지 속 문자를 못 다뤄도(예: Windows cp949) 로그 출력 자체가
    새 예외를 던져 폴백 로직을 깨뜨리지 않도록 방어적으로 출력한다."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(message.encode(encoding, errors="replace").decode(encoding))


def _seo_alt_text(title: str, focus_keyword: str) -> str:
    if focus_keyword and focus_keyword not in title:
        return f"{title} - {focus_keyword}"
    return title


def _publish_diagram_image(png_bytes: bytes, filename: str) -> str:
    """도식화 PNG를 이미지 저장소(GitHub + jsDelivr)에 올려 주소를 돌려준다. 저장소가 없거나
    실패하면 예전처럼 워드프레스에 올린다(호출하는 쪽이 예외를 잡아 마커를 제거함)."""
    if image_host.is_configured():
        try:
            return image_host.upload_image(png_bytes, filename)
        except Exception as e:
            _safe_print(f"  - 도식화 이미지 저장소 업로드 실패, 워드프레스로 대체: {type(e).__name__}: {e}")
    return upload_media(png_bytes, filename)["source_url"]


def replace_diagram_markers(
    body_html: str, video_id: str, client, model_name: str, focus_keyword: str = ""
) -> str:
    if not MARKER_PATTERN.search(body_html):
        return body_html

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(timeout=RENDER_TIMEOUT_MS)
            page = browser.new_page(viewport={"width": CARD_WIDTH + 40, "height": 800})
            page.set_default_timeout(RENDER_TIMEOUT_MS)

            def _replace(match: re.Match) -> str:
                marker_text = match.group(1)
                try:
                    spec = extract_chart_spec(marker_text, client, model_name)
                    if spec.chart_type == "skip" or not spec.items:
                        return ""
                    png_bytes = render_chart(spec, page)
                    filename = f"diagram-{video_id}-{uuid.uuid4().hex[:8]}.png"
                    image_url = _publish_diagram_image(png_bytes, filename)
                    alt = _seo_alt_text(spec.title, focus_keyword)
                    return (
                        f'<img src="{image_url}" alt="{html.escape(alt)}" '
                        'style="max-width:50%; display:block; margin:16px auto;" />'
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
