"""서현이 아빠 대표 인포그래픽(2:1 와이드) 생성 — `infographic_generator.py`(지니)의
네이버용 자매 모듈. 나노바나나2로 이미지를 만든 뒤, 실제 로고 파일을 Pillow로 합성한다
(로고를 텍스트로 설명해서 이미지 생성 모델이 재현하게 하면 형태가 왜곡될 수 있어,
실제 로고 PNG를 그대로 합성하는 방식을 택했다).

실패하면(모델 오류, 타임아웃, 콘텐츠 필터 등) 최대 2회까지 재시도하고, 그래도 실패하면
예외를 삼키고 None을 반환한다.
"""
import io
import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_TIMEOUT_MS = 60_000
MAX_RETRIES = 2

NAVY = "#132A46"
BLUE = "#3B82D9"

# Gemini 이미지 모델은 "2:1"을 직접 지원하지 않는다(지원값: 1:1/2:3/3:2/3:4/4:3/9:16/
# 16:9/21:9). 2:1(=1080x540 비율)보다 넓은 21:9로 생성한 뒤 가운데 기준으로 좌우를
# 잘라내 정확히 2:1을 맞춘다.
GEN_ASPECT_RATIO = "21:9"

LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "logo", "서현이 아빠 로고.png"
)


def _body_html_to_plain(body_html: str) -> str:
    text = re.sub(r"<!--.*?-->", "", body_html, flags=re.S)
    text = re.sub(r"</h2>|</p>|</blockquote>|</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text


def build_image_prompt(title: str, body_html: str) -> str:
    plain_body = _body_html_to_plain(body_html)
    return f"""\
아래 포스팅 원문 전체를 요약하는 일러스트 스타일의 인포그래픽 이미지를 만들어라.
어떻게 시각화할지는 전적으로 너의 디자인 판단에 맡긴다.

[포스팅 원문 전체]
제목: {title}

{plain_body}

절대 금지사항 (예외 없이 지켜야 함):
1. 위 원문에 실제로 없는 숫자, 통계, 사실관계, 해설, 전망을 새로 만들어내지 마라.
2. 데이터 신뢰성에 의문을 다는 문구(예: "임의의 예시값")를 절대 넣지 마라 — 여기 있는
모든 수치는 전부 실제 데이터이다.
3. 사진, 사람 얼굴, 실존 기업/브랜드 로고를 넣지 마라.
4. 지하철 노선도, 정밀 지도 등 정확한 지리 정보가 필요한 그래픽은 넣지 마라.
5. 이미지 안의 모든 텍스트는 한글을 우선 사용하고, 정확한 철자로 선명하게 렌더링되어야
한다 (영문 라벨 지양, 오탈자·깨진 글자 금지).

고정 사항:
- 색상: 네이비({NAVY})와 블루({BLUE}) 두 계열 위주. 배경은 흰색 또는 아주 옅은 톤.
- 가로로 넓은 와이드 배너 형태.
"""


def _crop_to_2_1(png_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    target_w = h * 2
    if target_w < w:
        left = (w - target_w) // 2
        img = img.crop((left, 0, left + target_w, h))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _composite_logo(png_bytes: bytes) -> bytes:
    if not os.path.exists(LOGO_PATH):
        print(f"  - 로고 파일 없음({LOGO_PATH}), 로고 없이 계속 진행")
        return png_bytes

    base = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    logo = Image.open(LOGO_PATH).convert("RGBA")

    logo_h = max(int(base.height * 0.18), 70)
    logo_w = int(logo.width * (logo_h / logo.height))
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

    margin = int(base.height * 0.05)
    pos = (base.width - logo_w - margin, base.height - logo_h - margin)
    base.alpha_composite(logo, dest=pos)

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def generate_infographic(title: str, body_html: str) -> bytes | None:
    try:
        client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=IMAGE_TIMEOUT_MS),
        )
    except Exception as e:
        print(f"  - 서현이 아빠 인포그래픽 생성 실패(클라이언트 초기화, 이미지 없이 계속 진행): {type(e).__name__}: {e}")
        return None

    prompt = build_image_prompt(title, body_html)
    image_config = types.GenerateContentConfig(image_config=types.ImageConfig(aspect_ratio=GEN_ASPECT_RATIO))
    total_attempts = MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        try:
            response = client.models.generate_content(model=IMAGE_MODEL, contents=prompt, config=image_config)
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    png_bytes = _crop_to_2_1(part.inline_data.data)
                    png_bytes = _composite_logo(png_bytes)
                    return png_bytes
            print(f"  - 서현이 아빠 인포그래픽 생성 실패(이미지 파트 없음, 시도 {attempt}/{total_attempts})")
        except Exception as e:
            print(f"  - 서현이 아빠 인포그래픽 생성 실패(시도 {attempt}/{total_attempts}): {type(e).__name__}: {e}")

    print("  - 서현이 아빠 인포그래픽 생성 최종 실패(이미지 없이 계속 진행)")
    return None


def main():
    sample_body_html = """\
<h2>1. 지수는 껑충 뛰었는데 대기 자금은 5조 원 증발?</h2>
<p>코스피 지수는 전 거래일 대비 107.73포인트(1.64%) 오르며 6,687.21까지 올랐습니다.
투자자예탁금은 1거래일 만에 약 5조 원 줄어 97조 7,614억 원으로 내려앉았습니다.</p>
<h2>2. 3.7조 쏟아낸 개미, 그 물량을 받아낸 손</h2>
<p>개인은 3조 7,224억 원 순매도, 외국인은 5,034억 원, 기관은 1조 6,691억 원 순매수로
받아냈습니다.</p>
"""
    png_bytes = generate_infographic("코스피 반등 속 예탁금 5조 급감한 이유", sample_body_html)
    if png_bytes is None:
        print("생성 실패")
        return
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "naver_infographic_preview.png"
    )
    with open(out_path, "wb") as f:
        f.write(png_bytes)
    print(f"저장됨: {out_path} ({len(png_bytes)} bytes)")


if __name__ == "__main__":
    main()
