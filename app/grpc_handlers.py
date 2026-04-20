import logging

import grpc

import app.proto  # noqa: F401  — sys.path 보정
from app.proto import rag_pb2, rag_pb2_grpc
from app.services.gdrive import ingest_from_gdrive
from app.services.rag import stream_query

logger = logging.getLogger(__name__)


class RagServiceServicer(rag_pb2_grpc.RagServiceServicer):

    async def Chat(self, request: rag_pb2.ChatRequest, context: grpc.aio.ServicerContext):
        """질문에 대해 토큰 단위로 스트리밍 응답."""
        logger.info("Chat request: user_id=%s, session_id=%s", request.user_id, request.session_id)

        current_timestamp = ""
        if request.HasField("current_timestamp"):
            current_timestamp = request.current_timestamp.ToDatetime().isoformat()

        k = request.k if request.k > 0 else 4

        try:
            async for token, is_final, docs in stream_query(
                question=request.query,
                k=k,
                current_timestamp=current_timestamp,
            ):
                if is_final:
                    sources = [
                        rag_pb2.SourceDocument(
                            title=doc.metadata.get("source", "unknown"),
                            uri=doc.metadata.get("gdrive_id", ""),
                            score=doc.metadata.get("relevance_score", 0.0),
                        )
                        for doc in docs
                    ]
                    yield rag_pb2.ChatResponse(token="", is_final=True, sources=sources)
                else:
                    yield rag_pb2.ChatResponse(token=token, is_final=False)
        except Exception as e:
            logger.exception("Chat RPC failed")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def IndexDocuments(self, request: rag_pb2.IndexDocumentsRequest, context: grpc.aio.ServicerContext):
        """Google Drive 문서 인덱싱."""
        logger.info("IndexDocuments request: folder_id=%s", request.drive_folder_id)

        if not request.access_token:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "access_token is required")

        try:
            chunk_count, files = await ingest_from_gdrive(request.access_token)
            return rag_pb2.IndexDocumentsResponse(
                chunk_count=chunk_count,
                files=files,
                message=f"{chunk_count}개 청크, {len(files)}개 파일 처리 완료",
            )
        except ValueError as e:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except Exception as e:
            logger.exception("IndexDocuments RPC failed")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))
