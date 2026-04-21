from pydantic import BaseModel


class IngestResponse(BaseModel):
    document_count: int
    message: str


class GdriveIngestRequest(BaseModel):
    access_token: str


class GdriveIngestResponse(BaseModel):
    chunk_count: int
    files: list[str]
    message: str


class QueryRequest(BaseModel):
    question: str
    k: int = 4


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
