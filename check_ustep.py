import json
import os
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


def scrape_cards_all_pages(page, mile_value):
    """특정 마일리지 구분의 모든 페이지를 순회하며 수집"""
    programs = []
    page_num = 1

    while True:
        target_url = f"{LIST_URL}?schMile={mile_value}&pageIndex={page_num}"
        page.goto(target_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)

        # 프로그램 카드 탐색
        cards = page.query_selector_all(".board-list-program a.item, .board-list-program .schedule-slide-wrap a.item")
        if not cards:
            cards = page.query_selector_all("a.item")

        # 해당 페이지에 카드가 없으면 마지막 페이지로 판단하고 종료
        if not cards:
            break

        current_page_count = 0
        for card in cards:
            # 제목 추출
            subj_el = card.query_selector(".board-subject, .board-con")
            title = subj_el.inner_text().strip() if subj_el else ""
            if not title:
                continue

            # 이미지 URL 추출
            img_el = card.query_selector(".board-img img, img")
            img_src = img_el.get_attribute("src") if img_el else ""
            if img_src and not img_src.startswith("http"):
                img_src = f"{BASE_URL}{img_src}"

            # D-Day 추출
            dday_el = card.query_selector(".badge-day, span[class*='badge']")
            d_day = dday_el.inner_text().strip() if dday_el else ""

            # 신청 기간 추출
            time_el = card.query_selector(".board-time")
            apply_period = time_el.inner_text().replace("\n", " ").strip() if time_el else ""

            # 링크 추출
            href = card.get_attribute("href") or ""
            link = f"{BASE_URL}{href}" if href.startswith("/") else href

            prog_id = f"{mile_value}_{href}" if href else f"{mile_value}_{title}"

            programs.append({
                "id": prog_id,
                "mile_type": mile_value,
                "title": title,
                "img_url": img_src,
                "d_day": d_day,
                "apply_period": apply_period,
                "link": link
            })
            current_page_count += 1

        print(f"[{MILEAGE_CONFIG[mile_value]['name']}] {page_num}페이지 수집 완료: {current_page_count}개")

        # 다음 페이지 존재 여부 확인 (페이지네이션 번호 또는 버튼 확인)
        # 전체 건수/페이지 표시 확인 (예: 현재 페이지 1 / 1 인 경우 중단)
        page_info_el = page.query_selector("span:has-text('현재 페이지'), .page-info")
        page_info_text = page_info_el.inner_text() if page_info_el else ""
        
        # 1페이지뿐이거나 마지막 페이지에 도달한 경우 루프 종료
        if "/1" in page_info_text and page_num >= 1:
            break

        # 다음 페이지 번호 링크가 DOM에 없으면 종료
        next_page_btn = page.query_selector(f"a[data-page='{page_num + 1}'], .paging a:has-text('{page_num + 1}')")
        if not next_page_btn and page_num > 1:
            break

        page_num += 1
        # 안전장치: 최대 10페이지까지만 탐색
        if page_num > 10:
            break

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

    print(f"[U-STEP] 이전 저장된 ID 수: {len(sent_ids)}개")

    all_progs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1: 일반 장학, 2: 도전 장학 순회 (모든 페이지 탐색)
        for m_type in ["1", "2"]:
            progs = scrape_cards_all_pages(page, m_type)
            all_progs.extend(progs)

        browser.close()

    # sent_ids에 없는 신규 프로그램만 필터링
    new_progs = [p for p in all_progs if p["id"] not in sent_ids]

    if not new_progs:
        print("[Info] U-STEP에 새로운 프로그램이 없습니다.")
        return

    print(f"[U-STEP] 새로 감지된 프로그램: {len(new_progs)}개")

    # 오래된 글부터 순서대로 발송
    for prog in reversed(new_progs):
        send_discord_alert(prog)
        sent_ids.add(prog["id"])

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"sent_ids": list(sent_ids)}, f, ensure_ascii=False, indent=2)

    print(f"[Success] U-STEP 상태 저장 완료 (총 {len(sent_ids)}개 기록)")


if __name__ == "__main__":
    run()