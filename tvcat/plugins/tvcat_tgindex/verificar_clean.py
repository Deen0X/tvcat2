import sqlite3

db = r"D:\Develop-AI\LegoBot\tvcat\plugins\tvcat_tgindex\data\tvcat.db"
conn = sqlite3.connect(db)

for t in ["unified_catalog", "item_episodes", "telegram_scan"]:
    cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"{t}: {cnt} filas")

conn.close()
