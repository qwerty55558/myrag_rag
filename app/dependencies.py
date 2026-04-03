from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_postgres import PGEngine, PGVectorStore

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


def get_vector_store() -> PGVectorStore:
    assert vector_store is not None, "Vector store not initialized"
    return vector_store
