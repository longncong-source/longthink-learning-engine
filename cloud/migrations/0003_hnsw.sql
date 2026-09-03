-- ============================================================================
-- HNSW cosine index on memories.embedding (production dimension fixed at 768).
-- Idempotent: guarded by column-type check; safe to re-apply via init_schema.
-- Target: vector search < 2s at 100k+ documents (VECTOR spec section 26).
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'embedding'
          AND udt_name = 'vector' AND character_maximum_length IS NULL
    ) THEN
        ALTER TABLE memories
            ALTER COLUMN embedding TYPE vector(768) USING embedding::vector(768);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);
