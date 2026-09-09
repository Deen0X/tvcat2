"""
tvcat_ambient_bg — plugin grid-decorator de fondo ambiental.

Sin tablas propias: solo prefs por usuario-dispositivo en la DB central
(tvcat_settings, clave ambient_pref_{user_id}). Todo el efecto es frontend.
"""

import json
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()

_DEFAULTS = {
    "enabled": True,
    "mode": "lava",       # cover | lava | off
    "crop": "center",     # center | random
    "veil": 55,           # 0..90 (% negro por encima)
    "blur": 48,           # ancho canvas mini (24|48|96)
    "drift_s": 24,        # 8..120 (duración ciclo lava)
}


def _sess(request: Request):
    try:
        from services.auth_service import get_session
        return get_session(request.cookies.get("tvcat_session", ""))
    except Exception:
        return None


def _need_login(request: Request):
    s = _sess(request)
    if not s:
        raise HTTPException(status_code=401, detail="Login requerido")
    return s


def _central_conn():
    from services.catalog_service import get_conn
    return get_conn()


def _pref_key(user_id) -> str:
    return f"ambient_pref_{user_id}"


def _load_map(user_id) -> dict:
    try:
        conn = _central_conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (_pref_key(user_id),)).fetchone()
        conn.close()
        if row and row[0]:
            d = json.loads(row[0])
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _save_map(user_id, data: dict):
    conn = _central_conn()
    conn.execute(
        "INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)",
        (_pref_key(user_id), json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def _clean(p: dict) -> dict:
    out = dict(_DEFAULTS)
    try:
        if isinstance(p.get("enabled"), bool):
            out["enabled"] = p["enabled"]
        if p.get("mode") in ("cover", "lava", "off"):
            out["mode"] = p["mode"]
        if p.get("crop") in ("center", "random"):
            out["crop"] = p["crop"]
        out["veil"] = max(0, min(90, int(p.get("veil", out["veil"]))))
        b = int(p.get("blur", out["blur"]))
        out["blur"] = b if b in (24, 48, 96) else 48
        out["drift_s"] = max(8, min(120, int(p.get("drift_s", out["drift_s"]))))
    except Exception:
        pass
    return out


class PrefBody(BaseModel):
    device_id: str = ""
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    crop: Optional[str] = None
    veil: Optional[int] = None
    blur: Optional[int] = None
    drift_s: Optional[int] = None


@router.get("/api/ambient/prefs")
async def get_prefs(request: Request, device_id: str = ""):
    s = _need_login(request)
    uid = s.get("user_id") or s.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Sin usuario")
    data = _load_map(uid)
    devs = data.get("devices") or {}
    pref = dict(_DEFAULTS)
    if device_id and isinstance(devs.get(device_id), dict):
        pref = _clean(devs[device_id])
    return {"device_id": device_id, "prefs": pref}


@router.post("/api/ambient/prefs")
async def save_prefs(body: PrefBody, request: Request):
    s = _need_login(request)
    uid = s.get("user_id") or s.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Sin usuario")
    dev = (body.device_id or "").strip() or "default"
    data = _load_map(uid)
    if not isinstance(data.get("devices"), dict):
        data["devices"] = {}
    cur = _clean(data["devices"].get(dev) or {})
    raw = body.model_dump(exclude_none=True)
    raw.pop("device_id", None)
    merged = dict(cur)
    merged.update(raw)
    data["devices"][dev] = _clean(merged)
    _save_map(uid, data)
    return {"ok": True, "device_id": dev, "prefs": data["devices"][dev]}
