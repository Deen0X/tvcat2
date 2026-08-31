"""
TVCat Installer 3DS — Companion (modo puente)
=============================================
Plugin tipo 'player' para títulos de consola 3DS (Juego/3DS).
Envía ficheros (CIA) a un companion 3DS que los guarda en microSD.

- Emparejamiento por token, asociado al usuario que lo genera.
- Cada usuario ve/administra sus consolas; el admin ve todas.
- Cola global: una entrada por (título, consola); cada consola procesa las suyas.
"""

import os
import json
import time
import secrets
import hashlib
import uuid

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(_DATA_DIR, "installer_3ds.json")
CONFIG_FILE = os.path.join(_DATA_DIR, "config.json")

PLATFORM = "3ds"


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class PairBody(BaseModel):
    token: str = ""
    id: Optional[str] = None
    name: Optional[str] = None
    download_dir: Optional[str] = None
    console_name: Optional[str] = None   # FriendlyName de la consola (handshake)
    console_hwid: Optional[str] = None   # Hash hardware (handshake)


class HeartbeatBody(BaseModel):
    token: str = ""
    state: Optional[str] = "idle"
    progress: Optional[float] = 0
    speed: Optional[int] = 0
    free: Optional[int] = 0
    file: Optional[str] = ""


class QueueBody(BaseModel):
    cid: str
    file_url: str
    filename: str = "download"
    size: Optional[int] = 0
    hash: Optional[str] = ""


class ConsoleUpdateBody(BaseModel):
    name: Optional[str] = None
    image: Optional[str] = None


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def _load():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"consoles": {}, "pairings": {}, "queue": []}


def _save(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def _load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _token_ok(console, token: str) -> bool:
    if not token or not console:
        return False
    return console.get("token_hash") == hashlib.sha256(token.encode()).hexdigest()


def _short_token(length: int = 6) -> str:
    """Token corto legible (sin caracteres ambiguos)."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _get_base_url(request: Request) -> str:
    cfg = _load_config()
    if cfg.get("public_url"):
        return cfg["public_url"].rstrip("/")
    host = request.headers.get("host", "localhost")
    return f"http://{host}"


def _session_user(request: Request):
    """Devuelve {user_id, role} de la sesión TVCat o None."""
    from tvcat.services.auth_service import get_session
    token = request.cookies.get("tvcat_session", "")
    s = get_session(token) if token else None
    if not s:
        return None
    return {"user_id": s["user_id"], "role": s.get("role", "user")}


def _can_manage(session, console):
    """El dueño o el admin pueden administrar la consola."""
    if not session:
        return False
    return session["role"] == "admin" or console.get("user_id") == session["user_id"]


# ---------------------------------------------------------------------------
# Emparejamiento
# ---------------------------------------------------------------------------
@router.api_route("/api/installer/3ds/companion.cia", methods=["GET", "HEAD"])
async def get_companion_cia(request: Request):
    """Sirve el companion .cia para FBI Remote Install.
    La URL debe terminar en .cia para que el parser HTTP de la 3DS lo reconozca.
    Response binaria explícita (no FileResponse) evita chunked encoding."""
    import os as _os
    from fastapi.responses import Response as _Response
    p = _os.path.join(_PLUGIN_DIR, "static", "companion.cia")
    if not _os.path.exists(p):
        raise HTTPException(status_code=404, detail="Companion no encontrado")

    file_size = _os.path.getsize(p)
    headers = {
        "Content-Type": "application/x-3ds-cia",
        "Content-Length": str(file_size),
        "Accept-Ranges": "bytes",
        "Content-Disposition": 'attachment; filename="companion.cia"',
        "Connection": "close"
    }

    if request.method == "HEAD":
        return _Response(status_code=200, headers=headers)

    with open(p, "rb") as f:
        content = f.read()

    return _Response(content=content, media_type="application/x-3ds-cia", headers=headers)


# Legacy: redirigir la ruta corta a la nueva con .cia
@router.get("/api/installer/3ds/cia")
async def get_companion_cia_legacy(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/installer/3ds/companion.cia", status_code=301)


@router.get("/api/installer/3ds/pair")
async def generate_pairing(request: Request):
    """Genera un pairing_token corto (6 chars) asociado al usuario de la sesión."""
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _load()
    token = _short_token()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db["pairings"][token_hash] = {
        "platform": PLATFORM,
        "user_id": session["user_id"],
        "created": time.time(),
    }
    _save(db)
    # URL base desde configuración móvil (preferred ip / dns custom)
    base = _get_base_url(request)
    try:
        from tvcat.gateway import get_global_setting
        dns = get_global_setting("mobile_dns_custom", "")
        pref = get_global_setting("mobile_preferred_ip", "")
        if dns:
            base = dns.rstrip("/")
        elif pref:
            base = f"http://{pref}:{request.url.port or 8093}"
    except Exception:
        pass
    pair_url = f"{base}/api/installer/{PLATFORM}/pair?token={token}"
    short_url = f"{base}/{PLATFORM}?token={token}"
    cfg = {"server_url": base, "pairing_token": token, "platform": PLATFORM, "pair_url": pair_url}
    return {"qr": json.dumps(cfg), "config": cfg, "token": token, "pair_url": pair_url, "short_url": short_url}


@router.get("/3ds")
async def short_pair_status(request: Request, token: str = ""):
    """Endpoint corto para el companion: /3ds?token=XXX.
    Devuelve JSON con el estado del pairing (no es una página para navegar)."""
    token = (token or "").strip().upper()
    if not token:
        return {"ok": False, "error": "token requerido"}
    th = hashlib.sha256(token.encode()).hexdigest()
    db = _load()
    valid = th in db.get("pairings", {})
    return {"ok": True, "platform": PLATFORM, "token_valid": valid}


@router.post("/api/installer/3ds/{cid}/pair")
async def complete_pairing(cid: str, body: PairBody):
    """El companion se registra consumiendo el pairing_token (hereda el user_id del generador)."""
    db = _load()
    if not body.token:
        raise HTTPException(401, "token requerido")
    th = hashlib.sha256(body.token.encode()).hexdigest()
    pairing = db["pairings"].pop(th, None)
    if not pairing:
        raise HTTPException(401, "Token de emparejamiento inv\u00e1lido o caducado")
    real_id = body.id or body.console_hwid or cid
    console_name = body.console_name or body.name or "3DS"
    db["consoles"][real_id] = {
        "id": real_id,
        "platform": PLATFORM,
        "name": console_name,
        "console_name": console_name,
        "console_hwid": body.console_hwid or "",
        "image": "",
        "token_hash": th,
        "user_id": pairing["user_id"],
        "last_seen": time.time(),
        "status": "online",
        "state": "idle",
        "progress": 0,
        "speed_bps": 0,
        "free_bytes": 0,
        "current_file": "",
        "download_dir": body.download_dir or "",
    }
    _save(db)
    return {"ok": True, "id": real_id}


# ---------------------------------------------------------------------------
# Heartbeat / Commands (companion)
# ---------------------------------------------------------------------------
@router.post("/api/installer/3ds/{cid}/heartbeat")
async def heartbeat(cid: str, body: HeartbeatBody):
    db = _load()
    c = db["consoles"].get(cid)
    if not _token_ok(c, body.token):
        raise HTTPException(401, "No autorizado")
    c["last_seen"] = time.time()
    c["status"] = "online"
    for k, key in (("state", "state"), ("progress", "progress"), ("speed", "speed_bps"),
                   ("free", "free_bytes"), ("file", "current_file")):
        if getattr(body, k) is not None:
            c[key] = getattr(body, k)
    _save(db)
    return {"ok": True}


@router.get("/api/installer/3ds/{cid}/commands")
async def get_commands(cid: str, token: str = ""):
    """Devuelve la cola destinada a esta consola (FIFO) y la retira."""
    db = _load()
    c = db["consoles"].get(cid)
    if not _token_ok(c, token):
        raise HTTPException(401, "No autorizado")
    pending = [e for e in db.get("queue", []) if e.get("target") == cid]
    db["queue"] = [e for e in db.get("queue", []) if e.get("target") != cid]
    _save(db)
    return {"commands": [{
        "cmd": "download",
        "id": e.get("id", ""),
        "url": e.get("file_url", ""),
        "filename": e.get("filename", "download"),
        "size": e.get("size", 0),
        "hash": e.get("hash", ""),
    } for e in pending]}


# ---------------------------------------------------------------------------
# Cola (navegador, sesión TVCat)
# ---------------------------------------------------------------------------
@router.post("/api/installer/3ds/queue")
async def add_to_queue(body: QueueBody, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión para encolar")
    db = _load()
    c = db["consoles"].get(body.cid)
    if not c:
        raise HTTPException(404, "Consola no encontrada")
    if not _can_manage(session, c):
        raise HTTPException(403, "No tienes acceso a esta consola")
    db.setdefault("queue", []).append({
        "id": uuid.uuid4().hex[:12],
        "target": body.cid,
        "user_id": session["user_id"],
        "file_url": body.file_url,
        "filename": body.filename,
        "size": body.size or 0,
        "hash": body.hash or "",
    })
    _save(db)
    pending = len([e for e in db["queue"] if e.get("target") == body.cid])
    return {"ok": True, "queued": pending}


@router.delete("/api/installer/3ds/queue")
async def clear_queue(cid: str, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _load()
    if cid:
        c = db["consoles"].get(cid)
        if not c:
            raise HTTPException(404, "Consola no encontrada")
        if not _can_manage(session, c):
            raise HTTPException(403, "No tienes acceso")
        db["queue"] = [e for e in db.get("queue", []) if e.get("target") != cid]
    else:
        db["queue"] = []
    _save(db)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Consolas (navegador)
# ---------------------------------------------------------------------------
@router.get("/api/installer/3ds/consoles")
async def list_consoles(request: Request, user: Optional[int] = None):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _load()
    now = time.time()
    result = []
    for cid, c in db["consoles"].items():
        # Usuario normal: solo las suyas. Admin: todas (o filtradas por ?user=).
        if session["role"] != "admin" and c.get("user_id") != session["user_id"]:
            continue
        if user is not None and c.get("user_id") != user:
            continue
        offline = (now - c.get("last_seen", 0)) > 20
        result.append({
            "id": cid,
            "platform": c.get("platform", PLATFORM),
            "name": c.get("name", cid),
            "console_name": c.get("console_name", ""),
            "console_hwid": c.get("console_hwid", ""),
            "image": c.get("image", ""),
            "user_id": c.get("user_id"),
            "status": "offline" if offline else "online",
            "state": c.get("state", "idle"),
            "progress": c.get("progress", 0),
            "speed_bps": c.get("speed_bps", 0),
            "free_bytes": c.get("free_bytes", 0),
            "current_file": c.get("current_file", ""),
            "queued": len([e for e in db.get("queue", []) if e.get("target") == cid]),
            "download_dir": c.get("download_dir", ""),
        })
    return {"consoles": result}


@router.patch("/api/installer/3ds/consoles/{cid}")
async def update_console(cid: str, body: ConsoleUpdateBody, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _load()
    c = db["consoles"].get(cid)
    if not c:
        raise HTTPException(404, "Consola no encontrada")
    if not _can_manage(session, c):
        raise HTTPException(403, "No tienes acceso a esta consola")
    if body.name is not None:
        c["name"] = body.name
    if body.image is not None:
        c["image"] = body.image
    _save(db)
    return {"ok": True}


@router.delete("/api/installer/3ds/consoles/{cid}")
async def delete_console(cid: str, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _load()
    c = db["consoles"].get(cid)
    if not c:
        raise HTTPException(404, "Consola no encontrada")
    if not _can_manage(session, c):
        raise HTTPException(403, "No tienes acceso")
    db["consoles"].pop(cid, None)
    db["queue"] = [e for e in db.get("queue", []) if e.get("target") != cid]
    _save(db)
    return {"ok": True}
