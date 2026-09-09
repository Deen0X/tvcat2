"""
tvcat_collections — Plugin heropage-action para gestionar colecciones
TVCatCollection: añadir títulos, reordenar y publicar/actualizar en Telegram.

- GET  /api/collections/by-channel?channel_id=  → colecciones de un canal
- GET  /api/collections/detail?item_id=         → colección + entradas + canal
- POST /api/collections/save                   → editar (edit_message) o
  publicar (cover + mensaje) una colección. Requiere sesión; publicar exige admin.
"""
import os
import re
import json
import sqlite3
import base64
import tempfile
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _central_conn():
    import sys as _sys
    _tvcat = os.path.abspath(os.path.join(_PLUGIN_DIR, "..", ".."))
    if _tvcat not in _sys.path:
        _sys.path.insert(0, _tvcat)
    from services.catalog_service import get_conn
    return get_conn()


def _session(request: Request):
    from services.auth_service import get_session
    return get_session(request.cookies.get("tvcat_session", ""))


def _require_user(request: Request, admin: bool = False):
    sess = _session(request)
    if not sess:
        raise HTTPException(401)
    if admin:
        is_admin = (sess.get("role") == "admin" or sess.get("is_admin")
                    or str(sess.get("username", "")).lower() == "admin")
        if not is_admin:
            raise HTTPException(403, "Solo admin puede publicar colecciones")
    return sess


def _bare_channel(channel_id: str) -> str:
    try:
        return str(channel_id).replace("-100", "").lstrip("-")
    except Exception:
        return str(channel_id or "")


def _channel_of_link(link: str) -> str:
    try:
        m = re.search(r"/c/(\d+)/", link or "")
        return m.group(1) if m else ""
    except Exception:
        return ""


def _build_text(entries: List[Dict[str, Any]]) -> str:
    lines = ["TVCatCollection"]
    for e in entries or []:
        t = str((e or {}).get("title", "")).strip()
        if not t:
            continue
        y = str((e or {}).get("year", "") or "").strip()
        bang = "!" if (e or {}).get("literal") else ""
        if y and re.match(r"^\d{4}$", y):
            lines.append(f"{y}; {bang}{t}")
        elif bang:
            lines.append(f"{bang}{t}")
        else:
            lines.append(t)
    return "\n".join(lines)


def _parse_entries(raw: str) -> List[Dict[str, Any]]:
    try:
        import sys as _sys
        _tvcat = os.path.abspath(os.path.join(_PLUGIN_DIR, "..", ".."))
        if _tvcat not in _sys.path:
            _sys.path.insert(0, _tvcat)
        from services.text_norm import parse_collection_entries
        return parse_collection_entries(raw or "")
    except Exception:
        return []


@router.get("/api/collections/by-channel")
async def by_channel(channel_id: str, request: Request):
    _require_user(request)
    bare = _bare_channel(channel_id)
    conn = _central_conn()
    try:
        rows = conn.execute(
            "SELECT item_id, title, telegram_link, collection_raw FROM unified_catalog "
            "WHERE COALESCE(is_collection,0)=1 AND telegram_link LIKE ? ORDER BY title ASC",
            (f"%/c/{bare}/%",)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            out.append({"item_id": d.get("item_id"), "title": d.get("title"),
                        "entries": len(_parse_entries(d.get("collection_raw") or ""))})
        return {"collections": out, "count": len(out)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/api/collections/detail")
async def detail(item_id: str, request: Request):
    _require_user(request)
    conn = _central_conn()
    try:
        row = conn.execute("SELECT * FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        d = dict(row)
        if not int(d.get("is_collection", 0) or 0):
            raise HTTPException(400, "No es una colección")
        return {"item_id": item_id, "title": d.get("title", ""),
                "description": d.get("description", ""),
                "telegram_link": d.get("telegram_link", ""),
                "telegram_msg_id": d.get("telegram_msg_id"),
                "channel_id": _channel_of_link(d.get("telegram_link") or ""),
                "entries": _parse_entries(d.get("collection_raw") or "")}
    finally:
        try:
            conn.close()
        except Exception:
            pass


class _CoverIn(BaseModel):
    kind: str = "keep"  # keep | title | upload
    item_id: str = ""
    b64: str = ""
    mime: str = "image/jpeg"


class _EntryIn(BaseModel):
    title: str = ""
    year: str = ""
    literal: bool = False
    item_id: str = ""


class _SaveIn(BaseModel):
    collection_item_id: str = ""
    name: str = ""
    channel_id: str = ""
    topic_id: Optional[int] = None
    entries: List[_EntryIn] = []
    cover: Optional[_CoverIn] = None


def _active_telethon_bots():
    try:
        import services.userbot_service as ubs
        out = []
        for r in (ubs.list_sessions() or []):
            try:
                if r.get("is_active") == 1 and (r.get("client_type") or "telethon") == "telethon" and r.get("tg_user_id"):
                    out.append(int(r["tg_user_id"]))
            except Exception:
                pass
        return out
    except Exception:
        return []


@router.post("/api/collections/save")
async def save_collection(body: _SaveIn, request: Request):
    """Guarda una colección. Si existe (collection_item_id) → edit_message con el
    primer userbot que tenga autoría. Si es nueva → publicar (admin): cover +
    mensaje en el canal. Valida mismo channel_id en los títulos con item_id."""
    sess = _require_user(request, admin=not bool(body.collection_item_id))
    entries = [{"title": e.title.strip(), "year": (e.year or "").strip(),
                "literal": bool(e.literal), "item_id": (e.item_id or "").strip()}
               for e in (body.entries or []) if e.title and e.title.strip()]
    if not entries:
        raise HTTPException(400, "La colección no tiene títulos")
    channel_id = (body.channel_id or "").strip()
    if not channel_id:
        raise HTTPException(400, "Falta channel_id")
    bare = _bare_channel(channel_id)

    # Validación mismo canal: los títulos con item_id deben vivir en el canal.
    conn = _central_conn()
    try:
        dropped = []
        kept = []
        for e in entries:
            iid = e.get("item_id") or ""
            if not iid:
                kept.append(e)
                continue
            try:
                r = conn.execute("SELECT telegram_link FROM unified_catalog WHERE item_id=?", (iid,)).fetchone()
                ch = _channel_of_link((dict(r).get("telegram_link") or "") if r else "")
                if ch and ch != bare:
                    dropped.append(e.get("title", ""))
                    continue
            except Exception:
                pass
            kept.append(e)
        entries = kept
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not entries:
        raise HTTPException(400, "Ningún título válido para este canal")
    text = _build_text(entries)

    if body.collection_item_id:
        return await _save_edit(body.collection_item_id, text)
    return await _save_publish(sess, body, entries, text, bare, dropped)


async def _save_edit(collection_item_id: str, text: str):
    from services.telegram_service import get_telegram_service
    conn = _central_conn()
    try:
        row = conn.execute("SELECT telegram_msg_id, telegram_link FROM unified_catalog WHERE item_id=?",
                           (collection_item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Colección no encontrada")
        d = dict(row)
        msg_id = int(d.get("telegram_msg_id") or 0)
        link = d.get("telegram_link") or ""
        m = re.search(r"/c/(\d+)/", link)
        if not msg_id or not m:
            raise HTTPException(400, "La colección no tiene mensaje asociado")
        channel_id = "-100" + m.group(1)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    svc = get_telegram_service()
    last_err = "sin userbots telethon activos"
    for tg_uid in _active_telethon_bots():
        try:
            res = await svc.edit_message(channel_id=channel_id, msg_id=msg_id, text=text,
                                         tg_user_id=tg_uid, client_type="telethon")
            if isinstance(res, dict) and res.get("success", True) and not res.get("error"):
                _update_central_raw(collection_item_id, text)
                return {"success": True, "mode": "edit", "tg_user_id": tg_uid}
            last_err = str((res or {}).get("error") or res)
        except Exception as e:
            last_err = str(e)
    raise HTTPException(400, f"No se pudo editar en Telegram (¿autoría?): {last_err}")


def _update_central_raw(item_id: str, text: str):
    try:
        conn = _central_conn()
        conn.execute("UPDATE unified_catalog SET collection_raw=? WHERE item_id=?", (text, item_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


async def _save_publish(sess, body: _SaveIn, entries, text: str, bare: str, dropped):
    import services.userbot_service as ubs
    cover = body.cover or _CoverIn()
    name = (body.name or "").strip() or "Colección"
    # 1. Bytes del cover
    cover_bytes = None
    if cover.kind == "upload" and cover.b64:
        try:
            cover_bytes = base64.b64decode(cover.b64)
        except Exception:
            raise HTTPException(400, "Imagen de portada inválida")
    elif cover.kind == "title" and cover.item_id:
        cover_bytes = await _cover_bytes_of_title(cover.item_id)
        if not cover_bytes:
            raise HTTPException(400, "No se pudo obtener el cover del título")
    # 2. Cliente + entidad
    try:
        ub = await ubs.get_active_client("telethon")
    except Exception as e:
        raise HTTPException(400, f"Sin userbot telethon disponible: {e}")
    client = ub._client
    full_cid = body.channel_id if str(body.channel_id).startswith("-") else "-100" + bare
    try:
        entity = await client.get_entity(int(full_cid))
    except Exception:
        try:
            entity = await client.get_entity(full_cid)
        except Exception as e:
            raise HTTPException(400, f"Canal no accesible: {e}")
    kwargs = {}
    if body.topic_id:
        try:
            kwargs["reply_to"] = int(body.topic_id)
        except Exception:
            pass
    # 3. Cover (foto + caption) y mensaje colección
    try:
        if cover_bytes:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                tf.write(cover_bytes)
                tmp = tf.name
            try:
                sent_cover = await client.send_file(entity, tmp, caption=f"Title: {name}", **kwargs)
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            cover_msg_id = getattr(sent_cover, "id", 0)
        else:
            cover_msg_id = 0
        sent = await client.send_message(entity, text, **kwargs)
        return {"success": True, "mode": "publish",
                "cover_msg_id": cover_msg_id,
                "collection_msg_id": getattr(sent, "id", 0),
                "dropped": dropped or []}
    except Exception as e:
        raise HTTPException(400, f"Error publicando: {e}")


async def _cover_bytes_of_title(item_id: str):
    """Descarga los bytes del cover de un título (mensaje de su telegram_link)."""
    try:
        import services.userbot_service as ubs
        conn = _central_conn()
        try:
            row = conn.execute("SELECT telegram_msg_id, telegram_link FROM unified_catalog WHERE item_id=?",
                               (item_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            msg_id = int(d.get("telegram_msg_id") or 0)
            m = re.search(r"/c/(\d+)/", d.get("telegram_link") or "")
            if not msg_id or not m:
                return None
            cid = "-100" + m.group(1)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        ub = await ubs.get_active_client("telethon")
        client = ub._client
        try:
            entity = await client.get_entity(int(cid))
        except Exception:
            entity = await client.get_entity(cid)
        msgs = await client.get_messages(entity, ids=msg_id)
        msg = msgs[0] if isinstance(msgs, list) else msgs
        if not msg:
            return None
        data = await client.download_media(msg, file=bytes)
        if isinstance(data, bytes) and data:
            return data
        return None
    except Exception:
        return None
