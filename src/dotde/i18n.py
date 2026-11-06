"""Minimal translations: English and Italian, chosen from LC_ALL / LC_MESSAGES / LANG."""

import json
import os
from functools import cache
from importlib import resources

FALLBACK = "en"
SUPPORTED = ("en", "it")


def current_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            code = value.split(".")[0].split("_")[0].lower()
            return code if code in SUPPORTED else FALLBACK
    return FALLBACK


@cache
def _catalog(lang: str) -> dict[str, str]:
    try:
        text = resources.files("dotde").joinpath("locales", f"{lang}.json").read_text("utf-8")
    except (FileNotFoundError, OSError):
        return {}
    return json.loads(text)


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    """Translate `key` into the current language, falling back to English, then to the key."""
    lang = lang or current_language()
    text = _catalog(lang).get(key) or _catalog(FALLBACK).get(key) or key
    return text.format(**kwargs) if kwargs else text


def label(labels: dict[str, str] | str, lang: str | None = None) -> str:
    """Pick the right entry from a {"en": ..., "it": ...} label used in profiles."""
    if isinstance(labels, str):
        return labels
    lang = lang or current_language()
    return labels.get(lang) or labels.get(FALLBACK) or next(iter(labels.values()), "")
