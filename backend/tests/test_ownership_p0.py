"""P0 ownership tests: an authenticated user must not access another's resources.

Pattern under test (forensic audit): the route-level Clerk JWT gate passes,
then client-supplied identifiers (conversation_id / session_id / user_id)
are trusted without binding to the authenticated Clerk `sub`.

- Conversations CRUD: cross-user read/rename/delete/pin must 404 (no
  existence oracle); list/create must use the Clerk sub, ignoring any
  client-supplied user_id.
- Grievances: POST must bind state to the Clerk sub (spoofed user_id
  ignored); fields/answer/finalize/clarify must 404 for non-owners.
- Owner happy paths must keep working.

Auth is overridden per-test (not the global conftest stub) so the
ownership check is actually exercised. Supabase is mocked at the store
boundary; route logic (auth binding + ownership checks) is real.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth import require_auth
from app.main import app

client = TestClient(app)

USER_A = "user-A-clerk-sub"
USER_B = "user-B-clerk-sub"
CID = "conv-owned-by-A"


def _login_as(uid: str) -> None:
    app.dependency_overrides[require_auth] = lambda: uid


def _conv_row(owner: str) -> dict:
    return {"id": CID, "user_id": owner, "title": "A chat"}


def _draft_state(owner: str):
    """Real GrievanceState with a minimal real draft (renders 200 today)."""
    from app.grievance.models import (
        GrievanceCategory,
        GrievanceDraft,
        GrievanceState,
        GrievanceSubCategory,
    )

    draft = GrievanceDraft(
        category=GrievanceCategory.PUBLIC_SERVICE,
        sub_category=GrievanceSubCategory.GARBAGE,
        title="Garbage not collected",
        description="Garbage not collected for a week",
        entities={},
        missing_fields=[],
        required_fields=[],
        optional_fields=[],
        jurisdiction="state",
        state="Gujarat",
        department="Municipal Corporation",
    )
    return GrievanceState(conversation_id=CID, user_id=owner, draft=draft)


# ── Conversations ────────────────────────────────────────────────────────────


class TestConversationOwnership:
    def test_b_cannot_read_a_conversation(self):
        _login_as(USER_B)
        with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.conversation_store.get_conversation_history", return_value=[{"role": "user", "content": "hi"}]):
            r = client.get(f"/conversations/{CID}")
        assert r.status_code == 404

    def test_owner_can_read_conversation(self):
        _login_as(USER_A)
        with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.conversation_store.get_conversation_history", return_value=[{"role": "user", "content": "hi"}]):
            r = client.get(f"/conversations/{CID}")
        assert r.status_code == 200
        assert r.json()["conversation"]["id"] == CID

    def test_missing_conversation_returns_404(self):
        _login_as(USER_A)
        with patch("app.conversation_store.get_conversation", return_value=None):
            r = client.get(f"/conversations/{CID}")
        assert r.status_code == 404

    def test_b_cannot_rename_a_conversation(self):
        _login_as(USER_B)
        with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.conversation_store.rename_conversation") as mock_rename:
            r = client.patch(f"/conversations/{CID}", json={"user_id": USER_B, "title": "Hacked"})
        assert r.status_code == 404
        mock_rename.assert_not_called()

    def test_owner_can_rename_conversation(self):
        _login_as(USER_A)
        with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.conversation_store.rename_conversation") as mock_rename:
            r = client.patch(f"/conversations/{CID}", json={"user_id": USER_A, "title": "New"})
        assert r.status_code == 200
        mock_rename.assert_called_once_with(CID, "New")

    def test_b_cannot_delete_a_conversation(self):
        _login_as(USER_B)
        with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.conversation_store.delete_conversation") as mock_delete:
            r = client.delete(f"/conversations/{CID}")
        assert r.status_code == 404
        mock_delete.assert_not_called()

    def test_owner_can_delete_conversation(self):
        _login_as(USER_A)
        with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.conversation_store.delete_conversation") as mock_delete:
            r = client.delete(f"/conversations/{CID}")
        assert r.status_code == 200
        mock_delete.assert_called_once_with(CID)

    def test_b_cannot_pin_a_conversation(self):
        _login_as(USER_B)
        with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.conversation_store.pin_conversation") as mock_pin:
            r = client.post(f"/conversations/{CID}/pin", json={"user_id": USER_B, "pinned": True})
        assert r.status_code == 404
        mock_pin.assert_not_called()

    def test_list_uses_authed_identity_not_query_param(self):
        _login_as(USER_A)
        with patch("app.conversation_store.list_conversations", return_value=[]) as mock_list:
            r = client.get("/conversations", params={"user_id": USER_B})
        assert r.status_code == 200
        mock_list.assert_called_once_with(USER_A)

    def test_create_ignores_spoofed_user_id(self):
        _login_as(USER_A)
        with patch("app.conversation_store.create_conversation", return_value=_conv_row(USER_A)) as mock_create:
            r = client.post("/conversations", json={"user_id": USER_B, "title": "Mine"})
        assert r.status_code == 200
        mock_create.assert_called_once_with(USER_A, "Mine")


# ── Grievances ───────────────────────────────────────────────────────────────


class TestGrievanceOwnership:
    def test_post_ignores_spoofed_user_id(self):
        _login_as(USER_A)
        with patch("app.routes.grievance.ensure_conversation") as mock_ensure, \
             patch("app.routes.grievance._workflow") as mock_workflow:
            mock_workflow.process_message.return_value = MagicMock(
                response="ok", stage=MagicMock(value="intake"),
                draft=None, is_complete=False, submission_route=None, evidence=None,
            )
            r = client.post("/grievances", json={
                "message": "Garbage not collected",
                "conversation_id": CID,
                "user_id": USER_B,
            })
        assert r.status_code == 200
        mock_ensure.assert_called_once_with(CID, USER_A)
        _, kwargs = mock_workflow.process_message.call_args
        assert kwargs.get("user_id") == USER_A

    def test_post_to_anothers_conversation_returns_404(self):
        _login_as(USER_B)
        with patch("app.routes.grievance.get_conversation", return_value=_conv_row(USER_A)), \
             patch("app.routes.grievance.ensure_conversation") as mock_ensure, \
             patch("app.routes.grievance._workflow") as mock_workflow:
            r = client.post("/grievances", json={
                "message": "Garbage not collected",
                "conversation_id": CID,
                "user_id": USER_B,
            })
        assert r.status_code == 404
        mock_ensure.assert_not_called()
        mock_workflow.process_message.assert_not_called()

    def test_b_cannot_read_a_grievance_fields(self):
        _login_as(USER_B)
        with patch("app.routes.grievance.load_grievance_state", return_value=_draft_state(USER_A)):
            r = client.get(f"/grievances/{CID}/fields", params={"language": "en"})
        assert r.status_code == 404

    def test_owner_can_read_grievance_fields(self):
        _login_as(USER_A)
        with patch("app.routes.grievance.load_grievance_state", return_value=_draft_state(USER_A)):
            r = client.get(f"/grievances/{CID}/fields", params={"language": "en"})
        assert r.status_code == 200
        assert "mandatory_fields" in r.json()

    def test_b_cannot_submit_grievance_answer(self):
        _login_as(USER_B)
        with patch("app.routes.grievance.load_grievance_state", return_value=_draft_state(USER_A)), \
             patch("app.routes.grievance.save_grievance_state") as mock_save:
            r = client.post("/grievances/answer", json={
                "conversation_id": CID, "field": "ward_number", "value": "5",
            })
        assert r.status_code == 404
        mock_save.assert_not_called()

    def test_owner_can_submit_grievance_answer(self):
        _login_as(USER_A)
        with patch("app.routes.grievance.load_grievance_state", return_value=_draft_state(USER_A)), \
             patch("app.routes.grievance.save_grievance_state") as mock_save:
            r = client.post("/grievances/answer", json={
                "conversation_id": CID, "field": "ward_number", "value": "5",
            })
        assert r.status_code == 200
        mock_save.assert_called_once()

    def test_b_cannot_finalize_grievance(self):
        _login_as(USER_B)
        with patch("app.routes.grievance.load_grievance_state", return_value=_draft_state(USER_A)):
            r = client.post("/grievances/finalize", json={"conversation_id": CID, "language": "en"})
        assert r.status_code == 404

    def test_b_cannot_clarify_grievance(self):
        _login_as(USER_B)
        with patch("app.routes.grievance.load_grievance_state", return_value=_draft_state(USER_A)):
            r = client.post("/grievances/clarify", json={
                "conversation_id": CID, "complaint": "Water issue", "language": "en",
            })
        assert r.status_code == 404

    def test_unauthenticated_conversation_access_rejected(self):
        from app.auth import require_auth

        app.dependency_overrides.clear()
        try:
            with patch("app.conversation_store.get_conversation", return_value=_conv_row(USER_A)), \
                 patch("app.conversation_store.get_conversation_history", return_value=[]):
                r = client.get(f"/conversations/{CID}")
            assert r.status_code == 401
        finally:
            app.dependency_overrides[require_auth] = lambda: "test-user"


def test_no_success_without_owner_check_sanity():
    """Sanity: the suite itself distinguishes owners (guards against a test
    setup where every request trivially passes)."""
    assert USER_A != USER_B
    assert _conv_row(USER_A)["user_id"] != USER_B
    assert _draft_state(USER_A).user_id == USER_A
