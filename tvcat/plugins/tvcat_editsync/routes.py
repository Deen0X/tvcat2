"""
tvcat_editsync — sync de ediciones locales (covers + colecciones) entre instancias.

- ZIP único (`formato:1`) o pull remoto con token (`X-Sync-Token`).
- Identidad híbrida: física `channelid_msgid` primero; lógica opt-in
  (title/original+year normalizados desde el cover).
- Dueño por canal; colecciones solo-local; tabla propia `editsync_pending`
  (nada en la DB central); standby de edición; página propia en "General".

Endpoints (sesión salvo hello/notify/pull con token):
- GET  /api/editsync/hello
- POST /api/editsync/notify {origen, since}
- GET  /api/editsync/pull?since=
- GET  /api/editsync/export
- POST /api/editsync/import (multipart ZIP)
- GET  /api/editsync/pending
- POST /api/editsync/pending/{id}/apply|discard
- POST /api/editsync/pull-now {peer} (trae + importa de un peer)
- GET/PUT /api/editsync/config (admin)
- POST /api/editsync/editing {item_id|null} (marca standby server-side)
"""
import asyncio
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import uuid
import zipfile

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import Response
from typing import Optional

router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "tvcat.db")
PENDING_COVERS_DIR = os.path.join(_DATA_DIR, "pending_covers")
os.makedirs(PENDING_COVERS_DIR, exist_ok=True)

_TVCAT_DIR = os.path.abspath(os.path.join(_PLUGIN_DIR, "..", ".."))
if _TVCAT_DIR not in sys.path:
    sys.path.insert(0, _TVCAT_DIR)

FORMATO = 1
EDITING_TTL_S = 300


# ─── DB del plugin ──────────────────────────────────────────────

def _pconn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return c


def _init_db():
    c = _pconn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS editsync_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            key TEXT NOT NULL,
            ident_json TEXT DEFAULT '{}',
            incoming_json TEXT NOT NULL,
            local_json TEXT DEFAULT '{}',
            state TEXT DEFAULT 'pending',
            created_at INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_editsync_pending_key ON editsync_pending(kind, key)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS editsync_config (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)
    c.commit()
    c.close()


_init_db()


def _central_conn():
    from services.catalog_service import get_conn
    return get_conn()


def _enricher_db():
    return os.path.join(_TVCAT_DIR, "plugins", "tvcat_enricher", "data", "tvcat.db")


def _enricher_conn():
    c = sqlite3.connect(_enricher_db(), timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return c


# ─── Sesión / auth ──────────────────────────────────────────────

def _session(request: Request):
    try:
        from services.auth_service import get_session
        return get_session(request.cookies.get("tvcat_session", ""))
    except Exception:
        return None


def _need_session(request: Request):
    s = _session(request)
    if not s:
        raise HTTPException(401, "Inicia sesión")
    return s


def _need_admin(request: Request):
    s = _need_session(request)
    if s.get("role") != "admin":
        raise HTTPException(403, "Solo admin")
    return s


# ─── Config (DB del plugin) ─────────────────────────────────────

def _cfg_all() -> dict:
    cfg = {"peers": [], "auto_export": False, "logical_mode": False,
           "notify_peers": True, "pull_pending": {}, "instance_id": ""}
    try:
        c = _pconn()
        for r in c.execute("SELECT key, value FROM editsync_config").fetchall():
            k = r["key"]
            if k in ("auto_export", "logical_mode", "notify_peers"):
                cfg[k] = str(r["value"]) == "1"
            elif k == "peers":
                try:
                    cfg[k] = json.loads(r["value"] or "[]") or []
                except Exception:
                    cfg[k] = []
            elif k in ("pull_pending",):
                try:
                    cfg[k] = json.loads(r["value"] or "{}") or {}
                except Exception:
                    cfg[k] = {}
            else:
                cfg[k] = r["value"] or ""
        c.close()
    except Exception:
        pass
    if not cfg["instance_id"]:
        cfg["instance_id"] = uuid.uuid4().hex[:8]
        _cfg_set("instance_id", cfg["instance_id"])
    return cfg


def _cfg_set(key: str, value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, bool):
        value = "1" if value else "0"
    else:
        value = str(value or "")
    c = _pconn()
    try:
        c.execute("INSERT OR REPLACE INTO editsync_config (key, value) VALUES (?, ?)", (key, value))
        c.commit()
    finally:
        try:
            c.close()
        except Exception:
            pass


def _peer_by_token(token: str):
    token = (token or "").strip()
    if not token:
        return None
    for p in (_cfg_all().get("peers") or []):
        try:
            if isinstance(p, dict) and str(p.get("token") or "") == token and token:
                return p
        except Exception:
            continue
    return None


def _token_of(request: Request) -> str:
    try:
        t = request.headers.get("x-sync-token", "") or ""
        if t.strip():
            return t.strip()
    except Exception:
        pass
    try:
        t = (request.query_params or {}).get("token", "") or ""
        return t.strip()
    except Exception:
        return ""


def _need_peer(request: Request):
    p = _peer_by_token(_token_of(request))
    if not p:
        raise HTTPException(401, "Token inválido")
    return p


# ─── Normalización lógica ───────────────────────────────────────

def _norm_logical(s: str) -> str:
    try:
        t = unicodedata.normalize("NFD", str(s or "").lower())
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
        t = re.sub(r"\s+", " ", t).strip()
        return t
    except Exception:
        return ""


def _ident_from_details(enrich_details) -> dict:
    """{title, original, year} normalizados desde enrich_details. Vacío si no hay."""
    try:
        d = enrich_details
        if isinstance(d, str):
            try:
                d = json.loads(d or "{}")
            except Exception:
                d = {}
        if not isinstance(d, dict):
            return {"title": "", "original": "", "year": ""}
        title = _norm_logical(d.get("api_title") or "")
        original = _norm_logical(d.get("api_original_title") or "")
        year = re.sub(r"\D", "", str(d.get("api_year") or ""))[:4]
        return {"title": title, "original": original, "year": year}
    except Exception:
        return {"title": "", "original": "", "year": ""}


def _ident_match(a: dict, b: dict) -> bool:
    """Match lógico: año obligatorio + (título u original iguales)."""
    try:
        a, b = a or {}, b or {}
        if not a.get("year") or a["year"] != b.get("year"):
            return False
        for k in ("title", "original"):
            if a.get(k) and a[k] == b.get(k):
                return True
        return False
    except Exception:
        return False


def _canon_hash(cover_text: str, enrich_details) -> str:
    try:
        d = enrich_details
        if isinstance(d, str):
            try:
                d = json.loads(d or "{}")
            except Exception:
                d = {}
        canon = json.dumps(d if isinstance(d, dict) else {}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(((cover_text or "") + "\n" + canon).encode("utf-8")).hexdigest()
    except Exception:
        return ""


# ─── Claves físicas ─────────────────────────────────────────────

def _key_from_link(link: str) -> str:
    try:
        from services.cache_keys import key_from_link
        return key_from_link(link or "") or ""
    except Exception:
        pass
    try:
        m = re.search(r"/c/(\d+)/", link or "")
        mid = re.search(r"/(\d+)/?$", link or "")
        if m and mid:
            return f"{m.group(1)}_{mid.group(1)}"
    except Exception:
        pass
    return ""


def _split_key(key: str):
    """key `bare_msgid` -> (channel_id canónico, msg_id)."""
    try:
        bare, mid = (key or "").rsplit("_", 1)
        mid = int(mid)
        try:
            from services.cache_keys import canon_channel
            cid = canon_channel(bare)
        except Exception:
            cid = ("-100" + bare) if len(bare) <= 13 and not bare.startswith("-") else bare
        return cid, mid
    except Exception:
        return "", 0


def _safe_cover_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", key or "x")[:80] + ".jpg"


# ─── Mis userbots / acceso / dueño ──────────────────────────────

def _my_tg_ids() -> set:
    out = set()
    try:
        import services.userbot_service as ubs
        for r in (ubs.list_sessions() or []):
            try:
                if r.get("tg_user_id") and r.get("is_active") == 1:
                    out.add(int(r["tg_user_id"]))
            except Exception:
                continue
        if not out:
            c = ubs._get_conn()
            try:
                for rr in c.execute("SELECT tg_user_id FROM telegram_users").fetchall():
                    try:
                        if rr["tg_user_id"]:
                            out.add(int(rr["tg_user_id"]))
                    except Exception:
                        continue
            finally:
                try:
                    c.close()
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _svc():
    from services.telegram_service import get_telegram_service
    return get_telegram_service()


async def _channel_accessible(channel_id: str) -> bool:
    try:
        await _svc().get_entity(str(channel_id))
        return True
    except Exception:
        return False


def _author_from_raw(raw: dict):
    """(author_id|None, is_out). Del Message.to_dict() de telethon."""
    try:
        raw = raw or {}
        if raw.get("out") is True:
            return None, True
        fid = raw.get("from_id") or raw.get("from") or {}
        if isinstance(fid, int) and fid:
            return int(fid), False
        if isinstance(fid, dict):
            if fid.get("_") == "PeerUser" and fid.get("user_id"):
                return int(fid["user_id"]), False
            if fid.get("user_id"):
                return int(fid["user_id"]), False
        return None, False
    except Exception:
        return None, False


async def _channel_is_mine(channel_id: str, sample_msg_id: int = 0, _cache: dict = None) -> bool:
    """Dueño por canal (se evalúa una vez por canal en cada import)."""
    try:
        if _cache is not None and channel_id in _cache:
            return bool(_cache[channel_id])
        mine = False
        try:
            if await _svc().check_owner(str(channel_id)):
                mine = True
        except Exception:
            pass
        if not mine and sample_msg_id:
            try:
                msg = await _svc().fetch_one(str(channel_id), int(sample_msg_id))
                raw = msg if isinstance(msg, dict) else {}
                author, is_out = _author_from_raw(raw)
                ids = _my_tg_ids()
                if is_out and ids:
                    mine = True
                elif author and author in ids:
                    mine = True
            except Exception:
                pass
        if _cache is not None:
            _cache[channel_id] = mine
        return mine
    except Exception:
        return False


# ─── Marca de edición (standby server-side) ─────────────────────

def _editing_key(user_id) -> str:
    return f"editsync_editing_{int(user_id or 0)}"


def _editing_get(user_id):
    try:
        conn = _central_conn()
        try:
            row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?",
                               (_editing_key(user_id),)).fetchone()
            if not row:
                return None
            v = row[0] if not isinstance(row, dict) else row.get("value")
            d = json.loads(v or "{}")
            if not isinstance(d, dict):
                return None
            if int(time.time()) - int(d.get("at") or 0) > EDITING_TTL_S:
                return None
            return d
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return None


def _editing_set(user_id, item_id_or_none):
    try:
        conn = _central_conn()
        try:
            if item_id_or_none:
                conn.execute(
                    "INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                    (_editing_key(user_id),
                     json.dumps({"item_id": item_id_or_none, "at": int(time.time())})))
            else:
                conn.execute("DELETE FROM tvcat_settings WHERE key=?", (_editing_key(user_id),))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass


def _editing_item_to_key(conn_central, item_id: str) -> str:
    """item_id en edición -> key física (vía telegram_link central)."""
    try:
        row = conn_central.execute(
            "SELECT telegram_link FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
        if not row:
            return ""
        link = row[0] if not isinstance(row, dict) else row.get("telegram_link")
        return _key_from_link(link or "")
    except Exception:
        return ""


# ─── Export ─────────────────────────────────────────────────────

def _export_rows(since: int = 0):
    rows = []
    try:
        if not os.path.isfile(_enricher_db()):
            return rows
        c = sqlite3.connect(f"file:{_enricher_db()}?mode=ro", uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            q = ("SELECT channelid_msgid, item_id, telegram_msg_id, telegram_link,"
                 " cover_text, enrich_details, poster_blob, poster_mime, updated_at"
                 " FROM enriched_covers")
            params: tuple = ()
            if since:
                q += " WHERE updated_at>=?"
                params = (int(since),)
            q += " ORDER BY updated_at ASC"
            rows = [dict(r) for r in c.execute(q, params).fetchall()]
        finally:
            try:
                c.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[EditSync] export rows: {e}", flush=True)
    return rows


def _export_collections():
    try:
        from services.catalog_service import list_local_collections
        return list_local_collections() or []
    except Exception as e:
        print(f"[EditSync] export collections: {e}", flush=True)
        return []


def build_package(since: int = 0, instance_id: str = "") -> bytes:
    """Construye el ZIP formato:1 en memoria. Sin secretos."""
    cfg = _cfg_all()
    now = int(time.time())
    titles, counts_covers = [], 0
    cover_files = {}
    for r in _export_rows(since):
        try:
            det_raw = r.get("enrich_details") or "{}"
            try:
                det = json.loads(det_raw) if isinstance(det_raw, str) else det_raw
            except Exception:
                det = {}
            ident = _ident_from_details(det)
            key = str(r.get("channelid_msgid") or "")
            blob = r.get("poster_blob")
            blob = bytes(blob) if blob else b""
            entry = {
                "key": key,
                "telegram_link": r.get("telegram_link") or "",
                "item_id": r.get("item_id") or "",
                "ident": ident if (ident.get("title") and ident.get("year")) else {},
                "cover_text": r.get("cover_text") or "",
                "enrich_details": det if isinstance(det, dict) else {},
                "updated_at": int(r.get("updated_at") or 0),
                "hash": _canon_hash(r.get("cover_text") or "", det),
            }
            if blob:
                fn = _safe_cover_name(key)
                entry["poster_file"] = fn
                try:
                    entry["poster_mime"] = r.get("poster_mime") or "image/jpeg"
                except Exception:
                    pass
                cover_files[fn] = blob
                counts_covers += 1
            titles.append(entry)
        except Exception:
            continue
    collections = []
    try:
        for col in _export_collections():
            try:
                collections.append({
                    "name": col.get("name") or "",
                    "serial": col.get("serial") or "",
                    "entries": col.get("entries_json") or col.get("entries") or [],
                    "description": col.get("description") or "",
                    "cover_text": col.get("cover_text") or "",
                    "cover_asset_key": col.get("cover_asset_key") or "",
                })
            except Exception:
                continue
    except Exception:
        pass
    manifest = {
        "formato": FORMATO,
        "origen": instance_id or cfg.get("instance_id") or "",
        "creado": now,
        "modo_logico": bool(cfg.get("logical_mode")),
        "counts": {"titles": len(titles), "collections": len(collections)},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr("titles.json", json.dumps(titles, ensure_ascii=False))
        z.writestr("collections.json", json.dumps(collections, ensure_ascii=False))
        for fn, blob in cover_files.items():
            z.writestr("covers/" + fn, blob)
    return buf.getvalue()


# ─── Import: matriz ─────────────────────────────────────────────

def _local_enriched_row(key: str):
    try:
        if not os.path.isfile(_enricher_db()):
            return None
        c = sqlite3.connect(f"file:{_enricher_db()}?mode=ro", uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            r = c.execute("SELECT * FROM enriched_covers WHERE channelid_msgid=?", (key,)).fetchone()
            return dict(r) if r else None
        finally:
            try:
                c.close()
            except Exception:
                pass
    except Exception:
        return None


def _upsert_enriched(key: str, item_id: str, link: str, cover_text: str,
                     details: dict, poster: bytes, mime: str):
    c = sqlite3.connect(_enricher_db(), timeout=30)
    try:
        try:
            c.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass
        now = int(time.time())
        msg_id = 0
        try:
            _cid, _mid = _split_key(key)
            msg_id = int(_mid or 0)
        except Exception:
            pass
        c.execute("""
            INSERT INTO enriched_covers
            (channelid_msgid, item_id, telegram_msg_id, telegram_link, cover_text,
             enrich_details, poster_blob, poster_mime, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channelid_msgid) DO UPDATE SET
                item_id=excluded.item_id, telegram_msg_id=excluded.telegram_msg_id,
                telegram_link=excluded.telegram_link, cover_text=excluded.cover_text,
                enrich_details=excluded.enrich_details, poster_blob=excluded.poster_blob,
                poster_mime=excluded.poster_mime, updated_at=excluded.updated_at
        """, (key, item_id or "", msg_id or None, link or "", cover_text or "",
              json.dumps(details or {}, ensure_ascii=False),
              bytes(poster) if poster else None, mime or "image/jpeg", now, now))
        c.commit()
    finally:
        try:
            c.close()
        except Exception:
            pass


def _pending_add(kind: str, key: str, ident: dict, incoming: dict, local: dict, state: str = "pending"):
    c = _pconn()
    try:
        now = int(time.time())
        c.execute("""
            INSERT INTO editsync_pending
            (kind, key, ident_json, incoming_json, local_json, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (kind, key, json.dumps(ident or {}, ensure_ascii=False),
              json.dumps(incoming or {}, ensure_ascii=False),
              json.dumps(local or {}, ensure_ascii=False), state, now, now))
        c.commit()
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        try:
            c.close()
        except Exception:
            pass


def _purge_resolved():
    try:
        c = _pconn()
        try:
            c.execute("DELETE FROM editsync_pending WHERE state IN ('done','discarded')")
            c.commit()
        finally:
            try:
                c.close()
            except Exception:
                pass
    except Exception:
        pass


def _read_package(data: bytes):
    """-> (manifest, titles, collections, covers{fn:bytes}). ZipSlip-safe."""
    try:
        buf = io.BytesIO(data or b"")
        with zipfile.ZipFile(buf) as z:
            names = z.namelist()
            if "manifest.json" not in names or "titles.json" not in names:
                return None, "ZIP sin manifest/titles"
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("formato") != FORMATO:
                return None, f"formato no soportado ({(manifest or {}).get('formato')})"
            titles = json.loads(z.read("titles.json").decode("utf-8") or "[]") or []
            collections = []
            if "collections.json" in names:
                try:
                    collections = json.loads(z.read("collections.json").decode("utf-8") or "[]") or []
                except Exception:
                    collections = []
            covers = {}
            for n in names:
                if not n.startswith("covers/"):
                    continue
                fn = n[len("covers/"):]
                if not fn or "/" in fn or fn.startswith(".") or ".." in fn:
                    continue
                try:
                    covers[fn] = z.read(n)
                except Exception:
                    continue
            return {"manifest": manifest, "titles": titles,
                    "collections": collections, "covers": covers}, ""
    except Exception as e:
        return None, f"ZIP inválido: {e}"


async def apply_package(pkg: dict, session: dict, access=None, owner=None):
    """Aplica la matriz. access/owner inyectables para tests.
    -> {applied, pending, skipped, bypassed, errors[]}."""
    res = {"applied": 0, "pending": 0, "skipped": 0, "bypassed": 0, "errors": []}
    try:
        cfg = _cfg_all()
        logical = bool(cfg.get("logical_mode"))
        manifest = pkg.get("manifest") or {}
        if logical or manifest.get("modo_logico"):
            logical = True
        owner_cache = {}
        editing_marks = {}

        async def _is_owner(cid, mid):
            if owner is not None:
                try:
                    return bool(owner(cid, mid))
                except Exception:
                    return False
            return await _channel_is_mine(cid, mid, owner_cache)

        async def _has_access(cid):
            if access is not None:
                try:
                    return bool(access(cid))
                except Exception:
                    return False
            return await _channel_accessible(cid)

        def _standby_for(user_id, key):
            try:
                if user_id in editing_marks:
                    return editing_marks[user_id]
                mark = _editing_get(user_id)
                if not mark:
                    editing_marks[user_id] = ""
                    return ""
                try:
                    conn = _central_conn()
                    try:
                        k = _editing_item_to_key(conn, str(mark.get("item_id") or ""))
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                except Exception:
                    k = ""
                editing_marks[user_id] = k or ""
                return editing_marks[user_id]
            except Exception:
                return ""

        user_id = (session or {}).get("user_id") or 0

        for t in (pkg.get("titles") or []):
            try:
                if not isinstance(t, dict):
                    continue
                key = str(t.get("key") or "")
                if not key:
                    res["errors"].append("entrada sin key")
                    continue
                cid, mid = _split_key(key)
                if not cid:
                    res["errors"].append(f"key inválida: {key}")
                    continue
                # Acceso / bypass
                has_access = await _has_access(cid)
                ident = t.get("ident") if isinstance(t.get("ident"), dict) else {}
                local = _local_enriched_row(key)
                local_ident = _ident_from_details((local or {}).get("enrich_details")) if local else {"title": "", "original": "", "year": ""}
                logical_ok = False
                if logical and ident.get("title") and ident.get("year"):
                    # match lógico contra el local (si existe) o válido para importar
                    if local and _ident_match(ident, local_ident):
                        logical_ok = True
                    elif not local:
                        logical_ok = True
                if not has_access and not (logical and logical_ok):
                    res["bypassed"] += 1
                    continue
                # Skips baratos
                incoming_hash = str(t.get("hash") or "")
                if local and incoming_hash and incoming_hash == _canon_hash(
                        local.get("cover_text") or "", local.get("enrich_details")):
                    res["skipped"] += 1
                    continue
                if local and t.get("updated_at") and local.get("updated_at"):
                    try:
                        if int(local["updated_at"]) > int(t["updated_at"]):
                            res["skipped"] += 1
                            continue
                    except Exception:
                        pass
                # Standby: modal editando esta key
                if _standby_for(user_id, key) == key:
                    _poster0 = (pkg.get("covers") or {}).get(str(t.get("poster_file") or "")) or b""
                    _pending_add("title", key, ident,
                                 {"cover_text": t.get("cover_text") or "",
                                  "enrich_details": t.get("enrich_details") or {},
                                  "poster_file": str(t.get("poster_file") or ""),
                                  "staged": _stage_cover(key, _poster0) if _poster0 else "",
                                  "link": t.get("telegram_link") or "",
                                  "item_id": t.get("item_id") or ""},
                                 {"cover_text": (local or {}).get("cover_text") or "",
                                  "updated_at": (local or {}).get("updated_at") or 0},
                                 state="standby")
                    res["pending"] += 1
                    continue
                is_owner = await _is_owner(cid, mid)
                poster = (pkg.get("covers") or {}).get(str(t.get("poster_file") or "")) or b""
                if not local:
                    # Sin local: dueño o no, se guarda en local (nunca Telegram)
                    _upsert_enriched(key, t.get("item_id") or "", t.get("telegram_link") or "",
                                     t.get("cover_text") or "", t.get("enrich_details") or {},
                                     poster, t.get("poster_mime") or "image/jpeg")
                    res["applied"] += 1
                    continue
                # Con local distinto: pending con diff (dueño o no)
                _pending_add("title", key, ident,
                             {"cover_text": t.get("cover_text") or "",
                              "enrich_details": t.get("enrich_details") or {},
                              "poster_file": str(t.get("poster_file") or ""),
                              "staged": _stage_cover(key, poster) if poster else "",
                              "link": t.get("telegram_link") or "",
                              "item_id": t.get("item_id") or ""},
                             {"cover_text": local.get("cover_text") or "",
                              "updated_at": local.get("updated_at") or 0},
                             state="pending")
                res["pending"] += 1
            except Exception as e:
                res["errors"].append(str(e)[:200])

        # Colecciones: siempre lógicas, solo local
        try:
            from services.catalog_service import list_local_collections, create_local_collection
        except Exception:
            try:
                from tvcat.services.catalog_service import list_local_collections, create_local_collection
            except Exception:
                list_local_collections = create_local_collection = None
        if list_local_collections and create_local_collection:
            try:
                existing = {str(c.get("serial") or ""): c for c in (list_local_collections() or [])}
            except Exception:
                existing = {}
            for col in (pkg.get("collections") or []):
                try:
                    if not isinstance(col, dict):
                        continue
                    serial = str(col.get("serial") or "")
                    name = str(col.get("name") or "")
                    if not serial and not name:
                        continue
                    if serial and serial in existing:
                        _pending_add("collection", serial, {}, dict(col), dict(existing[serial]), state="pending")
                        res["pending"] += 1
                        continue
                    try:
                        create_local_collection(name or serial, serial,
                                                col.get("entries") or [],
                                                user_id=user_id or None,
                                                description=col.get("description") or "",
                                                cover_text=col.get("cover_text") or "")
                        res["applied"] += 1
                    except Exception as e:
                        res["errors"].append(f"colección {name}: {str(e)[:120]}")
                except Exception as e:
                    res["errors"].append(str(e)[:200])
        _purge_resolved()
        return res
    except Exception as e:
        res["errors"].append(str(e)[:200])
        return res


def _stage_cover(key: str, blob: bytes):
    """Guarda el póster entrante en staging para apply posterior."""
    try:
        if not blob:
            return ""
        fn = _safe_cover_name("staged-" + (key or "x") + "-" + str(int(time.time())))
        with open(os.path.join(PENDING_COVERS_DIR, fn), "wb") as f:
            f.write(bytes(blob))
        return fn
    except Exception:
        return ""


def _staged_path(fn: str) -> str:
    try:
        fn = os.path.basename(fn or "")
        if not fn or "/" in fn or fn.startswith(".") or ".." in fn:
            return ""
        p = os.path.join(PENDING_COVERS_DIR, fn)
        return p if os.path.isfile(p) else ""
    except Exception:
        return ""


def _staged_path(fn: str) -> str:
    try:
        fn = os.path.basename(fn or "")
        if not fn or "/" in fn or fn.startswith(".") or ".." in fn:
            return ""
        p = os.path.join(PENDING_COVERS_DIR, fn)
        return p if os.path.isfile(p) else ""
    except Exception:
        return ""


def _staged_delete(fn: str):
    try:
        p = _staged_path(fn)
        if p:
            os.remove(p)
    except Exception:
        pass


def _pending_row(pid: int):
    try:
        c = _pconn()
        try:
            r = c.execute("SELECT * FROM editsync_pending WHERE id=?", (int(pid),)).fetchone()
            return dict(r) if r else None
        finally:
            try:
                c.close()
            except Exception:
                pass
    except Exception:
        return None


def _pending_delete(pid: int):
    try:
        row = _pending_row(pid)
        if row:
            try:
                inc = json.loads(row.get("incoming_json") or "{}")
                _staged_delete(inc.get("staged") or "")
            except Exception:
                pass
        c = _pconn()
        try:
            c.execute("DELETE FROM editsync_pending WHERE id=?", (int(pid),))
            c.commit()
        finally:
            try:
                c.close()
            except Exception:
                pass
    except Exception:
        pass


# ─── Endpoints remotos (token) ──────────────────────────────────

@router.get("/api/editsync/hello")
async def hello(request: Request):
    _need_peer(request)
    try:
        n_titles = len(_export_rows(0))
    except Exception:
        n_titles = 0
    try:
        n_cols = len(_export_collections())
    except Exception:
        n_cols = 0
    return {"ok": True, "formato": FORMATO, "titles": n_titles, "collections": n_cols}


@router.post("/api/editsync/notify")
async def notify(request: Request):
    _need_peer(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    _cfg_set("pull_pending", {"from": str(body.get("origen") or "?"),
                              "at": int(time.time()),
                              "since": int(body.get("since") or 0)})
    return {"ok": True}


@router.get("/api/editsync/pull")
async def pull(request: Request, since: int = 0):
    _need_peer(request)
    try:
        data = build_package(int(since or 0))
    except Exception as e:
        raise HTTPException(500, f"No se pudo generar: {e}")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=editsync-pull.zip"})


# ─── Endpoints locales (sesión) ─────────────────────────────────

@router.get("/api/editsync/export")
async def export_all(request: Request):
    _need_session(request)
    try:
        data = build_package(0)
    except Exception as e:
        raise HTTPException(500, f"No se pudo generar: {e}")
    ts = time.strftime("%Y%m%d-%H%M")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=editsync-{ts}.zip"})


@router.post("/api/editsync/import")
async def import_zip(request: Request, file: UploadFile = File(...)):
    sess = _need_session(request)
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer: {e}")
    if not data or len(data) > 300 * 1024 * 1024:
        raise HTTPException(400, "ZIP vacío o demasiado grande (>300MB)")
    pkg, err = _read_package(data)
    if not pkg:
        raise HTTPException(400, err or "ZIP inválido")
    res = await apply_package(pkg, sess)
    return res


@router.get("/api/editsync/pending")
async def pending_list(request: Request):
    _need_session(request)
    out = []
    try:
        c = _pconn()
        try:
            rows = c.execute(
                "SELECT * FROM editsync_pending WHERE state IN ('pending','standby')"
                " ORDER BY state DESC, updated_at DESC").fetchall()
        finally:
            try:
                c.close()
            except Exception:
                pass
        for r in rows:
            try:
                d = dict(r)
                inc = json.loads(d.get("incoming_json") or "{}")
                loc = json.loads(d.get("local_json") or "{}")
                ident = json.loads(d.get("ident_json") or "{}")
                out.append({
                    "id": d["id"], "kind": d.get("kind"), "key": d.get("key"),
                    "state": d.get("state"), "updated_at": d.get("updated_at"),
                    "ident": ident,
                    "incoming_text": (inc.get("cover_text") or "")[:2000],
                    "local_text": (loc.get("cover_text") or "")[:2000],
                    "text_differs": (inc.get("cover_text") or "") != (loc.get("cover_text") or ""),
                    "incoming_poster": bool(inc.get("poster_file") or inc.get("staged")),
                    "incoming_name": (inc.get("item_id") or "") or (ident.get("title") or d.get("key")),
                })
            except Exception:
                continue
    except Exception as e:
        raise HTTPException(500, str(e)[:200])
    return {"pending": out}


@router.post("/api/editsync/pending/{pid}/apply")
async def pending_apply(pid: int, request: Request):
    _need_session(request)
    row = _pending_row(pid)
    if not row or row.get("state") not in ("pending", "standby"):
        raise HTTPException(404, "Pendiente no encontrado")
    try:
        inc = json.loads(row.get("incoming_json") or "{}")
    except Exception:
        inc = {}
    try:
        if row.get("kind") == "collection":
            try:
                from services.catalog_service import list_local_collections, update_local_collection
            except Exception:
                from tvcat.services.catalog_service import list_local_collections, update_local_collection
            target = None
            try:
                for c in (list_local_collections() or []):
                    if str(c.get("serial") or "") == str(row.get("key") or ""):
                        target = c
                        break
            except Exception:
                target = None
            if not target:
                raise HTTPException(404, "Colección local no encontrada")
            update_local_collection(target["item_id"], name=inc.get("name") or None,
                                    entries=inc.get("entries"),
                                    description=inc.get("description"),
                                    cover_text=inc.get("cover_text"))
        else:
            poster = b""
            mime = "image/jpeg"
            try:
                sp = _staged_path(inc.get("staged") or "")
                if sp:
                    with open(sp, "rb") as f:
                        poster = f.read()
            except Exception:
                poster = b""
            _upsert_enriched(str(row.get("key") or ""), inc.get("item_id") or "",
                             inc.get("link") or "", inc.get("cover_text") or "",
                             inc.get("enrich_details") or {}, poster, mime)
            _staged_delete(inc.get("staged") or "")
        _pending_delete(pid)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e)[:200])


@router.post("/api/editsync/pending/{pid}/discard")
async def pending_discard(pid: int, request: Request):
    _need_session(request)
    row = _pending_row(pid)
    if not row:
        raise HTTPException(404, "Pendiente no encontrado")
    _pending_delete(pid)
    return {"ok": True}


@router.post("/api/editsync/pull-now")
async def pull_now(request: Request):
    sess = _need_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = str((body or {}).get("peer") or "")
    peer = None
    for p in (_cfg_all().get("peers") or []):
        if isinstance(p, dict) and str(p.get("name") or "") == name:
            peer = p
            break
    if not peer:
        raise HTTPException(404, "Peer no encontrado")
    url = str(peer.get("base_url") or "").rstrip("/") + "/api/editsync/pull"
    try:
        import httpx
        headers = {"X-Sync-Token": str(peer.get("token") or "")}
        with httpx.Client(timeout=120) as cli:
            r = cli.get(url, headers=headers)
        if r.status_code != 200:
            raise HTTPException(502, f"Peer respondió {r.status_code}")
        pkg, err = _read_package(r.content)
        if not pkg:
            raise HTTPException(502, err or "ZIP del peer inválido")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"No se pudo traer: {str(e)[:200]}")
    res = await apply_package(pkg, sess)
    try:
        _cfg_set("pull_pending", {})
    except Exception:
        pass
    return res


@router.get("/api/editsync/config")
async def config_get(request: Request):
    sess = _need_admin(request)
    cfg = _cfg_all()
    peers = []
    for p in (cfg.get("peers") or []):
        if isinstance(p, dict):
            peers.append({"name": p.get("name") or "",
                          "base_url": p.get("base_url") or "",
                          "has_token": bool(p.get("token"))})
    return {"peers": peers, "auto_export": bool(cfg.get("auto_export")),
            "logical_mode": bool(cfg.get("logical_mode")),
            "notify_peers": bool(cfg.get("notify_peers", True)),
            "pull_pending": cfg.get("pull_pending") or {},
            "instance_id": cfg.get("instance_id") or "",
            "is_admin": (sess.get("role") == "admin")}


@router.put("/api/editsync/config")
async def config_put(request: Request):
    _need_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if "peers" in body:
        clean = []
        for p in (body.get("peers") or []):
            if not isinstance(p, dict):
                continue
            name = str(p.get("name") or "").strip()[:60]
            base = str(p.get("base_url") or "").strip().rstrip("/")[:200]
            token = str(p.get("token") or "")
            if not name or not base:
                continue
            if not token and p.get("has_token"):
                try:
                    for old in (_cfg_all().get("peers") or []):
                        if isinstance(old, dict) and str(old.get("name") or "") == name and old.get("token"):
                            token = old["token"]
                            break
                except Exception:
                    pass
            clean.append({"name": name, "base_url": base, "token": token})
        _cfg_set("peers", clean)
    for k in ("auto_export", "logical_mode", "notify_peers"):
        if k in body:
            _cfg_set(k, bool(body.get(k)))
    return {"ok": True}


@router.post("/api/editsync/editing")
async def editing_mark(request: Request):
    sess = _need_session(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    item_id = str((body or {}).get("item_id") or "")
    _editing_set(sess.get("user_id") or 0, item_id or None)
    return {"ok": True}


# ─── Hooks para el enriquecedor (guardados, sin acoplar en caliente) ──

def discard_pending_for_key(key: str):
    """Regla de descarte: editar localmente purga pendientes/standby de la key."""
    try:
        if not key:
            return
        c = _pconn()
        try:
            rows = c.execute("SELECT id, incoming_json FROM editsync_pending WHERE key=? AND state IN ('pending','standby')",
                             (str(key),)).fetchall()
            for r in rows:
                try:
                    inc = json.loads(dict(r).get("incoming_json") or "{}")
                    _staged_delete(inc.get("staged") or "")
                except Exception:
                    pass
            c.execute("DELETE FROM editsync_pending WHERE key=? AND state IN ('pending','standby')", (str(key),))
            c.commit()
        finally:
            try:
                c.close()
            except Exception:
                pass
    except Exception:
        pass


async def _notify_all_peers():
    try:
        cfg = _cfg_all()
        if not cfg.get("auto_export") or not cfg.get("notify_peers", True):
            return
        peers = [p for p in (cfg.get("peers") or []) if isinstance(p, dict) and p.get("base_url") and p.get("token")]
        if not peers:
            return
        import httpx
        async with httpx.AsyncClient(timeout=10) as cli:
            for p in peers:
                try:
                    await cli.post(str(p["base_url"]).rstrip("/") + "/api/editsync/notify",
                                   json={"origen": cfg.get("instance_id") or "", "since": int(time.time())},
                                   headers={"X-Sync-Token": str(p.get("token") or "")})
                except Exception as e:
                    print(f"[EditSync] notify {p.get('name')}: {e}", flush=True)
    except Exception as e:
        print(f"[EditSync] notify error: {e}", flush=True)


def notify_local_save(user_id=None, channelid_key: str = ""):
    """Hook post-save del enriquecedor: purga pendientes de la key, limpia la
    marca de edición (el local gana) y notifica peers (fire-and-forget)."""
    try:
        if channelid_key:
            discard_pending_for_key(channelid_key)
        if user_id:
            _editing_set(user_id, None)
    except Exception:
        pass
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_notify_all_peers())
            return
    except Exception:
        pass
    try:
        asyncio.run(_notify_all_peers())
    except Exception:
        pass

