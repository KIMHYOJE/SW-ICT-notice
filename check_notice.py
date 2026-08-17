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
  if not DISCORD_WEBHOOK_URL:
    print("[Error] DISCORD_WEBHOOK 없음")
    return

  badge = "🚨 [중요] " if is_important else "📢 "
  color = 15158332 if is_important else 3066993

  payload = {
      "username": "울산대 SW공지 알리미",
      "avatar_url": "https://sw.ulsan.ac.kr/favicon.ico",
      "embeds": [{
          "title": f"{badge}{title}",
          "description": (
              f"**게시글 번호/ID**: {notice_id}\n"
              f"**작성일**: {date}\n\n"
              f"🔗 [공지사항 바로가기]({PAGE_URL})"
          ),
          "color": color,
      }],
  }

  res = requests.post(DISCORD_WEBHOOK_URL, json=payload)
  print(f"[Discord] SW 공지 전송: {title[:20]}... -> {res.status_code}")
  time.sleep(0.5)


def run():
  sent_ids = set()
  is_first_run = True

  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        loaded = data.get("sent_ids", [])
        if loaded:
          sent_ids = set(loaded)
          is_first_run = False
    except Exception as e:
      print(f"[Warning] 상태 파일 로드 에러: {e}")

  print(f"[SW] 이전 저장된 ID 수: {len(sent_ids)}개")

  current_notices = []
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    print(f"[Fetch] 접속 중: {PAGE_URL}")
    page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_selector("div.MuiDataGrid-row", timeout=20000)
    time.sleep(1)

    rows = page.query_selector_all("div.MuiDataGrid-row")
    for row in rows:
      row_id = row.get_attribute("data-id")
      lines = [t.strip() for t in row.inner_text().split("\n") if t.strip()]
      if not lines:
        continue

      is_important = "중요" in lines
      date = ""
      title = ""
      for item in lines:
        if item.startswith("202") and "." in item:
          date = item
        elif not item.isdigit() and item != "중요" and len(item) > len(title):
          title = item

      unique_id = str(row_id) if row_id else f"{date}_{title}"
      if title:
        current_notices.append({
            "id": unique_id,
            "title": title,
            "date": date,
            "is_important": is_important,
        })

    browser.close()

  # 최초 실행이면 DB 구축만 하고 알림 전송은 건너뜀 (알림 폭탄 방지)
  if is_first_run:
    print(
        f"[Init] 최초 실행: 현재 {len(current_notices)}개 글을 기준 데이터로"
        " 저장합니다. (알림 생략)"
    )
    for n in current_notices:
      sent_ids.add(n["id"])
  else:
    new_notices = [n for n in current_notices if n["id"] not in sent_ids]
    print(f"[SW] 새로 감지된 공지: {len(new_notices)}개")

    for notice in reversed(new_notices):
      send_discord_alert(
          notice["title"],
          notice["date"],
          notice["id"],
          notice["is_important"],
      )
      sent_ids.add(notice["id"])

  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
  run()