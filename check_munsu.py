import json
import os
import time
import requests
from bs4 import BeautifulSoup

DISCORD_WEBHOOK_MUNSU = os.environ.get("DISCORD_WEBHOOK_MUNSU")
BASE_URL = "https://www.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/kor/CMS/Board/Board.do?mCode=MN125"
STATE_FILE = "latest_munsu.json"


def send_discord_alert(notice):
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
          "color": 3447003,
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

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      )
  }

  try:
    res = requests.get(LIST_URL, headers=headers, timeout=30)
    res.raise_for_status()
  except Exception as e:
    print(f"[Error] 문수게시판 페이지 요청 실패: {e}")
    return

  soup = BeautifulSoup(res.text, "html.parser")
  table = soup.select_one("table.board-list-table")
  if not table:
    print("[Error] 테이블을 찾을 수 없습니다.")
    return

  rows = table.select("tbody tr")
  print(f"[Info] 문수게시판에서 총 {len(rows)}개의 행을 감지했습니다.")

  current_notices = []
  for row in rows:
    num_el = row.select_one("td.num")
    num = num_el.get_text(strip=True) if num_el else ""

    link_el = row.select_one("td.subject p.stitle a, td.subject a")
    title = link_el.get_text(strip=True) if link_el else ""
    href = link_el.get("href", "") if link_el else ""

    writer_el = row.select_one("td.writer")
    writer = writer_el.get_text(strip=True) if writer_el else ""

    date_el = row.select_one("td.date")
    date = date_el.get_text(strip=True) if date_el else ""

    if not title:
      continue

    if href.startswith("?"):
      full_link = f"{BASE_URL}/kor/CMS/Board/Board.do{href}"
    elif href.startswith("/"):
      full_link = f"{BASE_URL}{href}"
    else:
      full_link = href

    unique_id = str(num) if num else f"{date}_{title}"
    current_notices.append({
        "id": unique_id,
        "num": num,
        "title": title,
        "writer": writer,
        "date": date,
        "link": full_link,
    })

  # 최초 실행 시 알림 폭탄 방지 (알림 생략하고 저장만)
  if is_first_run:
    print(
        f"[Init] 문수게시판 최초 실행: 현재 {len(current_notices)}개 글을 기준"
        " 데이터로 저장합니다."
    )
    for n in current_notices:
      sent_ids.add(n["id"])
  else:
    new_notices = [n for n in current_notices if n["id"] not in sent_ids]
    print(f"[문수게시판] 새로 감지된 공지: {len(new_notices)}개")

    for notice in reversed(new_notices):
      send_discord_alert(notice)
      sent_ids.add(notice["id"])

  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

  print(f"[Success] 문수게시판 상태 저장 완료 (총 {len(sent_ids)}개 관리 중)")


if __name__ == "__main__":
  run()