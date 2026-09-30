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

# Claves en sondaje activo (reclamadas al pop, liberadas al terminar).
# Evita que la hero re-encole lo que ya se está procesando (reset de intentos).
_CLAIMED = set()


def is_claimed(episode_key: str) -> bool:
    try:
        return str(episode_key or "") in _CLAIMED
    except Exception:
        return False


async def _yield_to_bulk() -> bool:
    """True si la sonda debe ceder el paso: jobs del TransferService en
    curso, tráfico bulk reciente (descargas/subidas directas de plugins,
    que no pasan por TransferService) o carril bulk saturado. La
    reproducción ya la cubre playback_demand; aquí se protege la cola de
    episodios del tráfico de fondo de la sonda."""
    try:
        from services.file_transfer import bulk_active_recent as _bar
    except Exception:
        try:
            from tvcat.services.file_transfer import bulk_active_recent as _bar2
            _bar = _bar2
        except Exception:
            _bar = None
    if _bar is not None:
        try:
            if bool(_bar(30.0)):
                return True
        except Exception:
            pass
    try:
        from services.transfer_service import list_jobs as _ls
    except Exception:
        try:
            from tvcat.services.transfer_service import list_jobs as _ls2
            _ls = _ls2
        except Exception:
            _ls = None
    if _ls is not None:
        try:
            for j in (_ls() or []):
                if str((j or {}).get("state") or "") in ("queued", "running"):
                    return True
        except Exception:
            pass
    try:
        from services.telegram_service import get_telegram_service as _gts
    except Exception:
        try:
            from tvcat.services.telegram_service import get_telegram_service as _gts2
            _gts = _gts2
        except Exception:
            return False
    try:
        snap = (_gts().bulk_snapshot() or {})
        budget = int(snap.get("budget") or 0)
        if budget:
            if int(snap.get("waiters") or 0) > 0:
                return True
            if int(snap.get("inflight") or 0) >= max(1, budget - 2):
                return True
    except Exception:
        pass
    return False

HEAD_BYTES = 1024 * 1024
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
    multi-audio/subs); luego antigüedad. Salta aparcados vigentes."""
    try:
        from services.media_probe_queue import is_freshly_parked as _parked
    except Exception:
        try:
            from tvcat.services.media_probe_queue import is_freshly_parked as _parked
        except Exception:
            _parked = lambda k: False
    conn = _conn()
    try:
        for _try in range(6):
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
            try:
                _is_parked = _parked(d.get("episode_key"))
            except Exception:
                _is_parked = False
            conn.execute("DELETE FROM media_probe_queue WHERE episode_key=?",
                         (d["episode_key"],))
            conn.commit()
            if _is_parked:
                continue
            try:
                _CLAIMED.add(str(d["episode_key"]))
            except Exception:
                pass
            return d
        return None
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


def _purge_useless() -> int:
    """Borra filas sin resolución ni audios (no sirven para nada). Devuelve
    cuántas. Las re-sondan el worker/feeder/scan solas."""
    try:
        conn = _conn()
        try:
            cur = conn.execute(
                "DELETE FROM episode_media"
                " WHERE COALESCE(json_extract(media_json, '$.resolution'), '') = ''"
                " AND COALESCE(json_extract(media_json, '$.audiotracks'), '') = ''")
            conn.commit()
            n = cur.rowcount or 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if n:
            print(f" [PROBE] purga de sondas inútiles: {n}", flush=True)
        return n
    except Exception:
        return 0


def _save(episode_key, media, msg_date):
    try:
        try:
            from services.media_probe_queue import media_flags as _mf
            _fl = _mf(media or {})
        except Exception:
            _fl = {}
        try:
            from services.media_probe_queue import PROBE_CODE as _pcode
        except Exception:
            try:
                from tvcat.services.media_probe_queue import PROBE_CODE as _pcode
            except Exception:
                _pcode = 2
        conn = _conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO episode_media"
                " (episode_key, media_json, media_date, probed_at,"
                " has_multi_audio, has_subs, src)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (episode_key, json.dumps(media or {}, ensure_ascii=False),
                 str(msg_date or ""), int(time.time()),
                 1 if (_fl or {}).get("multi_audio") else 0,
                 1 if (_fl or {}).get("has_subs") else 0,
                 "worker%d" % int(_pcode)))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass


def _blob_diag(blob, ext) -> str:
    try:
        b = bytes(blob or b"")
        if (ext or "") in (".mp4", ".m4v", ".mov"):
            boxes = []
            off, n = 0, len(b)
            while off + 8 <= n and len(boxes) < 6:
                try:
                    typ = b[off + 4:off + 8].decode("latin1")
                except Exception:
                    break
                boxes.append("".join(c if 32 <= ord(c) < 127 else "?" for c in typ))
                try:
                    size = int.from_bytes(b[off:off + 4], "big")
                except Exception:
                    break
                if size == 1:
                    if off + 16 > n:
                        break
                    size = int.from_bytes(b[off + 8:off + 16], "big")
                if size < 8:
                    break
                off += size
            return "mp4 boxes=%s len=%d" % ("+".join(boxes) if boxes else "?", len(b))
        return "magia=%s len=%d" % (b[:4].hex() if len(b) >= 4 else "?", len(b))
    except Exception:
        return "?"


async def _probe_job(job):
    """Procesa un trabajo. Devuelve True si queda resuelto (bien o aparcado).
    Todo Telegram va por el servicio central (fetch_message_info +
    download_range en cola LOW); aquí solo queda DB + ffprobe local."""
    from services.media_probe import probe_file

    try:
        from services.telegram_service import get_telegram_service
        svc = get_telegram_service()
    except Exception:
        return False

    key = job["episode_key"]
    chat_id, msg_id = job["chat_id"], job["msg_id"]
    ext = str(job.get("ext") or "")

    # Frescura: fecha/tamaño actuales del mensaje (una sola llamada exacta).
    try:
        info = await asyncio.wait_for(
            svc.fetch_message_info(chat_id, msg_id), timeout=120)
    except Exception:
        info = None
    if not info:
        raise RuntimeError("mensaje no resoluble")
    fresh_date = str(info.get("date") or "")
    fsize = int(info.get("file_size") or 0)
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

    print(f" [PROBE] {key} ({ext or '?'}): size={fsize or 0}", flush=True)
    try:
        head = await asyncio.wait_for(
            svc.download_range(chat_id, msg_id, 0,
                               min(HEAD_BYTES, fsize or HEAD_BYTES)),
            timeout=180)
    except Exception:
        head = b""
    if not head:
        raise RuntimeError("head vacío")
    try:
        print(f" [PROBE] {key}: dl chat={chat_id} msg={msg_id} head={len(bytes(head or b''))} magic={bytes(head[:16]).hex()}", flush=True)
    except Exception:
        pass
    def _probe_blob_sync(b, _ext):
        import tempfile as _tf
        import os as _os
        from services.media_probe import probe_file as _pf
        _fd, _tmp = _tf.mkstemp(suffix=_ext or ".bin")
        try:
            _os.write(_fd, b)
        finally:
            try:
                _os.close(_fd)
            except Exception:
                pass
        try:
            return _pf(_tmp, total_size=int(fsize or 0)) or {}
        finally:
            try:
                _os.remove(_tmp)
            except Exception:
                pass

    async def _probe_blob(b):
        try:
            return await asyncio.to_thread(_probe_blob_sync, bytes(b or b""), ext)
        except Exception:
            return {}

    def _useful(m):
        try:
            return bool((m or {}).get("resolution") or (m or {}).get("audiotracks"))
        except Exception:
            return False

    async def _paused_for_playback():
        """True si hay reproducción activa (la cola de sonda se detiene)."""
        try:
            from services.playback_demand import queue_may_download as _may
            _fn = _may
        except Exception:
            try:
                from tvcat.services.playback_demand import queue_may_download as _mayb
                _fn = _mayb
            except Exception:
                return False
        try:
            return not bool(_fn())
        except Exception:
            return False

    async def _dl_range(offset, length):
        try:
            data = await asyncio.wait_for(
                svc.download_range(chat_id, msg_id, max(0, offset),
                                   max(0, length)),
                timeout=180)
        except Exception:
            data = b""
        return bytes(data or b"")

    def _looks_like_mp4(b):
        try:
            return len(b or b"") >= 8 and bytes(b[4:8]) == b"ftyp"
        except Exception:
            return False

    def _is_ebml(b):
        try:
            return bytes((b or b"")[:4]) == bytes.fromhex("1a45dfa3")
        except Exception:
            return False

    blob = bytes(head)
    # Sniff de contenido: un ".mkv" puede ser MP4 (magia=00000020+ftyp).
    is_mp4 = ext in (".mp4", ".m4v", ".mov") or _looks_like_mp4(blob)
    tail_eligible = bool(is_mp4) and (fsize or 0) > HEAD_BYTES
    moov_pos, moov_size = 0, 0
    if tail_eligible:
        try:
            from services.media_probe_queue import get_title_media as _gtm0
        except Exception:
            try:
                from tvcat.services.media_probe_queue import get_title_media as _gtm0
            except Exception:
                _gtm0 = lambda iid: {}
        try:
            _old = _gtm0(str(job.get("item_id") or "")) or {}
            moov_pos = int(_old.get("moovpos") or 0)
            moov_size = int(_old.get("moovsize") or 0)
        except Exception:
            moov_pos, moov_size = 0, 0

    async def _fetch_head_big():
        """Segunda oportunidad MKV (tracks más allá de 1MB por adjuntos):
        head de 8MB. None si pausa por reproducción."""
        if await _paused_for_playback():
            print(f" [PROBE] {key}: pausa por reproducción (reencola)", flush=True)
            return None
        return await _dl_range(0, 8 * 1048576)

    # MP4: si el head no basta, ensamblar init-segment ftyp+moov.
    # (Pegados con mdat en medio ffprobe NO los parsea: verificado.)
    # Moov conocido de sonda anterior: ir directo.
    media = await _probe_blob(blob)
    if not _useful(media) and tail_eligible:
        _mb = b""
        if not (moov_pos > 0 and moov_size > 0):
            try:
                from services.mp4_util import (
                    fetch_moov as _fetch_moov, extract_ftyp as _extract_ftyp)
            except Exception:
                try:
                    from tvcat.services.mp4_util import (
                        fetch_moov as _fetch_moov, extract_ftyp as _extract_ftyp)
                except Exception:
                    _fetch_moov, _extract_ftyp = None, lambda b: b""
            if _fetch_moov is not None:
                if await _paused_for_playback():
                    print(f" [PROBE] {key}: pausa por reproduccion (reencola)", flush=True)
                    return False
                async def _fetch_fn(_off, _ln):
                    return await _dl_range(_off, _ln)
                def _mlog(_m):
                    try:
                        print(f" [PROBE] {key}: {_m}", flush=True)
                    except Exception:
                        pass
                try:
                    _mb, moov_pos, moov_size = await _fetch_moov(
                        _fetch_fn, fsize, blob, _mlog)
                except Exception:
                    _mb, moov_pos, moov_size = b"", 0, 0
        else:
            print(f" [PROBE] {key}: moov conocido en {moov_pos} ({moov_size // 1024}KB)",
                  flush=True)
            if await _paused_for_playback():
                print(f" [PROBE] {key}: pausa por reproduccion (reencola)", flush=True)
                return False
            _mb = await _dl_range(moov_pos, min(moov_size, (fsize or 0) - moov_pos))
        try:
            _moov_ok = bool(_mb) and len(bytes(_mb)) >= 8 and bytes(_mb[4:8]) == b"moov"
        except Exception:
            _moov_ok = False
        if _moov_ok:
            try:
                _ft = _extract_ftyp(blob)
            except Exception:
                _ft = b""
            print(f" [PROBE] {key}: ensamblando ftyp+moov ({len(bytes(_mb)) // 1024}KB)",
                  flush=True)
            media = await _probe_blob(bytes(_ft or b"") + bytes(_mb))
    # MKV con EBML válido pero sin tracks en 1MB (adjuntos primero):
    # un intento con head de 8MB.
    if not _useful(media) and _is_ebml(blob) and (fsize or 0) > 8 * 1048576:
        _big = await _fetch_head_big()
        if _big is None:
            return False
        if _big and len(_big) > len(blob):
            print(f" [PROBE] {key}: reintento MKV con head de {len(_big) // 1024}KB",
                  flush=True)
            blob = bytes(_big)
            media = await _probe_blob(blob)
    if not media:
        raise RuntimeError("ffprobe sin datos")
    if not _useful(media):
        # Sin resolución ni audios no sirve para tags/badges: no guardar
        # (marcaría ready para siempre). Reintentar como fallo normal.
        print(f" [PROBE] {key}: inútil (bytes={len(blob)}, { _blob_diag(blob, ext)})",
              flush=True)
        raise RuntimeError("ffprobe sin datos útiles")
    try:
        if moov_pos > 0 and moov_size > 0:
            media["moovpos"] = int(moov_pos)
            media["moovsize"] = int(moov_size)
    except Exception:
        pass
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
    try:
        # Diagnóstico temporal: éxitos mp4 sin audio (¿moov parcial?).
        if str(ext or "").lower() in (".mp4", ".m4v", ".mov") and not media.get("audiotracks"):
            _sts = []
            for _s in (media.get("_streams") or []):
                _sts.append(str((_s or {}).get("codec_type") or "?") + ":" + str((_s or {}).get("codec_name") or "?"))
            print(f" [PROBE] {key}: streams=[{','.join(_sts)}] moovpos={media.get('moovpos') or 0}", flush=True)
    except Exception:
        pass
    try:
        _CLAIMED.discard(str(key or ""))
    except Exception:
        pass
    return True


def _quarantine_video_only(limit: int = 200) -> int:
    """Re-sonda filas mp4/m4v/mov con vídeo pero sin audios (moov parcial
    sospechoso de sondas viejas): borra la fila y re-encola el título.
    Una vez por arranque. Devuelve cuántas."""
    try:
        from services.media_probe_queue import enqueue_title as _enq
    except Exception:
        try:
            from tvcat.services.media_probe_queue import enqueue_title as _enq
        except Exception:
            return 0
    n = 0
    try:
        conn = _conn()
        try:
            # Solo lo no re-sondado ya por el worker actual (src): sin esa
            # memoria, los mp4 genuinamente sin audio entrarían en bucle
            # de re-sonda en cada arranque.
            rows = conn.execute(
                "SELECT episode_key FROM episode_media"
                " WHERE COALESCE(json_extract(media_json, '$.resolution'), '') <> ''"
                " AND COALESCE(json_extract(media_json, '$.audiotracks'), '') = ''"
                " AND LOWER(COALESCE(json_extract(media_json, '$.extension'), ''))"
                " IN ('mp4', 'm4v', 'mov')"
                " AND COALESCE(src, '') NOT LIKE 'worker%'"
                " LIMIT ?", (int(limit or 200),)).fetchall()
            keys = [str(r[0]) for r in rows if r[0]]
        finally:
            try:
                conn.close()
            except Exception:
                pass
        for key in keys:
            try:
                conn = _conn()
                try:
                    r = conn.execute(
                        "SELECT item_id FROM item_episodes WHERE episode_key=? LIMIT 1",
                        (key,)).fetchone()
                    iid = str(dict(r).get("item_id") or "") if r else ""
                    conn.execute("DELETE FROM episode_media WHERE episode_key=?", (key,))
                    conn.commit()
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                if iid and _enq(iid):
                    n += 1
            except Exception:
                pass
    except Exception:
        pass
    if n:
        print(f" [PROBE] cuarentena solo-vídeo: {n} a re-sonda", flush=True)
    return n


async def run():
    """Bucle del worker. Pensado para `_spawn` (cancelable)."""
    print(" [PROBE] worker de sonda media iniciado (fondo)", flush=True)
    # Limpieza de filas inútiles (sin resolución ni audios): marcaban ready
    # para siempre sin datos. Se re-sondarán solas.
    try:
        await asyncio.to_thread(_purge_useless)
    except Exception:
        pass
    # Cuarentena una vez por arranque: mp4 solo-vídeo (moov parcial
    # sospechoso) a re-sonda con el cazador actual.
    try:
        await asyncio.to_thread(_quarantine_video_only, 200)
    except Exception:
        pass
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
                try:
                    _busy = await _yield_to_bulk()
                except Exception:
                    _busy = False
                if _busy:
                    # Descargas/subidas en curso o bulk saturado: ceder paso.
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
                    # Sin clientes: devolver a la cola y esperar (log
                    # estrangulado para no spamear cada 30s).
                    try:
                        import time as _t
                        global _last_noclient_log
                        now = _t.time()
                        if now - float(globals().get("_last_noclient_log", 0) or 0) > 300:
                            globals()["_last_noclient_log"] = now
                            print(" [PROBE] sin clientes Telegram, reintento en 30s", flush=True)
                    except Exception:
                        pass
                    _requeue(job, int(job.get("attempts") or 0))
                    try:
                        _CLAIMED.discard(str(job.get("episode_key") or ""))
                    except Exception:
                        pass
                    await asyncio.sleep(NOCLIENT_SLEEP)
            except asyncio.CancelledError:
                try:
                    _CLAIMED.discard(str(job.get("episode_key") or ""))
                except Exception:
                    pass
                _requeue(job, int(job.get("attempts") or 0))
                raise
            except Exception as e:
                n = int(job.get("attempts") or 0) + 1
                print(f" [PROBE] {job.get('episode_key')}: {e}"
                      f" (intento {n}/{MAX_ATTEMPTS})", flush=True)
                if n < MAX_ATTEMPTS:
                    _requeue(job, n)
                    try:
                        _CLAIMED.discard(str(job.get("episode_key") or ""))
                    except Exception:
                        pass
                    await asyncio.sleep(2)
                else:
                    try:
                        from services.media_probe_queue import park_episode as _park
                    except Exception:
                        try:
                            from tvcat.services.media_probe_queue import park_episode as _park2
                            _park = _park2
                        except Exception:
                            _park = lambda *a, **k: None
                    try:
                        _park(job.get("episode_key"), n, str(e)[:200])
                    except Exception:
                        pass
                    try:
                        _CLAIMED.discard(str(job.get("episode_key") or ""))
                    except Exception:
                        pass
                    print(f" [PROBE] {job.get('episode_key')}: aparcado ({e})",
                          flush=True)
    except asyncio.CancelledError:
        print(" [PROBE] worker detenido", flush=True)
        raise
