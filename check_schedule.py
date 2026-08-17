import os
import time
import requests
from bs4 import BeautifulSoup
from firebase_helper import get_db
from firebase_admin import firestore

DISCORD_WEBHOOK_DAILY = os.environ.get("DISCORD_WEBHOOK_SCHEDULE_DAILY")
DISCORD_WEBHOOK_UPDATE = os.environ.get("DISCORD_WEBHOOK_SCHEDULE_UPDATE")
URL = "https://www.ulsan.ac.kr/kor/CMS/AcademicCal/AcademicCal.do"

def send_discord_alert(schedule, is_update=False):
    webhook = DISCORD_WEBHOOK_UPDATE if is_update else DISCORD_WEBHOOK_DAILY
    if not webhook: return

    payload = {
        "username": "울산대 학사일정 알리미",
        "embeds": [{
            "title": f"📅 {'[변경/신규]' if is_update else '[오늘의 일정]'} {schedule['date_raw']}",
            "description": schedule['content'],
            "color": 16753920 if is_update else 3447003,
        }]
    }
    requests.post(webhook, json=payload)
    time.sleep(0.5)

def run():
    db = get_db()
    sched_ref = db.collection("academic_schedules")

    # 1. Firestore 기존 ID 불러오기
    docs = sched_ref.stream()
    saved_ids = {doc.id for doc in docs}
    is_first_run = len(saved_ids) == 0

    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(URL, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    
    # 학사일정 테이블 추출 (사이트 구조에 맞게 조정 필요)
    schedules = []
    # 예시: 연월별로 일정을 순회하며 데이터 추출
    items = soup.select(".cal-list li") # 실제 사이트의 일정 리스트 태그 확인 필요
    
    for item in items:
        date_raw = item.select_one(".date").get_text(strip=True) if item.select_one(".date") else ""
        content = item.select_one(".txt").get_text(strip=True) if item.select_one(".txt") else ""
        
        # 고유 ID 생성
        doc_id = f"{date_raw.replace('.', '_')}_{content.replace(' ', '_')}"
        
        schedules.append({
            "id": doc_id,
            "date_raw": date_raw,
            "content": content
        })

    # 2. 신규 일정 필터링
    new_schedules = [s for s in schedules if s["id"] not in saved_ids]

    if not new_schedules:
        print("[Info] 새로운 학사일정이 없습니다.")
        return

    print(f"[학사일정] 신규 일정 발견: {len(new_schedules)}개")

    for sched in new_schedules:
        if not is_first_run:
            send_discord_alert(sched, is_update=True)
        
        sched_ref.document(sched["id"]).set({
            "date_raw": sched["date_raw"],
            "content": sched["content"],
            "createdAt": firestore.SERVER_TIMESTAMP
        })

    print(f"[Success] 학사일정 Firestore 동기화 완료")

if __name__ == "__main__":
    run()