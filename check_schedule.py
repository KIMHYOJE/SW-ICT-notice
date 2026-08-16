from datetime import datetime, timedelta, timezone
import json
import os
import re
import sys
import time
from playwright.sync_api import sync_playwright
import requests

WEBHOOK_DAILY = os.environ.get("DISCORD_WEBHOOK_SCHEDULE_DAILY")
WEBHOOK_UPDATE = os.environ.get("DISCORD_WEBHOOK_SCHEDULE_UPDATE")

BASE_URL = "https://ict.ulsan.ac.kr"
PAGE_URL = f"{BASE_URL}/ict/5785"
STATE_FILE = "latest_schedule.json"

KST = timezone(timedelta(hours=9))


def parse_date_range(year_str, month_str, date_raw):
  try:
    year = int(re.sub(r"[^0-9]", "", year_str))
    month = int(re.sub(r"[^0-9]", "", month_str))
  except Exception:
    return None, None

  cleaned = re.sub(r"\([가-힣A-Za-z]\)", "", date_raw).strip()

  if "~" in cleaned:
    parts = cleaned.split("~")
    start_d_match = re.search(r"(\d+)", parts[0])
    end_d_match = re.search(r"(\d+)", parts[1])
    if start_d_match and end_d_match:
      s_day = int(start_d_match.group(1))
      e_day = int(end_d_match.group(1))
      return f"{year:04d}-{month:02d}-{s_day:02d}", (
          f"{year:04d}-{month:02d}-{e_day:02d}"
      )
  else:
    d_match = re.search(r"(\d+)", cleaned)
    if d_match:
      day = int(d_match.group(1))
      d_str = f"{year:04d}-{month:02d}-{day:02d}"
      return d_str, d_str

  return None, None


def fetch_all_schedules():
  schedules = []

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    print(f"[Fetch] 학사일정 접속 중: {PAGE_URL}")
    page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector(
        ".tabcontent_schedule, ul[id^='monScroll_']", timeout=20000
    )
    time.sleep(1)

    # 1학기 / 2학기 탭 클릭하면서 수집
    tabs = page.query_selector_all(
        ".tabnav_schedule li a, .tab li a, ul.tabnav_schedule a"
    )
    tab_count = len(tabs) if tabs else 1

    for idx in range(tab_count):
      if tabs and idx > 0:
        try:
          tabs[idx].click()
          time.sleep(1)
        except Exception:
          pass

      month_blocks = page.query_selector_all("ul[id^='monScroll_']")
      for block in month_blocks:
        p_el = block.query_selector("p")
        if not p_el:
          continue

        span_year = p_el.query_selector("span")
        year_text = span_year.inner_text().strip() if span_year else ""
        month_text = p_el.inner_text().replace(year_text, "").strip()

        li_items = block.query_selector_all("li")
        for li in li_items:
          b_el = li.query_selector("b")
          date_raw = b_el.inner_text().strip() if b_el else ""

          full_text = li.inner_text().strip()
          content = (
              full_text.replace(date_raw, "").replace('"', "").strip()
          )

          if not content or not date_raw:
            continue

          start_date, end_date = parse_date_range(
              year_text, month_text, date_raw
          )
          unique_id = f"{year_text}_{month_text}_{date_raw}_{content}"

          schedules.append({
              "id": unique_id,
              "year": year_text,
              "month": month_text,
              "date_raw": date_raw,
              "content": content,
              "start_date": start_date,
              "end_date": end_date,
          })

    browser.close()

  dedup = {}
  for s in schedules:
    dedup[s["id"]] = s
  return list(dedup.values())


def send_discord(webhook_url, title, description, color, username):
  if not webhook_url:
    print(f"[Skip] {username} 웹훅 미설정")
    return
  payload = {
      "username": username,
      "avatar_url": f"{BASE_URL}/favicon.ico",
      "embeds": [{"title": title, "description": description, "color": color}],
  }
  res = requests.post(webhook_url, json=payload)
  print(f"[Discord] {username} 전송: {res.status_code}")
  time.sleep(0.5)


def check_and_notify():
  state = {"last_daily_sent_date": "", "schedules": []}
  is_first_run = True

  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
        if state.get("schedules"):
          is_first_run = False
    except Exception as e:
      print(f"[Warning] 상태 로드 실패: {e}")

  saved_schedules = state.get("schedules", [])
  last_daily_sent = state.get("last_daily_sent_date", "")

  # 1. 전체 일정 수집
  current_schedules = fetch_all_schedules()
  print(f"[Info] 수집된 학사일정: {len(current_schedules)}개")

  # 2. 변경/추가된 일정 확인
  saved_ids = {s["id"] for s in saved_schedules}

  if is_first_run:
    print(
        f"[Init] 학사일정 최초 실행: {len(current_schedules)}개 일정을"
        " 기준 데이터로 저장합니다."
    )
  else:
    new_or_modified = [s for s in current_schedules if s["id"] not in saved_ids]
    print(f"[Update] 새로 추가/수정된 학사일정: {len(new_or_modified)}개")
    for item in new_or_modified:
      desc = (
          f"**일정**: {item['content']}\n"
          f"**일시**: {item['year']} {item['month']} {item['date_raw']}\n\n"
          f"🔗 [학사일정 바로가기]({PAGE_URL})"
      )
      send_discord(
          WEBHOOK_UPDATE,
          "🔔 학사일정이 추가/수정되었습니다",
          desc,
          15105570,
          "울산대 학사일정 변경 알리미",
      )

  # 3. 오늘에 해당하는 일정 알림 (KST 기준 하루 1회)
  now_kst = datetime.now(KST)
  today_str = now_kst.strftime("%Y-%m-%d")

  if last_daily_sent != today_str:
    todays_events = []
    for s in current_schedules:
      s_date = s.get("start_date")
      e_date = s.get("end_date")
      if s_date and e_date:
        if s_date <= today_str <= e_date:
          todays_events.append(s)

    if todays_events:
      print(f"[Daily] 오늘 진행되는 일정: {len(todays_events)}건")
      event_texts = [f"• **{ev['content']}** ({ev['date_raw']})" for ev in todays_events]
      desc = (
          f"📅 **{today_str} 오늘의 학사일정 안내**\n\n"
          + "\n".join(event_texts)
          + f"\n\n🔗 [학사일정 바로가기]({PAGE_URL})"
      )
      send_discord(
          WEBHOOK_DAILY,
          "☀️ 오늘의 학사일정",
          desc,
          3066993,
          "울산대 학사일정 데일리 알리미",
      )
    else:
      print(f"[Daily] {today_str} 오늘 예정된 학사일정 없음")

    state["last_daily_sent_date"] = today_str

  state["schedules"] = current_schedules
  with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
  check_and_notify()