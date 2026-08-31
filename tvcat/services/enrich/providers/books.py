"""Proveedores de libros: Google Books (principal) + Open Library (fallback)."""
import json
import httpx


class BooksProvider:
    name = "books"

    def __init__(self, google_api_key=""):
        self.google_api_key = google_api_key or ""
        self.books_url = "https://www.googleapis.com/books/v1/volumes"
        self.openlib_url = "https://openlibrary.org/search.json"
        self.covers_url = "https://covers.openlibrary.org/b/id"

    async def search(self, title, author=None):
        candidates = []
        # 1) Google Books
        if self.google_api_key or True:  # Google Books funciona sin key (limitada)
            q = title
            if author:
                q += f" inauthor:{author}"
            params = {"q": q, "maxResults": 10, "printType": "all"}
            if self.google_api_key:
                params["key"] = self.google_api_key
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(self.books_url, params=params)
                    if resp.status_code == 200:
                        for item in (resp.json().get("items") or [])[:10]:
                            info = item.get("volumeInfo", {})
                            title_found = info.get("title", "")
                            year = None
                            pub = info.get("publishedDate", "")
                            if pub and pub[:4].isdigit():
                                year = int(pub[:4])
                            poster = None
                            links = info.get("imageLinks", {}) or {}
                            for k in ("extraLarge", "large", "medium", "small", "thumbnail"):
                                if links.get(k):
                                    poster = links[k].replace("http://", "https://")
                                    break
                            candidates.append({
                                "id": item.get("id") or "",
                                "title": title_found,
                                "poster": poster,
                                "year": year,
                                "provider": self.name,
                                "sub_provider": "google_books",
                            })
            except Exception:
                pass

        # 2) Open Library (fallback / complemento)
        try:
            q = title if not author else f"{title} {author}"
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(self.openlib_url, params={"q": q, "limit": 10})
                if resp.status_code == 200:
                    for doc in (resp.json().get("docs") or [])[:10]:
                        title_found = doc.get("title", "")
                        year = None
                        if doc.get("first_publish_year"):
                            year = doc["first_publish_year"]
                        poster = None
                        if doc.get("cover_i"):
                            poster = f"{self.covers_url}/{doc['cover_i']}-L.jpg"
                        candidates.append({
                            "id": (doc.get("key") or "").split("/")[-1],
                            "title": title_found,
                            "poster": poster,
                            "year": year,
                            "provider": self.name,
                            "sub_provider": "open_library",
                        })
        except Exception:
            pass
        return candidates

    async def get_details(self, book_id, sub_provider="google_books"):
        if sub_provider == "open_library":
            # Open Library no tiene endpoint de detalle simple; devolvemos mínimo
            return {"api_id": book_id, "api_title": "", "api_category": "book", "provider": self.name}
        if not self.google_api_key:
            # Sin key, intentamos por volumen sin key (limitado)
            pass
        params = {}
        if self.google_api_key:
            params["key"] = self.google_api_key
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{self.books_url}/{book_id}", params=params)
            if resp.status_code != 200:
                return None
            return self._format(resp.json())

    def _format(self, book_data):
        info = book_data.get("volumeInfo", {}) if book_data else {}
        if not info:
            return None
        api_data = {
            "api_id": book_data.get("id"),
            "api_title": info.get("title"),
            "api_description": info.get("description"),
            "api_release_date": info.get("publishedDate"),
            "api_category": "book",
            "provider": self.name,
        }
        authors = info.get("authors", []) or []
        if authors:
            api_data["api_author"] = authors[0]
            api_data["api_genres"] = json.dumps(info.get("categories", []))
        covers = []
        links = info.get("imageLinks", {}) or {}
        for k in ("extraLarge", "large", "medium", "small", "thumbnail"):
            if links.get(k):
                covers.append(links[k].replace("http://", "https://"))
        if covers:
            api_data["api_cover"] = json.dumps(covers)
        api_data["api_rating"] = info.get("averageRating")
        api_data["api_rating_count"] = info.get("ratingsCount")
        pub = info.get("publishedDate", "") or ""
        if pub and pub[:4].isdigit():
            api_data["api_year"] = int(pub[:4])
        return api_data
