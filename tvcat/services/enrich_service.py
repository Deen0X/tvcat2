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
    _ensure_default_templates()  # idempotente + rellena fallback vacío
    conn = get_conn()
    row = conn.execute("SELECT value FROM tvcat_settings WHERE key='enrich_templates'").fetchone()
    conn.close()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}


def _ensure_default_templates():
    """Siembra la plantilla por defecto en instalación limpia o DB antigua
    sin fila (solo si falta; nunca pisa lo guardado). Además rellena el
    fallback si está vacío (migración de DBs sembradas con fallback '')."""
    try:
        from .catalog_service import get_conn
        conn = get_conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key='enrich_templates'").fetchone()
        needs = False
        if not row or not row[0]:
            needs = True
        else:
            try:
                d = json.loads(row[0])
                lst = d.get("templates") or []
                has_content = bool((d.get("fallback") or "").strip()) or any(
                    isinstance(t, dict) and (t.get("content") or "").strip() for t in lst)
                needs = not has_content
            except Exception:
                needs = True
        if needs:
            seed = {"fallback": "", "templates": [
                {"name": "Por defecto", "categories": "", "subcategories": "",
                 "content": DEFAULT_TEMPLATE}], "categories": {}}
            conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                         ("enrich_templates", json.dumps(seed, ensure_ascii=False)))
            conn.commit()
            conn.close()
            return
        # Backfill: fallback vacío → plantilla por defecto (sin tocar el resto).
        try:
            d = json.loads(row[0])
            if not (d.get("fallback") or "").strip():
                d["fallback"] = DEFAULT_TEMPLATE
                conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                             ("enrich_templates", json.dumps(d, ensure_ascii=False)))
                conn.commit()
                print("[ENRICH] fallback vacío rellenado con plantilla por defecto", flush=True)
        except Exception:
            pass
        conn.close()
    except Exception:
        pass


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
    "{foriginal_title}{fepisodes}{fyear}{frating}{frating_count}{fgenres}\n"
    "\n"
    "{fsinopsis}\n"
    "\n"
    "{fcast}{fdirector}\n"
    "\n"
    "{falt_titles}"
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
      {author}, {autor}, {director}, {directores}, {release_date}, {fecha},
      {category}, {categoria}, {id}, {cover}, {originalmsg},
      {original_title}, {titulo_original},
      {title_es}, {titulo_espana}, {title_latam}, {title_mx}, {titulo_latino},
      {alt_titles}, {titulos_alt},
      {cast}, {reparto}, {actores}, {actors}
    """
    templates = _load_templates()
    tpl = _resolve_template(templates, category, subcategory)

    # Motor unificado de tags (CORE services/enrich_tags.py).
    try:
        from services.enrich_tags import resolve_cover as _resolve_cover
    except Exception:
        from .enrich_tags import resolve_cover as _resolve_cover
    return _resolve_cover(tpl, str((details or {}).get("api_title") or ""),
                          0, details or {})


# ─── API pública ───────────────────────────────────────────────────

_SEASON_SUFFIX_PATTERNS = (
    re.compile(r"(?i)/season/(?P<n>\d{1,2})\s*$"),  # URL .../season/N
    re.compile(r"(?i)\s+(temporada|season)\s+(?P<n>\d{1,2})\s*$"),
    re.compile(r"(?i)[\s\-_]+[TS](?P<n>\d{1,2})\s*$"),  # "X T1" / "X S01"
)


def _split_season_query(q: str):
    """Separa sufijo de temporada: (título limpio, nº|None). Solo sufijo final
    y con resto no vacío (no toca "T1" a mitad ni títulos solo-numéricos)."""
    for pat in _SEASON_SUFFIX_PATTERNS:
        m = pat.search(q or "")
        if not m:
            continue
        try:
            n = int(m.group("n"))
        except Exception:
            continue
        if not (0 <= n <= 99):
            continue
        title = (q[:m.start()] or "").strip(" \t-_")
        if title:
            return title, n
    return q, None


async def search(query: str, category: str = "", subcategory: str = "",
                 episode_count: int = None, provider_override: str = "") -> dict:
    """Busca candidatos de un título. Devuelve {candidates, has_more, provider, threshold, season}.
    Si el texto es una URL directa conocida (TMDB/IGDB/Google Books/ComicVine),
    la URL es la autoridad: se resuelve ese candidato directamente (sin search),
    cambiando al proveedor de la URL si está habilitado.
    Sufijo de temporada (solo tmdb): "X temporada N" / "X season N" / "X TN" /
    "X SN" / URL .../season/N → se busca X y se devuelve season=N."""
    provider_name = (provider_override or "").strip().lower() or select_provider_name(category, subcategory)
    threshold = _load_threshold()
    creds = _load_credentials()
    providers = build_providers(creds)
    provider = providers.get(provider_name)
    if not provider:
        return {"candidates": [], "has_more": False, "provider": provider_name,
                "configured": False, "threshold": threshold}

    if not provider_name or not _provider_enabled(provider_name, creds):
        return {"candidates": [], "has_more": False, "provider": provider_name,
                "configured": False, "threshold": threshold}

    q = (query or "").strip()

    season_n = None
    if provider_name == 'tmdb':
        q, season_n = _split_season_query(q)

    def _direct_candidate(details, pid, ptitle, pposter, pyear, extra=None):
        cand = {
            "id": str(pid or ""),
            "title": ptitle or "",
            "poster": pposter,
            "year": pyear,
            "provider": provider_name,
        }
        if extra:
            cand.update(extra)
        return {"candidates": [cand] if cand.get("title") else [],
                "has_more": False, "provider": provider_name,
                "configured": True, "threshold": threshold, "season": season_n}

    # ── URL directa de TMDB: ej. https://www.themoviedb.org/movie/1452176-slug
    #    o https://www.themoviedb.org/tv/108978-reacher → id + media_type del enlace.
    #    La URL es la autoridad: se usa tal cual sin validar contra búsqueda.
    url_match = re.match(r'^https?://(?:www\.)?themoviedb\.org/(movie|tv)/(\d+)', q)
    if url_match and provider_name == 'tmdb':
        media_type = "tv" if url_match.group(1) == "tv" else "movie"
        tmdb_id = url_match.group(2)
        details = None
        try:
            details = await provider.get_details(tmdb_id, media_type=media_type)
            # TMDB puede devolver datos de un tipo distinto al solicitado
            # (p.ej. /tv/ID que es en realidad una película). Detectar y corregir:
            # primera emisión → tv; estreno cinematográfico → movie.
            if details and media_type == "tv" and details.get("api_release_date"):
                _rd = details.get("api_release_date") or ""
                _fad = details.get("first_air_date")
                if _rd and not _fad:
                    print(f"[ENRICH] TMDB auto-correct: id={tmdb_id} es película, reintentando como movie", flush=True)
                    details = await provider.get_details(tmdb_id, media_type="movie")
            elif details and media_type == "movie" and details.get("first_air_date"):
                print(f"[ENRICH] TMDB auto-correct: id={tmdb_id} es serie, reintentando como tv", flush=True)
                details = await provider.get_details(tmdb_id, media_type="tv")
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
                "media_type": details.get("api_category") or media_type,
            }
            return {"candidates": [candidate] if candidate.get("title") else [],
                    "has_more": False, "provider": provider_name,
                    "configured": True, "threshold": threshold, "season": season_n}

    # ── URL directa de IGDB: https://www.igdb.com/games/<slug> → por slug.
    #    Cambia al proveedor igdb (si habilitado): la URL es la autoridad.
    igdb_match = re.match(r'^https?://(?:www\.)?igdb\.com/games/([a-z0-9\-_]+)', q, re.IGNORECASE)
    if igdb_match and (provider_name == 'igdb' or not provider_override):
        if provider_name != 'igdb':
            if not _provider_enabled('igdb', creds):
                return {"candidates": [], "has_more": False, "provider": 'igdb',
                        "configured": False, "threshold": threshold}
            provider_name = 'igdb'
            provider = providers['igdb']
        try:
            details = await provider.get_by_slug(igdb_match.group(1).lower())
        except Exception as e:
            print(f"[ENRICH] Error IGDB directo ('{query}'): {e}", flush=True)
            details = None
        if details:
            covers = []
            try:
                covers = json.loads(details.get("api_cover") or "[]")
            except Exception:
                covers = []
            return _direct_candidate(details, details.get("api_id"),
                                     details.get("api_title"),
                                     covers[0] if covers else None,
                                     details.get("api_year"))

    # ── URL directa de Google Books: .../books/edition/<titulo>/<VOLID>[?...]
    #    → volumen directo (funciona sin key).
    books_match = re.search(r'/books/edition/[^/?#]+/([A-Za-z0-9_\-]+)', q, re.IGNORECASE)
    if books_match and (provider_name == 'books' or not provider_override):
        if provider_name != 'books':
            provider_name = 'books'
            provider = providers['books']
        try:
            details = await provider.get_details(books_match.group(1), sub_provider="google_books")
        except Exception as e:
            print(f"[ENRICH] Error Books directo ('{query}'): {e}", flush=True)
            details = None
        if details:
            covers = []
            try:
                covers = json.loads(details.get("api_cover") or "[]")
            except Exception:
                covers = []
            return _direct_candidate(details, details.get("api_id"),
                                     details.get("api_title"),
                                     covers[0] if covers else None,
                                     details.get("api_year"),
                                     extra={"sub_provider": "google_books"})

    # ── URL directa de ComicVine: .../<slug>/<type>-<id>/ → issue directo.
    cv_match = re.search(r'comicvine\.gamespot\.com/[^?\s]*/(\d+)-(\d+)/?', q, re.IGNORECASE)
    if cv_match and (provider_name == 'comicvine' or not provider_override):
        if provider_name != 'comicvine':
            if not _provider_enabled('comicvine', creds):
                return {"candidates": [], "has_more": False, "provider": 'comicvine',
                        "configured": False, "threshold": threshold}
            provider_name = 'comicvine'
            provider = providers['comicvine']
        try:
            details = await provider.get_details(f"{cv_match.group(1)}-{cv_match.group(2)}")
        except Exception as e:
            print(f"[ENRICH] Error ComicVine directo ('{query}'): {e}", flush=True)
            details = None
        if details:
            covers = []
            try:
                covers = json.loads(details.get("api_cover") or "[]")
            except Exception:
                covers = []
            return _direct_candidate(details, details.get("api_id"),
                                     details.get("api_title"),
                                     covers[0] if covers else None,
                                     None)

    cleaned = clean_title_aggressive(query)
    attempts = []
    if cleaned:
        attempts.append(cleaned)
    second = re.split(r'[:\-]', cleaned)[0].strip() if cleaned else ""
    if second and second != cleaned:
        attempts.append(second)

    media_type = resolve_media_type(category, subcategory) if provider_name == 'tmdb' else None
    # Si episode_count indica múltiples episodios → serie probable → TV primero.
    # Si 1 episodio o desconocido → película probable → movie primero.
    # En ambos casos, si el primer intento no da resultados, se prueba el otro.
    if provider_name == 'tmdb':
        if episode_count is not None and episode_count > 1:
            search_order = ('tv', 'movie')
        else:
            search_order = ('movie', 'tv')
    else:
        search_order = (media_type,)

    print(f"[ENRICH] search query='{query}' cleaned='{cleaned}' attempts={attempts} cat='{category}' sub='{subcategory}' -> provider={provider_name} episode_count={episode_count} search_order={search_order}", flush=True)

    raw_candidates = []
    for attempt in attempts:
        if not attempt or attempt.replace(' ', '').isdigit():
            continue
        try:
            if provider_name == 'tmdb':
                for mt in search_order:
                    found = await provider.search(attempt, media_type=mt)
                    print(f"[ENRICH] provider.search('{attempt}', media_type={mt}) -> {len(found) if found else 0} resultados", flush=True)
                    if found:
                        raw_candidates.extend(found)
            else:
                found = await provider.search(attempt)
                print(f"[ENRICH] provider.search('{attempt}') -> {len(found) if found else 0} resultados", flush=True)
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
        # El título localizado puede no parecerse a la query ("Batman vuelve"
        # vs "Batman Returns"): puntuar también contra el original y quedarse
        # con la mejor nota para no filtrar candidatos válidos por idioma.
        score = max(
            get_match_score(cleaned or query, c.get("title") or ""),
            get_match_score(cleaned or query, c.get("original_title") or c.get("original_name") or ""),
        )
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Filtrar por umbral (0 = no filtrar, mostrar todos ordenados)
    if threshold > 0:
        scored = [x for x in scored if x[0] >= threshold]

    all_candidates = [c for _, c in scored]
    has_more = len(all_candidates) > 10
    candidates = all_candidates[:10]

    return {"candidates": candidates, "has_more": has_more, "provider": provider_name,
            "configured": True, "threshold": threshold, "season": season_n}


async def get_details(provider_name: str, item_id: str, category: str = "", subcategory: str = "",
                      media_type_hint: str = "", sub_provider: str = "", season: int = None) -> dict:
    """Obtiene la info completa de un candidato. media_type_hint permite forzar movie/tv
    (p.ej. cuando el candidato vino de una URL directa de themoviedb.org).
    season (solo tmdb/tv): fusiona el detalle de /tv/{id}/season/{n}."""
    creds = _load_credentials()
    providers = build_providers(creds)
    provider = providers.get(provider_name)
    if not provider:
        return {}
    media_type = (media_type_hint if media_type_hint in ("movie", "tv")
                  else resolve_media_type(category, subcategory)) if provider_name == 'tmdb' else None
    try:
        if provider_name == 'tmdb':
            details = await provider.get_details(item_id, media_type=media_type, season=season)
        elif provider_name == 'books':
            # El candidato indica de dónde vino (google_books u open_library).
            details = await provider.get_details(
                item_id, sub_provider=sub_provider or "google_books")
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
