import json
import os
import time
from playwright.sync_api import sync_playwright
import requests

DISCORD_WEBHOOK_MUNSU = os.environ.get("DISCORD_WEBHOOK_MUNSU")
BASE_URL = "https://ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/kor/CMS/Board/Board.do?mCode=MN125"
STATE_FILE = "latest_munsu.json"


def send_discord_alert(notice):
  """문수게시판 디스코드 웹훅 알림 발송"""
  if not DISCORD_WEBHOOK_MUNSU:
    print("[Skip] DISCORD_WEBHOOK_MUNSU 환경변수가 설정되지 않았습니다.")
    return

  payload = {
      "username": "울산대 문수게시판 알리미",
      "avatar_url": f"{BASE_URL}/favicon.ico",
      "embeds": [{
          "title": f"📋 {notice['title']}",
          "description": (
              f"**번호**: {notice['num']}\n"
              f"**작성자**: {notice['writer']}\n"
              f"**작성일**: {notice['date']}\n\n"
              f"🔗 [게시글 바로가기]({notice['link']})"
          ),
          "color": 3447003,  # 블루
      }],
  }

  res = requests.post(DISCORD_WEBHOOK_MUNSU, json=payload)
  print(
      f"[Discord] 문수게시판 전송: {notice['num']}번 {notice['title'][:15]}... ->"
      f" {res.status_code}"
  )
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
      print(f"[Warning] 문수게시판 상태 파일 로드 에러: {e}")

  print(f"[문수게시판] 기존 저장된 글 번호/ID 수: {len(sent_ids)}개")

  current_notices = []

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    print(f"[Fetch] 문수게시판 접속 중: {LIST_URL}")
    page.goto(LIST_URL, wait_until="networkidle", timeout=60000)

    # 테이블 행 대기
    try:
      page.wait_for_selector("table.board-list-table tbody tr", timeout=15000)
    except Exception as e:
      print(f"[Error] 테이블 로딩 실패: {e}")
      browser.close()
      return

    rows = page.query_selector_all("table.board-list-table tbody tr")
    print(f"[Info] 문수게시판에서 총 {len(rows)}개의 행을 감지했습니다.")

    for row in rows:
      # 1. 번호 (td.num)
      num_el = row.query_selector("td.num")
      num = num_el.inner_text().strip() if num_el else ""

      # 2. 제목 및 링크 (td.subject p.stitle a)
      link_el = row.query_selector("td.subject p.stitle a, td.subject a")
      title = link_el.inner_text().strip() if link_el else ""
      href = link_el.get_attribute("href") if link_el else ""

      # 3. 작성자 (td.writer)
      writer_el = row.query_selector("td.writer")
      writer = writer_el.inner_text().strip() if writer_el else ""

      # 4. 작성일 (td.date)
      date_el = row.query_selector("td.date")
      date = date_el.inner_text().strip() if date_el else ""

      if not title:
        continue

      # 상세 링크 생성
      if href.startswith("?"):
        full_link = f"{BASE_URL}/kor/CMS/Board/Board.do{href}"
      elif href.startswith("/"):
        full_link = f"{BASE_URL}{href}"
      else:
        full_link = href

      # 고유 ID 생성 (href의 board_seq 등 파라미터나 번호 기준)
      unique_id = str(num) if num else f"{date}_{title}"

      current_notices.append({
          "id": unique_id,
          "num": num,
          "title": title,
          "writer": writer,
          "date": date,
          "link": full_link,
      })

    browser.close()

  # 최초 실행 시 초기 데이터만 구축 (알림 폭탄 방지)
  if is_first_run:
    print(
        f"[Init] 문수게시판 최초 실행: 현재 {len(current_notices)}개 글을 기준"
        " 데이터로 저장합니다. (알림 생략)"
    )
    for n in current_notices:
      sent_ids.add(n["id"])
  else:
    new_notices = [n for n in current_notices if n["id"] not in sent_ids]
    print(f"[문수게시판] 새로 감지된 공지: {len(new_notices)}개")

    # 오래된 글부터 순서대로 발송
    for notice in reversed(new_notices):
      send_discord_alert(notice)
      sent_ids.add(notice["id"])

  # 상태 저장
  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

  print(f"[Success] 문수게시판 상태 저장 완료 (총 {len(sent_ids)}개 관리 중)")


if __name__ == "__main__":
  run()