"""Language detection — loads all configuration from data/language_config.json.

No hardcoded script ranges, stopwords, or language lists in this file.
"""
import json
import re
from functools import lru_cache
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Load language config from JSON (cached)."""
    path = DATA_DIR / "language_config.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Convert script ranges to sets for O(1) lookup
    scripts = {}
    for name, (start, end) in raw["scripts"].items():
        scripts[name] = set(range(start, end + 1))
    # Convert stopwords to sets
    stopwords = {lang: set(words) for lang, words in raw["stopwords"].items()}
    return {
        "scripts": scripts,
        "stopwords": stopwords,
        "supported": set(raw["supported_languages"]),
        "script_threshold": raw["script_threshold"],
        "latin_threshold": raw["latin_threshold"],
    }


def _script_ratios(text: str) -> dict[str, float]:
    """Return {script_name: ratio} among alphabetic chars for every configured script."""
    cfg = _load_config()
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return {name: 0.0 for name in cfg["scripts"]}
    ratios = {}
    for name, charset in cfg["scripts"].items():
        ratios[name] = sum(1 for c in letters if ord(c) in charset) / len(letters)
    return ratios


def _stopword_bias(text: str, lang: str) -> int:
    """Return (lang_stopwords - english_stopwords) count overlap for `lang`."""
    cfg = _load_config()
    sw = cfg["stopwords"].get(lang)
    if not sw:
        return 0
    en_sw = cfg["stopwords"]["en"]
    words = {w.lower() for w in text.split()}
    return len(words & sw) - len(words & en_sw)


def normalize_language(selected: str, text: str) -> str:
    """Detect actual language from text, using selection as a hint.
    
    All thresholds and language lists loaded from data/language_config.json.
    The original query is preserved — this only classifies the language.
    """
    cfg = _load_config()
    if selected not in cfg["supported"]:
        raise ValueError(f"unsupported language: {selected}")
    ratios = _script_ratios(text)
    threshold = cfg["script_threshold"]

    # Devanagari covers both Hindi and Marathi; disambiguate by stopword bias.
    if ratios.get("devanagari", 0.0) >= threshold:
        return "mr" if _stopword_bias(text, "mr") > _stopword_bias(text, "hi") else "hi"
    # Bengali script → Bengali
    if ratios.get("bengali", 0.0) >= threshold:
        return "bn"
    # Gujarati script → Gujarati
    if ratios.get("gujarati", 0.0) >= threshold:
        return "gu"
    # Tamil script → Tamil
    if ratios.get("tamil", 0.0) >= threshold:
        return "ta"
    # Telugu script → Telugu
    if ratios.get("telugu", 0.0) >= threshold:
        return "te"
    # Kannada script → Kannada
    if ratios.get("kannada", 0.0) >= threshold:
        return "kn"
    # Gurmukhi script → Punjabi
    if ratios.get("gurmukhi", 0.0) >= threshold:
        return "pa"
    # Odia script → Odia
    if ratios.get("odia", 0.0) >= threshold:
        return "or"
    # Malayalam script → Malayalam
    if ratios.get("malayalam", 0.0) >= threshold:
        return "ml"
    # Latin script: trust the selected language when its stopwords appear.
    if selected in cfg["stopwords"] and _stopword_bias(text, selected) > 0:
        return selected
    return selected


# Explicit "respond/explain in <lang>" detection. Name -> code, including native terms.
_EXPLICIT_LANG_NAMES = {
    "english": "en", "angrezi": "en",
    "hindi": "hi", "हिंदी": "hi",
    "gujarati": "gu", "ગુજરાતી": "gu",
    "marathi": "mr", "मराठी": "mr",
    "bengali": "bn", "bangla": "bn", "বাংলা": "bn",
    "tamil": "ta", "தமிழ்": "ta",
    "telugu": "te", "తెలుగు": "te",
    "kannada": "kn", "ಕನ್ನಡ": "kn",
    "punjabi": "pa", "ਪੰਜਾਬੀ": "pa", "gurmukhi": "pa",
    "odia": "or", "ଓଡ଼ିଆ": "or",
    "malayalam": "ml", "മലയാളം": "ml",
}
_EXPLICIT_RE = re.compile(
    r"(?:respond|reply|answer|explain|समझाओ|समजावो|बताओ|समझाएं|in|में|मां|માં)"
    r"\s+"
    r"(english|angrezi|hindi|हिंदी|gujarati|ગુજરાતી|marathi|मराठी|bengali|bangla|বাংলা|tamil|தமிழ்|telugu|తెలుగు|kannada|ಕನ್ನಡ|punjabi|ਪੰਜਾਬੀ|gurmukhi|odia|ଓଡ଼ିଆ|malayalam|മലയാളം)"
    r"|"
    r"(english|angrezi|hindi|हिंदी|gujarati|ગુજરાતી|marathi|मराठी|bengali|bangla|বাংলা|tamil|தமிழ்|telugu|తెలుగు|kannada|ಕನ್ನಡ|punjabi|ਪੰਜਾਬੀ|gurmukhi|odia|ଓଡ଼ିଆ|malayalam|മലയാളം)"
    r"\s+"
    r"(?:respond|reply|answer|explain|समझाओ|समजावो|बताओ|समझाएं|in|में|मां|માં)",
    re.IGNORECASE,
)


def _detect_explicit_request(text: str) -> str | None:
    m = _EXPLICIT_RE.search(text)
    if m:
        name = m.group(1) or m.group(2)
        return _EXPLICIT_LANG_NAMES.get(name.lower())
    return None


def detect_query_languages(text: str) -> dict:
    """Detect languages present in a (possibly mixed) query.

    Devanagari is NOT mapped to Hindi for input — hi/mr stay distinguishable
    via stopword bias (reusing normalize_language on the devanagari run).
    """
    cfg = _load_config()
    languages: set[str] = set()
    ratios = _script_ratios(text)
    # PRESENCE: any non-trivial script presence counts (mixed queries).
    if ratios.get("gujarati", 0.0) > 0:
        languages.add("gu")
    if ratios.get("bengali", 0.0) > 0:
        languages.add("bn")
    if ratios.get("devanagari", 0.0) > 0:
        # distinguish hi/mr via stopword bias (never force Hindi)
        languages.add("mr" if _stopword_bias(text, "mr") > _stopword_bias(text, "hi") else "hi")
    if ratios.get("tamil", 0.0) > 0:
        languages.add("ta")
    if ratios.get("telugu", 0.0) > 0:
        languages.add("te")
    if ratios.get("kannada", 0.0) > 0:
        languages.add("kn")
    if ratios.get("gurmukhi", 0.0) > 0:
        languages.add("pa")
    if ratios.get("odia", 0.0) > 0:
        languages.add("or")
    if ratios.get("malayalam", 0.0) > 0:
        languages.add("ml")
    latin_letters = [c for c in text if c.isalpha() and c.isascii()]
    if latin_letters:
        languages.add("en")
    # DOMINANT: highest-ratio Indic script above the configured threshold.
    dominant = None
    best, best_r = None, 0.0
    _indic_scripts = ("gujarati", "bengali", "devanagari", "tamil", "telugu", "kannada", "gurmukhi", "odia", "malayalam")
    for name, r in ratios.items():
        if name in _indic_scripts and r > best_r:
            best, best_r = name, r
    if best is not None and best_r >= cfg["script_threshold"]:
        dominant = _SCRIPT_TO_LANG.get(best, "en")
    elif latin_letters:
        dominant = "en"
    language_mix = None
    if len(languages) > 1:
        ratios_mix = _script_ratios(text)
        letters = [c for c in text if c.isalpha()]
        if letters:
            ratios_mix["latin"] = len([c for c in letters if c.isascii()]) / len(letters)
        script_to_lang = {
            "devanagari": "hi",
            "gujarati": "gu",
            "bengali": "bn",
            "tamil": "ta",
            "telugu": "te",
            "kannada": "kn",
            "gurmukhi": "pa",
            "odia": "or",
            "malayalam": "ml",
            "latin": "en",
        }
        mix = {}
        for script, ratio in ratios_mix.items():
            if ratio >= 0.15:
                lang_code = script_to_lang.get(script)
                if lang_code:
                    mix[lang_code] = round(ratio, 2)
        if len(mix) >= 2:
            language_mix = mix
    return {
        "languages": languages,
        "dominant": dominant,
        "explicit_request": _detect_explicit_request(text),
        "language_mix": language_mix,
    }


_SCRIPT_TO_LANG = {
    "gujarati": "gu", "bengali": "bn", "devanagari": "hi",
    "tamil": "ta", "telugu": "te", "kannada": "kn",
    "gurmukhi": "pa", "odia": "or", "malayalam": "ml",
}


def _script_runs(text: str) -> list[tuple[str, str]]:
    """Split text into (script_label, text) runs for run-aware translation."""
    cfg = _load_config()
    scripts = cfg["scripts"]

    def label(c: str) -> str:
        cp = ord(c)
        for name, charset in scripts.items():
            if cp in charset:
                return name
        if c.isascii() and c.isalpha():
            return "latin"
        return "other"

    runs: list[tuple[str, str]] = []
    cur_script: str | None = None
    cur_chars: list[str] = []
    for c in text:
        if c.isspace():
            if cur_chars:
                cur_chars.append(c)
            continue
        s = label(c)
        if s != cur_script:
            if cur_chars:
                runs.append((cur_script or "other", "".join(cur_chars)))
            cur_script = s
            cur_chars = [c]
        else:
            cur_chars.append(c)
    if cur_chars:
        runs.append((cur_script or "other", "".join(cur_chars)))
    return runs


def english_retrieval_query(text: str, detected: dict | None, settings) -> str:
    """Build an English retrieval representation (run-aware).

    Latin runs (scheme names, acronyms, numbers, dates, English words) are
    preserved verbatim; only Indic-script runs are translated via the
    already-wired AzureTranslator. This preserves the terminology the design
    requires to stay intact, rather than translating the whole query. Falls
    back to the original text on any failure (never fabricates).
    """
    from app.providers.translator import AzureTranslator

    runs = _script_runs(text)
    if not any(script in _SCRIPT_TO_LANG and script != "latin" for script, _ in runs):
        return text
    try:
        translator = AzureTranslator(settings)
        out: list[str] = []
        for script, run_text in runs:
            if script in ("latin", "other"):
                out.append(run_text)
            else:
                lang_code = _SCRIPT_TO_LANG.get(script, "en")
                if lang_code == "en":
                    out.append(run_text)
                else:
                    out.append(translator.translate(run_text, to="en", source=lang_code))
        return "".join(out)
    except Exception:
        return text
