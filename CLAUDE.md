# RAG Service
MSA 기반 RAG AI 서비스 LangChain + Gemini 기반(Python FastAPI)

## Rules

프로젝트 규칙은 `.claude/rules/` 내부의 마크다운 문서를 참조할 것.

- 코드 컨벤션: `.claude/rules/convention.md`

## Architecture

MSA 구조의 RAG 서비스. Spring Boot 백엔드와 gRPC로 통신.

- **gRPC 계약**: `myrag_proto` 별도 repo에서 관리 → 라이브러리로 배포 → pip dependency로 소비
  - repo: https://github.com/qwerty55558/myrag_proto.git
  - proto 변경 시 proto repo에서 빌드/배포 후, 이 프로젝트에서 라이브러리 버전을 업데이트할 것
- **통신**: Spring Boot → Python RAG (gRPC Server Streaming)
- **DB**: PostgreSQL + pgvector (HNSW), 스키마 `rag`


## 개요
- **프론트엔드 → Spring Boot**: STOMP WebSocket (인증된 세션만)
- **Spring Boot → Python RAG**: gRPC Server Streaming
  - **Spring Boot 역할**: 인증/세션/유저 관리 (Spring Security + JPA), Thymeleaf UI, gRPC relay
- **Python RAG 내부**: LangChain + GoogleGenerativeAIEmbeddings (`text-embedding-004`, 768차원) + pgvector (HNSW) + Gemini 2.0 Flash
- **문서 인덱싱**: GoogleDriveLoader로 동적 추가, 쿼리 경로와 분리된 background job
- **Proto 계약**: `proto-contracts` 별도 repo → CI로 Java JAR + Python wheel 빌드 → GitHub Packages 배포 → 각 서비스가 라이브러리로 소비
- **DB**: Spring용 PostgreSQL (유저/세션) + Python용 PostgreSQL + pgvector (문서 벡터) — 인스턴스 공유, 스키마 분리
- **인프라**: 각 서비스 독립 repo, ghcr.io에 Docker 이미지 관리, proto 버전 변경 시 Repository Dispatch로 downstream CD 자동 트리거