"""
Registro agnóstico de proveedores de cover enriquecido.

Cada proveedor registra una función `fn(channelid_msgid: str) -> Optional[dict]`
que devuelve, si existe enriquecimiento para esa clave:

    {
        "cover_text": str,
        "enrich_details": dict,
        "poster_blob": bytes | None,
        "poster_mime": str,
    }

Consultado por:
  - gateway.py  GET /api/cover/{item_id}  (antes de JIT)
  - gateway.py  GET /api/movie/{item_id}  (description)
  - tvcat_TGHirayi/routes.py  (bridge caso 2)
"""
from typing import Optional, Dict, Callable, Any

_PROVIDERS: Dict[str, Callable[[str], Optional[Dict[str, Any]]]] = {}


def register_cover_override_provider(name: str, fn: Callable[[str], Optional[Dict[str, Any]]]) -> None:
    _PROVIDERS[name] = fn


def unregister_cover_override_provider(name: str) -> None:
    _PROVIDERS.pop(name, None)


def get_enriched_cover(channelid_msgid: str) -> Optional[Dict[str, Any]]:
    if not channelid_msgid:
        return None
    for fn in _PROVIDERS.values():
        try:
            res = fn(channelid_msgid)
            if res:
                return res
        except Exception:
            pass
    return None


def get_enriched_by_item_id(item_id: str) -> Optional[Dict[str, Any]]:
    """Conveniencia: deriva channelid_msgid desde item_id (telegram_link) y consulta.
    Usa services.cache_keys (único criterio)."""
    if not item_id:
        return None
    try:
        from services.catalog_service import get_conn
        from services.cache_keys import key_from_link, canon_key, canon_channel
        conn = get_conn()
        row = conn.execute(
            "SELECT telegram_link, telegram_msg_id FROM unified_catalog WHERE item_id=?",
            (item_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        link = row["telegram_link"] or ""
        key = key_from_link(link)
        if not key:
            # Fallback por telegram_msg_id directo si el link no da clave
            tid = row["telegram_msg_id"]
            if tid:
                import re as _re
                m = _re.search(r"/c/(\d+)/", link or "")
                if m:
                    key = canon_key(canon_channel(m.group(1)), tid)
        if not key:
            return None
        return get_enriched_cover(key)
    except Exception:
        return None
