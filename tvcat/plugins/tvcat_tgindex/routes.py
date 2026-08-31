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
from .client import get_user_tg_client

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
        client = TelegramClient(StringSession(session_str), int(api_id), api_hash,
                                device_model="TVCat_TGIndex", app_version="1.0")
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return {"success": False, "error": "La cadena de sesión no es válida o ha caducado"}
            
        me = await client.get_me()
        username = me.username or f"{me.first_name} {me.last_name or ''}".strip()
        phone = me.phone or ""
        await client.disconnect()
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
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    from tvcat.gateway import get_global_setting
    api_id = get_global_setting("userbot_api_id")
    api_hash = get_global_setting("userbot_api_hash")
    session_string = get_global_setting("userbot_session_string")

    if not api_id or not api_hash or not session_string:
        return {"success": False, "error": "Credenciales no configuradas"}

    try:
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash,
                                device_model="TVCat_TGIndex", app_version="1.0")
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return {"success": False, "error": "Sesión no autorizada o caducada"}
        me = await client.get_me()
        username = me.username or f"{me.first_name} {me.last_name or ''}".strip()
        await client.disconnect()
        return {"success": True, "username": username}
    except Exception as e:
        return {"success": False, "error": str(e)}


# -------------------------------------------------------------------------
# Channels CRUD
# -------------------------------------------------------------------------
def _ensure_channel_category_column():
    """Migración: añade columna category a tvcat_scanned_channels si no existe."""
    try:
        conn = get_db_connection(system=True)
        conn.execute("ALTER TABLE tvcat_scanned_channels ADD COLUMN category TEXT")
        conn.commit()
        conn.close()
    except Exception:
        pass


@router.get("/api/user/channels")
async def list_channels():
    try:
        _ensure_channel_category_column()
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
        current_enabled = None
        if payload.id:
            row = conn.execute("SELECT last_scanned_msg_id, start_msg_id, enabled FROM tvcat_scanned_channels WHERE id = ?", (payload.id,)).fetchone()
            if row:
                current_last_scanned = row[0]
                current_start_msg_id = row[1]
                current_enabled = row[2]

        last_scanned_msg_id = max(0, start_msg_id - 1)
        if payload.id and start_msg_id == current_start_msg_id:
            last_scanned_msg_id = current_last_scanned
            
        content_type = (payload.content_type or 'media').strip()
        # Categoría: el nuevo campo `category` (combo) manda; si no viene, mapa legacy por content_type
        _category_map = {"media": "media", "ebook": "kiosko", "audiolibro": "media", "game": "game"}
        category = (payload.category or "").strip() or _category_map.get(content_type, "media")
        custom_sub = payload.custom_subcategory.strip() if payload.custom_subcategory else None
        auto_refresh = None  # Deshabilitado por ciclos de refresco
        enabled = payload.enabled if payload.enabled is not None else 1
        topic_only = (payload.topic_only or 0) and 1 or 0
        effective_topic_name = (payload.topic_name or "").strip() or None
        # Migración: columnas topic_only y topic_name
        for col in ["topic_only INTEGER DEFAULT 0", "topic_name TEXT"]:
            try: conn.execute(f"ALTER TABLE tvcat_scanned_channels ADD COLUMN {col}")
            except Exception: pass
        conn.commit()
        
        if payload.id:
            conn.execute(
                """UPDATE tvcat_scanned_channels 
                   SET channel_id = ?, display_name = ?, topology_type = ?, 
                       last_scanned_msg_id = ?, start_msg_id = ?, end_msg_id = ?, topic_id = ?, 
                       content_type = ?, category = ?, custom_subcategory = ?, auto_refresh_interval = ?,
                       telegram_account_id = ?, refresh_cycles = ?, enabled = ?, topic_only = ?, topic_name = ?
                   WHERE id = ?""",
                (channel_id, payload.display_name.strip(), payload.topology_type,
                 last_scanned_msg_id, start_msg_id or 0, end_msg_id, effective_topic_id, 
                 content_type, category, custom_sub, auto_refresh, payload.telegram_account_id,
                 payload.refresh_cycles, enabled, topic_only, effective_topic_name, payload.id),
            )
        else:
            conn.execute(
                """INSERT INTO tvcat_scanned_channels 
                   (channel_id, display_name, topology_type, last_scanned_msg_id, start_msg_id, end_msg_id, 
                    topic_id, content_type, category, custom_subcategory, auto_refresh_interval, telegram_account_id, refresh_cycles, enabled, topic_only, topic_name) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (channel_id, payload.display_name.strip(), payload.topology_type,
                 last_scanned_msg_id, start_msg_id or 0, end_msg_id, effective_topic_id, 
                 content_type, category, custom_sub, auto_refresh, payload.telegram_account_id, payload.refresh_cycles, enabled, topic_only, effective_topic_name),
            )
        new_id = payload.id or conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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
                effective_subcat = custom_sub if custom_sub else payload.display_name.strip()
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


@router.post("/api/user/channels/test")
async def test_channel_connection(payload: ChannelTestRequest):
    try:
        channel_url = payload.channel_url.strip()
        channel_id, topic_id, msg_id = parse_telegram_link(channel_url)
        
        from tvcat.gateway import get_global_setting
        api_id = get_global_setting("userbot_api_id")
        api_hash = get_global_setting("userbot_api_hash")

        if payload.telegram_account_id == -1:
            session_string = get_global_setting("userbot_session_string")
        else:
            conn = get_db_connection(system=True)
            cursor = conn.cursor()
            cursor.execute("SELECT session_string FROM tvcat_telegram_accounts WHERE id = ?", (payload.telegram_account_id,))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return {"success": False, "error": "La cuenta de Telegram seleccionada no está configurada"}
            session_string = row[0]
        
        if not api_id or not api_hash or not session_string:
            return {"success": False, "error": "api_id, api_hash o session_string no configurados en la aplicación"}
            
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash,
                                device_model="TVCat_TGIndex", app_version="1.0")
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return {"success": False, "error": "Sesión de Telegram no autorizada o caducada"}
            
        chat_entity = channel_id
        if chat_entity.replace("-100", "").isdigit():
            chat_entity = int(chat_entity)
            
        entity = await client.get_entity(chat_entity)
        title = getattr(entity, "title", "Canal de Telegram")
        await client.disconnect()
        
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
    scan_task = asyncio.create_task(run_background_scan(target_id=payload.id, mode=mode))
    scanner_status["_scan_task"] = scan_task
    return {"success": True}


@router.get("/api/user/scan/status")
async def get_scan_status():
    status = dict(scanner_status)
    status.pop("_scan_task", None)
    return status





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
    """Streaming directo desde canal personal via Userbot."""
    import traceback
    import re
    import json
    from fastapi.responses import JSONResponse

    # ── 1. Verificación de canal de escaneo habilitado (se ejecuta SIEMPRE) ─────
    # Si el canal de escaneo del que proviene este episodio está deshabilitado
    # en TGIndex, no se sirve a nadie (ni peers, ni clientes directos).
    _db_path_chk = get_plugin_db_path()
    try:
        conn_pre = sqlite3.connect(_db_path_chk)
        conn_pre.row_factory = sqlite3.Row
        cursor_pre = conn_pre.cursor()
        cursor_pre.execute("""
            SELECT u.source
            FROM unified_catalog u
            JOIN item_episodes e ON u.id = e.item_id
            WHERE e.id = ?
        """, (episode_id,))
        pre_row = cursor_pre.fetchone()
        conn_pre.close()
        if pre_row:
            source_pre = pre_row["source"] or ""
            if source_pre.startswith("scan_"):
                try:
                    scan_id_pre = int(source_pre.split("_")[1])
                except ValueError:
                    scan_id_pre = None
                if scan_id_pre is not None:
                    from tvcat.gateway import get_db_connection
                    conn_sys_pre = get_db_connection(system=True)
                    sys_row_pre = conn_sys_pre.execute(
                        "SELECT enabled FROM tvcat_scanned_channels WHERE id = ?", (scan_id_pre,)
                    ).fetchone()
                    conn_sys_pre.close()
                    if not sys_row_pre or not sys_row_pre[0]:
                        print(f" [STREAM BLOCKED] episode_id={episode_id} denegado: canal {source_pre} deshabilitado (IP: {request.client.host if request.client else '?'})")
                        return JSONResponse(
                            status_code=451,
                            content={"reason": "content_revoked", "episode_id": episode_id,
                                     "detail": "El canal de escaneo de este contenido está deshabilitado."}
                        )
    except Exception as e_pre:
        print(f" [STREAM PRE CHECK ERROR] {e_pre}")

    # ── 2. Validación de acceso federado (Peers) — solo si viene con Bridge Key ─
    bridge_key = request.headers.get("X-Bridge-Key", "")
    if bridge_key:
        from tvcat.plugins.tvcat_peers import bridge_manager as peer_mgr
        peer = peer_mgr.get_peer_by_api_key(bridge_key)
        if not peer:
            raise HTTPException(status_code=403, detail="Bridge Key no autorizada o inválida")
        
        # Si tiene la compartición desactivada
        if not peer.get("share_enabled"):
            return JSONResponse(status_code=451, content={"reason": "content_revoked", "episode_id": episode_id})

        # Comprobar si la subcategoría del ítem está compartida con este peer
        db_path = get_plugin_db_path()
        try:
            conn_chk = sqlite3.connect(db_path)
            conn_chk.row_factory = sqlite3.Row
            cursor_chk = conn_chk.cursor()
            cursor_chk.execute("""
                SELECT u.category, u.subcategory, u.source 
                FROM unified_catalog u
                JOIN item_episodes e ON u.id = e.item_id
                WHERE e.id = ?
            """, (episode_id,))
            item_row = cursor_chk.fetchone()
            conn_chk.close()
            
            if item_row:
                cat = item_row["category"] or ""
                sub = item_row["subcategory"] or ""

                # Cargar configuración compartida
                shared_cfg = peer.get("shared_config", {})
                allowed_subcats = shared_cfg.get("subcategories", [])
                allowed_cats = shared_cfg.get("categories", [])
                
                authorized = False
                if allowed_subcats:
                    subcat_path = f"{cat}/{sub}" if sub else cat
                    authorized = any(subcat_path.lower() == allowed.lower() for allowed in allowed_subcats)
                elif allowed_cats:
                    authorized = any(cat.lower() == allowed.lower() for allowed in allowed_cats)
                else:
                    # Sin filtro configurado → autorizado si share_enabled (ya verificado arriba)
                    authorized = True
                
                if not authorized:
                    logger = logging.getLogger("tvcat.peers")
                    logger.warning(f"Acceso DENEGADO a peer '{peer['name']}' para episode_id={episode_id} (cat={cat}, sub={sub})")
                    return JSONResponse(status_code=451, content={"reason": "content_revoked", "episode_id": episode_id})
        except Exception as e_chk:
            print(f" [STREAM ACC CHECK ERROR] {e_chk}")

    try:
        import os
        db_path = get_plugin_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Obtener el episodio (msg_id del video) y su item padre
        print(f" [STREAM EPISODE] Buscando episode_id={episode_id}")
        cursor.execute("""
            SELECT e.item_id, e.telegram_msg_id
            FROM item_episodes e
            WHERE e.id = ?
        """, (episode_id,))
        ep_row = cursor.fetchone()
        print(f" [STREAM EPISODE] ep_row={dict(ep_row) if ep_row else None}")
        if not ep_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Episodio no encontrado.")

        parent_item_id = ep_row["item_id"]
        msg_id = ep_row["telegram_msg_id"]
        print(f" [STREAM EPISODE] parent_item_id={parent_item_id}, msg_id={msg_id}")

        # Obtener telegram_link del item padre (tiene la entidad del canal)
        cursor.execute("SELECT telegram_link, source FROM unified_catalog WHERE id = ?", (parent_item_id,))
        uc_row = cursor.fetchone()
        print(f" [STREAM EPISODE] uc_row={dict(uc_row) if uc_row else None}")
        conn.close()

        if not uc_row:
            raise HTTPException(status_code=404, detail="Item padre no encontrado en unified_catalog.")

        telegram_link = uc_row["telegram_link"] or ""
        print(f" [STREAM EPISODE] telegram_link={telegram_link}")

        # Extraer chat_entity del telegram_link (misma lógica que Yuki)
        chat_entity = None
        if "/c/" in telegram_link:
            m = re.search(r"/c/(\d+)/", telegram_link)
            if m:
                chat_entity = int("-100" + m.group(1))
        elif "t.me/" in telegram_link:
            m = re.search(r"t\.me/([^/]+)/", telegram_link)
            if m:
                chat_entity = m.group(1)

        if not chat_entity:
            raise HTTPException(status_code=400, detail="No se pudo resolver la entidad del canal desde el enlace.")

        # Obtener el cliente de la cuenta asociada
        source = uc_row["source"] or ""
        scan_id = None
        if source.startswith("scan_"):
            try:
                scan_id = int(source.replace("scan_", ""))
            except ValueError:
                pass
                
        telegram_account_id = None
        if scan_id is not None:
            system_conn = get_db_connection(system=True)
            row = system_conn.execute("SELECT telegram_account_id FROM tvcat_scanned_channels WHERE id = ?", (scan_id,)).fetchone()
            system_conn.close()
            if row:
                telegram_account_id = row[0]
                
        if telegram_account_id is not None:
            from .scanner import get_client_for_account
            user_tg = await get_client_for_account(telegram_account_id)
        else:
            user_tg = await get_user_tg_client()

        if not user_tg:
            raise HTTPException(status_code=500, detail="TVCat_TGIndex no tiene cuenta/cliente configurado.")

        try:
            entity = await user_tg.get_entity(chat_entity)
            streaming_url = f"https://t.me/c/{str(chat_entity).replace('-100','')}/{msg_id}"
            print(f" [STREAM] Haciendo streaming desde: {streaming_url}")
            # Obtener el mensaje con caché (más fiable para canales forum)
            msgs = None
            msg = await _tgindex_get_message(user_tg, entity, msg_id)
            print(f" [STREAM] msg type={type(msg).__name__ if msg else 'None'}")
            if not msg or not msg.media:
                raise HTTPException(status_code=404, detail=f"Media no encontrado para msg_id={msg_id} en entity={chat_entity}.")
            print(f" [STREAM] media type={type(msg.media).__name__}")
            print(f" [STREAM] has_photo={hasattr(msg.media, 'photo')}, has_document={hasattr(msg.media, 'document')}")

            file_size = 0
            mime = "video/mp4"
            if hasattr(msg.media, "document"):
                doc = msg.media.document
                file_size = doc.size
                mime_original = doc.mime_type or "None"
                print(f" [STREAM EPISODE] msg_id={msg_id}, doc_id={doc.id}, mime_original={mime_original}, file_size={file_size}, dc_id={doc.dc_id}")
                if not file_size or file_size <= 0:
                    raise HTTPException(status_code=400, detail=f"Archivo multimedia vacío (file_size={file_size}).")
                mime = "video/mp4"
            else:
                raise HTTPException(status_code=400, detail=f"No es un archivo multimedia (msg_id={msg_id}, media={type(msg.media).__name__}).")

            print(f" [STREAM EPISODE] Intentando descarga con iter_download (dc_id={doc.dc_id})...")
            # TEST: descargar primeros 64 bytes con API directa
            try:
                from telethon.tl.functions.upload import GetFileRequest
                from telethon.tl.types import InputDocumentFileLocation
                from telethon.tl.types.upload import File as UploadFile, FileCdnRedirect
                test_req = await user_tg(GetFileRequest(
                    location=InputDocumentFileLocation(
                        id=doc.id, access_hash=doc.access_hash,
                        file_reference=doc.file_reference, thumb_size=""
                    ),
                    offset=0, limit=131072
                ))
                if isinstance(test_req, UploadFile):
                    print(f" [STREAM TEST] Inicio archivo (hex): {test_req.bytes[:16].hex()}")
                elif isinstance(test_req, FileCdnRedirect):
                    print(f" [STREAM TEST] CDN Redirect: dc_id={test_req.dc_id}")
            except Exception as test_err:
                print(f" [STREAM TEST] Error: {test_err}")
            
            # Leer tamaño de chunk de query string (con fallback a 1MB - max getFile de Telegram)
            try:
                q_chunk = request.query_params.get("chunk")
                pref_chunk_size = int(q_chunk) * 1024 if q_chunk else 1024 * 1024
            except:
                pref_chunk_size = 1024 * 1024

            async def sender(offset=0):
                chunk_count = 0
                total_bytes = 0
                first_bytes = None
                try:
                    async for chunk in user_tg.iter_download(msg, offset=offset, chunk_size=pref_chunk_size, dc_id=doc.dc_id):
                        chunk_count += 1
                        total_bytes += len(chunk)
                        if first_bytes is None and len(chunk) > 3:
                            first_bytes = chunk[:4].hex()
                        if chunk_count == 1:
                            print(f" [STREAM SENDER] Primer chunk: size={len(chunk)}, first_4_bytes={first_bytes}")
                        if chunk:
                            # Telethon retorna un objeto memoryview en algunas plataformas,
                            # Starlette/FastAPI requiere obligatoriamente bytes/str en su StreamingResponse
                            yield bytes(chunk)
                except Exception as dl_err:
                    print(f" [STREAM SENDER] Error descarga: {dl_err}")
                    traceback.print_exc()
                print(f" [STREAM SENDER] Total: {chunk_count} chunks, {total_bytes} bytes")

            headers = {
                "Accept-Ranges": "bytes",
                "Content-Type": mime,
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
            }
            range_hdr = request.headers.get("Range")
            if range_hdr:
                try:
                    start = int(range_hdr.replace("bytes=", "").split("-")[0])
                except:
                    start = 0
                headers["Content-Range"] = f"bytes {start}-{file_size - 1}/{file_size}"
                headers["Content-Length"] = str(file_size - start)
                return StreamingResponse(sender(start), status_code=206, headers=headers)

            headers["Content-Length"] = str(file_size)
            return StreamingResponse(sender(0), headers=headers)

        except HTTPException:
            raise
        except Exception as e_tg:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error streaming: {e_tg}")

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error BD: {e}")


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
