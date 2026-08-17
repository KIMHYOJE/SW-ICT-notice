import os
import time
import requests
from bs4 import BeautifulSoup
from firebase_helper import get_db
from firebase_admin import firestore

DISCORD_WEBHOOK_MUNSU = os.environ.get("DISCORD_WEBHOOK_MUNSU")
BASE_URL = "https://www.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/kor/CMS/Board/Board.do?mCode=MN125"

def send_discord_alert(notice):
    if not DISCORD_WEBHOOK_MUNSU:
        print("[Skip] DISCORD_WEBHOOK_MUNSU 웹훅 미설정")
        return

    payload = {
        "username": "울산대 문수게시판 알리미",
        "avatar_url": f"{BASE_URL}/favicon.ico",
        "embeds": [{
            "title": f"📋 {notice['title']}",
            "description": (
                f"**번호**: {notice['num']}\n"
                f"**작성자**: {notice['writer']}\n"
                f"**작성일**: {notice['date']}\n\n"
                f"🔗 [게시글 바로가기]({notice['link']})"
            ),
            "color": 3447003,
        }],
    }
    requests.post(DISCORD_WEBHOOK_MUNSU, json=payload)
    time.sleep(0.5)

def run():
    # Firestore DB 연결
    db = get_db()
    munsu_ref = db.collection("munsu_notices")

    # 1. Firestore에 저장된 기존 글 번호 불러오기
    docs = munsu_ref.stream()
    saved_ids = {doc.id for doc in docs}
    is_first_run = len(saved_ids) == 0

    print(f"[문수게시판] 기존 저장된 글 ID 수: {len(saved_ids)}개")

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        res = requests.get(LIST_URL, headers=headers, timeout=30)
        res.raise_for_status()
    except Exception as e:
        print(f"[Error] 문수게시판 접속 실패: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.select_one("table.board-list-table")
    if not table:
        print("[Error] 문수게시판 테이블을 찾을 수 없습니다.")
        return

    rows = table.select("tbody tr")
    current_notices = []
    for row in rows:
        num_el = row.select_one("td.num")
        num = num_el.get_text(strip=True) if num_el else ""
        if not num or num == "공지": continue # 번호 없는 행 제외

        link_el = row.select_one("td.subject p.stitle a, td.subject a")
        if not link_el: continue
        
        title = link_el.get_text(strip=True)
        href = link_el.get("href", "")
        writer = row.select_one("td.writer").get_text(strip=True) if row.select_one("td.writer") else ""
        date = row.select_one("td.date").get_text(strip=True) if row.select_one("td.date") else ""

        full_link = f"{BASE_URL}/kor/CMS/Board/Board.do{href}" if href.startswith("?") else href
        
        current_notices.append({
            "id": str(num), # 문수게시판은 게시글 번호가 고유함
            "num": num,
            "title": title,
            "writer": writer,
            "date": date,
            "link": full_link
        })

    # 2. 신규 글 필터링
    new_notices = [n for n in current_notices if n["id"] not in saved_ids]

    if not new_notices:
        print("[Info] 문수게시판에 새로운 글이 없습니다.")
        return

    print(f"[문수게시판] 신규 글 발견: {len(new_notices)}개")

    for notice in reversed(new_notices):
        if not is_first_run:
            send_discord_alert(notice)
        
        # Firestore 저장
        munsu_ref.document(notice["id"]).set({
            "title": notice["title"],
            "writer": notice["writer"],
            "date": notice["date"],
            "link": notice["link"],
            "num": notice["num"],
            "createdAt": firestore.SERVER_TIMESTAMP
        })

    print(f"[Success] 문수게시판 Firestore 동기화 완료")

if __name__ == "__main__":
    run()