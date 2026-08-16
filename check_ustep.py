import json
import os
import time
from playwright.sync_api import sync_playwright
import requests

WEBHOOK_GENERAL = os.environ.get("DISCORD_WEBHOOK_GENERAL")
WEBHOOK_CHALLENGE = os.environ.get("DISCORD_WEBHOOK_CHALLENGE")

BASE_URL = "https://ustep.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/home/sub/prog-list"
STATE_FILE = "latest_ustep.json"

MILEAGE_CONFIG = {
    "1": {
        "name": "일반 장학",
        "webhook": WEBHOOK_GENERAL,
        "color": 3447003,
        "badge": "📘 [일반 장학]",
    },
    "2": {
        "name": "도전 장학",
        "webhook": WEBHOOK_CHALLENGE,
        "color": 15844367,
        "badge": "🏆 [도전 장학]",
    },
}


def send_discord_alert(prog):
  mile_type = prog["mile_type"]
  config = MILEAGE_CONFIG.get(mile_type)
  if not config or not config["webhook"]:
    print(f"[Skip] {config['name'] if config else '미상'} 웹훅 미설정")
    return

  embed = {
      "title": f"{config['badge']} {prog['title']}",
      "description": (
          f"**구분**: {config['name']}\n"
          f"**일정/D-Day**: {prog['d_day']}\n"
          f"**신청기간**: {prog['apply_period']}\n\n"
          f"🔗 [프로그램 바로가기]({prog['link']})"
      ),
      "color": config["color"],
  }

  if prog["img_url"]:
    embed["image"] = {"url": prog["img_url"]}

  payload = {
      "username": f"U-STEP {config['name']} 알리미",
      "avatar_url": f"{BASE_URL}/favicon.ico",
      "embeds": [embed],
  }

  res = requests.post(config["webhook"], json=payload)
  print(f"[Discord] {config['name']} 전송: {prog['title'][:15]}... -> {res.status_code}")
  time.sleep(0.6)


def scrape_cards(page, mile_value):
  """해당 마일리지 페이지의 모든 카드 수집"""
  programs = []

  # URL 파라미터나 폼 선택으로 정확히 이동
  target_url = f"{LIST_URL}?schMile={mile_value}"
  page.goto(target_url, wait_until="networkidle", timeout=30000)
  page.wait_for_timeout(1000)

  # 카드 요소들 (a.item) 전체 탐색
  cards = page.query_selector_all(
      ".board-list-program a.item, .board-list-program .schedule-slide-wrap"
      " a.item"
  )
  if not cards:
    cards = page.query_selector_all("a.item")

  print(
      f"[{MILEAGE_CONFIG[mile_value]['name']}] 감지된 카드 수: {len(cards)}개"
  )

  for card in cards:
    # 1. 제목 추출 (.board-subject or .board-con)
    subj_el = card.query_selector(".board-subject, .board-con")
    title = subj_el.inner_text().strip() if subj_el else ""
    if not title:
      continue

    # 2. 이미지 URL 추출
    img_el = card.query_selector(".board-img img, img")
    img_src = img_el.get_attribute("src") if img_el else ""
    if img_src and not img_src.startswith("http"):
      img_src = f"{BASE_URL}{img_src}"

    # 3. D-day 추출
    dday_el = card.query_selector(".badge-day, span[class*='badge']")
    d_day = dday_el.inner_text().strip() if dday_el else ""

    # 4. 신청 기간 추출 (.board-time)
    time_el = card.query_selector(".board-time")
    apply_period = (
        time_el.inner_text().replace("\n", " ").strip() if time_el else ""
    )

    # 5. 링크 추출
    href = card.get_attribute("href") or ""
    link = f"{BASE_URL}{href}" if href.startswith("/") else href

    # 고유 ID (마일리지_제목 or href 파라미터 기반)
    prog_id = f"{mile_value}_{href}" if href else f"{mile_value}_{title}"

    programs.append({
        "id": prog_id,
        "mile_type": mile_value,
        "title": title,
        "img_url": img_src,
        "d_day": d_day,
        "apply_period": apply_period,
        "link": link,
    })

  return programs


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

  print(f"[U-STEP] 이전 저장된 ID 수: {len(sent_ids)}개")

  all_progs = []
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # 1: 일반 장학, 2: 도전 장학 순회
    for m_type in ["1", "2"]:
      progs = scrape_cards(page, m_type)
      all_progs.extend(progs)

    browser.close()

  # 최초 실행 여부 체크
  if is_first_run:
    print(
        f"[Init] U-STEP 최초 실행: 현재 {len(all_progs)}개 프로그램을 기준"
        " 데이터로 저장합니다. (알림 생략)"
    )
    for p in all_progs:
      sent_ids.add(p["id"])
  else:
    new_progs = [p for p in all_progs if p["id"] not in sent_ids]
    print(f"[U-STEP] 새로 감지된 프로그램: {len(new_progs)}개")

    for prog in reversed(new_progs):
      send_discord_alert(prog)
      sent_ids.add(prog["id"])

  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
  run()