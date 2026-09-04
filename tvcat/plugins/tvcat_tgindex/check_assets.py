import sqlite3
db = r"D:\Develop-AI\LegoBot\tvcat\plugins\tvcat_tgindex\data\tvcat.db"
conn = sqlite3.connect(db)
try:
    rows = conn.execute("SELECT channel_id, telegram_msg_id, asset_type, COUNT(*) FROM catalog_assets GROUP BY channel_id, telegram_msg_id, asset_type").fetchall()
    print("catalog_assets (channel, msg_id, type, count):")
    for r in rows:
        print(f"  channel={r[0]}, msg_id={r[1]}, type={r[2]}, count={r[3]}")
except Exception:
    rows = conn.execute("SELECT telegram_msg_id, asset_type, COUNT(*) FROM catalog_assets GROUP BY telegram_msg_id, asset_type").fetchall()
    print("catalog_assets (msg_id, type, count) [esquema viejo]:")
    for r in rows:
        print(f"  msg_id={r[0]}, type={r[1]}, count={r[2]}")
conn.close()
