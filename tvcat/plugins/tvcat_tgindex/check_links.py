import sqlite3

db_path = r"D:/Develop-AI/LegoBot/tvcat/plugins/tvcat_tgindex/data/tvcat.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print(" a la base de datos... verificando enlaces en unified_catalog\n")

rows = conn.execute("SELECT id, title, telegram_link, source FROM unified_catalog LIMIT 20").fetchall()
for r in rows:
    print(f"ID: {r['id']} | Source: {r['source']} | Link: {r['telegram_link']}")

conn.close()
