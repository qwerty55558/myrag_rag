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