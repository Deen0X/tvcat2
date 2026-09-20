"""Proveedor Comic Vine (cómics). Adaptado de SampleCode a httpx."""
import json
import httpx

BASE_URL = "https://comicvine.gamespot.com/api"
USER_AGENT = "TVCat/2.0"


class ComicVineProvider:
    name = "comicvine"

    # Tipos de recurso de la API (el prefijo de la URL lo indica).
    RESOURCE_ENDPOINTS = {
        "4000": "issue",
        "4005": "character",
        "4010": "publisher",
        "4020": "location",
        "4025": "movie",
        "4030": "object",
        "4040": "person",
        "4050": "volume",
        "4060": "team",
    }

    def __init__(self, api_key):
        self.api_key = api_key or ""

    def _enabled(self):
        return bool(self.api_key)

    async def search(self, title, issue_num=None):
        if not self._enabled():
            return []
        q = title
        if issue_num:
            q += f" {issue_num}"
        params = {
            "api_key": self.api_key,
            "format": "json",
            "query": q,
            "resources": "issue",
            "limit": 10,
        }
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{BASE_URL}/search/", params=params, headers=headers)
            if resp.status_code != 200:
                return []
            results = resp.json().get("results", []) or []
        candidates = []
        for r in results:
            vol_name = (r.get("volume") or {}).get("name", "") or ""
            issue = r.get("issue_number", "")
            candidates.append({
                "id": str(r.get("id")),
                "title": f"{vol_name} #{issue}" if vol_name else (r.get("name") or ""),
                "poster": (r.get("image") or {}).get("super_url") or (r.get("image") or {}).get("medium_url"),
                "year": None,
                "provider": self.name,
            })
        return candidates

    async def get_details(self, comic_id):
        if not self._enabled():
            return None
        # Acepta "4005-80689" (de la URL: tipo-id) o id suelto (asume issue).
        cid = str(comic_id or "").strip()
        endpoint = "issue"
        if "-" in cid:
            rtype, _rid = cid.split("-", 1)
            endpoint = self.RESOURCE_ENDPOINTS.get(rtype.strip(), "issue")
            cid = f"{rtype.strip()}-{_rid.strip()}"
        elif cid.isdigit():
            cid = f"4000-{cid}"
        else:
            return None
        if endpoint == "issue":
            fields = "id,issue_number,cover_date,description,image,volume,publisher,character_credits,team_credits,location_credits"
        elif endpoint == "volume":
            fields = "id,name,description,image,publisher,deck,start_year,count_of_issues"
        else:
            fields = "id,name,deck,description,image,publisher"
        params = {"api_key": self.api_key, "format": "json", "field_list": fields}
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{BASE_URL}/{endpoint}/{cid}/", params=params, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json().get("results") or {}
            return self._format(data)

    def _format(self, comic):
        if not comic:
            return None
        # Issues (volume + número) y resto de recursos (nombre directo).
        volume = comic.get("volume", {}) or {}
        if volume.get("name") or comic.get("issue_number") is not None:
            volume_name = volume.get("name", "Unknown")
            issue_num = comic.get("issue_number", "?")
            title = f"{volume_name} #{issue_num}"
            category = "comic"
        else:
            title = comic.get("name") or "Unknown"
            category = "comic"
        api_data = {
            "api_id": str(comic.get("id")),
            "api_title": title,
            "api_description": comic.get("description") or comic.get("deck"),
            "api_release_date": comic.get("cover_date"),
            "api_category": category,
            "provider": self.name,
        }
        publisher = comic.get("publisher", {}).get("name")
        if not publisher and volume:
            publisher = (volume.get("publisher") or {}).get("name")
        if publisher:
            api_data["api_author"] = publisher
        images = comic.get("image", {}) or {}
        covers = []
        for k in ("super_url", "screen_large_url", "medium_url", "small_url", "thumb_url"):
            if images.get(k):
                covers.append(images[k])
        if covers:
            api_data["api_cover"] = json.dumps(covers)
        extra = []
        for k in ("character_credits", "team_credits", "location_credits"):
            for c in comic.get(k, []) or []:
                if c.get("name"):
                    extra.append(c["name"])
        if extra:
            api_data["api_genres"] = json.dumps(list(set(extra)))
        return api_data
