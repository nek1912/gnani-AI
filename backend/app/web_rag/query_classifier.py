"""
Deterministic query classification for the Web RAG pipeline.

This module does NOT generate answers.

It determines:
- domain
- jurisdiction
- state
- intent

Supported domains:
- cooperative
- pacs
- schemes
- pmfby
- agriculture
- finlit / financial_inclusion
- grievance
- driving_licence

Supported intents:
- INFORMATIONAL
- ELIGIBILITY
- APPLICATION
- REGISTRATION
- DOCUMENT_REQUIREMENTS
- BENEFIT
- SUBSIDY_AMOUNT
- DEADLINE
- STATUS
- GRIEVANCE
- CONTACT
- SERVICE_ACCESS
- LOCATION
- COMPARISON
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class QueryClassification:
    domain: str
    jurisdiction: str
    state: Optional[str]
    intent: str
    confidence: float
    # P0-1 jurisdiction resolution (all optional/backward-compatible).
    # district: canonical district name (Gujarat district list) or None.
    district: Optional[str] = None
    # society_type: "mscs" (Multi-State) | "state_society" | None (unknown).
    society_type: Optional[str] = None
    # case_year: explicit 4-digit year mentioned in the query, if any.
    case_year: Optional[int] = None
    # season: "kharif" | "rabi" | "zaid" if explicitly mentioned, else None.
    season: Optional[str] = None
    # jurisdiction_source: "explicit" | "session" | "none".
    # ("recovery" is set by the web recovery path, never here.)
    jurisdiction_source: str = "none"
    # assumed_state: True when state did NOT come from an explicit query
    # signal (session/default fallback). Downstream answers must disclose it.
    assumed_state: bool = False
    # national_scope: True when the query explicitly claims national
    # scope ("national", "all india", ...). Beats inherited session
    # state in resolve_expected_state; English cues only (limitation).
    national_scope: bool = False


DOMAIN_KEYWORDS = {
    "pmfby": [
        "pmfby",
        "fasal bima",
        "pak vimo",
        "pak vima",
        "crop insurance",        "pradhan mantri fasal",
        "crop insurance scheme",
        "crop damage",
        "crop loss",
        "insurance claim",
        "premium subsidy",
        "wbcis",
        "पीएमएफबीवाई",
        "फसल बीमा",
        "प्रधानमंत्री फसल",
        "फसल नुकसान",
        "बीमा दावा",
        "વીમા",
        "ફસલ બીમા",
        "પીએમએફબીવાઈ",
        "પાક વીમો",
        "પાક નુકસાન",
        "વીમા દાવો",
        "પ્રધાનમંત્રી ફસલ બીમા યોજના",
        "पीक विमा",
        "पंतप्रधान पीक विमा योजना",
        "ফসল বীমা",
        "প্রধানমন্ত্রী ফসল বীমা",
        "பயிர் காப்பீடு",
    ],
    "pacs": [
        "pacs",
        "mandli",
        "seva sahkari mandli",
        "primary agricultural credit society",
        "primary agriculture credit society",
        "credit cooperative",
        "cooperative credit",
        "cooperative training",
        "sahakari talim",
        "sahakari bank",
        "pacs project",
        "pacspl",
        "प्राथमिक कृषि ऋण सहकारी समिति",
        "प्राथमिक कृषि साख समिति",
        "सहकारी प्रशिक्षण",
        "सहकारी बैंक",
        "सहकारी ऋण",
        "સહકારી તાલીમ",
        "સહકારી મંડળી",
        "સહકારી બેંક",
        "પ્રાથમિક કૃષિ ધિરાણ મંડળી",
        "સહકારી સંસ્થા",
        "सहकारी संस्था",
        "प्राथमिक कृषी पतसंस्था",
        "সমবায় সমিতি",
        "কৃষি ঋণ সমিতি",
        "கூட்டுறவு சங்கம்",
    ],
    "pacs_computerization": [
        # NOTE: the "ict" acronym was removed (audit): as a substring it
        # fires inside core vocabulary ("district", "predict", "victim"),
        # hijacking unrelated queries into an unsupported domain and
        # causing wrong abstentions. Remaining keywords cover genuine
        # computerization queries.
        "computerization",
        "digitization",
        "digital pacs",
        "pacspl",
        "ncip",
        "erp",
        "pmu",
        "micro-atm",
        "core banking",
        "pacs project",
        "data readiness",
    ],
    "cooperative": [
        "cooperative",
        "co-operative",
        "cooperative society",
        "cooperative law",
        "mscs",
        "crcs",
        "bylaws",
        "by-laws",
        "member rights",
        "society registration",
        "cooperative training",
        "sahakari",
        "chutni",
        "chuntni",
        "सहकारी",
        "समिति",
        "સહકારી",
        "સમવાય",
        "கூட்டுறவு",
        "সমবায়",
    ],
    "schemes": [
        "scheme",
        "yojana",
        "pmjjby",
        "pmsby",
        "ministry of cooperation",
        "government scheme",
        "subsidy",
        "benefit",
        "eligibility",
        "apply for",
        "apply to",
        "applicant",
        "beneficiary",
        "government program",
        "government programme",
        "portal",
        "registration for",
        "योजना",
        "सरकारी योजना",
        "યોજના",
        "સરકારી યોજના",
        "સબસિડી",
        "લાભ",
        "પાત્રતા",
        "शासकीय योजना",
        "প্রকল্প",
        "সরকারি প্রকল্প",
        "திட்டம்",
        "அரசு திட்டம்",
    ],
    "agriculture": [
        "farmer",
        "farmers",
        "farm",
        "farming",
        "agriculture",
        "agricultural",
        "crop",
        "crops",
        "cultivation",
        "harvest",
        "fertilizer",
        "pesticide",
        "irrigation",
        "seed",
        "tractor",
        "mandi",
        "apmc",
        "msp",
        "kisan",
        "khedut",
        "krushi",
        "krishi",
        "rahat",
        "किसान",
        "खेती",
        "फसल",
        "सिंचाई",
        "उर्वरक",
        "बीज",
        "ખેતી",
        "ખેડૂત",
        "પાક",
        "કાપાસ",
        "ફસલ",
        "ખાતર",
        "સિંચાઈ",
        "બીજ",
        "શેતી",
        "શતકરી",
        "কৃষি",
        "কৃষক",
        "চাষ",
        "விவசாயம்",
        "விவசாயி",
    ],
    "finlit": [
        "financial literacy",
        "loan",
        "credit",
        "interest",
        "banking",
        "savings",
        "financial",
        "account",
        "jan dhan",
        "pmjdy",
        "mudra",
        "microfinance",
        "self help group",
        "shg",
        "rupay",
        "kcc",
        "kisan credit card",
        "वित्तीय साक्षरता",
        "बैंक खाता",
        "जन धन",
        "मुद्रा ऋण",
        "ऋण",
        "बैंकिंग",
        "નાણાકીય સમાવેશ",
        "બેંક ખાતું",
        "જન ધન",
        "મુદ્રા લોન",
        "ஆર્થિક સમાવેશ",
        "ব্যাংক অ্যাকাউন্ট",
        "நிதி உள்ளடக்கம்",
    ],
    "financial_inclusion": [
        "financial inclusion",
        "jan dhan",
        "pmjdy",
        "mudra loan",
        "microfinance",
        "self help group",
        "shg",
        "bank account",
    ],
    "grievance": [
        "grievance",
        "complaint",
        "complain",
        "escalate",
        "escalation",
        "fraud",
        "appeal",
        "dispute",
        "redressal",
        "redress",
        "cpgrams",
        "rti",
        "right to information",
        "ombudsman",
        "शिकायत",
        "आरटीआई",
        "सूचना का अधिकार",
        "लोक शिकायत",
        "ફરિયાદ",
        "આરટીઆઈ",
        "માહિતી અધિકાર",
        "જાહેર ફરિયાદ",
        "તક્રાર",
        "माहिती अधिकार",
        "অভিযোগ",
        "তথ্য অধিকার",
        "புகார்",
        "தகவல் உரிமை",
    ],
    "driving_licence": [
        "driving licence",
        "driving license",
        "learner licence",
        "learner license",
        "learner's licence",
        "learner's license",
        "driving licence application",
        "rto",
        "motor vehicle",
        "driving test",
        "parivahan",
        "sarathi",
        "ड्राइविंग लाइसेंस",
        "लर्नर परमिट",
        "आरटीओ",
        "वाहन पंजीकरण",
        "ડ્રાઇવિંગ લાઇસન્સ",
        "લર્નર પરમિટ",
        "આરટીઓ",
        "વાહન નોંધણી",
        "वाहन चालक परवाना",
        "ড্রাইভিং লাইসেন্স",
        "ஓட்டுநர் உரிமம்",
    ],
}


INTENT_KEYWORDS = {
    "INFORMATIONAL": [
        "what is",
        "who is",
        "history",
        "overview",
        "about",
        "definition",
        "explain",
        "details",
        "information",
        "tell me about",
    ],
    "ELIGIBILITY": [
        "eligible",
        "eligibility",
        "qualify",
        "qualification",
        "who can",
        "requirements for",
        "criteria",
        "પાત્રતા",
        "पात्रता",
    ],
    "APPLICATION": [
        "apply",
        "application",
        "how to apply",
        "application process",
        "fill out",
        "submit application",
        "અરજી",
        "आवेदन",
    ],
    "REGISTRATION": [
        "register",
        "registration",
        "how to register",
        "sign up",
        "enroll",
        "enrollment",
        "નોંધણી",
        "पंजीकरण",
    ],
    "DOCUMENT_REQUIREMENTS": [
        "documents required",
        "what documents",
        "paperwork",
        "forms needed",
        "required documents",
        "દસ્તાવેજ",
        "दस्तावेज",
    ],
    "BENEFIT": [
        "benefit",
        "benefits",
        "what do i get",
        "advantages",
        "help",
        "assistance",
        "લાભ",
        "लाभ",
    ],
    "SUBSIDY_AMOUNT": [
        "subsidy amount",
        "how much",
        "amount",
        "value",
        "sum",
        "financial aid",
        "money",
        "સબસિડી",
        "सब्सिडी",
    ],
    "DEADLINE": [
        "deadline",
        "last date",
        "due date",
        "when to apply",
        "closing date",
        "time limit",
    ],
    "STATUS": [
        "status",
        "track",
        "check status",
        "application status",
        "progress",
        "સ્થિતિ",
        "स्थिति",
    ],
    "GRIEVANCE": [
        "grievance",
        "complaint",
        "complain",
        "escalate",
        "escalation",
        "fraud",
        "appeal",
        "dispute",
        "redressal",
        "redress",
        "report a",
        "reporting a",
        "report the",
        "report this",
        "file a complaint",
        "file a grievance",
        "ફરિયાદ",
        "शिकायत",
        "रिपोर्ट",
        "अभियोग",
    ],
    "CONTACT": [
        "contact",
        "phone number",
        "email",
        "address",
        "helpline",
        "customer care",
        "સંપર્ક",
        "संपर्क",
    ],
    "SERVICE_ACCESS": [
        "access",
        "how to access",
        "use the service",
        "avail",
        "availment",
    ],
    "LOCATION": [
        "where",
        "location",
        "nearest",
        "near me",
        "address",
        "branch",
        "office",
    ],
    "COMPARISON": [
        "compare",
        "difference",
        "vs",
        "versus",
        "better",
        "which is better",
    ],
}


STATE_KEYWORDS = {
    # Gujarat
    "gujarat": "Gujarat",
    "ગુજરાત": "Gujarat",
    "गुजरात": "Gujarat",
    "ahmedabad": "Gujarat",
    "અમદાવાદ": "Gujarat",
    "surat": "Gujarat",
    "સુરત": "Gujarat",
    "vadodara": "Gujarat",
    "વડોદરા": "Gujarat",
    "rajkot": "Gujarat",
    "રાજકોટ": "Gujarat",
    "ikhedut": "Gujarat",
    "digitalgujarat": "Gujarat",

    # Maharashtra
    "maharashtra": "Maharashtra",
    "महाराष्ट्र": "Maharashtra",
    "mumbai": "Maharashtra",
    "मुंबई": "Maharashtra",
    "pune": "Maharashtra",
    "पुणे": "Maharashtra",
    "nagpur": "Maharashtra",
    "नागपुर": "Maharashtra",
    "mahaonline": "Maharashtra",

    # Madhya Pradesh
    "madhya pradesh": "Madhya Pradesh",
    "मध्य प्रदेश": "Madhya Pradesh",
    "bhopal": "Madhya Pradesh",
    "भोपाल": "Madhya Pradesh",
    "indore": "Madhya Pradesh",
    "इंदौर": "Madhya Pradesh",
    "mpedistrict": "Madhya Pradesh",

    # Rajasthan
    "rajasthan": "Rajasthan",
    "राजस्थान": "Rajasthan",
    "jaipur": "Rajasthan",
    "जयपुर": "Rajasthan",
    "jodhpur": "Rajasthan",
    "emitra": "Rajasthan",

    # Tamil Nadu
    "tamil nadu": "Tamil Nadu",
    "தமிழ்நாடு": "Tamil Nadu",
    "chennai": "Tamil Nadu",
    "சென்னை": "Tamil Nadu",
    "tnega": "Tamil Nadu",

    # West Bengal
    "west bengal": "West Bengal",
    "পশ্চিমবঙ্গ": "West Bengal",
    "kolkata": "West Bengal",
    "কলকাতা": "West Bengal",

    # Karnataka
    "karnataka": "Karnataka",
    "ಕರ್ನಾಟಕ": "Karnataka",
    "bangalore": "Karnataka",
    "bengaluru": "Karnataka",

    # Andhra Pradesh
    "andhra pradesh": "Andhra Pradesh",
    "ఆంధ్ర ప్రదేశ్": "Andhra Pradesh",

    # Uttar Pradesh
    "uttar pradesh": "Uttar Pradesh",
    "उत्तर प्रदेश": "Uttar Pradesh",
    "lucknow": "Uttar Pradesh",
    "लखनऊ": "Uttar Pradesh",

    # Bihar
    "bihar": "Bihar",
    "बिहार": "Bihar",
    "patna": "Bihar",
    "पटना": "Bihar",

    # Odisha
    "odisha": "Odisha",
    "ଓଡ଼ିଶା": "Odisha",

    # Punjab
    "punjab": "Punjab",
    "ਪੰਜਾਬ": "Punjab",
    "पंजाब": "Punjab",

    # Other States
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "chhattisgarh": "Chhattisgarh",
    "goa": "Goa",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "jharkhand": "Jharkhand",
    "kerala": "Kerala",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "sikkim": "Sikkim",
    "telangana": "Telangana",
    "tripura": "Tripura",
    "uttarakhand": "Uttarakhand",
}


# P0-1: Gujarat district signals. Canonical name -> keyword variants
# (English lowercase names plus standard Gujarati-script forms, which are
# proper nouns rather than legal terminology).
GUJARAT_DISTRICTS = {
    "Ahmedabad": ["ahmedabad", "અમદાવાદ"],
    "Amreli": ["amreli", "અમરેલી"],
    "Anand": ["anand", "આણંદ"],
    "Aravalli": ["aravalli", "aravali", "અરવલ્લી"],
    "Banaskantha": ["banaskantha", "બનાસકાંઠા"],
    "Bharuch": ["bharuch", "ભરૂચ"],
    "Bhavnagar": ["bhavnagar", "ભાવનગર"],
    "Botad": ["botad", "બોટાદ"],
    "Chhota Udaipur": ["chhota udaipur", "chhota udepur", "છોટા ઉદેપુર"],
    "Dahod": ["dahod", "દાહોદ"],
    "Dang": ["dang", "ડાંગ"],
    "Devbhoomi Dwarka": ["devbhoomi dwarka", "dwarka", "દેવભૂમિ દ્વારકા", "દ્વારકા"],
    "Gandhinagar": ["gandhinagar", "ગાંધીનગર"],
    "Gir Somnath": ["gir somnath", "somnath", "ગીર સોમનાથ", "સોમનાથ"],
    "Jamnagar": ["jamnagar", "જામનગર"],
    "Junagadh": ["junagadh", "junagarh", "જૂનાગઢ"],
    "Kheda": ["kheda", "ખેડા"],
    "Kutch": ["kutch", "kachchh", "katch", "કચ્છ"],
    "Mahisagar": ["mahisagar", "મહીસાગર"],
    "Mehsana": ["mehsana", "mahesana", "મહેસાણા"],
    "Morbi": ["morbi", "મોરબી"],
    "Narmada": ["narmada", "નર્મદા"],
    "Navsari": ["navsari", "નવસારી"],
    "Panchmahal": ["panchmahal", "panchmahaal", "panchmahal", "પંચમહાલ"],
    "Patan": ["patan", "પાટણ"],
    "Porbandar": ["porbandar", "પોરબંદર"],
    "Rajkot": ["rajkot", "રાજકોટ"],
    "Sabarkantha": ["sabarkantha", "સાબરકાંઠા"],
    "Surat": ["surat", "સુરત"],
    "Surendranagar": ["surendranagar", "સુરેન્દ્રનગર"],
    "Tapi": ["tapi", "તાપી"],
    "Vadodara": ["vadodara", "baroda", "વડોદરા"],
    "Valsad": ["valsad", "વલસાડ"],
    "Vav-Tharad": ["vav-tharad", "vav tharad", "tharad", "વાવ-થરાદ", "થરાદ"],
}

# Generic sub-state administrative cues (district/taluka/village). These do
# not identify a district by themselves; they qualify a district match or
# signal that the query is locally scoped.
SUB_STATE_CUES = [
    "district", "jilla", "zilla", "જિલ્લો", "जिला",
    "taluka", "taluk", "tehsil", "તાલુકો", "तहसील",
    "village", "gaon", "ગામ", "गांव",
    "gram panchayat", "panchayat", "પંચાયત",
]

# P0-1: society-type cues. MSCS cues are checked first because they are
# more specific; a query mentioning both is treated as MSCS.
MSCS_CUES = [
    "multi-state", "multi state", "multistate", "mscs",
    "central registrar", "crcs",
    "cooperative election authority",
    "works in two states", "operates in two states",
    "operates in multiple states", "working in two states",
    "co-op ombudsman", "cooperative ombudsman",
    "બે રાજ્ય", "दो राज्यों",
]

STATE_SOCIETY_CUES = [
    "registrar of cooperative societies",
    "district registrar",
    "board of nominees",
    "gujarat co-operative societies act",
    "gujarat cooperative societies act",
    "state cooperative",
    "state co-operative",
    "સહકારી મંડળી અધિનિયમ",
]

# P1: the former subject-level Gujarat default (STATE_COMPETENT_DOMAINS
# + SUBJECT_DEFAULT_STATE, mirroring the dead Settings.selected_state)
# was removed. An unspecified state must not acquire Gujarat merely
# because the domain is Gujarat-competent: no-signal queries resolve to
# central jurisdiction (jurisdiction_source "none"), and callers that
# need jurisdiction prefer the existing INSUFFICIENT_DATA/abstention
# semantics over an invented state. Session inheritance (default_state)
# and explicit signals below are unchanged.

# P0-1/P0-2: explicit season vocabulary (English + Hindi; Gujarati season
# words are intentionally NOT included — no verified lexicon entry).
SEASON_KEYWORDS = {
    "kharif": ["kharif", "monsoon crop", "खरीफ"],
    "rabi": ["rabi", "winter crop", "रबी"],
    "zaid": ["zaid", "summer crop", "जायद"],
}

# P2-2: explicit national scope suppresses any state default.
# Matched with word boundaries ("international" must never trigger).
NATIONAL_CUES = [
    "national",
    "all india",
    "all-india",
    "central government",
    "countrywide",
]

# P0-1: central/MSCS anchor domains for the jurisdiction-first branch.
# All entries are research-verified publisher domains; every *.gov.in
# entry additionally passes the existing official-URL suffix check.
MSCS_ANCHOR_DOMAINS = [
    "cooperation.gov.in",
    "crcs.gov.in",
    "pib.gov.in",
    "gov.in",
    "nic.in",
]


def _match_keyword(keyword: str, text: str) -> bool:
    """Match one keyword against lowered query text.

    Multi-word phrases use substring matching (inflected forms still
    match); single words require word boundaries. Naive single-word
    substring matching creates known collisions ("goa" in "goat",
    "apy" in "therapy", short acronyms inside ordinary words), so it
    must not be used for semantic keywords.

    Indic exception: case suffixes agglutinate directly onto the word
    (Gujarati "ગુજરાતમાં" = Gujarat + locative "in"), and Python \\b
    does not see a boundary before combining vowel signs even for
    standalone words ("યોજના"). Non-ASCII keywords therefore also
    match as a left-anchored prefix. ASCII keywords stay strict so
    "goa" never matches "goat" — strictly narrower than substring.
    """
    if " " in keyword:
        return keyword in text
    if re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None:
        return True
    if any(ord(c) > 127 for c in keyword):
        return re.search(r"\b" + re.escape(keyword), text) is not None
    return False


# P1: high-precision scheme-code identifiers. Generic phrases such as
# "apply for" / "registration for" (2-word weight) otherwise outweigh a
# single scheme code, routing e.g. "registration for PMFBY" to schemes
# instead of pmfby. A standalone code match earns a bonus so the
# identifier decides; this weights precision, it does not reorder lists.
_DOMAIN_IDENTIFIERS: dict[str, set[str]] = {
    "pmfby": {"pmfby"},
    "schemes": {"pmjjby", "pmsby"},
}
_IDENTIFIER_BONUS = 2


def _best_key(
    scores: dict[str, int],
    matched: dict[str, list[str]],
    safety_key: str,
    order: list[str],
    prefer_longest: bool = True,
) -> str:
    """Deterministic winner for a score table with ties.

    1. Highest score wins outright.
    2. On a tie involving the safety key ("grievance"/"GRIEVANCE"),
       the safety key wins: a complaint signal must reach the
       redressal workflow rather than lose to an earlier dict entry.
    3. Otherwise (domains only) the tied entry with the longest
       matched keyword wins (most specific signal, e.g. "driving
       licence" over "apply for"). Intents keep the established
       dict-order precedence instead, so existing guidance intents
       (APPLICATION, INFORMATIONAL, ...) are unchanged.
    4. Final fallback is the existing keyword-dict order (unchanged,
       deterministic) — never a random or score-agnostic pick.
    """
    best_score = max(scores.values())
    tied = [k for k, v in scores.items() if v == best_score]
    if len(tied) == 1:
        return tied[0]
    if safety_key in tied:
        return safety_key
    position = {k: i for i, k in enumerate(order)}
    if prefer_longest:
        return max(
            tied,
            key=lambda k: (
                max((len(m) for m in matched.get(k, [])), default=0),
                -position.get(k, 0),
            ),
        )
    return min(tied, key=lambda k: position.get(k, 0))


def effective_domain(
    anchor_domain: str | None,
    classification: QueryClassification | None,
) -> str:
    """Single effective-domain rule shared by both RAG pipelines.

    The AnchorStore domain (keyword + embedding) wins whenever it is
    specific; the QueryClassifier domain only fills in when the anchor
    is empty/general. Domain 'grievance' maps to 'pacs_governance'.
    """
    res = anchor_domain or "general"
    if (
        (not anchor_domain or anchor_domain == "general")
        and classification is not None
        and classification.domain != "general"
    ):
        res = classification.domain
    if res == "grievance":
        res = "pacs_governance"
    return res



def resolve_expected_state(
    session_state: str | None,
    classification: QueryClassification | None,
) -> str | None:
    """State precedence for evidence filtering.

    An explicit state word in the query beats an inherited session
    value; an explicit national-scope claim beats it too (mirroring
    the classifier, where national suppresses session defaults).
    Otherwise the session value is used, falling back to the
    classifier's own (non-explicit) state. Absence of jurisdiction
    yields None (central-only filtering) — an assumed/default state is
    never invented here.
    """
    if classification is not None and getattr(
        classification, "national_scope", False
    ):
        return None
    if (
        classification is not None
        and getattr(classification, "jurisdiction_source", "none")
        == "explicit"
        and classification.state
    ):
        return classification.state
    if session_state:
        return session_state
    if classification is not None:
        return classification.state
    return None


class QueryClassifier:

    def classify(        self, query: str, default_state: Optional[str] = None
    ) -> QueryClassification:

        text = query.lower().strip()

        if not text:
            raise ValueError("Query cannot be empty.")

        domain_scores: dict[str, int] = {}
        domain_matched: dict[str, list[str]] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            score = 0
            matched: list[str] = []
            identifiers = _DOMAIN_IDENTIFIERS.get(domain, set())
            for keyword in keywords:
                if _match_keyword(keyword, text):
                    # Multi-word or specific keywords add proportional weight
                    score += len(keyword.split())
                    matched.append(keyword)
                    if keyword in identifiers:
                        score += _IDENTIFIER_BONUS
            if score:
                domain_scores[domain] = score
                domain_matched[domain] = matched

        if domain_scores:
            domain = _best_key(
                domain_scores, domain_matched, "grievance",
                list(DOMAIN_KEYWORDS),
            )
            highest_score = domain_scores[domain]
            confidence = min(
                1.0,
                0.55 + (highest_score * 0.1),
            )
        else:
            domain = "general"
            confidence = 0.25

        intent_scores: dict[str, int] = {}
        intent_matched: dict[str, list[str]] = {}
        for intent, keywords in INTENT_KEYWORDS.items():
            score = 0
            matched_intent: list[str] = []
            for keyword in keywords:
                if _match_keyword(keyword, text):
                    score += 1
                    matched_intent.append(keyword)
            if score:
                intent_scores[intent] = score
                intent_matched[intent] = matched_intent

        if intent_scores:
            intent = _best_key(
                intent_scores, intent_matched, "GRIEVANCE",
                list(INTENT_KEYWORDS), prefer_longest=False,
            )
        else:
            intent = "INFORMATIONAL"

        state = None
        for keyword, state_name in STATE_KEYWORDS.items():
            if _match_keyword(keyword, text):
                state = state_name
                break

        explicit_state = state is not None

        # P2-2: explicit national scope suppresses any state default.
        # Word-boundary matching so "international" never triggers it.
        national_scope = (
            not explicit_state
            and any(
                re.search(r"\b" + re.escape(cue) + r"\b", text)
                for cue in NATIONAL_CUES
            )
        )

        if not state and default_state and not national_scope:
            state = default_state

        jurisdiction_source = "none"
        assumed_state = False

        if explicit_state:
            jurisdiction_source = "explicit"
        elif state:
            # State came from the caller (session/selected state), not from
            # an explicit query signal.
            jurisdiction_source = "session"
            assumed_state = True

        # Society type: multi-state societies are under central
        # (CRCS/CEA) jurisdiction by definition and never take a state.
        society_type = _detect_society_type(text)

        # P2-2: explicit district implies its state (stronger than
        # session/default, weaker than an explicit state word).
        district_raw = _detect_district(text, "Gujarat")

        if (
            district_raw
            and not explicit_state
            and not national_scope
        ):
            state = "Gujarat"
            explicit_state = True
            jurisdiction_source = "explicit"
            assumed_state = False

        # H2 hardening: >=2 distinct explicit states + cooperative/society
        # context => multi-state society (central/CRCS jurisdiction), never
        # a silent single-state default. Comparison questions without
        # society words are unaffected (society gate below).
        if society_type is None and _has_society_context(text):
            distinct_states = _detect_explicit_states(text)
            if len(distinct_states) >= 2:
                society_type = "mscs"
                state = None
                explicit_state = False
                jurisdiction_source = "explicit"
                assumed_state = False

        if state:
            jurisdiction = "state"
        else:
            jurisdiction = "central"

        district = _detect_district(text, state)
        case_year, season = _detect_case_time(text)

        return QueryClassification(
            domain=domain,
            jurisdiction=jurisdiction,
            state=state,
            intent=intent,
            confidence=round(confidence, 2),
            district=district,
            society_type=society_type,
            case_year=case_year,
            season=season,
            jurisdiction_source=jurisdiction_source,
            assumed_state=assumed_state,
            national_scope=national_scope,
        )


def _detect_district(text: str, state: Optional[str]) -> Optional[str]:
    """Detect a Gujarat district mention. Returns the canonical name.

    District content is sparse, so detection only *targets* queries and
    ranking — it must never hard-filter evidence (see service layer).
    Non-Gujarat district vocabularies are intentionally out of scope for
    P0 (recorded limitation); only Gujarat districts are resolved.
    """
    if state is not None and state.lower() != "gujarat":
        return None
    for canonical, variants in GUJARAT_DISTRICTS.items():
        for variant in variants:
            if _match_keyword(variant, text):
                return canonical
    return None


def _detect_society_type(text: str) -> Optional[str]:
    """Detect cooperative society type: "mscs" | "state_society" | None.

    MSCS cues win on conflict because they are more specific. Unknown
    (None) means the query gives no society-type signal.
    """
    for cue in MSCS_CUES:
        if _match_keyword(cue, text):
            return "mscs"
    for cue in STATE_SOCIETY_CUES:
        if _match_keyword(cue, text):
            return "state_society"
    return None


# H2 hardening: minimal society-context gate. Only these cooperative
# words allow the >=2-states => mscs rule; comparison/economic questions
# mentioning two states never trigger it.
_SOCIETY_CONTEXT_WORDS = (
    "cooperative",
    "co-operative",
    "societ",  # society / societies stem
    "sahakari",
    "सहकारी",
    "સહકારી",
)


def _has_society_context(text: str) -> bool:
    """True when the query carries cooperative/society terminology."""
    return any(word in text for word in _SOCIETY_CONTEXT_WORDS)


def _detect_explicit_states(text: str) -> set[str]:
    """Collect distinct explicit states named in the query text."""
    found: set[str] = set()
    for keyword, state_name in STATE_KEYWORDS.items():
        if _match_keyword(keyword, text):
            found.add(state_name)
    return found


def _detect_case_time(text: str) -> tuple[Optional[int], Optional[str]]:
    """Detect an explicit case year and crop season, if reliably present.

    Only explicit mentions count: a 4-digit year (1900-2100) and the
    English/Hindi season words in SEASON_KEYWORDS. Nothing is inferred.
    """
    case_year: Optional[int] = None
    year_match = re.search(r"\b(19\d{2}|20\d{2}|2100)\b", text)
    if year_match:
        try:
            case_year = int(year_match.group(1))
        except ValueError:
            case_year = None

    season: Optional[str] = None
    for canonical, variants in SEASON_KEYWORDS.items():
        lowered = [v.lower() for v in variants]
        if any(_match_keyword(v, text) for v in lowered):
            season = canonical
            break

    return case_year, season
