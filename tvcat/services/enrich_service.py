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


def _sanitize_tpl_val(s: str) -> str:
    v = (s or "").strip().lower()
    if v == "*":
        return "*"
    return re.sub(r"[^a-z0-9]", "", v)


def _resolve_template(templates: dict, category, subcategory) -> str:
    # Nuevo formato: templates.templates = [{name, categories, subcategories, content}]
    lst = templates.get("templates") or []
    if isinstance(lst, list) and lst:
        cat_n = _sanitize_tpl_val(category)
        sub_n = _sanitize_tpl_val(subcategory)
        for tpl in lst:
            if not isinstance(tpl, dict):
                continue
            content = tpl.get("content") or ""
            if not content:
                continue
            # categorías / subcategorías como "a; b; c" o lista
            raw_cats = tpl.get("categories", "") or ""
            raw_subs = tpl.get("subcategories", "") or ""
            # permitir lista o string
            if isinstance(raw_cats, list):
                cats = [str(x) for x in raw_cats]
            else:
                cats = [x.strip() for x in str(raw_cats).split(";")]
            if isinstance(raw_subs, list):
                subs = [str(x) for x in raw_subs]
            else:
                subs = [x.strip() for x in str(raw_subs).split(";")]
            cats_n = [_sanitize_tpl_val(x) for x in cats if x.strip()]
            subs_n = [_sanitize_tpl_val(x) for x in subs if x.strip()]
            # comodín * o vacío en el template → no filtra (coincide con cualquiera)
            cat_match = not cats_n or "*" in cats_n or cat_n in cats_n
            sub_match = not subs_n or "*" in subs_n or sub_n in subs_n
            # Primera ocurrencia que coincide en alguna de las dos listas
            if cat_match or sub_match:
                # Requiere al menos una lista con datos; si ambas vacías, es genérica (matchea todo, pero la pondremos al final)
                # Evitar que una plantilla genérica capture todo al inicio: solo matchea si al menos una lista tiene datos
                if cats_n or subs_n:
                    return content
                # Si ambas vacías, solo si no hay otra (fallback genérico) — la dejamos como último recurso
        # Si ninguna del nuevo formato matchea, probar genérica vacía
        for tpl in lst:
            if isinstance(tpl, dict) and not (tpl.get("categories") or "").strip() and not (tpl.get("subcategories") or "").strip():
                if tpl.get("content"):
                    return tpl["content"]
    # Compatibilidad: formato antiguo categories { "cat|sub": "...", "cat": "..." }
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
      {categoria}, {id}, {cover}, {originalmsg}
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
        "{originalmsg}": str(details.get("originalmsg") or details.get("original_msg") or ""),
    }

    out = tpl
    for tag, value in replacements.items():
        out = out.replace(tag, value)
    # f-tags con formato (cover_tags.json): {ftitle} -> "Title: {value}" con salto de línea, se omite si vacío
    try:
        _FTAGS = {
            "title": "Title: {value}",
            "year": "Year: {value}",
            "release_year": "Year: {value}",
            "rating": "Rating: {value}",
            "rating_count": "Rating count: {value}",
            "genres": "Genres: {value}",
            "generos": "Genres: {value}",
            "themes": "Themes: {value}",
            "temas": "Themes: {value}",
            "author": "Author: {value}",
            "autor": "Author: {value}",
            "director": "Director: {value}",
            "release_date": "Release date: {value}",
            "fecha": "Release date: {value}",
            "category": "Category: {value}",
            "categoria": "Category: {value}",
            "id": "ID: {value}",
            "cover": "Cover: {value}",
            "episodes": "Episodes: {value}",
            "ext": "Ext: {value}",
            "extension": "Ext: {value}",
            "description": "Description:\n{value}",
            "sinopsis": "Sinopsis:\n{value}",
            "overview": "Overview:\n{value}",
            "originalmsg": "{value}",
        }
        # Cargar personalizaciones desde TGHirayi si existe
        try:
            _ftags_path = os.path.join(os.path.dirname(__file__), "..", "plugins", "tvcat_TGHirayi", "data", "cover_tags.json")
            if os.path.isfile(_ftags_path):
                with open(_ftags_path, "r", encoding="utf-8") as _f:
                    _cfg = json.load(_f)
                    for _k, _v in (_cfg.get("ftags") or {}).items():
                        if isinstance(_v, str):
                            _FTAGS[_k] = _v
        except Exception:
            pass
        has_title = ("{title}" in tpl) or ("{ftitle}" in tpl)
        raw_map = {k.strip("{}"): v for k, v in replacements.items()}
        for k, f_tpl in _FTAGS.items():
            val = raw_map.get(k, "")
            rendered = f_tpl.replace("{value}", val) if val else ""
            if k == "tagtitle" and not has_title:
                rendered = ""
            f_form = "{f" + k + "}"
            if f_form in out:
                if rendered:
                    out = out.replace(f_form, rendered + "\n")
                else:
                    out = out.replace(f_form, "")
    except Exception:
        pass
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


def _load_behavior() -> dict:
    from .catalog_service import get_conn
    import json
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key='enrich_behavior'").fetchone()
    conn.close()
    if not row or not row[0]:
        return {"auto_scan": False, "overwrite": False}
    try:
        d = json.loads(row[0])
        return {"auto_scan": bool(d.get("auto_scan")), "overwrite": bool(d.get("overwrite"))}
    except Exception:
        return {"auto_scan": False, "overwrite": False}

def _save_behavior(behavior: dict):
    from .catalog_service import get_conn
    import json
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("enrich_behavior", json.dumps({"auto_scan": bool(behavior.get("auto_scan")), "overwrite": bool(behavior.get("overwrite"))})))
    conn.commit()
    conn.close()

def get_config() -> dict:
    """Devuelve la config (sin secretos en claro) para el frontend admin."""
    creds = _load_credentials()
    templates = _load_templates()
    threshold = _load_threshold()
    behavior = _load_behavior()
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
        "behavior": behavior,
    }


def save_config(credentials: dict = None, templates: dict = None, threshold: float = None, behavior: dict = None) -> dict:
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

    if behavior is not None:
        _save_behavior(behavior)

    return get_config()
