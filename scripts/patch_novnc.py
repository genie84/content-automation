"""noVNC를 복사해 한글 입력 우회 패치를 적용한다 — 폰에서 한글이 안 들어가는 문제(2026-09-21) 대응.

원인: 폰 → noVNC → x11vnc → 서버 화면(Xvfb) → Chromium 경로에서, 한글 같은 유니코드 글자는 x11vnc가 남는
키코드에 임시로 매핑해서 넣는데(xkb tweak), 서버의 Chromium이 그 임시 매핑 키를 무시한다(키 이벤트는 서버까지
도착함을 x11vnc 진단 로그로 확인). 영문·숫자는 원래 키보드 배열에 있는 키라서 정상 동작한다.

우회: 라틴 범위를 넘는 유니코드 키는 ASCII 이스케이프 `16진수코드`(예: 살 → `c0b4`, 백틱으로 감쌈)로 바꿔서
보내고, 서버의 로그인 브라우저(naver_publisher.HANGUL_BRIDGE_JS)가 키 입력 단계에서 그걸 가로채 실제 글자를
"타이핑한 것처럼" 넣는다(이름 칸처럼 글자 종류를 걸러내는 입력칸에서도 통함).

캐시: 원본 noVNC 파일의 수정일이 2018년이라 브라우저가 "아직 최신"이라고 보고 저장된 옛 파일을 재사용하므로,
패치가 폰에 안 닿는다. 그래서 처음 보는 진입 주소(phone.html)와 버전 쿼리(?v=...)로 새로 받게 한다.
시스템 패키지 파일(/usr/share/novnc)은 건드리지 않고 복사본(/home/ubuntu/novnc-patched)에만 적용한다.
"""
import os
import shutil
import sys

SRC = "/usr/share/novnc"
DST = "/home/ubuntu/novnc-patched"
VERSION = "hb3"

MARKER = "        if (down === undefined) {\n            this.sendKey(keysym, code, true);\n"
PATCH = """        // HANGUL_BRIDGE: 라틴 범위를 넘는 유니코드 키(한글 등)는 서버 브라우저가 무시하므로 ASCII 이스케이프
        // `16진수`(백틱으로 감쌈)로 바꿔 보낸다(서버 쪽에서 다시 글자로 되돌림). down 이벤트에서 한 번에 다 보내고 up은 무시.
        if (keysym >= 0x01000100 && keysym <= 0x0110ffff) {
            if (down === false) { return; }
            var hb_seq = "`" + (keysym & 0xffffff).toString(16) + "`";
            for (var hb_i = 0; hb_i < hb_seq.length; hb_i++) {
                var hb_ks = hb_seq.charCodeAt(hb_i);
                RFB.messages.keyEvent(this._sock, hb_ks, 1);
                RFB.messages.keyEvent(this._sock, hb_ks, 0);
            }
            return;
        }

"""


def main(src: str = SRC, dst: str = DST) -> int:
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    path = os.path.join(dst, "core", "rfb.js")
    with open(path, encoding="utf-8") as f:
        code = f.read()
    if MARKER not in code:
        print("실패: noVNC rfb.js에서 패치 위치를 찾지 못했습니다(버전이 달라졌을 수 있음).")
        return 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(code.replace(MARKER, PATCH + MARKER, 1))

    # 캐시 우회: ui.js가 rfb.js를 버전 쿼리로 불러오게 하고, 처음 보는 진입 페이지(phone.html)가 ui.js도 버전 쿼리로 부른다.
    ui_path = os.path.join(dst, "app", "ui.js")
    with open(ui_path, encoding="utf-8") as f:
        ui = f.read()
    old_import = 'import RFB from "../core/rfb.js";'
    if old_import not in ui:
        print("실패: ui.js에서 rfb.js import를 찾지 못했습니다.")
        return 1
    with open(ui_path, "w", encoding="utf-8") as f:
        f.write(ui.replace(old_import, f'import RFB from "../core/rfb.js?v={VERSION}";', 1))

    with open(os.path.join(dst, "vnc.html"), encoding="utf-8") as f:
        page = f.read()
    old_tag = 'src="app/ui.js"'
    if old_tag not in page:
        print("실패: vnc.html에서 ui.js 로드 태그를 찾지 못했습니다.")
        return 1
    with open(os.path.join(dst, "phone.html"), "w", encoding="utf-8") as f:
        f.write(page.replace(old_tag, f'src="app/ui.js?v={VERSION}"', 1))
    print(f"패치 완료: {dst} (진입 주소: /phone.html)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
