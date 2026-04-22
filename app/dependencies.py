from collections import Counter

from langchain_core.documents import Document
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


async def weighted_retrieval(
    store: PGVectorStore,
    question: str,
) -> list[Document]:
    """1차 프로브로 소스 관련도를 측정한 뒤, 가중치 기반으로 소스별 청크를 수집한다."""
    probe_k = settings.retrieval_probe_k
    total_budget = settings.retrieval_total_budget
    min_per_source = settings.retrieval_min_per_source

    # 1차: 전체 대상 프로브 검색
    probe_docs = await store.asimilarity_search(question, k=probe_k)

    if not probe_docs:
        return []

    # 소스별 출현 횟수로 가중치 계산
    source_counts = Counter(
        doc.metadata.get("source", "unknown") for doc in probe_docs
    )
    all_sources = list(source_counts.keys())

    if len(all_sources) <= 1:
        # 소스가 1개면 그냥 전체 budget으로 검색
        return await store.asimilarity_search(question, k=total_budget)

    # 가중치 기반 k 할당: 최소 보장 + 나머지 비례 배분
    total_hits = sum(source_counts.values())
    reserved = min_per_source * len(all_sources)
    remaining = max(0, total_budget - reserved)

    k_per_source: dict[str, int] = {}
    for src in all_sources:
        weight = source_counts[src] / total_hits
        k_per_source[src] = min_per_source + round(remaining * weight)

    # 2차: 소스별 필터 검색
    all_docs: list[Document] = []
    seen_ids: set[str] = set()

    for src, k in k_per_source.items():
        src_docs = await store.asimilarity_search(
            question, k=k, filter={"source": src},
        )
        for doc in src_docs:
            doc_id = f"{doc.metadata.get('source')}:{doc.page_content[:80]}"
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                all_docs.append(doc)

    return all_docs


