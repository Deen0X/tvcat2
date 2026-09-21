"""
TVCat2 - Generador de String Session (Telethon)
================================================
Genera el String Session de Telethon para las sesiones userbot de TVCat2.

Al ejecutarlo, en "Dispositivos activos" de tu cuenta de Telegram aparece
el nombre "TVCat2", para identificar la sesion creada por TVCat2.

USO:
  Manual:   python generate_session_telethon.py
  Con args: python generate_session_telethon.py --api-id 12345 --api-hash abc --phone +34123456789
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
    import telethon
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("\n[ERROR] Telethon no esta instalado.")
    print("Instalalo con: pip install telethon")
    input("\nPulsa ENTER para cerrar...")
    sys.exit(1)

APP_NAME = "TVCat2"
BANNER = """
+======================================================+
|         TVCat2  -  Generador de Sesion (Telethon)     |
|                                                      |
|  El dispositivo aparecera en Telegram como:          |
|  > TVCat2                                            |
+======================================================+
"""


def parse_args():
    p = argparse.ArgumentParser(description="TVCat2: genera String Session de Telethon")
    p.add_argument("--api-id", dest="api_id", default="",
                   help="API ID numerico de https://my.telegram.org")
    p.add_argument("--api-hash", dest="api_hash", default="",
                   help="API Hash de https://my.telegram.org")
    p.add_argument("--phone", dest="phone", default="",
                   help="Telefono con prefijo internacional (ej. +34123456789)")
    p.add_argument("--verbose", "-v", dest="verbose", action="store_true",
                   help="Muestra traza detallada (conexion, send_code, errores)")
    p.add_argument("--resend", dest="resend", type=int, default=0,
                   help="Reintentos de send_code para forzar escalado a SMS "
                        "(si el codigo App no llega). Cada reintento invalida el anterior.")
    p.add_argument("--resend-wait", dest="resend_wait", type=int, default=120,
                   help="Segundos de espera entre reintentos (default 120)")
    p.add_argument("--sms", dest="sms", action="store_true",
                   help="Forzar envio por SMS (ResendCode inmediato si Telegram "
                        "responde via App). El force_sms de telethon esta "
                        "deprecado y no funciona: se hace a mano.")
    p.add_argument("--qr", dest="qr", action="store_true",
                   help="Login por QR (sin codigos): escanea con el movil en "
                        "Ajustes > Dispositivos > Vincular dispositivo.")
    return p.parse_args()


async def _qr_flow(client):
    """Login por QR: no necesita telefono ni codigos. Muestra el QR en
    ASCII + lo guarda/abre como PNG para escanearlo con el móvil."""
    import io as _io
    import os as _os
    import qrcode as _qr
    print("[QR] client.connect() ...")
    await client.connect()
    while True:
        qr = await client.qr_login()
        buf = _io.StringIO()
        _q = _qr.QRCode(border=1)
        _q.add_data(qr.url)
        _q.make(fit=True)
        _q.print_ascii(out=buf, invert=True)
        print("")
        print(buf.getvalue())
        try:
            img = _qr.make(qr.url)
            path = _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), "qr_login.png")
            img.save(path)
            print(f"  QR guardado en: {path} (intentando abrirlo)")
            if _os.name == "nt":
                try:
                    _os.startfile(path)  # noqa: PGH121
                except Exception:
                    pass
        except Exception as e:
            print(f"  [aviso] no se pudo generar el PNG: {e}")
        print("  Escanea con el móvil: Telegram > Ajustes > Dispositivos > "
              "Vincular dispositivo. (Ctrl+C cancela; si caduca se genera otro.)")
        try:
            if await qr.wait():
                print("[QR] aceptado en el móvil.")
                return
        except Exception as e:
            print(f"[QR] {type(e).__name__}: generando otro QR...")
            continue
        print("[QR] expirado: generando otro...")


async def generate(args):
    print(BANNER)
    print("Necesitas tu API_ID y API_HASH de https://my.telegram.org\n")

    api_id_str = (args.api_id or "").strip()
    if not api_id_str:
        api_id_str = input("Introduce tu API_ID (solo numeros): ").strip()
    api_hash = (args.api_hash or "").strip()
    if not api_hash:
        api_hash = input("Introduce tu API_HASH: ").strip()
    phone = (args.phone or "").strip()
    if not phone and not args.qr:
        phone = input("Introduce tu telefono (+34...): ").strip()

    if not api_id_str.isdigit():
        print("\n[ERROR] El API_ID debe ser un numero entero.")
        sys.exit(1)

    api_id = int(api_id_str)

    via = "args" if (args.api_id and args.api_hash) else "teclado"
    if args.verbose:
        print(f"[V] telethon {telethon.__version__} | api_id={api_id} "
              f"api_hash={api_hash[:3]}***{api_hash[-2:]} phone={phone or '(QR)'} (vía {via})")

    print(f"\nConectando con Telegram como '{APP_NAME}'...")
    if not args.qr:
        print("Telegram enviara un codigo a tu app o por SMS.\n")

    client = TelegramClient(
        StringSession(),
        api_id,
        api_hash,
        device_model=APP_NAME,
        system_version="TVCat2",
        app_version="2.0",
        lang_code="es",
    )

    if args.qr:
        await _qr_flow(client)
    # StringSession: sin fichero en disco, todo en memoria.
    # --sms usa también el flujo manual (start() no puede forzarlo: el
    # force_sms de telethon está deprecado y no hace nada).
    elif args.verbose or args.sms:
        # Flujo manual == start() pero mostrando cada paso: si el SMS no
        # llega, aquí se ve si send_code se envió, por qué vía (app/sms),
        # el timeout de reintento o el FloodWait.
        from telethon.errors import (
            SessionPasswordNeededError, FloodWaitError,
            SendCodeUnavailableError)
        import time as _time

        def _ask(prompt):
            try:
                return input(prompt).strip()
            except EOFError:
                print("[V] sin entrada disponible (stdin cerrado).")
                return ""
        print("[V] client.connect() ...")
        await client.connect()
        print("[V] conectado. is_user_authorized() ...")
        if not await client.is_user_authorized():
            max_tries = 1 + max(0, int(args.resend or 0))
            sent = None
            for attempt in range(1, max_tries + 1):
                if attempt > 1:
                    print(f"[V] esperando {args.resend_wait}s antes de reintentar...")
                    _time.sleep(args.resend_wait)
                print(f"[V] send_code_request({phone}) intento {attempt}/{max_tries} ...")
                try:
                    sent = await client.send_code_request(phone)
                except FloodWaitError as e:
                    print(f"[V] FloodWait: esperar {e.seconds}s (Telegram limita reintentos).")
                    _time.sleep(e.seconds + 5)
                    sent = await client.send_code_request(phone)
                except SendCodeUnavailableError:
                    # Telegram agotó las vías por ahora y pide OTRO reenvío
                    # (el siguiente suele caer en SMS). No es fatal... salvo
                    # que ya no queden intentos: entonces es cooldown de la
                    # cuenta (reintentar solo lo alarga) → salir limpio.
                    print("[V] SendCodeUnavailable: Telegram pide reenviar de nuevo "
                          "(vía agotada temporalmente, el siguiente suele ser SMS).")
                    if attempt >= max_tries:
                        print("")
                        print("[!] Telegram no tiene vías disponibles para este número ahora mismo.")
                        print("    Esto es un bloqueo temporal de la cuenta, NO un fallo del script.")
                        print("    1) NO lo intentes más durante 1-2 horas (cada intento lo alarga).")
                        print("    2) En el móvil: Ajustes > Dispositivos > Terminar las demás sesiones.")
                        print("    3) Después, UN solo intento desde UNA máquina:")
                        print("       generate_session_telethon.py --api-id ... --api-hash ... --phone ... --sms -v")
                        return
                    continue
                if args.sms and "App" in str(sent.type):
                    # Forzado SMS a mano: ResendCode inmediato tras el App.
                    from telethon import functions as _tfn
                    print("[V] --sms: ResendCodeRequest inmediato para forzar SMS ...")
                    try:
                        sent = await client(_tfn.auth.ResendCodeRequest(
                            phone, sent.phone_code_hash))
                    except SendCodeUnavailableError:
                        print("[V] SendCodeUnavailable en forzado SMS: se reintenta el ciclo.")
                        if attempt >= max_tries:
                            print("")
                            print("[!] Telegram no tiene vías disponibles para este número ahora mismo.")
                            print("    Bloqueo temporal de la cuenta: no insistir 1-2 horas,")
                            print("    terminar otras sesiones (Ajustes > Dispositivos) y")
                            print("    reintentar una sola vez con --sms -v.")
                            return
                        continue
                print(f"[V] send OK: type={sent.type} next={getattr(sent, 'next_type', None)} "
                      f"timeout={getattr(sent, 'timeout', None)} hash={'sí' if sent.phone_code_hash else 'NO'}")
                if "App" in str(sent.type):
                    print("[V] NOTA: el codigo va a la app Telegram (chat 'Telegram'), no por SMS.")
                if attempt < max_tries:
                    print("[V] Si no llega, pulsa ENTER sin codigo para reintentar "
                          "(invalida este codigo y Telegram escala hacia SMS).")
                code = _ask("Introduce el codigo recibido: ")
                if code:
                    break
                print("[V] sin codigo: reintentando (el anterior queda invalidado).")
            print("[V] sign_in() ...")
            try:
                await client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
            except SessionPasswordNeededError:
                print("[V] 2FA requerida.")
                pw = _ask("Introduce la contrasena 2FA: ")
                await client.sign_in(password=pw)
            print("[V] autorizado OK.")
        else:
            print("[V] sesion ya autorizada (inusualmente rápido).")
    else:
        if phone:
            await client.start(phone=phone)
        else:
            await client.start()

    me = await client.get_me()
    username = me.username or f"{me.first_name or ''} {me.last_name or ''}".strip()
    session_string = client.session.save()

    await client.disconnect()

    print("\n" + "=" * 56)
    print(f"  Sesion generada para: @{username or me.id}")
    print("=" * 56)
    print("\n  STRING SESSION (copia SOLO la linea entre marcadores):\n")
    print("---BEGIN SESSION---")
    print(session_string)
    print("---END SESSION---")
    print("\n" + "=" * 56)
    print("\n  Pegalo en TVCat2:")
    print("  Configuracion -> Userbot -> Anadir Session Strings -> Telethon")
    print("=" * 56 + "\n")


if __name__ == "__main__":
    args = parse_args()
    if args.verbose:
        logging.basicConfig(format="[%(levelname)s %(name)s] %(message)s",
                            level=logging.DEBUG)
        # Ruido de asyncio en DEBUG: se deja en INFO.
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
