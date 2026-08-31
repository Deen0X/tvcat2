"""Scoring de similitud (SimScore en fases), adaptado de SampleCode/enrichcode."""
import re
import unicodedata


def get_match_score(title_a, title_b):
    """Calcula una puntuación de similitud robusta y en fases.
    - Match exacto saneado → 1.0
    - Discrepancia de número final → 0.0 (rechazo total)
    - Títulos ultra-cortos (< 7 chars) → solo match exacto
    - Intersección de conjuntos de palabras → |A ∩ B| / max(|A|, |B|)
    """
    if not title_a or not title_b:
        return 0.0

    def normalize_final(t):
        t = "".join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
        t = t.encode('ascii', 'ignore').decode('ascii')
        t = t.lower().replace("'", "").replace("&", "and")
        t = re.sub(r'[^a-z0-9\s]', ' ', t)
        return " ".join(t.split()).strip()

    norm_a = normalize_final(title_a)
    norm_b = normalize_final(title_b)

    if not norm_a or not norm_b:
        return 0.0

    if norm_a == norm_b:
        return 1.0

    def extract_trailing_number(text):
        m = re.search(r'\b(\d+)\b$', text)
        return int(m.group(1)) if m else None

    num_a = extract_trailing_number(norm_a)
    num_b = extract_trailing_number(norm_b)
    if num_a != num_b:
        return 0.0

    if len(norm_a) < 7:
        return 0.0

    set_a = set(norm_a.split())
    set_b = set(norm_b.split())
    intersection = set_a.intersection(set_b)
    if not intersection:
        return 0.0

    max_len = max(len(set_a), len(set_b))
    return len(intersection) / max_len
