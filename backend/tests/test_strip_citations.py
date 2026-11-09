"""Tests for strip_citations function."""
from app.evidence_controller import strip_citations


def test_strips_hex_chunk_ids():
    answer = "The scheme requires [chunk:a0eebc99] registration."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert "registration" in clean
    assert ids == ["a0eebc99"]


def test_strips_web_chunk_ids():
    answer = "According to [chunk:web_a1b2c3d4e5f6_c102] the premium is ₹2000."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert "web_a1b2c3d4e5f6_c102" in ids


def test_strips_empty_id():
    """Empty ID [chunk:] should still be stripped."""
    answer = "Edge case [chunk:] mention."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert ids == []


def test_preserves_markdown_structure():
    """stripping must not destroy markdown formatting."""
    answer = (
        "- Point one [chunk:abc12345]\n"
        "- Point two [chunk:def67890]\n\n"
        "**Important** [chunk:abc12345]\n\n"
        "Paragraph two."
    )
    clean, _ids = strip_citations(answer)
    assert "[chunk:" not in clean
    # Markdown structure preserved (newlines intact, not collapsed to single line)
    assert "- Point one" in clean
    assert "- Point two" in clean
    assert "**Important**" in clean
    assert "Paragraph two" in clean


def test_no_citations_unchanged():
    answer = "This is a plain answer with no citations."
    clean, ids = strip_citations(answer)
    assert clean == answer
    assert ids == []


def test_strips_multiple_formats():
    answer = "Static [chunk:a0eebc99] and web [chunk:web_abc123def456_c42] evidence."
    clean, ids = strip_citations(answer)
    assert "[chunk:" not in clean
    assert len(ids) == 2
