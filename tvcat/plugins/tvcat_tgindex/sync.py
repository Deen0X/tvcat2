"""
TVCat 2 - TGIndex Sync Module
Puente entre las tablas internas (unified_catalog) y las tablas de exportación
(plugin_catalog_export, plugin_episodes_export) que el core lee para cachear.
"""

import os
import json
import sqlite3
import re

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DB = os.path.join(PLUGIN_DIR, "data", "tvcat.db")
BASE_DIR = os.path.abspath(os.path.join(PLUGIN_DIR, "..", ".."))
SYSTEM_DB = os.path.join(BASE_DIR, "data", "tvcat.db")


def _get_plugin_conn():
    os.makedirs(os.path.dirname(PLUGIN_DB), exist_ok=True)
    conn = sqlite3.connect(PLUGIN_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _get_system_conn():
    os.makedirs(os.path.dirname(SYSTEM_DB), exist_ok=True)
    conn = sqlite3.connect(SYSTEM_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_export_tables(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS plugin_catalog_export (
            item_id             TEXT PRIMARY KEY,
            title               TEXT NOT NULL,
            category            TEXT,
            subcategory         TEXT,
            description         TEXT,
            year                TEXT,
            rating              REAL DEFAULT 0,
            alt_titles          TEXT DEFAULT '[]',
            cover_url           TEXT,
            telegram_link       TEXT,
            telegram_msg_id     INTEGER,
            group_title         TEXT,
            group_title_flat    TEXT,
            season_display      TEXT,
            source              TEXT NOT NULL,
            source_channel_id   TEXT,
            tg_user_id          INTEGER,
            client_type         TEXT DEFAULT 'telethon',
            sync_status         TEXT DEFAULT 'active' CHECK(sync_status IN ('active', 'deleted')),
            sync_timestamp      INTEGER DEFAULT (unixepoch()),
            extra_json          TEXT DEFAULT '{}',
            info_messages       TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS plugin_episodes_export (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id         TEXT NOT NULL,
            episode_number  INTEGER,
            season_number   INTEGER DEFAULT 1,
            title           TEXT,
            duration        REAL,
            telegram_msg_id INTEGER,
            telegram_link   TEXT,
            file_size       INTEGER,
            file_name       TEXT,
            caption         TEXT,
            tg_user_id      INTEGER,
            client_type     TEXT DEFAULT 'telethon',
            sync_status     TEXT DEFAULT 'active' CHECK(sync_status IN ('active', 'deleted')),
            sync_timestamp  INTEGER DEFAULT (unixepoch()),
            FOREIGN KEY(item_id) REFERENCES plugin_catalog_export(item_id) ON DELETE CASCADE
        )
    """)
    # Migrar columnas si unified_catalog no tiene las nuevas
    for tbl in ["unified_catalog", "item_episodes"]:
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN sync_status TEXT DEFAULT 'active'")
        except:
            pass
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN sync_timestamp INTEGER DEFAULT (unixepoch())")
        except:
            pass
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN source_channel_id TEXT")
        except:
            pass
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN client_type TEXT DEFAULT 'telethon'")
        except:
            pass
    try:
        c.execute("ALTER TABLE plugin_catalog_export ADD COLUMN info_messages TEXT")
    except:
        pass
    conn.commit()


def _get_enabled_channels():
    """Retorna un set de (scan_id, channel_id) para canales habilitados."""
    sys_conn = _get_system_conn()
    rows = sys_conn.execute(
        "SELECT id, channel_id FROM tvcat_scanned_channels WHERE enabled = 1"
    ).fetchall()
    sys_conn.close()
    enabled = {}
    for r in rows:
        enabled[f"scan_{r['id']}"] = r["channel_id"]
    return enabled


def reconcile_plugin_sync_status():
    """Marca unified_catalog/item_episodes del plugin con sync_status='active'|'deleted'
    según el estado enabled de su scan config. El catálogo central solo lee registros 'active'."""
    conn = _get_plugin_conn()
    c = conn.cursor()
    enabled_channels = _get_enabled_channels()
    for row in c.execute("SELECT DISTINCT source FROM unified_catalog WHERE source IS NOT NULL AND source != ''"):
        src = row["source"]
        status = "active" if src in enabled_channels else "deleted"
        c.execute("UPDATE unified_catalog SET sync_status=? WHERE source=?", (status, src))
        c.execute(
            "UPDATE item_episodes SET sync_status=? WHERE item_id IN (SELECT id FROM unified_catalog WHERE source=?)",
            (status, src)
        )
    conn.commit()
    conn.close()


def sync():
    """
    Sincroniza las tablas internas (unified_catalog) con las tablas de exportación
    (plugin_catalog_export, plugin_episodes_export).
    Llamado por el core en cada ciclo de auto-refresh y bajo demanda.
    """
    conn = _get_plugin_conn()
    c = conn.cursor()
    _ensure_export_tables(conn)

    # Reconciliar sync_status del catálogo del plugin según canales activos
    reconcile_plugin_sync_status()

    enabled_channels = _get_enabled_channels()

    # Limpiar export tables para refresco completo
    c.execute("DELETE FROM plugin_catalog_export")
    c.execute("DELETE FROM plugin_episodes_export")

    # Copiar unified_catalog → plugin_catalog_export
    items_copied = 0
    catalog_rows = c.execute("SELECT * FROM unified_catalog").fetchall()
    for row in catalog_rows:
        d = dict(row)
        source_tag = d.get("source") or ""
        channel_id = enabled_channels.get(source_tag, "")
        sync_status = "active" if source_tag in enabled_channels else "deleted"

        c.execute("""
            INSERT INTO plugin_catalog_export
            (item_id, title, category, subcategory, description, year, rating,
             alt_titles, cover_url, telegram_link, telegram_msg_id,
             group_title, group_title_flat, season_display,
             source, source_channel_id, tg_user_id, client_type,
             sync_status, sync_timestamp, info_messages)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d.get("item_id"),
            d.get("title"),
            d.get("category", ""),
            d.get("subcategory", ""),
            d.get("description", ""),
            d.get("year", ""),
            d.get("rating", 0),
            d.get("alt_titles", "[]"),
            d.get("cover_url", ""),
            d.get("telegram_link"),
            d.get("telegram_msg_id"),
            d.get("group_title"),
            d.get("group_title_flat"),
            d.get("season_display"),
            "tvcat_tgindex",
            channel_id,
            d.get("tg_user_id"),
            d.get("client_type", "telethon"),
            sync_status,
            int(d.get("sync_timestamp", 0)) or 0,
            d.get("info_messages", "")
        ))
        items_copied += 1

    # Copiar item_episodes → plugin_episodes_export
    eps_copied = 0
    episode_rows = c.execute("""
        SELECT e.*, c.source as cat_source
        FROM item_episodes e
        LEFT JOIN unified_catalog c ON e.item_id = c.id
    """).fetchall()
    insert_cursor = conn.cursor()
    for row in episode_rows:
        ed = dict(row)
        source_tag = ed.get("cat_source") or ""
        sync_status = "active" if source_tag in enabled_channels else "deleted"

        cat_row = insert_cursor.execute(
            "SELECT item_id FROM plugin_catalog_export WHERE item_id = ?",
            (ed.get("item_id"),)
        ).fetchone()

        insert_cursor.execute("""
            INSERT INTO plugin_episodes_export
            (id, item_id, episode_number, season_number, title, duration,
             telegram_msg_id, telegram_link, file_size, file_name, caption,
             tg_user_id, client_type, sync_status, sync_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ed.get("id"),
            ed.get("item_id"),
            ed.get("episode_number"),
            ed.get("season_number", 1),
            ed.get("title"),
            ed.get("duration"),
            ed.get("telegram_msg_id"),
            ed.get("telegram_link"),
            ed.get("file_size"),
            ed.get("file_name"),
            ed.get("caption"),
            ed.get("tg_user_id"),
            ed.get("client_type", "telethon"),
            sync_status,
            int(ed.get("sync_timestamp", 0)) or 0
        ))
        eps_copied += 1

    conn.commit()
    conn.close()
    print(f" [TGINDEX SYNC] Exportación: {items_copied} items, {eps_copied} episodios "
          f"({len(enabled_channels)} canales activos)")
    return items_copied, eps_copied


def refresh_central_cache(context: str = "refresh"):
    """Regenera las tablas de exportación del plugin y avisa al catálogo central
    para que copie los registros activos. El plugin NUNCA escribe en la central:
    solo expone sus export tables y delega la copia al core."""
    try:
        sync()
    except Exception as e:
        print(f" [TGIndex] Aviso: sync de export ({context}) falló: {e}")
        return False
    try:
        from tvcat.gateway import _plugin_loader
        from services.catalog_service import sync_plugin_cache
        sync_plugin_cache(_plugin_loader, "tvcat_tgindex")
        return True
    except Exception as e:
        print(f" [TGIndex] Aviso: refresh caché central ({context}) falló: {e}")
        return False


def check_for_updates() -> bool:
    """
    Verifica si hay cambios desde la última sincronización.
    Retorna True si hay datos nuevos en unified_catalog.
    """
    conn = _get_plugin_conn()
    last = conn.execute(
        "SELECT COALESCE(MAX(sync_timestamp), 0) FROM plugin_catalog_export"
    ).fetchone()[0] or 0
    latest = conn.execute(
        "SELECT COALESCE(MAX(strftime('%s', created_at)), 0) FROM unified_catalog"
    ).fetchone()[0] or 0
    conn.close()
    return int(latest) > int(last)
