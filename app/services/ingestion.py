from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import UploadFile

from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredMarkdownLoader,
)
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.dependencies import get_vector_store

LOADER_MAP = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": UnstructuredMarkdownLoader,
}


def _get_loader(file_path: str, suffix: str):
    loader_cls = LOADER_MAP.get(suffix)
    if loader_cls is None:
        raise ValueError(f"지원하지 않는 파일 형식: {suffix}")
    return loader_cls(file_path)


async def ingest_file(file: UploadFile) -> int:
    """파일을 받아 청킹 후 벡터 저장. 저장된 문서 수 반환."""
    suffix = Path(file.filename or "").suffix.lower()

    with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp.flush()

        loader = _get_loader(tmp.name, suffix)
        documents: list[Document] = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_documents(documents)

    for chunk in chunks:
        chunk.metadata["source"] = file.filename

    store = get_vector_store()
    await store.aadd_documents(chunks)

    return len(chunks)
