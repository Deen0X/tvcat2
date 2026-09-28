"""Feeder de sonda en reposo (extensión MediaProbeQueue).

Cuando el sistema lleva 120s sin peticiones Telegram (ver tg_activity), va
encolando de uno en uno los títulos sin sonda para que el worker los procese
en fondo. Se cancela solo: en cuanto hay actividad deja de alimentar (el
worker sigue con lo encolado en prioridad baja).

Modo forzado (botón Config/Enriquecedor): alimenta sin esperar reposo hasta
quedar sin faltantes. El worker sigue en BulkGate LOW: la reproducción y las
copias mantienen prioridad.
"""
import asyncio
import sqlite3
import time

from services.media_probe_queue import DB_PATH

IDLE_SECONDS = 120
TICK_IDLE = 15
TICK_FORCED = 10
FEED_IDLE = 1
FEED_FORCED = 10

FORCED = {"on": False}
_last_id = {"v": 0}


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return conn


_MISSING_WHERE = (
    "COALESCE(uc.is_collection,0)=0"
    " AND NOT EXISTS (SELECT 1 FROM media_probe_queue q"
    " WHERE q.item_id = uc.item_id OR q.item_id = CAST(uc.id AS TEXT))"
    " AND NOT EXISTS (SELECT 1 FROM episode_media em WHERE em.episode_key = "
    "(SELECT e2.episode_key FROM item_episodes e2 WHERE "
    "(e2.item_id = uc.item_id OR e2.item_id = CAST(uc.id AS TEXT)) "
    "ORDER BY COALESCE(e2.episode_number, 999999), e2.id LIMIT 1))"
)


def missing_count() -> int:
    try:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM unified_catalog uc WHERE " + _MISSING_WHERE
            ).fetchone()
            return int(row[0] or 0)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return 0


def _candidates(after_id: int, limit: int):
    try:
        conn = _conn()
        try:
            return [(int(r["id"]), str(r["item_id"])) for r in conn.execute(
                "SELECT uc.id, uc.item_id FROM unified_catalog uc WHERE uc.id > ?"
                " AND " + _MISSING_WHERE + " ORDER BY uc.id ASC LIMIT ?",
                (after_id, limit)).fetchall()]
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return []


def _max_id() -> int:
    try:
        conn = _conn()
        try:
            row = conn.execute("SELECT MAX(id) FROM unified_catalog").fetchone()
            return int(row[0] or 0)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return 0


def feed_once(max_n: int = 1) -> int:
    """Encola hasta max_n faltantes (barrido por id con wrap). Devuelve
    cuántos entraron."""
    try:
        from services.media_probe_queue import enqueue_title as _enq
    except Exception:
        try:
            from tvcat.services.media_probe_queue import enqueue_title as _enq
        except Exception:
            return 0
    fed = 0
    cycled = False
    try:
        while fed < max_n:
            cands = _candidates(_last_id["v"], 25)
            if not cands:
                if _last_id["v"] == 0 or cycled:
                    break
                _last_id["v"] = 0  # wrap: reintentar desde el inicio
                cycled = True
                continue
            for cid, iid in cands:
                _last_id["v"] = cid
                if not iid:
                    continue
                try:
                    if _enq(iid):
                        fed += 1
                        print(f" [PROBE-FEED] {iid} ({fed}/{max_n})", flush=True)
                        if fed >= max_n:
                            break
                except Exception:
                    pass
    except Exception:
        pass
    return fed


async def run():
    """Bucle del feeder. Pensado para `_spawn` (cancelable)."""
    print(" [PROBE-FEED] alimentador en reposo iniciado (120s)", flush=True)
    try:
        from services.tg_activity import idle_seconds as _idle
    except Exception:
        try:
            from tvcat.services.tg_activity import idle_seconds as _idle
        except Exception:
            _idle = lambda: 9999.0
    try:
        from services.playback_demand import queue_may_download as _may_dl
    except Exception:
        try:
            from tvcat.services.playback_demand import queue_may_download as _may_dl
        except Exception:
            _may_dl = lambda: True
    try:
        while True:
            try:
                try:
                    _can = _may_dl()
                except Exception:
                    _can = True
                if not _can:
                    # Reproduciendo: la cola de sonda se detiene del todo
                    # (ni alimentar ni consumir).
                    await asyncio.sleep(10)
                    continue
                if FORCED["on"]:
                    n = await asyncio.to_thread(feed_once, FEED_FORCED)
                    if n == 0 and missing_count() == 0:
                        FORCED["on"] = False
                        print(" [PROBE-FEED] forzado completo, auto-off", flush=True)
                    await asyncio.sleep(TICK_FORCED)
                else:
                    try:
                        idle = _idle()
                    except Exception:
                        idle = 9999.0
                    if idle >= IDLE_SECONDS:
                        await asyncio.to_thread(feed_once, FEED_IDLE)
                    await asyncio.sleep(TICK_IDLE)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f" [PROBE-FEED] {e}", flush=True)
                await asyncio.sleep(TICK_IDLE)
    except asyncio.CancelledError:
        print(" [PROBE-FEED] detenido", flush=True)
        raise
