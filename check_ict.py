import os
import time
import requests
from bs4 import BeautifulSoup
from firebase_helper import get_db
from firebase_admin import firestore

DISCORD_WEBHOOK_ICT = os.environ.get("DISCORD_WEBHOOK_ICT")
BASE_URL = "https://ict.ulsan.ac.kr"
LIST_URL = f"{BASE_URL}/ict/5786"


def send_discord_alert(notice):
    """ICT융합학부 학과게시판 디스코드 웹훅 알림 전송"""
    if not DISCORD_WEBHOOK_ICT:
        print("[Skip] DISCORD_WEBHOOK_ICT 환경변수가 설정되지 않았습니다.")
        return

    badge = "📌 [공지] " if notice["is_notice"] else "📄 "
    color = 15158332 if notice["is_notice"] else 3066993

    payload = {
        "username": "울산대 ICT융합학부 공지 알리미",
        "avatar_url": f"{BASE_URL}/favicon.ico",
        "embeds": [
            {
                "title": f"{badge}{notice['title']}",
                "description": (
                    f"**번호**: {notice['num']}\n"
                    f"**작성자**: {notice['writer']}\n"
                    f"**작성일**: {notice['date']}\n\n"
                    f"🔗 [게시글 바로가기]({notice['link']})"
                ),
                "color": color,
            }
        ],
    }

    res = requests.post(DISCORD_WEBHOOK_ICT, json=payload)
    print(f"[Discord] ICT 전송: {notice['title'][:15]}... -> {res.status_code}")
    time.sleep(0.5)


def run():
    # Firestore DB 연결
    db = get_db()
    ict_ref = db.collection("ict_notices")

    # 1. Firestore에 저장된 기존 글 ID 목록 불러오기
    print("[Fetch] Firestore에서 기존 데이터 조회 중...")
    docs = ict_ref.stream()
    sent_ids = {doc.id for doc in docs}
    
    # Firestore에 데이터가 하나도 없으면 최초 실행으로 간주 (알림 스킵)
    is_first_run = len(sent_ids) == 0
    print(f"[ICT 학과게시판] 기존 저장된 글 ID 수: {len(sent_ids)}개")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        res = requests.get(LIST_URL, headers=headers, timeout=30)
        res.raise_for_status()
    except Exception as e:
        print(f"[Error] ICT 학과게시판 접속 실패: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.select_one("table.a_brdList")
    if not table:
        print("[Error] ICT 학과게시판 테이블을 찾을 수 없습니다.")
        return

    rows = table.select("tbody tr")
    print(f"[Info] ICT 학과게시판에서 총 {len(rows)}개의 행을 감지했습니다.")

    current_notices = []
    for row in rows:
        is_notice = "noti" in row.get("class", []) or row.select_one("td.bdlNum.noti") is not None
        num_el = row.select_one("td.bdlNum")
        num_text = num_el.get_text(strip=True) if num_el else ""

        link_el = row.select_one("td.bdlTitle a")
        if not link_el:
            continue
        title = link_el.get_text(strip=True)
        href = link_el.get("href", "")

        user_el = row.select_one("td.bdlUser")
        writer = user_el.get_text(strip=True) if user_el else "관리자"

        date_el = row.select_one("td.bdlDate")
        date = date_el.get_text(strip=True) if date_el else ""

        if not title:
            continue

        if href.startswith("?"):
            full_link = f"{LIST_URL}{href}"
        elif href.startswith("/"):
            full_link = f"{BASE_URL}{href}"
        else:
            full_link = href

        # 고유 식별키 생성 후 특수문자(/ 등) 치환 (Firestore Document ID 규칙)
        raw_id = href if href else f"{date}_{title}"
        doc_id = raw_id.replace("/", "_").replace("?", "_").replace("=", "_").replace("&", "_")

        current_notices.append({
            "doc_id": doc_id,
            "num": "공지" if is_notice else num_text,
            "title": title,
            "writer": writer,
            "date": date,
            "link": full_link,
            "is_notice": is_notice,
        })

    # 2. sent_ids에 없는 새 글 필터링
    new_notices = [n for n in current_notices if n["doc_id"] not in sent_ids]

    if not new_notices:
        print("[Info] ICT 학과게시판에 새로 전송할 공지가 없습니다.")
        return

    print(f"[ICT 학과게시판] 새로 감지되어 등록할 공지: {len(new_notices)}개")

    # 오래된 글부터 순서대로 발송 및 Firestore 저장
    for notice in reversed(new_notices):
        # 최초 실행일 때는 디스코드 알림 생략하고 DB에만 저장
        if not is_first_run:
            send_discord_alert(notice)
        
        # Firestore에 문서 생성
        doc_data = {
            "title": notice["title"],
            "num": notice["num"],
            "writer": notice["writer"],
            "date": notice["date"],
            "link": notice["link"],
            "is_notice": notice["is_notice"],
            "createdAt": firestore.SERVER_TIMESTAMP  # Flutter에서 최신순 정렬 시 사용
        }
        
        ict_ref.document(notice["doc_id"]).set(doc_data)

    print(f"[Success] ICT 학과게시판 Firestore 동기화 완료 (신규 {len(new_notices)}건)")


if __name__ == "__main__":
    run()