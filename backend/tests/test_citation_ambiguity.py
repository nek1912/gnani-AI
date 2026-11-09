"""Focused tests for citation prefix ambiguity detection.

Verifies that verify_citation_ids handles three cases:
  1. Unique prefix match → resolve successfully
  2. Zero matches → invalid/unresolved
  3. Ambiguous prefix (multiple matches) → treated as invalid, NOT silently resolved
"""


from app.citation_verifier import (
    short_citation_id,
    verify_citation_ids,
    verify_citations,
)


# ---------------------------------------------------------------------------
# Static (UUID-prefix) tests
# ---------------------------------------------------------------------------

class TestStaticUniquePrefix:
    """Exactly one evidence item matches the 8-char prefix."""

    def test_unique_prefix_resolves(self):
        answer = "As stated in [chunk:a0eebc99] the policy applies."
        evidence = ["a0eebc99-1111-2222-3333-444444444444"]
        valid, invalid = verify_citation_ids(answer, evidence)
        assert valid == ["a0eebc99-1111-2222-3333-444444444444"]
        assert invalid == []

    def test_full_uuid_in_answer_not_captured(self):
        """Full UUID with hyphens is NOT a valid citation format.

        The regex requires consecutive hex chars followed by ]. Hyphens in UUIDs
        break the match, so [chunk:a0eebc99-1111-2222-...] is not captured.
        LLMs emit truncated [chunk:a0eebc99], not full UUIDs.
        """
        answer = "See [chunk:a0eebc99-1111-2222-3333-444444444444]."
        evidence = ["a0eebc99-1111-2222-3333-444444444444"]
        valid, invalid = verify_citation_ids(answer, evidence)
        # Full UUID format not captured → no valid citations, no invalid prefixes
        assert valid == []
        assert invalid == []


class TestStaticMissingPrefix:
    """Zero evidence items match the citation prefix."""

    def test_missing_prefix_invalid(self):
        answer = "Cited [chunk:deadbeef] nowhere."
        evidence = ["a0eebc99-1111-2222-3333-444444444444"]
        valid, invalid = verify_citation_ids(answer, evidence)
        assert valid == []
        assert invalid == ["deadbeef"]

    def test_completely_fabricated_id(self):
        answer = "Source [chunk:ffffffff] is fake."
        evidence = ["a0eebc99-1111-2222-3333-444444444444"]
        valid, invalid = verify_citation_ids(answer, evidence)
        assert valid == []
        assert invalid == ["ffffffff"]


class TestStaticAmbiguousPrefix:
    """Two evidence items share the same 8-char prefix."""

    def test_ambiguous_prefix_not_resolved(self):
        """The core invariant: ambiguity MUST NOT silently select the first match."""
        answer = "According to [chunk:a0eebc99] both sources agree."
        evidence = [
            "a0eebc99-1111-2222-3333-444444444444",
            "a0eebc99-2222-3333-4444-555555555555",
        ]
        valid, invalid = verify_citation_ids(answer, evidence)
        # Ambiguous prefix must NOT appear in valid
        assert "a0eebc99-1111-2222-3333-444444444444" not in valid
        assert "a0eebc99-2222-3333-4444-555555555555" not in valid
        # Ambiguous prefix must appear in invalid
        assert "a0eebc99" in invalid

    def test_ambiguous_prefix_one_valid_one_ambiguous(self):
        """One citation is unique, another is ambiguous — both reported correctly."""
        answer = "First [chunk:a0eebc99] and second [chunk:bbbbbbbb]."
        evidence = [
            "a0eebc99-1111-2222-3333-444444444444",
            "a0eebc99-2222-3333-4444-555555555555",
            "bbbbbbbb-aaaa-bbbb-cccc-dddddddddddd",
        ]
        valid, invalid = verify_citation_ids(answer, evidence)
        # Unique prefix resolves
        assert "bbbbbbbb-aaaa-bbbb-cccc-dddddddddddd" in valid
        # Ambiguous prefix is rejected
        assert "a0eebc99" in invalid
        assert len(valid) == 1


# ---------------------------------------------------------------------------
# Web-style prefix tests
# ---------------------------------------------------------------------------

class TestWebUniquePrefix:
    """Web chunk IDs with unique prefixes."""

    def test_unique_web_prefix_resolves(self):
        answer = "Per [chunk:web_a1b2c3d4e5f6_c0] the data shows."
        evidence = ["web_a1b2c3d4e5f6_c0"]
        valid, invalid = verify_citation_ids(answer, evidence)
        assert valid == ["web_a1b2c3d4e5f6_c0"]
        assert invalid == []

    def test_unique_web_prefix_truncated(self):
        """LLM emits truncated web prefix (8 chars)."""
        answer = "Source [chunk:web_a1b2c3d4] confirms."
        evidence = ["web_a1b2c3d4e5f6_c0"]
        valid, invalid = verify_citation_ids(answer, evidence)
        assert valid == ["web_a1b2c3d4e5f6_c0"]
        assert invalid == []


class TestWebMissingPrefix:
    """Web citation that doesn't match any evidence."""

    def test_missing_web_prefix_invalid(self):
        answer = "Cited [chunk:web_deadbeef_c99] but not retrieved."
        evidence = ["web_a1b2c3d4e5f6_c0"]
        valid, invalid = verify_citation_ids(answer, evidence)
        assert valid == []
        assert len(invalid) == 1


class TestWebAmbiguousPrefix:
    """Two web chunk IDs share the same prefix (realistic if many chunks from same URL)."""

    def test_ambiguous_web_prefix_not_resolved(self):
        answer = "Both [chunk:web_a1b2c3d4] sources agree."
        evidence = [
            "web_a1b2c3d4e5f6_c0",
            "web_a1b2c3d4e5f6_c1",
        ]
        valid, invalid = verify_citation_ids(answer, evidence)
        # Neither should be silently selected
        assert "web_a1b2c3d4e5f6_c0" not in valid
        assert "web_a1b2c3d4e5f6_c1" not in valid
        assert len(invalid) >= 1  # prefix rejected as ambiguous


# ---------------------------------------------------------------------------
# verify_citations integration: ambiguous → is_valid=False
# ---------------------------------------------------------------------------

class TestAmbiguousCitationIntegration:
    """Ambiguous prefixes must cause the full verification to fail."""

    def test_ambiguous_static_causes_failure(self):
        answer = "Policy [chunk:a0eebc99] states X."
        evidence = [
            "a0eebc99-1111-2222-3333-444444444444",
            "a0eebc99-2222-3333-4444-555555555555",
        ]
        result = verify_citations(answer, evidence)
        assert result.is_valid is False
        assert "a0eebc99" in result.invalid_prefixes

    def test_unique_static_causes_success(self):
        answer = "Policy [chunk:a0eebc99] states X."
        evidence = ["a0eebc99-1111-2222-3333-444444444444"]
        result = verify_citations(answer, evidence)
        assert result.is_valid is True
        assert len(result.valid_citations) == 1


# ---------------------------------------------------------------------------
# Full web-ID disambiguation (live B7: same-URL chunks share the 12-hex stem;
# the old 8-char truncation made every such marker ambiguous → abstain).
# ---------------------------------------------------------------------------

class TestShortCitationId:
    def test_web_id_kept_whole(self):
        assert short_citation_id("web_89df1181cdaf_c2701") == "web_89df1181cdaf_c2701"

    def test_uuid_id_truncated(self):
        assert short_citation_id("a0eebc99-1111-2222-3333-444444444444") == "a0eebc99"


class TestWebFullIdDisambiguation:
    """A full web marker resolves to exactly one chunk even with same-stem siblings."""

    EVIDENCE = [
        "web_89df1181cdaf_c2701",
        "web_89df1181cdaf_c2702",
    ]

    def test_full_web_id_resolves_despite_shared_stem(self):
        answer = "Register [chunk:web_89df1181cdaf_c2701] now."
        valid, invalid = verify_citation_ids(answer, self.EVIDENCE)
        assert valid == ["web_89df1181cdaf_c2701"]
        assert invalid == []

    def test_truncated_web_id_still_ambiguous(self):
        """Old-style truncated markers stay invalid (never silently resolved)."""
        answer = "Register [chunk:web_89df] now."
        valid, invalid = verify_citation_ids(answer, self.EVIDENCE)
        assert valid == []
        assert invalid == ["web_89df"]

    def test_full_web_id_passes_verification(self):
        answer = "Register [chunk:web_89df1181cdaf_c2701] now."
        result = verify_citations(answer, self.EVIDENCE)
        assert result.is_valid is True

    def test_hallucinated_full_web_id_still_fails(self):
        answer = "Register [chunk:web_deadbeefcafe_c99] now."
        result = verify_citations(answer, self.EVIDENCE)
        assert result.is_valid is False
