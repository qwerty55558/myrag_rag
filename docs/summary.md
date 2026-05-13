# MyRAG - RAG AI Service

> MSA 기반 문서 검색 증강 생성(RAG) AI 서비스
> Google Drive 문서를 자동 인덱싱하고, 문서 기반 AI 챗봇을 제공한다.

---

## Overview

| 항목 | 내용 |
|------|------|
| 언어/프레임워크 | Python 3.13 / FastAPI + gRPC (비동기) |
| AI 스택 | LangChain + Google Gemini (LLM & Embedding) |
| 벡터 DB | PostgreSQL + pgvector (HNSW 인덱스) |
| 패키지 매니저 | uv |
| 통신 프로토콜 | gRPC Server Streaming (Spring Boot 백엔드 연동) |
| 컨테이너 | Docker → ghcr.io 배포 |

---

## Architecture

```
Spring Boot BE (STOMP WebSocket)
        │
        │  gRPC Server Streaming
        ▼
Python RAG Service (이 프로젝트)
        │
        ├── PostgreSQL + pgvector (스키마: rag)
        ├── Google Gemini (LLM + Embedding)
        └── Google Drive API (문서 수집)
```

- **Spring Boot 백엔드** — 프론트엔드(STOMP WebSocket)와 통신하며, RAG 서비스에 gRPC로 요청 전달
- **Python RAG 서비스** — gRPC 서버로 동작. 문서 인덱싱 + 질의응답 담당
- **gRPC 계약 (proto)** — 별도 레포지토리 [`myrag_proto`](https://github.com/qwerty55558/myrag_proto.git)에서 관리 → pip 패키지로 배포/소비

---

## Directory Structure

```
rag/
├── app/
│   ├── config.py              # Pydantic Settings (환경변수 기반 설정)
│   ├── dependencies.py        # 싱글톤 관리 (DB 엔진, 벡터스토어, 임베딩, LLM)
│   ├── grpc_server.py         # gRPC 서버 진입점 (포트 50051)
│   ├── grpc_handlers.py       # gRPC 서비스 핸들러 구현
│   ├── main.py                # FastAPI 앱 (레거시 HTTP API)
│   ├── schemas.py             # Pydantic 모델 (HTTP 요청/응답)
│   ├── routers/
│   │   ├── ingest.py          # 문서 업로드 / Google Drive 임베딩
│   │   └── query.py           # RAG 질의 엔드포인트
│   └── services/
│       ├── rag.py             # RAG 검색 + 스트리밍 응답 파이프라인
│       ├── ingestion.py       # 문서 파싱 + 청킹 + 벡터 저장
│       └── gdrive.py          # Google Drive 파일 수집/인덱싱
├── init-db/
│   └── init.sql               # PostgreSQL 초기화 (rag 스키마 + 유저 권한)
├── .github/workflows/
│   └── docker-publish.yml     # CI/CD: Docker 빌드 → ghcr.io 푸시
├── Dockerfile                 # python:3.13-slim + Tesseract OCR
└── pyproject.toml             # 프로젝트 의존성 정의
```

---

## Core Features

### 1. 문서 인덱싱 (`IndexDocuments`)

Google Drive 폴더의 문서를 자동 수집하여 벡터 DB에 저장한다.

**주요 메커니즘:**

- **유저별 벡터 테이블 격리** — `rag.documents_{user_id}` 형태로 유저마다 독립 테이블 생성
- **변경 감지** — md5 체크섬 기반, 변경된 파일만 재인덱싱 (기존 청크 삭제 후 새로 저장)
- **병렬 다운로드** — `asyncio.gather`로 병렬 처리, 3회 재시도
- **실패 리포트** — 개별 파일 실패 시 전체 중단 없이 `FailedFile` 목록으로 반환
- **Google Workspace 자동 변환** — Docs → `.docx` / Sheets → `.xlsx` / Slides → `.pptx`
- **HNSW 인덱스** — 유저별 테이블 생성 시 자동 적용 (m=16, ef_construction=64)

**지원 문서 형식 (12종):**

| 확장자 | 로더 | 비고 |
|--------|------|------|
| `.pdf` | PyMuPDFLoader (커스텀) | 텍스트 없는 페이지 → Tesseract OCR 폴백 |
| `.doc` | UnstructuredWordDocumentLoader | 레거시 Word |
| `.docx` | UnstructuredWordDocumentLoader | 최신 Word |
| `.xlsx` | UnstructuredExcelLoader | 최신 Excel |
| `.xls` | UnstructuredExcelLoader | 레거시 Excel |
| `.csv` | CSVLoader | |
| `.pptx` | UnstructuredPowerPointLoader | 최신 PowerPoint |
| `.ppt` | UnstructuredPowerPointLoader | 레거시 PowerPoint |
| `.txt` | TextLoader | |
| `.md` | UnstructuredMarkdownLoader | |
| `.html` | UnstructuredHTMLLoader | |
| `.htm` | UnstructuredHTMLLoader | |

---

### 2. RAG 채팅 (`Chat` — Server Streaming)

문서 기반 질의응답을 토큰 단위 스트리밍으로 제공한다.

**검색 파이프라인:**

| 단계 | 처리 | 설명 |
|------|------|------|
| 1 | 가중치 기반 소스 검색 | 1차 프로브(k=4)로 소스별 관련도 측정 → 관련도 비례로 총 예산(20개) 할당 → 소스별 필터 검색 |
| 2 | EmbeddingsFilter | 코사인 유사도 임계값(0.3) 이하 문서 필터링 |
| 3 | 프롬프트 구성 | 검색된 문서 + 이전 대화 요약(context_summary) + 현재 질문으로 조립 |
| 4 | 토큰 스트리밍 | LangChain `astream()`으로 토큰 단위 응답 전송 |
| 5 | 최종 응답 | 소스 문서 목록 + 갱신된 context_summary 전송 |

**LLM Fallback 체인:**

429(Rate Limit) 또는 503(서버 과부하) 시 자동으로 다음 모델로 전환. 모든 모델 실패 시 사용자에게 안내 메시지 반환.

| 순서 | 모델 |
|------|------|
| Primary | `gemini-3.1-flash-lite` |
| Fallback 1 | `gemini-3-flash-preview` |
| Fallback 2 | `gemini-2.5-flash` |
| Fallback 3 | `gemini-2.0-flash-lite` |
| Fallback 4 | `gemini-2.0-flash` |

**Context Summary (대화 맥락 요약):**

- 매 응답 완료 후 LLM으로 대화 내용을 3~5문장으로 압축
- 다음 요청 시 `context_summary` 필드로 전달받아 프롬프트에 삽입
- 긴 대화에서도 맥락 유지 + 토큰 사용량 절약

**보안:**

- 프롬프트 인젝션 방어 — 역할 변경, 시스템 프롬프트 무시 등의 조작 시도를 감지하고 거부

---

### 3. 문서 관리

- **ListIndexedDocuments** — 유저의 인덱싱된 문서 목록 조회 (gdrive_id 기준 그룹화, 청크 수/인덱싱 시각 포함)
- **DeleteDocuments** — gdrive_id 기준으로 해당 문서의 모든 청크 삭제
- **GetSupportedFormats** — 지원되는 파일 확장자 목록 반환

---

## gRPC Service Interface

> 서비스명: `myrag.v1.RagService` / 포트: `50051`

| 메서드 | 타입 | 설명 |
|--------|------|------|
| `Chat` | Server Streaming | 토큰 단위 RAG 응답 스트리밍 |
| `IndexDocuments` | Unary | Google Drive 문서 인덱싱 |
| `ListIndexedDocuments` | Unary | 인덱싱된 문서 목록 조회 |
| `DeleteDocuments` | Unary | 인덱싱된 문서 삭제 |
| `GetSupportedFormats` | Unary | 지원 파일 형식 목록 |

**추가 등록 서비스:**

- `grpc.health.v1.Health` — 표준 gRPC 헬스 체크
- gRPC Server Reflection — 개발/디버깅용

---

## Configuration

| 설정 | 값 | 설명 |
|------|-----|------|
| `embedding_model` | `gemini-embedding-2-preview` | 임베딩 모델 |
| `vector_size` | `3072` | 임베딩 벡터 차원 |
| `llm_model` | `gemini-3.1-flash-lite` | 기본 LLM 모델 |
| `llm_temperature` | `0.0` | LLM 응답 온도 |
| `chunk_size` | `1000` | 문서 청크 크기 |
| `chunk_overlap` | `200` | 청크 간 오버랩 |
| `probe_k` | `4` | 1차 프로브 검색 수 |
| `total_budget` | `20` | 총 검색 예산 |
| `min_per_source` | `3` | 소스당 최소 검색 수 |
| `compression_similarity` | `0.3` | 유사도 필터 임계값 |
| `grpc_port` | `50051` | gRPC 서버 포트 |
| `db_schema` | `rag` | PostgreSQL 스키마 |
| HNSW `m` | `16` | 인덱스 연결 수 |
| HNSW `ef_construction` | `64` | 인덱스 구축 정밀도 |

---

## Infrastructure / CI·CD

### Docker

| 항목 | 내용 |
|------|------|
| 베이스 이미지 | `python:3.13-slim` |
| 시스템 의존성 | `tesseract-ocr` + `tesseract-ocr-kor` (PDF OCR) |
| 패키지 매니저 | `uv` (astral-sh/uv 공식 이미지에서 복사) |
| 실행 커맨드 | `uv run python -m app.grpc_server` |
| 노출 포트 | `50051` (gRPC) |

### GitHub Actions (`docker-publish.yml`)

| 항목 | 내용 |
|------|------|
| 트리거 | `main` 또는 `develop` 브랜치 푸시 |
| 빌드 플랫폼 | `linux/amd64` |
| 레지스트리 | `ghcr.io/qwerty55558/myrag_rag` |
| 태그 전략 | 브랜치명, 커밋 SHA, `latest` (main/develop) |
| 캐시 | GitHub Actions 캐시로 Docker 레이어 재사용 |
| 시크릿 | `PROTO_ACCESS` — private proto repo 접근용 |

### Database

| 항목 | 내용 |
|------|------|
| 엔진 | PostgreSQL + `pgvector` 확장 |
| 스키마 | `rag` (서비스 간 DB 접근 분리) |
| 유저별 테이블 | `rag.documents_{user_id}` |
| 벡터 인덱스 | HNSW (m=16, ef_construction=64) |
| 초기화 | `init-db/init.sql` |

---

## Dependencies

| 카테고리 | 주요 패키지 |
|----------|-------------|
| 웹 프레임워크 | `fastapi`, `uvicorn` |
| gRPC | `grpcio`, `grpcio-tools`, `grpcio-health-checking` |
| AI/LLM | `langchain`, `langchain-google-genai` |
| 벡터 DB | `langchain-postgres` (PGVectorStore) |
| 문서 파싱 | `pymupdf`, `python-docx`, `openpyxl`, `python-pptx` |
| OCR | `pytesseract`, `pdf2image` |
| Google API | `google-api-python-client`, `google-auth` |
| Proto | `myrag-proto` (private git 패키지) |
| 설정 | `pydantic-settings` |

---

## Legacy HTTP API (FastAPI)

> gRPC 전환 이전 HTTP 엔드포인트. 현재는 gRPC 인터페이스가 주요 통신 수단.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/ingest` | 파일 업로드 → 벡터 저장 |
| `POST` | `/ingest/gdrive` | Google Drive 일괄 임베딩 |
| `POST` | `/query` | RAG 질의 (비스트리밍) |
| `GET` | `/health` | 헬스 체크 |

---

## Development History

### Phase 1: 초기 구축

| 커밋 | 내용 |
|------|------|
| `9ee828d` | **init commit** — 프로젝트 초기 커밋 |
| `f02cbe9` | **RAG 서비스 앱 구조 구축** — FastAPI + LangChain + Gemini + PGVector 기반 스캐폴딩. 설정, 의존성, 라우터, 서비스 레이어 분리 |
| `c6a56e4` | **RAG 검색 품질 개선 + Google Drive 엔드포인트** — HNSW 인덱스, ContextualCompressionRetriever, EmbeddingsFilter 도입. Google Drive OAuth 기반 파일 수집 |

### Phase 2: gRPC 전환 + 멀티테넌시

| 커밋 | 내용 |
|------|------|
| `e2702e7` | **gRPC 서버 구현** — Spring Boot와의 gRPC Server Streaming 통신. Chat + IndexDocuments 핸들러. 토큰 단위 스트리밍(`astream`). DB 스키마 분리(`rag`) |
| `8574d10` | **proto 패키지 전환** — 로컬 proto stub 제거, `myrag-proto` pip 패키지로 전환 |
| `373c7c0` | **유저별 벡터 테이블 격리** — 싱글톤 벡터스토어 → `get_user_vector_store(user_id)`. ListIndexedDocuments, DeleteDocuments, GetSupportedFormats 구현. md5 기반 중복 체크, 병렬 다운로드, 실패 리포트 |

### Phase 3: LLM 강화 + 문서 확장

| 커밋 | 내용 |
|------|------|
| `a02b24a` | **LLM Fallback 체인 + 프롬프트 인젝션 방어** — 5단계 모델 폴백, 프롬프트 조작 감지/거부, 임베딩 모델 업그레이드 (768→3072 차원) |
| `2895b95` | **문서 파싱 확장 (12종)** — PDF OCR 폴백(Tesseract), Word/Excel/PowerPoint 지원. Google Workspace 파일 자동 변환 |

### Phase 4: 컨테이너화 + CI/CD

| 커밋 | 내용 |
|------|------|
| `c74a429` | **Dockerfile 작성** — python:3.13-slim + Tesseract OCR + uv |
| `8231a21` | **GitHub Actions CI/CD** — Docker 빌드 → ghcr.io 푸시 자동화 |
| `c7eb570` ~ `802d9c5` | **CI 수정** — Dockerfile git 설치, private proto repo 인증 처리 |

### Phase 5: 프롬프트 개선 + 소스 필터링

| 커밋 | 내용 |
|------|------|
| `17e9af3` | **RAG 프롬프트 개선** — 검색된 컨텍스트를 무시하던 문제 수정 |
| `4d67095` | **develop 브랜치 latest 태그** — CI에서 develop도 latest 태그 생성 |
| `80768c8` | **context_summary + 소스별 필터링** — gRPC ChatRequest에서 context_summary 수신/반환. 소스 파일명 임베딩 기반 필터링 |
| `c88eea5` | **가중치 기반 소스 검색** — 파일명 임베딩 필터링을 가중치 기반 프로브 검색으로 교체 |

### Phase 6: 안정화

| 커밋 | 내용 |
|------|------|
| `d6f241d` | **빈 검색 결과 처리** — EmbeddingsFilter IndexError 수정, LLM fallback 체인을 summary 생성에도 적용 |
| `b3d437e` | **테이블 미존재 시 크래시 수정** — 인덱싱 전 문서 조회/삭제 시 UndefinedTableError 방지 |
