-- supabase/migrations/20260831_conversations_evidence_grievance.sql

-- Messages table (create if not exists — may already exist from prior setup)
CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  title TEXT DEFAULT 'New Chat',
  pinned BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);

-- Extend messages table with evidence and conversation link
ALTER TABLE messages ADD COLUMN IF NOT EXISTS evidence_json JSONB;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES conversations(id);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);

-- Evidence source cache
CREATE TABLE IF NOT EXISTS evidence_source_cache (
  cache_key TEXT PRIMARY KEY,
  chunk_id TEXT,
  source_url TEXT,
  source_title TEXT,
  source_type TEXT,
  source_text TEXT,
  locator_json JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Grievance states
CREATE TABLE IF NOT EXISTS grievance_states (
  conversation_id UUID PRIMARY KEY REFERENCES conversations(id),
  user_id TEXT NOT NULL,
  state_json JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_grievance_states_user_id ON grievance_states(user_id);
