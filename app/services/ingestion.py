from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import UploadFile

import fitz

from langchain_community.document_loaders import (
    CSVLoader,
    PyPDFLoader,
    TextLoader,
    UnstructuredExcelLoader,
    UnstructuredHTMLLoader,
    UnstructuredMarkdownLoader,
    UnstructuredPowerPointLoader,
    UnstructuredWordDocumentLoader,
)
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.dependencies import get_user_vector_store


class PyMuPDFLoader:
    """PyMuPDF 기반 PDF 로더. 텍스트 추출 실패 시 Tesseract OCR fallback."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def load(self) -> list[Document]:
        docs = []
        with fitz.open(self.file_path) as pdf:
            for i, page in enumerate(pdf):
                text = page.get_text()
                if not text.strip():
                    # 텍스트 없으면 OCR
                    tp = page.get_textpage_ocr(flags=0, language="kor+eng", full=True)
                    text = page.get_text("text", textpage=tp)
                if text.strip():
                    docs.append(Document(
                        page_content=text,
                        metadata={"page": i, "total_pages": len(pdf)},
                    ))
        return docs


LOADER_MAP = {
    # 문서
    ".pdf": PyMuPDFLoader,
    ".doc": UnstructuredWordDocumentLoader,
    ".docx": UnstructuredWordDocumentLoader,
    # 스프레드시트
    ".xlsx": UnstructuredExcelLoader,
    ".xls": UnstructuredExcelLoader,
    ".csv": CSVLoader,
    # 프레젠테이션
    ".pptx": UnstructuredPowerPointLoader,
    ".ppt": UnstructuredPowerPointLoader,
    # 텍스트
    ".txt": TextLoader,
    ".md": UnstructuredMarkdownLoader,
    ".html": UnstructuredHTMLLoader,
    ".htm": UnstructuredHTMLLoader,
}


def _get_loader(file_path: str, suffix: str):
    loader_cls = LOADER_MAP.get(suffix)
    if loader_cls is None:
        raise ValueError(f"지원하지 않는 파일 형식: {suffix}")
    return loader_cls(file_path)


async def ingest_file(file: "UploadFile", user_id: str) -> int:
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

    store = await get_user_vector_store(user_id)
    await store.aadd_documents(chunks)

    return len(chunks)
