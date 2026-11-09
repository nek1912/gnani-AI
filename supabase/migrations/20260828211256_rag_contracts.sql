-- Migration 0005: Additive schema for RAG refactor contracts
-- Adds: embedding_profiles, corpus_versions, ingestion_runs, evaluation_runs
-- Enhances: documents (provenance, status, authority), chunks (provenance, hash)
-- All ADDITIVE — no drops, no destructive changes to existing tables

-- ============================================================
-- 1. Embedding Profiles
-- ============================================================
CREATE TABLE IF NOT EXISTS embedding_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL,
  model_id text NOT NULL,
  model_revision text,
  dimension int NOT NULL CHECK (dimension > 0),
  vector_dtype text NOT NULL DEFAULT 'float32',
  distance_metric text NOT NULL DEFAULT 'cosine',
  document_task text NOT NULL DEFAULT 'retrieval.passage',
  query_task text NOT NULL DEFAULT 'retrieval.query',
  normalization text NOT NULL DEFAULT 'l2',
  preprocessing_version text NOT NULL DEFAULT 'v1',
  fingerprint text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. Corpus Versions
-- ============================================================
CREATE TABLE IF NOT EXISTS corpus_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_tag text NOT NULL UNIQUE,
  embedding_profile_id uuid NOT NULL REFERENCES embedding_profiles(id),
  source_manifest_hash text,
  document_count int NOT NULL DEFAULT 0,
  chunk_count int NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'staging'
    CHECK (status IN ('staging', 'active', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz
);

-- ============================================================
-- 3. Ingestion Runs
-- ============================================================
CREATE TABLE IF NOT EXISTS ingestion_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  corpus_version_id uuid REFERENCES corpus_versions(id),
  source_id text NOT NULL,
  source_checksum text,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'extracting', 'embedding', 'staged', 'activated', 'failed', 'rolled_back')),
  chunks_inserted int NOT NULL DEFAULT 0,
  error_message text,
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS ingestion_runs_source_idx ON ingestion_runs(source_id);
CREATE INDEX IF NOT EXISTS ingestion_runs_status_idx ON ingestion_runs(status);

-- ============================================================
-- 4. Evaluation Runs
-- ============================================================
CREATE TABLE IF NOT EXISTS evaluation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_tag text,
  git_commit text NOT NULL,
  dependency_lock_hash text,
  migration_head text,
  corpus_version_id uuid REFERENCES corpus_versions(id),
  embedding_profile_id uuid REFERENCES embedding_profiles(id),
  raw_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'passed', 'failed')),
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

-- ============================================================
-- 5. Enhance documents table (additive columns)
-- ============================================================
ALTER TABLE documents ADD COLUMN IF NOT EXISTS version_id text NOT NULL DEFAULT 'v1';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS issuer text NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS official_domain text NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS authority_tier text NOT NULL DEFAULT 'unknown'
  CHECK (authority_tier IN ('primary', 'secondary', 'tertiary', 'unknown'));
ALTER TABLE documents ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active'
  CHECK (status IN ('draft', 'active', 'superseded', 'withdrawn', 'unknown'));
ALTER TABLE documents ADD COLUMN IF NOT EXISTS effective_end date;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS supersedes text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS superseded_by text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parser_profile text NOT NULL DEFAULT 'pdfplumber-v1';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS metadata_schema_version text NOT NULL DEFAULT 'v1';

-- Indexes for new filter dimensions
CREATE INDEX IF NOT EXISTS documents_status_idx ON documents(status);
CREATE INDEX IF NOT EXISTS documents_authority_idx ON documents(authority_tier);
CREATE INDEX IF NOT EXISTS documents_effective_idx ON documents(effective_date, effective_end);

-- ============================================================
-- 6. Enhance chunks table (additive columns)
-- ============================================================
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_id text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_start int;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_end int;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS heading_path text NOT NULL DEFAULT '';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_number text NOT NULL DEFAULT '';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS language text NOT NULL DEFAULT 'en';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS token_count int NOT NULL DEFAULT 0;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunker_version text NOT NULL DEFAULT 'v1';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS ordinal int NOT NULL DEFAULT 0;

-- Deterministic chunk ID uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS chunks_chunk_id_unique ON chunks(chunk_id) WHERE chunk_id IS NOT NULL;

-- ============================================================
-- 7. GIN index for lexical search (hybrid retrieval)
-- ============================================================
CREATE INDEX IF NOT EXISTS chunks_content_gin ON chunks USING gin(to_tsvector('english', content));

-- ============================================================
-- 8. Legacy ID mapping (preserve historical citation resolution)
-- ============================================================
CREATE TABLE IF NOT EXISTS legacy_chunk_mapping (
  old_id uuid PRIMARY KEY,
  new_chunk_id text NOT NULL,
  migrated_at timestamptz NOT NULL DEFAULT now()
);
