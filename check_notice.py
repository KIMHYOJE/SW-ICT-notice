import json
import os
import sys
from playwright.sync_api import sync_playwright
import requests

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1538554047064317966/c06Z1gtK8w5jE3KhT_We8AGes4nWkcyx4l4DtY2xHMIdLf9-RELYfPuYcng8i6pEaXmF"
PAGE_URL = "https://sw.ulsan.ac.kr/site/swulsan/notices"
STATE_FILE = "latest_notice.json"


def send_discord_alert(title, date, link):
  if not DISCORD_WEBHOOK_URL:
    print("[Error] DISCORD_WEBHOOK 환경변수가 설정되지 않았습니다.")
    return

  payload = {
      "username": "울산대 SW공지 알리미",
      "avatar_url": "https://sw.ulsan.ac.kr/favicon.ico",
      "embeds": [{
          "title": f"📢 새로운 공지사항이 등록되었습니다!",
          "description": f"**{title}**\n\n📅 작성일: {date}\n🔗 [공지사항 바로가기]({link})",
          "color": 3066993,  # 에메랄드/그린 계열
      }],
  }

  res = requests.post(DISCORD_WEBHOOK_URL, json=payload)
  print(f"[Discord] 전송 결과: {res.status_code}")


def run():
  # 1. 이전 저장된 마지막 공지 확인
  last_title = ""
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        last_title = data.get("last_title", "")
    except Exception as e:
      print(f"[Warning] 상태 파일 읽기 실패: {e}")

  # 2. Playwright로 웹페이지 렌더링 및 데이터 파싱
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    print(f"[Fetch] 페이지 접속 중: {PAGE_URL}")
    page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)

    # MUI DataGrid 행이 나타날 때까지 대기
    page.wait_for_selector(".MuiDataGrid-row", timeout=15000)

    rows = page.query_selector_all(".MuiDataGrid-row")
    if not rows:
      print("[Error] 공지사항 목록을 찾을 수 없습니다.")
      browser.close()
      return

    # 상단 행들 중 최신 글 추출 (중요 공지 포함 최상단 또는 첫 일반 행)
    # 각 행의 텍스트 및 속성 파싱
    target_row = rows[0]  # 최상단 글 기준 (필요시 일반글 인덱스로 변경 가능)
    row_text = target_row.inner_text().split("\n")

    # MUI DataGrid 행의 텍스트 구조 파싱
    # 보통 [번호, 제목, 작성일, 조회수] 순서
    title = ""
    date = ""
    for item in row_text:
      item = item.strip()
      if not item:
        continue
      if item.startswith("202") and "." in item:
        date = item
      elif len(item) > len(title) and not item.isdigit() and item != "중요":
        title = item

    # 게시글 URL (링크 속성이 있는 경우 추출)
    link_element = target_row.query_selector("a")
    post_link = (
        link_element.get_attribute("href") if link_element else PAGE_URL
    )
    if post_link.startswith("/"):
      post_link = f"https://sw.ulsan.ac.kr{post_link}"

    browser.close()

    print(f"[Checked] 최신 공지: {title} ({date})")

    # 3. 새로운 공지 비교 및 알림
    if not title:
      print("[Warning] 제목 파싱 실패")
      return

    if title != last_title:
      print("[New] 새 공지 감지! 디스코드로 전송합니다.")
      send_discord_alert(title, date, post_link)

      # 상태 업데이트
      with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_title": title, "date": date}, f, ensure_ascii=False, indent=2)
    else:
      print("[Info] 최신 상태입니다. (새로운 공지 없음)")


if __name__ == "__main__":
  run()