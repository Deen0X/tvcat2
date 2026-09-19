"""
tvcat_hide — Plugin heropage-action para ocultar elementos del catálogo.

- Botón hero "Ocultar/Mostrar" por item (personal, propio perfil).
- Botones hero parentales (solo admin + flag show_parental).
- Botones de tray: toggle personal, ocultar filtrados, ocultar filtrados parental.
- Secciones core "Ocultos" y "Ocultos Parental" para revisar/recuperar.

- GET  /api/hide/config            → {show_parental, child_profile_id, child_profile_name, is_admin}
- PUT  /api/hide/config            → solo admin {show_parental?, child_profile_id?}
- GET  /api/hide/profiles          → perfiles (solo admin, para elegir child)
"""
import os
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _central_conn():
    import sys as _sys
    _tvcat = os.path.abspath(os.path.join(_PLUGIN_DIR, "..", ".."))
    if _tvcat not in _sys.path:
        _sys.path.insert(0, _tvcat)
    from services.catalog_service import get_conn
    return get_conn()


def _session(request: Request):
    from services.auth_service import get_session
    return get_session(request.cookies.get("tvcat_session", ""))


def _cfg_get(conn, key, default=""):
    try:
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (key,)).fetchone()
        if row:
            v = row["value"] if isinstance(row, dict) else row[0]
            return v
    except Exception:
        pass
    return default


@router.get("/api/hide/config")
async def hide_config(request: Request):
    sess = _session(request)
    if not sess:
        raise HTTPException(401)
    conn = _central_conn()
    try:
        show = _cfg_get(conn, "hide_show_parental", "0") == "1"
        cpid = _cfg_get(conn, "hide_child_profile", "")
        name = ""
        try:
            cpid_int = int(cpid or 0)
        except Exception:
            cpid_int = 0
        if cpid_int:
            try:
                prow = conn.execute("SELECT name FROM tvcat_profiles WHERE id=?", (cpid_int,)).fetchone()
                if prow:
                    name = prow["name"] if isinstance(prow, dict) else prow[0]
            except Exception:
                pass
        return {"show_parental": show, "child_profile_id": cpid_int,
                "child_profile_name": name or "",
                "is_admin": (sess.get("role") == "admin")}
    finally:
        try: conn.close()
        except: pass


@router.put("/api/hide/config")
async def hide_config_save(request: Request):
    sess = _session(request)
    if not sess or sess.get("role") != "admin":
        raise HTTPException(403)
    body = await request.json()
    conn = _central_conn()
    try:
        if "show_parental" in body:
            conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)",
                         ("hide_show_parental", "1" if body.get("show_parental") else "0"))
        if "child_profile_id" in body:
            try:
                cpid = int(body.get("child_profile_id") or 0)
            except Exception:
                cpid = 0
            conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)",
                         ("hide_child_profile", str(cpid)))
        conn.commit()
        return {"success": True}
    finally:
        try: conn.close()
        except: pass


@router.get("/api/hide/profiles")
async def hide_profiles(request: Request):
    sess = _session(request)
    if not sess or sess.get("role") != "admin":
        raise HTTPException(403)
    conn = _central_conn()
    try:
        rows = conn.execute("SELECT id, name, is_admin FROM tvcat_profiles ORDER BY id").fetchall()
        return {"profiles": [dict(r) for r in rows]}
    except Exception:
        return {"profiles": []}
    finally:
        try: conn.close()
        except: pass
