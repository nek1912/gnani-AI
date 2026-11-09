import numpy as np

from app.domains import AnchorStore

RULES = {"pmfby": ["pmfby"], "finlit": ["jan dhan"]}


def test_keyword_rule_short_circuits():
    store = AnchorStore(rules=RULES, domain_vectors={"pmfby": np.zeros(16), "finlit": np.zeros(16)})
    assert store.classify("tell me about PMFBY", [0.0] * 16)[0] == "pmfby"


def test_anchor_match_by_cosine():
    q = [1.0] + [0.0] * 15  # matches first domain's vector
    store = AnchorStore(rules={}, domain_vectors={"finlit": np.array([1.0] + [0.0] * 15)})
    domain, score = store.classify("bank account help", q)
    assert domain == "finlit" and score > 0.9


def test_out_of_scope_floor():
    store = AnchorStore(rules={}, domain_vectors={"finlit": np.zeros(16)})
    assert store.classify("who won the cricket match", [0.0] * 16)[0] == "out_of_scope"


def test_multi_domain_returns_correct_domain():
    """With multiple domains, the domain with the closest vector should be returned."""
    # 2 domains with distinct vectors
    vectors = {
        "pmfby": np.array([1.0] + [0.0] * 15),  # pmfby vector
        "finlit": np.array([0.0, 0.0] + [1.0] + [0.0] * 13),  # finlit vector
    }
    q = [1.0] + [0.0] * 15  # matches pmfby vector
    store = AnchorStore(rules={}, domain_vectors=vectors)
    domain, score = store.classify("test query", q)
    assert domain == "pmfby", f"Expected 'pmfby', got '{domain}'"
    assert score > 0.9
