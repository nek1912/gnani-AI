"""
eGovAssist Web RAG Layer.

Responsibilities:
- Query classification
- Jurisdiction resolution
- Tavily web discovery
- Official-source prioritization
- BM25 keyword ranking
- Evidence-threshold routing

This layer does NOT:
- generate answers
- perform citation validation
- replace RAG
"""

from app.web_rag.service import (
    WebDiscoveryService,
)
from app.web_rag.tavily_client import (
    TavilyClient,
)
from app.web_rag.firecrawl_client import (
    FirecrawlClient,
)
from app.web_rag.providers import (
    resolve_providers,
)
from app.web_rag.query_classifier import (
    QueryClassifier,
    QueryClassification,
)


__all__ = [
    "WebDiscoveryService",
    "TavilyClient",
    "FirecrawlClient",
    "resolve_providers",
    "QueryClassifier",
    "QueryClassification",
]
