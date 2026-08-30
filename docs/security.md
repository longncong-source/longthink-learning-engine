# LongThink Learning Engine — Security model

## Secrets handling (§18)
- No credentials in source code. All secrets come from `.env` files:
  - `cloud/.env` → `MEMORY_API_KEYS`, DB password, etc.
  - `local/.env` → `SECOND_BRAIN_API_KEY`, LLM keys.
- `.gitignore` blocks `.env*` (examples kept via `!.env.example`).
- Environment separation (§44): use `cloud/.env.development|.test|.production`
  and point the app at one by copying to `cloud/.env`; never mix credentials.

## Authentication (§21)
- MVP: static API keys (`MEMORY_API_KEYS`, comma-separated).
- Transport headers: `X-API-Key: <k>` or `Authorization: Bearer <k>`.
- Comparison is constant-time (`hmac.compare_digest`); fail-closed if no key
  configured server-side.
- Roadmap: per-user keys → JWT/OAuth2 (Phase 6+).

## Rate limiting (§26)
In-memory sliding window per API key/IP, default 240 req/min
(`RATE_LIMIT_PER_MINUTE`). Exceeding returns `429` + `Retry-After`.

## Secret redaction (§20) — deterministic, never LLM-based
Applied client-side *before upload* AND server-side *before storage*:
API keys (`sk-…`), GitHub tokens (`ghp_…`), Slack (`xox…`), AWS (`AKIA…`),
JWTs, PEM private-key blocks, `Bearer <token>` headers,
`password/token/api_key/secret… = value` assignments → `[REDACTED_*]`.
Count is returned in write responses (`redaction_count`) for auditability.

## Privacy policy (§19)
`DATA_POLICY` (in `local/.env`):
- `local_only`: nothing leaves the laptop (stored as local notes only)
- `selective`: default — agent/reflection decides what deserves cloud storage
- `cloud_allowed`: explicit CLI/user actions always sync

Per-call override: `--no-cloud` flag / `allow_cloud=False`.

## Retrieved data = untrusted (§34)
Priority hierarchy enforced in prompts and code:
`USER INSTRUCTION > SYSTEM POLICY > AGENT RULES > RETRIEVED DOCUMENTS`.
Evidence is wrapped in an explicit UNTRUSTED DATA block; the agent never
executes instructions found inside memories or documents.

## Human-in-the-loop (§40)
Destructive/high-impact actions (delete memory, store critical decision when
interactive) require explicit APPROVE. `brain demo --ask` demonstrates the gate;
automation paths use explicit flags instead of silent autonomy.

## Observability (§25)
Access logs contain `request_id · method · path · status · duration_ms` only —
never query text, bodies, or secrets. Errors return meaningful codes without
leaking internals; unexpected exceptions log full traces server-side but return
a generic body.

## Persistent audit trail (§41 Phase 6)
Every request and storage-domain action is appended to the `audit_events`
table in the same database as memories (survives restarts, unlike access logs).
Exposed read-only via `GET /v1/admin/audit`. Same privacy rule as logs:
metadata only, no payloads. Writes are best-effort — audit outages degrade to
a Prometheus counter, never to user-facing failures.
