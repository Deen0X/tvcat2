"""
tvcat_collections — Plugin heropage-action para gestionar colecciones
TVCatCollection: añadir títulos, reordenar y guardar.

Modelo 2026-09-09 (colección virtual):
- Crear = SIEMPRE local (tabla CORE collections_local, cualquier usuario).
  No existe en ningún canal hasta que se sube por TGHirayi.
- Editar escaneada propia (autoría) = edit_message del original.
- Editar escaneada ajena = copia local (el local prevalece por ser más nuevo).
- Editar local = actualiza la fila local.
- Publicar a un canal = vía TGHirayi (rama collection), nunca directo.

- GET  /api/collections/by-channel?channel_id=  → colecciones escaneadas de un canal
- GET  /api/collections/local/list              → colecciones locales (sin canal)
- GET  /api/collections/detail?item_id=         → colección + entradas (+ local)
- POST /api/collections/local/save              → crear/actualizar local (cualquier usuario)
- POST /api/collections/save                    → editar escaneada (autoría) o fallback local
"""
import os
import re
import json
import sqlite3
import base64
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


@router.get("/api/collections/local/list")
async def local_list(request: Request):
    """Colecciones locales (sintéticas CORE, sin canal). Visibilidad global."""
    _require_user(request)
    try:
        from services.catalog_service import list_local_collections
        out = []
        for loc in list_local_collections():
            try:
                n = len(json.loads(loc.get("entries_json") or "[]") or [])
            except Exception:
                n = 0
            out.append({"item_id": loc.get("item_id"), "title": loc.get("name") or "Colección",
                        "serial": loc.get("serial") or "", "entries": n, "local": 1})
        return {"collections": out, "count": len(out)}
    except Exception as e:
        raise HTTPException(500, str(e))


def _cover_body(caption):
    """Cuerpo del caption del cover sin la primera línea `Title:` (para el
    textarea de descripción). Si no hay línea Title, devuelve el texto íntegro."""
    try:
        lines = (caption or "").split("\n")
        if lines and re.match(r"(?i)^\s*(t[ií]tulo|titulo|title|nombre)\s*[:=\-]?", lines[0].strip()):
            return "\n".join(lines[1:]).strip()
        return (caption or "").strip()
    except Exception:
        return (caption or "").strip()


def _cover_caption(name, description):
    """Caption canónico del mensaje de cover (lo prepara el editor).
    Ver services.text_norm.build_collection_cover_text."""
    try:
        from services.text_norm import build_collection_cover_text
        return build_collection_cover_text(name, description)
    except Exception:
        cap = "TVCat Collection\nTitle: %s" % ((name or "").strip() or "Colección")
        if (description or "").strip():
            cap += "\n\nOverview:\n" + (description or "").strip()
        return cap


@router.get("/api/collections/detail")
async def detail(item_id: str, request: Request):
    _require_user(request)
    # Local/virtual: detalle sintético desde la tabla CORE.
    if (item_id or "").startswith("COL-"):
        try:
            from services.catalog_service import get_local_collection
            from services.text_norm import build_collection_text
            loc = get_local_collection(item_id)
            if not loc:
                raise HTTPException(404)
            try:
                entries = json.loads(loc.get("entries_json") or "[]") or []
            except Exception:
                entries = []
            try:
                text = build_collection_text(loc.get("name") or "", loc.get("serial") or "", entries)
            except Exception:
                text = ""
            return {"item_id": item_id, "title": loc.get("name") or "Colección",
                    "description": loc.get("description") or "",
                    "collection_text": text,
                    "telegram_link": "", "telegram_msg_id": 0,
                    "channel_id": "", "serial": loc.get("serial") or "",
                    "entries": entries, "local": 1}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))
    conn = _central_conn()
    try:
        row = conn.execute("SELECT * FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        d = dict(row)
        if not int(d.get("is_collection", 0) or 0):
            raise HTTPException(400, "No es una colección")
        return {"item_id": item_id, "title": d.get("title", ""),
                "description": _cover_body(d.get("description", "")),
                "telegram_link": d.get("telegram_link", ""),
                "telegram_msg_id": d.get("telegram_msg_id"),
                "channel_id": _channel_of_link(d.get("telegram_link") or ""),
                "serial": d.get("collection_serial") or "",
                "entries": _parse_entries(d.get("collection_raw") or ""), "local": 0}
    finally:
        try:
            conn.close()
        except Exception:
            pass


class _CoverIn(BaseModel):
    kind: str = "keep"  # keep | title | upload | url
    item_id: str = ""
    b64: str = ""
    url: str = ""
    mime: str = "image/jpeg"


class _EntryIn(BaseModel):
    title: str = ""
    year: str = ""
    literal: bool = False
    item_id: str = ""


class _SaveIn(BaseModel):
    collection_item_id: str = ""
    name: str = ""
    serial: str = ""
    description: str = ""
    channel_id: str = ""
    topic_id: Optional[int] = None
    entries: List[_EntryIn] = []
    cover: Optional[_CoverIn] = None


def _download_image_url(url: str):
    """Descarga una imagen por URL (tope 10MB, 15s). Devuelve (bytes, mime)."""
    import urllib.request as _url
    u = (url or "").strip()
    if not u or not re.match(r"^https?://", u, re.IGNORECASE):
        raise HTTPException(400, "URL no válida")
    try:
        req = _url.Request(u, headers={"User-Agent": "TVCat/2"})
        with _url.urlopen(req, timeout=15) as r:
            mime = (r.headers.get_content_type() or "image/jpeg").lower()
            if not mime.startswith("image/"):
                raise HTTPException(400, "La URL no es una imagen (%s)" % mime)
            data = r.read(10 * 1024 * 1024 + 1)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, "No se pudo descargar la imagen: %s" % e)
    if not data:
        raise HTTPException(400, "Imagen vacía")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "Imagen mayor de 10MB")
    return data, mime


def _clean_entries(body_entries):
    out = []
    for e in (body_entries or []):
        try:
            t = (e.title or "").strip()
        except Exception:
            continue
        if not t:
            continue
        out.append({"title": t, "year": ((e.year or "").strip()),
                    "literal": bool(e.literal), "item_id": ((e.item_id or "").strip())})
    # Refresco contra el catálogo actual: cada entrada CON item_id adopta el
    # título/año efectivos de HOY (incluye ediciones del enriquecedor
    # posteriores a haberla añadido; el year de unified_catalog casi nunca
    # está relleno, así que se completa desde el enriquecido).
    try:
        from services.catalog_service import refresh_collection_entries
        out = refresh_collection_entries(out)
    except Exception:
        pass
    return out


async def _cover_bytes_for_local(cover, collection_item_id=None):
    """Resuelve (bytes, mime) del cover para guardar en local.
    keep + escaneada => snapshot del cover actual; keep + local => None (conservar)."""
    kind = "keep"
    try:
        kind = (cover.kind if cover else "keep") or "keep"
    except Exception:
        kind = "keep"
    if kind == "upload":
        try:
            b64 = (cover.b64 or "") if cover else ""
            mime = (cover.mime or "image/jpeg") if cover else "image/jpeg"
            # FileReader/clipboard mandan dataURL: pelar el prefijo.
            m = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", b64 or "", re.DOTALL)
            if m:
                if m.group(1):
                    mime = m.group(1).lower()
                b64 = m.group(3) or ""
            if not b64.strip():
                return None, None
            return base64.b64decode(b64), mime
        except Exception:
            raise HTTPException(400, "Imagen de portada inválida")
        return None, None
    if kind == "title":
        iid = ((cover.item_id or "") if cover else "").strip()
        if not iid:
            raise HTTPException(400, "Falta el título de portada")
        data = await _cover_bytes_of_title(iid)
        if not data:
            raise HTTPException(400, "No se pudo obtener el cover del título")
        return data, "image/jpeg"
    if kind == "url":
        u = ((cover.url or "") if cover else "").strip()
        if not u:
            raise HTTPException(400, "Falta la URL de portada")
        return _download_image_url(u)
    # keep
    if collection_item_id and not str(collection_item_id).startswith("COL-"):
        data = await _cover_bytes_of_title(collection_item_id)
        if data:
            return data, "image/jpeg"
    return None, None


def _store_local_cover(item_id, img_bytes, mime):
    try:
        lid = int(str(item_id).split("-")[-1] or 0)
    except Exception:
        return
    if lid and img_bytes:
        try:
            from services.catalog_service import save_local_cover
            save_local_cover(lid, img_bytes, mime)
        except Exception:
            pass


@router.post("/api/collections/local/save")
async def save_local(body: _SaveIn, request: Request):
    """Crea/actualiza una colección LOCAL (virtual CORE). Cualquier usuario
    autenticado. Crear = siempre local; publicar a un canal = vía TGHirayi."""
    sess = _require_user(request)
    entries = _clean_entries(body.entries)
    if not entries:
        raise HTTPException(400, "La colección no tiene títulos")
    name = (body.name or "").strip() or "Colección"
    try:
        from services.catalog_service import (
            create_local_collection, update_local_collection,
            get_local_collection, next_collection_serial)
    except Exception as e:
        raise HTTPException(500, "Núcleo sin soporte local: %s" % e)
    uid = None
    try:
        uid = sess.get("user_id")
    except Exception:
        pass
    desc = (body.description or "").strip()
    cover_text = _cover_caption(name, desc)
    cid = (body.collection_item_id or "").strip()
    if cid.startswith("COL-"):
        loc = get_local_collection(cid)
        if not loc:
            raise HTTPException(404, "Colección local no encontrada")
        img, mime = await _cover_bytes_for_local(body.cover, None)
        update_local_collection(cid, name=name, entries=entries, user_id=uid, description=desc, cover_text=cover_text)
        if img:
            _store_local_cover(cid, img, mime)
        return {"success": True, "mode": "local-updated", "item_id": cid}
    serial = (body.serial or "").strip() or next_collection_serial()
    img, mime = await _cover_bytes_for_local(body.cover, None)
    loc = create_local_collection(name, serial, entries, uid, desc, cover_text)
    if not loc:
        raise HTTPException(500, "No se pudo crear la colección local")
    if img:
        _store_local_cover(loc.get("item_id"), img, mime)
    return {"success": True, "mode": "local-created", "item_id": loc.get("item_id"),
            "serial": serial}


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
    """Guarda una colección escaneada.
    - COL- => delega a local (actualiza la fila).
    - Sin collection_item_id => NUEVA: siempre local (cualquier usuario).
      Publicar a un canal se hace vía TGHirayi, nunca directo.
    - Con collection_item_id escaneado => intenta edit_message (autoría,
      mismo mecanismo actual: primer userbot con éxito); si falla (canal
      ajeno/sin permiso) => copia LOCAL con mismo nombre+serial (el local
      prevalece por ser más nuevo)."""
    sess = _require_user(request)
    entries = _clean_entries(body.entries)
    if not entries:
        raise HTTPException(400, "La colección no tiene títulos")
    cid = (body.collection_item_id or "").strip()
    if cid.startswith("COL-"):
        return await save_local(body, request)
    if not cid:
        # Nueva => local (sin validación de canal: las entradas son portables).
        return await save_local(body, request)

    # Editar escaneada: mismo canal obligatorio (el mensaje vive allí).
    channel_id = ""
    scanned_serial = ""
    conn = _central_conn()
    try:
        row = conn.execute("SELECT telegram_link, collection_serial FROM unified_catalog WHERE item_id=?",
                           (cid,)).fetchone()
        if row:
            d = dict(row)
            m = re.search(r"/c/(\d+)/", d.get("telegram_link") or "")
            channel_id = m.group(1) if m else ""
            scanned_serial = (d.get("collection_serial") or "").strip()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    bare = _bare_channel(channel_id) if channel_id else ""
    if bare:
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
    from services.text_norm import build_collection_text
    name = (body.name or "").strip() or "Colección"
    serial = (body.serial or "").strip() or scanned_serial
    desc = (body.description or "").strip()
    text = build_collection_text(name, serial, entries)

    # 1. Intentar edición del original (autoría): lista + cover si cambió.
    try:
        res = await _save_edit(cid, text)
        try:
            kind = ((body.cover.kind if body.cover else "keep") or "keep")
            if kind != "keep":
                img2, _m2 = await _cover_bytes_for_local(body.cover, None)
                ok, detail = await _save_cover_edit(cid, _cover_caption(name, desc), img2)
                if ok:
                    res["cover"] = "updated"
                else:
                    res["cover"] = "error"
                    res["cover_detail"] = detail
        except Exception:
            pass
        return res
    except HTTPException as he:
        # 2. Fallback local: copia con misma identidad (prevalece por fecha).
        if he.status_code in (400, 403, 404):
            try:
                from services.catalog_service import create_local_collection, next_collection_serial
                uid = None
                try:
                    uid = sess.get("user_id")
                except Exception:
                    pass
                if not serial:
                    serial = next_collection_serial()
                img, mime = await _cover_bytes_for_local(body.cover, cid)
                loc = create_local_collection(name, serial, entries, uid, desc, _cover_caption(name, desc))
                if loc:
                    if img:
                        _store_local_cover(loc.get("item_id"), img, mime)
                    return {"success": True, "mode": "local-fallback",
                            "item_id": loc.get("item_id"), "serial": serial,
                            "detail": "Sin permiso en el canal: guardada en local"}
            except HTTPException:
                raise
            except Exception:
                pass
        raise


async def _save_edit(collection_item_id: str, text: str):
    """Edita el mensaje de LISTA de la colección (el que lleva el tag), no el
    cover: telegram_msg_id guarda el cover. Localiza el mensaje de texto por
    identidad (nombre+serial) en el caché central; si el propio telegram_msg_id
    ya contiene el tag (colección autocontenida), se edita ese."""
    from services.telegram_service import get_telegram_service
    conn = _central_conn()
    try:
        row = conn.execute("SELECT telegram_msg_id, telegram_link, collection_name, collection_serial, title FROM unified_catalog WHERE item_id=?",
                           (collection_item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Colección no encontrada")
        d = dict(row)
        cover_id = int(d.get("telegram_msg_id") or 0)
        link = d.get("telegram_link") or ""
        m = re.search(r"/c/(\d+)/", link)
        if not cover_id or not m:
            raise HTTPException(400, "La colección no tiene mensaje asociado")
        bare = m.group(1)
        channel_id = "-100" + bare
        name = (d.get("collection_name") or "").strip() or (d.get("title") or "")
        serial = (d.get("collection_serial") or "").strip()
        target = _cached_text_msg_id(conn, bare, cover_id, name, serial)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    svc = get_telegram_service()
    last_err = "sin userbots telethon activos"
    for tg_uid in _active_telethon_bots():
        try:
            res = await svc.edit_message(channel_id=channel_id, msg_id=target, text=text,
                                         tg_user_id=tg_uid, client_type="telethon")
            if isinstance(res, dict) and res.get("success", True) and not res.get("error"):
                _update_central_raw(collection_item_id, text)
                return {"success": True, "mode": "edit", "tg_user_id": tg_uid, "item_id": collection_item_id}
            last_err = str((res or {}).get("error") or res)
        except Exception as e:
            last_err = str(e)
    raise HTTPException(400, f"No se pudo editar en Telegram (¿autoría?): {last_err}")


def _cached_text_msg_id(conn, bare, cover_id, name, serial):
    """Msg_id del mensaje de LISTA: el propio cover si contiene el tag,
    si no el más nuevo del canal con la misma identidad. 0 si no hay."""
    import json as _js
    try:
        from services.text_norm import is_collection_text, parse_collection_header, normalize_title
    except Exception:
        return cover_id
    variants = {bare, "-100" + bare}
    try:
        from services.cache_keys import canon_channel
        variants.add(canon_channel(bare))
    except Exception:
        pass
    try:
        rows = conn.execute(
            "SELECT msg_id, message FROM telegram_message_cache WHERE channel_id IN (%s)" % ",".join("?" * len(variants)),
            list(variants)).fetchall()
    except Exception:
        return cover_id
    key_name = normalize_title(name or "")
    best = 0
    for r in rows:
        try:
            rd = dict(r)
            mid = int(rd.get("msg_id") or 0)
            pay = _js.loads(rd.get("message") or "{}")
            txt = pay.get("message") or ""
        except Exception:
            continue
        if not txt or not is_collection_text(txt):
            continue
        try:
            hn, hs = parse_collection_header(txt)
        except Exception:
            hn, hs = "", ""
        if (hs or "").strip() != (serial or "").strip():
            continue
        if (hn or "").strip() and normalize_title(hn) != key_name:
            continue
        if mid == cover_id:
            return mid
        if mid > best:
            best = mid
    return best or cover_id


async def _save_cover_edit(collection_item_id: str, caption: str, img_bytes=None):
    """Edita el mensaje de COVER (telegram_msg_id) con caption e imagen.
    Devuelve (ok, detail)."""
    from services.telegram_service import get_telegram_service
    conn = _central_conn()
    try:
        row = conn.execute("SELECT telegram_msg_id, telegram_link FROM unified_catalog WHERE item_id=?",
                           (collection_item_id,)).fetchone()
        if not row:
            return False, "colección no encontrada"
        d = dict(row)
        msg_id = int(d.get("telegram_msg_id") or 0)
        m = re.search(r"/c/(\d+)/", d.get("telegram_link") or "")
        if not msg_id or not m:
            return False, "sin mensaje de cover"
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
            res = await svc.edit_message(channel_id=channel_id, msg_id=msg_id, text=caption or "",
                                         file_bytes=img_bytes, file_name="cover.jpg",
                                         tg_user_id=tg_uid, client_type="telethon")
            if isinstance(res, dict) and res.get("success", True) and not res.get("error"):
                return True, ""
            last_err = str((res or {}).get("error") or res)
        except Exception as e:
            last_err = str(e)
    return False, last_err


def _update_central_raw(item_id: str, text: str):
    try:
        conn = _central_conn()
        conn.execute("UPDATE unified_catalog SET collection_raw=? WHERE item_id=?", (text, item_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


@router.delete("/api/collections/delete")
async def delete_collection(item_id: str, request: Request):
    """Elimina una colección.
    - Local (COL-): borra la fila + su cover (cualquier usuario).
    - Escaneada: borra los mensajes en Telegram (cover + lista, requiere
      autoría) y limpia caché central + catálogos (central y plugin) para que
      el siguiente escaneo no la resucite."""
    _require_user(request)
    cid = (item_id or "").strip()
    if not cid:
        raise HTTPException(400, "Falta item_id")
    if cid.startswith("COL-"):
        try:
            from services.catalog_service import delete_local_collection
            if delete_local_collection(cid):
                return {"success": True, "mode": "local-deleted", "item_id": cid}
        except Exception as e:
            raise HTTPException(500, str(e))
        raise HTTPException(404, "Colección local no encontrada")
    # Escaneada: resolver cover + texto.
    conn = _central_conn()
    try:
        row = conn.execute("SELECT telegram_msg_id, telegram_link, collection_name, collection_serial, title FROM unified_catalog WHERE item_id=?",
                           (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "Colección no encontrada")
        d = dict(row)
        cover_id = int(d.get("telegram_msg_id") or 0)
        m = re.search(r"/c/(\d+)/", d.get("telegram_link") or "")
        if not cover_id or not m:
            raise HTTPException(400, "La colección no tiene mensaje asociado")
        bare = m.group(1)
        name = (d.get("collection_name") or "").strip() or (d.get("title") or "")
        serial = (d.get("collection_serial") or "").strip()
        text_id = _cached_text_msg_id(conn, bare, cover_id, name, serial)
        targets = sorted({i for i in (cover_id, text_id) if i})
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # Borrado en Telegram (todos los mensajes o nada).
    import services.userbot_service as ubs
    last_err = "sin userbots telethon activos"
    deleted = False
    for _uid in _active_telethon_bots():
        try:
            ub = await ubs.get_active_client("telethon")
            client = ub._client
            try:
                entity = await client.get_entity(int("-100" + bare))
            except Exception:
                entity = await client.get_entity("-100" + bare)
            await client.delete_messages(entity, targets)
            deleted = True
            break
        except Exception as e:
            last_err = str(e)
    if not deleted:
        raise HTTPException(400, f"No se pudo borrar en Telegram (¿autoría?): {last_err}")
    # Limpieza para que no resucite: caché central + central + plugin.
    try:
        conn = _central_conn()
        variants = {bare, "-100" + bare}
        try:
            from services.cache_keys import canon_channel
            variants.add(canon_channel(bare))
        except Exception:
            pass
        ph = ",".join("?" * len(targets))
        phv = ",".join("?" * len(variants))
        conn.execute("DELETE FROM telegram_message_cache WHERE channel_id IN (%s) AND msg_id IN (%s)" % (phv, ph),
                     list(variants) + targets)
        conn.execute("DELETE FROM unified_catalog WHERE item_id=?", (cid,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    try:
        import sqlite3 as _sq
        from services.catalog_service import BASE_DIR as _bd
        _pdb = os.path.join(_bd, "plugins", "tvcat_tgindex", "data", "tvcat.db")
        if os.path.isfile(_pdb):
            _pc = _sq.connect(_pdb, timeout=30)
            _pc.execute("DELETE FROM unified_catalog WHERE item_id=?", (cid,))
            try:
                _pc.execute("DELETE FROM plugin_catalog_export WHERE item_id=?", (cid,))
            except Exception:
                pass
            _pc.commit()
            _pc.close()
    except Exception:
        pass
    return {"success": True, "mode": "remote-deleted", "item_id": cid, "messages": targets}


async def _cover_bytes_of_title(item_id: str):
    """Bytes del cover de un título respetando ediciones (mismo orden que
    GET /api/cover): 1) override enriquecido (local o Telegram),
    2) caché central catalog_assets, 3) descarga del mensaje original."""
    try:
        # 1. Enriquecido (edición local o en Telegram del propio autor).
        try:
            from services.cover_override_registry import get_enriched_by_item_id
            enriched = get_enriched_by_item_id(item_id)
            if enriched and enriched.get("poster_blob"):
                return bytes(enriched["poster_blob"])
        except Exception:
            pass
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
            bare = m.group(1)
            # 2. Caché central (puede contener el cover editado/JIT).
            try:
                from services.cache_keys import canon_channel
                asset_ch = canon_channel(bare)
            except Exception:
                asset_ch = bare
            try:
                arow = conn.execute(
                    "SELECT image_blob FROM catalog_assets"
                    " WHERE channel_id=? AND telegram_msg_id=? AND asset_type='cover' LIMIT 1",
                    (asset_ch, msg_id)).fetchone()
                if arow and arow["image_blob"]:
                    return bytes(arow["image_blob"])
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        # 3. Mensaje original en Telegram.
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
