-- Phase 2: Stable chunk identity
-- Adds stable chunk identity and preserves document-level source_file for compatibility.
-- The canonical PDF provenance field is chunks.source_file.
-- Does NOT modify existing embeddings, chunk content, or the2,188 chunk rows
-- beyond adding nullable columns and populating them.

-- 1. Add source_file to documents
alter table documents add column if not exists source_file text;

-- 2. Add stable_chunk_id to chunks
alter table chunks add column if not exists stable_chunk_id text;

-- 3. Backfill source_file from source_url (extract filename portion)
update documents d
set source_file = regexp_replace(d.source_url, '.*/', '');

-- 4. Backfill stable_chunk_id using deterministic format: {source_id}:p{page}:c{rank}
--    rank = ROW_NUMBER() within (document, page) ordered by chunk id for determinism.
update chunks c
set stable_chunk_id = sub.new_id
from (
  select c2.id as chunk_id,
         d.source_id || ':p' || c2.page || ':c' || (
           row_number() over (
             partition by c2.document_id, c2.page
             order by c2.id
           ) - 1
         ) as new_id
  from chunks c2
  join documents d on d.id = c2.document_id
) sub
where c.id = sub.chunk_id;

-- 5. Update match_chunks to return both IDs + source_file + page range + subsection + clause
create or replace function match_chunks(
  query_embedding vector(768),
  match_domain text default null,
  match_state text default null,
  match_count int default 6
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
  order by c.embedding <=> query_embedding
  limit least(match_count, 20);
$$;
