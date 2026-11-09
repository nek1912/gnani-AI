# Canonical Domain Taxonomy

**Purpose:** Single source of truth for domain IDs used across classifier, retrieval, and evaluation.

**Status:** FROZEN — do not change without updating all consumers.

---

## Canonical Domain IDs

| Canonical ID | Description | Database Documents |
|--------------|-------------|-------------------|
| `pacs_governance` | PACS byelaws, governance, membership, cooperative society registration | `pacs_model_bylaws_2023` (337 chunks), `model_hr_policy_v21` (601 chunks), `moc_young_professionals` (213 chunks), `cooperative_sugar_mills_csm_scheme` (43 chunks) |
| `pacs_computerization` | PACS computerization scheme, digitization guidelines | `pacs_computerization_guidelines` (192 chunks), `pacs_computerization_corrigendum_2023_06_12` (22 chunks) |
| `pmfby` | PMFBY crop insurance, claims, premiums, eligibility | `pmfby_operational_guidelines` (1266 chunks) |
| `financial_inclusion` | RBI, Jan Dhan, financial literacy, deposit insurance, RuPay | `nsfi_2025_30` (371 chunks), `rbi_fame_financial_awareness` (579 chunks), `rbi_beaware_financial_fraud` (429 chunks), `irdai_introduction_to_insurance` (725 chunks) |
| `schemes` | Ministry of Cooperation schemes (no DB documents yet) | — |
| `agriculture` | Agriculture practices, MSP, mandi, fertilizer (no DB documents yet) | — |
| `grievance` | Complaint filing, grievance redressal (no DB documents yet) | — |
| `out_of_scope` | Query does not match any domain | — |

---

## Domain Routing Rules

1. **Exact match only.** The `match_chunks` RPC uses `c.domain = match_domain` (`backend/schema.sql`). No prefix/contains matching.

2. **Classifier must emit only canonical IDs.** If the classifier returns a non-canonical ID, it's a bug.

3. **Unknown domains route to `out_of_scope`.** The system abstains for unrecognized domains.

4. **Domains without DB documents return empty results.** This is expected — the system should abstain when no evidence exists.

---

## Mapping from Legacy IDs

| Legacy ID | Canonical ID | Notes |
|-----------|--------------|-------|
| `cooperative` | `pacs_governance` | Cooperative society = PACS governance |
| `pacs` | `pacs_governance` | PACS queries default to governance |
| `finlit` | `financial_inclusion` | Financial literacy = financial inclusion |
| `pmfby` | `pmfby` | No change |

---

## Consumer Conformance

| Component | Must Use | File |
|-----------|----------|------|
| Keyword rules | Canonical IDs | `backend/data/keyword_rules.json` |
| Anchor classifier | Canonical IDs | `backend/data/domain_anchors.json` |
| Database documents | Canonical IDs | `documents.domain` column |
| Gold cases | Canonical IDs | `backend/tests/eval_rag_v3.py` expected domains |
| Evaluation scripts | Canonical IDs | `backend/tests/eval_rag_v3.py` |

---

## Verification

After any domain taxonomy change (from `backend/`):
1. Run domain classification tests: `pytest tests/test_domains.py -v` — classifier must emit canonical IDs
