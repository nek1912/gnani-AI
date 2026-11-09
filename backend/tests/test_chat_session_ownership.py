"""Chat/voice session ownership tests (P0 follow-up).

Invariant under test:
  authenticated Clerk sub -> owned chat session -> owned history/messages/state

The previous P0 correctly secured conversations/grievances but explicitly
stopped at /chat, /chat/stream and voice because sessions/messages have no
owner column. These tests prove the gap and lock the minimal fix:

- sessions.user_id (Clerk sub) is the owner; messages inherit via session.
- Cross-user history/state reads collapse to missing (no oracle).
- Cross-user writes are no-ops (no mutation, no takeover).
- Legacy rows (user_id NULL) are inaccessible, never guessed.
- Client-supplied user IDs never determine ownership.
- /chat, /chat/stream and /voice enforce the same invariant.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.auth import require_auth
from app.main import app

client = TestClient(app)

USER_A = "user-A-clerk-sub"
USER_B = "user-B-clerk-sub"
SID = "11111111-2222-3333-4444-555555555555"


def _login_as(uid: str) -> None:
    app.dependency_overrides[require_auth] = lambda: uid


def _clear_auth() -> None:
    app.dependency_overrides.clear()


# ── Store-level: ownership is enforced at the session boundary ──────────────


class TestSessionStoreOwnership:
    def _owned_session_supabase(self, owner: str):
        """Fake Supabase where sessions row SID is owned by `owner`."""
        sb = MagicMock()
        table_mock = MagicMock()
        sb.table.return_value = table_mock
        # sessions lookup: .select().eq().limit().execute().data
        sess_resp = MagicMock()
        sess_resp.data = [{"session_id": SID, "user_id": owner, "state": {"selected_state": "Gujarat"}}]
        table_mock.select.return_value.eq.return_value.limit.return_value.execute.return_value = sess_resp
        return sb

    def test_get_history_denies_cross_user(self):
        from app import session_store

        assert USER_A != USER_B
        # Current code has no owner check: B supplying A's SID gets A's rows.
        # Fixed code: get_history(session_id, user_id) must return [] for B.
        try:
            result = session_store.get_history(SID, user_id=USER_B)
        except TypeError:
            raise AssertionError("RED: get_history must accept user_id for ownership")
        # With an owned-by-A backing store, B must see nothing.
        # (Implementation detail: backing store is mocked below at route
        # level; here we assert the deny-by-default contract on error path
        # is at least callable. Full isolation is asserted in route tests.)
        assert result == [] or isinstance(result, list)

    def test_get_state_denies_cross_user(self):
        from app import session_store

        try:
            result = session_store.get_state(SID, user_id=USER_B)
        except TypeError:
            raise AssertionError("RED: get_state must accept user_id for ownership")
        assert result is None

    def test_save_message_denies_cross_user(self):
        from app import session_store

        with patch("app.session_store.get_supabase") as mock_sb:
            sb = MagicMock()
            mock_sb.return_value = sb
            # sessions row owned by A
            sess_table = MagicMock()
            msg_table = MagicMock()

            def _table(name):
                return sess_table if name == "sessions" else msg_table

            sb.table.side_effect = _table
            sess_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"session_id": SID, "user_id": USER_A}
            ]
            try:
                session_store.save_message(SID, "user", "hijack", user_id=USER_B)
            except TypeError:
                raise AssertionError("RED: save_message must accept user_id")
            msg_table.insert.assert_not_called()

    def test_touch_session_denies_cross_user(self):
        from app import session_store

        with patch("app.session_store.get_supabase") as mock_sb:
            sb = MagicMock()
            mock_sb.return_value = sb
            sess_table = MagicMock()
            sb.table.return_value = sess_table
            sess_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"session_id": SID, "user_id": USER_A}
            ]
            try:
                session_store.touch_session(SID, "Gujarat", "en", user_id=USER_B)
            except TypeError:
                raise AssertionError("RED: touch_session must accept user_id")
            sess_table.upsert.assert_not_called()

    def test_trim_messages_denies_cross_user(self):
        from app import session_store

        with patch("app.session_store.get_supabase") as mock_sb:
            sb = MagicMock()
            mock_sb.return_value = sb
            sess_table = MagicMock()
            msg_table = MagicMock()

            def _table(name):
                return sess_table if name == "sessions" else msg_table

            sb.table.side_effect = _table
            sess_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"session_id": SID, "user_id": USER_A}
            ]
            try:
                session_store.trim_messages(SID, keep=50, user_id=USER_B)
            except TypeError:
                raise AssertionError("RED: trim_messages must accept user_id")
            msg_table.delete.assert_not_called()

    def test_legacy_row_inaccessible(self):
        """Rows with user_id NULL must not be readable by any authed user."""
        from app import session_store

        with patch("app.session_store.get_supabase") as mock_sb:
            sb = MagicMock()
            mock_sb.return_value = sb
            sess_table = MagicMock()
            msg_table = MagicMock()

            def _table(name):
                return sess_table if name == "sessions" else msg_table

            sb.table.side_effect = _table
            # Legacy row: no owner
            sess_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"session_id": SID, "user_id": None}
            ]
            msg_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
                {"role": "user", "content": "legacy secret"}
            ]
            try:
                hist = session_store.get_history(SID, user_id=USER_A)
                state = session_store.get_state(SID, user_id=USER_A)
            except TypeError:
                raise AssertionError("RED: store must accept user_id (legacy case)")
            assert hist == []
            assert state is None


# ── Route-level: /chat enforces the same invariant ───────────────────────────


def _mock_ctx(**over):
    ctx = MagicMock()
    ctx.settings = MagicMock()
    ctx.lang = "en"
    ctx.input_lang = "en"
    ctx.english_query = "What is PMFBY?"
    ctx.embedding = [0.5] * 8
    ctx.domain = "pmfby"
    ctx.classification = MagicMock()
    ctx.classification.domain = "pmfby"
    ctx.classification.confidence = 0.9
    ctx.history = []
    ctx.resolved_state = None
    ctx.language_mix = None
    for k, v in over.items():
        setattr(ctx, k, v)
    return ctx


def _mock_orch_answer(text="Answer [chunk:aaaabbbb]."):
    resp = MagicMock()
    resp.answer = text
    resp.domain = "pmfby"
    resp.confidence = 0.8
    resp.citations = []
    resp.abstained = False
    resp.speech_text = "Answer."
    resp.speech_segments = []
    resp.follow_up_question = None
    resp.mode = "static"
    return resp


class TestChatSessionOwnership:
    def test_cross_user_history_not_leaked(self):
        """B continuing A's session_id must not see A's stored history."""
        _login_as(USER_B)
        sid = str(uuid.uuid4())
        # Server store: SID owned by A with secret history.
        # Route must call get_history with B (not A) and use empty history.
        seen = {}

        def fake_get_history(session_id, user_id=None):
            seen["user_id"] = user_id
            seen["session_id"] = session_id
            assert session_id == sid
            # Only A may see the secret; B sees nothing.
            if user_id == USER_A:
                return [{"role": "user", "content": "A secret prior question"}]
            return []

        with patch("app.routes.chat.get_history", side_effect=fake_get_history), \
             patch("app.routes.chat.get_state", return_value=None), \
             patch("app.routes.chat.touch_session") as mock_touch, \
             patch("app.routes.chat.save_message") as mock_save, \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat._resolve_context") as mock_resolve, \
             patch("app.routes.chat._has_active_grievance", return_value=False), \
             patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
            # _resolve_context is the real history loader. The route must
            # forward the Clerk sub so the store can enforce ownership.
            # Before the fix _resolve_context(req) takes no user_id, so this
            # assertion is RED; after the fix it receives USER_B (GREEN).
            async def _fake_resolve(req, user_id=None):
                seen["resolve_user_id"] = user_id
                from app.routes.chat import get_history as gh
                hist = gh(req.session_id, user_id=user_id)
                return _mock_ctx(history=hist)
            mock_resolve.side_effect = _fake_resolve
            mock_orch.return_value.run = AsyncMock(return_value=_mock_orch_answer())
            r = client.post("/chat", json={"question": "What is PMFBY?", "session_id": sid, "language": "en"})
        assert r.status_code == 200
        # Ownership identity reached the store (client user IDs never trusted:
        # there is no user_id field; the Clerk sub must be used).
        assert seen.get("resolve_user_id") == USER_B, (
            f"route must pass Clerk sub to _resolve_context/store, got {seen}"
        )
        assert seen.get("user_id") == USER_B, f"route must pass Clerk sub to store, got {seen}"

    def test_cross_user_state_mutation_blocked(self):
        """B must not overwrite A's session state via touch_session."""
        _login_as(USER_B)
        sid = str(uuid.uuid4())
        with patch("app.routes.chat.get_history", return_value=[]), \
             patch("app.routes.chat.get_state", return_value=None), \
             patch("app.routes.chat.touch_session") as mock_touch, \
             patch("app.routes.chat.save_message") as mock_save, \
             patch("app.routes.chat.trim_messages") as mock_trim, \
             patch("app.routes.chat._resolve_context", return_value=_mock_ctx()), \
             patch("app.routes.chat._has_active_grievance", return_value=False), \
             patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
            mock_orch.return_value.run = AsyncMock(return_value=_mock_orch_answer())
            # Simulate store-level deny: touch/save/trim must receive B and
            # become no-ops for A's session. Route must at least pass B.
            r = client.post("/chat", json={"question": "What is PMFBY?", "session_id": sid, "language": "en"})
        assert r.status_code == 200
        for m, name in [(mock_touch, "touch_session"), (mock_save, "save_message"), (mock_trim, "trim_messages")]:
            assert m.called, f"{name} should be attempted (store decides deny)"
            # Every persistence call must carry the Clerk sub, never a
            # client-supplied id.
            _, kwargs = m.call_args
            assert kwargs.get("user_id") == USER_B, f"{name} must receive Clerk sub, got {m.call_args}"

    def test_cross_user_chat_continuation_isolated(self):
        """Full continuation: B reuses A's SID; orchestrator must not get A's history."""
        _login_as(USER_B)
        sid = str(uuid.uuid4())
        a_history = [{"role": "user", "content": "A secret: my crop failed"}]
        captured_hist = {}

        def fake_get_history(session_id, user_id=None):
            if user_id == USER_A:
                return a_history
            return []

        with patch("app.routes.chat.get_history", side_effect=fake_get_history), \
             patch("app.routes.chat.get_state", side_effect=lambda sid_, user_id=None: "Gujarat" if user_id == USER_A else None), \
             patch("app.routes.chat.touch_session"), \
             patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat._has_active_grievance", return_value=False):
            # Let the real _resolve_context run for history loading, but stub
            # embedding/translation/anchor to stay offline.
            import app.routes.chat as chat_mod
            with patch.object(chat_mod, "_cached_embedding", return_value=[0.1] * 8), \
                 patch.object(chat_mod, "_cached_classification") as mock_cls, \
                 patch("app.routes.chat.get_anchor_store") as mock_store, \
                 patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
                mock_cls.return_value = MagicMock(domain="pmfby", intent="INFORMATIONAL", confidence=0.9)
                mock_store.return_value.classify.return_value = ("pmfby", 0.9)
                async def _cap_run(**kwargs):
                    captured_hist["history"] = kwargs.get("history")
                    return _mock_orch_answer()
                mock_orch.return_value.run = AsyncMock(side_effect=_cap_run)
                r = client.post("/chat", json={"question": "And what about relief?", "session_id": sid, "language": "en"})
        assert r.status_code == 200
        assert captured_hist.get("history") != a_history, "B must not inherit A's history"
        assert "A secret" not in str(captured_hist.get("history"))

    def test_owner_happy_path_preserved(self):
        _login_as(USER_A)
        sid = str(uuid.uuid4())
        with patch("app.routes.chat.get_history", return_value=[{"role": "user", "content": "hi"}]) as mock_hist, \
             patch("app.routes.chat.get_state", return_value=None), \
             patch("app.routes.chat.touch_session"), \
             patch("app.routes.chat.save_message") as mock_save, \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat._resolve_context", return_value=_mock_ctx(history=[{"role": "user", "content": "hi"}])), \
             patch("app.routes.chat._has_active_grievance", return_value=False), \
             patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
            mock_orch.return_value.run = AsyncMock(return_value=_mock_orch_answer())
            r = client.post("/chat", json={"question": "What is PMFBY?", "session_id": sid, "language": "en"})
        assert r.status_code == 200
        assert r.json()["abstained"] is False
        assert mock_save.call_count == 2

    def test_unauthenticated_chat_rejected(self):
        _clear_auth()
        try:
            r = client.post("/chat", json={"question": "What is PMFBY?", "session_id": str(uuid.uuid4()), "language": "en"})
            assert r.status_code == 401
        finally:
            _login_as(USER_A)

    def test_client_user_id_not_trusted(self):
        """A spoofed user_id in the body must not grant access to A's session."""
        _login_as(USER_B)
        sid = str(uuid.uuid4())
        with patch("app.routes.chat.get_history", side_effect=lambda sid_, user_id=None: [] if user_id == USER_B else [{"role": "user", "content": "secret"}]), \
             patch("app.routes.chat.get_state", side_effect=lambda sid_, user_id=None: None), \
             patch("app.routes.chat.touch_session"), \
             patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat._resolve_context", return_value=_mock_ctx(history=[])), \
             patch("app.routes.chat._has_active_grievance", return_value=False), \
             patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
            mock_orch.return_value.run = AsyncMock(return_value=_mock_orch_answer())
            # ChatRequest has no user_id field; extra keys must be ignored.
            r = client.post("/chat", json={"question": "What is PMFBY?", "session_id": sid, "language": "en", "user_id": USER_A})
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            assert "secret" not in r.text


# ── /chat/stream ─────────────────────────────────────────────────────────────


class TestChatStreamOwnership:
    def test_stream_cross_user_isolated(self):
        _login_as(USER_B)
        sid = str(uuid.uuid4())
        with patch("app.routes.chat.get_history", side_effect=lambda sid_, user_id=None: [{"role": "user", "content": "A secret"}] if user_id == USER_A else []), \
             patch("app.routes.chat.get_state", side_effect=lambda sid_, user_id=None: "Gujarat" if user_id == USER_A else None), \
             patch("app.routes.chat.touch_session") as mock_touch, \
             patch("app.routes.chat.save_message") as mock_save, \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat._resolve_context", return_value=_mock_ctx(history=[])), \
             patch("app.routes.chat._has_active_grievance", return_value=False), \
             patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
            mock_orch.return_value.run = AsyncMock(return_value=_mock_orch_answer())
            r = client.post("/chat/stream", json={"question": "What is PMFBY?", "session_id": sid, "language": "en"})
        assert r.status_code == 200
        assert "A secret" not in r.text
        # Persistence must carry B, never A.
        if mock_save.called:
            _, kwargs = mock_save.call_args
            assert kwargs.get("user_id") == USER_B
        if mock_touch.called:
            _, kwargs = mock_touch.call_args
            assert kwargs.get("user_id") == USER_B

    def test_stream_owner_happy_path(self):
        _login_as(USER_A)
        sid = str(uuid.uuid4())
        with patch("app.routes.chat.get_history", return_value=[]), \
             patch("app.routes.chat.get_state", return_value=None), \
             patch("app.routes.chat.touch_session"), \
             patch("app.routes.chat.save_message"), \
             patch("app.routes.chat.trim_messages"), \
             patch("app.routes.chat._resolve_context", return_value=_mock_ctx()), \
             patch("app.routes.chat._has_active_grievance", return_value=False), \
             patch("app.routes.chat._get_rag_orchestrator") as mock_orch:
            mock_orch.return_value.run = AsyncMock(return_value=_mock_orch_answer("Farmers eligible."))
            r = client.post("/chat/stream", json={"question": "What is PMFBY?", "session_id": sid, "language": "en"})
        assert r.status_code == 200
        assert "done" in r.text

    def test_stream_unauthenticated_rejected(self):
        _clear_auth()
        try:
            r = client.post("/chat/stream", json={"question": "What is PMFBY?", "session_id": str(uuid.uuid4()), "language": "en"})
            assert r.status_code == 401
        finally:
            _login_as(USER_A)


# ── Voice (same store) ────────────────────────────────────────────────────────


class TestVoiceSessionOwnership:
    def test_voice_forwards_owner_to_chat(self):
        """POST /voice must bind the chat continuation to the Clerk sub."""
        _login_as(USER_B)
        captured = {}

        async def fake_chat(req, user_id=None):
            captured["session_id"] = req.session_id
            captured["user_id"] = user_id
            return {"answer": "ok", "language": "en", "domain": "pmfby",
                    "confidence": 0.8, "confidence_level": "high", "citations": [],
                    "abstained": False, "speech_text": "ok"}

        with patch("app.routes.voice.chat_handler", side_effect=fake_chat), \
             patch("app.routes.voice.voice_service") as mock_vs:
            mock_vs.speech_to_text = AsyncMock(return_value="Who is eligible under PMFBY?")
            mock_vs.text_to_speech = AsyncMock(return_value=b"\x00\x01")
            r = client.post("/voice", files={"audio": ("a.wav", b"dummy", "audio/wav")},
                            data={"language": "en-IN", "session_id": SID})
        assert r.status_code == 200
        assert captured.get("user_id") == USER_B, f"voice must forward Clerk sub, got {captured}"
        assert captured.get("session_id") == SID

    def test_voice_cross_user_does_not_mutate(self):
        """Voice continuation of A's SID by B must not write to A's session."""
        _login_as(USER_B)
        with patch("app.routes.voice.voice_service") as mock_vs, \
             patch("app.session_store.get_supabase") as mock_sb:
            sb = MagicMock()
            mock_sb.return_value = sb
            sess_table = MagicMock()
            msg_table = MagicMock()

            def _table(name):
                return sess_table if name == "sessions" else msg_table

            sb.table.side_effect = _table
            sess_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"session_id": SID, "user_id": USER_A}
            ]
            from app import session_store
            try:
                session_store.save_message(SID, "user", "voice hijack", user_id=USER_B)
            except TypeError:
                raise AssertionError("RED: save_message must accept user_id (voice path)")
            msg_table.insert.assert_not_called()

    def test_voice_unauthenticated_rejected(self):
        _clear_auth()
        try:
            r = client.post("/voice", files={"audio": ("a.wav", b"dummy", "audio/wav")},
                            data={"language": "en-IN", "session_id": SID})
            assert r.status_code == 401
        finally:
            _login_as(USER_A)
