"""
TVCat Installer PS3 — Push FTP
==============================
Plugin tipo 'player' para títulos de consola PS3 (Juego/PS3).

- Consolas FTP registradas manualmente (webMAN / multiMAN / Irisman).
- Cola global FIFO: una entrada por (título, consola); cada consola procesa las suyas.
- Worker en hilo daemon: descarga el fichero (endpoint de stream del núcleo) y lo
  sube por FTP con reanudación (REST).
- Persistencia JSON en data/installer_ps3.json (consolas + cola).
- Reutiliza (sin modificar) el soporte player del núcleo y auth_service.
"""

import os
import json
import time
import uuid
import threading
import tempfile
import importlib.util

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

import httpx

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")

_spec = importlib.util.spec_from_file_location(
    "tvcat_installer_ps3_ftp_client",
    os.path.join(_PLUGIN_DIR, "ftp_client.py"),
)
ftp_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ftp_client)

router = APIRouter()
os.makedirs(_DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(_DATA_DIR, "installer_ps3.json")

PLATFORM = "ps3"
MAX_ATTEMPTS = 3

_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class ConsoleBody(BaseModel):
    name: str = ""
    host: str = ""
    port: int = 21
    username: str = ""
    password: str = ""
    destination: str = "/dev_hdd0/PS3ISO"
    timeout: int = 20


class ConsoleUpdateBody(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    destination: Optional[str] = None
    timeout: Optional[int] = None


class QueueBody(BaseModel):
    cid: str
    file_url: str
    filename: str = "download"
    size: Optional[int] = 0


class CatsBody(BaseModel):
    categories: str = ""
    subcategories: str = ""


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def _load_raw():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"consoles": {}, "queue": []}


def _save_raw(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def _read():
    with _lock:
        return _load_raw()


def _mutate(mutator):
    with _lock:
        db = _load_raw()
        result = mutator(db)
        _save_raw(db)
        return result


def _set_console(cid, **fields):
    def mut(db):
        c = db["consoles"].get(cid)
        if c:
            c.update(fields)
            c["last_seen"] = time.time()
        return None
    _mutate(mut)


# ---------------------------------------------------------------------------
# Sesión / permisos (reutiliza auth_service del núcleo)
# ---------------------------------------------------------------------------
def _session_user(request: Request):
    from tvcat.services.auth_service import get_session
    token = request.cookies.get("tvcat_session", "")
    s = get_session(token) if token else None
    if not s:
        return None
    return {"user_id": s["user_id"], "role": s.get("role", "user")}


def _can_manage(session, console):
    if not session:
        return False
    return session["role"] == "admin" or console.get("user_id") == session["user_id"]


def _public_console(cid, c, queued):
    return {
        "id": cid,
        "platform": c.get("platform", PLATFORM),
        "name": c.get("name", cid),
        "host": c.get("host", ""),
        "port": c.get("port", 21),
        "username": c.get("username", ""),
        "has_password": bool(c.get("password", "")),
        "destination": c.get("destination", ""),
        "timeout": c.get("timeout", 20),
        "user_id": c.get("user_id"),
        "status": "online" if c.get("last_seen", 0) > 0 else "offline",
        "state": c.get("state", "idle"),
        "progress": c.get("progress", 0),
        "speed_bps": c.get("speed_bps", 0),
        "current_file": c.get("current_file", ""),
        "queued": queued,
    }


# ---------------------------------------------------------------------------
# Consolas
# ---------------------------------------------------------------------------
@router.get("/api/installer/ps3/consoles")
async def list_consoles(request: Request, user: Optional[int] = None):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _read()
    result = []
    for cid, c in db["consoles"].items():
        if session["role"] != "admin" and c.get("user_id") != session["user_id"]:
            continue
        if user is not None and c.get("user_id") != user:
            continue
        queued = len([e for e in db.get("queue", []) if e.get("target") == cid and e.get("state") != "failed"])
        result.append(_public_console(cid, c, queued))
    return {"consoles": result}


@router.post("/api/installer/ps3/consoles")
async def create_console(body: ConsoleBody, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    host = (body.host or "").strip()
    if not host:
        raise HTTPException(400, "Host requerido")
    cid = uuid.uuid4().hex[:12]

    def mut(db):
        db["consoles"][cid] = {
            "id": cid,
            "platform": PLATFORM,
            "name": (body.name or "").strip() or host,
            "host": host,
            "port": body.port or 21,
            "username": body.username or "",
            "password": body.password or "",
            "destination": (body.destination or "").strip() or "/dev_hdd0/PS3ISO",
            "timeout": body.timeout or 20,
            "user_id": session["user_id"],
            "last_seen": 0,
            "status": "offline",
            "state": "idle",
            "progress": 0,
            "speed_bps": 0,
            "current_file": "",
        }
        return cid

    cid = _mutate(mut)
    return {"ok": True, "id": cid}


@router.patch("/api/installer/ps3/consoles/{cid}")
async def update_console(cid: str, body: ConsoleUpdateBody, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")

    def mut(db):
        c = db["consoles"].get(cid)
        if not c:
            raise HTTPException(404, "Consola no encontrada")
        if not _can_manage(session, c):
            raise HTTPException(403, "No tienes acceso a esta consola")
        if body.name is not None:
            c["name"] = body.name
        if body.host is not None:
            c["host"] = body.host.strip()
        if body.port is not None:
            c["port"] = body.port
        if body.username is not None:
            c["username"] = body.username
        if body.password not in (None, ""):
            c["password"] = body.password
        if body.destination is not None:
            c["destination"] = body.destination.strip()
        if body.timeout is not None:
            c["timeout"] = body.timeout
        return None

    _mutate(mut)
    return {"ok": True}


@router.delete("/api/installer/ps3/consoles/{cid}")
async def delete_console(cid: str, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")

    def mut(db):
        c = db["consoles"].get(cid)
        if not c:
            raise HTTPException(404, "Consola no encontrada")
        if not _can_manage(session, c):
            raise HTTPException(403, "No tienes acceso")
        db["consoles"].pop(cid, None)
        db["queue"] = [e for e in db.get("queue", []) if e.get("target") != cid]
        return None

    _mutate(mut)
    return {"ok": True}


@router.post("/api/installer/ps3/consoles/{cid}/test")
async def test_console(cid: str, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _read()
    c = db["consoles"].get(cid)
    if not c:
        raise HTTPException(404, "Consola no encontrada")
    if not _can_manage(session, c):
        raise HTTPException(403, "No tienes acceso")

    result = await _run_in_thread(ftp_client.test, c)
    if result.get("ok"):
        _set_console(cid, status="online")
    return result


# ---------------------------------------------------------------------------
# Cola
# ---------------------------------------------------------------------------
@router.post("/api/installer/ps3/queue")
async def add_to_queue(body: QueueBody, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión para encolar")

    db = _read()
    c = db["consoles"].get(body.cid)
    if not c:
        raise HTTPException(404, "Consola no encontrada")
    if not _can_manage(session, c):
        raise HTTPException(403, "No tienes acceso a esta consola")

    base_url = str(request.base_url).rstrip("/")

    def mut(db):
        db.setdefault("queue", []).append({
            "id": uuid.uuid4().hex[:12],
            "target": body.cid,
            "user_id": session["user_id"],
            "file_url": body.file_url,
            "base_url": base_url,
            "filename": body.filename or "download",
            "size": body.size or 0,
            "state": "pending",
            "attempts": 0,
            "next_retry": 0,
            "error": "",
        })
        return None

    _mutate(mut)
    _ensure_worker()
    pending = len([e for e in _read().get("queue", []) if e.get("target") == body.cid and e.get("state") != "failed"])
    return {"ok": True, "queued": pending}


@router.delete("/api/installer/ps3/queue")
async def clear_queue(cid: str = "", request: Request = None):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")

    def mut(db):
        if cid:
            c = db["consoles"].get(cid)
            if not c:
                raise HTTPException(404, "Consola no encontrada")
            if not _can_manage(session, c):
                raise HTTPException(403, "No tienes acceso")
            db["queue"] = [e for e in db.get("queue", []) if e.get("target") != cid]
        else:
            db["queue"] = []
        return None

    _mutate(mut)
    return {"ok": True}


@router.get("/api/installer/ps3/status")
async def status(request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _read()
    queue = db.get("queue", [])
    return {
        "queue": queue,
        "pending": len([e for e in queue if e.get("state") != "failed"]),
        "failed": len([e for e in queue if e.get("state") == "failed"]),
    }


def _sanitize(s: str) -> str:
    import re
    if s.strip() == "*":
        return "*"
    return re.sub(r"\s+", " ", s.strip().lower().replace("_", " ").replace("-", " ")).strip()

def _parse_list(raw: str):
    import re
    parts = re.split(r"[;\n,]+", raw or "")
    out = []
    for p in parts:
        if p.strip() == "*":
            if "*" not in out:
                out.append("*")
            continue
        s = _sanitize(p)
        if s and s not in out:
            out.append(s)
    return out

@router.get("/api/installer/ps3/cats")
async def get_cats(request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    db = _read()
    cats = db.get("categories")
    subs = db.get("subcategories")
    # defaults
    if cats is None:
        cats = ["juego", "juegos", "game", "games", "gamez"]
    if subs is None:
        subs = ["ps3", "playstation 3", "playstation3", "ps 3"]
    # si están guardados como string, parsear
    if isinstance(cats, str):
        cats = _parse_list(cats)
    if isinstance(subs, str):
        subs = _parse_list(subs)
    return {"categories": cats, "subcategories": subs, "raw_categories": "; ".join(cats), "raw_subcategories": "; ".join(subs)}

@router.post("/api/installer/ps3/cats")
async def set_cats(body: CatsBody, request: Request):
    session = _session_user(request)
    if not session:
        raise HTTPException(401, "Inicia sesión")
    if session["role"] != "admin":
        raise HTTPException(403, "Solo admin")
    cats = _parse_list(body.categories)
    subs = _parse_list(body.subcategories)
    if not cats:
        cats = ["juego"]
    if not subs:
        subs = ["ps3"]
    def mut(db):
        db["categories"] = cats
        db["subcategories"] = subs
        return None
    _mutate(mut)
    # también guardar en el store genérico central para que lo vea /api/plugins/cats
    try:
        from tvcat.services.catalog_service import get_conn
        import json
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", ("plugin_cats_tvcat_installer_ps3", json.dumps(cats, ensure_ascii=False)))
        conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)", ("plugin_subs_tvcat_installer_ps3", json.dumps(subs, ensure_ascii=False)))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"ok": True, "categories": cats, "subcategories": subs}


# ---------------------------------------------------------------------------
# Worker de entrega (hilo daemon)
# ---------------------------------------------------------------------------
_worker_started = False
_worker_lock = threading.Lock()


def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        t = threading.Thread(target=_worker_loop, daemon=True, name="ps3-installer-worker")
        t.start()


async def _run_in_thread(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)


def _worker_loop():
    while True:
        try:
            _process_next()
        except Exception as e:
            print(f"[PS3-INSTALLER] Error en worker: {e}", flush=True)
        time.sleep(1)


def _process_next():
    db = _read()
    now = time.time()
    pending = [e for e in db.get("queue", []) if e.get("state") != "failed" and e.get("next_retry", 0) <= now]
    if not pending:
        return
    job = pending[0]
    cid = job.get("target")
    console = db["consoles"].get(cid)
    if not console:
        _drop_job(job["id"])
        return

    job_id = job["id"]
    filename = job.get("filename") or "download"
    total = job.get("size") or 0

    _set_console(cid, state="downloading", progress=0, speed_bps=0, current_file=filename)

    tmp_path = None
    try:
        url = job.get("file_url", "")
        if not url.startswith("http"):
            base = job.get("base_url", "http://127.0.0.1:8093")
            url = base + url

        fd, tmp_path = tempfile.mkstemp(prefix="ps3_", suffix=".part")
        os.close(fd)

        phase_start = time.time()
        phase_bytes = 0
        last_flush = 0.0

        def dl_progress(done, tot):
            nonlocal phase_bytes, phase_start, last_flush
            phase_bytes = done
            now = time.time()
            if now - last_flush >= 1.0:
                last_flush = now
                spd = done / max(now - phase_start, 0.001)
                _set_console(cid, state="downloading", progress=(done / tot) if tot else 0,
                             speed_bps=int(spd), current_file=filename)

        with httpx.Client(follow_redirects=True, timeout=None) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                content_length = int(resp.headers.get("Content-Length") or 0)
                dl_total = content_length or total
                done = 0
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1048576):
                        f.write(chunk)
                        done += len(chunk)
                        dl_progress(done, dl_total)

        local_size = os.path.getsize(tmp_path)
        if local_size == 0:
            raise ValueError("Fichero descargado vacío")

        _set_console(cid, state="uploading", progress=0, speed_bps=0, current_file=filename)

        phase_start = time.time()
        last_flush = 0.0

        def up_progress(done, tot):
            nonlocal last_flush
            now = time.time()
            if now - last_flush >= 1.0:
                last_flush = now
                spd = done / max(now - phase_start, 0.001)
                _set_console(cid, state="uploading", progress=(done / tot) if tot else 0,
                             speed_bps=int(spd), current_file=filename)

        ftp_client.store(console, tmp_path, filename, up_progress)

        _set_console(cid, state="idle", progress=1, speed_bps=0, current_file="")
        _drop_job(job_id)
        print(f"[PS3-INSTALLER] Enviado OK: {filename} -> {cid}", flush=True)

    except Exception as e:
        print(f"[PS3-INSTALLER] Error en {filename} -> {cid}: {e}", flush=True)
        _set_console(cid, state="idle", speed_bps=0, current_file=f"error: {e}")
        _mark_failed_or_retry(job_id, str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _drop_job(job_id):
    def mut(db):
        db["queue"] = [e for e in db.get("queue", []) if e.get("id") != job_id]
        return None
    _mutate(mut)


def _mark_failed_or_retry(job_id, error):
    def mut(db):
        for e in db.get("queue", []):
            if e.get("id") == job_id:
                e["attempts"] = e.get("attempts", 0) + 1
                e["error"] = error
                if e["attempts"] >= MAX_ATTEMPTS:
                    e["state"] = "failed"
                else:
                    e["next_retry"] = time.time() + 30
                return None
        return None
    _mutate(mut)


_ensure_worker()
