from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.dependencies import init_resources
from app.routers import ingest, query


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_resources()
    yield


app = FastAPI(
    title="RAG API",
    description="LangChain + Gemini RAG 서비스",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(ingest.router)
app.include_router(query.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
