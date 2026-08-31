"""
TVCat TGIndex - Generador de String Session
============================================
Este script genera el String Session de Telethon necesario para que el
plugin TVCat_TGIndex pueda acceder a tus canales personales de Telegram.

Al ejecutarlo, en la sección "Dispositivos activos" de tu cuenta de Telegram
aparecerá el nombre "TVCat_TGIndex", para que puedas identificar claramente
qué sesión fue creada por este script.

INSTRUCCIONES:
1. Ve a https://my.telegram.org e inicia sesión con tu número de teléfono.
2. En "API development tools", crea una app y copia el API_ID y API_HASH.
3. Ejecuta este script: python generate_session.py
4. Sigue las instrucciones (número de teléfono, código SMS, 2FA si aplica).
5. Copia el String Session generado al apartado de configuración del plugin.

IMPORTANTE: Nunca compartas tu String Session con nadie. TVCat solo lo
almacena en local en config/tvcat_user_config.json de tu servidor.
"""

import asyncio
import sys

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("\n[ERROR] Telethon no está instalado.")
    print("Instálalo con: pip install telethon")
    sys.exit(1)

APP_NAME = "TVCat_TGIndex"
BANNER = """
╔══════════════════════════════════════════════════════╗
║         TVCat TGIndex — Generador de Sesión          ║
║                                                      ║
║  El dispositivo aparecerá en Telegram como:          ║
║  > TVCat_TGIndex                                     ║
╚══════════════════════════════════════════════════════╝
"""

async def generate():
    print(BANNER)
    print("Necesitas tu API_ID y API_HASH de https://my.telegram.org\n")

    api_id_str = input("Introduce tu API_ID (solo números): ").strip()
    api_hash = input("Introduce tu API_HASH: ").strip()

    if not api_id_str.isdigit():
        print("\n[ERROR] El API_ID debe ser un número entero.")
        sys.exit(1)

    api_id = int(api_id_str)

    print(f"\nConectando con Telegram como '{APP_NAME}'...")
    print("Telegram enviará un código a tu app o por SMS.\n")

    client = TelegramClient(
        StringSession(),
        api_id,
        api_hash,
        device_model=APP_NAME,
        app_version="1.0",
        system_version="TVCat Gateway",
        lang_code="es",
    )

    await client.start()

    me = await client.get_me()
    username = me.username or f"{me.first_name} {me.last_name or ''}".strip()
    session_string = client.session.save()

    await client.disconnect()

    print("\n" + "═" * 56)
    print(f"  ✅ Sesión generada para: @{username}")
    print("═" * 56)
    print("\n  STRING SESSION (copia todo el texto de abajo):\n")
    print(f"  {session_string}")
    print("\n" + "═" * 56)
    print("\n  Pega este String Session en:")
    print("  Ajustes → Plugins → TGIndex → ⚙️ Configurar")
    print("═" * 56 + "\n")

    # Guardar también en fichero local por comodidad
    out_file = "session_output.txt"
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"Usuario: @{username}\n")
            f.write(f"API_ID: {api_id}\n")
            f.write(f"API_HASH: {api_hash}\n")
            f.write(f"Session String:\n{session_string}\n")
        print(f"  💾 También guardado en: {out_file}")
        print("  (Borra este fichero después de configurar el plugin)\n")
    except Exception as e:
        print(f"  [Aviso] No se pudo guardar el fichero de salida: {e}\n")


if __name__ == "__main__":
    try:
        asyncio.run(generate())
    except KeyboardInterrupt:
        print("\n\nOperación cancelada por el usuario.")
        sys.exit(0)
