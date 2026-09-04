"""
Claves canónicas de caché — ÚNICO criterio de direccionamiento (channel, msg).

- `canon_channel(value)` → string numérico SIN prefijo -100. Ej: "-1003603188285" → "3603188285".
  No numérico (username) → tal cual en minúsculas. '' → ''.
- `canon_key(channel, msg_id)` → "3603188285_5145" (formato channelid_msgid / episode_key).
- `key_from_link(telegram_link)` → canon_key desde t.me/c/{channel}/{msg} (topic intermedio ignorado).
  Sustituye a `catalog_service._derive_episode_key` y al `_derive_key` del enricher
  (se mantienen como wrappers por compatibilidad).

Toda lectura/escritura de `telegram_message_cache` y `catalog_assets` DEBE pasar
por aquí. Nada de variantes ±-100 fuera de este módulo.
"""
import re

_C_LINK_RE = re.compile(r"/c/(\d+)/(?:(\d+)/)?(\d+)")


def canon_channel(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # Quitar signo y prefijo -100/100 de Telegram: -100X | 100X | X → X
    t = s.lstrip("-").lstrip("+")
    if t.startswith("100") and t[3:].isdigit() and len(t) > 10:
        # -100xxxxxxxxxx (canal) → xxxxxxxxxx. Ojo: no confundir con un id corto que empiece por 100.
        return t[3:]
    if t.isdigit():
        return t
    return s.lower()


def canon_key(channel, msg_id) -> str:
    try:
        mid = int(msg_id)
    except (TypeError, ValueError):
        return ""
    ch = canon_channel(channel)
    if not ch or not mid:
        return ""
    return f"{ch}_{mid}"


def key_from_link(telegram_link: str) -> str:
    if not telegram_link:
        return ""
    m = _C_LINK_RE.search(telegram_link)
    if not m:
        return ""
    return canon_key(m.group(1), m.group(3))


def split_key(channelid_msgid: str):
    """Inversa de canon_key → (channel, msg_id:int|None)."""
    if not channelid_msgid or "_" not in str(channelid_msgid):
        return ("", None)
    ch, _, mid = str(channelid_msgid).rpartition("_")
    try:
        return (canon_channel(ch), int(mid))
    except (TypeError, ValueError):
        return (canon_channel(ch), None)
