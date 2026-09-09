"""
TVCat 2 - Normalización de títulos + parseo de colecciones (TVCatCollection).

Uso compartido: gateway (`/api/collection/resolve`) y cualquier plugin que
resuelva colecciones. El parser TGIndex (`scanner.py`) mantiene copias locales
equivalentes para no acoplar el path crítico de escaneo.
"""
import re
import unicodedata

_COLLECTION_TAG = "tvcatcollection"
_COLLECTION_LINE_RE = re.compile(r"^\s*(?:(\d{4})\s*;)?\s*;?\s*(!?)(.+?)\s*$")


def normalize_title(text):
    """Saneo para matching: minúsculas, sin tildes, espacios colapsados."""
    if not text:
        return ""
    try:
        t = unicodedata.normalize("NFD", str(text))
        t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
        t = t.lower()
        t = re.sub(r"\s+", " ", t).strip()
        return t
    except Exception:
        return str(text).lower().strip()


def is_collection_text(text):
    """True si el texto contiene el tag TVCatCollection (cualquier posición)."""
    if not text:
        return False
    try:
        compact = re.sub(r"[\s_\-]+", "", str(text).lower())
        return _COLLECTION_TAG in compact
    except Exception:
        return False


def parse_collection_entries(raw_text):
    """Lista ordenada [{year|None, title, literal}] desde el cuerpo del mensaje.
    `!` inicial = búsqueda literal (sin saneo)."""
    entries = []
    if not raw_text:
        return entries
    for line in str(raw_text).split("\n"):
        s = (line or "").strip()
        if not s:
            continue
        try:
            if _COLLECTION_TAG in re.sub(r"[\s_\-]+", "", s.lower()):
                continue
        except Exception:
            pass
        m = _COLLECTION_LINE_RE.match(s)
        if not m:
            continue
        year, bang, title = m.group(1), m.group(2), (m.group(3) or "").strip()
        if not title:
            continue
        entries.append({"year": year, "title": title, "literal": bool(bang)})
    return entries
