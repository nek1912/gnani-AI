"""Tests for the Azure Translator provider (Phase 10).

The provider must degrade gracefully: when unconfigured or on any HTTP/parse
error it returns the original text so retrieval still runs.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from app.providers.translator import AzureTranslator


def _settings_stub(key="k", endpoint="https://api.cognitive.microsofttranslator.com/", region="eastus"):
    return SimpleNamespace(
        azure_translator_key=key,
        azure_translator_endpoint=endpoint,
        azure_translator_region=region,
    )


def test_unconfigured_returns_original():
    s = SimpleNamespace(azure_translator_key="", azure_translator_endpoint="")
    t = AzureTranslator(s)
    assert t.configured is False
    assert t.translate("नमस्ते", to="en") == "नमस्ते"


def test_translate_success():
    s = _settings_stub()
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = [{"translations": [{"text": "Hello", "to": "en"}]}]
    with patch("app.providers.translator.get_settings", return_value=s), \
            patch("httpx.Client") as Client:
        Client.return_value.__enter__.return_value.post.return_value = fake_resp
        t = AzureTranslator(s)
        assert t.translate("नमस्ते", to="en", source="hi") == "Hello"


def test_translate_http_error_falls_back():
    s = _settings_stub()
    with patch("app.providers.translator.get_settings", return_value=s), \
            patch("httpx.Client") as Client:
        Client.return_value.__enter__.return_value.post.side_effect = httpx.HTTPError("boom")
        t = AzureTranslator(s)
        assert t.translate("नमस्ते", to="en") == "नमस्ते"


def test_empty_text_passthrough():
    s = _settings_stub()
    t = AzureTranslator(s)
    assert t.translate("   ", to="en") == "   "
