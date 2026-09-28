"""Worker de sonda media por título (plan MediaProbeQueue, F2).

Bucle único en prioridad fondo (BulkGate LOW): saca trabajos de
`media_probe_queue` (MKV primero, hero-boost primero), verifica frescura
por `msg.date`, descarga head (+tail si moov al final) y guarda el ffprobe
en `episode_media`. Sin clientes → espera; sin trabajos → duerme.
"""
import asyncio
import json
import os
import sqlite3
import tempfile
import time
from collections import deque

from services.media_probe_queue import DB_PATH

# Stats de sesión (mismo proceso que el gateway: el endpoint las lee para la
# barra de progreso + refresco en vivo del grid). `recent` retiene las últimas
# sondas con sus flags para parchear tarjetas sin pedir una a una.
_STATS = {"done": 0, "recent": deque(maxlen=50)}

HEAD_BYTES = 1024 * 1024
TAIL_BYTES = 5 * 1024 * 1024
MAX_ATTEMPTS = 3
IDLE_SLEEP = 5
NOCLIENT_SLEEP = 30


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return conn


def _pop():
    """Reclama el siguiente trabajo (o None). Orden: hero-boost primero;
    luego por formato (MKV > MP4-familia > resto: probabilidad de
    multi-audio/subs); luego antigüedad."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT episode_key, item_id, chat_id, msg_id, ext, msg_date, attempts"
            " FROM media_probe_queue WHERE attempts < ?"
            " ORDER BY priority DESC,"
            " CASE WHEN ext='.mkv' THEN 0"
            " WHEN ext IN ('.mp4','.m4v','.mov') THEN 1 ELSE 2 END,"
            " enqueued_at ASC LIMIT 1",
            (MAX_ATTEMPTS,)).fetchone()
        if not row:
            return None
        d = dict(row)
        conn.execute("DELETE FROM media_probe_queue WHERE episode_key=?",
                     (d["episode_key"],))
        conn.commit()
        return d
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _requeue(job, attempts):
    try:
        conn = _conn()
        try:
            conn.execute(
                "UPDATE media_probe_queue SET attempts=? WHERE episode_key=?",
                (attempts, job["episode_key"]))
            # Si ya no está (raro), reinsertar.
            if conn.total_changes == 0:
                conn.execute(
                    "INSERT OR IGNORE INTO media_probe_queue"
                    " (episode_key, item_id, chat_id, msg_id, ext, msg_date, attempts)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (job["episode_key"], job.get("item_id"), job.get("chat_id"),
                     job.get("msg_id"), job.get("ext"), job.get("msg_date"), attempts))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass


def _save(episode_key, media, msg_date):
    try:
        try:
            from services.media_probe_queue import media_flags as _mf
            _fl = _mf(media or {})
        except Exception:
            _fl = {}
        conn = _conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO episode_media"
                " (episode_key, media_json, media_date, probed_at,"
                " has_multi_audio, has_subs)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (episode_key, json.dumps(media or {}, ensure_ascii=False),
                 str(msg_date or ""), int(time.time()),
                 1 if (_fl or {}).get("multi_audio") else 0,
                 1 if (_fl or {}).get("has_subs") else 0))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass


def _mp4_moov_at_start(buf):
    """True = moov al inicio, False = mdat primero (moov al final),
    None = no se pudo determinar."""
    try:
        off, n = 0, len(buf or b"")
        while off + 8 <= n:
            size = int.from_bytes(buf[off:off + 4], "big")
            try:
                typ = buf[off + 4:off + 8].decode("latin1")
            except Exception:
                return None
            if typ == "moov":
                return True
            if typ == "mdat":
                return False
            if size < 8:
                return None
            off += size
            if off > HEAD_BYTES:
                break
        return None
    except Exception:
        return None


async def _fetch_msg(client, ctype, chat_id, msg_id):
    """Mensaje en el tipo del cliente (para fecha y file_size)."""
    try:
        if ctype == "pyrogram":
            m = await client.get_messages(int(chat_id), int(msg_id))
            if isinstance(m, list):
                return m[0] if m else None
            return m
        entity = await client.get_entity(int(chat_id))
        return await client.get_messages(entity, ids=int(msg_id))
    except Exception:
        return None


def _msg_date_str(msg):
    try:
        d = getattr(msg, "date", None)
        return str(d) if d else ""
    except Exception:
        return ""


def _msg_file_size(msg, ctype):
    try:
        if ctype == "pyrogram":
            from services.userbot_service import pyro_media as _pm
            doc = _pm(msg)
            if doc is not None:
                return int(getattr(doc, "file_size", 0) or 0)
            return 0
        media = getattr(msg, "media", None)
        doc = getattr(media, "document", None) if media else None
        if doc is None:
            doc = getattr(msg, "document", None)
        return int(getattr(doc, "size", 0) or 0)
    except Exception:
        return 0


async def _probe_job(job):
    """Procesa un trabajo. Devuelve True si queda resuelto (bien o aparcado)."""
    from services.userbot_service import get_active_client
    from services.file_transfer import download_range
    from services.media_probe import probe_file

    key = job["episode_key"]
    chat_id, msg_id = job["chat_id"], job["msg_id"]
    ext = str(job.get("ext") or "")

    wrapper = await get_active_client()
    if not wrapper:
        return False
    client = getattr(wrapper, "_client", wrapper)
    ctype = getattr(wrapper, "_type", "telethon")
    if ctype not in ("telethon", "pyrogram"):
        ctype = "telethon"

    # Frescura: fecha actual del mensaje.
    msg = await _fetch_msg(client, ctype, chat_id, msg_id)
    if msg is None:
        raise RuntimeError("mensaje no resoluble")
    fresh_date = _msg_date_str(msg)
    if fresh_date and fresh_date == str(job.get("msg_date") or ""):
        pass  # misma versión: sondar igual (barato) o reutilizar si existe
    # Si ya hay sonda vigente de la misma versión, no descargar nada.
    try:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT media_date FROM episode_media WHERE episode_key=?",
                (key,)).fetchone()
            if row and row[0] and row[0] == fresh_date:
                return True
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass

    fsize = _msg_file_size(msg, ctype)
    head = await download_range(client, int(chat_id), int(msg_id), 0,
                                min(HEAD_BYTES, fsize or HEAD_BYTES),
                                client_type=ctype, pre_msg=msg, bulk_priority=2)
    if not head:
        raise RuntimeError("head vacío")
    blob = bytes(head)
    # MP4 con moov al final → añadir tail para que ffprobe lo lea.
    if ext in (".mp4", ".m4v", ".mov") and fsize > HEAD_BYTES:
        if _mp4_moov_at_start(blob) is False:
            # Si empezó reproducción a medias, no seguir pidiendo.
            # Vuelve a la cola sin quemar intento.
            try:
                from services.playback_demand import queue_may_download as _may2
                _may_dl2 = _may2
            except Exception:
                try:
                    from tvcat.services.playback_demand import queue_may_download as _may2b
                    _may_dl2 = _may2b
                except Exception:
                    _may_dl2 = lambda: True
            try:
                _can = _may_dl2()
            except Exception:
                _can = True
            if not _can:
                print(f" [PROBE] {key}: pausa por reproducción (reencola)", flush=True)
                return False
            tail = await download_range(
                client, int(chat_id), int(msg_id),
                max(0, fsize - TAIL_BYTES), min(TAIL_BYTES, fsize),
                client_type=ctype, pre_msg=msg, bulk_priority=2)
            if tail:
                blob = blob + bytes(tail)
    fd, tmp = tempfile.mkstemp(suffix=ext or ".bin")
    try:
        os.write(fd, blob)
    finally:
        try:
            os.close(fd)
        except Exception:
            pass
    try:
        # fsize = tamaño real remoto: el tmp es un fragmento, así que el
        # filesize/bitrate se calculan con él (no con el fragmento).
        media = probe_file(tmp, total_size=int(fsize or 0)) or {}
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    if not media:
        raise RuntimeError("ffprobe sin datos")
    _save(key, media, fresh_date or str(job.get("msg_date") or ""))
    try:
        from services.media_probe_queue import media_flags as _mf
        _fl = _mf(media)
    except Exception:
        _fl = {}
    _STATS["done"] += 1
    try:
        _STATS["recent"].append({
            "seq": _STATS["done"],
            "item_id": job.get("item_id"),
            "ma": 1 if (_fl or {}).get("multi_audio") else 0,
            "subs": 1 if (_fl or {}).get("has_subs") else 0,
        })
    except Exception:
        pass
    print(f" [PROBE] {key} ({ext or '?'}): "
          f"{media.get('resolution') or '?'} "
          f"{media.get('vcodec') or '?'} "
          f"aud=[{media.get('audiotracks') or '-'}]"
          f" sub=[{media.get('subtitles') or '-'}]", flush=True)
    return True


async def run():
    """Bucle del worker. Pensado para `_spawn` (cancelable)."""
    print(" [PROBE] worker de sonda media iniciado (fondo)", flush=True)
    try:
        from services.playback_demand import queue_may_download as _may_dl
    except Exception:
        try:
            from tvcat.services.playback_demand import queue_may_download as _may_dl
        except Exception:
            _may_dl = lambda: True
    try:
        while True:
            try:
                try:
                    _can = _may_dl()
                except Exception:
                    _can = True
                if not _can:
                    # Reproduciendo: ni empezar sondas (la cola espera).
                    await asyncio.sleep(10)
                    continue
                job = await asyncio.to_thread(_pop)
            except Exception:
                job = None
            if not job:
                await asyncio.sleep(IDLE_SLEEP)
                continue
            try:
                ok = await _probe_job(job)
                if not ok:
                    # Sin clientes: devolver a la cola y esperar.
                    _requeue(job, int(job.get("attempts") or 0))
                    await asyncio.sleep(NOCLIENT_SLEEP)
            except asyncio.CancelledError:
                _requeue(job, int(job.get("attempts") or 0))
                raise
            except Exception as e:
                n = int(job.get("attempts") or 0) + 1
                print(f" [PROBE] {job.get('episode_key')}: {e}"
                      f" (intento {n}/{MAX_ATTEMPTS})", flush=True)
                if n < MAX_ATTEMPTS:
                    _requeue(job, n)
                    await asyncio.sleep(2)
                else:
                    print(f" [PROBE] {job.get('episode_key')}: aparcado",
                          flush=True)
    except asyncio.CancelledError:
        print(" [PROBE] worker detenido", flush=True)
        raise
