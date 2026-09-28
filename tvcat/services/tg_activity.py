"""Actividad Telegram (para el feeder de sonda en reposo).

`mark()` = hubo petición Telegram de verdad (escaneos, covers, copias,
reproducción...). El worker de sonda NO marca (si no, nunca habría reposo).
`idle_seconds()` = segundos desde la última actividad.
"""
import time

_last = {"ts": time.time()}


def mark():
    try:
        _last["ts"] = time.time()
    except Exception:
        pass


def idle_seconds() -> float:
    try:
        return max(0.0, time.time() - float(_last.get("ts") or 0.0))
    except Exception:
        return 0.0
