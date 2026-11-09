-- =====================================================
-- SQL Statements for Manual Execution in Supabase Dashboard
-- =====================================================
-- Copy these into SQL Editor and run them
-- =====================================================

-- 1. CHECK CURRENT FUNCTION STATE
-- =====================================================
SELECT 
    p.proname as function_name,
    pg_get_functiondef(p.oid) as function_definition
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.proname = 'atomic_replace_document'
AND n.nspname = 'public';

-- 2. CHECK FUNCTION PARAMETERS
-- =====================================================
SELECT 
    p.proname as function_name,
    pg_get_function_arguments(p.oid) as arguments,
    pg_get_function_result(p.oid) as return_type
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.proname = 'atomic_replace_document'
AND n.nspname = 'public';

-- 3. DROP AND RECREATE FUNCTION (if needed)
-- =====================================================
-- Only run this if the function needs updating

DROP FUNCTION IF EXISTS atomic_replace_document(text, jsonb, jsonb);

CREATE OR REPLACE FUNCTION atomic_replace_document(
    p_source_id text,
    p_doc_data jsonb,
    p_chunks_data jsonb
)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
    v_doc_id uuid;
    v_chunk jsonb;
BEGIN
    -- Validate inputs before deletion
    IF p_source_id IS NULL THEN
        RAISE EXCEPTION 'source_id cannot be null';
    END IF;
    
    IF p_doc_data IS NULL THEN
        RAISE EXCEPTION 'doc_data cannot be null';
    END IF;
    
    IF p_chunks_data IS NULL OR jsonb_typeof(p_chunks_data) != 'array' THEN
        RAISE EXCEPTION 'chunks_data must be a JSON array';
    END IF;
    
    IF jsonb_array_length(p_chunks_data) = 0 THEN
        RAISE EXCEPTION 'chunks_data must contain at least one chunk';
    END IF;

    -- Delete old document (cascades to chunks via FK)
    DELETE FROM chunks WHERE document_id = (
        SELECT id FROM documents WHERE source_id = p_source_id
    );
    DELETE FROM documents WHERE source_id = p_source_id;

    -- Insert new document
    INSERT INTO documents (
        source_id, title, organization, domain, jurisdiction, state,
        document_type, source_url, effective_date, document_date,
        verified_date, source_type
    )
    VALUES (
        p_source_id,
        p_doc_data->>'title',
        p_doc_data->>'organization',
        p_doc_data->>'domain',
        p_doc_data->>'jurisdiction',
        p_doc_data->>'state',
        p_doc_data->>'document_type',
        p_doc_data->>'source_url',
        (p_doc_data->>'effective_date')::DATE,
        (p_doc_data->>'document_date')::DATE,
        COALESCE((p_doc_data->>'verified_date')::DATE, CURRENT_DATE),
        COALESCE(p_doc_data->>'source_type', 'seed')
    )
    RETURNING id INTO v_doc_id;

    -- Insert chunks from JSON array
    FOR v_chunk IN
        SELECT value
        FROM jsonb_array_elements(p_chunks_data)
    LOOP
        INSERT INTO chunks (document_id, page, section, content, embedding)
        VALUES (
            v_doc_id,
            COALESCE((v_chunk->>'page')::INTEGER, 0),
            COALESCE(v_chunk->>'section', ''),
            v_chunk->>'content',
            -- Supabase pgvector handles JSONB to vector conversion
            (v_chunk->>'embedding')::VECTOR(768)
        );
    END LOOP;

    RETURN v_doc_id;
END;
$$;

-- 4. VERIFY FUNCTION WAS UPDATED
-- =====================================================
SELECT 
    p.proname as function_name,
    pg_get_function_arguments(p.oid) as arguments
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.proname = 'atomic_replace_document'
AND n.nspname = 'public';

-- 5. CHECK INDEX USAGE
-- =====================================================
SELECT 
    schemaname,
    relname as tablename,
    indexrelname as indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE relname = 'chunks'
ORDER BY idx_scan DESC;

-- 6. CHECK CHUNK COUNT PER DOCUMENT
-- =====================================================
SELECT 
    d.source_id,
    d.title,
    COUNT(c.id) as chunk_count
FROM documents d
LEFT JOIN chunks c ON c.document_id = d.id
GROUP BY d.id, d.source_id, d.title
ORDER BY d.source_id;

-- 7. CHECK EMBEDDING DIMENSION CONSISTENCY
-- =====================================================
SELECT 
    MIN(array_length(string_to_array(embedding::text, ','), 1)) as min_dim,
    MAX(array_length(string_to_array(embedding::text, ','), 1)) as max_dim,
    COUNT(*) as total_chunks
FROM chunks
WHERE embedding IS NOT NULL;

-- 8. TEST RPC FUNCTION
-- =====================================================
-- Run this to verify the function works
SELECT * FROM match_chunks(
    ARRAY[0.1]::vector(768),  -- dummy embedding
    NULL,  -- match_domain (any)
    NULL,  -- match_state (any)
    5      -- match_count
);

-- 9. CHECK FOR ORPHAN CHUNKS
-- =====================================================
SELECT 
    c.id as chunk_id,
    c.document_id
FROM chunks c
LEFT JOIN documents d ON c.document_id = d.id
WHERE d.id IS NULL
LIMIT 10;

-- 10. CHECK DUPLICATE SOURCE_IDS
-- =====================================================
SELECT 
    source_id,
    COUNT(*) as count
FROM documents
GROUP BY source_id
HAVING COUNT(*) > 1;
