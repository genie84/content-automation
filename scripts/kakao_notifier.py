"""새 draft가 발행될 때마다 카카오톡 '나에게 보내기'로 알림을 전송한다."""
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def get_access_token() -> str:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": os.environ["KAKAO_REST_API_KEY"],
            "client_secret": os.environ["KAKAO_CLIENT_SECRET"],
            "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def send_kakao_notification(title: str, link: str) -> None:
    access_token = get_access_token()
    template_object = {
        "object_type": "text",
        "text": f"새 draft 발행됨\n{title}",
        "link": {"web_url": link, "mobile_web_url": link},
        "button_title": "확인하러 가기",
    }
    response = requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=15,
    )
    response.raise_for_status()


def main():
    send_kakao_notification("[테스트] 카카오 알림 연동 확인", "https://lampgenie.co.kr/wp-admin/edit.php?post_status=draft")


if __name__ == "__main__":
    main()
