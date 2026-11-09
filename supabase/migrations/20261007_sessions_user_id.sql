-- Chat session ownership (P0 follow-up): bind sessions to Clerk sub.
-- Minimal additive change: messages inherit ownership through sessions.
-- Legacy rows keep user_id NULL and are quarantined (inaccessible) rather
-- than guessed. No data deletion, no RLS (app-layer, like conversations).
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
