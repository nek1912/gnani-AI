-- Combined migration script for Supabase
-- Run this in the Supabase SQL editor (Dashboard > SQL Editor)

-- Enable pgvector extension
create extension if not exists vector;

-- Create documents table
create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  source_id text unique not null,
  title text not null,
  organization text not null,
  jurisdiction text not null check (jurisdiction in ('central','state')),
  state text,
  domain text not null,
  document_type text not null,
  source_url text not null,
  effective_date date,
  document_date date,
  verified_date date not null default current_date,
  document_hash text,
  source_type text not null default 'seed',
  created_at timestamptz not null default now()
);

-- Create chunks table
create table if not exists chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  page int not null default 0,
  section text not null default '',
  content text not null,
  embedding vector(768) not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- Create indexes
create index if not exists chunks_embedding_hnsw
  on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists chunks_document_idx on chunks(document_id);
create index if not exists documents_source_type_idx on documents(source_type);

-- Create sessions table
create table if not exists sessions (
  session_id uuid primary key,
  state jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '24 hours'
);

-- Create grievances table
create table if not exists grievances (
  id uuid primary key default gen_random_uuid(),
  reference text unique not null,
  status text not null default 'NEW'
    check (status in ('NEW','NEEDS_INFORMATION','CLASSIFIED','CREATED','IN_PROGRESS','RESOLVED')),
  category text,
  location text,
  language text not null default 'en',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Create feedback table
create table if not exists feedback (
  id uuid primary key default gen_random_uuid(),
  session_id uuid,
  message_id text,
  rating int check (rating between 1 and 5),
  note text,
  created_at timestamptz not null default now()
);

-- Create match_chunks RPC function
create or replace function match_chunks(
  query_embedding vector(768),
  match_domain text default null,
  match_state text default null,
  match_count int default 6
)
returns table (
  chunk_id uuid, document_id uuid, title text, organization text,
  jurisdiction text, state text, domain text, source_url text,
  page int, section text, content text, similarity float
)
language sql stable as $$
  select c.id, d.id, d.title, d.organization, d.jurisdiction, d.state, d.domain,
         d.source_url, c.page, c.section, c.content,
         1 - (c.embedding <=> query_embedding) as similarity
  from chunks c
  join documents d on d.id = c.document_id
  where (match_domain is null or d.domain = match_domain)
    and (
      d.jurisdiction = 'central'
      or (match_state is not null and d.state = match_state)
    )
  order by c.embedding <=> query_embedding
  limit least(match_count, 20);
$$;

-- Create purge_expired_sessions function
create or replace function purge_expired_sessions() returns void
language sql as $$ delete from sessions where expires_at < now(); $$;

-- Create atomic_replace_document function
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
