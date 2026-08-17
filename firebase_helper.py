import json
import os
import firebase_admin
from firebase_admin import credentials, firestore

def get_db():
    if not firebase_admin._apps:
        key_json = os.environ.get("FIREBASE_KEY")
        
        # GitHub Secrets에 키가 등록되지 않았을 경우 명확한 에러 발생
        if not key_json:
            raise ValueError("[Error] FIREBASE_KEY 환경변수가 설정되지 않았습니다. GitHub Secrets를 확인해 주세요.")
            
        # JSON 문자열을 파싱하여 인증 정보로 사용
        cred_dict = json.loads(key_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        
    return firestore.client()