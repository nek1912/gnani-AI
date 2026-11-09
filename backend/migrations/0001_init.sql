create extension if not exists vector;

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

create index if not exists chunks_embedding_hnsw
  on chunks using hnsw (embedding vector_cosine_ops);
create index if not exists chunks_document_idx on chunks(document_id);

create table if not exists sessions (
  session_id uuid primary key,
  state jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '24 hours'
);

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

create table if not exists feedback (
  id uuid primary key default gen_random_uuid(),
  session_id uuid,
  message_id text,
  rating int check (rating between 1 and 5),
  note text,
  created_at timestamptz not null default now()
);

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
