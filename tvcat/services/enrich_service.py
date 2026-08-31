"""Enriquecedor de contenidos (CORE).

Orquestador que conecta con servicios online (TMDB, IGDB, Google Books/Open Library,
Comic Vine) para obtener metadatos de un título. Expone `search()` (candidatos) y
`get_details()` (info completa). Es una API pura: no escribe en el catálogo; cada
consumidor decide qué hacer con los datos.

Credenciales, plantillas y umbral viven en `tvcat_settings` (DB central).
"""
import json
import time
import re

from .enrich.cleaning import clean_title_aggressive
from .enrich.scoring import get_match_score
from .enrich.providers import build_providers, select_provider_name, resolve_media_type, BOOK_SUBCATS, COMIC_SUBCATS

# ─── Credenciales / config ─────────────────────────────────────────

def _load_credentials() -> dict:
    from .catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key='enrich_credentials'").fetchone()
    conn.close()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}


def _save_credentials(creds: dict):
    from .catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("enrich_credentials", json.dumps(creds)))
    conn.commit()
    conn.close()


def _load_templates() -> dict:
    from .catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key='enrich_templates'").fetchone()
    conn.close()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}


def _save_templates(templates: dict):
    from .catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("enrich_templates", json.dumps(templates)))
    conn.commit()
    conn.close()


def _load_threshold() -> float:
    from .catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key='enrich_match_threshold'").fetchone()
    conn.close()
    if not row or not row[0]:
        return 0.95
    try:
        return float(row[0])
    except Exception:
        return 0.95


# ─── Caché ─────────────────────────────────────────────────────────

def _cache_get(key: str):
    from .catalog_service import get_conn
    conn = get_conn()
    row = conn.execute("SELECT result FROM enrich_cache WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def _cache_set(key: str, value: dict):
    from .catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO enrich_cache (key, result, created_at) VALUES (?, ?, ?)",
                 (key, json.dumps(value), int(time.time())))
    conn.commit()
    conn.close()


# ─── Plantillas ────────────────────────────────────────────────────

DEFAULT_TEMPLATE = (
    "{title} ({year})\n"
    "{rating}\n"
    "{genres}\n"
    "{author}\n"
    "{description}"
)


def _resolve_template(templates: dict, category, subcategory) -> str:
    cat = (category or "").strip().lower()
    sub = (subcategory or "").strip().lower()
    cats = templates.get("categories", {}) or {}
    if sub and f"{cat}|{sub}" in cats:
        return cats[f"{cat}|{sub}"]
    if cat in cats:
        return cats[cat]
    return templates.get("fallback") or DEFAULT_TEMPLATE


def render_template(details: dict, category="", subcategory="") -> str:
    """Rellena la plantilla de cover con los datos del detalle.

    Tags disponibles (idioma neutro / inglés / español):
      {title}, {release_year}, {year}, {description}, {sinopsis}, {overview},
      {rating}, {rating_count}, {genres}, {generos}, {themes}, {temas},
      {author}, {autor}, {director}, {release_date}, {fecha}, {category},
      {categoria}, {id}, {cover}
    """
    templates = _load_templates()
    tpl = _resolve_template(templates, category, subcategory)

    def _num(v):
        if v is None:
            return ""
        try:
            return str(round(float(v), 1))
        except Exception:
            return ""

    def _json_list(v):
        if not v:
            return ""
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                return ""
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return ""

    rating = _num(details.get("api_rating"))
    rating_line = f"★ {rating}" if rating else ""
    rating_count = str(details.get("api_rating_count") or "")
    genres = _json_list(details.get("api_genres"))
    themes = _json_list(details.get("api_themes"))
    desc = details.get("api_description") or ""
    year = str(details.get("api_year") or "")
    release_date = str(details.get("api_release_date") or "")
    cover = _json_list(details.get("api_cover"))

    replacements = {
        "{title}": str(details.get("api_title") or ""),
        "{release_year}": year,
        "{year}": year,
        "{description}": desc,
        "{sinopsis}": desc,
        "{overview}": desc,
        "{rating}": rating_line,
        "{rating_count}": rating_count,
        "{genres}": genres,
        "{generos}": genres,
        "{themes}": themes,
        "{temas}": themes,
        "{author}": str(details.get("api_author") or ""),
        "{autor}": str(details.get("api_author") or ""),
        "{director}": str(details.get("api_author") or ""),
        "{release_date}": release_date,
        "{fecha}": release_date,
        "{category}": str(details.get("api_category") or ""),
        "{categoria}": str(details.get("api_category") or ""),
        "{id}": str(details.get("api_id") or ""),
        "{cover}": cover,
    }

    out = tpl
    for tag, value in replacements.items():
        out = out.replace(tag, value)
    # Colapsar líneas vacías
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()


# ─── API pública ───────────────────────────────────────────────────

async def search(query: str, category: str = "", subcategory: str = "") -> dict:
    """Busca candidatos de un título. Devuelve {candidates, has_more, provider, threshold}.
    Si el texto de búsqueda es una URL directa de themoviedb.org (movie/tv), se resuelve el
    id y media_type del propio enlace y se devuelve ese candidato directamente (sin search)."""
    provider_name = select_provider_name(category, subcategory)
    threshold = _load_threshold()
    creds = _load_credentials()
    providers = build_providers(creds)
    provider = providers[provider_name]

    if not provider_name or not _provider_enabled(provider_name, creds):
        return {"candidates": [], "has_more": False, "provider": provider_name,
                "configured": False, "threshold": threshold}

    # ── URL directa de TMDB: ej. https://www.themoviedb.org/movie/1452176-slug
    #    o https://www.themoviedb.org/tv/108978-reacher → id + media_type del enlace.
    url_match = re.match(r'^https?://(?:www\.)?themoviedb\.org/(movie|tv)/(\d+)', query.strip())
    if url_match and provider_name == 'tmdb':
        media_type = "tv" if url_match.group(1) == "tv" else "movie"
        tmdb_id = url_match.group(2)
        try:
            details = await provider.get_details(tmdb_id, media_type=media_type)
        except Exception as e:
            print(f"[ENRICH] Error TMDB directo ('{query}'): {e}", flush=True)
            details = None
        if details:
            covers = []
            try:
                covers = json.loads(details.get("api_cover") or "[]")
            except Exception:
                covers = []
            candidate = {
                "id": str(details.get("api_id") or tmdb_id),
                "title": details.get("api_title") or "",
                "poster": covers[0] if covers else None,
                "year": details.get("api_year"),
                "provider": provider_name,
                "media_type": media_type,
            }
            return {"candidates": [candidate] if candidate.get("title") else [],
                    "has_more": False, "provider": provider_name,
                    "configured": True, "threshold": threshold}

    cleaned = clean_title_aggressive(query)
    attempts = []
    if cleaned:
        attempts.append(cleaned)
    second = re.split(r'[:\-]', cleaned)[0].strip() if cleaned else ""
    if second and second != cleaned:
        attempts.append(second)

    media_type = resolve_media_type(category, subcategory) if provider_name == 'tmdb' else None

    raw_candidates = []
    for attempt in attempts:
        if not attempt or attempt.replace(' ', '').isdigit():
            continue
        try:
            if provider_name == 'tmdb':
                found = await provider.search(attempt, media_type=media_type)
            else:
                found = await provider.search(attempt)
            if found:
                raw_candidates.extend(found)
        except Exception as e:
            print(f"[ENRICH] Error search ({provider_name}, '{attempt}'): {e}", flush=True)

    # Deducir títulos y ordenar por score
    scored = []
    seen = set()
    for c in raw_candidates:
        cid = c.get("id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        score = get_match_score(cleaned or query, c.get("title") or "")
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Filtrar por umbral (0 = no filtrar, mostrar todos ordenados)
    if threshold > 0:
        scored = [x for x in scored if x[0] >= threshold]

    all_candidates = [c for _, c in scored]
    has_more = len(all_candidates) > 10
    candidates = all_candidates[:10]

    return {"candidates": candidates, "has_more": has_more, "provider": provider_name,
            "configured": True, "threshold": threshold}


async def get_details(provider_name: str, item_id: str, category: str = "", subcategory: str = "",
                      media_type_hint: str = "") -> dict:
    """Obtiene la info completa de un candidato. media_type_hint permite forzar movie/tv
    (p.ej. cuando el candidato vino de una URL directa de themoviedb.org)."""
    creds = _load_credentials()
    providers = build_providers(creds)
    provider = providers.get(provider_name)
    if not provider:
        return {}
    media_type = (media_type_hint if media_type_hint in ("movie", "tv")
                  else resolve_media_type(category, subcategory)) if provider_name == 'tmdb' else None
    try:
        if provider_name == 'tmdb':
            details = await provider.get_details(item_id, media_type=media_type)
        elif provider_name == 'books':
            # el id de books incluye sub_provider; se pasa separado
            details = await provider.get_details(item_id, sub_provider="google_books")
        else:
            details = await provider.get_details(item_id)
    except Exception as e:
        print(f"[ENRICH] Error details ({provider_name}, {item_id}): {e}", flush=True)
        return {}
    return details or {}


def _provider_enabled(provider_name: str, creds: dict) -> bool:
    creds = creds or {}
    if provider_name == 'tmdb':
        return bool((creds.get('tmdb', {}) or {}).get('api_key'))
    if provider_name == 'igdb':
        c = creds.get('igdb', {}) or {}
        return bool(c.get('client_id') and c.get('client_secret'))
    if provider_name == 'comicvine':
        return bool((creds.get('comicvine', {}) or {}).get('api_key'))
    if provider_name == 'books':
        return True  # Open Library no requiere key
    return False


def get_config() -> dict:
    """Devuelve la config (sin secretos en claro) para el frontend admin."""
    creds = _load_credentials()
    templates = _load_templates()
    threshold = _load_threshold()
    # Enmascarar secretos: devolver solo si está configurado (bool), no el valor
    masked = {}
    for k, v in creds.items():
        if isinstance(v, dict) and any(v.values()):
            masked[k] = {"configured": True}
        else:
            masked[k] = {"configured": False}
    return {
        "credentials": masked,
        "templates": templates,
        "threshold": threshold,
    }


def save_config(credentials: dict = None, templates: dict = None, threshold: float = None) -> dict:
    """Guarda la config. credentials: dict parcial (solo se actualizan los campos con valor)."""
    if threshold is not None:
        from .catalog_service import get_conn
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                     ("enrich_match_threshold", str(max(0.0, min(1.0, float(threshold))))))
        conn.commit()
        conn.close()

    if credentials is not None:
        # Merge: solo actualizar campos con valor no vacío (permite actualizar 1 proveedor)
        current = _load_credentials()
        for prov, fields in credentials.items():
            if not isinstance(fields, dict):
                continue
            current.setdefault(prov, {})
            for k, v in fields.items():
                v = (v or "").strip() if isinstance(v, str) else v
                if v:  # solo guardar si no vacío
                    current[prov][k] = v
        _save_credentials(current)

    if templates is not None:
        _save_templates(templates)

    return get_config()
