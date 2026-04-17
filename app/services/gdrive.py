import io
import tempfile
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.dependencies import get_vector_store
from app.services.ingestion import LOADER_MAP

MIME_EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/pdf",
        ".pdf",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "text/csv",
        ".txt",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        ".pdf",
    ),
}


def _build_drive_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds)


async def _find_folder_id(service, folder_path: str) -> str | None:
    """경로를 순회하여 최종 폴더 ID를 반환한다. 예: '/myRag/' -> folder_id"""
    parts = [p for p in folder_path.strip("/").split("/") if p]
    parent_id = "root"

    for part in parts:
        query = (
            f"name = '{part}' and '{parent_id}' in parents "
            f"and mimeType = 'application/vnd.google-apps.folder' "
            f"and trashed = false"
        )
        resp = service.files().list(
            q=query, fields="files(id, name)", pageSize=1
        ).execute()

        files = resp.get("files", [])
        if not files:
            return None
        parent_id = files[0]["id"]

    return parent_id


async def _list_files_recursive(service, folder_id: str) -> list[dict]:
    """폴더 내 모든 파일을 재귀적으로 탐색한다."""
    all_files = []
    page_token = None

    while True:
        query = f"'{folder_id}' in parents and trashed = false"
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
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


def _download_file(service, file_info: dict) -> tuple[bytes, str] | None:
    """파일을 다운로드하고 (bytes, suffix)를 반환한다."""
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
            return None
        request = service.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue(), suffix


async def ingest_from_gdrive(access_token: str) -> tuple[int, list[str]]:
    """Google Drive /myRag/ 경로의 모든 파일을 읽어 벡터 저장소에 임베딩한다."""
    service = _build_drive_service(access_token)

    folder_id = await _find_folder_id(service, "/myRag/")
    if folder_id is None:
        raise ValueError("Google Drive에서 /myRag/ 폴더를 찾을 수 없습니다.")

    files = await _list_files_recursive(service, folder_id)
    if not files:
        raise ValueError("/myRag/ 폴더에 파일이 없습니다.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    all_chunks: list[Document] = []
    processed_files: list[str] = []

    for file_info in files:
        result = _download_file(service, file_info)
        if result is None:
            continue

        data, suffix = result
        name = file_info["name"]

        with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
            tmp.write(data)
            tmp.flush()

            loader_cls = LOADER_MAP[suffix]
            loader = loader_cls(tmp.name)
            documents: list[Document] = loader.load()

        chunks = splitter.split_documents(documents)
        for chunk in chunks:
            chunk.metadata["source"] = name
            chunk.metadata["gdrive_id"] = file_info["id"]

        all_chunks.extend(chunks)
        processed_files.append(name)

    if all_chunks:
        store = get_vector_store()
        await store.aadd_documents(all_chunks)

    return len(all_chunks), processed_files
