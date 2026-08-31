"""Registry de proveedores + selección por categoría/subcategoría."""
from .tmdb import TMDBProvider
from .igdb import IGDBProvider
from .books import BooksProvider
from .comicvine import ComicVineProvider


# Subcategorías de libros
BOOK_SUBCATS = {'audiobook', 'ebook', 'libro', 'book'}
# Subcategorías de cómics
COMIC_SUBCATS = {'comic', 'manga'}


def select_provider_name(category, subcategory):
    """Devuelve el nombre del proveedor según categoría/subcategoría.
    - game → igdb
    - media con sub de libro → books
    - media con sub de cómic → comicvine
    - media resto → tmdb
    """
    cat = (category or "").strip().lower()
    sub = (subcategory or "").strip().lower()
    if cat == 'game':
        return 'igdb'
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
