import json
import os
import sys
import time
from playwright.sync_api import sync_playwright
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
PAGE_URL = "https://sw.ulsan.ac.kr/site/swulsan/notices"
STATE_FILE = "latest_notice.json"


def send_discord_alert(title, date, notice_id, is_important=False, link=PAGE_URL):
  """디스코드 웹훅으로 공지사항 전송"""
  if not DISCORD_WEBHOOK_URL:
    print("[Error] DISCORD_WEBHOOK 환경변수가 설정되지 않았습니다.")
    return

  badge = "🚨 [중요] " if is_important else "📢 "
  color = 15158332 if is_important else 3066993  # 빨간색 / 에메랄드색

  payload = {
      "username": "울산대 SW공지 알리미",
      "avatar_url": "https://sw.ulsan.ac.kr/favicon.ico",
      "embeds": [{
          "title": f"{badge}{title}",
          "description": (
              f"**번호/ID**: {notice_id}\n"
              f"**작성일**: {date}\n\n"
              f"🔗 [공지사항 바로가기]({link})"
          ),
          "color": color,
      }],
  }

  res = requests.post(DISCORD_WEBHOOK_URL, json=payload)
  print(f"[Discord] 전송 결과 ({notice_id} - {title[:15]}...): {res.status_code}")
  time.sleep(0.5)  # 디스코드 웹훅 Rate Limit 방지 (0.5초 간격 전송)


def run():
  # 1. 이전에 이미 전송했던 공지 식별자 목록 불러오기
  sent_ids = set()
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        sent_ids = set(data.get("sent_ids", []))
    except Exception as e:
      print(f"[Warning] 상태 파일 읽기 실패 (새로 생성합니다): {e}")

  is_first_run = len(sent_ids) == 0
  if is_first_run:
    print("[Init] 최초 실행: 현재 페이지의 모든 공지사항을 전송합니다.")

  # 2. Playwright로 웹페이지 렌더링 및 전체 목록 추출
  current_notices = []

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    print(f"[Fetch] 페이지 접속 중: {PAGE_URL}")
    page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)

    # MUI DataGrid 행 대기
    try:
      page.wait_for_selector(".MuiDataGrid-row", timeout=15000)
    except Exception as e:
      print(f"[Error] 테이블 행 로딩 실패: {e}")
      browser.close()
      return

    rows = page.query_selector_all(".MuiDataGrid-row")
    print(f"[Info] 총 {len(rows)}개의 행(공지)을 발견했습니다.")

    for row in rows:
      # data-id 속성 추출 (예: '77', '76' 또는 고유 UUID)
      row_id = row.get_attribute("data-id")
      row_text = [t.strip() for t in row.inner_text().split("\n") if t.strip()]

      if not row_text:
        continue

      is_important = "중요" in row_text
      date = ""
      title = ""

      # 텍스트 요소 분리 파싱
      for item in row_text:
        if item.startswith("202") and "." in item:
          date = item
        elif not item.isdigit() and item != "중요" and len(item) > len(title):
          title = item

      if not title:
        continue

      # 게시글 고유 키 (data-id가 없으면 번호/제목 조합)
      unique_key = str(row_id) if row_id else f"{date}_{title}"

      # 링크 추출
      link_elem = row.query_selector("a")
      post_link = link_elem.get_attribute("href") if link_elem else PAGE_URL
      if post_link and post_link.startswith("/"):
        post_link = f"https://sw.ulsan.ac.kr{post_link}"

      current_notices.append({
          "key": unique_key,
          "title": title,
          "date": date,
          "is_important": is_important,
          "link": post_link,
      })

    browser.close()

  # 3. 새로운 공지사항 필터링
  # 아직 전송된 적 없는 공지만 골라냄
  new_notices = [n for n in current_notices if n["key"] not in sent_ids]

  if not new_notices:
    print("[Info] 새로 올라온 공지가 없습니다.")
    return

  print(f"[Target] 전송 대상 공지: {len(new_notices)}개")

  # 사용자 알림 순서를 위해 오래된 글 -> 최신 글 순서(역순)로 전송
  for notice in reversed(new_notices):
    send_discord_alert(
        title=notice["title"],
        date=notice["date"],
        notice_id=notice["key"],
        is_important=notice["is_important"],
        link=notice["link"],
    )
    # 전송 완료한 ID 추가
    sent_ids.add(notice["key"])

  # 4. 상태 파일 갱신 (전송된 ID 목록 저장)
  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

  print(f"[Success] 상태 저장 완료 (총 {len(sent_ids)}개 기록됨)")


if __name__ == "__main__":
  run()