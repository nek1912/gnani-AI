-- =====================================================
-- CORRECTED SQL FOR VERIFICATION
-- =====================================================

-- 1. Test match_chunks with proper 768-dim vector
-- =====================================================
-- Create a proper 768-dimensional vector (all 0.1s)
SELECT * FROM match_chunks(
    (SELECT array_fill(0.1::real, ARRAY[768])::vector(768)),
    'pmfby',
    NULL,
    3
);

-- 2. Alternative: Use a simpler test with embedding from existing chunk
-- =====================================================
-- First get an existing embedding
DO $$
DECLARE
    existing_embedding vector(768);
BEGIN
    SELECT embedding INTO existing_embedding 
    FROM chunks 
    WHERE embedding IS NOT NULL 
    LIMIT 1;
    
    RAISE NOTICE 'Using existing embedding: %', left(existing_embedding::text, 100);
END $$;

-- 3. Test with proper vector construction
-- =====================================================
SELECT * FROM match_chunks(
    (SELECT embedding FROM chunks WHERE embedding IS NOT NULL LIMIT 1),
    'pmfby',
    NULL,
    3
);

-- 4. Quick verification (no RPC call)
-- =====================================================
SELECT 
    (SELECT COUNT(*) FROM documents) as documents,
    (SELECT COUNT(*) FROM chunks) as chunks;

-- 5. List all documents
SELECT source_id, title, domain, jurisdiction 
FROM documents 
ORDER BY source_id;

-- 6. Check embedding dimensions
SELECT 
    MIN(array_length(string_to_array(embedding::text, ','), 1)) as min_dim,
    MAX(array_length(string_to_array(embedding::text, ','), 1)) as max_dim
FROM chunks 
WHERE embedding IS NOT NULL;
