"""
CSV ingestion pipeline — exact port of src/rag/data-ingestion.service.ts.
Parse CSV → chunk → embed via ada-002 → upsert to Pinecone.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import uuid
from typing import Any

from app.config import get_settings
from app.rag.pipeline import EmbeddingService, VectorService

logger = logging.getLogger(__name__)


class DataIngestionService:
    def __init__(self) -> None:
        self._embedding_service = EmbeddingService()
        self._vector_service = VectorService()

    async def ingest_from_csv(self, csv_file_path: str | None = None) -> None:
        settings = get_settings()
        file_path = csv_file_path or settings.csv_file_path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        logger.info("[DataIngestion] Starting ingestion from: %s", file_path)

        await self._vector_service.initialize_index()
        documents = await asyncio.to_thread(self._parse_csv, file_path)
        logger.info("[DataIngestion] Parsed %d documents from CSV", len(documents))

        chunks = self._chunk_documents(documents)
        logger.info("[DataIngestion] Created %d chunks", len(chunks))

        await self._generate_embeddings_for_chunks(chunks)
        await self._vector_service.upsert_chunks(chunks)
        logger.info("[DataIngestion] Successfully ingested %d chunks into vector database", len(chunks))

    def _parse_csv(self, file_path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, str]] = []
        with open(file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return self._convert_rows_to_documents(rows)

    def _convert_rows_to_documents(self, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            data_quality = int(row.get("data_quality", "0") or "0")
            if data_quality < 30:
                logger.info(
                    "[DataIngestion] Skipping low quality page (%d/100): %s",
                    data_quality,
                    row.get("title", ""),
                )
                continue

            url_path = ""
            try:
                from urllib.parse import urlparse
                if row.get("url"):
                    url_path = urlparse(row["url"]).path
            except Exception:
                url_path = row.get("url", "")

            content_parts = [
                f"Title: {row.get('title', 'N/A')}",
                f"Page Type: {row.get('page_type', 'general')}",
                f"Location: {row.get('location', 'N/A')}",
            ]
            if row.get("price"):
                content_parts.append(f"Price: {row['price']}")
            if row.get("duration"):
                content_parts.append(f"Duration: {row['duration']}")
            content_parts.append(f"Description: {row.get('meta_description', 'N/A')}")
            if row.get("highlights"):
                content_parts.append(f"Highlights: {row['highlights']}")
            if row.get("itinerary"):
                content_parts.append(f"Itinerary: {row['itinerary']}")
            content_parts.append("")
            content_parts.append("Content:")
            content_parts.append(row.get("full_content") or row.get("content") or "")

            content = "\n".join(p for p in content_parts if p is not None)
            import re
            clean_content = re.sub(r"\s+", " ", content).strip()
            clean_content = re.sub(r"\n\s*\n", "\n", clean_content)

            documents.append(
                {
                    "id": f"rayna_{index}_{uuid.uuid4()}",
                    "content": clean_content,
                    "metadata": {
                        "source": "rayna_advanced",
                        "url": (row.get("url") or "")[:300],
                        "title": (row.get("title") or "")[:200],
                        "pageType": row.get("page_type", "general"),
                        "location": (row.get("location") or "")[:100],
                        "price": (row.get("price") or "")[:50],
                        "duration": (row.get("duration") or "")[:50],
                        "description": (row.get("meta_description") or "")[:300],
                        "imageCount": int(row.get("image_count") or "0"),
                        "mainImage": row.get("main_image") or "",
                        "contentLength": int(row.get("content_length") or "0"),
                        "dataQuality": data_quality,
                        "urlPath": url_path[:200],
                        "rowIndex": index,
                        "processedAt": "",
                    },
                }
            )

        logger.info(
            "[DataIngestion] Processed %d valid documents out of %d CSV rows",
            len(documents),
            len(rows),
        )
        return documents

    def _chunk_documents(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        settings = get_settings()
        chunks: list[dict[str, Any]] = []
        for doc in documents:
            doc_chunks = self._chunk_text(doc["content"], settings.rag_chunk_size, settings.rag_chunk_overlap)
            for chunk_index, chunk_content in enumerate(doc_chunks):
                chunks.append(
                    {
                        "id": f"{doc['id']}_chunk_{chunk_index}",
                        "content": chunk_content,
                        "metadata": {
                            **doc["metadata"],
                            "parentDocumentId": doc["id"],
                            "chunkIndex": chunk_index,
                            "totalChunks": len(doc_chunks),
                        },
                    }
                )
        return chunks

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        if len(text) <= chunk_size:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end < len(text):
                last_period = text.rfind(".", start, end)
                last_space = text.rfind(" ", start, end)
                if last_period > start + chunk_size * 0.5:
                    end = last_period + 1
                elif last_space > start + chunk_size * 0.5:
                    end = last_space
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = end - overlap
        return chunks

    async def _generate_embeddings_for_chunks(self, chunks: list[dict[str, Any]]) -> None:
        logger.info("[DataIngestion] Generating embeddings for %d chunks...", len(chunks))
        batch_size = 10
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c["content"] for c in batch]
            embeddings = await self._embedding_service.generate_embeddings(texts)
            for chunk, embedding in zip(batch, embeddings):
                chunk["embedding"] = embedding
                self._validate_metadata_size(chunk)
            logger.info(
                "[DataIngestion] Generated embeddings for batch %d/%d",
                i // batch_size + 1,
                total_batches,
            )
            await asyncio.sleep(0.1)
        logger.info("[DataIngestion] Successfully generated all embeddings")

    @staticmethod
    def _validate_metadata_size(chunk: dict[str, Any]) -> None:
        metadata_str = json.dumps(chunk.get("metadata", {}))
        size = len(metadata_str.encode("utf-8"))
        max_size = 40960  # 40KB Pinecone limit
        if size > max_size:
            logger.warning(
                "[DataIngestion] Metadata too large for chunk %s: %d bytes", chunk["id"], size
            )
            md = chunk["metadata"]
            if md.get("description") and len(md["description"]) > 200:
                md["description"] = md["description"][:200] + "..."
            if md.get("title") and len(md["title"]) > 150:
                md["title"] = md["title"][:150] + "..."
            new_size = len(json.dumps(md).encode("utf-8"))
            if new_size > max_size:
                chunk["metadata"] = {
                    "source": md.get("source", ""),
                    "url": (md.get("url") or "")[:200],
                    "title": (md.get("title") or "")[:100],
                    "pageType": md.get("pageType", ""),
                    "location": (md.get("location") or "")[:50],
                    "price": (md.get("price") or "")[:30],
                    "dataQuality": md.get("dataQuality", 0),
                    "rowIndex": md.get("rowIndex", 0),
                }
                logger.info("[DataIngestion] Severely truncated metadata for chunk %s", chunk["id"])

    async def reingest_from_csv(self, csv_file_path: str | None = None) -> None:
        logger.info("[DataIngestion] Starting re-ingestion...")
        await self._vector_service.clear_index()
        await self.ingest_from_csv(csv_file_path)
        logger.info("[DataIngestion] Re-ingestion completed")
