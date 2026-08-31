"""
TVCat Peers — Bridge Manager
=============================
Núcleo de gestión de peers: UUID de instancia, invites, CRUD,
scheduler de sync, semáforos de concurrencia y catálogo.
"""

import os
import json
import uuid
import hashlib
import sqlite3
import logging
import asyncio
import socket
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger("tvcat.peers.manager")

_PEERS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_PEERS_DIR, "data", "tvcat.db")
CONFIG_PATH = os.path.join(_PEERS_DIR, "data", "bridge_config.json")

# Semáforos de concurrencia
_peer_stream_semaphores: Dict[str, asyncio.Semaphore] = {}
_max_streams_per_peer = 1

# Scheduler task
_sync_scheduler_task: Optional[asyncio.Task] = None
_sync_callbacks = []


# ─── LAN IP Detection ────────────────────────────────────────────
def get_lan_ip() -> str:
    """Detecta la IP LAN no-loopback de esta máquina."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return ""

def get_lan_url(port: int = 8090) -> str:
    """Construye la URL LAN con la IP detectada y el puerto."""
    ip = get_lan_ip()
    if ip:
        return f"http://{ip}:{port}"
    return ""

# ─── Instance UUID ───────────────────────────────────────────────
def get_instance_uuid() -> str:
    """Retorna el UUID persistente de esta instancia TVCat.
    Almacenado en config/tvcat_config.json (mismo archivo que gateway.py).
    """
    base_dir = os.path.join(_PEERS_DIR, "..", "..")
    config_path = os.path.join(base_dir, "config", "tvcat_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
            if cfg.get("instance_uuid"):
                return cfg["instance_uuid"]
        except Exception:
            pass
    uid = str(uuid.uuid4())
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        cfg = {}
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cfg = json.load(f)
        cfg["instance_uuid"] = uid
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
    return uid


def get_instance_name() -> str:
    """Retorna el nombre configurable de esta instancia."""
    base_dir = os.path.join(_PEERS_DIR, "..", "..")
    config_path = os.path.join(base_dir, "config", "tvcat_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
            if cfg.get("instance_name"):
                return cfg["instance_name"]
        except Exception:
            pass
    return "TVCat"


def set_instance_name(name: str):
    base_dir = os.path.join(_PEERS_DIR, "..", "..")
    config_path = os.path.join(base_dir, "config", "tvcat_config.json")
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        cfg = {}
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cfg = json.load(f)
        cfg["instance_name"] = name
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.warning(f"Error guardando instance_name: {e}")


# ─── DB Helpers ─────────────────────────────────────────────────
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_tables():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS tvcat_bridge_peers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            alias TEXT,
            url TEXT NOT NULL,
            our_api_key TEXT NOT NULL,
            his_api_key TEXT NOT NULL,
            share_enabled INTEGER DEFAULT 1,
            receive_enabled INTEGER DEFAULT 1,
            shared_config TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            last_seen TEXT,
            last_sync TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tvcat_bridge_invites (
            token TEXT PRIMARY KEY,
            peer_id TEXT NOT NULL,
            peer_name TEXT,
            shared_config TEXT DEFAULT '{}',
            bound_peer_uuid TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tvcat_bridge_catalog (
            bridge_id TEXT PRIMARY KEY,
            peer_id TEXT NOT NULL,
            original_item_id TEXT NOT NULL,
            dedup_key TEXT,
            title TEXT,
            category TEXT,
            subcategory TEXT,
            year TEXT,
            description TEXT,
            metadata_json TEXT DEFAULT '{}',
            thumbnail_cached INTEGER DEFAULT 0,
            thumbnail_local TEXT,
            synced_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (peer_id) REFERENCES tvcat_bridge_peers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tvcat_bridge_catalog_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bridge_id TEXT NOT NULL,
            original_episode_id TEXT,
            episode_number INTEGER,
            season_number INTEGER DEFAULT 1,
            title TEXT,
            duration REAL,
            file_size INTEGER,
            FOREIGN KEY (bridge_id) REFERENCES tvcat_bridge_catalog(bridge_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tvcat_bridge_revoked (
            peer_uuid TEXT PRIMARY KEY,
            revoked_at TEXT DEFAULT (datetime('now')),
            cleanup_at TEXT
        );
    """)
    conn.commit()
    conn.close()


# ─── Peer CRUD ──────────────────────────────────────────────────
def add_peer(peer_id: str, name: str, url: str, our_key: str, his_key: str,
             shared_config: dict = None) -> dict:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO tvcat_bridge_peers
                (id, name, url, our_api_key, his_api_key, shared_config, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, (peer_id, name, url, our_key, his_key,
              json.dumps(shared_config or {})))
        conn.commit()
        return {"id": peer_id, "name": name, "url": url, "status": "active"}
    except sqlite3.IntegrityError:
        raise ValueError(f"Peer {peer_id} ya existe")
    finally:
        conn.close()


def get_peer(peer_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tvcat_bridge_peers WHERE id = ?",
                           (peer_id,)).fetchone()
        if row:
            data = dict(row)
            if isinstance(data.get("shared_config"), str):
                data["shared_config"] = json.loads(data["shared_config"])
            return data
        return None
    finally:
        conn.close()


def get_peer_by_api_key(api_key: str) -> Optional[dict]:
    """Busca un peer por su his_api_key (la clave que nos dieron para identificarnos).
    Útil como fallback cuando el peer_id aún no está registrado (race condition al aceptar invite)."""
    if not api_key:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM tvcat_bridge_peers WHERE his_api_key = ?",
            (api_key,)
        ).fetchone()
        if row:
            data = dict(row)
            if isinstance(data.get("shared_config"), str):
                data["shared_config"] = json.loads(data["shared_config"])
            return data
        return None
    finally:
        conn.close()


def get_peers() -> List[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM tvcat_bridge_peers ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("shared_config"), str):
                d["shared_config"] = json.loads(d["shared_config"])
            result.append(d)
        return result
    finally:
        conn.close()


def get_active_peers() -> List[dict]:
    """Retorna peers activos (status='active' y receive_enabled=1)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM tvcat_bridge_peers WHERE status='active' AND receive_enabled=1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_peer(peer_id: str, **kwargs):
    conn = get_connection()
    try:
        sets = []
        params = []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            params.append(v)
        params.append(peer_id)
        conn.execute(
            f"UPDATE tvcat_bridge_peers SET {', '.join(sets)} WHERE id = ?",
            params
        )
        conn.commit()
    finally:
        conn.close()


def delete_peer(peer_id: str):
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM tvcat_bridge_peers WHERE id = ?", (peer_id,))
        conn.commit()
    finally:
        conn.close()


# ─── Invites ────────────────────────────────────────────────────
def create_invite(peer_name: str, shared_config: dict,
                  ttl_hours: int = 72) -> dict:
    token = str(uuid.uuid4())
    peer_id = str(uuid.uuid4())
    expires_at = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO tvcat_bridge_invites
                (token, peer_id, peer_name, shared_config, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (token, peer_id, peer_name, json.dumps(shared_config), expires_at))
        conn.commit()
        return {"token": token, "peer_id": peer_id, "peer_name": peer_name,
                "expires_at": expires_at}
    finally:
        conn.close()


def get_invite(token: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM tvcat_bridge_invites WHERE token = ?", (token,)
        ).fetchone()
        if row:
            d = dict(row)
            if isinstance(d.get("shared_config"), str):
                d["shared_config"] = json.loads(d["shared_config"])
            return d
        return None
    finally:
        conn.close()


def accept_invite(token: str, remote_instance: dict) -> Optional[dict]:
    """
    Procesa la aceptación de un invite por parte del remoto.
    remote_instance: {uuid, name, url, api_key, our_api_key, shared_config}
    Es idempotente: si el invite ya estaba vinculado al mismo UUID, actualiza el peer.
    """
    invite = get_invite(token)
    if not invite:
        logger.warning(f"accept_invite: token '{token}' no encontrado en BD")
        print(f" [PEERS] accept_invite: token '{token}' no encontrado en BD")
        return None
    expires_at = datetime.fromisoformat(invite["expires_at"])
    if datetime.utcnow() > expires_at:
        logger.warning(f"accept_invite: invite '{token}' expirado")
        print(f" [PEERS] accept_invite: invite '{token}' expirado")
        return None

    invite_shared = invite.get("shared_config", {})

    if invite["bound_peer_uuid"]:
        # Si ya está vinculado al mismo UUID, es idempotente — actualizamos y devolvemos
        if invite["bound_peer_uuid"] == remote_instance["uuid"]:
            logger.info(f"accept_invite: invite ya vinculado al mismo peer {remote_instance['uuid']} — actualizando")
            print(f" [PEERS] accept_invite: invite ya vinculado al mismo peer {remote_instance['uuid']} — actualizando (idempotente)")
            conn = get_connection()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO tvcat_bridge_peers
                        (id, name, url, our_api_key, his_api_key, shared_config, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'active')
                """, (remote_instance["uuid"], remote_instance.get("name", "Desconocido"),
                      remote_instance["url"], remote_instance.get("our_api_key", ""),
                      remote_instance.get("api_key", ""),
                      json.dumps(invite_shared)))
                conn.commit()
                logger.info(f"accept_invite (idempotente): peer actualizado id='{remote_instance['uuid']}'")
                return invite
            finally:
                conn.close()
        else:
            logger.warning(f"accept_invite: invite '{token}' ya vinculado a {invite['bound_peer_uuid']}, rechazando a {remote_instance['uuid']}")
            return None

    conn = get_connection()
    try:
        conn.execute("UPDATE tvcat_bridge_invites SET bound_peer_uuid = ? WHERE token = ?",
                     (remote_instance["uuid"], token))
        conn.execute("""
            INSERT OR REPLACE INTO tvcat_bridge_peers
                (id, name, url, our_api_key, his_api_key, shared_config, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, (remote_instance["uuid"], remote_instance.get("name", "Desconocido"),
              remote_instance["url"], remote_instance.get("our_api_key", ""),
              remote_instance.get("api_key", ""),
              json.dumps(invite_shared)))
        conn.commit()
        # Verificar que realmente se guardó
        verify = conn.execute("SELECT id FROM tvcat_bridge_peers WHERE id = ?", (remote_instance["uuid"],)).fetchone()
        if verify:
            logger.info(f"accept_invite: peer guardado y verificado con id='{remote_instance['uuid']}', name='{remote_instance.get('name')}', url='{remote_instance.get('url')}'")
        else:
            logger.error(f"accept_invite: ¡FALLO! INSERT ejecutado pero el peer '{remote_instance['uuid']}' NO aparece en la BD")
        return invite
    finally:
        conn.close()


def revoke_peer(peer_uuid: str):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO tvcat_bridge_revoked (peer_uuid, cleanup_at)
            VALUES (?, datetime('now', '+30 days'))
        """, (peer_uuid,))
        conn.commit()
    finally:
        conn.close()


def is_revoked(peer_uuid: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM tvcat_bridge_revoked WHERE peer_uuid = ?",
            (peer_uuid,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ─── Catalog (unified_catalog bridge) ───────────────────────────
async def add_catalog_items(peer_id: str, items: list):
    """Inserta o actualiza items del catálogo remoto en la caché local (en hilo separado)."""
    def _sync():
        conn = get_connection()
        try:
            now = datetime.utcnow().isoformat()
            for item in items:
                conn.execute("""
                    INSERT OR REPLACE INTO tvcat_bridge_catalog
                        (bridge_id, peer_id, original_item_id, dedup_key,
                         title, category, subcategory, year, description,
                         metadata_json, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item["bridge_id"], peer_id, item["original_item_id"],
                    item.get("dedup_key", ""),
                    item.get("title", ""), item.get("category", ""),
                    item.get("subcategory", ""), item.get("year", ""),
                    item.get("description", ""),
                    json.dumps(item.get("metadata", {})), now
                ))
                if "episodes" in item:
                    conn.execute("DELETE FROM tvcat_bridge_catalog_episodes WHERE bridge_id = ?",
                                 (item["bridge_id"],))
                    for ep in item["episodes"]:
                        conn.execute("""
                            INSERT INTO tvcat_bridge_catalog_episodes
                                (bridge_id, original_episode_id, episode_number,
                                 season_number, title, duration, file_size)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (item["bridge_id"], ep.get("original_episode_id", ""),
                              ep.get("episode_number", 0), ep.get("season_number", 1),
                              ep.get("title", ""), ep.get("duration", 0),
                              ep.get("file_size", 0)))
            conn.commit()
        finally:
            conn.close()
    await asyncio.to_thread(_sync)


def remove_catalog_items_by_peer(peer_id: str):
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM tvcat_bridge_catalog WHERE peer_id = ?", (peer_id,))
        conn.commit()
    finally:
        conn.close()


async def remove_catalog_items_not_in_manifest(peer_id: str, bridge_ids: set):
    """Elimina items locales que ya no están en el manifest del peer (en hilo separado)."""
    def _sync():
        conn = get_connection()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            placeholders = ",".join("?" for _ in bridge_ids)
            conn.execute(f"""
                DELETE FROM tvcat_bridge_catalog
                WHERE peer_id = ? AND bridge_id NOT IN ({placeholders})
            """, (peer_id, *bridge_ids))
            conn.commit()
        finally:
            conn.close()
    await asyncio.to_thread(_sync)


def get_peer_catalog_categories(peer_id: str) -> dict:
    """Retorna estructura de categorías de un peer como {cat: [subcat, ...]}."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT DISTINCT category, subcategory
            FROM tvcat_bridge_catalog
            WHERE peer_id = ? AND category != ''
            ORDER BY category, subcategory
        """, (peer_id,)).fetchall()
        cats = {}
        for r in rows:
            cat = r["category"]
            sub = r["subcategory"]
            if cat not in cats:
                cats[cat] = []
            if sub and sub not in cats[cat]:
                cats[cat].append(sub)
        return cats
    finally:
        conn.close()


def get_peer_catalog_items(peer_id: str, category: str = None,
                           subcategory: str = None, limit: int = 100,
                           offset: int = 0) -> Tuple[List[dict], int]:
    """Retorna items del catálogo de un peer con paginación."""
    conn = get_connection()
    try:
        where = "WHERE peer_id = ?"
        params = [peer_id]
        if category:
            where += " AND category = ?"
            params.append(category)
        if subcategory:
            where += " AND subcategory = ?"
            params.append(subcategory)

        count = conn.execute(
            f"SELECT COUNT(*) FROM tvcat_bridge_catalog {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM tvcat_bridge_catalog {where} ORDER BY title LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        items = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("metadata_json"), str):
                d["metadata_json"] = json.loads(d["metadata_json"])
            items.append(d)
        return items, count
    finally:
        conn.close()


# ─── Sync Manifest Helpers ─────────────────────────────────────
def generate_manifest(peer_id: str) -> List[dict]:
    """
    Genera el manifest compacto de items compartidos con un peer específico.
    Filtra según shared_config del peer (categorías/subcategorías autorizadas).
    """
    peer = get_peer(peer_id)
    if not peer:
        logger.warning(f"generate_manifest: peer {peer_id} NO ENCONTRADO")
        print(f" [MANIFEST] generate_manifest: peer {peer_id} NO ENCONTRADO")
        return []
    if not peer.get("share_enabled"):
        logger.info(f"generate_manifest: peer {peer['name']} tiene share_enabled=False — manifest vacío")
        print(f" [MANIFEST] generate_manifest: peer {peer['name']} share_enabled=False")
        return []

    shared_config = peer.get("shared_config", {})
    if isinstance(shared_config, str):
        shared_config = json.loads(shared_config)

    allowed_cats = shared_config.get("categories", [])
    allowed_subcats = shared_config.get("subcategories", [])

    logger.info(f"generate_manifest: peer={peer['name']}, shared_config={shared_config}")
    print(f" [MANIFEST] generate_manifest: peer={peer['name']}")
    print(f" [MANIFEST]   shared_config={json.dumps(shared_config)}")
    print(f" [MANIFEST]   allowed_cats={allowed_cats}")
    print(f" [MANIFEST]   allowed_subcats={allowed_subcats}")

    from tvcat.gateway import get_enabled_plugin_dbs_with_names

    # Cargar los IDs de escaneo habilitados desde la base de datos del sistema
    enabled_scan_sources = set()
    try:
        from tvcat.gateway import get_db_connection
        conn_sys = get_db_connection(system=True)
        cur_sys = conn_sys.cursor()
        cur_sys.execute("SELECT id FROM tvcat_scanned_channels WHERE enabled = 1")
        for row_sys in cur_sys.fetchall():
            enabled_scan_sources.add(f"scan_{row_sys[0]}")
        conn_sys.close()
    except Exception as e_sys:
        print(f" [MANIFEST] Error cargando canales habilitados: {e_sys}")

    use_subcat_filter = bool(allowed_subcats)
    use_cat_filter = bool(allowed_cats) and not use_subcat_filter
    print(f" [MANIFEST]   use_subcat_filter={use_subcat_filter}, use_cat_filter={use_cat_filter}")
    dbs = get_enabled_plugin_dbs_with_names()
    print(f" [MANIFEST]   DBs disponibles: {[(pname, db_path) for db_path, pname in dbs]}")
    manifest = []

    for db_path, pname in dbs:
        if pname == "tvcat_peers":
            continue
        if not os.path.exists(db_path):
            print(f" [MANIFEST]   DB {pname} no existe en disco: {db_path}")
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Detectar columnas disponibles
            cols = {r["name"] for r in cursor.execute("PRAGMA table_info(unified_catalog)").fetchall()}
            if not cols:
                print(f" [MANIFEST]   DB {pname}: tabla unified_catalog no existe o está vacía")
                conn.close()
                continue
            select_cols = [c for c in ["item_id", "category", "subcategory", "title", "api_cover", "api_year", "description", "info_messages", "channel_id", "msg_id", "source"] if c in cols]
            cursor.execute(f"SELECT {','.join(select_cols)} FROM unified_catalog")
            rows = cursor.fetchall()
            print(f" [MANIFEST]   DB {pname}: {len(rows)} items totales en unified_catalog")

            for row in rows:
                if "source" in select_cols:
                    source = row["source"] or ""
                    if source.startswith("scan_") and source not in enabled_scan_sources:
                        print(f" [MANIFEST]   Excluyendo item {row['item_id']} porque su canal de escaneo ({source}) está deshabilitado")
                        continue

                cat = row["category"] or ""
                sub = row["subcategory"] or ""
                if use_subcat_filter:
                    subcat_path = f"{cat}/{sub}" if sub else cat
                    # Comparación case-insensitive
                    match = any(subcat_path.lower() == allowed.lower() for allowed in allowed_subcats)
                    print(f" [MANIFEST]   ITEM cat='{cat}' sub='{sub}' → subcat_path='{subcat_path}' | match={match} | allowed={allowed_subcats}")
                    if not match:
                        continue
                elif use_cat_filter:
                    # Comparación case-insensitive
                    match = any(cat.lower() == allowed.lower() for allowed in allowed_cats)
                    print(f" [MANIFEST]   ITEM cat='{cat}' → match={match} | allowed_cats={allowed_cats}")
                    if not match:
                        continue

                has_channel = "channel_id" in cols and "msg_id" in cols
                ch = row["channel_id"] if has_channel else ""
                msg = row["msg_id"] if has_channel else ""
                dedup_key = hashlib.sha256(f"{ch or ''}:{msg or ''}".encode()).hexdigest()[:12]

                bridge_id = f"PEER-{peer_id[:8]}-{row['item_id'][-16:]}"

                # Obtener episodios
                episodes = []
                try:
                    cursor.execute(
                        "SELECT original_episode_id, episode_number, season_number, title, duration, file_size FROM item_episodes WHERE item_id = ?",
                        (row["item_id"],)
                    )
                    episodes = [dict(e) for e in cursor.fetchall()]
                except Exception:
                    pass

                manifest.append({
                    "bridge_id": bridge_id,
                    "dedup_key": dedup_key,
                    "original_item_id": row["item_id"],
                    "title": row["title"] or "",
                    "category": cat,
                    "subcategory": sub,
                    "year": (row["api_year"] if "api_year" in cols else "") or "",
                    "description": (row["description"] if "description" in cols else "") or "",
                    "metadata": {
                        "api_cover": (row["api_cover"] if "api_cover" in cols else "") or "",
                        "info_messages": (row["info_messages"] if "info_messages" in cols else "") or "",
                    },
                    "episodes": episodes,
                    "updated_at": int(datetime.utcnow().timestamp()),
                })
            conn.close()
            print(f" [MANIFEST]   DB {pname}: {len(manifest)} items pasaron el filtro (acumulado)")
        except Exception as e:
            logger.warning(f"Error generando manifest desde {db_path}: {e}")
            print(f" [MANIFEST]   ERROR en DB {db_path}: {e}")

    print(f" [MANIFEST] TOTAL items en manifest para {peer['name']}: {len(manifest)}")
    logger.info(f"generate_manifest: TOTAL {len(manifest)} items para peer {peer['name']}")
    return manifest


# ─── Scheduler ──────────────────────────────────────────────────
def on_sync_scheduled(callback):
    """Registra callback para notificaciones del scheduler."""
    _sync_callbacks.append(callback)


async def _sync_loop():
    """Timer periódico que dispara sync para peers activos."""
    while True:
        try:
            await asyncio.sleep(300)
            peers = get_peers()
            for p in peers:
                if p["status"] == "active" and p.get("receive_enabled"):
                    for cb in _sync_callbacks:
                        try:
                            await cb(p["id"])
                        except Exception as e:
                            logger.warning(f"Error en sync callback: {e}")
        except asyncio.CancelledError:
            break
        except Exception:
            pass


_scheduler_started = False

def start_sync_scheduler():
    global _sync_scheduler_task, _scheduler_started
    if _scheduler_started:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _scheduler_started = True
    if _sync_scheduler_task is None or _sync_scheduler_task.done():
        _sync_scheduler_task = asyncio.create_task(_sync_loop())


# ─── Semaphore helpers ──────────────────────────────────────────
def get_peer_semaphore(peer_id: str) -> asyncio.Semaphore:
    if peer_id not in _peer_stream_semaphores:
        _peer_stream_semaphores[peer_id] = asyncio.Semaphore(_max_streams_per_peer)
    return _peer_stream_semaphores[peer_id]


# ─── Initialization ──────────────────────────────────────────────
init_tables()
