# LongThink Learning Engine

> ## 🧠 LongThink Learning Engine — MVP (First Brain + Second Brain)
>
> **Local Agent ↔ Cloud Long-Term Memory** theo spec `FIRST_SECOND_BRAIN.md`.
> MVP đúng 5 thành phần: **OpenCode + Ollama/LM Studio + FastAPI + PostgreSQL/pgvector + Docker Compose**
> (kèm SQLite fallback để chạy được ngay cả khi chưa có Docker — như trên laptop hiện tại).
>
> ### Quick start (Windows)
> ```powershell
> .\INSTALL.bat                                                              # one-click: venv + deps + .env + API :8100 + demo PASS
> # hoặc thủ công:
> .\scripts\setup.ps1                                                        # venv + deps + .env
> .\.venv\Scripts\python.exe -m uvicorn cloud.app.main:app --port 8100       # Second Brain API
> .\.venv\Scripts\python.exe -m local.brain_cli demo --yes                   # full loop demo
> .\.venv\Scripts\python.exe -m local.brain_cli doctor                       # diagnostics
> ```
> Mở **LongThink Control Center** (Obsidian Graph View): `http://127.0.0.1:8100/ui/` — quản lý Projects, Upload (local/cloud), Ghi Memory, Tìm kiếm hybrid, Metrics/Audit.
>
> ### Docker (PostgreSQL + pgvector)
> ```powershell
> docker compose -f docker-compose.brain.yml up -d --build   # api :8100, db :5433
> ```
>
> | Thành phần | Vị trí |
> |---|---|
> | Memory API (FastAPI) | `cloud/` — auth, hybrid search, dedupe, redaction |
> | First Brain (CLI/agent) | `local/` — `brain` CLI, agent loop 8 pha, queue/cache |
> | Document RAG | `brain doc upload file.pdf --project "LNG Project"` → search kèm citation filename+page |
> | Tài liệu | `docs/` architecture · api · memory-model · security · deployment |
> | Spec gốc | `FIRST_SECOND_BRAIN.md` |
>
> Tests: `.\.venv\Scripts\python.exe -m pytest` — **192 passed** · Web UI: `http://127.0.0.1:8100/ui/` · Bulk import: `POST /v1/memory/import` (json/jsonl/csv/md/txt).
> Trạng thái phase: xem bảng trong `docs/architecture.md`.

---

# AI Project Knowledge System - Local RAG on Windows Laptop

A complete local AI system for managing project knowledge documents with automatic
indexing, semantic search, and chat interface - all running offline on your laptop.

## Overview

This system automatically:
- Detects new/changed files in `documents/` subfolders
- Reads PDF, Word, and Excel files
- Chunks text with page number preservation
- Creates embeddings using local models
- Updates Qdrant Vector Database incrementally
- Provides RAG queries with source attribution (filename + page number)

## Architecture

```text
┌─────────────────┐      ┌──────────────────────┐
│  documents/     │      │  Qdrant Vector DB      │
│   Contract/     ├────►│  project_knowledge   │
│   Drawing/      │      │  (vectors + metadata) │
│   Specification│      └──────────────────────┘
│   QAQC/          │
│   Progress/     │      ┌──────────────────────┐
│   Meeting/      ├────►│  FastAPI RAG Service   │
└─────────────────┘      │  (port 8000)          │
                         │  Open WebUI (port 3000)│
                         └────────────────────────┘
                                   ▲
                                   │
                         ┌──────────────────────┐
                         │  Python Watchdog      │
                         │  (file monitoring)    │
                         └──────────────────────┘
                                   │
                          ┌──────────┴──────────┐
                          │  Ollama LLM (port)  │
                          └──────────────────────┘
```

## Prerequisites

- Windows 10/11 laptop
- Docker Desktop installed and running
- 8GB+ RAM recommended
- 10GB+ free disk space

## Quick Start

### 1. Clone and Setup

```powershell
# Clone this repository
git clone <your-repo-url>
cd Default-Project

# Run setup script (builds Docker images and starts services)
.\setup.ps1
```

### 2. Start All Services

```powershell
# Start all services via Docker Compose
docker compose up -d
```

This starts:
- **Qdrant** vector database (port 6333)
- **Ollama** LLM server (port 11434)
- **FastAPI** RAG API (port 8000)
- **Open WebUI** chat interface (port 3000)
- **Data ingestion** service with file watcher

### 3. Add Documents

Place your project files in the `documents/` subfolders:

```
documents/
├── Contract/
├── Drawing/
├── Specification/
├── QAQC/
├── Progress/
└── Meeting/
```

Supported formats: PDF, DOCX, XLSX

### 4. First Ingestion

The system will automatically detect and index all existing files when it first starts.
You can also trigger manual ingestion:

```powershell
# Run ingestion once (processes all current files)
docker compose run --rm data-ingest

# Or via the API
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your question here", "similarity_top_k": 3}'
```

### 5. Start Chatting

Open your browser to [http://localhost:3000](http://localhost:3000)

You can now ask questions about your project documents. The AI will:
- Search the vector database for relevant chunks
- Generate answers using the local LLM
- **Display the source document filename and page number** for each answer

## Incremental Updates

The system automatically tracks indexed files using modification time. When you:
- Add a new file to any `documents/` subfolder
- Modify an existing file

The Watchdog monitor detects the change and triggers re-ingestion of only that file.
No need to re-index the entire project.

To manually trigger re-ingestion:
```powershell
docker compose run --rm data-ingest
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Root status |
| `/health` | GET | Health check |
| `/api/search` | POST | RAG query with source attribution |

**Request:**
```json
{
  "query": "What are the safety requirements in the contract documents?",
  "similarity_top_k": 3
}
```

**Response:**
```json
{
  "answer": "Based on the contract documents...",
  "sources": [
    {
      "file_path": "documents/Contract/agreement.pdf",
      "filename": "agreement.pdf",
      "page_number": 5,
      "revision": "Rev B",
      "discipline": "Contract"
    }
  ]
}
```

## Development & Customization

### Adding New Features

The code is modular - located in `app/` directory:

- `app/chunks/` - File chunking (PDF, DOCX, Excel)
- `app/ingest/` - Ingestion pipeline with change detection
- `app/monitor/` - Watchdog file monitoring
- `app/vdb/` - Qdrant vector database operations
- `app/main.py` - FastAPI RAG endpoints

### Extending with DeepSeek Harness + LangGraph + OpenCode

The system is designed for future integration:

1. **DeepSeek Harness**: Add as alternative LLM provider in `app/vdb/`
2. **LangGraph**: Create agent workflows in `app/agents/` for:
   - Engineering document management
   - QA/QC compliance checking
   - Progress report generation
3. **OpenCode**: Hook into CI/CD for automatic documentation updates

### Configuration

Edit `.env` file to configure:
- `QDRANT_URL`, `COLLECTION_NAME` - Vector DB settings
- `OLLAMA_URL`, `OLLAMA_MODEL` - LLM configuration
- `EMBEDDING_MODEL` - Embedding model selection
- `CHUNK_SIZE`, `CHUNK_OVERLAP` - Chunking parameters
- `DOCUMENTS_DIR` - Documents directory path

## Troubleshooting

### Common Issues

1. **Docker containers won't start**
   - Ensure Docker Desktop is running
   - Check `docker compose logs` for errors
   - Verify WSL 2 is enabled

2. **No documents found**
   - Ensure files are in `documents/` subfolders
   - Supported: PDF, DOCX, XLSX
   - Check `.env` configuration

3. **RAG returns no results**
   - Ensure documents have been ingested
   - Run `docker compose run --rm data-ingest`
   - Check Qdrant dashboard at http://localhost:6333

4. **Embedding model mismatch**
   - Ensure `EMBEDDING_MODEL` matches between `.env` and code
   - Default: `sentence-transformers/all-MiniLM-L6-v2`

5. **Watchdog not detecting changes**
   - On Windows, ensure file events are properly fired
   - Try restarting the data-ingest service
   - Check that files are not open in other applications

### Logs

- Docker: `docker compose logs -f [service-name]`
- Application: Check container stdout/stderr
- Qdrant: Visit http://localhost:6333 for web dashboard

## Project Structure

```
Default-Project/
├── documents/              # Project documents (add your files here)
│   ├── Contract/
│   ├── Drawing/
│   ├── Specification/
│   ├── QAQC/
│   ├── Progress/
│   └── Meeting/
├── app/                    # Python application code
│   ├── chunks/             # File chunking logic
│   ├── ingest/             # Ingestion pipeline
│   ├── monitor/            # Watchdog file monitoring
│   ├── vdb/                # Qdrant vector DB operations
│   └── main.py             # FastAPI RAG endpoints
├── docker-compose.yml      # Service orchestration
├── Dockerfile.base         # Base Docker image
├── api/                    # API service Dockerfile
├── data/                   # Data ingestion Dockerfile
├── .env                    # Environment configuration
└── README.md               # This file
```

## License

This project is licensed under the MIT License.