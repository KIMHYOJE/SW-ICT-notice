import json
import os
import time
import requests
from playwright.sync_api import sync_playwright

# 환경변수에서 일반/도전 웹훅 각각 로드
WEBHOOK_GENERAL = os.environ.get("DISCORD_WEBHOOK_GENERAL")
WEBHOOK_CHALLENGE = os.environ.get("DISCORD_WEBHOOK_CHALLENGE")

BASE_URL = "https://ustep.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/home/sub/prog-list"
STATE_FILE = "latest_ustep.json"

# 마일리지 유형별 설정 (전송 대상 웹훅, 색상, 라벨)
MILEAGE_CONFIG = {
    "1": {
        "name": "일반 장학",
        "webhook": WEBHOOK_GENERAL,
        "color": 3447003,      # 블루
        "badge": "📘 [일반 장학]"
    },
    "2": {
        "name": "도전 장학",
        "webhook": WEBHOOK_CHALLENGE,
        "color": 15844367,     # 골드/옐로우
        "badge": "🏆 [도전 장학]"
    }
}


def send_discord_alert(program):
    """지정된 마일리지 전용 웹훅으로 임베드 + 썸네일 전송"""
    mile_type = program["mile_type"]
    config = MILEAGE_CONFIG.get(mile_type)

    if not config:
        print(f"[Error] 알 수 없는 마일리지 타입: {mile_type}")
        return

    target_webhook = config["webhook"]
    if not target_webhook:
        print(f"[Warning] {config['name']}용 웹훅 환경변수가 설정되지 않아 건너뜁니다.")
        return

    embed = {
        "title": f"{config['badge']} {program['title']}",
        "description": (
            f"**구분**: {config['name']}\n"
            f"**상태/D-Day**: {program['d_day']}\n"
            f"**학기**: {program['semester']}\n\n"
            f"🔗 [프로그램 바로가기]({program['link']})"
        ),
        "color": config["color"]
    }

    # 썸네일 이미지 포함
    if program["img_url"]:
        embed["image"] = {"url": program["img_url"]}

    payload = {
        "username": f"U-STEP {config['name']} 알리미",
        "avatar_url": f"{BASE_URL}/favicon.ico",
        "embeds": [embed]
    }

    res = requests.post(target_webhook, json=payload)
    print(f"[Discord] {config['name']} 전송: {program['title'][:15]}... -> {res.status_code}")
    time.sleep(0.6)  # Rate Limit 방지


def scrape_programs_by_mileage(page, mile_value):
    """드롭다운(일반/도전) 선택 후 리스트 크롤링"""
    programs = []

    page.select_option("select#schMile", mile_value)
    page.wait_for_timeout(1500)  # AJAX 렌더링 대기

    # 프로그램 카드 영역 선택
    cards = page.query_selector_all(".board-list-program .program-item, .board-list-program li, .board-list-program > div")

    for card in cards:
        title_el = card.query_selector("strong, .title, .tit, h4")
        title = title_el.inner_text().strip() if title_el else ""
        if not title:
            continue

        img_el = card.query_selector("img")
        img_src = img_el.get_attribute("src") if img_el else ""
        if img_src and img_src.startswith("/"):
            img_src = f"{BASE_URL}{img_src}"

        dday_el = card.query_selector(".d-day, span[class*='d-'], .badge")
        d_day = dday_el.inner_text().strip() if dday_el else "진행중"

        semester_el = card.query_selector(".semester, .cate, span")
        semester = semester_el.inner_text().strip() if semester_el else ""

        link_el = card.query_selector("a")
        link = link_el.get_attribute("href") if link_el else LIST_URL
        if link.startswith("/"):
            link = f"{BASE_URL}{link}"

        # 고유 식별키 (마일리지타입 + 제목)
        unique_key = f"{mile_value}_{title}"

        programs.append({
            "id": unique_key,
            "mile_type": mile_value,
            "title": title,
            "img_url": img_src,
            "d_day": d_day,
            "semester": semester,
            "link": link
        })

    return programs


def run():
    sent_ids = set()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                sent_ids = set(data.get("sent_ids", []))
        except Exception as e:
            print(f"[Warning] 상태 파일 로드 실패: {e}")

    all_programs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"[Fetch] U-STEP 접속 중: {LIST_URL}")
        page.goto(LIST_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_selector("select#schMile", timeout=15000)

        # 1. 일반 장학 수집
        print("[Fetch] 일반 장학 목록 조회...")
        all_programs.extend(scrape_programs_by_mileage(page, "1"))

        # 2. 도전 장학 수집
        print("[Fetch] 도전 장학 목록 조회...")
        all_programs.extend(scrape_programs_by_mileage(page, "2"))

        browser.close()

    # 새로운 비교과 프로그램 필터링
    new_programs = [p for p in all_programs if p["id"] not in sent_ids]

    if not new_programs:
        print("[Info] 새로 올라온 비교과 프로그램이 없습니다.")
        return

    print(f"[Alert] 새로 감지된 프로그램 수: {len(new_programs)}개")

    # 과거 순서부터 각 채널로 발송
    for prog in reversed(new_programs):
        send_discord_alert(prog)
        sent_ids.add(prog["id"])

    # 상태 저장
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

    print(f"[Success] 상태 저장 완료 (총 {len(sent_ids)}개 기록)")


if __name__ == "__main__":
    run()