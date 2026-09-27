"""Árbitro de demanda de reproducción (F3 QueuePriority).

Los reproductores avisan con heartbeat (cada ~5s con su buffer en segundos).
La cola TGHirayi (y futuros plugins) consulta `queue_may_download()` antes de
descargar; a mitad de fichero, la cesión se propaga por la bandera YIELD de
`abort_flags` (los servicios la chequean por chunk sin reintentar ni borrar).

Ajustes (`tvcat_settings`): `tg_bg_downloads` (0/1, default 0 = pausar en
reproducción), `tg_buf_low` (24), `tg_buf_high` (60).
"""

import time as _time

_PLAYERS = {}  # player_id -> {"seen": ts, "buffer": secs|None}
_YIELDING = False
_IDLE_SECS = 90


def _setting(key, default=None):
    try:
        from services.catalog_service import get_conn
        conn = get_conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def _num(key, default):
    try:
        return float(_setting(key, default))
    except Exception:
        return float(default)


def note_heartbeat(player_id, buffered=None):
    """Registra actividad de un reproductor. buffered: segundos en buffer o None."""
    try:
        if not player_id:
            return
        buf = None
        try:
            if buffered is not None:
                buf = float(buffered)
        except Exception:
            buf = None
        _PLAYERS[str(player_id)] = {"seen": _time.time(), "buffer": buf}
    except Exception:
        pass


def drop_player(player_id):
    try:
        _PLAYERS.pop(str(player_id), None)
    except Exception:
        pass


def active_players():
    now = _time.time()
    dead = [pid for pid, p in _PLAYERS.items() if now - p.get("seen", 0) >= _IDLE_SECS]
    for pid in dead:
        try:
            del _PLAYERS[pid]
        except Exception:
            pass
    return dict(_PLAYERS)


def min_buffer():
    act = active_players()
    if not act:
        return None
    bufs = [p["buffer"] for p in act.values() if isinstance(p.get("buffer"), (int, float))]
    if not bufs:
        return 0.0
    return min(bufs)


def _set_yield(flag):
    try:
        from services import abort_flags as _af
    except Exception:
        try:
            from tvcat.services import abort_flags as _af
        except Exception:
            return
    try:
        _af.set_yield_download(bool(flag))
    except Exception:
        pass


def evaluate():
    """¿Puede la cola descargar ahora? Actualiza la bandera YIELD."""
    global _YIELDING
    act = active_players()
    if not act:
        _YIELDING = False
        _set_yield(False)
        return True
    bg = str(_setting("tg_bg_downloads", "0")) == "1"
    low = _num("tg_buf_low", 24)
    high = _num("tg_buf_high", 60)
    if high < low:
        high = low
    if not bg:
        _YIELDING = True
        _set_yield(True)
        return False
    mb = min_buffer()
    if mb is None:
        mb = 0.0
    thresh = high if _YIELDING else low
    if mb < thresh:
        _YIELDING = True
        _set_yield(True)
        return False
    _YIELDING = False
    _set_yield(False)
    return True


def queue_may_download():
    try:
        return evaluate()
    except Exception:
        return True
