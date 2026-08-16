import json
import os
import sys
import time
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
BASE_URL = "https://sw.ulsan.ac.kr"
STATE_FILE = "latest_notice.json"


def send_discord_alert(title, date, notice_id, is_important=False, link=BASE_URL):
  """디스코드 웹훅 전송"""
  if not DISCORD_WEBHOOK_URL:
    print("[Error] DISCORD_WEBHOOK 환경변수가 설정되지 않았습니다.")
    return

  badge = "🚨 [중요] " if is_important else "📢 "
  color = 15158332 if is_important else 3066993

  payload = {
      "username": "울산대 SW공지 알리미",
      "avatar_url": f"{BASE_URL}/favicon.ico",
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
  print(f"[Discord] 전송 결과: {res.status_code} ({notice_id} - {title[:15]}...)")
  time.sleep(0.6)  # 디스코드 Rate Limit 방지


def fetch_all_notices():
  """
  울산대 SW 사이트에서 공지사항 전체 목록을 가져옵니다.
  (API 직접 조회 또는 백엔드 엔드포인트 활용)
  """
  all_notices = []
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      ),
      "Accept": "application/json, text/plain, */*",
  }

  # 1. API 호출 방식 (가장 안정적)
  # 울산대 SW 공지사항 백엔드 API 주소 (필요시 Network 탭의 실제 URI로 미세 조정)
  api_url = f"{BASE_URL}/api/notices"  # 혹은 사이트별 실제 API 엔드포인트

  try:
    # pageSize를 100 등 충분히 크게 주거나 1페이지부터 순회
    response = requests.get(
        api_url, params={"page": 1, "size": 100}, headers=headers, timeout=15
    )
    if response.status_code == 200:
      data = response.json()
      items = data.get("content", data.get("items", data.get("list", [])))
      for item in items:
        all_notices.append({
            "id": str(
                item.get("id")
                or item.get("noticeId")
                or item.get("seq")
                or item.get("title")
            ),
            "title": item.get("title", "").strip(),
            "date": item.get(
                "createdAt", item.get("regDate", item.get("date", ""))
            )[:10],
            "is_important": item.get("isImportant", False)
            or item.get("noticeType") == "IMPORTANT",
            "link": f"{BASE_URL}/site/swulsan/notices/{item.get('id', '')}",
        })
      return all_notices
  except Exception as e:
    print(f"[API 호출 시도 실패, 브라우저 크롤링 폴백 진행]: {e}")

  # 2. 만약 API 접근이 막혀있다면 Playwright로 가상 스크롤/전체 DOM 수집
  from playwright.sync_api import sync_playwright

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(
        f"{BASE_URL}/site/swulsan/notices",
        wait_until="networkidle",
        timeout=60000,
    )
    page.wait_for_selector(".MuiDataGrid-row", timeout=15000)

    # Virtual Scroller 컨테이너를 아래로 스크롤하여 모든 행을 DOM에 로드
    scroller = page.query_selector(".MuiDataGrid-virtualScroller")
    if scroller:
      for _ in range(5):  # 아래로 스크롤
        page.evaluate(
            "document.querySelector('.MuiDataGrid-virtualScroller').scrollTop +="
            " 1000"
        )
        time.sleep(0.3)

    rows = page.query_selector_all(".MuiDataGrid-row")
    for row in rows:
      row_id = row.get_attribute("data-id")
      row_text = [t.strip() for t in row.inner_text().split("\n") if t.strip()]
      if not row_text:
        continue

      is_important = "중요" in row_text
      date = ""
      title = ""
      for item in row_text:
        if item.startswith("202") and "." in item:
          date = item
        elif not item.isdigit() and item != "중요" and len(item) > len(title):
          title = item

      if title:
        unique_id = str(row_id) if row_id else f"{date}_{title}"
        all_notices.append({
            "id": unique_id,
            "title": title,
            "date": date,
            "is_important": is_important,
            "link": f"{BASE_URL}/site/swulsan/notices",
        })

    browser.close()

  return all_notices


def run():
  # 1. 기존에 이미 전송된 공지 ID 목록 로드
  sent_ids = set()
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        sent_ids = set(data.get("sent_ids", []))
    except Exception as e:
      print(f"[Warning] 상태 파일 읽기 오류: {e}")

  is_first_run = len(sent_ids) == 0
  print(f"[Info] 현재 저장된 공지 수: {len(sent_ids)}개")

  # 2. 전체 공지사항 수집
  current_notices = fetch_all_notices()
  print(f"[Info] 웹사이트에서 가져온 총 공지 수: {len(current_notices)}개")

  # 3. 새로운 공지만 필터링 (중요 공지든 일반 공지든 sent_ids에 없으면 새 공지)
  new_notices = [n for n in current_notices if n["id"] not in sent_ids]

  if not new_notices:
    print("[Info] 새로 등록된 공지사항이 없습니다.")
    return

  print(f"[Alert] 새로 감지된 공지: {len(new_notices)}개")

  # 4. 과거 글부터 최신 글 순서로 디스코드 알림 발송
  for notice in reversed(new_notices):
    send_discord_alert(
        title=notice["title"],
        date=notice["date"],
        notice_id=notice["id"],
        is_important=notice["is_important"],
        link=notice["link"],
    )
    sent_ids.add(notice["id"])

  # 5. 상태 파일 업데이트 (전체 전송된 ID 저장)
  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

  print(f"[Success] 상태 저장 완료 (총 {len(sent_ids)}개 관리 중)")


if __name__ == "__main__":
  run()