"""
DownloadService — servicio central de descarga secuencial (clon de TGHirayi).

Replica exactamente la funcionalidad de _parallel_download de TGHirayi:
- Descarga multi-conexión con GetFileRequest
- Sidecar .chunks para reanudación
- FileMigrate / FileReferenceExpired handling
- Reintentos y fallback

API para HLS y futuros plugins (juegos, etc.):
- download_sparse(episode_key, file_size, msg, dc_id, progress_callback=None)
  Descarga el fichero completo al sparse de forma resiliente, reanudable.
  Retorna path si completo, None si incompleto (reanudable).

Estado: velocidad, porcentaje, hasta qué byte está descargado (via sidecar/bitmap).
Control: cancel/pause/priority (Fase 2b).

El servicio serializa todas las descargas vía _HLS_DOWNLOAD_LOCK global
(ya existente en gateway) para evitar flood 429.
"""
import os
import asyncio
import time
import json
from typing import Optional

# Reutilizar directorios HLS existentes
# OJO: el gateway usa PROJECT_ROOT/data/cache (tvcat2/data/cache), NO BASE/data/cache.
# BASE = tvcat2/tvcat ; PROJECT_ROOT = tvcat2
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BASE)
_HLS_CACHE_DIR = os.path.join(_PROJECT_ROOT, "data", "cache")
HLS_BLOCK_SIZE = 512 * 1024

_jobs = {}  # episode_key -> {status, progress, speed, ...}
_lock = asyncio.Lock()


def get_status(episode_key: str) -> dict:
    """Retorna estado de descarga: {progress, speed, bytes_done, bytes_total, next_byte}."""
    return _jobs.get(episode_key, {"status": "idle", "progress": 0, "speed": 0, "bytes_done": 0, "bytes_total": 0})


def set_prefer(episode_key: str, prefer_block):
    """Re-prioriza en caliente el bloque prioritario de un job en curso (para seek)."""
    j = _jobs.get(episode_key)
    if j is not None:
        j["prefer_block"] = prefer_block


async def download_sparse(episode_key: str, file_size: int, msg, dc_id=None, progress_callback=None, prefer_block=None) -> Optional[str]:
    """Descarga el fichero completo al sparse (tvcat2/data/cache/{episode_key}.mp4).

    Clon de TGHirayi _parallel_download + prioridad por punto de reproducción:
    - `prefer_block`: bloque (512KB) del punto de reproducción/seek. Se descarga PRIMERO
      y su zona contigua, para que el reproductor pueda servir ese minuto sin esperar
      la descarga completa. Luego sigue con el resto (secuencial).
    - Usa el cliente principal + N-1 secundarios (pocos, para no saturar Telegram)
    - Divide en rangos contiguos, cada worker escribe en su offset
    - Sidecar .chunks para reanudar tras reinicio
    - Maneja FileMigrateError y FileReferenceExpiredError
    - Reintento final con cliente principal

    El fichero sparse se pre-asigna con truncate(file_size) si es nuevo.
    Si ya existe y sidecar es legible, solo descarga chunks pendientes.
    """
    # Guard anti-duplicado: si ya hay una descarga en curso para este episodio, NO lanzar otra.
    # (antes cada petición de segmento relanzaba download_sparse → decenas de descargas en
    #  paralelo abriendo conexiones → saturaba Telegram con 'Server closed'.)
    if _jobs.get(episode_key, {}).get("status") == "downloading":
        return None
    _jobs[episode_key] = {"status": "downloading", "progress": 0, "speed": 0, "bytes_done": 0, "bytes_total": file_size, "prefer_block": prefer_block}

    import asyncio as _aio
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import InputDocumentFileLocation
    from services.userbot_service import get_active_client

    ubot = await get_active_client()
    if not ubot:
        print(" [DOWNLOAD-SERVICE] No hay cliente Telegram activo")
        return None
    client = getattr(ubot, '_client', ubot)

    media = getattr(msg, 'media', None)
    doc = getattr(media, 'document', None) if media else None
    if not doc:
        doc = getattr(msg, 'document', None)
    if not doc or not getattr(doc, 'size', 0):
        print(f" [DOWNLOAD-SERVICE] {episode_key}: documento no encontrado")
        return None

    file_size = int(getattr(doc, 'size', file_size) or file_size)
    if file_size <= 0:
        return None

    location = InputDocumentFileLocation(
        id=doc.id,
        access_hash=doc.access_hash,
        file_reference=doc.file_reference,
        thumb_size=''
    )
    doc_dc = getattr(doc, 'dc_id', dc_id)

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

    # Conexiones como TGHirayi (download_threads, default 8, max 16).
    # NO satura porque solo hay 1 descarga por episodio (guard anti-duplicado + worker único).
    threads = 8
    threads = max(1, min(int(threads), 16))

    REQ_TIMEOUT = 90
    CONNECT_TIMEOUT = 15
    CHUNK = 512 * 1024

    # Clonar sesión para conexiones secundarias
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    session_string = client.session.save() if hasattr(client, 'session') else ''
    secondary = []
    for _ in range(max(0, threads - 1)):
        if not session_string:
            break
        c = TelegramClient(StringSession(session_string), client.api_id, client.api_hash)
        try:
            await asyncio.wait_for(c.connect(), timeout=CONNECT_TIMEOUT)
        except Exception:
            try:
                await c.disconnect()
            except:
                pass
            continue
        secondary.append(c)

    # Preparar fichero sparse (path espejo de HLS: tvcat2/data/cache/{key}.mp4)
    file_path = os.path.join(_HLS_CACHE_DIR, f"{episode_key}.mp4")
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    chunk_total = (file_size + CHUNK - 1) // CHUNK
    chunks_side = file_path + ".chunks"

    done = set()
    resume = False
    if os.path.isfile(file_path) and os.path.getsize(file_path) == file_size:
        try:
            with open(chunks_side, 'r', encoding='utf-8') as f:
                done = {int(x) for x in json.load(f)}
            done = {i for i in done if 0 <= i < chunk_total}
            resume = bool(done)
        except:
            done = set()
    if not resume:
        with open(file_path, 'wb') as f:
            f.truncate(file_size)
        done = set()
        try:
            os.remove(chunks_side)
        except:
            pass

    def _save_chunks():
        try:
            with open(chunks_side, 'w', encoding='utf-8') as f:
                json.dump(sorted(done), f)
        except:
            pass

    def _get_dynamic_prefer():
        # Leer el prefer_block dinámico del job (set_prefer lo actualiza en caliente para seek)
        j = _jobs.get(episode_key, {})
        return j.get("prefer_block", prefer_block)

    def _ranges():
        per = max(1, (chunk_total + threads - 1) // threads)
        ranges = []
        # 1º: rango centrado en el prefer_block dinámico (punto de reproducción) — se descarga primero
        dpb = _get_dynamic_prefer()
        if dpb is not None:
            pb = max(0, min(int(dpb), chunk_total - 1))
            start = max(0, pb - per // 2)
            end = min(chunk_total, start + per)
            if start < chunk_total:
                ranges.append((start, end))
        # 2º: resto del fichero en rangos contiguos (llenar todo)
        for s in range(0, chunk_total, per):
            e = min(s + per, chunk_total)
            to_skip = False
            if dpb is not None:
                pb0 = max(0, min(int(dpb), chunk_total-1))
                pstart = max(0, pb0 - per // 2)
                if s == pstart:
                    to_skip = True
            if not to_skip and s < chunk_total:
                ranges.append((s, e))
        return ranges

    ranges = _ranges()
    workers = secondary + [client]
    writers = workers[:len(ranges)]

    # Limitar ranges a writers disponibles
    if len(ranges) > len(writers):
        ranges = ranges[:len(writers)]

    _jobs[episode_key] = {"status": "downloading", "progress": len(done)/max(1,chunk_total)*100, "bytes_done": len(done)*CHUNK, "bytes_total": file_size}

    progress = [len(done) * CHUNK]
    lock = asyncio.Lock()
    last_save = [time.perf_counter()]
    from telethon import helpers as _tl_helpers

    async def _dl_range(c, range_start, range_end, retries=3):
        from telethon.errors.rpcerrorlist import FileMigrateError, FileReferenceExpiredError, FilerefUpgradeNeededError
        last_err = None
        migrated_sender = None
        for attempt in range(1, retries + 1):
            try:
                # Verificar conexión viva
                if hasattr(c, 'is_connected') and not c.is_connected():
                    print(f" [DOWNLOAD-SERVICE] conexión muerta rango {range_start}-{range_end}")
                    return False
                with open(file_path, 'r+b') as f:
                    for i in range(range_start, range_end):
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
                        progress[0] += len(data)
                        if progress_callback:
                            async with lock:
                                await _tl_helpers._maybe_await(progress_callback(progress[0], file_size))
                        # Actualizar estado
                        _jobs[episode_key].update({"progress": len(done)/max(1,chunk_total)*100, "bytes_done": progress[0]})
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
                except:
                    migrated_sender = None
            except (FileReferenceExpiredError, FilerefUpgradeNeededError) as e:
                last_err = repr(e)
                if not await _refresh_file_reference():
                    break
            except ConnectionError as ce:
                last_err = f"disconnect ({ce})"
                break
            except Exception as e:
                last_err = repr(e)
        _save_chunks()
        print(f" [DOWNLOAD-SERVICE] Rango {range_start}-{range_end} falló tras {retries} intentos ({last_err})")
        return False

    results = await asyncio.gather(*[
        _dl_range(writers[i], ranges[i][0], ranges[i][1])
        for i in range(len(ranges))
    ], return_exceptions=True)

    failed = [ranges[i] for i in range(len(ranges)) if results[i] is not True]
    if failed:
        for rng in failed:
            await _dl_range(client, rng[0], rng[1], retries=4)

    try:
        await asyncio.sleep(0.2)
        if len(done) >= chunk_total and os.path.isfile(file_path) and os.path.getsize(file_path) == file_size:
            try:
                os.remove(chunks_side)
            except:
                pass
            _jobs[episode_key].update({"status": "completed", "progress": 100})
            return file_path
        _save_chunks()
        _jobs[episode_key].update({"status": "partial", "progress": len(done)/max(1,chunk_total)*100})
        return None
    finally:
        # Resetear estado si no se completó (para permitir reanudar en próxima petición)
        if _jobs.get(episode_key, {}).get("status") == "downloading":
            _jobs[episode_key].update({"status": "partial", "progress": len(done)/max(1,chunk_total)*100})
        for c in secondary:
            try:
                await c.disconnect()
            except:
                pass
        # El servicio es standalone: NO actualiza el bitmap del gateway (evita import side-effects).
        # El llamador (HLS SEQ) sincronizará el bitmap con `done` vía get_status/descarga completa.
