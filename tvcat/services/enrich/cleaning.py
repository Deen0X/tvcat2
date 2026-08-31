"""Limpieza agresiva de títulos (adaptado de SampleCode/enrichcode/scripts/catalog_enricher.py)."""
import re
import unicodedata


def super_clean_text(text):
    """Limpia tildes, caracteres especiales y bytes rotos. Devuelve texto ASCII en minúsculas."""
    if not text:
        return ""
    text = text.replace('&', ' and ').replace("'", "")
    text = "".join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = text.lower()
    noise_patterns = [
        r'\[.*?\]',
        r'\b(audiolibro|ebook|completo|castellano|espanol|mp3|m4b|epub|pdf|scan|digital)\b',
        r'\b(por|by|escrito por)\b',
        r'\b(1080p|720p|4k|bluray|x264|h264|dual|multi|subs)\b'
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\((?:\d{4}|.{1,3})\)', '', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return " ".join(text.split())


def clean_title(title, category):
    """Limpia el título según la categoría."""
    if not title:
        return ""
    title = title.replace('&', ' and ').replace("'", "")
    t = super_clean_text(title)
    if category == 'game':
        t = re.sub(r'\b(psx|ps1|ps2|ps3|psp|n64|nds|snes|nes|genesis|gameboy|gbc|gba|full|rip)\b', '', t, flags=re.IGNORECASE)
    elif category == 'media':
        t = re.sub(r'\b(1080p|720p|4k|2160p|bluray|x264|h264|webrip|dual|multi|subs)\b', '', t, flags=re.IGNORECASE)
    elif category == 'comic':
        t = re.sub(r'\b(cbr|cbz|digital|vol|volume|issue|capitulo|completo|scan|tradumaquetado)\b', '', t, flags=re.IGNORECASE)
    return " ".join(t.split())


def clean_title_aggressive(title):
    """Limpieza agresiva para búsqueda: trunca contenedores, purga tags de región, normaliza."""
    if not title:
        return ""
    t = title.replace('_', ' ').replace('&', ' And ').replace("'", "").strip()

    t_trunc = re.split(r'[\(\[\{]', t)[0].strip()

    if not t_trunc or len(t_trunc) < 2:
        sospechosos = [
            r'gdi', r'cdi', r'iso', r'cso', r'xci', r'nsp', r'nsz', r'pkg', r'rom', r'rip',
            r'usa', r'eur', r'esp', r'jap', r'japan', r'kor', r'asia', r'eng', r'es', r'pt', r'de', r'fr', r'it', r'uk',
            r'slps', r'slpm', r'scps', r'scsj', r'sles', r'slus', r'sces', r'scus', r'bces', r'bcus', r'bljs', r'blus', r'npjb', r'npeb', r'npub', r'undub'
        ]
        t_temp = t
        for s in sospechosos:
            t_temp = re.sub(rf'[\(\[\{{]\s*{s}\s*[\)\]\}}]', '', t_temp, flags=re.IGNORECASE)
        t_temp = re.sub(r'[()\[\]{}]', ' ', t_temp)
        t_temp = " ".join(t_temp.split()).strip()
        if t_temp and len(t_temp) >= 2:
            t = t_temp
        else:
            t = t_trunc if t_trunc else t
    else:
        t = t_trunc

    t = "".join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-zA-Z0-9\s\'\"]', ' ', t)
    t = " ".join(t.split()).strip()

    ps_prefixes = "SLPS|SLPM|SCPS|SCSJ|SLES|SLUS|SCES|SCUS|BCES|BCUS|BLJS|BLUS|NPJB|NPEB|NPUB"
    regex_suffixes = rf"\s+({ps_prefixes}|\bupd\b|\bupdate\b|\bxci\b|\bnsp\b|\bnsz\b|CDPS2|\bISO\b|\bRIP\b|Season|Temporada|\bPart\b|\bParte\b|\bVol\b|\bVolume\b|Deluxe Edition|v\d+|\d{{3}}$)"
    t = re.split(regex_suffixes, t, flags=re.IGNORECASE)[0].strip()

    t = re.sub(r'[:\-._\s\'\"]+$', '', t).strip()
    return t
