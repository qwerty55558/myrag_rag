from pydantic import BaseModel


class IngestResponse(BaseModel):
    document_count: int
    message: str


class QueryRequest(BaseModel):
    question: str
    k: int = 4


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
