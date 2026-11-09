-- Phase 4: Hybrid retrieval support
-- Adds full-text search capability to chunks for hybrid vector+lexical retrieval.
-- Does NOT modify existing embeddings, chunk content, or the2,188 chunk rows
-- beyond adding a computed column and index.

-- 1. Add tsvector column for full-text search
alter table chunks add column if not exists content_fts tsvector;

-- 2. Populate from existing content (English + Hindi aware)
--    Uses 'english' configuration; Hindi tokens are stored as-is (no Hindi stemmer
--    in stock Postgres, but unaccent + simple tokenizer still helps).
update chunks set content_fts = to_tsvector('english', unaccent(content));

-- 3. Create GIN index for fast lexical lookup
create index if not exists chunks_content_fts_idx
  on chunks using gin (content_fts);

-- 4. Trigger to keep tsvector in sync on content update
create or replace function chunks_content_fts_trigger() returns trigger as $$
begin
  new.content_fts := to_tsvector('english', unaccent(new.content));
  return new;
end;
$$ language plpgsql;

drop trigger if exists chunks_content_fts_update on chunks;
create trigger chunks_content_fts_update
  before insert or update on chunks
  for each row execute function chunks_content_fts_trigger();

-- 5. Lexical search function for hybrid retrieval
--    Uses plainto_tsquery for safe, language-aware query parsing.
create or replace function match_chunks_lexical(
  query_text text,
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
         d.source_file,
         c.page,
         c.page,
         c.page,
         c.section,
         c.metadata->>'subsection',
         c.metadata->>'clause',
         c.content,
         -- Lexical similarity: ts_rank_cd with normalization
         ts_rank_cd(c.content_fts, plainto_tsquery('english', unaccent(query_text))) as similarity
  from chunks c
  join documents d on d.id = c.document_id
  where c.content_fts @@ plainto_tsquery('english', unaccent(query_text))
    and (match_domain is null or d.domain = match_domain)
    and (
      d.jurisdiction = 'central'
      or (match_state is not null and d.state = match_state)
    )
  order by ts_rank_cd(c.content_fts, plainto_tsquery('english', unaccent(query_text))) desc
  limit least(match_count, 20);
$$;
