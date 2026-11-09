import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent.parent / "data"
DOMAIN_FLOOR = 0.20  # lowered to be lenient with domain classification for general queries


def load_rules(path: Path = DATA_DIR / "keyword_rules.json") -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))


class AnchorStore:
    def __init__(self, rules: dict[str, list[str]], domain_vectors: dict[str, np.ndarray]):
        self.rules = rules
        self.domains = sorted(domain_vectors)
        vecs = np.array([domain_vectors[d] for d in self.domains])
        self.vectors = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)

    def classify(self, text: str, query_embedding: list[float]) -> tuple[str, float]:
        lowered = text.lower()
        for domain, keywords in self.rules.items():
            for kw in keywords:
                # Multi-word phrases: substring match (e.g. "crop insurance")
                # Single words: word-boundary match to avoid false positives
                # (e.g. "pmfby" must not match inside "pmjjby")
                if " " in kw:
                    if kw in lowered:
                        return domain, 1.0
                else:
                    if re.search(r"\b" + re.escape(kw) + r"\b", lowered):
                        return domain, 1.0
        q = np.asarray(query_embedding, dtype=float)
        q = q / max(np.linalg.norm(q), 1e-9)
        scores = self.vectors @ q
        best = int(scores.argmax())
        if scores[best] < DOMAIN_FLOOR:
            return "out_of_scope", float(scores[best])
        return self.domains[best], float(scores[best])

    def collect_hits(self, text: str) -> list[str]:
        lowered = text.lower()
        hits: list[str] = []
        for domain, keywords in self.rules.items():
            for kw in keywords:
                if " " in kw:
                    if kw in lowered:
                        hits.append(domain)
                        break
                else:
                    if re.search(r"\b" + re.escape(kw) + r"\b", lowered):
                        hits.append(domain)
                        break
        # scheme-code identifiers not in keyword_rules
        extra = {"pm-kisan": "schemes", "pmkisan": "schemes",
                 "farmer registry": "schemes", "farmer id": "schemes"}
        for k, d in extra.items():
            if k in lowered and d not in hits:
                hits.append(d)
        return hits


@lru_cache(maxsize=1)
def load_anchor_store(embed_texts, rules_path: Path = DATA_DIR / "keyword_rules.json",
                      anchors_path: Path = DATA_DIR / "domain_anchors.json") -> AnchorStore:
    anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
    
    # Batch all phrases into a single embedding call for efficiency
    all_phrases = []
    domain_phrase_counts = {}
    for domain, phrases in anchors.items():
        domain_phrase_counts[domain] = len(all_phrases)
        all_phrases.extend(phrases)
    
    # Single batch embedding call
    all_vecs = np.asarray(embed_texts(all_phrases), dtype=float)
    
    # Split back by domain and compute mean vectors
    domain_vectors = {}
    for domain, phrases in anchors.items():
        start_idx = domain_phrase_counts[domain]
        end_idx = start_idx + len(phrases)
        vecs = all_vecs[start_idx:end_idx]
        domain_vectors[domain] = vecs.mean(axis=0)
    
    return AnchorStore(load_rules(rules_path), domain_vectors)


_anchor_store_singleton: "AnchorStore | None" = None


def get_anchor_store() -> AnchorStore:
    """Process-wide singleton. The route MUST call THIS, never
    `load_anchor_store(provider.embed_texts)` directly — a fresh bound method
    per request would defeat the cache and re-embed all ~70 anchors on every
    `/chat` (P0-1). First call costs ~70 embedding requests; the FastAPI
    startup hook (Task 11) warms it so no user request ever pays for it."""
    global _anchor_store_singleton
    if _anchor_store_singleton is None:
        from app.providers.embeddings import get_embedding_provider
        _anchor_store_singleton = load_anchor_store(get_embedding_provider().embed_texts)
    return _anchor_store_singleton
