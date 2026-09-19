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
# Etiquetas reservadas del mensaje de COVER (nunca son entradas de lista).
_COLLECTION_RESERVED_RE = re.compile(
    r"^\s*(t[ií]tulo|titulo|title|nombre|overview|sinopsis|synopsis|descripci[oó]n|serial)\s*[:=\-]",
    re.IGNORECASE)
# Cabecera con identidad: `TVCatCollection: Rocky | SERIAL: a1b2c3d4-7`
# (nombre y serial opcionales: mensajes legacy traen el tag solo).
# También vale `TVCat Collection` (formato del mensaje de cover).
_COLLECTION_HEADER_RE = re.compile(
    r"^\s*TVCat\s*Collection\s*(?::\s*(.*?))?\s*(?:\|\s*SERIAL\s*:\s*(\S+))?\s*$",
    re.IGNORECASE)


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


def base_title(text):
    """Nombre base: normalizado sin el año final entre paréntesis
    ('Vaiana (2016)' -> 'vaiana'). Para igualdad exacta insensible al año
    del paréntesis (el año real lo confirma la columna/hint)."""
    try:
        t = normalize_title(text)
        t2 = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", t).strip()
        return t2 or t
    except Exception:
        return normalize_title(text)


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
    `!` inicial = búsqueda literal (sin saneo).
    Un mensaje con líneas-etiqueta (Title:/Overview:/...) es un COVER, no una
    lista: devuelve [] (las líneas de valor no son títulos)."""
    entries = []
    if not raw_text:
        return entries
    try:
        for _line in str(raw_text).split("\n"):
            if _line.strip() and _COLLECTION_RESERVED_RE.match(_line.strip()):
                return []
    except Exception:
        pass
    for line in str(raw_text).split("\n"):
        s = (line or "").strip()
        if not s:
            continue
        try:
            if _COLLECTION_TAG in re.sub(r"[\s_\-]+", "", s.lower()):
                continue
        except Exception:
            pass
        try:
            if _COLLECTION_RESERVED_RE.match(s):
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


def parse_collection_header(raw_text):
    """Extrae (nombre, serial) de la línea que contiene el tag.
    `TVCatCollection: Rocky | SERIAL: abc-1` -> ("Rocky", "abc-1").
    Tag solo -> ("", ""). Si no hay línea con tag -> (None, None)."""
    if not raw_text:
        return None, None
    for line in str(raw_text).split("\n"):
        s = (line or "").strip()
        if not s:
            continue
        try:
            if _COLLECTION_TAG not in re.sub(r"[\s_\-]+", "", s.lower()):
                continue
        except Exception:
            continue
        m = _COLLECTION_HEADER_RE.match(s)
        if not m:
            return "", ""
        name = (m.group(1) or "").strip()
        serial = (m.group(2) or "").strip()
        return name, serial
    return None, None


def build_collection_text(name, serial, entries):
    """Reconstruye el texto canónico de un mensaje colección:
    cabecera con identidad + líneas `AÑO; Título` en orden."""
    lines = []
    head = "TVCatCollection"
    if (name or "").strip():
        head += ": " + name.strip()
    if (serial or "").strip():
        head += " | SERIAL:" + serial.strip()
    lines.append(head)
    for e in entries or []:
        t = str((e or {}).get("title", "")).strip()
        if not t:
            continue
        y = str((e or {}).get("year", "") or "").strip()
        bang = "!" if (e or {}).get("literal") else ""
        if y and re.match(r"^\d{4}$", y):
            lines.append("%s; %s%s" % (y, bang, t))
        elif bang:
            lines.append("%s%s" % (bang, t))
        else:
            lines.append(t)
    return "\n".join(lines)


def build_collection_cover_text(name, description="", extra_tags=None):
    """Texto canónico del mensaje de COVER de una colección (lo prepara el
    editor; TGHirayi solo lo sube tal cual con la imagen):
        TVCat Collection
        Title: {nombre}

        Overview:
        {descripción}
    `extra_tags` (dict ordenado, p. ej. {"Universe": "MCU"}) añade bloques
    `Clave:\nvalor` tras el Overview para futuros usos. Sin(entries): el cover
    nunca genera ítem de colección (el parser solo acepta mensajes de texto).
    """
    name = (name or "").strip() or "Colección"
    lines = ["TVCat Collection", "Title: " + name]
    if (description or "").strip():
        lines += ["", "Overview:", (description or "").strip()]
    try:
        for k, v in (extra_tags or {}).items():
            if v is None or str(v).strip() == "":
                continue
            lines += ["", "%s:" % str(k).strip(), str(v).strip()]
    except Exception:
        pass
    return "\n".join(lines)
