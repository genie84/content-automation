"""포스팅 대표 인포그래픽(제목+핵심 3줄 요약 카드) 1장을 Gemini 이미지 생성 모델로 만든다.

실패하면(모델 오류, 타임아웃, 콘텐츠 필터 등) 예외를 삼키고 None을 반환한다 —
대표 이미지 하나가 실패했다고 전체 발행이 막히면 안 되기 때문이다.
"""
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_TIMEOUT_MS = 60_000

# Downloads/bond_yield_article.html(매거진 템플릿 참고 파일)에서 실측한 톤.
# 골드/올리브라고 전달받았지만 실제 파일은 골드+짙은 그린잉크 배색이고 폰트도
# Pretendard가 아니라 Gowun Batang(세리프)+IBM Plex였다 — 실측값을 기준으로 씀.
GOLD_ACCENT = "#A3781F"
PAPER_BG = "#F7F6F0"
INK_COLOR = "#1F2E27"


def build_image_prompt(title: str, summary_lines: list[str]) -> str:
    bullets = "\n".join(f"- {line}" for line in summary_lines)
    return f"""\
경제 매거진 표지에 어울리는, 절제되고 고급스러운 플랫 에디토리얼 인포그래픽 카드 이미지를
만들어라. 사진이나 사람 얼굴은 절대 넣지 말고, 타이포그래피 중심의 미니멀한 디자인이어야 한다.

레이아웃 지시:
- 배경: 아이보리/페이퍼 톤({PAPER_BG} 계열), 은은한 종이 질감
- 상단: 얇은 골드 색({GOLD_ACCENT} 계열) 가로 구분선 또는 라벨 하나
- 중앙: 굵은 세리프체(한국 명조 느낌)로 큰 제목 — "{title}"
- 하단: 아래 3개 요약 문장을 짧은 불릿이나 번호로 정갈하게 배치:
{bullets}
- 텍스트 색상: 짙은 그린빛 잉크 톤({INK_COLOR})
- 비율: 세로형 카드(1080x1350에 가까운 비율)
- 한국어 텍스트가 정확한 철자로 선명하게 렌더링되어야 한다(글자가 깨지거나 뭉개지면 안 됨).
"""


def generate_infographic(title: str, summary_lines: list[str]) -> bytes | None:
    try:
        client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=IMAGE_TIMEOUT_MS),
        )
        prompt = build_image_prompt(title, summary_lines)
        response = client.models.generate_content(model=IMAGE_MODEL, contents=prompt)
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
        print("  - 대표 인포그래픽 생성 실패(이미지 파트 없음, 이미지 없이 계속 진행)")
        return None
    except Exception as e:
        print(f"  - 대표 인포그래픽 생성 실패(이미지 없이 계속 진행): {type(e).__name__}: {e}")
        return None


def main():
    png_bytes = generate_infographic(
        "9월 증시를 덮친 삼중고와 살아남기",
        [
            "코스피가 매크로 악재에 4% 가깝게 폭락하며 6,560선까지 밀렸습니다.",
            "미국 국채금리 4.8% 돌파, 유가 90달러 돌파라는 이중 악재가 겹쳤습니다.",
            "'5-100-100' 지표 관찰과 현금 확보가 시급한 시점입니다.",
        ],
    )
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
