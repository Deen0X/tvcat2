"""
TGHirayi — Plugin de copia de contenidos a canales Telegram
======================================================================
Plugin tipo 'player' (applies_to: '*') que copia títulos completos
(cover + episodios) a canales Telegram destino, descargando y re-subiendo
para generar nuevos file_ids.

- Copia cover (mensajes hasta 1er adjunto) con texto, formato e imágenes.
- Copia contenido (mensajes con adjuntos): descarga 1 vez, sube a N destinos.
- Topologías: 1 (chat lineal), 2 (topic fijo), 3 (topic = nombre del título).
- Forward opcional desde 1er destino a los demás.
- Worker persistente que inicia en PAUSA (configurable).
"""

import os
import json
import time
import uuid
import re
import random
import asyncio
import logging
import subprocess
import threading
from collections import deque
from typing import Optional, List, Dict
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("TGHirayi_v2")
router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(_DATA_DIR, "TGHirayi_v2.json")
CONFIG_FILE = os.path.join(_DATA_DIR, "config.json")

# Caché de ficheros descargados/normalizados por episodio (reutilizable si falla la subida)
_CACHE_DIR = os.path.join(_DATA_DIR, "cache")
os.makedirs(_CACHE_DIR, exist_ok=True)

# ─── Worker global ────────────────────────────────────────────────
_worker_task: Optional[asyncio.Task] = None
_worker_paused = True  # Inicia en pausa
_worker_running = False
_worker_gen = 0  # generacion para evitar race condition
_current_job: Optional[dict] = None

# Registro del proceso ffmpeg en curso (recodificación). Un solo encode activo a la vez
# (slot de procesado de archives); permite matarlo desde la API con confirmación.
_encode_proc_registry: dict = {}

# ─── Slot de procesado de ARCHIVES en segundo plano ───────────────
# 1 slot: extraer+recodificar un archive corre como asyncio.Task independiente del
# worker secuencial. Solo uno a la vez (evitar 2 ffmpeg pesados simultáneos).
_archive_slot_lock = asyncio.Lock()
_archive_slot_owner: Optional[str] = None   # job_id del archive en processing
_archive_tasks: Dict[str, asyncio.Task] = {}  # job_id -> task en background

# ─── Log de consola por job (vista "terminal" de archives en la UI) ──
_job_logs: Dict[str, deque] = {}
_JOB_LOG_MAX = 800  # líneas retenidas por job

def _job_log(job_id, msg):
    """Registra una línea en el log del job (buffer en memoria) y la imprime en consola.
    Alimenta la vista 'terminal' de la cola para jobs de tipo ARCHIVE."""
    try:
        buf = _job_logs.setdefault(str(job_id), deque(maxlen=_JOB_LOG_MAX))
        buf.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    except Exception:
        pass
    print(msg, flush=True)


# ─── Silenciar el ruido de Pyrogram por updates inválidos (stories/pers) ──
# Pyrogram 2.3.x lanza un traceback en el dispatcher cuando un update de mensaje
# referencia un peer ya no disponible (p.ej. una story de un chat eliminado), y lo
# vuelve a repetir con cada update/worker. Ese fallo ocurre DURANTE el parsing del
# mensaje (Message._parse → MessageStory._parse → resolve_peer), antes de llegar a
# ningún handler, por lo que no se puede filtrar con filtros ni ErrorHandler.
# Solución: envolver Message._parse para que un fallo de parsing descarte el mensaje
# (None) en lugar de propagar la excepción al dispatcher.
try:
    from pyrogram.types import Message as _SafePyroMessage
    import functools as _functools

    _pyro_message_parse_orig = _SafePyroMessage._parse

    @_functools.wraps(_pyro_message_parse_orig)
    async def _safe_pyro_message_parse(client, message, users, chats, topics=None,
                                       is_scheduled=False, business_connection_id=None,
                                       replies=1):
        try:
            return await _pyro_message_parse_orig(client, message, users, chats,
                                                  topics=topics, is_scheduled=is_scheduled,
                                                  business_connection_id=business_connection_id,
                                                  replies=replies)
        except Exception:
            return None

    _SafePyroMessage._parse = staticmethod(_safe_pyro_message_parse)
except Exception:
    pass


# Estados terminales de un job (el worker nunca los vuelve a recoger).
# 'skipped' = título saltado por no tener cover válido en el origen.
_TERMINAL_STATUSES = ("completed", "error", "skipped")

# Subcadenas de error transitorio de cliente (merecen reintento del episodio
# con refresh + backoff en vez de abortar el job).
_TRANSIENT_CLIENT_ERRORS = (
    "has not been started", "not connected", "closed database",
    "storage pyro no disponible", "Connection lost", "ConnectionError",
    "socket", "Server closed", "Timeout", "Timed out",
)

# Firmas de sesión muerta/invalidada (NO reintentar: hay que regenerar sesión).
# Incluye nuestro marcador interno TGSESSION_DEAD.
_AUTH_DEAD_MARKERS = (
    "TGSESSION_DEAD",
    "two different IP",
    "authorization key",
    "AuthKey",
    "SESSION_REVOKED",
    "SessionRevoked",
    "unregistered",
    "SESSION_PASSWORD_NEEDED",
)


def _is_auth_dead(text) -> bool:
    try:
        _t = str(text or "")
        return any(k in _t for k in _AUTH_DEAD_MARKERS)
    except Exception:
        return False

# Topic compartido de colecciones en destinos topo 3: evita colisionar con el
# topic de un título homónimo. El escaneo colapsa por serial (última gana).
_COLLECTIONS_TOPIC = "TVCat Collections"

# F3 FastUpload: sonda de sesión Pyrofork (None=sin probar, True/False=resultado).
# Evita 12s de wait_for por episodio cuando no hay sesión pyro configurada.
_PYRO_FAST_OK = None

# ─── Suavizado de velocidad (media móvil) ─────────────────────────
_SMOOTH_WINDOW = 5  # nº de muestras para la media móvil de velocidad

# Límite de subida de Telegram (4000 MiB por fichero). Por encima hay que recodificar.
_MAX_UPLOAD_MIB = int(4000 * 1024 * 1024)

# Preset de libx265 para la recodificación. Los presets se adaptan a cualquier CPU
# (escalan el nº de hebras y la velocidad): "faster" equilibra calidad/tiempo tanto
# en equipos potentes como en contenedores Docker con CPU modestas.
_X265_PRESET = "faster"

def _speed_sample(state: dict, current: float) -> Optional[float]:
    """Velocidad instantánea (bytes/s) y media móvil de _SMOOTH_WINDOW muestras.
    Devuelve None si no ha pasado el intervalo mínimo (0.5s). El estado se
    reutiliza por dirección (descarga/subida) para suavizar los picos."""
    now = time.perf_counter()
    dt = now - state["last_t"]
    if dt < 0.5:
        return None
    speed = (current - state["last_bytes"]) / dt if dt > 0 else 0.0
    state["last_bytes"] = current
    state["last_t"] = now
    state.setdefault("buf", deque(maxlen=_SMOOTH_WINDOW)).append(speed)
    buf = state["buf"]
    return sum(buf) / len(buf)


# ─── Modelos ──────────────────────────────────────────────────────
class DestinationCreate(BaseModel):
    name: str
    link: str
    topology: int = 1
    topic_id: Optional[int] = None


class DestinationUpdate(BaseModel):
    name: Optional[str] = None
    link: Optional[str] = None
    topology: Optional[int] = None
    topic_id: Optional[int] = None


class ConfigUpdate(BaseModel):
    delay_seconds: Optional[float] = None
    resume_on_startup: Optional[bool] = None
    credential_name: Optional[str] = None
    upload_threads: Optional[int] = None       # Hilos subida (Telethon paralelo / workers fast pyro)
    pyro_workers: Optional[int] = None         # Workers de red Pyrofork (>2GB)
    download_threads: Optional[int] = None     # Hilos descarga (fast pyro N GetFile / Telethon paralelo)
    download_chunk_size_kb: Optional[int] = None
    real_copy_if_owner: Optional[bool] = None   # CB1: si el origen es del usuario → copia real en destino 1
    real_copy_rest: Optional[bool] = None       # CB2: copia real en el resto (solo si hay primera copia real)
    forward_third_party: Optional[bool] = None  # OCULTO: forward Telegram directo aunque el origen sea de terceros (bypass firewall de baneo)
    normalize_mp4: Optional[bool] = None        # Normalizador MP4 (activar/desactivar)
    streaming_mkv: Optional[bool] = None        # Subir MKV en modo streaming (sin re-encode; prioridad sobre normalize_mp4)
    extract_archives: Optional[bool] = None     # Extraer archives automáticamente
    archive_passwords: Optional[List[str]] = None  # Diccionario global de contraseñas
    seven_zip_path: Optional[str] = None        # Ruta personalizada a 7z
    unrar_path: Optional[str] = None            # Ruta personalizada a unrar
    archive_parallel: Optional[bool] = None     # Procesar archives en paralelo (opción B)
    download_parallel: Optional[bool] = None    # Descargar ep.N+1 mientras se sube ep.N (OFF = secuencial: toda la velocidad a una fase)
    max_pending_archives: Optional[int] = None  # Máx. archives en processing/ready_upload (esperando subir)
    default_audio_lang: Optional[str] = None    # Idioma audio por defecto para jobs nuevos (vacío = original)
    default_sub_lang: Optional[str] = None      # Idioma subs por defecto para jobs nuevos (vacío = ninguno)
    skip_if_exists_topo3: Optional[bool] = None  # Omitir si existe en destino (solo topología 3)
    topics_cache_ttl_min: Optional[int] = None   # TTL caché de topics en minutos


class TestLink(BaseModel):
    link: str


class QueueAdd(BaseModel):
    item_id: str
    title: str
    category: str = ""
    subcategory: str = ""
    destination_ids: List[str]
    total_episodes: int = 0
    telegram_link: str = ""  # Link al mensaje origen (título de la cola abre aquí)
    audio_lang: str = ""   # Código ISO pista de audio preferida (vacío = original)
    sub_lang: str = ""     # Código ISO subtítulos (vacío = ninguno; si se indica, se queman)
    skip_if_exists_topo3: Optional[bool] = None  # Por job (None = default de config)


class QueueNormUpdate(BaseModel):
    audio_lang: Optional[str] = None   # Código ISO pista de audio (normalización MP4; vacío = original)
    sub_lang: Optional[str] = None     # Código ISO subtítulos (normalización MP4; vacío = ninguno)


class QueueReorder(BaseModel):
    direction: str  # 'up', 'down', 'top', 'bottom'


class QueuePauseToggle(BaseModel):
    paused: bool


class QueueDestinationsUpdate(BaseModel):
    destination_ids: List[str]


class NextEpisodeUpdate(BaseModel):
    next_episode: int


# ─── Persistencia ─────────────────────────────────────────────────
_DB_LOCK = threading.Lock()  # acceso a DB_FILE seguro desde hilos (recodificación en background)

def _load_db():
    with _DB_LOCK:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"destinations": {}, "queue": [], "job_id_counter": 0}


def _save_db(db):
    with _DB_LOCK:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)


def _persist_job(job: dict):
    """Persiste SOLO el job indicado recargando la DB desde disco.
    Evita que el worker pise borrados/eliminaciones hechas vía API en otros jobs.
    Atómico bajo _DB_LOCK para no corromper DB_FILE con escritores concurrentes."""
    # Campos EDITABLES desde la UI (vía API) que el worker NO toca durante el
    # procesado: si persisted, preserva el valor de disco (que es el más reciente)
    # en lugar de pisarlo con la copia en memoria del worker.
    keep_disk = ("audio_lang", "sub_lang", "next_episode", "cover_text", "destination_ids",
                 "telegram_link", "use_enricher_cover", "enrich_details")
    with _DB_LOCK:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    db = json.load(f)
            except Exception:
                db = None
        else:
            db = None
        if db is None:
            db = {"destinations": {}, "queue": [], "job_id_counter": 0}
        queue = db.get("queue", [])
        for i, j in enumerate(queue):
            if j.get("id") == job.get("id"):
                merged = dict(job)
                for k in keep_disk:
                    if k in j:
                        merged[k] = j[k]
                queue[i] = merged
                break
        else:
            return  # El job ya no existe en la cola (fue eliminado) → no re-crearlo
        db["queue"] = queue
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)


def _load_config():
    cfg = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    defaults = {
        "delay_seconds": 3.0,
        "resume_on_startup": False,
        "credential_name": "",
        "upload_threads": 4,
        "pyro_workers": 16,
        "download_threads": 8,
        "download_chunk_size_kb": 1024,
        "real_copy_if_owner": False,
        "real_copy_rest": False,
        "forward_third_party": False,
        "normalize_mp4": False,
        "streaming_mkv": False,
        "extract_archives": True,
        "archive_passwords": [],
        "seven_zip_path": "",
        "unrar_path": "",
        "archive_parallel": True,
        "download_parallel": False,
        "max_pending_archives": 5,
        "default_audio_lang": "",
        "default_sub_lang": "",
        "skip_if_exists_topo3": False,
        "topics_cache_ttl_min": 60,
    }
    if isinstance(cfg, dict):
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        return cfg
    return defaults


def _save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _session_user(request: Request):
    from tvcat.services.auth_service import get_session
    token = request.cookies.get("tvcat_session", "")
    s = get_session(token) if token else None
    if not s:
        return None
    return {"user_id": s["user_id"], "role": s.get("role", "user")}


def _get_base_url(request: Request) -> str:
    cfg = _load_config()
    if cfg.get("public_url"):
        return cfg["public_url"].rstrip("/")
    host = request.headers.get("host", "localhost")
    return f"http://{host}"


def _extract_channel_id(link: str) -> Optional[str]:
    """Extrae channel_id de un telegram_link. Igual que el reproductor.
    https://t.me/c/3953846405/12345 -> -1003953846405"""
    if not link:
        return None
    import re
    m = re.search(r't\.me/c/(\d+)/(\d+)', link)
    if not m:
        return None
    raw = m.group(1)
    if len(raw) <= 13 and not raw.startswith("-100"):
        return "-100" + raw
    return raw


# ─── Helpers de Telegram (TODO por el servicio central) ──────────
# Regla: NINGUNA llamada a las APIs de Telegram fuera de
# services/telegram_service (control exclusivo). El plano de control usa sus
# operaciones (throttle+cola); el bulk usa services/file_transfer.

def _svc():
    from tvcat.services.telegram_service import get_telegram_service
    return get_telegram_service()


def _svc_creds(job: dict = None) -> dict:
    """Credenciales de la sesión elegida en la config (o defecto del servicio)."""
    try:
        name = (_load_config().get("credential_name") or "").strip()
    except Exception:
        name = ""
    if name:
        try:
            from tvcat.services.userbot_service import get_session_by_name
            s = get_session_by_name(name, "telethon")
            if s and s.get("session_string"):
                return {"tg_user_id": s.get("tg_user_id"),
                        "client_type": "telethon",
                        "session_string": s.get("session_string"),
                        "api_id": s.get("api_id"), "api_hash": s.get("api_hash")}
        except Exception:
            pass
    return {"client_type": "telethon"}


async def _get_telegram_client():
    """LEGACY (solo bulk local que aún no migra): NO usar en código nuevo."""
    from tvcat.services.userbot_service import get_active_client
    wrapper = await get_active_client("telethon")
    if not wrapper:
        raise ValueError("No se pudo obtener cliente Telethon")
    # UserbotClient._client es el TelegramClient subyacente
    raw = getattr(wrapper, '_client', wrapper)
    if not raw:
        raise ValueError("El cliente no expone _client")
    print("[TGHirayi_v2] Cliente obtenido del pool", flush=True)
    return raw


async def _get_pyrogram_client():
    """Obtiene un cliente Pyrogram del pool de userbot_service.
    v2: SIN reconexión forzada por `workers` (ese ajuste solo dimensiona el
    pool de handlers de pyrofork, irrelevante para los fast paths; y el
    disconnect cerraba el storage sqlite mientras otra tarea —prefetch y subida
    van en paralelo— usaba el mismo cliente → 'Cannot operate on a closed
    database'). El pool ya gestiona la (re)conexión de forma centralizada."""
    from tvcat.services.userbot_service import get_active_client
    wrapper = await get_active_client("pyrogram")
    if not wrapper:
        raise ValueError("No se pudo obtener cliente Pyrogram")
    raw = getattr(wrapper, '_client', wrapper)
    if not raw:
        raise ValueError("El cliente Pyrogram no expone _client")
    return raw


async def _refresh_pyrogram_client():
    """Reconecta el wrapper pyro del pool y devuelve el raw fresco.
    Solo para paths de fallo (cliente muerto). Si el cliente sigue vivo, no se
    toca (desconectar mataría el storage bajo otras tareas en vuelo)."""
    from tvcat.services.userbot_service import get_active_client
    wrapper = await get_active_client("pyrogram")
    if not wrapper:
        raise ValueError("No se pudo obtener cliente Pyrogram")
    try:
        raw = getattr(wrapper, '_client', None)
        alive = False
        try:
            alive = bool(raw is not None and await raw.is_connected())
        except Exception:
            alive = False
        if not alive:
            try:
                await wrapper.disconnect()
            except Exception:
                pass
            try:
                wrapper.session_data["workers"] = int((_load_config().get("pyro_workers", 16) or 16))
            except Exception:
                pass
            await wrapper.connect()
            raw = getattr(wrapper, '_client', wrapper)
    except Exception:
        pass
    raw = getattr(wrapper, '_client', wrapper)
    if not raw:
        raise ValueError("El cliente Pyrogram no expone _client")
    print(f"[TGHirayi_v2] Cliente Pyrogram refrescado", flush=True)
    return raw


def list_sessions_raw():
    """Lista todas las sesiones disponibles."""
    import sqlite3
    from tvcat.services.userbot_service import DB_PATH
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT s.*, u.name as tg_name FROM userbot_sessions s
            LEFT JOIN telegram_users u ON u.tg_user_id = s.tg_user_id
            ORDER BY s.is_active DESC, s.id
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _parse_channel_link(link: str) -> dict:
    """Parsea un enlace de Telegram para extraer channel_id, topic_id y msg_id.
    Formatos:
      https://t.me/c/123456789/12345               (canal, msg)
      https://t.me/c/123456789/12345?thread=67890   (canal, msg, topic en query)
      https://t.me/c/123456789/1213/1214            (canal, topic, msg)
      https://t.me/nombre/12345                     (canal por username, msg)
    """
    result = {"channel_id": None, "topic_id": None, "msg_id": None}
    if not link:
        return result
    import re

    # Formato: t.me/c/ID/A/B  (3 segmentos numéricos: canal, topic, msg)
    m = re.search(r't\.me/c/(\d+)/(\d+)/(\d+)', link)
    if m:
        raw_id = m.group(1)
        result["channel_id"] = int("-100" + raw_id) if len(raw_id) <= 13 else int(raw_id)
        result["topic_id"] = int(m.group(2))
        result["msg_id"] = int(m.group(3))
        return result

    # Formato: t.me/c/ID/X  (2 segmentos: canal, msg)
    m = re.search(r't\.me/c/(\d+)/(\d+)', link)
    if m:
        raw_id = m.group(1)
        result["channel_id"] = int("-100" + raw_id) if len(raw_id) <= 13 else int(raw_id)
        result["msg_id"] = int(m.group(2))
        # Buscar thread/topic en la URL (?thread=)
        thread = re.search(r'[?&]thread=(\d+)', link)
        if thread:
            result["topic_id"] = int(thread.group(1))
        return result

    # Formato: t.me/nombre/X
    m = re.search(r't\.me/([a-zA-Z0-9_]+)/(\d+)', link)
    if m:
        result["channel_id"] = m.group(1)
        result["msg_id"] = int(m.group(2))
        thread = re.search(r'[?&]thread=(\d+)', link)
        if thread:
            result["topic_id"] = int(thread.group(1))
        return result
    return result


async def _resolve_channel_info(client, channel_id, job: dict = None) -> dict:
    """Obtiene información del canal vía servicio central: title, has_topics, etc."""
    try:
        svc = _svc()
        creds = _svc_creds(job)
        ent = await svc.get_entity(channel_id, **creds)
        has_topics = False
        try:
            topics = await svc.list_forum_topics(channel_id, **creds)
            has_topics = bool(topics)
        except Exception:
            pass
        return {
            "title": (ent or {}).get("title") or str(channel_id),
            "has_topics": has_topics,
            "channel_id": str((ent or {}).get("id") or channel_id),
        }
    except Exception as e:
        raise ValueError(f"No se pudo resolver el canal: {e}")


# ─── Endpoints de Configuración ───────────────────────────────────
@router.get("/api/telegram-copy-v2/config")
async def get_config(request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    cfg = _load_config()
    sessions = list_sessions_raw()
    return {
        "config": cfg,
        "sessions": [{"name": s["name"], "tg_name": s.get("tg_name", ""), "is_active": s.get("is_active", 0)} for s in sessions],
        "worker_paused": _worker_paused,
        "worker_running": _worker_running,
    }


@router.post("/api/telegram-copy-v2/config")
async def update_config(body: ConfigUpdate, request: Request):
    session = _session_user(request)
    if not session or session["role"] != "admin":
        raise HTTPException(403, "Solo admin")
    cfg = _load_config()
    if body.delay_seconds is not None:
        cfg["delay_seconds"] = max(0.5, min(5.0, body.delay_seconds))
    if body.resume_on_startup is not None:
        cfg["resume_on_startup"] = body.resume_on_startup
    if body.credential_name is not None:
        cfg["credential_name"] = body.credential_name
    if body.upload_threads is not None:
        cfg["upload_threads"] = max(1, min(16, body.upload_threads))
    if body.pyro_workers is not None:
        cfg["pyro_workers"] = max(1, min(64, body.pyro_workers))
    if body.download_threads is not None:
        cfg["download_threads"] = max(1, min(16, body.download_threads))
    if body.download_chunk_size_kb is not None:
        cfg["download_chunk_size_kb"] = max(64, min(4096, body.download_chunk_size_kb))
    if body.real_copy_if_owner is not None:
        cfg["real_copy_if_owner"] = body.real_copy_if_owner
    if body.real_copy_rest is not None:
        cfg["real_copy_rest"] = body.real_copy_rest
    if body.forward_third_party is not None:
        cfg["forward_third_party"] = bool(body.forward_third_party)
        # Al activar el forward oculto se fuerzan ambos CBs a OFF (condición de activación)
        if cfg["forward_third_party"]:
            cfg["real_copy_if_owner"] = False
            cfg["real_copy_rest"] = False
    # Exclusión mutua: marcar cualquier CB desactiva el forward oculto
    if cfg.get("real_copy_if_owner") or cfg.get("real_copy_rest"):
        cfg["forward_third_party"] = False
    if body.normalize_mp4 is not None:
        cfg["normalize_mp4"] = body.normalize_mp4
    if body.streaming_mkv is not None:
        cfg["streaming_mkv"] = body.streaming_mkv
    if body.extract_archives is not None:
        cfg["extract_archives"] = body.extract_archives
    if body.archive_passwords is not None:
        cfg["archive_passwords"] = [p for p in body.archive_passwords if p and p.strip()]
    if body.seven_zip_path is not None:
        cfg["seven_zip_path"] = (body.seven_zip_path or "").strip()
    if body.unrar_path is not None:
        cfg["unrar_path"] = (body.unrar_path or "").strip()
    if body.archive_parallel is not None:
        cfg["archive_parallel"] = bool(body.archive_parallel)
    if body.download_parallel is not None:
        cfg["download_parallel"] = bool(body.download_parallel)
    if body.max_pending_archives is not None:
        cfg["max_pending_archives"] = max(1, min(50, body.max_pending_archives))
    if body.default_audio_lang is not None:
        cfg["default_audio_lang"] = (body.default_audio_lang or "").strip()
    if body.default_sub_lang is not None:
        cfg["default_sub_lang"] = (body.default_sub_lang or "").strip()
    if body.skip_if_exists_topo3 is not None:
        cfg["skip_if_exists_topo3"] = bool(body.skip_if_exists_topo3)
    if body.topics_cache_ttl_min is not None:
        cfg["topics_cache_ttl_min"] = max(5, min(1440, int(body.topics_cache_ttl_min)))
    _save_config(cfg)
    return {"ok": True}


# ─── Test de conexion ─────────────────────────────────────────────
@router.post("/api/telegram-copy-v2/destinations/test")
async def test_destination_link(body: TestLink, request: Request):
    """Prueba un link de destino: parsea, resuelve canal y devuelve info."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    parsed = _parse_channel_link(body.link)
    if not parsed["channel_id"]:
        raise HTTPException(400, "Link de canal invalido")
    try:
        info = await _resolve_channel_info(None, parsed["channel_id"])
        return {
            "ok": True,
            "channel_id": str(parsed["channel_id"]),
            "topic_id": parsed.get("topic_id"),
            "msg_id": parsed.get("msg_id"),
            "channel_title": info["title"],
            "has_topics": info["has_topics"],
        }
    except Exception as e:
        raise HTTPException(400, f"No se pudo conectar al canal: {e}")


# ─── Endpoints de Destinos ────────────────────────────────────────
@router.get("/api/telegram-copy-v2/destinations")
async def list_destinations(request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    result = []
    for did, d in db.get("destinations", {}).items():
        if session["role"] == "admin" or d.get("user_id") == session["user_id"]:
            d["id"] = did
            result.append(d)
    return {"destinations": result}


@router.post("/api/telegram-copy-v2/destinations")
async def create_destination(body: DestinationCreate, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    if session["role"] != "admin":
        raise HTTPException(403, "Solo admin")

    parsed = _parse_channel_link(body.link)
    if not parsed["channel_id"]:
        raise HTTPException(400, "Link de canal invalido. Pega un enlace a un mensaje del canal destino.")

    # Resolver info del canal vía servicio central
    try:
        info = await _resolve_channel_info(None, parsed["channel_id"])
    except Exception as e:
        raise HTTPException(400, f"No se pudo resolver el canal: {e}")

    if body.topology == 2 and not body.topic_id and not parsed.get("topic_id"):
        raise HTTPException(400, "Topologia 2 requiere un topic ID. Pega la URL de un mensaje dentro del topic destino.")

    # Usar topic_id del body o del parse
    effective_topic_id = body.topic_id or parsed.get("topic_id")

    db = _load_db()
    did = uuid.uuid4().hex[:12]
    db["destinations"][did] = {
        "name": body.name,
        "link": body.link,
        "channel_id": str(parsed["channel_id"]),
        "topic_id": effective_topic_id,
        "msg_id": parsed["msg_id"],
        "topology": body.topology,
        "channel_title": info["title"],
        "has_topics": info["has_topics"],
        "user_id": session["user_id"],
        "created": time.time(),
    }
    _save_db(db)
    return {"ok": True, "id": did, "channel_info": info}


@router.put("/api/telegram-copy-v2/destinations/{did}")
async def update_destination(did: str, body: DestinationUpdate, request: Request):
    session = _session_user(request)
    if not session or session["role"] != "admin":
        raise HTTPException(403, "Solo admin")
    db = _load_db()
    if did not in db["destinations"]:
        raise HTTPException(404, "Destino no encontrado")
    d = db["destinations"][did]
    if body.name is not None:
        d["name"] = body.name
    if body.link is not None:
        parsed = _parse_channel_link(body.link)
        if not parsed["channel_id"]:
            raise HTTPException(400, "Link invalido")
        d["link"] = body.link
        d["channel_id"] = str(parsed["channel_id"])
        d["topic_id"] = parsed["topic_id"]
        d["msg_id"] = parsed["msg_id"]
    if body.topology is not None:
        d["topology"] = body.topology
    if body.topic_id is not None:
        d["topic_id"] = body.topic_id
    _save_db(db)
    return {"ok": True}


@router.delete("/api/telegram-copy-v2/destinations/{did}")
async def delete_destination(did: str, request: Request):
    session = _session_user(request)
    if not session or session["role"] != "admin":
        raise HTTPException(403, "Solo admin")
    db = _load_db()
    if did not in db["destinations"]:
        raise HTTPException(404, "Destino no encontrado")
    del db["destinations"][did]
    _save_db(db)
    return {"ok": True}


# ─── Endpoints de Cola ────────────────────────────────────────────
@router.get("/api/telegram-copy-v2/queue")
async def list_queue(request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    current = _get_current_job()
    # Backfill: jobs sin flag skip (anteriores) heredan el default de config.
    try:
        _skip_def = bool(_load_config().get("skip_if_exists_topo3", False))
        _skip_changed = False
        for _j in db.get("queue", []):
            if "skip_if_exists_topo3" not in _j:
                _j["skip_if_exists_topo3"] = _skip_def
                _skip_changed = True
        if _skip_changed:
            _save_db(db)
    except Exception:
        pass
    # Backfill: jobs antiguos sin telegram_link lo recuperan del catálogo (una sola vez)
    _changed = False
    for _j in db.get("queue", []):
        if not _j.get("telegram_link"):
            _item = _fetch_item_data_sync(_j.get("item_id", ""))
            _link = (_item or {}).get("telegram_link", "") or ""
            if _link:
                _j["telegram_link"] = _link
                _changed = True
    if _changed:
        _save_db(db)
    # Backfill: jobs pendientes sin is_archive definido lo detectan (mismo criterio runtime).
    # Así el tag ARCHIVE aparece en la cola sin esperar a que el worker procese el job.
    _arch_changed = False
    for _j in db.get("queue", []):
        if "is_archive" not in _j and _j.get("status") not in _TERMINAL_STATUSES:
            try:
                _j["is_archive"] = _detect_archive_job(_j, _fetch_episodes_sync(_j.get("item_id", "")))
                _arch_changed = True
            except Exception:
                _j["is_archive"] = False
                _arch_changed = True
    if _arch_changed:
        _save_db(db)
    if current and not current.get("telegram_link"):
        _item = _fetch_item_data_sync(current.get("item_id", ""))
        _link = (_item or {}).get("telegram_link", "") or ""
        if _link:
            current["telegram_link"] = _link
            _persist_job(current)
    # Enriquecer current con datos de destinos
    if current and current.get("destination_ids"):
        dests = []
        for did in current["destination_ids"]:
            d = db.get("destinations", {}).get(did, {})
            dests.append({
                "id": did,
                "name": d.get("name", did),
                "uploaded": current.get("_uploaded_to", {}).get(did, False)
            })
        current = {**current, "destinations_detail": dests}
    return {
        "queue": db.get("queue", []),
        "current_job": current,
        "worker_paused": _worker_paused,
        "worker_running": _worker_running,
        "pending_archives": len(_count_pending_archives(db.get("queue", []))),
        "pending_archives_info": _pending_archives_info(db.get("queue", [])),
        "archive_slot_owner": _archive_slot_owner,
        "encode_job_id": _encode_proc_registry.get("job_id"),
        "encode_active": (_encode_proc_registry.get("proc") is not None
                          and _encode_proc_registry["proc"].poll() is None),
    }


@router.post("/api/telegram-copy-v2/queue")
async def add_to_queue(body: QueueAdd, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    db["job_id_counter"] = db.get("job_id_counter", 0) + 1
    # Idioma audio/subs por defecto de la configuración (sección streaming MKV):
    # si el add no especifica uno, el job toma estos valores.
    _cfg = _load_config()
    _def_audio = (_cfg.get("default_audio_lang") or "").strip()
    _def_sub = (_cfg.get("default_sub_lang") or "").strip()
    job = {
        "id": str(db["job_id_counter"]),
        "item_id": body.item_id,
        "title": body.title,
        "telegram_link": (body.telegram_link or "").strip(),
        "category": body.category,
        "subcategory": body.subcategory,
        "destination_ids": body.destination_ids,
        "skip_if_exists_topo3": bool(body.skip_if_exists_topo3) if body.skip_if_exists_topo3 is not None else bool(_cfg.get("skip_if_exists_topo3", False)),
        "total_episodes": body.total_episodes,
        "priority": len(db.get("queue", [])),  # Al final
        "paused": False,
        "status": "queued",
        "progress": 0.0,
        "download_progress": 0.0,
        "upload_progress": 0.0,
        "status_text": "En cola",
        "current_episode": 0,
        "current_destination": 0,
        "audio_lang": (body.audio_lang or "").strip() or _def_audio,
        "sub_lang": (body.sub_lang or "").strip() or _def_sub,
        "cover_text": "",
        "use_enricher_cover": True,
        "user_id": session["user_id"],
        "created": time.time(),
    }
    # 2026-09-04: sembrar cover editado en local (enricher) al encolar.
    try:
        _seed_job_cover_from_local(job)
    except Exception:
        pass
    db.setdefault("queue", []).append(job)
    # Detección temprana de tipo ARCHIVE: así la UI muestra el tag nada más añadir el job,
    # sin esperar a que el worker procese. Usa el mismo criterio del procesado.
    try:
        _eps = _fetch_episodes_sync(job["item_id"])
        job["is_archive"] = _detect_archive_job(job, _eps)
        if job["is_archive"]:
            print(f"[TGHirayi_v2] Job {job['id']} añadido como ARCHIVE ({len(_eps)} ficheros)", flush=True)
    except Exception as exc:
        job["is_archive"] = False
        print(f"[TGHirayi_v2] <<-- backtrace in add_to_queue -->>", flush=True)
        import traceback; traceback.print_exc()
    _save_db(db)
    # Si el worker esta pausado y hay trabajos, sugerir reanudar
    return {"ok": True, "job_id": job["id"], "worker_paused": _worker_paused}


@router.delete("/api/telegram-copy-v2/queue/{job_id}")
async def remove_job(job_id: str, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    job = next((j for j in db.get("queue", []) if j["id"] == job_id), None)
    # Si el job es archive con un encode persistido (posible huérfano del reinicio),
    # matarlo antes de eliminar para no dejar ffmpeg sueltos consumiendo CPU.
    if job and job.get("encode_state") and _pid_alive(job.get("encode_state", {}).get("pid")):
        _kill_pid(job["encode_state"]["pid"])
        print(f"[TGHirayi_v2] Job {job_id} eliminado: ffmpeg pid {job['encode_state']['pid']} matado", flush=True)
    if job:
        _cleanup_archive_workdir(job_id)
    db["queue"] = [j for j in db.get("queue", []) if j["id"] != job_id]
    _save_db(db)
    return {"ok": True}


@router.delete("/api/telegram-copy-v2/queue/completed/clean")
async def clean_completed_jobs(request: Request):
    """Elimina de la cola todos los trabajos finalizados (completed/error)."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    before = len(db.get("queue", []))
    db["queue"] = [j for j in db.get("queue", []) if j.get("status") not in _TERMINAL_STATUSES]
    _save_db(db)
    return {"ok": True, "removed": before - len(db["queue"])}


@router.put("/api/telegram-copy-v2/queue/{job_id}/move")
async def reorder_job(job_id: str, body: QueueReorder, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    queue = db.get("queue", [])
    idx = None
    for i, j in enumerate(queue):
        if j["id"] == job_id:
            idx = i
            break
    if idx is None:
        raise HTTPException(404, "Job no encontrado")
    job = queue.pop(idx)
    if body.direction == "up" and idx > 0:
        queue.insert(idx - 1, job)
    elif body.direction == "down" and idx < len(queue):
        queue.insert(idx + 1, job)
    elif body.direction == "top":
        queue.insert(0, job)
    elif body.direction == "bottom":
        queue.append(job)
    else:
        queue.insert(idx, job)
    db["queue"] = queue
    _save_db(db)
    return {"ok": True}


@router.put("/api/telegram-copy-v2/queue/{job_id}/pause")
async def toggle_job_pause(job_id: str, body: QueuePauseToggle, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["paused"] = body.paused
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.put("/api/telegram-copy-v2/queue/{job_id}/destinations")
async def update_job_destinations(job_id: str, body: QueueDestinationsUpdate, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["destination_ids"] = body.destination_ids
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.put("/api/telegram-copy-v2/queue/{job_id}/next-episode")
async def update_job_next_episode(job_id: str, body: NextEpisodeUpdate, request: Request):
    """Define explícitamente el siguiente episodio a procesar (override del 'auto')."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["next_episode"] = max(1, body.next_episode)
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.put("/api/telegram-copy-v2/queue/{job_id}/next-episode/auto")
async def reset_job_next_episode(job_id: str, request: Request):
    """Vuelve el siguiente episodio a 'auto' (usa current_episode)."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j.pop("next_episode", None)
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


class QueueSkipUpdate(BaseModel):
    skip_if_exists_topo3: bool


def _ep_in_scope(job, ep) -> bool:
    """El episodio pertenece al ámbito del job: si hay lista inclusiva
    (only_episode_msgs, jobs partidos) solo esos; si no, todos menos los
    omitidos (skip_episode_msgs). Por telegram_msg_id (robusto a reescaneos)."""
    try:
        _mid = str(ep.get("telegram_msg_id") or ep.get("msg_id") or "")
        _only = job.get("only_episode_msgs")
        if isinstance(_only, list):
            return _mid in {str(x) for x in _only}
        _skip = job.get("skip_episode_msgs") or []
        return _mid not in {str(x) for x in _skip}
    except Exception:
        return True


@router.put("/api/telegram-copy-v2/queue/{job_id}/skip-exists")
async def update_job_skip_exists(job_id: str, body: QueueSkipUpdate, request: Request):
    """Cambia por job la opción 'Omitir subida si el topic ya existe'."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["skip_if_exists_topo3"] = bool(body.skip_if_exists_topo3)
            if not j["skip_if_exists_topo3"]:
                j["_omitted"] = {}
                j.pop("_omit_src_ids", None)
            _save_db(db)
            return {"ok": True, "skip_if_exists_topo3": j["skip_if_exists_topo3"]}
    raise HTTPException(404, "Job no encontrado")


class QueueEpisodesUpdate(BaseModel):
    checked_msg_ids: List[str]


def _job_episode_rows(job):
    """Filas de episodios del item con estado para el modal (n, msg, nombre,
    tamaño, ámbito, procesado, fallido)."""
    _eps = _fetch_episodes_sync(job.get("item_id", "")) or []
    _cur = int(job.get("current_episode") or 0)
    _fails = set()
    try:
        _fails = {int(k) for k in (job.get("_dl_fails") or {}).keys()}
    except Exception:
        pass
    rows = []
    for _i, _ep in enumerate(_eps):
        _n = int(_ep.get("episode_number") or (_i + 1))
        _mid = _ep.get("telegram_msg_id") or _ep.get("msg_id") or 0
        try:
            _sz = int(_ep.get("file_size") or 0)
        except Exception:
            _sz = 0
        _in = _ep_in_scope(job, _ep)
        _state = "omitido" if not _in else ("fallido" if _n in _fails else ("procesado" if _n < _cur else ("en curso" if _n == _cur and job.get("status") == "processing" else "pendiente")))
        rows.append({"n": _n, "msg_id": int(_mid or 0),
                     "file_name": _ep.get("file_name") or _ep.get("title") or "",
                     "file_size": _sz, "in_scope": bool(_in), "state": _state})
    return rows


@router.get("/api/telegram-copy-v2/queue/{job_id}/episodes")
async def list_job_episodes(job_id: str, request: Request):
    """Lista episodios del job con estado (modal de episodios)."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            try:
                _nx = int(j.get("next_episode") or 0)
            except Exception:
                _nx = 0
            _rf = _nx if _nx > 0 else int(j.get("current_episode") or 0)
            return {"ok": True, "job_id": job_id, "title": j.get("title", ""),
                    "current_episode": int(j.get("current_episode") or 0),
                    "next_episode": _nx, "resume_from": _rf,
                    "is_archive": bool(j.get("is_archive", False)),
                    "episodes": _job_episode_rows(j)}
    raise HTTPException(404, "Job no encontrado")


@router.put("/api/telegram-copy-v2/queue/{job_id}/episodes")
async def update_job_episodes(job_id: str, body: QueueEpisodesUpdate, request: Request):
    """Fija los episodios a copiar (checked por msg_id). En jobs con lista
    inclusiva recorta esa lista; si no, ajusta la de omitidos."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            _all = _fetch_episodes_sync(j.get("item_id", "")) or []
            _all_msgs = [str(_e.get("telegram_msg_id") or _e.get("msg_id") or "") for _e in _all]
            _checked = {str(x) for x in (body.checked_msg_ids or [])}
            if isinstance(j.get("only_episode_msgs"), list):
                j["only_episode_msgs"] = [m for m in _all_msgs if m in _checked]
            else:
                j["skip_episode_msgs"] = [m for m in _all_msgs if m not in _checked]
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


class QueueSplitRequest(BaseModel):
    from_msg_id: int


@router.post("/api/telegram-copy-v2/queue/{job_id}/split")
async def split_job_from_episode(job_id: str, body: QueueSplitRequest, request: Request):
    """Corta desde un episodio en adelante: crea job nuevo pausado al final
    con esos episodios (solo entradas de cola, nada al catálogo) y los quita
    del original. Título = primer fichero, cover genérico."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            _all = _fetch_episodes_sync(j.get("item_id", "")) or []
            _pos = None
            for _i, _e in enumerate(_all):
                try:
                    if int(_e.get("telegram_msg_id") or _e.get("msg_id") or 0) == int(body.from_msg_id):
                        _pos = _i
                        break
                except Exception:
                    continue
            if _pos is None:
                raise HTTPException(404, "Episodio no encontrado en el job")
            _moved = _all[_pos:]
            _moved_checked = [_e for _e in _moved if _ep_in_scope(j, _e)]
            if not _moved_checked:
                raise HTTPException(400, "Nada que mover (todo desmarcado desde ahí)")
            _moved_msgs = [str(_e.get("telegram_msg_id") or _e.get("msg_id") or "") for _e in _moved]
            _first = _moved_checked[0]
            _only = [str(_e.get("telegram_msg_id") or _e.get("msg_id") or "") for _e in _moved_checked]
            if isinstance(j.get("only_episode_msgs"), list):
                _cur_only = {str(x) for x in j.get("only_episode_msgs")}
                j["only_episode_msgs"] = [m for m in _cur_only if m not in set(_moved_msgs)]
            else:
                _sk = {str(x) for x in (j.get("skip_episode_msgs") or [])}
                for _m in _moved_msgs:
                    _sk.add(_m)
                j["skip_episode_msgs"] = sorted(_sk)
            db["job_id_counter"] = db.get("job_id_counter", 0) + 1
            _nj = {
                "id": str(db["job_id_counter"]),
                "item_id": j.get("item_id"),
                "title": _first.get("file_name") or _first.get("title") or j.get("title"),
                "telegram_link": j.get("telegram_link", ""),
                "category": j.get("category", ""),
                "subcategory": j.get("subcategory", ""),
                "destination_ids": list(j.get("destination_ids") or []),
                "total_episodes": len(_moved_checked),
                "priority": len(db.get("queue", [])),
                "paused": True,
                "status": "queued",
                "progress": 0.0,
                "download_progress": 0.0,
                "upload_progress": 0.0,
                "status_text": "En cola (partido, pausado)",
                "current_episode": 0,
                "current_destination": 0,
                "audio_lang": j.get("audio_lang", ""),
                "sub_lang": j.get("sub_lang", ""),
                "skip_if_exists_topo3": bool(j.get("skip_if_exists_topo3", False)),
                "only_episode_msgs": _only,
                "force_generic_cover": True,
                "cover_text": "",
                "use_enricher_cover": True,
                "user_id": session["user_id"],
                "created": time.time(),
            }
            try:
                _nj["is_archive"] = _detect_archive_job(_nj, _moved_checked)
            except Exception:
                _nj["is_archive"] = False
            db.setdefault("queue", []).append(_nj)
            _save_db(db)
            return {"ok": True, "job_id": _nj["id"], "moved": len(_moved_checked)}
    raise HTTPException(404, "Job no encontrado")


@router.post("/api/telegram-copy-v2/queue/{job_id}/kill-encode")
async def kill_job_encode(job_id: str, request: Request):
    """Mata el ffmpeg de recodificación en curso de un job (tras confirmación del usuario).
    La recodificación re-encoda el vídeo: matarla pierde el pase actual (el job quedará
    en queued y re-encodará desde su extract_state al reprocesar)."""
    session = _session_user(request)
    if not session or session["role"] != "admin":
        raise HTTPException(403, "Solo admin")
    proc = _encode_proc_registry.get("proc")
    if proc is None or proc.poll() is not None:
        return {"ok": False, "error": "No hay encode en curso para este job"}
    if _encode_proc_registry.get("job_id") not in (None, job_id):
        return {"ok": False, "error": "El encode en curso pertenece a otro job"}
    try:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        _encode_proc_registry.pop("proc", None)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.put("/api/telegram-copy-v2/queue/{job_id}/normalize")
async def update_job_normalize(job_id: str, body: QueueNormUpdate, request: Request):
    """Define idioma de audio y subtítulos para la normalización MP4 del job."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            if body.audio_lang is not None:
                j["audio_lang"] = (body.audio_lang or "").strip()
            if body.sub_lang is not None:
                j["sub_lang"] = (body.sub_lang or "").strip()
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.get("/api/telegram-copy-v2/queue/{job_id}/cover")
async def get_job_cover(job_id: str, request: Request):
    """Devuelve la info del cover del job (plantilla + texto resuelto e imagen) para editar en la cola."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    job = None
    for j in db.get("queue", []):
        if j["id"] == job_id:
            job = j
            break
    if not job:
        raise HTTPException(404, "Job no encontrado")

    # 2026-09-04: sembrar edición local para que el modal muestre el cover
    # editado (texto + imagen) en vez del original.
    try:
        if _seed_job_cover_from_local(job):
            _save_db(db)
    except Exception:
        pass

    # Origen del cover: del item del catálogo si existe; si no (item aún no escaneado),
    # del link guardado en el job para poder cargar la imagen original igualmente.
    channel_id = None
    source_msg_id = None
    source_topic_id = None
    item_data = _fetch_item_data_sync(job.get("item_id", ""))
    if item_data:
        channel_id = _extract_channel_id(item_data.get("telegram_link", ""))
        source_msg_id = item_data.get("telegram_msg_id")
        source_topic_id = _parse_channel_link(item_data.get("telegram_link", "")).get("topic_id")
    if not channel_id or not source_msg_id:
        job_link = job.get("telegram_link", "")
        parsed_job = _parse_channel_link(job_link)
        if not channel_id:
            channel_id = _extract_channel_id(job_link)
        if not source_msg_id:
            source_msg_id = parsed_job.get("msg_id")
        if not source_topic_id:
            source_topic_id = parsed_job.get("topic_id")

    # Plantilla a editar: la del job si contiene tags, si no la default
    # (enriquecedor resuelta por categoría, legacy cover_tags.json si no hay).
    default_template = _default_cover_template(job.get("category", ""), job.get("subcategory", ""))

    stored = (job.get("cover_text") or "").strip()
    template = stored if "{f" in stored else default_template

    image_b64 = None
    file_found = False
    ep_count = len(_fetch_episodes_sync(job.get("item_id", ""))) if job.get("item_id") else 0
    details = job.get("enrich_details") or {}

    preview = ""
    if template:
        preview = _resolve_cover_tags(template, job.get("title", ""), ep_count, details)

    try:
        if channel_id and source_msg_id:
            msgs = await _fetch_cover_messages(None, channel_id, source_msg_id, source_topic_id, job)
            if msgs:
                file_found = True
                if not preview:
                    # Fallback: texto original del cover (primer mensaje con texto, o concatenación)
                    texts = []
                    for m in msgs:
                        t = (m.get("text") if isinstance(m, dict) else None) or getattr(m, 'message', None) or getattr(m, 'text', '') or ''
                        if t.strip():
                            texts.append(t.strip())
                    preview = "\n".join(texts)
                # Imagen del cover (primera foto encontrada, ya en bytes vía servicio)
                for m in msgs:
                    pb = (m.get("photo_bytes") if isinstance(m, dict) else None)
                    if pb:
                        import base64 as _b64
                        image_b64 = _b64.b64encode(bytes(pb)).decode('ascii')
                        break
    except Exception as e:
        print(f"[TGHirayi_v2] Error obteniendo cover: {e}", flush=True)

    # 2026-09-04: si hay póster editado en local, mostrarlo (manda sobre el origen).
    try:
        _bt, _bp = _bridge_enricher_cover(job)
        if _bp and isinstance(_bp, (bytes, bytearray, memoryview)):
            import base64 as _b64b
            image_b64 = _b64b.b64encode(bytes(_bp)).decode('ascii')
            file_found = True
    except Exception:
        pass

    return {"text": preview, "template": template, "image": image_b64, "file_found": file_found,
            "item_id": job.get("item_id", ""),
            "category": job.get("category", ""), "subcategory": job.get("subcategory", ""),
            "title": job.get("title", ""),
            "use_enricher_cover": bool(job.get("use_enricher_cover", True)),
            "details": job.get("enrich_details") or {}}


@router.post("/api/telegram-copy-v2/queue/{job_id}/cover/preview")
async def preview_job_cover(job_id: str, body: dict, request: Request):
    """Resuelve en tiempo real una plantilla de cover con los datos del job (para el editor interactivo).
    Los tags desconocidos se ignoran (se dejan tal cual si no hay dato)."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    job = None
    for j in db.get("queue", []):
        if j["id"] == job_id:
            job = j
            break
    if not job:
        raise HTTPException(404, "Job no encontrado")

    template = (body.get("template") or "")
    ep_count = len(_fetch_episodes_sync(job.get("item_id", ""))) if job.get("item_id") else 0
    details = body.get("details") or job.get("enrich_details") or {}
    try:
        preview = _resolve_cover_tags(template, job.get("title", ""), ep_count, details)
    except Exception as e:
        print(f"[TGHirayi_v2] Error en preview cover: {e}", flush=True)
        preview = template

    resp = {"text": preview}
    if body.get("debug"):
        resp["debug"] = _debug_cover_tags(template, job.get("title", ""), ep_count, details)
    return resp


@router.put("/api/telegram-copy-v2/queue/{job_id}/password")
async def set_archive_password(job_id: str, body: dict, request: Request):
    """Guarda la contraseña de un job archive en espera (awaiting_password)."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["archive_password"] = (body.get("password") or "").strip()
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.post("/api/telegram-copy-v2/queue/{job_id}/password/retry")
async def retry_archive_job(job_id: str, request: Request):
    """Reintenta un job archive en espera de contraseña: vuelve a encolarlo con prioridad normal."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["status"] = "queued"
            j["status_text"] = "Reintentando con contraseña..."
            j["priority"] = 10
            j["error"] = ""
            j["current_episode"] = 0
            # Restaurar ficheros preservados a download si siguen ahí
            preserved = j.get("preserved_dir")
            if preserved and os.path.isdir(preserved):
                import shutil as _sh
                for fn in os.listdir(preserved):
                    src = os.path.join(preserved, fn)
                    work = _archive_workdir(job_id)
                    try:
                        _sh.move(src, os.path.join(work["download"], fn))
                    except Exception:
                        pass
            _save_db(db)
            await _start_worker()
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.put("/api/telegram-copy-v2/queue/{job_id}/cover")
async def update_job_cover(job_id: str, body: dict, request: Request):
    """Guarda el texto editado del cover en el job. Si se indica title, actualiza el título del job."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["cover_text"] = (body.get("cover_text") or "")
            # 2026-09-04: edición manual en cola manda sobre el seed local.
            j["cover_manual"] = True
            j["cover_from_local"] = False
            if "use_enricher_cover" in body:
                j["use_enricher_cover"] = bool(body.get("use_enricher_cover"))
            if "title" in body:
                j["title"] = (body.get("title") or "").strip()
            if "details" in body and isinstance(body.get("details"), dict):
                j["enrich_details"] = body["details"]
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.post("/api/telegram-copy-v2/queue/{job_id}/requeue")
async def requeue_job(job_id: str, request: Request):
    """Vuelve a meter un trabajo finalizado en la cola para re-procesarlo.
    Conserva current_episode (progreso previo) para reanudar desde donde quedó."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    db = _load_db()
    for j in db.get("queue", []):
        if j["id"] == job_id:
            j["status"] = "queued"
            j["status_text"] = "En cola"
            j["progress"] = 0.0
            j["download_progress"] = 0.0
            j["upload_progress"] = 0.0
            j.pop("download_started", None)
            j.pop("upload_started", None)
            j.pop("download_finished", None)
            j.pop("upload_finished", None)
            j.pop("dl_client", None)
            j.pop("ul_client", None)
            j["current_destination"] = 0
            j["_uploaded_to"] = {}
            j["error"] = ""
            # Reenviar fuerza OFF el omitir-si-existe (si no, un job fallido u
            # omitido se saltaría el topic ya creado y no avanzaría) + limpia
            # omisiones obsoletas. current_episode se conserva para retomar.
            j["skip_if_exists_topo3"] = False
            j["_omitted"] = {}
            j.pop("_omit_src_ids", None)
            j.pop("_dl_fails", None)
            # Archives: si ya tienen vídeos extraídos/recodificados listos, se re-encolan
            # en fase ready_upload (subir directo sin re-descargar). Si no, se re-descargan.
            if j.get("is_archive"):
                ready = [v for v in (j.get("extract_state") or {}).get("extracted") or [] if os.path.isfile(v)]
                if ready:
                    j["archive_phase"] = "ready_upload"
                    j["status_text"] = "En cola (subir ficheros)"
                else:
                    j["archive_phase"] = "download"
                    j["status_text"] = "En cola"
            # current_episode se conserva: el worker reanudará desde ahí (o desde next_episode si se indicó)
            _save_db(db)
            return {"ok": True}
    raise HTTPException(404, "Job no encontrado")


@router.get("/api/telegram-copy-v2/queue/{job_id}/log")
async def get_job_log(job_id: str, request: Request):
    """Devuelve el log del reprocesamiento en memoria del job (terminal)."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesion")
    lines = list(_job_logs.get(job_id) or [])
    return {"ok": True, "lines": lines, "job_id": job_id}


@router.post("/api/telegram-copy-v2/worker/toggle")
async def toggle_worker(request: Request):
    session = _session_user(request)
    if not session or session["role"] != "admin":
        raise HTTPException(403, "Solo admin")
    global _worker_paused, _worker_task, _worker_running, _current_job, _worker_gen
    _worker_paused = not _worker_paused
    if not _worker_paused:
        # Solo crear worker si no hay uno corriendo
        if not _worker_running or (_worker_task is None) or _worker_task.done():
            _worker_gen += 1
            _worker_running = False
            _current_job = None
            _worker_task = asyncio.ensure_future(_start_worker(_worker_gen))
    return {"ok": True, "paused": _worker_paused}


# ─── Worker de Background ─────────────────────────────────────────
def _get_current_job():
    """Devuelve el job actual si el worker esta corriendo."""
    global _current_job
    return _current_job


def _count_pending_archives(all_q):
    """Nº de archives en procesado o pendientes de subir (miden el disco reservado).
    Excluye jobs finalizados o con error. Los que están solo 'download' no cuentan
    (aún no reservan espacio procesado)."""
    return [j for j in all_q
            if j.get("is_archive")
            and j.get("archive_phase") in ("processing", "ready_upload", "uploading")
            and j.get("status") not in _TERMINAL_STATUSES]


def _pending_archives_info(all_q) -> list:
    """Información compacta de los archives pendientes (para mostrar en el header de la UI)."""
    out = []
    for j in _count_pending_archives(all_q):
        out.append({
            "id": j.get("id"),
            "title": j.get("title", ""),
            "phase": j.get("archive_phase"),
        })
    return out


def _pick_next_worker_job(all_q) -> Optional[dict]:
    """Elige el siguiente job a procesar respetando el orden de prioridad (pos. en cola),
    saltando archives que no pueden iniciar su descarga:
    - phase download con slot de procesado ocupado O límite de pendientes alcanzado → skip
      (la cola sigue con el siguiente job normal; el archive espera su turno en la misma posición).
    - phase processing/uploading → los gestiona su task de fondo / subida → skip.
    - phase ready_upload → se elige para SUBIR (la extracción+recodificación ya terminó).
    """
    cfg = _load_config()
    parallel = bool(cfg.get("archive_parallel", True))
    max_pending = int(cfg.get("max_pending_archives", 5) or 5)
    pending = len(_count_pending_archives(all_q))
    for j in all_q:
        if j.get("paused") or j.get("status") in _TERMINAL_STATUSES:
            continue
        if not j.get("is_archive"):
            return j
        if not parallel:
            # Modo secuencial legacy: el archive se procesa entero en su turno
            return j
        phase = j.get("archive_phase") or "download"
        if phase in ("processing", "uploading"):
            # Si NO hay task de fondo viva registrada para este job (crash del gateway,
            # reinicio sin re-lanzar la task, o error que dejó phase=processing),
            # el procesado de 2º plano está muerto → volver a download para reprocesar.
            # Si hubo error durante el procesado, marcarlo 'paused' para no bloquear la
            # cola de archives y dejar que el usuario lo gestione/reintente.
            if j.get("id") not in _archive_tasks:
                if j.get("status") in ("error",):
                    j["status"] = "paused"
                    j["status_text"] = "Pausado (error en procesado)"
                else:
                    j["archive_phase"] = "download"
                    j["status_text"] = "En cola (reprocesando)"
                _job_log(j["id"], f"[TGHirayi_v2] [ARCHIVE] Job {j['id']} recuperado: sin task viva → {j['status_text']}")
                _persist_job(j)
            continue
        if phase == "ready_upload":
            return j
        # phase == download (o sin fase): requiere slot libre + margen de pendientes
        if _archive_slot_owner is not None:
            continue
        if pending >= max_pending:
            continue
        return j
    return None


async def _start_worker(gen: int = 0):
    global _worker_running, _worker_paused, _worker_task
    print(f" [TGHirayi_v2] _start_worker llamada (gen={gen})", flush=True)
    if _worker_running:
        print(" [TGHirayi_v2] Worker ya estaba corriendo, saliendo", flush=True)
        return
    _worker_running = True
    _worker_paused = False
    print(f" [TGHirayi_v2] Worker iniciado (gen={gen})", flush=True)

    # Reiniciar estado del slot de archives (un reinicio no mantiene tasks en vuelo)
    global _archive_slot_owner
    _archive_slot_owner = None
    _archive_tasks.clear()

    # Resetear jobs atascados al arrancar
    try:
        db = _load_db()
        print(f" [TGHirayi_v2] DB cargada, {len(db.get('queue',[]))} jobs", flush=True)
        n = 0
        for j in db.get("queue", []):
            old = j.get("status")
            if old in ("error",):
                if j.get("is_archive"):
                    # Error en procesado de archive: pausar en vez de re-encolar solo,
                    # para que no bloquee la cola y el usuario lo gestione/reintente.
                    j["status"] = "paused"
                    j["status_text"] = "Pausado (error en procesado)"
                    j["archive_phase"] = "download"
                    print(f" [TGHirayi_v2] Archive {j['id']} con error → paused (no bloquea cola)", flush=True)
                else:
                    j["status"] = "queued"
                    j["status_text"] = "En cola"
                    j["progress"] = 0.0
                    # current_episode SE CONSERVA para retomar donde quedó
                    # (resetearlo a 0 duplicaría lo ya subido).
                    n += 1
                    print(f" [TGHirayi_v2] Job {j['id']} reset: {old} -> queued (retoma ep.{j.get('current_episode', 0)})", flush=True)
            elif old in ("processing", "paused_by_worker"):
                j["status"] = "queued"
                j["status_text"] = "En cola (reanudando)"
                print(f" [TGHirayi_v2] Job {j['id']} reanudando desde ep.{j.get('current_episode',0)}", flush=True)
                n += 1
            # Archives cuyo procesado de fondo murió con el gateway → vuelven a download
            if j.get("is_archive") and j.get("archive_phase") in ("processing", "uploading"):
                j["archive_phase"] = "download"
                j["status_text"] = "En cola (reanudando)"
                print(f" [TGHirayi_v2] Archive {j['id']} vuelve a fase download (procesado perdido)", flush=True)
        if n:
            _save_db(db)
            print(f" [TGHirayi_v2] {n} jobs reseteados a queued", flush=True)
    except Exception as e:
        print(f" [TGHirayi_v2] Error en reset: {e}", flush=True)
        import traceback
        traceback.print_exc()

    try:
        while _worker_running:
            if _worker_paused:
                await asyncio.sleep(1)
                continue

            db = _load_db()
            all_q = db.get("queue", [])
            queue = [j for j in all_q if not j.get("paused") and j.get("status") not in _TERMINAL_STATUSES]
            if not queue:
                await asyncio.sleep(2)
                continue

            # Backfill temprano de is_archive (jobs antiguos sin el tag) para que el
            # salto inteligente funcione sin esperar a _process_job
            for jj in all_q:
                if jj.get("status") in _TERMINAL_STATUSES or jj.get("paused"):
                    continue
                if "is_archive" not in jj:
                    try:
                        jj["is_archive"] = _detect_archive_job(jj, _fetch_episodes_sync(jj.get("item_id", "")))
                    except Exception:
                        jj["is_archive"] = False

            job = _pick_next_worker_job(all_q)
            if job is None:
                await asyncio.sleep(2)
                continue
            global _current_job
            _current_job = job
            print(f" [TGHirayi_v2] Procesando job {job['id']}: {job['title']} (status={job.get('status')})", flush=True)

            try:
                await _process_job(job, db)
            except Exception as e:
                print(f" [TGHirayi_v2] Error procesando job {job['id']}: {e}", flush=True)
                import traceback
                traceback.print_exc()
                job["status"] = "error"
                job["error"] = str(e)
                _save_db(db)
                await asyncio.sleep(3)

            _current_job = None
    except asyncio.CancelledError:
        print(" [TGHirayi_v2] Worker cancelado", flush=True)
    except Exception as e:
        print(f" [TGHirayi_v2] Error en worker loop: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        _worker_running = False
        _worker_task = None
        print(" [TGHirayi_v2] Worker detenido", flush=True)


def _resolve_collection_package(item_id: str) -> Optional[dict]:
    """Si el item es una colección (escaneada con is_collection o local COL-),
    devuelve el paquete {name, serial, text, cover_bytes?, cover_mime?,
    cover_msg_id?, cover_link?}. None si no es colección."""
    try:
        if not item_id:
            return None
        if str(item_id).startswith("COL-"):
            from tvcat.services.catalog_service import get_local_collection, get_local_cover
            from tvcat.services.catalog_service import refresh_collection_entries as _refresh_entries
            import json as _js
            loc = get_local_collection(item_id)
            if not loc:
                return None
            try:
                entries = _js.loads(loc.get("entries_json") or "[]") or []
            except Exception:
                entries = []
            # Refresco a valores efectivos de HOY (título enriquecido + año):
            # lo guardado puede ser anterior a enriquecer cada entrada.
            try:
                entries = _refresh_entries(entries)
            except Exception:
                pass
            from tvcat.services.text_norm import build_collection_text
            try:
                text = build_collection_text(loc.get("name") or "", loc.get("serial") or "", entries)
            except Exception:
                text = "TVCatCollection"
            cov = None
            try:
                cov = get_local_cover(int(str(item_id).split("-")[-1] or 0))
            except Exception:
                cov = None
            return {"name": loc.get("name") or "Colección", "serial": loc.get("serial") or "",
                    "text": text, "cover_bytes": (cov or {}).get("blob"),
                    "cover_mime": (cov or {}).get("mime") or "image/jpeg", "local": True,
                    "is_collection": True,
                    "description": loc.get("description") or "",
                    "cover_text": loc.get("cover_text") or ""}
        data = _fetch_item_data_sync(item_id)
        if not data or not int(data.get("is_collection", 0) or 0):
            return None
        return {"name": data.get("collection_name") or data.get("title") or "Colección",
                "serial": data.get("collection_serial") or "",
                "text": data.get("collection_raw") or "TVCatCollection",
                "cover_bytes": None, "cover_mime": "image/jpeg",
                "cover_msg_id": data.get("telegram_msg_id"),
                "cover_link": data.get("telegram_link") or "", "local": False,
                "is_collection": True,
                # El caption es el existente (lo preparó el editor); no se compone aquí.
                "cover_text": data.get("description") or ""}
    except Exception:
        return None


async def _collection_cover_bytes(client, pkg, job: dict = None):
    """Bytes del cover del paquete vía servicio central (local directo; escaneado vía download)."""
    try:
        if pkg.get("cover_bytes"):
            return pkg["cover_bytes"], pkg.get("cover_mime") or "image/jpeg"
        link, msg_id = pkg.get("cover_link") or "", int(pkg.get("cover_msg_id") or 0)
        m = re.search(r"/c/(\d+)/", link)
        if not m or not msg_id or msg_id in (-999, -1000):
            return None, None
        cid = "-100" + m.group(1)
        data = await _svc().download_media(cid, msg_id, **_svc_creds(job))
        if isinstance(data, str) or not data:
            return None, None
        return bytes(data), "image/jpeg"
    except Exception as e:
        print(f"[TGHirayi_v2] cover colección no disponible: {e}", flush=True)
        return None, None


async def _process_collection_job(job: dict, db: dict, destinations: list, client, pkg: dict, delay: float, cfg: dict):
    """Publica una colección en N destinos: cover (caption preparado por el
    editor) + mensaje colección (cabecera con SERIAL + entradas). Sin
    descargas ni episodios. En destinos topo 3 va al topic compartido
    "TVCat Collections" (evita colisionar con el topic de un título homónimo);
    el escaneo colapsa por serial quedándose la más nueva. NUNCA se omite
    (sin verificación de existencia: el usuario organiza en Telegram)."""
    import io as _io
    name = pkg.get("name") or job.get("title") or "Colección"
    text = pkg.get("text") or "TVCatCollection"
    # El texto del cover lo prepara el editor (cover_text); aquí solo se sube.
    # Fallback por si viene de una colección antigua sin cover_text.
    caption = (pkg.get("cover_text") or "").strip()
    if not caption:
        caption = "TVCat Collection\nTitle: %s" % name
        if (pkg.get("description") or "").strip():
            caption += "\n\nOverview:\n" + (pkg.get("description") or "").strip()
    cover_bytes, _mime = await _collection_cover_bytes(client, pkg, job)
    total = len(destinations)
    sent = []
    job["_uploaded_to"] = {}
    creds = _svc_creds(job)
    for di, dest in enumerate(destinations):
        dname = dest.get("name") or dest.get("channel_id") or str(di + 1)
        job["status"] = "processing"
        job["progress"] = (di / max(total, 1)) * 100.0
        job["status_text"] = f"Publicando colección en {dname} ({di + 1}/{total})"
        _persist_job(job)
        # F5: destino omitido (topic ya existe) → no se sube nada, ni cover
        # ni lista. Para actualizar el cover de un topic existente, borrar el
        # topic o desactivar "Omitir si existe" y reprocesar.
        # Colecciones: NUNCA se omiten (siempre se publican; el escaneo colapsa
        # por serial). El topic es el compartido "TVCat Collections".
        _is_col = bool(pkg.get("is_collection") or pkg.get("local"))
        _col_omit = (not _is_col) and (str(dest.get("id") or dest.get("channel_id")) in (job.get("_omitted") or {}))
        try:
            if _is_col and int(dest.get("topology", 1)) == 3:
                topic = await _resolve_topic_id_async(client, dest, _COLLECTIONS_TOPIC, job)
            else:
                topic = await _resolve_topic_id_async(client, dest, name, job)
            rt = topic if topic else None
            cover_id = 0
            if _col_omit:
                sent.append({"dest": dest.get("id"), "cover_msg_id": 0,
                             "collection_msg_id": 0, "omitted": True})
                job["_uploaded_to"][dest.get("id")] = True
                _persist_job(job)
                print(f"[TGHirayi_v2] Colección '{name}' -> {dname}: omitida (topic ya existe)", flush=True)
            else:
                if cover_bytes:
                    cover_id = await _svc().send_photo(dest["channel_id"], bytes(cover_bytes),
                                                       caption=caption,
                                                       reply_to_msg_id=rt, **creds) or 0
                collection_id = await _svc().send_text(dest["channel_id"], text,
                                                       reply_to_msg_id=rt, **creds) or 0
                sent.append({"dest": dest.get("id"), "cover_msg_id": cover_id,
                             "collection_msg_id": collection_id})
                job["_uploaded_to"][dest.get("id")] = True
                _persist_job(job)
                print(f"[TGHirayi_v2] Colección '{name}' -> {dname}: cover={cover_id} msg={sent[-1]['collection_msg_id']}", flush=True)
        except Exception as e:
            print(f"[TGHirayi_v2] Error publicando colección en {dname}: {e}", flush=True)
            job["_uploaded_to"][dest.get("id")] = False
            _persist_job(job)
        if delay and di < total - 1:
            await asyncio.sleep(delay)
    job["progress"] = 100.0
    if len(sent) >= total and total > 0:
        job["status"] = "completed"
        job["status_text"] = f"Colección publicada en {len(sent)}/{total} destinos"
    else:
        job["status"] = "error"
        job["error"] = f"Solo {len(sent)}/{total} destinos OK"
        job["status_text"] = job["error"]
    job["_collection_sent"] = sent
    _persist_job(job)


def _job_has_local_cover(job) -> bool:
    """True si el job tiene cover editado en local (texto del modal o del
    enriquecedor vía registry). En ese caso la copia del cover no lee nada
    del origen y la verificación de existencia en origen no aplica."""
    try:
        if (job.get("cover_text") or "").strip():
            return True
    except Exception:
        pass
    try:
        _bt, _bp = _bridge_enricher_cover(job if isinstance(job, dict) else {})
        if _bt:
            return True
    except Exception:
        pass
    return False


async def _process_job(job: dict, db: dict):
    """Procesa un job completo: copiar cover + episodios a destinos."""
    try:
        cfg = _load_config()
        delay = cfg.get("delay_seconds", 3.0)
        # Paralelismo descarga/subida (config): OFF = secuencial, toda la
        # velocidad a una fase (recomendado si la subida limita el total).
        parallel_dl = bool(cfg.get("download_parallel", False))
        dest_ids = job.get("destination_ids", [])
        destinations = [db["destinations"][d] for d in dest_ids if d in db["destinations"]]

        if not destinations:
            job["status"] = "error"
            job["error"] = "No hay destinos validos"
            _persist_job(job)
            return

        job["status"] = "processing"
        job["progress"] = 0.0
        job["download_progress"] = 0.0
        job["upload_progress"] = 0.0
        job["status_text"] = "Iniciando..."
        job["_uploaded_to"] = {}
        job.pop("_dl_ep", None)
        job.pop("_ul_ep", None)
        _persist_job(job)
        print(f"[TGHirayi_v2] Procesando job {job['id']}: {job['title']}", flush=True)

        client = await _get_telegram_client()
        if not client:
            job["status"] = "error"
            job["error"] = "No se pudo obtener cliente"
            _persist_job(job)
            return

        # F5 — Omitir si existe en destino (solo topo 3): pre-check por destino
        # con caché + verificación viva. Pre-pobla job["_topics"] para que el
        # cover vaya al topic existente (no crear duplicado). El cover SÍ se
        # sube a destinos omitidos (puede estar editado); los episodios no.
        # Colecciones: excluidas (siempre se publican en su topic compartido;
        # el escaneo colapsa por serial).
        # Antes: re-siembra cover local (ediciones posteriores al encolado;
        # el título lo fija el catálogo y no se reescribe).
        try:
            if _seed_job_cover_from_local(job):
                _persist_job(job)
        except Exception:
            pass
        job.setdefault("_omitted", {})
        job.setdefault("_topics", {})
        # Flag POR JOB (la global solo es default al encolar; jobs antiguos sin
        # flag usan la global). Con flag OFF se limpian omisiones obsoletas.
        _skip_on = bool(job.get("skip_if_exists_topo3", cfg.get("skip_if_exists_topo3", False)))
        if not _skip_on and (job.get("_omitted") or job.get("_omit_src_ids") is not None):
            job["_omitted"] = {}
            job.pop("_omit_src_ids", None)
            _persist_job(job)
        try:
            _omit_is_col = False
            try:
                _omit_is_col = _resolve_collection_package(job.get("item_id", "")) is not None
            except Exception:
                pass
            if not _omit_is_col and _skip_on:
                for _sd in destinations:
                    try:
                        if int(_sd.get("topology", 1)) != 3:
                            continue
                    except Exception:
                        continue
                    _skey = str(_sd.get("id") or _sd.get("channel_id"))
                    if _skey in job["_omitted"]:
                        continue
                    try:
                        _stid = await _topic_find_cached(client, _sd, job.get("title", ""), job)
                    except Exception:
                        _stid = None
                    if _stid and await _verify_topic_alive(client, _sd, int(_stid)):
                        job["_omitted"][_skey] = int(_stid)
                        _dkey = str(_sd.get("id") or _sd.get("channel_id") or _sd.get("name") or 'dest')
                        job["_topics"][_dkey] = int(_stid)
                        print(f"[TGHirayi_v2] Job {job['id']} omitirá episodios en '{_sd.get('name','?')}': topic ya existe ({_stid})", flush=True)
                _persist_job(job)
        except Exception as _se:
            print(f"[TGHirayi_v2] Error en pre-check omitir: {_se}", flush=True)

        # Omitido en TODOS los destinos → título completo omitido (ni cover):
        # nada que descargar ni subir.
        try:
            _all_omit_now = bool(job.get("_omitted")) and all(
                str(_d.get("id") or _d.get("channel_id")) in (job.get("_omitted") or {})
                for _d in destinations)
        except Exception:
            _all_omit_now = False
        if _all_omit_now:
            _dnames = ", ".join([_d.get("name", "?") for _d in destinations])
            job["status"] = "skipped"
            job["status_text"] = f"Omitido por existente en destino ({_dnames}): topic '{job.get('title')}' ya existe"
            job["progress"] = 100.0
            _persist_job(job)
            print(f"[TGHirayi_v2] Job {job['id']} OMITIDO entero: {job['status_text']}", flush=True)
            return

        # Rama COLECCIÓN (2026-09-09): título virtual o escaneado con
        # is_collection. Se publica cover + mensaje colección en cada destino,
        # sin descargas ni episodios. Equivale a 'cualquier otro título'.
        try:
            _col_pkg = _resolve_collection_package(job.get("item_id", ""))
        except Exception:
            _col_pkg = None
        if _col_pkg:
            print(f"[TGHirayi_v2] Job {job['id']} es colección '{_col_pkg.get('name')}': rama collection", flush=True)
            await _process_collection_job(job, db, destinations, client, _col_pkg, delay, cfg)
            return

        # Cliente Pyrogram para ficheros >1.9GB (obtenido bajo demanda si existe sesión pyrogram)
        pyro_client = None
        try:
            print(f"[TGHirayi_v2] Intentando obtener cliente Pyrogram...", flush=True)
            pyro_client = await asyncio.wait_for(_get_pyrogram_client(), timeout=12)
            print(f"[TGHirayi_v2] Pyrogram {'obtenido' if pyro_client else 'no disponible'}", flush=True)
        except asyncio.TimeoutError:
            print(f"[TGHirayi_v2] Timeout obteniendo Pyrogram (12s), continuando sin él", flush=True)
            pyro_client = None
        except Exception as e:
            print(f"[TGHirayi_v2] Pyrogram no disponible: {e}", flush=True)
            pyro_client = None

        # Obtener datos del item
        item_data = _fetch_item_data_sync(job["item_id"])
        if not item_data:
            raise ValueError(f"No se encontraron datos para item_id={job['item_id']}")

        # Extraer channel_id de telegram_link (mismo metodo que el reproductor)
        telegram_link = item_data.get("telegram_link", "")
        source_channel_id = _extract_channel_id(telegram_link)
        source_msg_id = item_data.get("telegram_msg_id")
        source_topic_id = _parse_channel_link(telegram_link).get("topic_id")
        if not source_channel_id:
            raise ValueError(f"No se pudo extraer channel_id del telegram_link: {telegram_link}")
        if not source_msg_id:
            raise ValueError(f"No hay telegram_msg_id para el item")
        print(f"[TGHirayi_v2] source: channel={source_channel_id}, msg={source_msg_id}, topic={source_topic_id}", flush=True)

        # Regla del usuario: si el cover NO existe en el origen, se salta el título
        # ENTERO (ni cover ni episodios). El cover es obligatorio: sin él el item no
        # es válido y copiar "algo" arrastra mensajes de OTRO título como cover.
        # EXENCIÓN: cover editado en local (enriquecedor o modal) no necesita el
        # origen para nada (texto + póster local/genérico) → no se verifica.
        if not job.get("_cover_done"):
            # Topología 0 usa -999 como cover genérico (sin imagen en origen)
            if int(source_msg_id) in (-999, -1000):
                print(f"[TGHirayi_v2] Job {job['id']} cover genérico (-999) permitido (topo 0)", flush=True)
            elif job.get("force_generic_cover"):
                # Partido: cover genérico forzado, no hay nada que verificar en origen.
                print(f"[TGHirayi_v2] Job {job['id']} cover genérico forzado (partido): sin verificación de origen", flush=True)
            elif _job_has_local_cover(job):
                print(f"[TGHirayi_v2] Job {job['id']} cover editado en local: sin verificación de origen", flush=True)
            else:
                cover_check = await _fetch_cover_messages(client, source_channel_id, source_msg_id, source_topic_id, job)
                if not cover_check:
                    job["status"] = "skipped"
                    job["status_text"] = "Saltado: cover no existe en el origen"
                    job["error"] = f"El cover (msg {source_msg_id}) no existe en el canal origen. Título omitido."
                    _persist_job(job)
                    print(f"[TGHirayi_v2] Job {job['id']} SALTADO: cover no existe (msg={source_msg_id})", flush=True)
                    return

        # ¿El origen pertenece al userbot? (firewall de baneo)
        is_owner = await _channel_is_owner(client, source_channel_id, job)
        real_copy_if_owner = bool(cfg.get("real_copy_if_owner", False))   # CB1
        real_copy_rest = bool(cfg.get("real_copy_rest", False))           # CB2
        # OPCIÓN OCULTA: forward Telegram directo aunque el origen sea de terceros.
        # Solo aplica con ambos CBs OFF (la UI lo fuerza) y origen no propio. Con
        # origen propio el path normal de copia Telegram ya es óptimo (sin atribución).
        forward_hidden = bool(cfg.get("forward_third_party", False))
        use_forward = bool(forward_hidden and (not is_owner))
        # Primera copia real existe si: origen de terceros (firewall) o CB1=true con origen propio.
        # El forward oculto la anula (todo método Telegram, sin descarga/subida).
        first_real = (not is_owner) or real_copy_if_owner
        if use_forward:
            first_real = False
        # CB2 solo aplica si hay primera copia real (sin ella no hay media que re-descargar)
        cb2_active = first_real and real_copy_rest
        # Normalización MP4: global (config) + audio/subs por job
        normalize_mp4 = bool(cfg.get("normalize_mp4", False))
        # Modo streaming MKV: prioridad sobre normalize_mp4. Con streaming activo SE normaliza
        # siempre (cualquier formato no-MP4 → conversión MP4; única excepción: MKV se sube tal
        # cual, solo cambiando pista de audio/subs si se pidió).
        streaming_mkv = bool(cfg.get("streaming_mkv", False))
        if streaming_mkv:
            normalize_mp4 = True
        norm_audio = (job.get("audio_lang") or "").strip()
        norm_sub = (job.get("sub_lang") or "").strip()
        if normalize_mp4:
            print(f"[TGHirayi_v2] Normalización MP4 activa (audio='{norm_audio}', subs='{norm_sub}')", flush=True)
        if streaming_mkv:
            print(f"[TGHirayi_v2] Modo streaming MKV activo", flush=True)
        print(f"[TGHirayi_v2] is_owner={is_owner} first_real={first_real} cb2_active={cb2_active} "
              f"(CB1={real_copy_if_owner}, CB2={real_copy_rest}, FWD={use_forward})", flush=True)

        # next_episode (override explícito del usuario) tiene prioridad sobre 'auto' (current_episode)
        override = job.get("next_episode")
        resume_from = int(override) if isinstance(override, int) and override > 0 else job.get("current_episode", 0)
        if override:
            print(f"[TGHirayi_v2] Siguiente episodio explícito: {override}", flush=True)

        # Limpiar caché del canal conservando el PRIMER episodio pendiente.
        # El fichero ya descargado del episodio a procesar se conserva y se reutiliza
        # (reanudación tras un fallo de subida). El resto del canal se elimina.
        first_pending = resume_from if resume_from > 0 else 1
        ep = _fetch_episode_by_number(job["item_id"], first_pending)
        keep_msg = int(ep.get("telegram_msg_id") or ep.get("msg_id") or 0) if ep else None
        print(f"[TGHirayi_v2] Limpiando caché del canal (conservando ep.{first_pending}, msg={keep_msg})", flush=True)
        _cleanup_cache_except(source_channel_id, keep_msg)

        # 1. COVER: ya NO se copia aquí. Se copia justo antes del primer vídeo subido
        #    (regla general: nunca dejar un cover huérfano si el job falla a mitad).
        #    Flag de estado para saber si ya se copió (reanudación / flujo archive).
        #    Para jobs ARCHIVE el flag NO se fuerza aquí: lo gestiona _archive_upload_phase
        #    (solo marca True tras subir con éxito el PRIMER vídeo). Si se forzara con
        #    resume_from>0, un reinicio durante el primer vídeo (cover ya copiado pero vídeo
        #    sin subir) dejaría el cover huérfano. En jobs NORMAL: solo resume_from>1
        #    implica cover publicado (ep.1 completado). Con resume_from<=1 se VERIFICA
        #    el cover real en destino (no basta el flag: un reinicio entre
        #    current_episode=1 y la copia dejaba el título sin cover).
        if not job.get("is_archive"):
            if resume_from > 1:
                job["_cover_done"] = True
            else:
                try:
                    _ok = await _verify_cover_uploaded(job, client, destinations)
                except Exception:
                    _ok = False
                job["_cover_done"] = bool(_ok)
            print(f"[TGHirayi_v2] Cover programado para justo antes del 1er vídeo (_cover_done={job['_cover_done']})", flush=True)

        # 2. EPISODIOS (pipeline: descargar ep.N+1 mientras se sube ep.N)
        episodes = _fetch_episodes_sync(job["item_id"])
        total = len(episodes)
        job["total_episodes"] = total or job.get("total_episodes", 0)
        if not episodes:
            job["status"] = "error"
            job["error"] = (f"Sin episodios para '{job.get('title')}' en su variante ({job.get('item_id')}): "
                            f"sin préstamo entre variantes. Re-escanea el canal.")
            job["status_text"] = job["error"]
            _persist_job(job)
            print(f"[TGHirayi_v2] Job {job['id']} a ERROR: {job['error']}", flush=True)
            return

        # ── Detección de job tipo ARCHIVE ──
        # Categoría multimedia + todos los ficheros son archives (no vídeo/audio directo).
        # El criterio de categoría excluye juegos/consolas (no se tocan, usan tvcat_installer_*).
        _is_archive_job = _detect_archive_job(job, episodes) and bool(cfg.get("extract_archives", True))
        if use_forward:
            # Forward oculto: reenviar tal cual, sin extraer ni normalizar archives.
            _is_archive_job = False
        if _is_archive_job:
            job["is_archive"] = True
            print(f"[TGHirayi_v2] Job {job['id']} detectado como ARCHIVE ({len(episodes)} ficheros) "
                  f"cat={job.get('category')}/{job.get('subcategory')}", flush=True)
            _persist_job(job)
            await _process_archive_job(job, db, client, pyro_client, destinations, delay,
                                       source_channel_id, source_msg_id, resume_from, source_topic_id)
            return
        if job.get("is_archive"):
            # extract_archives desactivado (o archive degradado): el archive se trata como
            # episodio normal (se sube el fichero comprimido tal cual). No error.
            print(f"[TGHirayi_v2] Job {job['id']} es archive pero extract_archives=false → flujo normal", flush=True)
            job["is_archive"] = False

        # current_episode = índice 0-based del próximo a procesar (1-based en UI).
        # Guardado tras completar cada episodio → al reanudar con -1 se reprocesa el que quedó a medias.
        pending = [(i, ep) for i, ep in enumerate(episodes) if i >= max(0, resume_from - 1) and _ep_in_scope(job, ep)]
        total_pending = len(pending)
        total_dest = len(destinations)
        if not total_pending:
            print(f"[TGHirayi_v2] 0 episodios pendientes (resume_from={resume_from})", flush=True)
        # Primer pendiente real (para enganchar el cover al primer vídeo que
        # SÍ se procesa, no al primero de la lista si está omitido/partido).
        if pending:
            first_pending = pending[0][0] + 1
        if not pending and episodes:
            # Todo desmarcado: se completa generando el cover y sin vídeos.
            if not job.get("_cover_done"):
                try:
                    if job.get("force_generic_cover") or int(source_msg_id) in (-999, -1000):
                        _cm = []
                    else:
                        _cm = await _fetch_cover_messages(client, source_channel_id, source_msg_id, source_topic_id, job)
                    _cids = await _copy_cover_to_destinations(job, client, _cm, destinations, delay)
                    if _cids:
                        job["_cover_msg_ids"] = _cids
                    job["_cover_done"] = True
                except Exception as _ce:
                    print(f"[TGHirayi_v2] Cover en all-skip falló: {_ce}", flush=True)
            job["status"] = "completed"
            job["progress"] = 100.0
            job["status_text"] = "Completado (todo desmarcado: solo cover)"
            _persist_job(job)
            print(f"[TGHirayi_v2] Job {job['id']} completado sin vídeos (todo desmarcado)", flush=True)
            return

        # Episodio en curso para cada dirección (1-based; 0 = ninguno)
        dl_ep = {"n": 0}
        ul_ep = {"n": 0}

        # Estado para cálculo de velocidad (bytes/s) por dirección
        _speed_state = {
            "download": {"last_bytes": 0.0, "last_t": time.perf_counter(), "buf": deque(maxlen=_SMOOTH_WINDOW)},
            "upload": {"last_bytes": 0.0, "last_t": time.perf_counter(), "buf": deque(maxlen=_SMOOTH_WINDOW)},
        }

        def _progress(kind, current, total_bytes):
            pct = round((current / max(total_bytes, 1)) * 100, 1)
            st = _speed_state[kind]
            speed = _speed_sample(st, current)
            if speed is not None:
                job[f"{kind}_speed"] = max(0.0, speed)
            # Cronómetro de la fase POR EPISODIO: se reinicia al empezar una
            # operación nueva del episodio en curso y se congela al llegar al 100%.
            if kind == "download":
                if job.get("_dl_ep") != dl_ep["n"]:
                    job["_dl_ep"] = dl_ep["n"]
                    job["download_started"] = time.time()
                    job.pop("download_finished", None)
                if pct >= 100 and not job.get("download_finished"):
                    job["download_finished"] = time.time()
            else:
                if job.get("_ul_ep") != ul_ep["n"]:
                    job["_ul_ep"] = ul_ep["n"]
                    job["upload_started"] = time.time()
                    job.pop("upload_finished", None)
            if kind == "download":
                job["download_progress"] = pct
                job["download_episode"] = dl_ep["n"]
                txt = f"Descargando ep.{dl_ep['n']}/{total} {pct}%"
                if ul_ep["n"] and ul_ep["n"] != dl_ep["n"]:
                    txt += f" · Subiendo ep.{ul_ep['n']}/{total}"
            else:
                job["upload_progress"] = pct
                job["upload_episode"] = ul_ep["n"]
                txt = f"Subiendo ep.{ul_ep['n']}/{total} {pct}%"
                if dl_ep["n"] and dl_ep["n"] != ul_ep["n"]:
                    txt += f" · Descargando ep.{dl_ep['n']}/{total}"
            job["status_text"] = txt
            _persist_job(job)

        next_dl_task = None
        _failed_eps = []

        for slot in range(total_pending):
            if _worker_paused or not _worker_running:
                if next_dl_task is not None:
                    next_dl_task.cancel()
                job["status"] = "paused_by_worker"
                job["status_text"] = "Pausado por usuario"
                _persist_job(job)
                return

            ep_idx, episode = pending[slot]
            ep_num = ep_idx + 1

            # F5: si todos los destinos están omitidos (topics ya existen), no
            # descargar nada (los episodios se saltan abajo; el cover sí se copia).
            try:
                _omit_map_ep = job.get("_omitted") or {}
                _all_omit_ep = bool(_omit_map_ep) and all(
                    str(_d.get("id") or _d.get("channel_id")) in _omit_map_ep
                    for _d in destinations)
            except Exception:
                _all_omit_ep = False

            if (not first_real) or _all_omit_ep:
                # Todo telegram (origen propio + CB1=false): no se descarga media del origen
                media_data = []
                next_dl_task = None
            else:
                # Obtener media del episodio actual (prefetch ya lanzado, o descarga inicial)
                if next_dl_task is not None:
                    dl_ep["n"] = ep_num
                    job["current_episode"] = ep_num  # resiliencia: marcar antes de procesar
                    media_data = await next_dl_task
                    next_dl_task = None
                    job["download_progress"] = 100.0
                    _persist_job(job)
                else:
                    job["current_episode"] = ep_num
                    dl_ep["n"] = ep_num
                    job["status_text"] = f"Descargando ep.{ep_num}/{total}..."
                    _persist_job(job)
                    print(f"[TGHirayi_v2] Descargando episodio {ep_num}/{total}", flush=True)
                    media_data = await _download_episode_media(client, episode, source_channel_id, _progress,
                                                               normalize_mp4=normalize_mp4, audio_lang=norm_audio, sub_lang=norm_sub,
                                                               streaming_mkv=streaming_mkv, job=job)
                    job["download_progress"] = 100.0
                    _persist_job(job)

                # Lanzar descarga del SIGUIENTE episodio en paralelo (si el
                # paralelismo está activo; si no, cada episodio se descarga en
                # el flujo principal con toda la velocidad disponible).
                next_dl_task = None
                if parallel_dl and slot + 1 < total_pending:
                    n_idx, n_ep = pending[slot + 1]
                    dl_ep["n"] = n_idx + 1
                    next_dl_task = asyncio.create_task(
                        _download_episode_media(client, n_ep, source_channel_id, _progress,
                                                normalize_mp4=normalize_mp4, audio_lang=norm_audio, sub_lang=norm_sub,
                                                streaming_mkv=streaming_mkv, job=job)
                    )
                    print(f"[TGHirayi_v2] Prefetch descarga ep.{n_idx+1}/{total} (paralelo)", flush=True)

            # Subir/copiar el actual a todos los destinos
            ul_ep["n"] = ep_num
            job["status_text"] = f"Procesando ep.{ep_num}/{total}..."
            job["upload_progress"] = 0.0

            # ── Cover justo antes del primer vídeo real (todos los flujos) ──
            # Solo se verifica/copia para el PRIMER episodio; el resto lo da por
            # sentado (flag confirmado tras subir ep.1 a todos los destinos).
            if not job.get("_cover_done") and ep_num == (first_pending or 1):
                job["status_text"] = "Copiando cover..."
                _persist_job(job)
                if int(source_msg_id) in (-999, -1000) or job.get("force_generic_cover"):
                    cover_messages = []  # genérico, no pedir a Telegram (ya en cache -3 / partido)
                    _cids = await _copy_cover_to_destinations(job, client, cover_messages, destinations, delay)
                    if _cids:
                        job["_cover_msg_ids"] = _cids
                    print(f"[TGHirayi_v2] Cover genérico copiado", flush=True)
                else:
                    cover_messages = await _fetch_cover_messages(client, source_channel_id, source_msg_id, source_topic_id, job)
                    _cids = await _copy_cover_to_destinations(job, client, cover_messages, destinations, delay)
                    if _cids:
                        job["_cover_msg_ids"] = _cids
                    _ncop = sum(len(v or []) for v in (_cids or {}).values())
                    print(f"[TGHirayi_v2] Cover: origen {len(cover_messages)} msgs → copiados {_ncop} en {len(_cids or {})} destinos", flush=True)
            _persist_job(job)
            if first_real:
                print(f"[TGHirayi_v2] Descargado ep.{ep_num} ({len(media_data)} archivos), subiendo...", flush=True)
            else:
                print(f"[TGHirayi_v2] Ep.{ep_num} copia telegram (origen propio), sin descarga", flush=True)

            # Episodio sin media (el prefetch falló, p. ej. blip de red): UN reintento
            # de descarga directa antes de omitir. Sin esto un fallo transitorio
            # dejaba el episodio fuera para siempre (el job se completaba sin él).
            # F5 all-omit: no hay nada que subir → avance limpio sin descargar.
            if first_real and not media_data and _all_omit_ep:
                print(f"[TGHirayi_v2] ep.{ep_num} omitido en todos los destinos (topics ya existen), sin descarga", flush=True)
                job["current_episode"] = ep_num + 1
                job["_cover_done"] = True
                _persist_job(job)
                continue
            if first_real and not media_data:
                print(f"[TGHirayi_v2] ep.{ep_num} sin media (prefetch falló), reintentando descarga directa...", flush=True)
                try:
                    media_data = await _download_episode_media(client, episode, source_channel_id, _progress,
                                                               normalize_mp4=normalize_mp4, audio_lang=norm_audio, sub_lang=norm_sub,
                                                               streaming_mkv=streaming_mkv, job=job)
                except Exception as _e_rd:
                    print(f"[TGHirayi_v2] ep.{ep_num} reintento falló: {_e_rd}", flush=True)
                    media_data = []
            # Si sigue sin media: NO intentar subidas ni copias (generaba errores
            # confusos y mensajes sueltos). Tras 3 pasadas sin media el origen no
            # tiene documento (¿borrado?) → error claro en vez de loop infinito.
            if first_real and not media_data:
                _dlf = job.setdefault("_dl_fails", {})
                _dlf[str(ep_num)] = int(_dlf.get(str(ep_num), 0) or 0) + 1
                if _dlf[str(ep_num)] >= 3:
                    job["status"] = "error"
                    job["error"] = (f"Ep.{ep_num} (msg {episode.get('telegram_msg_id') or episode.get('msg_id')}) "
                                    f"sin media descargable tras 3 intentos: el mensaje origen no tiene documento "
                                    f"(¿borrado?). Re-escanea el canal o elimina el job.")
                    job["status_text"] = job["error"]
                    _persist_job(job)
                    print(f"[TGHirayi_v2] Job {job['id']} a ERROR: {job['error']}", flush=True)
                    return
                print(f"[TGHirayi_v2] ep.{ep_num} sin media descargada, se omite (reintentará al reanudar, intento {_dlf[str(ep_num)]}/3)", flush=True)
                job["status_text"] = f"Ep.{ep_num} sin media, omitido (reintento al reanudar)"
                _failed_eps.append(ep_num)
                _persist_job(job)
                continue

            # Reintentos por episodio ante errores transitorios de cliente
            # (pyro/telethon caídos a mitad de subida): refresca pyro y reintenta
            # el episodio (máx 3); si agota, a fallidos (auto-reencola desde el
            # primero) en vez de abortar el job.
            _ep_attempt = 0
            _ep_ok = False
            while True:
                first_dest_msg_ids = None
                try:

                    for dest_idx, dest in enumerate(destinations):
                        if _worker_paused:
                            if next_dl_task is not None:
                                next_dl_task.cancel()
                            return
                        job["current_destination"] = dest_idx
                        ep_portion = 1.0 / max(total, 1)
                        dest_portion = ep_portion / max(total_dest, 1)
                        job["progress"] = round((ep_idx * ep_portion + dest_idx * dest_portion) * 100, 1)
                        job["upload_progress"] = round((dest_idx / max(total_dest, 1)) * 100, 1)
                        # F5: destino omitido → topic existente (sin crear), episodios
                        # saltados (el cover ya se copió al topic existente).
                        _okey = str(dest.get("id") or dest.get("channel_id"))
                        _is_omit = _okey in (job.get("_omitted") or {})
                        if _is_omit:
                            topic_id = (job.get("_omitted") or {}).get(_okey)
                        else:
                            topic_id = await _resolve_topic_id_async(client, dest, job["title"], job)

                        if _is_omit:
                            _dn = dest.get('name', '?')
                            job["status_text"] = f"Omitido en dest {_dn}: Topic ya existe (ep.{ep_num}/{total})"
                            _persist_job(job)
                            if dest_idx == 0 and "_omit_src_ids" not in job:
                                # dest-0 es la fuente para la copia telegram al resto
                                try:
                                    job["_omit_src_ids"] = await _get_topic_episode_msg_ids(client, dest, int(topic_id))
                                except Exception:
                                    job["_omit_src_ids"] = []
                                _persist_job(job)
                            if dest_idx == 0:
                                first_dest_msg_ids = list(job.get("_omit_src_ids") or [])
                            await asyncio.sleep(delay)
                            if "_uploaded_to" not in job:
                                job["_uploaded_to"] = {}
                            job["_uploaded_to"][dest.get("channel_id")] = True
                            continue
                        if dest_idx == 0:
                            # Destino 1: real si first_real (firewall o CB1), si no telegram directo desde el origen
                            if first_real:
                                job["status_text"] = f"Subiendo ep.{ep_num}/{total} a {dest.get('name','?')}..."
                                _persist_job(job)
                                sent_ids = await _upload_episode_to_destination(client, pyro_client, episode, media_data, dest, topic_id, delay, _progress, job=job)
                            elif use_forward:
                                # OPCIÓN OCULTA: forward directo aunque el origen sea de terceros.
                                # Sin descarga ni subida. Si falla (NoForwards/sin acceso) → fallback
                                # a copia real del episodio para no dejar el job a medias.
                                job["status_text"] = f"Reenviando (telegram) ep.{ep_num}/{total} a {dest.get('name','?')}..."
                                _persist_job(job)
                                sent_ids = await _forward_episode_from_origin(client, source_channel_id, episode, dest, topic_id, delay, job)
                                if not sent_ids:
                                    print(f"[TGHirayi_v2] Forward falló en ep.{ep_num}, fallback a copia real", flush=True)
                                    job["status_text"] = f"Subiendo ep.{ep_num}/{total} a {dest.get('name','?')} (fallback)..."
                                    _persist_job(job)
                                    dl_ep["n"] = ep_num
                                    media_data = await _download_episode_media(client, episode, source_channel_id, _progress,
                                                                                normalize_mp4=normalize_mp4, audio_lang=norm_audio, sub_lang=norm_sub,
                                                                                streaming_mkv=streaming_mkv, job=job)
                                    sent_ids = await _upload_episode_to_destination(client, pyro_client, episode, media_data, dest, topic_id, delay, _progress, job=job)
                            else:
                                job["status_text"] = f"Copiando (telegram) ep.{ep_num}/{total} a {dest.get('name','?')}..."
                                _persist_job(job)
                                sent_ids = await _copy_episode_from_origin(client, source_channel_id, episode, dest, topic_id, delay, job)
                            first_dest_msg_ids = sent_ids
                        elif cb2_active:
                            # Resto: copia REAL desde el media descargado del origen (cada destino su file_id)
                            job["status_text"] = f"Subiendo ep.{ep_num}/{total} a {dest.get('name','?')}..."
                            _persist_job(job)
                            await _upload_episode_to_destination(client, pyro_client, episode, media_data, dest, topic_id, delay, _progress, job=job)
                        else:
                            # Resto: copia telegram desde el primer destino (sin re-subir).
                            # F5: si dest-0 fue omitido y su topic no dio msg_ids (vacío),
                            # fallback a copia desde el origen cuando es propio.
                            job["status_text"] = f"Copiando (telegram) ep.{ep_num}/{total} a {dest.get('name','?')}..."
                            _persist_job(job)
                            if first_dest_msg_ids:
                                await _copy_episode_from_first(client, destinations[0], dest, first_dest_msg_ids, topic_id, delay, job)
                            elif not first_real:
                                await _copy_episode_from_origin(client, source_channel_id, episode, dest, topic_id, delay, job)
                            else:
                                print(f"[TGHirayi_v2] ep.{ep_num} sin fuente en dest-0 omitido para {dest.get('name','?')} (topic vacío)", flush=True)
                        await asyncio.sleep(delay)
                        if "_uploaded_to" not in job:
                            job["_uploaded_to"] = {}
                        job["_uploaded_to"][dest.get("channel_id")] = True
                    _ep_ok = True
                    break
                except Exception as _e_ep:
                    _e_txt = str(_e_ep)
                    if _is_auth_dead(_e_txt):
                        # Sesión muerta: reintentar es inútil → aborta al error
                        # general (pausa worker + mensaje de regenerar sesión).
                        raise
                    _transient = any(k in _e_txt for k in _TRANSIENT_CLIENT_ERRORS)
                    _ep_attempt += 1
                    if not _transient:
                        raise
                    if _ep_attempt >= 3:
                        print(f"[TGHirayi_v2] ep.{ep_num} agotados 3 reintentos, a fallidos: {_e_txt[:150]}", flush=True)
                        _failed_eps.append(ep_num)
                        _persist_job(job)
                        break
                    print(f"[TGHirayi_v2] ep.{ep_num} error transitorio ({_e_txt[:150]}), reintento {_ep_attempt}/3", flush=True)
                    job["status_text"] = f"Ep.{ep_num} reintentando ({_ep_attempt}/3)..."
                    _persist_job(job)
                    await asyncio.sleep(10 * _ep_attempt)
                    try:
                        pyro_client = await asyncio.wait_for(_refresh_pyrogram_client(), 30)
                    except Exception as _e_rf:
                        print(f"[TGHirayi_v2] refresh pyro falló: {_e_rf}", flush=True)
                    try:
                        if await _verify_cover_uploaded(job, client, destinations):
                            job["_cover_done"] = True
                            _persist_job(job)
                    except Exception:
                        pass
            if not _ep_ok:
                media_data = None
                continue


            # Episodio subido a todos los destinos → marcar siguiente como próximo a procesar.
            # El cover se confirma SOLO tras subir con éxito el primer episodio: si la subida
            # del primer episodio falla tras copiar el cover, en el reintento se re-copia el
            # cover junto al episodio (nunca cover huérfano ni episodio sin su cover).
            job["current_episode"] = ep_num + 1
            try:
                (job.get("_dl_fails") or {}).pop(str(ep_num), None)
            except Exception:
                pass
            job["upload_finished"] = time.time()
            # Cover confirmado: llegar aquí implica que el episodio se subió a todos los
            # destinos sin error → el cover ya está pegado a su primer vídeo.
            job["_cover_done"] = True
            _persist_job(job)

            # Limpiar caché del episodio ya subido con éxito. Solo se conserva el
            # pendiente (vía _cleanup_cache_except al reanudar) por si la subida
            # falla y hay que reutilizar el fichero descargado.
            if first_real:
                ep_chat = _extract_channel_id(episode.get("telegram_link", "")) or source_channel_id
                ep_msg = int(episode.get("telegram_msg_id") or episode.get("msg_id") or 0)
                if ep_chat and ep_msg:
                    _delete_episode_cache(ep_chat, ep_msg)
                    print(f"[TGHirayi_v2] Caché de ep.{ep_num} eliminado tras subida", flush=True)

            media_data = None

        # Esperar a que termine la última descarga prefetch (si quedó alguna)
        if next_dl_task is not None:
            try:
                await next_dl_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[TGHirayi_v2] Error en prefetch final: {e}", flush=True)

        # Episodios fallidos sin media: NO completar (quedarían fuera para siempre).
        # Se reencola desde el primero fallido para reintentarlos.
        if _failed_eps:
            _first_failed = min(_failed_eps)
            job["status"] = "queued"
            job["current_episode"] = _first_failed
            job["status_text"] = f"Reintentando {len(_failed_eps)} episodio(s): {sorted(_failed_eps)}"
            job.pop("next_episode", None)
            _persist_job(job)
            print(f"[TGHirayi_v2] Job {job['id']} con fallidos {sorted(_failed_eps)}, reencolado desde ep.{_first_failed}", flush=True)
            return

        job["status"] = "completed"
        job["progress"] = 100.0
        job["download_progress"] = 100.0
        job["upload_progress"] = 100.0
        try:
            _omit_names = [_d.get("name", "?") for _d in destinations
                           if str(_d.get("id") or _d.get("channel_id")) in (job.get("_omitted") or {})]
        except Exception:
            _omit_names = []
        if _omit_names:
            job["status_text"] = "Completado (omitido en " + ", ".join(_omit_names) + ": Topic ya existe)"
        else:
            job["status_text"] = "Completado"
        job.pop("next_episode", None)  # override de un solo uso → vuelve a auto
        _persist_job(job)
        print(f"[TGHirayi_v2] Job {job['id']} completado: {job['title']}", flush=True)

    except Exception as e:
        print(f"[TGHirayi_v2] ERROR en _process_job: {e}", flush=True)
        import traceback
        traceback.print_exc()
        job["status"] = "error"
        if _is_auth_dead(str(e)):
            job["error"] = ("Sesión de Telegram invalidada o cliente caído "
                            "(¿dos gateways a la vez? ¿cambio de IP/VPN?). Regenera la sesión del userbot "
                            "en Configuración y reanuda la cola. Detalle: " + str(e)[:200])
            job["status_text"] = "Sesión invalidada: regenera sesión y reanuda"
            try:
                globals()["_worker_paused"] = True
            except Exception:
                pass
            print(f"[TGHirayi_v2] Worker pausado por sesión invalidada", flush=True)
        else:
            job["error"] = str(e)
        _persist_job(job)
    # No desconectar cliente: es del pool compartido de userbot_service


def _resolve_topic_id(dest: dict, title: str) -> Optional[int]:
    """Resuelve el topic_id segun la topologia del destino."""
    topo = dest.get("topology", 1)
    if topo == 1:
        return None  # Chat lineal, sin topic
    elif topo == 2:
        return dest.get("topic_id")  # Topic fijo configurado
    elif topo == 3:
        # Topic por nombre del titulo: se resuelve en _resolve_topic_id_async (requiere client)
        return None
    return None


async def _list_forum_topics(client, dest: dict, job: dict = None) -> list:
    """Topics del canal foro vía servicio central. Devuelve [{id, title}]."""
    try:
        items = await _svc().list_forum_topics(dest["channel_id"], **_svc_creds(job))
        return items or []
    except Exception as e:
        print(f"[TGHirayi_v2] Error listando topics: {e}", flush=True)
        return []


async def _create_forum_topic(client, dest: dict, title: str, job: dict = None) -> Optional[int]:
    """Crea un topic vía servicio central y devuelve su topic_id."""
    try:
        tid = await _svc().create_forum_topic(dest["channel_id"], title, **_svc_creds(job))
        if tid:
            print(f"[TGHirayi_v2] Topic creado: '{title}' -> {tid}", flush=True)
            return int(tid)
    except Exception as e:
        print(f"[TGHirayi_v2] Error creando topic: {e}", flush=True)
    return None


# ─── Caché de topics por destino (F4: completa con TTL + delta últimos 100) ───
_TOPIC_CACHE: dict = {}
_TOPIC_CACHE_LOCK = None

def _topic_cache_key(dest: dict) -> str:
    return str(dest.get("id") or dest.get("channel_id") or dest.get("name") or 'dest')

def _topic_norm(title) -> str:
    return (title or '').strip()

def _topic_cache_add(dest: dict, title: str, tid: int):
    try:
        _TOPIC_CACHE[_topic_cache_key(dest)]["map"][_topic_norm(title)] = int(tid)
    except Exception:
        pass

def _topics_to_map(items) -> dict:
    m: dict = {}
    for t in items or []:
        nt = _topic_norm((t.get("title") if isinstance(t, dict) else getattr(t, 'title', '')) or '')
        if nt and nt not in m:
            _tid = (t.get("id") if isinstance(t, dict) else getattr(t, 'id', None))
            if _tid:
                m[nt] = int(_tid)
    return m

async def _fetch_recent_topics(client, dest: dict, limit: int = 100, job: dict = None) -> list:
    # Delta rápido: 1 sola página vía cliente directo; fallback al servicio.
    try:
        from telethon.tl.functions.messages import GetForumTopicsRequest
        entity = await client.get_entity(int(dest["channel_id"]))
        peer = await client.get_input_entity(entity)
        res = await client(GetForumTopicsRequest(
            peer=peer, offset_date=0, offset_id=0, offset_topic=0, limit=int(limit)))
        return list(getattr(res, 'topics', []) or [])
    except Exception:
        return await _list_forum_topics(client, dest, job)

async def _get_topics_map_cached(client, dest: dict, job: dict = None) -> dict:
    """Mapa {norm_title: topic_id} con TTL. Completa al expirar; delta 100 en ventana vigente."""
    global _TOPIC_CACHE_LOCK
    import time as _time
    try:
        import asyncio as _aio
        if _TOPIC_CACHE_LOCK is None:
            _TOPIC_CACHE_LOCK = _aio.Lock()
    except Exception:
        _TOPIC_CACHE_LOCK = None
    key = _topic_cache_key(dest)
    try:
        ttl_min = max(5, min(1440, int(_load_config().get("topics_cache_ttl_min", 60) or 60)))
    except Exception:
        ttl_min = 60
    now = _time.time()
    entry = _TOPIC_CACHE.get(key)
    if entry and (now - float(entry.get("ts", 0))) < ttl_min * 60:
        try:
            merged = dict(entry.get("map", {}))
            for nt, _tid in _topics_to_map(await _fetch_recent_topics(client, dest, 100, job)).items():
                if nt not in merged:
                    merged[nt] = _tid
            entry["map"] = merged
            return merged
        except Exception as e:
            print(f"[TGHirayi_v2] Error delta topics ({key}): {e}", flush=True)
            return dict(entry.get("map", {}))
    lock = _TOPIC_CACHE_LOCK
    if lock is not None:
        await lock.acquire()
    try:
        entry2 = _TOPIC_CACHE.get(key)
        if entry2 and (now - float(entry2.get("ts", 0))) < ttl_min * 60:
            return dict(entry2.get("map", {}))
        m = _topics_to_map(await _list_forum_topics(client, dest, job))
        _TOPIC_CACHE[key] = {"ts": now, "map": m}
        return m
    except Exception as e:
        print(f"[TGHirayi_v2] Error listado completo topics ({key}): {e}", flush=True)
        if entry:
            return dict(entry.get("map", {}))
        return {}
    finally:
        try:
            if lock is not None:
                lock.release()
        except Exception:
            pass

async def _topic_find_cached(client, dest: dict, title: str, job: dict = None) -> Optional[int]:
    try:
        m = await _get_topics_map_cached(client, dest, job)
        tid = m.get(_topic_norm(title))
        if tid:
            print(f"[TGHirayi_v2] Topic existente en caché: '{title}' -> {tid}", flush=True)
            return int(tid)
    except Exception as e:
        print(f"[TGHirayi_v2] Error buscando topic en caché: {e}", flush=True)
    return None

async def _verify_topic_alive(client, dest: dict, topic_id: int) -> bool:
    """Verificación viva antes de saltar: confirma que el topic_id sigue existiendo."""
    try:
        from telethon.tl.functions.messages import GetForumTopicsByIDRequest as _GTB
    except Exception:
        return True  # Sin API de verificación: confía en caché
    try:
        entity = await client.get_entity(int(dest["channel_id"]))
        peer = await client.get_input_entity(entity)
        res = await client(_GTB(peer=peer, topics=[int(topic_id)]))
        topics = list(getattr(res, 'topics', []) or [])
        return len(topics) > 0
    except Exception as e:
        print(f"[TGHirayi_v2] Error verificando topic {topic_id}: {e} → se sube (fail-safe)", flush=True)
        return False

async def _get_topic_episode_msg_ids(client, dest: dict, topic_id: int) -> List[int]:
    """msg_ids de episodios (vídeos) del topic existente en dest-0, orden ASC. F6."""
    out: List[int] = []
    try:
        entity = await client.get_entity(int(dest["channel_id"]))
        async for msg in client.iter_messages(entity, reply_to=int(topic_id), limit=5000):
            try:
                media = getattr(msg, 'media', None)
                doc = getattr(media, 'document', None) if media else None
                if doc is not None:
                    out.append(int(getattr(msg, 'id', 0)))
            except Exception:
                continue
    except Exception as e:
        print(f"[TGHirayi_v2] Error listando episodios del topic {topic_id}: {e}", flush=True)
        return []
    out = sorted([i for i in out if i])
    return out


async def _resolve_topic_id_async(client, dest: dict, title: str, job: dict) -> Optional[int]:
    """Resuelve el topic_id para un destino. Para topología 3 busca por nombre del título
    en los topics existentes del grupo (vía caché F4); si no existe coincidencia exacta, lo crea.
    El topic_id se cachea en el job (_topics) para reutilizarlo en todos los episodios."""
    topo = dest.get("topology", 1)
    if topo == 1:
        return None
    elif topo == 2:
        return dest.get("topic_id")
    elif topo != 3:
        return None

    dest_key = str(dest.get("id") or dest.get("channel_id") or dest.get("name") or 'dest')
    cached = job.setdefault("_topics", {})
    if dest_key in cached:
        return cached[dest_key]

    tid = await _topic_find_cached(client, dest, title, job)

    if not tid:
        try:
            tid = await _create_forum_topic(client, dest, title, job)
            if tid:
                _topic_cache_add(dest, title, int(tid))
        except Exception as e:
            print(f"[TGHirayi_v2] Error creando topic '{title}': {e}", flush=True)

    if tid:
        cached[dest_key] = int(tid)
        _persist_job(job)
    return int(tid) if tid else None


def _collect_plugin_dbs():
    """Recolecta las DBs de los plugins con catalogo (db_path, plugin_name)."""
    import os
    dbs = []
    try:
        from tvcat.gateway import get_enabled_plugin_dbs_with_names
        dbs = list(get_enabled_plugin_dbs_with_names())
    except Exception:
        pass
    if not dbs:
        plugins_root = os.path.dirname(_PLUGIN_DIR)
        if os.path.isdir(plugins_root):
            for name in sorted(os.listdir(plugins_root)):
                pdb = os.path.join(plugins_root, name, "data", "tvcat.db")
                if os.path.isfile(pdb):
                    dbs.append((pdb, name))
    return dbs


def _fetch_item_data_sync(item_id: str) -> Optional[dict]:
    """Obtiene datos del item desde el catalogo central o las DBs de plugins (sincrono).
    Colecciones locales (COL-): viven en collections_local, no en unified_catalog;
    se devuelve dict sintético para evitar barrer DBs de plugins sin esa tabla."""
    import sqlite3
    from tvcat.services.userbot_service import DB_PATH as CENTRAL_DB
    try:
        if str(item_id or "").startswith("COL-"):
            try:
                from tvcat.services.catalog_service import get_local_collection
                import json as _js
                loc = get_local_collection(item_id)
                if loc:
                    try:
                        n = len(_js.loads(loc.get("entries_json") or "[]") or [])
                    except Exception:
                        n = 0
                    return {"item_id": item_id, "title": loc.get("name") or "Colección",
                            "telegram_link": "", "telegram_msg_id": 0,
                            "is_collection": 1, "local": 1,
                            "collection_name": loc.get("name") or "",
                            "collection_serial": loc.get("serial") or "",
                            "entries_count": n}
            except Exception:
                pass
            return None
    except Exception:
        pass
    try:
        conn = sqlite3.connect(CENTRAL_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM unified_catalog WHERE item_id=? LIMIT 1",
            (item_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception as e:
        print(f"[TGHirayi_v2] Error fetching item data: {e}", flush=True)
    for db_path, plugin_name in _collect_plugin_dbs():
        if not os.path.isfile(db_path):
            continue
        try:
            pconn = sqlite3.connect(db_path)
            pconn.row_factory = sqlite3.Row
            try:
                # Plugins sin catálogo (card_frames, enricher, peers...): saltar
                # en silencio en vez de loguear "no such table" por cada uno.
                _has = pconn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_catalog' LIMIT 1"
                ).fetchone()
                if not _has:
                    continue
                prow = pconn.execute(
                    "SELECT * FROM unified_catalog WHERE item_id=? LIMIT 1",
                    (item_id,)
                ).fetchone()
            finally:
                pconn.close()
            if prow:
                return dict(prow)
        except Exception as e:
            print(f"[TGHirayi_v2] Error fetching item data in {plugin_name}: {e}", flush=True)
    return None


def _fetch_episodes_sync(item_id: str) -> list:
    """Obtiene episodios SOLO del propio item_id (sin préstamo entre variantes:
    cada variante copia exclusivamente sus mensajes, aunque compartan nombre)."""
    import sqlite3, os
    from tvcat.services.userbot_service import DB_PATH as CENTRAL_DB

    def _own_eps(conn, tag: str):
        try:
            cat_row = conn.execute("SELECT id FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
        except Exception:
            return []
        if not cat_row:
            return []
        int_id = str(cat_row["id"])
        try:
            eps = [dict(e) for e in conn.execute(
                "SELECT * FROM item_episodes WHERE item_id=? OR item_id=? ORDER BY episode_number ASC",
                (item_id, int_id)).fetchall()]
        except Exception:
            return []
        if eps:
            print(f"[TGHirayi_v2] {len(eps)} episodios de {item_id} ({tag})", flush=True)
            for ep in eps:
                print(f"[TGHirayi_v2]   ep#{ep.get('episode_number','?')}: id={ep.get('id')} msg={ep.get('telegram_msg_id','?')} link={ep.get('telegram_link','?')}", flush=True)
        return eps

    try:
        conn = sqlite3.connect(CENTRAL_DB)
        conn.row_factory = sqlite3.Row
        try:
            eps = _own_eps(conn, "central")
        finally:
            conn.close()
        if eps:
            return eps
    except Exception as e:
        print(f"[TGHirayi_v2] Error central: {e}", flush=True)
        import traceback
        traceback.print_exc()

    # Fallback plugin DBs (solo filas propias)
    print("[TGHirayi_v2] Probando plugin DBs...", flush=True)
    dbs = list(_collect_plugin_dbs())
    print(f"[TGHirayi_v2] {len(dbs)} plugin DBs via _collect_plugin_dbs", flush=True)

    for db_path, plugin_name in dbs:
        print(f"[TGHirayi_v2]   {plugin_name}: {db_path} exists={os.path.isfile(db_path)}", flush=True)
        if not os.path.isfile(db_path):
            continue
        try:
            pconn = sqlite3.connect(db_path)
            pconn.row_factory = sqlite3.Row
            # Plugins sin catálogo (card_frames, enricher, peers...): saltar en silencio.
            _ptab = pconn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_catalog' LIMIT 1"
            ).fetchone()
            if not _ptab:
                pconn.close()
                continue
            try:
                peps = _own_eps(pconn, plugin_name)
            finally:
                pconn.close()
            if peps:
                return peps
        except Exception as ex:
            print(f"[TGHirayi_v2] Error en {plugin_name}: {ex}", flush=True)

    print(f"[TGHirayi_v2] 0 episodios final (item_id={item_id})", flush=True)
    return []


def _fetch_episode_by_number(item_id: str, number: int) -> Optional[dict]:
    """Devuelve el episodio 'number' (1-based) de un item, o None."""
    episodes = _fetch_episodes_sync(item_id)
    for e in episodes:
        if int(e.get("episode_number") or 0) == int(number):
            return e
    return None


# ─── Normalización MP4 (ffmpeg) ───────────────────────────────────
def _find_ffmpeg() -> Optional[str]:
    """Busca ffmpeg en PATH (Linux/Docker), bundle propio o bundle del v1 (Windows)."""
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    bundle = os.path.join(_PLUGIN_DIR, "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(bundle):
        return bundle
    sib = os.path.join(os.path.dirname(_PLUGIN_DIR), "tvcat_TGHirayi", "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(sib):
        return sib
    return None


def _find_7z() -> Optional[str]:
    """Busca 7z: ruta configurada → PATH (Linux/Docker p7zip) → tools/ del plugin (Windows portable)."""
    import shutil
    cfg = _load_config()
    cpath = (cfg.get("seven_zip_path") or "").strip()
    if cpath and os.path.isfile(cpath):
        return cpath
    for name in ("7z", "7za", "7z.exe", "7za.exe"):
        p = shutil.which(name)
        if p:
            return p
    bundle = os.path.join(_PLUGIN_DIR, "tools", "7z.exe")
    if os.path.isfile(bundle):
        return bundle
    sib = os.path.join(os.path.dirname(_PLUGIN_DIR), "tvcat_TGHirayi", "tools", "7z.exe")
    if os.path.isfile(sib):
        return sib
    return None


def _find_unrar() -> Optional[str]:
    """Busca unrar: ruta configurada → PATH → tools/ del plugin."""
    import shutil
    cfg = _load_config()
    cpath = (cfg.get("unrar_path") or "").strip()
    if cpath and os.path.isfile(cpath):
        return cpath
    p = shutil.which("unrar")
    if p:
        return p
    bundle = os.path.join(_PLUGIN_DIR, "tools", "unrar.exe")
    if os.path.isfile(bundle):
        return bundle
    sib = os.path.join(os.path.dirname(_PLUGIN_DIR), "tvcat_TGHirayi", "tools", "unrar.exe")
    if os.path.isfile(sib):
        return sib
    return None


def _ffprobe_duration(file_path: str) -> float:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return 0.0
    ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
    if not os.path.isfile(ffprobe):
        ffprobe = "ffprobe"
    import subprocess
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except Exception:
        return 0.0


def _is_video_file(file_name: str) -> bool:
    ext = os.path.splitext(file_name or "")[1].lower()
    return ext in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".mpeg", ".mpg")


_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wav", ".opus", ".wma"}
_ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".arj", ".tar", ".gz", ".tgz", ".bz2",
                 ".xz", ".cab", ".iso", ".z", ".lz", ".lzma", ".r00", ".r01",
                 ".z01", ".z02", ".001", ".002"}


def _is_audio_file(file_name: str) -> bool:
    ext = os.path.splitext(file_name or "")[1].lower()
    return ext in _AUDIO_EXTS


def _is_archive_file(file_name: str) -> bool:
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext in _ARCHIVE_EXTS:
        return True
    # Volúmenes multiparte con patrón (WinRAR .partN, .rNN, .zNN, .NNN)
    name = (file_name or "").lower()
    if re.search(r'\.part\d+$', name):
        return True
    # Extensiones numéricas de continuación (.001, .002, .003... → 7z/rar multiparte)
    if re.search(r'\.\d{2,3}$', name):
        return True
    return False


_MEDIA_CATS = {"media", "audio", "video", "peliculas", "series", "tv", "anime"}


def _detect_archive_job(job: dict, episodes: list) -> bool:
    """Un job es ARCHIVE si es categoría multimedia y TODOS sus ficheros son archives."""
    try:
        _cat = (job.get("category") or "").lower()
        _sub = (job.get("subcategory") or "").lower()
        _is_media_cat = _cat in _MEDIA_CATS or _sub in _MEDIA_CATS
        _names = [(e.get("file_name") or e.get("title") or "") for e in episodes]
        _all_archive = bool(_names) and all(_is_archive_file(n) for n in _names if n)
        return bool(_is_media_cat and _all_archive)
    except Exception:
        return False


def _archive_can_open(seven_zip: str, archive_path: str) -> bool:
    """True si 7z puede abrir el fichero como archive independiente (fuente de verdad).
    Los volúmenes de continuación (p.ej. part2.rar, .r01, .002) no se abren solos
    (7z devuelve exit != 0) → se consideran consumidos por un archive ya extraído."""
    try:
        r = subprocess.run([seven_zip, "l", archive_path],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def _is_multimedia_file(file_name: str) -> bool:
    return _is_video_file(file_name) or _is_audio_file(file_name)


def _check_free_space(job: dict, needed_bytes: int) -> bool:
    """Comprueba espacio libre en el disco del caché (margen fijo 4GB).
    Si no hay suficiente, deja el job en queued con status_text claro."""
    try:
        import shutil
        free = shutil.disk_usage(_CACHE_DIR).free
        required = needed_bytes + (4 * 1024 ** 3)
        if free < required:
            job["status_text"] = f"Sin espacio (necesita ~{required / (1024**3):.1f} GB)"
            _persist_job(job)
            return False
        return True
    except Exception as e:
        print(f"[TGHirayi_v2] Error en _check_free_space: {e}", flush=True)
        return True


def _archive_workdir(job_id: str) -> dict:
    """Carpetas de trabajo de un job archive (download/trash/extracted/preserved)."""
    base = os.path.join(_CACHE_DIR, "jobs", job_id)
    return {
        "base": base,
        "download": os.path.join(base, "download"),
        "trash": os.path.join(base, "trash"),
        "extracted": os.path.join(base, "extracted"),
        "preserved": os.path.join(base, "preserved"),
    }


def _estimate_archive_size(seven_zip, archive_path) -> int:
    """Estima el tamaño descomprimido de un archive: lee cabecera con 7z l -slt.
    Fallback: ×2 del tamaño comprimido."""
    try:
        r = subprocess.run([seven_zip, "l", "-slt", archive_path],
                           capture_output=True, text=True, timeout=60)
        total = 0
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("Size ="):
                try:
                    total += int(line.split("=", 1)[1].strip())
                except Exception:
                    pass
        if total > 0:
            return total
    except Exception:
        pass
    try:
        return os.path.getsize(archive_path) * 2
    except Exception:
        return 0


def _run_7z_extract(seven_zip, target, out_dir, password=None, progress_log=None) -> dict:
    """Ejecuta 7z x sobre un archive. Devuelve {ok, videos, consumed, wrong_password, output}.
    - 'consumed': ficheros que 7zip abrió (volúmenes). Se parsean del log verboso -bb1.
    - Si pide contraseña y password no funciona → wrong_password=True."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [seven_zip, "x", "-y", "-bb1", "-o" + out_dir]
    if password:
        cmd.append("-p" + password)
    cmd.append(target)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    except Exception as e:
        return {"ok": False, "videos": [], "consumed": [], "wrong_password": False,
                "output": f"error: {e}"}

    out = r.stdout + r.stderr
    if progress_log:
        progress_log(f"7z exit={r.returncode}")

    # Detección de error de contraseña / CRC
    low = out.lower()
    wrong_password = ("wrong password" in low or "incorrect password" in low
                      or "cannot open encrypted archive" in low
                      or ("crc failed" in low and "data error" in low))
    if r.returncode != 0 and wrong_password:
        return {"ok": False, "videos": [], "consumed": [], "wrong_password": True, "output": out[:2000]}

    # Vídeos extraídos (orden de extracción = orden en que 7z los lista)
    videos = []
    for root, _dirs, files in os.walk(out_dir):
        for fn in sorted(files):
            p = os.path.join(root, fn)
            if _is_video_file(fn) and os.path.isfile(p):
                videos.append(p)
    videos.sort()

    # Consumidos: el propio target. Los volúmenes que 7zip abrió los resuelve él solo
    # y se limpian en la siguiente iteración del bucle (7z ya no puede abrirlos como
    # archive independiente → se mueven a trash). Sin heurísticas de nombres.
    consumed = [target]

    return {"ok": r.returncode == 0, "videos": videos, "consumed": consumed,
            "wrong_password": False, "output": out[:2000]}


async def _download_archive_files(client, episodes, source_channel_id, workdir, job) -> list:
    """Descarga TODOS los ficheros (todas las partes) del título a jobs/{id}/download/
    con su nombre original. Devuelve la lista de paths descargados (en orden de episodio)."""
    os.makedirs(workdir, exist_ok=True)
    downloaded = []
    dl_cfg = _load_config()
    dl_threads = max(1, min(16, int(dl_cfg.get("download_threads", 8) or 8)))
    total = len(episodes)
    for i, ep in enumerate(episodes, 1):
        if _worker_paused or not _worker_running:
            raise RuntimeError("Worker pausado durante descarga de archive")
        chat_id = _extract_channel_id(ep.get("telegram_link", "")) or source_channel_id
        msg_id = ep.get("telegram_msg_id") or ep.get("msg_id")
        if not chat_id or not msg_id:
            _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] ep.{i} sin chat_id/msg_id, saltando")
            continue
        job["status_text"] = f"Descargando parte {i}/{total}..."
        job["download_progress"] = round(((i - 1) / max(total, 1)) * 100, 1)
        job["download_episode"] = i
        _persist_job(job)
        _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Descargando parte {i}/{total} (msg={msg_id})")

        _dl_state = {"last_bytes": 0.0, "last_t": time.perf_counter(), "buf": deque(maxlen=_SMOOTH_WINDOW)}

        def _dl_progress(current, total_bytes):
            pct = (current / max(total_bytes, 1)) * 100
            overall = ((i - 1) / max(total, 1)) * 100 + (1 / max(total, 1)) * pct
            job["download_progress"] = round(overall, 1)
            job["download_episode"] = i
            if not job.get("download_started"):
                job["download_started"] = time.time()
            speed = _speed_sample(_dl_state, current)
            if speed is not None:
                job["download_speed"] = max(0.0, speed)
            job["status_text"] = f"Descargando parte {i}/{total} ({pct:.0f}%)..."
            _persist_job(job)

        info = await _svc().get_file_info(chat_id, int(msg_id), **_svc_creds(job))
        if not info or not info.get("size"):
            continue
        doc_size = int(info.get("size") or 0)

        # Nombre original
        fname = info.get("file_name") or f"part_{i}"
        # Evitar colisiones de nombre
        fname = os.path.basename(fname)
        target = os.path.join(workdir, fname)
        n = 1
        while os.path.exists(target):
            root, ext = os.path.splitext(fname)
            target = os.path.join(workdir, f"{root}_{n}{ext}")
            n += 1

        doc_size = int(getattr(doc, 'size', 0) or 0)
        if os.path.isfile(target) and os.path.getsize(target) == doc_size:
            downloaded.append(target)
            continue
        # Un .target incompleto (de una sesión que murió antes de verificar) NO cuenta
        # como descargado: se vuelve a bajar.
        if os.path.isfile(target):
            try:
                os.remove(target)
            except Exception:
                pass

        tmp_dl = target + ".tmp"
        try:
            # v2: descarga centralizada (servicio core, mismos términos).
            from tvcat.services import file_transfer as _ft
            completed = False
            try:
                got = await _ft.download_file(client, chat_id, msg_id, tmp_dl,
                                              threads=dl_threads, progress=_dl_progress,
                                              client_type="telethon")
                if got and os.path.isfile(tmp_dl) and os.path.getsize(tmp_dl) == doc_size:
                    completed = True
            except Exception as e:
                _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] central falló: {e}")
            if not completed:
                try:
                    os.remove(tmp_dl)
                except Exception:
                    pass
                try:
                    os.remove(tmp_dl + ".chunks")
                except Exception:
                    pass
                _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Parte {i} NO descargada completa ({os.path.getsize(tmp_dl) if os.path.isfile(tmp_dl) else 0}/{doc_size} bytes), reintentará en el siguiente ciclo")
            # SOLO promover a 'target' cuando el tamaño coincide EXACTAMENTE con doc.size.
            # Un parcial (descarga a medias tras reinicio) nunca debe quedar como descargado.
            if completed and os.path.isfile(tmp_dl) and os.path.getsize(tmp_dl) == doc_size:
                try:
                    os.remove(tmp_dl + ".chunks")
                except Exception:
                    pass
                os.replace(tmp_dl, target)
                downloaded.append(target)
            else:
                # Incompleta: el parcial + sidecar se conservan solo 1 ciclo por si el
                # siguiente intento lo retoma; si el trabajador reintentó sin éxito se
                # limpia todo (arriba) para no falsificar completitud.
                if not os.path.exists(tmp_dl + ".chunks"):
                    try:
                        os.remove(tmp_dl)
                    except Exception:
                        pass
        except Exception as e:
            _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Error descargando parte {i}: {e}")
            try:
                os.remove(tmp_dl)
            except Exception:
                pass
    return downloaded


def _archive_password_candidates(job, cover_texts, content_texts) -> list:
    """Candidatas de contraseña: diccionario global + tokens extraídos de mensajes."""
    cfg = _load_config()
    candidates = []
    for p in (cfg.get("archive_passwords") or []):
        if p and p not in candidates:
            candidates.append(p)
    pat = re.compile(r'(passw?o?r?d?|contraseña|contraseña|clave|pwd|pass|password|pw)\s*[:=]\s*(\S+)', re.IGNORECASE)
    for text in list(cover_texts) + list(content_texts):
        for m in pat.finditer(text or ""):
            tok = m.group(2).strip().strip('"\'.,;:()[]')
            if tok and tok not in candidates:
                candidates.append(tok)
    return candidates


def _refresh_job_cover_fields(job):
    """Refresca campos editables del cover desde disco (captura ediciones hechas mientras descargaba).

    El worker mantiene el job en memoria; si el usuario edita el cover mientras
    descarga el primer episodio, esa edición queda en DB_FILE pero no en el dict
    en memoria. Antes de copiar el cover se debe recargar para no perder la edición.
    """
    try:
        db = _load_db()
        for j in db.get("queue", []):
            if str(j.get("id")) == str(job.get("id")):
                for k in ("cover_text", "title", "enrich_details", "use_enricher_cover", "category", "subcategory"):
                    if k in j:
                        job[k] = j[k]
                break
    except Exception as e:
        print(f"[TGHirayi_v2] refresh cover warn: {e}", flush=True)


def _default_cover_template(category: str = "", subcategory: str = "") -> str:
    """Plantilla por defecto del cover.
    1) La del enriquecedor (Configuración/Enriquecedor), resuelta por
       categoría/subcategoría con su fallback si no matchea.
    2) Legacy: default_template de cover_tags.json (si el enriquecedor no
       tiene plantillas configuradas).
    {originalmsg} se vacía: solo tiene sentido en el modal del enriquecedor.
    """
    try:
        import services.enrich_service as _es
        _tpls = _es._load_templates() or {}
        if _tpls.get("templates") or _tpls.get("categories") or _tpls.get("fallback"):
            _t = (_es._resolve_template(_tpls, category or "", subcategory or "") or "").strip()
            if _t:
                return _t.replace("{originalmsg}", "").replace("{foriginalmsg}", "")
    except Exception:
        pass
    try:
        cfg_path = os.path.join(_DATA_DIR, "cover_tags.json")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                return (json.load(f).get("default_template") or "").strip()
    except Exception:
        pass
    return ""


def _resolve_cover_override(job) -> Optional[str]:
    """Determina el texto del cover a copiar.

    Regla: la plantilla SOLO se usa cuando el cover se obtiene desde el ENRIQUECEDOR
    (el job tiene enrich_details con los datos resueltos). Si no es por esa vía
    (copia de telegram, job manual sin enriquecer) se copia el TEXTO ORIGINAL del
    cover tal cual → devuelve None, y el caller usa el texto del mensaje fuente.
    Un cover_text explícito (editado por el usuario) siempre manda si lo hay."""
    stored = (job.get("cover_text") or "").strip()
    if stored:
        if "{f" in stored:
            cover_episodes = len(_fetch_episodes_sync(job["item_id"])) if job.get("item_id") else 0
            return _resolve_cover_tags(stored, job.get("title", ""), cover_episodes, job.get("enrich_details") or {})
        return stored
    # Sin cover_text: solo usar plantilla default si vino del enriquecedor
    if not job.get("enrich_details"):
        return None
    dtpl = _default_cover_template(job.get("category", ""), job.get("subcategory", ""))
    if not dtpl:
        return None
    cover_episodes = len(_fetch_episodes_sync(job["item_id"])) if job.get("item_id") else 0
    return _resolve_cover_tags(dtpl, job.get("title", ""), cover_episodes, job.get("enrich_details") or {})


def _bridge_enricher_cover(job) -> tuple:
    """2026-09-04: puente al cover editado en local (tvcat_enricher) vía registry.
    Devuelve (cover_text|None, poster_blob|None). Se usa en AMBAS ramas de copia
    (con y sin cover_messages) y en el modal de la cola."""
    try:
        from services.cover_override_registry import get_enriched_by_item_id as _gebi
        _enr = _gebi(str(job.get("item_id") or ""))
        if _enr and _enr.get("cover_text"):
            return _enr["cover_text"], _enr.get("poster_blob")
    except Exception:
        pass
    try:
        from services.cover_override_registry import get_enriched_cover as _get_enr_h
        from services.catalog_service import _derive_episode_key as _dk
        _k = ""
        _lnk = job.get("telegram_link")
        if _lnk:
            _k = _dk(_lnk)
        if _k:
            _enr2 = _get_enr_h(_k)
            if _enr2 and _enr2.get("cover_text"):
                return _enr2["cover_text"], _enr2.get("poster_blob")
    except Exception:
        pass
    return None, None


def _seed_job_cover_from_local(job) -> bool:
    """2026-09-04: si el job no tiene cover manual y el item tiene edición local,
    la siembra (cover_text + enrich_details). Idempotente. Devuelve True si sembró.
    El TÍTULO no se toca: manda el del catálogo (vía Tag), que es posterior al
    api_title guardado del enriquecedor (TMDB). Reescribirlo revertía ediciones
    del usuario (p. ej. 'Vaiana (Live Action)' -> 'Vaiana')."""
    try:
        if not isinstance(job, dict):
            return False
        if job.get("cover_manual"):
            return False
        if (job.get("cover_text") or "").strip() and not job.get("cover_from_local"):
            return False
        from services.cover_override_registry import get_enriched_by_item_id as _gebi2
        _enr = _gebi2(str(job.get("item_id") or ""))
        if not _enr:
            return False
        _det = _enr.get("enrich_details") or {}
        if (_enr.get("cover_text") or "").strip():
            job["cover_text"] = _enr["cover_text"]
            if _det:
                job["enrich_details"] = _det
            job["cover_from_local"] = True
            return True
        if _det and not job.get("enrich_details"):
            job["enrich_details"] = _det
            return True
    except Exception:
        pass
    return False


def _job_poster_bytes_sync(job) -> Optional[bytes]:
    """Descarga (SÍNCRONO, ejecutar con asyncio.to_thread) el primer póster del
    enriquecedor del job. Devuelve bytes o None si no hay cover o falla la descarga."""
    # 2026-09-04: primero el póster LOCAL editado (registry, sin red).
    try:
        _bt, _bp = _bridge_enricher_cover(job if isinstance(job, dict) else {})
        if _bp and isinstance(_bp, (bytes, bytearray, memoryview)):
            return bytes(_bp)
    except Exception:
        pass
    try:
        details = (job or {}).get("enrich_details") or {}
        covers = details.get("api_cover") or ""
        if isinstance(covers, str):
            try:
                covers = json.loads(covers) or []
            except Exception:
                covers = []
        elif not isinstance(covers, list):
            covers = []
        url = covers[0] if covers else None
        if not url:
            return None
        import requests
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and r.content:
            return r.content
        print(f"[TGHirayi_v2] Póster enriquecedor status {r.status_code} ({url})", flush=True)
    except Exception as e:
        print(f"[TGHirayi_v2] Error descargando póster del enriquecedor: {e}", flush=True)
    return None


async def _copy_cover_to_destinations(job, client, cover_messages, destinations, delay) -> dict:
    """Copia el cover a los destinos NO omitidos del job.
    Los destinos omitidos (topic ya existe) se saltan ENTEROS (ni cover).
    Devuelve {channel_id(str): [msg_ids]} con los mensajes creados (verificación).
    - Si el cover está editado/enriquecido (_resolve_cover_override != None) se copia como
      UN SOLO mensaje: imagen elegida (póster del enriquecedor si use_enricher_cover y la
      descarga funciona; si no, la primera foto del cover original) + texto generado.
    - Si NO está editado: copia todos los mensajes del cover original tal cual (legacy).
    - Si cover_messages vacío y source es -999 (topo 0 genérico): genera cover genérico por categoría.
    El póster del enriquecedor se descarga UNA sola vez (no por destino)."""
    try:
        _omit = job.get("_omitted") or {}
        _before = len(destinations or [])
        destinations = [d for d in (destinations or [])
                        if str(d.get("id") or d.get("channel_id")) not in _omit]
        if len(destinations) != _before:
            print(f"[TGHirayi_v2] Job {job.get('id')}: cover omitido en {_before - len(destinations)} destino(s) (topic ya existe)", flush=True)
    except Exception:
        pass
    cover_ids: dict = {}
    if not cover_messages:
        # Cover genérico Topo 4 (-999/-1000): dos estados
        # a) NO EDITADO -> imagen genérica + Title sanitizado del primer fichero + Ext + Episodes
        # b) EDITADO   -> cover generado con editor/enriquecedor (plantilla + poster)
        _refresh_job_cover_fields(job)
        # 2026-09-04: sembrar edición local antes de decidir (esta rama nunca
        # consultaba el registry y copiaba el original aunque hubiera edit).
        # El worker persiste el db al avanzar el job; aquí solo se muta en memoria.
        try:
            _seed_job_cover_from_local(job)
        except Exception:
            pass
        stored = (job.get("cover_text") or "").strip()
        is_edited = bool(stored)
        if not is_edited and job.get("enrich_details"):
            ed = job.get("enrich_details") or {}
            if ed.get("api_title") or ed.get("api_description"):
                tmp = _resolve_cover_override(job)
                if tmp is not None:
                    is_edited = True
        if is_edited:
            cover_override = _resolve_cover_override(job)
            if cover_override is None:
                try:
                    dtpl = _default_cover_template(job.get("category", ""), job.get("subcategory", ""))
                    if dtpl and job.get("enrich_details"):
                        ep_cnt = len(_fetch_episodes_sync(job.get("item_id"))) if job.get("item_id") else 0
                        cover_override = _resolve_cover_tags(dtpl, job.get("title", ""), ep_cnt, job.get("enrich_details") or {})
                    else:
                        cover_override = (job.get("title") or "").strip()
                except Exception:
                    cover_override = (job.get("title") or "").strip()
                if not cover_override:
                    cover_override = job.get("title", "") or "Cover"
            poster_bytes = None
            if job.get("use_enricher_cover", True):
                poster_bytes = await asyncio.to_thread(_job_poster_bytes_sync, job)
        else:
            # NO EDITADO -> generar desde file_name del primer episodio EN SCOPE
            # (partidos: el primero movido, no el primero de la lista original)
            episodes = []
            try:
                _all = _fetch_episodes_sync(job.get("item_id", "")) or []
                episodes = [e for e in _all if _ep_in_scope(job, e)]
            except Exception:
                episodes = []
            first_fname = ""
            if episodes:
                first_fname = episodes[0].get("file_name") or episodes[0].get("title") or ""
            if not first_fname:
                first_fname = job.get("title") or ""
            sanitized, ext = _sanitize_file_title(first_fname)
            if not sanitized:
                sanitized = (job.get("title") or "").strip() or "Cover"
            total = len(episodes) if episodes else int(job.get("total_episodes") or 0) or 1
            if ext:
                cover_override = f"Title: {sanitized}\nExt: {ext}\nEpisodes: {total}"
            else:
                cover_override = f"Title: {sanitized}\nEpisodes: {total}"
            poster_bytes = None
        # Imagen genérica por categoría como fallback si no hay póster (común a ambos estados)
        generic_blob = None
        try:
            cat = (job.get("category") or "media").lower()
            fb_id = -1 if cat in ("juegos", "games", "game") else (-2 if cat in ("comic", "kiosko", "book", "manga") else -3)
            from tvcat.gateway import get_db_connection
            conn = get_db_connection()
            try:
                row = conn.execute("SELECT image_blob, mime_type FROM catalog_assets WHERE channel_id='' AND telegram_msg_id=? AND asset_type='cover' LIMIT 1", (fb_id,)).fetchone()
            except Exception:
                row = conn.execute("SELECT image_blob, mime_type FROM catalog_assets WHERE telegram_msg_id=? AND asset_type='cover' LIMIT 1", (fb_id,)).fetchone()
            conn.close()
            if row and row["image_blob"]:
                generic_blob = row["image_blob"]
        except Exception as e:
            print(f"[TGHirayi_v2] generic asset lookup error: {e}", flush=True)
        for dest in destinations:
            topic_id = await _resolve_topic_id_async(client, dest, job["title"], job)
            _dids: List[int] = []
            if poster_bytes:
                _dids = await _copy_messages_to_destination(client, [], dest, topic_id, delay,
                                                    cover_text_override=cover_override, poster_bytes=poster_bytes, job=job)
            elif generic_blob:
                try:
                    _gid = await _svc().send_photo(dest["channel_id"], bytes(generic_blob), caption=cover_override,
                                                   reply_to_msg_id=topic_id if topic_id else None, **_svc_creds(job))
                    if _gid:
                        _dids = [int(_gid)]
                except Exception as e:
                    print(f"[TGHirayi_v2] Error enviando cover genérico a {dest.get('channel_id')}: {e}")
                    _dids = await _copy_messages_to_destination(client, [], dest, topic_id, delay,
                                                        cover_text_override=cover_override, poster_bytes=None, job=job)
            else:
                _dids = await _copy_messages_to_destination(client, [], dest, topic_id, delay,
                                                    cover_text_override=cover_override, poster_bytes=None, job=job)
            cover_ids[str(dest.get("channel_id"))] = [i for i in _dids if i]
            await asyncio.sleep(delay)
        return cover_ids
    # Caso normal (cover_messages no vacío): también refrescar por si se editó durante la descarga
    _refresh_job_cover_fields(job)
    try:
        _seed_job_cover_from_local(job)
    except Exception:
        pass
    cover_override = _resolve_cover_override(job)
    poster_bytes = None
    if cover_override is not None and job.get("use_enricher_cover", True):
        poster_bytes = await asyncio.to_thread(_job_poster_bytes_sync, job)
    # Puente del Enriquecedor hero (tvcat_enricher, §21.6): si el job no trae cover enriquecido, probar el del plugin
    if cover_override is None:
        _bt, _bp = _bridge_enricher_cover(job)
        if _bt is not None:
            cover_override = _bt
            poster_bytes = _bp
    for dest in destinations:
        topic_id = await _resolve_topic_id_async(client, dest, job["title"], job)
        _dids = await _copy_messages_to_destination(client, cover_messages, dest, topic_id, delay,
                                            cover_text_override=cover_override, poster_bytes=poster_bytes, job=job)
        cover_ids[str(dest.get("channel_id"))] = [i for i in _dids if i]
        await asyncio.sleep(delay)
    return cover_ids


async def _verify_cover_uploaded(job, client, destinations) -> bool:
    """Verifica que el cover exista REALMENTE en cada destino (solo primer episodio).
    Usa los msg_id registrados en `job['_cover_msg_ids']` al copiar; si no hay
    registro o ningún mensaje existe → NO verificado (hay que copiarlo).
    Fail-closed: ante la duda se re-copia (un cover duplicado es menos grave
    que un título sin cover)."""
    try:
        stored = job.get("_cover_msg_ids") or {}
    except Exception:
        stored = {}
    if not stored:
        return False
    for dest in destinations or []:
        try:
            ids = [int(i) for i in (stored.get(str(dest.get("channel_id"))) or []) if int(i or 0)]
        except Exception:
            return False
        if not ids:
            return False
        try:
            # fetch_one devuelve dict o None (servicio central, con caché)
            ok = False
            for _id in ids:
                try:
                    _m = await _svc().fetch_one(dest["channel_id"], int(_id), **_svc_creds(job))
                except Exception:
                    _m = None
                if _m is not None:
                    ok = True
                    break
            if not ok:
                print(f"[TGHirayi_v2] Cover no encontrado en {dest.get('channel_id')} (ids={ids}), re-copiando", flush=True)
                return False
        except Exception as e:
            print(f"[TGHirayi_v2] No se pudo verificar cover en {dest.get('channel_id')}: {e}", flush=True)
            return False
    return True


async def _copy_cover_once(job, client, source_channel_id, source_msg_id, destinations, delay, source_topic_id=None):
    """Copia el cover (texto plantilla + imagen) a todos los destinos. Se llama JUSTO ANTES
    del primer vídeo. No hace nada si ya se copió (flag en el job).
    IMPORTANTE: este helper NO marca job['_cover_done']; el caller lo hace SOLO DESPUÉS de
    subir con éxito el primer vídeo (si no, un reinicio tras copiar el cover dejaría un
    cover huérfano y el primer vídeo se subiría después sin su cover)."""
    if job.get("_cover_done"):
        return
    try:
        if int(source_msg_id) in (-999, -1000):
            cover_messages = []  # genérico, no pedir a Telegram
        else:
            cover_messages = await _fetch_cover_messages(client, source_channel_id, source_msg_id, source_topic_id, job)
        _cids = await _copy_cover_to_destinations(job, client, cover_messages, destinations, delay)
        if _cids:
            job["_cover_msg_ids"] = _cids
            _persist_job(job)
    except Exception as e:
        _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Error copiando cover: {e}")


async def _process_archive_job(job, db, client, pyro_client, destinations, delay,
                               source_channel_id, source_msg_id, resume_from, source_topic_id=None):
    """Procesa un job tipo ARCHIVE según su fase (archive_phase):
    - download: descarga/extrae/recodifica. El worker la ejecuta en PRIMER plano si hay
      slot libre y no se supera max_pending_archives; al descargar lanza el procesado
      (extraer+recodificar) en SEGUNDO plano (1 slot) y la cola sigue con el siguiente job.
    - processing: el procesado corre en background (task propia); el worker la salta.
    - ready_upload: re-encolado tras el encode; se SUBEN los vídeos ya preparados.
    - uploading: subida en curso (el worker la salta).
    El job re-encolado conserva su posición de prioridad original (priority del job)."""
    cfg = _load_config()
    if not cfg.get("extract_archives", True):
        # Degradación ya resuelta en _process_job (flujo normal); defensa aquí.
        return
    phase = job.get("archive_phase") or "download"

    if phase == "ready_upload":
        job["archive_phase"] = "uploading"
        job["status"] = "processing"
        _persist_job(job)
        await _archive_upload_phase(job, client, pyro_client, destinations, delay,
                                    source_channel_id, source_msg_id, source_topic_id)
        return

    if phase in ("processing", "uploading"):
        # Gestionado por task de fondo / subida en curso → no re-procesar
        return

    # ── Fase download (primer plano: descarga todas las partes) ──
    seven_zip = _find_7z()
    if not seven_zip:
        job["status"] = "error"
        job["error"] = "No hay 7z disponible (instala p7zip o añade tools/7z)"
        _persist_job(job)
        return

    _cleanup_other_job_dirs(job["id"])

    work = _archive_workdir(job["id"])
    for d in work.values():
        os.makedirs(d, exist_ok=True)

    episodes = _fetch_episodes_sync(job["item_id"])
    total_parts = len(episodes)
    if not total_parts:
        job["status"] = "error"
        job["error"] = "Sin ficheros para extraer"
        _persist_job(job)
        return

    extract_state = job.get("extract_state") or {}
    downloaded = extract_state.get("downloaded") or []

    # F5: todos los destinos omitidos (topics ya existen) → título ENTERO
    # omitido (ni cover): sin descargar/extraer nada.
    try:
        _aomit_all = bool(job.get("_omitted")) and all(
            str(_d.get("id") or _d.get("channel_id")) in (job.get("_omitted") or {})
            for _d in destinations)
    except Exception:
        _aomit_all = False
    if _aomit_all and not downloaded:
        try:
            _aomit_n = [_d.get("name", "?") for _d in destinations]
        except Exception:
            _aomit_n = []
        job["status"] = "skipped"
        job["status_text"] = f"Omitido por existente en destino ({', '.join(_aomit_n)}): topic '{job.get('title')}' ya existe"
        job["progress"] = 100.0
        job["archive_phase"] = "completed"
        _persist_job(job)
        _cleanup_archive_workdir(job["id"])
        return

    try:
        # 1) Preflight de espacio estimado (comprimido + descomprimido ×1.3 + 4GB)
        total_compressed = sum(int(ep.get("file_size") or 0) for ep in episodes)
        job["status"] = "processing"
        job["status_text"] = "Archive: preflight espacio..."
        _persist_job(job)
        if not _check_free_space(job, int(total_compressed * 1.3)):
            return  # queda en queued, reintenta en el siguiente ciclo

        # 2) Descargar todas las partes (si no están ya descargadas)
        if not downloaded:
            job["status_text"] = "Descargando todas las partes..."
            _persist_job(job)
            job["archive_phase"] = "download"
            downloaded = await _download_archive_files(client, episodes, source_channel_id, work["download"], job)
            extract_state["downloaded"] = downloaded
            job["extract_state"] = extract_state
            _persist_job(job)
        if not downloaded:
            job["status"] = "error"
            job["error"] = "No se pudieron descargar los ficheros del archive"
            _persist_job(job)
            return

        # 3) Lanzar el procesado (extraer + recodificar) en segundo plano y liberar el
        #    worker para el siguiente job (solo si hay slot). Si archive_parallel=false,
        #    se ejecuta en primer plano (secuencial legacy).
        job["archive_phase"] = "processing"
        job["status"] = "processing"
        job["status_text"] = "Encolado (procesado en paralelo)..."
        _persist_job(job)

        if cfg.get("archive_parallel", True):
            # Reserva optimista del slot: evita que el worker descargue otro archive en
            # la ventana entre la creación de la task y la adquisición de _archive_slot_lock.
            _archive_slot_owner = job["id"]
            task = asyncio.create_task(_archive_process_background(
                job["id"], client, source_channel_id, source_msg_id, source_topic_id))
            _archive_tasks[job["id"]] = task
            _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Job {job['id']} procesado en 2º plano (slot propio)")
        else:
            try:
                await _archive_process_background(job["id"], client, source_channel_id, source_msg_id, source_topic_id)
            except Exception as e:
                _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Error en procesado: {e}")
                import traceback
                traceback.print_exc()

    except Exception as e:
        _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Error: {e}")
        import traceback
        traceback.print_exc()
        job["status"] = "paused"
        job["error"] = str(e)
        job["status_text"] = f"Pausado (error en procesado): {e}"
        _persist_job(job)


async def _archive_process_background(job_id: str, client, source_channel_id, source_msg_id, source_topic_id=None):
    """Extrae los archives y recodifica los vídeos >4GB en segundo plano (1 slot).
    Al terminar marca archive_phase='ready_upload' y re-encola el job en su misma
    posición de prioridad (priority intacta) → el worker lo sube en su turno."""
    global _archive_slot_owner
    async with _archive_slot_lock:
        _archive_slot_owner = job_id
        try:
            # Reload fresco del job (el worker ya no lo gestiona en este hilo)
            _cand = None
            try:
                _db = _load_db()
                for _j in _db.get("queue", []):
                    if _j.get("id") == job_id:
                        _cand = _j
                        break
            except Exception:
                _cand = None
            if _cand is None:
                return
            job = _cand

            cfg = _load_config()
            seven_zip = _find_7z()
            if not seven_zip:
                job["status"] = "error"
                job["error"] = "No hay 7z disponible"
                _persist_job(job)
                return

            work = _archive_workdir(job_id)
            for d in work.values():
                os.makedirs(d, exist_ok=True)
            episodes = _fetch_episodes_sync(job["item_id"])
            extract_state = job.get("extract_state") or {}
            downloaded = extract_state.get("downloaded") or []
            extracted = extract_state.get("extracted") or []
            pending = extract_state.get("pending") or []

            # Pendientes: ficheros archive descargados (7z como fuente de verdad)
            arc_files = [f for f in downloaded if _is_archive_file(os.path.basename(f)) and os.path.isfile(f)]
            pending = sorted((pending or arc_files), key=lambda p: os.path.basename(p).lower())

            # Candidatas de contraseña (cover + mensajes) + diccionario global
            try:
                cover_msgs = await _fetch_cover_messages(client, source_channel_id, source_msg_id or 0, source_topic_id, job)
                cover_texts = [(m.get("text") if isinstance(m, dict) else None) or getattr(m, 'message', None) or getattr(m, 'text', '') or '' for m in cover_msgs]
            except Exception:
                cover_texts = []
            content_texts = [ep.get("caption") or ep.get("title") or "" for ep in episodes if (ep.get("caption") or ep.get("title"))]
            passwords = _archive_password_candidates(job, cover_texts, content_texts)
            password = (job.get("archive_password") or "").strip()

            # Extracción iterativa
            job["archive_phase"] = "processing"
            job["status_text"] = "Extrayendo archives (2º plano)..."
            _persist_job(job)
            videos = [v for v in extracted if os.path.isfile(v)]
            while pending:
                target = next((f for f in pending if _archive_can_open(seven_zip, f)), None)
                if target is None:
                    break
                job["status_text"] = f"Extrayendo {os.path.basename(target)} (2º plano)..."
                _persist_job(job)
                _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] Extrayendo {os.path.basename(target)} (2º plano)...")
                est = _estimate_archive_size(seven_zip, target)
                if not _check_free_space(job, int(est * 1.3)):
                    job["archive_phase"] = "download"
                    job["status"] = "queued"
                    job["status_text"] = "En cola (sin espacio)"
                    _persist_job(job)
                    return

                res = await asyncio.to_thread(_run_7z_extract, seven_zip, target, work["extracted"], password=password or None)
                if res.get("wrong_password"):
                    solved = None
                    for cand in passwords:
                        if cand == password:
                            continue
                        r2 = await asyncio.to_thread(_run_7z_extract, seven_zip, target, work["extracted"], password=cand)
                        if r2.get("ok") and not r2.get("wrong_password"):
                            solved = cand
                            res = r2
                            break
                    if solved:
                        password = solved
                        arch = list(cfg.get("archive_passwords") or [])
                        if password not in arch:
                            arch.append(password)
                            cfg["archive_passwords"] = arch
                            _save_config(cfg)
                        job["archive_password"] = password
                        _persist_job(job)
                    else:
                        import shutil as _sh
                        for f in downloaded:
                            try:
                                _sh.move(f, os.path.join(work["preserved"], os.path.basename(f)))
                            except Exception:
                                pass
                        job["status"] = "awaiting_password"
                        job["status_text"] = "Archive protegido con contraseña"
                        job["preserved_dir"] = work["preserved"]
                        job["priority"] = 999
                        _persist_job(job)
                        return

                if not res.get("ok"):
                    raise RuntimeError(f"Fallo extrayendo {os.path.basename(target)}: {res.get('output','')[:300]}")

                new_videos = [v for v in res.get("videos", []) if v not in videos]
                videos.extend(new_videos)
                _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] {os.path.basename(target)} extraído: {len(res.get('videos', []))} vídeos (total {len(videos)})")
                for name in res.get("consumed", []):
                    cand = os.path.join(work["download"], os.path.basename(name))
                    if os.path.isfile(cand):
                        try:
                            os.replace(cand, os.path.join(work["trash"], os.path.basename(cand)))
                        except Exception:
                            pass
                pending = [f for f in pending if os.path.isfile(f)]
                for f in list(pending):
                    if not _archive_can_open(seven_zip, f):
                        try:
                            os.replace(f, os.path.join(work["trash"], os.path.basename(f)))
                        except Exception:
                            pass
                pending = [f for f in pending if os.path.isfile(f)]
                extract_state["pending"] = pending
                extract_state["extracted"] = videos
                job["extract_state"] = extract_state
                _persist_job(job)

            if not videos:
                job["status"] = "error"
                job["error"] = "No se extrajo ningún vídeo de los archives"
                _persist_job(job)
                return
            _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] Extracción completada: {len(videos)} vídeos")

            # Recodificar los vídeos en 2º plano (1 slot); registrar ffmpeg para kill
            # Normalizar vídeos en 2º plano (1 slot). Regla: TODO vídeo no-MP4/M4V se convierte
            # a MP4 (AVI, WMV, MOV...), salvo MKV con streaming_mkv activo que se sube tal cual.
            # >4GB se recodifican para caber en un mensaje. Con streaming_mkv TODOS pasan por
            # _normalize_video(streaming=True): MKV <4GB → directo, resto → conversión a MP4.
            job["status_text"] = "Normalizando vídeos (2º plano)..."
            _persist_job(job)
            _streaming = bool(cfg.get("streaming_mkv", False))
            # Estado de encode persistido (para reanudar tras un reinicio del gateway).
            # _run_ffmpeg_progress rellena en vivo pid/progress_pos/... en este mismo dict
            # y _persist_job(job) lo serializa tal cual -> sobrevive a reinicios.
            saved_resume = job.get("encode_state") or {}
            if saved_resume:
                _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] Reanudando normalize (v_idx={saved_resume.get('video_index')}, pid={saved_resume.get('pid')}, done={saved_resume.get('done')})")
                # Si el ffmpeg que venía murió pero ya dejó output válido, lo aprovechamos
            _resume_vidx = int(saved_resume.get("video_index") or 0)
            for v_idx, vpath in enumerate(videos, 1):
                # Seguridad: saltar vídeos que YA están normalizados (un run previo murió
                # justo al terminar el vídeo y nunca avanzó de índice). Evita re-encodear.
                _done_norm = vpath + ".normalized.mp4"
                if vpath.endswith(".normalized.mp4"):
                    _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] #{v_idx} ya normalizado en lista, saltando")
                    continue
                # Reuso SOLO si el output es completo (sin fichero .progress a medias):
                # un .normalized.mp4 parcial por caída del gateway mientras encodaba
                # no debe reutilizarse (archivo corrupto >1KB) → se re-normaliza.
                if (os.path.isfile(_done_norm) and os.path.getsize(_done_norm) > 1024
                        and not os.path.exists(_done_norm + ".progress")):
                    _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] #{v_idx} reutilizando output existente: {os.path.basename(_done_norm)}")
                    videos[v_idx - 1] = _done_norm
                    continue
                fsize = os.path.getsize(vpath)
                _vext = os.path.splitext(vpath)[1].lower()
                # SIEMPRE normalizar: MP4/M4V aplican faststart (rápido, sin re-encode),
                # otros formatos se convierten a MP4. MKV con streaming se sube tal cual.
                # faststart es necesario para HLS (moov al inicio).
                if True:  # Siempre normalizar
                    job["encode_progress"] = 0.0
                    if fsize > _MAX_UPLOAD_MIB:
                        job["status_text"] = f"Recodificando {fsize / 1024**3:.2f}GB para <4GB (2º plano)..."
                    elif _vext in (".mp4", ".m4v"):
                        job["status_text"] = "Aplicando faststart..."
                    else:
                        job["status_text"] = "Normalizando vídeo..."
                    _persist_job(job)
                    _rec_last = [0.0]
                    _rec_detail_state = {"total_size": 0, "speed": 0.0, "fps": 0.0, "frame": 0, "out_time": ""}
                    def _rec_log(m):
                        job["status_text"] = f"Normalizando: {m}"
                        _persist_job(job)
                    def _rec_pct(pct):
                        job["encode_progress"] = round(pct, 1)
                        now = time.time()
                        if now - _rec_last[0] >= 2.0:
                            _rec_last[0] = now
                            _persist_job(job)
                    def _rec_detail(d_metrics):
                        _rec_detail_state.update(d_metrics or {})
                        job["encode_size"] = _rec_detail_state.get("total_size", 0)
                        job["encode_speed"] = _rec_detail_state.get("speed", 0.0)
                        job["encode_fps"] = _rec_detail_state.get("fps", 0.0)
                        job["encode_frame"] = _rec_detail_state.get("frame", 0)
                        now = time.time()
                        if now - _rec_last[0] >= 2.0:
                            _rec_last[0] = now
                            _persist_job(job)
                    _encode_proc_registry["job_id"] = job["id"]
                    # ¿Es el vídeo que quedó encodando en un reinicio anterior?
                    this_resume = saved_resume if (v_idx == _resume_vidx and saved_resume) else {}
                    if this_resume and _pid_alive(this_resume.get("pid")) and not this_resume.get("done"):
                        # ADOPTAR el ffmpeg huérfano: esperar a que termine leyendo su
                        # -progress; no se re-lanza nada (el proceso sigue vivo).
                        _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] #{v_idx} adoptando ffmpeg pid={this_resume.get('pid')} (pase {this_resume.get('pass')})")
                        await asyncio.to_thread(_adopt_orphan_ffmpeg, this_resume,
                                                on_pct=_rec_pct, on_detail=_rec_detail,
                                                on_log=lambda m: _job_log(job_id, m))
                        _done = vpath + (".mkv" if (bool(_streaming) and os.path.splitext(os.path.basename(vpath))[1].lower() == ".mkv") else ".normalized.mp4")
                        if os.path.isfile(_done) and os.path.getsize(_done) > 1024:
                            videos[v_idx - 1] = _done
                            job["encode_progress"] = 100.0
                            job["status_text"] = f"Retomado y Normalizado OK: {os.path.getsize(_done)/1024**3:.2f}GB"
                            _persist_job(job)
                            continue
                        # El adoptado terminó sin output válido (p.ej. pase 1 se murió a
                        # medias o el puente 1->2 no se completó): re-encodear desde cero.
                        _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] #{v_idx} adoptado sin output -> re-normalizando desde cero")
                    resume_state = {"video_index": v_idx}
                    job["encode_state"] = resume_state
                    norm = await asyncio.to_thread(_normalize_video, vpath, os.path.basename(vpath),
                                                   progress_log=_rec_log, on_progress_pct=_rec_pct,
                                                   proc_registry=_encode_proc_registry, on_detail=_rec_detail,
                                                   streaming=_streaming, resume_state=resume_state)
                    if norm and os.path.isfile(norm) and os.path.getsize(norm) > 1024:
                        videos[v_idx - 1] = norm
                        job["encode_progress"] = 100.0
                        job["status_text"] = f"Normalizado OK: {os.path.getsize(norm)/1024**3:.2f}GB"
                        _persist_job(job)
                    else:
                        _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] Normalización falló, subiendo original")
                extract_state["extracted"] = videos
                job["extract_state"] = extract_state
                job["current_episode"] = v_idx
                job["total_episodes"] = len(videos)
                _persist_job(job)

            # Limpiar estado de encode (el trabajo terminó).
            # NOTA: conservamos job["extract_state"] (downloaded/pending) para que un
            # reinicio posterior en ready_upload/uploading no re-descargue ni re-extraiga.
            job.pop("encode_state", None)

            # Re-encolar para subir: conservar priority (posición original) y fase lista
            job["archive_phase"] = "ready_upload"
            job["status"] = "queued"
            job["status_text"] = "En cola (subir ficheros)"
            job["progress"] = 0.0
            job["upload_progress"] = 0.0
            job["current_episode"] = 0
            _encode_proc_registry.pop("job_id", None)
            _persist_job(job)
            _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] Job {job_id} procesado → ready_upload (priority {job.get('priority')})")
        except Exception as e:
            _job_log(job_id, f"[TGHirayi_v2] [ARCHIVE] Error en 2º plano: {e}")
            import traceback
            traceback.print_exc()
            try:
                _db = _load_db()
                for _j in _db.get("queue", []):
                    if _j.get("id") == job_id:
                        # Error en procesado de archive: 'paused' para no bloquear la
                        # cola de archives (el usuario lo ve y lo reintenta/gestione).
                        _j["status"] = "paused"
                        _j["error"] = str(e)
                        _j["status_text"] = f"Pausado (error en procesado): {e}"
                        _j["archive_phase"] = "download"
                        _persist_job(_j)
                        break
            except Exception:
                pass
        finally:
            _archive_slot_owner = None
            _archive_tasks.pop(job_id, None)


async def _archive_upload_phase(job, client, pyro_client, destinations, delay,
                                source_channel_id, source_msg_id, source_topic_id=None):
    """Sube los vídeos ya extraídos/recodificados (fase ready_upload) a los destinos."""
    try:
        extract_state = job.get("extract_state") or {}
        videos = [v for v in extract_state.get("extracted") or [] if os.path.isfile(v)]
        if not videos:
            job["status"] = "error"
            job["error"] = "No hay vídeos listos para subir"
            _persist_job(job)
            return

        total_videos = len(videos)
        total_dest = len(destinations)
        for v_idx, vpath in enumerate(videos, 1):
            if _worker_paused or not _worker_running:
                job["archive_phase"] = "ready_upload"
                job["status"] = "queued"
                job["status_text"] = "En cola (subir ficheros)"
                _persist_job(job)
                return
            fsize = os.path.getsize(vpath)
            # Cover SOLO justo antes del primer vídeo listo para subir, y solo si no se
            # copió ya en una pasada previa (flag persistido en el job). Así un fallo
            # en descarga/recodificación NUNCA deja un cover huérfano, y una reanudación
            # no duplica ni desordena covers.
            if not job.get("_cover_done"):
                await _copy_cover_once(job, client, source_channel_id,
                                       source_msg_id or 0, destinations, delay, source_topic_id)
            fname = os.path.basename(vpath)
            with open(vpath, 'rb') as f:
                data = f.read()
            _dims = _ffprobe_dimensions(vpath)
            thumb_data = _get_or_generate_thumb(vpath, (f"job{job['id']}", v_idx)) if _is_video_file(fname) else None
            media_entry = {
                "data": data,
                "file_name": fname,
                "file_size": fsize,
                "mime_type": "video/x-matroska" if fname.lower().endswith(".mkv") else "video/mp4",
                "attributes": [],
                "thumb_data": thumb_data,
                "video_attrs": None,
                "duration": _ffprobe_duration(vpath) or 0,
                "width": (_dims or (0, 0))[0],
                "height": (_dims or (0, 0))[1],
            }
            job["archive_phase"] = "uploading"
            job["status"] = "processing"
            job["current_episode"] = v_idx
            job["total_episodes"] = total_videos
            job["status_text"] = f"Subiendo vídeo {v_idx}/{total_videos}..."
            _persist_job(job)
            _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Subiendo vídeo {v_idx}/{total_videos}: {fname}")
            for dest in destinations:
                _aokey = str(dest.get("id") or dest.get("channel_id"))
                if _aokey in (job.get("_omitted") or {}):
                    # F5: topic ya existe → solo cover (ya copiado), sin vídeos.
                    _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Omitido en dest {dest.get('name','?')}: Topic ya existe ({fname})")
                    job["_uploaded_to"][dest.get("channel_id")] = True
                    continue
                topic_id = await _resolve_topic_id_async(client, dest, job["title"], job)
                await _upload_episode_to_destination(
                    client, pyro_client,
                    {"caption": fname, "title": fname, "episode_title": fname},
                    [media_entry], dest, topic_id, delay,
                    progress_callback=_archive_progress_cb(job, v_idx, total_videos, total_dest),
                    job=job,
                )
                await asyncio.sleep(delay)
            # El cover queda confirmado SOLO después de subir con éxito el primer vídeo.
            # Así un reinicio/fallo tras copiar el cover re-copia el cover junto al primer
            # vídeo (nunca cover huérfano adelantado, nunca primer vídeo sin su cover).
            if v_idx == 1:
                job["_cover_done"] = True
                _persist_job(job)

        job["status"] = "completed"
        try:
            _aomit = [_d.get("name", "?") for _d in destinations
                      if str(_d.get("id") or _d.get("channel_id")) in (job.get("_omitted") or {})]
        except Exception:
            _aomit = []
        if _aomit and len(_aomit) >= len(destinations) and destinations:
            job["status"] = "skipped"
            job["status_text"] = f"Omitido por existente en destino ({', '.join(_aomit)}): topic '{job.get('title')}' ya existe"
        elif _aomit:
            job["status_text"] = "Completado (omitido en " + ", ".join(_aomit) + ": Topic ya existe)"
        else:
            job["status_text"] = "Completado"
        job["progress"] = 100.0
        job["current_episode"] = total_videos + 1
        job["download_progress"] = 100.0
        job["upload_progress"] = 100.0
        job["archive_phase"] = "completed"
        _persist_job(job)
        _cleanup_archive_workdir(job["id"])
        _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Job {job['id']} completado ({total_videos} vídeos)")
    except Exception as e:
        _job_log(job["id"], f"[TGHirayi_v2] [ARCHIVE] Error subiendo: {e}")
        import traceback
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)
        job["status_text"] = f"Error: {e}"
        _persist_job(job)


def _archive_progress_cb(job, v_idx, total_videos, total_dest):
    """Factory del callback de progreso para la subida de un vídeo extraído."""
    def _cb(kind, current, total):
        if kind == "upload":
            if not job.get("upload_started"):
                job["upload_started"] = time.time()
            job["upload_progress"] = round((current / max(total, 1)) * 100, 1)
            job["status_text"] = f"Subiendo vídeo {v_idx}/{total_videos} {job['upload_progress']}%"
        _persist_job(job)
    return _cb


def _cleanup_archive_workdir(job_id: str):
    """Vacía la carpeta de trabajo del job archive al completar/eliminar."""
    import shutil as _sh
    base = os.path.join(_CACHE_DIR, "jobs", job_id)
    try:
        if os.path.isdir(base):
            _sh.rmtree(base, ignore_errors=True)
    except Exception as e:
        print(f"[TGHirayi_v2] Error limpiando workdir archive: {e}", flush=True)


def _cleanup_other_job_dirs(current_id):
    """Elimina las carpetas cache/jobs de OTROS jobs, dejando solo la del job en curso.
    Respeta los workdirs de archives en vuelo (processing/ready_upload/uploading) que
    están siendo trabajados por su task de 2º plano o pendientes de subir.
    Evita que reintentos o procesados previos conserven ficheros descargados/extraídos
    que ya no corresponden (y que un reintento del mismo job redescargue contenido
    quemado dentro de su propia carpeta)."""
    import shutil as _sh
    # Jobs cuyo workdir NO debe borrarse (en vuelo o pendientes de subir)
    protected = set()
    try:
        _db = _load_db()
        for _j in _db.get("queue", []):
            _ph = _j.get("archive_phase")
            if _j.get("is_archive") and _ph in ("processing", "ready_upload", "uploading"):
                protected.add(str(_j.get("id")))
    except Exception:
        pass
    if _archive_slot_owner:
        protected.add(str(_archive_slot_owner))
    base = os.path.join(_CACHE_DIR, "jobs")
    try:
        if not os.path.isdir(base):
            return
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if os.path.isdir(p) and name not in protected and name != str(current_id):
                try:
                    _sh.rmtree(p, ignore_errors=True)
                    print(f"[TGHirayi_v2] Cache de job {name} eliminado (no es el actual {current_id})", flush=True)
                except Exception as e:
                    print(f"[TGHirayi_v2] Error limpiando cache de job {name}: {e}", flush=True)
    except Exception as e:
        print(f"[TGHirayi_v2] Error limpiando cache de jobs: {e}", flush=True)


def _ffprobe_tracks(file_path: str) -> dict:
    """Devuelve las pistas de audio y subtítulos de un fichero (índice absoluto, título, idioma, default)."""
    probe = _find_ffprobe()
    if not probe:
        return {"audio": [], "subs": []}
    import subprocess, json as _json
    try:
        r = subprocess.run(
            [probe, "-v", "error",
             "-show_entries", "stream=index,codec_type:stream_tags=language,title:stream_disposition=default,forced",
             "-of", "json", file_path],
            capture_output=True, timeout=60)
        d = _json.loads((r.stdout or b"{}").decode("utf-8", errors="replace"))
    except Exception:
        return {"audio": [], "subs": []}
    audio, subs = [], []
    for s in d.get("streams", []):
        tags = s.get("tags", {}) or {}
        disp = s.get("disposition", {}) or {}
        entry = {
            "index": s.get("index"),
            "title": tags.get("title") or "",
            "language": tags.get("language") or "",
            "default": bool(disp.get("default")),
        }
        if s.get("codec_type") == "audio":
            audio.append(entry)
        elif s.get("codec_type") == "subtitle":
            subs.append(entry)
    return {"audio": audio, "subs": subs}


# ─── Generación de thumbnail (misma lógica que webscrapper) ────────
def _find_ffprobe() -> Optional[str]:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None
    probe = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
    if os.path.isfile(probe):
        return probe
    import shutil
    p = shutil.which("ffprobe")
    return p or "ffprobe"


def _ffprobe_dimensions(file_path: str) -> tuple:
    probe = _find_ffprobe()
    if not probe:
        return 0, 0
    import subprocess
    try:
        r = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", file_path],
            capture_output=True, text=True, timeout=30)
        parts = r.stdout.strip().split(",")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0


def _get_frame_brightness(ffmpeg: str, video_path: str, time_sec: float) -> Optional[float]:
    import subprocess
    cmd = [ffmpeg, "-ss", str(time_sec), "-i", video_path,
           "-vframes", "1", "-vf", "signalstats,metadata=print", "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        for line in result.stderr.split("\n"):
            m = re.search(r"signalstats\.YAVG=([\d.]+)", line)
            if m:
                try:
                    return float(m.group(1)) / 255.0 * 100
                except Exception:
                    return None
    except Exception:
        pass
    return None


_THUMB_ATTEMPTS = [
    (0.40, 0.45),
    (0.35, 0.40),
    (0.30, 0.35),
    (0.20, 0.30),
    (0.10, 0.20),
]
_THUMB_BRIGHTNESS_MIN = 40
_THUMB_BRIGHTNESS_MAX = 80


def _select_thumbnail_time(ffmpeg: str, video_path: str, duration: float) -> float:
    best_time = min(duration * 0.25, 30)
    best_diff = float('inf')
    for start_pct, end_pct in _THUMB_ATTEMPTS:
        start_sec = duration * start_pct
        end_sec = duration * end_pct
        rand_time = random.uniform(start_sec, end_sec)
        brightness = _get_frame_brightness(ffmpeg, video_path, rand_time)
        if brightness is None:
            continue
        if _THUMB_BRIGHTNESS_MIN <= brightness <= _THUMB_BRIGHTNESS_MAX:
            return rand_time
        diff = min(abs(brightness - _THUMB_BRIGHTNESS_MIN), abs(brightness - _THUMB_BRIGHTNESS_MAX))
        if diff < best_diff:
            best_diff = diff
            best_time = rand_time
    return best_time


def _make_thumb(ffmpeg: str, video_path: str, thumb_path: str, thumb_time: float = 1.0):
    import subprocess
    w, h = _ffprobe_dimensions(video_path)
    if w <= 0 or h <= 0:
        w, h = 320, 240
    max_dim = 320
    if w > h:
        new_w = max_dim
        new_h = int(h * max_dim / w)
    else:
        new_h = max_dim
        new_w = int(w * max_dim / h)
    if new_w % 2:
        new_w += 1
    if new_h % 2:
        new_h += 1
    subprocess.run(
        [ffmpeg, "-y", "-ss", str(thumb_time), "-i", video_path,
         "-vf", f"scale={new_w}:{new_h}", "-vframes", "1", "-q:v", "2", thumb_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _generate_thumbnail(video_path: str, thumb_path: str) -> bool:
    """Genera un thumbnail (jpg) para un vídeo eligiendo el frame por luminosidad.
    Devuelve True si se generó."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False
    duration = _ffprobe_duration(video_path) or 0
    if duration > 0:
        thumb_time = _select_thumbnail_time(ffmpeg, video_path, duration)
    else:
        thumb_time = 5
    _make_thumb(ffmpeg, video_path, thumb_path, thumb_time)
    return os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 0


def _get_or_generate_thumb(video_path: str, cache_key: tuple) -> Optional[bytes]:
    """Devuelve los bytes del thumbnail del vídeo, generándolo si no existe en caché.
    cache_key = (channel_id, msg_id) para persistir el .thumb.jpg en caché."""
    thumb_cache = _cache_path(str(cache_key[0]), int(cache_key[1]), ".thumb.jpg")
    if os.path.isfile(thumb_cache) and os.path.getsize(thumb_cache) > 0:
        with open(thumb_cache, 'rb') as f:
            return f.read()
    if _generate_thumbnail(video_path, thumb_cache):
        with open(thumb_cache, 'rb') as f:
            return f.read()
    return None


def _cache_path(channel_id: str, msg_id: int, suffix: str) -> str:
    """Path estable en el caché para un episodio (channel_id + msg_id + sufijo)."""
    safe = str(channel_id).replace("-", "m").replace(":", "_")
    return os.path.join(_CACHE_DIR, f"{safe}_{msg_id}{suffix}")


def _cleanup_cache_except(channel_id: str, msg_id: Optional[int], suffix: str = None):
    """Elimina del caché los ficheros del canal que no correspondan al episodio en curso.
    Conserva TODOS los ficheros del episodio en curso (channel_id+msg_id, cualquier sufijo
    .raw/.mp4) para reanudar tras un fallo. Si msg_id es None, limpia todo el caché."""
    try:
        safe = str(channel_id).replace("-", "m").replace(":", "_")
        prefix = f"{safe}_"
        keep_prefix = f"{safe}_{msg_id}" if msg_id is not None else None
        for fn in os.listdir(_CACHE_DIR):
            if not fn.startswith(prefix):
                continue
            # Conservar el episodio en curso (cualquier sufijo del mismo msg_id)
            if keep_prefix is not None and fn.startswith(keep_prefix):
                continue
            try:
                os.remove(os.path.join(_CACHE_DIR, fn))
            except Exception:
                pass
    except Exception as e:
        print(f"[TGHirayi_v2] Error limpiando caché: {e}", flush=True)


def _delete_episode_cache(channel_id: str, msg_id: int):
    """Elimina del caché todos los ficheros de un episodio concreto
    (raw/mp4/meta.json/thumb.jpg) tras subirlo con éxito a todos los destinos.
    El único episodio que se conserva es el pendiente (lo mantiene
    _cleanup_cache_except al reanudar) por si la subida falla y hay que
    reutilizar el fichero descargado."""
    try:
        safe = str(channel_id).replace("-", "m").replace(":", "_")
        prefix = f"{safe}_{int(msg_id)}"
        for fn in os.listdir(_CACHE_DIR):
            if fn.startswith(prefix):
                try:
                    os.remove(os.path.join(_CACHE_DIR, fn))
                except Exception:
                    pass
    except Exception as e:
        print(f"[TGHirayi_v2] Error borrando caché de ep.{msg_id}: {e}", flush=True)


# Mapa de idiomas: código corto (ISO-639-2/1) → conjunto de sinónimos normalizados.
# Se usa para casar el código elegido por el usuario contra el tag `language` o `title`
# de las pistas del vídeo (los títulos no están normalizados: "español", "english", etc.).
_LANG_SYNONYMS = {
    "eng": {"eng", "en", "english", "ingles", "inglés", "anglais", "englisch"},
    "spa": {"spa", "es", "esp", "spanish", "español", "espanol", "castellano", "espagnol", "spanisch"},
    "jpn": {"jpn", "ja", "jap", "japanese", "japonés", "japones", "japonais", "japanisch"},
    "kor": {"kor", "ko", "korean", "coreano", "coréen", "koreanisch"},
    "chi": {"chi", "zho", "zh", "chinese", "chino", "chinois", "chinesisch", "mandarin", "mandarín", "mandarin"},
    "fra": {"fra", "fre", "fr", "french", "francés", "frances", "français", "französisch"},
    "deu": {"deu", "ger", "de", "german", "alemán", "aleman", "deutsch"},
    "ita": {"ita", "it", "italian", "italiano", "italien", "italienisch"},
    "por": {"por", "pt", "portuguese", "portugués", "portugues", "portugais", "portugiesisch"},
    "rus": {"rus", "ru", "russian", "ruso", "russe", "russisch"},
    "ara": {"ara", "ar", "arabic", "árabe", "arabe", "arabe"},
    "hin": {"hin", "hi", "hindi"},
    "tur": {"tur", "tr", "turkish", "turco", "türkçe", "turkce"},
    "pol": {"pol", "pl", "polish", "polaco", "polonais"},
    "nld": {"nld", "dut", "nl", "dutch", "neerlandés", "neerlandes", "holandés", "holandes"},
    "swe": {"swe", "sv", "swedish", "sueco", "suédois"},
    "nor": {"nor", "no", "norwegian", "noruego", "norvégien"},
    "dan": {"dan", "da", "danish", "danés", "danes", "danois"},
    "fin": {"fin", "fi", "finnish", "finlandés", "finlandes", "finnois"},
    "ces": {"ces", "cze", "cs", "czech", "checo", "tchèque"},
    "ell": {"ell", "gre", "el", "greek", "griego", "grec"},
    "hun": {"hun", "hu", "hungarian", "húngaro", "hungaro", "hongrois"},
    "heb": {"heb", "he", "hebrew", "hebreo", "hébreu"},
    "tha": {"tha", "th", "thai", "tailandés", "tailandes", "thaï"},
    "vie": {"vie", "vi", "vietnamese", "vietnamita", "vietnamien"},
    "ind": {"ind", "id", "indonesian", "indonesio", "indonésien"},
    "zho": {"zho", "zh", "chi", "chinese", "chino", "chinois"},
}


def _normalize_lang_text(s: str) -> str:
    """Sanitiza y normaliza a minúsculas un texto de idioma/título para comparar."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ñ", "n").replace("Ñ", "n").replace("ç", "c").replace("Ç", "c")
    return " ".join(s.lower().split())


def _lang_code_to_candidates(code: str) -> set:
    """Devuelve el conjunto de sinónimos normalizados para un código de idioma dado."""
    norm = _normalize_lang_text(code)
    for key, syns in _LANG_SYNONYMS.items():
        if norm in syns or norm == key:
            return syns
    # Código desconocido: usar tal cual
    return {norm}


def _find_stream_by_lang(file_path: str, stream_type: str, lang_code: str) -> Optional[int]:
    """Busca el índice de stream (absoluto) de tipo audio/subtítulo cuyo idioma coincida.
    Prioridad: campo `language`; si no, campo `title` (comparación por campo completo).
    Devuelve el índice o None si no se encuentra."""
    if not lang_code:
        return None
    candidates = _lang_code_to_candidates(lang_code)
    tracks = _ffprobe_tracks(file_path)
    stream_list = tracks.get("audio" if stream_type == "audio" else "subs", [])

    # 1) Por campo language
    for t in stream_list:
        if _normalize_lang_text(t.get("language") or "") in candidates:
            return int(t["index"])
    # 2) Por campo title (comparación por campo completo, ya normalizado)
    for t in stream_list:
        if _normalize_lang_text(t.get("title") or "") in candidates:
            return int(t["index"])
    return None


def _pid_alive(pid):
    """True si el proceso `pid` sigue vivo (sin señal)."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _kill_pid(pid):
    """Mata un proceso por pid (taskkill en Windows, SIGTERM en POSIX)."""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(int(pid))],
                           capture_output=True, timeout=30)
        else:
            os.kill(int(pid), 15)
    except Exception:
        pass


def _adopt_orphan_ffmpeg(resume_state, on_pct=None, on_detail=None, on_log=None):
    """Adopta un ffmpeg huérfano de un reinicio: espera por pid leyendo su fichero
    `-progress` (el mismo mecanismo de _run_ffmpeg_progress, pero sin Popen).
    resume_state debe traer pid, progress_file, base, span, duration, progress_pos, pass.
    Devuelve True si el proceso terminó él solo (maduró el output del pase en curso)."""
    pid = resume_state.get("pid")
    prog = resume_state.get("progress_file")
    if not _pid_alive(pid):
        return False
    base = float(resume_state.get("base") or 0.0)
    span = float(resume_state.get("span") or 100.0)
    duration = float(resume_state.get("duration") or 0.0)
    pos = int(resume_state.get("progress_pos") or 0)
    tail = b""
    last_ms = -1.0
    last_pct = -1.0
    last_log = 0.0
    pase = resume_state.get("pass", 0)
    detail = {"total_size": 0, "speed": 0.0, "fps": 0.0, "frame": 0, "out_time": ""}

    def _parse_line(line):
        nonlocal last_ms, last_pct
        if line.startswith("out_time_ms="):
            try:
                v = float(line.split("=", 1)[1]) / 1_000_000.0
            except ValueError:
                return
            if v > last_ms:
                last_ms = v
                if duration > 0:
                    pct = base + min(span, span * (v / duration))
                    last_pct = pct
                    if on_pct:
                        try:
                            on_pct(pct)
                        except Exception:
                            pass
        elif line.startswith("total_size=") or line.startswith("speed=") or \
             line.startswith("fps=") or line.startswith("frame=") or line.startswith("out_time="):
            key = line.split("=", 1)[0]
            try:
                if key == "total_size":
                    detail["total_size"] = int(float(line.split("=", 1)[1] or 0))
                elif key == "speed":
                    val = (line.split("=", 1)[1] or "0x").strip().rstrip("x")
                    if val.endswith("x"):
                        val = val[:-1]
                    detail["speed"] = float(val)
                elif key == "fps":
                    detail["fps"] = float(line.split("=", 1)[1])
                elif key == "frame":
                    detail["frame"] = int(line.split("=", 1)[1])
                elif key == "out_time":
                    detail["out_time"] = line.split("=", 1)[1]
            except (ValueError, TypeError):
                pass
            if on_detail:
                try:
                    on_detail(dict(detail))
                except Exception:
                    pass

    def _pump():
        nonlocal pos, tail
        if not prog or not os.path.isfile(prog):
            return
        try:
            with open(prog, "rb") as _f:
                _f.seek(pos)
                chunk = _f.read()
        except Exception:
            return
        if not chunk:
            return
        pos += len(chunk)
        buf = tail + chunk
        lines = buf.split(b"\n")
        tail = lines.pop()
        for raw in lines:
            try:
                _parse_line(raw.decode(errors="replace").strip())
            except Exception:
                continue

    while _pid_alive(pid):
        _pump()
        now = time.time()
        if on_log and now - last_log >= 45.0:
            last_log = now
            try:
                on_log(f"[TGHirayi_v2] [ARCHIVE] ffmpeg adoptado pid={pid} sigue ejecutándose "
                       f"(pase {pase}) · {last_pct:.1f}% de pase · "
                       f"{detail.get('speed', 0.0):.1f}x, {detail.get('fps', 0.0):.1f}fps")
            except Exception:
                pass
        time.sleep(0.5)
    try:
        _pump()  # volcado final
    except Exception:
        pass
    return True


def _run_ffmpeg_progress(cmd: list, duration: float, base: float = 0.0, span: float = 100.0,
                         on_pct=None, err_log: Optional[str] = None,
                         progress_path: Optional[str] = None,
                         proc_registry: Optional[dict] = None,
                         on_detail=None, resume_state: Optional[dict] = None,
                         pass_no: int = 0) -> Optional[int]:
    """Ejecuta ffmpeg con `-progress <fichero>` y desgrana `out_time_ms` del fichero para
    reportar el porcentaje normalizado al rango [base, base+span].
    En 2-pass: 1er pase → [0-50], 2º pase → [50-100]. Devuelve el exit code o None si no
    se pudo lanzar. err_log: archivo donde volcar stderr para diagnóstico.
    Usar fichero de progreso (en vez de `pipe:1`) evita deadlocks por backpressure del
    pipe de stdout y funciona igual en Windows, Linux y Docker.
    IMPORTANTE: ffmpeg escribe `out_time_ms` en MICROsegundos (mismo valor que out_time_us).
    Dividir entre 1_000_000 para obtener segundos.
    proc_registry: dict opcional para exponer el `Popen` en curso (matar desde API).
    on_detail: callback opcional que recibe un dict con métricas reales
    {total_size, speed, fps, frame, out_time} del fichero `-progress`.
    resume_state: dict opcional que se rellena en vivo (pid, cmd, progress_file, base, span,
    duration, progress_pos, pass...) para poder ADOPTAR un ffmpeg huérfano tras reinicio."""
    full = list(cmd)
    if progress_path:
        full += ["-progress", progress_path]
        if os.path.exists(progress_path):
            try:
                os.remove(progress_path)
            except Exception:
                pass
    else:
        full += ["-progress", "pipe:1"]
    _err = open(err_log, "wb") if err_log else subprocess.DEVNULL
    try:
        proc = subprocess.Popen(full,
                                stdout=subprocess.DEVNULL if progress_path else subprocess.PIPE,
                                stderr=_err,
                                universal_newlines=True, errors="replace", bufsize=1)
    except Exception:
        if err_log:
            try:
                _err.close()
            except Exception:
                pass
        return None
    if proc_registry is not None:
        proc_registry["proc"] = proc
    if resume_state is not None:
        resume_state.update({
            "pid": proc.pid,
            "cmd": full,
            "progress_file": progress_path,
            "err_log": err_log,
            "base": base,
            "span": span,
            "duration": duration,
            "pass": pass_no,
            "progress_pos": 0,
            "done": False,
        })

    def _report(elapsed_s: float):
        if duration > 0 and on_pct:
            on_pct(base + min(span, span * (float(elapsed_s) / duration)))

    def _metrics(kv: dict):
        if on_detail:
            try:
                on_detail(kv)
            except Exception:
                pass

    if progress_path:
        # Lectura incremental del fichero de progreso (por posiciones)
        pos = 0
        tail = b""
        last_ms = -1.0
        last_advance = time.time()
        detail = {"total_size": 0, "speed": 0.0, "fps": 0.0, "frame": 0, "out_time": ""}

        def _pump():
            nonlocal pos, tail, last_ms, last_advance
            if not os.path.isfile(progress_path):
                return
            try:
                with open(progress_path, "rb") as _f:
                    _f.seek(pos)
                    chunk = _f.read()
            except Exception:
                return
            if not chunk:
                return
            pos += len(chunk)
            if resume_state is not None:
                resume_state["progress_pos"] = pos
            buf = tail + chunk
            lines = buf.split(b"\n")
            tail = lines.pop()
            for raw in lines:
                line = raw.decode(errors="replace").strip()
                if line.startswith("out_time_ms="):
                    try:
                        # ¡OJO! ffmpeg escribe out_time_ms en microsegundos (== out_time_us).
                        v = float(line.split("=", 1)[1]) / 1_000_000.0
                    except ValueError:
                        continue
                    if v > last_ms:
                        last_ms = v
                        last_advance = time.time()
                        _report(v)
                elif line.startswith("total_size=") or line.startswith("speed=") or \
                     line.startswith("fps=") or line.startswith("frame=") or line.startswith("out_time="):
                    key = line.split("=", 1)[0]
                    raw_val = line.split("=", 1)[1] if "=" in line else ""
                    if key == "total_size":
                        try:
                            detail["total_size"] = int(raw_val or 0)
                        except (ValueError, TypeError):
                            pass
                    elif key == "speed":
                        val = (raw_val or "0x").strip().rstrip("x")
                        if val.endswith("x"):
                            val = val[:-1]
                        try:
                            detail["speed"] = float(val)
                        except ValueError:
                            pass
                    elif key == "fps":
                        try:
                            detail["fps"] = float(raw_val)
                        except ValueError:
                            pass
                    elif key == "frame":
                        try:
                            detail["frame"] = int(raw_val)
                        except ValueError:
                            pass
                    elif key == "out_time":
                        detail["out_time"] = raw_val
                    _metrics(detail)
                elif line == "progress=end":
                    pass

        try:
            while proc.poll() is None:
                try:
                    _pump()
                except Exception:
                    pass
                time.sleep(0.5)
            try:
                _pump()  # volcado final tras la salida de ffmpeg
            except Exception:
                pass
        finally:
            try:
                proc.wait(timeout=36000)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            rc = proc.returncode
            if proc_registry is not None and proc_registry.get("proc") is proc:
                proc_registry.pop("proc", None)
            if resume_state is not None:
                resume_state["done"] = True
                resume_state["rc"] = rc
        try:
            _err.close()
        except Exception:
            pass
        return rc

    # Fallback pipe:1 (sin progress_path)
    for raw in proc.stdout:
        line = raw.strip()
        if line.startswith("out_time_ms="):
            try:
                # MICROsegundos → segundos
                elapsed = float(line.split("=", 1)[1]) / 1_000_000.0
            except ValueError:
                continue
            if duration > 0 and on_pct:
                on_pct(base + min(span, span * (elapsed / duration)))
        elif line == "progress=end":
            break
    try:
        proc.wait(timeout=36000)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        rc = -1
    else:
        rc = proc.returncode
    if proc_registry is not None and proc_registry.get("proc") is proc:
        proc_registry.pop("proc", None)
    if err_log:
        try:
            _err.close()
        except Exception:
            pass
    return rc


def _normalize_video(input_path: str, file_name: str, audio_lang: str = "", sub_lang: str = "",
                     max_bytes: int = int(3.9 * 1024 ** 3), progress_log=None,
                     on_progress_pct=None, proc_registry: Optional[dict] = None,
                     on_detail=None, streaming: bool = False,
                     resume_state: Optional[dict] = None) -> Optional[str]:
    """Convierte un vídeo a MP4 compatible con Telegram (streaming, 1 mensaje < 4GB).
    Reglas:
    - MP4/M4V → remux -c copy +faststart (audio re-mapeado si se pide).
    - MKV con streaming=True → se sube tal cual: remux -c:v copy a MKV, solo cambiando
      pista de audio (audio_lang) si se indica. Es la ÚNICA excepción a la conversión.
    - CUALQUIER otro formato (AVI, WMV, MOV, FLV, WEBM, TS...) → conversión MP4 (libx265).
    - > 3.9GB o subs quemados → 2-pass con bitrate calculado para caber en ~3.8GB
      (1er paso analiza el vídeo → 2º paso codifica con bitrate CBR fijo y menor tamaño).
    Devuelve el path del MP4/MKV final o None si no se pudo (y se sube el original)."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        if progress_log:
            progress_log("ffmpeg no encontrado, se sube el original")
        return None
    import subprocess
    import shutil as _shutil

    ext = os.path.splitext(file_name or input_path)[1].lower()
    file_size = os.path.getsize(input_path)
    output_path = input_path + ".normalized.mp4"

    def log(m):
        if progress_log:
            progress_log(m)

    # Regla de conversión:
    #   - MP4/M4V → remux faststart (sin re-encode).
    #   - MKV con streaming_mkv → se sube tal cual (remux solo si se pide cambiar pista).
    #   - CUALQUIER otro formato (AVI, WMV, MOV, FLV, WEBM, TS...) → conversión MP4.
    #   - > max_bytes → 2-pass; subs a quemar → re-encode.
    is_mp4 = ext in (".mp4", ".m4v")
    is_mkv = ext == ".mkv"
    mkv_directo = bool(streaming) and is_mkv
    need_encode = sub_lang != "" or file_size > max_bytes or (not is_mp4 and not mkv_directo)
    rc = 0

    if mkv_directo and not audio_lang and not sub_lang and file_size <= max_bytes:
        # MKV en modo streaming sin cambios de pista.
        # Remux rapido con cues_to_front para que el indice de seek este al inicio
        # (requerido para HLS y seek en SmartTV antigua).
        out_path = input_path + ".faststart.mkv"
        cmd_cues = [ffmpeg, "-y", "-i", input_path, "-c", "copy", "-cues_to_front", "true", out_path]
        log("MKV streaming: remux con cues_to_front...")
        try:
            proc = subprocess.run(cmd_cues, capture_output=True, timeout=3600)
            if proc.returncode == 0 and os.path.isfile(out_path):
                log(f"cues_to_front OK: {out_path}")
                return out_path
            else:
                log(f"cues_to_front fallo (rc={proc.returncode}), subiendo tal cual")
                if os.path.isfile(out_path):
                    os.remove(out_path)
        except Exception as e:
            log(f"cues_to_front excepcion: {e}, subiendo tal cual")
            if os.path.isfile(out_path):
                os.remove(out_path)
        return input_path

    if not need_encode:
        # Remux: vídeo en copia (sin re-encode), audio re-mapeado (solo pista si se pide),
        # faststart en el caso MP4. Ahora SÍ se ejecuta (antes se construía y descartaba).
        out_path = input_path + (".mkv" if mkv_directo else ".normalized.mp4")
        duration = _ffprobe_duration(input_path)
        cmd = [ffmpeg, "-y", "-i", input_path]
        if audio_lang:
            _aidx = _find_stream_by_lang(input_path, "audio", audio_lang)
            if _aidx is not None:
                cmd += ["-map", "0:v:0", "-map", f"0:{_aidx}"]
            else:
                cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
        if mkv_directo:
            cmd += ["-c:v", "copy"]
            cmd += (["-c:a", "aac", "-b:a", "128k"] if audio_lang else ["-c:a", "copy"])
            cmd += [out_path]
            log("Remux MKV directo (vídeo copia, solo pista)...")
        else:
            # MP4 ya compatible: remux total en copia (+faststart), sin re-encode de nada.
            cmd += ["-c", "copy", "-movflags", "+faststart", out_path]
            log("Remux MP4 faststart...")
        rc = _run_ffmpeg_progress(cmd, duration or 0.0, 0.0, 100.0, on_progress_pct, None, None,
                                  proc_registry=proc_registry, on_detail=on_detail,
                                  resume_state=resume_state, pass_no=0)
        if rc in (None, 0):
            output_path = out_path
        else:
            # Remux no soportado (códec incompatible con el contenedor destino, p.ej. AVI
            # con DivX/Xvid) → degradar a conversión MP4 completa.
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass
            log("Remux no soportado para este códec, convirtiendo a MP4...")
            need_encode = True

    if need_encode:
        # Conversión / 2-pass. Calculamos bitrate para caber en ~3.8GB si supera el límite.
        duration = _ffprobe_duration(input_path)
        audio_bitrate_k = 128
        v_bitrate_k = None
        if file_size > max_bytes and duration > 0:
            target_bits = int(3.8 * 1024 ** 3 * 8)
            v_bitrate_k = max(200, min(30000, int((target_bits / duration) / 1000 - audio_bitrate_k)))

        vcodec_args = (["-c:v", "libx265", "-preset", _X265_PRESET, "-b:v", f"{v_bitrate_k}k", "-bufsize", f"{v_bitrate_k*2}k"]
                       if v_bitrate_k else
                       ["-c:v", "libx265", "-preset", _X265_PRESET, "-crf", "23", "-b:v", "4M", "-bufsize", "8M"])

        # Mapeo de audio: pista preferida (resuelta por idioma language→title) o la primera
        audio_map = ["-map", "0:v:0"]
        if audio_lang:
            _aidx = _find_stream_by_lang(input_path, "audio", audio_lang)
            if _aidx is not None:
                audio_map += ["-map", f"0:{_aidx}"]
            else:
                audio_map += ["-map", "0:a:0?"]
        else:
            audio_map += ["-map", "0:a:0?"]
        # Extraer subtítulos para quemar (resueltos por idioma language→title)
        sub_map = []
        if sub_lang:
            sub_extract = output_path + ".sub"
            _sidx = _find_stream_by_lang(input_path, "subtitle", sub_lang)
            if _sidx is not None:
                subcmd = [ffmpeg, "-y", "-i", input_path, "-map", f"0:{_sidx}", "-c:s", "srt", sub_extract]
            else:
                subcmd = [ffmpeg, "-y", "-i", input_path, "-map", "0:s:0?", "-c:s", "srt", sub_extract]
            try:
                subprocess.run(subcmd, capture_output=True, timeout=300)
            except Exception:
                sub_extract = None
            if sub_extract and os.path.isfile(sub_extract) and os.path.getsize(sub_extract) > 0:
                # Escapar la ruta para el filtro subtitles= (ffmpeg usa \: y \, como escapes)
                sub_esc = sub_extract.replace("\\", "\\\\").replace(":", "\\:").replace(",", "\\,")
                sub_map = ["-vf", f"subtitles={sub_esc}"]
            elif os.path.exists(sub_extract):
                os.remove(sub_extract)

        err_log = output_path + ".fferr"
        pass_log = output_path + ".2pass"
        progress_log_f = output_path + ".progress"
        if v_bitrate_k:
            # 2-pass real: pase 1 analiza y escribe las estadísticas (passlogfile),
            # pase 2 codifica usando esas estadísticas para ajustarse al tamaño objetivo.
            log(f"2-pass encode (bitrate {v_bitrate_k}k, preset {_X265_PRESET}) para caber en ~3.8GB...")
            pass1 = ([ffmpeg, "-y", "-i", input_path] + audio_map + vcodec_args + sub_map
                     + ["-pass", "1", "-passlogfile", pass_log,
                        "-an", "-f", "null", "NUL" if os.name == "nt" else "/dev/null"])
            rc1 = _run_ffmpeg_progress(pass1, duration, 0.0, 50.0, on_progress_pct,
                                       err_log, progress_log_f,
                                       proc_registry=proc_registry, on_detail=on_detail,
                                       resume_state=resume_state, pass_no=1)
            if rc1 is None:
                log("ffmpeg pase 1 no se pudo lanzar")
            elif rc1 != 0:
                log(f"ffmpeg pase 1 terminó con código {rc1}")
            pass2 = ([ffmpeg, "-y", "-i", input_path] + audio_map + vcodec_args + sub_map
                     + ["-pass", "2", "-passlogfile", pass_log,
                        "-c:a", "aac", "-b:a", f"{audio_bitrate_k}k",
                        "-movflags", "+faststart", output_path])
            if resume_state is not None:
                resume_state["cmd_pass2"] = pass2
            rc = _run_ffmpeg_progress(pass2, duration, 50.0, 50.0, on_progress_pct,
                                      err_log, progress_log_f,
                                      proc_registry=proc_registry, on_detail=on_detail,
                                      resume_state=resume_state, pass_no=2)
        else:
            log("Conversión a MP4 (libx265)...")
            pass2 = [ffmpeg, "-y", "-i", input_path] + audio_map + vcodec_args + sub_map + ["-c:a", "aac", "-b:a", f"{audio_bitrate_k}k", "-movflags", "+faststart", output_path]
            rc = _run_ffmpeg_progress(pass2, duration, 0.0, 100.0, on_progress_pct, err_log, progress_log_f,
                                      proc_registry=proc_registry, on_detail=on_detail,
                                      resume_state=resume_state, pass_no=0)

        if v_bitrate_k:
            # Limpiar ficheros del 2-pass (estadísticas y progreso)
            import glob as _glob
            for _tmp in _glob.glob(pass_log + "*"):
                try:
                    os.remove(_tmp)
                except Exception:
                    pass
        if os.path.exists(progress_log_f):
            try:
                os.remove(progress_log_f)
            except Exception:
                pass

        if rc not in (None, 0):
            tail = ""
            if err_log and os.path.isfile(err_log):
                try:
                    with open(err_log, 'rb') as _f:
                        tail = _f.read()[:300].decode(errors='replace')
                except Exception:
                    pass
            log(f"ffmpeg error: {tail}")

    # Limpiar sub temporal si quedó (solo en ruta encode)
    if need_encode:
        sub_tmp = output_path + ".sub"
        if os.path.exists(sub_tmp):
            try:
                os.remove(sub_tmp)
            except Exception:
                pass

    if os.path.exists(output_path) and os.path.getsize(output_path) > 1024 and rc in (None, 0):
        log(f"Normalizado OK: {os.path.getsize(output_path) / (1024*1024):.1f} MB")
        return output_path
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass
    return None



async def _fetch_cover_messages(client, channel_id, msg_id, topic_id=None, job: dict = None) -> list:
    """Mensajes del cover vía servicio central. Devuelve [{text, photo_bytes, msg_id}].
    Misma semántica que el original (ancla verificada, filtro de topic, parada
    en documento), sin objetos raw fuera del servicio."""
    if not channel_id or not msg_id:
        return []
    try:
        items = await _svc().fetch_cover_messages(
            channel_id, int(msg_id),
            topic_id=int(topic_id) if topic_id else None,
            **_svc_creds(job))
        if not items:
            print(f"[TGHirayi_v2] Cover msg {msg_id} sin cover válido en canal {channel_id} → sin cover", flush=True)
        return items or []
    except Exception as e:
        print(f"[TGHirayi_v2] Error fetching cover: {e}", flush=True)
        import traceback
        traceback.print_exc()
    return []


def _sanitize_title_tag(title: str) -> str:
    """Genera un hashtag de Telegram a partir del título: minúsculas, sin espacios,
    sin caracteres especiales. 'La Jungla De Cristal (2007)' → '#lajungladecristal2007'."""
    s = (title or "").lower()
    s = re.sub(r'[^a-z0-9]+', '', s)
    return ('#' + s) if s else ''


def _sanitize_file_title(file_name: str) -> tuple:
    """Sanitiza nombre de fichero a título legible + extensión.
    'Mi.Video_2024-1080p.mkv' -> ('Mi Video 2024 1080p', 'mkv')
    Devuelve (titulo_sanitizado_con_mayusculas, ext_sin_punto)."""
    if not file_name:
        return ("", "")
    import os as _os
    base = _os.path.basename(file_name or "")
    name, ext = _os.path.splitext(base)
    ext = ext.lstrip(".").lower()
    name = re.sub(r'[._\-]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if name:
        name = ' '.join(w.capitalize() for w in name.split())
    return (name, ext)


def _load_cover_tags() -> dict:
    """Carga el fichero editable de plantillas de f-tags (data/cover_tags.json).
    Cada f-tag define una plantilla con {value} como marcador del dato."""
    _DEFAULT_FTAGS = {
        "tagtitle": "{value}",
        "title": "Title: {value}",
        "original_title": "Original title: {value}",
        "titulo_original": "Original title: {value}",
        "title_es": "Title ES: {value}",
        "titulo_espana": "Title ES: {value}",
        "title_latam": "Title Latam: {value}",
        "title_mx": "Title Latam: {value}",
        "titulo_latino": "Title Latam: {value}",
        "alt_titles": "Alt titles: {value}",
        "titulos_alt": "Alt titles: {value}",
        "cast": "Cast: {value}",
        "reparto": "Cast: {value}",
        "actores": "Cast: {value}",
        "actors": "Cast: {value}",
        "year": "Year: {value}",
        "release_year": "Year: {value}",
        "rating": "Rating: {value}",
        "rating_count": "Rating count: {value}",
        "genres": "Genres: {value}",
        "generos": "Genres: {value}",
        "themes": "Themes: {value}",
        "temas": "Themes: {value}",
        "author": "Author: {value}",
        "autor": "Author: {value}",
        "director": "Director: {value}",
        "directores": "Director: {value}",
        "release_date": "Release date: {value}",
        "fecha": "Release date: {value}",
        "category": "Category: {value}",
        "categoria": "Category: {value}",
        "id": "ID: {value}",
        "cover": "Cover: {value}",
        "episodes": "Episodes: {value}",
        "ext": "Ext: {value}",
        "extension": "Ext: {value}",
        "description": "Description:\n{value}",
        "sinopsis": "Sinopsis:\n{value}",
        "overview": "Overview:\n{value}",
    }
    try:
        cfg_path = os.path.join(_DATA_DIR, "cover_tags.json")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ftags = cfg.get("ftags") or {}
        else:
            ftags = {}
    except Exception as e:
        print(f"[TGHirayi_v2] Error leyendo cover_tags.json: {e}", flush=True)
        ftags = {}
    merged = dict(_DEFAULT_FTAGS)
    for k, v in ftags.items():
        if isinstance(v, str):
            merged[k] = v
    return merged


def _cover_tag_values(title: str, total_episodes: int, details: dict) -> dict:
    """Construye el mapa de valores de los tags del cover a partir del job y del detalle del enriquecedor."""
    details = details or {}

    def _num(v):
        if v is None:
            return ""
        try:
            return str(round(float(v), 1))
        except Exception:
            return ""

    def _json_list(v):
        if not v:
            return ""
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                return ""
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return ""

    year = str(details.get("api_year") or details.get("api_release_date") or "")
    rating = _num(details.get("api_rating"))
    rating_line = ("★ " + rating) if rating else ""
    genres = _json_list(details.get("api_genres"))
    themes = _json_list(details.get("api_themes"))
    author = str(details.get("api_author") or "")
    director = str(details.get("api_director") or author)
    release_date = str(details.get("api_release_date") or "")
    description = str(details.get("api_description") or "")
    cover = _json_list(details.get("api_cover"))
    episodes = str(int(total_episodes or 0)) if (total_episodes or 0) > 0 else ""
    original_title = str(details.get("api_original_title") or "")
    title_es = str(details.get("api_title_es") or "")
    title_latam = str(details.get("api_title_latam") or "")
    alt_titles = _json_list(details.get("api_alt_titles"))
    cast = _json_list(details.get("api_cast"))

    tagtitle = _sanitize_title_tag(details.get("api_title") or title)

    return {
        "tagtitle": tagtitle,
        "title": str(details.get("api_title") or title or ""),
        "original_title": original_title,
        "titulo_original": original_title,
        "title_es": title_es,
        "titulo_espana": title_es,
        "title_latam": title_latam,
        "title_mx": title_latam,
        "titulo_latino": title_latam,
        "alt_titles": alt_titles,
        "titulos_alt": alt_titles,
        "cast": cast,
        "reparto": cast,
        "actores": cast,
        "actors": cast,
        "year": year,
        "release_year": year,
        "rating": rating_line,
        "rating_count": str(details.get("api_rating_count") or ""),
        "genres": genres,
        "generos": genres,
        "themes": themes,
        "temas": themes,
        "author": author,
        "autor": author,
        "director": director,
        "directores": director,
        "release_date": release_date,
        "fecha": release_date,
        "category": str(details.get("api_category") or ""),
        "categoria": str(details.get("api_category") or ""),
        "id": str(details.get("api_id") or ""),
        "cover": cover,
        "description": description,
        "sinopsis": description,
        "overview": description,
        "episodes": episodes,
        "ext": "",
        "extension": "",
    }


def _resolve_cover_tags(text: str, title: str, total_episodes: int, details: dict = None) -> str:
    """Resuelve los tags del texto del cover.

    Todos los tags ({title}, {ftitle}, {themes}, {fthemes}, ...) usan el formato
    definido en el fichero editable data/cover_tags.json usando {value} como
    marcador del dato. El prefijo 'f' es opcional: {key} y {fkey} son equivalentes.
    Si un tag no tiene dato, no se emite (se elimina su línea).
    {tagtitle} / {ftagtitle} solo se emiten si existe {title} o {ftitle} en el texto.
    """
    if not text:
        return text
    # El título se considera presente si existe {title} o {ftitle} en el texto
    has_title = ("{title}" in text) or ("{ftitle}" in text)
    values = _cover_tag_values(title, total_episodes, details)
    ftags = _load_cover_tags()
    out = text

    # Resolver todos los tags: {k} -> valor crudo, {fk} -> valor formateado (cover_tags.json)
    for k, tpl in ftags.items():
        val = values.get(k, "")
        raw_val = val
        rendered = tpl.replace("{value}", val) if val else ""
        if k == "tagtitle":
            # tagtitle solo si el título está presente en el texto
            if not has_title:
                raw_val = ""
                rendered = ""
        # Forma cruda {k} -> valor sin formato
        raw_form = "{" + k + "}"
        if raw_form in out:
            if raw_val:
                out = out.replace(raw_form, raw_val + "\n")
            else:
                out = out.replace(raw_form, "")
        # Forma formateada {fk} -> con plantilla de cover_tags.json
        f_form = "{f" + k + "}"
        if f_form in out:
            if rendered:
                out = out.replace(f_form, rendered + "\n")
            else:
                out = out.replace(f_form, "")

    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()


_SIMPLE_TAG_NAMES = (
    "tagtitle", "title", "original_title", "titulo_original",
    "title_es", "titulo_espana", "title_latam", "title_mx", "titulo_latino",
    "alt_titles", "titulos_alt", "cast", "reparto", "actores", "actors",
    "year", "release_year", "rating", "rating_count",
    "genres", "generos", "themes", "temas", "author", "autor", "director",
    "directores", "release_date", "fecha", "category", "categoria", "id", "cover",
    "description", "sinopsis", "overview", "episodes", "ext", "extension",
)


def _debug_cover_tags(text: str, title: str, total_episodes: int, details: dict = None) -> list:
    """Diagnóstico por tag: nº, nombre, valor resuelto (o 'vacío') y si tiene dato.
    Sirve para ver en el editor qué tags resuelven y cuáles quedan vacíos."""
    values = _cover_tag_values(title, total_episodes, details)
    ftags = _load_cover_tags()
    has_title = ("{title}" in text) or ("{ftitle}" in text)
    tag = _sanitize_title_tag(title)

    lines = []
    idx = 0

    def _add(tag_name, value, active=True):
        nonlocal idx
        idx += 1
        has = bool(str(value or "").strip())
        if tag_name == "tagtitle":
            has = has and has_title
        lines.append({
            "n": idx,
            "tag": "{" + tag_name + "}" if tag_name.startswith("f") else "{f" + tag_name + "}",
            "value": value or "",
            "has": bool(has),
        })

    # Tags simples presentes
    for k in _SIMPLE_TAG_NAMES:
        if "{" + k + "}" in text:
            _add(k, values.get(k, ""))

    # Tags con 'f' presentes
    for k, tpl in ftags.items():
        ftag = "{f" + k + "}"
        if ftag not in text:
            continue
        val = values.get(k, "")
        _add(k, val)

    return lines


async def _copy_messages_to_destination(client, messages, dest: dict, topic_id, delay: float, cover_text_override: str = None, poster_bytes: bytes = None, job: dict = None) -> List[int]:
    """Copia mensajes de cover al destino vía servicio central (sin objetos raw).

    `messages`: lista de {text, photo_bytes} (servicio fetch_cover_messages).
    Devuelve los msg_id creados en el destino (para verificación de cover).
    Modo ORIGINAL (cover_text_override None): cada mensaje tal cual.
    Modo EDITADO: UN SOLO mensaje con el texto generado + póster (o 1ª foto)."""
    svc = _svc()
    creds = _svc_creds(job)
    chat = dest["channel_id"]
    sent_ids: List[int] = []

    def _norm(m):
        if isinstance(m, dict):
            return (m.get("text") or "", m.get("photo_bytes"))
        return (getattr(m, 'message', None) or getattr(m, 'text', '') or '',
                getattr(m, 'photo_bytes', None))

    if cover_text_override is not None:
        text = cover_text_override
        chosen = poster_bytes
        if not chosen:
            for msg in messages:
                _, pb = _norm(msg)
                if pb:
                    chosen = pb
                    break
        try:
            if chosen:
                _mid = await svc.send_photo(chat, chosen, caption=text or None,
                                            reply_to_msg_id=topic_id if topic_id else None,
                                            **creds)
            else:
                _mid = await svc.send_text(chat, text,
                                           reply_to_msg_id=topic_id if topic_id else None,
                                           **creds)
            if _mid:
                sent_ids.append(int(_mid))
        except Exception as e:
            print(f"[TGHirayi_v2] Error enviando cover editado con imagen: {e}", flush=True)
            try:
                _mid = await svc.send_text(chat, text,
                                           reply_to_msg_id=topic_id if topic_id else None,
                                           **creds)
                if _mid:
                    sent_ids.append(int(_mid))
            except Exception as e2:
                print(f"[TGHirayi_v2] Error enviando cover editado (texto): {e2}", flush=True)
        await asyncio.sleep(delay)
        return sent_ids

    for msg in messages:
        try:
            text, photo_bytes = _norm(msg)
            if photo_bytes:
                _mid = await svc.send_photo(chat, photo_bytes, caption=text or None,
                                            reply_to_msg_id=topic_id if topic_id else None,
                                            **creds)
            elif (text or '').strip():
                _mid = await svc.send_text(chat, text,
                                           reply_to_msg_id=topic_id if topic_id else None,
                                           **creds)
            else:
                continue
            if _mid:
                sent_ids.append(int(_mid))
            await asyncio.sleep(delay)
        except Exception as e:
            print(f"[TGHirayi_v2] Error copying cover: {e}", flush=True)
    return sent_ids


async def _download_episode_media(client, episode: dict, source_channel_id, progress_callback=None,
                                   normalize_mp4: bool = False, audio_lang: str = "", sub_lang: str = "",
                                   streaming_mkv: bool = False, job: dict = None) -> List[dict]:
    """Descarga los ficheros adjuntos de un episodio.
    Si normalize_mp4 y es vídeo, normaliza a MP4 compatible (remux/conversión/2-pass).
    Además, los vídeos no-MP4 (AVI, WMV, MOV, WEBM...) se convierten SIEMPRE a MP4.
    Solo los MKV saltan la conversión si streaming_mkv está activo (se suben tal cual).
    Si streaming_mkv, sube el MKV tal cual (sin re-encode)."""
    result = []
    # Extraer chat_id del telegram_link (mismo metodo que el reproductor)
    chat_id = _extract_channel_id(episode.get("telegram_link", "")) or source_channel_id
    msg_id = episode.get("telegram_msg_id") or episode.get("msg_id")
    if not chat_id or not msg_id:
        print(f"[TGHirayi_v2] _download_episode_media: sin chat_id o msg_id (link={episode.get('telegram_link','')})", flush=True)
        return result

    # ── Reutilización temprana del caché (ANTES de get_messages, que puede fallar
    #    por desfase de esquema TL si el mensaje usa un constructor nuevo) ──
    raw_cache = _cache_path(chat_id, int(msg_id), ".raw")
    mp4_cache = _cache_path(chat_id, int(msg_id), ".mp4")
    mkv_cache = _cache_path(chat_id, int(msg_id), ".mkv")
    meta_cache = _cache_path(chat_id, int(msg_id), ".meta.json")

    def _load_meta():
        try:
            import json as _json
            if os.path.isfile(meta_cache):
                with open(meta_cache, 'r', encoding='utf-8') as f:
                    return _json.load(f)
        except Exception:
            pass
        return None

    use_cache = None
    meta = _load_meta()
    _meta_sz = int((meta or {}).get("size") or 0)
    def _cache_valid(p):
        # Un caché SOLO es reutilizable si su tamaño coincide con el que registró el sidecar
        # (si existe). Un .raw/.mp4 parcial de una sesión rota no debe reutilizarse.
        if not os.path.isfile(p):
            return False
        try:
            _s = os.path.getsize(p)
        except Exception:
            return False
        return _s > 1024 and (_meta_sz <= 0 or _s == _meta_sz)

    if normalize_mp4 and _cache_valid(mp4_cache):
        use_cache = mp4_cache
        print(f"[TGHirayi_v2] [CACHE] Reutilizando MP4 normalizado de ep.{msg_id}", flush=True)
    elif streaming_mkv and _cache_valid(mkv_cache):
        use_cache = mkv_cache
        print(f"[TGHirayi_v2] [CACHE] Reutilizando MKV directo de ep.{msg_id}", flush=True)
    elif _cache_valid(raw_cache):
        # Si hay .raw pero normalize_mp4 activo y no existe .mp4 → normalizar el .raw en lugar
        # de re-descargar (aprovecha la descarga ya hecha).
        if normalize_mp4 and _is_video_file(episode.get("file_name") or episode.get("title") or "video.mkv"):
            raw_fname = episode.get("file_name") or episode.get("title") or "video.mkv"
            print(f"[TGHirayi_v2] [CACHE] Normalizando .raw cacheado de ep.{msg_id}...", flush=True)
            def _norm_log(m):
                print(f"[TGHirayi_v2] [NORM] {m}", flush=True)
            _norm_last = [0.0]
            def _norm_pct(pct):
                if job is None:
                    return
                job["encode_progress"] = round(pct, 1)
                now = time.time()
                if now - _norm_last[0] >= 2.0:
                    _norm_last[0] = now
                    _persist_job(job)
            if job is not None:
                job["encode_progress"] = 0.0
                job["status_text"] = "Normalizando vídeo..."
                _persist_job(job)
            norm_out = await asyncio.to_thread(_normalize_video, raw_cache, raw_fname,
                                                   audio_lang=audio_lang, sub_lang=sub_lang, progress_log=_norm_log,
                                                   on_progress_pct=_norm_pct,
                                                   streaming=streaming_mkv)
            if job is not None:
                job["encode_progress"] = 100.0
                _persist_job(job)
            if norm_out and os.path.isfile(norm_out) and os.path.getsize(norm_out) > 1024:
                if norm_out == raw_cache:
                    # MKV directo sin cambios: no se generó fichero nuevo, subir el .raw tal cual.
                    use_cache = raw_cache
                    print(f"[TGHirayi_v2] [CACHE] MKV directo (sin procesar) de ep.{msg_id}", flush=True)
                elif streaming_mkv and norm_out.lower().endswith(".mkv"):
                    # MKV en modo streaming con cambio de pista: guardar en caché .mkv
                    os.replace(norm_out, mkv_cache)
                    use_cache = mkv_cache
                    print(f"[TGHirayi_v2] [CACHE] MKV directo cacheado: {os.path.getsize(mkv_cache)/(1024*1024):.1f} MB", flush=True)
                else:
                    os.replace(norm_out, mp4_cache)
                    use_cache = mp4_cache
                    print(f"[TGHirayi_v2] [CACHE] MP4 normalizado cacheado: {os.path.getsize(mp4_cache)/(1024*1024):.1f} MB", flush=True)
            else:
                use_cache = raw_cache
        else:
            use_cache = raw_cache
        if use_cache == raw_cache:
            print(f"[TGHirayi_v2] [CACHE] Reutilizando descarga de ep.{msg_id}", flush=True)

    if use_cache:
        if job is not None:
            job["dl_client"] = "cache"
        with open(use_cache, 'rb') as f:
            data = f.read()
        import base64 as _b64
        # Obtener dimensiones y duración reales del fichero (para asignar al thumb/vídeo)
        real_w, real_h = _ffprobe_dimensions(use_cache)
        real_dur = _ffprobe_duration(use_cache) or 0
        if meta:
            thumb_data = _b64.b64decode(meta.get("thumb_b64", "")) if meta.get("thumb_b64") else None
            fname = meta.get("file_name") or "video.mp4"
            mime = meta.get("mime_type", "application/octet-stream")
            dur = int(real_dur or meta.get("duration", 0) or 0)
            # Dimensiones REALES del fichero cacheado SIEMPRE prevalecen sobre el sidecar:
            # un meta de una sesión previa puede traer valores erróneos (p.ej. 320x320 de un
            # vídeo subido antes sin informar el tamaño) y no deben propagarse en una recopia.
            w = int(real_w or meta.get("width", 0) or 0)
            h = int(real_h or meta.get("height", 0) or 0)
        else:
            # Sin sidecar: usar metadatos mínimos (file_size real del disco + nombre del episode)
            thumb_data = None
            fname = episode.get("file_name") or episode.get("title") or "video.mp4"
            mime = "application/octet-stream"
            dur = int(episode.get("duration") or real_dur) or 0
            w = real_w
            h = real_h
            # Si el fichero era MKV/AVI y ahora lo reutilizamos, mantener extensión original
            if os.path.splitext(fname)[1].lower() not in ('.mp4', '.m4v', '.mkv', '.avi'):
                fname = fname + ('.mp4' if use_cache != mkv_cache else '.mkv')

        # Si no hay thumbnail y es vídeo, generarlo a partir del fichero (frame por luminosidad).
        # Un vídeo reutilizado con fname sin extensión (p.ej. 'file', 'Archivo Sin Nombre')
        # no pasa el check de extensión → falso-negativo. Si ffprobe detecta dimensiones reales
        # (w/h > 0), es un vídeo aunque el nombre no tenga extensión.
        is_video = _is_video_file(fname)
        if is_video and not thumb_data:
            print(f"[TGHirayi_v2] [THUMB] Generando thumbnail para ep.{msg_id}...", flush=True)
            thumb_data = _get_or_generate_thumb(use_cache, (chat_id, int(msg_id)))
            if thumb_data:
                print(f"[TGHirayi_v2] [THUMB] Thumbnail generado: {len(thumb_data)} bytes", flush=True)
        elif not is_video and (real_w or real_h) and not thumb_data:
            # fname sin extensión pero fichero real con vídeo → forzar extensión .mp4
            is_video = True
            fname = (os.path.splitext(fname)[0] or f"ep{int(msg_id)}") + '.mp4'
            print(f"[TGHirayi_v2] [CACHE] Fichero vídeo sin extensión → '{fname}'", flush=True)
            thumb_data = _get_or_generate_thumb(use_cache, (chat_id, int(msg_id)))
            if thumb_data:
                print(f"[TGHirayi_v2] [THUMB] Thumbnail generado: {len(thumb_data)} bytes", flush=True)
        if is_video:
            mime = "video/x-matroska" if fname.lower().endswith(".mkv") else "video/mp4"

        result.append({
            "data": data,
            "file_name": fname,
            "file_size": len(data),
            "mime_type": mime,
            "attributes": [],
            "thumb_data": thumb_data,
            "video_attrs": None,
            "duration": dur,
            "width": w,
            "height": h,
        })
        return result

    try:
        info = await _svc().get_file_info(chat_id, int(msg_id), **_svc_creds(job))
        if not info or not info.get("size"):
            # El servicio devuelve None tanto si falta media como si falló el
            # transporte. Si la BD espera fichero, sondear el MISMO cliente que
            # usa el servicio (su pool, no el del userbot) antes de darlo por
            # borrado. Solo sin credencial explícita (la que usa el servicio
            # por defecto).
            try:
                _exp_sz = int(episode.get("file_size") or 0)
            except Exception:
                _exp_sz = 0
            if _exp_sz > 0 and not (_svc_creds(job) or {}).get("session_string"):
                try:
                    _svc_pool_cli = await asyncio.wait_for(_svc().pool.get_client(None, "telethon"), timeout=25)
                    await asyncio.wait_for(_svc_pool_cli.get_me(), timeout=25)
                except Exception as _e_me:
                    if _is_auth_dead(str(_e_me)):
                        raise RuntimeError("TGSESSION_DEAD: " + str(_e_me)[:200])
            print(f"[TGHirayi_v2] ep.{msg_id} sin documento en origen (mensaje vacío, sin media o borrado)", flush=True)
            return result
        file_size = int(info.get("size") or 0)

        last_up = [0.0]
        def _dl_progress(current, total):
            if progress_callback:
                now = time.perf_counter()
                if now - last_up[0] >= 1.0:
                    last_up[0] = now
                    progress_callback("download", current, total)

        # Nombre original del fichero
        fname = info.get("file_name") or ''
        # Detección de vídeo: extensión del nombre O mime del documento.
        is_video = _is_video_file(fname)
        if not is_video:
            _doc_mime = (info.get("mime_type") or '').lower()
            if _doc_mime.startswith('video/'):
                is_video = True
        if is_video and not _is_video_file(fname):
            # Vídeo sin extensión en el nombre (p.ej. 'file', 'Archivo Sin Nombre')
            # → conservar el stem y añadir .mp4 para que Telegram lo trate como vídeo.
            _stem = os.path.splitext(fname)[0].strip() or f"ep{int(msg_id)}"
            fname = _stem + '.mp4'
            print(f"[TGHirayi_v2] Vídeo sin extensión → asignado nombre '{fname}'", flush=True)
        fname = fname or 'file'
        is_video = _is_video_file(fname)

        # Thumbs del documento: solo se descargan para no-vídeo (vía servicio).
        # Para vídeo se genera SIEMPRE desde el fichero final (proporción real).
        thumb_data = None
        if (not is_video) and info.get("has_thumb"):
            try:
                _tr = await _svc().fetch_thumb(chat_id, int(msg_id), **_svc_creds(job))
                thumb_data = (_tr.get("data") if isinstance(_tr, dict) else _tr) or None
                if thumb_data:
                    print(f"[TGHirayi_v2] Thumbnail descargado: {len(thumb_data)} bytes", flush=True)
            except Exception as e:
                print(f"[TGHirayi_v2] Error descargando thumbnail: {e}", flush=True)

        # Atributos de video (duracion, ancho, alto) desde el servicio
        video_attrs = None
        duration = int(info.get("duration") or 0)
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)

        # ── Caché en disco: reutilizar descarga/normalización si ya existe ──
        raw_cache = _cache_path(chat_id, int(msg_id), ".raw")
        mp4_cache = _cache_path(chat_id, int(msg_id), ".mp4")
        mkv_cache = _cache_path(chat_id, int(msg_id), ".mkv")

        # doc_size esperado (verifica que un .raw no sea un parcial de una sesión rota).
        _exp_size = int(info.get("size") or 0)

        use_cache = None
        if normalize_mp4 and is_video and os.path.isfile(mp4_cache) and os.path.getsize(mp4_cache) > 1024:
            use_cache = mp4_cache
            print(f"[TGHirayi_v2] [CACHE] Reutilizando MP4 normalizado de ep.{msg_id}", flush=True)
        elif streaming_mkv and os.path.isfile(mkv_cache) and os.path.getsize(mkv_cache) > 1024:
            use_cache = mkv_cache
            print(f"[TGHirayi_v2] [CACHE] Reutilizando MKV directo de ep.{msg_id}", flush=True)
        elif os.path.isfile(raw_cache) and os.path.getsize(raw_cache) > 1024 and (_exp_size <= 0 or os.path.getsize(raw_cache) == _exp_size):
            use_cache = raw_cache
            print(f"[TGHirayi_v2] [CACHE] Reutilizando descarga de ep.{msg_id}", flush=True)
        else:
            # Un .raw parcial (tamaño != doc_size) de una sesión anterior NO es válido.
            if os.path.isfile(raw_cache) and _exp_size > 0 and os.path.getsize(raw_cache) != _exp_size:
                print(f"[TGHirayi_v2] [CACHE] .raw de ep.{msg_id} incompleto ({os.path.getsize(raw_cache)}/{_exp_size}), redescargando", flush=True)
                use_cache = None

        if use_cache:
            with open(use_cache, 'rb') as f:
                data = f.read()
            file_size = len(data)
            if use_cache == mp4_cache and os.path.splitext(fname)[1].lower() not in ('.mp4', '.m4v'):
                fname = os.path.splitext(fname)[0] + '.mp4'
        else:
            # Descargar a disco (caché) — NO se elimina tras usar (reutilizable ante fallos)
            print(f"[TGHirayi_v2] Descargando ep.{msg_id} a caché...", flush=True)
            tmp_dl = raw_cache + ".tmp"
            chunks_side = tmp_dl + ".chunks"
            try:
                # v2: descarga centralizada (servicio core). Pyro primero si hay
                # sesión (fast), si no Telethon multi-conexión.
                # Mismos términos: reanudable, validación por tamaño, fallback.
                from tvcat.services import file_transfer as _ft
                data = None
                dl_cfg = _load_config()
                dl_threads = max(1, min(16, int(dl_cfg.get("download_threads", 8) or 8)))
                downloaded = False
                doc_size = int(info.get("size") or 0)
                try:
                    _pyro_dl = await asyncio.wait_for(_get_pyrogram_client(), 12)
                except Exception:
                    _pyro_dl = None
                if _pyro_dl is not None:
                    _dc, _dt = _pyro_dl, "pyrogram"
                else:
                    _dc, _dt = client, "telethon"
                if job is not None:
                    job["dl_client"] = _dt
                try:
                    got = await _ft.download_file(_dc, chat_id, msg_id, tmp_dl,
                                                  threads=dl_threads, progress=_dl_progress,
                                                  client_type=_dt, pre_msg=None)
                except Exception as _e_dl:
                    # Cliente muerto bajo los pies (storage cerrado, conexión
                    # perdida, blip de red): refrescar cliente y reintentar una vez.
                    _e_txt = str(_e_dl)
                    if any(k in _e_txt for k in ("storage pyro no disponible", "closed database",
                                                "Connection lost", "has not been started",
                                                "socket", "Server closed", "Timeout")):
                        try:
                            _dc = await asyncio.wait_for(_refresh_pyrogram_client(), 30)
                            _dt = "pyrogram"
                            if job is not None:
                                job["dl_client"] = _dt
                            got = await _ft.download_file(_dc, chat_id, msg_id, tmp_dl,
                                                          threads=dl_threads, progress=_dl_progress,
                                                          client_type=_dt)
                        except Exception as _e_dl2:
                            print(f"[TGHirayi_v2] Descarga tras refresh falló: {_e_dl2}", flush=True)
                            got = None
                    else:
                        raise
                if got and os.path.isfile(tmp_dl) and (doc_size <= 0 or os.path.getsize(tmp_dl) == doc_size):
                    downloaded = True
                    print(f"[TGHirayi_v2] Descarga central OK ep.{msg_id} ({os.path.getsize(tmp_dl)/(1024*1024):.1f} MB, {_dt})", flush=True)
                # SOLO promover a .raw cuando el tamaño coincide EXACTAMENTE con doc.size.
                # Un parcial (descarga a medias tras reinicio) nunca debe quedar como
                # "descargado": si lo hiciera, el flujo subiría media película como buena.
                if downloaded and doc_size > 0 and os.path.isfile(tmp_dl) and os.path.getsize(tmp_dl) == doc_size:
                    try:
                        os.remove(chunks_side)
                    except Exception:
                        pass
                    os.replace(tmp_dl, raw_cache)
                elif downloaded and isinstance(data, bytes) and len(data) > 1024 and (doc_size <= 0 or len(data) == doc_size):
                    with open(raw_cache, 'wb') as f:
                        f.write(data)
                else:
                    # Incompleta: sin .raw válido → no se sube nada.
                    print(f"[TGHirayi_v2] Descarga ep.{msg_id} incompleta ({os.path.getsize(tmp_dl) if os.path.isfile(tmp_dl) else 0}/{doc_size} bytes), reintentará", flush=True)
                    for _junk in (tmp_dl, chunks_side):
                        try:
                            os.remove(_junk)
                        except Exception:
                            pass
                    return result
                # Evitar cargar 3GB en RAM: para ficheros grandes keep file_path
                _raw_sz = os.path.getsize(raw_cache) if os.path.isfile(raw_cache) else 0
                if _raw_sz > 500 * 1024 * 1024:
                    data = b""
                    file_size = _raw_sz
                    _raw_large_path = raw_cache
                else:
                    with open(raw_cache, 'rb') as f:
                        data = f.read()
                    file_size = len(data)
                    _raw_large_path = None
            except Exception as e:
                print(f"[TGHirayi_v2] Error descargando media: {e}", flush=True)
                import traceback as _tb; _tb.print_exc()
                if os.path.exists(tmp_dl):
                    try:
                        os.remove(tmp_dl)
                    except Exception:
                        pass
                return result

            # Normalización MP4 (solo vídeo y si está activa) → guarda en caché .mp4
            if normalize_mp4 and is_video and file_size > 1024:
                def _norm_log(m):
                    print(f"[TGHirayi_v2] [NORM] {m}", flush=True)
                _norm_last = [0.0]
                def _norm_pct(pct):
                    if job is None:
                        return
                    job["encode_progress"] = round(pct, 1)
                    now = time.time()
                    if now - _norm_last[0] >= 2.0:
                        _norm_last[0] = now
                        _persist_job(job)
                if job is not None:
                    job["encode_progress"] = 0.0
                    job["status_text"] = "Normalizando vídeo..."
                    _persist_job(job)
                norm_out = await asyncio.to_thread(_normalize_video, raw_cache, fname,
                                                   audio_lang=audio_lang, sub_lang=sub_lang, progress_log=_norm_log,
                                                   on_progress_pct=_norm_pct,
                                                   streaming=streaming_mkv)
                if job is not None:
                    job["encode_progress"] = 100.0
                    _persist_job(job)
                if norm_out and os.path.isfile(norm_out) and os.path.getsize(norm_out) > 1024:
                    if norm_out == raw_cache:
                        # MKV directo sin cambios: no se generó fichero nuevo, subir el .raw tal cual.
                        print(f"[TGHirayi_v2] [NORM] MKV directo (sin procesar): {file_size / (1024*1024):.1f} MB", flush=True)
                    elif streaming_mkv and norm_out.lower().endswith(".mkv"):
                        # MKV en modo streaming con cambio de pista: se sube tal cual.
                        os.replace(norm_out, mkv_cache)
                        _mkv_sz = os.path.getsize(mkv_cache) if os.path.isfile(mkv_cache) else 0
                        if _mkv_sz > 500 * 1024 * 1024:
                            data = b""
                            file_size = _mkv_sz
                            _large_path = mkv_cache
                        else:
                            with open(mkv_cache, 'rb') as f:
                                data = f.read()
                            file_size = len(data)
                            _large_path = None
                        if os.path.splitext(fname)[1].lower() not in ('.mkv',):
                            fname = os.path.splitext(fname)[0] + '.mkv'
                        mime = "video/x-matroska"
                        print(f"[TGHirayi_v2] [NORM] MKV directo cacheado: {file_size / (1024*1024):.1f} MB", flush=True)
                    else:
                        os.replace(norm_out, mp4_cache)
                        _mp4_sz = os.path.getsize(mp4_cache) if os.path.isfile(mp4_cache) else 0
                        if _mp4_sz > 500 * 1024 * 1024:
                            data = b""
                            file_size = _mp4_sz
                            _large_path = mp4_cache
                        else:
                            with open(mp4_cache, 'rb') as f:
                                data = f.read()
                            file_size = len(data)
                            _large_path = None
                        if os.path.splitext(fname)[1].lower() not in ('.mp4', '.m4v'):
                            fname = os.path.splitext(fname)[0] + '.mp4'
                        print(f"[TGHirayi_v2] [NORM] MP4 final cacheado: {file_size / (1024*1024):.1f} MB", flush=True)

            # Si no hay thumbnail y es vídeo, generarlo a partir del fichero final
            _norm_is_mkv = streaming_mkv and os.path.isfile(mkv_cache) and os.path.getsize(mkv_cache) > 1024
            final_path = (mkv_cache if _norm_is_mkv else
                          mp4_cache if (normalize_mp4 and os.path.isfile(mp4_cache) and os.path.getsize(mp4_cache) > 1024) else
                          raw_cache)
            if not thumb_data and is_video and os.path.isfile(final_path):
                print(f"[TGHirayi_v2] [THUMB] Generando thumbnail para ep.{msg_id}...", flush=True)
                thumb_data = _get_or_generate_thumb(final_path, (chat_id, int(msg_id)))
                if thumb_data:
                    print(f"[TGHirayi_v2] [THUMB] Thumbnail generado: {len(thumb_data)} bytes", flush=True)
            elif not thumb_data and not is_video and os.path.isfile(final_path):
                # Fallback por contenido: fname sin extensión ni mime video (p.ej. 'file')
                # pero el fichero real tiene vídeo → forzar .mp4 y generar thumbnail.
                _cw, _ch = _ffprobe_dimensions(final_path)
                if _cw or _ch:
                    is_video = True
                    fname = (os.path.splitext(fname)[0] or f"ep{int(msg_id)}") + '.mp4'
                    print(f"[TGHirayi_v2] [THUMB] Contenido vídeo, asignado '{fname}'", flush=True)
                    thumb_data = _get_or_generate_thumb(final_path, (chat_id, int(msg_id)))
                    if thumb_data:
                        print(f"[TGHirayi_v2] [THUMB] Thumbnail generado: {len(thumb_data)} bytes", flush=True)

            # Atributos de vídeo correctos: las dimensiones REALES del fichero descargado
            # SIEMPRE prevalecen sobre las del documento de origen. Un documento puede traer
            # metadatos desactualizados/erróneos (p.ej. 320x320 de una subida previa sin el
            # tamaño real informado → thumbnail cuadrado). Solo se usan las del documento si
            # ffprobe no consigue leer el fichero descargado.
            if is_video and os.path.isfile(final_path):
                _dw, _dh = _ffprobe_dimensions(final_path)
                if _dw > 0 and _dh > 0:
                    width, height = _dw, _dh
                if not duration:
                    _dr = _ffprobe_duration(final_path) or 0
                    if _dr:
                        duration = int(_dr)

            # Guardar sidecar de metadatos para poder reutilizar el caché sin get_messages.
            # Se hace DESPUÉS de los fixes (fname/mime/thumb/attrs) para persistir los
            # valores corregidos y que la reutilización posterior no vuelva a degradarlos.
            try:
                import json as _json, base64 as _b64
                _meta_mime = "video/mp4" if (is_video and not (info.get("mime_type") or '')) else (info.get("mime_type") or 'application/octet-stream')
                meta = {
                    "file_name": fname or 'file',
                    "mime_type": _meta_mime,
                    "duration": int(duration or 0),
                    "width": int(width or 0),
                    "height": int(height or 0),
                    "size": int(file_size or 0),
                    "thumb_b64": _b64.b64encode(thumb_data).decode('ascii') if thumb_data else "",
                    "attributes": [],
                }
                with open(meta_cache, 'w', encoding='utf-8') as f:
                    _json.dump(meta, f)
            except Exception as e:
                print(f"[TGHirayi_v2] Error guardando sidecar: {e}", flush=True)

            # For large files (>500MB) we keep data empty and use file_path to avoid 3GB RAM
            _file_path = None
            if (not data or len(data) == 0) and file_size > 500 * 1024 * 1024:
                # Prefer the actual cached file on disk (mp4/mkv/raw)
                try:
                    _cand = None
                    if '_large_path' in locals() and locals().get('_large_path') and os.path.isfile(locals().get('_large_path')):
                        _cand = locals().get('_large_path')
                    elif '_raw_large_path' in locals() and locals().get('_raw_large_path') and os.path.isfile(locals().get('_raw_large_path')):
                        _cand = locals().get('_raw_large_path')
                    elif 'final_path' in locals() and locals().get('final_path') and os.path.isfile(locals().get('final_path')):
                        _cand = locals().get('final_path')
                    if _cand and os.path.getsize(_cand) == file_size:
                        _file_path = _cand
                    elif os.path.isfile(raw_cache) and os.path.getsize(raw_cache) == file_size:
                        _file_path = raw_cache
                    elif os.path.isfile(mp4_cache) and os.path.getsize(mp4_cache) == file_size:
                        _file_path = mp4_cache
                except Exception:
                    pass
            result.append({
                "data": data,
                "file_name": fname or 'file',
                "file_size": file_size,
                "file_path": _file_path,
                "mime_type": info.get("mime_type") or "application/octet-stream",
                "attributes": [],
                "thumb_data": thumb_data,
                "video_attrs": video_attrs,
                "duration": duration,
                "width": width,
                "height": height,
            })
    except Exception as e:
        if _is_auth_dead(str(e)):
            raise
        print(f"[TGHirayi_v2] Error downloading media: {e}", flush=True)
        import traceback as _tb; _tb.print_exc()
    return result




# v2: migrado al servicio central (services/file_transfer).
# Ver download_file / upload_file.




# v2: migrado al servicio central (services/file_transfer).
# Ver download_file / upload_file.


async def _upload_episode_to_destination(client, pyro_client, episode: dict, media_data: list, dest: dict, topic_id, delay: float, progress_callback=None, job: dict = None) -> List[int]:
    """Sube un episodio (texto + ficheros) a un destino.
    F3: si hay sesión Pyrofork, subida rápida directa desde disco (cualquier tamaño).
    Telethon: >10MB con upload paralelo (upload_threads) y block size (part_size_kb, máx 512KB).
    Pyrogram (>=1.9GB obligatorio): ficheros >1.9GB.
    Devuelve la lista de msg_id creados en el destino."""
    print(f"[TGHirayi_v2] [UPLOAD] inicio: {len(media_data or [])} fichero(s), pyro={'SI' if pyro_client else 'NO'} (build 20260909-dbg)", flush=True)
    cfg = _load_config()
    block_kb = int(cfg.get("download_chunk_size_kb", 1024) or 1024)
    # MTProto: una parte de upload máximo 512KB
    part_size_kb = max(32, min(block_kb, 512))
    threads = max(1, int(cfg.get("upload_threads", 4) or 4))
    BIG_FILE_LIMIT = int(1.9 * 1024 * 1024 * 1024)  # <1.9GB Telethon, >=1.9GB Pyrogram (Telethon no sube >2GB)
    BIG_UPLOAD_THRESHOLD = 10 * 1024 * 1024
    sent_ids: List[int] = []

    channel_id = int(dest["channel_id"])
    text = episode.get("caption") or episode.get("title") or episode.get("episode_title", "")

    if media_data:
        for md in media_data:
            try:
                last_ul = [0.0]
                async def _ul_progress(current, total):
                    if progress_callback:
                        now = time.perf_counter()
                        if now - last_ul[0] >= 1.0:
                            last_ul[0] = now
                            from telethon import helpers as _tl_helpers
                            await _tl_helpers._maybe_await(progress_callback("upload", current, total))

                # Construir atributos de video correctos (estilo webscrapper)
                import io as _io
                video_attrs = md.get("video_attrs")
                fsize = int(md.get("file_size") or 0)

                # Pyrogram para ficheros >=1.9GB (Telethon no sube >2GB ni con premium).
                if fsize > BIG_FILE_LIMIT and not pyro_client:
                    try:
                        pyro_client = await _get_pyrogram_client()
                    except Exception as e:
                        raise RuntimeError(
                            f"Fichero de {fsize/(1024**3):.2f}GB requiere Pyrogram "
                            f"(Telethon no sube >2GB) y no está disponible: {e}"
                        )
                    if not pyro_client:
                        raise RuntimeError(
                            f"Fichero de {fsize/(1024**3):.2f}GB requiere Pyrogram y no está disponible. "
                            f"Genera la sesión Pyrogram en Configuración → Userbot."
                        )

                # Guardar en archivo temporal o usar file_path directo (evitar 3GB en RAM)
                import tempfile as _tmp
                fname = md.get("file_name", "video.mp4")
                _fpath = md.get("file_path")
                _is_temp = True
                if _fpath and os.path.isfile(_fpath):
                    tmp_name = _fpath
                    _is_temp = False
                else:
                    tmp = _tmp.NamedTemporaryFile(suffix='_' + fname, delete=False)
                    data_bytes = md.get("data") or b""
                    if data_bytes:
                        tmp.write(data_bytes)
                    tmp.close()
                    tmp_name = tmp.name
                    _is_temp = True
                try:
                    # v2: subida centralizada (servicio core). Pyro primero si hay
                    # sesión (fast multi-sesión, cualquier tamaño incl. >1.9GB),
                    # si no Telethon (directo/paralelo). Mismos términos.
                    from tvcat.services import file_transfer as _ft
                    _pyro_up = pyro_client
                    if _pyro_up is None and _PYRO_FAST_OK is not False:
                        try:
                            _pyro_up = await asyncio.wait_for(_get_pyrogram_client(), 12)
                            globals()["_PYRO_FAST_OK"] = True
                        except Exception:
                            globals()["_PYRO_FAST_OK"] = False
                            _pyro_up = None
                    if _pyro_up is not None:
                        _uc, _ut = _pyro_up, "pyrogram"
                    else:
                        _uc, _ut = client, "telethon"
                    if job is not None:
                        job["ul_client"] = _ut
                    try:
                        _mid = await _ft.upload_file(
                            _uc, channel_id, tmp_name, fname, caption=text or None,
                            thumb_bytes=md.get("thumb_data"),
                            is_video=_is_video_file(fname),
                            duration=int(md.get("duration", 0) or 0),
                            width=int(md.get("width", 0) or 0),
                            height=int(md.get("height", 0) or 0),
                            reply_to_msg_id=topic_id if topic_id else None,
                            threads=threads, part_size_kb=part_size_kb,
                            progress=_ul_progress, client_type=_ut)
                    except Exception as _e_ul:
                        # Cliente muerto a mitad de subida (storage cerrado,
                        # desconexión, blip): refrescar y reintentar una vez.
                        _e_txt = str(_e_ul)
                        if _ut == "pyrogram" and any(k in _e_txt for k in (
                                "storage pyro no disponible", "closed database",
                                "has not been started", "not connected",
                                "Connection lost", "ConnectionError",
                                "socket", "Server closed", "Timeout")):
                            _uc = await asyncio.wait_for(_refresh_pyrogram_client(), 30)
                            _mid = await _ft.upload_file(
                                _uc, channel_id, tmp_name, fname, caption=text or None,
                                thumb_bytes=md.get("thumb_data"),
                                is_video=_is_video_file(fname),
                                duration=int(md.get("duration", 0) or 0),
                                width=int(md.get("width", 0) or 0),
                                height=int(md.get("height", 0) or 0),
                                reply_to_msg_id=topic_id if topic_id else None,
                                threads=threads, part_size_kb=part_size_kb,
                                progress=_ul_progress, client_type="pyrogram")
                        else:
                            raise
                    if _mid:
                        sent_ids.append(int(_mid))
                        print(f"[TGHirayi_v2] Subida central OK ({fsize/(1024*1024):.1f} MB, {_ut})", flush=True)
                finally:
                    if _is_temp:
                        try:
                            os.unlink(tmp_name)
                        except Exception:
                            pass
                await asyncio.sleep(delay)
            except Exception as e:
                print(f"[TGHirayi_v2] Error upload: {e}", flush=True)
                raise  # El job debe fallar, no marcarse como completado
    else:
        if text:
            try:
                _mid = await _svc().send_text(channel_id, text,
                                              reply_to_msg_id=topic_id if topic_id else None,
                                              **_svc_creds(job))
                if _mid:
                    sent_ids.append(int(_mid))
                await asyncio.sleep(delay)
            except Exception as e:
                print(f"[TGHirayi_v2] Error sending text: {e}", flush=True)
                raise

    return sent_ids


async def _channel_is_owner(client, channel_id, job: dict = None) -> bool:
    """Determina si el canal/grupo pertenece a la cuenta del userbot (vía servicio)."""
    try:
        return bool(await _svc().check_owner(channel_id, **_svc_creds(job)))
    except Exception as e:
        print(f"[TGHirayi_v2] Error detectando propietario del canal: {e}", flush=True)
        return False


async def _forward_episode_from_origin(client, source_channel_id, episode: dict, target_dest: dict, topic_id, delay: float, job: dict = None) -> List[int]:
    """Forward Telegram directo desde el origen vía servicio central (sin descarga
    ni subida). SOLO para la opción oculta `forward_third_party`. Nunca lanza."""
    sent_ids: List[int] = []
    try:
        src_chat = _extract_channel_id(episode.get("telegram_link", "")) or source_channel_id
        msg_id = episode.get("telegram_msg_id") or episode.get("msg_id")
        if not src_chat or not msg_id:
            return sent_ids
        mid = await _svc().forward_message(target_dest["channel_id"], src_chat, int(msg_id),
                                           **_svc_creds(job))
        if mid:
            sent_ids.append(int(mid))
            await asyncio.sleep(delay)
        return sent_ids
    except Exception as e:
        print(f"[TGHirayi_v2] Forward directo falló (fallback a copia real): {e}", flush=True)
        return []


async def _copy_episode_from_origin(client, source_channel_id, episode: dict, target_dest: dict, topic_id, delay: float, job: dict = None) -> List[int]:
    """Copia un episodio vía servicio central como mensaje NUEVO (sin atribución,
    sin descargar/subir). Solo válido con origen del userbot (is_owner)."""
    sent_ids: List[int] = []
    try:
        src_chat = _extract_channel_id(episode.get("telegram_link", "")) or source_channel_id
        msg_id = episode.get("telegram_msg_id") or episode.get("msg_id")
        if not src_chat or not msg_id:
            return sent_ids
        mid = await _svc().copy_message(target_dest["channel_id"], src_chat, int(msg_id),
                                        reply_to_msg_id=topic_id if topic_id else None,
                                        **_svc_creds(job))
        if mid:
            sent_ids.append(int(mid))
            await asyncio.sleep(delay)
    except Exception as e:
        print(f"[TGHirayi_v2] Error copiando desde origen: {e}", flush=True)
    return sent_ids


async def _copy_episode_from_first(client, source_dest: dict, target_dest: dict, source_msg_ids: list, topic_id, delay: float, job: dict = None):
    """Copia vía servicio central los mensajes YA subidos en el primer destino
    a otro destino, como mensajes NUEVOS (sin atribución 'Enviado por')."""
    try:
        for mid in source_msg_ids or []:
            if _worker_paused or not _worker_running:
                return
            _mid = await _svc().copy_message(target_dest["channel_id"], source_dest["channel_id"], int(mid),
                                             reply_to_msg_id=topic_id if topic_id else None,
                                             **_svc_creds(job))
            if _mid:
                await asyncio.sleep(delay)
    except Exception as e:
        print(f"[TGHirayi_v2] Error copiando desde primer destino: {e}", flush=True)


# ─── Inicializacion ───────────────────────────────────────────────
def init_plugin():
    """Inicializa el plugin al cargarse."""
    cfg = _load_config()
    global _worker_paused, _worker_running, _worker_task
    _worker_paused = not cfg.get("resume_on_startup", False)
    if cfg.get("resume_on_startup", False):
        _worker_paused = False
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                _worker_task = loop.create_task(_start_worker())
        except RuntimeError:
            pass

# Inicializar al cargar el modulo
init_plugin()