from fastapi import APIRouter, UploadFile

from app.schemas import GdriveIngestRequest, GdriveIngestResponse, IngestResponse
from app.services.gdrive import ingest_from_gdrive
from app.services.ingestion import ingest_file

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", response_model=IngestResponse)
async def ingest(file: UploadFile):
    """문서 파일을 업로드하여 벡터 저장소에 저장합니다."""
    count = await ingest_file(file)
    return IngestResponse(
        document_count=count,
        message=f"{file.filename}: {count}개 청크 저장 완료",
    )


@router.post("/gdrive", response_model=GdriveIngestResponse)
async def ingest_gdrive(request: GdriveIngestRequest):
    """Google Drive /myRag/ 폴더의 모든 문서를 임베딩합니다."""
    chunk_count, files = await ingest_from_gdrive(request.access_token)
    return GdriveIngestResponse(
        chunk_count=chunk_count,
        files=files,
        message=f"{len(files)}개 파일, {chunk_count}개 청크 저장 완료",
    )
