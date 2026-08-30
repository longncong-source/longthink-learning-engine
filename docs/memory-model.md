# LongThink Learning Engine — Memory model

## Memory record (spec §5)
`id · user_id · project_id · type · title · content · summary · source ·
importance · confidence · metadata · embedding · created_at · updated_at`

## Types & semantics (spec §14)

| type | meaning | example |
|---|---|---|
| semantic | facts | "LNG Project uses FIDIC Silver Book." |
| episodic | events with time/impact | "Vendor A missed submission by 21 days." |
| procedural | how-to steps | "To submit an RFI: ..." |
| decision | approved choices | "Require vendor drawings 14 days before procurement." |
| lesson | experience learned | "Document review must start before procurement." |
| project/document/task/preference | reserved for later phases | — |

## Importance scale (spec §13)

| value | class | example |
|---|---|---|
| 0.0–0.25 | disposable | "opened file test.py" → never stored |
| 0.25–0.5 | low | casual chat context |
| 0.5 | normal | general facts |
| 0.7± | important | lessons, significant events |
| 0.85+ | critical | contract rules, key decisions |

Deterministic classifier: `local.agent.classify_memory`
(decision > lesson > episodic > semantic). Temporary markers
(`temp/todo/scratch/tạm`) are never stored.

## Write pipeline (§10 + §35)
validate → **redact secrets** (regex, both sides) → verify project exists →
generate embedding (provider configurable) → duplicate check within same
project+type via cosine similarity → merge-or-insert.

Merge policy on dedupe: newer content wins, importance/confidence take max,
metadata deep-merges, embedding refreshes, `deduplicated=true` returned.

## Retrieval pipeline (§11)
embed query → backend hybrid candidate selection → score components:

```
semantic  : 1 − cosine_distance        (pgvector <=> / python cosine)
keyword   : term-F1 overlap            (stopword-filtered, unicode-aware)
importance: stored importance          (0..1)
recency   : 0.5 ^ (age_days/half_life) (default half-life 30d)

final = normalize(w_sem·sem + w_kw·kw + w_imp·imp + w_rec·rec)   # §9
```

Weights via `WEIGHT_SEMANTIC/KEYWORD/IMPORTANCE/RECENCY`. They are a starting
point, not assumed optimal — tune per deployment.

## Decay (§36)
Recency decays automatically; nothing is ever deleted automatically.
Critical memories require explicit `DELETE /v1/memory/{id}` (or `brain memory delete`).

## Local vs cloud (§16/§19)
- Session notes, pending writes, query cache live in `local_data/local.db` only.
- `DATA_POLICY=local_only|selective|cloud_allowed` gates every upload;
  `local_only` keeps everything in SQLite notes and never sends.
- The agent stores only what reflection qualifies; explicit user statements can
  force storage with higher importance.
