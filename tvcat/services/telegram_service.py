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
            self._queues[priority].append(item)
            self._cond.notify()

    async def get(self):
        async with self._cond:
            while True:
                for q in self._queues:
                    if q:
                        return q.pop(0)
                await self._cond.wait()

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
            client = TelegramClient(
                session=sess.get("session_string", ""),
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
            self._conn = sqlite3.connect(DB_PATH)
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
        conn = self._get_conn()
        for msg in messages:
            conn.execute("""
                INSERT OR REPLACE INTO telegram_message_cache
                (channel_id, topic_id, msg_id, message, fetched_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                msg.get("channel_id"),
                msg.get("topic_id"),
                msg.get("msg_id"),
                json.dumps(msg.get("raw", {}), default=str),
                int(time.time())
            ))
        conn.commit()

    def get_all_messages(self, channel_id: str, topic_id: Optional[int] = None) -> List[Dict]:
        """Retorna TODOS los mensajes cacheados de un canal (para parseo de scans), ordenados por msg_id."""
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
    """Servicio central de Telegram con cola, rate limiting y caché."""

    def __init__(self):
        self.pool = TelegramClientPool()
        self.cache = TelegramMessageCache()
        self.queue = PriorityQueue()
        self._worker_task = None
        self._last_call = 0.0
        self._min_interval = 1.0  # segundos entre calls a MTProto
        self._running = False

    async def start(self):
        self.cache.init_table()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self):
        self._running = False
        await self.pool.disconnect_all()

    async def _worker_loop(self):
        while self._running:
            task = await self.queue.get()
            try:
                await self._execute_task(task)
            except Exception as e:
                print(f" [TELEGRAM SERVICE] Error en tarea: {e}", flush=True)

    async def _execute_task(self, task: Dict):
        now = time.time()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)

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

        self._last_call = time.time()

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

        cached = self.cache.get_messages(channel_id, [msg_id], topic_id)
        if cached:
            if result_callback:
                await result_callback(cached[0])
            return

        precache_from = max(1, msg_id - 50)
        precache_to = msg_id + 50
        task_data = {
            "action": "fetch_messages",
            "channel_id": channel_id,
            "from_id": precache_from,
            "to_id": precache_to,
            "topic_id": topic_id,
            "tg_user_id": tg_user_id,
            "client_type": client_type,
            "callback": lambda msgs: result_callback(msgs[-1]) if result_callback else None
        }
        await self._do_fetch_messages(task_data)

    async def _do_download_media(self, task: Dict):
        channel_id = task["channel_id"]
        msg_id = task["msg_id"]
        tg_user_id = task.get("tg_user_id")
        client_type = task.get("client_type", "telethon")
        result_callback = task.get("callback")

        client = await self.pool.get_client(tg_user_id, client_type)
        try:
            if client_type == "telethon":
                entity = await client.get_entity(int(channel_id))
                msg = await client.get_messages(entity, ids=msg_id)
            else:
                msg = await client.get_messages(int(channel_id), ids=msg_id)
            if msg and getattr(msg, 'media', None):
                data = await client.download_media(msg)
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

            entity = await client.get_entity(int(channel_id))

            # Mensaje cabecera de topic (para topo 1/2): se cachea con topic_id del topic.
            if header_msg_id:
                try:
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
        try:
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
                me = await client.get_me()
                my_id = getattr(me, 'id', None)
                if getattr(entity, 'creator', False):
                    result["can_post"] = True
                elif getattr(entity, 'broadcast', False):
                    # Canal: solo admin puede postear
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
        try:
            from telethon.tl.types import InputMessagesFilterPinned
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
        try:
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
        try:
            import io
            from telethon.tl.types import DocumentAttributeFilename
            attrs = [DocumentAttributeFilename(file_name)]
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
        try:
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
        try:
            import io
            entity = await client.get_entity(self._to_entity_id(chat))
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
                        client_type: str = "telethon") -> Optional[Dict]:
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
            "callback": callback
        }, priority=PRIORITY_NORMAL)
        return await fut

    async def download_media(self, channel_id: str, msg_id: int,
                             tg_user_id: int = None,
                             client_type: str = "telethon") -> Optional[bytes]:
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
            "callback": callback
        }, priority=PRIORITY_HIGH)
        return await fut


# Instancia global del servicio
_telegram_service: Optional[TelegramService] = None


def get_telegram_service() -> TelegramService:
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramService()
    return _telegram_service
