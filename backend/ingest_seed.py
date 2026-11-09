"""Clean seed re-ingestion for the Sahayak RAG corpus.

Strategy (per RAG rebuild decision):
- Canonical chunk manifest = ``corpus/seeds/chunks_jsonl/*.jsonl``. These were
  produced from MinerU ``content_list_v2.json`` (page/heading/clause-aware), with
  Markdown kept as a human-readable derived artifact in ``corpus/seeds/*.md``.
- We DO NOT re-chunk Markdown or feed 3756-char slices. The JSONL is the source
  of truth for retrieval records.
- Document-level metadata (domain, jurisdiction, effective_date, authority tier)
  is enriched here from a frozen map, because the JSONL only carries chunk-level
  fields.
- Embeddings: Jina Embeddings v3, 768d. Documents use ``retrieval.passage``; the
  chat route embeds queries with ``retrieval.query``.
- Old RAG data in Supabase is wiped first (documents cascade -> chunks), then the
  seed corpus is upserted deterministically (keyed by ``chunk_id``).

Run:
    python backend/ingest_seed.py            # clears + re-ingests
    python backend/ingest_seed.py --no-clear # keep existing rows, upsert seed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow `import app` when executed as a script.
BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env", override=True)

from supabase import Client, create_client

from app.config import get_settings
from app.providers.embeddings import get_embedding_provider

SEED_JSONL_DIR = BACKEND.parent / "corpus" / "seeds" / "chunks_jsonl"
IMAGE_PLACEHOLDER = re.compile(r"\[Image asset:\s*[^]]*\]", re.IGNORECASE)
MIN_EMBED_CHARS = 40
# Jina v3 input limit is 8192 tokens (~32k chars). Cap embedding text safely;
# the full (untruncated) text is still stored in `content` for generation.
MAX_EMBED_CHARS = 28_000

# Frozen document metadata map. Keyed by the exact `document_id` stored in each
# JSONL file. Domain IDs MUST be canonical (see backend/data/DOMAIN_TAXONOMY.md):
#   pacs_governance | pacs_computerization | pmfby | financial_inclusion
#   | schemes | agriculture | grievance | out_of_scope
DOC_META: dict[str, dict] = {
    "operational_guidelines_pmfby": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "Pradhan Mantri Fasal Bima Yojana (PMFBY) Operational Guidelines 2023",
        "organization": "Department of Agriculture & Farmers Welfare, Ministry of Agriculture & Farmers Welfare, GoI",
        "document_type": "operational_guidelines",
        "source_url": "https://www.pmfby.gov.in",
        "effective_date": "2023-06-01",
        "document_date": "2023-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Model Byelaws 05.01.2023": {
        "domain": "pacs_governance",
        "jurisdiction": "central",
        "state": None,
        "title": "Model Byelaws for Primary Agricultural Credit Societies (PACS), 2023",
        "organization": "National Cooperative Union of India / Ministry of Cooperation, GoI",
        "document_type": "model_byelaws",
        "source_url": "",
        "effective_date": "2023-01-05",
        "document_date": "2023-01-05",
        "authority_tier": "secondary",
        "status": "active",
    },
    "Revised Scheme guidelines (Computerization of PACS project)": {
        "domain": "pacs_computerization",
        "jurisdiction": "central",
        "state": None,
        "title": "Revised Scheme Guidelines for Computerization of PACS Project",
        "organization": "Ministry of Cooperation, GoI",
        "document_type": "scheme_guidelines",
        "source_url": "",
        "effective_date": "2023-01-01",
        "document_date": "2023-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Corrigendum and letter Jun 12, 2023": {
        "domain": "pacs_computerization",
        "jurisdiction": "central",
        "state": None,
        "title": "Corrigendum and Letter dated 12 June 2023 (Computerization of PACS)",
        "organization": "Ministry of Cooperation, GoI",
        "document_type": "corrigendum",
        "source_url": "",
        "effective_date": "2023-06-12",
        "document_date": "2023-06-12",
        "authority_tier": "secondary",
        "status": "active",
    },
    "NSFI_2025_30": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "National Strategy for Financial Inclusion (NSFI) 2025-2030",
        "organization": "Reserve Bank of India / Government of India",
        "document_type": "strategy_document",
        "source_url": "",
        "effective_date": "2025-01-01",
        "document_date": "2025-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "RBI_FAME_Financial_Awareness_Messages": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "Financial Awareness Messages (FAME) - Fourth Edition",
        "organization": "Reserve Bank of India, Financial Inclusion and Development Department",
        "document_type": "financial_literacy_booklet",
        "source_url": "https://www.rbi.org.in/commonman/images/FAME202426022024.pdf",
        "effective_date": "2024-02-26",
        "document_date": "2024-02-26",
        "authority_tier": "primary",
        "status": "active",
    },
    "RBI_BEAWARE_Financial_Fraud_Awareness": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "BE(A)WARE - A Booklet on Modus Operandi of Financial Frauds",
        "organization": "Reserve Bank of India, Consumer Education and Protection Department",
        "document_type": "fraud_awareness_booklet",
        "source_url": "https://www.rbi.org.in/commonperson/Upload/english/Content/PDFs/English%20BEAWARE.pdf",
        "effective_date": "2022-03-07",
        "document_date": "2022-03-07",
        "authority_tier": "primary",
        "status": "active",
    },
    "Introduction_To_Insurance_IRDAI": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "Introduction to Insurance - Insurance Education Series",
        "organization": "Insurance Regulatory and Development Authority of India (IRDAI)",
        "document_type": "insurance_education",
        "source_url": "https://irdai.gov.in/documents/37343/621990/IntroductionToInsurance.pdf",
        "effective_date": None,
        "document_date": None,
        "authority_tier": "primary",
        "status": "active",
    },
    "IntroductionToInsurance": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "Introduction to Insurance - RBI/NABARD Financial Literacy",
        "organization": "NABARD / Reserve Bank of India",
        "document_type": "financial_literacy_material",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "GUIDE310113_F": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "RBI Financial Education Guide",
        "organization": "Reserve Bank of India",
        "document_type": "financial_literacy_material",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "RBI_BEAWARE_Financial_Fraud": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "RBI BE(A)WARE - Financial Fraud Awareness",
        "organization": "Reserve Bank of India",
        "document_type": "financial_literacy_material",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "RBI_FAME_Financial_Awareness": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "RBI FAME - Financial Awareness Messages",
        "organization": "Reserve Bank of India",
        "document_type": "financial_literacy_material",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "RBI_Financial_Education_NSFE": {
        "domain": "financial_inclusion",
        "jurisdiction": "central",
        "state": None,
        "title": "RBI Financial Education and NSFI",
        "organization": "Reserve Bank of India",
        "document_type": "financial_literacy_material",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Model_HR_Policy_V21": {
        "domain": "pacs_governance",
        "jurisdiction": "central",
        "state": None,
        "title": "Model HR Policy for Transformation of Primary Agricultural Credit Societies (PACS)",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "hr_policy",
        "source_url": "https://cooperation.gov.in/en/node/3210",
        "effective_date": "2026-04-08",
        "document_date": "2026-04-08",
        "authority_tier": "primary",
        "status": "active",
    },
    "PACS_HR_Policy": {
        "domain": "pacs_governance",
        "jurisdiction": "central",
        "state": None,
        "title": "Human Resource (HR) Policy for Primary Agricultural Credit Societies (PACS)",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "hr_policy",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Cooperative_Sugar_Mills_CSM_Scheme": {
        "domain": "pacs_governance",
        "jurisdiction": "central",
        "state": None,
        "title": "Grant-in-aid to NCDC for Strengthening of Cooperative Sugar Mills (CSMs)",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "scheme_brief",
        "source_url": "https://cooperation.gov.in/en/node/3007",
        "effective_date": "2023-07-01",
        "document_date": "2023-07-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Cooperative_Sugar_Mills_Scheme": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Cooperative Sugar Mills - Centrally Sponsored Scheme",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "scheme_guidelines",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Young_Professionals_YPs": {
        "domain": "pacs_governance",
        "jurisdiction": "central",
        "state": None,
        "title": "Inviting Applications for Engagement of Young Professionals in Ministry of Cooperation",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "https://cooperation.gov.in/en/node/2964",
        "effective_date": "2026-04-16",
        "document_date": "2026-04-16",
        "authority_tier": "secondary",
        "status": "active",
    },
    "MoC_Advertisement_Faculty_2026": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Advertisement for Faculty Positions 2026 - Ministry of Cooperation",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2026-01-01",
        "document_date": "2026-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Hiring_Agency_GeM": {
        "domain": "pacs_computerization",
        "jurisdiction": "central",
        "state": None,
        "title": "Hiring of Agency for Maintenance of Computer System through GeM",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "procurement_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_TOR_Internship": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Terms of Reference for Internship - Ministry of Cooperation",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "internship_tor",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Advertisement_YPs": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Advertisement for Young Professionals in Ministry of Cooperation",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Lok_Sabha_Session_Calendar": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Commencement of 06th Session of 18th Lok Sabha - Provisional Calendar",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "parliamentary_notice",
        "source_url": "",
        "effective_date": "2025-01-01",
        "document_date": "2025-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_YP_Finance_CRCS": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Engagement of Young Professionals (Finance) in CRCS",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_YP_Legal_CEA": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Engagement of Young Professionals (Legal) in Cooperative Election Authority",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Consultant_CRCS": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Engagement of Consultant in Central Registrar of Cooperative Societies",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Retired_Consultant_A": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Engagement of Retired Central Government Employees as Consultants",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Retired_Consultant_B": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Engagement of Retired Central Government Employees as Consultants (Reg)",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Central_Registrar_Order": {
        "domain": "pacs_governance",
        "jurisdiction": "central",
        "state": None,
        "title": "Order of Office of the Central Registrar of Cooperative Societies",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "official_order",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_Recruitment_Deputation": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Rolling Advertisement for Recruitment on Deputation",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_YP_CET_Policy": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Selection of Young Professionals in CET and Policy Division",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_YP_Budget_Finance": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "YP Advertisement - Budget and Finance Division",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "MoC_YP_Legal_Ombudsman": {
        "domain": "schemes",
        "jurisdiction": "central",
        "state": None,
        "title": "Engagement of Young Professional (Legal) in Cooperative Ombudsman",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "recruitment_notice",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Cooperative_Member_Introduction": {
        "domain": "pacs_governance",
        "jurisdiction": "central",
        "state": None,
        "title": "Introduction to Cooperative Member Rights and Responsibilities",
        "organization": "Ministry of Cooperation, Government of India",
        "document_type": "reference_guide",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Gujarat_Cooperative_Act_1961": {
        "domain": "pacs_governance",
        "jurisdiction": "state",
        "state": "gujarat",
        "title": "The Gujarat Co-operative Societies Act, 1961",
        "organization": "Government of Gujarat",
        "document_type": "legislation",
        "source_url": "",
        "effective_date": "1961-01-01",
        "document_date": "1961-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Affordable Crop Insurance for Every Farmer": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "Affordable Crop Insurance for Every Farmer",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "scheme_brochure",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "aws_gui_cre": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "AWS GUI CRE - Weather Data for Crop Insurance",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "technical_guide",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "GuidlinesforAWSandWeather Data-15.04": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "Guidelines for AWS and Weather Data",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "guidelines",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "National Agricultural Insurance Scheme (NAIS)- Scheme and Operational Modalities": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "National Agricultural Insurance Scheme (NAIS) - Scheme and Operational Modalities",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "scheme_guidelines",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "New Schemes-english_": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "New Crop Insurance Schemes - English",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "scheme_brochure",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "PMFBY_Features": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "PMFBY Features and Benefits",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "scheme_brochure",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "PMFBY_WINDS_Manual_2023_for_Hyperlocal_Weather_Data_Procurement_120923": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "PMFBY WINDS Manual 2023 for Hyperlocal Weather Data Procurement",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "technical_manual",
        "source_url": "",
        "effective_date": "2023-09-12",
        "document_date": "2023-09-12",
        "authority_tier": "primary",
        "status": "active",
    },
    "PMFBY-Advertisement": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "PMFBY Advertisement",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "advertisement",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "PRESS_Bhima": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "PRESS Bhima - Crop Insurance Press Coverage",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "press_material",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Revamped Operational Guidelines_17th August 2020": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "Revamped Operational Guidelines - 17th August 2020",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "operational_guidelines",
        "source_url": "",
        "effective_date": "2020-08-17",
        "document_date": "2020-08-17",
        "authority_tier": "primary",
        "status": "active",
    },
    "RWBCIS_Revised_Guidelines_1": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "RWBCIS Revised Guidelines",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "guidelines",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Sop For Bank Branch Users For Implementation Of Pmfby Rwbcis During Kharif 2021": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "SOP for Bank Branch Users for Implementation of PMFBY RWBCIS during Kharif 2021",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "standard_operating_procedure",
        "source_url": "",
        "effective_date": "2021-01-01",
        "document_date": "2021-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Unified Package Insurance Scheme (UPIS)-Operational Guidelines (OGs)": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "Unified Package Insurance Scheme (UPIS) - Operational Guidelines",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "operational_guidelines",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "Weather Based Crop Insurance Scheme (WBCIS)-Operational Guidelines (OGs)": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "Weather Based Crop Insurance Scheme (WBCIS) - Operational Guidelines",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "operational_guidelines",
        "source_url": "",
        "effective_date": "2024-01-01",
        "document_date": "2024-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
    "YESTECH_Manual_2023_v2": {
        "domain": "pmfby",
        "jurisdiction": "central",
        "state": None,
        "title": "YESTECH Manual 2023 (v.2) - Crop Insurance Technology",
        "organization": "Ministry of Agriculture, Government of India",
        "document_type": "technical_manual",
        "source_url": "",
        "effective_date": "2023-01-01",
        "document_date": "2023-01-01",
        "authority_tier": "primary",
        "status": "active",
    },
}


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _embeddable_text(text: str) -> str:
    """Strip pure image placeholders; return cleaned text used for embedding."""
    return IMAGE_PLACEHOLDER.sub("", text).strip()


def _clear(supabase: Client) -> None:
    print("[clear] removing old chunks + documents from Supabase ...")
    old_docs = supabase.table("documents").select("id").execute().data or []
    if old_docs:
        ids = [d["id"] for d in old_docs]
        supabase.table("chunks").delete().in_("document_id", ids).execute()
        supabase.table("documents").delete().in_("id", ids).execute()
    print(f"[clear] removed {len(old_docs)} document(s) and their chunks.")


def _document_source_file(chunks: list[dict]) -> str | None:
    """Return the corpus PDF filename only when the manifest provides one.

    The filename is provenance data, not something to derive from a document
    title or source_id.  If the canonical JSONL manifest does not contain a
    source_file, keep it null so the UI cannot construct a misleading PDF link.
    """
    values = {
        str(c.get("source_file")).strip()
        for c in chunks
        if c.get("source_file") and str(c.get("source_file")).strip()
    }
    if not values:
        return None
    if len(values) > 1:
        raise ValueError(
            "Multiple source_file values found for one document: "
            + ", ".join(sorted(values))
        )
    return next(iter(values))


def _ingest_document(supabase: Client, provider, doc_id: str, chunks: list[dict]) -> tuple[int, int]:
    meta = DOC_META.get(doc_id)
    if meta is None:
        raise SystemExit(f"No DOC_META entry for document_id={doc_id!r}; add it to the map.")

    # 1. Upsert document row (id = source_id for a stable, lookup-friendly key).
    doc_row = {
        "source_id": doc_id,
        "title": meta["title"],
        "organization": meta["organization"],
        "issuer": meta["organization"],
        "jurisdiction": meta["jurisdiction"],
        "state": meta["state"],
        "domain": meta["domain"],
        "document_type": meta["document_type"],
        "source_url": meta["source_url"],
        "effective_date": meta["effective_date"],
        "document_date": meta["document_date"],
        "verified_date": "2026-08-29",
        "source_type": "pdf",
        "version_id": "v1",
        "authority_tier": meta["authority_tier"],
        "status": meta["status"],
        "parser_profile": "mineru-content_list_v2",
        "metadata_schema_version": "v1",
    }
    existing = supabase.table("documents").select("id").eq("source_id", doc_id).execute().data
    if existing:
        supabase.table("documents").update(doc_row).eq("source_id", doc_id).execute()
        doc_uuid = existing[0]["id"]
    else:
        doc_uuid = supabase.table("documents").insert(doc_row).execute().data[0]["id"]

    # 2. Build chunk rows; skip pure image/table-as-image placeholders from the
    #    text vector index (they carry no retrievable text).
    rows_to_embed: list[tuple[dict, str]] = []
    skipped = 0
    for c in chunks:
        text = c.get("text", "")
        clean = _embeddable_text(text)[:MAX_EMBED_CHARS]
        if len(clean) < MIN_EMBED_CHARS:
            skipped += 1
            continue
        heading_path = c.get("heading_path", []) or []
        section = c.get("subsection") or c.get("section") or ""
        page_start = c.get("page_start")
        page_end = c.get("page_end")
        rows_to_embed.append(({
            "document_id": doc_uuid,
            "chunk_id": c.get("chunk_id"),
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            "page": int(page_start) if page_start else 0,
            "page_start": int(page_start) if page_start else None,
            "page_end": int(page_end) if page_end else None,
            "heading_path": " > ".join(heading_path),
            "section": section,
            "section_number": c.get("clause") or "",
            "language": c.get("language") or "en",
            "token_count": len(text.split()),
            "chunker_version": "mineru-content_list_v2",
            "ordinal": len(rows_to_embed),
            "content": text,
            "metadata": {
                "heading_path": heading_path,
                "section": c.get("section", ""),
                "subsection": c.get("subsection", ""),
                "clause": c.get("clause", ""),
                "chunk_type": c.get("chunk_type", "text"),
                "images": c.get("images", []),
                "language": c.get("language") or "en",
                "domain": meta["domain"],
                "source_file": c.get("source_file", ""),
            },
        }, clean))

    # 3. Embed (Jina v3, retrieval.passage) in provider-batched calls.
    texts = [t for _, t in rows_to_embed]
    embeddings = provider.embed_texts(texts, task="retrieval.passage")
    if len(embeddings) != len(texts):
        raise SystemExit(f"Embedding count mismatch: {len(embeddings)} != {len(texts)}")

    # 4. Insert chunk rows. The chunks.chunk_id partial unique index is not a
    #    usable upsert conflict target for PostgREST, so we delete-then-insert
    #    keyed by chunk_id (idempotent per document). Batch to avoid oversized
    #    PostgREST requests when a document has hundreds of chunks.
    chunk_rows = []
    for (row, _), vec in zip(rows_to_embed, embeddings):
        row = dict(row)
        row["embedding"] = vec
        chunk_rows.append(row)
    if chunk_rows:
        chunk_ids = [r["chunk_id"] for r in chunk_rows]
        for i in range(0, len(chunk_ids), 100):
            supabase.table("chunks").delete().in_("chunk_id", chunk_ids[i:i + 100]).execute()
        for i in range(0, len(chunk_rows), 100):
            supabase.table("chunks").insert(chunk_rows[i:i + 100]).execute()

    print(f"  -> {doc_id}: {len(chunk_rows)} chunks embedded, {skipped} skipped (image/empty)")
    return len(chunk_rows), skipped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-clear", action="store_true",
                        help="Do not wipe existing documents; upsert seed on top.")
    args = parser.parse_args()

    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_service_key)
    provider = get_embedding_provider()
    print(f"Embedding provider: {provider.__class__.__name__}")

    if not args.no_clear:
        _clear(supabase)

    total_chunks = 0
    total_skipped = 0
    for jsonl_path in sorted(SEED_JSONL_DIR.glob("*.jsonl")):
        chunks = _load_jsonl(jsonl_path)
        doc_id = chunks[0]["document_id"]
        print(f"[doc] {doc_id} ({len(chunks)} raw chunks)")
        n, s = _ingest_document(supabase, provider, doc_id, chunks)
        total_chunks += n
        total_skipped += s

    print("=" * 60)
    print(f"RE-INGESTION COMPLETE: {total_chunks} chunks embedded, {total_skipped} skipped.")


if __name__ == "__main__":
    main()
