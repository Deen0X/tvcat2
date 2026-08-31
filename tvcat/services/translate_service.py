"""
TVCat 2 - xTranslate System
============================
Sistema multi-idioma basado en CSV.
Uso: xTranslate("texto original") → "translated text"
"""

import csv
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

TRANSLATE_IDX = 0  # 0=español, 1=inglés, 2=francés, etc.
TRANSLATIONS_FILE = os.path.join(PROJECT_ROOT, "tvcat_translations.csv")
_translation_cache = {}
_cache_loaded = False


def set_translate_idx(idx: int):
    global TRANSLATE_IDX
    TRANSLATE_IDX = idx
    load_translations()


def xTranslate(text: str) -> str:
    global _cache_loaded
    if not _cache_loaded:
        load_translations()

    if not text:
        return text

    if text in _translation_cache:
        translated = _translation_cache[text]
        if translated:
            return translated

    _append_translation(text)
    _translation_cache[text] = ""
    return text


def load_translations():
    global _cache_loaded, _translation_cache
    _translation_cache = {}
    if not os.path.exists(TRANSLATIONS_FILE):
        _cache_loaded = True
        return

    try:
        with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=";")
            headers = next(reader, None)
            if not headers:
                _cache_loaded = True
                return
            for row in reader:
                if row and row[0]:
                    value = row[TRANSLATE_IDX] if TRANSLATE_IDX < len(row) else ""
                    _translation_cache[row[0]] = value
    except Exception as e:
        print(f" [xTranslate] Error cargando traducciones: {e}")
    _cache_loaded = True


def _append_translation(text: str):
    try:
        os.makedirs(os.path.dirname(TRANSLATIONS_FILE), exist_ok=True)
        file_exists = os.path.exists(TRANSLATIONS_FILE)
        with open(TRANSLATIONS_FILE, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            if not file_exists:
                writer.writerow(["VARIABLE", "ENG", "FRA", "DEU", "POR", "ITA", "RUS", "CHI", "JPN", "KOR"])
            writer.writerow([text] + [""] * 9)
    except Exception as e:
        print(f" [xTranslate] Error añadiendo traducción: {e}")


def get_translation_dict() -> dict:
    """Devuelve el diccionario completo para el frontend."""
    if not _cache_loaded:
        load_translations()
    return {"dict": _translation_cache, "idx": TRANSLATE_IDX}
