"""
tvcat_card_frames — plugin grid-decorator de marcos PNG sobre el cover.

Modelo:
- card_borders: pares idle/selected en BLOB (seed con Border1_Off/On.png).
- card_sets: orden first-wins + categories/subcategories + border_id + enabled.
- card_config: default_border_id.
- Prefs por usuario-dispositivo en DB central (tvcat_settings, key cardframes_pref_{user_id}).
"""

import os
import re
import json
import time
import uuid
import sqlite3
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
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
        CREATE TABLE IF NOT EXISTS card_borders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            idle_blob BLOB NOT NULL,
            idle_mime TEXT DEFAULT 'image/png',
            selected_blob BLOB NOT NULL,
            selected_mime TEXT DEFAULT 'image/png',
            created_at INTEGER, updated_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS card_sets (
            id TEXT PRIMARY KEY,
            border_id TEXT NOT NULL,
            name TEXT NOT NULL,
            categories TEXT DEFAULT '',
            subcategories TEXT DEFAULT '',
            position INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at INTEGER, updated_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS card_config (
            key TEXT PRIMARY KEY, value TEXT
        )
    """)
    c.commit()
    c.close()
    _seed_default()


def _seed_default():
    """Siembra el par Border1 como borde default (una sola vez)."""
    try:
        c = _conn()
        n = c.execute("SELECT COUNT(*) AS n FROM card_borders").fetchone()["n"]
        if n and int(n) > 0:
            c.close()
            return
        # Border1 vive en la raíz del proyecto (4 niveles sobre el plugin).
        cands = [
            os.path.join(_PLUGIN_DIR, "..", "..", "..", "..", "Border1_Off.png"),
            os.path.join(_PLUGIN_DIR, "..", "..", "..", "Border1_Off.png"),
            os.path.join(_PLUGIN_DIR, "Border1_Off.png"),
        ]
        off = on = None
        for p in cands:
            try:
                p = os.path.normpath(p)
                if os.path.isfile(p):
                    with open(p, "rb") as f:
                        off = f.read()
                    break
            except Exception:
                pass
        cands_on = [
            os.path.join(_PLUGIN_DIR, "..", "..", "..", "..", "Border1_On.png"),
            os.path.join(_PLUGIN_DIR, "..", "..", "..", "Border1_On.png"),
            os.path.join(_PLUGIN_DIR, "Border1_On.png"),
        ]
        for p in cands_on:
            try:
                p = os.path.normpath(p)
                if os.path.isfile(p):
                    with open(p, "rb") as f:
                        on = f.read()
                    break
            except Exception:
                pass
        if not off or not on:
            c.close()
            return
        now = int(time.time())
        bid = "border-artdeco-1"
        c.execute(
            "INSERT OR IGNORE INTO card_borders (id, name, idle_blob, idle_mime, selected_blob, selected_mime, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (bid, "ArtDeco", sqlite3.Binary(off), "image/png", sqlite3.Binary(on), "image/png", now, now),
        )
        c.execute(
            "INSERT OR IGNORE INTO card_sets (id, border_id, name, categories, subcategories, position, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("set-default", bid, "Default", "", "", 0, 1, now, now),
        )
        c.execute("INSERT OR IGNORE INTO card_config (key, value) VALUES (?,?)", ("default_border_id", bid))
        c.commit()
        c.close()
    except Exception:
        pass


_init_db()


def _sess(request: Request):
    try:
        from services.auth_service import get_session
        return get_session(request.cookies.get("tvcat_session", ""))
    except Exception:
        return None


def _need_login(request: Request):
    s = _sess(request)
    if not s:
        raise HTTPException(status_code=401, detail="Login requerido")
    return s


def _need_admin(request: Request):
    s = _need_login(request)
    try:
        if s.get("role") == "admin":
            return s
        if (s.get("username", "").lower() == "admin") or s.get("is_admin"):
            return s
    except Exception:
        pass
    raise HTTPException(status_code=403, detail="Solo admin")


def _central_conn():
    from services.catalog_service import get_conn
    return get_conn()


def _pref_key(user_id) -> str:
    return f"cardframes_pref_{user_id}"


def _load_pref_map(user_id) -> dict:
    try:
        conn = _central_conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (_pref_key(user_id),)).fetchone()
        conn.close()
        if row and row[0]:
            d = json.loads(row[0])
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _save_pref_map(user_id, data: dict):
    conn = _central_conn()
    conn.execute(
        "INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)",
        (_pref_key(user_id), json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


_DEFAULT_PREF = {"enabled": True, "shine_enabled": True, "shine_delay_ms": 800, "shine_period_ms": 2600}


# ---------- Lectura pública (requiere login) ----------

@router.get("/api/cardframes/sets")
async def list_sets(request: Request):
    _need_login(request)
    c = _conn()
    borders = []
    for r in c.execute("SELECT id, name, length(idle_blob) AS idle_len, length(selected_blob) AS sel_len FROM card_borders ORDER BY name").fetchall():
        borders.append({"id": r["id"], "name": r["name"], "idle_bytes": r["idle_len"], "selected_bytes": r["sel_len"]})
    sets = []
    for r in c.execute("SELECT id, border_id, name, categories, subcategories, position, enabled FROM card_sets ORDER BY position, name").fetchall():
        sets.append({
            "id": r["id"], "border_id": r["border_id"], "name": r["name"],
            "categories": r["categories"] or "", "subcategories": r["subcategories"] or "",
            "position": r["position"] or 0, "enabled": int(r["enabled"] or 0),
        })
    cfg = c.execute("SELECT value FROM card_config WHERE key='default_border_id'").fetchone()
    try:
        vrow = c.execute("SELECT MAX(updated_at) AS v FROM (SELECT updated_at FROM card_borders UNION ALL SELECT updated_at FROM card_sets)").fetchone()
        v = int(vrow["v"] or 0)
    except Exception:
        v = 0
    c.close()
    return {"borders": borders, "sets": sets, "default_border_id": cfg["value"] if cfg else None, "v": v}


@router.get("/api/cardframes/img/{border_id}/{kind}")
async def serve_img(border_id: str, kind: str, request: Request):
    _need_login(request)
    col = "idle_blob" if kind == "idle" else "selected_blob" if kind == "selected" else None
    mime_col = "idle_mime" if kind == "idle" else "selected_mime" if kind == "selected" else None
    if not col:
        raise HTTPException(status_code=400, detail="kind inválido (idle|selected)")
    c = _conn()
    r = c.execute(f"SELECT {col} AS blob, {mime_col} AS mime FROM card_borders WHERE id=?", (border_id,)).fetchone()
    c.close()
    if not r or r["blob"] is None:
        raise HTTPException(status_code=404, detail="borde no encontrado")
    blob = bytes(r["blob"])
    mime = r["mime"] or "image/png"
    return Response(content=blob, media_type=mime, headers={"Cache-Control": "max-age=86400", "Content-Length": str(len(blob))})


# ---------- Prefs por usuario-dispositivo (servidor) ----------

class PrefBody(BaseModel):
    device_id: str = ""
    enabled: Optional[bool] = None
    shine_enabled: Optional[bool] = None
    shine_delay_ms: Optional[int] = None
    shine_period_ms: Optional[int] = None


@router.get("/api/cardframes/prefs")
async def get_prefs(request: Request, device_id: str = ""):
    s = _need_login(request)
    uid = s.get("user_id") or s.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Sin usuario")
    data = _load_pref_map(uid)
    devs = data.get("devices") or {}
    pref = dict(_DEFAULT_PREF)
    if device_id and isinstance(devs.get(device_id), dict):
        for k in pref:
            if k in devs[device_id]:
                pref[k] = devs[device_id][k]
    return {"device_id": device_id, "prefs": pref}


@router.post("/api/cardframes/prefs")
async def save_prefs(body: PrefBody, request: Request):
    s = _need_login(request)
    uid = s.get("user_id") or s.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Sin usuario")
    dev = (body.device_id or "").strip() or "default"
    data = _load_pref_map(uid)
    if not isinstance(data.get("devices"), dict):
        data["devices"] = {}
    cur = dict(_DEFAULT_PREF)
    if isinstance(data["devices"].get(dev), dict):
        cur.update(data["devices"][dev])
    if body.enabled is not None:
        cur["enabled"] = bool(body.enabled)
    if body.shine_enabled is not None:
        cur["shine_enabled"] = bool(body.shine_enabled)
    if body.shine_delay_ms is not None:
        try:
            cur["shine_delay_ms"] = max(0, min(10000, int(body.shine_delay_ms)))
        except Exception:
            pass
    if body.shine_period_ms is not None:
        try:
            cur["shine_period_ms"] = max(600, min(20000, int(body.shine_period_ms)))
        except Exception:
            pass
    data["devices"][dev] = cur
    _save_pref_map(uid, data)
    return {"ok": True, "device_id": dev, "prefs": cur}


# ---------- CRUD (solo admin) ----------

@router.post("/api/cardframes/borders")
async def create_border(
    request: Request,
    name: str = Form(""),
    idle: UploadFile = File(...),
    selected: UploadFile = File(...),
):
    _need_admin(request)
    nm = (name or "").strip() or "Sin nombre"
    idle_bytes = await idle.read()
    sel_bytes = await selected.read()
    if not idle_bytes or not sel_bytes:
        raise HTTPException(status_code=400, detail="Se requieren ambas imágenes (idle + selected)")
    if len(idle_bytes) > 8 * 1024 * 1024 or len(sel_bytes) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Imagen demasiado grande (máx 8MB por PNG de momento)")
    bid = "border-" + uuid.uuid4().hex[:12]
    now = int(time.time())
    c = _conn()
    c.execute(
        "INSERT INTO card_borders (id, name, idle_blob, idle_mime, selected_blob, selected_mime, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (bid, nm, sqlite3.Binary(idle_bytes), idle.content_type or "image/png",
         sqlite3.Binary(sel_bytes), selected.content_type or "image/png", now, now),
    )
    c.commit()
    c.close()
    return {"ok": True, "id": bid, "name": nm}


@router.put("/api/cardframes/borders/{border_id}")
async def update_border(
    border_id: str, request: Request,
    name: str = Form(""),
    idle: Optional[UploadFile] = File(None),
    selected: Optional[UploadFile] = File(None),
):
    _need_admin(request)
    c = _conn()
    r = c.execute("SELECT id FROM card_borders WHERE id=?", (border_id,)).fetchone()
    if not r:
        c.close()
        raise HTTPException(status_code=404, detail="borde no encontrado")
    now = int(time.time())
    if (name or "").strip():
        c.execute("UPDATE card_borders SET name=?, updated_at=? WHERE id=?", (name.strip(), now, border_id))
    if idle is not None:
        b = await idle.read()
        if b:
            c.execute("UPDATE card_borders SET idle_blob=?, idle_mime=?, updated_at=? WHERE id=?",
                      (sqlite3.Binary(b), idle.content_type or "image/png", now, border_id))
    if selected is not None:
        b = await selected.read()
        if b:
            c.execute("UPDATE card_borders SET selected_blob=?, selected_mime=?, updated_at=? WHERE id=?",
                      (sqlite3.Binary(b), selected.content_type or "image/png", now, border_id))
    c.commit()
    c.close()
    return {"ok": True, "id": border_id}


@router.delete("/api/cardframes/borders/{border_id}")
async def delete_border(border_id: str, request: Request):
    _need_admin(request)
    c = _conn()
    used = c.execute("SELECT COUNT(*) AS n FROM card_sets WHERE border_id=?", (border_id,)).fetchone()["n"]
    if used and int(used) > 0:
        c.close()
        raise HTTPException(status_code=400, detail="El borde está en uso por un set (cambia el set primero)")
    cfg = c.execute("SELECT value FROM card_config WHERE key='default_border_id'").fetchone()
    if cfg and cfg["value"] == border_id:
        c.close()
        raise HTTPException(status_code=400, detail="Es el borde default (cambia el default primero)")
    c.execute("DELETE FROM card_borders WHERE id=?", (border_id,))
    c.commit()
    c.close()
    return {"ok": True}


class SetBody(BaseModel):
    border_id: str = ""
    name: str = ""
    categories: str = ""
    subcategories: str = ""
    position: Optional[int] = 0
    enabled: Optional[int] = 1


@router.post("/api/cardframes/sets")
async def create_set(body: SetBody, request: Request):
    _need_admin(request)
    if not body.border_id:
        raise HTTPException(status_code=400, detail="border_id requerido")
    c = _conn()
    r = c.execute("SELECT id FROM card_borders WHERE id=?", (body.border_id,)).fetchone()
    if not r:
        c.close()
        raise HTTPException(status_code=404, detail="borde no encontrado")
    sid = "set-" + uuid.uuid4().hex[:12]
    now = int(time.time())
    c.execute(
        "INSERT INTO card_sets (id, border_id, name, categories, subcategories, position, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, body.border_id, (body.name or "").strip() or "Set",
         body.categories or "", body.subcategories or "",
         int(body.position or 0), 1 if int(body.enabled or 0) else 0, now, now),
    )
    c.commit()
    c.close()
    return {"ok": True, "id": sid}


@router.put("/api/cardframes/sets/{set_id}")
async def update_set(set_id: str, body: SetBody, request: Request):
    _need_admin(request)
    c = _conn()
    r = c.execute("SELECT id FROM card_sets WHERE id=?", (set_id,)).fetchone()
    if not r:
        c.close()
        raise HTTPException(status_code=404, detail="set no encontrado")
    if body.border_id:
        b = c.execute("SELECT id FROM card_borders WHERE id=?", (body.border_id,)).fetchone()
        if not b:
            c.close()
            raise HTTPException(status_code=404, detail="borde no encontrado")
        c.execute("UPDATE card_sets SET border_id=? WHERE id=?", (body.border_id, set_id))
    now = int(time.time())
    c.execute(
        "UPDATE card_sets SET name=?, categories=?, subcategories=?, position=?, enabled=?, updated_at=? WHERE id=?",
        ((body.name or "").strip() or "Set", body.categories or "", body.subcategories or "",
         int(body.position or 0), 1 if int(body.enabled or 0) else 0, now, set_id),
    )
    c.commit()
    c.close()
    return {"ok": True, "id": set_id}


@router.delete("/api/cardframes/sets/{set_id}")
async def delete_set(set_id: str, request: Request):
    _need_admin(request)
    c = _conn()
    c.execute("DELETE FROM card_sets WHERE id=?", (set_id,))
    c.commit()
    c.close()
    return {"ok": True}


class ReorderBody(BaseModel):
    ids: list = []


@router.post("/api/cardframes/reorder")
async def reorder_sets(body: ReorderBody, request: Request):
    _need_admin(request)
    c = _conn()
    for i, sid in enumerate(body.ids or []):
        c.execute("UPDATE card_sets SET position=? WHERE id=?", (i, sid))
    c.commit()
    c.close()
    return {"ok": True}


class DefaultBody(BaseModel):
    border_id: str = ""


@router.post("/api/cardframes/default")
async def set_default(body: DefaultBody, request: Request):
    _need_admin(request)
    c = _conn()
    r = c.execute("SELECT id FROM card_borders WHERE id=?", (body.border_id,)).fetchone()
    if not r:
        c.close()
        raise HTTPException(status_code=404, detail="borde no encontrado")
    c.execute("INSERT OR REPLACE INTO card_config (key, value) VALUES (?,?)", ("default_border_id", body.border_id))
    # Los sets generales (sin filtros) son el "se ve en todas partes": reorientarlos
    # al nuevo default para que el cambio sea visible de inmediato.
    c.execute("UPDATE card_sets SET border_id=? WHERE TRIM(COALESCE(categories,''))='' AND TRIM(COALESCE(subcategories,''))=''", (body.border_id,))
    c.commit()
    c.close()
    return {"ok": True}
