from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    google_api_key: str
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/myrag"
    )

    # Vector store
    db_schema: str = "rag"
    collection_name: str = "documents"
    vector_size: int = 3072  # gemini-embedding-2-preview

    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Models
    embedding_model: str = "models/gemini-embedding-2-preview"
    llm_model: str = "gemini-3.1-flash-lite-preview"
    llm_fallback_models: list[str] = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
    ]
    llm_temperature: float = 0.0

    # Retrieval
    retrieval_k: int = 8
    compression_similarity_threshold: float = 0.3
    source_similarity_threshold: float = 0.3

    # gRPC
    grpc_port: int = 50051


settings = Settings()
