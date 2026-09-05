"""포스팅 대표 인포그래픽 1장을 Gemini 이미지 생성 모델로 만든다.

시각화 방식(구역 개수, 레이아웃, 색상 등)은 프롬프트로 강제하지 않고 모델의 디자인
판단에 맡긴다 — 대신 원문에 없는 사실을 지어내지 않는 것, 정밀 지도류를 넣지 않는 것,
한글 우선 표기 등 "절대 금지사항"만 명확히 지정한다.

실패하면(모델 오류, 타임아웃, 콘텐츠 필터 등) 최대 2회까지 재시도하고, 그래도 실패하면
예외를 삼키고 None을 반환한다 — 대표 이미지 하나가 실패했다고 전체 발행이 막히면 안 되기
때문이다.

이 프롬프트는 램프지니(지니 페르소나) 자동화 트랙 전용이다. 네이버 트랙(서현이 아빠
페르소나) 콘텐츠에는 적용하지 않는다.
"""
import os
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_TIMEOUT_MS = 60_000
MAX_RETRIES = 2  # 최초 1회 + 재시도 최대 2회 = 총 최대 3회 시도

PAPER_BG = "#F7F6F0"


def _body_html_to_plain(body_html: str) -> str:
    """body_html의 HTML 태그를 제거해 읽기 쉬운 평문으로 변환한다(소제목 포함, 원문 그대로)."""
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
- 배경색: 아이보리/페이퍼 톤({PAPER_BG} 계열)
- 이미지 비율: 가로형 와이드 (16:9)
"""


def generate_infographic(title: str, body_html: str) -> bytes | None:
    try:
        client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=IMAGE_TIMEOUT_MS),
        )
    except Exception as e:
        print(f"  - 대표 인포그래픽 생성 실패(클라이언트 초기화, 이미지 없이 계속 진행): {type(e).__name__}: {e}")
        return None

    prompt = build_image_prompt(title, body_html)
    image_config = types.GenerateContentConfig(image_config=types.ImageConfig(aspect_ratio="16:9"))
    total_attempts = MAX_RETRIES + 1
    for attempt in range(1, total_attempts + 1):
        try:
            response = client.models.generate_content(model=IMAGE_MODEL, contents=prompt, config=image_config)
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    return part.inline_data.data
            print(f"  - 대표 인포그래픽 생성 실패(이미지 파트 없음, 시도 {attempt}/{total_attempts})")
        except Exception as e:
            print(f"  - 대표 인포그래픽 생성 실패(시도 {attempt}/{total_attempts}): {type(e).__name__}: {e}")

    print("  - 대표 인포그래픽 생성 최종 실패(이미지 없이 계속 진행)")
    return None


def main():
    # 실제 발행 포맷(prompts.py의 body_html 구조)에 맞춰, 실제 기사
    # (Downloads/bond_yield_article.html)의 사실관계를 그대로 채운 전체 본문.
    sample_body_html = """\
<p>안녕하세요, 지니입니다 \U0001f64c 최근 기업들의 굵직한 수출 소식과 사상 최대 실적
소식이 쏟아지는데도, 왠지 주식 시장 분위기나 지갑 사정은 묘하게 쌀쌀맞게 느껴지지
않으신가요?</p>
<blockquote>내가 가진 자산은 수출 호황의 온기를 제대로 받고 있을까, 아니면 치솟는 금리
파도에 갇혀 있는 걸까?</blockquote>
<h2>1. 글로벌 채권 시장을 덮친 '고금리의 역습'</h2>
<p>미국 30년물 국채금리가 5.27%를 넘기며 2007년 금융위기 직전 수준까지 치솟았습니다.
일본 10년물 국채금리는 장중 3.0% 안팎까지 올라 1996년 이후 약 30년 만의 최고치를
기록했고, 영국 30년물 국채금리도 1998년 이후 최고 수준인 5.9%에 육박했습니다.</p>
<h2>2. 역대급 세수 풍년과 '지출의 디테일'</h2>
<p>내년도 예산안에서 총수입이 880조 원을 웃돌고 총지출 역시 821조 원이라는 역대급
규모로 편성되었습니다. 160조 원 규모의 미래대응 기금이 피지컬 AI와 반도체 클러스터
인프라에 투입될 예정입니다.</p>
<h2>3. 뼈를 깎는 재정 다이어트와 교부금 개편</h2>
<p>정부는 100조 원이 넘는 지출 구조조정을 단행하며, 오랜 성역으로 여겨졌던 지방교육재정
교부금의 내국세 연동 방식을 손보기로 했습니다.</p>
<h2>4. 8월 수출 982억 달러, 그러나 비어 있는 온기</h2>
<p>8월 수출액은 전년 대비 68.7% 급증한 982억 5천만 달러를 찍으며 역대 8월 실적 중
압도적인 기록을 세웠습니다. 반도체 월간 수출은 466억 5천만 달러를 돌파하며
신기록을 썼습니다.</p>
<blockquote><strong>\U0001f4a1 지니의 생각</strong> 지금은 화려한 외형 성장 수치에
취하기보다, 내 자산 포트폴리오가 이 끈질긴 고금리 파도를 버텨낼 수 있는지 안전벨트부터
단단히 조여야 할 시점이라고 봅니다.</blockquote>
<h2>정리하며</h2>
<p>글로벌 금리의 구조적 고공행진, 역대급 세수 유입에 따른 인프라 예산 집행과 재정
개혁, 그리고 사상 최고치를 달리는 수출 실적까지 세 가지 톱니바퀴가 숨 가쁘게 맞물려
돌아가고 있습니다.</p>
<p>오늘도 읽어주셔서 감사합니다 \U0001f60a.</p>
<p><em>이 글은 정보 제공을 목적으로 하며, 투자·청약·법률 판단의 근거로 사용하지
마세요.</em></p>
<p>#국채금리 #반도체수출 #재정예산안 #지방교육재정교부금 #경제공부</p>
"""
    png_bytes = generate_infographic("수출 대박에도 웃지 못하는 국채금리의 역습", sample_body_html)
    if png_bytes is None:
        print("생성 실패")
        return
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "infographic_preview.png"
    )
    with open(out_path, "wb") as f:
        f.write(png_bytes)
    print(f"저장됨: {out_path} ({len(png_bytes)} bytes)")


if __name__ == "__main__":
    main()
