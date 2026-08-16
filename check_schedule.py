import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
import requests
from playwright.sync_api import sync_playwright

# 환경변수 (오늘 일정용, 변경 업데이트용)
WEBHOOK_DAILY = os.environ.get("DISCORD_WEBHOOK_SCHEDULE_DAILY")
WEBHOOK_UPDATE = os.environ.get("DISCORD_WEBHOOK_SCHEDULE_UPDATE")

BASE_URL = "https://ict.ulsan.ac.kr"
PAGE_URL = f"{BASE_URL}/ict/5785"
STATE_FILE = "latest_schedule.json"

KST = timezone(timedelta(hours=9))


def parse_date_range(year_str, month_str, date_raw):
    """
    날짜 문자열을 시작일(start_date)과 종료일(end_date) 형태(YYYY-MM-DD)로 변환
    예시 1: '01일 (화)' -> (2026-09-01, 2026-09-01)
    예시 2: '03일 (목) ~ 07일 (월)' -> (2026-09-03, 2026-09-07)
    """
    try:
        year = int(re.sub(r'[^0-9]', '', year_str))
        month = int(re.sub(r'[^0-9]', '', month_str))
    except Exception:
        return None, None

    # 숫자와 물결표(~) 추출
    cleaned = re.sub(r'\([가-힣A-Za-z]\)', '', date_raw).strip()
    
    if '~' in cleaned:
        parts = cleaned.split('~')
        start_d_match = re.search(r'(\d+)', parts[0])
        end_d_match = re.search(r'(\d+)', parts[1])
        if start_d_match and end_d_match:
            s_day = int(start_d_match.group(1))
            e_day = int(end_d_match.group(1))
            start_date = f"{year:04d}-{month:02d}-{s_day:02d}"
            end_date = f"{year:04d}-{month:02d}-{e_day:02d}"
            return start_date, end_date
    else:
        d_match = re.search(r'(\d+)', cleaned)
        if d_match:
            day = int(d_match.group(1))
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            return date_str, date_str

    return None, None


def fetch_all_schedules():
    """1학기 및 2학기 탭을 모두 순회하여 전체 일정 추출"""
    schedules = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"[Fetch] 학사일정 페이지 접속: {PAGE_URL}")
        page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_selector(".tabcontent_schedule", timeout=15000)

        # 탭 요소 확인 (1학기, 2학기)
        tabs = page.query_selector_all(".tabnav_schedule li a, .tab li a, ul.tabnav_schedule a")
        
        tab_indices = range(len(tabs)) if tabs else [0]

        for idx in tab_indices:
            if tabs:
                try:
                    tabs[idx].click()
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

            # 각 월별 ul[id^="monScroll_"] 요소 파싱
            month_blocks = page.query_selector_all("ul[id^='monScroll_']")
            for block in month_blocks:
                # 연도 및 월 추출
                p_el = block.query_selector("p")
                if not p_el:
                    continue
                
                span_year = p_el.query_selector("span")
                year_text = span_year.inner_text().strip() if span_year else ""
                month_text = p_el.inner_text().replace(year_text, "").strip()

                if not year_text or not month_text:
                    continue

                # li 내부 일정 목록 파싱
                li_items = block.query_selector_all("li")
                for li in li_items:
                    b_el = li.query_selector("b")
                    date_raw = b_el.inner_text().strip() if b_el else ""
                    
                    # li 전체 텍스트에서 날짜(b_el) 제외하여 내용(content) 추출
                    full_text = li.inner_text().strip()
                    content = full_text.replace(date_raw, "").strip()
                    content = content.replace('"', '').strip()

                    if not content or not date_raw:
                        continue

                    start_date, end_date = parse_date_range(year_text, month_text, date_raw)
                    unique_id = f"{year_text}_{month_text}_{date_raw}_{content}"

                    schedules.append({
                        "id": unique_id,
                        "year": year_text,
                        "month": month_text,
                        "date_raw": date_raw,
                        "content": content,
                        "start_date": start_date,
                        "end_date": end_date
                    })

        browser.close()

    # 중복 제거 (ID 기준)
    dedup = {}
    for s in schedules:
        dedup[s["id"]] = s
    return list(dedup.values())


def send_discord(webhook_url, title, description, color, username):
    if not webhook_url:
        print(f"[Skip] {username} 웹훅이 설정되지 않았습니다.")
        return
    payload = {
        "username": username,
        "avatar_url": f"{BASE_URL}/favicon.ico",
        "embeds": [{
            "title": title,
            "description": description,
            "color": color
        }]
    }
    res = requests.post(webhook_url, json=payload)
    print(f"[Discord] {username} 전송 상태: {res.status_code}")
    time.sleep(0.5)


def check_and_notify():
    state = {"last_daily_sent_date": "", "schedules": []}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            print(f"[Warning] 상태 로드 실패: {e}")

    saved_schedules = state.get("schedules", [])
    last_daily_sent = state.get("last_daily_sent_date", "")

    # 1. 전체 일정 크롤링
    current_schedules = fetch_all_schedules()
    print(f"[Info] 수집된 전체 일정: {len(current_schedules)}개")

    # 2. 학사일정 변경/신규 등록 체크
    saved_ids = {s["id"] for s in saved_schedules}
    
    if saved_schedules:  # 최초 실행이 아닌 경우에만 변동 알림 발송
        new_or_modified = [s for s in current_schedules if s["id"] not in saved_ids]
        if new_or_modified:
            print(f"[Update] 변동된 학사일정: {len(new_or_modified)}개")
            for item in new_or_modified:
                desc = (
                    f"**일정**: {item['content']}\n"
                    f"**일시**: {item['year']} {item['month']} {item['date_raw']}\n\n"
                    f"🔗 [학사일정 바로가기]({PAGE_URL})"
                )
                send_discord(
                    WEBHOOK_UPDATE,
                    "🔔 학사일정이 추가/변경되었습니다",
                    desc,
                    15105570,  # 주황색
                    "울산대 학사일정 변경 알리미"
                )

    # 3. 오늘의 학사일정 알림 (한국 시간 기준 하루 1회)
    now_kst = datetime.now(KST)
    today_str = now_kst.strftime("%Y-%m-%d")

    # 오늘 하루 동안 이미 발송했는지 확인
    if last_daily_sent != today_str:
        todays_events = []
        for s in current_schedules:
            s_date = s.get("start_date")
            e_date = s.get("end_date")
            if s_date and e_date:
                if s_date <= today_str <= e_date:
                    todays_events.append(s)

        if todays_events:
            print(f"[Daily] 오늘 진행되는 일정 {len(todays_events)}건 발견")
            event_texts = []
            for ev in todays_events:
                event_texts.append(f"• **{ev['content']}** ({ev['date_raw']})")

            desc = f"📅 **{today_str} 오늘의 학사일정 안내**\n\n" + "\n".join(event_texts) + f"\n\n🔗 [학사일정 바로가기]({PAGE_URL})"
            send_discord(
                WEBHOOK_DAILY,
                "☀️ 오늘의 학사일정",
                desc,
                3066993,  # 에메랄드 그린
                "울산대 학사일정 데일리 알리미"
            )
        else:
            print("[Daily] 오늘 예정된 학사일정이 없습니다.")

        # 오늘 날짜 전송 완료 기록
        state["last_daily_sent_date"] = today_str

    # 상태 저장
    state["schedules"] = current_schedules
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    check_and_notify()