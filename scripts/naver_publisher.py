"""네이버 블로그(서현이 아빠) 발행 자동화 — 이 스크립트는 로컬 PC에서만 실행한다
(GitHub Actions 등 클라우드 러너에서는 실행하지 않음).

인증 방식: 매 실행마다 로그인을 자동화하지 않는다(네이버의 "새 기기/새 위치 로그인"
탐지에 걸릴 위험이 커서). 대신 최초 1회 사람이 직접 로그인한 세션을
`data/naver_storage_state.json`(쿠키 스냅샷, git 추적 제외)에 저장해두고, 이후 실행은
그 파일을 재사용해 로그인 단계 자체를 건너뛴다.

(v2, 2026-09-07): 처음엔 Playwright의 "영구 브라우저 프로필"(user_data_dir 방식)을
썼는데, 두 가지 문제로 폐기함 —
1. 이전 실행이 비정상 종료되면 프로필 폴더가 잠겨서 다음 실행이 로그인 세션을 못 읽음.
2. 결정적으로, 네이버의 로그인 쿠키(NID_AUT/NID_SES)가 세션 전용(브라우저를 깨끗하게
   종료하면 삭제됨)으로 발급되는데, user_data_dir 방식은 종료 시 크로미움이 세션
   쿠키를 지워버려서 로그인이 매번 사라졌음(실제로 겪음).
지금은 `context.storage_state()`로 쿠키를 명시적으로 스냅샷 저장한다 — 이건 세션 쿠키도
그대로 파일에 담기고, 브라우저 종료 방식과 무관하게 남는다.

(v3, 2026-09-09): 실제 서식 자동화 추가. 처음엔 "네이버가 헤드리스를 탐지해서 로그인이
안 먹힌다"고 잘못 판단했었는데, 다시 보니 그때는 storage_state 자체가 무효했던 것뿐이고,
유효한 storage_state로는 헤드리스로도 정상 동작함을 확인함 — 사람이 매번 옆에 있을
필요 없이 완전 자동 실행이 가능하다.

(v4, 2026-09-09): 서식 자동화 방식을 "툴바 버튼을 하나씩 클릭하며 조립" → "완성된
스타일 HTML을 클립보드에 써서 한 번에 붙여넣기"로 전면 교체. 툴바 클릭 방식은 인용구/표
삽입 지점마다 에디터의 비동기 렌더링과 경합해서 내용 순서가 실행마다 다르게 꼬이는
문제가 9차례 반복 테스트로도 안 잡혔다 — 클립보드 붙여넣기는 한 번에 안정적으로 성공함
(자세한 내용은 `naver_editor_actions.py` 상단 참고).
"""
import html
import json
import os
import re
import time

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from scripts import naver_editor_actions as actions

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STORAGE_STATE_PATH = os.path.join(DATA_DIR, "naver_storage_state.json")
PENDING_DRAFT_PATH = os.path.join(DATA_DIR, "naver_draft_pending.json")
PENDING_IMAGE_PATH = os.path.join(DATA_DIR, "naver_infographic_pending.png")

LOGIN_URL = "https://nid.naver.com/nidlogin.login"

LOGIN_WAIT_TIMEOUT_SEC = 300  # 사람이 직접 로그인할 시간(5분)
LOGIN_POLL_INTERVAL_SEC = 2
# 로그인 후 화면을 확인할 수 있도록 창을 바로 닫지 않고 이만큼 더 유지한다.
POST_ACTION_LINGER_SEC = 15


def save_pending_draft(title: str, summary_lines: list[str], table_rows: list[dict], body_html: str, topic: str, category_label: str, image_bytes: bytes | None) -> None:
    """지니 트랙(main.py, 클라우드)이 같은 리서치 결과로 만든 서현이 아빠 초안을 로컬
    대기열에 저장한다. 실제 네이버 발행은 로컬에서 이 스크립트를 실행할 때 이뤄진다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PENDING_DRAFT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": title,
                "summary_lines": summary_lines,
                "table_rows": table_rows,
                "body_html": body_html,
                "topic": topic,
                "category_label": category_label,
                "has_image": image_bytes is not None,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    if image_bytes is not None:
        with open(PENDING_IMAGE_PATH, "wb") as f:
            f.write(image_bytes)


def load_pending_draft() -> dict | None:
    if not os.path.exists(PENDING_DRAFT_PATH):
        return None
    with open(PENDING_DRAFT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def clear_pending_draft() -> None:
    for path in (PENDING_DRAFT_PATH, PENDING_IMAGE_PATH):
        if os.path.exists(path):
            os.remove(path)


def _on_login_form(page) -> bool:
    """네이버 로그인 페이지의 아이디 입력창이 실제로 보이는지로 판단한다(도메인만으로
    판단하면 오탐이 있었음 — blog.naver.com 루트는 비로그인 상태에서도 nid.naver.com으로
    리다이렉트되지 않아서 "이미 로그인됨"으로 잘못 판단한 적이 있음)."""
    try:
        return page.locator("#id").is_visible(timeout=3000)
    except Exception:
        return False


def login_and_explore(blog_id: str | None = None):
    """저장된 storage_state가 있으면 그 세션으로 브라우저를 띄우고, 없거나 만료됐으면
    로그인 페이지를 띄운다. 로그인 페이지의 아이디 입력창이 보이면 사람이 직접 로그인할
    때까지 기다리고, 로그인이 확인되는 즉시(그리고 끝에서 한 번 더) storage_state를
    디스크에 저장한다 — 브라우저 종료 타이밍과 무관하게 세션 쿠키가 남도록.
    blog_id를 안 주면 .env의 NAVER_BLOG_ID를 쓴다(둘 다 없으면 블로그 홈만 확인) —
    페이지에서 아무 링크나 주워 블로그 ID를 추측하지 않는다(전에 엉뚱한 블로그로
    이동한 원인이 이거였음)."""
    blog_id = blog_id or os.environ.get("NAVER_BLOG_ID")
    storage_state = STORAGE_STATE_PATH if os.path.exists(STORAGE_STATE_PATH) else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=storage_state, viewport={"width": 1280, "height": 900})
        page = context.new_page()

        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        time.sleep(1)

        if _on_login_form(page):
            print(f"브라우저 창에서 네이버에 직접 로그인해주세요 (최대 {LOGIN_WAIT_TIMEOUT_SEC}초 대기).")
            waited = 0
            logged_in = False
            while waited < LOGIN_WAIT_TIMEOUT_SEC:
                time.sleep(LOGIN_POLL_INTERVAL_SEC)
                waited += LOGIN_POLL_INTERVAL_SEC
                try:
                    if not _on_login_form(page) and "nidlogin" not in page.url:
                        logged_in = True
                        break
                except Exception:
                    continue
            if not logged_in:
                print(f"{LOGIN_WAIT_TIMEOUT_SEC}초 안에 로그인이 확인되지 않았습니다. 다시 실행해주세요.")
                context.close()
                browser.close()
                return

            os.makedirs(DATA_DIR, exist_ok=True)
            context.storage_state(path=STORAGE_STATE_PATH)
            print(f"로그인 확인됨. 세션을 저장했습니다: {STORAGE_STATE_PATH} (다음부터는 자동 재사용).")
        else:
            print("이미 로그인된 세션입니다 — 로그인 단계 건너뜀.")

        if blog_id:
            write_url = f"https://blog.naver.com/{blog_id}?Redirect=Write"
            page.goto(write_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
        else:
            print("NAVER_BLOG_ID가 없어서 블로그 글쓰기 화면 대신 로그인 상태만 확인합니다.")
            print(".env에 NAVER_BLOG_ID=본인블로그아이디 를 추가하면 다음부터 글쓰기 화면까지 자동으로 엽니다.")

        print(f"현재 페이지: {page.url}")

        # 도움말 팝업이 열려있으면 화면을 가리므로 닫는다(있으면).
        try:
            page.keyboard.press("Escape")
            time.sleep(0.5)
        except Exception:
            pass

        os.makedirs(DATA_DIR, exist_ok=True)
        screenshot_path = os.path.join(DATA_DIR, "naver_editor_snapshot.png")
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"화면 스냅샷 저장: {screenshot_path}")

        # 네이버 블로그 에디터는 iframe(#mainFrame) 안에 있고, 그 안에 스마트에디터
        # 자체 iframe이 또 있을 수 있다. page.content()는 최상위 문서만 담기고 iframe
        # 내부는 안 잡히므로, 모든 프레임을 각각 순회하며 따로 저장한다.
        frames_dir = os.path.join(DATA_DIR, "naver_editor_frames")
        os.makedirs(frames_dir, exist_ok=True)
        print(f"프레임 {len(page.frames)}개 발견:")
        for i, frame in enumerate(page.frames):
            print(f"  [{i}] name={frame.name!r} url={frame.url}")
            try:
                content = frame.content()
            except Exception as e:
                print(f"      (내용 못 가져옴: {type(e).__name__}: {e})")
                continue
            dump_path = os.path.join(frames_dir, f"frame_{i}.html")
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(content)
        print(f"프레임별 DOM 덤프 저장 위치: {frames_dir}")

        # 마지막에 한 번 더 저장(위에서 이미 저장했어도 안전망으로).
        os.makedirs(DATA_DIR, exist_ok=True)
        context.storage_state(path=STORAGE_STATE_PATH)

        print(f"확인하실 수 있도록 {POST_ACTION_LINGER_SEC}초 더 창을 열어둡니다...")
        time.sleep(POST_ACTION_LINGER_SEC)
        context.close()
        browser.close()


BLOCK_PATTERN = re.compile(r"<(h2|p|blockquote)>(.*?)</\1>", re.S)
TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")


def parse_body_blocks(body_html: str) -> list[tuple[str, str]]:
    """body_html을 (태그, 내용) 순서 목록으로 쪼갠다. 도식화 HTML 주석은 네이버 자동화
    범위 밖이라 제거한다(원래도 방문자에게 안 보이는 마커)."""
    body_html = re.sub(r"<!--.*?-->", "", body_html, flags=re.S)
    return [(m.group(1), m.group(2).strip()) for m in BLOCK_PATTERN.finditer(body_html)]


def _strip_tags(html_fragment: str) -> str:
    return TAG_STRIP_PATTERN.sub("", html_fragment).strip()


_STRONG_PATTERN = re.compile(r"<strong>(.*?)</strong>", re.S)


def _build_paragraph_html(html_fragment: str) -> str:
    """<strong>단어</strong>만 굵게+블루 인라인 style로 감싸고, 나머지는 이스케이프한
    일반 텍스트로 둔 <p>를 만든다."""
    parts = []
    pos = 0
    for m in _STRONG_PATTERN.finditer(html_fragment):
        pre = html_fragment[pos : m.start()]
        if pre:
            parts.append(html.escape(pre))
        parts.append(
            f'<strong style="color:{actions.BLUE}; font-weight:bold;">{html.escape(m.group(1))}</strong>'
        )
        pos = m.end()
    rest = html_fragment[pos:]
    if rest:
        parts.append(html.escape(rest))
    return f"<p>{''.join(parts)}</p>"


def _build_table_html(table_rows: list[dict]) -> str:
    if not table_rows:
        return ""
    headers = list(table_rows[0].keys())
    header_cells = "".join(
        f'<td style="background-color:{actions.NAVY}; color:{actions.WHITE}; font-weight:bold;">{html.escape(h)}</td>'
        for h in headers
    )
    body_rows = ""
    for row in table_rows:
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row.values())
        body_rows += f"<tr>{cells}</tr>"
    return f"<table><tr>{header_cells}</tr>{body_rows}</table>"


def build_styled_body_html(body_html: str, table_rows: list[dict]) -> str:
    """우리 body_html(h2/p/blockquote, <strong> 강조 마커)을 네이버 에디터가 그대로
    받아들이는, 색상까지 인라인 style로 입힌 HTML로 변환한다(붙여넣기 한 번으로 처리).
    table_rows는 본문 첫 자가진단 인용구 바로 다음에 끼워 넣는다(지니/워드프레스 트랙의
    "요약박스+표를 글 앞쪽에" 배치와 같은 취지)."""
    parts = []
    table_rows = table_rows or []
    table_inserted = not table_rows

    for tag, inner in parse_body_blocks(body_html):
        if tag == "h2":
            text = _strip_tags(inner)
            parts.append(
                f'<h2 style="color:{actions.NAVY}; font-weight:bold; font-size:19pt;">{html.escape(text)}</h2>'
            )
        elif tag == "blockquote":
            strong_match = re.search(r"<strong>(.*?)</strong>", inner)
            if strong_match and "생각" in strong_match.group(1):
                # 문서 스펙은 "배경 박스(연한 노랑/회색)"였는데, 실제로 <p style=
                # "background-color">는 붙여넣기 시 사라짐(표 셀은 되는데 문단은 안 됨 —
                # 실측 확인). 시각적으로 확실히 구분되는 인용구 스타일로 대체.
                label = _strip_tags(strong_match.group(1))
                rest = _strip_tags(re.sub(r"<strong>.*?</strong>", "", inner))
                parts.append(
                    f'<blockquote><strong style="color:{actions.NAVY};">{html.escape(label)}</strong> '
                    f"{html.escape(rest)}</blockquote>"
                )
            else:
                parts.append(f"<blockquote>{html.escape(_strip_tags(inner))}</blockquote>")
                if not table_inserted:
                    parts.append(_build_table_html(table_rows))
                    table_inserted = True
        elif tag == "p":
            parts.append(_build_paragraph_html(inner))

    if not table_inserted:
        parts.append(_build_table_html(table_rows))

    return "\n".join(parts)


def apply_formatting(frame, page, content: dict) -> None:
    """대기 중인 초안(content: title/body_html/table_rows)을 에디터에 실제로 입력한다."""
    actions.dismiss_resume_popup(frame, page)
    actions.dismiss_tooltip(page)

    actions.set_title(frame, page, content["title"])
    actions.click_body(frame)
    time.sleep(0.3)

    styled_body_html = build_styled_body_html(content["body_html"], content.get("table_rows") or [])
    actions.paste_html(frame, page, styled_body_html)


def save_as_draft(frame) -> None:
    """"저장"(임시저장) 버튼을 누른다 — "발행" 버튼은 절대 누르지 않는다(최종 발행은
    사람이 직접 확인 후 하는 게 이 프로젝트의 원칙). CSS 모듈 해시 클래스(예:
    save_btn__bzc5B)는 배포마다 바뀔 수 있어서 실제로 하루 만에 셀렉터가 깨진 적이
    있음 — data-click-area(의미 기반 속성)를 대신 쓴다."""
    frame.locator('[data-click-area="tpb.save"]').first.click(timeout=5000)
    time.sleep(2)


def publish_pending_draft_to_naver(blog_id: str | None = None) -> bool:
    """대기 중인 초안이 있으면 네이버 에디터에 서식을 입혀 임시저장까지 한다.
    발행(publish)은 절대 하지 않는다 — 사용자가 네이버 화면에서 직접 확인 후 클릭한다.
    성공하면 True, 대기 중인 초안이 없거나 실패하면 False."""
    content = load_pending_draft()
    if content is None:
        print("대기 중인 네이버 초안이 없습니다.")
        return False

    blog_id = blog_id or os.environ.get("NAVER_BLOG_ID")
    if not blog_id:
        print("NAVER_BLOG_ID가 설정되어 있지 않습니다. .env에 추가해주세요.")
        return False

    storage_state = STORAGE_STATE_PATH if os.path.exists(STORAGE_STATE_PATH) else None
    if storage_state is None:
        print("저장된 네이버 로그인 세션이 없습니다. 먼저 login_and_explore()로 로그인해주세요.")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state, viewport={"width": 1280, "height": 900})
        # 클립보드 붙여넣기 방식(actions.paste_html)에 필요 — 없으면
        # navigator.clipboard.write()가 권한 오류를 던진다.
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()
        try:
            page.goto(f"https://blog.naver.com/{blog_id}?Redirect=Write", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)

            # mainFrame이 아직 안 붙어있을 때가 가끔 있어서(StopIteration 실제 발생함)
            # 몇 번 재시도한다.
            frame = None
            for _ in range(5):
                frame = next((f for f in page.frames if f.name == "mainFrame"), None)
                if frame is not None:
                    break
                page.wait_for_timeout(1000)
            if frame is None:
                raise RuntimeError("mainFrame을 찾지 못했습니다(페이지 로딩 실패 가능성)")

            apply_formatting(frame, page, content)

            os.makedirs(DATA_DIR, exist_ok=True)
            page.screenshot(path=os.path.join(DATA_DIR, "naver_draft_result.png"))

            save_as_draft(frame)
            context.storage_state(path=STORAGE_STATE_PATH)
            print("네이버 임시저장 완료. 최종 발행은 네이버 블로그 화면에서 직접 확인 후 진행해주세요.")
            clear_pending_draft()
            return True
        except Exception as e:
            print(f"네이버 발행 자동화 실패: {type(e).__name__}: {e}")
            os.makedirs(DATA_DIR, exist_ok=True)
            page.screenshot(path=os.path.join(DATA_DIR, "naver_draft_error.png"))
            return False
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    login_and_explore()
