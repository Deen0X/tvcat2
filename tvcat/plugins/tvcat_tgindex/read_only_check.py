import sqlite3, json

tg_db = r"D:/Develop-AI/LegoBot/tvcat/plugins/tvcat_tgindex/data/tvcat.db"
sys_db = r"D:/Develop-AI/LegoBot/tvcat/data/tvcat.db"

print("=== LECTURA DIRECTA (SIN ESCRIBIR NADA) ===")
print()

# DB tgindex
conn_tg = sqlite3.connect(tg_db)
conn_tg.row_factory = sqlite3.Row

# Tablitas en unificada
try:
    uc = conn_tg.execute("SELECT COUNT(*) FROM unified_catalog").fetchone()[0]
    print(f"unified_catalog: {uc} filas")
    if uc > 0:
        rows = conn_tg.execute("SELECT * FROM unified_catalog LIMIT 5").fetchall()
        for r in rows:
            d = dict(r)
            print(f"    id={d['id']}, title={d['title'][:60]}, link={d['telegram_link']}, cover={d['cover_id']}, subcat={d['subcategory'][:40] if d['subcategory'] else 'NULL'}, source={d.get('source','NULL')}")
except Exception as e:
    print(f"unified_catalog: {e}")

print()

try:
    ie = conn_tg.execute("SELECT COUNT(*) FROM item_episodes").fetchone()[0]
    print(f"item_episodes: {ie} filas")
    if ie > 0:
        # Ver item_id de los episodios
        rows = conn_tg.execute("SELECT id, item_id, title, telegram_link FROM item_episodes LIMIT 5").fetchall()
        for r in rows:
            d = dict(r)
            print(f"    ep_id={d['id']}, item_id={d['item_id']}, title={d['title'][:40]}, link={d['telegram_link']}")
except Exception as e:
    print(f"item_episodes: {e}")

print()

try:
    ts = conn_tg.execute("SELECT COUNT(*) FROM telegram_scan").fetchone()[0]
    print(f"telegram_scan: {ts} filas")
    if ts > 0:
        # Ver los canales en telegram_scan
        rows = conn_tg.execute("SELECT channel_id, topic_id, COUNT(*) as cnt, MIN(msg_id), MAX(msg_id) FROM telegram_scan GROUP BY channel_id, topic_id").fetchall()
        for r in rows:
            print(f"    channel={r['channel_id']}, topic={r['topic_id']}, msgs={r['cnt']}, msg_id={r['MIN(msg_id)']}-{r['MAX(msg_id)']}")
except Exception as e:
    print(f"telegram_scan: {e}")

print()

# DB sistema
print("--- tvcat/data/tvcat.db (tabla de configuración) ---")
conn_sys = sqlite3.connect(sys_db)
conn_sys.row_factory = sqlite3.Row
rows = conn_sys.execute("SELECT id, display_name, channel_id, topology_type, last_scanned_msg_id FROM tvcat_scanned_channels").fetchall()
for r in rows:
    d = dict(r)
    print(f"    id={d['id']}, name={d['display_name']}, channel_id={d['channel_id']}, topo={d['topology_type']}, last_scan={d['last_scanned_msg_id']}")

conn_tg.close()
conn_sys.close()
