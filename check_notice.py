import os
import time
import requests
from playwright.sync_api import sync_playwright
from firebase_helper import get_db
from firebase_admin import firestore

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
BASE_URL = "https://sw.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/sub.php?code=notice"

def send_discord_alert(notice):
    if not DISCORD_WEBHOOK:
        print("[Skip] DISCORD_WEBHOOK 웹훅 미설정")
        return

    badge = "📌 [공지]" if notice["is_important"] else "📄"
    color = 15158332 if notice["is_important"] else 3066993

    payload = {
        "username": "울산대 SW중심대학 공지 알리미",
        "avatar_url": f"{BASE_URL}/favicon.ico",
        "embeds": [{
            "title": f"{badge} {notice['title']}",
            "description": (
                f"**작성자**: {notice['writer']}\n"
                f"**작성일**: {notice['date']}\n\n"
                f"🔗 [게시글 바로가기]({notice['link']})"
            ),
            "color": color,
        }],
    }
    requests.post(DISCORD_WEBHOOK, json=payload)
    time.sleep(0.5)

def run():
    # Firestore DB 연결
    db = get_db()
    sw_ref = db.collection("sw_notices")

    # 1. Firestore에 저장된 기존 글 ID 목록 불러오기
    docs = sw_ref.stream()
    saved_ids = {doc.id for doc in docs}
    is_first_run = len(saved_ids) == 0

    print(f"[SW공지] 기존 저장된 글 ID 수: {len(saved_ids)}개")

    current_notices = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(LIST_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_selector("table tbody tr", timeout=20000)
        except Exception as e:
            print(f"[Error] SW공지 페이지 로딩 실패: {e}")
            browser.close()
            return

        rows = page.query_selector_all("table tbody tr")
        print(f"[Info] SW공지에서 총 {len(rows)}개의 행을 감지했습니다.")

        for row in rows:
            data_id = row.get_attribute("data-id")
            
            link_el = row.query_selector("td.subject a, a")
            if not link_el:
                continue
                
            title = link_el.inner_text().strip()
            href = link_el.get_attribute("href") or ""
            
            if not data_id:
                doc_id = href.replace("/", "_").replace("?", "_").replace("=", "_") or title
            else:
                doc_id = str(data_id)

            if not title:
                continue

            if href.startswith("http"):
                full_link = href
            elif href.startswith("/"):
                full_link = f"{BASE_URL}{href}"
            else:
                full_link = f"{BASE_URL}/{href}"

            tds = row.query_selector_all("td")
            writer = tds[2].inner_text().strip() if len(tds) > 2 else "관리자"
            date = tds[3].inner_text().strip() if len(tds) > 3 else ""

            row_class = row.get_attribute("class") or ""
            is_important = "notice" in row_class or "important" in row_class

            current_notices.append({
                "id": doc_id,
                "title": title,
                "writer": writer,
                "date": date,
                "link": full_link,
                "is_important": is_important
            })

        browser.close()

    # 2. 신규 공지 필터링
    new_notices = [n for n in current_notices if n["id"] not in saved_ids]

    if not new_notices:
        print("[Info] SW중심대학 공지에 새로운 글이 없습니다.")
        return

    print(f"[SW공지] 신규 글 발견: {len(new_notices)}개")

    for notice in reversed(new_notices):
        if not is_first_run:
            send_discord_alert(notice)
        
        # Firestore 저장
        sw_ref.document(notice["id"]).set({
            "title": notice["title"],
            "writer": notice["writer"],
            "date": notice["date"],
            "link": notice["link"],
            "is_important": notice["is_important"],
            "createdAt": firestore.SERVER_TIMESTAMP
        })

    print(f"[Success] SW중심대학 공지 Firestore 동기화 완료")

if __name__ == "__main__":
    run()