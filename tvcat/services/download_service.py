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
CHUNK = 512 * 1024  # bloque del sparse/sidecar (conserva formato .chunks previo)

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


_tasks = {}  # episode_key -> asyncio.Task del worker en curso


def cancel(episode_key: str) -> bool:
    """Cancela el worker en curso (al salir del player). El sidecar conserva lo
    descargado; al entrar de nuevo se reanuda (ensure → status partial)."""
    t = _tasks.get(episode_key)
    if t is not None and not t.done():
        try:
            t.cancel()
        except Exception:
            pass
    j = _jobs.get(episode_key)
    if j is not None and j.get("status") == "downloading":
        j["status"] = "partial"
    return True


async def reprioritize(episode_key: str, file_size: int, msg, dc_id=None,
                       prefer_block=None) -> bool:
    """Relanza el worker con un nuevo prefer_block (seek lejos). Cancela la tarea
    actual (el sidecar conserva lo descargado) y arranca otra que prioriza la
    nueva zona. Devuelve True si relanzó."""
    j = _jobs.get(episode_key)
    if j is not None:
        j["status"] = "partial"
    old = _tasks.get(episode_key)
    if old is not None and not old.done():
        try:
            old.cancel()
        except Exception:
            pass
    import asyncio as _aio
    t = _aio.get_running_loop().create_task(
        download_sparse(episode_key, file_size, msg, dc_id, prefer_block=prefer_block))
    _tasks[episode_key] = t
    print(f" [DOWNLOAD-SERVICE] {episode_key}: relanzado con prefer_block={prefer_block}", flush=True)
    return True


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

    import asyncio as _areg
    _me = _areg.get_running_loop().create_task(
        _download_sparse_inner(episode_key, file_size, msg, dc_id, progress_callback, prefer_block))
    _tasks[episode_key] = _me
    try:
        res = await _me
    except asyncio.CancelledError:
        # Relanzado con otro prefer (reprioritize): el sidecar conserva el progreso.
        _jobs[episode_key] = {"status": "partial", "progress": 0, "speed": 0,
                              "bytes_done": 0, "bytes_total": file_size,
                              "prefer_block": prefer_block}
        return None
    except Exception as e:
        # Que la tarea NUNCA muera en silencio con status 'downloading' (bucle
        # 503 eterno): marcar partial para que la próxima petición la relance.
        print(f" [DOWNLOAD-SERVICE] {episode_key}: ERROR {e}", flush=True)
        import traceback as _tb
        _tb.print_exc()
        _jobs[episode_key] = {"status": "partial", "progress": 0, "speed": 0,
                              "bytes_done": 0, "bytes_total": file_size,
                              "prefer_block": prefer_block}
        return None
    finally:
        if _tasks.get(episode_key) is _me:
            _tasks.pop(episode_key, None)
    # Sin resultado y todavía en 'downloading' (retorno temprano): partial para
    # no clavar el guard anti-duplicado (otra causa del 503 eterno).
    if res is None and _jobs.get(episode_key, {}).get("status") == "downloading":
        _jobs[episode_key] = {"status": "partial", "progress": 0, "speed": 0,
                              "bytes_done": 0, "bytes_total": file_size,
                              "prefer_block": prefer_block}
    return res


async def _download_sparse_inner(episode_key: str, file_size: int, msg, dc_id=None, progress_callback=None, prefer_block=None) -> Optional[str]:
    """Rellena el sparse usando el servicio central (file_transfer) con la
    librería preferida. Sin motor propio: sin clonado de sesiones ni GetFile
    directos aquí. Conserva sparse preasignado, sidecar, prefer-first, estado."""
    from services import file_transfer as _ft
    from services.userbot_service import get_active_client

    # 1. Librería preferida (ajuste global Comportamiento Telegram)
    try:
        from services.catalog_service import get_conn as _gc
        _c = _gc()
        _r = _c.execute("SELECT value FROM tvcat_settings WHERE key='telegram_client_type'").fetchone()
        _c.close()
        pref = (_r[0] if _r else None) or "telethon"
        if pref not in ("telethon", "pyrogram"):
            pref = "telethon"
    except Exception:
        pref = "telethon"

    try:
        ubot = await asyncio.wait_for(get_active_client(pref), timeout=30)
    except Exception as e:
        print(f" [DOWNLOAD-SERVICE] {episode_key}: cliente {pref} sin respuesta en 30s ({e})")
        return None
    if not ubot:
        print(f" [DOWNLOAD-SERVICE] {episode_key}: sin cliente {pref} activo")
        return None
    client = getattr(ubot, '_client', ubot)

    # 2. chat_id/msg_id del mensaje (cualquiera de las dos libs)
    chat_id, mid = _msg_chat_ids(msg)
    if not chat_id or not mid:
        print(f" [DOWNLOAD-SERVICE] {episode_key}: sin chat/msg")
        return None

    # 3. Mensaje del mismo tipo que el cliente (con timeout: sin cuelgues silenciosos)
    try:
        msg = await asyncio.wait_for(_coerce_msg(client, pref, msg, chat_id, mid), timeout=30)
    except Exception as e:
        print(f" [DOWNLOAD-SERVICE] {episode_key}: mensaje no resoluble vía {pref} en 30s ({e})")
        return None
    if msg is None:
        print(f" [DOWNLOAD-SERVICE] {episode_key}: mensaje no resoluble vía {pref}")
        return None

    # 4. Tamaño real (telethon .size / pyro .file_size)
    try:
        from services.userbot_service import pyro_media as _pm
        _med = _pm(msg) if pref == "pyrogram" else None
    except Exception:
        _med = None
    if _med is None:
        _media = getattr(msg, 'media', None)
        _med = getattr(_media, 'document', None) if _media else None
        if _med is None:
            _med = getattr(msg, 'document', None)
    file_size = int(getattr(_med, 'size', 0) or getattr(_med, 'file_size', 0) or file_size or 0)
    if file_size <= 0:
        print(f" [DOWNLOAD-SERVICE] {episode_key}: documento no encontrado")
        return None
    print(f" [DOWNLOAD-SERVICE] {episode_key}: {file_size/(1024*1024):.1f} MB vía {pref}", flush=True)

    # 5. Sparse + sidecar (igual que antes)
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
        except Exception:
            done = set()
    if not resume and os.path.isfile(file_path) and os.path.getsize(file_path) == file_size:
        # Sin sidecar (descarga completa anterior o sidecar perdido): reconstruir el
        # bitmap sondeando cada chunk (los huecos se leen como ceros; 4KB por chunk
        # basta para medios comprimidos). Resume exacto desde donde quedó.
        try:
            with open(file_path, 'rb') as _pf:
                for _i in range(chunk_total):
                    _pf.seek(_i * CHUNK)
                    if _pf.read(4096).strip(b'\x00'):
                        done.add(_i)
            if done:
                resume = True
                print(f" [DOWNLOAD-SERVICE] {episode_key}: sidecar ausente, bitmap reconstruido {len(done)}/{chunk_total} chunks, sigue descargando", flush=True)
            else:
                print(f" [DOWNLOAD-SERVICE] {episode_key}: fichero vacío, descarga desde cero", flush=True)
        except Exception as e:
            print(f" [DOWNLOAD-SERVICE] {episode_key}: sondeo falló ({e}), descarga desde cero", flush=True)
            pass
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
                json.dump(sorted(done), f)
        except Exception:
            pass

    def _get_dynamic_prefer():
        j = _jobs.get(episode_key, {})
        return j.get("prefer_block", prefer_block)

    # Orden: zona preferente primero, resto secuencial
    def _order():
        order = []
        dpb = _get_dynamic_prefer()
        if dpb is not None:
            pb = max(0, min(int(dpb), chunk_total - 1))
            start = max(0, pb - 4)
            end = min(chunk_total, start + 32)
            order += [i for i in range(start, end) if i not in done]
        order += [i for i in range(chunk_total) if i not in done and i not in order]
        return order

    _jobs[episode_key] = {"status": "downloading", "progress": len(done)/max(1,chunk_total)*100, "bytes_done": min(len(done)*CHUNK, file_size), "bytes_total": file_size}

    progress = [min(len(done) * CHUNK, file_size)]
    lock = asyncio.Lock()
    last_save = [time.perf_counter()]
    sem = asyncio.Semaphore(4)  # 4 rangos concurrentes (el central ya paraleliza dentro)

    async def _dl_chunk(i):
        async with sem:
            if i in done:
                return True
            offset = i * CHUNK
            if offset >= file_size:
                return True
            length = min(CHUNK, file_size - offset)
            try:
                data = await asyncio.wait_for(
                    _ft.download_range(client, chat_id, mid, offset, length,
                                       client_type=pref, pre_msg=msg),
                    timeout=120)
            except Exception as e:
                print(f" [DOWNLOAD-SERVICE] chunk {i} fallo: {e}", flush=True)
                return False
            if not data or len(data) < length:
                return False
            try:
                with open(file_path, 'r+b') as f:
                    f.seek(offset)
                    f.write(data)
            except Exception as e:
                print(f" [DOWNLOAD-SERVICE] chunk {i} escritura: {e}", flush=True)
                return False
            done.add(i)
            progress[0] += len(data)
            # Velocidad (media móvil de ~5s, mismo patrón que TGHirayi)
            try:
                _sj = _jobs.get(episode_key)
                if _sj is not None:
                    _now = time.perf_counter()
                    _buf = _sj.setdefault("_spd_buf", [])
                    _buf.append((_now, progress[0]))
                    while len(_buf) > 2 and (_now - _buf[0][0]) > 5.0:
                        _buf.pop(0)
                    if len(_buf) >= 2 and (_now - _buf[0][0]) >= 0.5:
                        _sj["speed"] = max(0.0, (_buf[-1][1] - _buf[0][1]) / max(_now - _buf[0][0], 0.01))
            except Exception:
                pass
            if progress_callback:
                try:
                    r = progress_callback(progress[0], file_size)
                    if asyncio.iscoroutine(r):
                        async with lock:
                            await r
                except Exception:
                    pass
            _jobs[episode_key].update({"progress": len(done)/max(1,chunk_total)*100, "bytes_done": progress[0]})
            now = time.perf_counter()
            if now - last_save[0] >= 1.0:
                last_save[0] = now
                _save_chunks()
            return True

    # Pasada 1: orden preferente. Pasada 2: reintento de pendientes.
    for _pass in (1, 2):
        order = _order()
        if not order:
            break
        results = await asyncio.gather(*[_dl_chunk(i) for i in order], return_exceptions=True)
        if all(r is True for r in results):
            break
        await asyncio.sleep(1)

    await asyncio.sleep(0.2)
    if len(done) >= chunk_total and os.path.isfile(file_path) and os.path.getsize(file_path) == file_size:
        try:
            os.remove(chunks_side)
        except Exception:
            pass
        _jobs[episode_key].update({"status": "completed", "progress": 100})
        return file_path
    _save_chunks()
    _jobs[episode_key].update({"status": "partial", "progress": len(done)/max(1,chunk_total)*100})
    return None


def _msg_chat_ids(msg):
    """Extrae (chat_id, msg_id) de un mensaje Telethon o Pyrogram."""
    mid = getattr(msg, 'id', None)
    chat = getattr(msg, 'chat', None)
    if chat is not None and getattr(chat, 'id', None) is not None:
        return int(chat.id), int(mid) if mid else None
    peer = getattr(msg, 'peer_id', None)
    if peer is not None:
        cid = getattr(peer, 'channel_id', None) or getattr(peer, 'chat_id', None)
        if cid is not None:
            return int("-100" + str(cid)) if int(cid) > 0 else int(cid), int(mid) if mid else None
    cid = getattr(msg, 'chat_id', None)
    if cid is not None:
        return int(cid), int(mid) if mid else None
    return None, int(mid) if mid else None


async def _coerce_msg(client, pref: str, msg, chat_id, mid):
    """Devuelve el mensaje en el tipo del cliente preferido (re-fetch si difiere)."""
    if pref == "pyrogram":
        if getattr(msg, 'file_id', None) is not None or getattr(msg, 'chat', None) is not None:
            return msg
        try:
            m = await client.get_messages(int(chat_id), int(mid))
            return m[0] if isinstance(m, list) else m
        except Exception:
            return None
    # telethon
    if getattr(getattr(msg, 'media', None), 'document', None) is not None and hasattr(msg, 'peer_id'):
        return msg
    try:
        ent = await client.get_entity(int(chat_id))
        return await client.get_messages(ent, ids=int(mid))
    except Exception:
        return None
