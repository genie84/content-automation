"""네이버 블로그(서현이 아빠) 발행 자동화 — 이 스크립트는 로컬 PC에서만 실행한다
(GitHub Actions 등 클라우드 러너에서는 실행하지 않음).

인증 방식: 매 실행마다 로그인을 자동화하지 않는다(네이버의 "새 기기/새 위치 로그인"
탐지에 걸릴 위험이 커서). 대신 Playwright의 영구 브라우저 프로필
(`data/naver_browser_profile/`, git 추적 제외)에 최초 1회 사람이 직접 로그인한 세션을
저장해두고, 이후 실행은 그 프로필을 재사용해 로그인 단계 자체를 건너뛴다.

이 파일에는 아직 "실제 에디터에 서식을 입히는" 자동화는 없다 — 네이버 스마트에디터의
실제 DOM 구조를 확인한 뒤(로그인 시 함께 확인) 추가할 예정.
"""
import json
import os
import time

from playwright.sync_api import sync_playwright

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PROFILE_DIR = os.path.join(DATA_DIR, "naver_browser_profile")
PENDING_DRAFT_PATH = os.path.join(DATA_DIR, "naver_draft_pending.json")
PENDING_IMAGE_PATH = os.path.join(DATA_DIR, "naver_infographic_pending.png")

LOGIN_URL = "https://nid.naver.com/nidlogin.login"
BLOG_HOME_URL = "https://blog.naver.com/"

LOGIN_WAIT_TIMEOUT_SEC = 300  # 사람이 직접 로그인할 시간(5분)
LOGIN_POLL_INTERVAL_SEC = 2


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


def is_logged_in(page) -> bool:
    page.goto(BLOG_HOME_URL, wait_until="domcontentloaded", timeout=30_000)
    # 로그인 안 된 상태로 blog.naver.com에 접근하면 로그인 페이지로 리다이렉트되거나
    # 로그인 페이지 도메인(nid.naver.com)으로 이동한다.
    return "nid.naver.com" not in page.url


def login_and_explore():
    """영구 프로필로 브라우저를 띄운다. 이미 로그인돼 있으면 바로 탐색 단계로,
    아니면 사람이 직접 로그인할 때까지 기다린 뒤 블로그 홈/글쓰기 화면을 저장한다."""
    os.makedirs(PROFILE_DIR, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        if is_logged_in(page):
            print("이미 로그인된 세션입니다 — 로그인 단계 건너뜀.")
        else:
            print(f"브라우저 창에서 네이버에 직접 로그인해주세요 (최대 {LOGIN_WAIT_TIMEOUT_SEC}초 대기).")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
            waited = 0
            logged_in = False
            while waited < LOGIN_WAIT_TIMEOUT_SEC:
                time.sleep(LOGIN_POLL_INTERVAL_SEC)
                waited += LOGIN_POLL_INTERVAL_SEC
                try:
                    if "nid.naver.com" not in page.url and page.url != LOGIN_URL:
                        # 로그인 성공 시 blog.naver.com 등으로 리다이렉트되거나
                        # naver.com 메인으로 이동함. 재확인.
                        if is_logged_in(page):
                            logged_in = True
                            break
                except Exception:
                    continue
            if not logged_in:
                print(f"{LOGIN_WAIT_TIMEOUT_SEC}초 안에 로그인이 확인되지 않았습니다. 다시 실행해주세요.")
                context.close()
                return

            print("로그인 확인됨. 세션이 로컬 프로필에 저장되었습니다(다음부터는 자동 재사용).")

        # 블로그 ID 확인 + 에디터 구조 파악용 스냅샷 저장(추후 실제 서식 자동화 개발에 사용)
        blog_id = None
        try:
            href = page.eval_on_selector("a[href*='blog.naver.com/']", "el => el.href")
            if href:
                blog_id = href.split("blog.naver.com/")[-1].split("/")[0].split("?")[0]
        except Exception:
            pass

        print(f"현재 페이지: {page.url}")
        if blog_id:
            print(f"블로그 ID로 추정됨: {blog_id}")
            write_url = f"https://blog.naver.com/{blog_id}?Redirect=Write"
            page.goto(write_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)

        os.makedirs(DATA_DIR, exist_ok=True)
        screenshot_path = os.path.join(DATA_DIR, "naver_editor_snapshot.png")
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"화면 스냅샷 저장: {screenshot_path}")

        html_dump_path = os.path.join(DATA_DIR, "naver_editor_dom.html")
        with open(html_dump_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"DOM 덤프 저장: {html_dump_path}")

        context.close()


if __name__ == "__main__":
    login_and_explore()
