import math

from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import EmbeddingsFilter
from langchain_core.retrievers import RetrieverLike
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from langchain_postgres.v2.indexes import HNSWIndex
from sqlalchemy import text

from app.config import settings

# -- Singletons (initialized in lifespan) --

engine: PGEngine | None = None
_user_stores: dict[str, PGVectorStore] = {}


def _user_table_name(user_id: str) -> str:
    return f"documents_{user_id}"


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.google_api_key,
    )


def get_llm(model: str | None = None) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model or settings.llm_model,
        google_api_key=settings.google_api_key,
        temperature=settings.llm_temperature,
    )


async def init_resources() -> None:
    """Called once at startup — DB 엔진 초기화."""
    global engine
    engine = PGEngine.from_connection_string(settings.database_url)


async def get_user_vector_store(user_id: str) -> PGVectorStore:
    """유저별 벡터 테이블을 생성/반환한다."""
    if user_id in _user_stores:
        return _user_stores[user_id]

    assert engine is not None, "Engine not initialized"

    table_name = _user_table_name(user_id)

    try:
        await engine.ainit_vectorstore_table(
            table_name=table_name,
            vector_size=settings.vector_size,
            schema_name=settings.db_schema,
            overwrite_existing=False,
        )
    except Exception:
        pass  # table already exists

    store = await PGVectorStore.create(
        engine=engine,
        embedding_service=get_embeddings(),
        table_name=table_name,
        schema_name=settings.db_schema,
    )

    index = HNSWIndex(m=16, ef_construction=64)
    try:
        await store.aapply_vector_index(index)
    except Exception:
        pass  # index already exists

    _user_stores[user_id] = store
    return store


async def get_user_sources(user_id: str) -> list[str]:
    """유저의 벡터 스토어에 저장된 고유 소스(파일명) 목록을 반환한다."""
    assert engine is not None
    table = _user_table_name(user_id)
    schema = settings.db_schema
    query = text(
        f'SELECT DISTINCT cmetadata->>\'source\' FROM "{schema}"."{table}"'
    )
    async with engine._pool.connect() as conn:
        result = await conn.execute(query)
        return [row[0] for row in result if row[0]]


async def filter_sources_by_query(
    question: str,
    sources: list[str],
    threshold: float | None = None,
) -> list[str] | None:
    """질문과 소스 파일명 간 임베딩 유사도를 비교해 관련 소스만 반환한다.

    모든 소스가 임계값 이하이면 None을 반환하여 필터 없이 검색하도록 한다.
    """
    if not sources or len(sources) <= 1:
        return None

    threshold = threshold or settings.source_similarity_threshold
    embeddings = get_embeddings()
    query_emb = await embeddings.aembed_query(question)
    source_embs = await embeddings.aembed_documents(sources)

    scores = []
    for emb in source_embs:
        dot = sum(a * b for a, b in zip(query_emb, emb))
        norm_q = math.sqrt(sum(a * a for a in query_emb))
        norm_s = math.sqrt(sum(b * b for b in emb))
        cos_sim = dot / (norm_q * norm_s + 1e-10)
        scores.append(cos_sim)

    max_score = max(scores)
    if max_score < threshold:
        return None

    # 최고 점수 대비 90% 이상인 소스만 선택
    cutoff = max_score * 0.9
    relevant = [src for src, sc in zip(sources, scores) if sc >= cutoff]
    return relevant if len(relevant) < len(sources) else None


def get_compression_retriever(base_retriever: RetrieverLike) -> ContextualCompressionRetriever:
    compressor = EmbeddingsFilter(
        embeddings=get_embeddings(),
        similarity_threshold=settings.compression_similarity_threshold,
    )
    return ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,
    )
