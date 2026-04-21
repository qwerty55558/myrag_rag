from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import EmbeddingsFilter
from langchain_core.retrievers import RetrieverLike
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from langchain_postgres.v2.indexes import HNSWIndex

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


def get_compression_retriever(base_retriever: RetrieverLike) -> ContextualCompressionRetriever:
    compressor = EmbeddingsFilter(
        embeddings=get_embeddings(),
        similarity_threshold=settings.compression_similarity_threshold,
    )
    return ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,
    )
