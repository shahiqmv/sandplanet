"""The words of the printed HSE forms — SP-HSE-F01 safety induction and
SP-HSE-F02 warning notice — in English and the languages they print in
beside it (owner 2026-10-26: Bengali, Tamil, Sinhala, Hindi, Nepali).

One JSON file per language, the same keys in each; en.json is the source.
A form prints English, and under it the worker's language (the warning) or
the training's language (the induction). Any other language — Dhivehi, or
none set — prints English alone and the form says to explain it verbally.

A new or changed English line is added to every file at once; the tests
refuse a language file whose keys differ from en.json's.
"""
import json
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent
TRANSLATED = ("BN", "TA", "SI", "HI", "NE")


@lru_cache(maxsize=None)
def _load(code):
    return json.loads((DIR / f"{code}.json").read_text("utf-8"))


def english():
    return _load("en")


def strings(lang):
    """The form's words in `lang`, or None where the form prints English
    alone."""
    lang = (lang or "").upper()
    return _load(lang.lower()) if lang in TRANSLATED else None


# Every language a worker's forms can be set to: the five translations,
# Dhivehi (the English form, explained verbally) and English. A worker added
# from now on must have one (owner 2026-10-26).
LANGUAGE_CODES = ("BN", "TA", "SI", "HI", "NE", "DV", "EN")


def check_language(value, required=True):
    """(code, error) for the language on a worker's record."""
    code = (value or "").strip().upper()
    if not code:
        return "", ("Choose the language his forms print in." if required
                    else None)
    if code not in LANGUAGE_CODES:
        return "", "Choose a language from the list."
    return code, None
