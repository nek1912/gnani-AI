"""P2-3 multilingual data expansion tests.

For MR/BN/TA (verified repo vocabulary): basic scheme, agriculture,
grievance, status, and jurisdiction-sensitive queries. For
TE/KN/ML/PA/OR (state names only): graceful English fallback without
native-branch invention. Plus: GU/HI behavior unchanged, Romanized
preserved, no branch explosion, no-unverified-term property.
"""

from app.web_rag.lexicon import (
    all_native_terms,
    load_lexicon,
    native_branch_query,
)
from app.web_rag.query_classifier import QueryClassifier
from app.web_rag.service import WebDiscoveryService

_classifier = QueryClassifier()


def _branches(query, **kwargs):
    cls = _classifier.classify(query, **kwargs)
    service = WebDiscoveryService()
    return service._build_stage1_branches(query, cls, query), cls


def _names(branches):
    return [b["name"] for b in branches]


class TestLexiconCoverage:
    def test_mr_bn_ta_present(self):
        concepts = {c["id"]: c for c in load_lexicon()}
        assert concepts["crop_insurance"]["mr"]
        assert concepts["crop_insurance"]["bn"]
        assert concepts["crop_insurance"]["ta"]
        assert concepts["scheme"]["mr"]
        assert concepts["grievance"]["ta"]

    def test_te_kn_ml_pa_or_absent(self):
        concepts = {c["id"]: c for c in load_lexicon()}
        for cid, concept in concepts.items():
            for lang in ("te", "kn", "ml", "pa", "or"):
                assert not concept.get(lang), (cid, lang)

    def test_native_branch_gated(self):
        assert native_branch_query("random words xyzzy", "mr") is None
        assert native_branch_query("crop insurance", "xx") is None


class TestMarathi:
    def test_scheme(self):
        branches, cls = _branches("महाराष्ट्र शासकीय योजना")
        assert cls.domain == "schemes" and cls.state == "Maharashtra"
        assert "native:mr" in _names(branches)

    def test_agriculture(self):
        branches, cls = _branches("महाराष्ट्र पीक विमा")
        assert cls.domain == "pmfby"
        assert "native:mr" in _names(branches)

    def test_grievance(self):
        branches, cls = _branches("माहिती अधिकार महाराष्ट्र")
        assert cls.domain == "grievance"
        assert "native:mr" in _names(branches)

    def test_status_english_token(self):
        branches, _ = _branches("Check status Maharashtra scheme")
        assert "status" in _names(branches)

    def test_jurisdiction(self):
        branches, cls = _branches("महाराष्ट्र सहकारी")
        assert cls.state == "Maharashtra"
        assert "native:mr" in _names(branches)

    def test_session_state_variant(self):
        branches, cls = _branches("पीक विमा", default_state="Maharashtra")
        assert cls.state == "Maharashtra"
        assert "native:mr" in _names(branches)


class TestBengali:
    def test_scheme(self):
        branches, cls = _branches("পশ্চিমবঙ্গ সরকারি প্রকল্প")
        assert cls.domain == "schemes" and cls.state == "West Bengal"
        assert "native:bn" in _names(branches)

    def test_agriculture(self):
        branches, cls = _branches("পশ্চিমবঙ্গ ফসল বীমা")
        assert cls.domain == "pmfby"
        assert "native:bn" in _names(branches)

    def test_grievance(self):
        branches, cls = _branches("অভিযোগ পশ্চিমবঙ্গ")
        assert cls.domain == "grievance"
        assert "native:bn" in _names(branches)

    def test_status_english_token(self):
        branches, _ = _branches("Check status West Bengal scheme")
        assert "status" in _names(branches)

    def test_jurisdiction(self):
        branches, cls = _branches("পশ্চিমবঙ্গ সমবায়")
        assert cls.state == "West Bengal"
        assert "native:bn" in _names(branches)


class TestTamil:
    def test_scheme(self):
        branches, cls = _branches("தமிழ்நாடு அரசு திட்டம்")
        assert cls.domain == "schemes" and cls.state == "Tamil Nadu"
        assert "native:ta" in _names(branches)

    def test_agriculture(self):
        branches, cls = _branches("தமிழ்நாடு பயிர் காப்பீடு")
        assert cls.domain == "pmfby"
        assert "native:ta" in _names(branches)

    def test_grievance(self):
        branches, cls = _branches("புகார் தமிழ்நாடு")
        assert cls.domain == "grievance"
        assert "native:ta" in _names(branches)

    def test_status_english_token(self):
        branches, _ = _branches("Check status Tamil Nadu scheme")
        assert "status" in _names(branches)

    def test_jurisdiction(self):
        branches, cls = _branches("தமிழ்நாடு கூட்டுறவு")
        assert cls.state == "Tamil Nadu"
        assert "native:ta" in _names(branches)


class TestNoInvention:
    def test_te_kn_ml_pa_or_no_native_branch(self):
        probes = [
            "KCC loan Karnataka",
            "KCC rom Andhra Pradesh",
            "crop insurance Punjab",
            "scheme Odisha",
            "KCC loan Kerala",
        ]
        for query in probes:
            branches, _ = _branches(query)
            assert not [b for b in _names(branches) if b.startswith("native:")], query
            assert len(branches) <= WebDiscoveryService.MAX_BRANCHES

    def test_gujarati_gets_no_foreign_native_branch(self):
        branches, _ = _branches("પાક વીમા યોજના ગુજરાત")
        names = _names(branches)
        assert "gujarati" in names
        assert not [b for b in names if b.startswith("native:")]

    def test_romanized_preserved(self):
        branches, _ = _branches("pak vimo sahay Gujarat")
        assert "gujarati" in _names(branches)

    def test_no_branch_explosion(self):
        queries = [
            "महाराष्ट्र शासकीय योजना तक्रार स्थिती",
            "পশ্চিমবঙ্গ সরকারি প্রকল্প অভিযোগ",
            "தமிழ்நாடு அரசு திட்டம் புகார்",
            "What is PMFBY?",
        ]
        for query in queries:
            branches, _ = _branches(query)
            assert len(branches) <= WebDiscoveryService.MAX_BRANCHES, query

    def test_native_terms_verified_only(self):
        queries = [
            "महाराष्ट्र शासकीय योजना",
            "महाराष्ट्र पीक विमा",
            "পশ্চিমবঙ্গ সরকারি প্রকল্প",
            "পশ্চিমবঙ্গ ফসল বীমা",
            "தமிழ்நாடு அரசு திட்டம்",
            "தமிழ்நாடு பயிர் காப்பீடு",
        ]
        lang_of = ["mr", "mr", "bn", "bn", "ta", "ta"]
        for query, lang in zip(queries, lang_of):
            branches, _ = _branches(query)
            native = next(
                (b for b in branches if b["name"] == f"native:{lang}"), None
            )
            assert native is not None, query
            remaining = native["query"]
            for term in sorted(all_native_terms(lang), key=len, reverse=True):
                remaining = remaining.replace(term, " ")
            state_words = ["महाराष्ट्र", "পশ্চিমবঙ্গ", "தமிழ்நாடு"]
            for word in state_words:
                remaining = remaining.replace(word, " ")
            assert "".join(remaining.split()) == "", (query, remaining)
