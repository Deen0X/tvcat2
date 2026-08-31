"""Proveedor IGDB (juegos). Adaptado de SampleCode a httpx (OAuth2 Twitch)."""
import json
import time
import httpx

BASE_URL = "https://api.igdb.com/v4"
AUTH_URL = "https://id.twitch.tv/oauth2/token"


class IGDBProvider:
    name = "igdb"

    def __init__(self, client_id, client_secret):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.access_token = None
        self.token_expiry = 0

    def _enabled(self):
        return bool(self.client_id and self.client_secret)

    async def _ensure_token(self):
        if self.access_token and time.time() < self.token_expiry:
            return True
        if not self._enabled():
            return False
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(AUTH_URL, params=params)
            if resp.status_code != 200:
                return False
            data = resp.json()
            self.access_token = data.get("access_token")
            self.token_expiry = time.time() + int(data.get("expires_in", 3600)) - 60
            return True

    async def search(self, title):
        if not await self._ensure_token():
            return []
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {self.access_token}"}
        query = (
            f'search "{title}"; '
            f'fields name, summary, first_release_date, cover.url; '
            f'limit 10;'
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{BASE_URL}/games", headers=headers, data=query)
            if resp.status_code != 200:
                return []
            results = resp.json() or []
        candidates = []
        for g in results:
            poster = None
            if g.get("cover", {}).get("url"):
                poster = "https:" + g["cover"]["url"].replace("t_thumb", "t_720p")
            year = None
            if g.get("first_release_date"):
                year = time.gmtime(g["first_release_date"]).tm_year
            candidates.append({
                "id": str(g.get("id")),
                "title": g.get("name") or "",
                "poster": poster,
                "year": year,
                "provider": self.name,
            })
        return candidates

    async def get_details(self, game_id):
        if not await self._ensure_token():
            return None
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {self.access_token}"}
        query = (
            f'fields name, summary, storyline, total_rating, total_rating_count, '
            f'first_release_date, cover.url, genres.name, themes.name, '
            f'screenshots.url, videos.video_id; '
            f'where id = {game_id}; limit 1;'
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{BASE_URL}/games", headers=headers, data=query)
            if resp.status_code != 200:
                return None
            results = resp.json() or []
            if not results:
                return None
            return self._format(results[0])

    def _format(self, g):
        api_data = {
            "api_id": str(g.get("id")),
            "api_title": g.get("name"),
            "api_description": g.get("summary"),
            "api_rating": g.get("total_rating"),
            "api_rating_count": g.get("total_rating_count"),
            "api_category": "game",
            "provider": self.name,
        }
        if g.get("first_release_date"):
            api_data["api_release_date"] = time.strftime("%Y-%m-%d", time.gmtime(g["first_release_date"]))
            api_data["api_year"] = time.gmtime(g["first_release_date"]).tm_year
        if g.get("genres"):
            api_data["api_genres"] = json.dumps([x["name"] for x in g["genres"]])
        if g.get("themes"):
            api_data["api_themes"] = json.dumps([x["name"] for x in g["themes"]])
        if g.get("cover", {}).get("url"):
            api_data["api_cover"] = json.dumps(["https:" + g["cover"]["url"].replace("t_thumb", "t_720p")])
        if g.get("screenshots"):
            api_data["api_screenshots"] = json.dumps(
                ["https:" + s["url"].replace("t_thumb", "t_720p") for s in g["screenshots"][:5]]
            )
        if g.get("videos"):
            api_data["api_videos"] = json.dumps([v.get("video_id") for v in g["videos"]])
        return api_data
