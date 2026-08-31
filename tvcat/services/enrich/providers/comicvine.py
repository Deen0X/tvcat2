"""Proveedor Comic Vine (cómics). Adaptado de SampleCode a httpx."""
import json
import httpx

BASE_URL = "https://comicvine.gamespot.com/api"
USER_AGENT = "TVCat/2.0"


class ComicVineProvider:
    name = "comicvine"

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
        params = {"api_key": self.api_key, "format": "json", "field_list": "id,issue_number,cover_date,description,image,volume,publisher,character_credits,team_credits,location_credits"}
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{BASE_URL}/issue/4000-{comic_id}/", params=params, headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json().get("results") or {}
            return self._format(data)

    def _format(self, comic):
        if not comic:
            return None
        volume = comic.get("volume", {}) or {}
        volume_name = volume.get("name", "Unknown")
        issue_num = comic.get("issue_number", "?")
        api_data = {
            "api_id": str(comic.get("id")),
            "api_title": f"{volume_name} #{issue_num}",
            "api_description": comic.get("description"),
            "api_release_date": comic.get("cover_date"),
            "api_category": "comic",
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
