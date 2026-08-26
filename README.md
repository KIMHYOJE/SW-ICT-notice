
# 🔔 울산대학교 주요 공지사항 자동 알림 봇 

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat-square&logo=python)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Automated-2088FF?style=flat-square&logo=github-actions)
![Firebase](https://img.shields.io/badge/Firebase-Database-FFCA28?style=flat-square&logo=firebase)

울산대학교의 여러 웹사이트에 흩어져 있는 주요 공지사항을 주기적으로 크롤링하고, 새로운 게시글이나 일정이 등록되면 **Discord 채널로 즉시 알림을 전송**하는 서버리스(Serverless) 자동화 봇입니다.

## 📌 프로젝트 기획 배경 및 목적

학업과 병행하며 매번 학교 홈페이지, 학부 사이트, 사업단 홈페이지를 일일이 확인하는 것은 매우 번거로운 일입니다. 특히 마감이 있는 프로그램이나 중요한 학사일정을 놓치지 않기 위해 이 프로젝트를 기획했습니다.

- **파편화된 정보 통합:** 대학 홈페이지, ICT융합학부, U-STEP 사업단, 문수관 등 분산된 공지를 한 곳에서 받아볼 수 있습니다.
- **비용 제로 서버리스 아키텍처:** 별도의 서버를 호스팅할 필요 없이 **GitHub Actions의 스케줄러(Cron)**를 활용해 주기적으로 자동 실행됩니다.
- **신속한 정보 전달:** 웹 크롤러가 새 글을 감지하는 즉시 디스코드 웹훅(Webhook)을 통해 메시지를 전송합니다.

---

## 🚀 주요 기능 및 크롤링 대상

웹페이지 구조에 맞춘 개별 파이썬 스크립트가 각 사이트를 모니터링합니다.

* 🏛 **일반 학사 공지** (`check_notice.py`) : 학교 메인 홈페이지의 주요 학사 공지사항 모니터링
* 💻 **ICT융합학부 공지** (`check_ict.py`) : 전공 관련 중요 공지 및 취업/행사 정보 모니터링
* 📈 **U-STEP 사업단 공지** (`check_ustep.py`) : U-STEP 관련 모집 및 안내 사항 모니터링
* 🏢 **문수관 공지** (`check_munsu.py`) : 문수관(기숙사 등) 관련 생활 공지 모니터링
* 📅 **학사일정 업데이트** (`check_schedule.py`) : 변동되거나 새로 추가되는 주요 학사일정 모니터링

---

## 🏗 시스템 아키텍처 및 동작 원리

본 프로젝트는 **GitHub Actions -> Python Crawler -> Firebase -> Discord** 흐름으로 동작합니다.

1. **스케줄링 (GitHub Actions):** `.github/workflows/check_notice.yml`에 설정된 시간에 따라 크롤링 스크립트가 자동 실행됩니다.
2. **데이터 파싱 및 비교 (Python):** 
   - 각 사이트의 최신 글 목록을 가져옵니다.
   - `latest_*.json` 파일에 기록된 마지막 게시글 ID와 비교하여 **새로운 글인지 판별**합니다.
3. **데이터베이스 업데이트 (Firebase):** `firebase_helper.py`를 통해 파이어베이스에 데이터를 백업 및 연동합니다.
4. **알림 전송 (Discord Webhook):** 새로운 글로 판별되면 디스코드 채널로 서식이 적용된 알림 메시지를 전송합니다.
5. **상태 저장 (Auto Commit):** 알림 전송이 완료되면 `latest_*.json` 파일을 업데이트하고, GitHub Actions 봇이 `[skip ci]` 태그와 함께 변경된 상태를 저장소에 자동 커밋합니다.

---

## 📁 디렉토리 및 주요 파일 구조

```plaintext
📦 sw
 ┣ 📂 .github
 ┃ ┗ 📂 workflows
 ┃   ┗ 📜 check_notice.yml      # GitHub Actions 스케줄링 및 CI/CD 설정 파일
 ┣ 📜 check_notice.py           # 일반 공지사항 크롤러
 ┣ 📜 check_ict.py              # ICT융합학부 공지사항 크롤러
 ┣ 📜 check_ustep.py            # U-STEP 사업단 공지사항 크롤러
 ┣ 📜 check_munsu.py            # 문수관 공지사항 크롤러
 ┣ 📜 check_schedule.py         # 학사일정 크롤러
 ┣ 📜 firebase_helper.py        # Firebase Realtime/Firestore DB 통신 헬퍼 모듈
 ┣ 📜 latest_notice.json        # 마지막으로 확인한 일반 공지 상태 저장
 ┣ 📜 latest_ict.json           # 마지막으로 확인한 ICT 공지 상태 저장
 ┣ 📜 latest_ustep.json         # 마지막으로 확인한 U-STEP 공지 상태 저장
 ┣ 📜 latest_munsu.json         # 마지막으로 확인한 문수관 공지 상태 저장
 ┣ 📜 latest_schedule.json      # 마지막으로 확인한 학사일정 상태 저장
 ┣ 📜 requirements.txt          # 프로젝트 실행에 필요한 파이썬 패키지 목록
 ┗ 📜 SECURITY.md               # 보안 정책 및 취약점 제보 가이드

```

---

## ⚙️ 로컬 환경 설정 및 실행 방법

직접 PC에서 실행해 보거나 코드를 수정하려면 아래 단계를 따라주세요.

### 1. 저장소 클론 및 패키지 설치

```bash
# 저장소 클론
git clone [https://github.com/KIMHYOJE/sw.git](https://github.com/KIMHYOJE/sw.git)
cd sw

# 의존성 패키지 설치
pip install -r requirements.txt

```

### 2. 환경 변수 설정 (`.env`)

루트 디렉토리에 `.env` 파일을 생성하고, 알림을 받을 디스코드 웹훅 주소와 Firebase 인증 정보를 입력합니다.

```env
DISCORD_WEBHOOK_URL="당신의_디스코드_웹훅_URL_입력"
FIREBASE_CREDENTIALS="파이어베이스_서비스계정_JSON_경로_또는_내용"

```

### 3. 스크립트 실행 테스트

원하는 크롤러 스크립트를 직접 실행하여 정상적으로 파싱되고 알림이 오는지 확인합니다.

```bash
python check_ict.py

```

---

## 🔒 보안 및 취약점 대응 (Security)

API 키, 웹훅 URL, Firebase 인증 키 등의 민감한 정보는 절대 코드에 하드코딩되지 않으며, **GitHub Secrets**를 통해 안전하게 관리됩니다.
보안 관련 정책 및 취약점 제보 방법은 [SECURITY.md](SECURITY.md)를 참고해 주세요.

---

## 👨‍💻 Author

* **김효제 (KIMHYOJE)**
* GitHub: [@KIMHYOJE](https://github.com/KIMHYOJE)
