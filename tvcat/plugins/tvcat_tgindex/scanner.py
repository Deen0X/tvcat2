"""
TVCat TGIndex — Motor de Escaneo Background
Separación total: fetch (telegram_scan) vs parse (unified_catalog).
"""

import os
import re
import sys
import json
import sqlite3
import asyncio
import difflib
from datetime import datetime
from typing import Optional

_TVCAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TVCAT_DIR not in sys.path:
    sys.path.insert(0, _TVCAT_DIR)

# Sobreescribible desde run_server_android() para redirigir la DB a filesDir en Android
_PLUGIN_DATA_DIR_OVERRIDE: Optional[str] = None

def get_plugin_db_path() -> str:
    """Devuelve la ruta real a la DB del plugin, respetando el override de Android."""
    if _PLUGIN_DATA_DIR_OVERRIDE:
        return os.path.join(_PLUGIN_DATA_DIR_OVERRIDE, "tvcat_tgindex", "data", "tvcat.db")
    return os.path.join(_TVCAT_DIR, "plugins", "tvcat_tgindex", "data", "tvcat.db")

from telethon import TelegramClient
from telethon.sessions import StringSession
from .config import load_user_config

scanner_status = {
    "status": "idle",
    "progress_percent": 0,
    "current_item": "",
    "logs": [],
    "refresh_signal": 0,
}


def add_log(msg: str):
    scanner_status["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(scanner_status["logs"]) > 200:
        scanner_status["logs"].pop(0)
    try:
        print(f" [TGINDEX SCANNER] {msg}", flush=True)
    except Exception:
        try:
            enc = sys.stdout.encoding or 'utf-8'
            print(f" [TGINDEX SCANNER] {msg.encode(enc, errors='replace').decode(enc)}")
        except Exception:
            pass


def _make_tag(text):
    """Genera un tag #sanitizado del texto dado."""
    clean = re.sub(r"[^a-zA-Z0-9\u00C0-\u024F]", "", text).lower()
    return f"#{clean}" if clean else ""


def insert_scanned_item(title, subcategory, category, description, telegram_msg_id, telegram_link, files, source=None, alt_titles=None, group_title=None, season_number=None, season_display=None, metadata=None, conn=None, tg_user_id=None):
    """Inserta o actualiza un título en unified_catalog + item_episodes."""
    should_close = False
    if conn is None:
        from tvcat.gateway import get_db_connection
        conn = get_db_connection()
        should_close = True
        
    cursor = conn.cursor()

    # Migración: asegurar columna tg_user_id (anterior a cualquier UPDATE/INSERT que la referencie)
    try:
        cursor.execute("ALTER TABLE unified_catalog ADD COLUMN tg_user_id INTEGER")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE item_episodes ADD COLUMN tg_user_id INTEGER")
    except:
        pass
    for col, typ in [("prepared_by_tghirayi", "INTEGER DEFAULT 0"), ("tghirayi_version", "TEXT DEFAULT ''"),
                     ("video_codec", "TEXT DEFAULT ''"), ("is_mkv", "INTEGER DEFAULT 0")]:
        try:
            cursor.execute(f"ALTER TABLE item_episodes ADD COLUMN {col} {typ}")
        except:
            pass
    try:
        cursor.execute("ALTER TABLE unified_catalog ADD COLUMN has_mkv INTEGER DEFAULT 0")
    except:
        pass

    effective_group = group_title or title
    group_title_flat = re.sub(r"[^a-zA-Z0-9]", "", effective_group).lower()
    item_id = f"USER-{group_title_flat[:15]}-{telegram_msg_id}"
    tag = _make_tag(title)

    # Construir info_messages con metadatos estructurados
    info_parts = [f"Tag: {tag}", f"Title: {title}"] if tag else [f"Title: {title}"]
    if metadata:
        for k, v in metadata.items():
            info_parts.append(f"{k}: {v}")
    info = "\n".join(info_parts)

    alt_json = json.dumps(alt_titles or [])

    cursor.execute("SELECT id, title, info_messages FROM unified_catalog WHERE item_id = ?", (item_id,))
    row = cursor.fetchone()
    if not row and int(telegram_msg_id) not in (-999, -1000):
        cursor.execute("SELECT id, title, info_messages FROM unified_catalog WHERE telegram_msg_id = ?", (telegram_msg_id,))
        row = cursor.fetchone()

    if row:
        cat_id = row["id"]
        actual_title = title
        if title == "Título pending":
            # Fallback 2: nombre del primer fichero sanitizado + [cat_id]
            name_from_file = ""
            if files:
                first_file = files[0]
                doc = getattr(first_file, 'document', None) or {}
                doc_info = doc.get("document") or {}
                fn = doc_info.get("original_name", "") or ""
                if not fn:
                    for attr in (doc_info.get("attributes") or []):
                        if attr.get("_") == "DocumentAttributeFilename":
                            fn = attr.get("file_name", "") or ""
                            break
                if fn:
                    fn = os.path.splitext(fn)[0]
                    fn = re.sub(r'[._]', ' ', fn).strip()
                    fn = re.sub(r'\s+', ' ', fn)
                    if fn:
                        name_from_file = fn
            # Si el bloque del cover no tiene ficheros (topo 1/2), leer desde BD
            if not name_from_file and row:
                try:
                    ep_row = cursor.execute(
                        "SELECT file_name FROM item_episodes WHERE item_id=? OR item_id=? ORDER BY episode_number ASC LIMIT 1",
                        (row["id"], str(row["id"]))
                    ).fetchone()
                    if ep_row and ep_row["file_name"]:
                        fn = os.path.splitext(ep_row["file_name"])[0]
                        fn = re.sub(r'[._]', ' ', fn).strip()
                        fn = re.sub(r'\s+', ' ', fn)
                        if fn:
                            name_from_file = fn
                except Exception:
                    pass
            if name_from_file:
                actual_title = f"{name_from_file} [{cat_id}]"
            else:
                existing_title = row["title"]
                if existing_title and not existing_title.startswith("Título pending"):
                    actual_title = existing_title
                else:
                    actual_title = f"Título {cat_id}"
        if source is not None:
            cursor.execute(
                "UPDATE unified_catalog SET title=?, description=?, telegram_link=?, subcategory=?, source=?, info_messages=?, alt_titles=?, group_title=?, group_title_flat=?, season_number=?, season_display=?, tg_user_id=COALESCE(?, tg_user_id) WHERE id=?",
                (actual_title, description, telegram_link, subcategory, source, info, alt_json, effective_group, group_title_flat, season_number, season_display, tg_user_id, cat_id),
            )
        else:
            cursor.execute(
                "UPDATE unified_catalog SET title=?, description=?, telegram_link=?, subcategory=?, info_messages=?, alt_titles=?, group_title=?, group_title_flat=?, season_number=?, season_display=?, tg_user_id=COALESCE(?, tg_user_id) WHERE id=?",
                (actual_title, description, telegram_link, subcategory, info, alt_json, effective_group, group_title_flat, season_number, season_display, tg_user_id, cat_id),
            )
    else:
        columns = ["item_id", "title", "category", "subcategory", "description", "telegram_msg_id", "telegram_link", "group_title", "group_title_flat", "info_messages", "alt_titles", "season_number", "season_display"]
        placeholders = ["?"] * len(columns)
        values = [item_id, title, category, subcategory, description, telegram_msg_id, telegram_link, effective_group, group_title_flat, info, alt_json, season_number, season_display]
        if tg_user_id is not None:
            columns.append("tg_user_id")
            placeholders.append("?")
            values.append(tg_user_id)
        if source is not None:
            columns.append("source")
            placeholders.append("?")
            values.append(source)
        cursor.execute(
            f"INSERT INTO unified_catalog ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
            values,
        )
        cat_id = cursor.lastrowid

        if title == "Título pending":
            # Fallback 2: nombre del primer fichero sanitizado + [cat_id]
            name_from_file = ""
            if files:
                first_file = files[0]
                if hasattr(first_file, 'media') and first_file.media and hasattr(first_file.media, 'document') and first_file.media.document:
                    for attr in first_file.media.document.attributes:
                        if hasattr(attr, 'file_name') and attr.file_name:
                            fn = os.path.splitext(attr.file_name)[0]
                            fn = re.sub(r'[._]', ' ', fn).strip()
                            fn = re.sub(r'\s+', ' ', fn)
                            if fn:
                                name_from_file = fn
                            break
            if name_from_file:
                actual_title = f"{name_from_file} [{cat_id}]"
            else:
                actual_title = f"Título {cat_id}"
            effective_group = actual_title
            group_title_flat = re.sub(r"[^a-zA-Z0-9]", "", actual_title).lower()
            cursor.execute(
                "UPDATE unified_catalog SET title = ?, group_title = ?, group_title_flat = ? WHERE id = ?",
                (actual_title, effective_group, group_title_flat, cat_id)
            )

    cursor.execute("SELECT MAX(episode_number) FROM item_episodes WHERE item_id = ? OR item_id = ?", (item_id, str(cat_id)))
    max_ep_row = cursor.fetchone()
    max_ep = max_ep_row[0] if max_ep_row and max_ep_row[0] is not None else 0

    for idx, msg in enumerate(files):
        cursor.execute("SELECT id FROM item_episodes WHERE (item_id = ? OR item_id = ?) AND telegram_msg_id = ?", (item_id, str(cat_id), msg.id))
        if cursor.fetchone():
            continue

        file_name = "Archivo Sin Nombre"
        file_size = 0
        duration = 0

        # Extraer info del archivo (Telethon object o _Msg wrapper)
        if hasattr(msg, "_raw_media"):
            # Dict-wrapper
            doc = msg._raw_media.get("document") or {}
            file_size = doc.get("size", 0)
            for a in doc.get("attributes", []):
                if a.get("file_name"):
                    file_name = a["file_name"]
                if a.get("duration"):
                    duration = a["duration"]
        elif hasattr(msg, "media") and msg.media:
            # Telethon object
            try:
                doc = msg.media.document
                if doc:
                    file_size = doc.size
                    for attr in doc.attributes:
                        if hasattr(attr, "file_name") and attr.file_name:
                            file_name = attr.file_name
                        if hasattr(attr, "duration") and attr.duration:
                            duration = attr.duration
            except Exception:
                pass

        ep_title = (msg.text or file_name or f"Episodio {max_ep + 1}").split("\n")[0][:80]
        ep_link = (
            f"https://t.me/c/{str(msg.chat_id).replace('-100', '')}/{msg.id}"
            if hasattr(msg, "chat_id")
            else telegram_link
        )

        max_ep += 1
        cursor.execute(
            """INSERT INTO item_episodes
               (item_id, episode_number, season_number, title, telegram_msg_id, telegram_link, duration, file_size, file_name, caption, tg_user_id, is_mkv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, max_ep, 1, ep_title, msg.id, ep_link, duration, file_size, file_name, msg.text or "", tg_user_id,
             1 if (file_name or "").lower().endswith(".mkv") else 0),
        )

    if should_close:
        conn.commit()
        conn.close()
    return cat_id



def _msg_has_image(m):
    """2026-09-04: el mensaje aporta IMAGEN (foto, preview con foto, o documento
    con mime image/*). El nombre de una imagen nunca es nombre de fichero."""
    try:
        if getattr(m, 'photo', None) is not None:
            return True
        _raw = getattr(m, '_raw_media', None)
        if _raw is None:
            _raw = getattr(m, 'document', None)
        if not isinstance(_raw, dict):
            return False
        _mt = _raw.get("_", "")
        if _mt == "MessageMediaWebPage":
            _wp = _raw.get("webpage") or {}
            return bool(_wp.get("photo")) and not bool(_wp.get("document"))
        _doc = _raw.get("document") or {}
        if isinstance(_doc, dict) and str(_doc.get("mime_type") or "").lower().startswith("image/"):
            return True
        return False
    except Exception:
        return False


def _msg_has_file(m):
    """2026-09-04: solo vídeo/audio/fichero NO imagen. Las imágenes (aunque vengan
    como documento) nunca cuentan como fichero para formar títulos."""
    try:
        if _msg_has_image(m):
            return False
        return (getattr(m, 'document', None) is not None
                or getattr(m, 'video', None) is not None
                or getattr(m, 'audio', None) is not None)
    except Exception:
        return False


def _segment_blocks(msgs):
    """Heurística file->image: segmenta mensajes en bloques {images, texts, files}.
    Frontera entre títulos = imagen (foto o documento-imagen) tras ficheros, o texto
    'tipo cover' (p. ej. '🎬 Nombre: ...') que aparece después de los ficheros del
    bloque anterior (covers donde el texto va ANTES que la portada/imagen)."""
    blocks = []
    current = {"images": [], "texts": [], "files": []}
    for msg in sorted(msgs, key=lambda x: x.id):
        is_image = msg.photo is not None
        is_file = msg.document is not None or msg.video is not None or msg.audio is not None
        is_text = bool(msg.text) and not is_image and not is_file

        if is_image:
            if current["files"]:
                blocks.append(current)
                current = {"images": [msg], "texts": [], "files": []}
            else:
                current["images"].append(msg)
        elif is_file:
            current["files"].append(msg)
        elif is_text:
            # Texto tipo cover tras los ficheros del bloque → nuevo título.
            # Evita que el PRIMER fichero del título siguiente se absorba en el bloque
            # anterior cuando su cover va 'texto antes que imagen' (link-preview sin
            # foto detectable, p. ej. MessageMediaWebPage).
            is_webpage = bool(getattr(msg, "is_webpage", False)) or bool((getattr(msg, "_raw_media", {}) or {}).get("webpage"))
            if current["files"] and (is_webpage or _looks_like_cover_text(msg.text)):
                blocks.append(current)
                current = {"images": [], "texts": [msg], "files": []}
            else:
                current["texts"].append(msg)

    if current["files"]:
        blocks.append(current)
    return blocks


def _normalize_fname_for_topo0(fname: str) -> str:
    """Normaliza nombre de fichero para comparar similitud en topología 0."""
    if not fname:
        return ""
    n = fname.lower()
    # quitar extensión final (y doble extensión tipo .zip.001)
    n = re.sub(r'\.zip\.\d{3}$', '', n)
    n = re.sub(r'\.part\d+.*$', '', n)
    n = re.sub(r'\.\d{3}$', '', n)
    n = os.path.splitext(n)[0]
    # quitar tags comunes: resolución, codec, año, etc
    n = re.sub(r'\b(1080p|720p|480p|2160p|4k|8k|x265|x264|h264|h265|hevc|avc|bluray|web[- ]?dl|hdr|dts|aac|ac3|eac3)\b', '', n)
    n = re.sub(r'\b(19|20)\d{2}\b', '', n)
    # quitar marcadores de episodio: e01, episode 01, s01e01, etc -> dejar base
    n = re.sub(r'\b(s\d+)?e\d+\b', '', n)
    n = re.sub(r'\bepisode\s*\d+\b', '', n)
    n = re.sub(r'\bpart\s*\d+\b', '', n)
    # quitar números sueltos al final tipo UniteUp1 -> UniteUp
    n = re.sub(r'[\s_\-]*\d+\s*$', '', n)
    n = re.sub(r'[\s_\.\-]+', ' ', n)
    n = re.sub(r'[^\w\s]', ' ', n)
    return n.strip()


def _similar_topo0(a: str, b: str, thresh: float = 0.75) -> bool:
    if not a or not b:
        return False
    # si uno es substring largo del otro, considerar similar
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= thresh


def _get_file_name_topo0(msg) -> str:
    try:
        doc = getattr(msg, 'document', None) or {}
        if isinstance(doc, dict):
            # dict reconstruido desde cache
            doc_info = doc.get("document") or doc
            fn = doc_info.get("original_name") or ""
            if not fn:
                for attr in (doc_info.get("attributes") or []):
                    if attr.get("_") == "DocumentAttributeFilename":
                        fn = attr.get("file_name") or ""
                        break
            if fn:
                return fn
            # fallback video/audio?
            # intentar desde _raw_media
            raw = getattr(msg, "_raw_media", {}) or {}
            if raw.get("document"):
                d = raw["document"]
                for attr in (d.get("attributes") or []):
                    if attr.get("_") == "DocumentAttributeFilename":
                        fn = attr.get("file_name") or ""
                        if fn:
                            return fn
        else:
            # objeto Telethon real
            for attr in getattr(doc, 'attributes', []) or []:
                fn = getattr(attr, 'file_name', None)
                if fn:
                    return fn
    except Exception:
        pass
    return f"file_{getattr(msg, 'id', 0)}"


_COVER_LINE_RE = re.compile(
    r"(?i)\b(?:nombre|t\u00edtulo|titulo|title|g\u00e9nero|genero|estreno|director|a\u00f1o)"
    r"\s*[:=]")


def _looks_like_cover_text(text):
    """Texto 'tipo cover' de un título nuevo: empieza con 🎬/▶, contiene claves de
    metadata (Nombre:, Género:, Título:...) o es un bloque de texto extenso."""
    if not text or not text.strip():
        return False
    t = text.strip()
    if t.startswith("\U0001f3ac") or t.startswith("\u25b6"):
        return True
    if _COVER_LINE_RE.search(t):
        return True
    return len(t) > 200


def _block_title(b):
    if b["images"] and b["images"][0].text:
        return b["images"][0].text.split("\n")[0][:60]
    if b["texts"]:
        return b["texts"][0].text.split("\n")[0][:60]
    if b["files"] and hasattr(b["files"][0].media, "document") and b["files"][0].media.document:
        for attr in b["files"][0].media.document.attributes:
            if hasattr(attr, "file_name") and attr.file_name:
                return attr.file_name.rsplit(".", 1)[0][:60]
    return "Contenido Sin Título"


def _block_desc(b):
    if b["images"] and b["images"][0].text:
        return b["images"][0].text
    if b["texts"]:
        return "\n".join(t.text for t in b["texts"])
    return ""


def _parse_block_title_desc(b, fallback_title=None, _extra_files=None):
    all_msgs = sorted(b["images"] + b["texts"] + b["files"], key=lambda x: x.id)
    first_text = ""
    for msg in all_msgs:
        if msg.text:
            first_text = msg.text
            break

    title = None
    if first_text:
        match = re.search(r"(?i)(?:title|t\u00edtulo|titulo)[ \t]*[:= \t-][ \t]*([^\n]+)", first_text)
        if match:
            title = match.group(1).strip()
            # Si el valor está vacío (ej. "Título :\n#Kamen..."), tomar siguiente línea con "#"
            if not title or title in (":", "-", ""):
                lines = [l.strip() for l in first_text.split("\n") if l.strip()]
                for idx, line in enumerate(lines):
                    if re.search(r"(?i)(?:title|t\u00edtulo|titulo)\s*[:=]", line):
                        if idx+1 < len(lines) and lines[idx+1].startswith("#"):
                            title = lines[idx+1].lstrip("#").strip().replace("_", " ")
                        break
                if not title or title in (":", "-", ""):
                    title = None

    if not title:
        # Fallback 1: primera línea del texto del cover si no es URL y no es solo "Título :"
        first_line = (first_text or "").strip().split("\n")[0].strip()
        if first_line and not re.search(r"https?://|t\.me/", first_line) and not re.match(r"(?i)^(?:title|t\u00edtulo|titulo)\s*[:=]\s*$", first_line):
            title = first_line[:120]
        elif first_text:
            # Buscar primera línea con contenido real que no sea label
            for line in (first_text or "").strip().split("\n"):
                line=line.strip()
                if not line or re.match(r"(?i)^(?:title|t\u00edtulo|titulo|serial|idioma|tama\u00f1o|formato|link|serial)\s*[:=]", line):
                    continue
                if line.startswith("#"):
                    title = line.lstrip("#").strip().replace("_", " ")[:120]
                    break
                if len(line) > 3:
                    title = line[:120]
                    break

    if not title:
        # Fallback 2: nombre del primer fichero del bloque (o _extra_files) sanitizado
        files = _extra_files if _extra_files else b.get("files")
        for msg in (files or []):
            doc = getattr(msg, 'document', None) or {}
            doc_info = doc.get("document") or {}
            fn = doc_info.get("original_name", "") or ""
            if not fn:
                for attr in (doc_info.get("attributes") or []):
                    if attr.get("_") == "DocumentAttributeFilename":
                        fn = attr.get("file_name", "") or ""
                        break
            if fn:
                fn = os.path.splitext(fn)[0]
                fn = re.sub(r'[._]', ' ', fn).strip()
                fn = re.sub(r'\s+', ' ', fn)
                if fn:
                    title = fn[:120]
                break

    if not title:
        title = fallback_title or "Título pending"

    desc = ""
    if b["images"] and b["images"][0].text:
        desc = b["images"][0].text
    else:
        desc = _block_desc(b)

    alt_titles = []
    metadata = {}
    clean_desc = ""

    if first_text:
        alt_titles = _parse_alt_titles(first_text)
        metadata, clean_desc = _extract_metadata_from_text(first_text)

    # Si no hay clean_desc, usar desc original
    if not clean_desc:
        clean_desc = desc

    group_title, season_number, season_display = _extract_group_and_season(first_text, title)

    return title, clean_desc, alt_titles, group_title, season_number, season_display, metadata


_SEASON_PATTERNS = [
    (r"(?i)\s*[-:.]?\s*season\s+(\d+)\s*$", None),          # "Title Season 2"
    (r"(?i)\s*[-:.]?\s*temporada\s+(\d+)\s*$", None),        # "Title Temporada 2"
    (r"(?i)\s*[-:.]?\s*temp\.?\s+(\d+)\s*$", None),          # "Title Temp. 2"
    (r"(?i)\s*[-:.]?\s*(\d+)(?:nd|rd|th|st)\s+season\s*$", "season_display"),  # "Title 2nd Season"
    (r"(?i)\s*[-:.]?\s*s(\d+)\s*$", None),                   # "Title S2"
    (r"(?i)\s*[-:.]?\s+(\d{1,2})\s*$", None),                # "Title 2" (number ≤ 50 at end)
]


def _deduce_season_number(text):
    """Intenta extraer un número de temporada del texto, retorna str o None."""
    if not text:
        return None
    for pat, _ in _SEASON_PATTERNS:
        m = re.search(pat, text)
        if m:
            num = int(m.group(1))
            # Para el patrón de número suelto al final, limitar a ≤ 50
            if pat == _SEASON_PATTERNS[-1][0] and num > 50:
                continue
            return str(num)
    return None


def _extract_group_and_season(first_text, title):
    """
    Extrae group_title (Main Title), season_number y season_display
    del texto del cover y/o del title.
    Retorna (group_title, season_number, season_display).
    """
    group_title = None
    season_number = None
    season_display = None

    # 1. Parsear Main Title y Season del texto del cover (si existe)
    if first_text:
        m = re.search(r"(?i)main\s*title[ \t]*[:= \t-][ \t]*(.+)", first_text)
        if m:
            group_title = m.group(1).strip()

        m = re.search(r"(?i)season[ \t]*[:= \t-][ \t]*(.+)", first_text)
        if m:
            season_number = m.group(1).strip()
            season_display = season_number

    # 2. Regla 1: Main Title + Season presentes → "Temporada X"
    if group_title and season_number:
        season_display = f"Temporada {season_number}"
        return group_title, season_number, season_display

    # 3. Regla 2: Solo Main Title → deducir season del title
    if group_title and not season_number:
        remainder = title
        gt_lower = group_title.lower().rstrip(".")
        t_lower = title.lower()
        if t_lower.startswith(gt_lower):
            remainder = title[len(gt_lower):].strip().lstrip("-:.,; ")
        season_number = _deduce_season_number(remainder) or _deduce_season_number(title)
        if season_number:
            season_display = f"Temporada {season_number}"
        elif remainder:
            season_display = remainder
        return group_title, season_number, season_display

    # 4. Regla 3: Sin Main Title ni Season → deducir del title
    # Probar cada patrón, el que matchee primero
    for pat, display_group in _SEASON_PATTERNS:
        m = re.search(pat, title)
        if m:
            num_val = m.group(1)
            season_number = num_val
            # Extraer group_title = título sin el patrón
            gt = title[:m.start()].strip().rstrip("-:.,; ")
            group_title = gt if gt else title
            if display_group:
                try:
                    int(num_val)
                    season_display = f"Temporada {num_val}"
                except ValueError:
                    season_display = m.group(0).strip()
            else:
                # Intentar parsear num_val como entero para display numérico
                try:
                    int(num_val)
                    season_display = f"Temporada {num_val}"
                except ValueError:
                    season_display = num_val
            return group_title, season_number, season_display

    # 5. Sin nada deducible
    return title, None, None


def _parse_alt_titles(text):
    """Extrae títulos alternativos del texto del cover.
    Acepta: Alt, Alt., Alt Title, Alt. Title, Title Alt, Title Alt.,
    Alternative, Syn, Syn., Sinónimo, synonym, Title Alt1, Title Alt2..."""
    if not text:
        return []
    alts = re.findall(
        r"(?i)(?:title\s+alt\d*\b\.?|alt[\s.]*title|alt[\s.]*|alternative|syn[\s.]*|sin[oó]nimo|synonym)\s*[:=\s\-]\s*(.+)",
        text
    )
    return [a.strip().rstrip(",") for a in alts if a.strip()]


_COVER_LABELS = [
    r"(?i)#\S+",
    r"(?i)title\s*[:=\s\-].*",
    r"(?i)main\s*title\s*[:=\s\-].*",
    r"(?i)title\s+alt\d*\b\.?\s*[:=\s\-].*",
    r"(?i)alt[\s.]*title\s*[:=\s\-].*",
    r"(?i)alt[\s.]*\s*[:=\s\-].*",
    r"(?i)alternative\s*[:=\s\-].*",
    r"(?i)syn[\s.]*\s*[:=\s\-].*",
    r"(?i)sin[oó]nimo\s*[:=\s\-].*",
    r"(?i)synonym\s*[:=\s\-].*",
    r"(?i)season\s*[:=\s\-].*",
    r"(?i)episodes?\s*[:=\s\-].*",
    r"(?i)year\s*[:=\s\-].*",
    r"(?i)type\s*[:=\s\-].*",
    r"(?i)rating\s*[:=\s\-].*",
    r"(?i)votes?\s*[:=\s\-].*",
    r"(?i)genres?\s*[:=\s\-].*",
    r"(?i)synopsis\s*[:=\s\-]*",
]


def _extract_metadata_from_text(text):
    """
    Extrae campos estructurados del texto del cover y retorna:
      metadata: dict con year, rating, episodes, type, votes, genres
      clean_desc: texto del cover sin las líneas de tags/labels
    """
    if not text:
        return {}, ""

    metadata = {}

    # Extraer campos específicos
    m = re.search(r"(?i)year\s*[:=\s\-]\s*(\d{4})", text)
    if m:
        metadata["year"] = m.group(1)

    m = re.search(r"(?i)rating\s*[:=\s\-]\s*([\d.]+)", text)
    if m:
        try:
            metadata["rating"] = float(m.group(1))
        except ValueError:
            metadata["rating"] = m.group(1)

    m = re.search(r"(?i)episodes?\s*[:=\s\-]\s*(\d+)", text)
    if m:
        metadata["episodes"] = int(m.group(1))

    m = re.search(r"(?i)type\s*[:=\s\-]\s*(.+)", text)
    if m:
        val = m.group(1).strip()
        if val.lower() not in ("n/a", "na", "none", ""):
            metadata["type"] = val

    m = re.search(r"(?i)votes?\s*[:=\s\-]\s*([\d.,]+)", text)
    if m:
        metadata["votes"] = m.group(1).replace(",", "")

    m = re.search(r"(?i)genres?\s*[:=\s\-]\s*(.+)", text)
    if m:
        val = m.group(1).strip()
        # Cortar en el primer label conocido (p.ej. 'Synopsis:') que no forma parte de los géneros
        val = re.split(
            r"(?i)\s+(?:synopsis|sinopsis|descripci[oó]n|rating|votes|votos|episodes?|episodios?"
            r"|type|title|year|a[ñn]o|season|temporada|duration|duraci[oó]n|categor[ií]a?s?|tags?)\s*[:=]",
            val, maxsplit=1)[0]
        # Normalizar términos corruptos conocidos
        val = val.replace("Senien", "Seinen").replace("sENIEN", "seinen").replace(", Serie de TV", "").replace(", serie de tv", "")
        # Separar por cualquier carácter que no sea letra ni espacio
        val = ", ".join([t for t in re.split(r"[,./:\;\-()\[\]]+", val) if t.strip()])
        if val.lower() not in ("n/a", "na", "none", ""):
            metadata["genres"] = val

    # Limpiar descripción: remover líneas que matchean labels
    lines = text.split("\n")
    clean_lines = []
    in_synopsis = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Si estamos dentro de Synopsis, el contenido se mantiene
        if re.match(r"(?i)synopsis\s*[:=\s\-]*", stripped):
            in_synopsis = True
            rest = re.sub(r"(?i)synopsis\s*[:=\s\-]*", "", stripped).strip()
            if rest:
                clean_lines.append(rest)
            continue
        if in_synopsis:
            clean_lines.append(stripped)
            continue
        # Saltar líneas que son tags/labels
        skip = False
        for pat in _COVER_LABELS:
            if re.match(pat + r"\s*$", stripped) or re.match(pat, stripped):
                skip = True
                break
        if not skip:
            clean_lines.append(stripped)

    clean_desc = "\n".join(clean_lines).strip()
    return metadata, clean_desc


# ---------------------------------------------------------------------------
# PARSE: lee telegram_message_cache (central), aplica topología, actualiza unified_catalog
# ---------------------------------------------------------------------------

async def parse_topology(scan_id, stop_event=None):
    """
    Lee telegram_scan para un scan config dado, aplica la topología
    y actualiza unified_catalog + item_episodes.
    Ejecuta en hilo separado para no bloquear el event loop.
    Retorna (new_count, updated_count).
    """
    if stop_event and stop_event.is_set():
        return (0, 0)

    def _sync():
        from tvcat.gateway import get_db_connection
        conn_sys = get_db_connection(system=True)
        conn_sys.row_factory = sqlite3.Row
        cur_sys = conn_sys.cursor()
        cur_sys.execute("SELECT * FROM tvcat_scanned_channels WHERE id = ?", (scan_id,))
        ch = cur_sys.fetchone()
        conn_sys.close()
        if not ch:
            add_log(f"  ⚠️ parse_topology: scan config #{scan_id} no encontrado.")
            return (0, 0)

        ch = dict(ch)
        name = ch["display_name"]
        topo = ch["topology_type"]
        topic_id = ch.get("topic_id")
        topic_only = ch.get("topic_only", 0)
        content_type = ch.get("content_type") or "media"
        custom_sub = ch.get("custom_subcategory")
        subcat = custom_sub.strip() if custom_sub and custom_sub.strip() else name
        # Si topic_only y hay nombre de topic, la subcategoría es el nombre del topic
        if topic_only:
            topic_name = (ch.get("topic_name") or "").strip()
            if topic_name:
                subcat = topic_name
        category_map = {"media": "media", "ebook": "kiosko", "audiolibro": "media", "game": "game"}
        category = (ch.get("category") or "").strip() or category_map.get(content_type, "media")
        source_tag = f"scan_{scan_id}"
        # Leer mensajes del caché central (telegram_message_cache)
        conn_cache = get_db_connection()
        conn_cache.row_factory = sqlite3.Row
        cur_cache = conn_cache.cursor()

        # Obtener channel_id del caché central
        cur_cache.execute("SELECT DISTINCT channel_id FROM telegram_message_cache")
        all_channels = [r["channel_id"] for r in cur_cache.fetchall()]

        # Normalizar channel_id de la configuración
        raw_cid = ch["channel_id"]
        # Telethon entity.id puede devolver el ID puro o con -100
        variants = set()
        variants.add(raw_cid)
        variants.add(str(raw_cid))
        variants.add(raw_cid.lstrip("-"))
        variants.add(raw_cid.replace("-100", "").replace("-", ""))
        if raw_cid.lstrip("-").isdigit():
            bare = raw_cid.lstrip("-")
            variants.add(bare)
            variants.add(f"-100{bare}")
            variants.add(f"100{bare}")
        # También integer comparison si es posible
        try:
            variants.add(str(int(raw_cid)))
        except ValueError:
            pass

        # Buscar el channel_id que corresponda
        scan_channel_id = None
        for cid in all_channels:
            if cid in variants:
                scan_channel_id = cid
                break

        if not scan_channel_id:
            print(f" [PARSE TOPOLOGY] '{name}': no match. raw_cid={raw_cid!r}, stored_ids={all_channels[:10]}, variants={variants}")

            conn_cache.close()
            add_log(f"  ℹ️ '{name}': sin datos en el caché aún.")
            return (0, 0)

        cur_cache.execute(
            "SELECT * FROM telegram_message_cache WHERE channel_id = ? ORDER BY msg_id ASC",
            (scan_channel_id,)
        )

        raw_rows = cur_cache.fetchall()
        conn_cache.close()
        max_scan_msg_id = max((r["msg_id"] for r in raw_rows), default=0) if raw_rows else 0

        if not raw_rows:
            return (0, 0)

        # Reconstruir objetos mensaje desde JSON (solo necesitamos photo, document, video, audio, text, id, reply_to)
        import json

        add_log(f"  🔄 Parseando {len(raw_rows)} mensajes para '{name}' (topo {topo})...")

        msgs = []
        for r in raw_rows:
            try:
                d = json.loads(r["message"])
                media_d = d.get("media") or {}
                media_type = media_d.get("_", "")

                # Envoltura simple con atributos planos (sin dependencia de Telethon)
                class _Msg:
                    pass
                m = _Msg()
                m.id = d.get("id", 0)
                m.text = d.get("message") or ""
                # Detectar imagen (2026-09-04): vale foto directa, preview de enlace
                # con foto, o documento-imagen (foto enviada como fichero). El orden
                # texto/imagen dentro del mensaje es irrelevante: Telegram lo manda
                # como una unidad (media + caption). Si el webpage trae document
                # (link a un fichero), NO es cover → se trata como contenido.
                _is_photo = media_type == "MessageMediaPhoto"
                if not _is_photo and media_type == "MessageMediaWebPage":
                    _wp = media_d.get("webpage") or {}
                    if _wp.get("photo") and not _wp.get("document"):
                        _is_photo = True
                if not _is_photo and media_type == "MessageMediaDocument":
                    _doc = media_d.get("document") or {}
                    _mime = str(_doc.get("mime_type") or "").lower()
                    if _mime.startswith("image/"):
                        _is_photo = True
                m.photo = media_d if _is_photo else None
                m.document = media_d if media_type == "MessageMediaDocument" else None
                m.video = None
                m.audio = None
                m._raw_media = media_d  # guardamos el dict original
                m._topic_id = r["topic_id"]
                m._msg_id = r["msg_id"]
                # Normalizar: quitar -100 para obtener el ID limpio usado en enlaces
                norm = scan_channel_id.replace("-100", "").lstrip("-") if scan_channel_id else "0"
                m.chat_id = int(norm) if norm.isdigit() else 0
                msgs.append(m)
            except Exception:
                pass

        if not msgs:
            return (0, 0)

        # Filtro por rango de msg_id del scan-item (Ghibli 19-42) y por topic
        try:
            start_id = int(ch.get("start_msg_id") or 1)
        except:
            start_id = 1
        try:
            end_id = int(ch.get("end_msg_id") or 0)
        except:
            end_id = 0
        # Recalcular max_scan_msg_id dentro del rango (para last_scanned_msg_id)
        if end_id and end_id > 0:
            max_scan_msg_id = min(max_scan_msg_id, end_id)
        # Filtrar msgs al rango configurado
        if start_id > 1 or (end_id and end_id > 0):
            msgs = [m for m in msgs if m.id >= start_id and (end_id == 0 or m.id <= end_id)]
            if not msgs:
                add_log(f"  ℹ️ '{name}': sin mensajes en rango {start_id}-{end_id if end_id else '∞'}")
                return (0, 0)

        # Filtro por topic_id cuando topic_only está activo (todas las topologías)
        if topic_only and topic_id is not None:
            msgs = [m for m in msgs if m._topic_id == topic_id]
            if not msgs:
                add_log(f"  ℹ️ '{name}': sin mensajes en topic {topic_id} dentro del rango")
                return (0, 0)

        # Normalizar para enlaces t.me/c/X: quitar -100 y signo, usar ID positivo limpio
        entity_id_str = scan_channel_id.replace("-100", "").lstrip("-") if scan_channel_id else "0"
        new_count = 0

        # 2. Optimización: conexión única a la base de datos del PLUGIN y una transacción global
        import sqlite3 as _sqlite3
        _db_path = get_plugin_db_path()
        conn_central = _sqlite3.connect(_db_path, timeout=30)
        conn_central.row_factory = _sqlite3.Row
        conn_central.execute("PRAGMA busy_timeout=30000")
        conn_central.execute("BEGIN IMMEDIATE")
        try:
            # ---- TOPOLOGÍA 1 (plano) ----
            if topo == 1:
                blocks = _segment_blocks(msgs)
                for i, b in enumerate(blocks):
                    # Si el bloque actual tiene cover pero no ficheros, y el siguiente bloque sí tiene,
                    # pasar los ficheros del siguiente para que el fallback de título pueda usarlos
                    block_files = b["files"]
                    if not block_files and b["images"] and i + 1 < len(blocks):
                        next_b = blocks[i + 1]
                        if next_b["files"]:
                            block_files = next_b["files"]
                    title, desc, alt_titles, grp, sn, sd, md = _parse_block_title_desc(b, fallback_title=name, _extra_files=block_files)
                    first_photo = b["images"][0].id if b["images"] else None
                    cover_id = first_photo if first_photo else (b["files"][0].id if b["files"] else 0)
                    link = f"https://t.me/c/{entity_id_str}/{cover_id}"
                    cat_id = insert_scanned_item(title, subcat, category, desc, cover_id, link, b["files"], source=source_tag, alt_titles=alt_titles, group_title=grp, season_number=sn, season_display=sd, metadata=md, conn=conn_central)
                    new_count += 1

            # ---- TOPOLOGÍA 0/4 (automática por patrón de nombre de fichero) ----
            elif topo == 4 or topo == 0:
                # Agrupa por fichero similar (75%), con pending cover (última imagen)
                has_topics = any(getattr(m, "_topic_id", None) not in (None, 0) for m in msgs)
                if has_topics:
                    topic_groups = {}
                    for m in msgs:
                        tid = m._topic_id or 0
                        topic_groups.setdefault(tid, []).append(m)
                    groups_to_process = list(topic_groups.items())
                else:
                    groups_to_process = [(0, msgs)]
                for tid, tmsgs in groups_to_process:
                    tmsgs_sorted = sorted(tmsgs, key=lambda x: x.id)
                    # subcategoría por topic si hay topics
                    current_subcat = subcat if not has_topics or tid == 0 else f"{subcat} — Tema #{tid}"
                    pending_cover = None
                    current_group = None
                    title_groups = []
                    for m in tmsgs_sorted:
                        # 2026-09-04: imágenes (foto/preview/documento-imagen) solo
                        # pueden ser cover, nunca fichero de título.
                        is_image = _msg_has_image(m)
                        is_file = _msg_has_file(m)
                        if is_image:
                            if current_group and current_group["files"]:
                                title_groups.append(current_group)
                                current_group = None
                            pending_cover = m
                            continue
                        if is_file:
                            fname = _get_file_name_topo0(m)
                            norm = _normalize_fname_for_topo0(fname)
                            if current_group is None:
                                cover_id = pending_cover.id if pending_cover else -1000
                                current_group = {"cover_msg": pending_cover, "cover_id": cover_id, "files": [m], "pattern_norm": norm, "fname": fname}
                                pending_cover = None
                            else:
                                # si hay pending cover, forzar cierre previo (imagen intercala títulos)
                                # ya manejado arriba, aquí solo comparar patrón
                                if _similar_topo0(current_group["pattern_norm"], norm, 0.75):
                                    current_group["files"].append(m)
                                else:
                                    title_groups.append(current_group)
                                    cover_id = pending_cover.id if pending_cover else -1000
                                    current_group = {"cover_msg": pending_cover, "cover_id": cover_id, "files": [m], "pattern_norm": norm, "fname": fname}
                                    pending_cover = None
                            continue
                    if current_group and current_group["files"]:
                        title_groups.append(current_group)
                    add_log(f"  📦 Topo4 topic {tid}: {len(title_groups)} grupos (msgs {len(tmsgs_sorted)}, pending_final={pending_cover.id if pending_cover else None})")
                    for g in title_groups:
                        files = g["files"]
                        cover_msg = g["cover_msg"]
                        cover_id = g["cover_id"]
                        add_log(f"    → Grupo cover {cover_id} files {len(files)}: {_get_file_name_topo0(files[0])[:40]}")
                        # Título: si hay cover con texto, usar lógica existente, si no usar nombre de fichero
                        if cover_msg and getattr(cover_msg, "text", None):
                            block = {"images": [cover_msg], "texts": [], "files": files}
                            title, desc, alt_titles, grp, sn, sd, md = _parse_block_title_desc(block, fallback_title=files[0].id if files else name, _extra_files=files)
                            if not title or title == "Título pending":
                                title = os.path.splitext(_get_file_name_topo0(files[0]))[0][:60]
                                title = re.sub(r'[._]', ' ', title).strip()
                                desc = ""
                                alt_titles = []
                                grp = title
                                sn = None
                                sd = None
                                md = {}
                        else:
                            # sin cover o sin texto -> nombre de fichero
                            base = os.path.splitext(_get_file_name_topo0(files[0]))[0][:60]
                            title = re.sub(r'[._]', ' ', base).strip() or "Título sin nombre"
                            desc = ""
                            alt_titles = []
                            grp = title
                            sn = None
                            sd = None
                            md = {}
                        # Si cover es genérico -999/-1000, link debe apuntar al primer fichero (no a -999)
                        link_tid = tid if has_topics and tid != 0 else None
                        if cover_id in (-999, -1000):
                            link_msg = files[0].id if files else 0
                            if link_tid:
                                link = f"https://t.me/c/{entity_id_str}/{link_tid}/{link_msg}"
                            else:
                                link = f"https://t.me/c/{entity_id_str}/{link_msg}"
                        else:
                            if link_tid:
                                link = f"https://t.me/c/{entity_id_str}/{link_tid}/{cover_id}"
                            else:
                                link = f"https://t.me/c/{entity_id_str}/{cover_id}"
                        try:
                            cat_id = insert_scanned_item(title, current_subcat, category, desc, cover_id, link, files, source=source_tag, alt_titles=alt_titles, group_title=grp, season_number=sn, season_display=sd, metadata=md, conn=conn_central)
                            new_count += 1
                        except Exception as e:
                            add_log(f"  ❌ Error insertando '{title}' cover {cover_id}: {e}")
                            import traceback; traceback.print_exc()

            # ---- TOPOLOGÍA 3 (cada topic = un título) ----
            elif topo == 3:
                topic_groups = {}
                for m in msgs:
                    tid = m._topic_id or 0
                    topic_groups.setdefault(tid, []).append(m)

                for tid, tmsgs in topic_groups.items():
                    blocks = _segment_blocks(tmsgs)
                    if not blocks:
                        continue
                    info_block = blocks[0]
                    # Solo generar item si el primer bloque tiene imagen de portada
                    if not info_block["images"]:
                        continue
                    content_files = []
                    for b in blocks:
                        content_files.extend(b["files"])
                    title, desc, alt_titles, grp, sn, sd, md = _parse_block_title_desc(info_block, fallback_title="Sin título", _extra_files=content_files)
                    # cover del primer contenido real (imagen o archivo), siempre es msg_id válido
                    cover_id = next((img.id for b in blocks for img in b["images"]), None)
                    if not cover_id:
                        continue
                    if not content_files:
                        continue
                    link = f"https://t.me/c/{entity_id_str}/{tid}/{cover_id}"
                    cat_id = insert_scanned_item(title, subcat, category, desc, cover_id, link, content_files, source=source_tag, alt_titles=alt_titles, group_title=grp, season_number=sn, season_display=sd, metadata=md, conn=conn_central)
                    new_count += 1

            # ---- TOPOLOGÍA 2 (topics = categorías, múltiples títulos por topic) ----
            elif topo == 2:
                if topic_id is not None:
                    blocks = _segment_blocks(msgs)
                    for b in blocks:
                        title, desc, alt_titles, grp, sn, sd, md = _parse_block_title_desc(b)
                        first_photo = b["images"][0].id if b["images"] else None
                        cover_id = first_photo if first_photo else (b["files"][0].id if b["files"] else 0)
                        link = f"https://t.me/c/{entity_id_str}/{cover_id}"
                        cat_id = insert_scanned_item(title, subcat, category, desc, cover_id, link, b["files"], source=source_tag, alt_titles=alt_titles, group_title=grp, season_number=sn, season_display=sd, metadata=md, conn=conn_central)
                        new_count += 1
                else:
                    topic_groups = {}
                    for m in msgs:
                        tid = m._topic_id or m.id
                        topic_groups.setdefault(tid, []).append(m)
                    for tid, tmsgs in topic_groups.items():
                        blocks = _segment_blocks(tmsgs)
                        tname = f"Tema #{tid}"
                        for b in blocks:
                            title, desc, alt_titles, grp, sn, sd, md = _parse_block_title_desc(b, fallback_title=tname)
                            first_photo = b["images"][0].id if b["images"] else None
                            cover_id = first_photo if first_photo else (b["files"][0].id if b["files"] else 0)
                            current_subcat = f"{subcat} — {tname}"
                            link = f"https://t.me/c/{entity_id_str}/{cover_id}"
                            cat_id = insert_scanned_item(title, current_subcat, category, desc, cover_id, link, b["files"], source=source_tag, alt_titles=alt_titles, group_title=grp, season_number=sn, season_display=sd, metadata=md, conn=conn_central)
                            new_count += 1
            
            # 3. Purgar duplicados viejos con cover genérico absorbidos por otro
            # título con cover real (restos de scans con topics rotos). Acotado a
            # este scan (source_tag): episodios del genérico TODOS en otro item.
            try:
                _stale = conn_central.execute("SELECT item_id FROM unified_catalog WHERE source=? AND telegram_msg_id IN (-999,-1000)", (source_tag,)).fetchall()
                for _sr in _stale:
                    _sid = _sr[0]
                    _eps = [e[0] for e in conn_central.execute("SELECT telegram_msg_id FROM item_episodes WHERE item_id=?", (_sid,)).fetchall() if e[0]]
                    if not _eps:
                        continue
                    _ph = ",".join("?" for _ in _eps)
                    _others = conn_central.execute("SELECT DISTINCT item_id FROM item_episodes WHERE item_id!=? AND telegram_msg_id IN (%s)" % _ph, tuple([_sid] + _eps)).fetchall()
                    for _or in _others:
                        _oid = _or[0]
                        _cnt = conn_central.execute("SELECT COUNT(*) FROM item_episodes WHERE item_id=? AND telegram_msg_id IN (%s)" % _ph, tuple([_oid] + _eps)).fetchone()[0]
                        _oc = conn_central.execute("SELECT telegram_msg_id FROM unified_catalog WHERE item_id=?", (_oid,)).fetchone()
                        if _cnt == len(_eps) and _oc and int(_oc[0]) not in (-999, -1000):
                            conn_central.execute("DELETE FROM item_episodes WHERE item_id=?", (_sid,))
                            conn_central.execute("DELETE FROM unified_catalog WHERE item_id=?", (_sid,))
                            add_log(f"  🧹 Duplicado genérico purgado: {_sid} (absorbido por {_oid})")
                            break
            except Exception as _e:
                add_log(f"  (purga duplicados omitida: {_e})")

            # 4. Guardar el progreso en el canal del sistema
            if max_scan_msg_id > 0:
                conn_sys = get_db_connection(system=True)
                conn_sys.execute("UPDATE tvcat_scanned_channels SET last_scanned_msg_id = ? WHERE id = ?", (max_scan_msg_id, scan_id))
                conn_sys.commit()
                conn_sys.close()

            conn_central.commit()
        except Exception as e:
            conn_central.rollback()
            raise e
        finally:
            conn_central.close()

        return (new_count, 0)

    return await asyncio.to_thread(_sync)


# ---------------------------------------------------------------------------
# SCAN: fetch puro de Telegram → telegram_scan
# ---------------------------------------------------------------------------

async def _scan_channel(account_id, ch, idx, total):
    """Escanea un canal/topic vía TelegramService (caché central), devuelve el último msg_id."""
    from services.telegram_service import get_telegram_service

    ch_id = ch["channel_id"]
    name = ch["display_name"]
    topo = ch["topology_type"]
    end_id = ch.get("end_msg_id") or 0
    topic_id = ch.get("topic_id")
    topic_only = ch.get("topic_only", 0)

    raw_ch_id = ch_id
    if raw_ch_id.isdigit():
        raw_ch_id = f"-100{raw_ch_id}"

    # Último msg_id escaneado desde el caché central (fuente de verdad)
    start_msg_id = ch.get("start_msg_id") or 1
    # 2026-09-04: sanear filas con topic NULL en el rango (wipe histórico por
    # guardados sin topic: covers/thumbs/refresh). Se refetchean con topic
    # correcto en este scan; UPSERT ya impide nuevos wipes.
    try:
        from services.cache_keys import canon_channel as _cc
        _canon = _cc(raw_ch_id)
        _c0 = get_db_connection()
        _end0 = end_id if end_id and end_id > 0 else 999999999
        _del = _c0.execute("DELETE FROM telegram_message_cache WHERE channel_id=? AND topic_id IS NULL AND msg_id>=? AND msg_id<=?", (_canon, start_msg_id, _end0))
        _c0.commit()
        if _del.rowcount:
            add_log(f"  🧹 Saneo topics: {_del.rowcount} filas NULL re-fetch en rango.")
        _c0.close()
    except Exception as _e:
        add_log(f"  (saneo topics omitido: {_e})")
    last_id = _get_last_cached_id(raw_ch_id)
    # En escaneo limpio el caché se vacía (last_id=0): respetar el mensaje de inicio configurado.
    if last_id < start_msg_id - 1:
        last_id = start_msg_id - 1

    log_suffix = f" (Topic {topic_id})" if topic_id is not None else ""
    add_log(f"🔄 Escaneando '{name}' ({raw_ch_id}){log_suffix} — Topología {topo}")

    if end_id > 0 and last_id >= end_id:
        add_log(f"  ℹ️ '{name}' ya escaneado hasta el límite ({end_id}).")
        return last_id

    add_log(f"  📊 Incremental desde msg_id={last_id}")

    # Header del topic solo si topic_only está activo y hay topic_id
    header_msg_id = None
    effective_topic = None
    if topic_only and topic_id is not None:
        if topo != 3:
            header_msg_id = int(topic_id)
        effective_topic = topic_id

    api_id, api_hash, session_string, _uname = _resolve_account_creds(account_id)
    if not api_id or not api_hash or not session_string:
        add_log(f"❌ Credenciales no válidas para la cuenta #{account_id}.")
        return last_id

    def _progress(saved):
        scanner_status["progress_percent"] = min(99, int((saved / 200) * 50) + 10)
        scanner_status["current_item"] = f"Escaneando '{name}': {saved} mensajes guardados..."

    service = get_telegram_service()
    try:
        saved = await asyncio.wait_for(
            service.scan_messages(
                channel_id=raw_ch_id,
                from_id=last_id,
                to_id=end_id if end_id > 0 else None,
                topic_id=effective_topic,
                session_string=session_string,
                api_id=api_id,
                api_hash=api_hash,
                header_msg_id=header_msg_id,
                on_batch=_progress,
            ),
            timeout=180,
        )
    except asyncio.TimeoutError:
        add_log(f"  ❌ Timeout escaneando '{name}' (180s).")
        return last_id
    except Exception as e:
        add_log(f"  ❌ Error escaneando '{name}': {e}")
        return last_id

    max_id = _get_last_cached_id(raw_ch_id)
    add_log(f"  ✅ Canal '{name}': {saved} mensajes nuevos guardados (último msg #{max_id}).")
    return max_id


def _get_last_cached_id(channel_id: str) -> int:
    """Último msg_id cacheado en telegram_message_cache (central) para un canal."""
    from tvcat.gateway import get_db_connection
    try:
        conn = get_db_connection()
        bare = channel_id.replace("-100", "").lstrip("-")
        variants = {channel_id, bare, f"-100{bare}"}
        last = 0
        for vid in variants:
            row = conn.execute("SELECT MAX(msg_id) FROM telegram_message_cache WHERE channel_id = ?", (vid,)).fetchone()
            val = row[0] if row and row[0] else 0
            if val > last:
                last = val
        conn.close()
        return last
    except Exception:
        return 0


def _resolve_account_creds(account_id):
    """Resuelve (api_id, api_hash, session_string, username) para un account_id de tvcat_telegram_accounts (-1 = Principal)."""
    from tvcat.gateway import get_db_connection
    api_id, api_hash, global_session = _resolve_api_creds()
    if account_id == -1:
        return api_id, api_hash, global_session, "Principal"
    try:
        conn = get_db_connection(system=True)
        row = conn.execute("SELECT session_string, username FROM tvcat_telegram_accounts WHERE id = ?", (account_id,)).fetchone()
        conn.close()
        if not row or not row[0]:
            return None, None, None, None
        return api_id, api_hash, row[0], row[1]
    except Exception:
        return None, None, None, None


async def _has_scan_data(channel_id: str) -> bool:
    """Verifica si telegram_message_cache tiene mensajes guardados para un canal."""
    from tvcat.gateway import get_db_connection
    bare = channel_id.replace("-100", "").lstrip("-")
    try:
        conn = get_db_connection()
        cnt = conn.execute(
            "SELECT COUNT(*) FROM telegram_message_cache WHERE channel_id IN (?, ?, ?)",
            (channel_id, bare, f"-100{bare}")
        ).fetchone()[0]
        conn.close()
        return cnt > 0
    except Exception:
        return False


async def _parse_loop(scan_ids, stop_event):
    """Cada 3s, solo parsea si telegram_scan tiene datos."""
    import sqlite3
    while not stop_event.is_set():
        try:
            if scanner_status.get("parse_pending"):
                scanner_status["parse_pending"] = False
                for sid in list(scan_ids):
                    if stop_event.is_set():
                        break
                    # Solo parsear si hay mensajes guardados
                    try:
                        from tvcat.gateway import get_db_connection
                        sys_conn = get_db_connection(system=True)
                        sys_row = sys_conn.execute("SELECT channel_id FROM tvcat_scanned_channels WHERE id = ?", (sid,)).fetchone()
                        sys_conn.close()
                        if sys_row and not await _has_scan_data(sys_row[0]):
                            continue
                    except Exception:
                        pass
                    n, _ = await parse_topology(sid, stop_event)
                    if n > 0:
                        scanner_status["refresh_signal"] = scanner_status.get("refresh_signal", 0) + n
                        scanner_status["current_item"] = f"+{n} título(s) nuevos"
        except Exception as e:
            print(f" [PARSE LOOP ERROR] {e}")
        await asyncio.sleep(3.0)


def _delete_all_channel_data(scan_config_id: int):
    """Helper: borra unified_catalog + item_episodes + catalog_assets + telegram_scan."""
    import os, re
    from tvcat.gateway import get_db_connection
    system_conn = get_db_connection(system=True)
    system_conn.row_factory = sqlite3.Row
    cursor = system_conn.cursor()
    cursor.execute("SELECT channel_id FROM tvcat_scanned_channels WHERE id = ?", (scan_config_id,))
    row = cursor.fetchone()
    # Resetear last_scanned_msg_id para que un futuro parse no salte los mensajes
    cursor.execute("UPDATE tvcat_scanned_channels SET last_scanned_msg_id = 0 WHERE id = ?", (scan_config_id,))
    system_conn.commit()
    system_conn.close()
    if not row:
        return
    ch_id = row["channel_id"]
    bare = ch_id.replace("-100", "").lstrip("-")
    link_pattern = f"https://t.me/c/{bare}/%"

    db_path = get_plugin_db_path()
    plugin_conn = sqlite3.connect(db_path, timeout=30)
    plugin_cursor = plugin_conn.cursor()

    plugin_cursor.execute("SELECT id, item_id, telegram_link FROM unified_catalog WHERE telegram_link LIKE ?", (link_pattern,))
    items = plugin_cursor.fetchall()
    msg_ids = set()
    item_ids = []
    user_item_ids = []
    for item in items:
        item_ids.append(item[0])
        if item[1]:
            user_item_ids.append(item[1])
        parts = item[2].rstrip("/").split("/")
        if parts:
            try:
                msg_ids.add(int(parts[-1]))
            except ValueError:
                pass

    if not msg_ids:
        cand = {ch_id, bare, f"-100{bare}"}
        cache_conn = get_db_connection()
        for sc in cand:
            rows = cache_conn.execute("SELECT DISTINCT msg_id FROM telegram_message_cache WHERE channel_id = ?", (sc,)).fetchall()
            for r in rows:
                msg_ids.add(r[0])
        cache_conn.close()

    if item_ids:
        ph = ",".join("?" for _ in item_ids)
        plugin_cursor.execute(f"DELETE FROM item_episodes WHERE item_id IN ({ph})", item_ids)

    for mid in msg_ids:
        try:
            plugin_cursor.execute("DELETE FROM catalog_assets WHERE channel_id = ? AND telegram_msg_id = ?", (bare, mid))
        except Exception:
            plugin_cursor.execute("DELETE FROM catalog_assets WHERE telegram_msg_id = ?", (mid,))

    if user_item_ids:
        ph = ",".join("?" for _ in user_item_ids)
        plugin_cursor.execute(f"DELETE FROM tvcat_cache WHERE item_id IN ({ph})", user_item_ids)

    plugin_cursor.execute("DELETE FROM unified_catalog WHERE telegram_link LIKE ?", (link_pattern,))
    plugin_cursor.execute("DELETE FROM item_episodes WHERE item_id NOT IN (SELECT id FROM unified_catalog)")

    plugin_conn.commit()
    plugin_conn.close()

    # Borrar mensajes raw del caché central
    cache_conn = get_db_connection()
    cand = {ch_id, bare, f"-100{bare}"}
    for rid in cand:
        cache_conn.execute("DELETE FROM telegram_message_cache WHERE channel_id = ?", (rid,))
    cache_conn.commit()
    cache_conn.close()


def _clean_scan_items(scan_config_id: int):
    """Borra items del catálogo + episodios + assets de un scan, sin tocar telegram_scan."""
    import os
    # Resetear last_scanned para que el parse posterior reprocese todo
    try:
        from tvcat.gateway import get_db_connection
        sc = get_db_connection(system=True)
        sc.execute("UPDATE tvcat_scanned_channels SET last_scanned_msg_id = 0 WHERE id = ?", (scan_config_id,))
        sc.commit(); sc.close()
    except Exception:
        pass
    source = f"scan_{scan_config_id}"
    db_path = get_plugin_db_path()
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cur = conn.cursor()
        cur.execute("SELECT id, item_id, telegram_link FROM unified_catalog WHERE source = ?", (source,))
        items = cur.fetchall()
        item_ids = []
        user_item_ids = []
        msg_ids = set()
        chan_mids = set()
        try:
            from services.cache_keys import key_from_link, split_key
        except Exception:
            key_from_link = None
            split_key = None
        for item in items:
            item_ids.append(item[0])
            if item[1]:
                user_item_ids.append(item[1])
            parts = item[2].rstrip("/").split("/")
            if parts:
                try:
                    msg_ids.add(int(parts[-1]))
                except ValueError:
                    pass
            if key_from_link and split_key and item[2]:
                try:
                    _ch, _mid = split_key(key_from_link(item[2]))
                    if _ch and _mid:
                        chan_mids.add((_ch, int(_mid)))
                except Exception:
                    pass
        if item_ids:
            ph = ",".join("?" for _ in item_ids)
            cur.execute(f"DELETE FROM item_episodes WHERE item_id IN ({ph})", item_ids)
            cur.execute(f"DELETE FROM unified_catalog WHERE id IN ({ph})", item_ids)
        if chan_mids:
            for (_ch, _mid) in chan_mids:
                try:
                    cur.execute("DELETE FROM catalog_assets WHERE channel_id = ? AND telegram_msg_id = ?", (_ch, _mid))
                except Exception:
                    cur.execute("DELETE FROM catalog_assets WHERE telegram_msg_id = ?", (_mid,))
        else:
            # Sin links parseables: comportamiento anterior (solo si la tabla no tiene canal)
            for mid in msg_ids:
                cur.execute("DELETE FROM catalog_assets WHERE telegram_msg_id = ?", (mid,))
        if user_item_ids:
            ph = ",".join("?" for _ in user_item_ids)
            cur.execute(f"DELETE FROM tvcat_cache WHERE item_id IN ({ph})", user_item_ids)
        cur.execute("DELETE FROM item_episodes WHERE item_id NOT IN (SELECT id FROM unified_catalog)")
        conn.commit()
        conn.close()
        if item_ids:
            add_log(f"  🧹 {len(item_ids)} item(s) eliminados del catálogo para re-parsear.")
    except Exception as e:
        print(f" [CLEAN SCAN ITEMS ERROR] {e}")


def _clear_channel_telegram_scan_cache(scan_config_id: int):
    from tvcat.gateway import get_db_connection
    system_conn = get_db_connection(system=True)
    system_cursor = system_conn.cursor()
    system_cursor.execute("SELECT channel_id FROM tvcat_scanned_channels WHERE id = ?", (scan_config_id,))
    row = system_cursor.fetchone()
    system_conn.close()
    if row:
        ch_id = row[0]
        cache_conn = get_db_connection()
        cand = {ch_id}
        bare = ch_id.replace("-100", "").lstrip("-")
        if bare.isdigit():
            cand.add(bare)
            cand.add(f"-100{bare}")
        for rid in cand:
            cache_conn.execute("DELETE FROM telegram_message_cache WHERE channel_id = ?", (rid,))
        cache_conn.commit()
        cache_conn.close()


# ---------------------------------------------------------------------------
# Centralized Sequential Queue Worker and Account Manager
# ---------------------------------------------------------------------------

_manual_queue = asyncio.Queue()
_active_clients = {}
_worker_task = None
_cycle_interval_seconds = 30 * 60  # 30 minutos
_cycle_counter = 0


def _resolve_api_creds():
    """Resuelve api_id/api_hash y session_string de la cuenta Principal.
    Orden:
      - settings globales (userbot_api_id/hash/session_string) si existen.
      - api_id/api_hash: userbot_sessions (preferir is_active=1; solo StringSession Telethon válidas).
      - session_string (Principal): la cuenta configurada en tvcat_telegram_accounts
        (la que el usuario marcó como principal); si no, userbot_sessions.
    """
    from tvcat.gateway import get_global_setting, get_db_connection
    api_id = get_global_setting("userbot_api_id")
    api_hash = get_global_setting("userbot_api_hash")
    session_string = get_global_setting("userbot_session_string")
    if api_id and api_hash and session_string:
        return api_id, api_hash, session_string
    try:
        conn = get_db_connection(system=True)
        # api_id/api_hash desde userbot_sessions (sesiones Telethon: prefijo mágico 1BJWap1w)
        row = conn.execute(
            "SELECT api_id, api_hash FROM userbot_sessions "
            "WHERE api_id IS NOT NULL AND api_hash IS NOT NULL "
            "AND session_string LIKE '1BJWap1w%' "
            "ORDER BY (is_active=1) DESC, id DESC LIMIT 1"
        ).fetchone()
        if row and row[0] and row[1]:
            if not api_id:
                api_id = row[0]
            if not api_hash:
                api_hash = row[1]
        # session_string (Principal): cuenta configurada en tvcat_telegram_accounts
        if not session_string:
            acc = conn.execute(
                "SELECT session_string FROM tvcat_telegram_accounts "
                "WHERE session_string IS NOT NULL AND session_string != '' "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if acc and acc[0]:
                session_string = acc[0]
        conn.close()
    except Exception:
        pass
    return api_id, api_hash, session_string


async def get_client_for_account(account_id: int):
    global _active_clients
    if account_id in _active_clients:
        client = _active_clients[account_id]
        if client.is_connected():
            return client

    from tvcat.gateway import get_db_connection
    api_id, api_hash, global_session = _resolve_api_creds()

    if account_id == -1:
        session_string = global_session
        username = "Principal"
    else:
        conn = get_db_connection(system=True)
        row = conn.execute("SELECT session_string, username FROM tvcat_telegram_accounts WHERE id = ?", (account_id,)).fetchone()
        conn.close()
        if not row:
            add_log(f"❌ No se encontró la sesión para la cuenta #{account_id}")
            return None
        session_string = row[0]
        username = row[1]

    if not api_id or not api_hash or not session_string:
        add_log(f"❌ api_id, api_hash o session_string no válidos para la cuenta '{username}'")
        return None

    try:
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash,
                                device_model="TVCat_TGIndex", app_version="1.0")
        await client.connect()
        if not await client.is_user_authorized():
            add_log(f"❌ Cuenta '{username}' no autorizada o sesión caducada")
            await client.disconnect()
            return None
        _active_clients[account_id] = client
        add_log(f"✅ Cliente Telegram para '{username}' iniciado.")
        return client
    except Exception as e:
        add_log(f"❌ Error al iniciar cliente para '{username}': {e}")
        return None


async def disconnect_client(account_id: int):
    global _active_clients
    if account_id in _active_clients:
        client = _active_clients.pop(account_id)
        try:
            await client.disconnect()
            add_log(f"🔌 Cliente de cuenta #{account_id} desconectado.")
        except:
            pass


def _migrate_telegram_scan_to_cache():
    """Una sola vez (flag migrate_tgscan_done_v1): vuelca telegram_scan (plugin y
    sistema) a telegram_message_cache (DB central). 2026-09-04: antes corría en CADA
    arranque con INSERT OR REPLACE y pisaba filas buenas con copias viejas
    (topics a NULL, raws antiguos) -> se hace una vez y con UPSERT seguro."""
    import json as _json
    try:
        from tvcat.gateway import get_db_connection

        try:
            _chk = get_db_connection()
            _done = _chk.execute("SELECT value FROM tvcat_settings WHERE key='migrate_tgscan_done_v1'").fetchone()
            _chk.close()
            if _done:
                return
        except Exception:
            pass

        try:
            from services.cache_keys import canon_channel as _canon
        except Exception:
            def _canon(x):
                return str(x or "")

        def _dump(conn, rows):
            n = 0
            for ch, tp, mid, msg in rows:
                try:
                    _d = _json.loads(msg)
                    _inner = _d.get("raw") if isinstance(_d.get("raw"), dict) else _d
                    _rid = (_inner or {}).get("id", None)
                    if _rid is not None and int(_rid) != int(mid):
                        continue
                    conn.execute(
                        """INSERT INTO telegram_message_cache
                        (channel_id, topic_id, msg_id, message, fetched_at)
                        VALUES (?,?,?,?,unixepoch())
                        ON CONFLICT(channel_id, msg_id) DO UPDATE SET
                            message=excluded.message,
                            fetched_at=excluded.fetched_at,
                            topic_id=COALESCE(excluded.topic_id, topic_id)""",
                        (_canon(ch), tp, mid, msg))
                    n += 1
                except Exception:
                    pass
            conn.commit()
            return n

        # Asegurar tabla en central
        try:
            cconn = get_db_connection()
            cconn.execute("""
                CREATE TABLE IF NOT EXISTS telegram_message_cache (
                    channel_id  TEXT NOT NULL,
                    topic_id    INTEGER,
                    msg_id      INTEGER NOT NULL,
                    message     TEXT NOT NULL,
                    fetched_at  INTEGER DEFAULT (unixepoch()),
                    PRIMARY KEY (channel_id, msg_id)
                )
            """)
            cconn.commit()
            cconn.close()
        except Exception:
            pass

        # 1. Desde la DB del plugin
        plugin_db = get_plugin_db_path()
        if os.path.exists(plugin_db):
            try:
                pconn = sqlite3.connect(plugin_db, timeout=30)
                has = pconn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_scan'").fetchone()
                if has:
                    rows = pconn.execute("SELECT channel_id, topic_id, msg_id, message FROM telegram_scan").fetchall()
                    if rows:
                        cconn = get_db_connection()
                        n = _dump(cconn, rows)
                        cconn.close()
                        print(f" [TGINDEX MIGRATE] {n} mensajes migrados (plugin telegram_scan → telegram_message_cache)")
                pconn.close()
            except Exception as e:
                print(f" [TGINDEX MIGRATE] error plugin: {e}")

        # 2. Desde la DB del sistema
        try:
            sconn = get_db_connection()
            has_sys = sconn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telegram_scan'").fetchone()
            if has_sys:
                rows = sconn.execute("SELECT channel_id, topic_id, msg_id, message FROM telegram_scan").fetchall()
                if rows:
                    n = _dump(sconn, rows)
                    if n:
                        print(f" [TGINDEX MIGRATE] {n} mensajes migrados (sistema telegram_scan → telegram_message_cache)")
            sconn.close()
        except Exception as e:
            print(f" [TGINDEX MIGRATE] error sistema: {e}")
        # Marcar como hecha (una sola vez)
        try:
            _fc = get_db_connection()
            _fc.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES ('migrate_tgscan_done_v1','1')")
            _fc.commit()
            _fc.close()
        except Exception:
            pass
    except Exception as e:
        print(f" [TGINDEX MIGRATE] error: {e}")


def start_worker_if_needed():
    global _worker_task
    try:
        loop = asyncio.get_running_loop()
        if _worker_task is None or _worker_task.done():
            _worker_task = loop.create_task(_sequential_worker_loop())
            print(" [TGINDEX SCANNER] [Worker] Worker secuencial iniciado.")
            try:
                import threading
                threading.Thread(target=_migrate_telegram_scan_to_cache, daemon=True).start()
            except Exception:
                pass
    except RuntimeError:
        pass


async def submit_manual_scan(channel_id: int, mode: str = "normal"):
    fut = asyncio.get_event_loop().create_future()
    await _manual_queue.put({"channel_id": channel_id, "mode": mode, "future": fut})
    return fut


async def _update_channel_status(channel_id: int, status: str):
    def _sync():
        from tvcat.gateway import get_db_connection
        try:
            conn = get_db_connection(system=True)
            conn.execute("UPDATE tvcat_scanned_channels SET status = ? WHERE id = ?", (status, channel_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f" [DB ERROR] Al actualizar estado del canal: {e}")
    await asyncio.to_thread(_sync)


async def _process_manual_task(task):
    channel_id = task["channel_id"]
    mode = task["mode"]
    fut = task["future"]

    global scanner_status
    scanner_status.update({"status": "scanning", "progress_percent": 0, "current_item": "Inicializando...", "logs": [], "parse_pending": False})

    try:
        from tvcat.gateway import get_db_connection
        conn = get_db_connection(system=True)
        conn.row_factory = sqlite3.Row
        ch = conn.execute("SELECT * FROM tvcat_scanned_channels WHERE id = ?", (channel_id,)).fetchone()
        conn.close()

        if not ch:
            add_log(f"❌ Canal #{channel_id} no encontrado.")
            fut.set_result(False)
            return

        ch_dict = dict(ch)
        name = ch_dict["display_name"]
        account_id = ch_dict.get("telegram_account_id")

        if not account_id:
            add_log(f"❌ El canal '{name}' no tiene una cuenta de Telegram asociada.")
            fut.set_result(False)
            return

        await _update_channel_status(channel_id, "scanning")

        api_id, api_hash, session_string, uname = _resolve_account_creds(account_id)
        if not api_id or not api_hash or not session_string:
            add_log(f"❌ No se pudo resolver la cuenta de Telegram para '{name}'.")
            await _update_channel_status(channel_id, "idle")
            fut.set_result(False)
            return

        add_log(f"📡 Iniciando escaneo manual de '{name}' en modo '{mode}'...")
        add_log(f"✅ Cliente Telegram para '{uname or account_id}' iniciado.")

        if mode == "clean":
            _delete_all_channel_data(channel_id)
        elif mode == "incremental":
            _clear_channel_telegram_scan_cache(channel_id)

        await _scan_channel(account_id, ch_dict, 0, 1)

        n, _ = await parse_topology(channel_id)
        if n > 0:
            scanner_status["refresh_signal"] = scanner_status.get("refresh_signal", 0) + n
            add_log(f"✅ Catálogo actualizado para '{name}': +{n} títulos nuevos.")

        add_log(f"🎉 Escaneo manual de '{name}' completado.")
        await _update_channel_status(channel_id, "idle")
        fut.set_result(True)
    except Exception as e:
        add_log(f"❌ Error durante escaneo manual de #{channel_id}: {e}")
        await _update_channel_status(channel_id, "idle")
        fut.set_result(False)
    finally:
        scanner_status.update({"status": "idle", "progress_percent": 100, "current_item": "Completado."})
        #   Tras cualquier escaneo/parse: regenerar export y avisar a la caché central
        try:
            from .sync import refresh_central_cache
            refresh_central_cache(f"scan #{channel_id}")
        except Exception as e:
            print(f" [TGIndex] Aviso: refresh central tras scan #{channel_id}: {e}")


async def _process_periodic_cycle():
    global _cycle_counter, scanner_status
    try:
        async def _get_enabled_channels():
            def _sync():
                from tvcat.gateway import get_db_connection
                conn = get_db_connection(system=True)
                conn.row_factory = sqlite3.Row
                channels = [dict(r) for r in conn.execute(
                    "SELECT * FROM tvcat_scanned_channels WHERE enabled = 1 ORDER BY priority ASC, id ASC"
                ).fetchall()]
                conn.close()
                return channels
            return await asyncio.to_thread(_sync)
        channels = await _get_enabled_channels()
    except Exception as e:
        print(f" [PERIODIC CYCLE ERROR] Al leer canales: {e}")
        return

    if not channels:
        return

    add_log(f"📡 Iniciando Ciclo Periódico de Escaneo #{_cycle_counter}...")
    total = len(channels)

    for idx, ch in enumerate(channels):
        channel_id = ch["id"]
        name = ch["display_name"]
        refresh_cycles = ch.get("refresh_cycles") or 1
        account_id = ch.get("telegram_account_id")

        if _cycle_counter % refresh_cycles != 0:
            add_log(f"⏳ Saltando '{name}' (refresco cada {refresh_cycles} ciclos).")
            continue

        if not account_id:
            add_log(f"⚠️ Saltando '{name}' (sin cuenta de Telegram asociada).")
            continue

        scanner_status.update({"status": "scanning", "progress_percent": int((idx / total) * 100), "current_item": f"Escaneando {name}..."})
        await _update_channel_status(channel_id, "scanning")

        try:
            api_id, api_hash, session_string, uname = _resolve_account_creds(account_id)
            if not api_id or not api_hash or not session_string:
                add_log(f"❌ No se pudo resolver la cuenta de Telegram para '{name}'.")
                await _update_channel_status(channel_id, "idle")
                continue

            await _scan_channel(account_id, ch, idx, total)

            n, _ = await parse_topology(channel_id)
            if n > 0:
                scanner_status["refresh_signal"] = scanner_status.get("refresh_signal", 0) + n
                add_log(f"✅ Catálogo actualizado para '{name}': +{n} títulos nuevos.")

            await _update_channel_status(channel_id, "idle")
        except Exception as e:
            add_log(f"❌ Error al escanear '{name}' en ciclo periódico: {e}")
            await _update_channel_status(channel_id, "idle")

        await asyncio.sleep(4.0)

    scanner_status.update({"status": "idle", "progress_percent": 100, "current_item": "Completado."})
    add_log(f"✅ Ciclo Periódico de Escaneo #{_cycle_counter} finalizado.")
    try:
        from .sync import refresh_central_cache
        refresh_central_cache("ciclo periódico")
    except Exception as e:
        print(f" [TGIndex] Aviso: refresh central tras ciclo periódico: {e}")


async def _sequential_worker_loop():
    while True:
        try:
            try:
                task = await asyncio.wait_for(_manual_queue.get(), timeout=2.0)
                await _process_manual_task(task)
                _manual_queue.task_done()
                continue
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f" [SEQUENTIAL WORKER ERROR] {e}")
            await asyncio.sleep(5.0)


async def run_background_scan(target_id: Optional[int] = None, mode: str = "normal"):
    """Interfaz compatible con el endpoint original: encola la tarea en el worker."""
    start_worker_if_needed()
    if target_id is not None:
        fut = await submit_manual_scan(target_id, mode=mode)
        await fut
    else:
        await _process_periodic_cycle()


async def auto_refresh_channel(scan_config_id: int):
    """Encola la tarea de auto-refresh de forma secuencial en el worker."""
    start_worker_if_needed()
    fut = await submit_manual_scan(scan_config_id, mode="normal")
    await fut


def _get_tgindex_refresh_status():
    st = scanner_status.get("status", "idle")
    prog = scanner_status.get("progress_percent", 0)
    return {
        "progress": prog,
        "status": st,
        "current": scanner_status.get("current_item", ""),
    }


async def _run_tgindex_refresh(trigger: str = "manual"):
    add_log("📡 Refresco gatillado desde el motor de catálogo central.")
    await _process_periodic_cycle()


# Registrar en el motor de catálogo del gateway
try:
    from tvcat.gateway import register_plugin_refresher
    register_plugin_refresher("tvcat_tgindex", _run_tgindex_refresh, _get_tgindex_refresh_status, start_delay=10)
except Exception:
    pass

# Iniciar worker secuencial
try:
    start_worker_if_needed()
except Exception:
    pass
