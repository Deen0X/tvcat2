import sys, os, json, asyncio
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scraper.database import Database, Anime, get_telegram_creds
from telethon import TelegramClient
from telethon.sessions import StringSession

creds = get_telegram_creds()
if not creds or not creds.get("api_id") or not creds.get("api_hash"):
    print("[!] Credenciales Telegram no configuradas en la DB. Configúralas en Ajustes → Telegram.")
    sys.exit(1)

api_id = int(creds["api_id"])
api_hash = creds["api_hash"]
session_str = creds.get("session_string", "")
if not session_str:
    print("[!] Sesión Telegram no configurada en la DB.")
    sys.exit(1)

CHANNEL_ID = -1003953846405


def sanitize_tag(title):
    return "#" + re.sub(r'[^a-z0-9]', '', title.lower().replace(' ', ''))


def es_tag_valido(linea):
    return bool(re.match(r'^#[a-z0-9]+$', linea.strip()))


def extraer_emoji(texto):
    for ch in ['🟢', '🟡', '🔴', '⬆️']:
        if ch in texto:
            return ch
    return '🟢'


def parse_cover(texto):
    d = {}
    for line in texto.split('\n'):
        l = line.strip()
        if l.startswith('Title:'): d['title'] = l.replace('Title:','').strip()
        elif l.startswith('Episodes:'):
            try: d['episodes'] = int(l.replace('Episodes:','').strip())
            except: pass
        elif l.startswith('Type:'): d['type'] = l.replace('Type:','').strip()
        elif l.startswith('Year:'): d['year'] = l.replace('Year:','').strip()
        elif l.startswith('Rating:'): d['rating'] = l.replace('Rating:','').strip()
        elif l.startswith('Votes:'): d['votes'] = l.replace('Votes:','').strip()
        elif l.startswith('Genres:'): d['genres'] = l.replace('Genres:','').strip()
    return d


async def main():
    client = TelegramClient(StringSession(session_str), api_id=api_id, api_hash=api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("[!] No autorizado"); await client.disconnect(); return

    entity = await client.get_entity(CHANNEL_ID)
    print(f"[OK] Canal: {entity.title}")

    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "webscrapper.db")
    db = Database(db_path)

    stats = {'revisados': 0, 'covers': 0, 'ya_tag': 0, 'taggeados': 0, 'limpiados': 0, 'enviados_general': 0, 'db_actualizados': 0, 'db_nuevos': 0, 'errores': 0, 'sin_reply_to': 0, 'con_reply_to': 0, 'topic_id_ok': 0}

    offset_id = 0
    batch = 0

    while True:
        batch += 1
        msgs = await client.get_messages(entity, limit=100, offset_id=offset_id, reverse=True)
        if not msgs:
            break

        for msg in msgs:
            stats['revisados'] += 1
            if not msg.text or 'Title:' not in msg.text:
                continue

            stats['covers'] += 1

            rt = msg.reply_to
            if not rt:
                stats['sin_reply_to'] += 1
                continue
            stats['con_reply_to'] += 1

            topic_id = getattr(rt, 'reply_to_top_id', None) or getattr(rt, 'reply_to_msg_id', None)
            if not topic_id or topic_id == 1:
                # DEBUG: print attrs when topic_id is missing
                if stats['con_reply_to'] <= 3:
                    attrs = [x for x in dir(rt) if not x.startswith('_')]
                    print(f'DEBUG: MSG#{msg.id} reply_to attrs: {attrs}')
                    for a in ['reply_to_msg_id', 'topic_id', 'forum_topic', 'chat_id']:
                        print(f'  reply_to.{a}: {getattr(rt, a, "N/A")}')
                continue
            stats['topic_id_ok'] += 1

            root = await client.get_messages(entity, ids=[topic_id])
            if not root:
                continue
            root_text = root[0].message or ''
            emoji = extraer_emoji(root_text)

            cover_data = parse_cover(msg.text)
            title = cover_data.get('title', '')
            if not title:
                continue

            tag = sanitize_tag(title)

            # Limpiar tag hardcodeado
            texto_limpio = msg.text.replace('#titulosaneadosinespacios', '').strip()

            # Verificar si primera linea es tag valido
            primera = texto_limpio.split('\n')[0].strip() if texto_limpio else ''
            ya_tiene_tag = es_tag_valido(primera)

            if ya_tiene_tag and texto_limpio == msg.text:
                stats['ya_tag'] += 1
                continue

            if ya_tiene_tag and texto_limpio != msg.text:
                stats['limpiados'] += 1
            elif not ya_tiene_tag:
                stats['taggeados'] += 1

            # Editar mensaje
            try:
                if not ya_tiene_tag:
                    nuevo_texto = tag + '\n' + texto_limpio
                else:
                    nuevo_texto = texto_limpio
                await client.edit_message(entity, msg.id, text=nuevo_texto)
            except Exception as e:
                stats['errores'] += 1
                continue

            # Enviar al general
            tg_link = f"https://t.me/c/{CHANNEL_ID}/{topic_id}"
            try:
                general_text = f"{emoji} {tag} {title}\n{tg_link}"
                await client.send_message(entity, general_text)
                stats['enviados_general'] += 1
            except:
                stats['errores'] += 1

            # Actualizar BD solo si falta info
            try:
                session = db.get_session()
                existing = session.query(Anime).filter(Anime.telegram_topic_id == topic_id).first()
                if existing:
                    changed = False
                    if not existing.telegram_link:
                        existing.telegram_link = tg_link; changed = True
                    if not existing.cover_message_id:
                        existing.cover_message_id = msg.id; changed = True
                    if cover_data.get('year') and not existing.year:
                        existing.year = cover_data['year']; changed = True
                    if cover_data.get('episodes') and not existing.episodes:
                        existing.episodes = cover_data['episodes']; changed = True
                    if cover_data.get('type') and not existing.type:
                        existing.type = cover_data['type']; changed = True
                    if changed:
                        session.commit(); stats['db_actualizados'] += 1
                else:
                    new_a = Anime(title=title, telegram_link=tg_link, telegram_topic_id=topic_id,
                                  cover_message_id=msg.id, status='Airing')
                    if cover_data.get('year'): new_a.year = cover_data['year']
                    if cover_data.get('episodes'): new_a.episodes = cover_data['episodes']
                    if cover_data.get('type'): new_a.type = cover_data['type']
                    session.add(new_a)
                    session.commit()
                    stats['db_nuevos'] += 1
                session.close()
            except Exception:
                stats['errores'] += 1

            await asyncio.sleep(3)

        offset_id = msgs[-1].id

    print(f"\n{'='*60}")
    print(f"RESUMEN:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"{'='*60}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
