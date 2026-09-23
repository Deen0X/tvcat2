"""Motor unificado de tags del enriquecedor (CORE).

Namespace único:
  - Tags BASE: datos crudos del detalle (`{title}`, `{temporada}`, ...),
    incluido `foreignname` (lógica especial con caracteres no latinos).
  - CUSTOM tags: plantillas de usuario que referencian tags base u otros
    customs por nombre explícito (`{temporada}`). Sin `{value}`.

Reglas:
  - Vacío contagioso: si algún tag referenciado está vacío o es erróneo, el
    custom entero resuelve vacío.
  - Ciclos por visited-set (sin límite de profundidad).
  - `\n` explícitos (sin salto automático). Colapso final + strip.
  - `tagtitle` solo se emite si hay `{title}`/`{ftitle}` en el texto raíz.
  - Nombres únicos en el conjunto base+customs (lo valida el guardado).
  - Tokens desconocidos se dejan tal cual (no contagian).

Store: `tvcat_settings` clave `enrich_custom_tags` = {"custom": {...}}.
"""
import json
import re

SETTINGS_KEY = "enrich_custom_tags"

_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_SPECIAL_RE = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\uac00-\ud7af\u0400-\u04ff\u0900-\u097f\u0e00-\u0e7f\u0600-\u06ff]")


# ─── Datos base ──────────────────────────────────────────────────────

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


def _sanitize_title_tag(title: str) -> str:
    s = (title or "").lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return ("#" + s) if s else ""


def _season_number(det: dict) -> str:
    try:
        n = det.get("api_season_number")
        if n is None:
            n = det.get("api_seasons")
        return str(n or "").strip()
    except Exception:
        return ""


def _foreignname(api_title, api_original, det: dict, season_suffix: str = "") -> str:
    """Port de enricher.js foreignNameValue: títulos con caracteres CJK /
    hangul / cirílico / devanagari / tailandés / árabe expanden a 2 líneas;
    si no, solo 'Original Title:'. Con saltos explícitos. El sufijo (p. ej.
    ' - Season 1') va en la línea del título visible."""
    det = det or {}
    season_suffix = season_suffix or ""

    def _latin(s):
        s = str(s or "")
        return s if (s and not _SPECIAL_RE.search(s)) else ""

    disp = str(api_title or "")
    orig = str(api_original or "")
    special = orig if _SPECIAL_RE.search(orig) else (disp if _SPECIAL_RE.search(disp) else "")
    if special:
        cands = [det.get("api_title_en"), det.get("api_title_es"), disp,
                 det.get("api_title_latam"), det.get("api_title_mx"),
                 det.get("api_title_latino")]
        try:
            al = det.get("api_alt_titles")
            if isinstance(al, str):
                try:
                    al = json.loads(al)
                except Exception:
                    al = []
            if isinstance(al, list):
                cands.extend(al)
        except Exception:
            pass
        cands.append(orig)
        t = ""
        for cnd in cands:
            v = _latin(cnd)
            if v:
                t = v
                break
        title_line = (t + season_suffix) if t else special
        return "Title: " + title_line + "\nOriginal Title: " + special + "\n"
    o = orig or disp
    if not o:
        return ""
    return "Original Title: " + o + season_suffix + "\n"


def _foreignnameseason(api_title, api_original, det: dict) -> str:
    """Igual que foreignname pero con ' - Season X' en la línea del título
    visible (Title si hay caracteres especiales, Original Title si no).
    Sin temporada => idéntico a foreignname (título limpio)."""
    det = det or {}
    season = _season_number(det)
    suffix = (" - Season " + season) if season else ""
    return _foreignname(api_title, api_original, det, suffix)


def get_base_tags(title: str = "", total_episodes: int = 0, details: dict = None,
                  media: dict = None) -> dict:
    """Mapa completo de tags base (unión de los que usaban v2 y enricher).
    `media` (ffprobe normalizado del primer fichero; ver media_probe.py) alimenta
    las claves `_*`, que solo tienen sentido al copiar en TGHirayi. También se
    acepta dentro de `details["_media"]`. Sin media → "" (se omiten)."""
    details = details or {}
    _md = dict(media or {}) if isinstance(media, dict) else {}
    try:
        _dm = details.get("_media")
        if isinstance(_dm, dict):
            for _k, _v in _dm.items():
                _md.setdefault(_k, _v)
    except Exception:
        pass
    year = str(details.get("api_year") or details.get("api_release_date") or "")
    rating = _num(details.get("api_rating"))
    rating_line = ("★ " + rating) if rating else ""
    genres = _json_list(details.get("api_genres"))
    themes = _json_list(details.get("api_themes"))
    author = str(details.get("api_author") or "")
    director = str(details.get("api_director") or author)
    release_date = str(details.get("api_release_date") or "")
    description = str(details.get("api_description") or "")
    cover = _json_list(details.get("api_cover"))
    episodes = str(int(total_episodes or 0)) if (total_episodes or 0) > 0 else ""
    season = str(details.get("api_season_number")
                 if details.get("api_season_number") is not None
                 else (details.get("api_seasons") or ""))
    season_episodes = str(details.get("api_season_episodes") or "")
    original_title = str(details.get("api_original_title") or "")
    title_es = str(details.get("api_title_es") or "")
    title_latam = str(details.get("api_title_latam") or "")
    alt_titles = _json_list(details.get("api_alt_titles"))
    cast = _json_list(details.get("api_cast"))
    api_title = str(details.get("api_title") or title or "")
    return {
        "tagtitle": _sanitize_title_tag(details.get("api_title") or title),
        "title": api_title,
        "original_title": original_title,
        "titulo_original": original_title,
        "title_es": title_es,
        "titulo_espana": title_es,
        "title_latam": title_latam,
        "title_mx": title_latam,
        "titulo_latino": title_latam,
        "alt_titles": alt_titles,
        "titulos_alt": alt_titles,
        "cast": cast,
        "reparto": cast,
        "actores": cast,
        "actors": cast,
        "year": year,
        "release_year": year,
        "rating": rating_line,
        "rating_count": str(details.get("api_rating_count") or ""),
        "genres": genres,
        "generos": genres,
        "themes": themes,
        "temas": themes,
        "author": author,
        "autor": author,
        "director": director,
        "directores": director,
        "release_date": release_date,
        "fecha": release_date,
        "category": str(details.get("api_category") or ""),
        "categoria": str(details.get("api_category") or ""),
        "id": str(details.get("api_id") or ""),
        "cover": cover,
        "description": description,
        "sinopsis": description,
        "overview": description,
        "originalmsg": str(details.get("originalmsg") or details.get("original_msg") or ""),
        "episodes": episodes,
        "season": season,
        "temporada": season,
        "season_episodes": season_episodes,
        "ext": "",
        "extension": "",
        "foreignname": _foreignname(details.get("api_title") or title,
                                     details.get("api_original_title"), details),
        "foreignnameseason": _foreignnameseason(details.get("api_title") or title,
                                                details.get("api_original_title"), details),
        "_resolution": str(_md.get("resolution") or ""),
        "_resolutionx": str(_md.get("resolutionx") or ""),
        "_resolutiony": str(_md.get("resolutiony") or ""),
        "_vcodec": str(_md.get("vcodec") or ""),
        "_fps": str(_md.get("fps") or ""),
        "_acodec": str(_md.get("acodec") or ""),
        "_audiotracks": str(_md.get("audiotracks") or ""),
        "_fullaudiotracks": str(_md.get("fullaudiotracks") or ""),
        "_subtitles": str(_md.get("subtitles") or ""),
        "_container": str(_md.get("container") or ""),
        "_extension": str(_md.get("extension") or ""),
        "_duration": str(_md.get("duration") or ""),
        "_durationm": str(_md.get("durationm") or ""),
        "_bitrate": str(_md.get("bitrate") or ""),
        "_filesize": str(_md.get("filesize") or ""),
        "_aspectratio": str(_md.get("aspectratio") or ""),
        "_quality": str(_md.get("quality") or ""),
        "_files": str(_md.get("files") or ""),
    }


def base_tag_names() -> list:
    return sorted(get_base_tags().keys())


# ─── Customs (store) ─────────────────────────────────────────────────

def _conn():
    from services.catalog_service import get_conn
    return get_conn()


def _custom_name(key: str) -> str:
    """Nombre del custom para una clave base: `f<key>` normal, `_f<resto>`
    si la clave empieza por `_` (tags media: `{_fresolution}`, y así se
    distinguen los que solo resuelven al copiar en TGHirayi)."""
    k = str(key or "")
    if k.startswith("_"):
        return "_f" + k[1:]
    return "f" + k


def _default_customs() -> dict:
    """Customs equivalentes a _legacy_defaults (sin leer fichero): base para
    mergear bajo los guardados (así los tags nuevos aparecen en instalaciones
    viejas sin pisar personalizaciones)."""
    out = {}
    for k, tpl in _legacy_defaults().items():
        if not isinstance(tpl, str):
            continue
        body = tpl.replace("{value}", "{" + str(k) + "}")
        if not body.endswith("\n"):
            body += "\n"
        out[_custom_name(k)] = body
    return out


def load_customs() -> dict:
    """{nombre: plantilla}. Mergea defaults bajo lo guardado (lo guardado
    manda). Si no hay fila, migra legacy/defaults y la crea."""
    stored = None
    try:
        conn = _conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?",
                           (SETTINGS_KEY,)).fetchone()
        conn.close()
        if row and (row[0] if not isinstance(row, dict) else row.get("value")):
            v = row[0] if not isinstance(row, dict) else row.get("value")
            d = json.loads(v)
            if isinstance(d.get("custom"), dict):
                stored = dict(d["custom"])
    except Exception:
        stored = None
    if stored is None:
        return _ensure_default_customs()
    try:
        merged = _default_customs()
        merged.update(stored)
        return merged
    except Exception:
        return stored


def _ensure_default_customs() -> dict:
    try:
        customs = migrate_legacy()
        save_customs(customs)
        return customs
    except Exception:
        return {}


def save_customs(customs: dict):
    conn = _conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 (SETTINGS_KEY, json.dumps({"custom": dict(customs or {})},
                                           ensure_ascii=False)))
    conn.commit()
    conn.close()


def _legacy_defaults() -> dict:
    """Defaults históricos (unión v2 + enricher) con {value}."""
    return {
        "tagtitle": "{value}",
        "title": "Title: {value}",
        "title_en": "Title EN: {value}",
        "original_title": "Original title: {value}",
        "titulo_original": "Original title: {value}",
        "title_es": "Title ES: {value}",
        "titulo_espana": "Title ES: {value}",
        "title_latam": "Title Latam: {value}",
        "title_mx": "Title Latam: {value}",
        "titulo_latino": "Title Latam: {value}",
        "alt_titles": "Alt titles: {value}",
        "titulos_alt": "Alt titles: {value}",
        "cast": "Cast: {value}",
        "reparto": "Cast: {value}",
        "actores": "Cast: {value}",
        "actors": "Cast: {value}",
        "year": "Year: {value}",
        "release_year": "Year: {value}",
        "season": "Season: {value}",
        "temporada": "Season: {value}",
        "season_episodes": "Season episodes: {value}",
        "rating": "Rating: {value}",
        "rating_count": "Rating count: {value}",
        "genres": "Genres: {value}",
        "generos": "Genres: {value}",
        "themes": "Themes: {value}",
        "temas": "Themes: {value}",
        "author": "Author: {value}",
        "autor": "Author: {value}",
        "director": "Director: {value}",
        "directores": "Director: {value}",
        "release_date": "Release date: {value}",
        "fecha": "Release date: {value}",
        "category": "Category: {value}",
        "categoria": "Category: {value}",
        "id": "ID: {value}",
        "cover": "Cover: {value}",
        "episodes": "Episodes: {value}",
        "_resolution": "Resolution: {value}",
        "_resolutionx": "Resolution X: {value}",
        "_resolutiony": "Resolution Y: {value}",
        "_vcodec": "Video: {value}",
        "_fps": "FPS: {value}",
        "_acodec": "Audio: {value}",
        "_audiotracks": "Audio tracks: {value}",
        "_fullaudiotracks": "Full audio: {value}",
        "_subtitles": "Subtitles: {value}",
        "_container": "Container: {value}",
        "_extension": "Ext: {value}",
        "_duration": "Duration: {value}",
        "_durationm": "Duration: {value} min",
        "_bitrate": "Bitrate: {value} Kbps",
        "_filesize": "Size: {value}",
        "_aspectratio": "Aspect: {value}",
        "_quality": "Quality: {value}",
        "_files": "Files: {value}",
        "ext": "Ext: {value}",
        "extension": "Ext: {value}",
        "description": "Description:\n{value}",
        "sinopsis": "Sinopsis:\n{value}",
        "overview": "Overview:\n{value}",
        "originalmsg": "{value}",
    }


def migrate_legacy() -> dict:
    """v1 cover_tags.json (si existe) o defaults => customs {fclave} con
    referencias explícitas y \\n final. Sin {value}."""
    src = dict(_legacy_defaults())
    try:
        import os
        p = os.path.join(os.path.dirname(__file__), "..", "plugins",
                         "tvcat_TGHirayi", "data", "cover_tags.json")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                file_ftags = (json.load(f).get("ftags") or {})
            for k, v in file_ftags.items():
                if isinstance(v, str):
                    src[k] = v
    except Exception:
        pass
    out = {}
    for k, tpl in src.items():
        if not isinstance(tpl, str):
            continue
        body = tpl.replace("{value}", "{" + str(k) + "}")
        if not body.endswith("\n"):
            body += "\n"
        out[_custom_name(k)] = body
    return out


# ─── Resolución ──────────────────────────────────────────────────────

def _resolve_token(token: str, base: dict, customs: dict, visited: tuple,
                   has_title: bool) -> str:
    """Resuelve UN token. visited = cadena de customs en expansión (ciclos)."""
    if token in visited:
        return ""
    if token == "tagtitle" and not has_title:
        return ""
    if token in customs:
        body = customs.get(token) or ""
        expanded, ok = _expand(body, base, customs, visited + (token,), has_title)
        return expanded if ok else ""
    if token in base:
        return base.get(token) or ""
    return "{" + token + "}"


def _expand(body: str, base: dict, customs: dict, visited: tuple,
            has_title: bool):
    """Expande customs: (texto, todo_ok). Si algún tag referenciado está
    vacío, todo_ok=False y el custom entero debe resolverse vacío."""
    if not body:
        return "", True
    ok = True

    def _rep(m):
        nonlocal ok
        token = m.group(1)
        # ¿referencia a custom/base conocido?
        if token in customs or token in base or token in ("tagtitle",):
            r = _resolve_token(token, base, customs, visited, has_title)
            if r == "":
                ok = False
            return r
        return m.group(0)

    try:
        return _TOKEN_RE.sub(_rep, body), ok
    except Exception:
        return "", False


def resolve(text: str, base: dict, customs: dict) -> str:
    """Resuelve una plantilla completa. Tokens desconocidos se dejan tal cual."""
    if not text:
        return text
    base = base or {}
    customs = customs or {}
    has_title = ("{title}" in text) or ("{ftitle}" in text)

    def _rep(m):
        token = m.group(1)
        if token in customs or token in base or token in ("tagtitle",):
            if token in customs:
                expanded, ok = _expand(customs.get(token) or "", base, customs,
                                       (token,), has_title)
                return expanded if ok else ""
            return _resolve_token(token, base, customs, (), has_title)
        return m.group(0)

    try:
        out = _TOKEN_RE.sub(_rep, text)
    except Exception:
        return text
    out = re.sub(r"\n{3,}", "\n\n", out)
    # Sin strip() total: un custom inline puede empezar por espacio intencional
    # (" - Season 1"). Solo se recortan saltos iniciales y la cola.
    return out.lstrip("\n").rstrip()


def resolve_cover(text: str, title: str = "", total_episodes: int = 0,
                  details: dict = None, media: dict = None) -> str:
    """Atajo: base + customs cargados + resolve. `media` alimenta los tags `_*`."""
    try:
        base = get_base_tags(title, total_episodes, details or {}, media=media)
        customs = load_customs()
        return resolve(text or "", base, customs)
    except Exception:
        return text or ""


# ─── Validación (editor) ─────────────────────────────────────────────

_MEDIA_TOKEN_RE = re.compile(r"\{(f)?_[A-Za-z][A-Za-z0-9_]*\}")


def strip_media_tags(text: str) -> str:
    """Quita los tags `_*` (crudos y f-forma) para DISPLAY (hero, etc.).
    Esos tags solo se resuelven al copiar en TGHirayi; en el resto de
    sitios saldrían literales."""
    if not text:
        return text
    try:
        out = _MEDIA_TOKEN_RE.sub("", text)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()
    except Exception:
        return text

def _refs_of(body: str) -> list:
    try:
        return _TOKEN_RE.findall(body or "")
    except Exception:
        return []


def check_cycle(name: str, body: str, customs: dict):
    """Si guardar name=body crease un ciclo, devuelve la cadena [..]; si no, None."""
    customs = dict(customs or {})
    customs[name] = body or ""
    chain = [name]
    seen = {name}

    def _visit(token, path):
        for ref in _refs_of(customs.get(token) or ""):
            if ref in customs:
                if ref in path:
                    return path + [ref]
                hit = _visit(ref, path + [ref])
                if hit:
                    return hit
        return None

    return _visit(name, [name])


def find_usages(name: str, customs: dict, templates=()) -> dict:
    """Dónde se usa {name}: customs y plantillas de cover (listas de nombres)."""
    used_in = []
    try:
        for cn, body in (customs or {}).items():
            if cn == name:
                continue
            if name in _refs_of(body or ""):
                used_in.append(cn)
    except Exception:
        pass
    in_templates = []
    try:
        for t in (templates or []):
            tname = t.get("name", "") if isinstance(t, dict) else ""
            tcontent = t.get("content", "") if isinstance(t, dict) else ""
            if name in _refs_of(tcontent or ""):
                in_templates.append(tname or "?")
    except Exception:
        pass
    return {"customs": used_in, "templates": in_templates}


def validate_custom(name: str, body: str, customs: dict):
    """(ok, error). Nombre no vacío, único en base+customs, sin ciclos."""
    n = (name or "").strip()
    if not n:
        return False, "Nombre requerido"
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", n):
        return False, "Nombre inválido (letras, dígitos y _)"
    if n in get_base_tags():
        return False, f"'{n}' es un tag base, no se puede usar"
    for cn in (customs or {}):
        if cn != n and str(cn).lower() == n.lower():
            return False, f"Ya existe el custom '{cn}'"
    cyc = check_cycle(n, body or "", customs or {})
    if cyc:
        return False, "Referencia cíclica: " + " → ".join("{%s}" % c for c in cyc)
    return True, ""
