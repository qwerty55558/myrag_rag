## Python 코드 컨벤션

### 네이밍
- 파일/모듈: snake_case
- 클래스: PascalCase
- 함수/변수: snake_case
- 상수: UPPER_SNAKE_CASE

### 구조
- 라우터: `app/routers/` — 엔드포인트 정의만, 비즈니스 로직 금지
- 서비스: `app/services/` — 비즈니스 로직
- 설정: `app/config.py` — Pydantic Settings, 환경변수 기반
- 의존성: `app/dependencies.py` — 싱글톤 및 DI 헬퍼

### 비동기
- 모든 I/O 작업은 async/await 사용
- DB, 외부 API 호출은 반드시 비동기

### Import 순서
1. 표준 라이브러리
2. 서드파티 (langchain, fastapi 등)
3. 로컬 (app.*)

### gRPC
- proto 생성 코드는 직접 수정하지 않음
- proto 변경은 myrag_proto repo에서 수행
