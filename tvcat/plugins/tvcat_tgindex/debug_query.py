import sqlite3

conn = sqlite3.connect(r'D:/Develop-AI/LegoBot/tvcat/plugins/tvcat_tgindex/data/tgindex.db')
conn.row_factory = sqlite3.Row

# List tables
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("=== TABLES ===")
for t in tables:
    count = conn.execute(f'SELECT COUNT(*) as cnt FROM "{t["name"]}"').fetchone()['cnt']
    print(f'  {t["name"]}: {count} rows')

# List columns in telegram_scan
print("\n=== telegram_scan schema ===")
cols = conn.execute("PRAGMA table_info(telegram_scan)").fetchall()
for c in cols:
    print(f'  {c["name"]} ({c["type"]})')

# List columns in unified_catalog
print("\n=== unified_catalog schema ===")
cols = conn.execute("PRAGMA table_info(unified_catalog)").fetchall()
for c in cols:
    print(f'  {c["name"]} ({c["type"]})')

# List columns in item_episodes
print("\n=== item_episodes schema ===")
cols = conn.execute("PRAGMA table_info(item_episodes)").fetchall()
for c in cols:
    print(f'  {c["name"]} ({c["type"]})')

# Counts per table
print("\n=== Row counts ===")
for t in tables:
    count = conn.execute(f'SELECT COUNT(*) as cnt FROM "{t["name"]}"').fetchone()['cnt']
    print(f'  {t["name"]}: {count}')

conn.close()
