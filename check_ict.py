import json
import os
import time
import requests
from bs4 import BeautifulSoup

DISCORD_WEBHOOK_ICT = os.environ.get("DISCORD_WEBHOOK_ICT")
BASE_URL = "https://ict.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/ict/5786"
STATE_FILE = "latest_ict.json"


def send_discord_alert(notice):
  """ICT융합학부 학과게시판 디스코드 웹훅 알림 전송"""
  if not DISCORD_WEBHOOK_ICT:
    print("[Skip] DISCORD_WEBHOOK_ICT 환경변수가 설정되지 않았습니다.")
    return

  badge = "📌 [공지] " if notice["is_notice"] else "📄 "
  color = 15158332 if notice["is_notice"] else 3066993  # 공지글 빨간색, 일반글 초록색

  payload = {
      "username": "울산대 ICT융합학부 공지 알리미",
      "avatar_url": f"{BASE_URL}/favicon.ico",
      "embeds": [{
          "title": f"{badge}{notice['title']}",
          "description": (
              f"**번호**: {notice['num']}\n"
              f"**작성자**: {notice['writer']}\n"
              f"**작성일**: {notice['date']}\n\n"
              f"🔗 [게시글 바로가기]({notice['link']})"
          ),
          "color": color,
      }],
  }

  res = requests.post(DISCORD_WEBHOOK_ICT, json=payload)
  print(
      f"[Discord] ICT 공지 전송: {notice['num']} - {notice['title'][:15]}... ->"
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
      print(f"[Warning] ICT 상태 파일 로드 에러: {e}")

  print(f"[ICT 학과게시판] 기존 저장된 글 ID 수: {len(sent_ids)}개")

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
    print(f"[Error] ICT 학과게시판 접속 실패: {e}")
    return

  soup = BeautifulSoup(res.text, "html.parser")
  table = soup.select_one("table.a_brdList")
  if not table:
    print("[Error] ICT 학과게시판 테이블(table.a_brdList)을 찾을 수 없습니다.")
    return

  rows = table.select("tbody tr")
  print(f"[Info] ICT 학과게시판에서 총 {len(rows)}개의 행을 감지했습니다.")

  current_notices = []
  for row in rows:
    # 1. 공지 여부 및 번호 (td.bdlNum)
    is_notice = (
        "noti" in row.get("class", [])
        or row.select_one("td.bdlNum.noti") is not None
    )
    num_el = row.select_one("td.bdlNum")
    num_text = num_el.get_text(strip=True) if num_el else ""

    # 2. 제목 및 링크 (td.bdlTitle a)
    link_el = row.select_one("td.bdlTitle a")
    if not link_el:
      continue
    title = link_el.get_text(strip=True)
    href = link_el.get("href", "")

    # 3. 작성자 (td.bdlUser)
    user_el = row.select_one("td.bdlUser")
    writer = user_el.get_text(strip=True) if user_el else "관리자"

    # 4. 작성일 (td.bdlDate)
    date_el = row.select_one("td.bdlDate")
    date = date_el.get_text(strip=True) if date_el else ""

    if not title:
      continue

    # 링크 완성
    if href.startswith("?"):
      full_link = f"{LIST_URL}{href}"
    elif href.startswith("/"):
      full_link = f"{BASE_URL}{href}"
    else:
      full_link = href

    # 고유 식별키 (링크 파라미터 no=... 또는 제목/작성일 기준)
    unique_id = href if href else f"{date}_{title}"

    current_notices.append({
        "id": unique_id,
        "num": "공지" if is_notice else num_text,
        "title": title,
        "writer": writer,
        "date": date,
        "link": full_link,
        "is_notice": is_notice,
    })

  # 최초 1회 실행 시 기존 글을 기준 데이터(DB)로 저장만 하고 알림 전송은 건너뜀 (알림 폭탄 방지)
  if is_first_run:
    print(
        f"[Init] ICT 학과게시판 최초 실행: 현재 {len(current_notices)}개 글을"
        " 기준 데이터로 저장합니다. (알림 생략)"
    )
    for n in current_notices:
      sent_ids.add(n["id"])
  else:
    new_notices = [n for n in current_notices if n["id"] not in sent_ids]
    print(f"[ICT 학과게시판] 새로 감지된 공지: {len(new_notices)}개")

    # 오래된 글부터 순서대로 발송
    for notice in reversed(new_notices):
      send_discord_alert(notice)
      sent_ids.add(notice["id"])

  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

  print(f"[Success] ICT 학과게시판 상태 저장 완료 (총 {len(sent_ids)}개 관리 중)")


if __name__ == "__main__":
  run()