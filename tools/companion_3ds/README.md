# TVCat Companion 3DS (modo puente)

App homebrew (libctru) que se conecta al servidor TVCat, recibe ficheros de
juego (CIA) y los guarda en la microSD. La instalación la hace **FBI** después.

**Estado actual (scaffold)**: arranca red, lee config, envía heartbeat y hace
poll de `/commands`. Pendiente: parsear el JSON de commands y descargar los
ficheros por rangos a `download_dir` (está marcado como TODO en `main.c`).

## Requisitos de build

- [devkitARM](https://devkitpro.org/) + libctru (instalar vía `pacman -S 3ds-dev` en devkitPro).
- En Windows con WSL o MSYS2, o en Linux/macOS.

```bash
cd tvcat2/tools/companion_3ds
export DEVKITPRO=/opt/devkitpro
export DEVKITARM=$DEVKITPRO/devkitARM
make
```

Produce `tvcat_companion.3dsx`.

## Instalación en la 3DS

1. Copia `tvcat_companion.3dsx` a `sdmc:/3ds/`.
2. Ejecútalo desde el Homebrew Menu (CFW Luma3DS).

## Configuración

El companion lee `sdmc:/3ds/tvcat/config.cfg` (se autogenera con valores por
defecto en la primera ejecución). Edítalo con un editor en la SD:

```ini
server_url=http://192.168.1.10:8093
pairing_token=<token del panel Instalador de TVCat>
name=3DS de casa
id=3ds-xxxx
download_dir=sdmc:/3ds/tvcat/downloads
heartbeat_ms=10000
```

El `pairing_token` se obtiene en TVCat → botón flotante `¡⏩` (Instalador) →
**Generar QR/config**. El `id` debe ser único (una entrada por consola en TVCat).

## Flujo

1. TVCat genera un QR/config (server_url + pairing_token).
2. El companion empareja (POST /pair) y guarda el token.
3. Heartbeat cada `heartbeat_ms` → TVCat marca la consola online (LED verde).
4. Al encolar un título en TVCat, el companion lo recibe por /commands y lo
   descarga por rangos (Range) a `download_dir`.
5. El usuario abre **FBI** → instalación por CIA desde `download_dir`.

## Pendiente (segunda iteración)

- Parsear el JSON de `/commands` y descargar los ficheros (resume por Range + verificación SHA-256).
- Entrada de config por pantalla / QR con la cámara.
- Instalación directa (reutilizando lógica de instaladores open-source).
