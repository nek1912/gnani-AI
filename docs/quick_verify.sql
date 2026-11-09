-- =====================================================
-- QUICK VERIFICATION SQL
-- Run these one at a time in Supabase SQL Editor
-- =====================================================

-- 1. Count documents and chunks
SELECT 
    (SELECT COUNT(*) FROM documents) as documents,
    (SELECT COUNT(*) FROM chunks) as chunks;

-- 2. List all documents
SELECT source_id, title, domain, jurisdiction 
FROM documents 
ORDER BY source_id;

-- 3. Check embedding dimensions
SELECT 
    MIN(array_length(string_to_array(embedding::text, ','), 1)) as min_dim,
    MAX(array_length(string_to_array(embedding::text, ','), 1)) as max_dim
FROM chunks 
WHERE embedding IS NOT NULL;

-- 4. Test match_chunks RPC
SELECT * FROM match_chunks(
    ARRAY[0.1]::vector(768),
    'pmfby',
    NULL,
    3
);

-- 5. Check for orphans
SELECT COUNT(*) as orphan_count
FROM chunks c
LEFT JOIN documents d ON c.document_id = d.id
WHERE d.id IS NULL;
