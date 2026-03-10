# Rayna Tours AI Chatbot — Python/FastAPI Backend

## Prerequisites

- **Python 3.12 or 3.13** (3.14 is not supported yet)
- **Redis** (required for rate limiting and Celery background tasks)
- **MongoDB** (optional — needed for conversation history persistence)
- **Docker & Docker Compose** (optional — for containerized setup)

## Project Structure

```
rayna-python/
├── .env                  # Environment variables (create this)
├── pyproject.toml        # Project config & dependencies
├── Dockerfile
├── docker-compose.yml
├── data/                 # Knowledge base CSV files
└── app/
    ├── main.py           # FastAPI entrypoint
    ├── config.py         # Settings (reads .env)
    ├── agent/            # LangGraph agent (graph, state, provider)
    ├── api/v1/           # API routes (chat, history, rag)
    ├── memory/           # Session & MongoDB repositories
    ├── middleware/        # Rate limiting
    ├── models/           # Pydantic schemas
    ├── prompts/          # System prompts
    ├── rag/              # RAG pipeline & ingestion
    └── tools/            # Tour database, visa service, etc.
```

## Setup

### 1. Create a virtual environment

```bash
py -3.13 -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e .
```

For development tools (ruff, mypy, pytest):

```bash
pip install -e ".[dev]"
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
# Server
PORT=3001
NODE_ENV=development
CORS_ORIGIN=http://localhost:3000

# LLM Provider — choose one: claude, openai, groq, grok
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...

# MongoDB (optional — history won't persist without it)
MONGODB_URI=mongodb+srv://<username>:<password>@cluster.mongodb.net/rayna

# RAG (optional — for knowledge base search)
RAG_ENABLED=true
PINECONE_API_KEY=...
PINECONE_ENVIRONMENT=us-east-1
PINECONE_INDEX_NAME=raynatour-openai
EMBEDDING_MODEL=text-embedding-ada-002

# Redis
REDIS_URL=redis://localhost:6379/0
```

**Required:** At least one LLM API key matching your `LLM_PROVIDER`.

## Running the App

### Option A: Local (without Docker)

Make sure Redis is running locally, then:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

### Option B: Docker Compose (recommended)

This starts the FastAPI app, Redis, and a Celery worker automatically:

```bash
docker-compose up --build
```

## Verify It's Running

Open in your browser or use curl:

- **Root:** `http://localhost:3001/` — returns API info and available endpoints
- **Health:** `http://localhost:3001/health` — returns `{"status": "ok"}`

## API Endpoints

| Method | Endpoint                              | Description                 |
| ------ | ------------------------------------- | --------------------------- |
| POST   | `/api/chat`                           | Send a chat message         |
| DELETE  | `/api/chat/session/{sessionId}`      | Clear a session             |
| GET    | `/api/chat/health`                    | Chat health check           |
| GET    | `/api/history`                        | List all conversations      |
| GET    | `/api/history/{sessionId}`            | Get conversation messages   |
| DELETE  | `/api/history/{sessionId}`           | Delete a conversation       |
| GET    | `/api/history/{sessionId}/conversions`| Session conversions         |
| GET    | `/api/history/conversions/all`        | All conversions             |
| GET    | `/api/rag/status`                     | RAG pipeline status         |
| POST   | `/api/rag/test`                       | Test RAG query              |
| POST   | `/api/rag/ingest`                     | Ingest knowledge base       |
| POST   | `/api/rag/search`                     | Search knowledge base       |
