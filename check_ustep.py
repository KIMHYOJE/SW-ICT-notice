import os
import re
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from firebase_helper import get_db
from firebase_admin import firestore

WEBHOOK_GENERAL = os.environ.get("DISCORD_WEBHOOK_GENERAL")
WEBHOOK_CHALLENGE = os.environ.get("DISCORD_WEBHOOK_CHALLENGE")

BASE_URL = "https://ustep.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/home/sub/prog-list"

MILEAGE_CONFIG = {
    "1": {
        "name": "일반 장학",
        "webhook": WEBHOOK_GENERAL,
        "color": 3447003,
        "badge": "📘 [일반 장학]"
    },
    "2": {
        "name": "도전 장학",
        "webhook": WEBHOOK_CHALLENGE,
        "color": 15844367,
        "badge": "🏆 [도전 장학]"
    }
}


def extract_prog_id(href, title, mile_type):
    """URL에서 MA_IDX와 SUB_IDX 고유 번호 추출"""
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


def scrape_all_cards_for_mileage(page, mile_value):
    """드롭다운 선택 후 1페이지부터 끝 페이지까지 버튼 클릭하며 전부 수집"""
    programs = []
    
    page.goto(LIST_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_selector("select#schMile", timeout=20000)

    page.select_option("select#schMile", mile_value)
    page.evaluate("document.querySelector('select#schMile').dispatchEvent(new Event('change', { bubbles: true }))")
    page.wait_for_timeout(2000)

    current_page = 1

    while True:
        print(f"[{MILEAGE_CONFIG[mile_value]['name']}] {current_page}페이지 탐색 중...")
        cards = page.query_selector_all("div.sub-con a.item[href*='prog-detail']")
        
        page_items_count = 0
        for card in cards:
            href = card.get_attribute("href") or ""
            if "prog-detail" not in href:
                continue

            title = ""
            con_el = card.query_selector(".board-con")
            subj_el = card.query_selector(".board-subject")
            
            if con_el and con_el.inner_text().strip():
                title = con_el.inner_text().strip()
            elif subj_el and subj_el.inner_text().strip():
                title = subj_el.inner_text().strip()
            
            if not title:
                continue

            img_el = card.query_selector(".board-img img, img")
            img_src = img_el.get_attribute("src") if img_el else ""
            if img_src and not img_src.startswith("http"):
                img_src = f"{BASE_URL}{img_src}"

            dday_el = card.query_selector(".badge-day, span[class*='badge-day']")
            d_day = dday_el.inner_text().strip() if dday_el else ""

            time_el = card.query_selector(".board-time")
            apply_period = time_el.inner_text().strip() if time_el else ""

            link = f"{BASE_URL}{href}" if href.startswith("/") else href
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
            page_items_count += 1

        print(f"[{MILEAGE_CONFIG[mile_value]['name']}] {current_page}페이지에서 {page_items_count}개 수집")

        next_page = current_page + 1
        next_btn = page.query_selector(f"div.board-page a.btn-page[data-page='{next_page}']")

        if next_btn:
            next_btn.click()
            page.wait_for_timeout(2000)
            current_page = next_page
        else:
            print(f"[{MILEAGE_CONFIG[mile_value]['name']}] 마지막 페이지 도달")
            break

        if current_page > 15:
            break

    return programs


def run():
    # Firestore DB 연결
    db = get_db()
    ustep_ref = db.collection("ustep_programs")

    # 1. Firestore에 저장된 기존 프로그램 ID 목록 불러오기
    docs = ustep_ref.stream()
    saved_ids = {doc.id for doc in docs}
    is_first_run = len(saved_ids) == 0

    print(f"[U-STEP] 기존 저장된 프로그램 ID 수: {len(saved_ids)}개")

    all_programs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("[Fetch] 일반 장학 전체 페이지 수집 시작...")
        all_programs.extend(scrape_all_cards_for_mileage(page, "1"))

        print("[Fetch] 도전 장학 전체 페이지 수집 시작...")
        all_programs.extend(scrape_all_cards_for_mileage(page, "2"))

        browser.close()

    print(f"[U-STEP] 총 수집된 프로그램 수: {len(all_programs)}개")

    # 신규 프로그램 필터링
    new_programs = [p for p in all_programs if p["id"] not in saved_ids]

    if not new_programs:
        print("[Info] U-STEP에 새로운 프로그램이 없습니다.")
        return

    print(f"[Alert] 새로 감지된 프로그램: {len(new_programs)}개")

    for prog in reversed(new_programs):
        if not is_first_run:
            send_discord_alert(prog)
        
        # Firestore 저장
        ustep_ref.document(prog["id"]).set({
            "mile_type": prog["mile_type"],
            "title": prog["title"],
            "img_url": prog["img_url"],
            "d_day": prog["d_day"],
            "apply_period": prog["apply_period"],
            "link": prog["link"],
            "createdAt": firestore.SERVER_TIMESTAMP
        })

    print(f"[Success] U-STEP Firestore 동기화 완료")


if __name__ == "__main__":
    run()