"""
SoulScrapper - Generador de String Session para Pyrogram
=========================================================
Este script genera el String Session de Pyrogram necesario para que
SoulScrapper pueda subir archivos >1.9GB usando Pyrogram.

Al ejecutarlo, en la seccion "Dispositivos activos" de tu cuenta de Telegram
aparecera el nombre "SoulScrapper Pyrogram", para que puedas identificar
claramente que sesion fue creada por este script.

INSTRUCCIONES:
1. Ve a https://my.telegram.org e inicia sesion con tu numero de telefono.
2. En "API development tools", crea una app y copia el API_ID y API_HASH.
3. Asegurate de tener Pyrogram instalado: pip install pyrogram tgcrypto
4. Ejecuta: python generate_session_pyrogram.py
5. Sigue las instrucciones (numero de telefono, codigo SMS, 2FA si aplica).
6. Copia el String Session generado al campo "Userbot / Pyrogram" en la configuracion.

IMPORTANTE: Nunca compartas tu String Session con nadie.
"""

import asyncio
import sys

try:
    from pyrogram import Client
except ImportError:
    print("\n[ERROR] Pyrogram no esta instalado.")
    print("Instalalo con: pip install pyrogram tgcrypto")
    sys.exit(1)

APP_NAME = "SoulScrapper Pyrogram"
BANNER = """
╔══════════════════════════════════════════════════════╗
║    SoulScrapper — Generador de Sesion Pyrogram       ║
║                                                      ║
║  El dispositivo aparecera en Telegram como:          ║
║  > SoulScrapper Pyrogram                             ║
╚══════════════════════════════════════════════════════╝
"""


async def generate():
    print(BANNER)
    print("Necesitas tu API_ID y API_HASH de https://my.telegram.org\n")

    api_id_str = input("Introduce tu API_ID (solo numeros): ").strip()
    api_hash = input("Introduce tu API_HASH: ").strip()

    if not api_id_str.isdigit():
        print("\n[ERROR] El API_ID debe ser un numero entero.")
        sys.exit(1)

    api_id = int(api_id_str)

    print(f"\nConectando con Telegram como '{APP_NAME}'...")
    print("Telegram enviara un codigo a tu app o por SMS.\n")

    client = Client(APP_NAME, api_id=api_id, api_hash=api_hash)

    await client.start()

    me = await client.get_me()
    username = me.username or f"{me.first_name or ''} {me.last_name or ''}".strip()
    session_string = await client.export_session_string()

    await client.stop()

    print("\n" + "=" * 56)
    print(f"  Sesion generada para: @{username or me.id}")
    print("=" * 56)
    print("\n  STRING SESSION (copia todo el texto de abajo):\n")
    print(f"  {session_string}")
    print("\n" + "=" * 56)
    print("\n  Pega este String Session en:")
    print("  Configuracion -> Userbot / Pyrogram -> Session String (Pyrogram)")
    print("=" * 56 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(generate())
    except KeyboardInterrupt:
        print("\n\nOperacion cancelada por el usuario.")
        sys.exit(0)
