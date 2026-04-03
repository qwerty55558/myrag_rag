from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from app.dependencies import get_llm, get_vector_store

PROMPT_TEMPLATE = """\
다음 컨텍스트를 기반으로 질문에 답변하세요.
컨텍스트에 답이 없으면 "제공된 문서에서 답을 찾을 수 없습니다."라고 답하세요.

컨텍스트:
{context}

질문: {question}
"""


def _format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


async def query(question: str, k: int = 4) -> tuple[str, list[str]]:
    """질문에 대해 RAG 응답과 소스 목록 반환."""
    store = get_vector_store()
    retriever = store.as_retriever(search_kwargs={"k": k})

    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    llm = get_llm()

    chain = (
        {"context": retriever | _format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    # 소스 추출을 위해 별도 검색
    docs = await store.asimilarity_search(question, k=k)
    sources = list({doc.metadata.get("source", "unknown") for doc in docs})

    answer = await chain.ainvoke(question)

    return answer, sources
