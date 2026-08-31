import sqlite3, json

print("=== TABLAS EXISTENTES ===")
conn = sqlite3.connect(r'D:/Develop-AI/LegoBot/tvcat/plugins/tvcat_tgindex/data/tgindex.db')
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for r in rows:
    cnt = conn.execute(f"SELECT COUNT(*) FROM {r[0]}").fetchone()[0]
    print(f"  {r[0]}: {cnt} filas")

print("\n=== CANALES EN CONFIG ===")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, display_name, channel_id, topology_type FROM tvcat_scanned_channels").fetchall()
for r in rows:
    print(f"  id={r['id']}, name={r['display_name']}, channel_id={r['channel_id']}, topo={r['topology_type']}")

print("\n=== ITEMS UNIFIED (anteriores a clean) ===")
rows = conn.execute("SELECT id, title, telegram_link, category, subcategory, cover_id, source FROM unified_catalog").fetchall()
for r in rows:
    d = dict(r)
    print(f"  id={d['id']}, title={d['title'][:60]}, link={d['telegram_link']}, cover={d['cover_id']}, source={d['source']}, sub={d['subcategory'][:50] if d['subcategory'] else 'NULL'}")

print("\n=== EPISODIOS (anteriores a clean) ===")
rows = conn.execute("SELECT id, item_id, title, telegram_link FROM item_episodes").fetchall()
for r in rows:
    print(f"  id={r['id']}, item_id={r['item_id']}, title={r['title'][:50]}, link={r['telegram_link']}")

print("\n=== TELEGRAM_SCAN por channel_id ===")
rows = conn.execute("SELECT channel_id, COUNT(*) as cnt, MIN(msg_id) as min_id, MAX(msg_id) as max_id, topic_id FROM telegram_scan GROUP BY channel_id, topic_id ORDER BY channel_id, topic_id").fetchall()
for r in rows:
    print(f"  channel={r['channel_id']}, topic={r['topic_id']}, count={r['cnt']}, msg_id range={r['min_id']}-{r['max_id']}")

print("\n=== MENSajes en tema 2559 (si existen) ===")
cids = ('3953846405','-1003953846405','1003953846405')
ph = ','.join(['?' for _ in cids])
rows = conn.execute(f"SELECT msg_id, message FROM telegram_scan WHERE channel_id IN ({ph}) AND topic_id=2559 ORDER BY msg_id", cids).fetchall()
for r in rows:
    m = json.loads(r["message"])
    media_type = (m.get('media') or {}).get('_', '')
    msg_text = (m.get('message') or '')[:60]
    print(f"  msg_id={r['msg_id']}, media={media_type}, text={msg_text[:60]}")
