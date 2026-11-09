-- Sahayak API — Supabase schema
-- Run this in Supabase SQL Editor before ingesting corpus.

-- 1. pgvector extension
create extension if not exists vector;

-- 2. Documents table
create table if not exists documents (
  id            uuid primary key default gen_random_uuid(),
  source_id     text unique not null,
  title         text not null,
  organization  text,
  domain        text not null,
  jurisdiction  text not null default 'central',
  state         text,
  document_type text,
  source_url    text,
  effective_date date,
  verified_date date,
  created_at    timestamptz default now()
);

-- 3. Chunks table with 768-dim embedding
create table if not exists chunks (
  id              uuid primary key default gen_random_uuid(),
  document_id     uuid references documents(id) on delete cascade,
  stable_chunk_id text,
  page            int default 0,
  page_start      int default 0,
  page_end        int default 0,
  section         text default '',
  subsection      text,
  clause          text,
  content         text not null,
  embedding       vector(768),
  domain          text,
  jurisdiction    text,
  state           text,
  source_url      text,
  source_file     text,
  created_at      timestamptz default now()
);

-- 4. Indexes
create index if not exists idx_chunks_domain on chunks(domain);
create index if not exists idx_chunks_state on chunks(state);
create index if not exists idx_chunks_domain_state on chunks (domain, state) where state is not null;
create index if not exists idx_documents_domain on documents(domain);

-- HNSW index for vector search (only create once)
do $$
begin
  if not exists (
    select 1 from pg_indexes where indexname = 'idx_chunks_embedding_hnsw'
  ) then
    create index idx_chunks_embedding_hnsw on chunks
      using hnsw (embedding vector_cosine_ops) with (m = 16, ef_construction = 64);
  end if;
end
$$;

-- 5. match_chunks RPC function
create or replace function match_chunks(
  query_embedding vector(768),
  match_domain    text,
  match_state     text,
  match_count     int default 6,
  as_of_date      date default null
)
returns table (
  chunk_id       uuid,
  stable_chunk_id text,
  document_id    uuid,
  title          text,
  page           int,
  page_start     int,
  page_end       int,
  section        text,
  subsection     text,
  clause         text,
  content        text,
  similarity     float,
  source_url     text,
  source_file    text,
  domain         text,
  jurisdiction   text,
  state          text
)
language sql stable
set hnsw.ef_search = 40
as $$
  select c.id,
         coalesce(c.stable_chunk_id, c.id::text),
         c.document_id,
         d.title,
         c.page,
         coalesce(c.page_start, c.page),
         coalesce(c.page_end, c.page),
         coalesce(c.section, ''),
         c.subsection,
         c.clause,
         c.content,
         1 - (c.embedding <=> query_embedding) as similarity,
         coalesce(c.source_url, d.source_url, '') as source_url,
         c.source_file,
         coalesce(c.domain, d.domain, match_domain),
         coalesce(c.jurisdiction, d.jurisdiction, 'central'),
         c.state
  from chunks c
  join documents d on d.id = c.document_id
  where c.domain = match_domain
    and (match_state is null or c.state is null or c.state = match_state)
    and (as_of_date is null or d.effective_date is null or d.effective_date <= as_of_date)
  order by c.embedding <=> query_embedding
  limit match_count;
$$;

-- 6. Sessions table (for session_store.py)
-- user_id is the Clerk sub owner (nullable for legacy rows, which are
-- quarantined — never guessed). Messages inherit ownership via session.
create table if not exists sessions (
  session_id text primary key,
  user_id    text,
  state      jsonb default '{}',
  expires_at timestamptz,
  created_at timestamptz default now()
);
create index if not exists idx_sessions_user_id on sessions(user_id);

-- 7. Purge expired sessions RPC
create or replace function purge_expired_sessions()
returns void
language sql
as $$
  delete from sessions where expires_at < now();
$$;

-- 8. Users table (Clerk sync)
create table if not exists users (
  id            text primary key,
  email         text,
  full_name     text,
  preferred_language text default 'en',
  state         text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

-- Auto-update updated_at on users
create or replace function update_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists users_updated_at on users;
create trigger users_updated_at
  before update on users
  for each row
  execute function update_updated_at();
