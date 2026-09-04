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


class TelegramClientPool:
    """Pool de clientes Telegram por (tg_user_id, client_type)."""

    def __init__(self):
        self._clients = {}
        self._lock = asyncio.Lock()

    async def get_client(self, tg_user_id: int, client_type: str = "telethon"):
        key = (tg_user_id, client_type)
        async with self._lock:
            if key not in self._clients:
                self._clients[key] = await self._create_client(tg_user_id, client_type)
            return self._clients[key]

    async def create_temp_client(self, tg_user_id: int, client_type: str = "telethon"):
        return await self._create_client(tg_user_id, client_type)

    async def _create_client(self, tg_user_id: int, client_type: str):
        from services.userbot_service import get_session_for_user
        sess = get_session_for_user(tg_user_id, client_type)
        if not sess:
            raise ValueError(f"No session found for tg_user_id={tg_user_id}, type={client_type}")
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
            client = Client(
                name=f"temp_{tg_user_id}_{int(time.time())}",
                session_string=sess.get("session_string", ""),
                api_id=sess.get("api_id", 0),
                api_hash=sess.get("api_hash", "")
            )
        await client.connect()
        return client

    async def disconnect_all(self):
        async with self._lock:
            for key, client in self._clients.items():
                try:
                    await client.disconnect()
                except:
                    pass
            self._clients.clear()


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
        return {"per_minute": pm, "burst": bu, "users": users, "queue": self.queue.qsize()}

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
                if client_type == "telethon":
                    from telethon import TelegramClient
                    msgs = await client.get_messages(await client.get_entity(int(channel_id)), limit=batch_size, offset_id=batch_to)
                else:
                    msgs = await client.get_messages(int(channel_id), limit=batch_size, offset_id=batch_to)

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
            if client_type == "telethon":
                entity = await client.get_entity(int(channel_id))
                await self._throttle(_uid, floor=_floor)
                msg = await client.get_messages(entity, ids=msg_id)
            else:
                await self._throttle(_uid, floor=_floor)
                msg = await client.get_messages(int(channel_id), ids=msg_id)
            data = None
            if msg and getattr(msg, 'media', None):
                data = self._inline_photo_bytes(msg)
                if data is None:
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
        `on_batch(total)` se invoca por cada lote (para progreso)."""
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

            iter_kwargs = {}
            if from_id and from_id > 0:
                iter_kwargs["min_id"] = from_id
            if to_id:
                iter_kwargs["max_id"] = to_id + 1  # Telethon max_id es inclusivo
            if topic_id is not None:
                iter_kwargs["reply_to"] = int(topic_id)

            total = 0
            batch = []
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
                    self.cache.save_messages(batch)
                    total += len(batch)
                    batch = []
                    await self._throttle(_uid, floor=_floor)
                    if on_batch:
                        on_batch(total)
            if batch:
                self.cache.save_messages(batch)
                total += len(batch)
                if on_batch:
                    on_batch(total)
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

    async def _get_temp_or_pool_client(self, task):
        """Devuelve (client, need_disconnect) según credenciales explícitas o pool."""
        session_string = task.get("session_string")
        api_id = task.get("api_id")
        api_hash = task.get("api_hash")
        if session_string and api_id and api_hash:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(StringSession(session_string), int(api_id), api_hash,
                                    device_model="TVCat_Central", app_version="1.0")
            await client.connect()
            return client, True
        client = await self.pool.get_client(task.get("tg_user_id"), task.get("client_type", "telethon"))
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
        client_type = task.get("client_type", "telethon")
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
                msg_obj = await client.get_messages(self._to_entity_id(channel_id), ids=msg_id)
            except Exception as e:
                await _done({"ok": False, "error": str(e)[:200]})
                return
            if msg_obj is None:
                await _done({"ok": False, "error": "message-missing"})
                return
            data = self._coerce_download_bytes(await client.download_media(msg_obj))
            if data:
                await _done({"ok": True, "data": data})
            else:
                await _done({"ok": False, "error": "empty-download"})
        except Exception as e:
            await _done({"ok": False, "error": str(e)[:200]})

    async def fetch_cover(self, channel_id: str, msg_id: int,
                          topic_id: int = None, tg_user_id: int = None,
                          client_type: str = "telethon", force: bool = False) -> Dict[str, Any]:
        """Descarga el cover (foto) de un mensaje. 1 token por operación.
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
            "client_type": client_type,
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
                          client_type: str = "telethon") -> Dict[str, Any]:
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
            "callback": callback
        }, priority=PRIORITY_HIGH)
        return await fut

    async def _do_edit_message(self, task: Dict):
        channel_id = task["channel_id"]
        msg_id = int(task["msg_id"])
        text = task.get("text", "")
        file_bytes = task.get("file_bytes")
        file_name = task.get("file_name", "cover.jpg")
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type", "telethon")
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
            if file_bytes is not None:
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
                    raw = self._serialize_message(result, "telethon" if hasattr(client, 'edit_message') else client_type)
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
                           tg_user_id: int = None, client_type: str = "telethon",
                           session_string: str = None, api_id: int = None, api_hash: str = None) -> Dict[str, Any]:
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
