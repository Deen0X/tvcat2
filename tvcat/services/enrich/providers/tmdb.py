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

    async def search(self, title, media_type="movie"):
        if not self._enabled():
            return []
        url = f"{self.base_url}/search/{media_type}"
        params = {
            "api_key": self.api_key,
            "query": title,
            "language": "es-ES",
            "include_adult": "false",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = data.get("results", []) or []
        candidates = []
        for r in results:
            poster = f"{IMAGE_BASE}{r['poster_path']}" if r.get("poster_path") else None
            year = None
            date_str = r.get("release_date") or r.get("first_air_date") or ""
            if date_str:
                year = int(date_str[:4]) if date_str[:4].isdigit() else None
            candidates.append({
                "id": str(r.get("id")),
                "title": r.get("title") or r.get("name") or "",
                "poster": poster,
                "year": year,
                "provider": self.name,
                "media_type": media_type,
            })
        return candidates

    async def get_details(self, tmdb_id, media_type="movie"):
        if not self._enabled():
            return None
        url = f"{self.base_url}/{media_type}/{tmdb_id}"
        params = {
            "api_key": self.api_key,
            "language": "es-ES",
            "append_to_response": "images,videos,credits",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            return self._format(resp.json(), media_type)

    def _format(self, details, media_type):
        if not details:
            return None
        api_data = {
            "api_id": str(details.get("id")),
            "api_title": details.get("title") or details.get("name"),
            "api_description": details.get("overview"),
            "api_rating": details.get("vote_average"),
            "api_rating_count": details.get("vote_count"),
            "api_release_date": details.get("release_date") or details.get("first_air_date"),
            "api_category": media_type,
            "provider": self.name,
        }
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
        if covers:
            api_data["api_cover"] = json.dumps(covers)
        videos = (details.get("videos", {}) or {}).get("results", []) or []
        yt = [v["key"] for v in videos if v.get("site") == "YouTube"]
        if yt:
            api_data["api_videos"] = json.dumps(yt)
        # Año
        date_str = api_data.get("api_release_date") or ""
        if date_str and date_str[:4].isdigit():
            api_data["api_year"] = int(date_str[:4])
        return api_data
