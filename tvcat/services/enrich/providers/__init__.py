"""Registry de proveedores + selección por categoría/subcategoría."""
from .tmdb import TMDBProvider
from .igdb import IGDBProvider
from .books import BooksProvider
from .comicvine import ComicVineProvider


# Subcategorías exactas (legado) + keywords para texto libre (p.ej. tópicos
# "J3m → Audiolibros", "J3m → Comic y manga": contains, no igualdad).
BOOK_SUBCATS = {'audiobook', 'ebook', 'libro', 'book'}
COMIC_SUBCATS = {'comic', 'manga'}

GAME_KEYWORDS = ('videojuego', 'game', 'games', 'juego', 'juegos', 'gaming',
                 'playstation', 'ps3', 'ps4', 'ps5', 'xbox', 'nintendo', 'switch',
                 'pc gaming', 'retro', 'arcade')
BOOK_KEYWORDS = ('audiobook', 'audiobooks', 'audiolibro', 'audiolibros',
                 'ebook', 'ebooks', 'libro', 'libros', 'book', 'books',
                 'novela', 'novelas', 'literatura', 'biblioteca')
COMIC_KEYWORDS = ('comic', 'comics', 'tebeo', 'tebeos', 'teveo', 'manga',
                  'mangas', 'historieta', 'novela grafica')


def _norm(s):
    import re
    import unicodedata
    s = unicodedata.normalize('NFD', str(s or '').lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _has_kw(text, keywords):
    t = f" {_norm(text)} "
    for kw in keywords:
        if f" {kw} " in t:
            return True
    return False


def select_provider_name(category, subcategory):
    """Proveedor según categoría/subcategoría (keywords, no igualdad exacta):
    - game/juego/... (cat o sub) → igdb
    - book/ebook/libro/... (cat, o sub si media) → books
    - comic/tebeo/manga/... (cat, o sub si media) → comicvine
    - media resto → tmdb
    """
    cat = (category or "").strip().lower()
    sub = (subcategory or "").strip().lower()
    if cat == 'game' or _has_kw(category, GAME_KEYWORDS) or _has_kw(subcategory, GAME_KEYWORDS):
        return 'igdb'
    if (cat in ('book', 'libro', 'ebook', 'audiobook')
            or _has_kw(category, BOOK_KEYWORDS)
            or (cat in ('media', 'movie', 'tv', 'anime', 'series', '')
                and _has_kw(subcategory, BOOK_KEYWORDS))):
        return 'books'
    if (cat in ('comic', 'manga')
            or _has_kw(category, COMIC_KEYWORDS)
            or (cat in ('media', 'movie', 'tv', 'anime', 'series', '')
                and _has_kw(subcategory, COMIC_KEYWORDS))):
        return 'comicvine'
    if cat in ('media', 'movie', 'tv', 'anime', 'series'):
        if sub in BOOK_SUBCATS:
            return 'books'
        if sub in COMIC_SUBCATS:
            return 'comicvine'
        return 'tmdb'
    if cat in ('book', 'libro', 'ebook', 'audiobook'):
        return 'books'
    if cat in ('comic', 'manga'):
        return 'comicvine'
    return 'tmdb'


def build_providers(credentials: dict):
    """Construye los proveedores a partir del dict de credenciales.
    credentials: {tmdb:{api_key}, igdb:{client_id,client_secret}, comicvine:{api_key}, google_books:{api_key}}"""
    creds = credentials or {}
    tmdb = creds.get('tmdb', {}) or {}
    igdb = creds.get('igdb', {}) or {}
    comicvine = creds.get('comicvine', {}) or {}
    google_books = creds.get('google_books', {}) or {}
    return {
        'tmdb': TMDBProvider(tmdb.get('api_key', '')),
        'igdb': IGDBProvider(igdb.get('client_id', ''), igdb.get('client_secret', '')),
        'books': BooksProvider(google_books.get('api_key', '')),
        'comicvine': ComicVineProvider(comicvine.get('api_key', '')),
    }


def resolve_media_type(category, subcategory):
    """Resuelve 'movie' o 'tv' para TMDB según subcategoría."""
    sub = (subcategory or "").strip().lower()
    if sub in ('anime', 'series', 'tv'):
        return 'tv'
    return 'movie'
