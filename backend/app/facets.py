from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Facet:
    facet_id: str
    domain: str
    query: str
    state: str | None


_SCHEME_CODES = ["pmfby", "pm-kisan", "pmkisan", "farmer registry", "farmer id"]


def _slice_query(english_query: str, domain: str, state: str | None) -> str:
    # Discriminative window slice: find query words matching this facet's
    # domain/scheme tokens, keep them plus ±8 surrounding words. Falls back
    # to the full query (truncated) when nothing matches.
    words = english_query.split()
    low_words = [w.lower().strip(".,;:!?()\"'") for w in words]
    domain_tokens = {t for t in domain.lower().replace("_", " ").split() if len(t) > 2}
    scheme_tokens: set[str] = set()
    for code in _SCHEME_CODES:
        scheme_tokens.update(code.split())
    target = domain_tokens | scheme_tokens
    hit_idx = [i for i, lw in enumerate(low_words) if lw in target]
    if not hit_idx:
        base = english_query[:300]
    else:
        keep_idx: set[int] = set()
        for i in hit_idx:
            for j in range(max(0, i - 8), min(len(words), i + 9)):
                keep_idx.add(j)
        base = " ".join(words[j] for j in sorted(keep_idx))
    if state and state.lower() not in base.lower():
        base = f"{base} {state}"
    return base[:400]


def split_facets(english_query, hits, classification, complexity, state):
    uniq: list[str] = []
    for h in hits or []:
        if h not in uniq:
            uniq.append(h)
    if classification is not None and getattr(classification, "domain", None):
        d = classification.domain
        if d not in ("general", "out_of_scope") and d not in uniq:
            uniq.append(d)
    multi = len(uniq) >= 2 or (complexity in ("multi_condition", "comparison", "multi_hop") and len(uniq) >= 2)
    if not multi:
        dom = uniq[0] if uniq else (getattr(classification, "domain", "general") or "general")
        return [Facet(facet_id=dom, domain=dom, query=english_query, state=state)]
    out: list[Facet] = []
    for d in uniq[:3]:
        out.append(Facet(facet_id=d, domain=d, query=_slice_query(english_query, d, state), state=state))
    return out


def select_coverage(facet_chunks: dict[str, list]) -> tuple[list, dict]:
    merged: list = []
    coverage: dict = {}
    for fid, chunks in facet_chunks.items():
        good = [c for c in chunks if (c.dense_score or c.rerank_score or 0) >= 0.40]
        if good:
            status = "supported"
        elif chunks:
            status = "partial"
        else:
            status = "unsupported"
        coverage[fid] = {"status": status, "chunk_ids": [c.chunk_id for c in chunks[:3]]}
    # round-robin: 2 per supported facet first (deduped: the same chunk
    # may surface under multiple facets when facet queries overlap)
    seen: set = set()
    for fid, chunks in facet_chunks.items():
        for c in chunks[:2]:
            if c.chunk_id not in seen:
                merged.append(c)
                seen.add(c.chunk_id)
    # fill to 12 by score order
    rest: list = []
    for chunks in facet_chunks.values():
        for c in chunks[2:]:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                rest.append(c)
    rest.sort(key=lambda c: -((c.dense_score or 0) + (c.rerank_score or 0)))
    merged = (merged + rest)[:12]
    return merged, coverage
