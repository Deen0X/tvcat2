"""
TVCat 2 - Telegram Service
Wrapper centralizado para toda comunicación con Telegram.
Gestiona clientes, caché de mensajes, cola de prioridades y rate limiting.
"""

import os
import json
import asyncio
import time
import sqlite3
import re
from typing import Optional, List, Dict, Any, Tuple

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "data", "tvcat.db")

# --- Cola de prioridades ---
PRIORITY_HIGH = 0
PRIORITY_NORMAL = 1
PRIORITY_LOW = 2


class PriorityQueue:
    def __init__(self):
        self._queues = [[], [], []]
        self._cond = asyncio.Condition()

    async def put(self, item, priority=PRIORITY_NORMAL):
        async with self._cond:
            if isinstance(item, dict):
                item["_priority"] = priority
            self._queues[priority].append(item)
            self._cond.notify()

    async def get(self):
        async with self._cond:
            while True:
                for q in self._queues:
                    if q:
                        return q.pop(0)
                await self._cond.wait()

    async def wait_ready(self, eligible_fn, running_fn):
        """Extrae la primera tarea lista por prioridad sin inanición.

        eligible_fn(task) -> segundos de espera (0 = lista ahora).
        Si ninguna está lista, duerme hasta el próximo candidato (cap 30s)
        y despierta en cada put.
        """
        async with self._cond:
            while running_fn():
                best_wait = None
                for q in self._queues:
                    for it in q:
                        try:
                            w = eligible_fn(it)
                        except Exception:
                            w = 0
                        if w <= 0:
                            q.remove(it)
                            return it
                        if best_wait is None or w < best_wait:
                            best_wait = w
                try:
                    await asyncio.wait_for(
                        self._cond.wait(),
                        timeout=min(best_wait, 30.0) if best_wait else 30.0,
                    )
                except asyncio.TimeoutError:
                    pass
            return None

    async def wakeup(self):
        async with self._cond:
            self._cond.notify_all()

    def qsize(self):
        return sum(len(q) for q in self._queues)


def _sess_key(session_string, api_id, ctype):
    import hashlib
    try:
        return hashlib.sha256(
            f"{ctype}|{api_id}|{session_string or ''}".encode()).hexdigest()[:16]
    except Exception:
        return "x"


_TEMP_SHARED = {}   # key -> {"client": Client}
_TEMP_LOCKS = {}    # key -> asyncio.Lock


async def _shared_temp_client(session_string, api_id, api_hash, ctype):
    """Un SOLO cliente vivo por credencial en todo el proceso (single-flight).
    Antes cada tarea creaba+conectaba+destruía un Client con la MISMA auth_key
    (decenas/min en ráfagas de covers): Telegram lo interpreta como la clave
    usada en varios sitios a la vez y la quema (AUTH_KEY_DUPLICATED).
    Salud por get_me (barato); ante muerte de auth se desaloja y se propaga
    el error SIN recrear en caliente (no aporrear una clave muerta)."""
    import asyncio as _aio
    # DUEÑO ÚNICO: si las credenciales explícitas son las del wrapper activo
    # del userbot, se toma prestado su raw (sin crear segundo Client con la
    # misma auth_key). Solo se mira el pool, sin crearlo (sin efectos).
    try:
        from services import userbot_service as _ubs
        _w = ((_ubs._client_pool or {}).get(f"active_{ctype}")) if ctype else None
        _wraw = getattr(_w, "_client", None) if _w else None
        _wss = str(((getattr(_w, "session_data", None) or {}).get("session_string")) or "")
        if _wraw is not None and _wss and _wss == str(session_string or ""):
            # client_is_alive: pyro=atributo, telethon=método (no llamar a ciegas).
            try:
                if _ubs.client_is_alive(_wraw):
                    return _wraw
            except Exception:
                pass
    except Exception:
        pass
    key = _sess_key(session_string, api_id, ctype)
    lk = _TEMP_LOCKS.get(key)
    if lk is None:
        lk = _aio.Lock()
        _TEMP_LOCKS[key] = lk
    async with lk:
        ent = _TEMP_SHARED.get(key) or {}
        cli = ent.get("client")
        if cli is not None:
            try:
                if ctype == "pyrogram":
                    await asyncio.wait_for(cli.get_me(), timeout=10)
                elif not cli.is_connected():
                    raise ConnectionError("telethon desconectado")
                return cli
            except Exception as e:
                _tn = type(e).__name__
                if "AuthKey" in _tn or "Duplicated" in str(e) or "Unregistered" in str(e):
                    try:
                        await cli.disconnect()
                    except Exception:
                        pass
                    _TEMP_SHARED.pop(key, None)
                    raise
                try:
                    await cli.disconnect()
                except Exception:
                    pass
                _TEMP_SHARED.pop(key, None)
        if ctype == "pyrogram":
            from pyrogram import Client as _Pyro
            import tempfile as _tf
            cli = _Pyro(
                name=f"tvcat_shared_{key}",
                session_string=session_string,
                api_id=int(api_id), api_hash=api_hash,
                in_memory=True, workdir=_tf.gettempdir())
        else:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            cli = TelegramClient(StringSession(session_string), int(api_id), api_hash,
                                 device_model="TVCat_Central", app_version="1.0")
        await cli.connect()
        if ctype == "pyrogram":
            try:
                _me = await cli.get_me()
                try:
                    cli.me = _me
                except Exception:
                    pass
            except Exception:
                pass
        _TEMP_SHARED[key] = {"client": cli}
        print(f" [TELEGRAM SERVICE] temporal compartido creado ({ctype} {key})", flush=True)
        return cli


def _preferred_client_type(explicit=None):
    """Tipo de cliente efectivo: explícito > ajuste global (Comportamiento
    Telegram) > telethon. Sin esto, los métodos con default "telethon"
    ignoraban el ajuste global."""
    try:
        from services.userbot_service import get_preferred_client_type
        return get_preferred_client_type(explicit)
    except Exception:
        return explicit if explicit in ("telethon", "pyrogram") else "telethon"


class TelegramClientPool:
    """Pool de clientes Telegram por (tg_user_id, client_type)."""

    def __init__(self):
        self._clients = {}
        self._lock = asyncio.Lock()
        # Claves quemadas en esta vida del proceso (AuthKeyDuplicated): no se
        # reintentan (cada intento es ruido y no resucita la clave).
        self._burned = set()
        # Claves PRESTADAS del pool de userbot_service (dueño único del Client).
        # disconnect_all NUNCA las toca: matarlas cortaría al worker por debajo.
        self._borrowed = set()

    async def get_client(self, tg_user_id: int, client_type: str = "telethon"):
        key = (tg_user_id, client_type)
        async with self._lock:
            if key in self._burned:
                raise ValueError(f"Sesión quemada (AuthKeyDuplicated): {tg_user_id}/{client_type}. "
                                 f"Regenera la sesión; no se reintenta en este proceso.")
            if key in self._clients and key in (self._borrowed or set()):
                # Prestado: el dueño (userbot) puede haber reconectado con un
                # objeto nuevo; refrescar el mapeo sin crear nada.
                try:
                    from services import userbot_service as _ubs
                    _w = (_ubs._client_pool or {}).get(f"active_{client_type}")
                    _wraw = getattr(_w, "_client", None) if _w else None
                    if _wraw is not None and _wraw is not self._clients[key]:
                        self._clients[key] = _wraw
                except Exception:
                    pass
            if key not in self._clients:
                self._clients[key] = await self._create_client(tg_user_id, client_type)
            return self._clients[key]

    async def create_temp_client(self, tg_user_id: int, client_type: str = "telethon"):
        return await self._create_client(tg_user_id, client_type)

    async def _create_client(self, tg_user_id: int, client_type: str):
        """DUEÑO ÚNICO: userbot_service. Este pool NO crea un segundo Client con
        la misma session_string (dos vivos = AUTH_KEY_DUPLICATED): toma prestado
        el raw del wrapper activo. Solo si la sesión pedida es OTRA cuenta
        distinta (auth_key diferente, sin conflicto) se crea cliente propio."""
        from services.userbot_service import (get_active_client, get_session_for_user,
                                              get_default_telegram_user)
        if tg_user_id is None:
            try:
                _du = get_default_telegram_user()
                tg_user_id = (_du or {}).get("tg_user_id")
            except Exception:
                tg_user_id = None
        sess = get_session_for_user(tg_user_id, client_type) if tg_user_id is not None else None
        if not sess:
            raise ValueError(f"No session found for tg_user_id={tg_user_id}, type={client_type}")
        wanted_ss = str(sess.get("session_string") or "")
        if not wanted_ss:
            raise ValueError(f"No session found for tg_user_id={tg_user_id}, type={client_type}")
        try:
            wrapper = await get_active_client(client_type)
        except Exception:
            wrapper = None
        _wraw = getattr(wrapper, "_client", None) if wrapper else None
        _wss = str((getattr(wrapper, "session_data", None) or {}).get("session_string") or "")
        if _wraw is not None and _wss == wanted_ss:
            # Misma sesión: prestar (nunca desconectar desde aquí).
            try:
                self._borrowed.add((tg_user_id, client_type))
            except Exception:
                pass
            if client_type != "telethon":
                try:
                    _me = await asyncio.wait_for(_wraw.get_me(), timeout=10)
                    try:
                        _wraw.me = _me
                    except Exception:
                        pass
                except Exception as e:
                    _tn = type(e).__name__
                    if "AuthKeyDuplicated" in _tn or "AuthKeyUnregistered" in _tn:
                        try:
                            from services.userbot_service import quarantine_session
                            quarantine_session(tg_user_id, client_type, _tn)
                        except Exception:
                            pass
                        try:
                            self._burned.add((tg_user_id, client_type))
                        except Exception:
                            pass
                        raise
                    raise ConnectionError(f"Userbot {client_type} prestado no responde: {e}")
            else:
                try:
                    from services.userbot_service import client_is_alive as _alive2
                    if not _alive2(_wraw):
                        raise ConnectionError(f"Userbot telethon prestado desconectado")
                except ConnectionError:
                    raise
                except Exception:
                    pass
            return _wraw
        # Otra cuenta distinta (o wrapper sin raw): cliente propio con OTRA
        # auth_key — sin conflicto de duplicado. in_memory para no ensuciar
        # el workdir con temp_*.session.
        if client_type == "telethon":
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(
                StringSession(sess.get("session_string", "")),
                api_id=sess.get("api_id", 0),
                api_hash=sess.get("api_hash", "")
            )
        else:
            from pyrogram import Client
            import tempfile as _tf
            client = Client(
                name=f"temp_{tg_user_id}_{int(time.time())}",
                session_string=sess.get("session_string", ""),
                api_id=sess.get("api_id", 0),
                api_hash=sess.get("api_hash", ""),
                in_memory=True,
                workdir=_tf.gettempdir()
            )
        await client.connect()
        # Pyrogram: send_photo/edit consultan client.me.is_premium; con solo
        # connect() me es None → AttributeError. Se fija aquí una vez.
        if client_type != "telethon":
            try:
                _me = await client.get_me()
                try:
                    client.me = _me
                except Exception:
                    pass
            except Exception:
                pass
        # Validación inmediata con clave real (solo sesiones guardadas, no
        # temporales vacías): una auth_key quemada (AuthKeyDuplicated) se
        # detecta AQUÍ una vez y se pone en cuarentena, en vez de tormenta
        # de reconnects en cada cover/stream que la pida.
        if sess.get("session_string"):
            try:
                await client.get_me()
            except Exception as e:
                _tn = type(e).__name__
                if "AuthKeyDuplicated" in _tn or "AuthKeyUnregistered" in _tn:
                    try:
                        from services.userbot_service import quarantine_session
                        quarantine_session(tg_user_id, client_type, _tn)
                    except Exception:
                        pass
                    try:
                        self._burned.add((tg_user_id, client_type))
                    except Exception:
                        pass
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    raise
        return client

    async def disconnect_all(self):
        async with self._lock:
            for key, client in self._clients.items():
                if key in (self._borrowed or set()):
                    continue  # prestado del userbot: el dueño lo gestiona
                try:
                    await client.disconnect()
                except:
                    pass
            self._clients.clear()
            try:
                self._borrowed.clear()
            except Exception:
                pass


class TelegramMessageCache:
    """Caché de mensajes RAW de Telegram en la DB central."""

    def __init__(self):
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            self._conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init_table(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_message_cache (
                channel_id  TEXT NOT NULL,
                topic_id    INTEGER,
                msg_id      INTEGER NOT NULL,
                message     TEXT NOT NULL,
                fetched_at  INTEGER DEFAULT (unixepoch()),
                PRIMARY KEY (channel_id, msg_id)
            )
        """)
        conn.commit()

    def get_cached_range(self, channel_id: str, topic_id: Optional[int] = None) -> Tuple[int, int, set]:
        """Devuelve (min_msg, max_msg, set_of_ids) para los mensajes cacheados de un canal."""
        try:
            from services.cache_keys import canon_channel
            channel_id = canon_channel(channel_id)
        except Exception:
            pass
        conn = self._get_conn()
        if topic_id is not None:
            row = conn.execute(
                "SELECT MIN(msg_id), MAX(msg_id) FROM telegram_message_cache WHERE channel_id=? AND topic_id=?",
                (channel_id, topic_id)
            ).fetchone()
            ids = set(r["msg_id"] for r in conn.execute(
                "SELECT msg_id FROM telegram_message_cache WHERE channel_id=? AND topic_id=?",
                (channel_id, topic_id)
            ).fetchall())
        else:
            row = conn.execute(
                "SELECT MIN(msg_id), MAX(msg_id) FROM telegram_message_cache WHERE channel_id=? AND topic_id IS NULL",
                (channel_id,)
            ).fetchone()
            ids = set(r["msg_id"] for r in conn.execute(
                "SELECT msg_id FROM telegram_message_cache WHERE channel_id=? AND topic_id IS NULL",
                (channel_id,)
            ).fetchall())
        if row and row[0] is not None:
            return row[0], row[1], ids
        return 0, 0, set()

    def save_messages(self, messages: List[Dict]):
        try:
            from services.cache_keys import canon_channel
            for _m in messages:
                try:
                    _m["channel_id"] = canon_channel(_m.get("channel_id"))
                except Exception:
                    pass
            conn = self._get_conn()
            for msg in messages:
                # 2026-09-04: UPSERT que NUNCA borra un topic conocido con NULL.
                # Los guardados sin topic (covers/thumbs/refresh) pisaban el topic
                # real y el scan topo separaba la foto del vídeo (títulos partidos).
                # 2026-09-04b: guardia anti-corrupción (caso 4041=Sakamoto bajo otra
                # clave): si el raw trae id y no coincide con la clave, NO se guarda.
                try:
                    _raw = msg.get("raw") or {}
                    _rid = _raw.get("id", None)
                    if _rid is not None and int(_rid) != int(msg.get("msg_id")):
                        print(f" [CACHE] raw incoherente ch={msg.get('channel_id')} key={msg.get('msg_id')} raw_id={_rid} (descartado)", flush=True)
                        continue
                except Exception:
                    pass
                conn.execute("""
                    INSERT INTO telegram_message_cache
                    (channel_id, topic_id, msg_id, message, fetched_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id, msg_id) DO UPDATE SET
                        message=excluded.message,
                        fetched_at=excluded.fetched_at,
                        topic_id=COALESCE(excluded.topic_id, topic_id)
                """, (
                    msg.get("channel_id"),
                    msg.get("topic_id"),
                    msg.get("msg_id"),
                    json.dumps(msg.get("raw", {}), default=str),
                    int(time.time())
                ))
            conn.commit()
        except Exception as e:
            print(f" [CACHE] save_messages error (no bloquea): {e}", flush=True)

    def get_all_messages(self, channel_id: str, topic_id: Optional[int] = None) -> List[Dict]:
        """Retorna TODOS los mensajes cacheados de un canal (para parseo de scans), ordenados por msg_id."""
        try:
            from services.cache_keys import canon_channel
            channel_id = canon_channel(channel_id)
        except Exception:
            pass
        conn = self._get_conn()
        if topic_id is not None:
            rows = conn.execute(
                "SELECT * FROM telegram_message_cache WHERE channel_id=? AND topic_id=? ORDER BY msg_id ASC",
                (channel_id, topic_id)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM telegram_message_cache WHERE channel_id=? ORDER BY msg_id ASC",
                (channel_id,)
            ).fetchall()
        result = []
        for r in rows:
            try:
                result.append({
                    "channel_id": r["channel_id"],
                    "topic_id": r["topic_id"],
                    "msg_id": r["msg_id"],
                    "message": json.loads(r["message"])
                })
            except Exception:
                pass
        return result

    def get_messages(self, channel_id: str, msg_ids: List[int], topic_id: Optional[int] = None) -> List[Dict]:
        try:
            from services.cache_keys import canon_channel
            channel_id = canon_channel(channel_id)
        except Exception:
            pass
        conn = self._get_conn()
        if not msg_ids:
            return []
        placeholders = ",".join("?" for _ in msg_ids)
        if topic_id is not None:
            rows = conn.execute(
                f"SELECT * FROM telegram_message_cache WHERE channel_id=? AND topic_id=? AND msg_id IN ({placeholders})",
                [channel_id, topic_id] + msg_ids
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM telegram_message_cache WHERE channel_id=? AND topic_id IS NULL AND msg_id IN ({placeholders})",
                [channel_id] + msg_ids
            ).fetchall()
        result = []
        for r in rows:
            try:
                result.append({
                    "channel_id": r["channel_id"],
                    "topic_id": r["topic_id"],
                    "msg_id": r["msg_id"],
                    "message": json.loads(r["message"])
                })
            except:
                pass
        return result


class BulkGate:
    """Carril bulk: concurrencia global con prioridades (streaming > copia > prefetch).

    La velocidad MTProto viene de las peticiones en vuelo (N × chunk / RTT), NO
    de ir sin control. El gate limita el total en vuelo (presupuesto configurable
    `tg_bulk_inflight`) y ordena por prioridad, sin limitar peticiones/minuto.
    Ante FloodWait real reduce el presupuesto (AIMD) y lo recupera solo.
    """

    def __init__(self, budget: int = 12):
        self.budget = max(4, min(int(budget or 12), 32))
        self.inflight = 0
        self._waiters = []  # (priority, seq, Future)
        self._seq = 0
        self._lock = None
        self._shrink_until = 0.0

    def _ensure_lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self, priority: int = PRIORITY_NORMAL):
        lock = self._ensure_lock()
        async with lock:
            if not self._waiters and self.inflight < self.budget:
                self.inflight += 1
                return
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._seq += 1
            self._waiters.append((int(priority), self._seq, fut))
        await fut

    async def release(self):
        lock = self._ensure_lock()
        async with lock:
            self.inflight = max(0, self.inflight - 1)
            self._pump()

    def _pump(self):
        while self._waiters and self.inflight < self.budget:
            self._waiters.sort(key=lambda w: (w[0], w[1]))
            _, _, fut = self._waiters.pop(0)
            if not fut.done():
                self.inflight += 1
                fut.set_result(None)

    def flood_report(self, seconds: float = 0):
        """FloodWait real en bulk: encoger presupuesto a la mitad 5 min."""
        try:
            self.budget = max(4, self.budget // 2)
            self._shrink_until = time.time() + 300
            print(f" [BULK] FloodWait: presupuesto a {self.budget} (5 min)", flush=True)
        except Exception:
            pass

    def maybe_recover(self, base: int):
        try:
            if self.budget < base and time.time() > self._shrink_until:
                self.budget = min(base, self.budget + 2)
                self._pump()
        except Exception:
            pass

    def snapshot(self):
        try:
            return {"budget": self.budget, "inflight": self.inflight,
                    "waiters": len(self._waiters)}
        except Exception:
            return {}


class TelegramService:
    """Servicio central de Telegram con cola, rate limiting y caché.

    Throttle adaptativo por cuenta (token bucket + AIMD, ver Project_Architecture.md §22):
    1 token por llamada de método remota; el bulk (GetFile, partes de upload) queda fuera.
    """

    # AIMD (ver plan Telegram_Throttle_Implementation_Plan.md)
    THROTTLE_FLOOR = 0.5
    THROTTLE_CEIL = 30.0
    THROTTLE_RELAX_STEP = 0.2
    THROTTLE_RELAX_AFTER = 120
    THROTTLE_MAX_RETRIES = 3
    THROTTLE_CFG_TTL = 30.0

    def __init__(self):
        self.pool = TelegramClientPool()
        self.cache = TelegramMessageCache()
        self.queue = PriorityQueue()
        self._worker_task = None
        self._running = False
        # Estado throttle por usuario: uid -> {interval, tokens, last_refill,
        #   last_call, cooldown_until, clean, persisted}
        self._throttle_state = {}
        self._learned_users = {}
        self._cfg_cache = {}
        self._cfg_ts = 0.0
        # Uso real por cuenta (2026-09-04 F2): timestamps de llamadas a métodos
        # (no bulk). Ventana 120s para niveles con decaimiento.
        self._usage = {}
        # Carril bulk (control exclusivo del bulk: nadie invoca GetFile/SavePart
        # directo sin slot). Presupuesto configurable, prioridades por uso.
        self._bulk = None
        self._bulk_base = 12

    def bulk_gate(self) -> BulkGate:
        """Puerta bulk global (lazy, ligada al loop en curso)."""
        if self._bulk is None:
            try:
                base = int(self._cfg("tg_bulk_inflight", 12))
            except Exception:
                base = 12
            self._bulk_base = max(4, min(base, 32))
            self._bulk = BulkGate(self._bulk_base)
        else:
            try:
                base = int(self._cfg("tg_bulk_inflight", 12))
                base = max(4, min(base, 32))
                self._bulk_base = base
                self._bulk.maybe_recover(base)
                if self._bulk.budget > base:
                    self._bulk.budget = base
            except Exception:
                pass
        return self._bulk

    async def bulk_acquire(self, priority: int = PRIORITY_NORMAL):
        await self.bulk_gate().acquire(priority)

    async def bulk_release(self):
        if self._bulk is not None:
            await self._bulk.release()

    def bulk_flood_report(self, seconds: float = 0):
        if self._bulk is not None:
            self._bulk.flood_report(seconds)

    def bulk_snapshot(self):
        try:
            return self.bulk_gate().snapshot()
        except Exception:
            return {}

    async def start(self):
        self.cache.init_table()
        self._load_learned()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self):
        self._running = False
        try:
            await self.queue.wakeup()
        except Exception:
            pass
        await self.pool.disconnect_all()

    # ─── Throttle adaptativo ──────────────────────────────────────────

    @staticmethod
    def _user_key(task: Dict) -> str:
        try:
            uid = task.get("tg_user_id")
            return str(uid) if uid is not None else "default"
        except Exception:
            return "default"

    def _cfg(self, name: str, default):
        now = time.time()
        if now - self._cfg_ts > self.THROTTLE_CFG_TTL:
            try:
                from services.catalog_service import get_conn
                conn = get_conn()
                vals = {}
                for k in ("tg_throttle_per_minute", "tg_throttle_burst"):
                    try:
                        r = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (k,)).fetchone()
                        if r and r[0] not in (None, ""):
                            vals[k] = r[0]
                    except Exception:
                        pass
                conn.close()
                if vals:
                    self._cfg_cache.update(vals)
            except Exception:
                pass
            self._cfg_ts = now
        try:
            v = self._cfg_cache.get(name, default)
            return type(default)(v)
        except Exception:
            return default

    def _base_interval(self) -> float:
        try:
            pm = max(1, int(self._cfg("tg_throttle_per_minute", 20)))
        except Exception:
            pm = 20
        return max(self.THROTTLE_FLOOR, min(self.THROTTLE_CEIL, 60.0 / pm))

    def _burst(self) -> float:
        try:
            return max(1.0, float(self._cfg("tg_throttle_burst", 5)))
        except Exception:
            return 5.0

    def _tstate(self, uid) -> dict:
        uid = str(uid or "default")
        st = self._throttle_state.get(uid)
        if st is None:
            try:
                learned = float(self._learned_users.get(uid))
            except Exception:
                learned = None
            iv = learned or self._base_interval()
            iv = max(self.THROTTLE_FLOOR, min(self.THROTTLE_CEIL, iv))
            st = {
                "interval": iv, "tokens": float(self._burst()),
                "last_refill": time.time(), "last_call": 0.0,
                "cooldown_until": 0.0, "clean": 0, "persisted": iv,
            }
            self._throttle_state[uid] = st
        return st

    def _task_wait(self, task: Dict) -> float:
        """Segundos hasta que la tarea es elegible (solo cooldown; tokens dentro)."""
        try:
            st = self._tstate(self._user_key(task))
            return max(0.0, st["cooldown_until"] - time.time())
        except Exception:
            return 0.0

    async def _throttle(self, uid, floor: float = 0.0, cost: float = 1.0):
        """Espera lo necesario (bucket + suelo) y consume `cost` tokens. 1 llamada = 1 token."""
        try:
            floor = float(floor or 0.0)
        except Exception:
            floor = 0.0
        st = self._tstate(uid)
        now = time.time()
        elapsed = now - st["last_refill"]
        if elapsed > 0:
            st["tokens"] = min(float(self._burst()), st["tokens"] + elapsed / st["interval"])
            st["last_refill"] = now
        wait = 0.0
        if st["tokens"] < cost:
            wait = max(wait, (cost - st["tokens"]) * st["interval"])
        if floor:
            since = now - (st["last_call"] or 0.0)
            if since < floor:
                wait = max(wait, floor - since)
        if wait > 0:
            await asyncio.sleep(wait)
            now = time.time()
            elapsed = now - st["last_refill"]
            st["tokens"] = min(float(self._burst()), st["tokens"] + elapsed / st["interval"])
            st["last_refill"] = now
        st["tokens"] -= cost
        st["last_call"] = now
        # 2026-09-04 F2: registrar uso real (podar ventana 120s).
        try:
            _uk = str(uid or "default")
            _ul = self._usage.setdefault(_uk, [])
            _ul.append(now)
            _cut = now - 120.0
            while _ul and _ul[0] < _cut:
                _ul.pop(0)
        except Exception:
            pass
        # AIMD: relajar ante éxito sostenido
        try:
            st["clean"] = int(st.get("clean", 0)) + 1
            if st["clean"] >= self.THROTTLE_RELAX_AFTER:
                st["clean"] = 0
                new_iv = max(self.THROTTLE_FLOOR, st["interval"] - self.THROTTLE_RELAX_STEP)
                if new_iv < st["interval"]:
                    st["interval"] = new_iv
                    self._persist_learned(uid, st)
        except Exception:
            pass

    def _harden(self, uid, seconds):
        """Endurecer ante FloodWait: cooldown + intervalo mayor + persistir + log."""
        uid = str(uid or "default")
        st = self._tstate(uid)
        now = time.time()
        try:
            secs = int(seconds or 0)
        except Exception:
            secs = 0
        wait = min(secs + 2, 300)
        st["cooldown_until"] = max(st["cooldown_until"], now + wait)
        new_iv = max(st["interval"] * 2.0, min(secs / 10.0, self.THROTTLE_CEIL))
        st["interval"] = min(self.THROTTLE_CEIL, max(self.THROTTLE_FLOOR, new_iv))
        st["clean"] = 0
        self._persist_learned(uid, st, force=True)
        print(f" [THROTTLE] FloodWait uid={uid} {secs}s: cooldown {wait}s, interval {st['interval']:.1f}s", flush=True)

    def _load_learned(self):
        try:
            from services.catalog_service import get_conn
            conn = get_conn()
            row = conn.execute("SELECT value FROM tvcat_settings WHERE key='tg_throttle_learned'").fetchone()
            conn.close()
            if not row or not row[0]:
                return
            data = json.loads(row[0])
            if not isinstance(data, dict):
                return
            try:
                cur_pm = int(self._cfg("tg_throttle_per_minute", 20))
            except Exception:
                cur_pm = 20
            try:
                saved_pm = int(data.get("per_minute", cur_pm))
            except Exception:
                saved_pm = cur_pm
            if saved_pm != cur_pm:
                return  # la config manda: re-aprender desde la nueva base
            users = data.get("users") or {}
            for k, v in users.items():
                try:
                    self._learned_users[str(k)] = max(self.THROTTLE_FLOOR, min(self.THROTTLE_CEIL, float(v)))
                except Exception:
                    pass
        except Exception:
            pass

    def _persist_learned(self, uid, st, force=False):
        try:
            uid = str(uid or "default")
            if not force and abs(float(st["interval"]) - float(st.get("persisted", st["interval"]))) <= 0.2:
                return
            from services.catalog_service import get_conn
            conn = get_conn()
            cur = None
            try:
                r = conn.execute("SELECT value FROM tvcat_settings WHERE key='tg_throttle_learned'").fetchone()
                cur = json.loads(r[0]) if r and r[0] else {}
                if not isinstance(cur, dict):
                    cur = {}
            except Exception:
                cur = {}
            try:
                cur_pm = int(self._cfg("tg_throttle_per_minute", 20))
            except Exception:
                cur_pm = 20
            users = cur.get("users") or {}
            if not isinstance(users, dict):
                users = {}
            users[uid] = float(st["interval"])
            cur["per_minute"] = cur_pm
            cur["users"] = users
            conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                         ("tg_throttle_learned", json.dumps(cur)))
            conn.commit()
            conn.close()
            st["persisted"] = float(st["interval"])
        except Exception:
            pass

    def throttle_status(self) -> dict:
        now = time.time()
        users = {}
        for uid, st in self._throttle_state.items():
            try:
                users[str(uid)] = {
                    "interval": round(float(st["interval"]), 2),
                    "tokens": round(float(st["tokens"]), 2),
                    "in_cooldown": now < float(st.get("cooldown_until", 0.0)),
                    "cooldown_left": max(0, round(float(st.get("cooldown_until", 0.0)) - now, 1)),
                    "clean": int(st.get("clean", 0)),
                }
            except Exception:
                pass
        try:
            pm = int(self._cfg("tg_throttle_per_minute", 20))
        except Exception:
            pm = 20
        try:
            bu = float(self._cfg("tg_throttle_burst", 5))
        except Exception:
            bu = 5.0
        out = {"per_minute": pm, "burst": bu, "users": users, "queue": self.queue.qsize()}
        try:
            out["bulk"] = self.bulk_snapshot()
        except Exception:
            pass
        return out

    def estimate_wait(self, tg_user_id=None, cost: float = 1.0) -> float:
        """Espera estimada SIN consumir (réplica pura de _throttle). Para fail-fast
        externo: si supera el umbral, mejor 404 rápido + retry en fondo que
        mantener la conexión HTTP ocupada (2026-09-04: grid saturaba el navegador)."""
        try:
            uid = str(tg_user_id) if tg_user_id is not None else "default"
            st = self._tstate(uid)
            now = time.time()
            elapsed = now - st["last_refill"]
            tokens = st["tokens"] + (elapsed / st["interval"] if elapsed > 0 else 0.0)
            tokens = min(float(self._burst()), tokens)
            wait = max(0.0, st.get("cooldown_until", 0.0) - now)
            if tokens < cost:
                wait = max(wait, (cost - tokens) * st["interval"])
            return wait
        except Exception:
            return 0.0

    def usage_snapshot(self) -> Dict[str, Any]:
        """2026-09-04 F2: uso por cuenta con decaimiento. level 2 = llamadas en
        últimos 30s (rojo), 1 = solo 30-60s (atenuado), 0 = nada (gris)."""
        out = {}
        try:
            now = time.time()
            for uid, lst in list(self._usage.items()):
                try:
                    c30 = sum(1 for t in lst if now - t <= 30.0)
                    c60 = sum(1 for t in lst if now - t <= 60.0)
                    out[str(uid)] = {"calls_30s": c30, "calls_60s": c60,
                                     "level": 2 if c30 else (1 if c60 else 0)}
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def bucket_snapshot(self) -> Dict[str, Any]:
        """2026-09-04: estado de buckets por cuenta para UI y otros plugins.
        state: gray (0 llamadas/60s), green (dentro de ráfaga: tokens>0),
        yellow (entre ráfaga y límite: dosificando), red (en cooldown/delay)."""
        out = {}
        try:
            now = time.time()
            burst = float(self._burst())
            for uid in list(self._throttle_state.keys()):
                try:
                    st = self._tstate(uid)
                    cd = max(0.0, float(st.get("cooldown_until", 0.0)) - now)
                    tok = float(st.get("tokens", 0.0))
                    iv = float(st.get("interval", 3.0))
                    calls = sum(1 for t in self._usage.get(str(uid), []) if now - t <= 60.0)
                    if calls == 0:
                        state = "gray"
                    elif cd > 0:
                        state = "red"
                    elif tok > 0:
                        state = "green"
                    else:
                        state = "yellow"
                    out[str(uid)] = {
                        "tokens": round(tok, 2),
                        "burst": burst,
                        "interval": round(iv, 2),
                        "per_minute": int(round(60.0 / max(0.5, iv))),
                        "cooldown_s": round(cd, 1),
                        "calls_60s": calls,
                        "state": state,
                    }
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def throttle_snapshot(self) -> Dict[str, Any]:
        """2026-09-04 F3: estado de buckets por cuenta (tokens, intervalo, cooldown)."""
        return self.bucket_snapshot()

    def quiet_remaining(self) -> float:
        """Segundos de cooldown máximo entre usuarios (0 = vía libre). Para gating externo."""
        try:
            now = time.time()
            return max(0.0, max(
                [float(st.get("cooldown_until", 0.0)) for st in self._throttle_state.values()],
                default=now) - now)
        except Exception:
            return 0.0

    async def _worker_loop(self):
        while self._running:
            task = await self.queue.wait_ready(self._task_wait, lambda: self._running)
            if task is None:
                continue
            try:
                await self._execute_task(task)
            except Exception as e:
                print(f" [TELEGRAM SERVICE] Error en tarea {task.get('action')} : {e}", flush=True)
                # FloodWait por usuario: cooldown + endurecer + reencolar (presupuesto 3).
                # Sin sleep global: wait_ready salta los usuarios en cooldown y el resto fluye.
                _is_flood = False
                try:
                    from telethon.errors import FloodWaitError
                    _is_flood = isinstance(e, FloodWaitError)
                except Exception:
                    _is_flood = "FloodWait" in type(e).__name__ or "FLOOD_WAIT" in str(e)
                if _is_flood:
                    try:
                        _secs = int(getattr(e, "seconds", 0) or 0)
                    except Exception:
                        _secs = 0
                    _uid = self._user_key(task)
                    self._harden(_uid, _secs)
                    _retries = int(task.get("_retries", 0) or 0) + 1
                    if _retries <= self.THROTTLE_MAX_RETRIES:
                        task["_retries"] = _retries
                        await self.queue.put(task, priority=int(task.get("_priority", PRIORITY_NORMAL)))
                        continue
                # Asegurar que el callback se llame para no colgar el Future
                cb = task.get("callback")
                if cb:
                    try:
                        await cb(None)
                    except Exception:
                        pass

    async def _execute_task(self, task: Dict):
        action = task.get("action")

        action = task.get("action")
        if action == "fetch_messages":
            await self._do_fetch_messages(task)
        elif action == "fetch_one":
            await self._do_fetch_one(task)
        elif action == "download_media":
            await self._do_download_media(task)
        elif action == "fetch_scan":
            await self._do_fetch_scan(task)
        elif action == "get_entity":
            await self._do_get_entity(task)
        elif action == "get_pinned":
            await self._do_get_pinned(task)
        elif action == "search_media":
            await self._do_search_media(task)
        elif action == "send_document":
            await self._do_send_document(task)
        elif action == "pin_message":
            await self._do_pin_message(task)
        elif action == "download_document":
            await self._do_download_document(task)
        elif action == "edit_message":
            await self._do_edit_message(task)
        elif action == "fetch_cover":
            await self._do_fetch_cover(task)
        elif action == "fetch_thumb":
            await self._do_fetch_thumb(task)
        elif action == "channel_last":
            await self._do_channel_last(task)
        elif action == "send_text":
            await self._do_send_text(task)
        elif action == "send_photo":
            await self._do_send_photo(task)
        elif action == "list_topics":
            await self._do_list_topics(task)
        elif action == "create_topic":
            await self._do_create_topic(task)
        elif action == "check_owner":
            await self._do_check_owner(task)
        elif action == "fetch_cover_messages":
            await self._do_fetch_cover_messages(task)
        elif action == "get_file_info":
            await self._do_get_file_info(task)
        elif action == "copy_message":
            await self._do_copy_message(task)
        elif action == "forward_message":
            await self._do_forward_message(task)

    async def _do_fetch_messages(self, task: Dict):
        channel_id = task["channel_id"]
        from_id = task["from_id"]
        to_id = task.get("to_id")
        topic_id = task.get("topic_id")
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type", "telethon")
        result_callback = task.get("callback")

        cached_min, cached_max, cached_ids = self.cache.get_cached_range(channel_id, topic_id)

        client = await self.pool.get_client(tg_user_id, client_type)
        _uid = self._user_key(task)
        _floor = 0.0
        try:
            _floor = float(task.get("min_interval") or 0.0)
        except Exception:
            _floor = 0.0
        batch_size = 100
        current_from = from_id
        new_messages = []

        while current_from <= (to_id or float('inf')):
            batch_to = min(current_from + batch_size - 1, to_id) if to_id else current_from + batch_size - 1
            need = [m for m in range(current_from, batch_to + 1) if m not in cached_ids]
            if not need:
                current_from = batch_to + 1
                continue

            try:
                await self._throttle(_uid, floor=_floor)
                if client_type == "telethon" and not self._is_pyro(client, client_type):
                    from telethon import TelegramClient
                    msgs = await client.get_messages(await client.get_entity(int(channel_id)), limit=batch_size, offset_id=batch_to)
                else:
                    msgs = [m async for m in client.get_chat_history(
                        self._pyro_chat_id(channel_id), limit=batch_size, offset_id=batch_to)]

                batch = []
                for m in msgs:
                    mid = getattr(m, 'id', 0)
                    batch.append({
                        "channel_id": channel_id,
                        "topic_id": topic_id,
                        "msg_id": mid,
                        "raw": self._serialize_message(m, client_type)
                    })
                if batch:
                    self.cache.save_messages(batch)
                    new_messages.extend(batch)

                current_from = batch_to + 1
            except Exception as e:
                print(f" [TELEGRAM SERVICE] Error fetch: {e}")
                break

        if result_callback:
            if new_messages:
                await result_callback(new_messages)
            else:
                cached = self.cache.get_messages(channel_id, list(range(from_id, (to_id or from_id) + 1)), topic_id)
                await result_callback(cached)

    async def _do_fetch_one(self, task: Dict):
        channel_id = task["channel_id"]
        msg_id = task["msg_id"]
        topic_id = task.get("topic_id")
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type", "telethon")
        result_callback = task.get("callback")
        force = bool(task.get("force"))

        if not force:
            cached = self.cache.get_messages(channel_id, [msg_id], topic_id)
            if cached:
                if result_callback:
                    await result_callback(cached[0])
                return

        precache_from = max(1, msg_id - 50)
        precache_to = msg_id + 50
        try:
            _inner_floor = float(task.get("min_interval") or 0.0)
        except Exception:
            _inner_floor = 0.0

        def _pick_exact(msgs):
            try:
                for _it in (msgs or []):
                    if isinstance(_it, dict) and int(_it.get("msg_id", -1)) == int(msg_id):
                        if "message" not in _it and "raw" in _it:
                            _it = dict(_it)
                            _it["message"] = _it.pop("raw")
                        return _it
            except Exception:
                pass
            return None

        task_data = {
            "action": "fetch_messages",
            "channel_id": channel_id,
            "from_id": precache_from,
            "to_id": precache_to,
            "topic_id": topic_id,
            "tg_user_id": tg_user_id,
            "client_type": client_type,
            "min_interval": _inner_floor,
            "callback": lambda msgs: result_callback(_pick_exact(msgs)) if result_callback else None
        }
        await self._do_fetch_messages(task_data)

    @staticmethod
    def _inline_photo_bytes(msg):
        """Si la foto solo tiene tamaños inline (stripped/cached), devuelve sus bytes SIN red.
        Evita el quirk de Telethon: download_media(msg) sin file devuelve un PATH str
        (y escribe un photo_*.jpg en el cwd) cuando el size es stripped/cached."""
        try:
            from telethon.tl import types as _t
            from telethon import utils as _u
            media = getattr(msg, 'media', None)
            photo = getattr(media, 'photo', None)
            if not isinstance(photo, _t.Photo):
                return None
            best = None
            for s in (getattr(photo, 'sizes', None) or []):
                if isinstance(s, (_t.PhotoCachedSize, _t.PhotoStrippedSize)):
                    best = s
            if best is None:
                return None
            if isinstance(best, _t.PhotoStrippedSize):
                return _u.stripped_photo_to_jpg(bytes(getattr(best, 'bytes', b'') or b''))
            return bytes(getattr(best, 'bytes', b'') or b'') or None
        except Exception:
            return None

    @staticmethod
    def _coerce_download_bytes(data):
        """Normaliza el retorno de download_media a bytes|None.
        Si Telethon devolvió un path (size stripped/cached + file=None): leer + limpiar."""
        if data is None or isinstance(data, (bytes, bytearray, memoryview)):
            return bytes(data) if data is not None else None
        if isinstance(data, str):
            try:
                if os.path.isfile(data):
                    with open(data, 'rb') as f:
                        out = f.read()
                    try:
                        os.remove(data)
                    except Exception:
                        pass
                    return out
            except Exception:
                pass
            return None
        return None

    async def _do_download_media(self, task: Dict):
        channel_id = task["channel_id"]
        msg_id = task["msg_id"]
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type", "telethon")
        result_callback = task.get("callback")

        client = await self.pool.get_client(tg_user_id, client_type)
        _uid = self._user_key(task)
        _floor = 0.0
        try:
            _floor = float(task.get("min_interval") or 0.0)
        except Exception:
            _floor = 0.0
        try:
            await self._throttle(_uid, floor=_floor)
            if client_type == "telethon" and not self._is_pyro(client, client_type):
                entity = await client.get_entity(int(channel_id))
                await self._throttle(_uid, floor=_floor)
                msg = await client.get_messages(entity, ids=msg_id)
            else:
                await self._throttle(_uid, floor=_floor)
                try:
                    msg = await client.get_messages(self._pyro_chat_id(channel_id), msg_id)
                except Exception:
                    msg = None
            data = None
            if msg and getattr(msg, 'media', None):
                data = self._inline_photo_bytes(msg)
                if data is None:
                    if self._is_pyro(client, client_type):
                        try:
                            bio = await client.download_media(msg, in_memory=True)
                            data = bytes(bio.getvalue()) if bio is not None else None
                        except Exception:
                            data = None
                    else:
                        data = self._coerce_download_bytes(await client.download_media(msg))
            if result_callback:
                await result_callback(data)
        except Exception as e:
            print(f" [TELEGRAM SERVICE] Error download media: {e}")
            if result_callback:
                await result_callback(None)

    async def _do_fetch_scan(self, task: Dict):
        """Escaneo de un rango de mensajes de un canal: usa el pool central (o cliente temp por
        sesión explícita) y guarda en el caché central. Salta mensajes de sistema/action.
        `on_batch(total, lo, hi)` se invoca por cada lote (para progreso)."""
        channel_id = task["channel_id"]
        from_id = task["from_id"]
        to_id = task.get("to_id") or None
        topic_id = task.get("topic_id")
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type", "telethon")
        session_string = task.get("session_string")
        api_id = task.get("api_id")
        api_hash = task.get("api_hash")
        header_msg_id = task.get("header_msg_id")
        on_batch = task.get("on_batch")

        need_disconnect = False
        client = None
        try:
            if session_string and api_id and api_hash:
                from telethon import TelegramClient
                from telethon.sessions import StringSession
                client = TelegramClient(StringSession(session_string), int(api_id), api_hash,
                                        device_model="TVCat_Central", app_version="1.0")
                await client.connect()
                need_disconnect = True
            else:
                client = await self.pool.get_client(tg_user_id, client_type)

            _uid = self._user_key(task)
            _floor = 0.0
            try:
                _floor = float(task.get("min_interval") or 0.0)
            except Exception:
                _floor = 0.0
            await self._throttle(_uid, floor=_floor)
            try:
                entity = await client.get_entity(int(channel_id))
            except ValueError as _ve:
                # Sesión fresca con caché de entidades vacía: Telethon no
                # resuelve IDs de canales que nunca vio. Sincronizar diálogos
                # una vez y reintentar antes de rendirse.
                if "Could not find the input entity" not in str(_ve):
                    raise
                print(f" [TELEGRAM SERVICE] entidad no cacheada {channel_id}: "
                      f"sincronizando diálogos y reintentando", flush=True)
                try:
                    _dlg = await client.get_dialogs()
                    print(f" [TELEGRAM SERVICE] diálogos sincronizados: "
                          f"{len(_dlg or [])} chats visibles para esta sesión", flush=True)
                except Exception as _de:
                    print(f" [TELEGRAM SERVICE] fallo sincronizando diálogos: "
                          f"{type(_de).__name__}: {str(_de)[:150]}", flush=True)
                entity = await client.get_entity(int(channel_id))

            # Mensaje cabecera de topic (para topo 1/2): se cachea con topic_id del topic.
            if header_msg_id:
                try:
                    await self._throttle(_uid, floor=_floor)
                    h = await client.get_messages(entity, ids=int(header_msg_id))
                    if h and getattr(h, 'action', None) is None:
                        self.cache.save_messages([{
                            "channel_id": str(channel_id),
                            "topic_id": topic_id,
                            "msg_id": int(getattr(h, 'id', 0)),
                            "raw": self._serialize_message(h, client_type)
                        }])
                except Exception:
                    pass

            iter_kwargs = {"reverse": True}  # de antiguo a nuevo (lotes 1-100, 101-200...)
            if from_id and from_id > 0:
                iter_kwargs["min_id"] = from_id
            if to_id:
                iter_kwargs["max_id"] = to_id + 1  # Telethon max_id es inclusivo
            if topic_id is not None:
                iter_kwargs["reply_to"] = int(topic_id)

            total = 0
            batch = []
            _lote = 0
            # Rango del lote: iter_messages va de nuevo a viejo.
            async def _flush(_final=False):
                nonlocal total, batch, _lote
                if not batch and not _final:
                    return 0, 0
                _lo = min(int(m["msg_id"]) for m in batch) if batch else 0
                _hi = max(int(m["msg_id"]) for m in batch) if batch else 0
                if batch:
                    self.cache.save_messages(batch)
                    total += len(batch)
                    _lote += 1
                    batch = []
                    await self._throttle(_uid, floor=_floor)
                    print(f" [TELEGRAM SERVICE] fetch_scan {channel_id}: "
                          f"lote {_lote} msgs {_lo}-{_hi} (total {total})", flush=True)
                if on_batch:
                    try:
                        on_batch(total, _lo, _hi)
                    except TypeError:
                        on_batch(total)
                return _lo, _hi
            async for msg in client.iter_messages(entity, **iter_kwargs):
                if getattr(msg, 'action', None) is not None:
                    continue
                t_id = topic_id
                if t_id is None:
                    reply = getattr(msg, 'reply_to', None)
                    if reply is not None and hasattr(reply, 'reply_to_msg_id') and reply.reply_to_msg_id:
                        t_id = int(reply.reply_to_msg_id)
                batch.append({
                    "channel_id": str(channel_id),
                    "topic_id": t_id,
                    "msg_id": int(getattr(msg, 'id', 0)),
                    "raw": self._serialize_message(msg, client_type)
                })
                if len(batch) >= 100:
                    await _flush()
            if batch:
                await _flush()
        except Exception as e:
            print(f" [TELEGRAM SERVICE] Error fetch_scan: {e}", flush=True)
            total = 0
        finally:
            if need_disconnect:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        result_callback = task.get("callback")
        if result_callback:
            await result_callback(total)

    async def scan_messages(self, channel_id: str, from_id: int, to_id: int = None,
                            topic_id: int = None, tg_user_id: int = None,
                            session_string: str = None, api_id: int = None,
                            api_hash: str = None, header_msg_id: int = None,
                            client_type: str = "telethon",
                            on_batch=None) -> int:
        """Escanea un rango de mensajes de un canal, cacheándolos en `telegram_message_cache` (central).
        Acepta sesión explícita (account del plugin) o tg_user_id (pool central).
        Retorna el total de mensajes guardados."""
        fut = asyncio.get_event_loop().create_future()
        async def callback(total):
            if not fut.done():
                fut.set_result(total)
        await self.queue.put({
            "action": "fetch_scan",
            "channel_id": channel_id,
            "from_id": from_id,
            "to_id": to_id,
            "topic_id": topic_id,
            "tg_user_id": tg_user_id,
            "session_string": session_string,
            "api_id": api_id,
            "api_hash": api_hash,
            "header_msg_id": header_msg_id,
            "client_type": client_type,
            "on_batch": on_batch,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    # ─── Operaciones para CacheRelay ───────────────────────────────

    @staticmethod
    def _to_entity_id(chat):
        """Convierte el chat a entidad: si es un id numérico (o '-100...'), a int.
        Telethon get_entity falla con strings numéricos pero funciona con int."""
        if isinstance(chat, int):
            return chat
        s = str(chat).strip()
        if re.match(r'^-?\d+$', s):
            return int(s)
        return chat

    @staticmethod
    def _is_pyro(client, client_type=None):
        """True si el cliente crudo es Pyrogram (sin get_input_entity) o el
        tipo resuelto es pyrogram. Telethon y Pyrogram comparten nombres
        (get_messages, get_me...), así que se detecta por API exclusiva."""
        try:
            if client is not None and hasattr(client, "get_input_entity"):
                return False
            if client_type == "pyrogram":
                return True
            if client is not None and hasattr(client, "edit_message_media"):
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _pyro_chat_id(chat):
        """chat_id válido para Pyrogram: int (-100...) o username."""
        if isinstance(chat, int):
            return chat
        try:
            return int(str(chat).strip())
        except Exception:
            return str(chat).strip()

    async def _get_temp_or_pool_client(self, task):
        """Devuelve (client, need_disconnect) según credenciales explícitas o pool.
        El temporal respeta client_type (antes siempre era Telethon)."""
        session_string = task.get("session_string")
        api_id = task.get("api_id")
        api_hash = task.get("api_hash")
        ctype = _preferred_client_type(task.get("client_type"))
        if session_string and api_id and api_hash:
            client = await _shared_temp_client(session_string, api_id, api_hash, ctype)
            # Compartido: el caller NO lo desconecta (need_disc=False).
            return client, False
        client = await self.pool.get_client(task.get("tg_user_id"), ctype)
        task["client_type"] = ctype
        return client, False

    async def _do_get_entity(self, task: Dict):
        chat = task["chat"]
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            await self._throttle(_uid)
            entity = await client.get_entity(self._to_entity_id(chat))
            result = {
                "id": getattr(entity, 'id', None),
                "title": getattr(entity, 'title', None) or getattr(entity, 'first_name', ''),
                "username": getattr(entity, 'username', None),
                "megagroup": bool(getattr(entity, 'megagroup', False)),
                "broadcast": bool(getattr(entity, 'broadcast', False)),
                "creator": bool(getattr(entity, 'creator', False)),
                "can_post": False,
            }
            # Determinar can_post
            try:
                await self._throttle(_uid)
                me = await client.get_me()
                my_id = getattr(me, 'id', None)
                if getattr(entity, 'creator', False):
                    result["can_post"] = True
                elif getattr(entity, 'broadcast', False):
                    # Canal: solo admin puede postear
                    await self._throttle(_uid)
                    perms = await client.get_permissions(entity, my_id)
                    admin = getattr(perms, 'admin_rights', None)
                    result["can_post"] = bool(admin and getattr(admin, 'post_messages', False))
                elif getattr(entity, 'megagroup', False):
                    # Grupo/supergrupo: miembro no restringido con send_messages permitido por defecto
                    banned = getattr(entity, 'default_banned_rights', None)
                    result["can_post"] = not (banned and getattr(banned, 'send_messages', False))
                else:
                    result["can_post"] = True
            except Exception:
                pass
            if callback:
                await callback(result)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _do_get_pinned(self, task: Dict):
        chat = task["chat"]
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            from telethon.tl.types import InputMessagesFilterPinned
            await self._throttle(_uid)
            result = []
            async for m in client.iter_messages(self._to_entity_id(chat), filter=InputMessagesFilterPinned(), limit=100):
                result.append({
                    "msg_id": int(getattr(m, 'id', 0)),
                    "caption": getattr(m, 'message', '') or getattr(m, 'text', '') or '',
                    "date": str(getattr(m, 'date', '')),
                })
            if callback:
                await callback(result)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _do_search_media(self, task: Dict):
        chat = task["chat"]
        query = task["query"]
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            await self._throttle(_uid)
            result = []
            async for m in client.iter_messages(self._to_entity_id(chat), search=query, limit=50):
                result.append({
                    "msg_id": int(getattr(m, 'id', 0)),
                    "caption": getattr(m, 'message', '') or getattr(m, 'text', '') or '',
                    "date": str(getattr(m, 'date', '')),
                })
            if callback:
                await callback(result)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _do_send_document(self, task: Dict):
        chat = task["chat"]
        file_bytes = task["file_bytes"]
        file_name = task.get("file_name", "file.bin")
        caption = task.get("caption", "")
        callback = task.get("callback")
        progress_callback = task.get("progress_callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            import io
            from telethon.tl.types import DocumentAttributeFilename
            attrs = [DocumentAttributeFilename(file_name)]
            await self._throttle(_uid)
            sent = await client.send_file(
                self._to_entity_id(chat), io.BytesIO(file_bytes),
                caption=caption, force_document=True, attributes=attrs,
                progress_callback=progress_callback)
            msg_id = int(getattr(sent, 'id', 0))
            if callback:
                await callback(msg_id)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _do_pin_message(self, task: Dict):
        chat = task["chat"]
        msg_id = task["msg_id"]
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            await self._throttle(_uid)
            await client.pin_message(self._to_entity_id(chat), msg_id, notify=False)
            if callback:
                await callback(True)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _do_download_document(self, task: Dict):
        chat = task["chat"]
        msg_id = task["msg_id"]
        callback = task.get("callback")
        progress_callback = task.get("progress_callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            import io
            await self._throttle(_uid)
            entity = await client.get_entity(self._to_entity_id(chat))
            await self._throttle(_uid)
            msg = await client.get_messages(entity, ids=msg_id)
            if msg and getattr(msg, 'media', None):
                buf = io.BytesIO()
                await client.download_media(msg, file=buf, progress_callback=progress_callback)
                data = buf.getvalue()
                if callback:
                    await callback(data)
            else:
                if callback:
                    await callback(None)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def get_entity(self, chat, tg_user_id=None, client_type="telethon",
                         session_string=None, api_id=None, api_hash=None) -> dict:
        fut = asyncio.get_event_loop().create_future()
        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "get_entity", "chat": chat,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def get_channel_last(self, chat, tg_user_id=None, client_type="telethon",
                                 session_string=None, api_id=None, api_hash=None) -> int:
        """2026-09-04 F3: último msg_id del canal/topic (1 llamada, sin escribir en caché).
        Para planificar progreso granular de scans."""
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "channel_last", "chat": chat,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        try:
            return int(await fut) or 0
        except Exception:
            return 0

    async def get_pinned_messages(self, chat, tg_user_id=None, client_type="telethon",
                                        session_string=None, api_id=None, api_hash=None) -> List[Dict]:
        fut = asyncio.get_event_loop().create_future()
        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "get_pinned", "chat": chat,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def search_messages_by_text(self, chat, query, tg_user_id=None, client_type="telethon",
                                      session_string=None, api_id=None, api_hash=None) -> List[Dict]:
        fut = asyncio.get_event_loop().create_future()
        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "search_media", "chat": chat, "query": query,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def upload_backup(self, chat, file_bytes, file_name="backup.bin", caption="",
                            tg_user_id=None, client_type="telethon",
                            session_string=None, api_id=None, api_hash=None,
                            progress_callback=None) -> int:
        fut = asyncio.get_event_loop().create_future()
        async def callback(msg_id):
            if not fut.done():
                fut.set_result(msg_id)
        await self.queue.put({
            "action": "send_document", "chat": chat, "file_bytes": file_bytes,
            "file_name": file_name, "caption": caption,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "progress_callback": progress_callback,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def pin_message(self, chat, msg_id, tg_user_id=None, client_type="telethon",
                          session_string=None, api_id=None, api_hash=None):
        fut = asyncio.get_event_loop().create_future()
        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "pin_message", "chat": chat, "msg_id": msg_id,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def download_document(self, chat, msg_id, tg_user_id=None, client_type="telethon",
                                session_string=None, api_id=None, api_hash=None,
                                progress_callback=None) -> Optional[bytes]:
        fut = asyncio.get_event_loop().create_future()
        async def callback(data):
            if not fut.done():
                fut.set_result(data)
        await self.queue.put({
            "action": "download_document", "chat": chat, "msg_id": msg_id,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "progress_callback": progress_callback,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    def _serialize_message(self, msg, client_type: str) -> dict:
        """Serializa un mensaje de Telegram al formato que consume el parser de tgindex
        (dict completo tipo `Message.to_dict()`: id, message, media con `_` discriminador,
        document/photo, action, reply_to, chat_id)."""
        try:
            if client_type == "telethon":
                try:
                    d = msg.to_dict()
                    if isinstance(d, dict):
                        return d
                except Exception:
                    pass

            base = {
                "id": int(getattr(msg, 'id', 0) or 0),
                "date": str(getattr(msg, 'date', '')) if hasattr(msg, 'date') else "",
                "message": getattr(msg, 'message', None) or getattr(msg, 'text', None) or "",
                "media": None,
                "grouped_id": getattr(msg, 'grouped_id', None),
                "reply_to": getattr(msg, 'reply_to_msg_id', None),
                "chat_id": str(getattr(msg, 'chat_id', '')),
            }
            media = getattr(msg, 'media', None)
            if media:
                try:
                    md = media.to_dict()
                    if isinstance(md, dict):
                        base["media"] = md
                except Exception:
                    base["media"] = {"_": "MessageMediaUnknown"}
            action = getattr(msg, 'action', None)
            if action is not None:
                base["action"] = {"_": getattr(action, '_', str(type(action).__name__))}
            return base
        except Exception:
            return {"id": 0, "message": ""}

    async def fetch_messages(self, channel_id: str, from_id: int, to_id: int = None,
                             topic_id: int = None, tg_user_id: int = None,
                             client_type: str = "telethon") -> List[Dict]:
        fut = asyncio.get_event_loop().create_future()
        async def callback(msgs):
            if not fut.done():
                fut.set_result(msgs)
        await self.queue.put({
            "action": "fetch_messages",
            "channel_id": channel_id,
            "from_id": from_id,
            "to_id": to_id,
            "topic_id": topic_id,
            "tg_user_id": tg_user_id,
            "client_type": client_type,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def fetch_one(self, channel_id: str, msg_id: int,
                        topic_id: int = None, tg_user_id: int = None,
                        client_type: str = "telethon",
                        min_interval: float = None, force: bool = False) -> Optional[Dict]:
        fut = asyncio.get_event_loop().create_future()
        async def callback(msg):
            if not fut.done():
                fut.set_result(msg)
        await self.queue.put({
            "action": "fetch_one",
            "channel_id": channel_id,
            "msg_id": msg_id,
            "topic_id": topic_id,
            "tg_user_id": tg_user_id,
            "client_type": client_type,
            "min_interval": min_interval,
            "force": bool(force),
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def download_media(self, channel_id: str, msg_id: int,
                             tg_user_id: int = None,
                             client_type: str = "telethon",
                             min_interval: float = None) -> Optional[bytes]:
        fut = asyncio.get_event_loop().create_future()
        async def callback(data):
            if not fut.done():
                fut.set_result(data)
        await self.queue.put({
            "action": "download_media",
            "channel_id": channel_id,
            "msg_id": msg_id,
            "tg_user_id": tg_user_id,
            "client_type": client_type,
            "min_interval": min_interval,
            "callback": callback
        }, priority=PRIORITY_HIGH)
        return await fut

    async def _do_fetch_cover(self, task: Dict):
        """Operación cover completa = 1 token: raw exacto (hit 0 llamadas) + descarga.
        Devuelve SIEMPRE dict: {"ok": True, "data": bytes|None} (None = sin foto real)
        o {"ok": False, "error": ...} (transitorio: reintentar, NO servir genérico)."""
        channel_id = task["channel_id"]
        msg_id = int(task["msg_id"])
        topic_id = task.get("topic_id")
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type") or _preferred_client_type()
        callback = task.get("callback")
        uid = self._user_key(task)
        force = bool(task.get("force"))

        async def _done(payload):
            if callback:
                try:
                    await callback(payload)
                except Exception:
                    pass

        try:
            # 1) raw exacto ANTES del throttle (2026-09-04): si está en caché y
            # dice "sin foto", se responde al instante SIN consumir token. Solo
            # se paga throttle cuando habrá llamada real a Telegram.
            raw = None
            if not force:
                try:
                    hits = self.cache.get_messages(str(channel_id), [msg_id], topic_id)
                    if hits:
                        raw = hits[0].get("message") or hits[0].get("raw")
                except Exception:
                    raw = None
            if raw is not None:
                _media0 = (raw or {}).get("media") or {}
                if _media0.get("_") != "MessageMediaPhoto":
                    await _done({"ok": True, "data": None})
                    return
            await self._throttle(uid)
            msg_obj = None
            if raw is None:
                # Miss o force: fetch exacto del mensaje (1 llamada) + guardar en caché
                client = await self.pool.get_client(tg_user_id, client_type)
                if self._is_pyro(client, client_type):
                    try:
                        msg_obj = await client.get_messages(self._pyro_chat_id(channel_id), msg_id)
                    except Exception:
                        msg_obj = None
                else:
                    try:
                        msg_obj = await client.get_messages(self._to_entity_id(channel_id), ids=msg_id)
                    except Exception:
                        msg_obj = None
                if msg_obj is None:
                    await _done({"ok": False, "error": "message-missing"})
                    return
                try:
                    raw = self._serialize_message(msg_obj, client_type)
                    self.cache.save_messages([{
                        "channel_id": str(channel_id),
                        "topic_id": topic_id,
                        "msg_id": int(getattr(msg_obj, "id", msg_id)),
                        "raw": raw,
                    }])
                except Exception:
                    pass
            media = (raw or {}).get("media") or {}
            _is_photo = media.get("_") == "MessageMediaPhoto"
            if not _is_photo and media.get("_") == "MessageMediaWebPage":
                # 2026-09-04: preview de enlace con foto (covers de texto+link).
                # download_media trae la foto del preview; sin document se intenta.
                _wp = media.get("webpage") or {}
                if _wp.get("photo") and not _wp.get("document"):
                    _is_photo = True
            if not _is_photo:
                await _done({"ok": True, "data": None})
                return
            # 2) ref fresca + descarga COMPLETA (file_reference caduca en caché).
            # NOTA 2026-09-04: prohibido el atajo inline aquí. _inline_photo_bytes
            # devuelve el stripped/cached (~30-40px) y se fosilizaba como cover
            # (pixelado al estirar). download_media trae la foto real (mayor tamaño).
            try:
                client = await self.pool.get_client(tg_user_id, client_type)
                if self._is_pyro(client, client_type):
                    try:
                        msg_obj = await client.get_messages(self._pyro_chat_id(channel_id), msg_id)
                    except Exception:
                        msg_obj = None
                else:
                    msg_obj = await client.get_messages(self._to_entity_id(channel_id), ids=msg_id)
            except Exception as e:
                await _done({"ok": False, "error": str(e)[:200]})
                return
            if msg_obj is None:
                await _done({"ok": False, "error": "message-missing"})
                return
            if self._is_pyro(client, client_type):
                try:
                    bio = await client.download_media(msg_obj, in_memory=True)
                    data = bytes(bio.getvalue()) if bio is not None else None
                except Exception:
                    data = None
            else:
                data = self._coerce_download_bytes(await client.download_media(msg_obj))
            if data:
                await _done({"ok": True, "data": data})
            else:
                await _done({"ok": False, "error": "empty-download"})
        except Exception as e:
            await _done({"ok": False, "error": str(e)[:200]})

    async def fetch_cover(self, channel_id: str, msg_id: int,
                          topic_id: int = None, tg_user_id: int = None,
                          client_type: str = None, force: bool = False) -> Dict[str, Any]:
        """Descarga el cover (foto) de un mensaje. 1 token por operación.
        client_type None = ajuste global (Comportamiento Telegram).
        force=True salta la caché (re-descarga raw + foto, p.ej. refresh_cover).
        Retorna {"ok": True, "data": bytes|None} | {"ok": False, "error": ...}."""
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "fetch_cover",
            "channel_id": channel_id,
            "msg_id": int(msg_id),
            "topic_id": topic_id,
            "tg_user_id": tg_user_id,
            "client_type": _preferred_client_type(client_type),
            "force": bool(force),
            "callback": callback
        }, priority=PRIORITY_HIGH)
        return await fut

    async def _do_fetch_thumb(self, task: Dict):
        """Descarga el thumbnail pequeño de un documento (1 token + bulk mínimo).
        Devuelve {"ok": True, "data": bytes|None} | {"ok": False, "error": ...}."""
        channel_id = task["channel_id"]
        msg_id = int(task["msg_id"])
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type", "telethon")
        callback = task.get("callback")
        uid = self._user_key(task)

        async def _done(payload):
            if callback:
                try:
                    await callback(payload)
                except Exception:
                    pass

        try:
            await self._throttle(uid)
            client = await self.pool.get_client(tg_user_id, client_type)
            if self._is_pyro(client, client_type):
                # Pyro: thumbs por file_id (el mejor disponible); sin thumbs → None.
                try:
                    msg = await client.get_messages(self._pyro_chat_id(channel_id), msg_id)
                except Exception as e:
                    await _done({"ok": False, "error": str(e)[:200]})
                    return
                if msg is None:
                    await _done({"ok": True, "data": None})
                    return
                doc = getattr(msg, "document", None)
                thumbs = list(getattr(doc, "thumbs", None) or []) if doc is not None else []
                if not thumbs:
                    await _done({"ok": True, "data": None})
                    return
                thumbs.sort(key=lambda t: int(getattr(t, "file_size", 0) or 0))
                try:
                    bio = await client.download_media(thumbs[-1].file_id, in_memory=True)
                    blob = bytes(bio.getvalue()) if bio is not None else None
                except Exception:
                    blob = None
                await _done({"ok": True, "data": blob})
                return
            try:
                msg = await client.get_messages(self._to_entity_id(channel_id), ids=msg_id)
            except Exception as e:
                await _done({"ok": False, "error": str(e)[:200]})
                return
            if isinstance(msg, list):
                msg = msg[0] if msg else None
            if not msg or not getattr(getattr(msg, "media", None), "document", None):
                await _done({"ok": True, "data": None})
                return
            doc = msg.media.document
            if not getattr(doc, "thumbs", None):
                await _done({"ok": True, "data": None})
                return
            thumb_type = "x" if any(getattr(t, "type", "") == "x" for t in doc.thumbs) else "m"
            from telethon.tl.types import InputDocumentFileLocation
            loc = InputDocumentFileLocation(
                id=doc.id, access_hash=doc.access_hash,
                file_reference=doc.file_reference, thumb_size=thumb_type)
            import io as _io
            buf = _io.BytesIO()
            try:
                async for chunk in client.iter_download(loc, offset=0, chunk_size=256 * 1024):
                    if chunk:
                        buf.write(chunk)
            except Exception as e:
                await _done({"ok": False, "error": str(e)[:200]})
                return
            blob = buf.getvalue()
            await _done({"ok": True, "data": blob or None})
        except Exception as e:
            await _done({"ok": False, "error": str(e)[:200]})

    async def fetch_thumb(self, channel_id: str, msg_id: int,
                          tg_user_id: int = None,
                          client_type: str = "telethon",
                          session_string=None, api_id=None, api_hash=None) -> Dict[str, Any]:
        """Thumbnail de documento vía servicio. Retorna {"ok","data"|None} | {"ok","error"}."""
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "fetch_thumb",
            "channel_id": channel_id,
            "msg_id": int(msg_id),
            "tg_user_id": tg_user_id,
            "client_type": client_type,
            "session_string": session_string,
            "api_id": api_id,
            "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_HIGH)
        return await fut

    async def _do_channel_last(self, task: Dict):
        """Último msg_id del chat/topic sin escribir en caché."""
        chat = task.get("chat")
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)

        async def _done(v):
            if callback:
                try:
                    await callback(v)
                except Exception:
                    pass

        try:
            await self._throttle(_uid)
            try:
                entity = await client.get_entity(self._to_entity_id(chat))
            except ValueError as _ve:
                # Sesión fresca con caché de entidades vacía (ver _do_fetch_scan).
                if "Could not find the input entity" not in str(_ve):
                    raise
                try:
                    await client.get_dialogs()
                except Exception:
                    pass
                entity = await client.get_entity(self._to_entity_id(chat))
            last = 0
            try:
                msgs = await client.get_messages(entity, limit=1)
                if msgs:
                    m0 = msgs[0] if isinstance(msgs, list) else msgs
                    last = int(getattr(m0, "id", 0) or 0)
            except Exception:
                last = 0
            await _done(last)
        except Exception:
            await _done(0)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _do_send_text(self, task: Dict):
        """Envía un mensaje de texto (1 token). Carril control Telethon."""
        chat = task["chat"]
        text = task.get("text", "")
        reply_to = task.get("reply_to_msg_id")
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            await self._throttle(_uid)
            if self._is_pyro(client, task.get("client_type")):
                sent = await client.send_message(
                    chat_id=self._pyro_chat_id(chat), text=text,
                    reply_to_message_id=int(reply_to) if reply_to else None)
            else:
                sent = await client.send_message(
                    self._to_entity_id(chat), text,
                    reply_to=reply_to if reply_to else None)
            if callback:
                await callback(int(getattr(sent, 'id', 0) or 0))
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def send_text(self, chat, text: str, reply_to_msg_id: int = None,
                        tg_user_id=None, client_type="telethon",
                        session_string=None, api_id=None, api_hash=None) -> int:
        fut = asyncio.get_event_loop().create_future()

        async def callback(msg_id):
            if not fut.done():
                fut.set_result(msg_id)
        await self.queue.put({
            "action": "send_text", "chat": chat, "text": text or "",
            "reply_to_msg_id": reply_to_msg_id,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_send_photo(self, task: Dict):
        """Envía una foto con caption (1 token). photo_bytes o nada (solo texto)."""
        chat = task["chat"]
        photo_bytes = task.get("photo_bytes")
        caption = task.get("caption")
        reply_to = task.get("reply_to_msg_id")
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            import io as _io
            await self._throttle(_uid)
            if photo_bytes:
                if self._is_pyro(client, task.get("client_type")):
                    import tempfile as _tmp, os as _os
                    with _tmp.NamedTemporaryFile(suffix=".jpg", delete=False) as _tf:
                        _tf.write(bytes(photo_bytes))
                        _tmp_path = _tf.name
                    try:
                        sent = await client.send_photo(
                            chat_id=self._pyro_chat_id(chat), photo=_tmp_path,
                            caption=caption or None,
                            reply_to_message_id=int(reply_to) if reply_to else None)
                    finally:
                        try:
                            _os.remove(_tmp_path)
                        except Exception:
                            pass
                else:
                    bio = _io.BytesIO(bytes(photo_bytes))
                    bio.name = "cover.jpg"
                    sent = await client.send_file(
                        self._to_entity_id(chat), bio,
                        caption=caption or None, force_document=False,
                        reply_to=reply_to if reply_to else None)
            elif self._is_pyro(client, task.get("client_type")):
                sent = await client.send_message(
                    chat_id=self._pyro_chat_id(chat), text=caption or "",
                    reply_to_message_id=int(reply_to) if reply_to else None)
            else:
                sent = await client.send_message(
                    self._to_entity_id(chat), caption or "",
                    reply_to=reply_to if reply_to else None)
            if callback:
                await callback(int(getattr(sent, 'id', 0) or 0))
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def send_photo(self, chat, photo_bytes=None, caption: str = None,
                         reply_to_msg_id: int = None,
                         tg_user_id=None, client_type="telethon",
                         session_string=None, api_id=None, api_hash=None) -> int:
        fut = asyncio.get_event_loop().create_future()

        async def callback(msg_id):
            if not fut.done():
                fut.set_result(msg_id)
        await self.queue.put({
            "action": "send_photo", "chat": chat, "photo_bytes": photo_bytes,
            "caption": caption, "reply_to_msg_id": reply_to_msg_id,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_list_topics(self, task: Dict):
        chat = task["chat"]
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            if self._is_pyro(client, task.get("client_type")):
                # Raw directo: el high-level de pyrofork 2.3.69 pasa
                # channel= a una raw que espera peer= (roto por dentro).
                from pyrogram.raw import functions as _rf
                await self._throttle(_uid)
                try:
                    peer = await client.resolve_peer(self._pyro_chat_id(chat))
                except Exception:
                    peer = self._pyro_chat_id(chat)
                result = []
                seen = set()
                off_date, off_id, off_topic = 0, 0, 0
                for _page in range(20):
                    try:
                        res = await client.invoke(_rf.messages.GetForumTopics(
                            peer=peer, offset_date=off_date, offset_id=off_id,
                            offset_topic=off_topic, limit=100))
                    except Exception as e:
                        print(f" [TELEGRAM SERVICE] list_topics pyro raw: {e}", flush=True)
                        break
                    batch = list(getattr(res, "topics", []) or [])
                    fresh = [t for t in batch if int(getattr(t, "id", 0) or 0) not in seen]
                    for t in fresh:
                        seen.add(int(getattr(t, "id", 0) or 0))
                        result.append({"id": int(getattr(t, "id", 0) or 0),
                                       "title": getattr(t, "title", "") or ""})
                    if len(batch) < 100 or not fresh:
                        break
                    last = batch[-1]
                    off_id = int(getattr(last, "top_message", 0) or 0)
                    off_topic = int(getattr(last, "id", 0) or 0)
                if callback:
                    await callback(result)
                return
            from telethon.tl.functions.messages import GetForumTopicsRequest
            await self._throttle(_uid)
            entity = await client.get_entity(self._to_entity_id(chat))
            peer = await client.get_input_entity(entity)
            result = []
            seen = set()
            offset_topic = 0
            offset_id = 0
            for _page in range(20):  # tope: 2000 topics
                res = await client(GetForumTopicsRequest(
                    peer=peer, offset_date=0, offset_id=offset_id,
                    offset_topic=offset_topic, limit=100))
                batch = getattr(res, 'topics', []) or []
                fresh = [t for t in batch if int(getattr(t, 'id', 0) or 0) not in seen]
                for t in fresh:
                    seen.add(int(getattr(t, 'id', 0) or 0))
                    result.append({"id": int(getattr(t, 'id', 0) or 0),
                                   "title": getattr(t, 'title', '') or ''})
                if len(batch) < 100 or not fresh:
                    break  # última página o el servidor repite página
                last = batch[-1]
                offset_id = getattr(last, 'top_message', 0) or 0
                offset_topic = getattr(last, 'id', 0) or 0
            if callback:
                await callback(result)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def list_forum_topics(self, chat, tg_user_id=None, client_type="telethon",
                                session_string=None, api_id=None, api_hash=None) -> list:
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "list_topics", "chat": chat,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_create_topic(self, task: Dict):
        import uuid as _uuid
        chat = task["chat"]
        title = task.get("title", "")
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            if self._is_pyro(client, task.get("client_type")):
                # Raw directo por el mismo motivo que list (high-level roto).
                from pyrogram.raw import functions as _rf, types as _rt
                await self._throttle(_uid)
                tid = None
                try:
                    try:
                        peer = await client.resolve_peer(self._pyro_chat_id(chat))
                    except Exception:
                        peer = self._pyro_chat_id(chat)
                    res = await client.invoke(_rf.messages.CreateForumTopic(
                        peer=peer, title=title or "",
                        random_id=int(__import__("random").randint(1, 2**31 - 1))))
                    for upd in getattr(res, "updates", []) or []:
                        try:
                            m = getattr(upd, "message", None)
                            act = getattr(m, "action", None)
                            if act is not None and type(act).__name__ == "MessageActionTopicCreate":
                                tid = getattr(m, "id", None)
                                break
                        except Exception:
                            continue
                except Exception as e:
                    print(f" [TELEGRAM SERVICE] create_topic pyro raw: {e}", flush=True)
                    tid = None
                if tid is None:
                    # Fallback: re-listar y buscar por nombre exacto.
                    try:
                        peer = await client.resolve_peer(self._pyro_chat_id(chat))
                        res2 = await client.invoke(_rf.messages.GetForumTopics(
                            peer=peer, offset_date=0, offset_id=0,
                            offset_topic=0, limit=100))
                        for t in getattr(res2, "topics", []) or []:
                            if (getattr(t, "title", "") or "").strip() == (title or "").strip():
                                tid = getattr(t, "id", None)
                                break
                    except Exception:
                        pass
                if callback:
                    await callback(int(tid) if tid else None)
                return
            from telethon.tl.functions.messages import CreateForumTopicRequest
            from telethon.tl.types import MessageActionTopicCreate, UpdateNewChannelMessage
            await self._throttle(_uid)
            entity = await client.get_entity(self._to_entity_id(chat))
            peer = await client.get_input_entity(entity)
            res = await client(CreateForumTopicRequest(
                peer=peer, title=title,
                random_id=int(_uuid.uuid4().int & 0x7fffffff)))
            tid = None
            for upd in getattr(res, 'updates', []) or []:
                if isinstance(upd, UpdateNewChannelMessage):
                    m = getattr(upd, 'message', None)
                    if m and isinstance(getattr(m, 'action', None), MessageActionTopicCreate):
                        tid = getattr(m, 'id', None)
                        break
            if callback:
                await callback(int(tid) if tid else None)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def create_forum_topic(self, chat, title: str, tg_user_id=None,
                                 client_type="telethon",
                                 session_string=None, api_id=None, api_hash=None):
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "create_topic", "chat": chat, "title": title,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_check_owner(self, task: Dict):
        chat = task["chat"]
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            if self._is_pyro(client, task.get("client_type")):
                from pyrogram.enums import ChatMembersFilter
                await self._throttle(_uid)
                me = await client.get_me()
                my_id = getattr(me, "id", None)
                is_owner = False
                can_post = False
                try:
                    async for m in client.get_chat_members(
                            self._pyro_chat_id(chat),
                            filter=ChatMembersFilter.ADMINISTRATORS, limit=200):
                        try:
                            if int(getattr(getattr(m, "user", None), "id", -1)) != int(my_id):
                                continue
                        except Exception:
                            continue
                        st = str(getattr(getattr(m, "status", ""), "value", None)
                                 or getattr(m, "status", "") or "").lower()
                        if st in ("owner", "creator"):
                            is_owner, can_post = True, True
                            break
                        if "administrat" in st:
                            priv = getattr(m, "privileges", None)
                            try:
                                can_post = bool(getattr(priv, "can_post_messages", False))
                            except Exception:
                                can_post = False
                            break
                except Exception:
                    pass
                if callback:
                    await callback(bool(is_owner or can_post))
                return
            from telethon.tl.types import ChannelParticipantsAdmins, ChannelParticipantCreator
            await self._throttle(_uid)
            entity = await client.get_entity(self._to_entity_id(chat))
            if getattr(entity, 'creator', False):
                if callback:
                    await callback(True)
                return
            me = await client.get_me()
            my_id = getattr(me, 'id', None)
            is_owner = False
            if my_id is not None:
                async for p in client.iter_participants(entity, filter=ChannelParticipantsAdmins(), limit=200):
                    if isinstance(p, ChannelParticipantCreator) and int(p.user_id) == int(my_id):
                        is_owner = True
                        break
            if callback:
                await callback(is_owner)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def check_owner(self, chat, tg_user_id=None, client_type="telethon",
                          session_string=None, api_id=None, api_hash=None) -> bool:
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "check_owner", "chat": chat,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_fetch_cover_messages(self, task: Dict):
        """Recorre hacia IDs menores desde el ancla recogiendo mensajes SIN
        documento (fotos/texto); para al encontrar uno CON documento.
        Verifica que el ancla existe y pertenece al topic (forum_topic incluido).
        Devuelve [{msg_id, text, photo_bytes}] — sin objetos raw fuera del servicio."""
        chat = task["channel_id"]
        msg_id = int(task["msg_id"])
        topic_id = int(task["topic_id"]) if task.get("topic_id") else None
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            if self._is_pyro(client, task.get("client_type")):
                # Recorrido hacia IDs menores con get_chat_history + filtro de
                # topic por reply_to_top_message_id (los mensajes fuera del
                # topic se saltan; el ancla debe pertenecer al topic).
                # DEBUG temporal: diagnosticar [] en covers con ancla válida.
                await self._throttle(_uid)
                anchor = await client.get_messages(self._pyro_chat_id(chat), msg_id)
                print(f" [TELEGRAM SERVICE] fetch_cover_messages pyro: anchor="
                      f"{type(anchor).__name__}/{getattr(anchor, 'id', '?')} "
                      f"topic_arg={topic_id}", flush=True)
                if anchor is None:
                    if callback:
                        await callback([])
                    return
                if topic_id is None:
                    topic_id = (getattr(anchor, "reply_to_top_message_id", None)
                                or getattr(anchor, "reply_to_message_id", None))
                _atid = (getattr(anchor, "reply_to_top_message_id", None)
                         or getattr(anchor, "reply_to_message_id", None))
                if topic_id and _atid and int(_atid) != int(topic_id):
                    if callback:
                        await callback([])
                    return
                out = []
                await self._throttle(_uid)
                _walked = 0
                async for m in client.get_chat_history(
                        self._pyro_chat_id(chat), limit=100, offset_id=msg_id + 1):
                    _walked += 1
                    try:
                        if getattr(m, "service", None) is not None:
                            continue
                        _mtid = (getattr(m, "reply_to_top_message_id", None)
                                 or getattr(m, "reply_to_message_id", None))
                        if topic_id and _mtid and int(_mtid) != int(topic_id) \
                                and int(getattr(m, "id", -1)) != int(topic_id):
                            continue
                        has_doc = getattr(m, "document", None) is not None
                        if has_doc and len(out) > 0:
                            break
                        text = getattr(m, "text", None) or getattr(m, "caption", "") or ""
                        photo_bytes = None
                        if getattr(m, "photo", None):
                            try:
                                await self.bulk_acquire(PRIORITY_NORMAL)
                                try:
                                    bio = await client.download_media(m, in_memory=True)
                                    photo_bytes = bytes(bio.getvalue()) if bio is not None else None
                                finally:
                                    await self.bulk_release()
                            except Exception:
                                photo_bytes = None
                        if (text or "").strip() or photo_bytes:
                            out.append({"msg_id": int(getattr(m, "id", 0) or 0),
                                        "text": text, "photo_bytes": photo_bytes})
                    except Exception:
                        continue
                out.reverse()
                print(f" [TELEGRAM SERVICE] fetch_cover_messages pyro: walked={_walked} "
                      f"out={len(out)}", flush=True)
                if callback:
                    await callback(out)
                return
            await self._throttle(_uid)
            entity = await client.get_entity(self._to_entity_id(chat))
            anchor = await client.get_messages(entity, ids=msg_id)
            if anchor is None:
                if callback:
                    await callback([])
                return
            if topic_id is None:
                topic_id = self._msg_topic_id(anchor)
            if not self._msg_in_topic_or_none(anchor, topic_id):
                if callback:
                    await callback([])
                return
            out = []
            it_kwargs = {}
            if topic_id:
                it_kwargs["reply_to"] = topic_id
            await self._throttle(_uid)
            async for m in client.iter_messages(entity, offset_id=msg_id + 1, limit=100, **it_kwargs):
                if getattr(m, 'action', None) is not None:
                    continue
                if topic_id and not self._msg_in_topic_or_none(m, topic_id) and int(getattr(m, 'id', -1)) != topic_id:
                    continue
                media = getattr(m, 'media', None)
                has_doc = media is not None and hasattr(media, 'document')
                if has_doc and len(out) > 0:
                    break
                text = getattr(m, 'message', '') or ''
                photo_bytes = None
                try:
                    has_photo = media and hasattr(media, 'photo') and media.photo
                except Exception:
                    has_photo = False
                if has_photo:
                    try:
                        await self.bulk_acquire(PRIORITY_NORMAL)
                        try:
                            photo_bytes = bytes(await client.download_media(m, file=bytes) or b"") or None
                        finally:
                            await self.bulk_release()
                    except Exception:
                        photo_bytes = None
                if (text or '').strip() or photo_bytes:
                    out.append({"msg_id": int(getattr(m, 'id', 0) or 0),
                                "text": text, "photo_bytes": photo_bytes})
            out.reverse()
            if callback:
                await callback(out)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    @staticmethod
    def _msg_topic_id(msg):
        try:
            rt = getattr(msg, 'reply_to', None)
            if rt is not None:
                top = getattr(rt, 'reply_to_top_id', None)
                if top is None:
                    top = getattr(rt, 'top_id', None)
                if top is None and getattr(rt, 'forum_topic', False):
                    top = getattr(rt, 'reply_to_msg_id', None)
                if top is not None:
                    return int(top)
            top = getattr(msg, 'reply_to_top_id', None) or getattr(msg, 'top_id', None)
            return int(top) if top is not None else None
        except Exception:
            return None

    @staticmethod
    def _msg_in_topic_or_none(msg, topic_id) -> bool:
        if not topic_id:
            return True
        try:
            if int(getattr(msg, 'id', -1)) == int(topic_id):
                return True
        except Exception:
            pass
        top = TelegramService._msg_topic_id(msg)
        return top is not None and top == topic_id

    @staticmethod
    def _msg_in_topic(msg, topic_id: int) -> bool:
        try:
            rt = getattr(msg, 'reply_to', None)
            if rt is None:
                return False
            top = getattr(rt, 'reply_to_top_id', None) or getattr(rt, 'top_id', None)
            if top:
                return int(top) == int(topic_id)
            if getattr(rt, 'forum_topic', False):
                return int(getattr(rt, 'reply_to_msg_id', -1) or -1) == int(topic_id)
        except Exception:
            pass
        return False

    async def fetch_cover_messages(self, channel_id, msg_id: int, topic_id=None,
                                   tg_user_id=None, client_type="telethon",
                                   session_string=None, api_id=None, api_hash=None) -> list:
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "fetch_cover_messages", "channel_id": channel_id,
            "msg_id": int(msg_id), "topic_id": topic_id,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_get_file_info(self, task: Dict):
        chat = task["chat"]
        msg_id = int(task["msg_id"])
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            if self._is_pyro(client, task.get("client_type")):
                # Pyrogram: document/video/audio nativos.
                await self._throttle(_uid)
                try:
                    m = await client.get_messages(self._pyro_chat_id(chat), msg_id)
                except Exception as e:
                    # NO tragar en silencio: el "¿borrado?" de TGHirayi es solo
                    # una hipótesis; el transporte (Flood/closed-db/auth) debe
                    # verse en el log para diagnosticar.
                    print(f" [TELEGRAM SERVICE] get_file_info pyro fallo chat={chat} "
                          f"msg={msg_id}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                    if callback:
                        await callback({"_transport_error": f"{type(e).__name__}: {str(e)[:150]}"})
                    return
                info = {"file_name": "", "size": 0, "mime_type": "",
                        "duration": 0, "width": 0, "height": 0, "has_thumb": False}
                if m is not None:
                    doc = getattr(m, "document", None)
                    vid = getattr(m, "video", None)
                    aud = getattr(m, "audio", None)
                    src = doc or vid or aud
                    if src is None:
                        print(f" [TELEGRAM SERVICE] get_file_info pyro sin media "
                              f"chat={chat} msg={msg_id} (empty={getattr(m, 'empty', '?')})",
                              flush=True)
                        if callback:
                            await callback(None)
                        return
                    info.update({
                        "file_name": getattr(src, "file_name", "") or "file",
                        "size": int(getattr(src, "file_size", 0) or 0),
                        "mime_type": getattr(src, "mime_type", "") or "",
                        "duration": int(getattr(src, "duration", 0) or 0),
                        "width": int(getattr(src, "width", 0) or 0),
                        "height": int(getattr(src, "height", 0) or 0),
                        "has_thumb": bool(getattr(src, "thumbs", None))})
                else:
                    print(f" [TELEGRAM SERVICE] get_file_info pyro mensaje None "
                          f"chat={chat} msg={msg_id} (sin excepcion: borrado o sin acceso)",
                          flush=True)
                    info = None
                if callback:
                    await callback(info)
                return
            from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo
            await self._throttle(_uid)
            try:
                entity = await client.get_entity(self._to_entity_id(chat))
                m = await client.get_messages(entity, ids=msg_id)
            except Exception as e:
                print(f" [TELEGRAM SERVICE] get_file_info telethon fallo chat={chat} "
                      f"msg={msg_id}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                if callback:
                    await callback({"_transport_error": f"{type(e).__name__}: {str(e)[:150]}"})
                return
            info = {"file_name": "", "size": 0, "mime_type": "",
                    "duration": 0, "width": 0, "height": 0, "has_thumb": False}
            if m is None or not getattr(m, 'media', None):
                if callback:
                    await callback(None)
                return
            media = m.media
            doc = getattr(media, 'document', None) if media else None
            if doc is None:
                if callback:
                    await callback(None)
                return
            fname = getattr(doc, 'original_name', '') or ''
            if not fname:
                for a in (doc.attributes or []):
                    if isinstance(a, DocumentAttributeFilename):
                        fname = a.file_name
                        break
            for a in (doc.attributes or []):
                if isinstance(a, DocumentAttributeVideo):
                    info["duration"] = int(getattr(a, 'duration', 0) or 0)
                    info["width"] = int(getattr(a, 'w', 0) or 0)
                    info["height"] = int(getattr(a, 'h', 0) or 0)
                    break
            info.update({"file_name": fname or "file",
                         "size": int(getattr(doc, 'size', 0) or 0),
                         "mime_type": getattr(doc, 'mime_type', '') or '',
                         "has_thumb": bool(getattr(doc, 'thumbs', None))})
            if callback:
                await callback(info)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def get_file_info(self, chat, msg_id: int, tg_user_id=None,
                            client_type="telethon",
                            session_string=None, api_id=None, api_hash=None) -> dict:
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "get_file_info", "chat": chat, "msg_id": int(msg_id),
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_copy_message(self, task: Dict):
        """Copia server-side (sin atribución): reenvía la media como nueva."""
        chat = task["chat"]
        from_chat = task["from_chat"]
        msg_id = int(task["msg_id"])
        reply_to = task.get("reply_to_msg_id")
        caption = task.get("caption")
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            if self._is_pyro(client, task.get("client_type")):
                await self._throttle(_uid)
                if caption is None:
                    try:
                        src_m = await client.get_messages(
                            self._pyro_chat_id(from_chat), msg_id)
                        caption = (getattr(src_m, "caption", None)
                                   or getattr(src_m, "text", None))
                    except Exception:
                        pass
                sent = await client.copy_message(
                    chat_id=self._pyro_chat_id(chat),
                    from_chat_id=self._pyro_chat_id(from_chat),
                    message_id=msg_id, caption=caption,
                    reply_to_message_id=int(reply_to) if reply_to else None)
                if callback:
                    await callback(int(getattr(sent, 'id', 0) or 0))
                return
            await self._throttle(_uid)
            src = await client.get_entity(self._to_entity_id(from_chat))
            tgt = await client.get_entity(self._to_entity_id(chat))
            m = await client.get_messages(src, ids=msg_id)
            if m is None:
                if callback:
                    await callback(0)
                return
            sent = await client.send_file(
                tgt, m.media or m.message or '',
                caption=caption if caption is not None else (m.message or None),
                reply_to=reply_to if reply_to else None,
                force_document=True if getattr(m, 'media', None) and hasattr(m.media, 'document') else False)
            if callback:
                await callback(int(getattr(sent, 'id', 0) or 0))
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def copy_message(self, chat, from_chat, msg_id: int, reply_to_msg_id=None,
                           caption=None, tg_user_id=None, client_type="telethon",
                           session_string=None, api_id=None, api_hash=None) -> int:
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "copy_message", "chat": chat, "from_chat": from_chat,
            "msg_id": int(msg_id), "reply_to_msg_id": reply_to_msg_id,
            "caption": caption,
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_forward_message(self, task: Dict):
        """Forward con atribución (Telegram)."""
        chat = task["chat"]
        from_chat = task["from_chat"]
        msg_id = int(task["msg_id"])
        reply_to = task.get("reply_to_msg_id")
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            await self._throttle(_uid)
            if self._is_pyro(client, task.get("client_type")):
                sent = await client.forward_messages(
                    chat_id=self._pyro_chat_id(chat),
                    from_chat_id=self._pyro_chat_id(from_chat),
                    message_ids=msg_id)
            else:
                sent = await client.forward_messages(
                    self._to_entity_id(chat), msg_id,
                    self._to_entity_id(from_chat))
            mid = 0
            try:
                mid = int(getattr(sent[0] if isinstance(sent, list) else sent, 'id', 0) or 0)
            except Exception:
                pass
            if reply_to and mid:
                pass  # forward no admite reply_to directo; se deja el hilo
            if callback:
                await callback(mid)
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def forward_message(self, chat, from_chat, msg_id: int,
                              tg_user_id=None, client_type="telethon",
                              session_string=None, api_id=None, api_hash=None) -> int:
        fut = asyncio.get_event_loop().create_future()

        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "forward_message", "chat": chat, "from_chat": from_chat,
            "msg_id": int(msg_id),
            "tg_user_id": tg_user_id, "client_type": client_type,
            "session_string": session_string, "api_id": api_id, "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def _do_edit_message(self, task: Dict):
        channel_id = task["channel_id"]
        msg_id = int(task["msg_id"])
        text = task.get("text", "")
        file_bytes = task.get("file_bytes")
        file_name = task.get("file_name", "cover.jpg")
        tg_user_id = task.get("tg_user_id")
        client_type = _preferred_client_type(task.get("client_type"))
        # La tarea viaja con el tipo resuelto (el pool indexa por él).
        task["client_type"] = client_type
        callback = task.get("callback")
        client, need_disc = await self._get_temp_or_pool_client(task)
        _uid = self._user_key(task)
        try:
            import io
            # need_disc==True means temp client created from explicit session_string/api_id/api_hash
            # else use entity resolution via _to_entity_id
            entity = self._to_entity_id(channel_id)
            try:
                await self._throttle(_uid)
                entity = await client.get_entity(entity)
            except Exception:
                pass
            is_pyro = self._is_pyro(client, client_type)
            if is_pyro:
                # Pyrogram: edit_message_text (solo texto) / edit_message_media (foto).
                # chat_id admite int (-100...) o username.
                chat_id = self._pyro_chat_id(entity if isinstance(entity, int) else channel_id)
                await self._throttle(_uid)
                if file_bytes is not None:
                    from pyrogram.types import InputMediaPhoto
                    import tempfile as _tmp, os as _os
                    with _tmp.NamedTemporaryFile(suffix=".jpg", delete=False) as _tf:
                        _tf.write(bytes(file_bytes))
                        _tmp_path = _tf.name
                    try:
                        result = await client.edit_message_media(
                            chat_id=chat_id, message_id=msg_id,
                            media=InputMediaPhoto(media=_tmp_path, caption=text or ""))
                    finally:
                        try:
                            _os.remove(_tmp_path)
                        except Exception:
                            pass
                else:
                    result = await client.edit_message_text(
                        chat_id=chat_id, message_id=msg_id, text=text)
            elif file_bytes is not None:
                bio = io.BytesIO(file_bytes)
                bio.name = file_name
                await self._throttle(_uid)
                result = await client.edit_message(entity, msg_id, text=text, file=bio)
            else:
                await self._throttle(_uid)
                result = await client.edit_message(entity, msg_id, text=text)
            # Refrescar el cache del mensaje editado
            try:
                if result is not None:
                    # result is the edited Message object
                    edited_id = getattr(result, 'id', msg_id)
                    raw = self._serialize_message(result, client_type)
                    self.cache.save_messages([{
                        "channel_id": str(channel_id),
                        "topic_id": task.get("topic_id"),
                        "msg_id": int(edited_id),
                        "raw": raw
                    }])
            except Exception as e:
                print(f" [TELEGRAM SERVICE] cache refresh post-edit: {e}", flush=True)
            if callback:
                await callback({"ok": True, "msg_id": int(getattr(result, 'id', msg_id)) if result else msg_id})
        except Exception as e:
            print(f" [TELEGRAM SERVICE] edit_message error: {e}", flush=True)
            if callback:
                await callback({"ok": False, "error": str(e)})
        finally:
            if need_disc:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def edit_message(self, channel_id: str, msg_id: int, text: str = "",
                           file_bytes: Optional[bytes] = None, file_name: str = "cover.jpg",
                           tg_user_id: int = None, client_type: str = None,
                           session_string: str = None, api_id: int = None, api_hash: str = None) -> Dict[str, Any]:
        # client_type None = ajuste global (Comportamiento Telegram).
        fut = asyncio.get_event_loop().create_future()
        async def callback(result):
            if not fut.done():
                fut.set_result(result)
        await self.queue.put({
            "action": "edit_message",
            "channel_id": channel_id,
            "msg_id": int(msg_id),
            "text": text or "",
            "file_bytes": file_bytes,
            "file_name": file_name,
            "tg_user_id": tg_user_id,
            "client_type": client_type,
            "session_string": session_string,
            "api_id": api_id,
            "api_hash": api_hash,
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut


# Instancia global del servicio
_telegram_service: Optional[TelegramService] = None


def get_telegram_service() -> TelegramService:
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramService()
    return _telegram_service
