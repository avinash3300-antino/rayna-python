"""
RAG API — replaces src/rag/rag.router.ts.
GET  /api/rag/status
POST /api/rag/test
POST /api/rag/ingest
POST /api/rag/search
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.rag.ingest import DataIngestionService
from app.rag.pipeline import RAGService

router = APIRouter(prefix="/api/rag", tags=["rag"])

_rag_service = RAGService()
_ingestion_service: DataIngestionService | None = None


def _get_ingestion_service() -> DataIngestionService:
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = DataIngestionService()
    return _ingestion_service


@router.get("/status")
async def rag_status() -> JSONResponse:
    try:
        stats = await _rag_service.get_stats()
        return JSONResponse(status_code=200, content={"success": True, "data": stats})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": "Failed to get RAG status"})


class TestRequest(BaseModel):
    query: str | None = None


@router.post("/test")
async def rag_test(body: TestRequest) -> JSONResponse:
    try:
        test_query = body.query or "What services do you offer?"
        result = await _rag_service.test_rag(test_query)
        return JSONResponse(status_code=200, content={"success": True, "data": result})
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "error": "Failed to test RAG"})


class IngestRequest(BaseModel):
    csvFilePath: str | None = None
    reingest: bool = False


@router.post("/ingest")
async def rag_ingest(body: IngestRequest) -> JSONResponse:
    try:
        svc = _get_ingestion_service()
        import logging
        logging.getLogger(__name__).info(
            "[RAG Router] Starting %singestion...", "re-" if body.reingest else ""
        )
        if body.reingest:
            await svc.reingest_from_csv(body.csvFilePath)
        else:
            await svc.ingest_from_csv(body.csvFilePath)

        stats = await _rag_service.get_stats()
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Data {'re-' if body.reingest else ''}ingestion completed successfully",
                "data": stats,
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


class SearchRequest(BaseModel):
    query: str
    topK: int | None = None


@router.post("/search")
async def rag_search(body: SearchRequest) -> JSONResponse:
    if not body.query:
        return JSONResponse(status_code=400, content={"success": False, "error": "Query is required"})
    try:
        context = await _rag_service.retrieve_context(body.query, body.topK)
        return JSONResponse(status_code=200, content={"success": True, "data": context})
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "error": "Failed to search context"})
