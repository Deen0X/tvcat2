"""FileTransfer — transferencia directa de ficheros (CORE, sin cola).

Réplica 1:1 de la maquinaria de TGHirayi en sus mismos términos (fichero
COMPLETO, sin seek) para que todos los plugins se beneficien de su velocidad
sin duplicar código. TGHirayi NO se toca (migración futura).

- `download_file()`: multi-conexión Telethon reanudable (sidecar .chunks,
  FileMigrate, refresh de file_reference) o `fast_download_media` con Pyrofork.
- `upload_file()`: Telethon directo (<10MB) / paralelo + send_file, o
  `fast_send_media` con Pyrofork. Devuelve el msg_id creado (0 si no extraíble).
- `download_episode_files()`: versión slim de "episodes" (sin normalizado ni
  thumbs, que siguen en el plugin): lista de {file_path, file_name, file_size}.

F2: `download_range()` con seek para reproductores (implementado abajo).
"""

import asyncio
import os
import time
from typing import List, Optional

CHUNK = 512 * 1024          # 512KB: límite máximo por GetFileRequest
BIG_UPLOAD_THRESHOLD = 10 * 1024 * 1024   # <10MB envío directo
BIG_FILE_LIMIT = int(1.9 * 1024 * 1024 * 1024)  # >=1.9GB requiere Pyrofork
REQ_TIMEOUT = 90            # una sola petición debe responder en <90s
CONNECT_TIMEOUT = 15        # un secundario debe conectar en <15s


def _client_type(client, hint: str = None) -> str:
    """Detecta 'telethon' o 'pyrogram' (hint explícito manda). Sin pista,
    el preferido global: nunca telethon hardcodeado."""
    if hint in ("telethon", "pyrogram"):
        return hint
    try:
        mod = type(client).__module__ or ""
        if "pyrogram" in mod:
            return "pyrogram"
        if "telethon" in mod:
            return "telethon"
    except Exception:
        pass
    try:
        from services.userbot_service import get_preferred_client_type as _pct
        return _pct()
    except Exception:
        try:
            from tvcat.services.userbot_service import get_preferred_client_type as _pct2
            return _pct2()
        except Exception:
            return "telethon"


def _report(progress, cur, tot):
    if not progress:
        return None
    try:
        res = progress(cur, tot)
        if asyncio.iscoroutine(res):
            return res
    except Exception:
        pass
    return None


_ACT_MARK = {"t": 0.0}
_BULK_ACTIVE = {"t": 0.0}


def bulk_active_recent(secs: float = 30.0) -> bool:
    """True si hubo tráfico bulk (descarga/subida de ficheros) hace menos
    de `secs` segundos. La sonda lo usa para ceder el paso a la cola de
    episodios (que no pasa por TransferService y el BulkGate solo la ve a
    ráfagas por chunk)."""
    try:
        import time as _t
        return (_t.monotonic() - float(_BULK_ACTIVE.get("t") or 0.0)) < float(secs or 30.0)
    except Exception:
        return False


def _touch_activity():
    """Marca actividad Telegram (estrangulada a 1/5s): el tráfico bulk en
    curso queda visible para feeder/sonda sin spamear."""
    try:
        now = time.monotonic()
        try:
            _BULK_ACTIVE["t"] = now
        except Exception:
            pass
        if now - float(_ACT_MARK.get("t") or 0.0) < 5.0:
            return
        _ACT_MARK["t"] = now
        try:
            from services.tg_activity import mark as _mk
        except Exception:
            from tvcat.services.tg_activity import mark as _mk
        _mk()
    except Exception:
        pass


def _tracked(progress):
    """Envuelve el callback de progreso del llamador marcando actividad."""
    if progress is None:
        def _p(cur, tot):
            _touch_activity()
            return None
        return _p

    def _p2(cur, tot):
        _touch_activity()
        return progress(cur, tot)
    return _p2


def _mbps(nbytes, seconds):
    try:
        if seconds <= 0:
            return 0.0
        return (float(nbytes) / 1048576.0) / float(seconds)
    except Exception:
        return 0.0


# ─── Descarga ────────────────────────────────────────────────────

async def download_file(client, chat_id, msg_id, dest_path: str,
                        threads: int = 8, progress=None,
                        client_type: str = None,
                        pre_msg=None, bulk_priority: int = 1) -> Optional[str]:
    """Descarga el documento de (chat_id, msg_id) a `dest_path` (fichero completo).
    Reanudable (sidecar `dest_path + ".chunks"`). Devuelve dest_path en éxito,
    None si no se pudo (el llamador aplica su fallback).
    `pre_msg`: mensaje ya resuelto (evita un get_messages)."""
    ctype = _client_type(client, client_type)
    _t0 = time.monotonic()
    _tprogress = _tracked(progress)
    if ctype == "pyrogram":
        from services import fast_download as _fd
        workers = _fd.resolve_workers(threads, "tg_fastdl_workers", _fd.DEFAULT_WORKERS)
        try:
            if pre_msg is None:
                pre_msg = await client.get_messages(int(chat_id), int(msg_id))
            if pre_msg is None:
                return None
            got = await _fd.fast_download_media(client, pre_msg, dest_path,
                                                workers=workers, progress=_tprogress,
                                                bulk_priority=bulk_priority)
            if got and os.path.isfile(got):
                try:
                    _sz = os.path.getsize(got)
                    print(f"[FT-DL] {_sz/1048576.0:.1f}MB en {time.monotonic()-_t0:.1f}s"
                          f" = {_mbps(_sz, time.monotonic()-_t0):.1f}MB/s"
                          f" (fast pyro, workers={workers})", flush=True)
                except Exception:
                    pass
                return got
        except Exception as e:
            print(f"[FILE-TRANSFER] fast download falló, fallback telethon/secuencial: {e}", flush=True)
        # Fallback secuencial pyro (si hay cliente pyro pero el fast no aplica)
        try:
            if pre_msg is None:
                pre_msg = await client.get_messages(int(chat_id), int(msg_id))
            if pre_msg is not None:
                data = await client.download_media(pre_msg)
                if data:
                    _d = os.path.dirname(dest_path)
                    if _d:
                        os.makedirs(_d, exist_ok=True)
                    with open(dest_path, "wb") as f:
                        f.write(bytes(data))
                    if progress:
                        await _report(progress, len(data), len(data)) or None
                    return dest_path
        except Exception:
            pass
        return None
    _got = await _telethon_parallel_download(client, chat_id, msg_id, dest_path,
                                             threads=threads, progress=_tprogress,
                                             pre_msg=pre_msg)
    if _got and os.path.isfile(_got):
        try:
            _sz = os.path.getsize(_got)
            print(f"[FT-DL] {_sz/1048576.0:.1f}MB en {time.monotonic()-_t0:.1f}s"
                  f" = {_mbps(_sz, time.monotonic()-_t0):.1f}MB/s"
                  f" (telethon 1-conexion, threads={threads})", flush=True)
        except Exception:
            pass
    return _got


async def _telethon_parallel_download(client, chat_id, msg_id, file_path: str,
                                      threads: int, progress=None,
                                      pre_msg=None) -> Optional[str]:
    """Port fiel de TGHirayi `_parallel_download` (multi-TCP + sidecar + migrate).
    No modificar comportamiento sin migrar el plugin a este servicio."""
    import json as _json
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import InputDocumentFileLocation

    msg = pre_msg
    if msg is None:
        try:
            entity = await client.get_entity(int(chat_id))
            msg = await client.get_messages(entity, ids=int(msg_id))
        except Exception:
            return None
    if not msg or not getattr(msg, 'media', None):
        return None

    media = msg.media
    doc = getattr(media, 'document', None) if media else None
    if not doc:
        return None
    file_size = int(getattr(doc, 'size', 0) or 0)
    if file_size <= 0:
        return None

    location = InputDocumentFileLocation(
        id=doc.id,
        access_hash=doc.access_hash,
        file_reference=doc.file_reference,
        thumb_size=''
    )

    async def _refresh_file_reference():
        try:
            peer = getattr(msg, 'peer_id', None) or getattr(msg, 'chat_id', None)
            if peer is None:
                return False
            m = await client.get_messages(peer, ids=msg.id)
            if m and getattr(m, 'media', None) and getattr(m.media, 'document', None):
                nd = m.media.document
                location.file_reference = nd.file_reference
                location.access_hash = nd.access_hash
                return True
        except Exception:
            pass
        return False

    threads = max(1, min(int(threads or 8), 16))

    # Sin conexiones secundarias: un segundo TelegramClient con el mismo
    # session_string (misma auth_key) convive con el del pool y Telegram lo
    # quema como duplicado. Solo el cliente principal (1 conexión).
    secondary = []

    chunk_total = (file_size + CHUNK - 1) // CHUNK
    chunks_side = file_path + ".chunks"

    done = set()
    resume = False
    if os.path.isfile(file_path) and os.path.getsize(file_path) == file_size:
        try:
            with open(chunks_side, 'r', encoding='utf-8') as f:
                done = {int(x) for x in _json.load(f)}
            done = {i for i in done if 0 <= i < chunk_total}
            resume = bool(done)
        except Exception:
            done = set()

    helpers_dir = os.path.dirname(file_path)
    if helpers_dir:
        os.makedirs(helpers_dir, exist_ok=True)
    if not resume:
        with open(file_path, 'wb') as f:
            f.truncate(file_size)
        done = set()
        try:
            os.remove(chunks_side)
        except Exception:
            pass

    def _save_chunks():
        try:
            with open(chunks_side, 'w', encoding='utf-8') as f:
                _json.dump(sorted(done), f)
        except Exception:
            pass

    workers = secondary + [client]
    _nw = max(1, len(workers))  # rangos con workers REALES (no los pedidos)

    def _ranges():
        per = max(1, (chunk_total + _nw - 1) // _nw)
        ranges = []
        for start in range(0, chunk_total, per):
            end = min(start + per, chunk_total)
            if start < chunk_total:
                ranges.append((start, end))
        return ranges

    ranges = _ranges()
    writers = workers

    progress_n = [len(done) * CHUNK]
    lock = asyncio.Lock()
    last_save = [time.perf_counter()]
    from telethon import helpers as _tl_helpers

    async def _dl_range(c, range_start, range_end, retries=3):
        from telethon.errors.rpcerrorlist import FileMigrateError, FileReferenceExpiredError, FilerefUpgradeNeededError
        from services.abort_flags import should_abort_download, DownloadAborted
        if should_abort_download():
            raise DownloadAborted("descarga detenida por el usuario")
        last_err = None
        migrated_sender = None
        for attempt in range(1, retries + 1):
            try:
                with open(file_path, 'r+b') as f:
                    for i in range(range_start, range_end):
                        if should_abort_download():
                            raise DownloadAborted("descarga detenida por el usuario")
                        if i in done:
                            continue
                        offset = i * CHUNK
                        if offset >= file_size:
                            break
                        req = GetFileRequest(location=location, offset=offset, limit=CHUNK)
                        if migrated_sender is not None:
                            result = await asyncio.wait_for(client._call(migrated_sender, req), timeout=REQ_TIMEOUT)
                        else:
                            result = await asyncio.wait_for(c(req), timeout=REQ_TIMEOUT)
                        data = bytes(result.bytes)
                        if not data:
                            last_err = f"chunk {i} vacío"
                            break
                        f.seek(offset)
                        f.write(data)
                        done.add(i)
                        progress_n[0] += len(data)
                        if progress:
                            async with lock:
                                await _tl_helpers._maybe_await(progress(progress_n[0], file_size))
                        now = time.perf_counter()
                        if now - last_save[0] >= 1.0:
                            last_save[0] = now
                            _save_chunks()
                remaining = [i for i in range(range_start, range_end) if i not in done]
                if remaining:
                    last_err = f"{len(remaining)} chunks restantes"
                    raise RuntimeError(last_err)
                return True
            except asyncio.TimeoutError:
                last_err = "timeout"
            except FileMigrateError as e:
                last_err = repr(e)
                try:
                    migrated_sender = await client._borrow_exported_sender(e.new_dc)
                except Exception:
                    migrated_sender = None
            except (FileReferenceExpiredError, FilerefUpgradeNeededError):
                last_err = "file-reference"
                if not await _refresh_file_reference():
                    break
            except DownloadAborted:
                raise
            except Exception as e:
                last_err = repr(e)
        _save_chunks()
        print(f"[FILE-TRANSFER] Rango {range_start}-{range_end} falló tras {retries} intentos ({last_err})", flush=True)
        return False

    try:
        results = await asyncio.gather(*[
            _dl_range(writers[i], ranges[i][0], ranges[i][1])
            for i in range(len(ranges))
        ], return_exceptions=True)
        failed = [ranges[i] for i in range(len(ranges)) if results[i] is not True]
        if failed:
            for rng in failed:
                await _dl_range(client, rng[0], rng[1], retries=4)
        await asyncio.sleep(0.2)
        if len(done) >= chunk_total and os.path.isfile(file_path) and os.path.getsize(file_path) == file_size:
            try:
                os.remove(chunks_side)
            except Exception:
                pass
            return file_path
        _save_chunks()
        return None
    finally:
        for c in secondary:
            try:
                await c.disconnect()
            except Exception:
                pass


# ─── Subida ──────────────────────────────────────────────────────

async def upload_file(client, chat_id, src, file_name: str = "file.bin",
                      caption: str = None, thumb_bytes: bytes = None,
                      is_video: bool = False, duration: int = 0,
                      width: int = 0, height: int = 0,
                      reply_to_msg_id: int = None,
                      threads: int = 4, part_size_kb: int = 512,
                      progress=None, client_type: str = None,
                      bulk_priority: int = 1) -> int:
    """Sube un fichero completo (ruta en disco o bytes) y devuelve el msg_id
    creado (0 si no se pudo extraer). Port de la lógica de subida de TGHirayi:
    Telethon directo (<10MB) / paralelo + send_file, Pyrofork vía fast_send_media
    (cualquier tamaño, incluido >1.9GB)."""
    import io as _io
    import tempfile as _tmp
    ctype = _client_type(client, client_type)
    _t0 = time.monotonic()

    if isinstance(src, str) and os.path.isfile(src):
        tmp_name = src
        _is_temp = False
        fsize = os.path.getsize(src)
    else:
        data_bytes = bytes(src or b"")
        fsize = len(data_bytes)
        tmp = _tmp.NamedTemporaryFile(prefix="ft_up_", suffix='_' + (file_name or "file.bin"), delete=False)
        if data_bytes:
            tmp.write(data_bytes)
        tmp.close()
        tmp_name = tmp.name
        _is_temp = True

    try:
        print(f"[FT-UL] fname={file_name!r} video={bool(is_video)} thumb={bool(thumb_bytes)} "
              f"{int(width or 0)}x{int(height or 0)} d={int(duration or 0)} via={ctype} "
              f"size={fsize}", flush=True)
        if ctype == "pyrogram":
            from services import fast_download as _fd
            _uw = _fd.resolve_workers(threads, "tg_fastul_workers", _fd.DEFAULT_WORKERS)

            def _p(cur, tot):
                _touch_activity()
                if progress:
                    try:
                        r = progress(cur, tot)
                        if asyncio.iscoroutine(r):
                            return r
                    except Exception:
                        pass

            _mid = await _fd.fast_send_media(
                client, int(chat_id), tmp_name, bool(is_video),
                file_name=file_name, caption=caption,
                duration=int(duration or 0), width=int(width or 0),
                height=int(height or 0), thumb_bytes=thumb_bytes,
                reply_to_msg_id=reply_to_msg_id, workers=_uw, progress=_p,
                bulk_priority=bulk_priority)
            try:
                print(f"[FT-UL] {fsize/1048576.0:.1f}MB en {time.monotonic()-_t0:.1f}s"
                      f" = {_mbps(fsize, time.monotonic()-_t0):.1f}MB/s"
                      f" (fast pyro, workers={_uw}) -> msg {_mid}", flush=True)
            except Exception:
                pass
            return _mid

        # Telethon
        from telethon.tl.types import DocumentAttributeVideo
        entity = await client.get_entity(int(chat_id))
        thumb = _io.BytesIO(thumb_bytes) if thumb_bytes else None
        if thumb is not None:
            thumb.name = "thumb.jpg"
        if fsize >= BIG_FILE_LIMIT:
            raise RuntimeError(f"Fichero de {fsize/(1024**3):.2f}GB requiere Pyrofork (Telethon no sube >2GB)")
        if is_video:
            attrs = [DocumentAttributeVideo(duration=int(duration or 0), w=int(width or 0),
                                            h=int(height or 0), supports_streaming=True)]
        else:
            attrs = None

        async def _ul_progress(cur, tot):
            _touch_activity()
            if progress:
                try:
                    r = progress(cur, tot)
                    if asyncio.iscoroutine(r):
                        await r
                except Exception:
                    pass

        if fsize > BIG_UPLOAD_THRESHOLD and max(1, int(threads or 1)) > 1:
            input_file = await _telethon_parallel_upload(
                client, tmp_name, fsize, max(1, int(threads)), max(32, min(int(part_size_kb or 512), 512)),
                file_name=file_name, progress_callback=_ul_progress)
            sent = await client.send_file(entity, input_file, caption=caption or None,
                                          attributes=attrs, thumb=thumb,
                                          reply_to=reply_to_msg_id if reply_to_msg_id else None,
                                          supports_streaming=bool(is_video))
        else:
            sent = await client.send_file(entity, tmp_name, caption=caption or None,
                                          attributes=attrs, thumb=thumb,
                                          reply_to=reply_to_msg_id if reply_to_msg_id else None,
                                           supports_streaming=bool(is_video),
                                           progress_callback=_ul_progress)
        _mid2 = int(getattr(sent, 'id', 0) or 0)
        try:
            print(f"[FT-UL] {fsize/1048576.0:.1f}MB en {time.monotonic()-_t0:.1f}s"
                  f" = {_mbps(fsize, time.monotonic()-_t0):.1f}MB/s"
                  f" (telethon 1-conexion, threads={threads}) -> msg {_mid2}", flush=True)
        except Exception:
            pass
        return _mid2
    finally:
        if _is_temp:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass


async def _telethon_parallel_upload(client, file_path, file_size, threads, part_size_kb,
                                    file_name="file.bin", progress_callback=None):
    """Port fiel de TGHirayi `_parallel_upload` (SaveBigFilePart multi-TCP).
    Devuelve InputFileBig listo para send_file."""
    import time as _time
    from telethon.tl.functions.upload import SaveBigFilePartRequest
    from telethon.tl.types import InputFileBig
    from telethon.helpers import generate_random_long

    part_size = int(part_size_kb * 1024)
    part_count = (file_size + part_size - 1) // part_size
    file_id = generate_random_long()
    threads = max(1, min(int(threads), 16))

    # Sin conexiones secundarias: un segundo TelegramClient con el mismo
    # session_string (misma auth_key) convive con el del pool y Telegram lo
    # quema como duplicado. Solo el cliente principal (1 conexión).
    secondary = []

    last_ul = [0.0]
    pos = [0]
    lock = asyncio.Lock()
    from telethon import helpers as _tl_helpers

    async def _report():
        if progress_callback:
            now = _time.perf_counter()
            if now - last_ul[0] >= 1.0:
                last_ul[0] = now
                await _tl_helpers._maybe_await(progress_callback(pos[0], file_size))

    async def _upload_range(c, indices):
        for idx in indices:
            with open(file_path, 'rb') as f:
                f.seek(idx * part_size)
                part = f.read(part_size)
            req = SaveBigFilePartRequest(file_id, idx, part_count, part)
            ok = await c(req)
            if not ok:
                raise RuntimeError(f"Fallo subiendo parte {idx + 1}/{part_count}")
            pos[0] += len(part)
            async with lock:
                await _report()

    clients = (secondary + [client])[:threads]
    groups = [[] for _ in range(len(clients))]
    for i in range(part_count):
        groups[i % len(clients)].append(i)

    try:
        await asyncio.gather(*[
            _upload_range(clients[g], groups[g])
            for g in range(len(clients)) if groups[g]
        ])
    finally:
        for c in secondary:
            try:
                await c.disconnect()
            except Exception:
                pass

    return InputFileBig(file_id, part_count, file_name)


# ─── Episodios (slim) ────────────────────────────────────────────

async def download_episode_files(client, chat_id, msg_ids: list, dest_dir: str,
                                 threads: int = 8, progress=None,
                                 client_type: str = None) -> List[dict]:
    """Descarga los mensajes indicados (ficheros completos) a `dest_dir`.
    Devuelve [{file_path, file_name, file_size}] solo con los OK.
    Sin normalizado ni thumbs (siguen en el plugin)."""
    out = []
    os.makedirs(dest_dir, exist_ok=True)
    for mid in (msg_ids or []):
        try:
            dest = os.path.join(dest_dir, f"msg_{int(mid)}.bin")
            got = await download_file(client, chat_id, int(mid), dest,
                                      threads=threads, progress=progress,
                                      client_type=client_type)
            if got and os.path.isfile(got):
                out.append({"file_path": got,
                            "file_name": os.path.basename(got),
                            "file_size": os.path.getsize(got)})
        except Exception as e:
            print(f"[FILE-TRANSFER] episodio msg={mid} falló: {e}", flush=True)
    return out


# ─── Rangos con seek (F2, reproductores) ─────────────────────────

async def download_range(client, chat_id, msg_id, offset: int, length: int,
                         chunk_size: int = 1024 * 1024,
                         client_type: str = None, pre_msg=None,
                         bulk_priority: int = 1) -> bytes:
    """Lee [offset, offset+length) del documento (seek arbitrario, útil para
    reproductores). Devuelve los bytes exactos (pueden ser menos al llegar a EOF).
    Telethon: GetFileRequest con offset alineado a 1KB y limit a 4096.
    Pyrofork: GetFile con offset múltiplo del limit (patrón Telethon).
    Todo GetFile/SavePart pasa por el carril bulk del servicio central."""
    if length <= 0:
        return b""
    offset = max(0, int(offset))
    ctype = _client_type(client, client_type)

    msg = pre_msg
    if msg is None:
        if ctype == "pyrogram":
            msg = await client.get_messages(int(chat_id), int(msg_id))
        else:
            entity = await client.get_entity(int(chat_id))
            msg = await client.get_messages(entity, ids=int(msg_id))
        if msg is None:
            return b""

    if ctype == "pyrogram":
        return await _pyro_range(client, msg, offset, length, chunk_size, bulk_priority)
    return await _telethon_range(client, msg, offset, length, chunk_size, bulk_priority)


def _bulk():
    """Carril bulk del servicio central (lazy import, sin ciclos)."""
    from services.telegram_service import get_telegram_service
    return get_telegram_service()


async def _telethon_range(client, msg, offset: int, length: int, chunk_size: int,
                          bulk_priority: int = 1) -> bytes:
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import InputDocumentFileLocation

    media = getattr(msg, 'media', None)
    doc = getattr(media, 'document', None) if media else None
    if not doc:
        doc = getattr(msg, 'document', None)
    if not doc:
        return b""
    location = InputDocumentFileLocation(
        id=doc.id, access_hash=doc.access_hash,
        file_reference=doc.file_reference, thumb_size='')
    # Alinear offset a 1KB y cubrir el rango con límites múltiplos de 4096.
    base = (offset // 1024) * 1024
    skip = offset - base
    need = skip + length
    step = max(4096, (min(chunk_size, 1024 * 1024) // 4096) * 4096)
    out = bytearray()
    cur = base
    gate = _bulk()
    while len(out) < need:
        lim = min(step, ((need - len(out)) // 4096 + 1) * 4096)
        await gate.bulk_acquire(bulk_priority)
        try:
            result = await asyncio.wait_for(client(GetFileRequest(location=location, offset=cur, limit=lim)),
                                            timeout=REQ_TIMEOUT)
        except Exception as e:
            if type(e).__name__ in ("FloodWaitError", "FloodWait", "FloodPremiumWait"):
                gate.bulk_flood_report(float(getattr(e, 'seconds', getattr(e, 'value', 0)) or 0))
            print(f" [TG-RANGE] GetFile offset={cur} falló: {type(e).__name__}: {str(e)[:150]}", flush=True)
            break
        finally:
            await gate.bulk_release()
        data = bytes(result.bytes or b"")
        if not data:
            break
        out += data
        cur += len(data)
        if len(data) < lim:
            break
    return bytes(out[skip:skip + length])


async def _pyro_range(client, msg, offset: int, length: int, chunk_size: int,
                      bulk_priority: int = 1) -> bytes:
    from pyrogram import raw
    from pyrogram.file_id import FileId

    doc = None
    try:
        from services.userbot_service import pyro_media as _pyro_media
        doc = _pyro_media(msg)
    except Exception:
        doc = getattr(msg, "document", None)
    if doc is None:
        try:
            _attrs = [a for a in ("document", "video", "audio", "animation", "voice", "video_note", "photo", "sticker", "media", "empty") if getattr(msg, a, None) is not None]
        except Exception:
            _attrs = ["?"]
        print(f" [PYRO-RANGE] sin documento (attrs={_attrs})", flush=True)
        return b""
    try:
        if hasattr(doc, "file_id") and getattr(doc, "file_id"):
            _fid = FileId.decode(doc.file_id)
            _mid, _ah, _fr = _fid.media_id, _fid.access_hash, _fid.file_reference
        else:
            _mid, _ah, _fr = doc.id, doc.access_hash, doc.file_reference
    except Exception:
        return b""
    location = raw.types.InputDocumentFileLocation(
        id=_mid, access_hash=_ah,
        file_reference=bytes(_fr) if _fr else b"", thumb_size="")
    # Sesión de medios del DC del fichero: el invoke directo sobre la sesión
    # principal falla con FILE_MIGRATE_X si el fichero vive en otro DC (los
    # fallos aquí eran silenciosos: break sin log y parcial vacío).
    _invoker = client
    try:
        _fdc = FileId.decode(doc.file_id).dc_id if hasattr(doc, "file_id") and getattr(doc, "file_id") else None
    except Exception:
        _fdc = None
    if _fdc:
        try:
            from services.fast_download import _get_media_session as _gms
            _ms = await _gms(client, _fdc)
            if _ms is not None:
                _invoker = _ms
        except Exception as e:
            print(f" [PYRO-RANGE] sin media session DC{_fdc} ({e}), invoke directo", flush=True)
    limit = max(4096, min(int(chunk_size or 0) or 1024 * 1024, 1024 * 1024))
    base = (offset // limit) * limit
    skip = offset - base
    need = skip + length
    out = bytearray()
    cur = base
    gate = _bulk()
    while len(out) < need:
        await gate.bulk_acquire(bulk_priority)
        try:
            result = await asyncio.wait_for(
                _invoker.invoke(raw.functions.upload.GetFile(location=location, offset=cur, limit=limit)),
                timeout=REQ_TIMEOUT)
        except Exception as e:
            if type(e).__name__ in ("FloodWaitError", "FloodWait", "FloodPremiumWait"):
                gate.bulk_flood_report(float(getattr(e, 'seconds', getattr(e, 'value', 0)) or 0))
            print(f" [PYRO-RANGE] GetFile offset={cur} falló: {type(e).__name__}: {str(e)[:120]}", flush=True)
            break
        finally:
            await gate.bulk_release()
        data = bytes(getattr(result, "bytes", b"") or b"")
        if not data:
            break
        out += data
        cur += len(data)
        if len(data) < limit:
            break
    return bytes(out[skip:skip + length])
