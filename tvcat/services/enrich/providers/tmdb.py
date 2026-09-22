"""Proveedor TMDB (cine/TV/anime). Adaptado de SampleCode a httpx.

Contrato del provider:
- search(title) -> list[dict]  candidatos: {id, title, poster, year, provider}
- get_details(id, media_type) -> dict  campos api_* (api_cover es JSON list de URLs)
"""
import json
import httpx

IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE = "https://image.tmdb.org/t/p/original"


class TMDBProvider:
    name = "tmdb"

    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"

    def _enabled(self):
        return bool(self.api_key)

    # Idiomas de búsqueda en orden de prioridad: España → México/Latam → original (EN).
    # TMDB localiza los títulos según `language`: con solo es-ES, un título latam
    # ("rápido y furioso") no devuelve nada aunque la web sí lo encuentre, porque
    # la web busca en todos los idiomas. Se consultan los 3 y se fusionan por id.
    SEARCH_LANGUAGES = ("es-ES", "es-MX", "en-US")

    async def search(self, title, media_type="movie"):
        if not self._enabled():
            return []
        url = f"{self.base_url}/search/{media_type}"
        seen = {}
        async with httpx.AsyncClient(timeout=20) as client:
            for lang in self.SEARCH_LANGUAGES:
                params = {
                    "api_key": self.api_key,
                    "query": title,
                    "language": lang,
                    "include_adult": "false",
                }
                try:
                    resp = await client.get(url, params=params)
                    print(f"[TMDB] {url} lang={lang} -> status={resp.status_code}", flush=True)
                    if resp.status_code != 200:
                        print(f"[TMDB]   body={resp.text[:300]}", flush=True)
                        continue
                    data = resp.json()
                    results = data.get("results", []) or []
                    print(f"[TMDB]   lang={lang} -> {len(results)} results (total_pages={data.get('total_pages',0)} total_results={data.get('total_results',0)})", flush=True)
                except Exception as ex:
                    print(f"[TMDB] EXCEPTION {url} lang={lang}: {ex}", flush=True)
                    continue
                for r in results:
                    rid = str(r.get("id"))
                    if not rid or rid in seen:
                        continue
                    poster = f"{IMAGE_BASE}{r['poster_path']}" if r.get("poster_path") else None
                    year = None
                    date_str = r.get("release_date") or r.get("first_air_date") or ""
                    if date_str:
                        year = int(date_str[:4]) if date_str[:4].isdigit() else None
                    seen[rid] = {
                        "id": rid,
                        "title": r.get("title") or r.get("name") or "",
                        "original_title": r.get("original_title") or r.get("original_name") or "",
                        "poster": poster,
                        "year": year,
                        "provider": self.name,
                        "media_type": media_type,
                        "lang": lang,
                    }
        return list(seen.values())

    async def get_details(self, tmdb_id, media_type="movie", season=None):
        if not self._enabled():
            return None
        url = f"{self.base_url}/{media_type}/{tmdb_id}"
        params = {
            "api_key": self.api_key,
            "language": "es-ES",
            "append_to_response": "images,videos,credits,alternative_titles,translations",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            api_data = self._format(resp.json(), media_type)
            if api_data and season is not None and (api_data.get("api_category") or media_type) == "tv":
                try:
                    _s = await self._get_season(client, tmdb_id, int(season))
                    if _s:
                        api_data = self._merge_season(api_data, _s, int(season))
                except Exception as e:
                    print(f"[TMDB] season {season} de {tmdb_id}: {e}", flush=True)
            return api_data

    async def _get_season(self, client, tmdb_id, season):
        """Detalle de una temporada: /tv/{id}/season/{n} (cover, episodios, año)."""
        url = f"{self.base_url}/tv/{tmdb_id}/season/{season}"
        resp = await client.get(url, params={"api_key": self.api_key, "language": "es-ES"})
        if resp.status_code != 200:
            return None
        return resp.json()

    @classmethod
    def _merge_season(cls, api_data, s, season):
        """Fusiona el detalle de temporada: año/fecha/descripción pasan a la
        temporada (también mandan en el nombre del topic), el póster de la
        temporada queda primero en la lista de covers."""
        air = (s.get("air_date") or "").strip()
        if air and air[:4].isdigit():
            api_data["api_season_year"] = int(air[:4])
            api_data["api_year"] = int(air[:4])
            api_data["api_release_date"] = air
        api_data["api_season_number"] = int(season)
        try:
            api_data["api_season_episodes"] = len(s.get("episodes") or [])
        except Exception:
            pass
        if (s.get("overview") or "").strip():
            api_data["api_season_overview"] = s["overview"].strip()
            api_data["api_description"] = s["overview"].strip()
        _sp = s.get("poster_path")
        if _sp:
            _url = f"{IMAGE_BASE}{_sp}"
            api_data["api_season_poster"] = _url
            try:
                import json as _js
                # El póster de la temporada queda PRIMERO (preview + Obtenida 1),
                # conservando el idioma de cada carátula para el filtro.
                _merged = [{"url": _url, "lang": ""}]
                for _c in (_js.loads(api_data.get("api_covers_all") or "[]") or []):
                    if isinstance(_c, dict):
                        _u, _l = _c.get("url"), _c.get("lang") or ""
                    else:
                        _u, _l = _c, ""
                    if _u and _u != _url and all(x["url"] != _u for x in _merged):
                        _merged.append({"url": _u, "lang": _l})
                api_data["api_covers_all"] = _js.dumps(_merged[:12])
                _cov = _js.loads(api_data.get("api_cover") or "[]") or []
                api_data["api_cover"] = _js.dumps([_url] + [c for c in _cov if c != _url])
            except Exception:
                pass
        return api_data

    # Países latam hispanohablantes por prioridad (MX primero).
    _LATAM_PRIORITY = ("MX", "AR", "CL", "CO", "PE", "VE", "UY", "EC", "BO",
                       "PY", "CR", "PA", "DO", "GT", "HN", "NI", "SV", "CU", "PR")

    @classmethod
    def _extract_regional_titles(cls, details):
        """Devuelve (title_es, title_latam, alt_titles) desde alternative_titles
        (movie: .titles / tv: .results) + translations en español."""
        by_country = {}
        ordered_alts = []

        def _push(country, title):
            if not title:
                return
            t = str(title).strip()
            if not t:
                return
            if t not in ordered_alts:
                ordered_alts.append(t)
            c = (country or "").upper()
            if c:
                by_country.setdefault(c, [])
                if t not in by_country[c]:
                    by_country[c].append(t)

        alt = details.get("alternative_titles") or {}
        for t in (alt.get("titles") or alt.get("results") or []):
            _push(t.get("iso_3166_1"), t.get("title"))
        trans = details.get("translations") or {}
        title_en = ""
        for tr in (trans.get("translations") or []):
            iso = (tr.get("iso_639_1") or "").lower()
            if iso == "en" and not title_en:
                data = tr.get("data") or {}
                title_en = (data.get("title") or data.get("name") or "").strip()
            if iso != "es":
                continue
            data = tr.get("data") or {}
            _push(tr.get("iso_3166_1"), data.get("title") or data.get("name"))

        title_es = (by_country.get("ES") or [""])[0]
        title_latam = ""
        for cc in cls._LATAM_PRIORITY:
            lst = by_country.get(cc) or []
            if lst:
                title_latam = lst[0]
                break
        # Título inglés (US, si no GB, si no traducción en): para foreignname.
        title_en = ((by_country.get("US") or []) + (by_country.get("GB") or []) + [title_en] + [""])[0]
        return title_es, title_latam, ordered_alts[:20], title_en

    def _format(self, details, media_type):
        if not details:
            return None
        # Detectar tipo REAL de la respuesta: TMDB puede devolver datos de película
        # aunque se consulte como TV (o viceversa) si el ID no existe en ese namespace.
        # first_air_date presente → tv; release_date presente → movie.
        actual_type = media_type
        has_fad = bool(details.get("first_air_date"))
        has_rd = bool(details.get("release_date"))
        if has_fad and not has_rd:
            actual_type = "tv"
        elif has_rd and not has_fad:
            actual_type = "movie"
        api_data = {
            "api_id": str(details.get("id")),
            "api_title": details.get("title") or details.get("name"),
            "api_original_title": details.get("original_title") or details.get("original_name") or "",
            "api_description": details.get("overview"),
            "api_rating": details.get("vote_average"),
            "api_rating_count": details.get("vote_count"),
            "api_release_date": details.get("release_date") or details.get("first_air_date"),
            "api_category": actual_type,
            "provider": self.name,
            # Pasar fechas crudas para que enrich_service pueda detectar inconsistencias.
            "first_air_date": details.get("first_air_date"),
            "release_date": details.get("release_date"),
        }
        # Títulos regionales (España / Latam) + lista de alternativos.
        try:
            title_es, title_latam, alt_titles, title_en = self._extract_regional_titles(details)
            api_data["api_title_es"] = title_es
            api_data["api_title_latam"] = title_latam
            if title_en:
                api_data["api_title_en"] = title_en
            if alt_titles:
                api_data["api_alt_titles"] = json.dumps(alt_titles)
        except Exception:
            pass
        # Reparto + director (credits ya viene en append_to_response).
        try:
            credits = details.get("credits") or {}
            cast = [c.get("name") for c in (credits.get("cast") or []) if c.get("name")][:10]
            if cast:
                api_data["api_cast"] = json.dumps(cast)
            crew = credits.get("crew") or []
            directors = [c.get("name") for c in crew
                         if c.get("job") == "Director" and c.get("name")]
            if not directors and actual_type == "tv":
                directors = [c.get("name") for c in (details.get("created_by") or [])
                             if c.get("name")]
            if directors:
                # dict.fromkeys para deduplicar manteniendo orden
                api_data["api_director"] = ", ".join(list(dict.fromkeys(directors))[:3])
        except Exception:
            pass
        if "genres" in details:
            api_data["api_genres"] = json.dumps([g["name"] for g in details["genres"]])
        covers = []
        if details.get("poster_path"):
            covers.append(f"{IMAGE_BASE}{details['poster_path']}")
        if details.get("backdrop_path"):
            api_data["api_media"] = json.dumps([f"{BACKDROP_BASE}{details['backdrop_path']}"])
        images = details.get("images", {}) or {}
        logos = images.get("logos", []) or []
        if logos:
            api_data["api_logo"] = f"{BACKDROP_BASE}{logos[0]['file_path']}"
        # Carátulas extra de la MISMA respuesta (sin cambiar la llamada):
        # la localizada (poster_path) primero, luego el resto por votos.
        # api_covers_all lleva idioma por carátula para filtrar en el modal.
        _iso_by_path = {}
        try:
            for _ip in ((images.get("posters", []) or [])):
                _ifp = _ip.get("file_path")
                if _ifp and (_ip.get("iso_639_1") or ""):
                    _iso_by_path.setdefault(_ifp, (_ip.get("iso_639_1") or ""))
        except Exception:
            pass
        _all_covers = []
        if covers:
            _all_covers.append({"url": covers[0],
                                "lang": _iso_by_path.get(details.get("poster_path") or "", "")})
        try:
            _psts = sorted((images.get("posters", []) or []),
                           key=lambda p: float(p.get("vote_average") or 0), reverse=True)
            for _p in _psts:
                _fp = _p.get("file_path")
                if not _fp:
                    continue
                _u = f"{IMAGE_BASE}{_fp}"
                _lang = (_p.get("iso_639_1") or "") or ""
                if _u not in [c["url"] for c in _all_covers]:
                    _all_covers.append({"url": _u, "lang": _lang})
                if len(_all_covers) >= 12:
                    break
        except Exception:
            pass
        if covers:
            api_data["api_cover"] = json.dumps(covers)
        if _all_covers:
            api_data["api_covers_all"] = json.dumps(_all_covers)
        videos = (details.get("videos", {}) or {}).get("results", []) or []
        yt = [v["key"] for v in videos if v.get("site") == "YouTube"]
        if yt:
            api_data["api_videos"] = json.dumps(yt)
        # Año
        date_str = api_data.get("api_release_date") or ""
        if date_str and date_str[:4].isdigit():
            api_data["api_year"] = int(date_str[:4])
        # Temporadas (solo TV; en películas no existe → el tag se omite).
        try:
            _ns = details.get("number_of_seasons")
            if _ns is not None and str(_ns).strip() != "":
                api_data["api_seasons"] = int(_ns)
        except Exception:
            pass
        return api_data
