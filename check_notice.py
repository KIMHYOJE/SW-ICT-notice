import json
import os
import sys
import time
import requests
from playwright.sync_api import sync_playwright

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
PAGE_URL = "https://sw.ulsan.ac.kr/site/swulsan/notices"
STATE_FILE = "latest_notice.json"


def send_discord_alert(title, date, notice_id, is_important=False):
    """디스코드 웹훅 메시지 전송"""
    if not DISCORD_WEBHOOK_URL:
        print("[Error] DISCORD_WEBHOOK 환경변수가 없습니다.")
        return

    badge = "🚨 [중요] " if is_important else "📢 "
    color = 15158332 if is_important else 3066993

    payload = {
        "username": "울산대 SW공지 알리미",
        "avatar_url": "https://sw.ulsan.ac.kr/favicon.ico",
        "embeds": [
            {
                "title": f"{badge}{title}",
                "description": f"**게시글 번호/ID**: {notice_id}\n**작성일**: {date}\n\n🔗 [공지사항 바로가기]({PAGE_URL})",
                "color": color
            }
        ]
    }

    res = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    print(f"[Discord] 전송 완료 ({notice_id} - {title[:20]}...) -> 상태코드: {res.status_code}")
    time.sleep(0.6)  # 디스코드 Rate Limit 방지


def run():
    # 1. 기존에 이미 전송했던 ID 목록 불러오기
    sent_ids = set()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                sent_ids = set(data.get("sent_ids", []))
        except Exception as e:
            print(f"[Warning] 상태 파일 로드 실패: {e}")

    print(f"[Info] 이전에 저장된 공지 ID 수: {len(sent_ids)}개")

    # 2. Playwright로 화면에 렌더링된 모든 행 파싱
    current_notices = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"[Fetch] 페이지 접속 중: {PAGE_URL}")
        page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)

        # MuiDataGrid 행이 로딩될 때까지 대기
        page.wait_for_selector("div.MuiDataGrid-row", timeout=20000)
        time.sleep(1)  # 렌더링 안정화 대기

        # 모든 행(중요 공지 + 일반 공지 전체) 선택
        rows = page.query_selector_all("div.MuiDataGrid-row")
        print(f"[Info] 화면에서 총 {len(rows)}개의 공지 행을 감지했습니다.")

        for row in rows:
            row_id = row.get_attribute("data-id")
            row_idx = row.get_attribute("data-rowindex")
            text_lines = [t.strip() for t in row.inner_text().split("\n") if t.strip()]

            if not text_lines:
                continue

            is_important = "중요" in text_lines
            date = ""
            title = ""

            for item in text_lines:
                if item.startswith("202") and "." in item:
                    date = item
                elif not item.isdigit() and item != "중요" and len(item) > len(title):
                    title = item

            # 고유 ID 생성 (data-id 우선)
            unique_id = str(row_id) if row_id else f"{date}_{title}"

            if title:
                current_notices.append({
                    "id": unique_id,
                    "title": title,
                    "date": date,
                    "is_important": is_important,
                    "row_index": int(row_idx) if row_idx and row_idx.isdigit() else 999
                })

        browser.close()

    # 3. 새로운 공지(sent_ids에 없는 공지)만 필터링
    new_notices = [n for n in current_notices if n["id"] not in sent_ids]

    if not new_notices:
        print("[Info] 새로운 공지사항이 없습니다.")
        return

    print(f"[Target] 새로 전송할 공지: {len(new_notices)}개")

    # 아래쪽 행(오래된 글)부터 최신 글 순서로 디스코드 알림 전송
    for notice in reversed(new_notices):
        send_discord_alert(
            title=notice["title"],
            date=notice["date"],
            notice_id=notice["id"],
            is_important=notice["is_important"]
        )
        sent_ids.add(notice["id"])

    # 4. 상태 파일 갱신
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

    print(f"[Success] 상태 저장 완료 (총 {len(sent_ids)}개 저장됨)")


if __name__ == "__main__":
    run()