"""Cola persistente de sonda media por título (plan MediaProbeQueue).

Productores (baratos, sin descargas): `enqueue_title` (cover/grid) y
`prioritize_title` (hero-open). Consumidor: `services/media_probe_worker`.
Lectores (tags de cover): `get_title_media`.
"""
import os
import sqlite3
import time

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "data", "tvcat.db")

# Versión del sondador: al subir, los aparcados antiguos reintentan.
PROBE_CODE = 3
PARK_TTL_SECS = 7 * 86400

_VIDEO_EXTS = (".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".flv",
              ".webm", ".ts", ".m2ts", ".mpg", ".mpeg")
_AUDIO_EXTS = (".mp3", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".opus",
              ".wav", ".wma")


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return conn


def _ext_of(name: str) -> str:
    try:
        n = str(name or "").lower()
        i = n.rfind(".")
        if 0 < i < len(n) - 1:
            return n[i:]
    except Exception:
        pass
    return ""


def _first_episode(conn, item_id: str):
    """Primer episodio del título (nº episodio, luego id)."""
    try:
        return conn.execute(
            "SELECT episode_key, telegram_link, telegram_msg_id, file_name, title"
            " FROM item_episodes WHERE item_id=? ORDER BY"
            " COALESCE(episode_number, 999999), id LIMIT 1",
            (str(item_id or ""),)).fetchone()
    except Exception:
        return None


def _chat_of(link: str):
    try:
        import re as _re
        m = _re.search(r"/c/(\d+)/", str(link or ""))
        if m:
            return "-100" + m.group(1)
    except Exception:
        pass
    return ""


def _ensure_park_table(conn):
    """Crea probe_parked si falta (auto-reparación si init_db no la creó)."""
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS probe_parked ("
            "episode_key TEXT PRIMARY KEY,"
            " parked_at INTEGER DEFAULT (unixepoch()),"
            " attempts INTEGER DEFAULT 0,"
            " reason TEXT DEFAULT '',"
            " code INTEGER DEFAULT 0)")
        conn.commit()
    except Exception as e:
        print(f" [PROBE] sin tabla probe_parked: {e}", flush=True)
        raise


def is_freshly_parked(episode_key: str) -> bool:
    """¿Aparcado vigente (TTL y código)? Si sí, no re-encolar."""
    try:
        if not episode_key:
            return False
        conn = _conn()
        try:
            _ensure_park_table(conn)
            row = conn.execute(
                "SELECT parked_at, code FROM probe_parked WHERE episode_key=?",
                (str(episode_key),)).fetchone()
            if not row:
                return False
            try:
                age = int(time.time()) - int(row[0] or 0)
            except Exception:
                return False
            if age > PARK_TTL_SECS:
                return False
            try:
                return int(row[1] or 0) >= PROBE_CODE
            except Exception:
                return False
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        print(f" [PROBE] is_freshly_parked: {e}", flush=True)
        return False
    return False


def park_episode(episode_key: str, attempts: int = 0, reason: str = ""):
    """Aparca un episodio (frena el bucle encolar->aparcar)."""
    try:
        if not episode_key:
            return
        conn = _conn()
        try:
            _ensure_park_table(conn)
            conn.execute(
                "INSERT OR REPLACE INTO probe_parked"
                " (episode_key, parked_at, attempts, reason, code)"
                " VALUES (?, ?, ?, ?, ?)",
                (str(episode_key), int(time.time()), int(attempts or 0),
                 str(reason or "")[:200], PROBE_CODE))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        print(f" [PROBE] park_episode: {e}", flush=True)


def enqueue_title(item_id: str) -> bool:
    """Encola la sonda del primer episodio (idempotente, ~1ms, sin red).
    Solo media de vídeo/audio. MKV sale antes por orden de cola."""
    try:
        if not item_id:
            return False
        conn = _conn()
        try:
            ep = _first_episode(conn, item_id)
            if not ep:
                return False
            d = dict(ep)
            key = str(d.get("episode_key") or "")
            if not key:
                return False
            # Ya sondado y vigente → nada que hacer.
            try:
                row = conn.execute(
                    "SELECT 1 FROM episode_media WHERE episode_key=?",
                    (key,)).fetchone()
                if row:
                    return False
            except Exception:
                pass
            ext = _ext_of(d.get("file_name") or d.get("title"))
            if ext not in _VIDEO_EXTS and ext not in _AUDIO_EXTS:
                return False
            chat = _chat_of(d.get("telegram_link"))
            try:
                msg = int(d.get("telegram_msg_id") or 0) or None
            except Exception:
                msg = None
            if not chat or not msg:
                return False
            if is_freshly_parked(key):
                return False
            conn.execute(
                "INSERT OR IGNORE INTO media_probe_queue"
                " (episode_key, item_id, chat_id, msg_id, ext)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, str(item_id), chat, msg, ext))
            conn.commit()
            return True
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return False


def prioritize_title(item_id: str) -> bool:
    """El hero-open pone sus episodios al frente (sin duplicar)."""
    try:
        if not item_id:
            return False
        conn = _conn()
        try:
            cur = conn.execute(
                "UPDATE media_probe_queue SET priority=1 WHERE item_id=?",
                (str(item_id),))
            conn.commit()
            n = (cur.rowcount or 0) > 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if n:
            print(f" [PROBE-BOOST] {item_id} al frente", flush=True)
        return n
    except Exception:
        return False


def get_title_media(item_id: str) -> dict:
    """media_json del primer episodio (para tags de cover). {} si ausente."""
    try:
        if not item_id:
            return {}
        conn = _conn()
        try:
            ep = _first_episode(conn, item_id)
            if not ep:
                return {}
            key = str(dict(ep).get("episode_key") or "")
            if not key:
                return {}
            row = conn.execute(
                "SELECT media_json FROM episode_media WHERE episode_key=?",
                (key,)).fetchone()
            if not row or not row[0]:
                return {}
            import json as _js
            d = _js.loads(row[0])
            return d if isinstance(d, dict) else {}
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return {}


def probe_status(item_id: str) -> str:
    """'ready' = sonda vigente del primer episodio; 'pending' = encolable o
    en cola (el worker la resolverá); 'na' = no es media vídeo/audio o sin
    chat/msg (nada que sondar)."""
    try:
        if not item_id:
            return "na"
        conn = _conn()
        try:
            ep = _first_episode(conn, item_id)
            if not ep:
                return "na"
            d = dict(ep)
            key = str(d.get("episode_key") or "")
            if not key:
                return "na"
            try:
                row = conn.execute(
                    "SELECT 1 FROM episode_media WHERE episode_key=?",
                    (key,)).fetchone()
                if row:
                    return "ready"
            except Exception:
                pass
            ext = _ext_of(d.get("file_name") or d.get("title"))
            if ext not in _VIDEO_EXTS and ext not in _AUDIO_EXTS:
                return "na"
            chat = _chat_of(d.get("telegram_link"))
            try:
                msg = int(d.get("telegram_msg_id") or 0) or None
            except Exception:
                msg = None
            if not chat or not msg:
                return "na"
            if is_freshly_parked(key):
                return "parked"
            try:
                from services.media_probe_worker import is_claimed as _claimed
                if _claimed(key):
                    return "probing"
            except Exception:
                try:
                    from tvcat.services.media_probe_worker import is_claimed as _claimed2
                    if _claimed2(key):
                        return "probing"
                except Exception:
                    pass
            return "pending"
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return "na"


def ensure_probed(item_id: str) -> str:
    """Garantiza sonda con prioridad: encola si falta y pone al frente.
    Devuelve probe_status() resultante ('ready'/'pending'/'na')."""
    try:
        st = probe_status(item_id)
        if st != "pending":
            return st
        try:
            enqueue_title(item_id)
        except Exception:
            pass
        try:
            prioritize_title(item_id)
        except Exception:
            pass
        return "pending"
    except Exception:
        return "na"


def media_flags(media: dict) -> dict:
    """{'multi_audio': bool, 'has_subs': bool} desde un media_json sondado.
    Usa claves normalizadas con fallback al raw `_streams`."""
    out = {"multi_audio": False, "has_subs": False}
    try:
        m = media or {}
        if not isinstance(m, dict):
            return out
        try:
            na = int(str(m.get("audiocount") or 0))
        except Exception:
            na = 0
        try:
            ns = int(str(m.get("subcount") or 0))
        except Exception:
            ns = 0
        if na == 0 or ns == 0:
            # Fallback al raw (sondas antiguas o parciales).
            try:
                streams = m.get("_streams") or []
                if na == 0:
                    na = sum(1 for s in streams
                             if (s or {}).get("codec_type") == "audio")
                if ns == 0:
                    ns = sum(1 for s in streams
                             if (s or {}).get("codec_type") == "subtitle")
            except Exception:
                pass
        if na == 0 and not out["multi_audio"]:
            # Último recurso: fullaudiotracks con coma = varias pistas.
            # Ojo: la coma dentro de paréntesis es del detalle
            # ("spa (aac, 2ch)"), no separador: se quitan los paréntesis.
            try:
                import re as _re
                fa = _re.sub(r"\([^)]*\)", "", str(m.get("fullaudiotracks") or ""))
                if "," in fa:
                    na = 2
            except Exception:
                pass
        if ns == 0:
            try:
                if str(m.get("subtitles") or "").strip():
                    ns = 1
            except Exception:
                pass
        out["multi_audio"] = na >= 2
        out["has_subs"] = ns >= 1
    except Exception:
        pass
    return out


def diagnose(item_id: str) -> dict:
    """Por qué un título no tiene sonda: estado + detalle (ext, chat, msg,
    en cola, sondado). Para el LED de la hero y diagnóstico."""
    d = {"state": "na", "ext": "", "has_chat": False, "has_msg": False,
         "queued": False, "probed": False, "park_reason": ""}
    try:
        if not item_id:
            return d
        d["state"] = probe_status(item_id)
        conn = _conn()
        try:
            ep = _first_episode(conn, item_id)
            if not ep:
                return d
            e = dict(ep)
            key = str(e.get("episode_key") or "")
            ext = _ext_of(e.get("file_name") or e.get("title"))
            d["ext"] = ext
            chat = _chat_of(e.get("telegram_link"))
            try:
                msg = int(e.get("telegram_msg_id") or 0) or None
            except Exception:
                msg = None
            d["has_chat"] = bool(chat)
            d["has_msg"] = bool(msg)
            if key:
                try:
                    r = conn.execute(
                        "SELECT 1 FROM episode_media WHERE episode_key=?",
                        (key,)).fetchone()
                    d["probed"] = bool(r)
                except Exception:
                    pass
                try:
                    r = conn.execute(
                        "SELECT 1 FROM media_probe_queue WHERE episode_key=?",
                        (key,)).fetchone()
                    d["queued"] = bool(r)
                except Exception:
                    pass
                if d["state"] == "parked":
                    try:
                        r = conn.execute(
                            "SELECT reason FROM probe_parked WHERE episode_key=?",
                            (key,)).fetchone()
                        if r and r[0]:
                            d["park_reason"] = str(r[0])[:200]
                    except Exception:
                        pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        pass
    return d
