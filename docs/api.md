# LongThink Learning Engine — Memory API reference

Base URL (local): `http://127.0.0.1:8100` — OpenAPI docs at `/docs`.

Authentication on all routes except `/health`: header
`X-API-Key: <key>` **or** `Authorization: Bearer <key>`.
Keys are configured via `MEMORY_API_KEYS` (comma-separated) in `cloud/.env`.

## GET /health
```json
{"status": "ok"}
```

## GET /health/details *(auth)*
Returns environment, storage backend info/counts, embedding config. `503`-free:
degraded state reported as `"reachable": false`.

## POST /v1/memory *(auth)* — write
```json
{
  "project_id": null,
  "type": "episodic",
  "title": "Vendor A mechanical drawing delay",
  "content": "Vendor A delayed approval by 21 days.",
  "summary": null,
  "source": "demo",
  "importance": 0.75,
  "confidence": 0.9,
  "metadata": {"vendor": "A"}
}
```
Response `201`:
```json
{
  "memory": { "id": "...", "...": "..." },
  "deduplicated": false,
  "redaction_count": 0
}
```
Server-side pipeline: validate → redact secrets → verify project → embed →
dedupe-check (merge if cosine ≥ `DEDUPE_THRESHOLD`) → store.

## POST /v1/memory/search *(auth)*
```json
{
  "query": "mechanical drawing delays",
  "project_id": null,
  "top_k": 8,
  "filters": {
    "type": "lesson",           // string or list
    "min_importance": 0.6,
    "metadata": {"vendor": "A"}
  }
}
```
Response includes per-result breakdown:
```json
{
  "query": "...",
  "total": 2,
  "results": [
    {
      "id": "...", "type": "episodic", "title": "...", "content": "...",
      "score": 0.52,
      "scores": {"semantic": 0.42, "keyword": 0.47, "importance": 0.7, "recency": 1.0},
      "metadata": {}, "created_at": "...", "updated_at": "..."
    }
  ]
}
```

## GET /v1/memory?limit=&offset=&project_id=&type= *(auth)*
List newest-first (used by `brain memory list`).

## GET /v1/memory/{id} *(auth)* → 200 / 404
## DELETE /v1/memory/{id} *(auth)* → 204 / 404

## GET /v1/projects · POST /v1/projects · GET /v1/projects/{id} *(auth)*
Duplicate names → `409 conflict`.

## Documents / RAG (spec sections 31-32)

### POST /v1/documents/upload *(auth, multipart)*
Fields: `file` (PDF/DOCX/TXT/MD), optional `project_id`, `title`, `source`.
Pipeline: extract text (PDF page numbers preserved) → semantic chunking
(`CHUNK_SIZE_CHARS`, `CHUNK_OVERLAP_CHARS`) → embed each chunk → store chunks +
mirror every chunk as a `type="document"` memory.
```bash
curl -X POST $BASE/v1/documents/upload -H "X-API-Key: $KEY" \
  -F "file=@brief.md" -F "project_id=<uuid>" -F "title=Brief"
# 201 {"document": {...}, "chunks_indexed": 5}
```
Errors: `413` too large (`MAX_UPLOAD_MB`), `415` unsupported type,
`422` no extractable text (e.g. scanned PDF without OCR), `503` parser dep missing.

Search documents through the normal endpoint:
```json
{"query": "hydrotest boundaries", "filters": {"type": "document"}}
```
Each hit carries `metadata.filename`, `metadata.page`, `metadata.document_id`,
`metadata.chunk_index` for source citation.

### GET /v1/documents?limit=&project_id= · GET /v1/documents/{id} *(auth)*
### DELETE /v1/documents/{id} *(auth)* → 204
Removes the document, all its chunks, and every mirrored chunk memory.

## Admin & observability *(auth)*

### GET /v1/admin/audit?limit=&kind=
Recent operational events, newest first (`limit` ≤ 500). Two kinds:
- `http` — one row per request: `method`, `path`, `status`, `duration_ms`, `request_id`
- domain events — `memory.write`, `memory.search`, `document.ingest`,
  `document.delete`, `project.create` with `result_count` and a small `detail`
  object (e.g. `{"deduplicated": true, "redactions": 0}`)

Never contains query text, bodies, or secrets. Audit writes are best-effort:
a failed audit insert increments `fsb_audit_write_failures_total` but never
fails the user request.

```bash
curl "$BASE/v1/admin/audit?limit=20" -H "X-API-Key: $KEY"
```

### GET /v1/admin/metrics
Prometheus text format. Counters/gauges: `fsb_build_info{backend}`,
`fsb_uptime_seconds`, `fsb_http_requests_total{code}`, `fsb_memory_writes_total{result=created|merged}`,
`fsb_memory_searches_total`, `fsb_documents_ingested_total`, `fsb_document_chunks_total`,
`fsb_documents_deleted_total`, `fsb_projects_created_total`, `fsb_audit_write_failures_total`.

## Error envelope (all errors)
```json
{"error": {"code": "unauthorized|validation_error|not_found|conflict|rate_limited|upstream_unavailable|storage_unavailable", "message": "...", "details": {}}}
```

## curl examples
```bash
KEY=dev-local-key BASE=http://127.0.0.1:8100

curl $BASE/health
curl -X POST $BASE/v1/memory -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"type":"decision","title":"Rule","content":"Vendor drawings 14 days before procurement","importance":0.85}'
curl -X POST $BASE/v1/memory/search -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" -d '{"query":"vendor drawings rule","top_k":3}'
curl "$BASE/v1/memory?limit=5" -H "X-API-Key: $KEY"
```
