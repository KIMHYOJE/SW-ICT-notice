import json
import os
import re
import time
import requests
from playwright.sync_api import sync_playwright

WEBHOOK_GENERAL = os.environ.get("DISCORD_WEBHOOK_GENERAL")
WEBHOOK_CHALLENGE = os.environ.get("DISCORD_WEBHOOK_CHALLENGE")

BASE_URL = "https://ustep.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/home/sub/prog-list"
STATE_FILE = "latest_ustep.json"

MILEAGE_CONFIG = {
    "1": {
        "name": "일반 장학",
        "webhook": WEBHOOK_GENERAL,
        "color": 3447003,      # 파란색
        "badge": "📘 [일반 장학]"
    },
    "2": {
        "name": "도전 장학",
        "webhook": WEBHOOK_CHALLENGE,
        "color": 15844367,     # 골드/노란색
        "badge": "🏆 [도전 장학]"
    }
}


def extract_prog_id(href, title, mile_type):
    """URL 쿼리에서 고유 번호(MA_IDX, SUB_IDX) 추출"""
    ma = re.search(r'MA_IDX=(\d+)', href)
    sub = re.search(r'SUB_IDX=(\d+)', href)
    if ma and sub:
        return f"{mile_type}_{ma.group(1)}_{sub.group(1)}"
    elif ma:
        return f"{mile_type}_{ma.group(1)}"
    return f"{mile_type}_{title.strip()}"


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
            f"**상태/D-Day**: {prog['d_day']}\n"
            f"**신청/운영기간**:\n{prog['apply_period']}\n\n"
            f"🔗 [프로그램 바로가기]({prog['link']})"
        ),
        "color": config["color"]
    }

    if prog["img_url"]:
        embed["image"] = {"url": prog["img_url"]}

    payload = {
        "username": f"U-STEP {config['name']} 알리미",
        "avatar_url": f"{BASE_URL}/favicon.ico",
        "embeds": [embed]
    }

    res = requests.post(config["webhook"], json=payload)
    print(f"[Discord] {config['name']} 전송: {prog['title'][:15]}... -> {res.status_code}")
    time.sleep(0.6)


def scrape_by_mileage(page, mile_value):
    """드롭다운 직접 선택 후 카드 크롤링"""
    programs = []
    
    # 1. 페이지 접속
    page.goto(LIST_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_selector("select#schMile", timeout=20000)

    # 2. 마일리지 드롭다운 선택 및 change 이벤트 발생
    page.select_option("select#schMile", mile_value)
    # 검색 폼 제출 또는 엔터/버튼 클릭 트리거
    page.evaluate("""() => {
        const select = document.querySelector('select#schMile');
        if (select) {
            select.dispatchEvent(new Event('change', { bubbles: true }));
        }
        const form = document.querySelector('form');
        if (form && form.submit) {
            // submit 함수가 있으면 호출
        }
    }""")
    page.wait_for_timeout(2000)  # 목록 갱신 대기

    # 3. 카드 목록 (a.item) 탐색
    cards = page.query_selector_all("a.item")
    print(f"[{MILEAGE_CONFIG[mile_value]['name']}] 감지된 카드 태그: {len(cards)}개")

    for card in cards:
        # 제목 추출: board-con 우선 (텍스트가 있는 요소를 탐색)
        title = ""
        con_el = card.query_selector(".board-con")
        subj_el = card.query_selector(".board-subject")
        
        if con_el and con_el.inner_text().strip():
            title = con_el.inner_text().strip()
        elif subj_el and subj_el.inner_text().strip():
            title = subj_el.inner_text().strip()
        
        # 그래도 없으면 h4, strong 탐색
        if not title:
            h_el = card.query_selector("h4, strong, .title")
            if h_el:
                title = h_el.inner_text().strip()

        if not title:
            continue

        # 이미지 URL 추출
        img_el = card.query_selector("img")
        img_src = img_el.get_attribute("src") if img_el else ""
        if img_src and not img_src.startswith("http"):
            img_src = f"{BASE_URL}{img_src}"

        # D-Day 추출
        dday_el = card.query_selector(".badge-day, span[class*='badge']")
        d_day = dday_el.inner_text().strip() if dday_el else ""

        # 신청 기간 / 운영 기간
        time_el = card.query_selector(".board-time")
        apply_period = time_el.inner_text().strip() if time_el else ""

        # 링크
        href = card.get_attribute("href") or ""
        link = f"{BASE_URL}{href}" if href.startswith("/") else href

        # 고유 식별 ID
        prog_id = extract_prog_id(href, title, mile_value)

        programs.append({
            "id": prog_id,
            "mile_type": mile_value,
            "title": title,
            "img_url": img_src,
            "d_day": d_day,
            "apply_period": apply_period,
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
            print(f"[Warning] 상태 파일 로드 에러: {e}")

    print(f"[U-STEP] 기존 저장된 ID 수: {len(sent_ids)}개")

    all_programs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1: 일반 장학, 2: 도전 장학 순회
        print("[Fetch] 일반 장학 조회 시작...")
        all_programs.extend(scrape_by_mileage(page, "1"))

        print("[Fetch] 도전 장학 조회 시작...")
        all_programs.extend(scrape_by_mileage(page, "2"))

        browser.close()

    print(f"[U-STEP] 총 수집된 프로그램 수: {len(all_programs)}개")

    # 신규 프로그램 필터링
    new_programs = [p for p in all_programs if p["id"] not in sent_ids]

    if not new_programs:
        print("[Info] U-STEP에 새로운 프로그램이 없습니다.")
        return

    print(f"[Alert] 새로 감지되어 전송할 프로그램: {len(new_programs)}개")

    # 디스코드 전송 (오래된 순서대로)
    for prog in reversed(new_programs):
        send_discord_alert(prog)
        sent_ids.add(prog["id"])

    # 상태 저장
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

    print(f"[Success] U-STEP 상태 저장 완료 (총 {len(sent_ids)}개 기록)")


if __name__ == "__main__":
    run()