"""P1 session-state contamination reproduction (RED before fix).

Covers task cases A-I deterministically, no live services.
"""
from __future__ import annotations

import json
import threading
import uuid
from unittest.mock import MagicMock, patch

from app.resolve_response_language import resolve_and_remember
from app.services.lang_memory import (
    clear_session_language,
    get_session_language,
)


def _fresh(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _clear(*sids: str) -> None:
    for s in sids:
        try:
            clear_session_language(s)
        except Exception:
            pass


# A. Language contamination: different sessions, same process
def test_A_different_sessions_isolated():
    sA, sB = _fresh("sessA"), _fresh("sessB")
    try:
        rA = resolve_and_remember(sA, "explain in Gujarati please", None)
        assert rA == "gu", f"expected gu, got {rA}"
        rB = resolve_and_remember(sB, "what is the weather like today", None)
        # B must NOT inherit A's Gujarati
        assert rB == "en", f"RED-A: B inherited {rB} from A"
        assert get_session_language(sB) is None
    finally:
        _clear(sA, sB)


# B. Same session ID, different authenticated user — language must not leak
def test_B_same_session_different_user_isolated():
    sid = _fresh("sharedX")
    try:
        # User A establishes Gujarati on X (owner-namespaced)
        rA = resolve_and_remember(sid, "explain in Gujarati please", None, user_id="user-A")
        assert rA == "gu"
        # User B uses same X with neutral text — must NOT see A's gu
        rB = resolve_and_remember(sid, "what is the weather like today", None, user_id="user-B")
        assert rB == "en", f"RED-B: same-session cross-user leak: B got {rB}"
        # A still sees gu
        rA2 = resolve_and_remember(sid, "what is the weather like today", None, user_id="user-A")
        assert rA2 == "gu", f"B clobbered A's memory: A got {rA2}"
    finally:
        _clear(sid)


# B2. Same session, explicit overwrite: B must not clobber A's memory
def test_B2_same_session_write_isolation():
    sid = _fresh("sharedW")
    try:
        assert resolve_and_remember(sid, "explain in Gujarati please", None, user_id="user-A") == "gu"
        # B writes Hindi to same X — must land in B's namespace only
        assert resolve_and_remember(sid, "explain in Hindi please", None, user_id="user-B") == "hi"
        assert get_session_language(sid, user_id="user-A") == "gu"
        assert get_session_language(sid, user_id="user-B") == "hi"
    finally:
        _clear(sid)


# C. Different session IDs, same user — session state isolated
def test_C_same_user_different_sessions_isolated():
    sA, sB = _fresh("sessC1"), _fresh("sessC2")
    try:
        assert resolve_and_remember(sA, "explain in Gujarati please", None) == "gu"
        rB = resolve_and_remember(sB, "what is the weather like today", None)
        assert rB == "en", f"RED-C: session leak {rB}"
    finally:
        _clear(sA, sB)


# D. Sequential sessions: abandoned A must not transfer to B
def test_D_sequential_sessions_no_transfer():
    sA, sB = _fresh("sessD1"), _fresh("sessD2")
    try:
        assert resolve_and_remember(sA, "explain in Marathi please", None) == "mr"
        _clear(sA)  # abandon A
        rB = resolve_and_remember(sB, "what is the weather like today", None)
        assert rB == "en"
        assert get_session_language(sA) is None
    finally:
        _clear(sA, sB)


# E. Concurrent requests: same process, two sessions/users
def test_E_concurrent_sessions_isolated():
    sA, sB = _fresh("concA"), _fresh("concB")
    results: dict[str, str] = {}
    try:
        def _work(sid: str, text: str, key: str):
            results[key] = resolve_and_remember(sid, text, None)

        t1 = threading.Thread(target=_work, args=(sA, "explain in Gujarati please", "a"))
        t2 = threading.Thread(target=_work, args=(sB, "what is the weather like today", "b"))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert results.get("a") == "gu"
        assert results.get("b") == "en", f"RED-E: concurrent leak {results}"
    finally:
        _clear(sA, sB)


# E2. Concurrent same-session different-user writes must not share key
def test_E2_concurrent_same_session_cross_user():
    sid = _fresh("concX")
    try:
        resolve_and_remember(sid, "explain in Gujarati please", None, user_id="user-A")
        # Simulate B reading same X concurrently — must NOT see A's gu
        seen: dict[str, str] = {}

        def _read():
            seen["b"] = resolve_and_remember(
                sid, "what is the weather like today", None, user_id="user-B"
            )

        t = threading.Thread(target=_read)
        t.start()
        t.join(timeout=5)
        assert seen.get("b") == "en", f"RED-E2: cross-user concurrent leak {seen}"
    finally:
        _clear(sid)


# F. Voice -> text: voice session must not leak to different text session
def test_F_voice_to_text_different_sessions():
    v, t = _fresh("voice"), _fresh("text")
    try:
        assert resolve_and_remember(v, "explain in Gujarati please", None) == "gu"
        r = resolve_and_remember(t, "what is the weather like today", None)
        assert r == "en", f"RED-F: voice leaked to text {r}"
    finally:
        _clear(v, t)


# G. Text -> voice: reverse
def test_G_text_to_voice_different_sessions():
    tx, v = _fresh("text2"), _fresh("voice2")
    try:
        assert resolve_and_remember(tx, "explain in Hindi please", None) == "hi"
        r = resolve_and_remember(v, "what is the weather like today", None)
        assert r == "en", f"RED-G: text leaked to voice {r}"
    finally:
        _clear(tx, v)


# H. Grievance state: B must not inherit A's active workflow
def test_H_grievance_cross_user_isolated():
    from app.grievance.models import GrievanceStage, GrievanceState
    from app.grievance import workflow as wf_mod
    from app.grievance.draft_builder import GrievanceDraftBuilder

    conv = _fresh("convH")
    builder = GrievanceDraftBuilder()
    draftA = builder.build_initial_draft(
        "garbage piling up near my house in ward 5", conv, "user-A"
    )
    stateA = GrievanceState(conversation_id=conv, user_id="user-A")
    stateA.stage = GrievanceStage.FOLLOWUP
    stateA.draft = draftA
    stateA.current_field = (draftA.required_fields or [None])[0]
    blob = json.dumps(stateA.to_dict())

    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"state_json": blob}
    ]
    with patch.object(wf_mod, "get_supabase", return_value=sb):
        # Route-level gate correctly hides A's state from B
        from app.routes.chat import _has_active_grievance

        with patch("app.routes.chat.load_grievance_state", return_value=stateA):
            assert _has_active_grievance(conv, "user-A") is True
            assert _has_active_grievance(conv, "user-B") is False
        # Workflow-level: process_message as B must NOT continue A's state.
        # Current impl loads A's state regardless of caller, so B inherits
        # A's stage/fields — RED.
        from app.grievance.workflow import GrievanceWorkflow

        wf = GrievanceWorkflow()
        with patch.object(wf_mod, "save_grievance_state", lambda s: None):
            # Intake-like message that would continue FOLLOWUP if A's state leaks
            result = wf.process_message(
                user_message="ward 5",
                conversation_id=conv,
                user_id="user-B",
            )
            # If B inherited A's FOLLOWUP, the workflow advanced A's draft
            # instead of starting fresh INTAKE/CLASSIFICATION for B.
            assert result.stage in (GrievanceStage.INTAKE, GrievanceStage.CLASSIFICATION), (
                f"RED-H: B continued A's {result.stage} workflow"
            )


# I. Cached classifier context: same text shared is safe (pure function)
def test_I_classifier_cache_safe_to_share():
    import app.routes.chat as chat_mod

    chat_mod._cached_classification.cache_clear()
    try:
        c1 = chat_mod._cached_classification("what is pmfby premium?")
        c2 = chat_mod._cached_classification("what is pmfby premium?")
        assert c1.domain == c2.domain
        assert c1.intent == c2.intent
    finally:
        chat_mod._cached_classification.cache_clear()


# Legitimate behavior: same owner + same session persists
def test_legit_same_owner_same_session_persists():
    sid = _fresh("legit")
    try:
        assert resolve_and_remember(sid, "explain in Gujarati please", None, user_id="user-A") == "gu"
        assert resolve_and_remember(sid, "what is the weather like today", None, user_id="user-A") == "gu"
    finally:
        _clear(sid)


# Voice/text continuity when intentionally sharing session (same user, same id)
def test_legit_voice_text_shared_session_same_user():
    sid = _fresh("shared-legit")
    try:
        assert resolve_and_remember(sid, "explain in Hindi please", None, user_id="user-A") == "hi"
        # Same user, same session via voice then text: shared by design
        assert resolve_and_remember(sid, "what is the weather like today", None, user_id="user-A") == "hi"
    finally:
        _clear(sid)


def test_ensure_conversation_no_takeover():
    from app import conversation_store

    cid = _fresh("conv-ensure")
    with patch("app.conversation_store.get_conversation", return_value={"id": cid, "user_id": "user-A"}):
        with patch("app.conversation_store.get_supabase") as mock_sb:
            conversation_store.ensure_conversation(cid, "user-B")
            mock_sb.return_value.table.return_value.upsert.assert_not_called()
    with patch("app.conversation_store.get_conversation", return_value=None):
        with patch("app.conversation_store.get_supabase") as mock_sb:
            sb = MagicMock()
            mock_sb.return_value = sb
            conversation_store.ensure_conversation(cid, "user-B")
            sb.table.return_value.upsert.assert_called_once()


def test_save_grievance_state_no_overwrite():
    from app.grievance import workflow as wf_mod
    from app.grievance.models import GrievanceState

    conv = _fresh("conv-save")
    stateB = GrievanceState(conversation_id=conv, user_id="user-B")
    stateA = GrievanceState(conversation_id=conv, user_id="user-A")
    with patch.object(wf_mod, "load_grievance_state", return_value=stateA):
        with patch.object(wf_mod, "get_supabase") as mock_sb:
            wf_mod.save_grievance_state(stateB)
            mock_sb.return_value.table.return_value.upsert.assert_not_called()
    with patch.object(wf_mod, "load_grievance_state", return_value=None):
        with patch.object(wf_mod, "get_supabase") as mock_sb:
            sb = MagicMock()
            mock_sb.return_value = sb
            wf_mod.save_grievance_state(stateB)
            sb.table.return_value.upsert.assert_called_once()
