"""
TVCat TGIndex — Cliente Telethon del Userbot
Gestiona la sesión de Telethon para el escáner personal.
"""

import os
import sys

# Asegurar imports desde el core de TVCat
_TVCAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _TVCAT_DIR not in sys.path:
    sys.path.insert(0, _TVCAT_DIR)

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession
from .config import load_user_config

_user_tg_client = None
_client_lock = asyncio.Lock()


async def get_user_tg_client():
    """Devuelve un TelegramClient autenticado con la sesión del Userbot personal."""
    global _user_tg_client
    from tvcat.gateway import get_global_setting, get_db_connection
    api_id = get_global_setting("userbot_api_id")
    api_hash = get_global_setting("userbot_api_hash")
    session_string = get_global_setting("userbot_session_string")
    if not api_id or not api_hash or not session_string:
        try:
            conn = get_db_connection(system=True)
            # api_id/api_hash desde userbot_sessions (sesiones Telethon válidas)
            if not api_id or not api_hash:
                row = conn.execute(
                    "SELECT api_id, api_hash FROM userbot_sessions "
                    "WHERE api_id IS NOT NULL AND api_hash IS NOT NULL "
                    "AND session_string LIKE '1BJWap1w%' "
                    "ORDER BY (is_active=1) DESC, id DESC LIMIT 1"
                ).fetchone()
                if row and row[0] and row[1]:
                    if not api_id:
                        api_id = row[0]
                    if not api_hash:
                        api_hash = row[1]
            # session_string (Principal): cuenta configurada en tvcat_telegram_accounts
            if not session_string:
                acc = conn.execute(
                    "SELECT session_string FROM tvcat_telegram_accounts "
                    "WHERE session_string IS NOT NULL AND session_string != '' "
                    "ORDER BY id ASC LIMIT 1"
                ).fetchone()
                if acc and acc[0]:
                    session_string = acc[0]
            conn.close()
        except Exception:
            pass
    if not session_string or not api_id or not api_hash:
        return None
    if _user_tg_client and _user_tg_client.is_connected():
        return _user_tg_client
    async with _client_lock:
        if _user_tg_client and _user_tg_client.is_connected():
            return _user_tg_client
        try:
            client = TelegramClient(
                StringSession(session_string),
                int(api_id),
                api_hash,
                device_model="TVCat_TGIndex",
                app_version="1.0",
            )
            await client.start()
            _user_tg_client = client
            # Evitar caracteres no-ASCII para prevenir fallos de codificación de consola en Windows
            print(" [TGINDEX CLIENT] [OK] Cliente Telethon del Userbot iniciado.")
            return _user_tg_client
        except Exception as e:
            msg = str(e).encode('ascii', 'replace').decode('ascii')
            print(f" [TGINDEX CLIENT] [ERROR] Error al inicializar Telethon: {msg}")
            _user_tg_client = None
        return None


async def disconnect():
    global _user_tg_client
    if _user_tg_client and _user_tg_client.is_connected():
        await _user_tg_client.disconnect()
        _user_tg_client = None
