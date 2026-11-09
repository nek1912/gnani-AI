-- Add document_date (publication date, distinct from effective_date)
-- Existing rows get NULL (unknown), new rows must provide explicit value
ALTER TABLE documents ADD COLUMN document_date date;

-- Add source_type to distinguish PDF, HTML, seed sources
-- Existing rows get 'seed' (backward compatible with current seed ingestion)
ALTER TABLE documents ADD COLUMN source_type text not null default 'seed';

-- Add index for source_type filtering
CREATE INDEX IF NOT EXISTS documents_source_type_idx ON documents(source_type);