import logging
from datetime import datetime, timezone

import grpc
from asyncpg.exceptions import UndefinedTableError
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy.exc import ProgrammingError

import rag_pb2
import rag_pb2_grpc
import app.dependencies as deps
from app.config import settings
from app.services.gdrive import ingest_from_gdrive
from app.services.rag import stream_query

logger = logging.getLogger(__name__)


class RagServiceServicer(rag_pb2_grpc.RagServiceServicer):

    async def Chat(self, request: rag_pb2.ChatRequest, context: grpc.aio.ServicerContext):
        """질문에 대해 토큰 단위로 스트리밍 응답."""
        logger.info("Chat request: user_id=%s, session_id=%s", request.user_id, request.session_id)

        if not request.user_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")

        current_timestamp = ""
        if request.HasField("current_timestamp"):
            current_timestamp = request.current_timestamp.ToDatetime().isoformat()

        try:
            async for token, is_final, docs, new_summary in stream_query(
                question=request.query,
                user_id=request.user_id,
                current_timestamp=current_timestamp,
                context_summary=request.context_summary,
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
                    yield rag_pb2.ChatResponse(
                        token="",
                        is_final=True,
                        sources=sources,
                        context_summary=new_summary,
                    )
                else:
                    yield rag_pb2.ChatResponse(token=token, is_final=False)
        except Exception as e:
            logger.exception("Chat RPC failed")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def IndexDocuments(self, request: rag_pb2.IndexDocumentsRequest, context: grpc.aio.ServicerContext):
        """Google Drive 문서 인덱싱."""
        logger.info("IndexDocuments request: user_id=%s, folder_id=%s", request.user_id, request.drive_folder_id)

        if not request.access_token:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "access_token is required")
        if not request.user_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")

        try:
            chunk_count, files, failed = await ingest_from_gdrive(
                request.access_token, request.user_id, request.drive_folder_id
            )
            failed_protos = []
            for f in failed:
                # "filename (reason)" 형식 파싱
                if " (" in f and f.endswith(")"):
                    name, reason = f.rsplit(" (", 1)
                    reason = reason.rstrip(")")
                else:
                    name, reason = f, "알 수 없는 오류"
                failed_protos.append(rag_pb2.FailedFile(file_name=name, reason=reason))

            msg = f"{chunk_count}개 청크, {len(files)}개 파일 처리 완료"
            if failed:
                msg += f" ({len(failed)}개 파일 실패)"
            return rag_pb2.IndexDocumentsResponse(
                chunk_count=chunk_count,
                files=files,
                message=msg,
                failed_files=failed_protos,
            )
        except ValueError as e:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except Exception as e:
            logger.exception("IndexDocuments RPC failed")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def ListIndexedDocuments(self, request: rag_pb2.ListDocumentsRequest, context: grpc.aio.ServicerContext):
        """인덱싱된 문서 목록 조회."""
        logger.info("ListIndexedDocuments request: user_id=%s", request.user_id)

        if not request.user_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")

        try:
            assert deps.engine is not None
            table_name = f"documents_{request.user_id}"
            schema = settings.db_schema

            async def _query():
                async with deps.engine._pool.connect() as conn:
                    result = await conn.execute(
                        __import__("sqlalchemy").text(f"""
                            SELECT
                                langchain_metadata->>'gdrive_id' as document_id,
                                langchain_metadata->>'source' as file_name,
                                langchain_metadata->>'gdrive_id' as source_uri,
                                COUNT(*) as chunk_count,
                                MIN(langchain_metadata->>'indexed_at') as indexed_at
                            FROM "{schema}"."{table_name}"
                            GROUP BY langchain_metadata->>'gdrive_id', langchain_metadata->>'source'
                            ORDER BY indexed_at DESC
                        """)
                    )
                    return result.fetchall()

            try:
                rows = await deps.engine._run_as_async(_query())
            except (ProgrammingError, UndefinedTableError):
                return rag_pb2.ListDocumentsResponse(documents=[])

            documents = []
            for row in rows:
                ts = Timestamp()
                if row.indexed_at:
                    dt = datetime.fromisoformat(row.indexed_at)
                    ts.FromDatetime(dt)
                else:
                    ts.FromDatetime(datetime.now(timezone.utc))

                documents.append(rag_pb2.IndexedDocument(
                    document_id=row.document_id or "",
                    file_name=row.file_name or "",
                    source_uri=row.source_uri or "",
                    chunk_count=row.chunk_count,
                    indexed_at=ts,
                ))

            return rag_pb2.ListDocumentsResponse(documents=documents)
        except Exception as e:
            logger.exception("ListIndexedDocuments RPC failed")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def DeleteDocuments(self, request: rag_pb2.DeleteDocumentsRequest, context: grpc.aio.ServicerContext):
        """인덱싱된 문서 삭제."""
        logger.info("DeleteDocuments request: user_id=%s, ids=%s", request.user_id, list(request.document_ids))

        if not request.user_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "user_id is required")
        if not request.document_ids:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "document_ids is required")

        try:
            assert deps.engine is not None
            table_name = f"documents_{request.user_id}"
            schema = settings.db_schema
            ids = list(request.document_ids)

            async def _delete():
                async with deps.engine._pool.connect() as conn:
                    result = await conn.execute(
                        __import__("sqlalchemy").text(f"""
                            DELETE FROM "{schema}"."{table_name}"
                            WHERE langchain_metadata->>'gdrive_id' = ANY(:ids)
                        """),
                        {"ids": ids},
                    )
                    await conn.commit()
                    return result.rowcount

            try:
                deleted = await deps.engine._run_as_async(_delete())
            except (ProgrammingError, UndefinedTableError):
                return rag_pb2.DeleteDocumentsResponse(
                    deleted_count=0,
                    message="인덱싱된 문서가 없습니다.",
                )

            return rag_pb2.DeleteDocumentsResponse(
                deleted_count=deleted,
                message=f"{deleted}개 청크 삭제 완료",
            )
        except Exception as e:
            logger.exception("DeleteDocuments RPC failed")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def GetSupportedFormats(self, request: rag_pb2.GetSupportedFormatsRequest, context: grpc.aio.ServicerContext):
        """지원 파일 확장자 목록 반환."""
        from app.services.ingestion import LOADER_MAP

        FORMAT_DESCRIPTIONS = {
            ".pdf": "PDF 문서",
            ".doc": "Word 문서 (구버전)",
            ".docx": "Word 문서",
            ".xlsx": "Excel 스프레드시트",
            ".xls": "Excel 스프레드시트 (구버전)",
            ".csv": "CSV 파일",
            ".pptx": "PowerPoint 프레젠테이션",
            ".ppt": "PowerPoint 프레젠테이션 (구버전)",
            ".txt": "텍스트 파일",
            ".md": "마크다운 문서",
            ".html": "HTML 문서",
            ".htm": "HTML 문서",
        }

        formats = [
            rag_pb2.SupportedFormat(
                extension=ext,
                description=FORMAT_DESCRIPTIONS.get(ext, ext),
            )
            for ext in LOADER_MAP
        ]
        return rag_pb2.GetSupportedFormatsResponse(formats=formats)
