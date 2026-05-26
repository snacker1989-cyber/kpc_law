# 사내규정 이력관리 시스템 설계

## 1. 목표

대한민국 법제처 국가법령정보센터의 열람 방식을 참고하되, 사내규정 관리에 필요한 기능만 남긴 경량 시스템을 구축한다.

필수 열람 영역은 다음 4개로 한정한다.

- 본문
- 제정/개정이유
- 별표/서식
- 연혁

법제처 시스템의 3단비교, 신구법비교, 법령체계도 등은 1차 범위에서 제외한다.

## 2. 사용자 유형

- 일반 사용자: 현행 규정 검색, 규정 본문 열람, 첨부 다운로드, 과거 버전 확인
- 규정 관리자: 규정 등록, 개정 버전 추가, 시행일 관리, 첨부 업로드, 폐지 처리
- 시스템 관리자: 사용자/권한 관리, 분류 관리, 감사 로그 확인

## 3. 핵심 화면

### 3.1 메인/검색

법제처 메인처럼 검색을 가장 강한 진입점으로 둔다. 다만 사내 시스템에서는 메뉴를 단순화한다.

- 통합 검색창
- 규정명 검색
- 본문 검색
- 분류별 탐색
- 최근 개정 규정
- 시행 예정 규정

### 3.2 규정 목록

- 규정명
- 분류
- 규정번호
- 현행 버전 시행일
- 상태: 현행, 시행예정, 폐지
- 담당부서
- 최근 개정일

필터:

- 분류
- 담당부서
- 상태
- 시행일 범위
- 키워드

### 3.3 규정 상세

법제처 개별 법령 페이지의 상단 탭 구조를 축소하여 사용한다.

- 본문
- 제정/개정이유
- 별표/서식
- 연혁

상단 고정 정보:

- 규정명
- 규정번호
- 소관부서
- 현행 시행일
- 공포/승인일
- 상태
- 이전/다음 버전 선택

### 3.4 관리자 화면

- 규정 기본정보 등록/수정
- 새 버전 등록
- 버전별 본문 편집
- 제정/개정이유 입력
- 별표/서식 첨부
- 시행 예정 버전 예약
- 폐지 처리
- 변경 이력 확인

## 4. 데이터 모델

### 4.1 Regulation

규정의 변하지 않는 식별 정보를 가진다.

- id
- title
- category_id
- department_id
- regulation_number
- status
- created_at
- updated_at

### 4.2 RegulationVersion

규정의 각 제정/개정 이력을 가진다. 본문과 개정이유는 버전 단위로 보관한다.

- id
- regulation_id
- version_label
- promulgation_date
- effective_date
- amendment_type: 제정, 일부개정, 전부개정, 폐지
- reason
- body
- is_current
- created_by
- created_at
- updated_at

### 4.3 Attachment

별표/서식 파일을 버전 단위로 연결한다.

- id
- regulation_version_id
- title
- file_name
- file_path
- file_type
- file_size
- sort_order
- uploaded_by
- uploaded_at

### 4.4 Category

- id
- name
- parent_id
- sort_order

### 4.5 Department

- id
- name
- sort_order

### 4.6 AuditLog

관리자 작업 추적용 로그다.

- id
- actor_id
- action
- target_type
- target_id
- summary
- created_at

## 5. 연혁 생성 규칙

연혁 화면은 별도 수기 입력이 아니라 `RegulationVersion` 목록에서 자동 생성한다.

정렬:

- 최신순 기본
- 필요 시 오래된순 전환

표시 항목:

- 시행일
- 공포/승인일
- 개정 유형
- 버전명
- 제정/개정이유 요약
- 해당 버전 보기

현행 버전 판정:

- 오늘 날짜 기준 `effective_date <= today`인 버전 중 가장 최신 시행일
- 시행 예정 버전은 별도 배지로 표시
- 폐지 버전이 현행이면 규정 상태를 폐지로 표시

## 6. 검색 설계

1차 구현은 데이터베이스 LIKE 검색으로 시작한다.

검색 대상:

- 규정명
- 규정번호
- 본문
- 제정/개정이유
- 첨부 제목

추후 확장:

- PostgreSQL full-text search
- Elasticsearch/OpenSearch
- 한글 형태소 분석 기반 검색

## 7. 권한 설계

- anonymous: 공개 열람만 허용할지 여부는 운영 정책으로 결정
- viewer: 열람
- editor: 규정/버전/첨부 등록 및 수정
- admin: 사용자, 분류, 부서, 감사 로그 관리

최소 권한 원칙:

- 버전 삭제는 기본 비활성화
- 잘못 등록된 버전은 숨김 또는 정정 버전으로 처리
- 시행된 버전의 본문 수정은 제한하고 새 개정 버전 등록을 권장

## 8. 1차 구현 범위

- 메인 검색
- 규정 목록
- 규정 상세 4개 탭
- 관리자 규정 등록
- 관리자 버전 등록
- 첨부 업로드/다운로드
- 연혁 자동 표시
- 간단 로그인

## 9. 제외 범위

- 3단비교
- 신구법비교
- 법령체계도
- 판례/해석례 연결
- 외부 법령 API 연동
- 전자결재 연동
- 문서 OCR

## 10. 추천 기술 스택

소규모 내부 서비스 기준:

- Backend: FastAPI
- Template/UI: Jinja2 + 정적 CSS/JS
- Database: SQLite로 시작, 운영 시 PostgreSQL 권장
- File storage: 로컬 파일 시스템으로 시작, 운영 시 NAS 또는 S3 호환 스토리지
- Auth: 세션 기반 로그인

확장성과 관리자 기능을 더 중시한다면:

- Backend: Django
- Admin: Django Admin 커스터마이징
- Database: PostgreSQL

## 11. 초기 URL 구조

- `GET /` 메인/검색
- `GET /regulations` 규정 목록
- `GET /regulations/{id}` 규정 상세
- `GET /regulations/{id}/versions/{version_id}` 특정 버전 상세
- `GET /attachments/{id}/download` 첨부 다운로드
- `GET /admin/regulations` 관리자 규정 목록
- `GET /admin/regulations/new` 규정 등록
- `GET /admin/regulations/{id}/versions/new` 버전 등록

## 12. 다음 단계

1. 기술 스택 확정
2. 기존 파일 정리 여부 결정
3. 데이터베이스 스키마 작성
4. 화면 와이어프레임 작성
5. 1차 기능 구현
