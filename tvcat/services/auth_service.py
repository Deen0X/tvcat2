"""
TVCat 2 - Auth Service
Manejo de usuarios, sesiones y perfiles.
"""
import os
import sqlite3
import secrets
import json
from typing import Optional

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "data", "tvcat.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def login(username: str, password: str) -> Optional[dict]:
    conn = _get_conn()
    c = conn.cursor()
    user = c.execute(
        "SELECT id, username, role, allowed_categories, profile_id FROM tvcat_users WHERE LOWER(username) = LOWER(?) AND password = ?",
        (username, password)
    ).fetchone()
    if not user:
        conn.close()
        return None

    # Garantizar un perfil (default: admin → 'admin', resto → 'usuario normal')
    profile_id = user["profile_id"] or 0
    if not profile_id:
        row = c.execute("SELECT id FROM tvcat_profiles WHERE name=?",
                        ("admin" if user["role"] == "admin" else "usuario normal",)).fetchone()
        profile_id = row[0] if row else None

    token = secrets.token_hex(32)
    c.execute("INSERT INTO tvcat_sessions (user_id, token, profile_id) VALUES (?, ?, ?)",
              (user["id"], token, profile_id))
    conn.commit()
    conn.close()

    return {
        "token": token,
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "profile_id": profile_id,
        "allowed_categories": json.loads(user["allowed_categories"] or "[]")
    }


def login_with_google(google_email: str) -> Optional[dict]:
    """Login por cuenta Google asociada (google_email). Si no hay usuario asociado, None."""
    conn = _get_conn()
    c = conn.cursor()
    user = c.execute(
        "SELECT id, username, role, allowed_categories, profile_id FROM tvcat_users WHERE LOWER(google_email) = LOWER(?)",
        (google_email,)
    ).fetchone()
    if not user:
        conn.close()
        return None

    profile_id = user["profile_id"] or 0
    if not profile_id:
        row = c.execute("SELECT id FROM tvcat_profiles WHERE name=?",
                        ("admin" if user["role"] == "admin" else "usuario normal",)).fetchone()
        profile_id = row[0] if row else None

    token = secrets.token_hex(32)
    c.execute("INSERT INTO tvcat_sessions (user_id, token, profile_id) VALUES (?, ?, ?)",
              (user["id"], token, profile_id))
    conn.commit()
    conn.close()

    return {
        "token": token,
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "profile_id": profile_id,
        "allowed_categories": json.loads(user["allowed_categories"] or "[]")
    }


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, username, role, google_email FROM tvcat_users WHERE id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_prefs(user_id: int) -> dict:
    """Devuelve las preferencias de perfil de un usuario (nick, avatar, color, etc.)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT display_name, avatar, avatar_url, color, category_preferences, watch_threshold_min, watch_threshold_max, hls_title_prefs FROM tvcat_user_prefs WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {}
    prefs = dict(row)
    try:
        if prefs.get("category_preferences"):
            prefs["category_preferences"] = json.loads(prefs["category_preferences"])
        elif "category_preferences" in prefs:
            prefs["category_preferences"] = {}
    except Exception:
        prefs["category_preferences"] = {}
    try:
        if prefs.get("hls_title_prefs"):
            prefs["hls_title_prefs"] = json.loads(prefs["hls_title_prefs"])
        elif "hls_title_prefs" in prefs:
            prefs["hls_title_prefs"] = {}
    except Exception:
        prefs["hls_title_prefs"] = {}
    return {k: v for k, v in prefs.items() if v is not None}


def save_user_prefs(user_id: int, prefs: dict) -> None:
    """Guarda preferencias de perfil de un usuario (solo las claves presentes)."""
    conn = _get_conn()
    c = conn.cursor()
    # Asegurar la fila
    c.execute("INSERT OR IGNORE INTO tvcat_user_prefs (user_id) VALUES (?)", (user_id,))
    fields = []
    values = []
    for key in ("display_name", "avatar", "avatar_url", "color", "category_preferences", "watch_threshold_min", "watch_threshold_max", "hls_title_prefs"):
        if key in prefs:
            val = prefs[key]
            # Serializar dicts a JSON para columnas TEXT
            if isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)
            fields.append(f"{key}=?")
            values.append(val)
    if fields:
        values.append(user_id)
        c.execute(f"UPDATE tvcat_user_prefs SET {', '.join(fields)} WHERE user_id=?", values)
    conn.commit()
    conn.close()


def link_google_email(user_id: int, google_email: str) -> bool:
    """Asocia (o desasocia) una cuenta Google a un usuario TVCat. Retorna True si se asoció."""
    conn = _get_conn()
    # Comprobar que el email no esté ya asociado a otro usuario
    other = conn.execute(
        "SELECT id FROM tvcat_users WHERE LOWER(google_email)=LOWER(?) AND id<>?",
        (google_email, user_id)
    ).fetchone()
    if other:
        conn.close()
        return False
    if google_email.strip():
        conn.execute("UPDATE tvcat_users SET google_email=? WHERE id=?", (google_email.strip(), user_id))
    else:
        conn.execute("UPDATE tvcat_users SET google_email=NULL WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


def logout(token: str):
    conn = _get_conn()
    conn.execute("DELETE FROM tvcat_sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def get_session(token: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("""
        SELECT u.id, u.username, u.role, u.allowed_categories, u.google_email, s.profile_id
        FROM tvcat_sessions s
        JOIN tvcat_users u ON u.id = s.user_id
        WHERE s.token = ?
    """, (token,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "user_id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "allowed_categories": json.loads(row["allowed_categories"] or "[]"),
        "profile_id": row["profile_id"],
        "google_email": row["google_email"] or ""
    }
