"""FastDownload Pyrofork — descarga paralela sobre UNA sola conexión.

Port fiel de `SampleCode/Nanaki_docker/fast_download.py` (bot verificado a
18-20 MB/s). Ver `FastDownload_Implementation_Plan.md` (F1).

Idea: pyrogram descarga en serie (1 trozo de 1MB → espera → siguiente), con lo
que el throughput queda limitado por `chunk / RTT`. La sesión MTProto ya
soporta N peticiones en vuelo sobre la MISMA conexión (cada una con su msg_id),
así que basta lanzar N `GetFile()` concurrentes (offsets distintos) con
`asyncio.gather()` + semáforo. Sin clonar sesiones, sin N handshakes TLS por
fichero (a diferencia del multi-TCP Telethon, que queda como fallback).

Diferencias mínimas respecto al original (adaptación TVCat):
- `progress` es un callback simple `cb(cur, tot)` (sync o async), sin
  `progress_args` (nuestro `_cb` de TransferService ya cierra sobre el job).
- Acepta `message` Pyrogram O `file_id_str` + `file_size` explícito (los
  llamadores CORE resuelven el documento de formas distintas).
- Si algo falla o el contenido no aplica (fotos CDN, archivos pequeños),
  devuelve None y el llamador usa su fallback habitual. NUNCA deja sin archivo
  por un fallo aquí (el parcial truncado se borra antes de devolver None).
"""

import asyncio
import logging
import os
import time

log = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1MB; tamaño de trozo que exige la API de Telegram
DEFAULT_WORKERS = 8
MAX_RETRIES_PER_CHUNK = 8
# Errores de red a nivel de sesión: con estos NO se abandona (el download_media
# normal va a ~1.3MB/s); se reintenta el chunk y se reconecta la media session.
NETWORK_ERROR_TYPES = (ConnectionError, OSError, TimeoutError)

# ─── Ajustes globales (tvcat_settings, configurables en
#     Configuración → Credenciales → Comportamiento Telegram) ───
_SPEED_CACHE = {}
_SPEED_TS = 0.0
_SPEED_TTL = 30.0


def get_speed_setting(key: str, default: int) -> int:
    """Lee un ajuste de velocidad (tg_fastdl_workers/tg_fastul_workers)."""
    global _SPEED_TS
    now = time.monotonic()
    if now - _SPEED_TS > _SPEED_TTL:
        try:
            from services.catalog_service import get_conn
            conn = get_conn()
            for k in ("tg_fastdl_workers", "tg_fastul_workers", "tg_fastul_sessions"):
                try:
                    r = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (k,)).fetchone()
                    if r and r[0] not in (None, ""):
                        _SPEED_CACHE[k] = r[0]
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass
        except Exception:
            pass
        _SPEED_TS = now
    try:
        return max(1, min(16, int(_SPEED_CACHE.get(key, default))))
    except Exception:
        return default


def resolve_workers(explicit, key: str, default: int = DEFAULT_WORKERS) -> int:
    """Precedencia: valor explícito (plugin/llamada) > ajuste global > defecto."""
    try:
        if explicit is not None and int(explicit) > 0:
            return max(1, min(16, int(explicit)))
    except Exception:
        pass
    return get_speed_setting(key, default)


class _UnsupportedForFastDownload(Exception):
    """Se lanza para indicar al llamador que use su descarga normal."""


def _extract_file_id_str(message):
    """Saca el file_id (string) del medio del mensaje (documento, vídeo, foto,
    audio, nota de voz/vídeo, animación, sticker). Casos raros → excepción."""
    if isinstance(message, str):
        return message

    media = getattr(message, "media", None)
    if media is None:
        raise _UnsupportedForFastDownload("mensaje sin campo .media")

    medium = getattr(message, media.value, None)
    if medium is None:
        raise _UnsupportedForFastDownload("media.value sin atributo correspondiente")

    # Las fotos son una lista de tamaños; nos interesa el mayor (el último).
    if hasattr(medium, "sizes"):
        medium = medium.sizes[-1]

    file_id_str = getattr(medium, "file_id", None)
    if not file_id_str:
        raise _UnsupportedForFastDownload("medio sin file_id")

    return file_id_str


def _build_location(file_id_obj):
    """Construye el Input*FileLocation según el tipo (foto vs documento)."""
    from pyrogram import raw
    from pyrogram.file_id import FileType

    file_type = file_id_obj.file_type
    if file_type == FileType.CHAT_PHOTO:
        raise _UnsupportedForFastDownload("CHAT_PHOTO no soportado en descarga rápida")
    elif file_type == FileType.PHOTO:
        return raw.types.InputPhotoFileLocation(
            id=file_id_obj.media_id,
            access_hash=file_id_obj.access_hash,
            file_reference=file_id_obj.file_reference,
            thumb_size=file_id_obj.thumbnail_size,
        )
    else:
        return raw.types.InputDocumentFileLocation(
            id=file_id_obj.media_id,
            access_hash=file_id_obj.access_hash,
            file_reference=file_id_obj.file_reference,
            thumb_size=file_id_obj.thumbnail_size,
        )


async def _get_media_session(client, dc_id):
    """Reutiliza la sesión de medios de ese DC (igual que `Client.get_file()`
    por dentro): no reinventa autenticación ni import de autorización."""
    from pyrogram import raw
    from pyrogram.errors import AuthBytesInvalid
    from pyrogram.session import Auth, Session

    session = client.media_sessions.get(dc_id)
    if session:
        return session

    session = client.media_sessions[dc_id] = Session(
        client, dc_id,
        await Auth(client, dc_id, await client.storage.test_mode()).create()
        if dc_id != await client.storage.dc_id()
        else await client.storage.auth_key(),
        await client.storage.test_mode(),
        is_media=True,
    )
    await session.start()

    if dc_id != await client.storage.dc_id():
        for _ in range(3):
            exported_auth = await client.invoke(
                raw.functions.auth.ExportAuthorization(dc_id=dc_id)
            )
            try:
                await session.invoke(
                    raw.functions.auth.ImportAuthorization(
                        id=exported_auth.id, bytes=exported_auth.bytes
                    )
                )
            except AuthBytesInvalid:
                continue
            else:
                break
        else:
            raise AuthBytesInvalid

    return session


# Pool de sesiones extra de subida por DC (multi-conexión). La primera sesión
# es siempre la del cliente (sin handshake); las extra se crean una vez y se
# reutilizan entre ficheros. Si el pool reconecta (nuevo objeto cliente), las
# sesiones viejas se descartan (si no, pyro las revive solo con create_task →
# ruido 'closed database' y conexiones zombi).
_UL_SESSION_POOL = {}  # (sess_hash, dc_id) -> {"client": client, "sessions": [...]}


def _sess_hash(client) -> int:
    try:
        return abs(hash(str(getattr(getattr(client, 'session', None), 'session_string', None)
                             or getattr(client, 'name', ''))))
    except Exception:
        return 0


def _drop_upload_sessions(live_client=None):
    """Descarta sesiones extra cuyo dueño no es `live_client` (muerto tras
    reconnect). Sin argumento lo vacía todo."""
    try:
        for key in list(_UL_SESSION_POOL.keys()):
            entry = _UL_SESSION_POOL.get(key) or {}
            if live_client is not None and entry.get("client") is live_client:
                continue
            for s in entry.get("sessions", []):
                try:
                    if asyncio.iscoroutinefunction(getattr(s, 'stop', None)):
                        try:
                            asyncio.get_running_loop().create_task(s.stop())
                        except Exception:
                            pass
                    else:
                        s.stop()
                except Exception:
                    pass
            _UL_SESSION_POOL.pop(key, None)
    except Exception:
        pass


async def _get_upload_sessions(client, dc_id, n: int):
    """Devuelve N sesiones de medios para subir en multi-conexión.
    N=1 → solo la del cliente. N>1 → extra dedicadas (pool reutilizable)."""
    from pyrogram.session import Session

    first = await _get_media_session(client, dc_id)
    n = max(1, min(int(n or 1), 8))
    if n <= 1:
        return [first]
    key = (_sess_hash(client), dc_id)
    entry = _UL_SESSION_POOL.get(key)
    if entry is None or entry.get("client") is not client:
        # Cliente nuevo (reconnect) o primera vez: descartar sesiones viejas.
        _drop_upload_sessions(live_client=client)
        entry = {"client": client, "sessions": []}
        _UL_SESSION_POOL[key] = entry
    pool = entry["sessions"]
    # Sin API pública de estado en pyrofork (no hay is_connected): se reutiliza
    # el pool tal cual; si una sesión murió, el worker la reinicia al fallar
    # (Session.restart) y reintenta la parte.
    while len(pool) < n - 1:
        try:
            s = Session(client, dc_id, await client.storage.auth_key(),
                        await client.storage.test_mode(), is_media=True)
            await s.start()
            # Mismo DC de la cuenta → auth_key ya válido, sin export/import.
            # (Subimos al DC de la cuenta; el download ya cubre DCs ajenos.)
            pool.append(s)
        except Exception as e:
            print(f"[FASTUL] sesión extra no disponible ({e})", flush=True)
            break
    print(f"[FASTUL] pool sesiones: {len(pool) + 1} (dc={dc_id})", flush=True)
    return [first] + pool[:max(0, n - 1)]


async def _report_progress(progress, current, total):
    """Llama al callback de progreso (sync o async)."""
    if not progress:
        return
    try:
        res = progress(current, total)
        if asyncio.iscoroutine(res):
            await res
    except Exception as e:
        log.debug(f"fast_download: error en progress callback: {e}")


async def _fetch_chunk(session, location, offset, limit, sleep_threshold, semaphore,
                       bulk_priority: int = 1):
    from pyrogram import raw
    from pyrogram.errors import FloodWait

    def _gate():
        from services.telegram_service import get_telegram_service
        return get_telegram_service()

    async with semaphore:
        network_errors_streak = 0
        for attempt in range(MAX_RETRIES_PER_CHUNK):
            await _gate().bulk_acquire(bulk_priority)
            try:
                r = await session.invoke(
                    raw.functions.upload.GetFile(location=location, offset=offset, limit=limit),
                    sleep_threshold=sleep_threshold,
                )
                network_errors_streak = 0
            except FloodWait as e:
                _gate().bulk_flood_report(float(getattr(e, 'value', 0) or 0))
                await asyncio.sleep(e.value + 1)
                continue
            except NETWORK_ERROR_TYPES:
                network_errors_streak += 1
                # Fallo de red persistente: reconectar la media session una vez
                # (el auth key sigue en storage).
                if network_errors_streak >= 3:
                    try:
                        await session.stop()
                    except Exception:
                        pass
                    try:
                        await session.start()
                    except Exception:
                        pass
                await asyncio.sleep(min(0.5 * attempt, 4))
                continue
            finally:
                await _gate().bulk_release()

            if isinstance(r, raw.types.upload.File):
                return offset, r.bytes
            # FileCdnRedirect u otro tipo inesperado: fallback a download normal.
            raise _UnsupportedForFastDownload(f"respuesta inesperada de GetFile: {type(r)}")

        raise TimeoutError(f"chunk en offset {offset} agotó los {MAX_RETRIES_PER_CHUNK} reintentos")


async def fast_download_media(client, message, file_path: str,
                              file_size: int = 0,
                              workers: int = None,
                              progress=None,
                              bulk_priority: int = 1):
    """Descarga el medio a `file_path` con N trozos en paralelo (1 sola conexión).

    `message`: mensaje Pyrogram o file_id (string). Si es file_id, `file_size`
    es obligatorio. `workers`: nº de GetFile concurrentes (None = ajuste global
    `tg_fastdl_workers`, defecto 8; 1 = fallback). `progress`: callback
    `cb(cur, tot)` sync o async. `bulk_priority`: 0 streaming, 1 copia, 2 fondo.
    Devuelve `file_path` en éxito, None si hay que usar la descarga normal.
    """
    try:
        from pyrogram.file_id import FileId

        file_id_str = _extract_file_id_str(message)
        file_id_obj = FileId.decode(file_id_str)
        location = _build_location(file_id_obj)

        if not file_size:
            media = getattr(message, message.media.value, None) if not isinstance(message, str) else None
            file_size = int(getattr(media, "file_size", 0) or 0)

        if file_size <= 0:
            raise _UnsupportedForFastDownload("tamaño de archivo desconocido")

        workers = resolve_workers(workers, "tg_fastdl_workers", DEFAULT_WORKERS)
        if workers <= 1 or file_size <= CHUNK_SIZE * workers:
            # Archivo pequeño o paralelismo desactivado: no compensa.
            raise _UnsupportedForFastDownload("archivo pequeño o workers<=1, no compensa")

        dc_id = file_id_obj.dc_id
        session = await _get_media_session(client, dc_id)

        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        semaphore = asyncio.Semaphore(workers)
        bytes_done = 0
        bytes_done_lock = asyncio.Lock()
        loop = asyncio.get_running_loop()

        # Preasignar el fichero al tamaño final (el parcial truncado se borra
        # en el except general si la descarga no se completa).
        fd = os.open(file_path, os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            os.ftruncate(fd, file_size)
        finally:
            os.close(fd)

        def _write_at(path, data, offset):
            # os.pwrite NO existe en Windows: open/seek/write/close por
            # chunk (seguro en paralelo, sin locks ni handles compartidos).
            with open(path, "r+b") as f:
                f.seek(offset)
                f.write(data)

        async def worker(chunk_index):
            nonlocal bytes_done
            offset = chunk_index * CHUNK_SIZE
            limit = min(CHUNK_SIZE, file_size - offset)
            # El limit se pide completo (offset % limit == 0); el servidor
            # devuelve menos bytes en la cola. Acortarlo da LIMIT_INVALID.
            _, data = await _fetch_chunk(
                session, location, offset, CHUNK_SIZE,
                getattr(client, "sleep_threshold", 10), semaphore,
                bulk_priority)
            if data:
                await loop.run_in_executor(None, _write_at, file_path, data[:limit], offset)
            async with bytes_done_lock:
                bytes_done += limit
                current = bytes_done
            await _report_progress(progress, current, file_size)

        await asyncio.gather(*(worker(i) for i in range(total_chunks)))

        await _report_progress(progress, file_size, file_size)
        return file_path

    except _UnsupportedForFastDownload as e:
        log.info(f"fast_download: fallback a descarga normal ({e})")
    except Exception as e:
        log.warning(f"fast_download: fallo inesperado, fallback a descarga normal ({e})")
        # Borrar el parcial (truncado a tamaño final pero incompleto) para que
        # el fallback no escriba sobre un fichero a medias.
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

    return None


# ─── Subida rápida ───────────────────────────────────────────────
# Misma idea que la descarga pero en sentido contrario: pyrofork sube con
# workers_count=4 fijo (save_file.py) y crea una sesión nueva POR FICHERO
# (handshake TLS cada vez). Aquí los workers son configurables
# (`tg_fastul_workers`), se reutiliza la media session del cliente y, si el DC
# raciona el ingress por conexión (subida estable muy por debajo de la bajada
# con el mismo RTT), se reparte en N sesiones (`tg_fastul_sessions`, pool
# reutilizable sin handshakes por fichero).

async def fast_upload_file(client, file_path: str, workers: int = None,
                           progress=None, file_id: int = None, sessions: int = None,
                           bulk_priority: int = 1):
    """Sube `file_path` por partes concurrentes (multi-conexión si sessions>1).
    Devuelve `InputFile` (<10MB, con md5) o `InputFileBig`.
    Lanza excepción si falla (el llamador aplica su fallback)."""
    from pyrogram import raw
    from pyrogram.errors import FloodWait

    workers = resolve_workers(workers, "tg_fastul_workers", DEFAULT_WORKERS)
    try:
        _ns = int(sessions) if sessions else int(get_speed_setting("tg_fastul_sessions", 1))
    except Exception:
        _ns = 1
    _ns = max(1, min(_ns, 4))
    part_size = 512 * 1024

    file_size = os.path.getsize(file_path)
    if file_size <= 0:
        raise ValueError("File size equals to 0 B")

    try:
        # is_premium cacheado en el propio cliente (get_me = users.GetFullUser,
        # con FloodWait en escalada si se llama por fichero).
        if hasattr(client, "_tvcat_premium"):
            _premium = bool(client._tvcat_premium)
        else:
            _me = await client.get_me()
            _premium = bool(getattr(_me, "is_premium", False))
            try:
                client._tvcat_premium = _premium
            except Exception:
                pass
    except Exception:
        _premium = True  # no bloquear por no poder leer el flag
    if file_size > (4000 if _premium else 2000) * 1024 * 1024:
        raise ValueError("Fichero por encima del límite de subida")

    import math
    from hashlib import md5
    file_total_parts = int(math.ceil(file_size / part_size))
    is_big = file_size > 10 * 1024 * 1024
    file_id = file_id or client.rnd_id()
    md5_sum = md5() if not is_big else None

    try:
        dc_id = await client.storage.dc_id()
    except Exception as e:
        # Storage sqlite cerrado (cliente desconectado por otra tarea):
        # no reintentar aquí, el llamador aplica su fallback (Telethon).
        raise RuntimeError(f"storage pyro no disponible ({e})")
    _sessions = await _get_upload_sessions(client, dc_id, _ns)
    print(f"[FASTUL] subiendo {file_size/(1024*1024):.1f} MB en {len(_sessions)} sesion(es) x {workers} workers", flush=True)
    _t0 = time.monotonic()

    queue = asyncio.Queue(max(1, workers))
    done_parts = [0]

    def _gate():
        from services.telegram_service import get_telegram_service
        return get_telegram_service()

    async def _worker(sess):
        while True:
            item = await queue.get()
            if item is None:
                return
            part_no, chunk = item
            try:
                if is_big:
                    rpc = raw.functions.upload.SaveBigFilePart(
                        file_id=file_id, file_part=part_no,
                        file_total_parts=file_total_parts, bytes=chunk)
                else:
                    rpc = raw.functions.upload.SaveFilePart(
                        file_id=file_id, file_part=part_no, bytes=chunk)
                for attempt in range(MAX_RETRIES_PER_CHUNK):
                    await _gate().bulk_acquire(bulk_priority)
                    try:
                        await sess.invoke(rpc, sleep_threshold=getattr(client, "sleep_threshold", 10))
                        break
                    except FloodWait as e:
                        _gate().bulk_flood_report(float(getattr(e, 'value', 0) or 0))
                        await asyncio.sleep(e.value + 1)
                        continue
                    except NETWORK_ERROR_TYPES:
                        # Sesión posiblemente muerta (sin is_connected en pyrofork):
                        # reiniciarla una vez antes de seguir reintentando.
                        if attempt == 2:
                            try:
                                await sess.restart()
                            except Exception:
                                pass
                        await asyncio.sleep(min(0.5 * attempt, 4))
                        continue
                    finally:
                        await _gate().bulk_release()
                async with _lock:
                    done_parts[0] += 1
                    _cur = min(done_parts[0] * part_size, file_size)
                await _report_progress(progress, _cur, file_size)
            finally:
                del chunk

    _lock = asyncio.Lock()
    _loop = asyncio.get_running_loop()
    tasks = [_loop.create_task(_worker(_sessions[i % len(_sessions)])) for i in range(workers)]
    try:
        with open(file_path, "rb") as fp:
            part_no = 0
            while True:
                chunk = fp.read(part_size)
                if not chunk:
                    break
                if md5_sum is not None:
                    md5_sum.update(chunk)
                await queue.put((part_no, chunk))
                part_no += 1
        for _ in tasks:
            await queue.put(None)
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()

    if done_parts[0] != file_total_parts:
        raise TimeoutError(f"subida incompleta ({done_parts[0]}/{file_total_parts} partes)")

    await _report_progress(progress, file_size, file_size)
    _dt = max(time.monotonic() - _t0, 0.01)
    print(f"[FASTUL] partes OK en {_dt:.0f}s ({file_size/1024/1024/_dt:.1f} MB/s)", flush=True)
    if is_big:
        return raw.types.InputFileBig(id=file_id, parts=file_total_parts,
                                      name=os.path.basename(file_path))
    return raw.types.InputFile(id=file_id, parts=file_total_parts,
                               name=os.path.basename(file_path),
                               md5_checksum="".join(hex(i)[2:].zfill(2) for i in md5_sum.digest()))


async def fast_send_media(client, chat_id: int, file_path: str, is_video: bool,
                          file_name: str = None, caption: str = None,
                          duration: int = 0, width: int = 0, height: int = 0,
                          thumb_bytes: bytes = None, reply_to_msg_id: int = None,
                          workers: int = None, progress=None, sessions: int = None,
                          bulk_priority: int = 1) -> int:
    """Subida rápida completa: partes concurrentes + SendMedia raw.
    Vídeo → atributos de vídeo con streaming; resto → documento.
    Devuelve el msg_id creado (0 si no se pudo extraer)."""
    import io
    import mimetypes
    from pyrogram import raw

    fname = file_name or os.path.basename(file_path)
    _st0 = time.monotonic()
    input_file = await fast_upload_file(client, file_path, workers=workers,
                                        progress=progress, sessions=sessions,
                                        bulk_priority=bulk_priority)

    thumb_input = None
    if thumb_bytes:
        # Subida manual del thumb (SaveFilePart directo): client.save_file()
        # exige client.me (solo lo fija start(); con connect() es None).
        try:
            from hashlib import md5 as _md5
            import math as _math
            _td = bytes(thumb_bytes)
            _tparts = max(1, int(_math.ceil(len(_td) / (512 * 1024))))
            _tfile_id = client.rnd_id()
            _tmd5 = _md5()
            _tdc = await client.storage.dc_id()
            _tsess = await _get_media_session(client, _tdc)
            for _n in range(_tparts):
                _chunk = _td[_n * 512 * 1024:(_n + 1) * 512 * 1024]
                _tmd5.update(_chunk)
                await _tsess.invoke(raw.functions.upload.SaveFilePart(
                    file_id=_tfile_id, file_part=_n, bytes=_chunk),
                    sleep_threshold=getattr(client, "sleep_threshold", 10))
            thumb_input = raw.types.InputFile(
                id=_tfile_id, parts=_tparts, name="thumb.jpg",
                md5_checksum="".join(hex(i)[2:].zfill(2) for i in _tmd5.digest()))
        except Exception as e:
            print(f"[FASTUL] thumb no subido ({e}), se envía sin thumb", flush=True)
            thumb_input = None

    if is_video:
        ext = os.path.splitext(fname)[1].lower()
        mime = "video/x-matroska" if ext == ".mkv" else "video/mp4"
        attrs = [raw.types.DocumentAttributeVideo(
                    duration=int(duration or 0), w=int(width or 0),
                    h=int(height or 0), supports_streaming=True),
                 raw.types.DocumentAttributeFilename(file_name=fname)]
    else:
        mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        attrs = [raw.types.DocumentAttributeFilename(file_name=fname)]

    media = raw.types.InputMediaUploadedDocument(
        file=input_file, mime_type=mime, attributes=attrs, thumb=thumb_input)
    peer = await client.resolve_peer(int(chat_id))
    reply_to = None
    if reply_to_msg_id:
        try:
            reply_to = raw.types.InputReplyToMessage(reply_to_msg_id=int(reply_to_msg_id))
        except Exception:
            reply_to = None

    r = await client.invoke(raw.functions.messages.SendMedia(
        peer=peer, media=media, message=caption or "",
        random_id=client.rnd_id(), reply_to=reply_to))

    # Extraer el msg_id del update resultante.
    try:
        for upd in getattr(r, "updates", []):
            m = getattr(upd, "message", None)
            if m is not None and getattr(m, "id", 0):
                _mid = int(m.id)
                print(f"[FASTUL] enviado msg={_mid} en {time.monotonic()-_st0:.0f}s", flush=True)
                return _mid
    except Exception:
        pass
    return 0
