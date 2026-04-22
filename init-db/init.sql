-- pgvector 확장 활성화
CREATE EXTENSION IF NOT EXISTS vector;

-- ── RAG 스키마 + 전용 유저 ──
CREATE SCHEMA IF NOT EXISTS rag;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_user') THEN
        CREATE ROLE rag_user WITH LOGIN PASSWORD 'changeme';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA rag TO rag_user;
GRANT CREATE ON SCHEMA rag TO rag_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag GRANT ALL ON TABLES TO rag_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag GRANT ALL ON SEQUENCES TO rag_user;

-- ── Spring Boot 유저 (public 스키마) ──
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_spring') THEN
        CREATE ROLE app_spring WITH LOGIN PASSWORD 'spring_pw';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO app_spring;
GRANT CREATE ON SCHEMA public TO app_spring;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_spring;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_spring;
