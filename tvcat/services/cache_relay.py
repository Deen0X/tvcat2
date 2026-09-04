"""CacheRelay — Orquestador de export/import de caché de mensajes Telegram.

Exporta el caché raw (`telegram_message_cache`) + imágenes (`catalog_assets`) a un
`.db.gz`, lo publica como fichero fijado en Telegram, y permite descubrirlo e importarlo
en otra instancia. Dos destinos:

- Canal destino (escaneado): caché filtrado de ESE canal (solo si `can_post`).
- Canal auxiliar (configurado): DB completa sin filtrar (`full=1`).

Punto de acceso a Telegram: `TelegramService` (único punto de acceso, §17 arquitectura).
"""
import os
import re
import io
import gzip
import json
import time
import uuid
import base64
import sqlite3
import hashlib
import asyncio
from typing import Optional

_TVCAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _central_conn():
    from services.catalog_service import get_conn
    return get_conn()


def _plugin_conn():
    from plugins.tvcat_tgindex.scanner import get_plugin_db_path
    conn = sqlite3.connect(get_plugin_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _channel_variants(channel_id: str):
    bare = str(channel_id).replace("-100", "").lstrip("-")
    return {str(channel_id), bare, f"-100{bare}"}


def _ensure_tables():
    conn = _plugin_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache_relay_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            chat_origen TEXT NOT NULL,
            msg_id_backup INTEGER,
            bk TEXT,
            max_msg_id INTEGER,
            count INTEGER,
            ts INTEGER,
            parts INTEGER DEFAULT 1,
            size_bytes INTEGER,
            hash TEXT,
            status TEXT DEFAULT 'local',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


# ─── Resolución de credenciales ────────────────────────────────────

def _resolve_creds():
    """(api_id, api_hash, session_string) de la cuenta Principal (patrón scanner)."""
    try:
        from plugins.tvcat_tgindex.scanner import _resolve_api_creds
        return _resolve_api_creds()
    except Exception:
        return None, None, None


async def _service():
    from services.telegram_service import get_telegram_service
    return get_telegram_service()


def _cred_kwargs():
    api_id, api_hash, session_string = _resolve_creds()
    if not session_string or not api_id or not api_hash:
        return {}
    return {"session_string": session_string, "api_id": int(api_id), "api_hash": api_hash}


# ─── Helpers de config ─────────────────────────────────────────────

def _get_config():
    from services.catalog_service import get_conn
    conn = get_conn()
    aux = conn.execute("SELECT value FROM tvcat_settings WHERE key='cache_relay_chat_aux'").fetchone()
    ow = conn.execute("SELECT value FROM tvcat_settings WHERE key='cache_relay_overwrite'").fetchone()
    conn.close()
    return {
        "chat_aux": (aux[0] if aux else "") or "",
        "overwrite": (ow[0] if ow else "0") == "1",
    }


def _save_config(chat_aux, overwrite):
    from services.catalog_service import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("cache_relay_chat_aux", (chat_aux or "").strip()))
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                 ("cache_relay_overwrite", "1" if overwrite else "0"))
    conn.commit()
    conn.close()


# ─── Export ────────────────────────────────────────────────────────

def _build_db(channel_id: Optional[str] = None) -> bytes:
    """Crea un .db temporal con telegram_message_cache + catalog_assets.
    Si channel_id es None → DB completa (full). Devuelve los bytes del .db (sin gzip)."""
    src = _central_conn()
    tmp = io.BytesIO()
    dst = sqlite3.connect(':memory:') if False else sqlite3.connect(os.path.join(_TVCAT_DIR, "data", "_cache_relay_tmp.db"))
    try:
        # esquema (canónico: channel_id sin -100 en ambas tablas)
        dst.execute("CREATE TABLE telegram_message_cache (channel_id TEXT NOT NULL, topic_id INTEGER, msg_id INTEGER NOT NULL, message TEXT NOT NULL, fetched_at INTEGER)")
        dst.execute("CREATE TABLE catalog_assets (channel_id TEXT NOT NULL DEFAULT '', telegram_msg_id INTEGER, asset_type TEXT, asset_index INTEGER DEFAULT 0, image_blob BLOB, mime_type TEXT, file_size INTEGER, width INTEGER, height INTEGER, source TEXT)")

        if channel_id is not None:
            variants = _channel_variants(channel_id)
            placeholders = ",".join("?" for _ in variants)
            rows = src.execute(
                f"SELECT channel_id, topic_id, msg_id, message, fetched_at FROM telegram_message_cache WHERE channel_id IN ({placeholders})",
                list(variants)).fetchall()
        else:
            rows = src.execute("SELECT channel_id, topic_id, msg_id, message, fetched_at FROM telegram_message_cache").fetchall()

        try:
            from services.cache_keys import canon_channel
        except Exception:
            def canon_channel(x):
                return str(x or "").replace("-100", "").lstrip("-")
        msg_ids = set()
        for r in rows:
            dst.execute("INSERT INTO telegram_message_cache VALUES (?,?,?,?,?)",
                        (canon_channel(r["channel_id"]), r["topic_id"], r["msg_id"], r["message"], r["fetched_at"]))
            msg_ids.add(r["msg_id"])

        if msg_ids:
            ph = ",".join("?" for _ in msg_ids)
            # Filtrar assets también por canal (evita arrastrar el asset de otro canal con mismo msg_id)
            exp_chan = canon_channel(channel_id) if channel_id is not None else None
            try:
                _acols = [rr[1] for rr in src.execute("PRAGMA table_info(catalog_assets)").fetchall()]
            except Exception:
                _acols = []
            if exp_chan is not None and "channel_id" in _acols:
                assets = src.execute(
                    f"SELECT channel_id, telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height, source FROM catalog_assets WHERE telegram_msg_id IN ({ph}) AND channel_id=?",
                    list(msg_ids) + [exp_chan]).fetchall()
            else:
                assets = src.execute(
                    f"SELECT telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height, source FROM catalog_assets WHERE telegram_msg_id IN ({ph})",
                    list(msg_ids)).fetchall()
            for a in assets:
                ad = dict(a)
                dst.execute("INSERT INTO catalog_assets VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (canon_channel(ad.get("channel_id", exp_chan or "")),
                             ad["telegram_msg_id"], ad["asset_type"], ad["asset_index"], ad["image_blob"],
                             ad["mime_type"], ad["file_size"], ad["width"], ad["height"], ad["source"]))
        dst.commit()
        with open(os.path.join(_TVCAT_DIR, "data", "_cache_relay_tmp.db"), "rb") as f:
            raw_db = f.read()
    finally:
        dst.close()
        src.close()
        try:
            os.remove(os.path.join(_TVCAT_DIR, "data", "_cache_relay_tmp.db"))
        except Exception:
            pass
    return raw_db


def _gzip_bytes(data: bytes) -> bytes:
    return gzip.compress(data, 9)


def _build_and_gzip(channel_id):
    """Combina _build_db + _gzip_bytes (síncrono, para ejecutar en hilo)."""
    raw_db = _build_db(channel_id)
    return raw_db, _gzip_bytes(raw_db)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Constantes para encriptación simple
_CACHE_RELAY_KEY = b"TVCatCacheRelayV1"


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _encrypt_payload(payload: str) -> str:
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    combined = (payload + "|" + digest).encode()
    enc = _xor_bytes(combined, _CACHE_RELAY_KEY)
    return base64.urlsafe_b64encode(enc).decode().rstrip("=")


def _decrypt_payload(token: str) -> Optional[str]:
    try:
        enc = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        combined = _xor_bytes(enc, _CACHE_RELAY_KEY).decode()
        payload, digest = combined.rsplit("|", 1)
        if hashlib.sha256(payload.encode()).hexdigest()[:16] != digest:
            return None
        return payload
    except Exception:
        return None


def _manifest(bk, channel_id, full, max_msg_id, count, parts, size, hash_val):
    if full:
        payload = f"bk={bk} full=1 max={max_msg_id} n={count} ts={int(time.time())} parts={parts} size={size} hash={hash_val}"
    else:
        payload = f"bk={bk} ch={channel_id} max={max_msg_id} n={count} ts={int(time.time())} parts={parts} size={size} hash={hash_val}"
    token = _encrypt_payload(payload)
    return (
        "#cacheRelay\n\n"
        "Cache Relay de sistema TVCat\n\n"
        "Este mensaje es un respaldo de caché del sistema TVCat. "
        "Se utiliza para sincronizar el historial de mensajes entre instancias. "
        "No lo borres ni lo modifiques.\n\n"
        "NO MODIFIQUES LA SIGUIENTE LINEA:\n"
        f"enc={token}"
    )


def _parse_manifest(caption: str) -> Optional[dict]:
    if not caption or "#cacheRelay" not in caption:
        return None
    m = re.search(r'#cacheRelay\s+(.*)', caption)
    if not m:
        return None
    d = {}
    for part in m.group(1).split():
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = v
    if "bk" not in d:
        return None
    d["parts"] = int(d.get("parts", 1))
    d["size"] = int(d.get("size", 0))
    d["max"] = int(d.get("max", 0))
    d["n"] = int(d.get("n", 0))
    d["ts"] = int(d.get("ts", 0))
    return d


async def export_channel_cache(channel_id: str) -> dict:
    """Exporta el caché de ESE canal y publica en el canal destino (solo si can_post)."""
    global _progress_state
    _progress_state.update({"running": True, "operation": "upload", "step": "Preparando", "current": 0, "total": 0, "channel_id": str(channel_id)})
    try:
        _ensure_tables()
        svc = await _service()
        creds = _cred_kwargs()
        if not creds:
            return {"ok": False, "error": "No hay credenciales de sesión configuradas"}

        entity = await svc.get_entity(channel_id, **creds)
        if not entity.get("can_post"):
            return {"ok": False, "error": f"No se puede publicar en el canal (can_post=false). No se sube al auxiliar."}

        # Recuento y max local
        variants = _channel_variants(channel_id)
        conn = _central_conn()
        ph = ",".join("?" for _ in variants)
        row = conn.execute(
            f"SELECT COUNT(*) c, MAX(msg_id) m FROM telegram_message_cache WHERE channel_id IN ({ph})",
            list(variants)).fetchone()
        conn.close()
        count = row["c"] or 0
        max_msg_id = row["m"] or 0
        if count == 0:
            return {"ok": False, "error": "No hay caché para este canal"}

        # Fase pesada (build_db + gzip) en hilo para no bloquear el event loop
        _progress_state["step"] = "Generando backup"
        raw_db, gz = await asyncio.to_thread(_build_and_gzip, channel_id)
        h = _sha256(gz)
        bk = uuid.uuid4().hex[:12]

        _progress_state["step"] = "Subiendo"

        def _p(job):
            _progress_state["current"] = job.get("current", 0)
            _progress_state["total"] = job.get("total", 0)

        result = await _upload_and_pin(svc, creds, channel_id, bk, channel_id, full=False,
                                       max_msg_id=max_msg_id, count=count, gz=gz, hash_val=h,
                                       progress_callback=_p)
        if not result.get("ok"):
            return result

        conn = _plugin_conn()
        conn.execute("INSERT INTO cache_relay_backups (channel_id, chat_origen, msg_id_backup, bk, max_msg_id, count, ts, parts, size_bytes, hash, status) VALUES (?,?,?,?,?,?,?,?,?,?,'local')",
                     (str(channel_id), str(channel_id), result.get("msg_id"), bk, max_msg_id, count, int(time.time()), result.get("parts", 1), len(gz), h))
        conn.commit()
        conn.close()
        return {"ok": True, "msg_id": result.get("msg_id"), "bk": bk, "count": count, "size": len(gz)}
    finally:
        _reset_progress()


async def export_full_backup(aux_chat: str) -> dict:
    """Exporta la DB completa y publica en el canal auxiliar."""
    global _progress_state
    _progress_state.update({"running": True, "operation": "upload", "step": "Preparando", "current": 0, "total": 0, "channel_id": "*"})
    try:
        _ensure_tables()
        svc = await _service()
        creds = _cred_kwargs()
        if not creds:
            return {"ok": False, "error": "No hay credenciales de sesión configuradas"}
        if not aux_chat:
            return {"ok": False, "error": "Canal auxiliar no configurado"}

        entity = await svc.get_entity(aux_chat, **creds)
        if not entity.get("can_post"):
            return {"ok": False, "error": "No se puede publicar en el canal auxiliar (can_post=false)"}

        conn = _central_conn()
        row = conn.execute("SELECT COUNT(*) c, MAX(msg_id) m FROM telegram_message_cache").fetchone()
        conn.close()
        count = row["c"] or 0
        max_msg_id = row["m"] or 0
        if count == 0:
            return {"ok": False, "error": "No hay caché para exportar"}

        _progress_state["step"] = "Generando backup"
        raw_db, gz = await asyncio.to_thread(_build_and_gzip, None)
        h = _sha256(gz)
        bk = uuid.uuid4().hex[:12]

        _progress_state["step"] = "Subiendo"

        def _p(job):
            _progress_state["current"] = job.get("current", 0)
            _progress_state["total"] = job.get("total", 0)

        result = await _upload_and_pin(svc, creds, aux_chat, bk, "*", full=True,
                                       max_msg_id=max_msg_id, count=count, gz=gz, hash_val=h,
                                       progress_callback=_p)
        if not result.get("ok"):
            return result

        conn = _plugin_conn()
        conn.execute("INSERT INTO cache_relay_backups (channel_id, chat_origen, msg_id_backup, bk, max_msg_id, count, ts, parts, size_bytes, hash, status) VALUES (?,?,?,?,?,?,?,?,?,?,'local')",
                     ("*", str(aux_chat), result.get("msg_id"), bk, max_msg_id, count, int(time.time()), result.get("parts", 1), len(gz), h))
        conn.commit()
        conn.close()
        return {"ok": True, "msg_id": result.get("msg_id"), "bk": bk, "count": count, "size": len(gz)}
    finally:
        _reset_progress()


async def _upload_and_pin(svc, creds, chat, bk, channel_id, full, max_msg_id, count, gz, hash_val,
                          progress_callback=None):
    """Sube el .db.gz (fragmentado si >2GB) y fija la cabecera, usando TransferService."""
    from services import transfer_service
    LIMIT = 2 * 1024 * 1024 * 1024  # 2GB
    parts = []
    if len(gz) <= LIMIT:
        parts = [gz]
    else:
        for i in range(0, len(gz), LIMIT):
            parts.append(gz[i:i+LIMIT])

    N = len(parts)
    total_bytes = len(gz)
    sent_bytes = 0
    last_msg_id = None
    for i, part in enumerate(parts, 1):
        if N == 1:
            caption = _manifest(bk, channel_id, full, max_msg_id, count, 1, len(gz), hash_val)
            fname = "TVCacheRelay.db.gz"
        else:
            caption = f"#cacheRelay bk={bk} part={i}/{N}" if i < N else _manifest(bk, channel_id, full, max_msg_id, count, N, len(gz), hash_val)
            fname = f"TVCacheRelay_Part{i}.db.gz"

        part_len = len(part)

        def _p(job):
            if progress_callback:
                progress_callback({"current": sent_bytes + job.get("current", 0),
                                   "total": total_bytes})

        job = await transfer_service.enqueue_upload(
            chat, part, file_name=fname, caption=caption,
            creds=_transfer_creds(creds), on_progress=_p, persist=False, _kind="cache_relay")
        done = await transfer_service.wait_job(job["id"])
        if done.get("state") != "done" or not done.get("result"):
            raise RuntimeError(f"Fallo subiendo {fname}: {done.get('error')}")
        last_msg_id = done["result"].get("msg_id")
        sent_bytes += part_len
        if i == N:
            try:
                await svc.pin_message(chat, last_msg_id, **creds)
            except Exception as e:
                print(f"[CacheRelay] Error fijando mensaje: {e}", flush=True)

    return {"ok": True, "msg_id": last_msg_id if N == 1 else None, "parts": N}


def _transfer_creds(creds: dict) -> dict:
    """Adapta las credenciales (session_string, api_id, api_hash) al formato del TransferService."""
    out = {}
    for k in ("session_string", "api_id", "api_hash"):
        if k in creds:
            out[k] = creds[k]
    return out


# ─── Discover / Download / Import ──────────────────────────────────

async def discover_backups(chat: str, channel_id: str = None) -> Optional[dict]:
    """Busca el manifest del backup más reciente en el chat (opcionalmente filtrado por canal).
    Primero en pinned; si no hay, por búsqueda de texto '#cacheRelay' (no depende del pin).
    Devuelve el manifest enriquecido con 'msg_id' (mensaje cabecera) o None."""
    svc = await _service()
    creds = _cred_kwargs()
    if not creds:
        return None

    def _matches(d):
        if not d:
            return False
        if channel_id is not None:
            if d.get("full") == "1":
                return False
            if d.get("ch") != str(channel_id):
                return False
        return True

    candidates = {}  # bk -> {"manifest": d, "msg_id": mid}

    # 1) Pinned
    try:
        pinned = await svc.get_pinned_messages(chat, **creds)
        for p in pinned:
            d = _parse_manifest(p.get("caption", ""))
            if _matches(d):
                candidates[d["bk"]] = {"manifest": d, "msg_id": p.get("msg_id")}
    except Exception as e:
        print(f"[CacheRelay] Error en pinned: {e}", flush=True)

    # 2) Fallback: búsqueda por texto (cubre el caso de no poder fijar el mensaje)
    if not candidates:
        try:
            found = await svc.search_messages_by_text(chat, "#cacheRelay", **creds)
            for m in found:
                d = _parse_manifest(m.get("caption", ""))
                if _matches(d):
                    candidates[d["bk"]] = {"manifest": d, "msg_id": m.get("msg_id")}
        except Exception as e:
            print(f"[CacheRelay] Error en búsqueda: {e}", flush=True)

    if not candidates:
        return None

    best = max(candidates.values(), key=lambda x: x["manifest"].get("ts", 0))
    result = dict(best["manifest"])
    result["msg_id"] = best["msg_id"]
    return result


async def download_backup(manifest: dict, chat: str, progress_callback=None) -> Optional[bytes]:
    """Descarga y ensambla el .db.gz desde el chat, verifica sha256, usando TransferService."""
    from services import transfer_service
    svc = await _service()
    creds = _cred_kwargs()
    if not creds:
        return None
    bk = manifest.get("bk")
    parts = manifest.get("parts", 1)

    async def _one(msg_id_target):
        def _p(job):
            if progress_callback:
                progress_callback(job.get("current", 0), job.get("total", 0))
        job = await transfer_service.enqueue_download(
            chat, int(msg_id_target), dest_path=None,
            creds=_transfer_creds(creds), on_progress=_p, persist=False, _kind="cache_relay")
        done = await transfer_service.wait_job(job["id"])
        if done.get("state") != "done":
            return None
        return done.get("_downloaded")

    # Helper para buscar por #cacheRelay y filtrar por bk (funciona con ambos formatos)
    async def _find_by_bk():
        found = await svc.search_messages_by_text(chat, "#cacheRelay", **creds)
        result = []
        for m in found:
            d = _parse_manifest(m.get("caption", ""))
            if d and d.get("bk") == bk:
                result.append(m)
        return result

    if parts <= 1:
        target = manifest.get("msg_id")
        if not target:
            found = await _find_by_bk()
            if not found:
                return None
            target = found[0].get("msg_id")
        return await _one(target)

    # Multipartes: buscar por #cacheRelay, filtrar por bk, y detectar partes
    found = await _find_by_bk()
    parts_map = {}
    for m in found:
        cap = m.get("caption", "")
        d = _parse_manifest(cap)
        if not d or d.get("bk") != bk:
            continue
        mm = re.search(r'part=(\d+)/(\d+)', cap)
        if mm:
            parts_map[int(mm.group(1))] = m.get("msg_id")
        else:
            # cabecera = última parte (usa parts del manifest descifrado)
            parts_map[d.get("parts", parts)] = m.get("msg_id")

    if len(parts_map) < parts:
        return None
    chunks = []
    for i in range(1, parts + 1):
        if i not in parts_map:
            return None
        data = await _one(parts_map[i])
        if data is None:
            return None
        chunks.append(data)
    return b"".join(chunks)


def import_channel_cache(gz_bytes: bytes, channel_id: str, overwrite: bool, manifest: Optional[dict], chat_origen: str,
                         on_progress=None) -> dict:
    """Descomprime e importa el .db.gz con INSERT OR IGNORE/REPLACE por lotes (executemany).
    Añade solo los mensajes que no existen localmente (no reemplaza salvo overwrite).
    on_progress(step, current, total) opcional para barra de progreso."""
    def _progress(step, current, total):
        if on_progress:
            try:
                on_progress(step, current, total)
            except Exception:
                pass

    try:
        raw_db = gzip.decompress(gz_bytes)
    except Exception:
        return {"ok": False, "error": "Fichero .db.gz inválido"}

    h = hashlib.sha256(gz_bytes).hexdigest()
    if manifest and manifest.get("hash") and h != manifest.get("hash"):
        return {"ok": False, "error": "Hash SHA-256 no coincide"}

    # Escribir el .db temporal y validar integridad
    tmp_db = os.path.join(_TVCAT_DIR, "data", "_cache_relay_import.db")
    with open(tmp_db, "wb") as f:
        f.write(raw_db)

    src = None
    try:
        src = sqlite3.connect(tmp_db)
        src.row_factory = sqlite3.Row
        ok = src.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            return {"ok": False, "error": f"integrity_check: {ok}"}

        variants = _channel_variants(channel_id) if channel_id and channel_id != "*" else None

        # Leer filas del backup
        if variants:
            ph = ",".join("?" for _ in variants)
            rows = [dict(r) for r in src.execute(
                f"SELECT * FROM telegram_message_cache WHERE channel_id IN ({ph})", list(variants)).fetchall()]
        else:
            rows = [dict(r) for r in src.execute("SELECT * FROM telegram_message_cache").fetchall()]

        total_rows = len(rows)
        _progress("import", 0, total_rows)

        conn = _central_conn()
        try:
            local_max = 0
            if variants:
                ph = ",".join("?" for _ in variants)
                row = conn.execute(f"SELECT MAX(msg_id) m FROM telegram_message_cache WHERE channel_id IN ({ph})", list(variants)).fetchone()
                local_max = row["m"] or 0

            manifest_max = (manifest.get("max") or 0) if manifest else 0
            if local_max >= manifest_max and manifest_max > 0 and not overwrite:
                total = (manifest.get("n") or 0) if manifest else 0
                return {"ok": True, "skipped": True, "imported": 0, "new_max": local_max, "total": total, "reason": "ya actualizado"}

            # Conjunto de msg_id ya existentes localmente (para contar solo los nuevos)
            existing_ids = set()
            if variants:
                ph = ",".join("?" for _ in variants)
                for r in conn.execute(f"SELECT msg_id FROM telegram_message_cache WHERE channel_id IN ({ph})", list(variants)).fetchall():
                    existing_ids.add(r[0])
            else:
                for r in conn.execute("SELECT msg_id FROM telegram_message_cache").fetchall():
                    existing_ids.add(r[0])

            # Filtrar: si no overwrite, solo los que no existen localmente
            if overwrite:
                to_insert = rows
            else:
                to_insert = [r for r in rows if r["msg_id"] not in existing_ids]

            mode = "OR REPLACE" if overwrite else "OR IGNORE"
            try:
                from services.cache_keys import canon_channel as _cc
            except Exception:
                def _cc(x):
                    return str(x or "").replace("-100", "").lstrip("-")
            data = [(_cc(r["channel_id"]), r["topic_id"], r["msg_id"], r["message"], r["fetched_at"]) for r in to_insert]
            BATCH = 500
            for i in range(0, len(data), BATCH):
                conn.executemany(
                    f"INSERT {mode} INTO telegram_message_cache (channel_id, topic_id, msg_id, message, fetched_at) VALUES (?,?,?,?,?)",
                    data[i:i+BATCH])
                _progress("import", min(i + BATCH, len(data)), total_rows)

            imported = len(to_insert)

            # catalog_assets: solo los de los mensajes importados (con canal canónico;
            # backups viejos sin channel_id heredan el canal importado)
            if to_insert:
                try:
                    _bcols = [rr[1] for rr in src.execute("PRAGMA table_info(catalog_assets)").fetchall()]
                except Exception:
                    _bcols = []
                _bhas_chan = "channel_id" in _bcols
                try:
                    _imp_chan = _cc(channel_id) if channel_id and channel_id != "*" else ""
                except Exception:
                    _imp_chan = ""
                msg_ids = [r["msg_id"] for r in to_insert]
                # ejecutar por lotes de msg_ids para no exceder límite de parámetros SQL
                assets = []
                for j in range(0, len(msg_ids), 500):
                    sub = msg_ids[j:j+500]
                    ph2 = ",".join("?" for _ in sub)
                    for a in src.execute(f"SELECT * FROM catalog_assets WHERE telegram_msg_id IN ({ph2})", sub).fetchall():
                        assets.append(dict(a))
                if assets:
                    adata = [((_cc(a.get("channel_id")) if (_bhas_chan and a.get("channel_id")) else _imp_chan),
                              a["telegram_msg_id"], a["asset_type"], a["asset_index"], a["image_blob"],
                              a["mime_type"], a["file_size"], a["width"], a["height"], a["source"]) for a in assets]
                    for j in range(0, len(adata), BATCH):
                        conn.executemany(
                            f"INSERT {mode} INTO catalog_assets (channel_id, telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            adata[j:j+BATCH])

            conn.commit()
        finally:
            conn.close()
    finally:
        if src:
            src.close()
        try:
            os.remove(tmp_db)
        except Exception:
            pass

    _progress("import", total_rows, total_rows)
    new_max = max(local_max, manifest_max)
    total = (manifest.get("n") or 0) if manifest else 0
    if not total:
        total = total_rows
    return {"ok": True, "skipped": False, "imported": imported, "new_max": new_max, "total": total}


# ─── Listado de canales ────────────────────────────────────────────

def get_channels_for_relay() -> list:
    _ensure_tables()
    conn = _central_conn()
    channels = []
    try:
        rows = conn.execute("SELECT DISTINCT channel_id, display_name FROM tvcat_scanned_channels").fetchall()
        for r in rows:
            cid = r["channel_id"]
            variants = _channel_variants(cid)
            ph = ",".join("?" for _ in variants)
            stat = conn.execute(
                f"SELECT COUNT(*) c, MAX(msg_id) m FROM telegram_message_cache WHERE channel_id IN ({ph})",
                list(variants)).fetchone()
            channels.append({
                "channel_id": str(cid),
                "name": r["display_name"] or cid,
                "count": stat["c"] or 0,
                "max_msg_id": stat["m"] or 0,
            })
    except Exception:
        pass
    finally:
        conn.close()
    return channels


# ─── can_post por canal (con caché en memoria) ─────────────────────

_can_post_cache = {}


def _ensure_permission_columns():
    """Añade cache_owner / cache_can_post a tvcat_scanned_channels (idempotente)."""
    conn = _central_conn()
    for col in ["cache_owner INTEGER", "cache_can_post INTEGER"]:
        try:
            conn.execute(f"ALTER TABLE tvcat_scanned_channels ADD COLUMN {col}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def _get_cached_permission(channel_id: str):
    """Devuelve (owner, can_post) guardados en DB, o (None, None) si no hay."""
    conn = _central_conn()
    try:
        row = conn.execute(
            "SELECT cache_owner, cache_can_post FROM tvcat_scanned_channels WHERE channel_id=? LIMIT 1",
            (str(channel_id),)).fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if not row or row["cache_owner"] is None:
        return None, None
    return int(row["cache_owner"]), (int(row["cache_can_post"]) if row["cache_can_post"] is not None else None)


def _save_permission(channel_id: str, owner: bool, can_post: bool):
    """Guarda owner/can_post en tvcat_scanned_channels (todas las filas de ese channel)."""
    conn = _central_conn()
    conn.execute("UPDATE tvcat_scanned_channels SET cache_owner=?, cache_can_post=? WHERE channel_id=?",
                 (1 if owner else 0, 1 if can_post else 0, str(channel_id)))
    conn.commit()
    conn.close()


async def get_channel_can_post(channel_id: str) -> bool:
    """Determina si la cuenta puede escribir en el canal.
    Usa DB primero: si ya sabemos que es dueño → True sin consultar Telegram.
    Solo consulta Telegram en canales sin info guardada."""
    cid = str(channel_id)
    _ensure_permission_columns()

    # 1) DB guardada (persistente entre reinicios)
    owner, can_post = _get_cached_permission(cid)
    if owner is not None:
        return bool(owner or can_post)

    # 2) Caché en memoria (fallback rápido intra-sesión)
    now = time.time()
    cached = _can_post_cache.get(cid)
    if cached and (now - cached[0]) < 600:
        return cached[1]

    # 3) Consultar Telegram y guardar en DB
    try:
        svc = await _service()
        creds = _cred_kwargs()
        if not creds:
            return False
        entity = await svc.get_entity(cid, **creds)
        is_owner = bool(entity.get("creator", False))
        val = bool(entity.get("can_post", False))
    except Exception as e:
        print(f"[CacheRelay] Error resolviendo can_post para {cid}: {e}", flush=True)
        is_owner = False
        val = False
    _can_post_cache[cid] = (now, val)
    _save_permission(cid, is_owner, val)
    return val


async def get_channels_with_can_post() -> list:
    """Lista de canales (tvcat_scanned_channels) con su can_post resuelto."""
    conn = _central_conn()
    rows = conn.execute("SELECT DISTINCT channel_id, display_name FROM tvcat_scanned_channels").fetchall()
    conn.close()
    result = []
    for r in rows:
        cid = r["channel_id"]
        can_post = await get_channel_can_post(cid)
        result.append({"channel_id": str(cid), "name": r["display_name"] or cid, "can_post": can_post})
    return result


# ─── Estado de progreso (para barra de progreso en la UI) ─────────

_progress_state = {
    "running": False,
    "operation": "",       # "download" | "upload" | "import"
    "step": "",            # descripción legible
    "current": 0,
    "total": 0,
    "channel_id": "",
}


def get_progress_state() -> dict:
    return dict(_progress_state)


def _reset_progress():
    _progress_state.update({"running": False, "operation": "", "step": "", "current": 0, "total": 0, "channel_id": ""})


async def download_and_import(channel_id: str, chat: str, overwrite: bool) -> dict:
    """Descarga el backup de un canal e importa, reportando progreso en _progress_state."""
    global _progress_state
    _progress_state.update({"running": True, "operation": "download", "step": "Buscando backup", "current": 0, "total": 0, "channel_id": str(channel_id)})
    try:
        manifest = await discover_backups(chat, channel_id=channel_id)
        if not manifest:
            return {"ok": False, "error": "No se encontró backup en los anclados del canal"}
        _progress_state["step"] = "Descargando backup"

        def _dl_progress(current, total):
            _progress_state["current"] = current
            _progress_state["total"] = total

        gz = await download_backup(manifest, chat, progress_callback=_dl_progress)
        if gz is None:
            return {"ok": False, "error": "No se pudo descargar/ensamblar el backup"}
        _progress_state["operation"] = "import"
        _progress_state["step"] = "Importando mensajes"
        _progress_state["current"] = 0

        def _on_progress(step, current, total):
            _progress_state["current"] = current
            _progress_state["total"] = total

        # Importar en un hilo (es síncrono/sqlite) para no bloquear el event loop
        result = await asyncio.to_thread(
            import_channel_cache, gz, channel_id, overwrite, manifest, chat, _on_progress)
        return result
    finally:
        _reset_progress()
