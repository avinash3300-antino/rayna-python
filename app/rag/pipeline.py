"""
RAG pipeline — exact port of src/rag/rag.service.ts + embedding.service.ts + vector.service.ts.
Embed user query → Pinecone search → inject context into system prompt.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pinecone import Pinecone

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Wraps OpenAI text-embedding-ada-002 — mirrors embedding.service.ts."""

    def __init__(self) -> None:
        import openai

        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI API key is required for embeddings")
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.embedding_model

    async def generate_embedding(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model, input=text, encoding_format="float"
        )
        return response.data[0].embedding

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self._model, input=texts, encoding_format="float"
        )
        return [item.embedding for item in response.data]


class VectorService:
    """Wraps Pinecone operations — mirrors vector.service.ts."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.pinecone_api_key:
            raise RuntimeError("Pinecone API key is required")
        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index_name = settings.pinecone_index_name

    def _get_index(self):  # type: ignore[no-untyped-def]
        return self._pc.Index(self._index_name)

    async def initialize_index(self, dimension: int = 1536) -> None:
        """Create index if not exists; recreate on dimension mismatch."""

        def _sync_init() -> None:
            existing = self._pc.list_indexes()
            names = [idx.name for idx in existing.indexes] if hasattr(existing, "indexes") else []
            if self._index_name not in names:
                logger.info("[VectorService] Creating Pinecone index: %s dim=%d", self._index_name, dimension)
                self._pc.create_index(
                    name=self._index_name,
                    dimension=dimension,
                    metric="cosine",
                    spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
                )
                self._wait_for_ready()
            else:
                info = self._pc.describe_index(self._index_name)
                if info.dimension != dimension:
                    logger.warning("[VectorService] Dimension mismatch, recreating index")
                    self._pc.delete_index(self._index_name)
                    import time
                    time.sleep(10)
                    self._pc.create_index(
                        name=self._index_name,
                        dimension=dimension,
                        metric="cosine",
                        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
                    )
                    self._wait_for_ready()
                logger.info("[VectorService] Index %s ready (dim=%d)", self._index_name, dimension)

        await asyncio.to_thread(_sync_init)

    def _wait_for_ready(self) -> None:
        import time
        for attempt in range(30):
            info = self._pc.describe_index(self._index_name)
            if info.status.get("ready", False) if isinstance(info.status, dict) else getattr(info.status, "ready", False):
                return
            logger.info("[VectorService] Waiting for index... (%d/30)", attempt + 1)
            time.sleep(2)
        raise TimeoutError(f"Index {self._index_name} not ready after 30 attempts")

    async def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        def _sync_upsert() -> None:
            index = self._get_index()
            vectors = [
                {
                    "id": c["id"],
                    "values": c["embedding"],
                    "metadata": {"content": c["content"], **c.get("metadata", {})},
                }
                for c in chunks
            ]
            batch_size = 100
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i : i + batch_size]
                index.upsert(vectors=batch)
                logger.info(
                    "[VectorService] Upserted batch %d/%d",
                    i // batch_size + 1,
                    (len(vectors) + batch_size - 1) // batch_size,
                )
            logger.info("[VectorService] Successfully upserted %d chunks", len(chunks))

        await asyncio.to_thread(_sync_upsert)

    async def search(self, query_embedding: list[float], top_k: int | None = None) -> list[dict[str, Any]]:
        settings = get_settings()
        k = top_k or settings.rag_top_k

        def _sync_search() -> list[dict[str, Any]]:
            index = self._get_index()
            result = index.query(vector=query_embedding, top_k=k, include_metadata=True, include_values=False)
            matches: list[dict[str, Any]] = []
            for m in result.get("matches", []):
                matches.append(
                    {
                        "id": m.get("id", ""),
                        "score": m.get("score", 0),
                        "metadata": m.get("metadata", {}),
                        "content": m.get("metadata", {}).get("content", ""),
                    }
                )
            return matches

        return await asyncio.to_thread(_sync_search)

    async def clear_index(self) -> None:
        def _sync_clear() -> None:
            index = self._get_index()
            index.delete(delete_all=True)
            logger.info("[VectorService] Cleared all vectors from index: %s", self._index_name)

        await asyncio.to_thread(_sync_clear)

    async def get_index_stats(self) -> dict[str, Any]:
        def _sync_stats() -> dict[str, Any]:
            index = self._get_index()
            return index.describe_index_stats()  # type: ignore[return-value]

        return await asyncio.to_thread(_sync_stats)

    async def delete_index(self) -> None:
        def _sync_delete() -> None:
            self._pc.delete_index(self._index_name)
            logger.info("[VectorService] Deleted index: %s", self._index_name)

        await asyncio.to_thread(_sync_delete)


class RAGService:
    """Orchestration layer — mirrors rag.service.ts."""

    def __init__(self) -> None:
        settings = get_settings()
        self._enabled = settings.rag_enabled
        self._embedding_service: EmbeddingService | None = None
        self._vector_service: VectorService | None = None
        if self._enabled:
            try:
                self._embedding_service = EmbeddingService()
                self._vector_service = VectorService()
            except Exception:
                logger.warning("[RAGService] Failed to initialise RAG services; disabling RAG")
                self._enabled = False

    def is_enabled(self) -> bool:
        settings = get_settings()
        return self._enabled and bool(settings.pinecone_api_key) and bool(settings.openai_api_key)

    async def retrieve_context(
        self, query: str, top_k: int | None = None
    ) -> dict[str, Any] | None:
        if not self.is_enabled() or not self._embedding_service or not self._vector_service:
            logger.info("[RAGService] RAG is disabled or not properly configured")
            return None
        try:
            query_embedding = await self._embedding_service.generate_embedding(query)
            matches = await self._vector_service.search(query_embedding, top_k)
            relevant = [m for m in matches if m["score"] > 0.7]
            if not relevant:
                logger.info("[RAGService] No relevant context found for query")
                return {"query": query, "matches": [], "totalMatches": 0}
            logger.info("[RAGService] Found %d relevant context chunks", len(relevant))
            return {"query": query, "matches": relevant, "totalMatches": len(matches)}
        except Exception:
            logger.exception("[RAGService] Failed to retrieve context")
            return None

    @staticmethod
    def format_context_for_prompt(context: dict[str, Any]) -> str:
        if not context or not context.get("matches"):
            return ""
        lines: list[str] = []
        for i, match in enumerate(context["matches"]):
            lines.append(
                f"Context {i + 1} (Relevance: {match['score'] * 100:.1f}%):\n{match['content']}"
            )
        context_text = "\n\n".join(lines)
        return (
            f"\nRELEVANT KNOWLEDGE BASE CONTEXT:\n{context_text}\n\n"
            "Please use the above context to help answer the user's question. "
            "If the context contains relevant information, incorporate it into your response. "
            "If the context doesn't contain relevant information for the user's question, "
            "rely on your general knowledge but mention that you don't have specific information "
            "about their query in the knowledge base.\n"
        )

    async def get_enhanced_system_prompt(self, original_prompt: str, user_query: str) -> str:
        if not self.is_enabled():
            return original_prompt
        try:
            context = await self.retrieve_context(user_query)
            if not context or not context.get("matches"):
                return original_prompt
            context_prompt = self.format_context_for_prompt(context)
            return f"{original_prompt}\n\n{context_prompt}"
        except Exception:
            logger.exception("[RAGService] Failed to enhance system prompt")
            return original_prompt

    async def get_stats(self) -> dict[str, Any]:
        if not self.is_enabled() or not self._vector_service:
            return {"error": "RAG is not enabled"}
        try:
            settings = get_settings()
            stats = await self._vector_service.get_index_stats()
            return {"enabled": True, "indexName": settings.pinecone_index_name, **stats}
        except Exception:
            logger.exception("[RAGService] Failed to get stats")
            return {"error": "Failed to get statistics"}

    async def test_rag(self, test_query: str = "What services do you offer?") -> dict[str, Any]:
        if not self.is_enabled():
            settings = get_settings()
            return {
                "enabled": False,
                "error": "RAG is not enabled or not properly configured",
                "configuration": {
                    "ragEnabled": settings.rag_enabled,
                    "hasPineconeKey": bool(settings.pinecone_api_key),
                    "hasOpenAIKey": bool(settings.openai_api_key),
                },
            }
        try:
            context = await self.retrieve_context(test_query, 3)
            stats = await self.get_stats()
            from datetime import datetime, timezone
            return {
                "enabled": True,
                "testQuery": test_query,
                "context": context,
                "stats": stats,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"enabled": False, "error": str(e), "testQuery": test_query}
