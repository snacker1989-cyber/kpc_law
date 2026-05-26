# 사내규정 이력관리 시스템

법제처 국가법령정보센터의 열람 흐름을 참고해 만든 사내규정용 경량 MVP입니다.

## 주요 기능

- 규정 검색
- 규정 목록
- 규정 상세 4개 탭: 본문, 제정/개정이유, 별표/서식, 연혁
- 관리자 규정 등록
- 관리자 개정 버전 추가
- 버전별 별표/서식 업로드
- SQLite 기반 샘플 데이터 자동 생성

## 실행

```powershell
pip install -r requirements.txt
uvicorn main:app --reload
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다.

## 설계 문서

- `docs/system-design.md`
- `docs/implementation-roadmap.md`
