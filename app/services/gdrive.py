import asyncio
import io
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.dependencies import get_user_vector_store
from app.services.ingestion import LOADER_MAP

logger = logging.getLogger(__name__)

MIME_EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}


def _build_drive_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds)


async def _list_files_recursive(service, folder_id: str) -> list[dict]:
    """폴더 내 모든 파일을 재귀적으로 탐색한다. md5Checksum 포함."""
    all_files = []
    page_token = None

    while True:
        query = f"'{folder_id}' in parents and trashed = false"
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, md5Checksum, size, modifiedTime)",
            pageSize=100,
            pageToken=page_token,
        ).execute()

        for item in resp.get("files", []):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                sub_files = await _list_files_recursive(service, item["id"])
                all_files.extend(sub_files)
            else:
                all_files.append(item)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return all_files


def _download_and_parse(access_token: str, file_info: dict) -> tuple[list[Document], str] | None:
    """파일 다운로드 + 파싱 (동기). 스레드별로 service 생성."""
    # 스레드별 service 생성 (thread-safe)
    service = _build_drive_service(access_token)

    mime_type = file_info["mimeType"]
    file_id = file_info["id"]
    name = file_info["name"]

    if mime_type in MIME_EXPORT_MAP:
        export_mime, suffix = MIME_EXPORT_MAP[mime_type]
        request = service.files().export_media(
            fileId=file_id, mimeType=export_mime
        )
    else:
        suffix = Path(name).suffix.lower()
        if suffix not in LOADER_MAP:
            logger.info("Skipping unsupported file: %s (mime: %s, ext: %s)", name, mime_type, suffix)
            return None
        request = service.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    data = buffer.getvalue()

    with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()

        loader_cls = LOADER_MAP[suffix]
        loader = loader_cls(tmp.name)
        documents: list[Document] = loader.load()

    return documents, name


async def _get_indexed_checksums(user_id: str) -> dict[str, str]:
    """이미 인덱싱된 문서들의 gdrive_id → md5 매핑 반환."""
    import app.dependencies as deps

    if deps.engine is None:
        return {}

    table_name = f"documents_{user_id}"
    schema = settings.db_schema

    try:
        async def _query():
            async with deps.engine._pool.connect() as conn:
                result = await conn.execute(
                    __import__("sqlalchemy").text(f"""
                        SELECT DISTINCT
                            langchain_metadata->>'gdrive_id' as gdrive_id,
                            langchain_metadata->>'md5' as md5
                        FROM "{schema}"."{table_name}"
                        WHERE langchain_metadata->>'gdrive_id' IS NOT NULL
                    """)
                )
                return result.fetchall()

        rows = await deps.engine._run_as_async(_query())
        return {row.gdrive_id: row.md5 for row in rows if row.md5}
    except Exception:
        return {}


async def _delete_document_chunks(user_id: str, gdrive_id: str) -> None:
    """특정 문서의 기존 청크를 삭제한다 (재인덱싱 전)."""
    import app.dependencies as deps

    if deps.engine is None:
        return

    table_name = f"documents_{user_id}"
    schema = settings.db_schema

    async def _delete():
        async with deps.engine._pool.connect() as conn:
            await conn.execute(
                __import__("sqlalchemy").text(f"""
                    DELETE FROM "{schema}"."{table_name}"
                    WHERE langchain_metadata->>'gdrive_id' = :gdrive_id
                """),
                {"gdrive_id": gdrive_id},
            )
            await conn.commit()

    await deps.engine._run_as_async(_delete())


async def ingest_from_gdrive(access_token: str, user_id: str, folder_id: str | None = None) -> tuple[int, list[str], list[str]]:
    """Google Drive 폴더의 모든 지원 파일을 병렬로 읽어 벡터 저장소에 임베딩한다.

    변경된 파일만 재인덱싱 (md5 기반 중복 체크).
    """
    service = _build_drive_service(access_token)

    if not folder_id:
        raise ValueError("drive_folder_id is required")

    files = await _list_files_recursive(service, folder_id)
    if not files:
        raise ValueError("폴더에 파일이 없습니다.")

    # 이미 인덱싱된 문서의 md5 조회
    indexed_checksums = await _get_indexed_checksums(user_id)

    # 변경된 파일만 필터링
    files_to_process = []
    skipped_count = 0
    for f in files:
        gdrive_id = f["id"]
        # Google Apps 문서는 md5Checksum 없음 → modifiedTime 기반
        file_md5 = f.get("md5Checksum") or f.get("modifiedTime", "")
        existing_md5 = indexed_checksums.get(gdrive_id)

        if existing_md5 and existing_md5 == file_md5:
            skipped_count += 1
            continue
        files_to_process.append(f)

    if skipped_count > 0:
        logger.info("Skipped %d unchanged files", skipped_count)

    logger.info(
        "Processing %d files (total: %d, skipped unchanged: %d)",
        len(files_to_process), len(files), skipped_count,
    )

    if not files_to_process:
        return 0, [], []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    loop = asyncio.get_event_loop()
    MAX_RETRIES = 3

    async def _process_with_retry(file_info: dict) -> tuple[list[Document], str] | str | None:
        for attempt in range(MAX_RETRIES):
            try:
                result = await loop.run_in_executor(
                    None, _download_and_parse, access_token, file_info
                )
                return result
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "Retry %d/%d for %s: %s",
                        attempt + 1, MAX_RETRIES, file_info["name"], e,
                    )
                    await asyncio.sleep(1)
                else:
                    logger.error("Failed after %d retries: %s", MAX_RETRIES, file_info["name"])
                    return "FAILED"
        return None

    results = await asyncio.gather(*[_process_with_retry(f) for f in files_to_process])

    all_chunks: list[Document] = []
    processed_files: list[str] = []
    failed_files: list[str] = []
    now = datetime.now(timezone.utc).isoformat()

    for i, result in enumerate(results):
        file_info = files_to_process[i]
        name = file_info["name"]

        if result == "FAILED":
            failed_files.append(name)
            continue
        if result is None:
            continue

        documents, _ = result

        # 기존 청크 삭제 (재인덱싱인 경우)
        if file_info["id"] in indexed_checksums:
            await _delete_document_chunks(user_id, file_info["id"])

        file_md5 = file_info.get("md5Checksum") or file_info.get("modifiedTime", "")

        # 빈 페이지 필터링
        documents = [doc for doc in documents if doc.page_content.strip()]
        chunks = splitter.split_documents(documents)
        logger.info("File %s: %d pages → %d chunks", name, len(documents), len(chunks))

        if not chunks:
            logger.warning("File %s produced 0 chunks (이미지 기반 또는 텍스트 없음)", name)
            failed_files.append(f"{name} (텍스트 추출 불가)")
            continue

        for chunk in chunks:
            chunk.metadata["source"] = name
            chunk.metadata["gdrive_id"] = file_info["id"]
            chunk.metadata["md5"] = file_md5
            chunk.metadata["indexed_at"] = now

        all_chunks.extend(chunks)
        processed_files.append(f"{name} ({len(chunks)} chunks)")

    if all_chunks:
        store = await get_user_vector_store(user_id)
        await store.aadd_documents(all_chunks)

    logger.info(
        "Indexed %d chunks from %d files (skipped: %d, failed: %d) for user %s",
        len(all_chunks), len(processed_files), skipped_count, len(failed_files), user_id,
    )
    return len(all_chunks), processed_files, failed_files
