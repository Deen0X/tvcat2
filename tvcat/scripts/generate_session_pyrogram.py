"""
TVCat2 - Generador de String Session (Pyrogram)
================================================
Genera el String Session de Pyrogram para las sesiones userbot de TVCat2.

Al ejecutarlo, en "Dispositivos activos" de tu cuenta de Telegram aparece
el nombre "TVCat2", para identificar la sesion creada por TVCat2.

USO:
  Manual:   python generate_session_pyrogram.py
  Con args: python generate_session_pyrogram.py --api-id 12345 --api-hash abc --phone +34123456789
  (los parametros que falten se piden por teclado)

INSTRUCCIONES:
1. Ve a https://my.telegram.org e inicia sesion con tu numero de telefono.
2. En "API development tools", crea una app y copia el API_ID y API_HASH.
3. Ejecuta este script y sigue las instrucciones (codigo SMS, 2FA si aplica).
4. Copia el String Session (entre BEGIN/END) al modal "Anadir Session
   Strings" de TVCat2 (Configuracion -> Userbot).

IMPORTANTE: Nunca compartas tu String Session con nadie.
"""

import argparse
import asyncio
import logging
import sys

try:
    import pyrogram
    from pyrogram import Client
except ImportError:
    print("\n[ERROR] Pyrogram no esta instalado.")
    print("Instalalo con: pip install pyrogram tgcrypto")
    input("\nPulsa ENTER para cerrar...")
    sys.exit(1)

APP_NAME = "TVCat2"
BANNER = """
+======================================================+
|         TVCat2  -  Generador de Sesion (Pyrogram)     |
|                                                      |
|  El dispositivo aparecera en Telegram como:          |
|  > TVCat2                                            |
+======================================================+
"""


def parse_args():
    p = argparse.ArgumentParser(description="TVCat2: genera String Session de Pyrogram")
    p.add_argument("--api-id", dest="api_id", default="",
                   help="API ID numerico de https://my.telegram.org")
    p.add_argument("--api-hash", dest="api_hash", default="",
                   help="API Hash de https://my.telegram.org")
    p.add_argument("--phone", dest="phone", default="",
                   help="Telefono con prefijo internacional (ej. +34123456789)")
    p.add_argument("--verbose", "-v", dest="verbose", action="store_true",
                   help="Muestra traza detallada (conexion, send_code, errores)")
    return p.parse_args()


async def generate(args):
    print(BANNER)
    print("Necesitas tu API_ID y API_HASH de https://my.telegram.org\n")

    api_id_str = (args.api_id or "").strip()
    if not api_id_str:
        api_id_str = input("Introduce tu API_ID (solo numeros): ").strip()
    api_hash = (args.api_hash or "").strip()
    if not api_hash:
        api_hash = input("Introduce tu API_HASH: ").strip()
    phone = (args.phone or "").strip() or None
    if not phone:
        phone = input("Introduce tu telefono (+34...): ").strip() or None

    if not api_id_str.isdigit():
        print("\n[ERROR] El API_ID debe ser un numero entero.")
        sys.exit(1)

    api_id = int(api_id_str)

    via = "args" if (args.api_id and args.api_hash) else "teclado"
    if args.verbose:
        print(f"[V] pyrogram {pyrogram.__version__} | api_id={api_id} "
              f"api_hash={api_hash[:3]}***{api_hash[-2:]} phone={phone} (vía {via})")

    print(f"\nConectando con Telegram como '{APP_NAME}'...")
    print("Telegram enviara un codigo a tu app o por SMS.\n")

    # in_memory=True: sin fichero .session residual en disco.
    client = Client(
        name="tvcat2_gen_pyro",
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
        device_model=APP_NAME,
        system_version="TVCat2",
        app_version="2.0",
        lang_code="es",
        in_memory=True,
    )

    if args.verbose:
        print("[V] client.start() ... (mira el log [pyrogram] para send_code/FloodWait)")
    await client.start()
    if args.verbose:
        print("[V] start OK: autorizado.")

    me = await client.get_me()
    username = me.username or f"{me.first_name or ''} {me.last_name or ''}".strip()
    session_string = await client.export_session_string()

    await client.stop()

    print("\n" + "=" * 56)
    print(f"  Sesion generada para: @{username or me.id}")
    print("=" * 56)
    print("\n  STRING SESSION (copia SOLO la linea entre marcadores):\n")
    print("---BEGIN SESSION---")
    print(session_string)
    print("---END SESSION---")
    print("\n" + "=" * 56)
    print("\n  Pegalo en TVCat2:")
    print("  Configuracion -> Userbot -> Anadir Session Strings -> Pyrogram")
    print("=" * 56 + "\n")


if __name__ == "__main__":
    args = parse_args()
    if args.verbose:
        logging.basicConfig(format="[%(levelname)s %(name)s] %(message)s",
                            level=logging.DEBUG)
        logging.getLogger("asyncio").setLevel(logging.INFO)
    try:
        asyncio.run(generate(args))
    except KeyboardInterrupt:
        print("\n\nOperacion cancelada por el usuario.")
    except Exception:
        print("\n[ERROR] Fallo la generacion:")
        import traceback
        traceback.print_exc()
    finally:
        input("\nPulsa ENTER para cerrar...")
