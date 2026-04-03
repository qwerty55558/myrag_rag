from fastapi import FastAPI

app = FastAPI(
    title="RAG API",
    description="LangChain + Gemini RAG 서비스",
    version="0.1.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}
