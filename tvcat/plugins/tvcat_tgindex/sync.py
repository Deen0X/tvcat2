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
            info_messages       TEXT,
            is_collection       INTEGER DEFAULT 0,
            collection_raw      TEXT DEFAULT ''
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
    for _tbl in ["unified_catalog", "plugin_catalog_export"]:
        for _col, _typ in [("is_collection", "INTEGER DEFAULT 0"), ("collection_raw", "TEXT DEFAULT ''")]:
            try:
                c.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_typ}")
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
             sync_status, sync_timestamp, info_messages,
             is_collection, collection_raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            d.get("info_messages", ""),
            int(d.get("is_collection", 0) or 0),
            d.get("collection_raw", "")
        ))
        items_copied += 1

    # Copiar item_episodes → plugin_episodes_export
    eps_copied = 0
    episode_rows = c.execute("""
        SELECT e.*, u.sync_status as cat_source
        FROM item_episodes e
        LEFT JOIN unified_catalog u ON (e.item_id = u.id OR e.item_id = u.item_id)
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


def reconcile_availability(ordered_tags):
    """2026-09-04: orquestación en el PLUGIN (el core solo pone primitivas):
    wipe total de tgindex en central y copia solo de los tags habilitados, en orden.
    Sin diffs parciales: imposible dejar restos. Sin registry (ruta directa)."""
    from services.catalog_service import wipe_plugin_central, sync_plugin_db_copy
    w = wipe_plugin_central("tvcat_tgindex")
    if not w.get("success"):
        return w
    total_items, total_eps = 0, 0
    for tag in (ordered_tags or []):
        refresh_export_source(tag)
        try:
            conn = _get_plugin_conn()
            rows = conn.execute("SELECT item_id FROM unified_catalog WHERE source = ?", (tag,)).fetchall()
            conn.close()
        except Exception:
            continue
        ids = [r["item_id"] for r in rows if r["item_id"]]
        if not ids:
            continue
        res = sync_plugin_db_copy(PLUGIN_DB, "tvcat_tgindex", ids, True)
        total_items += res.get("items", 0)
        total_eps += res.get("episodes", 0)
    print(f" [TGIndex] Reconcile: {total_items} items, {total_eps} episodios ({len(ordered_tags or [])} sources)")
    return {"success": True, "items": total_items, "episodes": total_eps}


def has_parsed_rows(source_tag):
    """2026-09-04: True si el source tiene generados en plugin (evita saltar el
    parse tras un wipe: sin filas hay que parsear aunque no haya mensajes nuevos)."""
    try:
        conn = _get_plugin_conn()
        n = conn.execute("SELECT COUNT(*) FROM unified_catalog WHERE source = ?", (source_tag,)).fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return True


def refresh_export_source(source_tag):
    """2026-09-04: reconstruye las filas de export de un source desde
    unified/episodes (el export quedaba rancio tras wipes/regens y la copia a
    central insertaba 0). Mismo mapeo de columnas que sync()."""
    conn = _get_plugin_conn()
    c = conn.cursor()
    try:
        urows = [dict(r) for r in c.execute("SELECT * FROM unified_catalog WHERE source = ?", (source_tag,)).fetchall()]
        user_ids = [d["item_id"] for d in urows if d.get("item_id")]
        int_ids = [str(d["id"]) for d in urows]
        if user_ids:
            ph = ",".join("?" * len(user_ids))
            c.execute(f"DELETE FROM plugin_catalog_export WHERE item_id IN ({ph})", user_ids)
        if int_ids:
            phi = ",".join("?" * len(int_ids))
            c.execute(f"DELETE FROM plugin_episodes_export WHERE item_id IN ({phi})", int_ids)
        if user_ids:
            c.execute(f"DELETE FROM plugin_episodes_export WHERE item_id IN ({ph})", user_ids)
        for d in urows:
            st = d.get("sync_status") or "active"
            c.execute("""
                INSERT INTO plugin_catalog_export
                (item_id, title, category, subcategory, description, year, rating,
                 alt_titles, cover_url, telegram_link, telegram_msg_id,
                 group_title, group_title_flat, season_display,
                 source, source_channel_id, tg_user_id, client_type,
                 sync_status, sync_timestamp, extra_json, info_messages,
                 is_collection, collection_raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d.get("item_id"), d.get("title"), d.get("category", ""), d.get("subcategory", ""),
                d.get("description", ""), "", d.get("rating", 0),
                d.get("alt_titles", "[]"), "", d.get("telegram_link"), d.get("telegram_msg_id"),
                d.get("group_title"), d.get("group_title_flat"), d.get("season_display"),
                "tvcat_tgindex", d.get("source_channel_id", ""), d.get("tg_user_id"),
                d.get("client_type", "telethon"), st, 0, "{}",
                d.get("info_messages", ""),
                int(d.get("is_collection", 0) or 0), d.get("collection_raw", "")
            ))
        if int_ids:
            phi = ",".join("?" * len(int_ids))
            for erow in c.execute(f"""
                SELECT e.*, u.sync_status AS _pst FROM item_episodes e
                JOIN unified_catalog u ON (e.item_id = u.id OR e.item_id = u.item_id)
                WHERE u.source = ?""", (source_tag,)).fetchall():
                ed = dict(erow)
                c.execute("""
                    INSERT INTO plugin_episodes_export
                    (id, item_id, episode_number, season_number, title, duration,
                     telegram_msg_id, telegram_link, file_size, file_name, caption,
                     tg_user_id, client_type, sync_status, sync_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ed.get("id"), ed.get("item_id"), ed.get("episode_number"),
                    ed.get("season_number", 1), ed.get("title"), ed.get("duration"),
                    ed.get("telegram_msg_id"), ed.get("telegram_link"),
                    ed.get("file_size"), ed.get("file_name"), ed.get("caption"),
                    ed.get("tg_user_id"), ed.get("client_type", "telethon"),
                    ed.get("_pst") or "active", 0
                ))
        conn.commit()
        return len(urows)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _central_matches(item_ids, active):
    """Comprueba en central lo que el flag dice: todos presentes (active) o
    ninguno (deleted). Solo lectura."""
    try:
        from services.catalog_service import get_conn as _cc
        if not item_ids:
            return True
        cc = _cc()
        ph = ",".join("?" * len(item_ids))
        n = cc.execute(f"SELECT COUNT(*) FROM unified_catalog WHERE item_id IN ({ph})", list(item_ids)).fetchone()[0]
        cc.close()
        return (n >= len(item_ids)) if active else (n == 0)
    except Exception:
        return False


def apply_toggles_incremental(toggles):
    """Aplica toggles {cid: enabled} sin reconstrucción total (2026-09-04 F1):
    flags + export acotado por source + alta/baja incremental en central.
    toggles: dict {str(cid): 0/1}. Devuelve resumen por scan. Sin registry."""
    from services.catalog_service import sync_plugin_db_copy
    conn = _get_plugin_conn()
    c = conn.cursor()
    _ensure_export_tables(conn)
    out = {}
    for cid, enabled in (toggles or {}).items():
        try:
            cid = int(cid)
        except Exception:
            continue
        # 2026-09-04: un scan problemático no tumba el lote (antes 500 global).
        try:
            active = bool(enabled)
            status = "active" if active else "deleted"
            source_tag = f"scan_{cid}"
            # IDs del source (2026-09-04: el export guarda source='tvcat_tgindex'
            # siempre, así que se resuelve por unified; episodes usa ids enteros,
            # export usa item_ids USER-).
            _urows = c.execute("SELECT id, item_id FROM unified_catalog WHERE source = ?", (source_tag,)).fetchall()
            _int_ids = [str(r["id"]) for r in _urows]
            _user_ids = [r["item_id"] for r in _urows if r["item_id"]]
            # Skip solo si plugin Y central ya reflejan el estado (2026-09-04:
            # el flag en plugin no garantiza nada en central tras fallos parciales).
            try:
                _cur = c.execute("SELECT sync_status FROM unified_catalog WHERE source = ? LIMIT 1", (source_tag,)).fetchone()
                if _cur and _cur["sync_status"] == status:
                    _uids = [r["item_id"] for r in c.execute("SELECT item_id FROM unified_catalog WHERE source = ?", (source_tag,)).fetchall() if r["item_id"]]
                    if _central_matches(_uids, active):
                        out[cid] = {"enabled": active, "items": 0, "episodes": 0, "success": True, "skipped": True}
                        continue
            except Exception:
                pass
            try:
                sys_conn = _get_system_conn()
                sys_conn.execute("UPDATE tvcat_scanned_channels SET enabled = ? WHERE id = ?", (1 if active else 0, cid))
                sys_conn.commit()
                sys_conn.close()
            except Exception:
                pass
            c.execute("UPDATE unified_catalog SET sync_status = ? WHERE source = ?", (status, source_tag))
            _all_ids = _int_ids + _user_ids
            if _all_ids:
                _ph = ",".join("?" * len(_all_ids))
                c.execute(f"UPDATE item_episodes SET sync_status = ? WHERE item_id IN ({_ph})", [status] + _all_ids)
            if _user_ids:
                _ph2 = ",".join("?" * len(_user_ids))
                c.execute(f"UPDATE plugin_catalog_export SET sync_status = ? WHERE item_id IN ({_ph2})", [status] + _user_ids)
            if _int_ids:
                _ph3 = ",".join("?" * len(_int_ids))
                c.execute(f"UPDATE plugin_episodes_export SET sync_status = ? WHERE item_id IN ({_ph3})", [status] + _int_ids)
            conn.commit()
            refresh_export_source(source_tag)
            res = sync_plugin_db_copy(PLUGIN_DB, "tvcat_tgindex", _user_ids, active)
            if not res.get("success"):
                print(f" [TGIndex] toggle scan #{cid} central: {res.get('error')}")
            out[cid] = {"enabled": active, "items": res.get("items", 0), "episodes": res.get("episodes", 0),
                        "success": bool(res.get("success")), "error": res.get("error", "")}
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f" [TGIndex] toggle scan #{cid} error: {e}")
            out[cid] = {"enabled": bool(enabled), "items": 0, "episodes": 0, "success": False, "error": str(e)}
    conn.commit()
    conn.close()
    return out


def regenerate_source_items(source_tag):
    """2026-09-04: Regenerar = borra los GENERADOS de un source (plugin + export +
    central) para re-parsear desde caché. No toca raws ni Telegram. Devuelve nº items.
    Por listas explícitas (el export guarda source='tvcat_tgindex', nunca scan_N)."""
    from services.catalog_service import get_conn as _central_conn
    conn = _get_plugin_conn()
    c = conn.cursor()
    urows = c.execute("SELECT id, item_id FROM unified_catalog WHERE source = ?", (source_tag,)).fetchall()
    int_ids = [str(r["id"]) for r in urows]
    user_ids = [r["item_id"] for r in urows if r["item_id"]]
    if int_ids:
        phi = ",".join("?" * len(int_ids))
        c.execute(f"DELETE FROM item_episodes WHERE item_id IN ({phi})", int_ids)
        c.execute(f"DELETE FROM plugin_episodes_export WHERE item_id IN ({phi})", int_ids)
    if user_ids:
        phu = ",".join("?" * len(user_ids))
        c.execute(f"DELETE FROM plugin_episodes_export WHERE item_id IN ({phu})", user_ids)
        c.execute(f"DELETE FROM plugin_catalog_export WHERE item_id IN ({phu})", user_ids)
    c.execute("DELETE FROM unified_catalog WHERE source = ?", (source_tag,))
    conn.commit()
    conn.close()
    if user_ids:
        try:
            cc = _central_conn()
            ph = ",".join("?" * len(user_ids))
            cc.execute(f"DELETE FROM item_episodes WHERE item_id IN ({ph})", list(user_ids))
            cc.execute(f"DELETE FROM unified_catalog WHERE item_id IN ({ph})", list(user_ids))
            cc.commit()
            cc.close()
        except Exception as e:
            print(f" [TGIndex] regenerate central {source_tag}: {e}")
    return len(user_ids)


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
