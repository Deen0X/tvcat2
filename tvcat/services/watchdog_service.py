"""Watchdog de salud de Telegram + auto-reinicio de emergencia (CORE).

Problema: a veces la cuenta queda en un estado wedged (sockets muertos,
reconnects que no prosperan) sin quemar la sesión. Todo falla con errores
de transporte, la cola no avanza y solo un reinicio lo arregla.

Este servicio:
1. REGISTRA eventos de salud (fallos de transporte, reconnects fallidos,
   FloodWait, auth muerta, tareas completadas). Flood/auth NUNCA disparan
   reinicio (el Flood se calma solo; la auth quemada no la arregla reiniciar).
2. EVALÚA cada minuto si hay fallo SISTÉMICO: N fallos de transporte en
   ventana, K reconnects fallidos, o cola con trabajo pendiente y cero
   completadas durante stall_min con al menos un fallo en el periodo.
3. Si está armado + en ventana horaria + fuera de cooldown, EJECUTA el
   comando de reinicio (defecto: `docker restart tvcat2`, mismo que el
   endpoint /api/admin/restart-custom) y deja constancia en settings.

Ajustes (tvcat_settings, UI en Comportamiento Telegram):
  watchdog_enabled ("0"/"1", defecto 0 = solo observa y registra)
  watchdog_hours ("02:00-06:00", admite cruce de medianoche)
  watchdog_fail_threshold (defecto 8 fallos de transporte)
  watchdog_window_min (defecto 15)
  watchdog_stall_min (defecto 20, cola parada con trabajo pendiente)
  watchdog_cooldown_min (defecto 180 entre auto-reinicios)
  watchdog_restart_cmd (defecto "docker restart tvcat2")
"""
import re
import time as _time
from collections import deque

_EVENTS = deque(maxlen=500)  # (ts, kind, detail)
_COMPLETED = {"n": 0, "ts": 0.0}
_DOCKER_CACHE = {"ts": 0.0, "ok": False, "detail": ""}

_KIND_FLOOD = "flood"
_KIND_AUTH = "auth_dead"
_KIND_TRANSPORT = "transport_fail"
_KIND_RECONNECT = "reconnect_fail"


def _setting(key, default=None):
    try:
        from services.catalog_service import get_conn
    except Exception:
        try:
            from tvcat.services.catalog_service import get_conn
        except Exception:
            return default
    try:
        conn = get_conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (key,)).fetchone()
        conn.close()
        if row is None:
            return default
        v = row[0] if not isinstance(row, dict) else row.get("value")
        return default if v is None else v
    except Exception:
        return default


def _setting_int(key, default):
    try:
        return int(float(_setting(key, default)))
    except Exception:
        return default


def get_settings() -> dict:
    return {
        "enabled": str(_setting("watchdog_enabled", "0") or "0") == "1",
        "hours": str(_setting("watchdog_hours", "02:00-06:00") or "02:00-06:00"),
        "fail_threshold": max(2, _setting_int("watchdog_fail_threshold", 8)),
        "window_min": max(2, _setting_int("watchdog_window_min", 15)),
        "stall_min": max(2, _setting_int("watchdog_stall_min", 20)),
        "cooldown_min": max(10, _setting_int("watchdog_cooldown_min", 180)),
        "restart_cmd": str(_setting("watchdog_restart_cmd", "docker restart tvcat2")
                           or "docker restart tvcat2"),
    }


def classify_error(e) -> str:
    """flood | auth_dead | transport_fail. Nunca lanza."""
    try:
        name = type(e).__name__ if e is not None else ""
        txt = ("%s %s" % (name, str(e or ""))).upper()
        if "FLOOD" in txt or "FLOODWAIT" in txt.replace("_", "").replace(" ", ""):
            return _KIND_FLOOD
        for sig in ("AUTH_KEY_DUPLICATED", "AUTH_KEY", "SESSION_REVOKED",
                    "SESSION_PASSWORD_NEEDED", "USER_DEACTIVATED",
                    "PHONE_NUMBER_BANNED", "API_ID_INVALID", "API_HASH"):
            if sig in txt:
                return _KIND_AUTH
        return _KIND_TRANSPORT
    except Exception:
        return _KIND_TRANSPORT


def record(kind: str, detail: str = ""):
    """Registra un evento de salud. Nunca lanza."""
    try:
        _EVENTS.append((_time.time(), str(kind or ""), str(detail or "")[:200]))
    except Exception:
        pass


def note_completion():
    try:
        _COMPLETED["n"] += 1
        _COMPLETED["ts"] = _time.time()
    except Exception:
        pass


def _counts_since(cutoff: float) -> dict:
    out = {_KIND_TRANSPORT: 0, _KIND_RECONNECT: 0, _KIND_FLOOD: 0, _KIND_AUTH: 0}
    try:
        for ts, kind, _d in list(_EVENTS):
            if ts >= cutoff and kind in out:
                out[kind] += 1
    except Exception:
        pass
    return out


def in_window(now_ts: float = None, hours: str = "") -> bool:
    """¿now dentro de 'HH:MM-HH:MM'? Admite cruce de medianoche. Malformado = True."""
    try:
        h = (hours or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", h)
        if not m:
            return True
        h1, m1, h2, m2 = (int(m.group(1)) % 24, int(m.group(2)) % 60,
                          int(m.group(3)) % 24, int(m.group(4)) % 60)
        import datetime as _dt
        now = _dt.datetime.fromtimestamp(now_ts if now_ts else _time.time())
        cur = now.hour * 60 + now.minute
        lo, hi = h1 * 60 + m1, h2 * 60 + m2
        if lo <= hi:
            return lo <= cur < hi
        return cur >= lo or cur < hi
    except Exception:
        return True


def docker_ok() -> dict:
    """¿Hay CLI docker utilizable? Cache 10 min. Nunca lanza."""
    try:
        now = _time.time()
        if now - float(_DOCKER_CACHE.get("ts") or 0) < 600 and _DOCKER_CACHE.get("detail") != "":
            return {"ok": bool(_DOCKER_CACHE.get("ok")), "detail": _DOCKER_CACHE.get("detail")}
    except Exception:
        pass
    ok, detail = False, "sin comprobar"
    try:
        import shutil as _sh
        cli = _sh.which("docker")
        if not cli:
            detail = "sin CLI docker en el contenedor"
        else:
            import subprocess as _sp
            r = _sp.run([cli, "version", "--format", "{{.Server.Version}}"],
                        capture_output=True, timeout=10)
            if r.returncode == 0:
                ok = True
                detail = "docker server %s" % (r.stdout.decode("utf-8", "replace").strip() or "?")
            else:
                detail = "docker sin acceso al daemon (¿socket montado?)"
    except Exception as e:
        detail = "probe docker: %s" % str(e)[:100]
    try:
        _DOCKER_CACHE["ts"] = _time.time()
        _DOCKER_CACHE["ok"] = ok
        _DOCKER_CACHE["detail"] = detail
    except Exception:
        pass
    return {"ok": ok, "detail": detail}


def _last_fire() -> tuple:
    try:
        v = _setting("watchdog_last", "")
        r = _setting("watchdog_last_reason", "")
        return (str(v or ""), str(r or ""))
    except Exception:
        return ("", "")


def evaluate(queue_pending: int = 0) -> dict:
    """Decide si hay que reiniciar. Retorna {fire, reason, info}.
    Nunca lanza, nunca ejecuta nada."""
    cfg = get_settings()
    now = _time.time()
    info = {"enabled": cfg["enabled"], "in_window": in_window(now, cfg["hours"]),
            "queue_pending": int(queue_pending or 0)}
    if not cfg["enabled"]:
        return {"fire": False, "reason": "", "info": info}
    last_ts_s, _ = _last_fire()
    try:
        last_ts = float(last_ts_s or 0)
    except Exception:
        last_ts = 0.0
    if last_ts and (now - last_ts) < cfg["cooldown_min"] * 60:
        info["cooldown_left_min"] = round((cfg["cooldown_min"] * 60 - (now - last_ts)) / 60, 1)
        return {"fire": False, "reason": "", "info": info}
    if not info["in_window"]:
        return {"fire": False, "reason": "", "info": info}
    wcut = now - cfg["window_min"] * 60
    counts = _counts_since(wcut)
    info["counts"] = counts
    # A) ráfaga de fallos de transporte en ventana.
    if counts[_KIND_TRANSPORT] >= cfg["fail_threshold"]:
        return {"fire": True,
                "reason": "%d fallos de transporte en %d min (cola parada)"
                          % (counts[_KIND_TRANSPORT], cfg["window_min"]),
                "info": info}
    # B) reconnects que no prosperan.
    if counts[_KIND_RECONNECT] >= 3:
        return {"fire": True,
                "reason": "%d reconnects fallidos en %d min (cliente wedged)"
                          % (counts[_KIND_RECONNECT], cfg["window_min"]),
                "info": info}
    # C) cola con trabajo pendiente y cero completadas en stall_min, con al
    # menos un fallo en el periodo (evita reiniciar por simple inactividad).
    if int(queue_pending or 0) > 0:
        scut = now - cfg["stall_min"] * 60
        scounts = _counts_since(scut)
        last_ok = float(_COMPLETED.get("ts") or 0)
        if last_ok < scut and (scounts[_KIND_TRANSPORT] + scounts[_KIND_RECONNECT]) > 0:
            return {"fire": True,
                    "reason": ("cola con %d pendientes y 0 completadas en %d min "
                               "(%d fallos transporte/reconnect)")
                              % (int(queue_pending), cfg["stall_min"],
                                 scounts[_KIND_TRANSPORT] + scounts[_KIND_RECONNECT]),
                    "info": info}
    return {"fire": False, "reason": "", "info": info}


def fire(reason: str) -> dict:
    """Ejecuta el reinicio de emergencia. Registra antes de lanzar."""
    cfg = get_settings()
    try:
        from services.catalog_service import get_conn
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                     ("watchdog_last", str(_time.time())))
        conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                     ("watchdog_last_reason", str(reason or "")[:300]))
        conn.commit()
        conn.close()
    except Exception:
        pass
    print(f" [WATCHDOG] REINICIO DE EMERGENCIA: {reason}", flush=True)
    print(f" [WATCHDOG] Ejecutando: {cfg['restart_cmd']}", flush=True)
    try:
        import subprocess as _sp
        _sp.Popen(cfg["restart_cmd"], shell=True,
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                  start_new_session=True)
        return {"ok": True, "reason": reason, "cmd": cfg["restart_cmd"]}
    except Exception as e:
        print(f" [WATCHDOG] No se pudo lanzar el reinicio: {e}", flush=True)
        return {"ok": False, "reason": reason, "error": str(e)[:200]}


def status(queue_pending: int = 0) -> dict:
    """Estado para el endpoint/UI. Nunca lanza."""
    try:
        cfg = get_settings()
        now = _time.time()
        ev = evaluate(queue_pending)
        last_ts, last_reason = _last_fire()
        recent = []
        try:
            for ts, kind, det in list(_EVENTS)[-15:]:
                import datetime as _dt
                recent.append({"t": _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S"),
                               "kind": kind, "detail": det})
        except Exception:
            pass
        return {"ok": True, "enabled": cfg["enabled"], "settings": cfg,
                "in_window": ev["info"].get("in_window"),
                "would_fire": bool(ev["fire"]), "fire_reason": ev.get("reason") or "",
                "counts_15m": _counts_since(now - 900),
                "completed_total": int(_COMPLETED.get("n") or 0),
                "docker": docker_ok(),
                "last_fire": last_ts, "last_reason": last_reason,
                "recent": recent}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


async def run():
    """Bucle del watchdog. Pensado para `_spawn` (cancelable)."""
    print(" [WATCHDOG] vigilante iniciado (observa; reinicia solo si está armado)", flush=True)
    try:
        import asyncio as _aio
        while True:
            try:
                pending = 0
                try:
                    from services.telegram_service import get_telegram_service as _gts
                    svc = _gts()
                    q = getattr(svc, "queue", None)
                    if q is not None and hasattr(q, "qsize"):
                        pending = int(q.qsize() or 0)
                except Exception:
                    pending = 0
                ev = evaluate(pending)
                if ev.get("fire"):
                    fire(ev.get("reason") or "fallo sistémico")
                    try:
                        await _aio.sleep(120)
                    except Exception:
                        pass
            except Exception as e:
                print(f" [WATCHDOG] {e}", flush=True)
            try:
                await _aio.sleep(60)
            except Exception:
                raise
    except _aio.CancelledError:
        print(" [WATCHDOG] detenido", flush=True)
        raise
