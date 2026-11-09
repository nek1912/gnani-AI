-- Phase 6: Effective date filtering
-- Adds effective_date parameter to match_chunks and match_chunks_lexical
-- so retrieval can filter by document effective date.
-- Does NOT modify existing data — only updates the RPC functions.

-- 1. Update match_chunks to accept effective_date filter
create or replace function match_chunks(
  query_embedding vector(768),
  match_domain text default null,
  match_state text default null,
  match_count int default 6,
  as_of_date date default null
)
returns table (
  chunk_id uuid,
  stable_chunk_id text,
  document_id uuid,
  title text,
  organization text,
  jurisdiction text,
  state text,
  domain text,
  source_url text,
  source_file text,
  page int,
  page_start int,
  page_end int,
  section text,
  subsection text,
  clause text,
  content text,
  similarity float
)
language sql stable as $$
  select c.id,
         c.stable_chunk_id,
         d.id,
         d.title,
         d.organization,
         d.jurisdiction,
         d.state,
         d.domain,
         d.source_url,
         c.source_file,
         c.page,
         c.page,
         c.page,
         c.section,
         c.metadata->>'subsection',
         c.metadata->>'clause',
         c.content,
         1 - (c.embedding <=> query_embedding) as similarity
  from chunks c
  join documents d on d.id = c.document_id
  where (match_domain is null or d.domain = match_domain)
    and (
      d.jurisdiction = 'central'
      or (match_state is not null and d.state = match_state)
    )
    and (as_of_date is null or d.effective_date is null or d.effective_date <= as_of_date)
  order by c.embedding <=> query_embedding
  limit least(match_count, 20);
$$;

-- 2. Update match_chunks_lexical to accept effective_date filter
create or replace function match_chunks_lexical(
  query_text text,
  match_domain text default null,
  match_state text default null,
  match_count int default 6,
  as_of_date date default null
)
returns table (
  chunk_id uuid,
  stable_chunk_id text,
  document_id uuid,
  title text,
  organization text,
  jurisdiction text,
  state text,
  domain text,
  source_url text,
  source_file text,
  page int,
  page_start int,
  page_end int,
  section text,
  subsection text,
  clause text,
  content text,
  similarity float
)
language sql stable as $$
  select c.id,
         c.stable_chunk_id,
         d.id,
         d.title,
         d.organization,
         d.jurisdiction,
         d.state,
         d.domain,
         d.source_url,
         c.source_file,
         c.page,
         c.page,
         c.page,
         c.section,
         c.metadata->>'subsection',
         c.metadata->>'clause',
         c.content,
         ts_rank_cd(c.content_fts, plainto_tsquery('english', unaccent(query_text))) as similarity
  from chunks c
  join documents d on d.id = c.document_id
  where c.content_fts @@ plainto_tsquery('english', unaccent(query_text))
    and (match_domain is null or d.domain = match_domain)
    and (
      d.jurisdiction = 'central'
      or (match_state is not null and d.state = match_state)
    )
    and (as_of_date is null or d.effective_date is null or d.effective_date <= as_of_date)
  order by ts_rank_cd(c.content_fts, plainto_tsquery('english', unaccent(query_text))) desc
  limit least(match_count, 20);
$$;
