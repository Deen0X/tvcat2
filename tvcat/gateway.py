"""
TVCat 2 Gateway
===============
"""

import sys
import os
import json
import re
import sqlite3
import struct
import uvicorn
import asyncio
import traceback
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, Response, RedirectResponse

# Global rate limiter for Telegram API calls (JIT cover downloads)
_jit_semaphore = asyncio.Semaphore(1)
_jit_last_call = 0.0

# Thumbnail extraction (async cache)
_thumb_pending_extractions = set()
_thumb_extract_semaphore = asyncio.Semaphore(3)

def _get_jit_interval():
    val = get_global_setting("jit_cover_interval", "1.0")
    try:
        return float(val)
    except:
        return 1.0

try:
    if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

# ─── Duplicar stdout+stderr a un log en disco (para análisis) ───────────────
import time as _t
_LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
try:
    os.makedirs(_LOGS_DIR, exist_ok=True)
except Exception:
    _LOGS_DIR = os.path.dirname(os.path.abspath(__file__))


class _Tee:
    """Replica escritura a stdout/stderr originales + un archivo de log.
    El fichero se trunca (limpia) en la primera escritura de cada ejecución."""
    _truncated = False
    def __init__(self, stream, path):
        self._stream = stream
        self._init = False
        self._file = None
        self._path = path
    def _ensure(self):
        if not self._init:
            try:
                mode = "w" if not _Tee._truncated else "a"
                self._file = open(self._path, mode, encoding="utf-8", errors="replace")
                _Tee._truncated = True
            except Exception:
                self._file = None
            self._init = True
    def write(self, data):
        self._ensure()
        # si hay una línea abierta de printLog, cerrarla antes de otro write
        try:
            if globals().get("_HLS_LOG_OPEN"):
                _hls_log_finalize()
        except Exception:
            pass
        try:
            self._stream.write(data)
            self._stream.flush()
        except Exception:
            pass
        if self._file is not None:
            try:
                self._file.write(data)
                self._file.flush()
            except Exception:
                pass
        return len(data) if isinstance(data, str) else len(str(data))
    def flush(self):
        try:
            if globals().get("_HLS_LOG_OPEN"):
                _hls_log_finalize()
        except Exception:
            pass
        try:
            self._stream.flush()
        except Exception:
            pass
        if self._file is not None:
            try:
                self._file.flush()
            except Exception:
                pass
    # uvicorn/logging esperan isatty() y otros atributos del stream real
    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False
    def __getattr__(self, name):
        # delegar cualquier otro atributo (encoding, fileno, buffer, ...) al stream original
        try:
            return getattr(self._stream, name)
        except Exception:
            raise AttributeError(name)


try:
    # Log único: siempre el mismo fichero; se trunca (limpia) al iniciar cada ejecución.
    _log_path = os.path.join(_LOGS_DIR, "gateway.log")
    _real_stdout = sys.stdout if hasattr(sys.stdout, 'write') else None
    _real_stderr = sys.stderr if hasattr(sys.stderr, 'write') else None
    if _real_stdout:
        sys.stdout = _Tee(_real_stdout, _log_path)
    if _real_stderr:
        sys.stderr = _Tee(_real_stderr, _log_path)
    print(f" [LOG] Salida duplicada a: {_log_path}", flush=True)
except Exception as e:
    print(f" [LOG] No se pudo configurar log a disco: {e}", flush=True)

# --- printLog centralizado: colapso in-place en consola, definitivo en fichero ---
_HLS_LOG_LAST = None
_HLS_LOG_COUNT = 0
_HLS_LOG_OPEN = False

def _hls_log_finalize():
    global _HLS_LOG_LAST, _HLS_LOG_COUNT, _HLS_LOG_OPEN
    if not _HLS_LOG_OPEN or _HLS_LOG_LAST is None:
        return
    # cerrar línea abierta en consola
    try:
        _real_stdout.write("\n")
        _real_stdout.flush()
    except Exception:
        pass
    # volcar al fichero solo lo definitivo
    try:
        tee = sys.stdout if isinstance(sys.stdout, _Tee) else None
        fh = getattr(tee, '_file', None) if tee else None
        if fh is not None:
            if _HLS_LOG_COUNT > 1:
                fh.write(f"{_HLS_LOG_LAST} [x {_HLS_LOG_COUNT}]\n")
            else:
                fh.write(f"{_HLS_LOG_LAST}\n")
            fh.flush()
    except Exception:
        pass
    _HLS_LOG_OPEN = False

def printLog(msg):
    """Log centralizado. En consola colapsa repeticiones editando la línea con \\r;
    en fichero solo escribe líneas definitivas (con \\n)."""
    global _HLS_LOG_LAST, _HLS_LOG_COUNT, _HLS_LOG_OPEN
    line = msg.rstrip("\r\n")
    if not line:
        _hls_log_finalize()
        try:
            _real_stdout.write("\n")
            _real_stdout.flush()
        except Exception:
            pass
        try:
            tee = sys.stdout if isinstance(sys.stdout, _Tee) else None
            fh = getattr(tee, '_file', None) if tee else None
            if fh is not None:
                fh.write("\n")
                fh.flush()
        except Exception:
            pass
        _HLS_LOG_LAST = None
        _HLS_LOG_COUNT = 0
        _HLS_LOG_OPEN = False
        return
    if line == _HLS_LOG_LAST and _HLS_LOG_OPEN:
        _HLS_LOG_COUNT += 1
        # reescribir la misma línea con contador
        try:
            _real_stdout.write(f"\r{line} [x {_HLS_LOG_COUNT}]\033[K")
            _real_stdout.flush()
        except Exception:
            pass
        # fichero aún no se escribe
        return
    # línea distinta: finalizar anterior
    _hls_log_finalize()
    _HLS_LOG_LAST = line
    _HLS_LOG_COUNT = 1
    _HLS_LOG_OPEN = True
    try:
        _real_stdout.write(line)
        _real_stdout.flush()
    except Exception:
        pass
    # fichero: aún pendiente hasta que se sepa si se repite

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

base_path = os.environ.get("TVCAT_BASE_PATH", "").rstrip("/")
CORE_DIR = os.path.join(BASE_DIR, "core")
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
DB_PATH = os.path.join(BASE_DIR, "data", "tvcat.db")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "tvcat_config.json")
__version__ = "2.0.0"

from services.translate_service import xTranslate, load_translations
load_translations()

from plugin_loader import PluginLoader
_plugin_loader = PluginLoader(plugins_dir=PLUGINS_DIR)

# --- Shims legacy ---
_GLOBAL_STREAM_SEMAPHORE = None
_PLUGIN_REFRESHERS = {}
# Estado de la reconstrucción asíncrona de la caché central (arranque)
_rebuild_state = {"running": False, "done": False, "error": None}

def register_plugin_refresher(name, func=None, status_func=None, **kwargs):
    _PLUGIN_REFRESHERS[name] = func or kwargs.get("func")
def get_db_connection(item_id=None, system=False):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "data", "tvcat.db"), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
def get_enabled_plugin_dbs():
    return [os.path.join(d["_dir"], "data", "tvcat.db") for n,d in _plugin_loader.registry.items() if d.get("enabled") and d.get("_dir")]
def get_enabled_plugin_dbs_with_names():
    return [(os.path.join(d["_dir"], "data", "tvcat.db"), n) for n,d in _plugin_loader.registry.items() if d.get("enabled") and d.get("_dir")]
def is_plugin_enabled(name):
    return _plugin_loader.is_enabled(name)
def get_plugin_db_path(name):
    d = _plugin_loader.registry.get(name)
    return os.path.join(d["_dir"], "data", "tvcat.db") if d and d.get("_dir") else ""
def get_global_setting(key, default=None):
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


@asynccontextmanager
async def lifespan(app_instance):
    print(f" [TVCAT2] Iniciando TVCat 2 v{__version__}")
    print(f" [TVCAT2] Base path: '{base_path}'")
    _plugin_loader.scan()
    _plugin_loader.register_routers(app_instance)
    _plugin_loader.register_static(app_instance, base_path)
    core_static = os.path.join(CORE_DIR, "static")
    if os.path.isdir(core_static):
        app_instance.mount(f"{base_path}/static", StaticFiles(directory=core_static), name="static")
    from services.catalog_service import init_db, rebuild_cache
    init_db()
    _hls_cache_init_db()
    # Reconstrucción asíncrona de la caché central (no bloquea el arranque).
    # Se regeneran las export tables de los plugins y se repobla la central.
    # Se ejecuta en un hilo para no bloquear el event loop (SQLite síncrono).
    async def _background_rebuild():
        try:
            _rebuild_state["running"] = True
            _rebuild_state["done"] = False
            def _work():
                _plugin_loader.sync_all()
                rebuild_cache(_plugin_loader)
            await asyncio.to_thread(_work)
            _rebuild_state["done"] = True
            print(" [TVCAT2] Reconstrucción de caché central completada (fondo)")
        except Exception as e:
            _rebuild_state["error"] = str(e)
            print(f" [TVCAT2] Error en reconstrucción de caché (fondo): {e}")
        finally:
            _rebuild_state["running"] = False
    asyncio.create_task(_background_rebuild())
    # Iniciar servicio de Telegram
    from services.telegram_service import get_telegram_service
    asyncio.create_task(get_telegram_service().start())
    print(f" [TVCAT2] Listo. Plugins cargados: {len(_plugin_loader.registry)}")
    yield
    print(" [TVCAT2] Apagando...")
    from services.telegram_service import get_telegram_service
    await get_telegram_service().stop()
    from services.userbot_service import disconnect_all
    await disconnect_all()

app = FastAPI(title="TVCat 2", root_path=base_path, lifespan=lifespan)

def api_url(path):
    return f"{base_path}{path}"


@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    """Evita que navegadores antiguos (Smart TVs) congelen CSS/JS/HTML con caché caducado."""
    path = request.url.path
    response = await call_next(request)
    # Excluir streaming, covers e installer (binarios grandes / Range requests / FBI)
    if "/api/stream" not in path and "/api/cover" not in path and "/api/installer" not in path and "/api/qr" not in path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# --- Static SPA ---
@app.get(api_url("/"))
async def serve_index():
    return FileResponse(os.path.join(CORE_DIR, "index.html"))
@app.get(api_url("/login"))
async def serve_login():
    return FileResponse(os.path.join(CORE_DIR, "login.html"))
@app.get(api_url("/player"))
async def serve_player():
    return FileResponse(os.path.join(CORE_DIR, "player.html"))
@app.get(api_url("/sw-player-pro.js"))
async def serve_pro_sw():
    _sw = os.path.join(os.path.dirname(__file__), "plugins", "tvcat_player_pro", "static", "player_pro_sw.js")
    if os.path.exists(_sw):
        return FileResponse(_sw, headers={"Service-Worker-Allowed": "/", "Content-Type": "application/javascript", "Cache-Control": "no-cache, no-store, must-revalidate"})
    return Response(status_code=404)


# --- API: Server ---
@app.get(api_url("/api/server/info"))
async def server_info():
    return {"name": "TVCat 2", "version": __version__, "base_path": base_path, "plugins_count": len(_plugin_loader.registry)}

@app.get(api_url("/api/plugins"))
async def get_plugins():
    return {"plugins": _plugin_loader.get_frontend_manifest()}

@app.post(api_url("/api/plugins/toggle"))
async def toggle_plugin(request: Request):
    body = await request.json()
    name = body.get("name")
    if not name or name not in _plugin_loader.registry:
        raise HTTPException(404)
    force = body.get("force")
    if force is not None:
        _plugin_loader.set_enabled(name, force)
        new_state = force
    else:
        new_state = _plugin_loader.toggle(name)
    if _plugin_loader.registry[name].get("type") == "source":
        from services.catalog_service import rebuild_cache
        rebuild_cache(_plugin_loader)
    return {"success": True, "name": name, "enabled": new_state}

@app.get(api_url("/api/plugins/order"))
async def get_plugins_order():
    order_path = os.path.join(BASE_DIR, "data", "plugins_order.json")
    if os.path.exists(order_path):
        with open(order_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"order": []}

@app.post(api_url("/api/plugins/order"))
async def set_plugins_order(request: Request):
    body = await request.json()
    order = body.get("order", [])
    order_path = os.path.join(BASE_DIR, "data", "plugins_order.json")
    os.makedirs(os.path.dirname(order_path), exist_ok=True)
    with open(order_path, "w", encoding="utf-8") as f:
        json.dump({"order": order}, f)
    return {"success": True}

@app.get(api_url("/api/plugins/status"))
async def plugins_status():
    return {"plugins": _plugin_loader.get_all()}

@app.post(api_url("/api/cache/refresh"))
async def cache_refresh(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin":
        raise HTTPException(403)
    body = await request.json()
    plugin_name = body.get("plugin", "")
    if not plugin_name:
        # Refresh todos los plugins
        from services.catalog_service import rebuild_cache
        rebuild_cache(_plugin_loader)
        return {"success": True, "plugin": "all"}
    from services.catalog_service import sync_plugin_cache
    result = sync_plugin_cache(_plugin_loader, plugin_name)
    return result


# --- API: Auth ---
@app.post(api_url("/api/auth/login"))
async def auth_login(request: Request):
    from services.auth_service import login
    body = await request.json()
    result = login(body.get("username",""), body.get("password",""))
    if not result:
        raise HTTPException(401, detail="Credenciales inválidas")
    resp = JSONResponse({"success": True, "token": result["token"], "user": {"username": result["username"], "role": result["role"]}})
    resp.set_cookie("tvcat_session", result["token"], httponly=True, max_age=315360000, path="/")
    return resp


# ─── Login con Google (opcional, activado por config) ─────────────
def _google_creds() -> tuple:
    from services.catalog_service import get_conn
    conn = get_conn()
    def g(k):
        r = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (k,)).fetchone()
        return (r[0] if r else "") or ""
    cid, csec = g("google_client_id"), g("google_client_secret")
    redir = g("google_redirect_uri")
    conn.close()
    return cid, csec, redir


def _google_redirect_uri(request: Request) -> str:
    """URI de redirección de Google. Si el admin definió una fija (google_redirect_uri),
    se usa esa (permite puerto estable). Si no, se calcula de la request actual."""
    cid, csec, redir = _google_creds()
    if redir:
        return redir
    return str(request.base_url).rstrip("/") + api_url("/api/auth/google/callback")


@app.post(api_url("/api/auth/google/config"))
async def google_config_set(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin":
        raise HTTPException(403)
    body = await request.json()
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("google_client_id", (body.get("client_id") or "").strip()))
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("google_client_secret", (body.get("client_secret") or "").strip()))
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("google_redirect_uri", (body.get("redirect_uri") or "").strip()))
    conn.commit(); conn.close()
    return {"ok": True}


@app.get(api_url("/api/auth/google/config"))
async def google_config_get(request: Request):
    cid, csec, redir = _google_creds()
    return {"enabled": bool(cid and csec), "redirect_uri": redir or _google_redirect_uri(request)}


@app.get(api_url("/api/auth/google/start"))
async def google_start(request: Request):
    """Redirige directamente a la pantalla de selección de cuenta de Google.
    Al autorizar, Google vuelve a /api/auth/google/callback con un code."""
    import urllib.parse
    cid, csec, _redir = _google_creds()
    if not cid or not csec:
        raise HTTPException(400, detail="Login con Google no configurado")
    action = request.query_params.get("action", "login")  # login | link
    # redirect_uri apunta al propio TVCat (fijo si el admin lo definió, para puerto estable)
    redirect_uri = _google_redirect_uri(request)
    # state = acción (login o link) para saber qué hacer al volver
    params = urllib.parse.urlencode({
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": action,
    })
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return RedirectResponse(url)


@app.get(api_url("/api/auth/google/callback"))
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Vuelta de Google con el code. Intercambia, obtiene el email y hace login (o asocia)."""
    import urllib.parse, requests as _r, base64, json as _json
    if error:
        # Usuario canceló o error: redirigir al login
        return RedirectResponse(api_url("/login") + "?g_error=" + urllib.parse.quote(error))
    cid, csec, _redir = _google_creds()
    if not cid or not csec:
        return RedirectResponse(api_url("/login") + "?g_error=no_config")
    if not code:
        return RedirectResponse(api_url("/login") + "?g_error=no_code")

    redirect_uri = _google_redirect_uri(request)
    try:
        tok = _r.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": cid,
            "client_secret": csec,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=15).json()
    except Exception as e:
        return RedirectResponse(api_url("/login") + "?g_error=" + urllib.parse.quote(str(e)))

    if "error" in tok:
        return RedirectResponse(api_url("/login") + "?g_error=" + urllib.parse.quote(tok.get("error_description", tok["error"])))

    # Obtener email del id_token
    email = ""
    id_token = tok.get("id_token", "")
    if id_token:
        parts = id_token.split(".")
        if len(parts) >= 2:
            try:
                payload = parts[1]
                payload += "=" * (-len(payload) % 4)
                claims = _json.loads(base64.urlsafe_b64decode(payload))
                email = claims.get("email", "")
            except Exception:
                pass
    if not email:
        try:
            ui = _r.get("https://www.googleapis.com/oauth2/v3/userinfo",
                        headers={"Authorization": f"Bearer {tok.get('access_token','')}"}, timeout=15)
            email = ui.json().get("email", "")
        except Exception:
            pass
    if not email:
        return RedirectResponse(api_url("/login") + "?g_error=no_email")

    from services.auth_service import get_session, login_with_google, link_google_email
    if state == "link":
        session = get_session(request.cookies.get("tvcat_session",""))
        if not session:
            return RedirectResponse(api_url("/login") + "?g_error=not_logged")
        if link_google_email(session["user_id"], email):
            return RedirectResponse(api_url("/") + "?google_linked=1")
        return RedirectResponse(api_url("/") + "?google_linked=exists")
    else:
        result = login_with_google(email)
        if not result:
            return RedirectResponse(api_url("/login") + "?g_error=" + urllib.parse.quote(f"No hay ningún usuario TVCat asociado a {email}"))
        resp = RedirectResponse(api_url("/"))
        resp.set_cookie("tvcat_session", result["token"], httponly=True, max_age=315360000, path="/")
        return resp


@app.post(api_url("/api/auth/google/unlink"))
async def google_unlink(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session:
        raise HTTPException(401)
    from services.auth_service import link_google_email
    link_google_email(session["user_id"], "")
    return {"success": True}


@app.post(api_url("/api/auth/google/link-email"))
async def google_link_email(request: Request):
    """Asocia un correo Google manualmente (escrito por el usuario) a su cuenta TVCat."""
    from services.auth_service import get_session, link_google_email
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session:
        raise HTTPException(401)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(400, detail="Correo no válido")
    if link_google_email(session["user_id"], email):
        return {"success": True, "email": email}
    raise HTTPException(400, detail="Ese correo ya está asociado a otro usuario de TVCat")


# ─── Enriquecedor de contenidos (CORE) ─────────────────────────────
@app.post(api_url("/api/enrich/search"))
async def enrich_search(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s:
        raise HTTPException(401)
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return {"candidates": [], "has_more": False, "configured": False, "threshold": 0.95}
    from services import enrich_service
    return await enrich_service.search(query, body.get("category", ""), body.get("subcategory", ""))


@app.post(api_url("/api/enrich/details"))
async def enrich_details(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s:
        raise HTTPException(401)
    body = await request.json()
    from services import enrich_service
    details = await enrich_service.get_details(
        body.get("provider", ""), body.get("id", ""),
        body.get("category", ""), body.get("subcategory", ""),
        body.get("media_type", ""))
    return {"details": details}


@app.get(api_url("/api/enrich/config"))
async def enrich_config_get(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s:
        raise HTTPException(401)
    from services import enrich_service
    return enrich_service.get_config()


@app.post(api_url("/api/enrich/config"))
async def enrich_config_set(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin":
        raise HTTPException(403)
    body = await request.json()
    from services import enrich_service
    return enrich_service.save_config(
        credentials=body.get("credentials"),
        templates=body.get("templates"),
        threshold=body.get("threshold"),
    )


# ─── TransferService (cola de subida/bajada, depuración/programático) ───
@app.get(api_url("/api/transfer/queue"))
async def transfer_queue(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session", ""))
    if not s:
        raise HTTPException(401)
    from services import transfer_service
    return {"jobs": transfer_service.list_jobs()}


@app.get(api_url("/api/transfer/status/{job_id}"))
async def transfer_status(job_id: str, request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session", ""))
    if not s:
        raise HTTPException(401)
    from services import transfer_service
    return await transfer_service.get_status(job_id)


@app.post(api_url("/api/transfer/upload"))
async def transfer_upload(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session", ""))
    if not s:
        raise HTTPException(401)
    body = await request.json()
    chat = (body.get("chat") or "").strip()
    if not chat:
        return {"ok": False, "error": "chat requerido"}
    file_name = body.get("file_name") or "file.bin"
    caption = body.get("caption") or ""
    payload = body.get("payload") or ""
    if not payload:
        return {"ok": False, "error": "payload requerido (ruta o base64)"}
    if isinstance(payload, str) and not os.path.isfile(payload):
        try:
            payload = bytes.fromhex(payload)  # también admite hex
        except Exception:
            pass
    from services import transfer_service
    job = await transfer_service.enqueue_upload(chat, payload, file_name=file_name, caption=caption,
                                                persist=bool(body.get("persist")), _kind="api")
    return {"ok": True, "job_id": job["id"]}


@app.post(api_url("/api/transfer/download"))
async def transfer_download(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session", ""))
    if not s:
        raise HTTPException(401)
    body = await request.json()
    chat = (body.get("chat") or "").strip()
    msg_id = body.get("msg_id")
    if not chat or not msg_id:
        return {"ok": False, "error": "chat y msg_id requeridos"}
    from services import transfer_service
    job = await transfer_service.enqueue_download(chat, int(msg_id), dest_path=body.get("dest_path"),
                                                  persist=bool(body.get("persist")), _kind="api")
    return {"ok": True, "job_id": job["id"]}


# ─── Login QR — Diseño A (autorizar dispositivo desde el móvil) ───
@app.post(api_url("/api/auth/qr/request"))
async def qr_auth_request():
    """La TV/dispositivo pide un request_id y genera un QR con ?auth={id}.
    El móvil escanea, hace login y autoriza; la TV hace polling del estado."""
    import secrets, time
    from services.catalog_service import get_conn
    request_id = secrets.token_urlsafe(12)
    conn = get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS tvcat_qr_auth (request_id TEXT PRIMARY KEY, user_id INTEGER, status TEXT DEFAULT 'pending', created INTEGER)")
    conn.execute("DELETE FROM tvcat_qr_auth WHERE created < ?", (int(time.time()) - 600,))
    conn.execute("INSERT OR REPLACE INTO tvcat_qr_auth (request_id, user_id, status, created) VALUES (?,?,?,?)",
                 (request_id, None, "pending", int(time.time())))
    conn.commit(); conn.close()
    return {"request_id": request_id}


@app.get(api_url("/api/auth/qr/status"))
async def qr_auth_status(request: Request):
    request_id = request.query_params.get("request_id", "")
    if not request_id:
        raise HTTPException(400)
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT user_id, status FROM tvcat_qr_auth WHERE request_id=?", (request_id,)).fetchone()
    conn.close()
    if not row:
        return {"status": "expired"}
    return {"status": row["status"], "authorized": row["status"] == "authorized"}


@app.post(api_url("/api/auth/qr/authorize"))
async def qr_auth_authorize(request: Request):
    """El móvil valida credenciales y autoriza el dispositivo que mostró el QR."""
    from services.auth_service import login
    body = await request.json()
    request_id = (body.get("request_id") or "").strip()
    result = login(body.get("username",""), body.get("password",""))
    if not result:
        raise HTTPException(401, detail="Credenciales inválidas")
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT status FROM tvcat_qr_auth WHERE request_id=?", (request_id,)).fetchone()
    if not row or row["status"] != "pending":
        conn.close()
        raise HTTPException(400, detail="Código QR inválido o caducado")
    conn.execute("UPDATE tvcat_qr_auth SET user_id=?, status='authorized' WHERE request_id=?", (result["user_id"], request_id))
    conn.commit(); conn.close()
    return {"success": True, "username": result["username"]}


@app.get(api_url("/api/auth/qr/device"))
async def qr_auth_device_login(request: Request):
    """La TV hace polling y, cuando el request_id queda autorizado, obtiene su sesión."""
    request_id = request.query_params.get("request_id", "")
    if not request_id:
        raise HTTPException(400)
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT user_id, status FROM tvcat_qr_auth WHERE request_id=?", (request_id,)).fetchone()
    conn.close()
    if not row or row["status"] != "authorized" or not row["user_id"]:
        raise HTTPException(401, detail="No autorizado todavía")
    # Crear sesión para el user_id autorizado
    from services.catalog_service import get_conn as _ac
    import secrets
    ac = _ac()
    profile_id = 0
    u = ac.execute("SELECT role, profile_id FROM tvcat_users WHERE id=?", (row["user_id"],)).fetchone()
    if u:
        profile_id = u["profile_id"] or 0
        if not profile_id:
            p = ac.execute("SELECT id FROM tvcat_profiles WHERE name=?", ("admin" if u["role"]=="admin" else "usuario normal")).fetchone()
            profile_id = p[0] if p else 0
    token = secrets.token_hex(32)
    ac.execute("INSERT INTO tvcat_sessions (user_id, token, profile_id) VALUES (?,?,?)", (row["user_id"], token, profile_id))
    ac.commit()
    u2 = ac.execute("SELECT username, role FROM tvcat_users WHERE id=?", (row["user_id"],)).fetchone()
    ac.close()
    # Marcar el request como usado
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM tvcat_qr_auth WHERE request_id=?", (request_id,))
    conn.commit(); conn.close()
    resp = JSONResponse({"success": True, "token": token, "username": u2["username"] if u2 else ""})
    resp.set_cookie("tvcat_session", token, httponly=True, max_age=315360000, path="/")
    return resp


@app.post(api_url("/api/auth/logout"))
async def auth_logout(request: Request):
    from services.auth_service import logout
    token = request.cookies.get("tvcat_session", "")
    if token:
        logout(token)
    resp = JSONResponse({"success": True})
    resp.delete_cookie("tvcat_session")
    return resp

@app.get(api_url("/api/auth/me"))
async def auth_me(request: Request):
    from services.auth_service import get_session
    token = request.cookies.get("tvcat_session", "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        return {"logged_in": False}
    session = get_session(token)
    if not session:
        return {"logged_in": False}
    profile_id = session.get("profile_id")
    profile_name = ""
    if profile_id:
        try:
            from services.catalog_service import get_conn
            pconn = get_conn()
            prow = pconn.execute("SELECT name FROM tvcat_profiles WHERE id=?", (profile_id,)).fetchone()
            profile_name = prow["name"] if prow else ""
            pconn.close()
        except Exception:
            pass
    return {"logged_in": True, "username": session["username"], "role": session["role"],
            "profile_id": profile_id, "profile_name": profile_name,
            "google_email": session.get("google_email", "")}

@app.post(api_url("/api/auth/change-password"))
async def auth_change_password(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session:
        raise HTTPException(401)
    body = await request.json()
    from services.catalog_service import get_conn
    conn = get_conn()
    user = conn.execute("SELECT id FROM tvcat_users WHERE id=? AND password=?", (session["user_id"], body.get("current",""))).fetchone()
    if not user:
        conn.close()
        raise HTTPException(400, detail="Contraseña actual incorrecta")
    conn.execute("UPDATE tvcat_users SET password=? WHERE id=?", (body.get("new_password",""), session["user_id"]))
    conn.commit()
    conn.close()
    return {"success": True}


# --- API: Catalog ---
@app.get(api_url("/api/catalog/tree"))
async def get_catalog_tree():
    from services.catalog_service import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT source, category, subcategory
        FROM unified_catalog
        WHERE source IS NOT NULL AND source != ''
        ORDER BY source, category, subcategory
    """).fetchall()
    conn.close()
    tree = {}
    for r in rows:
        src = r["source"] or "unknown"
        cat = r["category"] or "unknown"
        sub = r["subcategory"] or ""
        if src not in tree: tree[src] = {}
        if cat not in tree[src]: tree[src][cat] = []
        if sub and sub not in tree[src][cat]: tree[src][cat].append(sub)
    result = []
    for src in sorted(tree.keys()):
        cats = []
        for cat in sorted(tree[src].keys()):
            cats.append({"name": cat, "subcategories": tree[src][cat]})
        result.append({"source": src, "categories": cats})
    return {"tree": result}

@app.get(api_url("/api/catalog/continue"))
async def catalog_continue(request: Request):
    from services.favorites_service import get_continue_watching
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    return {"items": get_continue_watching(session.get("profile_id") or session["user_id"])}

@app.get(api_url("/api/catalog/completed"))
async def catalog_completed(request: Request):
    from services.favorites_service import get_completed
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    return {"items": get_completed(session.get("profile_id") or session["user_id"])}

@app.get(api_url("/api/catalog/visibility"))
async def get_visibility(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    from services.catalog_service import get_conn
    row = get_conn().execute("SELECT value FROM tvcat_settings WHERE key=?", (f"visibility_{session['user_id']}",)).fetchone()
    if row:
        try: return json.loads(row["value"])
        except: pass
    return {"categories": {}, "plugins": {}}

@app.post(api_url("/api/catalog/visibility"))
async def set_visibility(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", (f"visibility_{session['user_id']}", json.dumps(await request.json())))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get(api_url("/api/catalog/{category}"))
async def get_catalog(category: str, request: Request, search: str = "", limit: int = 200, fields: Optional[str] = None, year_from: str = "", year_to: str = "", genres: str = ""):
    from services.auth_service import get_session
    from services.catalog_service import get_random_items, get_conn
    s = get_session(request.cookies.get("tvcat_session",""))
    user_id = s.get("user_id") if s else None
    profile_id = s.get("profile_id") or user_id
    search_fields = [f.strip() for f in fields.split(",") if f.strip()] if fields is not None else None
    yf = int(year_from) if year_from else None
    yt = int(year_to) if year_to else None
    exclude_genres = [g.strip().lower() for g in genres.split(",") if g.strip()] if genres else []
    
    # Para favoritos, consultar directamente la tabla de favoritos
    if category == 'favorites' and profile_id:
        conn = get_conn()
        try:
            fav_rows = conn.execute("""
                SELECT uc.* FROM unified_catalog uc
                JOIN tvcat_favorites f ON f.item_id = uc.item_id
                WHERE f.profile_id = ?
                ORDER BY uc.title ASC
            """, (profile_id,)).fetchall()
            items = [dict(r) for r in fav_rows]
            for item in items:
                item["fav"] = True
            conn.close()
            return {"items": items, "count": len(items)}
        except Exception as e:
            conn.close()
            return {"items": [], "count": 0}
    
    result = get_random_items(category=category, search=search, limit=min(limit, 200), user_id=user_id, search_fields=search_fields, year_from=yf, year_to=yt, exclude_genres=exclude_genres)
    # Añadir campo fav a cada item según los favoritos del usuario
    if profile_id and isinstance(result, dict) and "items" in result:
        try:
            conn = get_conn()
            fav_rows = conn.execute("SELECT item_id FROM tvcat_favorites WHERE profile_id=?", (profile_id,)).fetchall()
            fav_set = {str(r["item_id"]) for r in fav_rows}
            conn.close()
            for item in result["items"]:
                item["fav"] = str(item.get("item_id", "")) in fav_set
            # Si la categoría es 'favorites', filtrar solo favoritos
            if category == 'favorites':
                result["items"] = [it for it in result["items"] if it.get("fav")]
                result["count"] = len(result["items"])
        except:
            pass
    return result

@app.get(api_url("/api/categories"))
async def get_categories():
    from services.catalog_service import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT category FROM unified_catalog WHERE category IS NOT NULL AND category!='' ORDER BY category").fetchall()
    conn.close()
    return {"categories": [r["category"] for r in rows]}

@app.get(api_url("/api/categories/all"))
async def get_categories_all():
    """Devuelve categorías y, por cada categoría, sus subcategorías, desde el catálogo central.
    Usado por los combos de scan items (TGIndex) con opción de añadir manualmente."""
    from services.catalog_service import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT category, subcategory
        FROM unified_catalog
        WHERE category IS NOT NULL AND category != ''
        ORDER BY category, subcategory
    """).fetchall()
    conn.close()
    categories = []
    sub_map = {}
    seen_cat = set()
    for r in rows:
        cat = r["category"]
        if cat not in seen_cat:
            seen_cat.add(cat)
            categories.append(cat)
        sub = r["subcategory"]
        if sub:
            sub_map.setdefault(cat, [])
            if sub not in sub_map[cat]:
                sub_map[cat].append(sub)
    return {"categories": categories, "subcategories": sub_map}

@app.get(api_url("/api/genres"))
async def get_genres():
    from services.catalog_service import get_conn, get_tag_dictionary
    conn = get_conn()
    raw = set()
    row_nogenre = 0
    try:
        # Leer de la columna normalizada `genres` (rápido); fallback al JSON antiguo.
        for row in conn.execute("SELECT genres, metadata_json FROM unified_catalog").fetchall():
            gcol = row["genres"] if "genres" in row.keys() else ""
            if isinstance(gcol, str) and gcol:
                for p in gcol.split(","):
                    p = p.strip().lower()
                    if p: raw.add(p)
            else:
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                    for g in [meta.get("info_messages",""), meta.get("genres","")]:
                        if isinstance(g, str):
                            for p in g.split(","):
                                p = p.strip().lower()
                                if p: raw.add(p)
                        elif isinstance(g, list):
                            for item in g:
                                if item: raw.add(str(item).strip().lower())
                except Exception: pass
        row_nogenre = conn.execute("SELECT COUNT(*) FROM unified_catalog WHERE COALESCE(genres,'')=''").fetchone()[0]
    except Exception: pass
    conn.close()

    # Construir términos agrupados por diccionario
    terms = get_tag_dictionary()
    covered = set()
    for t in terms:
        covered.update(t["tags"])

    # Términos del diccionario pero solo si tienen géneros reales en el catálogo
    ordered = []
    for t in terms:
        tags = [g for g in t["tags"] if g in raw]
        if tags:
            ordered.append({"term": t["term"], "tags": tags})

    # Géneros crudos sin término asignado -> término propio
    standalone = sorted(raw - covered)
    for g in standalone:
        ordered.append({"term": g, "tags": [g]})

    # Término virtual: títulos sin género (no excluible con un LIKE normal)
    if row_nogenre > 0:
        ordered.append({"term": "Sin género", "tags": ["__no_genre__"], "no_genre": True})

    return {"genres": sorted(raw), "terms": ordered}

def _sort_variants(variants: list) -> list:
    """Ordena variantes: primero temporadas numeradas, luego especiales/OVAs."""
    def _weight(v):
        label = (v.get("season_display") or v.get("title") or "").lower()
        is_special = 1 if any(x in label for x in ("ova","pelicula","movie","especial","special")) else 0
        import re
        m = re.search(r"(\d+)", label)
        num = int(m.group(1)) if m else (999 if is_special else 500)
        return (is_special, num, label)
    seen = set()
    result = []
    for v in variants:
        key = v.get("id", "")
        if key in seen:
            continue
        seen.add(key)
        result.append(v)
    result.sort(key=_weight)
    return result

_SEASON_PATTERNS_V = [
    (r"(?i)\s*[-:.]?\s*season\s+(\d+)\s*$", None),
    (r"(?i)\s*[-:.]?\s*temporada\s+(\d+)\s*$", None),
    (r"(?i)\s*[-:.]?\s*temp\.?\s+(\d+)\s*$", None),
    (r"(?i)\s*[-:.]?\s*(\d+)(?:nd|rd|th|st)\s+season\s*$", "season_display"),
    (r"(?i)\s*[-:.]?\s*s(\d+)\s*$", None),
    (r"(?i)\s*[-:.]?\s+(\d{1,2})\s*$", None),
]


def _deduce_season_number_v(text):
    """Copia directa de scanner._deduce_season_number."""
    if not text:
        return None
    for pat, _ in _SEASON_PATTERNS_V:
        m = re.search(pat, text)
        if m:
            num = int(m.group(1))
            if pat == _SEASON_PATTERNS_V[-1][0] and num > 50:
                continue
            return str(num)
    return None


def _variant_label(title: str, group_title: str) -> str:
    """Replica _extract_group_and_season de tvcat1 usando title+group_title (sin cover text).
    Regla 2 del scanner: resta group_title del title para obtener remainder y deduce season."""
    if not group_title:
        return title
    gt_lower = group_title.lower().rstrip(".")
    t_lower = title.lower()
    remainder = title
    if t_lower.startswith(gt_lower):
        remainder = title[len(gt_lower):].strip().lstrip("-:.,; ")
    if not remainder:
        return "Temporada 1"
    season_number = _deduce_season_number_v(remainder) or _deduce_season_number_v(title)
    if season_number:
        return f"Temporada {season_number}"
    # "Season X rest" embedded (no al final, _deduce_season_number no lo captura)
    m = re.search(r"(?i)(?:season|temporada|temp)\s+(\d+)\s*\.?\s*(.*)", remainder)
    if m:
        rest = m.group(2).strip()
        if rest:
            return f"Temporada {m.group(1)}. {rest}"
        return f"Temporada {m.group(1)}"
    # Keywords especiales
    m = re.search(r"(?i)(movie|pel[íi]cula|ova|especial|special)", remainder)
    if m:
        return f"Temporada {m.group(1).title()}"
    return remainder.strip()


def _get_variants_and_rep(conn, item_id: str):
    """Retorna (variants: list, representative_id: str)."""
    row = conn.execute("SELECT group_title_flat, subcategory FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
    if not row:
        return [], item_id
    gtf = row["group_title_flat"]
    subcat = row["subcategory"] or ""
    if not gtf:
        return [], item_id
    rows = conn.execute(
        "SELECT id, item_id, title, group_title FROM unified_catalog WHERE group_title_flat=? AND COALESCE(subcategory,'')=? ORDER BY id ASC",
        (gtf, subcat)
    ).fetchall()
    variants = []
    rep_id = item_id
    min_id = None
    for r in rows:
        vid = r["item_id"]
        sd = _variant_label(r["title"], r["group_title"] or "")
        v = {"id": vid, "title": r["title"], "season_display": sd}
        variants.append(v)
        if r["id"] < (min_id or float('inf')):
            min_id = r["id"]
            rep_id = vid
    return _sort_variants(variants), rep_id

# --- Caché de mensajes para streaming (evita 1 get_messages por cada chunk HTTP) ---
_stream_msg_cache = {}
_stream_msg_cache_order = []

async def _stream_get_message(ubot, chat_entity, msg_id):
    """Obtiene el mensaje con caché en memoria (TTL 15 min, máx 100 entradas)."""
    import time as _time
    key = (chat_entity, int(msg_id))
    now = _time.time()
    cached = _stream_msg_cache.get(key)
    if cached and (now - cached[0]) < 900:
        return cached[1]
    msg = await ubot.get_messages(chat_entity, ids=int(msg_id))
    if msg is not None:
        _stream_msg_cache[key] = (now, msg)
        _stream_msg_cache_order.append(key)
        while len(_stream_msg_cache_order) > 100:
            old = _stream_msg_cache_order.pop(0)
            _stream_msg_cache.pop(old, None)
    return msg


async def _do_stream(ubot, chat_entity, msg_id, range_header=None, tag="STREAM", chunk_size=1024 * 1024):
    """Core streaming logic: fetch message, detect media, stream with proper headers."""
    from fastapi.responses import StreamingResponse
    try:
        # NOTA: no se resuelve la entidad aquí (get_entity = round-trip de red a Telegram en
        # cada request). iter_download usa directamente el mensaje (msg), que ya contiene el
        # documento con su access_hash/location. get_messages ya resuelve la entidad internamente.
        msg = await _stream_get_message(ubot, chat_entity, msg_id)
        if not msg:
            print(f" [{tag}] ERROR: Media no encontrado (entity={chat_entity}, msg={msg_id})")
            raise HTTPException(404, "Media no encontrado en Telegram.")

        file_size = 0
        mime = "video/mp4"
        dc_id = None

        media_type_name = type(msg.media).__name__ if hasattr(msg, 'media') and msg.media else 'None'
        print(f" [{tag}] msg type={type(msg).__name__}, msg.media type={media_type_name}")

        doc = None
        if hasattr(msg, 'document') and msg.document:
            doc = msg.document
            print(f" [{tag}] Fuente: msg.document (Pyrogram)")
        elif hasattr(msg, 'media') and msg.media:
            if hasattr(msg.media, 'document') and msg.media.document:
                doc = msg.media.document
                print(f" [{tag}] Fuente: msg.media.document")
            elif hasattr(msg.media, 'video') and msg.media.video:
                vid = msg.media.video
                file_size = getattr(vid, 'size', 0)
                mime = getattr(vid, 'mime_type', None) or "video/mp4"
                print(f" [{tag}] Media detectado (video): mime={mime}, size={file_size} bytes")
            elif hasattr(msg.media, 'webpage') and msg.media.webpage:
                wp = msg.media.webpage
                if hasattr(wp, 'document') and wp.document:
                    doc = wp.document
                    print(f" [{tag}] Fuente: msg.media.webpage.document")
            else:
                for attr_name in ['document', 'video', 'photo', 'audio']:
                    candidate = getattr(msg.media, attr_name, None)
                    if candidate and hasattr(candidate, 'size'):
                        doc = candidate
                        print(f" [{tag}] Fuente: msg.media.{attr_name} (fallback)")
                        break

        if doc:
            file_size = getattr(doc, 'size', 0) or getattr(doc, 'file_size', 0)
            mime = getattr(doc, 'mime_type', None) or "video/mp4"
            dc_id = getattr(doc, 'dc_id', None)
            print(f" [{tag}] Documento detectado: mime={mime}, size={file_size} bytes, dc_id={dc_id}")
        else:
            print(f" [{tag}] WARNING: No se pudo detectar documento, usando defaults mime={mime}, size={file_size}")

        if file_size == 0:
            print(f" [{tag}] WARNING: file_size=0")

        if "x-matroska" in mime or "octet-stream" in mime:
            mime = "video/mp4"

        total_sent = 0

        async def file_sender(offset):
            nonlocal total_sent
            try:
                async for chunk in ubot.iter_download(msg, offset=offset, chunk_size=chunk_size, dc_id=dc_id):
                    if chunk:
                        yield chunk
                        total_sent += len(chunk)
                        if total_sent % (512 * 1024) < 128 * 1024:
                            print(f" [{tag}] Enviados {total_sent} bytes hasta ahora...")
                print(f" [{tag}] Streaming completado: total {total_sent} bytes")
            except Exception as ex:
                traceback.print_exc()
                print(f" [{tag}] Error en file_sender: {ex}")

        headers = {
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
            "Content-Type": mime
        }

        if file_size > 0 and range_header:
            try:
                range_val = range_header.replace("bytes=", "").split("-")
                start = int(range_val[0])
                end = int(range_val[1]) if len(range_val) > 1 and range_val[1] else file_size - 1
            except:
                start = 0
                end = file_size - 1
            if end >= file_size:
                end = file_size - 1
            content_length = end - start + 1
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            headers["Content-Length"] = str(content_length)
            print(f" [{tag}] Respondiendo 206 Partial: start={start}, end={end}, content_length={content_length}")
            async def bounded_sender(offset, limit):
                nonlocal total_sent
                remaining = limit
                try:
                    async for chunk in ubot.iter_download(msg, offset=offset, chunk_size=chunk_size, dc_id=dc_id):
                        if chunk:
                            if remaining <= 0:
                                break
                            send = chunk[:remaining] if len(chunk) > remaining else chunk
                            yield send
                            total_sent += len(send)
                            remaining -= len(send)
                            if total_sent % (512 * 1024) < 128 * 1024:
                                print(f" [{tag}] Enviados {total_sent} bytes hasta ahora...")
                    print(f" [{tag}] Streaming completado: total {total_sent} bytes")
                except Exception as ex:
                    traceback.print_exc()
                    print(f" [{tag}] Error en bounded_sender: {ex}")
            return StreamingResponse(bounded_sender(start, content_length), status_code=206, headers=headers)

        if file_size > 0:
            headers["Content-Length"] = str(file_size)
            print(f" [{tag}] Respondiendo 200 OK: content_length={file_size}")
        else:
            print(f" [{tag}] Respondiendo 200 OK: sin Content-Length, chunked transfer")
        return StreamingResponse(file_sender(0), headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        print(f" [{tag}] Error: {e}")
        raise HTTPException(500, str(e))


@app.get(api_url("/api/stream/direct"))
async def stream_direct(chat_id: str = "", msg_id: str = "", request: Request = None):
    if not chat_id or not msg_id:
        raise HTTPException(400, "chat_id y msg_id requeridos")
    from services.userbot_service import get_active_client
    ubot = await get_active_client()
    if not ubot:
        raise HTTPException(400, "No hay sesiones de userbot disponibles")
    try:
        cid = chat_id
        if cid.isdigit() and not cid.startswith("-"):
            cid = "-100" + cid
        chat_entity = int(cid)
    except ValueError:
        chat_entity = chat_id
    range_header = request.headers.get("Range") if request else None
    pref_chunk = 1024 * 1024
    if request:
        try:
            q_chunk = request.query_params.get("chunk")
            if q_chunk:
                pref_chunk = int(q_chunk) * 1024
        except:
            pass
    print(f" [STREAM] Request: chat_id={cid}, msg_id={msg_id}, Range={range_header}, chunk={pref_chunk}")
    return await _do_stream(ubot, chat_entity, int(msg_id), range_header, tag="STREAM", chunk_size=pref_chunk)


@app.get(api_url("/api/stream/episode/{episode_id}"))
async def stream_by_episode_id(episode_id: int, request: Request = None):
    """Stream video por episode_id (estilo tvcat1). Busca telegram_msg_id en BD."""
    from services.catalog_service import get_conn
    conn = get_conn()
    ep_row = conn.execute(
        "SELECT ie.*, i.telegram_link as item_link, i.item_id, i.id as cat_int_id "
        "FROM item_episodes ie "
        "JOIN unified_catalog i ON i.id = CAST(ie.item_id AS INTEGER) OR i.item_id = ie.item_id "
        "WHERE ie.id=?", (episode_id,)).fetchone()
    ep_link = ""
    msg_id = None
    if ep_row:
        ep_link = ep_row["telegram_link"] or ep_row.get("item_link", "") or ""
        msg_id = ep_row["telegram_msg_id"]
    # Si no se encontró en main DB o no tiene msg_id, buscar en plugin DBs
    if not msg_id:
        ep_plugin = _find_episode_by_id_in_plugin_dbs(episode_id)
        if ep_plugin:
            ep_link = ep_plugin.get("telegram_link") or ep_plugin.get("item_link") or ""
            msg_id = ep_plugin.get("telegram_msg_id")
    conn.close()
    if not msg_id:
        raise HTTPException(404, "Fuente de video no disponible para este episodio")
    if not ep_link:
        raise HTTPException(400, "telegram_link no disponible para este episodio")
    m = re.search(r"t\.me/c/(\d+)/(\d+)", ep_link)
    if m:
        chat_id = m.group(1)
    else:
        raise HTTPException(400, "No se pudo determinar el chat_id del telegram_link")
    cid = chat_id
    if cid.isdigit() and not cid.startswith("-"):
        cid = "-100" + cid
    try:
        chat_entity = int(cid)
    except ValueError:
        chat_entity = chat_id
    from services.userbot_service import get_active_client
    ubot = await get_active_client()
    if not ubot:
        raise HTTPException(400, "No hay sesiones de userbot disponibles")
    range_header = request.headers.get("Range") if request else None
    # Obtener chunk size preferido del cliente (query param ?chunk=128); default 1MB (max getFile de Telegram)
    pref_chunk = 1024 * 1024
    if request:
        try:
            q_chunk = request.query_params.get("chunk")
            if q_chunk:
                pref_chunk = int(q_chunk) * 1024
        except:
            pass
    print(f" [STREAM EPISODE] episode_id={episode_id}, chat_id={cid}, msg_id={msg_id}, Range={range_header}, chunk={pref_chunk}")
    return await _do_stream(ubot, chat_entity, msg_id, range_header, tag="STREAM_EPISODE", chunk_size=pref_chunk)


@app.get(api_url("/api/stream/video/{video_src:path}"))
async def stream_by_video_src(video_src: str):
    """Stream video usando video_src (item_id:ep_id)."""
    parts = video_src.split(":")
    if len(parts) < 2:
        raise HTTPException(400, "video_src debe ser item_id:ep_id")
    item_id_part = parts[0]
    ep_id_part = int(parts[1])
    from services.catalog_service import get_conn
    conn = get_conn()
    # Obtener item de catálogo primero (para tener tanto item_id TEXT como id INTEGER)
    cat_row = conn.execute("SELECT id, item_id, telegram_link, telegram_msg_id FROM unified_catalog WHERE item_id=?", (item_id_part,)).fetchone()
    if not cat_row:
        conn.close()
        raise HTTPException(404, "Item no encontrado")
    int_id_str = str(cat_row["id"])
    # Buscar episodio por item_id TEXT o id INTEGER (bug scanner: usa cat_id INTEGER)
    ep_row = conn.execute(
        "SELECT * FROM item_episodes WHERE (item_id=? OR item_id=?) AND id=?",
        (item_id_part, int_id_str, ep_id_part)).fetchone()
    if ep_row:
        ep_link = ep_row["telegram_link"] or cat_row["telegram_link"] or ""
        msg_id = ep_row["telegram_msg_id"]
    else:
        # Fallback: buscar primer episodio real (para pseudoEp con id=0)
        first_ep = conn.execute(
            "SELECT telegram_link, telegram_msg_id FROM item_episodes WHERE (item_id=? OR item_id=?) ORDER BY id ASC LIMIT 1",
            (item_id_part, int_id_str)).fetchone()
        if first_ep and first_ep["telegram_msg_id"]:
            ep_link = first_ep["telegram_link"] or cat_row["telegram_link"] or ""
            msg_id = first_ep["telegram_msg_id"]
        else:
            # Sin episodios: usar datos del item (cover)
            ep_link = cat_row["telegram_link"] or ""
            msg_id = cat_row["telegram_msg_id"]
    conn.close()
    if not msg_id:
        raise HTTPException(404, "Fuente de video no disponible")
    m = re.search(r"t\.me/c/(\d+)/(\d+)", ep_link)
    if m:
        chat_id = m.group(1)
    else:
        raise HTTPException(400, "No se pudo determinar el chat_id")
    cid = chat_id
    if cid.isdigit() and not cid.startswith("-"):
        cid = "-100" + cid
    try:
        chat_entity = int(cid)
    except ValueError:
        chat_entity = chat_id

    from services.userbot_service import get_active_client
    ubot = await get_active_client()
    if not ubot:
        raise HTTPException(400, "No hay sesiones de userbot disponibles")

    print(f" [STREAM VIDEO] chat_id={cid}, msg_id={msg_id}")
    return await _do_stream(ubot, chat_entity, msg_id, tag="STREAM_VIDEO")


# ═════════════════════════════════════════════════════════════════════════════
# HLS ENDPOINTS — Streaming HLS nativo para SmartTV antigua
# Descarga bytes de Telegram por segmento, remux a .ts con ffmpeg.
# ═════════════════════════════════════════════════════════════════════════════

_HLS_SEG_CACHE = {}   # episode_key -> {file_size, duration, dc_id, msg_obj, chat_entity}
_HLS_SEG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "hls_segments")
os.makedirs(_HLS_SEG_DIR, exist_ok=True)
_HLS_SEG_DURATION = 6
# Prefetch secuencial: 1 sola descarga Telegram a la vez (Telethon no tolera iter_download concurrente)
_HLS_DOWNLOAD_LOCK = asyncio.Lock()          # LOCK GLOBAL: serializa TODAS las descargas Telegram (HLS + thumbs + covers)
_HLS_PREFETCH_AHEAD_DEFAULT = 2          # nº de segmentos a precargar por delante
_HLS_PREFETCH_QUEUE = {}                 # episode_key -> set de segmentos en cola/siendo precargados

# ═════════════════════════════════════════════════════════════════════════════
# HLS CACHE SPARSE (arquitectura §20.7) — fichero local por episodio + bitmap
# ═════════════════════════════════════════════════════════════════════════════
_HLS_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
os.makedirs(_HLS_CACHE_DIR, exist_ok=True)
_HLS_BLOCK_SIZE = 512 * 1024            # bloque de relleno del bitmap (== límite GetFileRequest)
_HLS_BUFFER_BYTES = 8 * 1024 * 1024     # bytes por delante del punto de reproducción (configurable)
                                        # ~16s de vídeo a 2.5Mbps; la descarga va mucho más rápido
_HLS_RATE_LIMIT_PER_MIN = 90            # token bucket: nº max de GetFile (512KB) por minuto (anti-429)
                                        # 90×512KB = 46MB/min = 0.77MB/s ≈ 1.4x la reproducción media (0.54MB/s)
_HLS_CACHE_LIMIT_BYTES = 5 * 1024 * 1024 * 1024  # límite total de /data/cache (LRU)

# Estado en memoria por episode_key (complementa el bitmap persistido en BD):
#   cache_files  -> {episode_key: {path, file_size, total_blocks, cursor_block, bitmap(set), users:set}}
#   download_task-> {episode_key: asyncio.Task} (worker de descarga por episodio)
_HLS_SPARSE = {}       # episode_key -> dict de estado del fichero sparse
_HLS_WORKER_TASK = None  # worker global único de descarga
_HLS_WORKER_QUEUE = []   # lista de episode_key activos (round-robin)
_HLS_WORKER_STOP = False


# ═════════════════════════════════════════════════════════════════════════════
# HLS CACHE SPARSE — capa de BD (tabla hls_cache) + bitmap + fichero
# ═════════════════════════════════════════════════════════════════════════════

def _hls_cache_init_db():
    """Crea la tabla hls_cache en la BD central si no existe."""
    from services.catalog_service import get_conn
    conn = get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hls_cache (
                episode_key TEXT PRIMARY KEY,
                file_path TEXT,
                file_size INTEGER DEFAULT 0,
                total_blocks INTEGER DEFAULT 0,
                bitmap TEXT DEFAULT '',
                complete INTEGER DEFAULT 0,
                last_access REAL DEFAULT 0,
                created REAL DEFAULT 0
            )
        """)
        # Migración: añadir columna complete si no existe (BD previa)
        try:
            conn.execute("ALTER TABLE hls_cache ADD COLUMN complete INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


def _hls_cache_row(episode_key):
    """Lee la fila hls_cache de un episodio (o None)."""
    from services.catalog_service import get_conn
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM hls_cache WHERE episode_key=?", (episode_key,)).fetchone()
    finally:
        conn.close()


def _hls_cache_save(episode_key, file_path, file_size, total_blocks, bitmap, last_access=None, complete=0):
    """Upsert de la fila hls_cache."""
    import time as _t2
    from services.catalog_service import get_conn
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO hls_cache
            (episode_key, file_path, file_size, total_blocks, bitmap, complete, last_access, created)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created FROM hls_cache WHERE episode_key=?), ?))
        """, (episode_key, file_path, file_size, total_blocks, bitmap, complete,
              last_access if last_access is not None else _t2.time(),
              episode_key, _t2.time()))
        conn.commit()
    finally:
        conn.close()


def _hls_cache_touch(episode_key):
    """Actualiza last_access (detección de 'en uso')."""
    import time as _t2
    from services.catalog_service import get_conn
    conn = get_conn()
    try:
        conn.execute("UPDATE hls_cache SET last_access=? WHERE episode_key=?", (_t2.time(), episode_key))
        conn.commit()
    finally:
        conn.close()


def _hls_bitmap_new(total_blocks):
    """Crea un bitmap (set de índices rellenados) vacío. Retorna set."""
    return set()


def _hls_bitmap_serialize(bitmap):
    """Serializa el set de bloques a string (lista separada por comas)."""
    if not bitmap:
        return ""
    return ",".join(str(i) for i in sorted(bitmap))


def _hls_bitmap_deserialize(s):
    """Deserializa el string a set de enteros."""
    if not s:
        return set()
    try:
        return set(int(x) for x in s.split(",") if x.strip() != "")
    except Exception:
        return set()


def _hls_bitmap_islands(bitmap, total_blocks):
    """Convierte el set de bloques descargados en una lista de islas contiguas
    [[start, end), ...] (end exclusivo) para pintar el mapa real de descarga."""
    if not bitmap:
        return []
    blocks = sorted(bitmap)
    islands = []
    start = prev = blocks[0]
    for b in blocks[1:]:
        if b == prev + 1:
            prev = b
            continue
        islands.append([start, prev + 1])
        start = prev = b
    islands.append([start, prev + 1])
    return islands


def _hls_cache_cleanup(current_episode_key=None):
    """Limpieza LRU al iniciar reproducción. Respeta el episodio actual (current_episode_key)
    y los que tengan last_access reciente (en uso). Borra el más antiguo si se supera el límite."""
    import time as _t2, os as _os
    from services.catalog_service import get_conn
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM hls_cache ORDER BY last_access ASC").fetchall()
    finally:
        conn.close()
    now = _t2.time()
    total_size = sum(r["file_size"] for r in rows)
    for r in rows:
        ek = r["episode_key"]
        if ek == current_episode_key:
            continue
        in_use = (now - (r["last_access"] or 0)) < 60
        if in_use:
            continue
        if total_size <= _HLS_CACHE_LIMIT_BYTES:
            break
        # borrar fichero + fila
        try:
            if r["file_path"] and _os.path.isfile(r["file_path"]):
                _os.remove(r["file_path"])
        except Exception:
            pass
        from services.catalog_service import get_conn as _gc
        c = _gc()
        try:
            c.execute("DELETE FROM hls_cache WHERE episode_key=?", (ek,))
            c.commit()
        finally:
            c.close()
        total_size -= r["file_size"]
        _HLS_SPARSE.pop(ek, None)
        printLog(f" [HLS-CACHE] LRU: eliminado {ek} ({r['file_size']/1024/1024:.0f}MB)")
    _hls_cache_init_db()


# ═════════════════════════════════════════════════════════════════════════════
# MP4 BOX PARSING — Búsqueda de moov atom para obtener duración
# ═════════════════════════════════════════════════════════════════════════════

def _parse_mp4_boxes(data, offset=0):
    """Parsea boxes MP4 desde datos binarios. Retorna lista de (box_type, box_offset, box_size)."""
    boxes = []
    pos = offset
    end = len(data)
    while pos + 8 <= end:
        size = struct.unpack('>I', data[pos:pos+4])[0]
        box_type = data[pos+4:pos+8].decode('ascii', errors='replace')
        if size < 8:
            break
        boxes.append((box_type, pos, size))
        pos += size
    return boxes

def _find_moov_in_data(data):
    """Busca box 'moov' en datos binarios. Retorna (offset, size) o (None, 0)."""
    boxes = _parse_mp4_boxes(data)
    for box_type, box_offset, box_size in boxes:
        if box_type == 'moov':
            return box_offset, box_size
    return None, 0

def _extract_duration_from_mvhd(data, moov_offset, moov_size):
    """Extrae duración del box mvhd dentro del moov. Retorna duración en segundos o 0."""
    try:
        moov_end = moov_offset + moov_size
        print(f" [HLS-MVHD] data_len={len(data)}, moov_offset={moov_offset}, moov_size={moov_size}, moov_end={moov_end}")
        if moov_end > len(data):
            print(f" [HLS-MVHD] WARN: moov_end > data_len, intentando con datos disponibles")
            moov_end = len(data)
        moov_data = data[moov_offset:moov_end]
        # Saltar header del moov (8 bytes: [size][moov]) para parsear sub-boxes
        inner_boxes = _parse_mp4_boxes(moov_data, 8)
        print(f" [HLS-MVHD] Sub-boxes dentro de moov: {[(bt, bo, bs) for bt, bo, bs in inner_boxes[:15]]}")
        for box_type, box_offset, box_size in inner_boxes:
            if box_type == 'mvhd':
                mvhd = moov_data[box_offset:box_offset + box_size]
                print(f" [HLS-MVHD] mvhd encontrado: offset={box_offset}, size={box_size}, data_len={len(mvhd)}")
                if len(mvhd) < 28:
                    print(f" [HLS-MVHD] mvhd muy pequeño ({len(mvhd)} bytes), saltando")
                    continue
                version = mvhd[8]
                print(f" [HLS-MVHD] version={version}")
                if version == 0:
                    timescale = struct.unpack('>I', mvhd[20:24])[0]
                    duration = struct.unpack('>I', mvhd[24:28])[0]
                elif version == 1:
                    timescale = struct.unpack('>I', mvhd[28:32])[0]
                    duration = struct.unpack('>Q', mvhd[32:40])[0]
                else:
                    print(f" [HLS-MVHD] Version desconocida: {version}")
                    continue
                print(f" [HLS-MVHD] timescale={timescale}, duration={duration}")
                if timescale > 0:
                    result = duration / timescale
                    print(f" [HLS-MVHD] Duración calculada: {result:.1f}s")
                    return result
        print(f" [HLS-MVHD] No se encontró box mvhd en moov")
    except Exception as e:
        print(f" [HLS-MVHD] Excepción: {e}")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# SAMPLE TABLE MP4 — Extracción de tablas de muestras para descarga por-slice
# Permite aterrizar en el keyframe exacto (stss) en vez de descarga acumulativa.
# ═════════════════════════════════════════════════════════════════════════════

def _mp4_find_box(data, box_type, offset=8):
    """Busca un sub-box de tipo box_type dentro de data. Retorna (offset_local, size) o (None, 0)."""
    for bt, bo, bs in _parse_mp4_boxes(data, offset):
        if bt == box_type:
            return bo, bs
    return None, 0


def _mp4_parse_sample_table(moov_bytes, track_index=0):
    """Extrae la sample table (stts/stsc/stsz/stco/co64/stss) del track indicado.
    Retorna dict con timescale, delta, total_samples, sizes, chunk_offsets,
    stsc_entries, sync_samples, y tiempos/offsets precomputados. O None si no se puede."""
    try:
        # Recorrer moov -> trak (elegir el indicado, default video = primer trak con vmhd)
        moov_boxes = _parse_mp4_boxes(moov_bytes, 8)
        traks = [b for b in moov_boxes if b[0] == 'trak']
        if not traks:
            return None
        if track_index >= len(traks):
            track_index = 0
        trak_bo, trak_bs = traks[track_index][1], traks[track_index][2]
        trak = moov_bytes[trak_bo:trak_bo + trak_bs]

        mdia_bo, mdia_bs = _mp4_find_box(trak, 'mdia')
        if not mdia_bo:
            return None
        mdia = trak[mdia_bo:mdia_bo + mdia_bs]

        # mdhd: version + timescale + duration
        mdhd_bo, mdhd_bs = _mp4_find_box(mdia, 'mdhd')
        if not mdhd_bo:
            return None
        mver = mdia[mdhd_bo + 8]
        if mver == 0:
            timescale = struct.unpack('>I', mdia[mdhd_bo + 20:mdhd_bo + 24])[0]
            mdur = struct.unpack('>I', mdia[mdhd_bo + 24:mdhd_bo + 28])[0]
        elif mver == 1:
            timescale = struct.unpack('>I', mdia[mdhd_bo + 28:mdhd_bo + 32])[0]
            mdur = struct.unpack('>Q', mdia[mdhd_bo + 32:mdhd_bo + 40])[0]
        else:
            return None
        if timescale <= 0:
            return None

        minf_bo, minf_bs = _mp4_find_box(mdia, 'minf')
        if not minf_bo:
            return None
        minf = mdia[minf_bo:minf_bo + minf_bs]
        stbl_bo, stbl_bs = _mp4_find_box(minf, 'stbl')
        if not stbl_bo:
            return None
        stbl = minf[stbl_bo:stbl_bo + stbl_bs]

        def rf(typ):
            b, s = _mp4_find_box(stbl, typ)
            return stbl[b:b + s] if b else b""

        stts = rf('stts'); stsc = rf('stsc'); stsz = rf('stsz'); stco = rf('stco'); co64 = rf('co64'); stss = rf('stss')
        if not stts or not stsc or not stsz or (not stco and not co64):
            return None

        # stts: acumular (sample_count, sample_delta) -> lista de (start_offset, count, delta_ts, pos)
        ec = struct.unpack('>I', stts[12:16])[0]
        stts_entries = []
        pos = 0
        for i in range(ec):
            off = 16 + i * 8
            cnt = struct.unpack('>I', stts[off:off + 4])[0]
            delta = struct.unpack('>I', stts[off + 4:off + 8])[0]
            stts_entries.append((pos, cnt, delta))
            pos += cnt
        total_samples = pos
        if total_samples == 0:
            return None

        # stsz: sizes por sample (unified o tabla)
        smpl_size = struct.unpack('>I', stsz[12:16])[0]
        szcnt = struct.unpack('>I', stsz[16:20])[0]
        sizes = []
        for i in range(szcnt):
            if smpl_size == 0 and 20 + i * 4 + 4 <= len(stsz):
                sizes.append(struct.unpack('>I', stsz[20 + i * 4:24 + i * 4])[0])
            else:
                sizes.append(smpl_size)

        # stco/co64: chunk offsets
        chunk_offsets = []
        if stco:
            e = struct.unpack('>I', stco[12:16])[0]
            chunk_offsets = [struct.unpack('>I', stco[16 + i * 4:20 + i * 4])[0] for i in range(e)]
        elif co64:
            e = struct.unpack('>I', co64[12:16])[0]
            chunk_offsets = [struct.unpack('>Q', co64[16 + i * 8:24 + i * 8])[0] for i in range(e)]
        if not chunk_offsets:
            return None

        # _helper para listar pistas (usado por extractor de tracks)
        # stsc: (first_chunk, samples_per_chunk)
        e3 = struct.unpack('>I', stsc[12:16])[0]
        stsc_entries = []
        for i in range(e3):
            off = 16 + i * 12
            fc = struct.unpack('>I', stsc[off:off + 4])[0]
            spc = struct.unpack('>I', stsc[off + 4:off + 8])[0]
            stsc_entries.append((fc, spc))

        # stss: keyframe sample numbers
        sync_samples = []
        if stss:
            e4 = struct.unpack('>I', stss[12:16])[0]
            sync_samples = sorted(struct.unpack('>I', stss[16 + i * 4:20 + i * 4])[0] for i in range(e4))

        # Precomputar chunk_sample_start: para cada chunk, el primer sample (1-based)
        chunk_sample_start = {}
        sample = 1
        total_chunks = len(chunk_offsets)
        chunk_idx = 0
        samples_per_chunk = 1
        for c in range(1, total_chunks + 1):
            # actualizar samples_per_chunk al entrar en un grupo de stsc
            while chunk_idx < len(stsc_entries) and stsc_entries[chunk_idx][0] <= c:
                samples_per_chunk = stsc_entries[chunk_idx][1]
                chunk_idx += 1
            chunk_sample_start[c] = sample
            sample += samples_per_chunk

        return {
            "timescale": timescale, "total_samples": total_samples,
            "stts_entries": stts_entries, "sizes": sizes,
            "chunk_offsets": chunk_offsets, "stsc_entries": stsc_entries,
            "sync_samples": sync_samples, "chunk_sample_start": chunk_sample_start,
            "video_duration": mdur / timescale if timescale else 0,
        }
    except Exception as e:
        print(f" [HLS-STBL] Error parseando sample table: {e}")
        return None


def _mp4_time_to_sample_index(st, seconds):
    """Convierte segundos → índice de sample (1-based). Asume deltas de stts."""
    ts = st["timescale"]
    if ts <= 0:
        return 1
    target_tick = int(seconds * ts)
    # Recorrer stts_entries acumulando
    used = 0
    for (start, count, delta) in st["stts_entries"]:
        if delta <= 0:
            continue
        # Los samples de esta entrada abarcan ticks [used_start, used_start + count*delta)
        entry_dur = count * delta
        if target_tick < used + entry_dur:
            offset_in_entry = (target_tick - used) // delta
            idx = start + offset_in_entry + 1  # 1-based
            return max(1, min(idx, st["total_samples"]))
        used += entry_dur
    return st["total_samples"]


def _mp4_keyframe_for_sample(st, sample_idx):
    """Devuelve el sample keyframe (stss) más cercano <= sample_idx. Si no hay stss, devuelve sample_idx."""
    sync = st.get("sync_samples")
    if not sync:
        return max(1, sample_idx)
    import bisect
    i = bisect.bisect_right(sync, sample_idx) - 1
    if i < 0:
        return sync[0] if sync else 1
    return sync[i]


def _hls_extract_tracks(moov_bytes):
    """Extrae pistas de audio/subs del moov: lista de {idx, type, lang, codec}."""
    tracks = []
    try:
        from collections import defaultdict
        moov_boxes = _parse_mp4_boxes(moov_bytes, 8)
        idx = 0
        for bt, bo, bs in moov_boxes:
            if bt != 'trak':
                continue
            trak = moov_bytes[bo:bo+bs]
            hdlr_bo, hdlr_bs = _mp4_find_box(trak, 'hdlr')
            mdia_bo, mdia_bs = _mp4_find_box(trak, 'mdia')
            if not mdia_bo:
                idx += 1
                continue
            mdia = trak[mdia_bo:mdia_bo+mdia_bs]
            # hdlr dentro de mdia/minf
            hdlr = None
            for search in [mdia, trak]:
                hb, _ = _mp4_find_box(search, 'hdlr')
                if hb:
                    try:
                        hdlr = search[hb+16:hb+20].decode('ascii', errors='ignore')
                    except Exception:
                        hdlr = None
                    break
            # buscar stsd para codec
            codec = ""
            try:
                minf_bo, _ = _mp4_find_box(mdia, 'minf')
                if minf_bo:
                    minf = mdia[minf_bo:]
                    stbl_bo, _ = _mp4_find_box(minf, 'stbl')
                    if stbl_bo:
                        stbl = minf[stbl_bo:]
                        stsd_bo, stsd_bs = _mp4_find_box(stbl, 'stsd')
                        if stsd_bo and stsd_bs > 16:
                            # primer entry tras stsd header: size+type
                            codec = stbl[stsd_bo+12:stsd_bo+16].decode('ascii', errors='ignore') if stsd_bo+16 <= len(stbl) else ""
            except Exception:
                pass
            # idioma desde mdhd
            lang = "und"
            try:
                mdhd_bo, _ = _mp4_find_box(mdia, 'mdhd')
                if mdhd_bo:
                    # mdhd: ... language 2 bytes en offset 20 (version 0) o 32 (version 1)
                    v = mdia[mdhd_bo+8] if mdhd_bo+8 < len(mdia) else 0
                    off = mdhd_bo+24 if v==1 else mdhd_bo+20
                    if off+2 <= len(mdia):
                        lang_code = struct.unpack('>H', mdia[off:off+2])[0]
                        if lang_code != 0:
                            c1 = chr(((lang_code >> 10) & 0x1F) + 0x60)
                            c2 = chr(((lang_code >> 5) & 0x1F) + 0x60)
                            c3 = chr((lang_code & 0x1F) + 0x60)
                            lang = c1+c2+c3
            except Exception:
                pass
            typ = "unknown"
            if hdlr == "vide":
                typ = "video"
            elif hdlr == "soun":
                typ = "audio"
            elif hdlr in ("sbtl", "subt", "text"):
                typ = "subs"
            tracks.append({"idx": idx, "stream_index": idx, "type": typ, "lang": lang, "codec": codec, "hdlr": hdlr or ""})
            idx += 1
    except Exception:
        pass
    return tracks


def _mp4_sample_to_byte_offset(st, sample_idx):
    """Devuelve el byte offset absoluto (en el fichero original) donde empieza el sample."""
    csm = st.get("chunk_sample_start")
    if not csm:
        return None
    import bisect
    # Buscar sobre los STARTS (monótono), NO sobre chunk ids.
    chunk_ids = sorted(csm.keys())
    starts = [csm[c] for c in chunk_ids]
    idx = bisect.bisect_right(starts, sample_idx) - 1
    if idx < 0:
        idx = 0
    chunk = chunk_ids[idx]
    start_s = csm[chunk]
    off = st["chunk_offsets"][chunk - 1]
    sizes = st["sizes"]
    # sumar tamaños de samples desde el inicio del chunk hasta sample_idx-1
    for s in range(start_s - 1, sample_idx - 1):
        if s < len(sizes):
            off += sizes[s]
    return off


def _mp4_resolve_slice(st, seconds, slice_seconds=6.0, file_size=None):
    """Resuelve el rango de bytes [start,end] para un clip de slice_seconds en seconds.
    start aterriza en el CHUNK con el keyframe (stss). Alinea start a 1KB y end a 1KB para GetFileRequest."""
    sample_idx = _mp4_time_to_sample_index(st, seconds)
    kf = _mp4_keyframe_for_sample(st, sample_idx)
    # Inicio = offset del chunk que contiene el keyframe (NO el offset del keyframe)
    csm = st.get("chunk_sample_start")
    if not csm:
        return None, None
    import bisect
    chunk_ids = sorted(csm.keys())
    starts = [csm[c] for c in chunk_ids]
    idx = bisect.bisect_right(starts, kf) - 1
    if idx < 0:
        idx = 0
    chunk = chunk_ids[idx]
    start = st["chunk_offsets"][chunk - 1]
    # Final: byte del sample al final del clip (no keyframe necesario)
    end_idx = _mp4_time_to_sample_index(st, seconds + slice_seconds)
    end = _mp4_sample_to_byte_offset(st, end_idx)
    if end is None:
        end = start
    # Sumar el tamaño del sample final para incluir su último byte
    sizes = st["sizes"]
    if end_idx - 1 < len(sizes):
        end += sizes[end_idx - 1]
    # Margen de seguridad (64KB) para cubrir el final del último sample
    end += 64 * 1024
    if file_size:
        end = min(end, file_size - 1)
    # Alinear a múltiplo de 1KB (GetFileRequest exige offset%1024==0 y limit%4096==0)
    start = (start // 1024) * 1024
    end = ((end // 1024) + 1) * 1024
    if file_size:
        end = min(end, file_size)
    return start, end


async def _hls_resolve_duration(ubot, msg, dc_id, file_size, episode_key):
    """Resuelve duración: para MP4 busca moov; para AVI/MKV usa ffprobe. Retorna segundos o 0."""
    # Contenedor genérico (AVI/MKV): no buscar moov, usar ffprobe sobre cabecera
    if not _hls_is_mp4(msg):
        print(f" [HLS] Contenedor no-MP4 detectado, probando ffprobe para duración...")
        try:
            tmp = await _hls_download_range(ubot, msg, dc_id, 0, min(2*1024*1024, file_size))
            if tmp:
                try:
                    import asyncio as _aio2
                    from services import stream_packager as _sp
                    loop = asyncio.get_event_loop()
                    dur = await loop.run_in_executor(None, _sp.get_duration, tmp)
                    if dur and dur > 0:
                        # Validar duración: si es sospechosamente corta para un fichero grande, ignorar
                        if file_size > 100*1024*1024 and dur < 60:
                            print(f" [HLS] Duración ffprobe genérico sospechosa ({dur:.1f}s para {file_size} bytes), ignorando")
                        else:
                            print(f" [HLS] Duración ffprobe genérico: {dur:.1f}s")
                            return float(dur)
                finally:
                    try: import os as _os2; _os2.remove(tmp)
                    except: pass
        except Exception as e:
            print(f" [HLS] ffprobe genérico falló: {e}")
        # fallback: estimar por tamaño (bitrate medio ~1.5 Mbps para AVI)
        est = file_size / (1500*1024/8)  # ~1.5 Mbps
        if est > 0:
            print(f" [HLS] Duración estimada genérica: {est:.0f}s")
            return float(est)
        return 0
    CHUNK = 1 * 1024 * 1024  # 1 MB

    # FASE 1: Leer cabecera para determinar estructura (ftyp + mdat size → moov position)
    print(f" [HLS] Leyendo cabecera MP4 para encontrar moov...")
    tmp_hdr = await _hls_download_range(ubot, msg, dc_id, 0, min(CHUNK, file_size))
    if tmp_hdr:
        try:
            with open(tmp_hdr, 'rb') as f:
                data_hdr = f.read()
            # Parsear boxes desde el inicio
            boxes = _parse_mp4_boxes(data_hdr, 0)
            moov_off = None
            moov_size = 0
            mdat_size = 0
            for box_type, box_offset, box_size in boxes:
                if box_type == 'moov':
                    moov_off = box_offset
                    moov_size = box_size
                elif box_type == 'mdat':
                    mdat_size = box_size
            if moov_off is not None:
                # Moov encontrado al inicio (faststart)
                print(f" [HLS] Moov al inicio: offset={moov_off}, size={moov_size}")
                if moov_off + moov_size <= len(data_hdr):
                    dur = _extract_duration_from_mvhd(data_hdr, moov_off, moov_size)
                    if dur > 0:
                        print(f" [HLS] Duración desde moov (inicio): {dur:.1f}s")
                        return dur
                # Moov se extiende, descargar más
                needed = moov_off + moov_size - len(data_hdr)
                if needed > 0:
                    extra = await _hls_download_range(ubot, msg, dc_id, len(data_hdr), needed)
                    if extra:
                        try:
                            with open(extra, 'rb') as f:
                                data_extra = f.read()
                            full = data_hdr + data_extra
                            dur = _extract_duration_from_mvhd(full, moov_off, moov_size)
                            if dur > 0:
                                print(f" [HLS] Duración desde moov (inicio+extra): {dur:.1f}s")
                                return dur
                        finally:
                            try: os.remove(extra)
                            except: pass
            elif mdat_size > 0:
                # Moov no está al inicio → calcular posición exacta (después de mdat)
                moov_pos = 32 + mdat_size  # ftyp=32 + mdat_size
                print(f" [HLS] Moov no al inicio. mdat_size={mdat_size}, moov estimado en offset={moov_pos}")
                # Descargar suficiente para encontrar moov (5 MB típicamente cubre)
                download_size = min(5 * 1024 * 1024, file_size - moov_pos)
                tmp_moov = await _hls_download_range(ubot, msg, dc_id, moov_pos, download_size)
                if tmp_moov:
                    try:
                        with open(tmp_moov, 'rb') as f:
                            data_moov = f.read()
                        print(f" [HLS] Descargados {len(data_moov)} bytes desde offset {moov_pos}")
                        boxes2 = _parse_mp4_boxes(data_moov, 0)
                        print(f" [HLS] Boxes encontrados: {[(bt, bo, bs) for bt, bo, bs in boxes2[:5]]}")
                        for bt, bo, bs in boxes2:
                            if bt == 'moov':
                                print(f" [HLS] Moov encontrado: box_offset={bo}, box_size={bs}, data_len={len(data_moov)}")
                                # Si el moov completo está en los datos descargados
                                if bo + bs <= len(data_moov):
                                    dur = _extract_duration_from_mvhd(data_moov, bo, bs)
                                    if dur > 0:
                                        print(f" [HLS] Duración desde moov: {dur:.1f}s")
                                        return dur
                                else:
                                    # Moov se extiende, descargar el resto
                                    remaining = (bo + bs) - len(data_moov)
                                    print(f" [HLS] Moov incompleto, descargando {remaining} bytes más...")
                                    extra = await _hls_download_range(ubot, msg, dc_id, moov_pos + len(data_moov), remaining)
                                    if extra:
                                        try:
                                            with open(extra, 'rb') as f:
                                                data_extra = f.read()
                                            full_moov = data_moov + data_extra
                                            dur = _extract_duration_from_mvhd(full_moov, bo, bs)
                                            if dur > 0:
                                                print(f" [HLS] Duración desde moov (completo): {dur:.1f}s")
                                                return dur
                                        finally:
                                            try: os.remove(extra)
                                            except: pass
                    finally:
                        try: os.remove(tmp_moov)
                        except: pass
            else:
                print(f" [HLS] No se pudo determinar estructura MP4 (sin mdat ni moov en cabecera)")
        finally:
            try: os.remove(tmp_hdr)
            except: pass

    # FASE 2: Fallback - buscar "moov" por bytes en los últimos 10 MB
    print(f" [HLS] Fallback: buscando bytes 'moov' en últimos 10 MB...")
    search_from = max(0, file_size - 10 * 1024 * 1024)
    tmp_end = await _hls_download_range(ubot, msg, dc_id, search_from, file_size - search_from)
    if tmp_end:
        try:
            with open(tmp_end, 'rb') as f:
                data_end = f.read()
            idx = data_end.find(b'moov')
            if idx >= 0:
                # Encontrar el inicio del box (4 bytes antes del tipo)
                box_start = max(0, idx - 4)
                box_size = struct.unpack('>I', data_end[box_start:box_start+4])[0]
                abs_offset = search_from + box_start
                print(f" [HLS] Moov encontrado por bytes: abs_offset={abs_offset}, size={box_size}")
                # Descargar moov completo si no cabe
                moov_data = data_end[box_start:]
                if box_size > len(moov_data):
                    extra = await _hls_download_range(ubot, msg, dc_id, abs_offset + len(moov_data), box_size - len(moov_data))
                    if extra:
                        try:
                            with open(extra, 'rb') as f:
                                moov_data = moov_data + f.read()
                        finally:
                            try: os.remove(extra)
                            except: pass
                dur = _extract_duration_from_mvhd(moov_data, 0, box_size)
                if dur > 0:
                    print(f" [HLS] Duración desde moov (fallback): {dur:.1f}s")
                    return dur
        finally:
            try: os.remove(tmp_end)
            except: pass

    print(f" [HLS] No se encontró moov atom en el vídeo")
    return 0


def _hls_patch_stco(moov_data: bytes, delta: int) -> bytes:
    """Parchea stco/co64 dentro de moov sumando delta a cada offset. Retorna moov parcheado."""
    try:
        data = bytearray(moov_data)
        # Buscar boxes dentro de moov recursivamente
        def patch_in_range(start, end):
            pos = start
            while pos + 8 <= end:
                size = struct.unpack('>I', data[pos:pos+4])[0]
                typ = bytes(data[pos+4:pos+8]).decode('ascii', errors='ignore')
                if size < 8 or pos + size > end:
                    break
                if typ == 'stco':
                    # stco: [size][type][version/flags][entry_count][entries...]
                    entry_count = struct.unpack('>I', data[pos+12:pos+16])[0]
                    printLog(f" [HLS-PATCH] stco en {pos}, entries={entry_count}, delta={delta}")
                    for i in range(entry_count):
                        off = pos+16 + i*4
                        old = struct.unpack('>I', data[off:off+4])[0]
                        new = old + delta
                        if new < 0:
                            new = 0
                        elif new > 0xFFFFFFFF:
                            new = 0xFFFFFFFF
                        struct.pack_into('>I', data, off, new)
                    # Log primer/último
                    if entry_count>0:
                        first = struct.unpack('>I', data[pos+16:pos+20])[0]
                        last = struct.unpack('>I', data[pos+16+(entry_count-1)*4:pos+20+(entry_count-1)*4])[0]
                        printLog(f" [HLS-PATCH] stco parcheado: first={first} last={last}")
                elif typ == 'co64':
                    entry_count = struct.unpack('>I', data[pos+12:pos+16])[0]
                    printLog(f" [HLS-PATCH] co64 en {pos}, entries={entry_count}, delta={delta}")
                    for i in range(entry_count):
                        off = pos+16 + i*8
                        old = struct.unpack('>Q', data[off:off+8])[0]
                        new = old + delta
                        if new < 0:
                            new = 0
                        struct.pack_into('>Q', data, off, new)
                elif typ in ('moov','trak','mdia','minf','stbl','edts','mvex'):
                    # Contenedor: recursivo (header 8 bytes)
                    patch_in_range(pos+8, pos+size)
                pos += size
        # moov box incluye header 8 bytes; empezar después
        patch_in_range(8, len(data))
        return bytes(data)
    except Exception as e:
        printLog(f" [HLS-PATCH] Error parcheando stco: {e}")
        import traceback; traceback.print_exc()
        return moov_data


def _hls_is_mp4(msg):
    """Detecta si el documento es MP4/MOV (soporta FakeMP4). Si no, usará remux genérico."""
    try:
        media = getattr(msg, 'media', None)
        doc = getattr(media, 'document', None) if media else None
        if not doc:
            doc = getattr(msg, 'document', None)
        if not doc:
            return True
        mime = getattr(doc, 'mime_type', '') or ''
        if mime == 'video/mp4':
            return True
        if mime in ('video/x-msvideo', 'video/avi', 'video/x-matroska', 'video/mkv',
                      'video/webm', 'video/x-flv', 'video/x-ms-wmv', 'video/mp2t',
                      'video/mpeg', 'video/3gpp', 'video/ogg'):
            return False
        fname = ''
        for attr in getattr(doc, 'attributes', []) or []:
            fn = getattr(attr, 'file_name', None)
            if fn:
                fname = fn.lower()
                break
        if fname.endswith(('.mp4', '.m4v', '.mov', '.qt')):
            return True
        if fname.endswith(('.avi', '.mkv', '.webm', '.flv', '.wmv', '.asf',
                          '.ts', '.m2ts', '.mts', '.mpg', '.mpeg', '.vob',
                          '.3gp', '.3g2', '.ogv', '.ogm', '.rm', '.rmvb')):
            return False
    except Exception:
        pass
    return True




_HLS_SUBS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "hls_subs")

def _hls_subs_path(episode_key, lang="es"):
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(episode_key))
    os.makedirs(_HLS_SUBS_DIR, exist_ok=True)
    return os.path.join(_HLS_SUBS_DIR, f"{safe}_{lang}.srt")

def _parse_srt_time(t):
    # "00:00:05,000" or "00:00:05.000" -> seconds float
    try:
        t = t.strip().replace(',', '.')
        hms, ms = t.split('.')
        h, m, s = hms.split(':')
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0
    except Exception:
        return 0

def _parse_srt_cues(text):
    cues = []
    # normalizar saltos de línea
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\s*\n', text.strip())
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip() != '']
        if len(lines) < 2:
            continue
        # primera línea puede ser índice numérico
        idx = 0
        if re.match(r'^\d+$', lines[0]):
            idx = 1
        if idx >= len(lines):
            continue
        time_line = lines[idx]
        m = re.match(r'(.+?)\s*-->\s*(.+)', time_line)
        if not m:
            continue
        start = _parse_srt_time(m.group(1))
        end = _parse_srt_time(m.group(2).split()[0])
        txt = "\n".join(lines[idx+1:])
        cues.append((start, end, txt))
    return cues

def _cues_to_webvtt(cues, seg_start, seg_end):
    # cues que solapan [seg_start, seg_end)
    out = ["WEBVTT", ""]
    for s, e, txt in cues:
        if e <= seg_start or s >= seg_end:
            continue
        # recortar al intervalo del segmento para HLS (tiempos relativos al segmento)
        cs = max(s, seg_start) - seg_start
        ce = min(e, seg_end) - seg_start
        # formato WebVTT: HH:MM:SS.mmm
        def fmt(t):
            h = int(t // 3600); m = int((t % 3600) // 60); s_ = t % 60
            return f"{h:02d}:{m:02d}:{s_:06.3f}".replace('.', '.')
        out.append(f"{fmt(cs)} --> {fmt(ce)}")
        out.append(txt)
        out.append("")
    if len(out) <= 2:
        return None
    return "\n".join(out)


def _fmt_vtt_time(t):
    """Formatea segundos float a WebVTT HH:MM:SS.mmm."""
    t = max(0.0, t)
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _parse_vtt_cues(text):
    """Parsea un WebVTT a [(start_sec, end_sec, text), ...] con tiempos absolutos en segundos."""
    cues = []
    if not text:
        return cues
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # eliminar header y bloques NOTE/STYLE/REGION
    blocks = re.split(r'\n\s*\n', text)
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip() != '']
        if not lines:
            continue
        # buscar línea de tiempo con -->
        time_idx = None
        for i, l in enumerate(lines):
            if '-->' in l:
                time_idx = i
                break
        if time_idx is None:
            continue
        m = re.match(r'(\d{1,2}(?::\d{2}){1,2}[.,]\d{3})\s*-->\s*(\d{1,2}(?::\d{2}){1,2}[.,]\d{3})', lines[time_idx])
        if not m:
            continue
        s = _parse_vtt_timestamp(m.group(1))
        e = _parse_vtt_timestamp(m.group(2))
        txt = "\n".join(lines[time_idx+1:])
        cues.append((s, e, txt))
    return cues


def _parse_vtt_timestamp(t):
    """'HH:MM:SS.mmm' o 'MM:SS.mmm' -> segundos float."""
    t = t.strip().replace(',', '.')
    parts = t.split(':')
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h)*3600 + int(m)*60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m)*60 + float(s)
        else:
            return float(parts[0])
    except Exception:
        return 0.0


async def _hls_ensure_header_cache(ubot, msg, dc_id, file_size, episode_key):
    """Asegura que _HLS_SEG_CACHE[episode_key] tiene ftyp_bytes, moov_bytes, moov_pos, mdat_start."""
    info = _HLS_SEG_CACHE.get(episode_key, {})
    is_mp4 = _hls_is_mp4(msg)
    _cont = ""
    try:
        _media2 = getattr(msg, 'media', None)
        _doc2 = getattr(_media2, 'document', None) if _media2 else None
        if not _doc2:
            _doc2 = getattr(msg, 'document', None)
        if _doc2:
            _cont = getattr(_doc2, 'mime_type', '') or ''
            if not _cont:
                for _a in getattr(_doc2, 'attributes', []) or []:
                    _fn = getattr(_a, 'file_name', None)
                    if _fn:
                        _cont = _fn
                        break
    except Exception:
        _cont = ""
    _HLS_SEG_CACHE.setdefault(episode_key, {})["is_mp4"] = is_mp4
    _HLS_SEG_CACHE.setdefault(episode_key, {})["container"] = _cont
    if is_mp4:
        if info.get("ftyp_bytes") and info.get("moov_bytes"):
            return info
    else:
        if info.get("header_bytes"):
            return info
    printLog(f" [HLS-CACHE] Construyendo cache de header para {episode_key}")
    if not is_mp4:
        tmp_hdr = await _hls_download_range(ubot, msg, dc_id, 0, min(1024*1024, file_size))
        header_bytes = b""
        if tmp_hdr:
            try:
                with open(tmp_hdr, 'rb') as f:
                    header_bytes = f.read()
            finally:
                try: os.remove(tmp_hdr)
                except: pass
        if header_bytes:
            _HLS_SEG_CACHE[episode_key]["header_bytes"] = header_bytes
            # ffprobe para pistas (genérico)
            try:
                import tempfile as _tf2
                fd2, p2 = _tf2.mkstemp(suffix=".hdr")
                os.close(fd2)
                with open(p2, 'wb') as _f2: _f2.write(header_bytes)
                info2 = None
                try:
                    import subprocess as _sp_sub, json as _js
                    from services import stream_packager as _sp2
                    ffprobe = getattr(_sp2, '_find_ffprobe', lambda: None)() or "ffprobe"
                    out = _sp_sub.check_output([ffprobe, "-v", "error", "-print_format", "json", "-show_streams", p2], timeout=10)
                    info2 = _js.loads(out.decode('utf-8', errors='ignore'))
                except Exception:
                    info2 = None
                try: os.remove(p2)
                except: pass
                if info2 and isinstance(info2, dict) and info2.get("streams"):
                    tr = []
                    for idx, s in enumerate(info2["streams"]):
                        t = s.get("codec_type", "")
                        typ = "video" if t=="video" else "audio" if t=="audio" else "subs" if t=="subtitle" else "unknown"
                        lang = (s.get("tags") or {}).get("language", "und")
                        # Para MKV el nombre va en title, no language
                        title = (s.get("tags") or {}).get("title", "")
                        if lang == "und" and title:
                            lang = title
                        codec = s.get("codec_name", "")
                        tr.append({"idx": 0, "stream_index": s.get("index", idx), "type": typ, "lang": lang, "codec": codec, "hdlr": t})
                    # reindexar audios/subs por separado (idx relativo) manteniendo stream_index global
                    a_i = s_i = 0
                    for tt in tr:
                        if tt["type"]=="audio": tt["idx"]=a_i; a_i+=1
                        elif tt["type"]=="subs": tt["idx"]=s_i; s_i+=1
                    _HLS_SEG_CACHE[episode_key]["tracks"] = tr
            except Exception:
                pass
            printLog(f" [HLS-CACHE] header genérico {len(header_bytes)}B para {episode_key} (no-MP4)")
            # escribir cabecera al sparse para que ffmpeg remux la encuentre
            try:
                _sp = _hls_sparse_load(episode_key, file_size)
                with open(_sp["path"], 'r+b') as _f:
                    _f.seek(0)
                    _f.write(header_bytes)
                for _b in range(0, min(2, _sp["total_blocks"])):
                    _sp["bitmap"].add(_b)
                _hls_cache_save(episode_key, _sp["path"], file_size, _sp["total_blocks"], _hls_bitmap_serialize(_sp["bitmap"]))
            except Exception:
                pass
        return _HLS_SEG_CACHE.get(episode_key, {})
    # Descargar ftyp (primeros 32 bytes)
    tmp_ftyp = await _hls_download_range(ubot, msg, dc_id, 0, 32)
    ftyp_bytes = b""
    if tmp_ftyp:
        try:
            with open(tmp_ftyp, 'rb') as f:
                ftyp_bytes = f.read()
        finally:
            try: os.remove(tmp_ftyp)
            except: pass
    # Obtener moov: descargar cabecera y detectar si el moov está al inicio (faststart)
    # o al final (tradicional). Leer el primer box tras ftyp para decidir.
    tmp_hdr = await _hls_download_range(ubot, msg, dc_id, 0, min(1024*1024, file_size))
    mdat_size = 0
    moov_pos = None
    moov_at_start = False
    if tmp_hdr:
        try:
            with open(tmp_hdr, 'rb') as f:
                hdr = f.read()
            boxes = _parse_mp4_boxes(hdr, 0)
            for bt, bo, bs in boxes:
                if bt == 'mdat':
                    mdat_size = bs
                    break
                if bt == 'moov':
                    # moov al INICIO (faststart)
                    moov_pos = bo
                    moov_at_start = True
                    break
        finally:
            try: os.remove(tmp_hdr)
            except: pass
    if moov_at_start:
        pass  # moov_pos ya asignado (offset del box moov al inicio)
    elif mdat_size > 0:
        moov_pos = 32 + mdat_size
    else:
        moov_pos = max(0, file_size - 10*1024*1024)
    # Descargar el moov COMPLETO con multi-conexión (rápido, como TGHirayi).
    moov_bytes = b""
    threads = await _hls_get_hls_download_threads()
    # 1º leer el header del box (4 bytes de tamaño) con 1MB inicial
    tmp_moov = await _hls_download_range(ubot, msg, dc_id, moov_pos, min(1024*1024, file_size - moov_pos))
    if tmp_moov:
        try:
            with open(tmp_moov, 'rb') as f:
                first = f.read()
        finally:
            try: os.remove(tmp_moov)
            except: pass
        box_size = 0
        box_start = None
        if len(first) >= 8 and first[4:8] == b'moov':
            box_size = struct.unpack('>I', first[0:4])[0]
            box_start = moov_pos
        else:
            idx = first.find(b'moov')
            if idx >= 4:
                box_size = struct.unpack('>I', first[idx-4:idx])[0]
                box_start = moov_pos + idx - 4
        if box_size >= 8 and box_start is not None:
            box_size = min(box_size, file_size - box_start)
            if box_size <= len(first):
                moov_bytes = first[0:box_size]
            else:
                # descargar el resto con multi-conexión
                moov_bytes = await _hls_download_bytes_parallel(ubot, msg, box_start, box_size, threads)
    if ftyp_bytes and moov_bytes:
        _HLS_SEG_CACHE[episode_key]["ftyp_bytes"] = ftyp_bytes
        _HLS_SEG_CACHE[episode_key]["moov_bytes"] = moov_bytes
        _HLS_SEG_CACHE[episode_key]["moov_pos"] = box_start if box_start is not None else moov_pos
        _HLS_SEG_CACHE[episode_key]["mdat_data_start"] = 40  # ftyp(32)+mdat header(8)
        # Parsear sample table del track de vídeo (para descarga por-slice con keyframes)
        st = _mp4_parse_sample_table(moov_bytes, 0)
        if st:
            _HLS_SEG_CACHE[episode_key]["sample_table"] = st
            printLog(f" [HLS-CACHE] sample_table OK: samples={st['total_samples']}, chunks={len(st['chunk_offsets'])}, sync={len(st['sync_samples'])}, dur_video={st['video_duration']:.2f}s")
        else:
            printLog(f" [HLS-CACHE] WARN: no se pudo parsear sample table (fallback a descarga acumulativa)")
        # Extraer pistas de audio/subs del moov
        try:
            tracks = _hls_extract_tracks(moov_bytes)
            if tracks:
                _HLS_SEG_CACHE[episode_key]["tracks"] = tracks
                printLog(f" [HLS-CACHE] tracks: {tracks}")
        except Exception:
            pass
        printLog(f" [HLS-CACHE] ftyp={len(ftyp_bytes)}B moov={len(moov_bytes)}B moov_pos={moov_pos}")
    return _HLS_SEG_CACHE.get(episode_key, {})


async def _hls_download_bytes_parallel(ubot, msg, offset, length, threads):
    """Descarga [offset, offset+length) a bytes con UNA sola conexión (secuencial).
    Se usa para el moov: la multi-conexión dispara flood 429 de Telegram."""
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import InputDocumentFileLocation
    client = getattr(ubot, '_client', ubot)
    media = getattr(msg, 'media', None)
    doc = getattr(media, 'document', None) if media else None
    if not doc:
        doc = getattr(msg, 'document', None)
    if not doc:
        return b""
    CHUNK = 512 * 1024
    # GetFileRequest exige offset divisible por 1024 y limit divisible por 4096.
    # Alineamos el offset hacia abajo a múltiplo de CHUNK y descargamos un poco
    # más, para luego recortar el prefijo sobrante y devolver EXACTAMENTE
    # [offset, offset+length) como espera el caller.
    aligned_offset = (offset // CHUNK) * CHUNK
    skip = offset - aligned_offset
    padded_len = ((skip + length + CHUNK - 1) // CHUNK) * CHUNK
    location = InputDocumentFileLocation(
        id=doc.id, access_hash=doc.access_hash,
        file_reference=doc.file_reference, thumb_size=''
    )
    total_chunks = (padded_len + CHUNK - 1) // CHUNK
    buf = bytearray(padded_len)
    REQ_TIMEOUT = 90

    for i in range(total_chunks):
        abs_off = aligned_offset + i * CHUNK
        data = None
        for attempt in range(1, 4):
            try:
                req = GetFileRequest(location=location, offset=abs_off, limit=CHUNK)
                result = await asyncio.wait_for(client(req), timeout=REQ_TIMEOUT)
                data = bytes(result.bytes)
                if data:
                    break
            except asyncio.TimeoutError:
                data = None
            except Exception:
                data = None
            if attempt < 3:
                await asyncio.sleep(0.5 * attempt)
        if data is None:
            print(f" [HLS-DLB] chunk {i} (off={abs_off}) falló tras reintentos")
            continue
        start = i * CHUNK
        buf[start:start + len(data)] = data

    return bytes(buf[skip:skip + length])

async def _hls_resolve_episode(episode_key):
    """Resuelve episodio por episode_key (channelid_msgid) → (msg, chat_entity, file_size, dc_id)."""
    if episode_key in _HLS_SEG_CACHE and _HLS_SEG_CACHE[episode_key].get("msg_obj"):
        c = _HLS_SEG_CACHE[episode_key]
        return c["msg_obj"], c["chat_entity"], c["file_size"], c["dc_id"]

    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT ie.*, i.telegram_link as item_link "
        "FROM item_episodes ie "
        "LEFT JOIN unified_catalog i ON i.id = CAST(ie.item_id AS INTEGER) OR i.item_id = ie.item_id "
        "WHERE ie.episode_key=?", (episode_key,)
    ).fetchone()

    # Fallback: si episode_key no está en BD, derivar desde telegram_link
    if not row:
        parts = episode_key.split("_")
        if len(parts) == 2:
            msg_id_part = int(parts[1])
            row = conn.execute(
                "SELECT ie.*, i.telegram_link as item_link "
                "FROM item_episodes ie "
                "LEFT JOIN unified_catalog i ON i.id = CAST(ie.item_id AS INTEGER) OR i.item_id = ie.item_id "
                "WHERE ie.telegram_msg_id=?", (msg_id_part,)
            ).fetchone()
            if row:
                print(f" [HLS] Encontrado por telegram_msg_id={msg_id_part} (fallback)")

    conn.close()
    if not row:
        print(f" [HLS] Episodio {episode_key} no encontrado en BD")
        return None, None, 0, None

    ep_link = row["telegram_link"] or ""
    msg_id = row["telegram_msg_id"]
    print(f" [HLS] ep_key={episode_key}, link={ep_link}, msg_id={msg_id}")
    if not ep_link or not msg_id:
        print(f" [HLS] Falta link o msg_id")
        return None, None, 0, None

    m = re.search(r"t\.me/c/(\d+)/(\d+)", ep_link)
    if not m:
        print(f" [HLS] No se pudo parsear telegram_link: {ep_link}")
        return None, None, 0, None
    chat_id = m.group(1)
    cid = chat_id
    if cid.isdigit() and not cid.startswith("-"):
        cid = "-100" + cid
    try:
        chat_entity = int(cid)
    except ValueError:
        print(f" [HLS] chat_entity invalido: {cid}")
        return None, None, 0, None

    from services.userbot_service import get_active_client
    ubot = await get_active_client()
    if not ubot:
        print(f" [HLS] Userbot no disponible")
        return None, None, 0, None

    print(f" [HLS] Obteniendo mensaje: chat_entity={chat_entity}, msg_id={msg_id}")
    msg = await _stream_get_message(ubot, chat_entity, int(msg_id))
    if not msg:
        print(f" [HLS] Mensaje no encontrado en Telegram")
        return None, None, 0, None

    file_size = 0
    dc_id = None
    doc = None
    if hasattr(msg, 'document') and msg.document:
        doc = msg.document
    elif hasattr(msg, 'media') and msg.media:
        for attr_name in ['document', 'video']:
            candidate = getattr(msg.media, attr_name, None)
            if candidate and hasattr(candidate, 'size'):
                doc = candidate
                break
    if doc:
        file_size = getattr(doc, 'size', 0) or getattr(doc, 'file_size', 0)
        dc_id = getattr(doc, 'dc_id', None)

    _HLS_SEG_CACHE[episode_key] = {
        "msg_obj": msg, "chat_entity": chat_entity,
        "file_size": file_size, "dc_id": dc_id
    }

    # Intentar obtener duración de los metadatos de Telegram (sin descargar)
    duration = 0
    try:
        # Log raw mínimo
        try:
            print(f" [HLS] msg.id={msg.id}, has_doc={msg.document is not None}")
        except: pass
        if msg.document:
            try:
                print(f" [HLS] doc.mime_type={getattr(msg.document,'mime_type','?')}, doc.size={getattr(msg.document,'size',0)}")
                for i, attr in enumerate(getattr(msg.document,'attributes',[]) or []):
                    print(f" [HLS] doc attr[{i}]: {type(attr).__name__} = {attr}")
            except Exception as e:
                print(f" [HLS] doc log error: {e}")
        # Extracción robusta: solo desde document.attributes (único fiable)
        if msg.document and getattr(msg.document,'attributes',None):
            for attr in (msg.document.attributes or []):
                try:
                    if hasattr(attr, 'duration') and attr.duration:
                        duration = float(attr.duration)
                        print(f" [HLS] Duración desde Telegram: {duration}s (attr {type(attr).__name__})")
                        break
                except: pass
        if duration > 0:
            _HLS_SEG_CACHE[episode_key]["duration"] = duration
        else:
            print(f" [HLS] Sin duración en metadatos de Telegram")
    except Exception as e:
        print(f" [HLS] Error leyendo duración de Telegram: {e}")
        import traceback; traceback.print_exc()

    return msg, chat_entity, file_size, dc_id


async def _hls_get_hls_download_threads() -> int:
    """Reutiliza download_threads de la config de TGHirayi (si está disponible).
    No modifica TGHirayi; solo lectura. Default 8."""
    try:
        from plugins.tvcat_TGHirayi import routes as _tg_routes
        cfg = _tg_routes._load_config()
        t = int(cfg.get("download_threads", 8) or 8)
        return max(1, min(16, t))
    except Exception:
        return 8


async def _hls_parallel_download_tgh(client, msg, file_path, threads, progress_callback=None):
    """Descarga el documento COMPLETO a file_path usando EXACTAMENTE el _parallel_download
    de TGHirayi (multi-conexión + sidecar .chunks reanudable). Devuelve path si completo,
    None si incompleto (el sidecar queda para reanudar)."""
    try:
        from plugins.tvcat_TGHirayi import routes as _tg_routes
        return await _tg_routes._parallel_download(client, msg, file_path, threads,
                                                   progress_callback=progress_callback)
    except Exception as e:
        print(f" [HLS-PDL-TGH] error importando _parallel_download de TGHirayi: {e}")
        # fallback: usar el _parallel_download local (copia)
        return await _hls_parallel_download(client, msg, file_path, 0, 0, threads) if False else None


async def _hls_download_range(ubot, msg, dc_id, offset, length):
    """Descarga un rango de bytes de Telegram (.bin temp). Telethon: multi-conexión paralela.
    Pyrogram: iter_download del wrapper (ya por rangos). Retorna path o None."""
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix=".bin", dir=_HLS_SEG_DIR)
    os.close(fd)
    if length <= 0:
        try: os.remove(tmp_path)
        except Exception: pass
        return None
    async with _HLS_DOWNLOAD_LOCK:
        # Descarga secuencial exacta (respeta length). Se usa para ftyp/moov/cabecera,
        # que necesitan tamaño exacto (la multi-conexión re-alinea length a 4096).
        collected = 0
        with open(tmp_path, "wb") as f:
            async for chunk in ubot.iter_download(msg, offset=offset, chunk_size=min(length, 1024*1024), dc_id=dc_id):
                if chunk:
                    remaining = length - collected
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    f.write(chunk)
                    collected += len(chunk)
                    if collected >= length:
                        break
        if collected > 0:
            return tmp_path
    try:
        os.remove(tmp_path)
    except Exception:
        pass
    return None


async def _hls_download_pyrogram(ubot, msg, file_path, dc_id, offset, length) -> bool:
    """Descarga por rangos para clientes Pyrogram usando el iter_download del wrapper."""
    collected = 0
    try:
        with open(file_path, "wb") as f:
            async for chunk in ubot.iter_download(msg, offset=offset, chunk_size=min(length, 4*1024*1024), dc_id=dc_id):
                if chunk:
                    remaining = length - collected
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                    f.write(chunk)
                    collected += len(chunk)
                    if collected >= length:
                        break
    except Exception as e:
        print(f" [HLS-DL] Error pyrogram: {e}")
        return False
    return collected >= length


async def _hls_parallel_download(client, msg, file_path, offset, length, threads: int) -> bool:
    """Descarga [offset, offset+length) del documento con N conexiones paralelas (512KB cada una).
    Devuelve True si se escribió el rango completo en file_path (abierto en r+b, seek + write)."""
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import InputDocumentFileLocation

    media = getattr(msg, 'media', None)
    doc = getattr(media, 'document', None) if media else None
    if not doc:
        doc = getattr(msg, 'document', None)
    if not doc:
        return False
    import tempfile, io

    # Alinear offset a múltiplo de 1KB (GetFileRequest) y length a múltiplo de 4096
    offset = (offset // 1024) * 1024
    aligned_end = ((offset + length) // 4096 + 1) * 4096
    length = aligned_end - offset

    end_off = offset + length
    location = InputDocumentFileLocation(
        id=doc.id,
        access_hash=doc.access_hash,
        file_reference=doc.file_reference,
        thumb_size=''
    )

    threads = max(1, min(int(threads), 16))
    CHUNK = 512 * 1024  # límite Telegram

    # Clonar sesión para abrir conexiones secundarias al mismo DC
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    session_string = client.session.save() if hasattr(client, 'session') else ''
    secondary = []
    for _ in range(max(0, threads - 1)):
        if not session_string:
            break
        try:
            c = TelegramClient(StringSession(session_string), client.api_id, client.api_hash)
            await c.connect()
            secondary.append(c)
        except Exception as e:
            print(f" [HLS-PDL] No se pudo abrir conexión secundaria: {e}")
            break

    # Preasignar el fichero a 'length' bytes
    with open(file_path, 'wb') as f:
        f.truncate(length)

    # Repartir el rango en 'threads' trozos contiguos de CHUNK
    total_chunks = (length + CHUNK - 1) // CHUNK
    per = max(1, (total_chunks + threads - 1) // threads)
    ranges = []
    for start in range(0, total_chunks, per):
        end = min(start + per, total_chunks)
        if start < total_chunks:
            ranges.append((start, end))

    workers = secondary + [client]
    writers = workers[:len(ranges)]

    async def _dl_range(c, range_start, range_end):
        try:
            with open(file_path, 'r+b') as f:
                for i in range(range_start, range_end):
                    chunk_off = i * CHUNK
                    abs_off = offset + chunk_off
                    if chunk_off >= length:
                        break
                    if abs_off % 1024 != 0:
                        print(f" [HLS-PDL] WARN abs_off={abs_off} no divisible 1KB (range {range_start}-{range_end} i={i})")
                        abs_off = (abs_off // 1024) * 1024
                    req = GetFileRequest(location=location, offset=abs_off, limit=CHUNK)
                    result = await c(req)
                    data = bytes(result.bytes)
                    f.seek(chunk_off)
                    f.write(data)
        except Exception as e:
            print(f" [HLS-PDL] Error en rango {range_start}-{range_end} abs_off={abs_off if 'abs_off' in locals() else '?'}: {e}")
            raise

    try:
        await asyncio.gather(*[
            _dl_range(writers[i], ranges[i][0], ranges[i][1])
            for i in range(len(ranges))
        ])
    except Exception:
        return False
    finally:
        for c in secondary:
            try:
                await c.disconnect()
            except Exception:
                pass

    return os.path.isfile(file_path) and os.path.getsize(file_path) >= length


async def _hls_open_secondary(client, threads):
    """Abre conexiones secundarias (clonando la sesión, mismo DC) para descargas
    multi-conexión. Devuelve la lista de clientes secundarios conectados.
    El llamador es responsable de cerrarlas. Se abre UNA vez por episodio para evitar
    el churn de handshakes que dispara el flood 429 de Telegram."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    session_string = client.session.save() if hasattr(client, 'session') else ''
    secondary = []
    if session_string:
        for _ in range(max(0, threads - 1)):
            try:
                c = TelegramClient(StringSession(session_string), client.api_id, client.api_hash)
                await asyncio.wait_for(c.connect(), timeout=15)
                secondary.append(c)
            except Exception:
                break
    return secondary


async def _hls_close_secondary(secondary):
    """Cierra las conexiones secundarias (best effort)."""
    for c in secondary:
        try:
            await c.disconnect()
        except Exception:
            pass


async def _hls_download_priority_range(ubot, msg, state, start_off, end_off, threads, secondary=None):
    """Descarga un RANGO [start_off, end_off) al fichero sparse con multi-conexión,
    copiando EXACTAMENTE el patrón de _parallel_download de TGHirayi: REQ_TIMEOUT=90,
    reintentos de rango (re-descargando solo lo que falta) y reintento final con el
    cliente principal.

    `secondary`: conexiones secundarias YA abiertas (reutilizar entre lotes). Si es
    None, solo usa el cliente principal (1 conexión). NO cierra las conexiones aquí:
    el llamador las gestiona para evitar el churn de handshakes → flood 429.

    Escribe en el offset absoluto y marca el bitmap. Devuelve nº de bloques rellenados."""
    from telethon.tl.functions.upload import GetFileRequest
    from telethon.tl.types import InputDocumentFileLocation
    from telethon.errors import FloodWaitError
    client = getattr(ubot, '_client', ubot)
    media = getattr(msg, 'media', None)
    doc = getattr(media, 'document', None) if media else None
    if not doc:
        doc = getattr(msg, 'document', None)
    if not doc:
        return 0

    CHUNK = 512 * 1024
    start_off = (start_off // CHUNK) * CHUNK
    end_off = min(((end_off + CHUNK - 1) // CHUNK) * CHUNK, state["file_size"])
    if end_off <= start_off:
        return 0
    location = InputDocumentFileLocation(
        id=doc.id, access_hash=doc.access_hash,
        file_reference=doc.file_reference, thumb_size=''
    )
    threads = max(1, min(int(threads), 3))   # pocas conexiones: menos presión anti-flood
    REQ_TIMEOUT = 90
    bucket = _hls_get_token_bucket()

    # Repartir el rango en 'threads' trozos contiguos de CHUNK
    total_chunks = (end_off - start_off + CHUNK - 1) // CHUNK
    per = max(1, (total_chunks + threads - 1) // threads)
    ranges = []
    for s in range(0, total_chunks, per):
        e = min(s + per, total_chunks)
        if s < total_chunks:
            ranges.append((s, e))

    workers = (secondary or []) + [client]
    writers = workers[:len(ranges)]
    done = [0]
    lock = asyncio.Lock()

    async def _dl_range(c, rs, re, retries=3):
        # Patrón TGHirayi: reintenta el rango; en cada intento solo descarga los
        # chunks que faltan (marcados en el bitmap), no re-escribe lo ya escrito.
        # Además limita el ritmo con el token bucket (anti-flood 429) y respeta
        # el FloodWaitError de Telegram esperando los segundos indicados.
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                with open(state["path"], 'r+b') as f:
                    for i in range(rs, re):
                        abs_off = start_off + i * CHUNK
                        if abs_off >= state["file_size"]:
                            break
                        b = abs_off // CHUNK
                        if b in state["bitmap"]:
                            continue
                        if state.get("last_active", 0) == 0:
                            printLog(f" [HLS-PRI] abortado por leave en bloque {b}")
                            return True
                        # 1 token por bloque (512KB) → ritmo sostenible anti-429
                        await bucket.acquire(1)
                        req = GetFileRequest(location=location, offset=abs_off, limit=CHUNK)
                        try:
                            result = await asyncio.wait_for(c(req), timeout=REQ_TIMEOUT)
                        except FloodWaitError as fw:
                            # Telegram pide esperar: respetar los segundos indicados.
                            wait_s = getattr(fw, 'seconds', 30) or 30
                            print(f" [HLS-PRI] FloodWait {wait_s}s, esperando...")
                            await asyncio.sleep(wait_s)
                            raise
                        data = bytes(result.bytes)
                        if not data:
                            raise RuntimeError("chunk vacío")
                        f.seek(abs_off)
                        f.write(data)
                        async with lock:
                            state["bitmap"].add(b)
                            done[0] += 1
                return True
            except asyncio.TimeoutError:
                last_err = "timeout"
            except FloodWaitError as fw:
                last_err = f"floodwait {getattr(fw, 'seconds', '?')}s"
            except Exception as e:
                last_err = repr(e)
        print(f" [HLS-PRI] rango {rs}-{re} falló tras {retries} intentos ({last_err})")
        return False

    results = await asyncio.gather(*[
        _dl_range(writers[i], ranges[i][0], ranges[i][1])
        for i in range(len(ranges))
    ], return_exceptions=True)

    # Reintento final de los rangos fallidos con el cliente principal (patrón TGHirayi)
    failed = [ranges[i] for i in range(len(ranges)) if results[i] is not True]
    if failed:
        for rng in failed:
            await _dl_range(client, rng[0], rng[1], retries=2)

    _hls_cache_save(state.get("_episode_key", ""), state["path"], state["file_size"],
                    state["total_blocks"], _hls_bitmap_serialize(state["bitmap"]))
    return done[0]


# ═════════════════════════════════════════════════════════════════════════════
# HLS CACHE SPARSE — Token bucket + descarga de bloques contiguos al fichero
# ═════════════════════════════════════════════════════════════════════════════

class _HlsTokenBucket:
    """Token bucket global: limita GetFile (512KB) por minuto para no disparar 429.
    Cada bloque de 512KB consume 1 token. Se recarga a rate_per_min tokens/minuto."""

    def __init__(self, rate_per_min):
        self.rate = float(rate_per_min)
        self.tokens = 0.0                 # empieza vacío → recarga gradual (sin ráfaga inicial que sature)
        self._last = None
        self._lock = asyncio.Lock()

    async def acquire(self, n=1):
        import time as _t3
        async with self._lock:
            while True:
                now = _t3.monotonic()
                if self._last is None:
                    self._last = now
                elapsed = now - self._last
                self._last = now
                self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / 60.0))
                if self.tokens >= n:
                    self.tokens -= n
                    return
                # esperar lo necesario para juntar n tokens
                need = n - self.tokens
                wait = need / (self.rate / 60.0)
                await asyncio.sleep(min(wait, 5.0))


_HLS_TOKEN_BUCKET = None


def _hls_get_token_bucket():
    global _HLS_TOKEN_BUCKET
    if _HLS_TOKEN_BUCKET is None:
        _HLS_TOKEN_BUCKET = _HlsTokenBucket(_HLS_RATE_LIMIT_PER_MIN)
    return _HLS_TOKEN_BUCKET


def _hls_sparse_path(episode_key):
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(episode_key))
    return os.path.join(_HLS_CACHE_DIR, f"{safe}.mp4")


def _hls_sparse_load(episode_key, file_size):
    """Carga/crea el estado del fichero sparse en memoria. Retorna dict de estado."""
    if episode_key in _HLS_SPARSE:
        return _HLS_SPARSE[episode_key]
    path = _hls_sparse_path(episode_key)
    total_blocks = max(1, (file_size + _HLS_BLOCK_SIZE - 1) // _HLS_BLOCK_SIZE)
    state = {
        "path": path,
        "file_size": file_size,
        "total_blocks": total_blocks,
        "cursor_block": 0,          # siguiente bloque a descargar (secuencial hacia adelante)
        "playback_block": 0,        # bloque del punto de reproducción (para prioridad)
        "last_active": 0.0,         # timestamp de la última petición de segmento (prioridad de reproducción)
        "fill_full": False,         # True = descargar fichero COMPLETO (modo solo-descarga/warmup)
        "bitmap": set(),            # set de índices de bloque ya rellenados
        "users": set(),             # user_ids activos (para conteo de 'en uso')
        "moov_bytes": None,
        "moov_off": None,
        "_episode_key": episode_key,
    }
    # Restaurar bitmap persistido (fuente de verdad = BD, NO el fichero en disco)
    row = _hls_cache_row(episode_key)
    if row is not None:
        if row["file_path"]:
            state["path"] = row["file_path"]
        state["bitmap"] = _hls_bitmap_deserialize(row["bitmap"])
        if row["complete"]:
            # ya estaba completo → bitmap lleno (aunque el fichero se haya borrado)
            for b in range(total_blocks):
                state["bitmap"].add(b)
            state["cursor_block"] = total_blocks
    _HLS_SPARSE[episode_key] = state
    # Asegurar que el fichero sparse existe con el tamaño correcto (sin tocar contenido)
    if not os.path.isfile(path):
        with open(path, "wb") as f:
            f.truncate(file_size)
    # Restaurar bitmap desde el sidecar de TGHirayi (.chunks) si existe
    _hls_refresh_bitmap_from_sidecar(state)
    return state


async def _hls_fill_blocks(episode_key, state, start_block, count, ubot, msg, dc_id):
    """Descarga `count` bloques contiguos desde `start_block` al fichero sparse,
    SECUENCIALMENTE en 1 conexión (GetFileRequest directo), 1 token por bloque.
    La multi-conexión (8 sockets) satura Telegram → 429, así que NO se usa aquí.
    Retorna el nº de bloques realmente rellenados."""
    if count <= 0:
        return 0
    start_block = max(0, start_block)
    end_block = min(start_block + count, state["total_blocks"])
    if end_block <= start_block:
        return 0
    offset = start_block * _HLS_BLOCK_SIZE
    length = (end_block - start_block) * _HLS_BLOCK_SIZE
    n_blocks = end_block - start_block

    client = getattr(ubot, '_client', ubot)
    ctype = getattr(ubot, '_type', 'telethon')

    print(f" [TGHirayi-DOWNLOAD] ep={episode_key} rango={offset}..{offset+length} ({length/1024/1024:.1f}MB, {n_blocks} bloques)")

    filled = 0
    try:
        async with _HLS_DOWNLOAD_LOCK:  # serializar con header cache (mismo cliente Telethon)
            for b in range(start_block, end_block):
                # 1 token por bloque (1 request de 512KB)
                await _hls_get_token_bucket().acquire(1)
                block_off = b * _HLS_BLOCK_SIZE
                block_len = min(_HLS_BLOCK_SIZE, state["file_size"] - block_off)
                if block_len <= 0:
                    break
                data = await _hls_get_file_block(client, msg, block_off, block_len, ctype)
                if data is None:
                    print(f" [TGHirayi-DOWNLOAD] bloque {b} falló, pausa...")
                    await asyncio.sleep(2.0)  # backoff si falla
                    break
                # escribir al sparse en el offset exacto
                with open(state["path"], "r+b") as fdst:
                    fdst.seek(block_off)
                    fdst.write(data)
                state["bitmap"].add(b)
                filled += 1
                # persistir cada N bloques
                if filled % 16 == 0:
                    _hls_cache_save(episode_key, state["path"], state["file_size"],
                                    state["total_blocks"], _hls_bitmap_serialize(state["bitmap"]))
    except Exception as e:
        print(f" [TGHirayi-DOWNLOAD] error: {e}")

    if filled > 0:
        _hls_cache_save(episode_key, state["path"], state["file_size"],
                        state["total_blocks"], _hls_bitmap_serialize(state["bitmap"]))
        print(f" [TGHirayi-DOWNLOAD] OK: {filled}/{n_blocks} bloques rellenados (bitmap={len(state['bitmap'])}/{state['total_blocks']})")
    return filled


async def _hls_get_file_block(client, msg, offset, length, ctype):
    """Descarga 1 bloque (<=512KB) con GetFileRequest directo (1 sola request).
    Retorna bytes o None si falla."""
    if ctype == 'telethon':
        from telethon.tl.functions.upload import GetFileRequest
        from telethon.tl.types import InputDocumentFileLocation
        media = getattr(msg, 'media', None)
        doc = getattr(media, 'document', None) if media else None
        if not doc:
            doc = getattr(msg, 'document', None)
        if not doc:
            return None
        # alinear offset a 1KB (exigencia de GetFileRequest)
        aligned_off = (offset // 1024) * 1024
        location = InputDocumentFileLocation(
            id=doc.id, access_hash=doc.access_hash,
            file_reference=doc.file_reference, thumb_size=''
        )
        try:
            result = await client(GetFileRequest(location=location, offset=aligned_off, limit=min(length, 512*1024)))
            return bytes(result.bytes)
        except Exception as e:
            print(f" [TGHirayi-DOWNLOAD] GetFile error (off={aligned_off}): {e}")
            return None
    else:
        # pyrogram: descarga por rango
        import io
        buf = io.BytesIO()
        try:
            async for chunk in client.iter_download(msg, offset=offset, chunk_size=min(length, 512*1024)):
                if chunk:
                    buf.write(chunk)
                    if buf.tell() >= length:
                        break
        except Exception as e:
            print(f" [TGHirayi-DOWNLOAD] pyrogram error: {e}")
            return None
        return buf.getvalue() or None


def _hls_next_missing_block(state, prefer_from=None):
    """Busca el siguiente bloque no rellenado PRIORIZANDO prefer_from (punto de reproducción).
    Rellena secuencialmente hacia adelante TODO el fichero (como TGHirayi), priorizando
    primero la zona de reproducción y luego el resto. Devuelve None si el fichero está
    completo."""
    if prefer_from is None:
        prefer_from = state["cursor_block"]
    total = state["total_blocks"]
    # 1º: huecos desde prefer_from hacia adelante (zona prioritaria de reproducción)
    for b in range(prefer_from, total):
        if b not in state["bitmap"]:
            return b
    # 2º: huecos atrás de prefer_from (islas dejadas por seeks)
    for b in range(0, prefer_from):
        if b not in state["bitmap"]:
            return b
    return None


async def _hls_worker_loop():
    """Worker global único: descarga el fichero al sparse con multi-conexión robusta
    (patrón TGHirayi), PRIORIZANDO el punto de reproducción (playback_block) para que
    el seek a zonas no descargadas se rellenen primero. Mantiene un pool de conexiones
    secundarias abierto por episodio (sin churn de handshakes → sin flood 429)."""
    print(" [HLS-WORKER] Iniciado")
    global _HLS_WORKER_STOP
    secondary = []          # conexiones secundarias abiertas para el episodio actual
    current_ep = None       # episode_key para el que está abierto el pool
    try:
        while not _HLS_WORKER_STOP:
            if not _HLS_WORKER_QUEUE:
                await asyncio.sleep(0.3)
                continue
            # Priorizar el episodio reproducido más recientemente (evita que un fichero
            # antiguo en cola monopolice el worker mientras otro se está viendo).
            _HLS_WORKER_QUEUE.sort(
                key=lambda k: _HLS_SPARSE.get(k, {}).get("last_active", 0.0),
                reverse=True
            )
            episode_key = _HLS_WORKER_QUEUE[0]  # el más reciente primero
            state = _HLS_SPARSE.get(episode_key)
            info = _HLS_SEG_CACHE.get(episode_key, {})
            msg = info.get("msg_obj")
            if not state or not msg:
                _HLS_WORKER_QUEUE.pop(0)
                continue

            # Pausar SOLO si se solicitó leave explícito (last_active==0).
            # Se QUITA el guard de inactividad (>30s sin segmento) para que el worker
            # siga descargando hacia adelante aunque el cliente esté en pausa o la
            # reproducción esté estable (la descarga corre por delante del playback).
            _last = state.get("last_active", 0)
            if _last == 0:
                printLog(f" [HLS-WORKER] ep={episode_key} leave detectado, pausado")
                _HLS_WORKER_QUEUE.pop(0)
                await _hls_close_secondary(secondary)
                secondary = []
                current_ep = None
                continue

            # Si cambió el episodio activo, cerrar el pool del anterior y abrir el nuevo.
            if episode_key != current_ep:
                await _hls_close_secondary(secondary)
                secondary = []
                current_ep = None

            # refrescar bitmap desde el sidecar (si hubo descarga previa reanudable)
            _hls_refresh_bitmap_from_sidecar(state)
            if len(state["bitmap"]) >= state["total_blocks"]:
                _hls_cache_save(episode_key, state["path"], state["file_size"],
                                state["total_blocks"], _hls_bitmap_serialize(state["bitmap"]), complete=1)
                _HLS_WORKER_QUEUE.pop(0)
                await _hls_close_secondary(secondary)
                secondary = []
                current_ep = None
                continue
            from services.userbot_service import get_active_client
            ubot = await get_active_client()
            if not ubot:
                await asyncio.sleep(0.5)
                continue
            client = getattr(ubot, '_client', ubot)
            # Pocas conexiones: el token bucket ya limita el ritmo; con 2 secundarias
            # (3 totales) hay presión suficiente sin saturar Telegram.
            threads = min(3, await _hls_get_hls_download_threads())

            # Abrir el pool de conexiones UNA vez por episodio (si aún no está abierto).
            if current_ep is None and not secondary:
                secondary = await _hls_open_secondary(client, threads)
                current_ep = episode_key

            # Determinar el hueco a rellenar PRIORIZANDO playback_block (seek)
            pb = state.get("playback_block", 0)
            buffer_blocks = max(1, _HLS_BUFFER_BYTES // _HLS_BLOCK_SIZE)
            # MKV/AVI (no-MP4): ffmpeg no puede indexar un sparse fragmentado a mitad (validado
            # empíricamente: `-ss` input Y output fallan sobre MKV con huecos). Para que ffmpeg
            # pueda transcodecar a mitad, el fichero debe estar CONTIGUO desde el inicio hasta el
            # punto de reproducción. Forzamos descarga secuencial desde bloque 0 para este caso.
            _is_mkv = not info.get("is_mp4", True)
            _prefer = 0 if _is_mkv else pb
            block = _hls_next_missing_block(state, prefer_from=_prefer)
            if block is None:
                _HLS_WORKER_QUEUE.pop(0)
                await _hls_close_secondary(secondary)
                secondary = []
                current_ep = None
                continue

            # Descargar un lote desde `block` (buffer por delante del punto de reproducción)
            lot = min(buffer_blocks, state["total_blocks"] - block)
            start_off = block * _HLS_BLOCK_SIZE
            end_off = min((block + lot) * _HLS_BLOCK_SIZE, state["file_size"])
            try:
                print(f" [TGHirayi-DOWNLOAD] ep={episode_key} lote bloques {block}..{block+lot} ({lot*512//1024}MB) playback={pb}")
                n = await _hls_download_priority_range(ubot, msg, state, start_off, end_off, threads, secondary=secondary)
                if n > 0:
                    # avanzar cursor contiguo
                    while state["cursor_block"] in state["bitmap"] and state["cursor_block"] < state["total_blocks"]:
                        state["cursor_block"] += 1
                    if len(state["bitmap"]) >= state["total_blocks"]:
                        _hls_cache_save(episode_key, state["path"], state["file_size"],
                                        state["total_blocks"], _hls_bitmap_serialize(state["bitmap"]), complete=1)
                        print(f" [TGHirayi-DOWNLOAD] ep={episode_key} COMPLETO")
                        _HLS_WORKER_QUEUE.pop(0)
                        await _hls_close_secondary(secondary)
                        secondary = []
                        current_ep = None
                else:
                    await asyncio.sleep(1.0)
            except Exception as e:
                print(f" [HLS-WORKER] error descargando {episode_key}: {e}")
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass
    finally:
        await _hls_close_secondary(secondary)
        print(" [HLS-WORKER] Detenido")


def _hls_on_progress(episode_key, cur_bytes):
    """Callback de progreso: NO marca el bitmap (la descarga multi-conexión escribe en
    rangos no contiguos). Solo refresca el bitmap real desde el sidecar .chunks."""
    state = _HLS_SPARSE.get(episode_key)
    if not state:
        return
    # La fuente de verdad es el sidecar .chunks de TGHirayi (chunks realmente escritos).
    _hls_refresh_bitmap_from_sidecar(state)


def _hls_refresh_bitmap_from_sidecar(state):
    """Relee el sidecar .chunks (escrito por _parallel_download de TGHirayi) al bitmap."""
    side = state["path"] + ".chunks"
    if os.path.isfile(side):
        try:
            import json as _json
            with open(side, 'r', encoding='utf-8') as f:
                done = set(int(x) for x in _json.load(f))
            state["bitmap"].update(done)
            complete = 1 if len(state["bitmap"]) >= state["total_blocks"] else 0
            _hls_cache_save(state.get("_episode_key", ""), state["path"], state["file_size"],
                            state["total_blocks"], _hls_bitmap_serialize(state["bitmap"]), complete=complete)
        except Exception:
            pass


def _hls_start_worker():
    global _HLS_WORKER_TASK
    if _HLS_WORKER_TASK is None or _HLS_WORKER_TASK.done():
        _HLS_WORKER_TASK = asyncio.get_event_loop().create_task(_hls_worker_loop())


def _hls_enqueue_episode(episode_key):
    if episode_key not in _HLS_WORKER_QUEUE:
        _HLS_WORKER_QUEUE.append(episode_key)
    _hls_start_worker()


async def _hls_get_duration(episode_key, file_path_or_data):
    """Obtiene duración. Primero intenta cache, luego ffprobe sobre datos descargados."""
    if episode_key in _HLS_SEG_CACHE and _HLS_SEG_CACHE[episode_key].get("duration", 0) > 0:
        return _HLS_SEG_CACHE[episode_key]["duration"]
    from services import stream_packager
    loop = asyncio.get_event_loop()
    dur = await loop.run_in_executor(None, stream_packager.get_duration, file_path_or_data)
    if dur > 0 and episode_key in _HLS_SEG_CACHE:
        _HLS_SEG_CACHE[episode_key]["duration"] = dur
    return dur


@app.get(api_url("/api/hls/{episode_key}/playlist.m3u8"))
async def hls_playlist(episode_key: str, prefetch: int = 0, audio: int = 0):
    """Playlist maestra HLS del episodio (por episode_key channelid_msgid)."""
    msg, chat_entity, file_size, dc_id = await _hls_resolve_episode(episode_key)
    if not msg or file_size <= 0:
        raise HTTPException(404, "Episodio no encontrado o sin media")

    info = _HLS_SEG_CACHE.get(episode_key, {})
    duration = info.get("duration", 0)

    # Guardar prefetch_ahead del cliente (configurable) si viene en la request
    if prefetch > 0:
        info["prefetch_ahead"] = prefetch
        _HLS_SEG_CACHE[episode_key] = info

    if duration <= 0:
        print(f" [HLS] Sin duración de Telegram, buscando moov atom...")
        from services.userbot_service import get_active_client
        ubot = await get_active_client()
        if not ubot:
            raise HTTPException(500, "Userbot no disponible")
        duration = await _hls_resolve_duration(ubot, msg, dc_id, file_size, episode_key)
        if duration > 0:
            _HLS_SEG_CACHE[episode_key]["duration"] = duration

    if duration <= 0:
        raise HTTPException(400, "No se pudo obtener duracion del video")

    print(f" [HLS] Generando playlist: {duration}s, file_size={file_size}, key={episode_key}")

    total_segments = max(1, int(duration / _HLS_SEG_DURATION) + 1)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:%d" % _HLS_SEG_DURATION,
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    qseg = f"?audio={audio}" if audio else ""
    for i in range(total_segments):
        lines.append("#EXTINF:%.3f," % _HLS_SEG_DURATION)
        lines.append(f"/api/hls/{episode_key}/segment/{i}.ts{qseg}")
    lines.append("#EXT-X-ENDLIST")

    from fastapi.responses import Response
    return Response(content="\n".join(lines), media_type="application/vnd.apple.mpegurl",
                   headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"})


@app.get(api_url("/api/hls/{episode_key}/segment/{n}.ts"))
async def hls_segment(episode_key: str, n: int, request: Request = None, audio: int = 0):
    """Segmento N: lee el rango del fichero sparse (ya rellenado por el worker) +
    moov cacheado → FakeMP4 → ffmpeg → .ts. Si la zona no está rellenada → 503."""
    info = _HLS_SEG_CACHE.get(episode_key, {})
    file_size = info.get("file_size", 0)
    msg = info.get("msg_obj")
    dc_id = info.get("dc_id")

    if not msg or not file_size:
        msg, chat_entity, file_size, dc_id = await _hls_resolve_episode(episode_key)
        info = _HLS_SEG_CACHE.get(episode_key, {})
    if not msg or file_size <= 0:
        raise HTTPException(404, "Episodio no disponible")

    duration = info.get("duration", 0)
    if duration <= 0:
        raise HTTPException(400, "Duracion no disponible")

    target_time = n * _HLS_SEG_DURATION
    if target_time >= duration:
        raise HTTPException(404, "Segmento fuera de rango")

    # Registrar usuario (para LRU y conteo de uso). Fallback anónimo.
    user_id = "anon"
    try:
        if request is not None:
            from services.auth_service import get_session
            s = get_session(request.cookies.get("tvcat_session", ""))
            if s:
                user_id = str(s.get("user_id", "anon"))
    except Exception:
        user_id = "anon"

    # Limpieza LRU al iniciar (respetando el episodio actual) — una vez por sesión de usuario
    _hls_cache_cleanup(episode_key)

    # Header (moov + sample_table): solo descargar si NO está ya cacheado.
    # Si ya está en _HLS_SEG_CACHE, NO llamar a get_active_client (evita reconectar
    # la conexión Telethon "quemada" → Server closed).
    info = _HLS_SEG_CACHE.get(episode_key, {})
    # Determinar si es MP4 (si no se sabe aún, asumir MP4 y dejar que _hls_ensure_header_cache decida)
    _is_mp4_cached = info.get("is_mp4", True)
    _need_header = False
    if _is_mp4_cached:
        _need_header = not (info.get("ftyp_bytes") and info.get("moov_bytes"))
    else:
        _need_header = not info.get("header_bytes")
    # Si no hay info en absoluto, también necesita header
    if not info:
        _need_header = True
    if _need_header:
        from services.userbot_service import get_active_client
        ubot = await get_active_client()
        if not ubot:
            raise HTTPException(500, "Userbot no disponible")
        info = await _hls_ensure_header_cache(ubot, msg, dc_id, file_size, episode_key)
    # Validar header según tipo
    is_mp4 = info.get("is_mp4", True)
    if is_mp4:
        ftyp_bytes = info.get("ftyp_bytes")
        moov_bytes = info.get("moov_bytes")
        if not ftyp_bytes or not moov_bytes:
            raise HTTPException(500, "No se pudo obtener header MP4")
        header_bytes = None
    else:
        header_bytes = info.get("header_bytes")
        ftyp_bytes = None
        moov_bytes = None
        if not header_bytes:
            raise HTTPException(500, "No se pudo obtener header genérico")

    # Cargar estado sparse y registrar usuario + enqueue worker
    state = _hls_sparse_load(episode_key, file_size)
    state["users"].add(user_id)
    state["playback_block"] = max(0, (download_offset := 0))  # placeholder, se actualiza abajo
    state["last_active"] = _t.time()
    _hls_cache_touch(episode_key)
    _hls_enqueue_episode(episode_key)

    # Calcular rango por-slice (aterrizando en keyframe)
    st = info.get("sample_table")
    if st:
        slice_start, slice_end = _mp4_resolve_slice(st, target_time, _HLS_SEG_DURATION, file_size)
        if slice_start is None or slice_end is None or slice_end <= slice_start:
            st = None
    if not st:
        # fallback: estimación lineal
        if not is_mp4:
            hdr_len = len(info.get("header_bytes") or b"")
            mdat_data_start = hdr_len if hdr_len else 0
            mdat_data_size = file_size - mdat_data_start
            if mdat_data_size <= 0:
                mdat_data_size = file_size
        else:
            mdat_data_start = 40
            mdat_data_size = file_size - 32 - len(moov_bytes or b"") - 8
            if mdat_data_size <= 0:
                mdat_data_size = file_size - 40 - len(moov_bytes or b"")
        slice_start = mdat_data_start + int((target_time / duration) * mdat_data_size)
        slice_end = mdat_data_start + int(((target_time + _HLS_SEG_DURATION) / duration) * mdat_data_size)
        slice_start = (slice_start // 1024) * 1024
        slice_end = ((slice_end // 1024) + 1) * 1024

    # Audio_idx viene del query param (master) y afecta al mapeo a:* de ffmpeg
    audio_idx = max(0, int(audio or 0))
    _all_tracks = info.get("tracks", [])
    _audio_tracks = [t for t in _all_tracks if t.get("type") == "audio"]
    if _audio_tracks and audio_idx >= len(_audio_tracks):
        audio_idx = 0

    # Actualizar playback_block (bloque del punto de reproducción)
    state["playback_block"] = slice_start // _HLS_BLOCK_SIZE

    # Refrescar el bitmap REAL desde el sidecar .chunks (chunks escritos por TGHirayi)
    _hls_refresh_bitmap_from_sidecar(state)

    # Comprobar si la zona del slice está completamente rellenada en el sparse
    start_block = slice_start // _HLS_BLOCK_SIZE
    end_block = (slice_end + _HLS_BLOCK_SIZE - 1) // _HLS_BLOCK_SIZE
    missing = [b for b in range(start_block, end_block) if b not in state["bitmap"]]
    if missing:
        # Zona no rellenada: priorizar descarga y responder 503 (hls.js reintenta)
        state["cursor_block"] = min(missing)
        # Exponer progreso del segmento para el loader del frontend
        try:
            info["loader_seg"] = n
            info["loader_missing"] = len(missing)
            info["loader_total"] = end_block - start_block
            if "loader_initial" not in info or info.get("loader_initial_seg") != n:
                info["loader_initial"] = len(missing)
                info["loader_initial_seg"] = n
        except Exception:
            pass
        printLog(f" [HLS-SEG] seg={n} zona no rellenada (faltan {len(missing)} bloques desde {min(missing)}), 503")
        raise HTTPException(503, "Segmento no disponible aún")
    else:
        # Segmento disponible -> resetear loader_initial si era para este seg
        try:
            if info.get("loader_initial_seg") == n:
                info.pop("loader_initial", None)
                info.pop("loader_initial_seg", None)
                info["loader_missing"] = 0
        except Exception:
            pass

    # Zona rellenada: preparar segmento según contenedor
    is_mp4 = info.get("is_mp4", True)
    # Lock por episodio (serializa ffmpeg para el mismo episodio)
    if "_gen_lock" not in info:
        info["_gen_lock"] = asyncio.Lock()
    gen_lock = info["_gen_lock"]

    async with gen_lock:
        # Incluir audio_idx en el cache del segmento para evitar servir audio equivocado
        seg_suffix = f"_a{audio_idx}" if audio_idx else ""
        seg_path = os.path.join(_HLS_SEG_DIR, "seg_%s_%d%s.ts" % (episode_key, n, seg_suffix))
        if os.path.isfile(seg_path) and os.path.getsize(seg_path) > 0:
            with open(seg_path, 'rb') as f:
                data = f.read()
            from fastapi.responses import Response as _Resp2
            return _Resp2(content=data, media_type="video/mp2t", headers={"Cache-Control": "max-age=3600", "Access-Control-Allow-Origin": "*", "Accept-Ranges": "none", "Content-Length": str(len(data))})

        if not is_mp4:
            # Contenedor genérico (AVI/MKV): remux con ffmpeg usando el sparse como entrada
            from services import stream_packager
            ffmpeg = stream_packager._find_ffmpeg()
            if not ffmpeg:
                raise HTTPException(500, "ffmpeg no encontrado")
            # Seleccionar pista de audio por índice (si hay varias)
            _audio_map = ["-map", "0:v:0", "-map", f"0:a:{audio_idx}"] if _audio_tracks else []
            _audio_opts = ["-c:a", "aac", "-ac", "2", "-b:a", "128k"] if _audio_tracks or True else []
            cmd = [ffmpeg, "-y", "-ss", str(target_time), "-i", state["path"], "-t", str(_HLS_SEG_DURATION)] + _audio_map + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"] + _audio_opts + ["-muxdelay", "0", "-muxpreload", "0", "-output_ts_offset", str(target_time), "-f", "mpegts", seg_path]
            if not _audio_map:
                cmd = [ffmpeg, "-y", "-ss", str(target_time), "-i", state["path"], "-t", str(_HLS_SEG_DURATION), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-ac", "2", "-b:a", "128k", "-muxdelay", "0", "-muxpreload", "0", "-output_ts_offset", str(target_time), "-f", "mpegts", seg_path]
            printLog(f" [HLS-SEG] seg={n} (genérico {info.get('container','')}) ffmpeg: {' '.join(cmd)}")
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0 or not os.path.isfile(seg_path) or os.path.getsize(seg_path) <= 0:
                err_msg = stderr.decode(errors="replace")[-800:] if stderr else "sin stderr"
                # Si el sparse aún no tiene datos para ese seek, es 503 (no listo) no 500
                if "Output file is empty" in err_msg or os.path.getsize(seg_path) == 0 if os.path.isfile(seg_path) else True:
                    print(f" [HLS] ffmpeg genérico vacío seg {n} -> 503 (sparse no listo)")
                    try: os.remove(seg_path)
                    except: pass
                    # marcar como no rellenado para el loader
                    try:
                        info["loader_missing"] = info.get("loader_total", 10)
                        info["loader_seg"] = n
                    except: pass
                    raise HTTPException(503, "Segmento no disponible aún")
                print(f" [HLS] ffmpeg error genérico (seg {n}, rc={proc.returncode}): {err_msg}")
                try: os.remove(seg_path)
                except: pass
                raise HTTPException(500, "Error generando segmento genérico")
            printLog(f" [HLS-SEG] Segmento {n} generado (genérico): {os.path.getsize(seg_path)} bytes")
        else:
            # MP4 con FakeMP4 (rápido, evita re-mux completo)
            length = slice_end - slice_start + 1
            try:
                with open(state["path"], "rb") as f:
                    f.seek(slice_start)
                    mdat_data = f.read(length)
            except Exception as e:
                print(f" [HLS-SEG] error leyendo sparse: {e}")
                raise HTTPException(500, "Error leyendo cache")
            if len(mdat_data) < length:
                print(f" [HLS-SEG] seg={n} sparse incompleto ({len(mdat_data)}/{length}), 503")
                raise HTTPException(503, "Segmento incompleto")
            # Construir MP4 simulado: ftyp + moov_parcheado + mdat
            new_mdat_data_start = 32 + len(moov_bytes) + 8
            delta = new_mdat_data_start - slice_start
            patched_moov = _hls_patch_stco(moov_bytes, delta)
            mdat_size = 8 + len(mdat_data)
            mdat_header = struct.pack('>I', mdat_size) + b'mdat'
            import tempfile
            fd, tmp_fake = tempfile.mkstemp(suffix=".mp4", dir=_HLS_SEG_DIR)
            os.close(fd)
            with open(tmp_fake, 'wb') as f:
                f.write(ftyp_bytes)
                f.write(patched_moov)
                f.write(mdat_header)
                f.write(mdat_data)
            from services import stream_packager
            ffmpeg = stream_packager._find_ffmpeg()
            if not ffmpeg:
                try: os.remove(tmp_fake)
                except: pass
                raise HTTPException(500, "ffmpeg no encontrado")
            # Selección de audio para MP4 (si hay varias pistas)
            _a_map = ["-map", "0:v:0", "-map", f"0:a:{audio_idx}"] if _audio_tracks else []
            _a_opts = ["-c:a", "aac", "-ac", "2", "-b:a", "128k"]
            if _a_map:
                cmd = [ffmpeg, "-y", "-ss", str(target_time), "-i", tmp_fake, "-t", str(_HLS_SEG_DURATION)] + _a_map + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"] + _a_opts + ["-muxdelay", "0", "-muxpreload", "0", "-output_ts_offset", str(target_time), "-f", "mpegts", seg_path]
            else:
                cmd = [ffmpeg, "-y", "-ss", str(target_time), "-i", tmp_fake, "-t", str(_HLS_SEG_DURATION), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-ac", "2", "-b:a", "128k", "-muxdelay", "0", "-muxpreload", "0", "-output_ts_offset", str(target_time), "-f", "mpegts", seg_path]
            printLog(f" [HLS-SEG] seg={n} ffmpeg: {' '.join(cmd)}")
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            try: os.remove(tmp_fake)
            except: pass
            if proc.returncode != 0 or not os.path.isfile(seg_path) or os.path.getsize(seg_path) <= 0:
                err_msg = stderr.decode(errors="replace")[-800:] if stderr else "sin stderr"
                print(f" [HLS] ffmpeg error (seg {n}, rc={proc.returncode}): {err_msg}")
                try: os.remove(seg_path)
                except: pass
                raise HTTPException(500, "Error generando segmento")
            printLog(f" [HLS-SEG] Segmento {n} generado: {os.path.getsize(seg_path)} bytes")

    with open(seg_path, 'rb') as f:
        data = f.read()
    from fastapi.responses import Response
    import asyncio as _aio
    async def _deferred_cleanup2():
        await _aio.sleep(60)
        try: os.remove(seg_path)
        except: pass
    _aio.create_task(_deferred_cleanup2())
    return Response(content=data, media_type="video/mp2t",
                    headers={"Cache-Control": "max-age=3600", "Access-Control-Allow-Origin": "*", "Accept-Ranges": "none", "Content-Length": str(len(data))})



@app.get(api_url("/api/hls/{episode_key}/cache-status"))
async def hls_cache_status(episode_key: str):
    """Estado del fichero sparse (barra de progreso de descarga)."""
    state = _HLS_SPARSE.get(episode_key)
    if not state:
        # intentar cargar del disco/BD
        row = _hls_cache_row(episode_key)
        total = 0
        filled = 0
        if row is not None:
            total = row["total_blocks"]
            filled = len(_hls_bitmap_deserialize(row["bitmap"]))
        return {"episode_key": episode_key, "total_blocks": total, "filled_blocks": filled,
                "progress": (filled / total) if total else 0, "cursor_block": 0, "playback_block": 0}
    total = state["total_blocks"]
    # Refrescar bitmap REAL desde el sidecar .chunks (para la barra refleje lo escrito)
    _hls_refresh_bitmap_from_sidecar(state)
    filled = len(state["bitmap"])
    # Islas de bloques descargados: lista de [start, end) para pintar el mapa real
    islands = _hls_bitmap_islands(state["bitmap"], total)
    # Pistas cacheadas (si se extrajeron)
    info2 = _HLS_SEG_CACHE.get(episode_key, {})
    tr = info2.get("tracks", [])
    audio_tracks = [t for t in tr if t.get("type") == "audio"] if tr else []
    sub_tracks = [t for t in tr if t.get("type") == "subs"] if tr else []
    loader_info = {}
    try:
        if "loader_missing" in info2:
            loader_info = {
                "loader_seg": info2.get("loader_seg", 0),
                "loader_missing": info2.get("loader_missing", 0),
                "loader_total": info2.get("loader_total", 0),
                "loader_initial": info2.get("loader_initial", 0),
            }
    except Exception:
        pass
    result = {
        "episode_key": episode_key,
        "total_blocks": total,
        "filled_blocks": filled,
        "progress": (filled / total) if total else 0,
        "cursor_block": state.get("cursor_block", 0),
        "playback_block": state.get("playback_block", 0),
        "buffer_blocks": _HLS_BUFFER_BYTES // _HLS_BLOCK_SIZE,
        "islands": islands,
        "audio_tracks": audio_tracks,
        "sub_tracks": sub_tracks,
    }
    result.update(loader_info)
    return result


@app.post(api_url("/api/hls/{episode_key}/leave"))
async def hls_leave(episode_key: str):
    """El player notifica que se cerró: pausar descarga en background de forma inmediata."""
    state = _HLS_SPARSE.get(episode_key)
    if state is not None:
        state["last_active"] = 0
    if episode_key in _HLS_WORKER_QUEUE:
        try:
            _HLS_WORKER_QUEUE.remove(episode_key)
        except ValueError:
            pass
        printLog(f" [HLS-WORKER] ep={episode_key} leave solicitado, pausado")
    return {"left": True}


@app.get(api_url("/api/hls/{episode_key}/warmup"))
async def hls_warmup(episode_key: str):
    """Inicia la descarga del fichero sparse SIN reproducir (para prueba/diagnóstico).
    Resuelve episodio, descarga moov, carga sparse y encola el worker."""
    msg, chat_entity, file_size, dc_id = await _hls_resolve_episode(episode_key)
    if not msg or file_size <= 0:
        raise HTTPException(404, "Episodio no disponible")

    from services.userbot_service import get_active_client
    ubot = await get_active_client()
    if not ubot:
        raise HTTPException(500, "Userbot no disponible")

    info = await _hls_ensure_header_cache(ubot, msg, dc_id, file_size, episode_key)
    if not info.get("moov_bytes"):
        raise HTTPException(500, "No se pudo obtener header MP4")

    state = _hls_sparse_load(episode_key, file_size)
    state["fill_full"] = True
    _hls_cache_touch(episode_key)
    _hls_enqueue_episode(episode_key)
    return {"episode_key": episode_key, "file_size": file_size,
            "total_blocks": state["total_blocks"], "warmup": "started"}


@app.get(api_url("/api/hls/{episode_key}/subs"))
async def hls_subs_list(episode_key: str):
    """Lista de subtítulos externos asociados al episodio."""
    import glob
    os.makedirs(_HLS_SUBS_DIR, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(episode_key))
    pattern = os.path.join(_HLS_SUBS_DIR, f"{safe}_*.srt")
    files = glob.glob(pattern)
    langs = []
    for f in files:
        base = os.path.basename(f)
        # formato: {safe}_{lang}.srt
        if base.startswith(safe + "_"):
            lang = base[len(safe)+1:-4]
            langs.append(lang)
    return {"episode_key": episode_key, "subs": langs}

@app.post(api_url("/api/hls/{episode_key}/subs"))
async def hls_subs_upload(episode_key: str, lang: str = "es", file: UploadFile = File(...)):
    """Sube un .srt externo y lo asocia al episodio (lang)."""
    os.makedirs(_HLS_SUBS_DIR, exist_ok=True)
    path = _hls_subs_path(episode_key, lang)
    data = await file.read()
    # validar que parece SRT (contiene -->)
    try:
        text = data.decode('utf-8', errors='replace')
    except Exception:
        text = ""
    if "-->" not in text:
        raise HTTPException(400, "Fichero no parece SRT válido")
    with open(path, 'wb') as f:
        f.write(data)
    printLog(f" [HLS-SUBS] {episode_key} [{lang}] subido {len(data)} bytes")
    return {"episode_key": episode_key, "lang": lang, "size": len(data)}

@app.get(api_url("/api/hls/{episode_key}/subs/{lang}.m3u8"))
async def hls_subs_playlist(episode_key: str, lang: str):
    """Playlist WebVTT para subtítulos externos segmentados cada 6s."""
    path = _hls_subs_path(episode_key, lang)
    if not os.path.isfile(path):
        raise HTTPException(404, "Subtítulo no encontrado")
    info = _HLS_SEG_CACHE.get(episode_key, {})
    duration = info.get("duration", 0)
    if duration <= 0:
        msg, _, file_size, _ = await _hls_resolve_episode(episode_key)
        if not msg:
            raise HTTPException(404, "Episodio no encontrado")
        # intentar duration de Telegram
        duration = 0
        try:
            for attr in getattr(msg.document, 'attributes', []) or []:
                d = getattr(attr, 'duration', None)
                if d:
                    duration = float(d)
                    break
        except Exception:
            pass
        if duration <= 0:
            duration = 3600
    total = max(1, int(duration / _HLS_SEG_DURATION) + 1)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{_HLS_SEG_DURATION}", "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD"]
    for i in range(total):
        lines.append(f"#EXTINF:{_HLS_SEG_DURATION:.3f},")
        lines.append(f"/api/hls/{episode_key}/subs/{lang}/{i}.vtt")
    lines.append("#EXT-X-ENDLIST")
    from fastapi.responses import Response
    return Response(content="\n".join(lines), media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"})

@app.get(api_url("/api/hls/{episode_key}/subs/{lang}/{n}.vtt"))
async def hls_subs_segment(episode_key: str, lang: str, n: int):
    """Segmento WebVTT para subtítulos externos: filtra cues del .srt que solapan [n*6,(n+1)*6)."""
    path = _hls_subs_path(episode_key, lang)
    if not os.path.isfile(path):
        raise HTTPException(404, "Subtítulo no encontrado")
    try:
        text = open(path, 'r', encoding='utf-8', errors='replace').read()
    except Exception:
        raise HTTPException(500, "Error leyendo subtítulo")
    cues = _parse_srt_cues(text)
    seg_start = n * _HLS_SEG_DURATION
    seg_end = seg_start + _HLS_SEG_DURATION
    vtt = _cues_to_webvtt(cues, seg_start, seg_end)
    if vtt is None:
        vtt = "WEBVTT\n\n"
    from fastapi.responses import Response
    return Response(content=vtt, media_type="text/vtt", headers={"Cache-Control": "max-age=3600", "Access-Control-Allow-Origin": "*"})

@app.get(api_url("/api/hls/{episode_key}/subs_embed/{idx}.m3u8"))
async def hls_subs_embed_playlist(episode_key: str, idx: int):
    """Playlist WebVTT para subtítulos embebidos (plex del MKV/MP4) segmentados cada 6s."""
    info = _HLS_SEG_CACHE.get(episode_key, {})
    duration = info.get("duration", 0)
    if duration <= 0:
        msg, _, _, _ = await _hls_resolve_episode(episode_key)
        if not msg:
            raise HTTPException(404, "Episodio no encontrado")
        duration = 3600
    total = max(1, int(duration / _HLS_SEG_DURATION) + 1)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{_HLS_SEG_DURATION}", "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD"]
    for i in range(total):
        lines.append(f"#EXTINF:{_HLS_SEG_DURATION:.3f},")
        lines.append(f"/api/hls/{episode_key}/subs_embed/{idx}/{i}.vtt")
    lines.append("#EXT-X-ENDLIST")
    from fastapi.responses import Response
    return Response(content="\n".join(lines), media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"})

@app.get(api_url("/api/hls/{episode_key}/subs_embed/{idx}/{n}.vtt"))
async def hls_subs_embed_segment(episode_key: str, idx: int, n: int):
    """Segmento WebVTT de subtítulos embebidos. Extrae el WebVTT completo del fichero
    (ffmpeg -ss no respeta -t para subtítulos) y corta las cues del intervalo [n*6,(n+1)*6),
    restando seg_start para que los tiempos queden RELATIVOS al segmento."""
    info = _HLS_SEG_CACHE.get(episode_key, {})
    msg, _, file_size, _ = await _hls_resolve_episode(episode_key)
    if not msg or file_size <= 0:
        raise HTTPException(404, "Episodio no encontrado")
    seg_start = n * _HLS_SEG_DURATION
    seg_end = seg_start + _HLS_SEG_DURATION
    from services import stream_packager
    ffmpeg = stream_packager._find_ffmpeg()
    if not ffmpeg:
        raise HTTPException(500, "ffmpeg no encontrado")
    sparse_path = _HLS_SPARSE.get(episode_key, {}).get("path")
    if not sparse_path or not os.path.isfile(sparse_path):
        raise HTTPException(503, "Cache no disponible aún")

    # Cache del WebVTT completo por (episode_key, idx) para no re-extraer en cada segmento
    _vtt_cache = _HLS_SEG_CACHE.setdefault(episode_key, {}).setdefault("_vtt_full", {})
    # idx es el relativo; buscar stream_index global del track
    tracks = _HLS_SEG_CACHE.get(episode_key, {}).get("tracks", [])
    subs = [t for t in tracks if t.get("type") == "subs"]
    stream_idx = idx
    if subs and idx < len(subs):
        stream_idx = subs[idx].get("stream_index", idx)
    vtt_full = _vtt_cache.get(idx)
    if vtt_full is None:
        import tempfile
        fd, tmp_vtt = tempfile.mkstemp(suffix=".vtt")
        os.close(fd)
        # -map 0:{stream_idx} global (el índice de stream del contenedor)
        cmd = [ffmpeg, "-y", "-i", sparse_path, "-map", f"0:{stream_idx}", "-f", "webvtt", tmp_vtt]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            if os.path.isfile(tmp_vtt) and os.path.getsize(tmp_vtt) > 0:
                vtt_full = open(tmp_vtt, 'r', encoding='utf-8', errors='replace').read()
            else:
                vtt_full = ""
        except Exception:
            vtt_full = ""
        finally:
            try: os.remove(tmp_vtt)
            except: pass
        _vtt_cache[idx] = vtt_full

    cues = _parse_vtt_cues(vtt_full)
    # Recortar al intervalo y re-anclar a 0 con X-TIMESTAMP-MAP para sincronía correcta
    # Sin X-TIMESTAMP-MAP, hls.js trata los tiempos como media time absoluto y se solapan;
    # con X-TIMESTAMP-MAP, los tiempos relativos se mapean a MPEGTS = seg_start*90000
    mpegts = int(seg_start * 90000)
    out = ["WEBVTT", f"X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:{mpegts}", ""]
    for s, e, txt in cues:
        if e <= seg_start or s >= seg_end:
            continue
        cs = max(s, seg_start) - seg_start
        ce = min(e, seg_end) - seg_start
        out.append(f"{_fmt_vtt_time(cs)} --> {_fmt_vtt_time(ce)}")
        out.append(txt)
        out.append("")
    if len(out) <= 3:
        out = ["WEBVTT", f"X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:{mpegts}", ""]
    from fastapi.responses import Response
    return Response(content="\n".join(out), media_type="text/vtt", headers={"Cache-Control": "max-age=3600", "Access-Control-Allow-Origin": "*"})

@app.get(api_url("/api/hls/{episode_key}/master.m3u8"))
async def hls_master(episode_key: str, prefetch: int = 0, audio: int = 0):
    """Master playlist con video + audios embebidos + subtítulos (externos y embebidos)."""
    # Asegurar header/tracks para que la primera master ya liste audios/subs
    try:
        msg_h, _, fs_h, dc_h = await _hls_resolve_episode(episode_key)
        if msg_h and fs_h > 0 and not _HLS_SEG_CACHE.get(episode_key, {}).get("tracks"):
            from services.userbot_service import get_active_client as _gac2
            ub2 = await _gac2()
            if ub2:
                await _hls_ensure_header_cache(ub2, msg_h, dc_h, fs_h, episode_key)
    except Exception:
        pass
    subs_info = await hls_subs_list(episode_key)
    subs = subs_info.get("subs", [])
    info = _HLS_SEG_CACHE.get(episode_key, {})
    tracks = info.get("tracks", [])
    audios = [t for t in tracks if t.get("type") == "audio"]
    embedded_subs = [t for t in tracks if t.get("type") == "subs"]
    import json as _jd
    printLog(" [HLS-MASTER] tracks=" + _jd.dumps(tracks) + " subs=" + str(subs))
    lines = ["#EXTM3U"]
    # Audios embebidos (si se detectaron)
    for a in audios:
        lang = a.get("lang", "und")
        idx = a.get("idx", 0)
        default = "YES" if idx == int(audio or 0) else "NO"
        lines.append(f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audios",LANGUAGE="{lang}",NAME="Audio {lang} #{idx}",DEFAULT={default},AUTOSELECT=YES,URI="/api/hls/{episode_key}/playlist.m3u8?audio={idx}&prefetch={prefetch}"')
    for lang in subs:
        lines.append(f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="{lang}",NAME="{lang} (ext)",DEFAULT=NO,AUTOSELECT=YES,URI="/api/hls/{episode_key}/subs/{lang}.m3u8"')
    for s in embedded_subs:
        lang = s.get("lang", "und")
        idx = s.get("idx", 0)
        lines.append(f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="{lang}",NAME="{lang} #{idx}",DEFAULT=NO,AUTOSELECT=YES,URI="/api/hls/{episode_key}/subs_embed/{idx}.m3u8"')
    q = f"?prefetch={prefetch}" if prefetch else ""
    # Propagar audio selecc. a la variante
    q2 = f"?audio={audio}&prefetch={prefetch}" if prefetch else (f"?audio={audio}" if audios else q)
    has_subs = bool(subs or embedded_subs)
    extra = ""
    if audios:
        extra += ',AUDIO="audios"'
    if has_subs:
        extra += ',SUBTITLES="subs"'
    lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH=800000,CODECS="avc1.64001f,mp4a.40.2"{extra}')
    lines.append(f"/api/hls/{episode_key}/playlist.m3u8{q2}")
    from fastapi.responses import Response
    return Response(content="\n".join(lines), media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"})


@app.get(api_url("/api/hls/{episode_key}/metadata"))
async def hls_metadata(episode_key: str):
    """Metadata de pistas de audio/subtitulos del episodio (por episode_key)."""
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM item_episodes WHERE episode_key=?", (episode_key,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Episodio no encontrado")

    int_id = row["id"]
    prepared = bool(row["prepared_by_tghirayi"]) if "prepared_by_tghirayi" in row.keys() else False
    tgh_version = row["tghirayi_version"] if "tghirayi_version" in row.keys() else ""
    vcodec = row["video_codec"] if "video_codec" in row.keys() else ""
    is_mkv = bool(row["is_mkv"]) if "is_mkv" in row.keys() else False

    audio, subs = [], []
    try:
        conn2 = get_conn()
        tracks = conn2.execute(
            "SELECT * FROM episode_tracks WHERE episode_id=? AND track_type='audio'", (int_id,)
        ).fetchall()
        for t in tracks:
            audio.append({
                "index": t["track_index"], "language": t["language"],
                "title": t["title"], "codec": t["codec"],
                "default": bool(t["is_default"])
            })
        sub_tracks = conn2.execute(
            "SELECT * FROM episode_tracks WHERE episode_id=? AND track_type='subtitle'", (int_id,)
        ).fetchall()
        for t in sub_tracks:
            subs.append({
                "index": t["track_index"], "language": t["language"],
                "title": t["title"]
            })
        conn2.close()
    except Exception:
        pass

    return {
        "audio": audio, "subs": subs,
        "prepared": prepared, "tghirayi_version": tgh_version,
        "video_codec": vcodec, "is_mkv": is_mkv
    }


# === Helper: verificar si thumbnail está cacheado ===
def _thumb_exists(telegram_msg_id):
    """Retorna True si el thumbnail del episodio está cacheado en catalog_assets."""
    from services.catalog_service import get_conn
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM catalog_assets WHERE telegram_msg_id=? AND asset_type='episode_thumb' LIMIT 1",
            (telegram_msg_id,)).fetchone()
        if row:
            conn.close()
            return True
        conn.close()
    except Exception:
        pass
    for db_path, _ in get_enabled_plugin_dbs_with_names():
        if not os.path.isfile(db_path):
            continue
        try:
            pconn = sqlite3.connect(db_path)
            row = pconn.execute(
                "SELECT 1 FROM catalog_assets WHERE telegram_msg_id=? AND asset_type='episode_thumb' LIMIT 1",
                (telegram_msg_id,)).fetchone()
            pconn.close()
            if row:
                return True
        except Exception:
            pass
    return False


# === Helper: buscar episodios en BDs de plugins (fallback cuando main DB no tiene datos) ===
def _find_episodes_in_plugin_dbs(item_id):
    """Busca episodios en TODAS las BDs de plugins habilitadas. Devuelve lista de dicts."""
    from services.catalog_service import get_conn, _derive_episode_key
    results = []
    for db_path, plugin_name in get_enabled_plugin_dbs_with_names():
        if not os.path.isfile(db_path):
            continue
        try:
            pconn = sqlite3.connect(db_path)
            pconn.row_factory = sqlite3.Row
            prow = pconn.execute("SELECT id FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
            if prow:
                plugin_int = str(prow["id"])
                eps = [dict(e) for e in pconn.execute(
                    "SELECT id, episode_number, season_number, title, duration, telegram_msg_id, telegram_link, file_size "
                    "FROM item_episodes WHERE item_id=? OR item_id=? ORDER BY season_number, episode_number",
                    (item_id, plugin_int)).fetchall()]
                for ep in eps:
                    ep["has_thumb"] = 1 if (ep.get("telegram_msg_id") and _thumb_exists(ep["telegram_msg_id"])) else 0
                    ep["episode_key"] = _derive_episode_key(ep.get("telegram_link"))
                if eps:
                    results = eps
                    pconn.close()
                    break
            pconn.close()
        except Exception as e:
            print(f" [FALLBACK] Error en plugin {plugin_name}: {e}")
    return results


def _find_episode_by_id_in_plugin_dbs(episode_id):
    """Busca un episodio por su id INTEGER en BDs de plugins. Retorna dict o None."""
    for db_path, plugin_name in get_enabled_plugin_dbs_with_names():
        if not os.path.isfile(db_path):
            continue
        try:
            pconn = sqlite3.connect(db_path)
            pconn.row_factory = sqlite3.Row
            ep = pconn.execute(
                "SELECT ie.*, i.telegram_link as item_link, i.item_id "
                "FROM item_episodes ie "
                "JOIN unified_catalog i ON i.id = CAST(ie.item_id AS INTEGER) OR i.item_id = ie.item_id "
                "WHERE ie.id=?", (episode_id,)).fetchone()
            if ep:
                result = dict(ep)
                pconn.close()
                return result
            pconn.close()
        except Exception as e:
            print(f" [FALLBACK] Error buscando episode {episode_id} en {plugin_name}: {e}")
    return None


@app.get(api_url("/api/movie/{item_id}"))
async def get_item_details(item_id: str, request: Request = None):
    from services.catalog_service import get_conn
    from services.auth_service import get_session
    conn = get_conn()
    row = conn.execute("SELECT * FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    result = dict(row)
    # Verificar si está en favoritos del usuario actual
    is_fav = False
    if request:
        session = get_session(request.cookies.get("tvcat_session",""))
        if session:
            profile_id = session.get("profile_id") or session["user_id"]
            fav_row = conn.execute("SELECT 1 FROM tvcat_favorites WHERE profile_id=? AND item_id=?", (profile_id, item_id)).fetchone()
            is_fav = fav_row is not None
    result["favorite"] = is_fav
    # Buscar episodios por item_id TEXT o por id INTEGER (bug scanner: usa cat_id INTEGER)
    int_id_str = str(row["id"])
    raw_eps = [dict(e) for e in conn.execute(
        "SELECT id, episode_number, season_number, title, duration, telegram_msg_id, telegram_link, file_size FROM item_episodes WHERE item_id=? OR item_id=? ORDER BY season_number, episode_number",
        (item_id, int_id_str)).fetchall()]
    if not raw_eps:
        # Fallback: buscar en BDs de plugins
        raw_eps = _find_episodes_in_plugin_dbs(item_id)
    for ep in raw_eps:
        ep["video_src"] = f"/api/stream/episode/{ep['id']}"
        ep["has_thumb"] = 1 if (ep["telegram_msg_id"] and _thumb_exists(ep["telegram_msg_id"])) else 0
        ep["item_id"] = item_id
    result["episodes"] = raw_eps
    variants, rep_id = _get_variants_and_rep(conn, item_id)
    result["variants"] = variants
    result["representative_id"] = rep_id
    conn.close()
    return result


@app.get(api_url("/api/media/{item_id}/episodes"))
async def get_item_episodes(item_id: str):
    from services.catalog_service import get_conn, _derive_episode_key
    conn = get_conn()
    row = conn.execute("SELECT group_title_flat FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    gtf = row["group_title_flat"]
    seasons = {}
    if gtf:
        vars_rows = conn.execute("SELECT item_id, title, season_display FROM unified_catalog WHERE group_title_flat=? ORDER BY id ASC", (gtf,)).fetchall()
    else:
        vars_rows = [{"item_id": item_id, "title": "", "season_display": ""}]
    for vr in vars_rows:
        vid = vr["item_id"]
        # Obtener el id INTEGER para buscar episodios (bug scanner: usa cat_id INTEGER)
        cat_int = conn.execute("SELECT id FROM unified_catalog WHERE item_id=?", (vid,)).fetchone()
        int_id_str = str(cat_int["id"]) if cat_int else vid
        label = vr["season_display"] or vr["title"] or f"Season {len(seasons)+1}"
        eps = [dict(e) for e in conn.execute(
            "SELECT id, item_id, episode_key, episode_number, season_number, title, duration, telegram_msg_id, telegram_link, caption, file_size FROM item_episodes WHERE item_id=? OR item_id=? ORDER BY episode_number ASC", (vid, int_id_str)).fetchall()]
        if not eps:
            # Fallback: buscar en BDs de plugins
            eps = _find_episodes_in_plugin_dbs(vid)
        for ep in eps:
            ep["video_src"] = f"/api/stream/episode/{ep['id']}"
            ep["has_thumb"] = 1 if (ep["telegram_msg_id"] and _thumb_exists(ep["telegram_msg_id"])) else 0
            ep["item_id"] = vid
            if not ep.get("episode_key"):
                ep["episode_key"] = _derive_episode_key(ep.get("telegram_link"))
        if eps:
            seasons[label] = eps
    conn.close()
    return seasons

# --- Thumbnail extraction (async cache) ---
async def _extract_and_cache_thumb(telegram_msg_id: int, telegram_link: str, tg=None):
    """Extrae thumbnail de un mensaje Telegram y lo cachea en catalog_assets."""
    if telegram_msg_id in _thumb_pending_extractions:
        return
    _thumb_pending_extractions.add(telegram_msg_id)
    try:
        async with _thumb_extract_semaphore:
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
                return

            if tg is None:
                from services.userbot_service import get_active_client
                tg = await get_active_client()
                if not tg:
                    return

            try:
                async with _HLS_DOWNLOAD_LOCK:  # serializar con HLS (mismo cliente Telethon)
                    msg = await tg.get_messages(chat_entity, ids=telegram_msg_id)
            except Exception:
                return
            if isinstance(msg, list):
                msg = msg[0] if msg else None
            if not msg or not msg.media or not hasattr(msg.media, "document"):
                return

            doc = msg.media.document
            if not doc.thumbs:
                return

            thumb_type = "x" if any(t.type == "x" for t in doc.thumbs) else "m"

            from telethon.tl.types import InputDocumentFileLocation
            loc = InputDocumentFileLocation(
                id=doc.id,
                access_hash=doc.access_hash,
                file_reference=doc.file_reference,
                thumb_size=thumb_type
            )
            import io
            buffer = io.BytesIO()
            try:
                async with _HLS_DOWNLOAD_LOCK:  # serializar con HLS (mismo cliente Telethon)
                    async for chunk in tg.iter_download(loc, offset=0, chunk_size=256 * 1024):
                        if chunk:
                            buffer.write(chunk)
            except Exception:
                return
            blob = buffer.getvalue()
            if not blob:
                return

            if blob[:2] == b'\xff\xd8':
                mime = "image/jpeg"
            elif blob[:4] == b'\x89PNG':
                mime = "image/png"
            elif blob[:4] == b'RIFF':
                mime = "image/webp"
            else:
                mime = "image/jpeg"

            from services.catalog_service import get_conn
            conn = get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO catalog_assets (telegram_msg_id, asset_type, asset_index, image_blob, mime_type) VALUES (?, 'episode_thumb', 0, ?, ?)",
                    (telegram_msg_id, blob, mime))
                conn.commit()
            except Exception:
                pass
            conn.close()

            for db_path, _ in get_enabled_plugin_dbs_with_names():
                if not os.path.isfile(db_path):
                    continue
                try:
                    pconn = sqlite3.connect(db_path, timeout=5)
                    pconn.execute(
                        "INSERT OR REPLACE INTO catalog_assets (telegram_msg_id, asset_type, asset_index, image_blob, mime_type) VALUES (?, 'episode_thumb', 0, ?, ?)",
                        (telegram_msg_id, blob, mime))
                    pconn.commit()
                    pconn.close()
                except Exception:
                    pass
    finally:
        _thumb_pending_extractions.discard(telegram_msg_id)


# --- API: Episode Thumbnail ---
@app.get(api_url("/api/media/episode/thumbnail/{telegram_msg_id}"))
async def serve_episode_thumbnail(telegram_msg_id: int):
    """Thumbnail de episodio. Si no está cacheado, gatilla descarga async y devuelve 404."""
    from services.catalog_service import get_conn
    conn = get_conn()
    asset = conn.execute(
        "SELECT image_blob, mime_type FROM catalog_assets WHERE telegram_msg_id=? AND asset_type='episode_thumb' LIMIT 1",
        (telegram_msg_id,)).fetchone()
    if asset and asset["image_blob"]:
        blob = asset["image_blob"]
        mime = asset["mime_type"] or "image/jpeg"
        conn.close()
        return Response(content=blob, media_type=mime)
    for db_path, _ in get_enabled_plugin_dbs_with_names():
        if not os.path.isfile(db_path):
            continue
        try:
            pconn = sqlite3.connect(db_path)
            pconn.row_factory = sqlite3.Row
            passet = pconn.execute(
                "SELECT image_blob, mime_type FROM catalog_assets WHERE telegram_msg_id=? AND asset_type='episode_thumb' LIMIT 1",
                (telegram_msg_id,)).fetchone()
            if passet and passet["image_blob"]:
                blob = passet["image_blob"]
                mime = passet["mime_type"] or "image/jpeg"
                pconn.close()
                conn.close()
                return Response(content=blob, media_type=mime)
            pconn.close()
        except Exception:
            pass
    # No cacheado: buscar telegram_link para gatillar descarga async
    telegram_link = None
    for db_path, _ in get_enabled_plugin_dbs_with_names():
        if not os.path.isfile(db_path):
            continue
        try:
            pconn = sqlite3.connect(db_path)
            pconn.row_factory = sqlite3.Row
            row = pconn.execute("SELECT telegram_link FROM item_episodes WHERE telegram_msg_id=?", (telegram_msg_id,)).fetchone()
            pconn.close()
            if row and row["telegram_link"]:
                telegram_link = row["telegram_link"]
                break
        except Exception:
            pass
    if telegram_link:
        asyncio.create_task(_extract_and_cache_thumb(telegram_msg_id, telegram_link))
    conn.close()
    raise HTTPException(status_code=404, detail="Thumbnail no disponible")


# --- API: Cover ---
@app.get(api_url("/api/cover/{item_id}"))
async def get_cover(item_id: str):
    from services.catalog_service import get_conn
    conn = get_conn()
    data = conn.execute("SELECT source, telegram_msg_id FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
    conn.close()
    if not data:
        raise HTTPException(404)
    source = data["source"]
    if source == "demo":
        color = abs(hash(item_id)) % 0xFFFFFF
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450" viewBox="0 0 300 450"><rect fill="#{color:06x}" width="300" height="450"/><text fill="white" font-family="Outfit,sans-serif" font-size="24" text-anchor="middle" x="150" y="225">{item_id[-4:] if len(item_id)>4 else item_id}</text></svg>'
        return Response(content=svg, media_type="image/svg+xml")

    # Buscar portada en la CACHÉ CENTRAL (contiene todos los assets copiados de plugins)
    msg_id = data["telegram_msg_id"]
    from services.catalog_service import get_conn
    cache_conn = get_conn()
    cache_conn.row_factory = sqlite3.Row
    try:
        asset = None
        # -999/-1000 son marcadores de cover genérico (topo 0) -> no buscar asset -999 (colisiona con PEER), ir directo a fallback
        if msg_id and int(msg_id) not in (-999, -1000):
            asset = cache_conn.execute("SELECT image_blob, mime_type FROM catalog_assets WHERE telegram_msg_id=? AND asset_type='cover' LIMIT 1", (msg_id,)).fetchone()
        if not asset and msg_id and int(msg_id) not in (-999, -1000):
            asset = cache_conn.execute("SELECT image_blob, mime_type FROM catalog_assets WHERE telegram_msg_id=? LIMIT 1", (msg_id,)).fetchone()
        if asset and asset["image_blob"]:
            blob = asset["image_blob"]
            mime = asset["mime_type"] or "image/jpeg"
            cache_conn.close()
            return Response(content=blob, media_type=mime)
    except Exception as e:
        print(f" [COVER] Cache error: {e}")
    cache_conn.close()

    # JIT Download: probar todas las sesiones disponibles (con rate limiting global)
    if source != "demo" and msg_id and int(msg_id) not in (-999, -1000):
        try:
            global _jit_last_call
            async with _jit_semaphore:
                # Rate limiting: esperar si es muy pronto desde la última llamada
                now = asyncio.get_event_loop().time()
                elapsed = now - _jit_last_call
                if elapsed < _get_jit_interval():
                    await asyncio.sleep(_get_jit_interval() - elapsed)
                _jit_last_call = asyncio.get_event_loop().time()

                c4 = get_conn()
                c4.row_factory = sqlite3.Row
                link_row = c4.execute("SELECT telegram_link FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
                c4.close()
                tel_link = link_row["telegram_link"] if link_row else ""
                if tel_link and msg_id:
                    import re
                    chat_entity = None
                    if "/c/" in tel_link:
                        m = re.search(r"/c/(\d+)/", tel_link)
                        if m:
                            chat_entity = int("-100" + m.group(1))
                    else:
                        m = re.search(r"t\.me/([^/]+)/", tel_link)
                        if m:
                            chat_entity = m.group(1)
                    if chat_entity:
                        from services.userbot_service import get_active_client
                        ubot = await get_active_client()
                        if ubot:
                            try:
                                async with _HLS_DOWNLOAD_LOCK:  # serializar con HLS (mismo cliente Telethon)
                                    entity = await ubot.get_entity(chat_entity)
                                    cover_msg = await ubot.get_messages(entity, ids=int(msg_id))
                                if cover_msg and getattr(cover_msg, 'photo', None):
                                    async with _HLS_DOWNLOAD_LOCK:
                                        photo_bytes = await ubot.download_media(cover_msg)
                                    if photo_bytes:
                                        from PIL import Image
                                        import io
                                        buf = io.BytesIO()
                                        with Image.open(io.BytesIO(photo_bytes)) as img:
                                            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                                            img.save(buf, "WEBP", quality=85)
                                            webp_bytes = buf.getvalue()
                                        cc = get_conn()
                                        cc.execute("INSERT OR REPLACE INTO catalog_assets (telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, source) VALUES (?, 'cover', 0, ?, 'image/webp', ?, ?)", (msg_id, webp_bytes, len(webp_bytes), source))
                                        cc.commit()
                                        cc.close()
                                        print(f" [JIT COVER] Portada descargada para msg_id {msg_id}")
                                        return Response(content=webp_bytes, media_type="image/webp")
                            except Exception as e:
                                print(f" [JIT COVER] Error sesion {sess.get('name','?')}: {e}")
                                await asyncio.sleep(0.3)
        except Exception as e:
            print(f" [JIT COVER] Error general: {e}")

    # Redirección a api_cover (portada externa)
    try:
        c3 = get_conn()
        api_row = c3.execute("SELECT metadata_json FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
        c3.close()
        if api_row:
            meta = json.loads(api_row["metadata_json"] or "{}")
            api_cover = meta.get("api_cover", "")
            if api_cover and api_cover.startswith("http"):
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url=api_cover.replace("t_thumb", "t_cover_big"))
    except Exception as e:
        print(f" [COVER] API error: {e}")

    # Fallback: portada genérica por categoría
    try:
        c2 = get_conn()
        cat_row = c2.execute("SELECT category FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
        c2.close()
        cat = (cat_row["category"] if cat_row else "").lower()
        fb_id = -1 if cat in ("juegos","games","game") else (-2 if cat in ("comic","kiosko","book","manga") else -3)
        fb = get_conn().execute("SELECT image_blob, mime_type FROM catalog_assets WHERE telegram_msg_id=? AND asset_type='cover' LIMIT 1", (fb_id,)).fetchone()
        if fb and fb[0]:
            return Response(content=fb[0], media_type=fb[1] or "image/jpeg")
    except Exception as e:
        print(f" [COVER] Fallback error: {e}")

    raise HTTPException(404)


# --- API: Favorites, Watch, Sync, Config, Admin, Visibility ---
@app.post(api_url("/api/favorites/toggle"))
async def favorites_toggle(request: Request):
    from services.favorites_service import toggle_favorite
    from services.auth_service import get_session
    from services.catalog_service import get_conn
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    body = await request.json()
    item_id = body.get("item_id","")
    is_fav = toggle_favorite(session.get("profile_id") or session["user_id"], item_id)
    # Obtener representative_id para sincronizar UI
    rep_id = item_id
    try:
        conn = get_conn()
        row = conn.execute("SELECT representative_id FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
        if row and row["representative_id"]:
            rep_id = row["representative_id"]
        conn.close()
    except:
        pass
    return {"success": True, "is_favorite": is_fav, "representative_id": rep_id}

@app.get(api_url("/api/favorites/list"))
async def favorites_list(request: Request):
    from services.favorites_service import get_favorites
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    items = get_favorites(session.get("profile_id") or session["user_id"])
    return {"items": items, "count": len(items)}

@app.get(api_url("/api/watch/history"))
async def watch_history(request: Request):
    from services.favorites_service import get_watch_history
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    return {"history": get_watch_history(session.get("profile_id") or session["user_id"])}

@app.post(api_url("/api/watch/progress"))
async def watch_progress(request: Request):
    from services.favorites_service import update_progress
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session: raise HTTPException(401)
    body = await request.json()
    print(f" [WATCH_PROGRESS] POST recibido: item={body.get('item_id')}, episode_key={body.get('episode_key')}, episode_id={body.get('episode_id')}, progress={body.get('progress')}, duration={body.get('duration')}, completed={body.get('completed')}, watched_state={body.get('watched_state')}")
    update_progress(session.get("profile_id") or session["user_id"], body.get("item_id",""), body.get("episode_key") or "", body.get("episode_id",0), float(body.get("progress",0)), float(body.get("duration",0)), int(body.get("completed",0)), int(body.get("watched_state",0)))
    return {"success": True}

@app.get(api_url("/api/admin/log/tail"))
async def admin_log_tail(request: Request, lines: int = 1000):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role") != "admin":
        raise HTTPException(403, "Solo admin")
    log_path = os.path.join(os.path.dirname(__file__), "logs", "gateway.log")
    if not os.path.isfile(log_path):
        return {"lines": []}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail = all_lines[-max(1, min(lines, 5000)):]
        return {"lines": [l.rstrip("\n") for l in tail]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post(api_url("/api/admin/restart"))
async def admin_restart(request: Request):
    from services.auth_service import get_session
    import sys
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role") != "admin":
        raise HTTPException(403, "Solo admin")
    print(" [ADMIN] Reinicio Python solicitado por admin")
    # Responder antes de reiniciar
    async def _do_restart():
        await asyncio.sleep(0.5)
        try:
            os.execv(sys.executable, [sys.executable, "gateway.py"] + sys.argv[1:])
        except Exception:
            sys.exit(1)
    asyncio.create_task(_do_restart())
    return {"success": True, "message": "Reiniciando..."}

@app.post(api_url("/api/admin/restart-custom"))
async def admin_restart_custom(request: Request):
    from services.auth_service import get_session
    import subprocess, shlex
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role") != "admin":
        raise HTTPException(403, "Solo admin")
    body = await request.json()
    cmd = (body.get("command") or "").strip()
    if not cmd:
        cmd = "docker restart tvcat2"
    print(f" [ADMIN] Reinicio custom solicitado: {cmd}")
    try:
        # Ejecutar sin bloquear
        subprocess.Popen(cmd, shell=True)
        return {"success": True, "message": f"Comando lanzado: {cmd}"}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get(api_url("/api/cache/rebuild-status"))
async def rebuild_status():
    return {"running": _rebuild_state.get("running"), "done": _rebuild_state.get("done"), "error": _rebuild_state.get("error")}

@app.get(api_url("/api/sync/refresh"))
async def sync_refresh():
    _plugin_loader.sync_all()
    from services.catalog_service import rebuild_cache
    rebuild_cache(_plugin_loader)
    return {"success": True, "message": xTranslate("Sincronización completada")}

@app.get(api_url("/api/sync/check-updates"))
async def check_updates():
    return _plugin_loader.check_updates()

_USER_PREF_KEYS = ("display_name", "avatar", "avatar_url", "color", "category_preferences", "watch_threshold_min", "watch_threshold_max", "hls_title_prefs")

@app.get(api_url("/api/config"))
async def get_config(request: Request):
    import platform
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f: cfg = json.load(f)
    cfg["hostname"] = platform.node() or "unknown"
    # Si hay sesión, el perfil del usuario (nick/avatar/color) tiene prioridad sobre la config global.
    from services.auth_service import get_session, get_user_prefs, save_user_prefs
    token = request.cookies.get("tvcat_session", "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    session = get_session(token) if token else None
    if session:
        user_id = session.get("user_id")
        # Migración 1 vez: si el fichero global guardaba el perfil (sistema previo por-usuario no existía),
        # ese perfil pertenecía al admin; se traspasa a sus prefs y se limpia del fichero global.
        legacy = {k: cfg[k] for k in _USER_PREF_KEYS if k in cfg}
        if legacy and session.get("role") == "admin":
            prefs = get_user_prefs(user_id)
            if not prefs.get("display_name") and not prefs.get("avatar") and not prefs.get("avatar_url"):
                save_user_prefs(user_id, legacy)
            try:
                for k in _USER_PREF_KEYS:
                    cfg.pop(k, None)
                os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
                with open(CONFIG_PATH, "w") as f: json.dump({kk: vv for kk, vv in cfg.items() if kk != "hostname"}, f, indent=2)
            except Exception:
                pass
        # Con sesión nunca se exponen los campos de perfil del fichero global, solo los del usuario.
        for k in _USER_PREF_KEYS:
            cfg.pop(k, None)
        prefs = get_user_prefs(user_id)
        for k in _USER_PREF_KEYS:
            if k in prefs:
                cfg[k] = prefs[k]
    return cfg

@app.post(api_url("/api/config"))
async def save_config(request: Request):
    body = await request.json()
    # Si hay sesión, guardar el perfil de usuario (nick/avatar/color) por usuario en BD;
    # el resto se mantiene en la config global (userbot, etc.).
    from services.auth_service import get_session, save_user_prefs
    token = request.cookies.get("tvcat_session", "")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    session = get_session(token) if token else None
    if session:
        user_prefs = {k: body[k] for k in _USER_PREF_KEYS if k in body}
        if user_prefs:
            save_user_prefs(session.get("user_id"), user_prefs)
        global_body = {k: v for k, v in body.items() if k not in _USER_PREF_KEYS}
        if global_body:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f: json.dump(global_body, f, indent=2)
        return {"success": True}
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f: json.dump(body, f, indent=2)
    return {"success": True}

@app.get(api_url("/api/admin/users"))
async def admin_users(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    from services.catalog_service import get_conn
    conn = get_conn()
    users = [dict(r) for r in conn.execute("""
        SELECT u.id, u.username, u.role, u.profile_id, p.name as profile_name
        FROM tvcat_users u LEFT JOIN tvcat_profiles p ON p.id = u.profile_id
        ORDER BY u.id
    """).fetchall()]
    conn.close()
    return {"users": users}

@app.post(api_url("/api/admin/users/create"))
async def admin_create_user(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    body = await request.json()
    if not body.get("username") or not body.get("password"): raise HTTPException(400, detail="Campos requeridos")
    from services.catalog_service import get_conn
    conn = get_conn()
    try:
        profile_id = body.get("profile_id")
        role = "user"
        if profile_id:
            prow = conn.execute("SELECT is_admin FROM tvcat_profiles WHERE id=?", (profile_id,)).fetchone()
            if prow and prow["is_admin"]:
                role = "admin"
        conn.execute("INSERT INTO tvcat_users (username, password, role, profile_id) VALUES (?,?,?,?)",
                     (body["username"], body["password"], role, profile_id))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        conn.close()
        raise HTTPException(400, detail=str(e))

@app.post(api_url("/api/admin/users/delete"))
async def admin_delete_user(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    body = await request.json()
    from services.catalog_service import get_conn
    conn = get_conn()
    for tbl in ["tvcat_sessions", "tvcat_favorites", "watch_progress"]:
        conn.execute(f"DELETE FROM {tbl} WHERE profile_id=?", (body["user_id"],))
    conn.execute("DELETE FROM tvcat_users WHERE id=? AND role!='admin'", (body["user_id"],))
    conn.commit()
    conn.close()
    return {"success": True}

# --- Perfiles de contenido (etiquetas de agrupación) ---
@app.get(api_url("/api/admin/profiles"))
async def admin_profiles(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    from services.catalog_service import get_conn
    conn = get_conn()
    profiles = [dict(r) for r in conn.execute("SELECT id, name, is_admin FROM tvcat_profiles ORDER BY id").fetchall()]
    conn.close()
    return {"profiles": profiles}

@app.post(api_url("/api/admin/profiles/create"))
async def admin_create_profile(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name: raise HTTPException(400, detail="Nombre requerido")
    from services.catalog_service import get_conn
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO tvcat_profiles (name) VALUES (?)", (name,))
        conn.commit()
        pid = cur.lastrowid
        conn.close()
        return {"success": True, "id": pid}
    except Exception as e:
        conn.close()
        raise HTTPException(400, detail=str(e))

@app.post(api_url("/api/admin/profiles/rename"))
async def admin_rename_profile(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not body.get("id") or not name: raise HTTPException(400)
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("UPDATE tvcat_profiles SET name=? WHERE id=?", (name, body["id"]))
    conn.commit(); conn.close()
    return {"success": True}

@app.post(api_url("/api/admin/profiles/delete"))
async def admin_delete_profile(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    body = await request.json()
    pid = body.get("id")
    if not pid: raise HTTPException(400)
    from services.catalog_service import get_conn
    conn = get_conn()
    prow = conn.execute("SELECT is_admin FROM tvcat_profiles WHERE id=?", (pid,)).fetchone()
    if prow and prow["is_admin"]:
        conn.close()
        raise HTTPException(400, detail="El perfil de administrador no se puede eliminar.")
    cnt = conn.execute("SELECT COUNT(*) FROM tvcat_users WHERE profile_id=?", (pid,)).fetchone()[0]
    if cnt > 0:
        conn.close()
        raise HTTPException(400, detail=f"Hay {cnt} usuario(s) asignado(s) a este perfil. Reasigna antes de eliminarlo.")
    conn.execute("DELETE FROM tvcat_profiles WHERE id=?", (pid,))
    conn.execute("DELETE FROM tvcat_settings WHERE key=?", (f"access_{pid}",))
    conn.commit(); conn.close()
    return {"success": True}

@app.post(api_url("/api/admin/users/assign-profile"))
async def admin_assign_profile(request: Request):
    from services.auth_service import get_session
    session = get_session(request.cookies.get("tvcat_session",""))
    if not session or session.get("role")!="admin": raise HTTPException(403)
    body = await request.json()
    if not body.get("user_id") or not body.get("profile_id"): raise HTTPException(400)
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("UPDATE tvcat_users SET profile_id=? WHERE id=?", (body["profile_id"], body["user_id"]))
    conn.commit(); conn.close()
    return {"success": True}

# --- Filtros de contenidos (3 niveles) ---
def _auth_user(request: Request):
    from services.auth_service import get_session
    return get_session(request.cookies.get("tvcat_session",""))

@app.get(api_url("/api/content/access"))
async def get_content_access(request: Request, profile: int = 0):
    session = _auth_user(request)
    if not session or session.get("role") != "admin": raise HTTPException(403)
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (f"access_{profile}",)).fetchone()
    conn.close()
    if row:
        try: return json.loads(row["value"])
        except Exception: pass
    return {}

@app.post(api_url("/api/content/access"))
async def set_content_access(request: Request):
    session = _auth_user(request)
    if not session or session.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    profile = int(body.get("profile") or 0)
    data = body.get("data") or {}
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", (f"access_{profile}", json.dumps(data)))
    conn.commit(); conn.close()
    return {"success": True}

@app.get(api_url("/api/content/available"))
async def get_content_available(request: Request):
    session = _auth_user(request)
    if not session: raise HTTPException(401)
    from services.catalog_service import get_conn
    conn = get_conn()
    # Nivel 1: acceso del perfil (para usuarios no-admin) — es la base de lo disponible
    result = {}
    if session.get("role") != "admin" and session.get("profile_id"):
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (f"access_{session['profile_id']}",)).fetchone()
        if row:
            try:
                acc = json.loads(row["value"])
                if isinstance(acc, dict):
                    result["plugins"] = acc.get("plugins") or {}
                    result["categories"] = acc.get("categories") or {}
                    result["subcategories"] = acc.get("subcategories") or {}
            except Exception:
                pass
    result.setdefault("plugins", {})
    result.setdefault("categories", {})
    result.setdefault("subcategories", {})
    # Nivel 2: disponibilidad personal del usuario — solo puede restringir más (nunca ampliar)
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (f"available_{session['user_id']}",)).fetchone()
    conn.close()
    if row:
        try:
            av = json.loads(row["value"])
            if isinstance(av, dict):
                for group in ("plugins", "categories", "subcategories"):
                    for k, v in (av.get(group) or {}).items():
                        if v is False:
                            result[group][k] = False
        except Exception:
            pass
    return result

@app.post(api_url("/api/content/available"))
async def set_content_available(request: Request):
    session = _auth_user(request)
    if not session: raise HTTPException(401)
    body = await request.json()
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", (f"available_{session['user_id']}", json.dumps(body.get("data") or {})))
    conn.commit(); conn.close()
    return {"success": True}

@app.get(api_url("/api/content/visibility"))
async def get_content_visibility(request: Request):
    session = _auth_user(request)
    if not session: raise HTTPException(401)
    from services.catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (f"visibility_{session['user_id']}",)).fetchone()
    conn.close()
    if row:
        try: return json.loads(row["value"])
        except Exception: pass
    return {}

@app.post(api_url("/api/content/visibility"))
async def set_content_visibility(request: Request):
    session = _auth_user(request)
    if not session: raise HTTPException(401)
    body = await request.json()
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", (f"visibility_{session['user_id']}", json.dumps(body.get("data") or {})))
    conn.commit(); conn.close()
    return {"success": True}

# ── Móvil: interfaces de red, QR, token ──

@app.post(api_url("/api/network/scan"))
async def scan_network(request: Request):
    """Escanea la subred local buscando servidores TVCat (puerto 8093 u otro).
    Devuelve lista de {ip, port, url, name}."""
    body = await request.json()
    port = int(body.get("port") or 8093)
    timeout = float(body.get("timeout") or 0.35)
    import psutil, ipaddress, socket, concurrent.futures, urllib.request, json as _json

    # Descubrir subred local (primer adaptador real)
    network = None
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == 2:
                ip, mask = a.address, a.netmask
                if ip.startswith("127.") or ip.startswith("169.254."): continue
                try:
                    network = ipaddress.ip_network(f"{ip}/{mask}", strict=False)
                    break
                except Exception: continue
        if network: break
    if not network:
        return {"hosts": [], "network": ""}

    # Limitar a /24 para no escanear /8 enormes
    hosts = list(network.hosts())[:254]
    hosts = [h for h in hosts if str(h) != ip]

    def _probe(host):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            result = s.connect_ex((str(host), port))
            s.close()
            if result != 0: return None
            # Verificar si responde como TVCat
            try:
                req = urllib.request.Request(f"http://{host}:{port}/api/network/interfaces", headers={"User-Agent": "TVCatScan/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = _json.loads(r.read().decode() or "{}")
                    if isinstance(d, dict) and "interfaces" in d:
                        return {"ip": str(host), "port": port, "url": f"http://{host}:{port}", "name": "TVCat"}
            except Exception:
                pass
            return {"ip": str(host), "port": port, "url": f"http://{host}:{port}", "name": "Puerto abierto"}
        except Exception:
            return None

    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as ex:
        for res in ex.map(_probe, hosts):
            if res: found.append(res)
    found.sort(key=lambda x: x["ip"])
    return {"hosts": found, "network": str(network)}


@app.get(api_url("/api/network/interfaces"))
async def get_network_interfaces():
    """Devuelve las IPs reales de los adaptadores (filtra loopback y APIPA)."""
    import psutil
    ifaces = []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == 2:
                ip = a.address
                if ip.startswith("127."): continue
                if ip.startswith("169.254."): continue
                nl = name.lower()
                if any(k in nl for k in ("loopback","docker","vmware","vbox","bluetooth","ws_win5","vpn","tunnel","hyper-v")): continue
                t = "wifi" if ("wi" in nl and "win" not in nl) else "lan"
                ifaces.append({"name": name, "ip": ip, "type": t})
    ifaces.sort(key=lambda x: (0 if x["type"]=="lan" else 1, x["name"]))
    from services.catalog_service import get_conn
    conn = get_conn()
    p = conn.execute("SELECT value FROM tvcat_settings WHERE key='mobile_preferred_ip'").fetchone()
    d = conn.execute("SELECT value FROM tvcat_settings WHERE key='mobile_dns_custom'").fetchone()
    conn.close()
    return {"interfaces": ifaces, "preferred": p[0] if p else (ifaces[0]["ip"] if ifaces else ""), "dns_custom": d[0] if d else ""}

@app.post(api_url("/api/mobile/config"))
async def save_mobile_config(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s: raise HTTPException(401)
    body = await request.json()
    from services.catalog_service import get_conn
    conn = get_conn()
    if "preferred" in body: conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", ("mobile_preferred_ip", body["preferred"]))
    if "dns_custom" in body: conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", ("mobile_dns_custom", body["dns_custom"]))
    conn.commit(); conn.close()
    return {"success": True}

@app.post(api_url("/api/mobile/test-dns"))
async def test_mobile_dns(request: Request):
    """Prueba una URL DNS desde el servidor (evita CORS)."""
    body = await request.json()
    url = (body.get("url") or "").strip().rstrip("/")
    if not url: raise HTTPException(400)
    import urllib.request, asyncio
    def _try():
        try:
            req = urllib.request.Request(url + "/", headers={"User-Agent": "TVCat/2.0"})
            urllib.request.urlopen(req, timeout=15)
            return True
        except Exception:
            return False
    ok = await asyncio.to_thread(_try)
    return {"success": ok, "error": "" if ok else "No accesible"}

@app.get(api_url("/api/qr"))
async def generate_qr(data: str = "", size: int = 8):
    import qrcode, io
    from fastapi.responses import Response
    if not data: return Response(status_code=400)
    img = qrcode.make(data, box_size=size)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return Response(content=buf.read(), media_type="image/png")

@app.post(api_url("/api/auth/qr-token"))
async def create_qr_token(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s: raise HTTPException(401)
    import secrets, time
    token = secrets.token_hex(3)[:6].upper()
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS tvcat_qr_tokens (token TEXT PRIMARY KEY, user_id INTEGER, created INTEGER)")
    conn.execute("INSERT OR REPLACE INTO tvcat_qr_tokens (token, user_id, created) VALUES (?,?,?)", (token, s["user_id"], int(time.time())))
    conn.commit(); conn.close()
    return {"token": token, "expires_in": 300}

@app.post(api_url("/api/auth/qr-login"))
async def qr_login(request: Request, response: Response):
    body = await request.json()
    token = (body.get("token") or "").strip().upper()
    if len(token) < 4: raise HTTPException(401)
    from services.catalog_service import get_conn
    import time, secrets
    conn = get_conn()
    row = conn.execute("SELECT user_id, created FROM tvcat_qr_tokens WHERE token=?", (token,)).fetchone()
    if row:
        if int(time.time()) - int(row["created"] or 0) <= 300:
            conn.execute("DELETE FROM tvcat_qr_tokens WHERE token=?", (token,))
            sess_token = secrets.token_hex(32)
            conn.execute("INSERT INTO tvcat_sessions (user_id, token) VALUES (?, ?)", (row["user_id"], sess_token))
            conn.commit(); conn.close()
            response.set_cookie("tvcat_session", sess_token, max_age=3600*24*30, path="/", samesite="lax")
            return {"success": True, "token": sess_token}
    conn.close()
    raise HTTPException(401, detail="Token inv\u00e1lido o caducado")

@app.get(api_url("/api/settings"))
async def get_settings(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    from services.catalog_service import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM tvcat_settings WHERE key NOT LIKE 'visibility_%'").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

@app.post(api_url("/api/settings"))
async def set_settings(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    from services.catalog_service import get_conn
    conn = get_conn()
    for key, value in body.items():
        conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()
    return {"success": True}

# --- Telegram Users API ---
@app.get(api_url("/api/telegram/users"))
async def list_telegram_users(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    from services.userbot_service import list_telegram_users, list_sessions
    users = list_telegram_users()
    for u in users:
        u["sessions"] = list_sessions(u["tg_user_id"])
    return {"users": users}

@app.post(api_url("/api/telegram/users"))
async def create_telegram_user(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    from services.userbot_service import save_telegram_user
    result = save_telegram_user(
        tg_user_id=int(body["tg_user_id"]),
        name=body["name"],
        phone=body.get("phone"),
        api_id=int(body.get("api_id", 0)),
        api_hash=body.get("api_hash"),
        is_default=body.get("is_default", False)
    )
    return {"success": True, "user": result}

@app.put(api_url("/api/telegram/users/{tg_user_id}"))
async def update_telegram_user(tg_user_id: int, request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    from services.userbot_service import get_default_telegram_user, set_active_client, set_default_telegram_user
    client_type = body.get("active_client")
    if client_type:
        set_active_client(tg_user_id, client_type)
    is_default = body.get("is_default")
    if is_default:
        set_default_telegram_user(tg_user_id)
    return {"success": True}

@app.delete(api_url("/api/telegram/users/{tg_user_id}"))
async def delete_telegram_user(tg_user_id: int, request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    from services.userbot_service import delete_telegram_user
    delete_telegram_user(tg_user_id)
    return {"success": True}

# --- Userbot Endpoints ---
# --- Userbot Sessions API ---
@app.get(api_url("/api/userbot/sessions"))
async def list_userbot_sessions(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    from services.userbot_service import list_sessions
    sessions = list_sessions()
    # Ocultar session_string y enmascarar teléfono
    for sess in sessions:
        sess.pop("session_string", None)
        if sess.get("phone") and len(sess["phone"]) > 4:
            sess["phone"] = sess["phone"][:3] + "***" + sess["phone"][-2:]
    return {"sessions": sessions}

@app.post(api_url("/api/userbot/sessions"))
async def create_userbot_session(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    from services.userbot_service import save_session
    result = save_session(
        name=body["name"],
        client_type=body["client_type"],
        phone=body.get("phone", ""),
        api_id=int(body.get("api_id", 0)),
        api_hash=body.get("api_hash", ""),
        session_string=body.get("session_string", ""),
        is_active=body.get("is_active", False)
    )
    result.pop("session_string", None)
    return {"success": True, "session": result}

@app.put(api_url("/api/userbot/sessions/{session_id}"))
async def update_userbot_session(session_id: int, request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    from services.userbot_service import update_session, get_session as _get_session, build_session_name
    if "name" in body:
        sess = _get_session(session_id)
        if sess:
            raw_alias = body["name"].strip()
            if raw_alias:
                try:
                    body["name"] = build_session_name(sess["client_type"], raw_alias, exclude_id=session_id, strict=True)
                except ValueError as e:
                    return {"success": False, "error": str(e)}
    update_session(session_id, **body)
    return {"success": True}

@app.delete(api_url("/api/userbot/sessions/{session_id}"))
async def delete_userbot_session(session_id: int, request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    from services.userbot_service import delete_session
    delete_session(session_id)
    return {"success": True}

@app.post(api_url("/api/userbot/test/{session_id}"))
async def test_userbot_session(session_id: int, request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    from services.userbot_service import get_session, UserbotClient
    sess_data = get_session(session_id)
    if not sess_data:
        return {"success": False, "error": "Sesión no encontrada"}
    try:
        client = UserbotClient(sess_data)
        await client.connect()
        me = await client.get_me()
        await client.disconnect()
        return {"success": True, "message": f"Conectado como @{me.username or me.first_name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Auth sessions temporales (mantener cliente conectado entre send_code y confirm_code).
# Clave: "phone|client_type" para poder tener Telethon y Pyrofork en paralelo durante el flujo.
_auth_sessions = {}


@app.post(api_url("/api/userbot/auth/send_code"))
async def userbot_send_code(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    phone = body.get("phone", "")
    client_type = body.get("client_type", "telethon")
    api_id = int(body.get("api_id", 0))
    api_hash = body.get("api_hash", "")
    if not phone or not api_id or not api_hash:
        return {"success": False, "error": "Teléfono, API ID y API Hash requeridos"}
    try:
        auth_key = f"{phone}|{client_type}"
        # Desconectar sesión temporal anterior del mismo tipo si existe
        if auth_key in _auth_sessions:
            try:
                await _auth_sessions[auth_key]["client"].disconnect()
            except:
                pass
            del _auth_sessions[auth_key]

        from services.userbot_service import UserbotClient
        temp = {"client_type": client_type, "api_id": api_id, "api_hash": api_hash, "session_string": ""}
        ubot = UserbotClient(temp)
        await ubot.connect()

        # Cada cliente solicita su PROPIO código SMS (auth_key independiente).
        # No se reutiliza el phone_code_hash entre Telethon y Pyrofork: cada login
        # real necesita su propio código.
        result = await ubot.send_code_request(phone)
        pch = result.get("phone_code_hash", "")

        _auth_sessions[auth_key] = {"client": ubot, "phone_code_hash": pch}
        return {"success": True, "phone_code_hash": pch, "client_type": client_type}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post(api_url("/api/userbot/auth/confirm_code"))
async def userbot_confirm_code(request: Request):
    from services.auth_service import get_session
    s = get_session(request.cookies.get("tvcat_session",""))
    if not s or s.get("role") != "admin": raise HTTPException(403)
    body = await request.json()
    phone = body.get("phone", "")
    client_type = body.get("client_type", "telethon")
    auth_key = f"{phone}|{client_type}"
    if auth_key not in _auth_sessions:
        return {"success": False, "error": "Sesión de autenticación expirada. Solicita el código de nuevo."}
    try:
        auth_data = _auth_sessions[auth_key]
        ubot = auth_data["client"]
        pch = auth_data["phone_code_hash"]

        # Intentar sign in con código (y password si ya se solicitó 2FA)
        code = body.get("code", "")
        password = body.get("password") or None
        try:
            me = await ubot.sign_in(phone=phone, code=code, password=password, phone_code_hash=pch)
        except Exception as e:
            err_str = str(e).upper()
            is_2fa = any(kw in err_str for kw in ["SESSION_PASSWORD_NEEDED", "PASSWORDNEEDED", "TWO-STEPS", "PASSWORD IS REQUIRED"])
            if is_2fa:
                if not password:
                    return {"success": False, "needs_2fa": True, "error": "Se requiere contrasena 2FA"}
            return {"success": False, "error": str(e)}

        ss = await ubot.get_session_string()

        from services.userbot_service import build_session_name, save_session, save_telegram_user, get_telegram_user
        raw_name = body.get("name", "").strip()
        if not raw_name:
            return {"success": False, "error": "Nombre requerido"}
        final_name = build_session_name(client_type, raw_name)

        # Registrar usuario Telegram si no existe
        tg_user_id = body.get("tg_user_id")
        if not tg_user_id and hasattr(me, 'id'):
            tg_user_id = me.id
        existing = get_telegram_user(tg_user_id) if tg_user_id else None
        if not existing:
            save_telegram_user(
                tg_user_id=tg_user_id,
                name=raw_name,
                phone=phone,
                api_id=int(body.get("api_id",0)),
                api_hash=body.get("api_hash",""),
                is_default=False
            )

        session_data = save_session(
            name=final_name,
            client_type=client_type,
            phone=phone,
            api_id=int(body.get("api_id",0)),
            api_hash=body.get("api_hash",""),
            session_string=ss,
            tg_user_id=tg_user_id,
            is_active=True  # la sesión recién generada queda ACTIVA para su client_type
        )
        session_data.pop("session_string", None)

        await ubot.disconnect()
        if auth_key in _auth_sessions:
            del _auth_sessions[auth_key]

        return {"success": True, "session": session_data, "client_type": client_type}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get(api_url("/api/translations"))
async def get_translations():
    from services.translate_service import get_translation_dict
    return get_translation_dict()


# --- SPA fallback (404 handler) ---
import starlette.exceptions
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def spa_fallback(request: Request, exc):
    if exc.status_code == 404:
        path = request.url.path
        # Only serve SPA for non-API paths
        if not path.startswith(api_url("/api/")):
            fp = os.path.join(CORE_DIR, path.lstrip("/"))
            if os.path.isfile(fp):
                return FileResponse(fp)
            return FileResponse(os.path.join(CORE_DIR, "index.html"))
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


_MDNS_ZC = None


def _register_mdns(port: int):
    """Anuncia TVCat en la red local vía mDNS: http://tvcat.<hostname>.local:<port>

    Registra el servicio DNS-SD `_http._tcp` con instancia "tvcat" y un registro
    A para `tvcat.<hostname>.local` apuntando a la IP LAN activa. Cada máquina
    anuncia su propio nombre, evitando conflictos con otras instancias en la red.
    """
    global _MDNS_ZC
    try:
        import socket
        from zeroconf import ServiceInfo, Zeroconf

        machine = socket.gethostname().lower()
        machine = re.sub(r"[^a-z0-9-]", "", machine).strip("-")
        if not machine:
            machine = "tvcat"

        # IP de la interfaz de red activa (mismo patrón que get_lan_ip de tvcat_peers)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()

        if not ip:
            raise RuntimeError("no se detectó IP de red local")

        hostname = f"tvcat.{machine}.local."
        _MDNS_ZC = Zeroconf()
        info = ServiceInfo(
            "_http._tcp.local.",
            f"tvcat._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=port,
            server=hostname,
        )
        _MDNS_ZC.register_service(info)
        print(f"[mDNS] TVCat anunciado: http://tvcat.{machine}.local:{port} ({ip})")
        return _MDNS_ZC
    except Exception as e:
        if _MDNS_ZC:
            try:
                _MDNS_ZC.close()
            except Exception:
                pass
        print(f"[mDNS] No se pudo anunciar en la red local: {e}")
        return None


if __name__ == "__main__":
    import argparse
    import logging

    # Silenciar access logs de endpoints de polling (ruido constante en la consola)
    _QUIET_ACCESS_PATHS = (
        "/api/installer/3ds/consoles",
        "/api/telegram-copy/queue",
        "/api/user/scan/status",
        "/api/cache-relay/status",
    )

    class _QuietAccessFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            # Raíz exacta (GET / HTTP/1.1) — polling del móvil/dispositivo
            if '"GET / HTTP/1.1"' in msg:
                return False
            for p in _QUIET_ACCESS_PATHS:
                if f'"{p}' in msg or p in msg:
                    return False
            return True

    _access_logger = logging.getLogger("uvicorn.access")
    if _access_logger:
        _access_logger.addFilter(_QuietAccessFilter())

    parser = argparse.ArgumentParser(description="TVCat 2 Gateway")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TVCAT_PORT", 8098)))
    parser.add_argument("--host", type=str, default=os.environ.get("TVCAT_HOST", "0.0.0.0"))
    args, _ = parser.parse_known_args()
    port = args.port
    host = args.host

    # Anuncio mDNS: http://tvcat.<hostname>.local:<port> (red local)
    _MDNS_ZC = _register_mdns(port)

    uvicorn.run(app, host=host, port=port)