CREATE OR REPLACE FUNCTION atomic_replace_document(
  p_source_id text,
  p_doc_data jsonb,
  p_chunks_data jsonb  -- JSON array, not PostgreSQL array
)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_doc_id uuid;
  v_chunk jsonb;
BEGIN
  -- Validate inputs before deletion
  IF p_chunks_data IS NULL THEN
    RAISE EXCEPTION 'p_chunks_data must not be NULL';
  END IF;

  IF jsonb_typeof(p_chunks_data) != 'array' THEN
    RAISE EXCEPTION 'p_chunks_data must be a JSON array, got %', jsonb_typeof(p_chunks_data);
  END IF;

  IF jsonb_array_length(p_chunks_data) = 0 THEN
    RAISE EXCEPTION 'p_chunks_data must contain at least one chunk';
  END IF;

  -- Delete old document (cascades to chunks)
  DELETE FROM documents WHERE source_id = p_source_id;
  
  -- Insert new document
  INSERT INTO documents (source_id, title, organization, jurisdiction, state, 
                         domain, document_type, source_url, effective_date, 
                         document_date, verified_date, source_type)
  VALUES (
    p_source_id,
    p_doc_data->>'title',
    p_doc_data->>'organization',
    p_doc_data->>'jurisdiction',
    p_doc_data->>'state',
    p_doc_data->>'domain',
    p_doc_data->>'document_type',
    p_doc_data->>'source_url',
    (p_doc_data->>'effective_date')::date,
    (p_doc_data->>'document_date')::date,
    (p_doc_data->>'verified_date')::date,
    p_doc_data->>'source_type'
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
      (v_chunk->>'page')::int,
      v_chunk->>'section',
      v_chunk->>'content',
      (v_chunk->>'embedding')::vector(768)
    );
  END LOOP;
  
  RETURN v_doc_id;
END;
$$;