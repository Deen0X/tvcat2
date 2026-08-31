"""
TVCat TGIndex — Gestión de configuración
Lee y escribe config/tvcat_tgindex_config.json
"""

import os
import json

_PLUGIN_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_PLUGIN_DIR, "..", "..", ".."))

# Sobreescribible desde run_server_android() para redirigir la config a filesDir en Android
_PROJECT_ROOT_OVERRIDE: str = ""

def _get_config_path() -> str:
    root = _PROJECT_ROOT_OVERRIDE if _PROJECT_ROOT_OVERRIDE else _PROJECT_ROOT
    return os.path.join(root, "config", "tvcat_tgindex_config.json")

USER_CONFIG_PATH = _get_config_path()


def load_user_config() -> dict:
    path = _get_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"api_id": "", "api_hash": "", "session_string": "", "channels": []}


def save_user_config(config: dict):
    try:
        path = _get_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f" [TGINDEX CONFIG] Error al guardar configuración: {e}")

