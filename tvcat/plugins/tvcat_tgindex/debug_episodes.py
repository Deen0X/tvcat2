import sqlite3
db = r"D:\Develop-AI\LegoBot\tvcat\plugins\tvcat_tgindex\data\tvcat.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

# Episodios totales y rango
rows = conn.execute("SELECT COUNT(*) as cnt, MIN(id) as min_id, MAX(id) as max_id FROM item_episodes").fetchone()
print(f"item_episodes: {rows['cnt']} total, IDs: {rows['min_id']} - {rows['max_id']}")

# Buscar el 48653
r = conn.execute("SELECT id FROM item_episodes WHERE id = 48653").fetchone()
print(f"episode_id 48653 existe: {r is not None}")

# Items con sus episodios
rows = conn.execute("""
    SELECT u.id, u.title, u.telegram_link, COUNT(e.id) as eps
    FROM unified_catalog u
    LEFT JOIN item_episodes e ON e.item_id = u.id
    WHERE u.telegram_link LIKE '%3953846405%'
    GROUP BY u.id
    ORDER BY u.id DESC LIMIT 5
""").fetchall()
print()
print("Últimos 5 items y sus episodios:")
for r in rows:
    print(f"  item.id={r['id']}, title={r['title'][:50]}, link={r['telegram_link']}, episodios={r['eps']}")

# Episode IDs para un item específico
r = conn.execute("SELECT id FROM unified_catalog WHERE title LIKE '%Mushoku%'").fetchone()
if r:
    item_id = r['id']
    print(f"\nItem Mushoku: id={item_id}")
    eps = conn.execute("SELECT id, item_id, episode_number, telegram_msg_id FROM item_episodes WHERE item_id = ? ORDER BY episode_number", (item_id,)).fetchall()
    for e in eps:
        print(f"  ep.id={e['id']}, item_id={e['item_id']}, ep#={e['episode_number']}, msg_id={e['telegram_msg_id']}")
conn.close()
