"""Tests for QueryRequirementClassifier and EvidenceController."""


from app.evidence_controller import QueryRequirementClassifier


classifier = QueryRequirementClassifier()


def test_general_query_no_year():
    qr = classifier.classify("What are PMFBY rules?", "en")
    assert qr.temporal_scope == "general"
    assert qr.requires_dynamic is False


def test_current_year_query():
    qr = classifier.classify("PMFBY premium 2026", "en")
    assert qr.temporal_scope == "2026"
    assert qr.requires_dynamic is True


def test_haalmaa_query():
    qr = classifier.classify("હાલમાં PMFBY notified crops", "gu")
    assert qr.temporal_scope == "current"
    assert qr.requires_dynamic is True


def test_historical_query():
    qr = classifier.classify("2023 PMFBY guidelines", "en")
    assert qr.temporal_scope == "historical"
    assert qr.requires_dynamic is False


def test_unspecified_with_district():
    qr = classifier.classify("Surat district crops", "en")
    assert qr.geographic_scope == "district"
    assert qr.requires_dynamic is True


def test_state_query():
    qr = classifier.classify("Gujarat PMFBY scheme", "en")
    assert qr.geographic_scope == "state"
    assert qr.requires_dynamic is False  # state-level doesn't always need dynamic


def test_no_geographic():
    qr = classifier.classify("What is PMFBY?", "en")
    assert qr.geographic_scope == "none"
    assert qr.requires_dynamic is False


# ---------------------------------------------------------------------------
# EvidenceController tests
# ---------------------------------------------------------------------------

from app.contracts import RAGResult, EvidenceChunk, QueryRequirements, ConfidenceBand


def test_build_bundle_both_available():
    from app.evidence_controller import EvidenceController
    controller = EvidenceController()

    static = RAGResult(
        chunks=[
            EvidenceChunk(chunk_id="static1", content="PMFBY rules", source_type="static", title="Guidelines"),
        ],
        abstained=False, band=ConfidenceBand.HIGH, domain="pmfby",
    )
    web = RAGResult(
        chunks=[
            EvidenceChunk(chunk_id="web1", content="Current premium 2%", source_type="web", title="Current data"),
        ],
        abstained=False, band=ConfidenceBand.MEDIUM, domain="pmfby",
    )
    reqs = QueryRequirements(temporal_scope="current", geographic_scope="state", required_specificity="state", requires_dynamic=True)

    bundle = controller.build_bundle(static, web, reqs, "PMFBY premium")
    assert bundle.static.available is True
    assert bundle.dynamic.available is True
    assert len(bundle.static.chunks) == 1
    assert len(bundle.dynamic.chunks) == 1


def test_build_bundle_dynamic_absent():
    from app.evidence_controller import EvidenceController
    controller = EvidenceController()

    static = RAGResult(
        chunks=[EvidenceChunk(chunk_id="s1", content="rules", source_type="static", title="t")],
        abstained=False, band=ConfidenceBand.HIGH, domain="pmfby",
    )
    web = RAGResult(chunks=[], abstained=True, band=ConfidenceBand.LOW, domain="pmfby")
    reqs = QueryRequirements(temporal_scope="current", geographic_scope="district", required_specificity="district", requires_dynamic=True)

    bundle = controller.build_bundle(static, web, reqs, "current crops in Surat")
    assert bundle.static.available is True
    assert bundle.dynamic.available is False
    assert bundle.dynamic.reason is not None


def test_build_curated_prompt_separates_evidence():
    from app.contracts import EvidenceBundle, StaticEvidence, DynamicEvidence
    from app.evidence_controller import EvidenceController
    controller = EvidenceController()

    bundle = EvidenceBundle(
        static=StaticEvidence(
            available=True,
            chunks=[EvidenceChunk(chunk_id="s1", content="PMFBY is a scheme", source_type="static", title="Guidelines")],
            summary="Policy rules",
        ),
        dynamic=DynamicEvidence(available=False, chunks=[], reason="No web results"),
        query_requirements=QueryRequirements(temporal_scope="current", geographic_scope="district", required_specificity="district", requires_dynamic=True),
        query="current crops",
    )

    system, user = controller.build_curated_prompt(bundle, "current crops in Surat", None, "gu")
    assert "[STATIC]" in user
    assert "DYNAMIC EVIDENCE" in user
    assert "rural areas" in system


# ---------------------------------------------------------------------------
# Prompt focus: guidance must never inject evidence-absent offices/schemes
# (live farmer-registry answer contained an unsupported "PACS office" claim
# because rules 8/9 named specific offices unconditionally).
# ---------------------------------------------------------------------------


def _curated_prompts():
    from app.contracts import EvidenceBundle, StaticEvidence, DynamicEvidence
    from app.evidence_controller import EvidenceController
    controller = EvidenceController()
    bundle = EvidenceBundle(
        static=StaticEvidence(available=False, chunks=[], summary="none"),
        dynamic=DynamicEvidence(available=False, chunks=[], reason="No web results"),
        query_requirements=QueryRequirements(temporal_scope="current", geographic_scope="state", required_specificity="state", requires_dynamic=True),
        query="farmer registry",
    )
    return controller.build_curated_prompt(bundle, "farmer registry", None, "gu")


def test_prompt_does_not_instruct_specific_office_guidance():
    system, user = _curated_prompts()
    combined = " ".join((system + "\n" + user).split())
    # Old unconditional directives must be gone (the "[PACS office / ...]"
    # bracket alternatives and "visit your ..." instructions). A mention of
    # "PACS office" solely as a prohibited example is expected.
    assert "[PACS office" not in combined
    assert "visit your local" not in combined
    assert "visit your nearest" not in combined
    assert "call [relevant helpline]" not in combined


def test_prompt_bounds_guidance_to_evidence():
    system, user = _curated_prompts()
    combined = " ".join((system + "\n" + user).split())
    assert "never introduce a specific office" in combined
    assert "does not appear in the evidence" in combined
    assert "concerned government office" in combined
