"""
TVCat 2 - Favorites Service
Gestión de favoritos y progreso de visualización.

El seguimiento de visualización usa la clave natural `episode_key` (channel_msgid)
para identificar episodios de forma estable e independiente del AUTOINCREMENT.
"""
import os
import sqlite3
from typing import Optional

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "data", "tvcat.db")

DEFAULT_THRESHOLD_MIN = 5.0
DEFAULT_THRESHOLD_MAX = 85.0


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get_thresholds(profile_id: int):
    """Devuelve (min, max) como fracciones (0-1) desde las preferencias centrales del usuario.

    El parámetro puede ser un user_id o un profile_id (el gateway pasa 'profile_id or user_id').
    Se resuelve al usuario para leer sus preferencias de umbral.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM tvcat_users WHERE id = ? OR profile_id = ? ORDER BY (id = ?) DESC LIMIT 1",
        (profile_id, profile_id, profile_id)
    ).fetchone()
    if not row:
        conn.close()
        return DEFAULT_THRESHOLD_MIN / 100.0, DEFAULT_THRESHOLD_MAX / 100.0
    uid = row["id"]
    prefs = conn.execute(
        "SELECT watch_threshold_min, watch_threshold_max FROM tvcat_user_prefs WHERE user_id=?",
        (uid,)
    ).fetchone()
    conn.close()
    tmin = DEFAULT_THRESHOLD_MIN
    tmax = DEFAULT_THRESHOLD_MAX
    if prefs:
        tmin = prefs["watch_threshold_min"] if prefs["watch_threshold_min"] is not None else DEFAULT_THRESHOLD_MIN
        tmax = prefs["watch_threshold_max"] if prefs["watch_threshold_max"] is not None else DEFAULT_THRESHOLD_MAX
    return tmin / 100.0, tmax / 100.0


def toggle_favorite(profile_id: int, item_id: str) -> bool:
    conn = _get_conn()
    c = conn.cursor()
    existing = c.execute(
        "SELECT 1 FROM tvcat_favorites WHERE profile_id = ? AND item_id = ?",
        (profile_id, item_id)
    ).fetchone()
    if existing:
        c.execute("DELETE FROM tvcat_favorites WHERE profile_id = ? AND item_id = ?",
                  (profile_id, item_id))
        conn.commit()
        conn.close()
        return False
    else:
        c.execute("INSERT INTO tvcat_favorites (profile_id, item_id) VALUES (?, ?)",
                  (profile_id, item_id))
        conn.commit()
        conn.close()
        return True


def get_favorites(profile_id: int) -> list:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.* FROM unified_catalog c
        JOIN tvcat_favorites f ON f.item_id = c.item_id
        WHERE f.profile_id = ?
    """, (profile_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_progress(profile_id: int, item_id: str, episode_key: str, episode_id: int, progress: float, duration: float, completed: int = 0, watched_state: int = 0):
    """Guarda el progreso de un episodio.

    episode_key: clave natural 'channel_msgid' que identifica el episodio de forma estable.
    watched_state: 0=auto (deducible por porcentaje), 1=sin ver, 2=viendo, 3=visto (forzados).
    El progreso real SIEMPRE se conserva tal cual se recibe (nunca se inventa una posición).
    """
    conn = _get_conn()
    if episode_key:
        conn.execute("""
            INSERT OR REPLACE INTO watch_progress
                (profile_id, item_id, episode_key, episode_id, progress, duration, updated_at, completed, watched_state)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
        """, (profile_id, item_id, episode_key, int(episode_id or 0), progress, duration, int(completed or 0), int(watched_state or 0)))
    else:
        # Fallback legacy (sin episode_key): mantener el registro por episode_id
        conn.execute("""
            INSERT OR REPLACE INTO watch_progress
                (profile_id, item_id, episode_key, episode_id, progress, duration, updated_at, completed, watched_state)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
        """, (profile_id, item_id, "", int(episode_id or 0), progress, duration, int(completed or 0), int(watched_state or 0)))
    conn.commit()
    conn.close()


def get_continue_watching(profile_id: int, limit: int = 200) -> list:
    """Items con al menos 1 episodio en estado 'viendo' (2 forzado, o auto con progreso dentro del rango min..max)."""
    tmin, tmax = _get_thresholds(profile_id)
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.*
        FROM unified_catalog c
        WHERE EXISTS (
            SELECT 1 FROM item_episodes ie
            JOIN watch_progress wp ON wp.item_id = ie.item_id
                                  AND wp.episode_key = ie.episode_key
                                  AND wp.profile_id = ?
            WHERE ie.item_id = c.item_id
              AND (
                  wp.watched_state = 2
                  OR (wp.watched_state = 0 AND ie.duration > 0
                      AND wp.progress / ie.duration >= ? AND wp.progress / ie.duration <= ?)
              )
        )
        ORDER BY (SELECT MAX(updated_at) FROM watch_progress w2
                  WHERE w2.item_id = c.item_id AND w2.profile_id = ?) DESC
        LIMIT ?
    """, (profile_id, tmin, tmax, profile_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_completed(profile_id: int, limit: int = 200) -> list:
    """Items donde TODOS los episodios están en estado 'visto' (3 forzado, o auto con progreso > max)."""
    tmin, tmax = _get_thresholds(profile_id)
    conn = _get_conn()
    # Títulos que tienen ALGÚN episodio no visto (estado efectivo distinto de 3). Una sola pasada.
    # COALESCE: los episodios SIN registro en watch_progress cuentan como 'no vistos' (estado 1).
    rows = conn.execute("""
        SELECT c.*
        FROM unified_catalog c
        WHERE EXISTS (SELECT 1 FROM item_episodes ie WHERE ie.item_id = c.item_id)
          AND c.item_id NOT IN (
              SELECT ie.item_id FROM item_episodes ie
              LEFT JOIN watch_progress wp
                     ON wp.item_id = ie.item_id AND wp.episode_key = ie.episode_key AND wp.profile_id = ?
              WHERE NOT (
                  COALESCE(wp.watched_state, 0) = 3
                  OR (COALESCE(wp.watched_state, 0) = 0 AND ie.duration > 0
                      AND COALESCE(wp.progress, 0) / ie.duration > ?)
              )
              GROUP BY ie.item_id
          )
        ORDER BY (SELECT MAX(updated_at) FROM watch_progress w2
                  WHERE w2.item_id = c.item_id AND w2.profile_id = ?) DESC
        LIMIT ?
    """, (profile_id, tmax, profile_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unwatched_badge(profile_id: int, item_id: str) -> int:
    """Episodios no vistos para un item."""
    tmin, tmax = _get_thresholds(profile_id)
    conn = _get_conn()
    row = conn.execute("""
        SELECT COUNT(*) as total FROM item_episodes WHERE item_id = ?
    """, (item_id,)).fetchone()
    total = row["total"] if row else 0
    if total == 0:
        conn.close()
        return 0

    watched = conn.execute("""
        SELECT COUNT(*) as cnt FROM item_episodes ie
        WHERE ie.item_id = ?
          AND EXISTS (
              SELECT 1 FROM watch_progress wp
              WHERE wp.profile_id = ? AND wp.item_id = ie.item_id AND wp.episode_key = ie.episode_key
                AND (
                    wp.watched_state = 3
                    OR (wp.watched_state = 0 AND ie.duration > 0 AND wp.progress / ie.duration > ?)
                )
          )
    """, (item_id, profile_id, tmax)).fetchone()
    unwatched = total - (watched["cnt"] if watched else 0)
    conn.close()
    return max(0, unwatched)


def get_watch_history(profile_id: int) -> list:
    """Devuelve todo el historial de progreso para un perfil."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT wp.*, ie.title as episode_title, ie.episode_number, ie.duration as ep_duration
        FROM watch_progress wp
        LEFT JOIN item_episodes ie ON ie.item_id = wp.item_id AND ie.episode_key = wp.episode_key
        WHERE wp.profile_id = ?
        ORDER BY wp.updated_at DESC
    """, (profile_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
