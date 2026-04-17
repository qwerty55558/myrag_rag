from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import EmbeddingsFilter
from langchain_core.retrievers import RetrieverLike
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_postgres import PGEngine, PGVectorStore
from langchain_postgres.v2.indexes import HNSWIndex

from app.config import settings

# -- Singletons (initialized in lifespan) --

engine: PGEngine | None = None
vector_store: PGVectorStore | None = None


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.google_api_key,
    )


def get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.google_api_key,
        temperature=settings.llm_temperature,
    )


async def init_resources() -> None:
    """Called once at startup via FastAPI lifespan."""
    global engine, vector_store

    engine = PGEngine.from_connection_string(settings.database_url)

    await engine.ainit_vectorstore_table(
        table_name=settings.collection_name,
        vector_size=settings.vector_size,
        overwrite_existing=False,
    )

    vector_store = await PGVectorStore.create(
        engine=engine,
        embedding_service=get_embeddings(),
        table_name=settings.collection_name,
    )

    index = HNSWIndex(m=16, ef_construction=64)
    try:
        await vector_store.aapply_vector_index(index)
    except Exception:
        pass  # index already exists


def get_vector_store() -> PGVectorStore:
    assert vector_store is not None, "Vector store not initialized"
    return vector_store


def get_compression_retriever(base_retriever: RetrieverLike) -> ContextualCompressionRetriever:
    compressor = EmbeddingsFilter(
        embeddings=get_embeddings(),
        similarity_threshold=settings.compression_similarity_threshold,
    )
    return ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,
    )
