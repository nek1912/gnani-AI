import uuid
from unittest.mock import MagicMock, patch


@patch("app.session_store.get_supabase")
def test_save_message_inserts(mock_sb):
    from app.session_store import save_message
    sb = MagicMock()
    mock_sb.return_value = sb
    save_message(str(uuid.uuid4()), "user", "Hello")
    sb.table.assert_called_with("messages")
    sb.table().insert.assert_called_once()
    call_args = sb.table().insert.call_args[0][0]
    assert call_args["role"] == "user"
    assert call_args["content"] == "Hello"


@patch("app.session_store.get_supabase")
def test_get_history_returns_chronological(mock_sb):
    from app.session_store import get_history
    sb = MagicMock()
    mock_sb.return_value = sb
    # Simulate Supabase returning newest-first
    sb.table().select().eq().order().limit().execute.return_value.data = [
        {"role": "assistant", "content": "B"},
        {"role": "user", "content": "A"},
    ]
    result = get_history(str(uuid.uuid4()), limit=5)
    assert result == [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}]


@patch("app.session_store.get_supabase")
def test_get_history_returns_empty_on_error(mock_sb):
    from app.session_store import get_history
    sb = MagicMock()
    mock_sb.return_value = sb
    sb.table().select().eq().order().limit().execute.side_effect = Exception("table missing")
    result = get_history(str(uuid.uuid4()), limit=5)
    assert result == []


@patch("app.session_store.get_supabase")
def test_trim_messages_deletes_old(mock_sb):
    from app.session_store import trim_messages
    sb = MagicMock()
    mock_sb.return_value = sb
    sb.table().select().eq().order().range().execute.return_value.data = [
        {"id": "old-1"}, {"id": "old-2"}
    ]
    trim_messages(str(uuid.uuid4()), keep=50)
    sb.table().delete.assert_called_once()


@patch("app.session_store.get_supabase")
def test_get_session_falls_back_without_user_id_column(mock_sb):
    # Pre-migration schema: the modern select raises naming user_id;
    # get_session must retry legacy columns with user_id None.
    import app.session_store as store
    store._WARNED_LEGACY_SESSIONS_SCHEMA = True  # silence warn-once in tests
    from app.session_store import get_session
    sb = MagicMock()
    mock_sb.return_value = sb
    legacy_resp = MagicMock()
    legacy_resp.data = [{"session_id": "s1", "state": {"selected_state": None}}]
    sb.table().select().eq().limit().execute.side_effect = [
        Exception('column "user_id" does not exist'),
        legacy_resp,
    ]
    row = get_session("s1")
    assert row is not None
    assert row["session_id"] == "s1"
    assert row["user_id"] is None


@patch("app.session_store.get_supabase")
def test_get_session_none_on_generic_error(mock_sb):
    # Non-schema errors keep the legacy silent fail-open (None).
    import app.session_store as store
    store._WARNED_LEGACY_SESSIONS_SCHEMA = True
    from app.session_store import get_session
    sb = MagicMock()
    mock_sb.return_value = sb
    sb.table().select().eq().limit().execute.side_effect = Exception("connection refused")
    assert get_session("s1") is None


@patch("app.session_store.get_supabase")
def test_touch_session_upsert_falls_back_without_user_id_column(mock_sb):
    # Pre-migration schema: upsert with user_id fails naming user_id;
    # touch_session must retry without it so the session still persists.
    import app.session_store as store
    store._WARNED_LEGACY_SESSIONS_SCHEMA = True
    from app.session_store import touch_session
    sb = MagicMock()
    mock_sb.return_value = sb
    # get_session inside touch_session: no existing row
    # upsert: first (with user_id) raises, second (legacy) succeeds
    sb.table().select().eq().limit().execute.return_value.data = []
    sb.table().upsert.side_effect = [
        Exception('column "user_id" does not exist'),
        MagicMock(),
    ]
    touch_session("s1", None, "gu", user_id="user-1")
    assert sb.table().upsert.call_count == 2
    legacy_payload = sb.table().upsert.call_args[0][0]
    assert "user_id" not in legacy_payload
    assert legacy_payload["session_id"] == "s1"
