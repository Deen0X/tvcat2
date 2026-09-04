"""
TVCat 2 - Userbot Service Central
Wrapper unificado para Telethon y Pyrogram.
"""
import os
import sqlite3
import platform
import logging
from datetime import datetime
from typing import Optional

# 2026-09-04: silenciar la race conocida de Telethon 1.43 (recv_loop/reconnect
# con _connection=None en red inestable). Ruido que no afecta al gateway;
# los errores reales siguen en nuestros logs [USERBOT]/[JIT COVER].
logging.getLogger("telethon.network.mtprotosender").setLevel(logging.CRITICAL)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "data", "tvcat.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn


def init_table():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_user_id INTEGER UNIQUE,
            name TEXT NOT NULL,
            phone TEXT,
            api_id INTEGER,
            api_hash TEXT,
            is_default INTEGER DEFAULT 0,
            active_client TEXT DEFAULT 'telethon',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS userbot_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            client_type TEXT NOT NULL,
            tg_user_id INTEGER,
            phone TEXT,
            api_id INTEGER,
            api_hash TEXT,
            session_string TEXT,
            is_active INTEGER DEFAULT 0,
            is_primary INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Añadir columna tg_user_id a unified_catalog si no existe
    try:
        conn.execute("ALTER TABLE unified_catalog ADD COLUMN tg_user_id INTEGER")
    except:
        pass
    # Añadir columna tg_user_id a tvcat_scanned_channels si no existe
    try:
        conn.execute("ALTER TABLE tvcat_scanned_channels ADD COLUMN tg_user_id INTEGER")
    except:
        pass
    # Añadir columna is_active a userbot_sessions si no existe (migración desde is_primary)
    try:
        conn.execute("ALTER TABLE userbot_sessions ADD COLUMN is_active INTEGER DEFAULT 0")
        # Migrar datos existentes: is_primary=1 → is_active=1
        conn.execute("UPDATE userbot_sessions SET is_active=1 WHERE is_primary=1")
    except:
        pass
    # Añadir columna tg_user_id a userbot_sessions si no existe (migración)
    try:
        conn.execute("ALTER TABLE userbot_sessions ADD COLUMN tg_user_id INTEGER")
    except:
        pass
    # Añadir columna tg_user_id a item_episodes si no existe
    try:
        conn.execute("ALTER TABLE item_episodes ADD COLUMN tg_user_id INTEGER")
    except:
        pass
    conn.commit()
    conn.close()


def build_session_name(client_type: str, raw_name: str, exclude_id: int = None, strict: bool = False) -> str:
    """Construye nombre único (sin prefijo T_/P_). strict=True → error si ya existe."""
    conn = _get_conn()
    row = conn.execute("SELECT id FROM userbot_sessions WHERE name=?", (raw_name,)).fetchone()
    if not row or (exclude_id is not None and row["id"] == exclude_id):
        conn.close()
        return raw_name
    if strict:
        conn.close()
        raise ValueError(f"Ya existe una sesion '{raw_name}'")
    counter = 2
    while True:
        candidate = f"{raw_name}_{counter}"
        row = conn.execute("SELECT id FROM userbot_sessions WHERE name=?", (candidate,)).fetchone()
        if not row or (exclude_id is not None and row["id"] == exclude_id):
            conn.close()
            return candidate
        counter += 1

def generate_name(client_type: str) -> str:
    hostname = platform.node() or "unknown"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return build_session_name(client_type, f"{hostname}-{ts}")


def list_telegram_users() -> list:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM telegram_users ORDER BY is_default DESC, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_telegram_user(tg_user_id: int) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM telegram_users WHERE tg_user_id=?", (tg_user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_default_telegram_user() -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM telegram_users WHERE is_default=1 LIMIT 1").fetchone()
    if not row:
        row = conn.execute("SELECT * FROM telegram_users LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def save_telegram_user(tg_user_id: int, name: str, phone: str = None, api_id: int = None,
                       api_hash: str = None, is_default: bool = False) -> dict:
    conn = _get_conn()
    if is_default:
        conn.execute("UPDATE telegram_users SET is_default=0")
    conn.execute("""
        INSERT INTO telegram_users (tg_user_id, name, phone, api_id, api_hash, is_default)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(tg_user_id) DO UPDATE SET
            name=excluded.name, phone=excluded.phone,
            api_id=excluded.api_id, api_hash=excluded.api_hash,
            is_default=excluded.is_default
    """, (tg_user_id, name, phone, api_id, api_hash, 1 if is_default else 0))
    conn.commit()
    row = conn.execute("SELECT * FROM telegram_users WHERE tg_user_id=?", (tg_user_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_telegram_user(tg_user_id: int) -> bool:
    conn = _get_conn()
    conn.execute("DELETE FROM telegram_users WHERE tg_user_id=?", (tg_user_id,))
    conn.execute("DELETE FROM userbot_sessions WHERE tg_user_id=?", (tg_user_id,))
    conn.commit()
    conn.close()
    return True


def set_active_client(tg_user_id: int, client_type: str) -> bool:
    conn = _get_conn()
    conn.execute("UPDATE telegram_users SET active_client=? WHERE tg_user_id=?",
                 (client_type, tg_user_id))
    conn.commit()
    conn.close()
    return True


def set_default_telegram_user(tg_user_id: int) -> bool:
    conn = _get_conn()
    conn.execute("UPDATE telegram_users SET is_default=0")
    conn.execute("UPDATE telegram_users SET is_default=1 WHERE tg_user_id=?", (tg_user_id,))
    conn.commit()
    conn.close()
    return True


def _get_global_client_type() -> Optional[str]:
    try:
        conn = _get_conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key='telegram_client_type'").fetchone()
        conn.close()
        if row and row["value"] in ("telethon", "pyrogram"):
            return row["value"]
    except Exception:
        pass
    return None

def get_active_session(tg_user_id: int = None) -> Optional[dict]:
    """Devuelve la sesión activa para un usuario (o default).
    Si hay cliente global configurado (telegram_client_type), se usa ese."""
    conn = _get_conn()
    if tg_user_id is None:
        user = get_default_telegram_user()
        if not user:
            conn.close()
            return None
        tg_user_id = user["tg_user_id"]
    gct = _get_global_client_type()
    if gct:
        row = conn.execute(
            "SELECT s.*, u.active_client FROM userbot_sessions s "
            "JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
            "WHERE s.tg_user_id=? AND s.is_active=1 "
            "AND s.client_type=? LIMIT 1",
            (tg_user_id, gct)
        ).fetchone()
        # fallback si no hay sesión del tipo global para este usuario
        if not row:
            row = conn.execute(
                "SELECT s.*, u.active_client FROM userbot_sessions s "
                "JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
                "WHERE s.tg_user_id=? AND s.is_active=1 "
                "AND s.client_type=u.active_client LIMIT 1",
                (tg_user_id,)
            ).fetchone()
        conn.close()
        return dict(row) if row else None
    row = conn.execute(
        "SELECT s.*, u.active_client FROM userbot_sessions s "
        "JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
        "WHERE s.tg_user_id=? AND s.is_active=1 "
        "AND s.client_type=u.active_client LIMIT 1",
        (tg_user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_sessions(tg_user_id: int = None) -> list:
    conn = _get_conn()
    if tg_user_id:
        rows = conn.execute(
            "SELECT s.*, u.name as tg_name FROM userbot_sessions s "
            "LEFT JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
            "WHERE s.tg_user_id=? ORDER BY s.client_type, s.is_active DESC, s.id",
            (tg_user_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT s.*, u.name as tg_name FROM userbot_sessions s "
            "LEFT JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
            "ORDER BY s.tg_user_id, s.client_type, s.is_active DESC, s.id"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(session_id: int) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT s.*, u.name as tg_name FROM userbot_sessions s "
        "LEFT JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
        "WHERE s.id=?", (session_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_session(name: str, client_type: str, phone: str, api_id: int, api_hash: str,
                 session_string: str, tg_user_id: int = None, is_active: bool = False) -> dict:
    conn = _get_conn()
    # Si no hay tg_user_id, usa el default
    if tg_user_id is None:
        user = get_default_telegram_user()
        if user:
            tg_user_id = user["tg_user_id"]
    if is_active:
        conn.execute(
            "UPDATE userbot_sessions SET is_active=0 WHERE tg_user_id=? AND client_type=?",
            (tg_user_id, client_type)
        )
    conn.execute("""
        INSERT OR REPLACE INTO userbot_sessions
        (name, client_type, phone, api_id, api_hash, session_string, tg_user_id, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, client_type, phone, api_id, api_hash, session_string, tg_user_id, 1 if is_active else 0))
    conn.commit()
    row = conn.execute("SELECT * FROM userbot_sessions WHERE name=?", (name,)).fetchone()
    conn.close()
    return dict(row)


def update_session(session_id: int, **kwargs) -> bool:
    conn = _get_conn()
    if kwargs.get("is_active"):
        # Desactivar otras sessions del mismo tg_user_id y client_type
        sess = get_session(session_id)
        if sess and sess.get("tg_user_id"):
            conn.execute(
                "UPDATE userbot_sessions SET is_active=0 WHERE tg_user_id=? AND client_type=?",
                (sess["tg_user_id"], sess["client_type"])
            )
    sets = []
    vals = []
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        vals.append(v)
    if sets:
        conn.execute(f"UPDATE userbot_sessions SET {', '.join(sets)} WHERE id=?", vals + [session_id])
    conn.commit()
    conn.close()
    return True


def delete_session(session_id: int) -> bool:
    conn = _get_conn()
    conn.execute("DELETE FROM userbot_sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()
    return True


def get_session_for_user(tg_user_id: int, client_type: str = "telethon") -> Optional[dict]:
    """Devuelve una sesión para un usuario y tipo de cliente específicos."""
    conn = _get_conn()
    # Primero buscar activa, luego cualquier sesión
    row = conn.execute(
        "SELECT s.*, u.active_client FROM userbot_sessions s "
        "JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
        "WHERE s.tg_user_id=? AND s.client_type=? AND s.is_active=1 "
        "LIMIT 1",
        (tg_user_id, client_type)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT s.*, u.active_client FROM userbot_sessions s "
            "JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
            "WHERE s.tg_user_id=? AND s.client_type=? "
            "LIMIT 1",
            (tg_user_id, client_type)
        ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_primary_session() -> Optional[dict]:
    """Compatibilidad: devuelve la primera sesión activa o default. Usar get_active_session()."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT s.*, u.name as tg_name FROM userbot_sessions s "
        "LEFT JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
        "WHERE s.is_active=1 LIMIT 1"
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT s.*, u.name as tg_name FROM userbot_sessions s "
            "LEFT JOIN telegram_users u ON u.tg_user_id = s.tg_user_id "
            "LIMIT 1"
        ).fetchone()
    conn.close()
    return dict(row) if row else None


# === Pool de Clientes Persistentes ===
# Exactamente 2 clientes: uno Telethon, uno Pyrogram. Se crean bajo demanda.

_client_pool = {}

# 2026-09-04: locks single-flight por clave. Sin esto, N corutinas concurrentes
# veían el cliente caído y lanzaban N connect() en paralelo -> N-1 senders
# abandonados cuyo recv_loop/reconnect crashea en Telethon (_connection=None)
# y fuga de sockets que Telegram corta en bucle.
import asyncio as _asyncio
_client_locks = {}

def _pool_lock(key: str):
    lk = _client_locks.get(key)
    if lk is None:
        lk = _asyncio.Lock()
        _client_locks[key] = lk
    return lk

async def get_active_client(client_type: str = None) -> 'UserbotClient':
    """Devuelve el cliente activo para el tipo dado (o el del usuario default)."""
    if client_type:
        key = f"active_{client_type}"
        async with _pool_lock(key):
            if key in _client_pool:
                c = _client_pool[key]
                # Si el cliente cacheado quedó desconectado (disconnect manual, caída de red),
                # reconectar antes de devolverlo (una sola vez, bajo lock).
                try:
                    raw = getattr(c, '_client', None)
                    connected = await raw.is_connected() if raw else False
                except Exception:
                    connected = False
                if not connected:
                    try:
                        await c.connect()
                    except Exception as e:
                        print(f" [USERBOT] Reconnect fallido {client_type}: {e}")
                return c
        sess = get_active_session()
        if sess and sess.get("client_type") == client_type:
            client = UserbotClient(sess)
            await client.connect()
            _client_pool[key] = client
            print(f" [USERBOT] Cliente {client_type} creado para {sess.get('name','?')}")
            return client
        # Buscar cualquier sesión de ese tipo
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM userbot_sessions WHERE client_type=? LIMIT 1",
            (client_type,)
        ).fetchone()
        conn.close()
        if row:
            sess = dict(row)
            client = UserbotClient(sess)
            await client.connect()
            _client_pool[key] = client
            print(f" [USERBOT] Cliente {client_type} creado (fallback) para {sess.get('name','?')}")
            return client
        return None

    # Sin client_type: usar el tipo de la sesión activa primero
    sess = get_active_session()
    if sess:
        ct = sess.get("client_type")
        if ct:
            c = await get_active_client(ct)
            if c:
                return c
    # Fallback a cualquier tipo disponible
    for ct in ["telethon", "pyrogram"]:
        c = await get_active_client(ct)
        if c:
            return c
    return None

async def disconnect_all():
    """Desconectar todos los clientes del pool (al apagar)."""
    for key, client in list(_client_pool.items()):
        try:
            await client.disconnect()
            print(f" [USERBOT] Cliente {key} desconectado")
        except:
            pass
        del _client_pool[key]

async def force_reconnect_all():
    """Fuerza reconexión global: cierra todos los clientes del pool y los elimina.
    El próximo get_active_client creará uno fresco. Usado tras detectar estado zombie."""
    for key in list(_client_pool.keys()):
        try:
            c = _client_pool.get(key)
            if c:
                await c.disconnect()
        except Exception:
            pass
        _client_pool.pop(key, None)
    print(f" [USERBOT] force_reconnect_all ejecutado (pool limpiado)")

class UserbotClient:
    """Wrapper que abstrae Telethon y Pyrogram."""

    def __init__(self, session_data: dict):
        self.session_data = session_data
        self._client = None
        self._type = session_data.get("client_type", "telethon")

    async def connect(self):
        if self._type == "pyrogram":
            return await self._connect_pyrogram()
        return await self._connect_telethon()

    async def _connect_telethon(self):
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        # 2026-09-04: desconectar el anterior ANTES de crear uno nuevo. Si no,
        # cada reconnect (red inestable) fugaba un socket zombi que Telegram
        # corta ("Server closed the connection") y Telethon reintenta en bucle.
        old = self._client
        self._client = None
        if old is not None:
            try:
                await old.disconnect()
            except Exception:
                pass
        ss = StringSession(self.session_data.get("session_string", ""))
        self._client = TelegramClient(
            ss,
            self.session_data["api_id"],
            self.session_data["api_hash"]
        )
        await self._client.connect()
        return self._client

    async def _connect_pyrogram(self):
        from pyrogram import Client
        import os, tempfile
        # 2026-09-04: igual que telethon, cerrar el anterior para no fugarlo.
        old = self._client
        self._client = None
        if old is not None:
            try:
                await old.disconnect()
            except Exception:
                pass
        name = f"tvcat_pyro_{abs(hash(str(self.session_data.get('session_string',''))))}"
        # Workers de red configurables (por defecto 16). Afecta a subida/descarga del cliente.
        workers = int(self.session_data.get("workers", 16) or 16)
        self._client = Client(
            name=name,
            session_string=self.session_data.get("session_string") or None,
            api_id=self.session_data["api_id"],
            api_hash=self.session_data["api_hash"],
            in_memory=True,
            workers=workers,
            workdir=tempfile.gettempdir()
        )
        if self.session_data.get("session_string"):
            # start() conecta y autentica (no conectar antes, ya lo hace internamente)
            await self._client.start()
        else:
            # Sin sesión (generación): solo conectar
            await self._client.connect()
        return self._client

    async def get_me(self):
        if self._type == "pyrogram":
            return await self._client.get_me()
        return await self._client.get_me()

    async def get_entity(self, entity):
        return await self._client.get_entity(entity)

    async def get_messages(self, entity, ids):
        if self._type == "pyrogram":
            from pyrogram.types import Message
            msgs = await self._client.get_messages(entity, message_ids=[ids])
            return msgs[0] if msgs else None
        return await self._client.get_messages(entity, ids=int(ids))

    async def download_media(self, message, file: str = None):
        if self._type == "pyrogram":
            import io
            buf = io.BytesIO()
            await self._client.download_media(message, file=buf)
            buf.seek(0)
            return buf.read()
        return await self._client.download_media(message, file=bytes)

    async def iter_download(self, message, offset=0, chunk_size=131072, dc_id=None):
        print(f" [ITER_DOWNLOAD] type={self._type}, offset={offset}, chunk_size={chunk_size}, dc_id={dc_id}")
        if self._type == "pyrogram":
            # Descarga por RANGOS con GetFileRequest (evita descargar el archivo completo en memoria por petición)
            from pyrogram.raw.functions.upload import GetFile
            from pyrogram.raw.types import InputDocumentFileLocation
            from pyrogram.raw.types.upload import File as UploadFile, FileCdnRedirect
            doc = getattr(message, "document", None)
            if doc is None:
                media = getattr(message, "media", None)
                doc = getattr(media, "document", None) if media else None
            if doc is None:
                print(" [ITER_DOWNLOAD] Pyrogram: documento no disponible, fallback a download_media")
                data = await self.download_media(message)
                while offset < len(data):
                    end = min(offset + chunk_size, len(data))
                    yield data[offset:end]
                    offset = end
                return
            loc = InputDocumentFileLocation(
                id=doc.id,
                access_hash=doc.access_hash,
                file_reference=bytes(doc.file_reference) if doc.file_reference else b"",
                thumb_size=""
            )
            # Telegram capa upload.getFile en ~1MB por petición
            limit = max(4096, min(chunk_size, 1024 * 1024))
            chunk_count = 0
            while True:
                result = await self._client.invoke(GetFile(location=loc, offset=offset, limit=limit))
                if isinstance(result, FileCdnRedirect):
                    print(" [ITER_DOWNLOAD] Pyrogram: CDN Redirect detectado, fallback a download_media")
                    data = await self.download_media(message)
                    while offset < len(data):
                        end = min(offset + chunk_size, len(data))
                        yield data[offset:end]
                        offset = end
                    return
                if not result.bytes:
                    break
                yield bytes(result.bytes)
                offset += len(result.bytes)
                chunk_count += 1
                if chunk_count <= 3 or chunk_count % 50 == 0:
                    print(f" [ITER_DOWNLOAD] Pyrogram chunk #{chunk_count}: {len(result.bytes)} bytes (offset={offset})")
                if getattr(result, "type", "") == "last":
                    break
            print(f" [ITER_DOWNLOAD] Pyrogram: streaming completado ({offset} bytes, {chunk_count} chunks)")
            return
        chunk_count = 0
        kwargs = {}
        if dc_id is not None:
            kwargs["dc_id"] = dc_id
        async for chunk in self._client.iter_download(message, offset=offset, chunk_size=chunk_size, **kwargs):
            if chunk:
                chunk_count += 1
                if chunk_count <= 3 or chunk_count % 50 == 0:
                    print(f" [ITER_DOWNLOAD] Chunk #{chunk_count}: {len(bytes(chunk))} bytes")
                yield bytes(chunk)
        print(f" [ITER_DOWNLOAD] Telethon: streaming completado ({chunk_count} chunks)")

    async def send_code_request(self, phone: str):
        if self._type == "pyrogram":
            sent = await self._client.send_code(phone)
            return {"phone_code_hash": sent.phone_code_hash, "requires_2fa": False}
        sent = await self._client.send_code_request(phone)
        return {"phone_code_hash": sent.phone_code_hash, "requires_2fa": getattr(sent, 'phone_registered', False)}

    async def sign_in(self, phone: str, code: str, password: str = None, phone_code_hash: str = None):
        if self._type == "pyrogram":
            try:
                return await self._client.sign_in(phone_number=phone, phone_code=code, phone_code_hash=phone_code_hash)
            except Exception as e:
                err_str = str(e).upper()
                if "SESSION_PASSWORD_NEEDED" in err_str:
                    if password:
                        return await self._client.check_password(password)
                raise
        else:
            from telethon.errors import SessionPasswordNeededError
            try:
                return await self._client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                if password:
                    return await self._client.sign_in(password=password)
                raise

    async def get_session_string(self) -> str:
        if self._type == "pyrogram":
            return await self._client.export_session_string()
        return self._client.session.save()

    async def disconnect(self):
        try:
            await self._client.disconnect()
        except:
            pass
