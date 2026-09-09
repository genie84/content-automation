"""네이버 스마트에디터 ONE(SE ONE) 실제 서식 자동화 — 클립보드 붙여넣기 방식(v2).

[배경] 처음엔 툴바 버튼을 하나씩 클릭하며 조립하는 방식으로 만들었는데(제목/문단/
소제목 스타일/강조/인용구/표), 인용구·표처럼 팝업/컴포넌트 삽입이 끼는 지점마다
스마트에디터의 비동기 렌더링과 경합이 나서 내용 순서가 실행마다 다르게 꼬였다(9차례
반복 테스트로 확인). 합성 클립보드 이벤트(`dispatchEvent(new ClipboardEvent('paste'))`)
도 시도했지만 신뢰 안 된 이벤트로 무시당했다.

[해결] 실제 OS 클립보드에 `navigator.clipboard.write()`로 HTML을 쓰고, 진짜
`Control+V` 키 입력을 보내는 방식으로 바꾸니 완전히 안정적으로 동작했다 — 순서/구조
(진짜 표·인용구 컴포넌트로 변환됨)/색상(인라인 style이 그대로 살아남음)까지 한 번에
해결됨. 브라우저 컨텍스트에 clipboard-read/write 권한을 미리 허용해야 한다
(`context.grant_permissions(["clipboard-read", "clipboard-write"])`).

[색상 제약] 인라인 style의 hex 색상은 그대로 반영되므로, 다른 곳(툴바 색상 피커)과
달리 원하는 정확한 hex(#132A46, #3B82D9)를 그대로 쓸 수 있다 — 툴바 팔레트의 71개
사전색으로 제한됐던 문제가 이 방식에서는 해당 없음.
"""
import time

NAVY = "#132A46"
BLUE = "#3B82D9"
WHITE = "#ffffff"

PASTE_SETTLE_SEC = 1.5


def dismiss_resume_popup(frame, page) -> None:
    """"작성 중인 글이 있습니다" 이어쓰기 팝업이 뜨면 취소(새 글로 시작)한다."""
    cancel_btn = frame.locator(".se-popup-button-cancel")
    if cancel_btn.count() > 0:
        cancel_btn.first.click(timeout=5000)
        time.sleep(0.3)


def dismiss_tooltip(page) -> None:
    try:
        page.keyboard.press("Escape")
        time.sleep(0.2)
    except Exception:
        pass


def set_title(frame, page, title: str) -> None:
    title_el = frame.locator(".se-documentTitle .se-text-paragraph").first
    title_el.click(timeout=5000)
    page.keyboard.type(title)


def click_body(frame) -> None:
    """제목이 아닌 본문 영역(첫 텍스트 컴포넌트)을 클릭해 커서를 둔다."""
    frame.locator(".se-component.se-text .se-text-paragraph").first.click(timeout=5000)


def paste_html(frame, page, html_content: str) -> None:
    """스타일이 입혀진 HTML을 실제 OS 클립보드에 쓰고 진짜 Ctrl+V로 붙여넣는다.

    호출 전에 `context.grant_permissions(["clipboard-read", "clipboard-write"])`가
    돼 있어야 한다(권한 없으면 navigator.clipboard.write가 예외를 던진다)."""
    plain_text = frame.evaluate(
        "(html) => { const d = document.createElement('div'); d.innerHTML = html; return d.textContent; }",
        html_content,
    )
    page.evaluate(
        """
        async ({html, plain}) => {
          const htmlBlob = new Blob([html], {type: 'text/html'});
          const textBlob = new Blob([plain], {type: 'text/plain'});
          const item = new ClipboardItem({'text/html': htmlBlob, 'text/plain': textBlob});
          await navigator.clipboard.write([item]);
        }
        """,
        {"html": html_content, "plain": plain_text},
    )
    time.sleep(0.3)
    page.keyboard.press("Control+V")
    time.sleep(PASTE_SETTLE_SEC)
