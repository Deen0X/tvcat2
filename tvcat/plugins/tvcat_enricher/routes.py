"""
tvcat_enricher — Plugin heropage-action que sustituye el cover ancla
                (foto + caption) por uno enriquecido.

Caso 1: el mensaje es de uno de mis userbots → edit_message en Telegram.
Caso 2: mensaje ajeno → guardado local (DB propia) y servido a todos vía registry.

Clave estable: channelid_msgid (derive de telegram_link).
"""

import os
import json
import time
import re
import sqlite3
import base64
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "tvcat.db")


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return c


def _init_db():
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS enriched_covers (
            channelid_msgid TEXT PRIMARY KEY,
            item_id TEXT,
            telegram_msg_id INTEGER,
            telegram_link TEXT,
            cover_text TEXT,
            enrich_details TEXT DEFAULT '{}',
            poster_blob BLOB,
            poster_mime TEXT DEFAULT 'image/jpeg',
            author_user_id INTEGER,
            created_by_user_id INTEGER,
            created_at INTEGER,
            updated_at INTEGER
        )
    """)
    c.commit()
    c.close()


_init_db()


def _derive_key(telegram_link: str) -> str:
    """Delega en services.cache_keys (único criterio)."""
    try:
        from services.cache_keys import key_from_link
        return key_from_link(telegram_link)
    except Exception:
        if not telegram_link:
            return ""
        m = re.search(r"/c/(\d+)/(?:(\d+)/)?(\d+)", telegram_link)
        if not m:
            return ""
        return f"{m.group(1)}_{m.group(3)}"


def _get_my_userbots() -> List[Dict[str, Any]]:
    """Devuelve los tg_user_id de todos los userbots activos."""
    try:
        import services.userbot_service as ubs
        rows = ubs.list_sessions()
        out = []
        for r in rows:
            tid = r.get("tg_user_id")
            if tid and r.get("is_active") == 1:
                out.append({"tg_user_id": int(tid), "client_type": r.get("client_type", "telethon"), "name": r.get("name", "")})
        # fallback: también los telegram_users (todos los userbots asociados)
        if not out:
            try:
                import services.userbot_service as ubs2
                c = ubs2._get_conn()
                for rr in c.execute("SELECT tg_user_id FROM telegram_users").fetchall():
                    if rr["tg_user_id"]:
                        out.append({"tg_user_id": int(rr["tg_user_id"]), "client_type": "telethon", "name": ""})
                c.close()
            except Exception:
                pass
        return out
    except Exception:
        return []


def _resolve_link(item_id: str) -> tuple:
    """Devuelve (telegram_link, telegram_msg_id, channelid_msgid) para el item."""
    try:
        from services.catalog_service import get_conn
        conn = get_conn()
        row = conn.execute(
            "SELECT telegram_link, telegram_msg_id FROM unified_catalog WHERE item_id=?",
            (item_id,)
        ).fetchone()
        conn.close()
        if not row:
            return (None, None, None)
        link = row["telegram_link"]
        mid = row["telegram_msg_id"]
        key = _derive_key(link) if link else ""
        if not key and mid:
            import re as _re
            m = _re.search(r"/c/(\d+)/", link or "")
            if m:
                key = f"{m.group(1)}_{int(mid)}"
        return (link, mid, key)
    except Exception:
        return (None, None, None)


def _get_enriched_for_key(channelid_msgid: str) -> Optional[Dict[str, Any]]:
    if not channelid_msgid:
        return None
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM enriched_covers WHERE channelid_msgid=?",
        (channelid_msgid,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["enrich_details"] = json.loads(d.get("enrich_details") or "{}")
    except Exception:
        d["enrich_details"] = {}
    return d


# ── Registro en el registry agnóstico ─────────────────────────────────

try:
    from services.cover_override_registry import register_cover_override_provider

    def _enricher_provider(channelid_msgid: str) -> Optional[Dict[str, Any]]:
        row = _get_enriched_for_key(channelid_msgid)
        if not row:
            return None
        return {
            "cover_text": row.get("cover_text") or "",
            "enrich_details": row.get("enrich_details") or {},
            "poster_blob": row.get("poster_blob"),
            "poster_mime": row.get("poster_mime") or "image/jpeg",
        }

    register_cover_override_provider("tvcat_enricher", _enricher_provider)
except Exception as e:
    print(f" [ENRICHER] registry register failed: {e}", flush=True)


# ── Modelos ─────────────────────────────────────────────────────────────

class SearchReq(BaseModel):
    query: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    episode_count: Optional[int] = None
    provider: Optional[str] = None  # override manual (tabs del modal)


class DetailsReq(BaseModel):
    provider: str
    id: str
    media_type: Optional[str] = None
    sub_provider: Optional[str] = None  # books: google_books u open_library
    season: Optional[int] = None  # tmdb/tv: fusiona /tv/{id}/season/{n}


class SaveReq(BaseModel):
    cover_text: str = ""
    enrich_details: Optional[Dict[str, Any]] = None
    poster_b64: Optional[str] = None  # base64 de la imagen (data:..., o raw b64)
    poster_mime: Optional[str] = None
    poster_url: Optional[str] = None  # URL del póster (fallback: lo descarga el servidor)


def _sniff_mime(data: bytes, declared: str = "") -> str:
    if declared and declared.startswith("image/"):
        return declared.split(";")[0].strip()
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF":
        return "image/gif"
    return "image/jpeg"


async def _resolve_poster_bytes(body: SaveReq):
    """Devuelve (bytes|None, mime, name). Prioridad: poster_b64 → poster_url (descarga servidor)."""
    import asyncio as _aio
    # 1) base64 del frontend (si el fetch del navegador funcionó)
    if body.poster_b64:
        raw = body.poster_b64.strip()
        mime = body.poster_mime or "image/jpeg"
        if raw.startswith("data:"):
            m = re.match(r"data:([^;]+);base64,(.+)", raw)
            if m:
                mime = m.group(1) or mime
                raw = m.group(2)
        try:
            data = base64.b64decode(raw)
            if data:
                return data, mime, "cover.jpg" if "png" not in mime else "cover.png"
        except Exception as e:
            print(f" [ENRICHER] poster_b64 inválido: {e}", flush=True)
    # 2) URL: descarga en servidor (sin problemas de CORS del navegador)
    url = (body.poster_url or "").strip()
    if url.startswith("http"):
        def _dl():
            import requests
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and r.content:
                return r.content, r.headers.get("Content-Type", "")
            print(f" [ENRICHER] póster status {r.status_code} ({url})", flush=True)
            return None, ""
        try:
            data, ctype = await _aio.to_thread(_dl)
        except Exception as e:
            print(f" [ENRICHER] error descargando póster: {e}", flush=True)
            data, ctype = None, ""
        if data:
            mime = _sniff_mime(data, ctype)
            return data, mime, "cover.png" if "png" in mime else "cover.jpg"
    return None, body.poster_mime or "image/jpeg", "cover.jpg"


# ── Endpoints ───────────────────────────────────────────────────────────

@router.get("/api/enricher/templates")
async def get_templates(request: Request):
    try:
        import services.enrich_service as es
        tpls = es._load_templates()  # {fallback, categories: {}}
        return tpls
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Proveedores configurados + enlaces externos de búsqueda ──────────
# El modal muestra junto a "Buscar" un enlace pequeño por cada proveedor con
# API key configurada, para abrir la búsqueda en la web del proveedor.

_EXTERNAL_SEARCH_URLS = {
    "tmdb": "https://www.themoviedb.org/search?query={q}",
    "igdb": "https://www.igdb.com/search?q={q}",
    "books": "https://www.google.com/search?tbm=bks&q={q}",
    "comicvine": "https://comicvine.gamespot.com/search/?q={q}",
}

_PROVIDER_LABELS = {
    "tmdb": "tmdb",
    "igdb": "igdb",
    "books": "books",
    "comicvine": "comicvine",
}


@router.get("/api/enricher/providers")
async def get_providers(request: Request):
    """Devuelve los proveedores con su estado de configuración y URL externa.

    {providers: [{name, label, configured, search_url}]}
    search_url lleva el placeholder {q} para la query.
    """
    try:
        import services.enrich_service as es
        creds = es._load_credentials()
    except Exception:
        creds = {}
    out = []
    for name in ("tmdb", "igdb", "books", "comicvine"):
        try:
            import services.enrich_service as es2
            configured = es2._provider_enabled(name, creds)
        except Exception:
            configured = False
        out.append({
            "name": name,
            "label": _PROVIDER_LABELS.get(name, name),
            "configured": bool(configured),
            "search_url": _EXTERNAL_SEARCH_URLS.get(name, ""),
        })
    return {"providers": out}


class FtagReq(BaseModel):
    tag: str
    template: str


@router.get("/api/enricher/ftags")
async def get_ftags(request: Request):
    try:
        import os, json
        from pathlib import Path
        p = Path(__file__).resolve().parents[1] / "tvcat_TGHirayi" / "data" / "cover_tags.json"
        ftags = {}
        if p.is_file():
            try:
                ftags = json.loads(p.read_text(encoding="utf-8")).get("ftags") or {}
            except Exception:
                ftags = {}
        if not ftags:
            ftags = {
                "tagtitle": "{value}",
                "title": "Title: {value}",
                "title_en": "Title EN: {value}",
                "year": "Year: {value}",
                "release_year": "Year: {value}",
                "season": "Season: {value}",
                "temporada": "Season: {value}",
                "season_episodes": "Season episodes: {value}",
                "season": "Season: {value}",
                "temporada": "Season: {value}",
                "season_episodes": "Season episodes: {value}",
                "rating": "Rating: {value}",
                "rating_count": "Rating count: {value}",
                "genres": "Genres: {value}",
                "generos": "Genres: {value}",
                "themes": "Themes: {value}",
                "temas": "Themes: {value}",
                "author": "Author: {value}",
                "autor": "Author: {value}",
                "director": "Director: {value}",
                "directores": "Director: {value}",
                "release_date": "Release date: {value}",
                "fecha": "Release date: {value}",
                "category": "Category: {value}",
                "categoria": "Category: {value}",
                "id": "ID: {value}",
                "cover": "Cover: {value}",
                "episodes": "Episodes: {value}",
                "ext": "Ext: {value}",
                "extension": "Ext: {value}",
                "description": "Description:\n{value}",
                "sinopsis": "Sinopsis:\n{value}",
                "overview": "Overview:\n{value}",
                "originalmsg": "{value}",
                "original_title": "Original title: {value}",
                "titulo_original": "Original title: {value}",
                "title_es": "Title ES: {value}",
                "titulo_espana": "Title ES: {value}",
                "title_latam": "Title Latam: {value}",
                "title_mx": "Title Latam: {value}",
                "titulo_latino": "Title Latam: {value}",
                "alt_titles": "Alt titles: {value}",
                "titulos_alt": "Alt titles: {value}",
                "cast": "Cast: {value}",
                "reparto": "Cast: {value}",
                "actores": "Cast: {value}",
                "actors": "Cast: {value}",
            }
        return {"ftags": ftags}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/enricher/ftags")
async def save_ftag(req: FtagReq, request: Request):
    try:
        from services.auth_service import get_session
        sess = get_session(request.cookies.get("tvcat_session", ""))
        if not sess or sess.get("role") != "admin":
            if not sess or (sess.get("username","").lower() != "admin" and not sess.get("is_admin")):
                raise HTTPException(status_code=403, detail="Solo admin")
    except HTTPException:
        raise
    except Exception:
        pass
    tag = (req.tag or "").strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag requerido")
    tag = tag.strip("{} ").lstrip("f").strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag inválido")
    import os, json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "tvcat_TGHirayi" / "data" / "cover_tags.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"ftags": {}}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if "ftags" not in data:
                data["ftags"] = {}
        except Exception:
            data = {"ftags": {}}
    if req.template is not None:
        if req.template.strip() == "":
            data["ftags"].pop(tag, None)
        else:
            data["ftags"][tag] = req.template
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "tag": tag, "template": req.template}


@router.get("/api/enricher/item/{item_id}")
async def get_enricher_item(item_id: str, request: Request):
    link, mid, key = _resolve_link(item_id)
    if not link:
        raise HTTPException(status_code=404, detail="item not found")
    enriched = _get_enriched_for_key(key) if key else None
    # Datos originales (del catálogo)
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT title, category, subcategory, description, year, rating, rorder, season_number FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
    conn.close()
    original = dict(row) if row else {}
    # 2026-09-04: poster_blob (bytes) no es serializable a JSON (rompía el modal
    # con 500). Se expone flag; la imagen va por GET /cover dedicado.
    if enriched is not None:
        enriched = dict(enriched)
        if enriched.get("poster_blob"):
            enriched["has_poster"] = True
        enriched.pop("poster_blob", None)
    # authorship (lazy)
    return {
        "item_id": item_id,
        "telegram_link": link,
        "telegram_msg_id": mid,
        "channelid_msgid": key,
        "original": original,
        "enriched": enriched,
        "has_enriched": enriched is not None,
    }


@router.get("/api/enricher/item/{item_id}/authorship")
async def get_authorship(item_id: str, request: Request):
    link, mid, key = _resolve_link(item_id)
    if not link or not mid:
        raise HTTPException(status_code=404, detail="item not found")
    my = _get_my_userbots()
    if not my:
        return {"is_mine": False, "author_user_id": None, "author_type": None, "reason": "no userbots"}

    # 1) Intento rápido por cache (from_id en el mensaje raw si existe)
    channel_id = None
    try:
        from services.cache_keys import canon_channel as _canon
    except Exception:
        def _canon(x):
            return str(x or "")
    m = re.search(r"/c/(\d+)/", link)
    # Clave canónica única (tras la migración no hay variantes ±-100)
    channel_id = _canon(m.group(1)) if m else ""
    cached_author = None
    cached_type = "unknown"
    # 1) Intento por cache directo a la DB central (sin pasar por el worker, con timeout y fallback)
    try:
        import sqlite3 as _sq
        from pathlib import Path as _P
        central_db = str(_P(__file__).resolve().parents[2] / "data" / "tvcat.db")
        # Intentar abrir con timeout; si hay WAL bloqueado, reintentar
        _c = None
        for _try in range(2):
            try:
                _c = _sq.connect(f"file:{central_db}?mode=ro", uri=True, timeout=10, check_same_thread=False)
                break
            except Exception as e:
                if "unable to open" in str(e) and _try == 0:
                    import time as _t; _t.sleep(0.3); continue
                raise
        if _c:
            _c.row_factory = _sq.Row
            r = None
            if channel_id:
                try:
                    r = _c.execute("SELECT message FROM telegram_message_cache WHERE channel_id=? AND msg_id=? LIMIT 1", (channel_id, int(mid))).fetchone()
                except Exception:
                    r = None
            if r and r[0]:
                import json as _js
                try:
                    raw = _js.loads(r[0])
                except Exception:
                    raw = {}
                # from_id puede venir como PeerUser directo o envuelto
                fid = raw.get("from_id") or raw.get("from") or {}
                # En algunos dumps from_id es int directo
                if isinstance(fid, int):
                    cached_author = int(fid)
                    cached_type = "group"
                elif isinstance(fid, dict):
                    if fid.get("_") == "PeerUser" and fid.get("user_id"):
                        cached_author = int(fid["user_id"])
                        cached_type = "group"
                    elif fid.get("_") == "PeerChannel":
                        cached_type = "channel"
                    elif fid.get("user_id"):
                        cached_author = int(fid["user_id"])
                        cached_type = "group"
                # Fallback: _serialize_message a veces guarda from_id como dict en raw["from_id"] con peer
                # Si no hay from_id, probar peer_id o from
                if cached_author is None:
                    peer = raw.get("peer_id") or {}
                    if isinstance(peer, dict) and peer.get("_") == "PeerUser":
                        pass  # peer es el canal, no el autor
            _c.close()
    except Exception:
        pass
    if cached_author is not None:
        mine_ids = {x["tg_user_id"] for x in my}
        if cached_author in mine_ids:
            return {"is_mine": True, "author_user_id": cached_author, "author_type": cached_type, "reason": "from_id match (cache)"}
        return {"is_mine": False, "author_user_id": cached_author, "author_type": cached_type, "reason": "from_id not in my userbots"}

    # 2) Canales broadcast: si no hay from_id útil (channel), no bloqueamos con fetch_one (hang si el worker está con WAL bloqueado)
    #    Para el modal es suficiente saber que no es grupo con author visible; el botón "Aplicar en Telegram" quedará deshabilitado
    #    hasta que el diagnóstico confirme el canal. Así el modal abre siempre.
    return {"is_mine": False, "author_user_id": cached_author, "author_type": cached_type, "reason": "no userbot matched (broadcast: requiere diagnóstico)"}


@router.get("/api/enricher/item/{item_id}/cover")
async def get_enriched_cover(item_id: str):
    _ok, _1, key = _resolve_link(item_id)
    if not key:
        raise HTTPException(status_code=404)
    row = _get_enriched_for_key(key)
    if not row or not row.get("poster_blob"):
        raise HTTPException(status_code=404)
    return Response(content=row["poster_blob"], media_type=row.get("poster_mime") or "image/jpeg")


@router.post("/api/enricher/search")
async def proxy_search(req: SearchReq):
    try:
        import services.enrich_service as es
        res = await es.search(req.query, req.category or "", req.subcategory or "",
                             episode_count=req.episode_count,
                             provider_override=req.provider or "")
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/enricher/details")
async def proxy_details(req: DetailsReq):
    try:
        import services.enrich_service as es
        res = await es.get_details(req.provider, req.id, media_type_hint=req.media_type,
                                     sub_provider=req.sub_provider or "",
                                     season=req.season)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/enricher/item/{item_id}/save")
async def save_enriched(item_id: str, body: SaveReq, request: Request):
    link, mid, key = _resolve_link(item_id)
    if not key:
        raise HTTPException(status_code=404, detail="item not found / no channelid_msgid")
    poster_blob, poster_mime, _ = await _resolve_poster_bytes(body)

    now = int(time.time())
    conn = _conn()
    # Sin póster nuevo (reapertura sin reseleccionar): conservar el existente
    # en vez de pisarlo con NULL (perdía la imagen del cover al re-guardar).
    if not poster_blob:
        try:
            _old = conn.execute(
                "SELECT poster_blob, poster_mime FROM enriched_covers WHERE channelid_msgid=?",
                (key,)).fetchone()
            if _old and _old["poster_blob"]:
                poster_blob = bytes(_old["poster_blob"])
                poster_mime = _old["poster_mime"] or poster_mime
        except Exception:
            pass
    # Resolver created_by_user_id si existe sesión
    created_by = None
    try:
        from services.auth_service import get_session
        sess = get_session(request.cookies.get("tvcat_session", ""))
        if sess:
            created_by = int(sess.get("user_id", 0)) or None
    except Exception:
        pass
    conn.execute("""
        INSERT INTO enriched_covers
        (channelid_msgid, item_id, telegram_msg_id, telegram_link, cover_text, enrich_details, poster_blob, poster_mime, author_user_id, created_by_user_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channelid_msgid) DO UPDATE SET
            item_id=excluded.item_id,
            telegram_msg_id=excluded.telegram_msg_id,
            telegram_link=excluded.telegram_link,
            cover_text=excluded.cover_text,
            enrich_details=excluded.enrich_details,
            poster_blob=excluded.poster_blob,
            poster_mime=excluded.poster_mime,
            updated_at=excluded.updated_at
    """, (
        key, item_id, int(mid) if mid else None, link, body.cover_text or "",
        json.dumps(body.enrich_details or {}, ensure_ascii=False),
        poster_blob, poster_mime,
        None, created_by, now, now
    ))
    conn.commit()
    conn.close()
    # Propagación centralizada (services/enrich_apply): título del tag +
    # variantes al catálogo central, con réplica en DBs de plugins.
    # (Misma lógica que había inline aquí; ahora compartida con el reapply
    # post-rebuild para que no se pierda al rearrancar.)
    try:
        from services.enrich_apply import apply_enriched_title as _apply_enriched_title
        _ap = _apply_enriched_title(item_id, body.cover_text or "") or {}
    except Exception as _e_ap:
        print(f" [Enricher] apply error: {_e_ap}")
        _ap = {}
    _title_applied = bool(_ap.get("title_applied"))
    _c_title = _ap.get("catalog_title") or ""
    _alts_applied = _ap.get("alts_applied") or []
    return {"ok": True, "channelid_msgid": key, "title_applied": _title_applied, "catalog_title": _c_title if _title_applied else "", "alts_applied": _alts_applied}


@router.post("/api/enricher/item/{item_id}/apply")
async def apply_enriched(item_id: str, body: SaveReq, request: Request):
    """Edita el mensaje ancla en Telegram (solo si es mío) y guarda local."""
    link, mid, key = _resolve_link(item_id)
    if not key or not mid:
        raise HTTPException(status_code=404, detail="item not found")
    # Guardar local primero (reflejo inmediato; propaga título al catálogo)
    saved = await save_enriched(item_id, body, request)
    # Ancla ficticia (corte de slicer / genérico topo -999/-1000): no hay mensaje
    # real que editar en Telegram; solo guardado local (clave propia por parte).
    if int(mid) in (-999, -1000):
        return {"ok": True, "channelid_msgid": key, "edited": False,
                "reason": "cover ficticio: solo guardado local",
                "title_applied": bool((saved or {}).get("title_applied")),
                "catalog_title": (saved or {}).get("catalog_title") or ""}
    # Authorship check
    auth = await get_authorship(item_id, request)
    if not auth.get("is_mine"):
        raise HTTPException(status_code=403, detail="El mensaje no es de ninguno de tus userbots (no editable)")

    # Guardar local (reflejo inmediato; propaga título al catálogo)
    saved = await save_enriched(item_id, body, request)

    # Editar en Telegram (channel_id + msg_id)
    m = re.search(r"/c/(\d+)/", link)
    if not m:
        raise HTTPException(status_code=400, detail="No se pudo derivar el channel_id de telegram_link")
    channel_id = "-100" + m.group(1)
    author_tid = auth["author_user_id"]
    poster_bytes, poster_mime, poster_name = await _resolve_poster_bytes(body)
    try:
        from services.telegram_service import get_telegram_service
        svc = get_telegram_service()
        res = await svc.edit_message(
            channel_id=str(channel_id),
            msg_id=int(mid),
            text=body.cover_text or "",
            file_bytes=poster_bytes,
            file_name=poster_name,
            tg_user_id=int(author_tid)
        )
        if not res.get("ok"):
            raise HTTPException(status_code=502, detail=res.get("error") or "edit_message falló")
        # Editado en Telegram: la copia local deja de ser necesaria
        # ("pendiente de sincronizar"; el título ya se propagó al guardar y
        # los rescans leerán el mensaje editado). Best-effort.
        try:
            _dc = _conn()
            _dc.execute("DELETE FROM enriched_covers WHERE channelid_msgid=?", (key,))
            _dc.commit()
            _dc.close()
        except Exception:
            pass
        return {"ok": True, "channelid_msgid": key, "edited": True, "author_user_id": author_tid,
                "local_kept": False,
                "title_applied": bool((saved or {}).get("title_applied")),
                "catalog_title": (saved or {}).get("catalog_title") or ""}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/api/enricher/item/{item_id}")
async def delete_enriched(item_id: str, request: Request):
    _link, _mid, key = _resolve_link(item_id)
    if not key:
        raise HTTPException(status_code=404)
    conn = _conn()
    conn.execute("DELETE FROM enriched_covers WHERE channelid_msgid=?", (key,))
    conn.commit()
    deleted = conn.total_changes
    conn.close()
    return {"ok": True, "deleted": bool(deleted), "channelid_msgid": key}


# ─── Ediciones locales: listado + bulk (LocalEdits_Implementation_Plan.md) ───
class BulkReq(BaseModel):
    keys: List[str] = []


def _local_session_user(request: Request) -> dict:
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session", ""))
    if not s:
        raise HTTPException(status_code=401, detail="Inicia sesión")
    return s


def _local_my_ids() -> set:
    try:
        return {int(x["tg_user_id"]) for x in _get_my_userbots() if x.get("tg_user_id")}
    except Exception:
        return set()


def _local_slicer_new_ids() -> set:
    """new_item_id de slicer_cuts (lectura cruzada best-effort, como unsplit)."""
    try:
        _p = os.path.normpath(os.path.join(
            _PLUGIN_DIR, "..", "tvcat_episode_slicer", "data", "tvcat.db"))
        if not os.path.isfile(_p):
            return set()
        _c = sqlite3.connect(f"file:{_p}?mode=ro", uri=True, timeout=10)
        rows = _c.execute("SELECT new_item_id FROM slicer_cuts").fetchall()
        _c.close()
        return {str(r[0]) for r in rows if r and r[0]}
    except Exception:
        return set()


async def _row_is_mine(row: dict, my_ids: set, request: Request) -> tuple:
    """(is_mine, author_user_id). Autor cacheado si existe; si no, resolución
    en vivo (solo caché central, sin red). Huérfanos (sin item) → no."""
    try:
        if row.get("author_user_id") and int(row["author_user_id"]) in my_ids:
            return True, int(row["author_user_id"])
    except Exception:
        pass
    try:
        if row.get("author_user_id"):
            return False, int(row["author_user_id"])
    except Exception:
        pass
    iid = (row.get("item_id") or "").strip()
    if not iid:
        return False, None
    try:
        auth = await get_authorship(iid, request)
        return bool(auth.get("is_mine")), auth.get("author_user_id")
    except Exception:
        return False, None


def _central_by_ids(item_ids: list) -> dict:
    if not item_ids:
        return {}
    try:
        from services.catalog_service import get_conn
        conn = get_conn()
        out = {}
        for _i in range(0, len(item_ids), 500):
            _ch = item_ids[_i:_i + 500]
            _q = ("SELECT * FROM unified_catalog WHERE item_id IN (%s)" %
                  ",".join("?" * len(_ch)))
            for _r in conn.execute(_q, _ch).fetchall():
                try:
                    out[str(_r["item_id"])] = dict(_r)
                except Exception:
                    continue
        conn.close()
        return out
    except Exception:
        return {}


@router.get("/api/enricher/covers")
async def list_local_covers(request: Request):
    """Todas las copias locales con shape de catálogo (como /api/hidden)
    + `_local={is_mine,is_cut,orphan}`. Para la sección Ediciones locales."""
    _local_session_user(request)
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT channelid_msgid, item_id, telegram_msg_id, telegram_link,"
            " cover_text, updated_at, author_user_id FROM enriched_covers"
            " ORDER BY updated_at DESC").fetchall()]
    finally:
        try:
            conn.close()
        except Exception:
            pass
    my_ids = _local_my_ids()
    cut_ids = _local_slicer_new_ids()
    central = _central_by_ids([r["item_id"] for r in rows if r.get("item_id")])
    items = []
    for r in rows:
        iid = str(r.get("item_id") or "")
        base = central.get(iid)
        is_mine, author = await _row_is_mine(r, my_ids, request)
        loc = {"is_mine": is_mine, "author_user_id": author,
               "is_cut": iid in cut_ids,
               "channelid_msgid": r.get("channelid_msgid"),
               "orphan": base is None}
        if base is not None:
            it = dict(base)
        else:
            # Huérfana (título borrado del catálogo): título del cover para
            # poder limpiarla desde la sección.
            _t = (r.get("cover_text") or "").strip().split("\n")[0][:80]
            it = {"item_id": iid, "title": _t or "(sin título)",
                  "category": "", "subcategory": "", "year": "",
                  "description": "", "telegram_link": r.get("telegram_link") or ""}
        it["_local"] = loc
        items.append(it)
    return {"items": items, "count": len(items)}


@router.get("/api/enricher/has_local")
async def has_local_covers(request: Request):
    _local_session_user(request)
    conn = _conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM enriched_covers").fetchone()[0]
    except Exception:
        n = 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {"count": int(n or 0)}


@router.post("/api/enricher/bulk_delete")
async def bulk_delete_covers(body: BulkReq, request: Request):
    _local_session_user(request)
    keys = [str(k or "").strip() for k in (body.keys or []) if str(k or "").strip()]
    if not keys:
        return {"ok": True, "deleted": 0, "missing": 0}
    conn = _conn()
    deleted = 0
    try:
        for k in keys:
            cur = conn.execute(
                "DELETE FROM enriched_covers WHERE channelid_msgid=?", (k,))
            deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {"ok": True, "deleted": deleted, "missing": len(keys) - deleted}


@router.post("/api/enricher/bulk_apply")
async def bulk_apply_covers(body: BulkReq, request: Request):
    """Aplica en Telegram las copias indicadas (solo mensajes propios) con
    los datos guardados y BORRA la fila local tras edit OK. Reporte por fila."""
    _local_session_user(request)
    keys = [str(k or "").strip() for k in (body.keys or []) if str(k or "").strip()]
    if not keys:
        return {"ok": True, "report": []}
    conn = _conn()
    try:
        rows = {}
        for k in keys:
            r = conn.execute(
                "SELECT * FROM enriched_covers WHERE channelid_msgid=?", (k,)).fetchone()
            if r:
                rows[k] = dict(r)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    my_ids = _local_my_ids()
    report = []
    for k in keys:
        r = rows.get(k)
        if not r:
            report.append({"key": k, "ok": False, "skipped": True,
                           "reason": "ya no existe"})
            continue
        try:
            mid = int(r.get("telegram_msg_id") or 0)
        except Exception:
            mid = 0
        if mid in (-999, -1000):
            report.append({"key": k, "item_id": r.get("item_id"), "ok": False,
                           "skipped": True, "reason": "cover ficticio: solo local"})
            continue
        is_mine, author = await _row_is_mine(r, my_ids, request)
        if not is_mine or not author:
            report.append({"key": k, "item_id": r.get("item_id"), "ok": False,
                           "skipped": True, "reason": "mensaje ajeno"})
            continue
        link = r.get("telegram_link") or ""
        m = re.search(r"/c/(\d+)/", link)
        if not m:
            report.append({"key": k, "item_id": r.get("item_id"), "ok": False,
                           "error": "sin channel_id en el link"})
            continue
        try:
            from services.telegram_service import get_telegram_service
            svc = get_telegram_service()
            res = await svc.edit_message(
                channel_id="-100" + m.group(1), msg_id=mid,
                text=r.get("cover_text") or "",
                file_bytes=(bytes(r["poster_blob"]) if r.get("poster_blob") else None),
                file_name="cover.jpg", tg_user_id=int(author))
            if not (res or {}).get("ok"):
                raise RuntimeError((res or {}).get("error") or "edit_message falló")
        except Exception as e:
            report.append({"key": k, "item_id": r.get("item_id"), "ok": False,
                           "error": f"{type(e).__name__}: {str(e)[:150]}"})
            continue
        try:
            c2 = _conn()
            c2.execute("DELETE FROM enriched_covers WHERE channelid_msgid=?", (k,))
            c2.commit()
            c2.close()
        except Exception:
            pass
        _t = ""
        try:
            _t = (r.get("cover_text") or "").strip().split("\n")[0][:80]
        except Exception:
            pass
        report.append({"key": k, "item_id": r.get("item_id"), "title": _t,
                       "ok": True, "local_kept": False})
    return {"ok": True, "report": report}
