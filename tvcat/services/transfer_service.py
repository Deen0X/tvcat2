"""TransferService — Cola de transferencias (subida/bajada) de ficheros a/desde Telegram.

Servicio CORE, único punto de acceso para transferir ficheros (principio §17 de la arquitectura).
Los plugins encolan jobs (subida/descarga) y consumen su progreso/resultado, en vez de
reinventar la conexión o la gestión de subida/bajada.

Decisiones de diseño (ver TransferService_Implementation_Plan.md):
- Cola SECUENCIAL: 1 job a la vez (no disparar llamadas a la API de Telegram).
- Clientes: userbot_service.get_active_client (Telethon/Pyrofork) con credenciales explícitas opcionales.
- Progreso por job (current/total por fase) consultable vía get_status.
- Sin UI: observación por logs de terminal [TRANSFER] y endpoints /api/transfer/* (depuración).
- Persistencia opcional por job (flag persist): serializa estado a disco para reanudar tras crash.
- Subida: <10MB send_file directo; 10MB..1.9GB _parallel_upload; >1.9GB Pyrofork.
- Descarga: <20MB download_media secuencial; >=20MB _parallel_download.
"""
import os
import json
import time
import uuid
import asyncio
from typing import Optional

_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(_DATA_DIR, exist_ok=True)

BIG_FILE_LIMIT = int(1.9 * 1024 * 1024 * 1024)     # <1.9GB Telethon, >=1.9GB Pyrofork
BIG_UPLOAD_THRESHOLD = 10 * 1024 * 1024            # <10MB send_file directo
BIG_DOWNLOAD_THRESHOLD = 20 * 1024 * 1024          # <20MB descarga secuencial
_PERSIST_FILE = os.path.join(_DATA_DIR, "transfer_jobs.json")
_MAX_HISTORY = 50

# ─── Modelo de job ────────────────────────────────────────────────

_jobs = {}          # job_id -> job dict
_queue = []         # lista ordenada de job_id pendientes (FIFO)
_worker_task = None
_worker_running = False
_current_job_id = None


def _new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def _make_job(**fields) -> dict:
    job = {
        "id": _new_job_id(),
        "type": fields.get("type", "upload"),
        "state": "queued",            # queued | running | done | error
        "phase": fields.get("phase", ""),
        "current": 0,
        "total": 0,
        "chat": fields.get("chat", ""),
        "file_name": fields.get("file_name", ""),
        "persist": bool(fields.get("persist", False)),
        "result": None,
        "error": "",
        "created": time.time(),
        "finished": None,
        "_kind": fields.get("_kind", ""),   # consumidor opcional ("cache_relay", ...)
    }
    return job


# ─── Persistencia (opcional, flag persist) ────────────────────────

def _save_persist(job: dict):
    if not job.get("persist"):
        return
    try:
        data = {}
        if os.path.isfile(_PERSIST_FILE):
            with open(_PERSIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data[job["id"]] = {k: v for k, v in job.items() if k not in ("current", "total")}
        with open(_PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[TRANSFER] Error persist: {e}", flush=True)


def _load_persisted_jobs() -> dict:
    """Reanuda jobs persistidos que quedaron 'running' tras un crash."""
    out = {}
    try:
        if not os.path.isfile(_PERSIST_FILE):
            return out
        with open(_PERSIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for jid, j in data.items():
            j["id"] = jid
            j["state"] = "queued"
            j["phase"] = ""
            out[jid] = j
        return out
    except Exception:
        return {}


# ─── API pública (para plugins) ───────────────────────────────────

async def enqueue_upload(chat, file_bytes_or_path, file_name="file.bin",
                         caption="", creds=None, on_progress=None,
                         post_process=None, persist=False, _kind="") -> dict:
    """Encola una subida. file_bytes_or_path: bytes o ruta a fichero.
    creds: {session_string, api_id, api_hash} o None (cuenta activa por defecto).
    on_progress(job) se llama en cada actualización.
    post_process(job) opcional: callback async al final (ej. pin, registro local).
    Devuelve el job (con id)."""
    job = _make_job(type="upload", chat=str(chat), file_name=file_name,
                    phase="Preparando", persist=persist, _kind=_kind)
    job["_caption"] = caption
    job["_creds"] = creds
    job["_on_progress"] = on_progress
    job["_post_process"] = post_process
    job["_payload"] = file_bytes_or_path
    job["_file_size"] = _payload_size(file_bytes_or_path)
    _jobs[job["id"]] = job
    _queue.append(job["id"])
    _log(f"Encolada subida '{file_name}' -> {chat} ({job['id']})")
    _save_persist(job)
    _ensure_worker()
    return job


async def enqueue_download(chat, msg_id, dest_path=None,
                           creds=None, on_progress=None,
                           post_process=None, persist=False, _kind="") -> dict:
    """Encola una descarga del documento msg_id del chat. dest_path: ruta destino o None (devuelve bytes).
    post_process(job) opcional: recibe el job con job['_downloaded'] = bytes (o path) al terminar.
    Devuelve el job (con id)."""
    job = _make_job(type="download", chat=str(chat), file_name=f"msg_{msg_id}",
                    phase="Preparando", persist=persist, _kind=_kind)
    job["_msg_id"] = msg_id
    job["_dest_path"] = dest_path
    job["_creds"] = creds
    job["_on_progress"] = on_progress
    job["_post_process"] = post_process
    _jobs[job["id"]] = job
    _queue.append(job["id"])
    _log(f"Encolada descarga msg={msg_id} de {chat} ({job['id']})")
    _save_persist(job)
    _ensure_worker()
    return job


async def wait_job(job_id: str, timeout: Optional[float] = None) -> dict:
    """Espera a que el job termine. Devuelve el job final."""
    start = time.time()
    while True:
        j = _jobs.get(job_id)
        if not j:
            return {}
        if j.get("state") in ("done", "error"):
            return j
        if timeout and (time.time() - start) > timeout:
            return j
        await asyncio.sleep(0.25)


async def get_status(job_id: str) -> dict:
    j = _jobs.get(job_id)
    if not j:
        return {"id": job_id, "state": "not_found"}
    return {
        "id": j["id"],
        "type": j["type"],
        "state": j["state"],
        "phase": j.get("phase", ""),
        "current": j.get("current", 0),
        "total": j.get("total", 0),
        "chat": j.get("chat", ""),
        "file_name": j.get("file_name", ""),
        "result": j.get("result"),
        "error": j.get("error", ""),
        "created": j.get("created"),
        "finished": j.get("finished"),
    }


def list_jobs() -> list:
    """Jobs activos + historial reciente (máx _MAX_HISTORY)."""
    def _snapshot(j):
        return {
            "id": j["id"],
            "type": j["type"],
            "state": j["state"],
            "phase": j.get("phase", ""),
            "current": j.get("current", 0),
            "total": j.get("total", 0),
            "chat": j.get("chat", ""),
            "file_name": j.get("file_name", ""),
            "result": j.get("result"),
            "error": j.get("error", ""),
            "created": j.get("created"),
            "finished": j.get("finished"),
        }
    items = [_snapshot(j) for j in _jobs.values()]
    items.sort(key=lambda x: x.get("created") or 0, reverse=True)
    return items[:_MAX_HISTORY]


def _payload_size(payload) -> int:
    try:
        if isinstance(payload, (bytes, bytearray)):
            return len(payload)
        if isinstance(payload, str) and os.path.isfile(payload):
            return os.path.getsize(payload)
    except Exception:
        pass
    return 0


# ─── Worker (cola secuencial) ─────────────────────────────────────

def _log(msg: str):
    print(f"[TRANSFER] {msg}", flush=True)


def _ensure_worker():
    global _worker_task, _worker_running
    if _worker_running:
        return
    _worker_running = True
    _worker_task = asyncio.get_event_loop().create_task(_worker_loop())


async def _worker_loop():
    global _worker_running, _current_job_id
    _log("Worker iniciado (cola secuencial)")
    try:
        while True:
            if not _queue:
                await asyncio.sleep(0.5)
                continue
            jid = _queue.pop(0)
            job = _jobs.get(jid)
            if not job:
                continue
            _current_job_id = jid
            try:
                await _run_job(job)
            except Exception as e:
                _log(f"Error procesando {jid}: {e}")
                job["state"] = "error"
                job["error"] = str(e)
                job["finished"] = time.time()
            _save_persist(job)
            _current_job_id = None
    except asyncio.CancelledError:
        pass
    finally:
        _worker_running = False


async def _run_job(job: dict):
    job["state"] = "running"
    _save_persist(job)
    if job["type"] == "upload":
        await _run_upload(job)
    else:
        await _run_download(job)

    # post_process (opcional)
    pp = job.get("_post_process")
    if pp:
        try:
            if asyncio.iscoroutinefunction(pp):
                await pp(job)
            else:
                pp(job)
        except Exception as e:
            _log(f"Error post_process {job['id']}: {e}")

    job["state"] = "done"
    job["finished"] = time.time()
    _log(f"Job {job['id']} completado ({job['type']})")


# ─── Subida ───────────────────────────────────────────────────────

async def _run_upload(job: dict):
    payload = job.get("_payload")
    file_name = job.get("file_name", "file.bin")
    caption = job.get("_caption", "")
    creds = job.get("_creds") or {}
    size = job.get("_file_size") or _payload_size(payload)

    client, ctype = await _get_raw_client(creds)
    if client is None:
        raise RuntimeError("No hay cliente Telegram disponible")

    # Materializar bytes si es ruta
    if isinstance(payload, str) and os.path.isfile(payload):
        with open(payload, "rb") as f:
            data = f.read()
    elif isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
    else:
        raise RuntimeError("Payload de subida no válido")

    job["total"] = size
    job["phase"] = "Subiendo"
    _log(f"Subiendo '{file_name}' ({size} bytes) a {job['chat']}")
    _save_persist(job)

    def _cb(cur, tot):
        job["current"] = cur
        job["total"] = tot
        op = job.get("_on_progress")
        if op:
            try:
                op(job)
            except Exception:
                pass
        _save_persist(job)

    msg_id = await _upload_data(client, ctype, job, data, file_name, caption, size, _cb, creds)
    job["result"] = {"ok": True, "msg_id": msg_id, "size": size}
    _save_persist(job)


async def _upload_data(client, ctype, job, data: bytes, file_name: str, caption: str,
                       size: int, progress_callback, creds: dict) -> int:
    """Sube bytes a un chat. Elige estrategia según tamaño (igual que TGHirayi)."""
    chat_id = int(job["chat"])
    entity = await client.get_entity(chat_id)

    if size < BIG_UPLOAD_THRESHOLD:
        # <10MB: send_file directo
        import io
        buf = io.BytesIO(data)
        buf.name = file_name
        if ctype == "pyrogram":
            m = await client.send_document(chat_id, buf, caption=caption or None, file_name=file_name)
        else:
            m = await client.send_file(entity, buf, caption=caption or None)
        progress_callback(size, size)
        return int(m.id)

    if size >= BIG_FILE_LIMIT:
        # >1.9GB: Pyrofork
        if ctype != "pyrogram":
            raise RuntimeError("Fichero >1.9GB requiere sesión Pyrofork")
        return await _upload_pyrofork(client, chat_id, data, file_name, caption, size, progress_callback, creds)

    # 10MB..1.9GB: parallel upload Telethon
    part_size_kb = 512
    threads = max(1, int(creds.get("upload_threads") or 4))
    tmp_path = os.path.join(_DATA_DIR, f"_transfer_up_{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        input_file = await _parallel_upload(client, tmp_path, size, threads, part_size_kb,
                                            file_name=file_name, progress_callback=progress_callback)
        m = await client.send_file(entity, input_file, caption=caption or None)
        return int(m.id)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


async def _upload_pyrofork(client, chat_id, data: bytes, file_name: str, caption: str,
                           size: int, progress_callback, creds: dict) -> int:
    """Sube >1.9GB con Pyrofork (send_document) a un path temporal."""
    tmp_path = os.path.join(_DATA_DIR, f"_transfer_up_{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        workers = int(creds.get("pyro_workers") or 16)

        def _p(cur, tot):
            progress_callback(cur, tot)

        m = await client.send_document(chat_id, tmp_path, caption=caption or None,
                                       progress=_p, file_name=file_name)
        return int(m.id)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ─── Descarga ─────────────────────────────────────────────────────

async def _run_download(job: dict):
    chat = job["chat"]
    msg_id = int(job.get("_msg_id"))
    dest_path = job.get("_dest_path")
    creds = job.get("_creds") or {}

    client, ctype = await _get_raw_client(creds)
    if client is None:
        raise RuntimeError("No hay cliente Telegram disponible")

    entity = await client.get_entity(int(chat))
    msg = await client.get_messages(entity, ids=msg_id)
    if msg is None:
        raise RuntimeError(f"Mensaje {msg_id} no encontrado")

    media = getattr(msg, 'media', None)
    doc = getattr(media, 'document', None) if media else None
    if not doc:
        raise RuntimeError(f"Mensaje {msg_id} no tiene documento")

    size = int(getattr(doc, 'size', 0) or 0)
    job["total"] = size
    job["phase"] = "Descargando"
    _save_persist(job)

    def _cb(cur, tot):
        job["current"] = cur
        job["total"] = tot
        op = job.get("_on_progress")
        if op:
            try:
                op(job)
            except Exception:
                pass
        _save_persist(job)

    data = None
    if size >= BIG_DOWNLOAD_THRESHOLD and ctype == "telethon":
        # Descarga multi-conexión (>=20MB, solo Telethon)
        tmp_path = os.path.join(_DATA_DIR, f"_transfer_dl_{uuid.uuid4().hex}.tmp")
        try:
            got = await _parallel_download(client, msg, tmp_path, threads=8, progress_callback=_cb)
            if got:
                with open(tmp_path, "rb") as f:
                    data = f.read()
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    else:
        # Descarga secuencial con progreso incremental (bytes)
        import io
        buf = io.BytesIO()
        try:
            if ctype == "pyrogram":
                await client.download_media(msg, file=buf, progress=lambda c, t: _cb(c, t or size))
            else:
                await client.download_media(msg, file=buf, progress_callback=lambda c, t: _cb(c, t or size))
            data = buf.getvalue()
        except TypeError:
            # Firma sin callback de progreso (variante) → descarga directa
            data = await client.download_media(msg, file=bytes)
        if data is not None:
            _cb(len(data), size)

    if data is None:
        raise RuntimeError(f"Fallo descargando msg {msg_id}")

    job["_downloaded"] = data
    if dest_path:
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)
        job["_downloaded"] = dest_path
    job["result"] = {"ok": True, "size": len(data)}
    _save_persist(job)


# ─── Cliente ──────────────────────────────────────────────────────

async def _get_raw_client(creds: dict):
    """Devuelve (client_raw, client_type). Resuelve el cliente activo o uno con credenciales explícitas."""
    from services import userbot_service
    if creds and creds.get("session_string"):
        sess = {
            "session_string": creds["session_string"],
            "api_id": creds.get("api_id"),
            "api_hash": creds.get("api_hash"),
            "client_type": creds.get("client_type", "telethon"),
            "workers": creds.get("pyro_workers") or 16,
        }
        ub = userbot_service.UserbotClient(sess)
        await ub.connect()
        return ub._client, sess["client_type"]

    ub = await userbot_service.get_active_client()
    if ub is None:
        return None, None
    return ub._client, getattr(ub, "_type", "telethon")


# ─── Multi-conexión (extraído de TGHirayi, comportamiento idéntico) ─

async def _parallel_download(client, msg, file_path: str, threads: int, progress_callback=None) -> Optional[str]:
    """Descarga un documento a máxima velocidad usando múltiples conexiones TCP
    independientes (patrón fast_telethon). Divide el fichero en rangos y cada conexión
    descarga su rango vía GetFileRequest, escribiendo en su offset (sin solaparse).

    - threads: nº de conexiones TCP paralelas (el client principal + N-1 secundarios).
    - Fallback: devuelve None si no se pudo; el llamador usa download_media secuencial.
    Devuelve file_path en caso de éxito."""
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import InputDocumentFileLocation

    media = getattr(msg, 'media', None)
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

    threads = max(1, min(threads, 16))

    # Clonar la sesión del cliente principal para abrir conexiones secundarias
    # al mismo DC (mismo auth_key/dc_id) sin re-login.
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    session_string = client.session.save() if hasattr(client, 'session') else ''
    secondary = []
    for _ in range(max(0, threads - 1)):
        if not session_string:
            break
        c = TelegramClient(StringSession(session_string), client.api_id, client.api_hash)
        await c.connect()
        secondary.append(c)

    # Preasignar el fichero y mantener un único handle abierto en r+b.
    helpers_dir = os.path.dirname(file_path)
    if helpers_dir:
        os.makedirs(helpers_dir, exist_ok=True)
    with open(file_path, 'wb') as f:
        f.truncate(file_size)

    CHUNK = 512 * 1024  # 512KB: límite máximo permitido por GetFileRequest

    def _ranges():
        # Repartir el fichero en 'threads' rangos contiguos (no solapados).
        chunk_total = (file_size + CHUNK - 1) // CHUNK
        per = max(1, (chunk_total + threads - 1) // threads)
        ranges = []
        for start in range(0, chunk_total, per):
            end = min(start + per, chunk_total)
            if start < chunk_total:
                ranges.append((start, end))
        return ranges

    ranges = _ranges()
    workers = secondary + [client]
    writers = workers[:len(ranges)]

    progress = [0]
    lock = asyncio.Lock()
    from telethon import helpers as _tl_helpers

    async def _dl_range(c, range_start, range_end):
        try:
            # Un único handle abierto por worker no es seguro en Windows si se comparte;
            # cada worker abre el fichero en r+b, hace seek+write en su offset.
            with open(file_path, 'r+b') as f:
                for i in range(range_start, range_end):
                    offset = i * CHUNK
                    if offset >= file_size:
                        break
                    # Se pide SIEMPRE el chunk completo (divisible por 4096). En el último
                    # tramo el servidor devuelve solo los bytes restantes.
                    req = GetFileRequest(location=location, offset=offset, limit=CHUNK)
                    result = await c(req)
                    data = bytes(result.bytes)
                    f.seek(offset)
                    f.write(data)
                    progress[0] += len(data)
                    if progress_callback:
                        async with lock:
                            await _tl_helpers._maybe_await(progress_callback(progress[0], file_size))
        except Exception as e:
            print(f"[TRANSFER] [PDL] Error en rango {range_start}-{range_end}: {e}", flush=True)
            raise

    try:
        await asyncio.gather(*[
            _dl_range(writers[i], ranges[i][0], ranges[i][1])
            for i in range(len(ranges))
        ])
    except Exception:
        # Si falla, el llamador reintentará con descarga secuencial.
        return None
    finally:
        for c in secondary:
            try:
                await c.disconnect()
            except Exception:
                pass

    if os.path.isfile(file_path) and os.path.getsize(file_path) == file_size:
        return file_path
    return None


async def _parallel_upload(client, file_path, file_size, threads, part_size_kb, file_name="video.mp4", progress_callback=None):
    """Sube un fichero >10MB a Telegram en paralelo usando SaveBigFilePartRequest,
    con múltiples conexiones TCP independientes (patrón fast_telethon).
    Cada conexión sube un subconjunto de partes de forma secuencial.
    Devuelve un InputFileBig listo para send_file (no se re-subirá)."""
    from telethon.tl.functions.upload import SaveBigFilePartRequest
    from telethon.tl.types import InputFileBig
    from telethon.helpers import generate_random_long

    part_size = int(part_size_kb * 1024)
    part_count = (file_size + part_size - 1) // part_size
    file_id = generate_random_long()

    threads = max(1, min(int(threads), 16))

    # Clonar la sesión del cliente principal para abrir conexiones secundarias
    # al mismo DC (mismo auth_key/dc_id) sin re-login.
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    session_string = client.session.save() if hasattr(client, 'session') else ''
    secondary = []
    for _ in range(max(0, threads - 1)):
        if not session_string:
            break
        c = TelegramClient(StringSession(session_string), client.api_id, client.api_hash)
        await c.connect()
        secondary.append(c)

    last_ul = [0.0]
    pos = [0]
    lock = asyncio.Lock()
    from telethon import helpers as _tl_helpers

    async def _report():
        if progress_callback:
            now = time.perf_counter()
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

    # Repartir índices de partes en 'threads' grupos contiguos
    clients = secondary + [client]
    clients = clients[:threads]
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


# ─── Instancia global ─────────────────────────────────────────────

_transfer_service = None


def get_transfer_service():
    global _transfer_service
    if _transfer_service is None:
        _transfer_service = TransferServiceFacade()
    return _transfer_service


class TransferServiceFacade:
    """Fachada que expone la API del servicio con la misma firma que las funciones del módulo.
    Permite a los plugins hacer `from services.transfer_service import get_transfer_service`."""

    async def enqueue_upload(self, *a, **kw):
        return await enqueue_upload(*a, **kw)

    async def enqueue_download(self, *a, **kw):
        return await enqueue_download(*a, **kw)

    async def wait_job(self, *a, **kw):
        return await wait_job(*a, **kw)

    async def get_status(self, *a, **kw):
        return await get_status(*a, **kw)

    def list_jobs(self):
        return list_jobs()