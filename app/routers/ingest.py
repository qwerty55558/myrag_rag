from fastapi import APIRouter, UploadFile

from app.schemas import IngestResponse
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
