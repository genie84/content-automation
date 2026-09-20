"""워드프레스에 쌓인 자동화 이미지(infographic-*/diagram-*)를 WebP로 줄여 이미지 저장소(GitHub + jsDelivr)로
옮기고, 글 본문의 이미지 주소와 대표 이미지를 바꾼 뒤 옛 미디어를 지운다(카페24 디스크 절약, 2026-09-20).

세 단계로 나눠 실행한다 — 각 단계를 확인한 뒤 다음으로 넘어갈 수 있게:
  --dry-run   읽기 전용 시뮬레이션. 내려받기·변환·치환만 하고 아무것도 쓰지 않는다(절감량/이상 징후 확인용).
  --apply     이미지 저장소 업로드 → 글 본문 주소 치환 + 대표 이미지를 작은 WebP로 교체 → 글마다 다시 읽어 검증
              (실패하면 그 글을 원래 내용으로 되돌림). 옛 미디어는 지우지 않는다. --limit N이면 N개 미디어만(시험용).
  --cleanup   apply가 성공으로 기록한 옛 미디어 중 지금도 어디에서도 안 쓰이는 것만 삭제.

기록은 data/migration/ 에 남긴다: posts_backup.json(수정 전 본문·대표이미지, 되돌리기용),
migrated_media.json(미디어별 결과), report.txt.
"""
import argparse
import collections
import io
import json
import os
import re
import sys
from urllib.parse import unquote

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

from scripts import image_host  # noqa: E402
from scripts.wordpress_publisher import WP_BASE_URL, upload_media  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
MIGRATION_DIR = os.path.join(DATA_DIR, "migration")
MAPPING_PATH = os.path.join(MIGRATION_DIR, "migrated_media.json")
BACKUP_PATH = os.path.join(MIGRATION_DIR, "posts_backup.json")
REPORT_PATH = os.path.join(MIGRATION_DIR, "report.txt")

AUTO_PREFIXES = ("infographic-", "diagram-")
# 자동화 이미지 주소(도메인이 예전 것이든 http든 상관없이). group(1) = 확장자 뺀 파일명(리사이즈본이면 -300x200 포함).
AUTO_FILE = re.compile(
    r"https?://[^\"'\s<>]*?/wp-content/uploads/[^\"'\s<>]*?/((?:infographic|diagram)-[^/\"'\s<>]+?)\.(?:png|jpe?g|webp)",
    re.I,
)


def _auth():
    return (os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"])


def _norm_stem(name: str) -> str:
    return re.sub(r"-\d+x\d+$", "", name)


def _wp_get_all(path: str, params: dict) -> list:
    rows, page = [], 1
    while True:
        r = requests.get(
            f"{WP_BASE_URL}/wp-json/wp/v2/{path}", auth=_auth(), params={**params, "per_page": 100, "page": page}, timeout=90
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows += batch
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    return rows


def _footprint(m: dict) -> int:
    md = m.get("media_details") or {}
    return (md.get("filesize") or 0) + sum((v.get("filesize") or 0) for v in (md.get("sizes") or {}).values())


def _filename(m: dict) -> str:
    return unquote(m["source_url"].rsplit("/", 1)[-1])


def _stem(m: dict) -> str:
    return _filename(m).rsplit(".", 1)[0]


def _load_state():
    media = _wp_get_all("media", {"_fields": "id,slug,mime_type,source_url,media_details"})
    posts = _wp_get_all(
        "posts",
        {"context": "edit", "status": "publish,draft,private,future,pending", "_fields": "id,status,featured_media,content"},
    )
    return media, posts


def _to_webp(data: bytes, is_diagram: bool) -> tuple[bytes, str]:
    """(변환된 바이트, 확장자). 변환본이 원본보다 안 작으면 원본을 그대로 쓴다."""
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        fmt = (im.format or "PNG").lower()
        rgb = im.convert("RGB")
    buf = io.BytesIO()
    if is_diagram:
        rgb.save(buf, "WEBP", lossless=True, quality=100, method=6)  # 평면 색 위주 카드는 무손실이 더 작다
    else:
        rgb.save(buf, "WEBP", quality=90, method=6)
    if len(buf.getvalue()) >= len(data):
        return data, "jpg" if fmt in ("jpeg", "jpg") else fmt
    return buf.getvalue(), "webp"


def _make_thumb(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        if im.width > 1000:
            im = im.resize((1000, round(im.height * 1000 / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=82, method=6)
        return buf.getvalue()


def _serves(url: str) -> bool:
    try:
        r = requests.get(url, timeout=30)
        return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
    except requests.RequestException:
        return False


def _write_records(entries: dict, backup: dict, report_lines: list[str]) -> None:
    os.makedirs(MIGRATION_DIR, exist_ok=True)
    merged = {}
    if os.path.exists(MAPPING_PATH):
        for e in json.load(open(MAPPING_PATH, encoding="utf-8")):
            merged[e["id"]] = e
    for mid, e in entries.items():
        merged[mid] = {k: v for k, v in e.items() if k != "thumb"}
    json.dump(sorted(merged.values(), key=lambda e: e["id"]), open(MAPPING_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    old_backup = json.load(open(BACKUP_PATH, encoding="utf-8")) if os.path.exists(BACKUP_PATH) else {}
    old_backup.update({str(k): v for k, v in backup.items()})
    json.dump(old_backup, open(BACKUP_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(REPORT_PATH, "w", encoding="utf-8").write("\n".join(report_lines))


def run(apply: bool, limit: int) -> int:
    mode = "적용" if apply else "시뮬레이션(쓰기 없음)"
    if apply and not image_host.is_configured():
        print("중단: IMAGE_HOST_TOKEN이 없습니다.")
        return 1
    media, posts = _load_state()
    auto = {_stem(m): m for m in media if _filename(m).startswith(AUTO_PREFIXES)}
    by_id = {m["id"]: m for m in auto.values()}

    refs = collections.defaultdict(lambda: {"body": set(), "featured": set()})
    unmatched = []
    for p in posts:
        for mo in AUTO_FILE.finditer(p["content"]["raw"]):
            m = auto.get(_norm_stem(mo.group(1)))
            if m:
                refs[m["id"]]["body"].add(p["id"])
            else:
                unmatched.append((p["id"], mo.group(0)))
        fm = p.get("featured_media")
        if fm in by_id:
            refs[fm]["featured"].add(p["id"])
    used = sorted(refs)
    if limit:
        used = used[-limit:]  # 시험용이면 가장 최근 것부터
    print(f"[{mode}] 자동화 미디어 {len(auto)}개 중 글에서 쓰는 것 {len(refs)}개, 이번 대상 {len(used)}개, 매칭 안 된 자동화 주소 {len(unmatched)}건")

    # A단계: 내려받기 → 변환 → (적용 시) 이미지 저장소 업로드
    entries, before, after = {}, 0, 0
    for mid in used:
        m = by_id[mid]
        is_diagram = _filename(m).startswith("diagram-")
        try:
            data = requests.get(m["source_url"], timeout=90)
            data.raise_for_status()
            data = data.content
            body, ext = _to_webp(data, is_diagram)
            if apply:
                new_url = image_host.upload_image(body, f"m{mid}-{_stem(m)}.{ext}")
                if not _serves(new_url):
                    raise RuntimeError("jsDelivr가 이미지를 내주지 않음")
            else:
                new_url = f"https://cdn.jsdelivr.net/gh/DRYRUN/x@0/m{mid}-{_stem(m)}.{ext}"
        except Exception as e:
            print(f"  - 미디어 {mid} 건너뜀({type(e).__name__}: {e})")
            continue
        before += len(data)
        after += len(body)
        entries[mid] = {
            "id": mid, "filename": _filename(m), "new_url": new_url, "old_bytes": len(data), "new_bytes": len(body),
            "old_footprint": _footprint(m), "body_posts": sorted(refs[mid]["body"]), "featured_posts": sorted(refs[mid]["featured"]),
            "thumb": _make_thumb(data) if refs[mid]["featured"] else None, "thumb_id": None, "ok": False, "fail": [],
        }

    # B단계: 글 본문 주소 치환 + 대표 이미지 교체 (+ 검증, 실패하면 되돌림)
    backup, changed_posts, occurrences = {}, 0, 0
    for p in posts:
        raw = p["content"]["raw"]
        touched = set()

        def sub(mo):
            m = auto.get(_norm_stem(mo.group(1)))
            if m and m["id"] in entries:
                touched.add(m["id"])
                return entries[m["id"]]["new_url"]
            return mo.group(0)

        new_raw = AUTO_FILE.sub(sub, raw)
        payload = {}
        if new_raw != raw:
            payload["content"] = new_raw
        fm = p.get("featured_media")
        new_featured = None
        if fm in entries and entries[fm]["thumb"] is not None:
            e = entries[fm]
            if e["thumb_id"] is None:
                if apply:
                    try:
                        e["thumb_id"] = upload_media(e["thumb"], f"m{fm}-thumb.webp", content_type="image/webp")["id"]
                    except Exception as ex:
                        print(f"  - 글 {p['id']} 대표 이미지 썸네일 업로드 실패({type(ex).__name__}) — 대표 이미지는 그대로 둠")
                        e["fail"].append(f"thumb:{p['id']}")
                else:
                    e["thumb_id"] = -1
            if e["thumb_id"]:
                new_featured = e["thumb_id"]
                payload["featured_media"] = new_featured
                touched.add(fm)
        if not payload:
            continue
        changed_posts += 1
        occurrences += len(AUTO_FILE.findall(raw))
        backup[p["id"]] = {"content_raw": raw, "featured_media": fm}
        if not apply:
            continue
        r = requests.post(f"{WP_BASE_URL}/wp-json/wp/v2/posts/{p['id']}", auth=_auth(), json=payload, timeout=120)
        ok = r.status_code == 200
        if ok:
            chk = requests.get(
                f"{WP_BASE_URL}/wp-json/wp/v2/posts/{p['id']}", auth=_auth(), params={"context": "edit", "_fields": "content,featured_media"}, timeout=60
            ).json()
            got_raw = chk["content"]["raw"]
            ok = all(_stem(by_id[t]) not in got_raw for t in touched if t in entries and payload.get("content")) and (
                new_featured is None or chk.get("featured_media") == new_featured
            )
        if not ok:
            print(f"  ! 글 {p['id']} 검증 실패 → 원래 내용으로 되돌림 (HTTP {r.status_code})")
            requests.post(
                f"{WP_BASE_URL}/wp-json/wp/v2/posts/{p['id']}", auth=_auth(),
                json={"content": raw, "featured_media": fm or 0}, timeout=120,
            )
            for t in touched:
                if t in entries:
                    entries[t]["fail"].append(f"post:{p['id']}")
    for e in entries.values():
        e["ok"] = apply and not e["fail"]

    est_saved = sum(e["old_footprint"] for e in entries.values())
    est_added = sum(len(e["thumb"]) * 2.2 for e in entries.values() if e["thumb"])
    lines = [
        f"[{mode}] 대상 미디어 {len(entries)}개 / 수정한 글 {changed_posts}개 / 치환한 주소 {occurrences}건",
        f"이미지 파일 크기(원본 → 변환): {before/1024/1024:.1f}MB → {after/1024/1024:.1f}MB",
        f"카페24 디스크 예상: 옛 미디어 {est_saved/1024/1024:.0f}MB 정리 가능, 새 대표이미지 약 {est_added/1024/1024:.0f}MB 추가 → 순 절감 약 {(est_saved-est_added)/1024/1024:.0f}MB",
        f"성공 {sum(1 for e in entries.values() if e['ok'])}개 / 실패 {sum(1 for e in entries.values() if e['fail'])}개 / 매칭 안 된 자동화 주소 {len(unmatched)}건",
    ]
    if unmatched:
        lines.append("매칭 안 된 예: " + ", ".join(u for _, u in unmatched[:3]))
    print("\n".join(lines))
    if apply:
        _write_records(entries, backup, lines)
    else:
        os.makedirs(MIGRATION_DIR, exist_ok=True)
        open(os.path.join(MIGRATION_DIR, "dryrun_report.txt"), "w", encoding="utf-8").write("\n".join(lines))
    return 0


def cleanup() -> int:
    if not os.path.exists(MAPPING_PATH):
        print("중단: 이전 기록(migrated_media.json)이 없습니다. 먼저 --apply를 실행하세요.")
        return 1
    entries = [e for e in json.load(open(MAPPING_PATH, encoding="utf-8")) if e.get("ok") and not e.get("deleted")]
    media, posts = _load_state()
    pages = _wp_get_all("pages", {"context": "edit", "status": "publish,draft,private", "_fields": "id,featured_media,content"})
    blobs = [x["content"]["raw"] + x["content"].get("rendered", "") for x in posts + pages]
    featured = {x.get("featured_media") for x in posts + pages}
    present = {m["id"] for m in media}
    deleted, skipped, freed = 0, 0, 0
    all_entries = {e["id"]: e for e in json.load(open(MAPPING_PATH, encoding="utf-8"))}
    for e in entries:
        stem = e["filename"].rsplit(".", 1)[0]
        if e["id"] not in present:
            e["deleted"] = True
            continue
        if e["id"] in featured or any(stem in b for b in blobs) or not _serves(e["new_url"]):
            skipped += 1
            print(f"  - 미디어 {e['id']} 건너뜀(아직 쓰이거나 새 주소가 안 열림)")
            continue
        r = requests.delete(f"{WP_BASE_URL}/wp-json/wp/v2/media/{e['id']}", auth=_auth(), params={"force": "true"}, timeout=60)
        if r.status_code == 200 and r.json().get("deleted"):
            deleted += 1
            freed += e["old_footprint"]
            all_entries[e["id"]]["deleted"] = True
        else:
            skipped += 1
            print(f"  - 미디어 {e['id']} 삭제 실패 HTTP {r.status_code}")
    json.dump(sorted(all_entries.values(), key=lambda x: x["id"]), open(MAPPING_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    line = f"[정리] 삭제 {deleted}개 / 건너뜀 {skipped}개 / 메타데이터 기준 확보 {freed/1024/1024:.0f}MB"
    print(line)
    open(REPORT_PATH, "a", encoding="utf-8").write("\n" + line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--cleanup", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--apply 시험용: 가장 최근 미디어 N개만")
    args = ap.parse_args()
    if args.cleanup:
        return cleanup()
    return run(apply=args.apply, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())
