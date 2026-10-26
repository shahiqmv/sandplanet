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
