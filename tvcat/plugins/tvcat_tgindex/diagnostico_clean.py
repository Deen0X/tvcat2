import sqlite3

db_system = r"D:\Develop-AI\LegoBot\tvcat\data\tvcat.db"
db_tgindex = r"D:\Develop-AI\LegoBot\tvcat\plugins\tvcat_tgindex\data\tvcat.db"

conn_sys = sqlite3.connect(db_system)
conn_sys.row_factory = sqlite3.Row

print("=== Canales en tvcat_scanned_channels (DB del sistema) ===")
rows = conn_sys.execute("SELECT id, display_name, channel_id, topology_type FROM tvcat_scanned_channels").fetchall()
for r in rows:
    print(f"  id={r['id']}, name={r['display_name']}, channel_id={r['channel_id']}, topo={r['topology_type']}")
conn_sys.close()

print()

conn_tg = sqlite3.connect(db_tgindex)
conn_tg.row_factory = sqlite3.Row

print("=== Sources únicos en unified_catalog (DB del plugin) ===")
rows = conn_tg.execute("SELECT DISTINCT source FROM unified_catalog").fetchall()
for r in rows:
    print(f"  source='{r['source']}'")
conn_tg.close()
