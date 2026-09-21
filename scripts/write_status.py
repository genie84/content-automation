"""서버 크론(10분마다)이 폰에서 볼 수 있는 현황 페이지(status.html)를 만든다.
비밀값(토큰·비밀번호)이나 글 내용은 넣지 않는다 — 시각/개수/성공·실패 같은 상태만."""
import glob
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "/home/ubuntu/novnc-patched/status.html"
REPO = "genie84/content-automation"


def _token():
    try:
        p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=10, cwd=ROOT)
        for line in p.stdout.splitlines():
            if line.startswith("password="):
                return line[len("password="):]
    except Exception:
        pass
    return ""


def _runs():
    tok = _token()
    if not tok:
        return ["(GitHub 인증 없음)"]
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/actions/runs?per_page=12",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
        data = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:
        return [f"(조회 실패: {type(e).__name__})"]
    rows = []
    for r in data.get("workflow_runs", []):
        t = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).astimezone(KST).strftime("%m-%d %H:%M")
        state = r["conclusion"] or r["status"]
        mark = {"success": "✅", "failure": "❌", "in_progress": "⏳", "queued": "⏳", "cancelled": "⚪"}.get(state, "•")
        rows.append(f"{mark} {t} {r['name']} ({state})")
    return rows or ["(실행 기록 없음)"]


def main():
    queue = len(glob.glob(os.path.join(ROOT, "data", "naver_queue", "*.json")))
    try:
        sess = open("/home/ubuntu/naver_session.log", encoding="utf-8").read().strip().splitlines()[-4:]
    except Exception:
        sess = ["(아직 기록 없음)"]
    now = datetime.now(KST).strftime("%m-%d %H:%M")
    lines = [f"현황 갱신: {now} (10분마다)", "",
             f"네이버 대기 글(큐): {queue}건  ← 0이면 처리할 글 없음", "",
             "[네이버 세션 점검 (2시간마다)]"] + sess + ["", "[최근 자동 실행]"] + _runs()
    body = "\n".join(lines).replace("&", "&amp;").replace("<", "&lt;")
    html = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>현황</title><pre style="font:15px/1.6 sans-serif;white-space:pre-wrap;padding:16px">' + body + "</pre>")
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
