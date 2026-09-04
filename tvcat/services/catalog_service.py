"""
TVCat 2 - Catalog Service
Manejo de la base de datos central y operaciones de catálogo.
"""
import os
import re
import sqlite3
import json
import random

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "data", "tvcat.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    """Crea las tablas iniciales si no existen."""
    conn = get_conn()
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS unified_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT UNIQUE,
            title TEXT,
            category TEXT,
            subcategory TEXT,
            source TEXT,
            origin_depth INTEGER DEFAULT 0,
            description TEXT,
            year TEXT,
            rating REAL,
            cover_url TEXT,
            backdrop_url TEXT,
            alt_titles TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}',
            telegram_msg_id INTEGER,
            group_title TEXT,
            group_title_flat TEXT,
            telegram_link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS item_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT,
            episode_key TEXT,
            episode_number INTEGER,
            season_number INTEGER DEFAULT 1,
            title TEXT,
            duration REAL,
            FOREIGN KEY(item_id) REFERENCES unified_catalog(item_id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'user',
            allowed_categories TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            token TEXT UNIQUE,
            profile_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES tvcat_users(id) ON DELETE CASCADE
        )
    """)

    # --- Perfiles de contenido (etiqueta de agrupación para filtros) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Perfiles iniciales (solo la primera vez: si la tabla está vacía)
    cnt = c.execute("SELECT COUNT(*) FROM tvcat_profiles").fetchone()[0]
    if cnt == 0:
        for pname in ("admin", "usuario normal"):
            c.execute("INSERT INTO tvcat_profiles (name) VALUES (?)", (pname,))
    # Migración: is_admin (perfil que otorga rol admin = el que usan los usuarios admin)
    try:
        c.execute("ALTER TABLE tvcat_profiles ADD COLUMN is_admin INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Migración: tvcat_users.profile_id (debe existir antes del UPDATE que lo usa)
    try:
        c.execute("ALTER TABLE tvcat_users ADD COLUMN profile_id INTEGER")
    except sqlite3.OperationalError:
        pass
    c.execute("UPDATE tvcat_profiles SET is_admin=1 WHERE id IN (SELECT DISTINCT profile_id FROM tvcat_users WHERE role='admin' AND profile_id IS NOT NULL)")
    # Migración: tvcat_users.google_email (asociación de login con Google)
    try:
        c.execute("ALTER TABLE tvcat_users ADD COLUMN google_email TEXT")
    except sqlite3.OperationalError:
        pass
    # Asignar perfil por defecto: admin → perfil admin, resto → usuario normal
    c.execute("""
        UPDATE tvcat_users SET profile_id = (SELECT id FROM tvcat_profiles WHERE name='admin')
        WHERE role='admin' AND (profile_id IS NULL OR profile_id=0)
    """)
    c.execute("""
        UPDATE tvcat_users SET profile_id = (SELECT id FROM tvcat_profiles WHERE name='usuario normal')
        WHERE profile_id IS NULL OR profile_id=0
    """)

    # --- Preferencias de perfil por usuario (nick, avatar, color, etc.) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_user_prefs (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            avatar TEXT,
            avatar_url TEXT,
            color TEXT,
            category_preferences TEXT DEFAULT '{}',
            watch_threshold_min REAL DEFAULT 5,
            watch_threshold_max REAL DEFAULT 85,
            hls_title_prefs TEXT DEFAULT '{}',
            FOREIGN KEY(user_id) REFERENCES tvcat_users(id) ON DELETE CASCADE
        )
    """)


    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_favorites (
            profile_id INTEGER,
            item_id TEXT,
            PRIMARY KEY (profile_id, item_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS watch_progress (
            profile_id INTEGER,
            item_id TEXT,
            episode_key TEXT,
            episode_id INTEGER,
            progress REAL DEFAULT 0,
            duration REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed INTEGER DEFAULT 0,
            watched_state INTEGER DEFAULT 0,
            PRIMARY KEY (profile_id, item_id, episode_key)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_qr_auth (
            request_id TEXT PRIMARY KEY,
            user_id INTEGER,
            status TEXT DEFAULT 'pending',
            created INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS enrich_cache (
            key TEXT PRIMARY KEY,
            result TEXT,
            created_at INTEGER
        )
    """)

    # Commit antes de init_userbot_table para liberar el lock de la DB central
    conn.commit()
    from services.userbot_service import init_table as init_userbot_table
    try:
        init_userbot_table()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            import time
            time.sleep(0.5)
            init_userbot_table()
        else:
            raise

    c.execute("""
        CREATE TABLE IF NOT EXISTS tvcat_telegram_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            display_name TEXT,
            phone TEXT,
            session_string TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute(CATALOG_ASSETS_DDL)

    c.execute("""
        CREATE TABLE IF NOT EXISTS telegram_message_cache (
            channel_id  TEXT NOT NULL,
            topic_id    INTEGER,
            msg_id      INTEGER NOT NULL,
            message     TEXT NOT NULL,
            fetched_at  INTEGER DEFAULT (unixepoch()),
            PRIMARY KEY (channel_id, msg_id)
        )
    """)

    # --- Diccionario de géneros (agrupación de tags para filtros) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS tag_dictionary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL UNIQUE,
            tags TEXT NOT NULL DEFAULT '[]',
            sort_order INTEGER DEFAULT 0
        )
    """)
    _seed_tag_dictionary(conn)

    # Crear admin por defecto si no existe
    c.execute("SELECT id FROM tvcat_users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute("INSERT INTO tvcat_users (username, password, role) VALUES (?, ?, ?)",
                  ("admin", "admintvcat", "admin"))

    # Migraciones seguras
    for col, typ in [("telegram_msg_id", "INTEGER"), ("cover_url", "TEXT"), ("group_title", "TEXT"), ("group_title_flat", "TEXT"), ("telegram_link", "TEXT"), ("season_display", "TEXT"),
                     ("info_messages", "TEXT"), ("season_number", "TEXT"), ("api_year", "TEXT"), ("active_cover_idx", "INTEGER"), ("api_cover", "TEXT"),
                     ("backdrop", "TEXT"), ("release_date", "TEXT"), ("sync_status", "TEXT"), ("source_channel_id", "TEXT"), ("client_type", "TEXT"), ("genres", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE unified_catalog ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    for col, typ in [("telegram_msg_id", "INTEGER"), ("telegram_link", "TEXT"), ("file_size", "INTEGER"), ("file_name", "TEXT"), ("caption", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE item_episodes ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    for col, typ in [("prepared_by_tghirayi", "INTEGER DEFAULT 0"), ("tghirayi_version", "TEXT DEFAULT ''"),
                     ("video_codec", "TEXT DEFAULT ''"), ("is_mkv", "INTEGER DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE item_episodes ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE unified_catalog ADD COLUMN has_mkv INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Tabla de metadata de pistas de audio/subtítulos por episodio (HLS multitrack).
    c.execute("""
        CREATE TABLE IF NOT EXISTS episode_tracks (
            episode_id INTEGER NOT NULL,
            track_type TEXT NOT NULL,
            track_index INTEGER NOT NULL,
            language TEXT DEFAULT '',
            title TEXT DEFAULT '',
            is_default INTEGER DEFAULT 0,
            codec TEXT DEFAULT '',
            PRIMARY KEY (episode_id, track_type, track_index)
        )
    """)
    for col, typ in [("completed", "INTEGER DEFAULT 0"), ("watched_state", "INTEGER DEFAULT 0"), ("episode_key", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE watch_progress ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    for col, typ in [("watch_threshold_min", "REAL DEFAULT 5"), ("watch_threshold_max", "REAL DEFAULT 85"), ("hls_title_prefs", "TEXT DEFAULT '{}'")]:
        try:
            c.execute(f"ALTER TABLE tvcat_user_prefs ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE item_episodes ADD COLUMN episode_key TEXT")
    except sqlite3.OperationalError:
        pass

    # Reconstrucción de watch_progress: migrar PK de (profile_id,item_id,episode_id)
    # a (profile_id,item_id,episode_key). Los datos sin episode_key se descartan (historial de prueba).
    try:
        wp_sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='watch_progress'"
        ).fetchone()[0]
        if "episode_key" not in wp_sql or "PRIMARY KEY (profile_id, item_id, episode_key)" not in (wp_sql or ""):
            c.execute("ALTER TABLE watch_progress RENAME TO watch_progress_old")
            c.execute("""
                CREATE TABLE watch_progress (
                    profile_id INTEGER,
                    item_id TEXT,
                    episode_key TEXT,
                    episode_id INTEGER,
                    progress REAL DEFAULT 0,
                    duration REAL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed INTEGER DEFAULT 0,
                    watched_state INTEGER DEFAULT 0,
                    PRIMARY KEY (profile_id, item_id, episode_key)
                )
            """)
            # Conservar solo registros con episode_key (historial nuevo válido)
            c.execute("""
                INSERT INTO watch_progress
                    (profile_id, item_id, episode_key, episode_id, progress, duration, updated_at, completed, watched_state)
                SELECT profile_id, item_id, episode_key, episode_id, progress, duration, updated_at, completed, watched_state
                FROM watch_progress_old WHERE episode_key IS NOT NULL AND episode_key != ''
            """)
            c.execute("DROP TABLE watch_progress_old")
    except sqlite3.OperationalError:
        pass

    # Poblar is_mkv en item_episodes y has_mkv en unified_catalog para datos existentes (idempotente).
    try:
        c.execute("""
            UPDATE item_episodes SET is_mkv = 1
            WHERE LOWER(file_name) LIKE '%.mkv' AND is_mkv = 0
        """)
        c.execute("""
            UPDATE unified_catalog SET has_mkv = 1
            WHERE item_id IN (
                SELECT DISTINCT item_id FROM item_episodes WHERE is_mkv = 1
            )
        """)
    except sqlite3.OperationalError:
        pass

    # Índices para consultas de progreso/visualización (item_episodes sin índice causa scans de 170k filas por item).
    c.execute("CREATE INDEX IF NOT EXISTS idx_item_episodes_item_id ON item_episodes(item_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_watch_progress_item ON watch_progress(item_id, episode_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_item_episodes_key ON item_episodes(item_id, episode_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_watch_progress_key ON watch_progress(profile_id, episode_key)")

    conn.commit()
    conn.close()
    print(" [CATALOG] Base de datos inicializada")
    # Migración de claves canónicas channelid_msgid (una vez; ver CatalogAssets_ChannelKey_Fix_Plan.md)
    try:
        migrate_cache_keys()
    except Exception as e:
        print(f" [CATALOG] migrate_cache_keys omitida: {e}", flush=True)


def _seed_tag_dictionary(conn):
    """Puebla la tabla tag_dictionary desde data/tag_dictionary_base.json
    SOLO si la tabla está vacía (semilla inicial). No se sobrescribe nunca el diccionario editado."""
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM tag_dictionary").fetchone()[0]
        if cnt > 0:
            return
        seed_path = os.path.join(BASE_DIR, "data", "tag_dictionary_base.json")
        with open(seed_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        terms = data.get("terms", [])
        for i, t in enumerate(terms):
            conn.execute(
                "INSERT INTO tag_dictionary (term, tags, sort_order) VALUES (?, ?, ?)",
                (t["term"], json.dumps(t.get("tags", []), ensure_ascii=False), i),
            )
        conn.commit()
        print(f" [CATALOG] Diccionario de géneros sembrado: {len(terms)} términos")
    except FileNotFoundError:
        print(" [CATALOG] tag_dictionary_base.json no encontrado; diccionario vacío")
    except Exception as e:
        print(f" [CATALOG] Error sembrando tag_dictionary: {e}")


def get_tag_dictionary():
    """Devuelve el diccionario de géneros ordenado."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT term, tags, sort_order FROM tag_dictionary ORDER BY sort_order, term"
        ).fetchall()
    finally:
        conn.close()
    return [{"term": r["term"], "tags": json.loads(r["tags"] or "[]")} for r in rows]


def rebuild_cache(plugin_loader):
    """Reconstruye la caché central desde los source plugins (items + episodios + assets)."""
    conn = get_conn()
    c = conn.cursor()

    # 1. Preservar catalog_assets de fuentes externas (JIT covers, thumbs)
    c.execute("SELECT * FROM catalog_assets")
    preserved_assets = [dict(r) for r in c.fetchall()]

    # 2. Limpiar TODOS los datos de plugins (incluyendo deshabilitados): items Y episodios
    c.execute("SELECT item_id FROM unified_catalog WHERE source IS NOT NULL")
    plugin_item_ids = [r[0] for r in c.fetchall()]
    if plugin_item_ids:
        ph = ",".join("?" for _ in plugin_item_ids)
        c.execute(f"DELETE FROM item_episodes WHERE item_id IN ({ph})", plugin_item_ids)
    c.execute("DELETE FROM unified_catalog WHERE source IS NOT NULL")
    c.execute("DELETE FROM catalog_assets")
    # Commit antes de delegar en sync_plugin_cache (que usa su propia conexión)
    conn.commit()

    # 3. Re-insertar solo desde plugins habilitados (delega en sync_plugin_cache)
    for name, data in plugin_loader.registry.items():
        if not data.get("enabled") or data.get("type") != "source":
            continue
        try:
            sync_plugin_cache(plugin_loader, name)
        except Exception as e:
            print(f" [CATALOG] Error cacheando plugin {name}: {e}")

    # 4. Re-insertar assets preservados que no hayan sido copiados por plugins (JIT covers, etc.)
    c = conn.cursor()
    for ad in preserved_assets:
        try:
            c.execute("""
                INSERT OR IGNORE INTO catalog_assets
                (channel_id, telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ad.get("channel_id", ""),
                ad.get("telegram_msg_id"),
                ad.get("asset_type", "cover"),
                ad.get("asset_index", 0),
                ad.get("image_blob"),
                ad.get("mime_type"),
                ad.get("file_size"),
                ad.get("width"),
                ad.get("height"),
                ad.get("source", "__preserved__")
            ))
        except Exception:
            pass

    conn.commit()

    total = c.execute("SELECT COUNT(*) FROM unified_catalog").fetchone()[0]
    eps_total = c.execute("SELECT COUNT(*) FROM item_episodes").fetchone()[0]

    conn.commit()
    conn.close()
    print(f" [CATALOG] Caché reconstruida ({total} items, {eps_total} episodios)")


def _derive_episode_key(telegram_link):
    """Deriva la clave natural 'channel_msgid' desde un telegram_link.
    Formatos soportados:
      https://t.me/c/{channel}/{msgid}          -> '{channel}_{msgid}'
      https://t.me/c/{channel}/{topic}/{msgid}  -> '{channel}_{msgid}' (se ignora el topic)
    Devuelve '' si no se puede derivar.
    Delega en services.cache_keys (único criterio, Project_Architecture §21.9 / plan channel-key).
    """
    try:
        from services.cache_keys import key_from_link
        return key_from_link(telegram_link)
    except Exception:
        if not telegram_link:
            return ""
        m = re.search(r"/c/(\d+)/(?:(\d+)/)?(\d+)", telegram_link)
        if not m:
            return ""
        return f"{m.group(1)}_{m.group(3)}"


CATALOG_ASSETS_DDL = """
    CREATE TABLE IF NOT EXISTS catalog_assets (
        channel_id TEXT NOT NULL DEFAULT '',
        telegram_msg_id INTEGER,
        asset_type TEXT,
        asset_index INTEGER DEFAULT 0,
        image_blob BLOB,
        mime_type TEXT,
        file_size INTEGER,
        width INTEGER,
        height INTEGER,
        source TEXT,
        PRIMARY KEY (channel_id, telegram_msg_id, asset_type, asset_index)
    )
"""


def migrate_cache_keys():
    """Migración 2026-09-03 — unifica claves channelid_msgid (canon_channel).
    - telegram_message_cache: normaliza channel_id a canónico + dedupe (conserva fetched_at mayor).
    - catalog_assets (central + plugins con la tabla): rebuild con channel_id en PK;
      conserva filas sintéticas (telegram_msg_id < 0, channel_id=''), purga el resto (caché regenerable vía JIT).
    Idempotente (flag tvcat_settings schema_cache_keys_v1). Ver CatalogAssets_ChannelKey_Fix_Plan.md.
    """
    from services.cache_keys import canon_channel
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key='schema_cache_keys_v1'").fetchone()
    except Exception:
        row = None
    if row and (row[0] == "1"):
        conn.close()
        return {"migrated": False, "reason": "already applied"}

    stats = {"raw_normalized": 0, "raw_deduped": 0, "assets_purged": 0, "assets_kept": 0}

    # 1) telegram_message_cache: normalizar + dedupe
    try:
        rows = conn.execute(
            "SELECT channel_id, topic_id, msg_id, message, fetched_at FROM telegram_message_cache"
        ).fetchall()
        winners = {}
        for r in rows:
            key = (canon_channel(r["channel_id"]), int(r["msg_id"]))
            prev = winners.get(key)
            if prev is None or int(r["fetched_at"] or 0) >= int(prev["fetched_at"] or 0):
                winners[key] = r
        stats["raw_deduped"] = len(rows) - len(winners)
        conn.execute("DELETE FROM telegram_message_cache")
        for (ch, mid), r in winners.items():
            if ch != str(r["channel_id"]):
                stats["raw_normalized"] += 1
            conn.execute(
                "INSERT OR REPLACE INTO telegram_message_cache (channel_id, topic_id, msg_id, message, fetched_at) VALUES (?, ?, ?, ?, ?)",
                (ch, r["topic_id"], int(r["msg_id"]), r["message"], int(r["fetched_at"] or 0)),
            )
        conn.commit()
    except Exception as e:
        print(f" [MIGRATE keys] raw normalize error: {e}", flush=True)

    # 2) catalog_assets central: rebuild con channel_id (conserva sintéticos < 0)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(catalog_assets)").fetchall()]
        if cols and "channel_id" not in cols:
            gen = conn.execute(
                "SELECT telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height, source FROM catalog_assets WHERE telegram_msg_id < 0"
            ).fetchall()
            stats["assets_kept"] = len(gen)
            purged = conn.execute("SELECT COUNT(*) FROM catalog_assets WHERE telegram_msg_id >= 0").fetchone()[0]
            stats["assets_purged"] = purged or 0
            conn.execute("DROP TABLE IF EXISTS catalog_assets")
            conn.execute(CATALOG_ASSETS_DDL)
            for g in gen:
                conn.execute(
                    "INSERT OR REPLACE INTO catalog_assets (channel_id, telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height, source) VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (g["telegram_msg_id"], g["asset_type"], g["asset_index"], g["image_blob"], g["mime_type"], g["file_size"], g["width"], g["height"], g["source"]),
                )
            conn.commit()
    except Exception as e:
        print(f" [MIGRATE keys] assets rebuild error: {e}", flush=True)

    # 3) catalog_assets en DBs de plugins (si existe la tabla): mismo rebuild
    try:
        import glob as _glob
        for db_path in _glob.glob(os.path.join(BASE_DIR, "plugins", "*", "data", "tvcat.db")):
            try:
                pc = sqlite3.connect(db_path, timeout=30)
                pc.execute("PRAGMA busy_timeout=30000")
                pcols = [r[1] for r in pc.execute("PRAGMA table_info(catalog_assets)").fetchall()]
                if not pcols:
                    pc.close()
                    continue
                if "channel_id" not in pcols:
                    gen = pc.execute(
                        "SELECT telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height FROM catalog_assets WHERE telegram_msg_id < 0"
                    ).fetchall()
                    pc.execute("DROP TABLE IF EXISTS catalog_assets")
                    pc.execute("""
                        CREATE TABLE IF NOT EXISTS catalog_assets (
                            channel_id TEXT NOT NULL DEFAULT '',
                            telegram_msg_id INTEGER,
                            asset_type TEXT,
                            asset_index INTEGER DEFAULT 0,
                            image_blob BLOB,
                            mime_type TEXT,
                            file_size INTEGER,
                            width INTEGER,
                            height INTEGER,
                            PRIMARY KEY (channel_id, telegram_msg_id, asset_type, asset_index)
                        )
                    """)
                    for g in gen:
                        pc.execute(
                            "INSERT OR REPLACE INTO catalog_assets (channel_id, telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height) VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?)",
                            (g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7]),
                        )
                    pc.commit()
                pc.close()
            except Exception as e:
                print(f" [MIGRATE keys] plugin {db_path}: {e}", flush=True)
    except Exception as e:
        print(f" [MIGRATE keys] plugins error: {e}", flush=True)

    try:
        conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES ('schema_cache_keys_v1', '1')")
        conn.commit()
    except Exception:
        pass
    conn.close()
    print(f" [MIGRATE keys] done: {stats}", flush=True)
    return {"migrated": True, **stats}


def sync_plugin_cache(plugin_loader, plugin_name: str):
    """Sincroniza la caché central desde las tablas de exportación de un plugin."""
    if plugin_name not in plugin_loader.registry:
        return {"success": False, "error": "Plugin no encontrado"}

    data = plugin_loader.registry[plugin_name]
    if not data.get("enabled"):
        return {"success": False, "error": "Plugin deshabilitado"}

    plugin_dir = data.get("_dir", "")
    plugin_db = os.path.join(plugin_dir, "data", "tvcat.db")
    if not os.path.exists(plugin_db):
        return {"success": False, "error": "Base de datos del plugin no encontrada"}

    conn = get_conn()
    c = conn.cursor()

    try:
        pconn = sqlite3.connect(plugin_db, timeout=30)
        pconn.execute("PRAGMA busy_timeout=30000")
        pconn.row_factory = sqlite3.Row
        pc = pconn.cursor()

        # Verificar si el plugin tiene tablas de exportación
        has_export = False
        for tbl in pc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='plugin_catalog_export'").fetchall():
            has_export = True
            break

        if not has_export:
            pconn.close()
            conn.close()
            return {"success": False, "error": "El plugin no tiene tabla plugin_catalog_export"}

        # Mapa id_interno (unified_catalog.id) -> item_id de catálogo (USER-...)
        # El plugin guarda item_episodes.item_id = unified_catalog.id (entero).
        # Este mapa permite traducir a la clave de catálogo al copiar los episodios.
        id_to_item = {}
        for r in pc.execute("SELECT id, item_id FROM unified_catalog"):
            id_to_item[str(r["id"])] = r["item_id"]
            if r["item_id"]:
                id_to_item[r["item_id"]] = r["item_id"]

        def resolve_item_id(raw):
            return id_to_item.get(str(raw), raw)

        # Eliminar datos antiguos del plugin en la caché central
        # Primero episodios, luego catálogo (por FK). Borra por item_id del catálogo (USER-...)
        c.execute("""
            DELETE FROM item_episodes WHERE item_id IN (
                SELECT item_id FROM unified_catalog WHERE source = ?
            )
        """, (plugin_name,))
        c.execute("DELETE FROM unified_catalog WHERE source = ?", (plugin_name,))

        # Insertar ítems activos
        items_inserted = 0
        active_item_ids = set()
        for row in pc.execute("SELECT * FROM plugin_catalog_export WHERE sync_status = 'active'"):
            d = dict(row)
            item_id = d.get("item_id", "")
            if not item_id:
                continue
            active_item_ids.add(item_id)
            info = d.get("info_messages") or ""
            genres = _extract_genres(info, d.get("metadata_json"))
            c.execute("""
                INSERT OR REPLACE INTO unified_catalog
                (item_id, title, category, subcategory, source, origin_depth,
                 description, year, rating, alt_titles, metadata_json, cover_url,
                 telegram_msg_id, group_title, group_title_flat, telegram_link,
                 season_display, info_messages, genres)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item_id,
                d.get("title"),
                d.get("category", ""),
                d.get("subcategory", ""),
                plugin_name,
                0,
                d.get("description", ""),
                d.get("year", ""),
                d.get("rating", 0),
                d.get("alt_titles", "[]"),
                "{}",
                f"/api/cover/{item_id}",
                d.get("telegram_msg_id"),
                d.get("group_title"),
                d.get("group_title_flat"),
                d.get("telegram_link"),
                d.get("season_display"),
                info,
                genres
            ))
            items_inserted += 1

        # Insertar episodios de items activos (mapeando item_id interno -> catálogo y derivando episode_key).
        # No se confía en el sync_status de plugin_episodes_export (puede venir mal marcado por el plugin);
        # se filtra por si el item resuelto está en los items activos.
        eps_inserted = 0
        for row in pc.execute("SELECT * FROM plugin_episodes_export"):
            ed = dict(row)
            resolved_item = resolve_item_id(ed.get("item_id", ""))
            if not resolved_item:
                continue
            if resolved_item not in active_item_ids:
                continue
            ep_key = ed.get("episode_key") or _derive_episode_key(ed.get("telegram_link"))
            c.execute("""
                INSERT OR REPLACE INTO item_episodes
                (item_id, episode_key, episode_number, season_number, title, duration,
                 telegram_msg_id, telegram_link, file_size, file_name, is_mkv)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                resolved_item,
                ep_key,
                ed.get("episode_number"),
                ed.get("season_number", 1),
                ed.get("title"),
                ed.get("duration"),
                ed.get("telegram_msg_id"),
                ed.get("telegram_link"),
                ed.get("file_size"),
                ed.get("file_name"),
                1 if (ed.get("file_name") or "").lower().endswith(".mkv") else 0
            ))
            eps_inserted += 1

        # Marcar has_mkv en unified_catalog si alguno de sus episodios es MKV.
        if active_item_ids:
            placeholders = ",".join("?" * len(active_item_ids))
            c.execute(f"""
                UPDATE unified_catalog SET has_mkv = 1
                WHERE item_id IN (
                    SELECT DISTINCT item_id FROM item_episodes
                    WHERE is_mkv = 1 AND item_id IN ({placeholders})
                )
            """, list(active_item_ids))
            c.execute(f"""
                UPDATE unified_catalog SET has_mkv = 0
                WHERE item_id IN ({placeholders})
                  AND item_id NOT IN (
                    SELECT DISTINCT item_id FROM item_episodes WHERE is_mkv = 1
                )
            """, list(active_item_ids))

        # Copiar catalog_assets del plugin (channel_id con fallback '' para esquemas viejos)
        try:
            for arow in pc.execute("SELECT * FROM catalog_assets").fetchall():
                ad = dict(arow)
                c.execute("""
                    INSERT OR IGNORE INTO catalog_assets
                    (channel_id, telegram_msg_id, asset_type, asset_index, image_blob, mime_type, file_size, width, height, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad.get("channel_id", ""),
                    ad.get("telegram_msg_id"),
                    ad.get("asset_type", "cover"),
                    ad.get("asset_index", 0),
                    ad.get("image_blob"),
                    ad.get("mime_type"),
                    ad.get("file_size"),
                    ad.get("width"),
                    ad.get("height"),
                    plugin_name
                ))
        except Exception as ae:
            print(f" [CATALOG] Error copiando assets de {plugin_name}: {ae}")

        pconn.close()
        conn.commit()
        conn.close()

        print(f" [CATALOG] Sync plugin {plugin_name}: {items_inserted} items, {eps_inserted} episodios")
        return {"success": True, "items": items_inserted, "episodes": eps_inserted}

    except Exception as e:
        conn.close()
        print(f" [CATALOG] Error sync plugin {plugin_name}: {e}")
        return {"success": False, "error": str(e)}


# Labels que cortan el valor de géneros: cualquier campo conocido tras los géneros
_GENRE_CUT_RE = re.compile(
    r"(?i)\s+(?:synopsis|sinopsis|descripci[oó]n|rating|votes|votos|episodes?|episodios?"
    r"|type|title|year|a[ñn]o|season|temporada|duration|duraci[oó]n|categor[ií]a?s?"
    r"|tags?)\s*[:=]"
)

# Correcciones de datos fuente corruptos: término -> valor limpio ('' = descartar)
_GENRE_NORMALIZE = {
    "senien": "seinen",
    "serie de tv": "",
}


def _split_genres_value(value):
    """Divide un valor crudo de géneros en términos limpios (minúsculas).

    - Corta en el primer label conocido (p.ej. 'Synopsis:'), que no forma parte de los géneros.
    - Separa por cualquier carácter que NO sea letra ni espacio (.,:;/- etc.).
    - Normaliza términos corruptos conocidos (typos, labels no-genéricos)."""
    cut = _GENRE_CUT_RE.split(value, maxsplit=1)[0]
    parts = re.split(r"[^\w\u00e0-\u02af ]+", cut)
    out = []
    for p in parts:
        p = p.strip().lower()
        if not p:
            continue
        p = _GENRE_NORMALIZE.get(p, p)
        if p and p not in out:
            out.append(p)
    return out


def _extract_genres(info_messages=None, metadata_json=None) -> str:
    """Extrae géneros normalizados (minúsculas, separados por coma) desde
    info_messages (texto con línea 'genres: a, b, c') y/o metadata_json.
    Devuelve una cadena 'a,b,c' o '' si no hay géneros."""
    genres = set()
    if isinstance(info_messages, str) and info_messages:
        for line in info_messages.splitlines():
            m = re.search(r'genres?\s*[:=]\s*(.+)', line, re.IGNORECASE)
            if m:
                genres.update(_split_genres_value(m.group(1)))
    if isinstance(metadata_json, str) and metadata_json:
        try:
            meta = json.loads(metadata_json)
        except Exception:
            meta = None
    elif isinstance(metadata_json, dict):
        meta = metadata_json
    else:
        meta = None
    if meta:
        for key in ("genres", "api_genres"):
            val = meta.get(key)
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    val = [x.strip() for x in val.split(',')]
            if isinstance(val, list):
                for g in val:
                    g = str(g).strip().lower()
                    if g:
                        genres.add(g)
    return ",".join(sorted(genres))


def _load_content_filter(conn, key):
    """Devuelve dict filtro o None si no existe. Capa ausente/vacía = todo permitido."""
    try:
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        d = json.loads(row["value"])
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _apply_content_layer(conn, where_clauses, params, key):
    """Añade cláusulas WHERE para una capa de filtro (plugins/categorías/subcategorías deshabilitadas)."""
    d = _load_content_filter(conn, key)
    if not d:
        return
    try:
        hidden_plugins = [p for p, v in d.get("plugins", {}).items() if not v]
        if hidden_plugins:
            ph = ",".join("?" for _ in hidden_plugins)
            where_clauses.append(f"COALESCE(source,'') NOT IN ({ph})")
            params.extend(hidden_plugins)
        hidden_cats = [cat for cat, v in d.get("categories", {}).items() if not v]
        if hidden_cats:
            placeholders = ",".join("?" for _ in hidden_cats)
            where_clauses.append(f"LOWER(category) NOT IN ({placeholders})")
            params.extend([x.lower() for x in hidden_cats])
        hidden_subs = [k for k, v in d.get("subcategories", {}).items() if not v]
        if hidden_subs:
            for key2 in hidden_subs:
                if "||" in key2:
                    cat_part, sub_part = key2.split("||", 1)
                    where_clauses.append("NOT (LOWER(category)=? AND LOWER(subcategory)=?)")
                    params.append(cat_part.lower())
                    params.append(sub_part.lower())
    except Exception:
        pass


def get_random_items(category=None, search=None, limit=200, filters=None, user_id=None, search_fields=None, year_from=None, year_to=None, exclude_genres=None):
    """Retorna items aleatorios del catálogo central."""
    conn = get_conn()
    c = conn.cursor()

    where_clauses = []
    params = []

    if category and category not in ('home', 'favorites', 'continue', 'completed'):
        where_clauses.append("LOWER(category) = ?")
        params.append(category.lower())

    # Filtrado de contenidos: 3 niveles
    if user_id:
        try:
            urow = conn.execute("SELECT role, profile_id FROM tvcat_users WHERE id=?", (user_id,)).fetchone()
            role = urow["role"] if urow else "user"
            profile_id = urow["profile_id"] if urow else None
        except Exception:
            role = "user"
            profile_id = None

        # Nivel 3: visibilidad (usuario, panel izquierdo)
        _apply_content_layer(conn, where_clauses, params, f"visibility_{user_id}")
        # Nivel 2: catálogo (usuario)
        _apply_content_layer(conn, where_clauses, params, f"available_{user_id}")
        # Nivel 1: acceso (perfil) — solo no-admin
        if role != "admin" and profile_id:
            _apply_content_layer(conn, where_clauses, params, f"access_{profile_id}")

    if search and len(search.strip()) >= 2:
        query = search.strip().lower()
        like_clauses = []

        # Determinar qué campos buscar
        fields_to_search = search_fields if search_fields is not None else ["title", "description", "alt_titles"]

        # Parsear comodines
        if '*' in query:
            parts = [p.strip() for p in query.split('*') if p.strip()]
            for part in parts:
                for field in fields_to_search:
                    like_clauses.append(f"LOWER({field}) LIKE ?")
                    params.append(f"%{part}%")
        else:
            for field in fields_to_search:
                like_clauses.append(f"LOWER({field}) LIKE ?")
                params.append(f"%{query}%")

        if like_clauses:
            where_clauses.append(f"({' OR '.join(like_clauses)})")
        else:
            # No hay campos para buscar, forzar resultados vacíos
            where_clauses.append("1=0")

    # Filtro por año
    if year_from:
        try:
            where_clauses.append("CAST(year AS INTEGER) >= ?")
            params.append(int(year_from))
        except: pass
    if year_to:
        try:
            where_clauses.append("CAST(year AS INTEGER) <= ?")
            params.append(int(year_to))
        except: pass

    # Filtro por géneros excluidos: un item se descarta si alguno de sus géneros
    # coincide con uno de los excluidos. `genres` está normalizado 'a,b,c' en minúsculas.
    if exclude_genres:
        for g in exclude_genres:
            if g == "__no_genre__":
                # Término virtual "Sin género": descarta títulos sin género asignado
                where_clauses.append("(COALESCE(genres,'') != '')")
                continue
            where_clauses.append(
                "(',' || COALESCE(genres,'') || ',' NOT LIKE ?)"
            )
            params.append(f"%,{g},%")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    c.execute(f"SELECT COUNT(*) FROM unified_catalog WHERE {where_sql}", params)
    total = c.fetchone()[0]

    c.execute(f"""
        SELECT * FROM unified_catalog
        WHERE id IN (
            SELECT MIN(id)
            FROM unified_catalog
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(group_title_flat, ''), id), COALESCE(subcategory, '')
        )
        ORDER BY RANDOM()
        LIMIT ?
    """, params + [limit])

    rows = c.fetchall()
    items = []
    for row in rows:
        d = dict(row)
        items.append({
            "item_id": d.get("item_id"),
            "title": d.get("title"),
            "category": d.get("category", ""),
            "subcategory": d.get("subcategory", ""),
            "source": d.get("source", ""),
            "description": d.get("description", ""),
            "year": d.get("year", ""),
            "rating": d.get("rating", 0),
            "cover_url": d.get("cover_url", ""),
            "has_mkv": d.get("has_mkv", 0),
        })

    conn.close()
    return {"items": items, "count": len(items)}
