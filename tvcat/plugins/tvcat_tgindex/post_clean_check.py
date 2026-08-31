import sqlite3, json

print("=== VERIFICACION POST-CLEAN ===")
print()

tg_db = r"D:/Develop-AI/LegoBot/tvcat/plugins/tvcat_tgindex/data/tvcat.db"
sys_db = r"D:/Develop-AI/LegoBot/tvcat/data/tvcat.db"

# 1. Tablas en DB tgindex
print("--- Tablas en tvcat_tgindex/data/tvcat.db ---")
conn_tg = sqlite3.connect(tg_db)
conn_tg.row_factory = sqlite3.Row

for table in ["unified_catalog", "item_episodes", "telegram_scan"]:
    try:
        cnt = conn_tg.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
        print(f"  {table}: {cnt} filas")
        if cnt > 0:
            if table == "unified_catalog":
                rows = conn_tg.execute("SELECT id, title, telegram_link, cover_id, source FROM unified_catalog LIMIT 5").fetchall()
                for r in rows:
                    d = dict(r)
                    print(f"    id={d['id']}, title={d['title'][:50]}, link={d['telegram_link']}, cover={d['cover_id']}, source={d.get('source','NULL')}")
            elif table == "item_episodes":
                rows = conn_tg.execute("SELECT id, item_id, title FROM item_episodes LIMIT 5").fetchall()
                for r in rows:
                    d = dict(r)
                    print(f"    id={d['id']}, item_id={d['item_id']}, title={d['title'][:50]}")
            elif table == "telegram_scan":
                # Ver canales y cantidad de messages
                rows = conn_tg.execute("SELECT channel_id, topic_id, COUNT(*) as cnt FROM telegram_scan GROUP BY channel_id, topic_id LIMIT 10").fetchall()
                for r in rows:
                    d = dict(r)
                    print(f"    channel={d['channel_id']}, topic={d['topic_id']}, msgs={d['cnt']}")
    except Exception as e:
        print(f"  {table}: {e}")

print()

# 2. Tablas en DB sistema
print("--- Tablas en tvcat/data/tvcat.db (sistema/config) ---")
conn_sys = sqlite3.connect(sys_db)
conn_sys.row_factory = sqlite3.Row

# Verificar si tvcat_scanned_channels existe
try:
    cnt = conn_sys.execute("SELECT COUNT(*) FROM tvcat_scanned_channels").fetchone()[0]
    print(f"  tvcat_scanned_channels: {cnt} filas")
    rows = conn_sys.execute("SELECT id, display_name, channel_id, topology_type FROM tvcat_scanned_channels").fetchall()
    for r in rows:
        print(f"    id={r['id']}, name={r['display_name']}, channel_id={r['channel_id']}, topo={r['topology_type']}")
except Exception as e:
    print(f"  tvcat_scanned_channels: {e}")

print()

# 3. Status de clean
print("=== ESTADO RESULTANTE ===")
uc = conn_tg.execute("SELECT COUNT(*) FROM unified_catalog").fetchone()[0]
ie = conn_tg.execute("SELECT COUNT(*) FROM item_episodes").fetchone()[0]
ts = conn_tg.execute("SELECT COUNT(*) FROM telegram_scan").fetchone()[0]

if uc == 0 and ie == 0 and ts == 0:
    print("  OK - Todos los datos del canal fueron limpiados")
else:
    print(f"  WARNING - Quedan datos: catalog={uc}, episodes={ie}, scan={ts}")
    print("  Verificar por:")
    if uc > 0:
        remaining_links = conn_tg.execute("SELECT telegram_link FROM unified_catalog LIMIT 3").fetchall()
        remaining = dict(conn_tg.execute("SELECT COUNT(*) FROM unified_catalog WHERE telegram_link LIKE '%3953846405%'").fetchone())[0] if uc > 0 else 0
        print(f"    Items relacionados con canal: {remaining}")
        for r in remaining_links:
            print(f"    - {r['telegram_link']}")
    if ie > 0:
        remaining_eps = conn_tg.execute("SELECT COUNT(*) FROM item_episodes WHERE item_id IN (SELECT id FROM unified_catalog WHERE telegram_link LIKE '%3953846405%')").fetchone()[0] if uc > 0 else 0
        print(f"    Episodios relacionados con canal: {remaining_eps}")
    if ts > 0:
        remaining_scan = conn_tg.execute("SELECT COUNT(*) FROM telegram_scan WHERE channel_id IN ('3953846405', '-1003953846405', '1003953846405')").fetchone()[0]
        print(f"    Mensajes restantes del canal: {remaining_scan}")

print()
print("Listo para RESCAN si todo esta limpio OK")
conn_tg.close()
conn_sys.close()
