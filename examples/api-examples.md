# API usage examples

See `docs/api.md` for full reference. Quick copy-paste flows:

## 1. Write a decision (with confirmation semantics on the CLI side)
```bash
KEY=dev-local-key BASE=http://127.0.0.1:8100
curl -X POST "$BASE/v1/memory" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{
    "type": "decision",
    "title": "We decided to require vendor drawings 14 days before procurement",
    "content": "We decided to require vendor drawings 14 days before procurement.",
    "importance": 0.85,
    "metadata": {"rule_id": "VD-14"}
  }'
```

## 2. Search with filters
```bash
curl -X POST "$BASE/v1/memory/search" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "query": "what is our rule for vendor drawings?",
    "top_k": 5,
    "filters": {"min_importance": 0.6}
  }'
```

## 3. Duplicate suppression demo
POST the same content twice → second response returns
`"deduplicated": true` and the SAME memory id.

## 4. Secret redaction demo
```bash
curl -X POST "$BASE/v1/memory" -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"drill","content":"key sk-proj-abcdefgh123456789012 leaked"}'
# -> stored content contains [REDACTED_API_KEY], redaction_count >= 1
```

## 5. CLI equivalents
```powershell
.\scripts\brain.ps1 status
.\scripts\brain.ps1 doctor
.\scripts\brain.ps1 memory search "mechanical drawing delays"
.\scripts\brain.ps1 memory add --title "Fact" --content "..." --type semantic --importance 0.55
.\scripts\brain.ps1 project create "My New Project"
.\scripts\brain.ps1 sync
.\scripts\brain.ps1 demo --yes
```
