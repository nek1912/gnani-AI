"""In-memory per-session response-language store.

Single-instance / demo use ONLY. This is NOT persistent and does not cover
multi-worker production deployments. The resolver (resolve_response_language)
is the sole owner of reading/writing session language; this module only
provides the storage primitive.

Ownership: entries are keyed by (user_id, session_id) so two authenticated
users sharing a session_id cannot see or overwrite each other's remembered
language. user_id=None preserves the legacy offline/test path.
"""

from threading import Lock

_session_language: dict[tuple[str | None, str], str] = {}
_lock = Lock()

DEFAULT_LANGUAGE = "en"


def _key(session_id: str, user_id: str | None) -> tuple[str | None, str]:
    return (user_id, session_id)


def get_session_language(session_id: str, user_id: str | None = None) -> str | None:
    with _lock:
        return _session_language.get(_key(session_id, user_id))


def set_session_language(
    session_id: str, language: str, user_id: str | None = None
) -> None:
    if not session_id:
        raise ValueError("session_id must be non-empty")
    if not language or not isinstance(language, str):
        raise ValueError("language must be a non-empty string")
    with _lock:
        _session_language[_key(session_id, user_id)] = language


def clear_session_language(session_id: str, user_id: str | None = None) -> None:
    with _lock:
        if user_id is None:
            # Legacy/test clear: drop every owner variant for this session.
            for k in [k for k in _session_language if k[1] == session_id]:
                _session_language.pop(k, None)
        else:
            _session_language.pop(_key(session_id, user_id), None)
