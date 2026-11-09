create or replace function purge_expired_sessions() returns void
language sql as $$ delete from sessions where expires_at < now(); $$;
