from app.facets import split_facets


class _Cls:
    domain = "pmfby"
    intent = "INFORMATIONAL"
    state = "Gujarat"


def test_single_pmfby_stays_single():
    facets = split_facets("What is PMFBY premium?", ["pmfby"], _Cls(), "simple", "Gujarat")
    assert len(facets) == 1
    assert facets[0].domain == "pmfby"


def test_triple_splits_to_three():
    facets = split_facets(
        "PM-KISAN PMFBY Farmer Registry Gujarat land records",
        ["pmfby", "schemes", "agriculture"],
        _Cls(),
        "multi_condition",
        "Gujarat",
    )
    assert 2 <= len(facets) <= 3
