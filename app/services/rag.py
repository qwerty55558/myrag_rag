from collections.abc import AsyncGenerator

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from app.dependencies import get_compression_retriever, get_llm, get_vector_store

PROMPT_TEMPLATE = """\
당신은 제공된 문서만을 기반으로 답변하는 AI 어시스턴트입니다.
반드시 아래 컨텍스트에 포함된 정보만 사용하세요.
컨텍스트에 답이 없으면 "제공된 문서에서 답을 찾을 수 없습니다."라고 답하세요.
절대로 외부 지식이나 추측을 사용하지 마세요.
현재 시각: {current_timestamp}

컨텍스트:
{context}

질문: {question}
"""


def _format_docs(docs: list[Document]) -> str:
    return "\n\n".join(doc.page_content for doc in docs)


async def query(question: str, k: int = 4) -> tuple[str, list[str]]:
    """질문에 대해 RAG 응답과 소스 목록 반환."""
    store = get_vector_store()
    base_retriever = store.as_retriever(search_kwargs={"k": k})
    retriever = get_compression_retriever(base_retriever)

    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    llm = get_llm()

    chain = (
        {"context": retriever | _format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    docs = await retriever.ainvoke(question)
    sources = list({doc.metadata.get("source", "unknown") for doc in docs})

    answer = await chain.ainvoke(question)

    return answer, sources


async def stream_query(
    question: str,
    k: int = 4,
    current_timestamp: str = "",
) -> AsyncGenerator[tuple[str, bool, list[Document]], None]:
    """토큰 단위로 RAG 응답을 스트리밍한다.

    Yields:
        (token, is_final, docs) — 마지막 청크에서 is_final=True, docs에 소스 문서 포함.
    """
    store = get_vector_store()
    base_retriever = store.as_retriever(search_kwargs={"k": k})
    retriever = get_compression_retriever(base_retriever)

    docs = await retriever.ainvoke(question)
    context = _format_docs(docs)

    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    llm = get_llm()

    chain = prompt | llm | StrOutputParser()

    async for token in chain.astream({
        "context": context,
        "question": question,
        "current_timestamp": current_timestamp,
    }):
        yield token, False, []

    yield "", True, docs
