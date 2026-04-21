from fastapi import APIRouter

from app.schemas import QueryRequest, QueryResponse
from app.services.rag import query

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def ask(request: QueryRequest):
    """질문을 받아 RAG 기반으로 답변합니다."""
    answer, sources = await query(request.question, k=request.k)
    return QueryResponse(answer=answer, sources=sources)
