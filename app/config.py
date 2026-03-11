"""
Pydantic-settings configuration — replaces src/config/index.ts
All env vars from the Node.js .env work unchanged.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProviderEnum(str, Enum):
    claude = "claude"
    openai = "openai"
    groq = "groq"
    grok = "grok"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    port: int = Field(default=3001, alias="PORT")
    node_env: str = Field(default="production", alias="NODE_ENV")
    cors_origin: str = Field(default="http://localhost:3000", alias="CORS_ORIGIN")

    # LLM
    llm_provider: LLMProviderEnum = Field(default=LLMProviderEnum.claude, alias="LLM_PROVIDER")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    grok_api_key: str = Field(default="", alias="GROK_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")

    # Rayna API
    rayna_api_base_url: str = Field(
        default="https://earnest-panda-e8edbd.netlify.app/api",
        alias="RAYNA_API_BASE_URL",
    )

    # Session
    session_max_messages: int = Field(default=10, alias="SESSION_MAX_MESSAGES")
    session_ttl_minutes: int = Field(default=30, alias="SESSION_TTL_MINUTES")

    # Rate limiting
    rate_limit_window_ms: int = Field(default=60000, alias="RATE_LIMIT_WINDOW_MS")
    rate_limit_max_requests: int = Field(default=20, alias="RATE_LIMIT_MAX_REQUESTS")

    # PostgreSQL
    database_url: str = Field(default="", alias="DATABASE_URL")

    # RAG
    rag_enabled: bool = Field(default=True, alias="RAG_ENABLED")
    pinecone_api_key: str = Field(default="", alias="PINECONE_API_KEY")
    pinecone_environment: str = Field(default="us-east-1", alias="PINECONE_ENVIRONMENT")
    pinecone_index_name: str = Field(default="raynatour-openai", alias="PINECONE_INDEX_NAME")
    embedding_model: str = Field(default="text-embedding-ada-002", alias="EMBEDDING_MODEL")
    rag_chunk_size: int = Field(default=1000, alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(default=200, alias="RAG_CHUNK_OVERLAP")
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")
    csv_file_path: str = Field(default="data/knowledge.csv", alias="CSV_FILE_PATH")

    # Redis (new for Python stack)
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
