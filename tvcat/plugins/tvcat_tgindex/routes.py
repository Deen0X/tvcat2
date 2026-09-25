"""
TVCat TGIndex — FastAPI Routes
Endpoints de configuración del Userbot, gestión de canales y control del escáner.
"""

import os
import sys
import sqlite3

import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

_TVCAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TVCAT_DIR not in sys.path:
    sys.path.insert(0, _TVCAT_DIR)

from tvcat.gateway import get_db_connection  # type: ignore
from .config import load_user_config, save_user_config
from .scanner import run_background_scan, parse_topology, scanner_status, _delete_all_channel_data, _clean_scan_items, get_plugin_db_path

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

router = APIRouter()

# Caché de mensajes para streaming (evita 1 get_messages por cada chunk HTTP)
_tgindex_stream_msg_cache = {}
_tgindex_stream_msg_order = []

async def _tgindex_get_message(user_tg, entity, msg_id):
    """Obtiene el mensaje con caché en memoria (TTL 15 min, máx 100 entradas)."""
    import time as _time
    key = (entity, int(msg_id))
    now = _time.time()
    cached = _tgindex_stream_msg_cache.get(key)
    if cached and (now - cached[0]) < 900:
        return cached[1]
    msgs = await user_tg.get_messages(entity, ids=[msg_id])
    msg = msgs[0] if msgs else None
    if msg is not None:
        _tgindex_stream_msg_cache[key] = (now, msg)
        _tgindex_stream_msg_order.append(key)
        while len(_tgindex_stream_msg_order) > 100:
            old = _tgindex_stream_msg_order.pop(0)
            _tgindex_stream_msg_cache.pop(old, None)
    return msg

# -------------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------------
class UserbotConfigRequest(BaseModel):
    api_id: str
    api_hash: str
    session_string: Optional[str] = ""

class PluginConfigRequest(BaseModel):
    cycle_minutes: Optional[int] = 30
    scan_enabled: Optional[bool] = True

class TestSessionRequest(BaseModel):
    session_string: str

class SaveAccountRequest(BaseModel):
    username: str
    phone: str
    session_string: str

class UpdateDisplayNameRequest(BaseModel):
    display_name: str

class SendCodeRequest(BaseModel):
    phone: str
    is_global: Optional[bool] = False

class ConfirmCodeRequest(BaseModel):
    phone: str
    code: str
    password: Optional[str] = None
    is_global: Optional[bool] = False

class ScanRequest(BaseModel):
    id: Optional[int] = None
    rescan: Optional[bool] = False
    mode: Optional[str] = "normal"  # "normal" | "clean" | "incremental"
    regen: Optional[list] = None  # 2026-09-04: scan_ids a regenerar antes de parsear

class TopologyRequest(BaseModel):
    topology_type: int

def parse_telegram_link(url_str: str):
    """
    Parses a telegram message link.
    Returns: (channel_id, topic_id, msg_id)
    """
    url_str = url_str.strip()
    while url_str.endswith('/'):
        url_str = url_str[:-1]
        
    if "t.me/" in url_str:
        part = url_str.split("t.me/")[1]
        if part.startswith("s/"):
            part = part[2:]
            
        parts = part.split('/')
        if parts[0] == 'c':
            if len(parts) >= 3:
                raw_cid = parts[1]
                if len(parts) >= 4:
                    try:
                        topic_id = int(parts[2])
                    except ValueError:
                        topic_id = None
                    try:
                        msg_id = int(parts[3])
                    except ValueError:
                        msg_id = None
                else:
                    topic_id = None
                    try:
                        msg_id = int(parts[2])
                    except ValueError:
                        msg_id = None
                return f"-100{raw_cid}", topic_id, msg_id
            elif len(parts) == 2:
                return f"-100{parts[1]}", None, None
        else:
            if len(parts) >= 2:
                username = parts[0]
                if len(parts) >= 3:
                    try:
                        topic_id = int(parts[1])
                    except ValueError:
                        topic_id = None
                    try:
                        msg_id = int(parts[2])
                    except ValueError:
                        msg_id = None
                else:
                    topic_id = None
                    try:
                        msg_id = int(parts[1])
                    except ValueError:
                        msg_id = None
                return username, topic_id, msg_id
            else:
                return parts[0], None, None

                
    if url_str.lstrip("-").isdigit():
        val = int(url_str)
        if val > 0:
            return f"-100{val}", None, None
        return str(val), None, None
        
    return url_str, None, None

class ChannelRequest(BaseModel):
    id: Optional[int] = None
    channel_id: str = ""                 # ID del canal (URL t.me o ID), editable
    start_msg: Optional[str] = None      # Mensaje de inicio (URL o nº); vacío = 1
    end_msg: Optional[str] = None        # Mensaje de fin (URL o nº); vacío = hasta el último
    display_name: str = ""
    topology_type: Optional[int] = 2
    end_channel_id: Optional[str] = None  # Legacy alias de end_msg
    content_type: Optional[str] = "media"
    category: Optional[str] = None        # Categoría (sustituye al combo fijo content_type)
    custom_subcategory: Optional[str] = None
    topic_id: Optional[int] = None        # ID del topic (thread) para filtrar escaneo a un solo topic
    topic_name: Optional[str] = None      # Nombre descriptivo del topic (ej. "3DS")
    topic_only: Optional[int] = None      # 1 = solo este topic; 0/null = canal completo
    drop_empty_covers: Optional[int] = None  # 1 = descartar covers vacíos (último cover vigente)
    auto_refresh_interval: Optional[str] = None
    telegram_account_id: Optional[int] = None
    refresh_cycles: Optional[int] = 1
    enabled: Optional[int] = 1

class ChannelTestRequest(BaseModel):
    channel_url: str
    telegram_account_id: int

class ReorderRequest(BaseModel):
    ids: List[int]


_auth_sessions = {}

# -------------------------------------------------------------------------
# Multi-Account Telegram Sessions Management
# -------------------------------------------------------------------------
@router.post("/api/admin/telegram/auth/send_code")
async def send_auth_code(payload: SendCodeRequest):
    phone = payload.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="El teléfono es obligatorio")
        
    from tvcat.gateway import get_global_setting
    api_id = get_global_setting("userbot_api_id")
    api_hash = get_global_setting("userbot_api_hash")
    if not api_id or not api_hash:
        raise HTTPException(status_code=400, detail="Debe configurar api_id y api_hash primero en la aplicación")
        
    # Desconectar anterior si existe
    if phone in _auth_sessions:
        try:
            await _auth_sessions[phone]["client"].disconnect()
        except:
            pass
        del _auth_sessions[phone]
        
    try:
        client = TelegramClient(StringSession(), int(api_id), api_hash,
                                device_model="TVCat_TGIndex", app_version="1.0")
        await client.connect()
        sent = await client.send_code_request(phone)
        _auth_sessions[phone] = {
            "client": client,
            "phone_code_hash": sent.phone_code_hash
        }
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al enviar código: {e}")

@router.post("/api/admin/telegram/auth/confirm_code")
async def confirm_auth_code(payload: ConfirmCodeRequest):
    phone = payload.phone.strip()
    code = payload.code.strip()
    password = payload.password.strip() if payload.password else None
    
    if phone not in _auth_sessions:
        raise HTTPException(status_code=400, detail="No hay una sesión de autenticación activa para este teléfono. Solicite el código de nuevo.")
        
    session_data = _auth_sessions[phone]
    client = session_data["client"]
    phone_code_hash = session_data["phone_code_hash"]
    
    print(f"DEBUG: confirm_auth_code - phone={phone}, code={code}, has_password={bool(password)}, is_global={payload.is_global}")
    try:
        try:
            if password:
                await client.sign_in(password=password)
            else:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            return {"success": False, "needs_2fa": True}
            
        me = await client.get_me()
        username = me.username or f"{me.first_name} {me.last_name or ''}".strip()
        if not username:
            username = phone
            
        session_string = client.session.save()
        await client.disconnect()
        
        if payload.is_global:
            from tvcat.gateway import set_global_setting
            set_global_setting("userbot_session_string", session_string)
            set_global_setting("userbot_username", username)
        else:
            conn = get_db_connection(system=True)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tvcat_telegram_accounts WHERE username = ? OR phone = ?", (username, phone))
            cursor.execute(
                "INSERT INTO tvcat_telegram_accounts (username, display_name, phone, session_string) VALUES (?, ?, ?, ?)",
                (username, username, phone, session_string)
            )
            conn.commit()
            conn.close()
        
        del _auth_sessions[phone]
        return {"success": True, "username": username}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de autenticación: {e}")

@router.get("/api/admin/telegram/accounts")
async def list_telegram_accounts():
    main_account = {
        "id": -1,
        "username": "Principal",
        "display_name": "Cuenta Principal (Global)",
        "phone": "Ocultado",
        "created_at": None
    }
    try:
        conn = get_db_connection(system=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, display_name, phone, created_at FROM tvcat_telegram_accounts ORDER BY id DESC")
        accounts = [main_account]
        for row in cursor.fetchall():
            d = dict(row)
            if not d.get("display_name"):
                d["display_name"] = d["username"]
            d["phone"] = "Ocultado"
            accounts.append(d)
        conn.close()
        return accounts
    except Exception as e:
        # Si la tabla no existe o la DB no esta lista (tipico en Android en primer arranque),
        # devolvemos igualmente la cuenta principal para no bloquear la UI.
        print(f" [TGINDEX] list_telegram_accounts degradado: {e}")
        return [main_account]

@router.delete("/api/admin/telegram/accounts/{id}")
async def delete_telegram_account(id: int):
    try:
        conn = get_db_connection(system=True)
        conn.execute("DELETE FROM tvcat_telegram_accounts WHERE id = ?", (id,))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/admin/telegram/accounts/test_session")
async def test_session_string(payload: TestSessionRequest):
    session_str = payload.session_string.strip()
    if not session_str:
        return {"success": False, "error": "La cadena de sesión está vacía"}
        
    from tvcat.gateway import get_global_setting
    api_id = get_global_setting("userbot_api_id")
    api_hash = get_global_setting("userbot_api_hash")
    
    if not api_id or not api_hash:
        return {"success": False, "error": "api_id y api_hash no configurados en la aplicación"}
        
    try:
        # Verificación puntual vía servicio central (dueño único de
        # conexiones): valida contra el pool si coincide, o conexión
        # secuencial con desconexión inmediata. Nunca deja temporales.
        from services.userbot_service import test_session_string, get_preferred_client_type
        ctype = get_preferred_client_type()
        ok, me = await test_session_string(session_str, int(api_id), api_hash, ctype)
        if not ok:
            return {"success": False, "error": me if isinstance(me, str) else "La cadena de sesión no es válida o ha caducado"}

        username = getattr(me, "username", None) or f"{getattr(me, 'first_name', '') or ''} {getattr(me, 'last_name', '') or ''}".strip()
        phone = getattr(me, "phone", "") or ""
        return {"success": True, "username": username, "phone": phone}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/admin/telegram/accounts/save")
async def save_telegram_account(payload: SaveAccountRequest):
    try:
        username = payload.username.strip()
        phone = payload.phone.strip()
        session_string = payload.session_string.strip()
        
        if not username or not session_string:
            raise HTTPException(status_code=400, detail="Faltan datos requeridos")
            
        conn = get_db_connection(system=True)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tvcat_telegram_accounts WHERE username = ? OR phone = ?", (username, phone))
        cursor.execute(
            "INSERT INTO tvcat_telegram_accounts (username, display_name, phone, session_string) VALUES (?, ?, ?, ?)",
            (username, username, phone, session_string)
        )
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/admin/telegram/accounts/{id}/display_name")
async def update_display_name(id: int, payload: UpdateDisplayNameRequest):
    try:
        conn = get_db_connection(system=True)
        conn.execute(
            "UPDATE tvcat_telegram_accounts SET display_name = ? WHERE id = ?",
            (payload.display_name.strip(), id)
        )
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------------------------------------------------
# Userbot config & connection
# -------------------------------------------------------------------------


@router.get("/api/plugin/config")
async def get_plugin_config():
    config = load_user_config()
    return {
        "cycle_minutes": config.get("cycle_minutes", 30),
        "scan_enabled": config.get("scan_enabled", True),
    }


@router.post("/api/plugin/config")
async def post_plugin_config(payload: PluginConfigRequest):
    config = load_user_config()
    config["cycle_minutes"] = payload.cycle_minutes
    config["scan_enabled"] = payload.scan_enabled
    save_user_config(config)
    return {"success": True}


@router.post("/api/plugin/save")
async def save_plugin():
    """Guarda y sincroniza las tablas de exportación del plugin."""
    try:
        from .sync import sync as tgindex_sync
        items, eps = tgindex_sync()
        return {"success": True, "items": items, "episodes": eps}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/userbot/test")
async def test_userbot_connection():
    from tvcat.gateway import get_global_setting
    api_id = get_global_setting("userbot_api_id")
    api_hash = get_global_setting("userbot_api_hash")
    session_string = get_global_setting("userbot_session_string")

    if not api_id or not api_hash or not session_string:
        return {"success": False, "error": "Credenciales no configuradas"}

    try:
        # Vía servicio central: el pool conecta SU único cliente del tipo
        # preferido (dueño único, sin temporales ni segundos clientes).
        from services.userbot_service import get_active_client, get_preferred_client_type
        ctype = get_preferred_client_type()
        wrapper = await get_active_client(ctype)
        raw = getattr(wrapper, "_client", None) if wrapper else None
        if raw is None:
            return {"success": False, "error": f"Sin cliente {ctype} en el pool central"}
        try:
            me = await raw.get_me()
        except Exception:
            return {"success": False, "error": "Sesión no autorizada o caducada"}
        username = getattr(me, "username", None) or f"{getattr(me, 'first_name', '') or ''} {getattr(me, 'last_name', '') or ''}".strip()
        return {"success": True, "username": username}
    except Exception as e:
        return {"success": False, "error": str(e)}


# -------------------------------------------------------------------------
# Channels CRUD
# -------------------------------------------------------------------------
_SCANNED_CHANNELS_DDL = """CREATE TABLE IF NOT EXISTS tvcat_scanned_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                display_name TEXT,
                topology_type INTEGER,
                parsing_rules TEXT DEFAULT '{}',
                last_scanned_msg_id INTEGER DEFAULT 0,
                start_msg_id INTEGER DEFAULT 0,
                end_msg_id INTEGER DEFAULT 0,
                topic_id INTEGER DEFAULT NULL,
                content_type TEXT DEFAULT 'media',
                telegram_account_id INTEGER DEFAULT NULL,
                priority INTEGER DEFAULT 0,
                refresh_cycles INTEGER DEFAULT 1,
                status TEXT DEFAULT 'idle',
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                custom_subcategory TEXT,
                drop_empty_covers INTEGER DEFAULT 0,
                auto_refresh_interval TEXT,
                tg_user_id INTEGER,
                category TEXT,
                topic_only INTEGER DEFAULT 0,
                topic_name TEXT,
                cache_owner INTEGER,
                cache_can_post INTEGER,
                channel_last_msg_id INTEGER DEFAULT 0,
                test_only INTEGER DEFAULT 0,
                channel_last_checked_at INTEGER DEFAULT 0,
                parse_sig TEXT DEFAULT '',
                scanned_upto_msg_id INTEGER DEFAULT 0,
                range_complete INTEGER DEFAULT 0
            )"""


def _ensure_scanned_channels_table():
    """Autocurado instancia fresca: crea tvcat_scanned_channels si no existe."""
    try:
        conn = get_db_connection(system=True)
        conn.execute(_SCANNED_CHANNELS_DDL)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _ensure_channel_category_column():
    """Migración: añade columna category a tvcat_scanned_channels si no existe."""
    try:
        _ensure_scanned_channels_table()
        conn = get_db_connection(system=True)
        conn.execute("ALTER TABLE tvcat_scanned_channels ADD COLUMN category TEXT")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _ensure_scanstate_columns():
    """2026-09-04 F4: columnas de estado por scan item (tolerante, sin migración dura).
    2026-09-06: + scanned_upto_msg_id (cursor de fetch) + range_complete, con
    backfill conservador U=L (solo filas con U=0; no pisa re-ejecuciones)."""
    try:
        _ensure_scanned_channels_table()
        conn = get_db_connection(system=True)
        for ddl in ("ALTER TABLE tvcat_scanned_channels ADD COLUMN channel_last_msg_id INTEGER DEFAULT 0",
                    "ALTER TABLE tvcat_scanned_channels ADD COLUMN test_only INTEGER DEFAULT 0",
                    "ALTER TABLE tvcat_scanned_channels ADD COLUMN channel_last_checked_at INTEGER DEFAULT 0",
                    "ALTER TABLE tvcat_scanned_channels ADD COLUMN parse_sig TEXT DEFAULT ''",
                    "ALTER TABLE tvcat_scanned_channels ADD COLUMN scanned_upto_msg_id INTEGER DEFAULT 0",
                    "ALTER TABLE tvcat_scanned_channels ADD COLUMN range_complete INTEGER DEFAULT 0"):
            try:
                conn.execute(ddl)
            except Exception:
                pass
        try:
            conn.execute("UPDATE tvcat_scanned_channels SET scanned_upto_msg_id = last_scanned_msg_id "
                         "WHERE scanned_upto_msg_id IS NULL OR scanned_upto_msg_id = 0")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception:
        pass


@router.get("/api/user/channels")
async def list_channels():
    try:
        _ensure_channel_category_column()
        _ensure_scanstate_columns()
        conn = get_db_connection(system=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, COALESCE(a.display_name, a.username) as telegram_account_username
            FROM tvcat_scanned_channels c
            LEFT JOIN tvcat_telegram_accounts a ON c.telegram_account_id = a.id
            ORDER BY c.id DESC
        """)
        channels = [dict(r) for r in cursor.fetchall()]
        conn.close()
        # Nº de títulos identificados por scan item (source='scan_X' en la DB del plugin).
        try:
            _pdb = get_plugin_db_path()
            if os.path.isfile(_pdb):
                _pc = sqlite3.connect(f"file:{_pdb}?mode=ro", uri=True, timeout=10)
                try:
                    _rows = _pc.execute(
                        "SELECT source, COUNT(*) FROM unified_catalog WHERE source LIKE 'scan_%' GROUP BY source").fetchall()
                    _counts = {str(r[0]): int(r[1]) for r in _rows}
                finally:
                    _pc.close()
                for _ch in channels:
                    _ch["items_count"] = _counts.get(f"scan_{_ch.get('id')}", 0)
        except Exception:
            pass
        return channels
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/user/channels")
async def add_channel(payload: ChannelRequest):
    try:
        _ensure_channel_category_column()
        # --- channel_id: ID del canal (URL t.me o ID), editable ---
        chan_field = (payload.channel_id or "").strip()
        if not chan_field:
            raise HTTPException(400, "channel_id requerido")
        channel_id, topic_id, chan_msg_id = parse_telegram_link(chan_field)
        effective_topic_id = topic_id  # inicial: del channel URL; la auto-detección del start_msg lo sobreescribe

        # --- start_msg: mensaje de inicio (URL o nº). Vacío → 1 ---
        start_msg_id = 1
        start_topic_id = None
        start_str = (payload.start_msg or "").strip()
        if start_str:
            if start_str.isdigit():
                start_msg_id = int(start_str)
            else:
                _, start_topic_id, sm_id = parse_telegram_link(start_str)
                start_msg_id = sm_id or 1
        elif chan_msg_id:
            # El channel_id venía como URL con mensaje (t.me/c/123/5) → usar ese msg
            start_msg_id = chan_msg_id
        if start_msg_id < 1:
            start_msg_id = 1

        # Auto-detectar topic_id del start_msg si no se envió explícitamente
        if payload.topic_id is not None:
            effective_topic_id = payload.topic_id
        elif start_topic_id is not None:
            effective_topic_id = start_topic_id

        # --- end_msg: mensaje de fin (URL o nº). Vacío → 0 (hasta el último) ---
        end_msg_id = 0
        end_str = (payload.end_msg or payload.end_channel_id or "").strip()
        if end_str:
            if end_str.isdigit():
                end_msg_id = int(end_str)
            else:
                _, _, e_id = parse_telegram_link(end_str)
                end_msg_id = e_id or 0
        if end_msg_id and end_msg_id < start_msg_id:
            end_msg_id = 0

        conn = get_db_connection(system=True)
        
        current_last_scanned = 0
        current_start_msg_id = 0
        current_end_msg_id = 0
        current_topic_id = None
        current_topic_only = 0
        current_enabled = None
        if payload.id:
            row = conn.execute("SELECT last_scanned_msg_id, start_msg_id, end_msg_id, topic_id, topic_only, enabled FROM tvcat_scanned_channels WHERE id = ?", (payload.id,)).fetchone()
            if row:
                current_last_scanned = row[0]
                current_start_msg_id = row[1]
                current_end_msg_id = row[2] or 0
                current_topic_id = row[3]
                current_topic_only = row[4] or 0
                current_enabled = row[5]

        last_scanned_msg_id = max(0, start_msg_id - 1)
        if payload.id and start_msg_id == current_start_msg_id:
            last_scanned_msg_id = current_last_scanned
            
        content_type = (payload.content_type or 'media').strip()
        # Categoría: el nuevo campo `category` (combo) manda; si no viene, mapa legacy por content_type
        _category_map = {"media": "media", "ebook": "kiosko", "audiolibro": "media", "game": "game"}
        category = (payload.category or "").strip() or _category_map.get(content_type, "media")
        custom_sub = payload.custom_subcategory.strip() if payload.custom_subcategory else None
        # Si no hay subcategoría personalizada, usar topic_name como subcategoría (incluyendo "General")
        if not custom_sub:
            custom_sub = (payload.topic_name or "").strip() or None
        auto_refresh = None  # Deshabilitado por ciclos de refresco
        enabled = payload.enabled if payload.enabled is not None else 1
        topic_only = (payload.topic_only or 0) and 1 or 0
        effective_topic_name = (payload.topic_name or "").strip() or None
        drop_empty = (payload.drop_empty_covers or 0) and 1 or 0
        # Migración: columnas topic_only y topic_name
        for col in ["topic_only INTEGER DEFAULT 0", "topic_name TEXT",
                    "drop_empty_covers INTEGER DEFAULT 0"]:
            try: conn.execute(f"ALTER TABLE tvcat_scanned_channels ADD COLUMN {col}")
            except Exception: pass
        conn.commit()
        
        if payload.id:
            conn.execute(
                """UPDATE tvcat_scanned_channels 
                   SET channel_id = ?, display_name = ?, topology_type = ?, 
                       last_scanned_msg_id = ?, start_msg_id = ?, end_msg_id = ?, topic_id = ?, 
                       content_type = ?, category = ?, custom_subcategory = ?, auto_refresh_interval = ?,
                       telegram_account_id = ?, refresh_cycles = ?, enabled = ?, topic_only = ?, topic_name = ?,
                       drop_empty_covers = ?
                   WHERE id = ?""",
                (channel_id, payload.display_name.strip(), payload.topology_type,
                 last_scanned_msg_id, start_msg_id or 0, end_msg_id, effective_topic_id, 
                 content_type, category, custom_sub, auto_refresh, payload.telegram_account_id,
                 payload.refresh_cycles, enabled, topic_only, effective_topic_name, drop_empty, payload.id),
            )
        else:
            conn.execute(
                """INSERT INTO tvcat_scanned_channels 
                   (channel_id, display_name, topology_type, last_scanned_msg_id, start_msg_id, end_msg_id, 
                    topic_id, content_type, category, custom_subcategory, auto_refresh_interval, telegram_account_id, refresh_cycles, enabled, topic_only, topic_name, drop_empty_covers) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (channel_id, payload.display_name.strip(), payload.topology_type,
                 last_scanned_msg_id, start_msg_id or 0, end_msg_id, effective_topic_id, 
                 content_type, category, custom_sub, auto_refresh, payload.telegram_account_id, payload.refresh_cycles, enabled, topic_only, effective_topic_name, drop_empty),
            )
        new_id = payload.id or conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # 2026-09-06: si cambia el universo examinado (rango o topic), el cursor y
        # la cobertura caducan: reset U/L/RC para re-examinar desde el inicio.
        # (El `max(start-1, U)` del ciclo ya se autocorrige si el inicio avanza;
        # si retrocede o cambia el topic, sin reset esos mensajes no se fetchean.)
        try:
            _rc_reset = False
            if payload.id:
                _rc_reset = (start_msg_id != (current_start_msg_id or 0)
                             or int(end_msg_id or 0) != int(current_end_msg_id or 0)
                             or (effective_topic_id or 0) != (current_topic_id or 0)
                             or int(topic_only or 0) != int(current_topic_only or 0))
            else:
                _rc_reset = True
            if _rc_reset:
                conn.execute("UPDATE tvcat_scanned_channels SET scanned_upto_msg_id = ?, range_complete = 0, "
                             "last_scanned_msg_id = ? WHERE id = ?",
                             (max(0, start_msg_id - 1), max(0, start_msg_id - 1), new_id))
        except Exception:
            pass
        conn.commit()
        conn.close()

        # --- Propagar categoría y subcategoría al unified_catalog del plugin ---
        # Si el canal ya existe (update), actualizar category/subcategory en unified_catalog del
        # PLUGIN para los ítems de este scan (source = 'scan_{id}'), así el sidebar refleja el
        # cambio sin re-parsear. (get_db_connection() devuelve la DB del SISTEMA; aquí se usa la del plugin.)
        if payload.id:
            try:
                import sqlite3 as _sqlite3
                plugin_db = get_plugin_db_path()
                plugin_conn = _sqlite3.connect(plugin_db, timeout=30)
                plugin_conn.execute("PRAGMA busy_timeout=30000")
                # Asegurar columna sync_timestamp (migración idempotente)
                try:
                    plugin_conn.execute("ALTER TABLE unified_catalog ADD COLUMN sync_timestamp INTEGER DEFAULT (unixepoch())")
                    plugin_conn.commit()
                except Exception:
                    pass
                source_tag = f"scan_{payload.id}"
                effective_subcat = custom_sub if custom_sub else None
                plugin_conn.execute(
                    "UPDATE unified_catalog SET subcategory = ?, category = ?, sync_timestamp = unixepoch() WHERE source = ?",
                    (effective_subcat, category, source_tag)
                )
                # Si cambió el estado habilitado, propagar sync_status (mismo criterio que el toggle)
                if current_enabled is not None and int(current_enabled) != int(enabled):
                    status = "active" if enabled else "deleted"
                    plugin_conn.execute(
                        "UPDATE unified_catalog SET sync_status = ? WHERE source = ?",
                        (status, source_tag)
                    )
                    plugin_conn.execute(
                        "UPDATE item_episodes SET sync_status = ? WHERE item_id IN (SELECT id FROM unified_catalog WHERE source = ?)",
                        (status, source_tag)
                    )
                plugin_conn.commit()
                plugin_conn.close()
            except Exception as subcat_err:
                print(f" [TGIndex] Aviso: no se pudo propagar subcategory al catalog: {subcat_err}")

        # Registrar/actualizar timer de auto-refresh (siempre desactivado ahora)
        pass

        # Import automático desde CacheRelay (solo en creación, no en edición).
        # Si el canal ya tiene caché publicada por el dueño, se recupera e importa.
        cache_relay = None
        if not payload.id:
            try:
                from services.cache_relay import discover_backups, download_backup, import_channel_cache, _get_config
                cfg = _get_config()
                manifest = await discover_backups(channel_id, channel_id=channel_id)
                if manifest:
                    gz = await download_backup(manifest, channel_id)
                    if gz is not None:
                        res = import_channel_cache(gz, channel_id, cfg.get("overwrite", False), manifest, channel_id)
                        if res.get("ok"):
                            cache_relay = {"found": True, "imported": res.get("imported", 0), "total": res.get("total", 0), "skipped": res.get("skipped", False)}
            except Exception as cr_err:
                print(f" [TGIndex] Aviso: import CacheRelay falló: {cr_err}")

        # Si cambió el estado habilitado: regenerar export + refrescar caché central
        if payload.id and current_enabled is not None and int(current_enabled) != int(enabled):
            from .sync import refresh_central_cache
            refresh_central_cache(f"save scan #{payload.id}")

        return {"success": True, "id": new_id, "cache_relay": cache_relay}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ToggleRequest(BaseModel):
    enabled: int


@router.post("/api/user/channels/{cid}/toggle")
async def toggle_channel(cid: int, payload: ToggleRequest):
    """Activa/desactiva un scan item y marca sus registros (unified_catalog/item_episodes del
    plugin) con sync_status='active'|'deleted'. El catálogo central solo obtiene activos."""
    try:
        enabled = 1 if payload.enabled else 0
        conn = get_db_connection(system=True)
        row = conn.execute("SELECT channel_id FROM tvcat_scanned_channels WHERE id = ?", (cid,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Scan item no encontrado")
        conn.execute("UPDATE tvcat_scanned_channels SET enabled = ? WHERE id = ?", (enabled, cid))
        conn.commit()
        conn.close()

        # Marcar sync_status en el catálogo del plugin para este scan
        source_tag = f"scan_{cid}"
        status = "active" if enabled else "deleted"
        try:
            import sqlite3 as _sqlite3
            plugin_db = get_plugin_db_path()
            pconn = _sqlite3.connect(plugin_db, timeout=30)
            pconn.execute("PRAGMA busy_timeout=30000")
            pconn.execute("UPDATE unified_catalog SET sync_status = ? WHERE source = ?", (status, source_tag))
            pconn.execute(
                "UPDATE item_episodes SET sync_status = ? WHERE item_id IN (SELECT id FROM unified_catalog WHERE source = ?)",
                (status, source_tag)
            )
            pconn.commit()
            pconn.close()
        except Exception as e:
            print(f" [TGIndex] Aviso: no se pudo marcar sync_status del scan #{cid}: {e}")

        # Señal de actualización: refrescar export + caché central
        from .sync import refresh_central_cache
        refresh_central_cache(f"toggle #{cid}")

        return {"success": True, "enabled": enabled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TopoRequest(BaseModel):
    topology_type: int = 4


@router.post("/api/user/channels/{cid}/topology")
async def set_channel_topology(cid: int, body: TopoRequest):
    """2026-09-04 F4: cambia solo la topología (los generados se regeneran en el próximo Aplicar)."""
    try:
        t = int(body.topology_type)
        if t not in (0, 1, 2, 3, 4):
            raise HTTPException(status_code=400, detail="Topología no válida")
        conn = get_db_connection(system=True)
        conn.execute("UPDATE tvcat_scanned_channels SET topology_type = ? WHERE id = ?", (t, cid))
        conn.commit()
        conn.close()
        return {"success": True, "topology_type": t}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class FlagsRequest(BaseModel):
    toggles: dict = {}


@router.post("/api/user/channels/flags")
async def set_channels_flags(body: FlagsRequest):
    """2026-09-04: persiste SOLO los flags enabled (ms). La disponibilidad se aplica
    al final del scan (pasada en orden de prioridad)."""
    try:
        conn = get_db_connection(system=True)
        n = 0
        for k, v in (body.toggles or {}).items():
            try:
                conn.execute("UPDATE tvcat_scanned_channels SET enabled = ? WHERE id = ?",
                             (1 if v else 0, int(k)))
                n += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        return {"success": True, "updated": n}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TogglesRequest(BaseModel):
    toggles: dict = {}


@router.post("/api/user/channels/toggles")
async def toggle_channels_bulk(body: TogglesRequest):
    """2026-09-04 F1: toggles diferidos en lote. Persiste flags y aplica alta/baja
    incremental SIN reconstrucción total (ms en vez de segundos)."""
    try:
        from .sync import apply_toggles_incremental
        toggles = {}
        for k, v in (body.toggles or {}).items():
            try:
                toggles[int(k)] = 1 if v else 0
            except Exception:
                pass
        if not toggles:
            return {"success": True, "applied": {}}
        applied = await asyncio.to_thread(apply_toggles_incremental, toggles)
        return {"success": True, "applied": applied}
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f" [TGIndex] toggle bulk error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TestParseRequest(BaseModel):
    channel_id: str = ""
    start_msg_id: int = 1
    end_msg_id: int = 0
    topic_id: Optional[int] = None
    topology_type: int = 4
    telegram_account_id: Optional[int] = None
    scan_id: Optional[int] = None


@router.post("/api/user/channels/test-parse")
async def test_parse_channel(body: TestParseRequest):
    """2026-09-04 F2: Test de scan item. Trae 100 mensajes desde el inicio (se cachean
    normal, no se desperdician), parsea en memoria con la topología indicada y devuelve
    conteo + muestra de títulos. NO guarda items ni toca la central."""
    try:
        from .scanner import (_rows_to_msgs, _group_messages_topo4,
                                 _segment_blocks, _parse_block_title_desc,
                                 _get_file_name_topo0, _is_collection_text,
                                 _parse_collection_entries, _resolve_scan_target)
        from services.telegram_service import get_telegram_service
        from services.cache_keys import canon_channel
        from tvcat.gateway import get_db_connection
        import json as _json

        channel = (body.channel_id or "").strip()
        if not channel:
            raise HTTPException(status_code=400, detail="Falta channel_id")
        start = max(1, int(body.start_msg_id or 1))
        Ulm = start + 99
        if body.end_msg_id and int(body.end_msg_id) > 0:
            Ulm = min(Ulm, int(body.end_msg_id))
        _tgt, _tctype, _twhy = _resolve_scan_target(body.telegram_account_id)
        if not _tgt:
            raise HTTPException(status_code=400, detail=f"Cuenta de Telegram no válida ({_twhy})")
        svc = get_telegram_service()
        try:
            await asyncio.wait_for(svc.scan_messages(
                channel_id=channel, from_id=start, to_id=Ulm,
                topic_id=body.topic_id, tg_user_id=_tgt,
                client_type=_tctype), timeout=120)
        except asyncio.TimeoutError:
            pass
        canon = canon_channel(channel)
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM telegram_message_cache WHERE channel_id = ? AND msg_id >= ? AND msg_id <= ? ORDER BY msg_id ASC",
            (canon, start, Ulm)).fetchall()
        conn.close()
        msgs = _rows_to_msgs(rows, canon)
        if body.topic_id is not None:
            msgs = [m for m in msgs if (m._topic_id or 0) == int(body.topic_id)]
        n_photo = sum(1 for m in msgs if m.photo is not None)
        n_file = sum(1 for m in msgs if m.document is not None)
        n_text = sum(1 for m in msgs if (m.text or "") and m.photo is None and m.document is None)
        # Colecciones: mensajes con tag (no escriben nada, solo conteo + muestra)
        _col_entries = []
        n_collections = 0
        for m in msgs:
            try:
                if _is_collection_text(getattr(m, "text", "") or ""):
                    n_collections += 1
                    _col_entries.extend(_parse_collection_entries(getattr(m, "text", "") or ""))
            except Exception:
                pass
        groups = 0
        sample = []
        try:
            topo = int(body.topology_type or 4)
            if topo in (0, 4):
                tsorted = sorted(msgs, key=lambda x: x.id)
                tgroups, _pend = _group_messages_topo4(tsorted)
                groups = len(tgroups)
                for g in tgroups[:5]:
                    try:
                        cv = g.get("cover_msg")
                        fl = g.get("files") or []
                        if cv is not None and getattr(cv, "text", None):
                            t, _d, _a, _g2, _s, _sd, _m = _parse_block_title_desc(
                                {"images": [cv], "texts": [], "files": fl}, fallback_title="?", _extra_files=fl)
                            sample.append(t or "?")
                        elif fl:
                            import os as _os, re as _re
                            sample.append(_re.sub(r"[._]", " ", _os.path.splitext(_get_file_name_topo0(fl[0]))[0][:60]).strip())
                    except Exception:
                        sample.append("?")
            else:
                blocks = _segment_blocks(sorted(msgs, key=lambda x: x.id))
                groups = len(blocks)
                for b in blocks[:5]:
                    try:
                        t, _d, _a, _g2, _s, _sd, _m = _parse_block_title_desc(b, fallback_title="?")
                        sample.append(t or "?")
                    except Exception:
                        sample.append("?")
        except Exception:
            pass
        # 2026-09-04 F4: el Test deja marca provisional (la quita el primer scan completo).
        try:
            if body.scan_id:
                _ensure_scanstate_columns()
                _tc = get_db_connection(system=True)
                _tc.execute("UPDATE tvcat_scanned_channels SET test_only = 1 WHERE id = ?", (int(body.scan_id),))
                _tc.commit()
                _tc.close()
        except Exception:
            pass
        return {"success": True, "messages": len(msgs), "photos": n_photo,
                "files": n_file, "texts": n_text, "groups": groups, "sample": sample,
                "collections": n_collections,
                "collection_sample": [e.get("title", "") for e in _col_entries[:10]]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PreviewTopoRequest(BaseModel):
    channel_id: str = ""
    start_msg_id: int = 1
    end_msg_id: int = 0
    topic_id: Optional[int] = None
    topology_type: int = 4


@router.post("/api/user/channels/preview-topo")
async def preview_topo(body: PreviewTopoRequest):
    """2026-09-04 F4: conteo por topología SOLO con caché (cero llamadas a Telegram)."""
    try:
        from .scanner import _rows_to_msgs, _group_messages_topo4, _segment_blocks
        from services.cache_keys import canon_channel
        from tvcat.gateway import get_db_connection
        import sqlite3 as _sq
        canon = canon_channel((body.channel_id or "").strip())
        start = max(1, int(body.start_msg_id or 1))
        end = int(body.end_msg_id or 0)
        conn = get_db_connection()
        conn.row_factory = _sq.Row
        q = "SELECT * FROM telegram_message_cache WHERE channel_id = ? AND msg_id >= ?"
        args = [canon, start]
        if end and end > 0:
            q += " AND msg_id <= ?"
            args.append(end)
        q += " ORDER BY msg_id ASC"
        rows = conn.execute(q, args).fetchall()
        conn.close()
        msgs = _rows_to_msgs(rows, canon)
        if body.topic_id is not None:
            msgs = [m for m in msgs if (m._topic_id or 0) == int(body.topic_id)]
        topo = int(body.topology_type or 4)
        if topo in (0, 4):
            groups, _p = _group_messages_topo4(sorted(msgs, key=lambda x: x.id))
            n = len(groups)
        else:
            n = len(_segment_blocks(sorted(msgs, key=lambda x: x.id)))
        return {"success": True, "messages": len(msgs), "groups": n}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/user/channels/{cid}/check")
async def check_channel_last(cid: int):
    """2026-09-04 F4: Comprobar — resuelve el último del canal y actualiza channel_last.
    2026-09-04b: frescura — si se comprobó hace <10 min y hay valor, se devuelve
    sin tocar Telegram (evita tormentas de checks al abrir la config)."""
    import time as _time
    try:
        from .scanner import _resolve_scan_target
        from services.telegram_service import get_telegram_service
        conn = get_db_connection(system=True)
        conn.row_factory = sqlite3.Row
        for _ddl in ("ALTER TABLE tvcat_scanned_channels ADD COLUMN channel_last_checked_at INTEGER DEFAULT 0",
                     "ALTER TABLE tvcat_scanned_channels ADD COLUMN scanned_upto_msg_id INTEGER DEFAULT 0",
                     "ALTER TABLE tvcat_scanned_channels ADD COLUMN range_complete INTEGER DEFAULT 0"):
            try:
                conn.execute(_ddl)
            except Exception:
                pass
        row = conn.execute("SELECT channel_id, telegram_account_id, last_scanned_msg_id, channel_last_msg_id, test_only, channel_last_checked_at, scanned_upto_msg_id, range_complete, start_msg_id, end_msg_id FROM tvcat_scanned_channels WHERE id = ?", (cid,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Scan item no encontrado")
        d = dict(row)
        now = int(_time.time())
        try:
            fresh = (now - int(d.get("channel_last_checked_at") or 0)) < 600 and int(d.get("channel_last_msg_id") or 0) > 0
        except Exception:
            fresh = False
        if fresh:
            conn.close()
            return {"success": True, "last_scanned": d.get("last_scanned_msg_id") or 0,
                    "channel_last": d.get("channel_last_msg_id") or 0, "test_only": d.get("test_only") or 0,
                    "scanned_upto": d.get("scanned_upto_msg_id") or 0,
                    "range_complete": d.get("range_complete") or 0,
                    "start_msg_id": d.get("start_msg_id") or 0,
                    "end_msg_id": d.get("end_msg_id") or 0,
                    "cached": True}
        ch_id = d["channel_id"]
        _tgt, _tctype, _twhy = _resolve_scan_target(d["telegram_account_id"])
        last = 0
        if _tgt:
            try:
                svc = get_telegram_service()
                last = await asyncio.wait_for(svc.get_channel_last(
                    ch_id, tg_user_id=_tgt, client_type=_tctype), timeout=60)
            except Exception:
                last = 0
        conn.execute("UPDATE tvcat_scanned_channels SET channel_last_msg_id = ?, channel_last_checked_at = ? WHERE id = ?", (int(last or 0), now, cid))
        conn.commit()
        cur = conn.execute("SELECT last_scanned_msg_id, channel_last_msg_id, test_only, scanned_upto_msg_id, range_complete, start_msg_id, end_msg_id FROM tvcat_scanned_channels WHERE id = ?", (cid,)).fetchone()
        conn.close()
        d2 = dict(cur) if cur else {}
        return {"success": True, "last_scanned": d2.get("last_scanned_msg_id") or 0,
                "channel_last": d2.get("channel_last_msg_id") or 0, "test_only": d2.get("test_only") or 0,
                "scanned_upto": d2.get("scanned_upto_msg_id") or 0,
                "range_complete": d2.get("range_complete") or 0,
                "start_msg_id": d2.get("start_msg_id") or 0,
                "end_msg_id": d2.get("end_msg_id") or 0}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/user/channels/test")
async def test_channel_connection(payload: ChannelTestRequest):
    try:
        channel_url = payload.channel_url.strip()
        channel_id, topic_id, msg_id = parse_telegram_link(channel_url)

        from .scanner import _resolve_scan_target
        from services.telegram_service import get_telegram_service
        _tgt, _tctype, _twhy = _resolve_scan_target(payload.telegram_account_id)
        if not _tgt:
            return {"success": False, "error": f"Cuenta de Telegram no válida ({_twhy})"}

        try:
            ent = await get_telegram_service().get_entity(
                channel_id, tg_user_id=_tgt, client_type=_tctype)
        except Exception as e:
            return {"success": False, "error": str(e)}

        title = (ent or {}).get("title") or "Canal de Telegram"
        return {"success": True, "title": title}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/user/channels/reorder")
async def reorder_channels(payload: ReorderRequest):
    try:
        conn = get_db_connection(system=True)
        cursor = conn.cursor()
        for idx, ch_id in enumerate(payload.ids):
            cursor.execute("UPDATE tvcat_scanned_channels SET priority = ? WHERE id = ?", (idx, ch_id))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/user/channels/{id}")
async def delete_channel(id: int):
    try:
        plugin_conn = get_db_connection()
        plugin_conn.row_factory = sqlite3.Row
        plugin_cursor = plugin_conn.cursor()
        
        system_conn = get_db_connection(system=True)
        system_conn.row_factory = sqlite3.Row
        system_cursor = system_conn.cursor()
        
        # 1. Limpiar unified_catalog
        src = f"scan_{id}"
        plugin_cursor.execute("DELETE FROM item_episodes WHERE item_id IN (SELECT id FROM unified_catalog WHERE source = ?)", (src,))
        plugin_cursor.execute("DELETE FROM unified_catalog WHERE source = ?", (src,))
        # También items legacy sin source
        system_cursor.execute("SELECT display_name FROM tvcat_scanned_channels WHERE id = ?", (id,))
        ch_row2 = system_cursor.fetchone()
        if ch_row2:
            dname = ch_row2["display_name"]
            plugin_cursor.execute(
                "SELECT id FROM unified_catalog WHERE source IS NULL AND (subcategory = ? OR subcategory LIKE ?)",
                (dname, dname + " — %")
            )
            legacy_ids = [r["id"] for r in plugin_cursor.fetchall()]
            if legacy_ids:
                ph = ",".join("?" for _ in legacy_ids)
                plugin_cursor.execute(f"DELETE FROM item_episodes WHERE item_id IN ({ph})", legacy_ids)
                plugin_cursor.execute(f"DELETE FROM unified_catalog WHERE id IN ({ph})", legacy_ids)
        plugin_conn.commit()
        
        # 2. Limpiar telegram_scan
        system_cursor.execute("SELECT channel_id FROM tvcat_scanned_channels WHERE id = ?", (id,))
        row = system_cursor.fetchone()
        if row:
            ch_id = row["channel_id"]
            ch_entity_id = f"-100{ch_id}" if ch_id.isdigit() else ch_id
            plugin_conn.execute("DELETE FROM telegram_scan WHERE channel_id = ?", (ch_entity_id,))
            plugin_cursor.execute("DELETE FROM telegram_scan WHERE channel_id = ?", (ch_id,))
            plugin_conn.commit()
        
        # 3. Eliminar la configuración del canal
        system_cursor.execute("DELETE FROM tvcat_scanned_channels WHERE id = ?", (id,))
        system_conn.commit()
        
        plugin_conn.close()
        system_conn.close()

        # Regenerar export + refrescar caché central (los registros del scan ya no existen)
        from .sync import refresh_central_cache
        refresh_central_cache(f"delete scan #{id}")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/user/channels/{id}/topology")
async def update_topology(id: int, payload: TopologyRequest):
    try:
        conn = get_db_connection(system=True)
        conn.execute("UPDATE tvcat_scanned_channels SET topology_type = ? WHERE id = ?", (payload.topology_type, id))
        conn.commit()
        conn.close()
        
        # Limpiar todo y re-parsear con nueva topología
        _delete_all_channel_data(id)
        
        n, _ = await parse_topology(id)

        # Regenerar export + refrescar caché central tras el re-parseo
        from .sync import refresh_central_cache
        refresh_central_cache(f"topology scan #{id}")
        
        return {"success": True, "reparsed": n}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





# -------------------------------------------------------------------------
# Standalone cleanup (sin escaneo)
# -------------------------------------------------------------------------
@router.post("/api/user/channels/{id}/clean-records")
async def clean_records(id: int):
    """Elimina TODOS los registros del canal: unified_catalog + item_episodes + telegram_scan."""
    import traceback
    try:
        _delete_all_channel_data(id)
        from .sync import refresh_central_cache
        refresh_central_cache(f"clean scan #{id}")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------------
# Auto-refresh (Actualizar ligero)
# -------------------------------------------------------------------------
@router.post("/api/user/scan/update/{channel_id}")
async def trigger_update(channel_id: int):
    """Actualización ligera: solo mensajes nuevos, reusa cliente Telegram."""
    from .scanner import scanner_status, auto_refresh_channel
    if scanner_status["status"] == "scanning":
        return {"success": False, "error": "Ya hay un escaneo en curso"}
    try:
        await auto_refresh_channel(channel_id)
        from .sync import refresh_central_cache
        refresh_central_cache(f"update scan #{channel_id}")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------------
# Scanner control
# -------------------------------------------------------------------------
@router.post("/api/user/scan/start")
async def start_scan(payload: ScanRequest = ScanRequest()):
    if scanner_status["status"] == "scanning":
        return {"success": False, "error": "Ya hay un escaneo en curso"}
        
    mode = (payload.mode or "normal").lower()
    print(f" [SCAN START] Lanzando run_background_scan(target_id={payload.id}) en modo {mode}")
    prev_task = scanner_status.get("_scan_task")
    if prev_task and not prev_task.done():
        prev_task.cancel()
    try:
        scanner_status["regen_ids"] = [int(x) for x in (payload.regen or [])]
    except Exception:
        scanner_status["regen_ids"] = []
    scan_task = asyncio.create_task(run_background_scan(target_id=payload.id, mode=mode))
    scanner_status["_scan_task"] = scan_task
    return {"success": True}


@router.get("/api/user/scan/status")
async def get_scan_status():
    status = dict(scanner_status)
    status.pop("_scan_task", None)
    return status


@router.post("/api/user/scan/logs/clear")
async def clear_scan_logs():
    """2026-09-07: vacía el log del servidor (el frontal solo limpiaba el DOM
    y el siguiente poll repintaba las líneas viejas)."""
    try:
        from .scanner import scanner_status as _ss
        _ss["logs"] = []
    except Exception:
        pass
    return {"success": True}





@router.post("/api/user/parse/{channel_id}")
async def trigger_parse(channel_id: int):
    """Limpia items del scan y re-parsea desde telegram_scan."""
    from .scanner import scanner_status as ss, add_log
    _clean_scan_items(channel_id)
    add_log(f"▶️ Parse manual para scan #{channel_id}")
    n, u = await parse_topology(channel_id)
    ss["refresh_signal"] = ss.get("refresh_signal", 0) + n
    ss["parse_pending"] = False
    add_log(f"  ✅ Parse completado: {n} título(s) nuevo(s)")
    from .sync import refresh_central_cache
    refresh_central_cache(f"parse scan #{channel_id}")
    return {"success": True, "new_items": n, "updated": u}


@router.post("/api/user/parse")
async def trigger_parse_all():
    """Limpia items de todos los scans y re-parsea."""
    from .scanner import scanner_status as ss
    import sqlite3
    conn = get_db_connection(system=True)
    conn.row_factory = sqlite3.Row
    channels = [dict(r) for r in conn.execute("SELECT id FROM tvcat_scanned_channels").fetchall()]
    conn.close()
    total_new = 0
    for ch in channels:
        _clean_scan_items(ch["id"])
        n, u = await parse_topology(ch["id"])
        total_new += n
    ss["refresh_signal"] = ss.get("refresh_signal", 0) + total_new
    ss["parse_pending"] = False
    from .sync import refresh_central_cache
    refresh_central_cache("parse all")
    return {"success": True, "new_items": total_new}


# -------------------------------------------------------------------------
# Streaming desde canales de usuario (item_id con prefijo USER-)
# -------------------------------------------------------------------------
@router.get("/stream/user/episode/{episode_id}")
async def stream_user_episode(episode_id: int, request: Request):
    """Retirado (410): streaming legacy Telethon-directo eliminado en la
    centralizacion. Usar /api/stream del gateway (agnostico al cliente)."""
    raise HTTPException(status_code=410, detail="Endpoint retirado: usar /api/stream del gateway")



# ─── CacheRelay ────────────────────────────────────────────────────

class CacheRelayConfigRequest(BaseModel):
    chat_aux: str = ""
    overwrite: bool = False


class CacheRelayDownloadRequest(BaseModel):
    source: str = "auto"  # auto | aux | channel


@router.get("/api/cache-relay/channels")
async def cache_relay_channels(request: Request):
    from services.cache_relay import get_channels_with_can_post
    return {"channels": await get_channels_with_can_post()}


@router.get("/api/cache-relay/status")
async def cache_relay_status(request: Request):
    from services.cache_relay import get_progress_state
    return get_progress_state()


@router.get("/api/cache-relay/config")
async def cache_relay_config_get(request: Request):
    from services.cache_relay import _get_config
    return _get_config()


@router.post("/api/cache-relay/config")
async def cache_relay_config_set(body: CacheRelayConfigRequest, request: Request):
    from services.cache_relay import _save_config
    _save_config(body.chat_aux, body.overwrite)
    return {"ok": True}


@router.post("/api/cache-relay/{channel_id}/upload")
async def cache_relay_channel_upload(channel_id: str, request: Request):
    from services.cache_relay import export_channel_cache
    result = await export_channel_cache(channel_id)
    return result


@router.post("/api/cache-relay/{channel_id}/download")
async def cache_relay_channel_download(channel_id: str, body: CacheRelayDownloadRequest, request: Request):
    from services.cache_relay import download_and_import, _get_config
    cfg = _get_config()
    # El backup por canal se publica en el PROPIO canal (donde el dueño lo subió),
    # no en el auxiliar (el auxiliar solo guarda el full=1). No requiere can_post.
    return await download_and_import(channel_id, channel_id, cfg.get("overwrite", False))


@router.post("/api/cache-relay/upload-full")
async def cache_relay_upload_full(request: Request):
    from services.cache_relay import export_full_backup, _get_config
    cfg = _get_config()
    if not cfg.get("chat_aux"):
        return {"ok": False, "error": "Canal auxiliar no configurado"}
    return await export_full_backup(cfg["chat_aux"])


@router.post("/api/cache-relay/download-full")
async def cache_relay_download_full(request: Request):
    from services.cache_relay import discover_backups, download_backup, import_channel_cache, _get_config
    cfg = _get_config()
    if not cfg.get("chat_aux"):
        return {"ok": False, "error": "Canal auxiliar no configurado"}
    manifest = await discover_backups(cfg["chat_aux"], channel_id=None)
    if not manifest:
        return {"ok": False, "error": "No se encontró backup completo en los anclados"}
    gz = await download_backup(manifest, cfg["chat_aux"])
    if gz is None:
        return {"ok": False, "error": "No se pudo descargar el backup"}
    result = import_channel_cache(gz, "*", cfg.get("overwrite", False), manifest, cfg["chat_aux"])
    return result



# ─── Convención Indexator: canales con acceso (fuentes) ─────────────────
def get_indexator_channels():
    """Lista [{name, channel_id, topology}] desde tvcat_scanned_channels
    (DB central/sistema, igual que /api/user/channels).
    Convención para Indexator (no es endpoint)."""
    try:
        from services.catalog_service import get_conn
        conn = get_conn()
        conn.row_factory = __import__("sqlite3").Row
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tvcat_scanned_channels)").fetchall()]
        sel = [c for c in ("id", "channel_id", "display_name", "title", "name", "topology_type") if c in cols]
        out = []
        if sel:
            q = "SELECT " + ", ".join(sel) + " FROM tvcat_scanned_channels"
            for r in conn.execute(q).fetchall():
                d = dict(r)
                out.append({
                    "name": d.get("display_name") or d.get("title") or d.get("name") or d.get("channel_id"),
                    "channel_id": str(d.get("channel_id") or ""),
                    "topology": d.get("topology_type"),
                })
        conn.close()
        return out
    except Exception:
        return []

# -------------------------------------------------------------------------
# Diccionario de subcategor�as (normalizaci�n Type/Tipo/... del cover)
# -------------------------------------------------------------------------
class SubcatDictReq(BaseModel):
    terms: list = []


@router.get("/api/tgindex/subcat-dict")
async def get_subcat_dict():
    try:
        from .scanner import _load_subcat_dict
        return _load_subcat_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/tgindex/subcat-dict")
async def save_subcat_dict(body: SubcatDictReq, request: Request):
    try:
        from tvcat.gateway import get_db_connection as _gdb
        from tvcat.services.auth_service import get_session as _gs
        sess = _gs(request.cookies.get("tvcat_session", ""))
        if not sess or sess.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Solo admin")
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        from .scanner import _save_subcat_dict
        return _save_subcat_dict({"terms": body.terms or []})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
