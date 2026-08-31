# TVCat Companion 3DS

Companion homebrew para Nintendo 3DS (CFW) que recibe ficheros desde TVCat y los guarda en la microSD (modo puente). La instalación final se hace con FBI.

## Requisitos

- **devkitPro** con **devkitARM** (compilador ARM11) + **libctru** + **citro2d/citro3d**.
- [quirc](https://github.com/dlbeer/quirc) para decodificación QR (copiar a `include/` y `source/`).
- 3DS con CFW (Luma) y Homebrew Launcher.

## Compilar

```bash
export DEVKITPRO=D:/devkitPro
export DEVKITARM=$DEVKITPRO/devkitARM
make
```

Produce `tvcat_companion.3dsx` (y `.cia` opcional).

## Uso

1. En TVCat: Configuración → Plugins → Instalador 3DS → **Generar nuevo código**.
2. En la consola, lanza `tvcat_companion.3dsx` / `tvcat_companion.cia`:
   - **A**: escanea el QR con la cámara. El QR contiene la URL corta `http://servidor:puerto/3ds?token=CÓDIGO`; el companion la parsea (server_url + token) y hace el handshake.
   - **B**: entrada manual. Escribe la URL corta o el código. El companion extrae servidor + token.
3. Handshake: `POST /api/installer/3ds/pair` con `{token, console_name, console_hwid}`.
4. Loop: heartbeat + poll de comandos + descarga por rangos a `sdmc:/tvcat/`.

### Instalar el companion en la 3DS

1. Compila: `make` → genera `tvcat_companion.3dsx` (y `.elf`, `.smdh`).
2. Copia el `.3dsx` a `tvcat/plugins/tvcat_installer_3ds/static/companion.3dsx`.
3. En la config del plugin 3DS (servidor) se genera un QR que apunta a
   `/api/installer/3ds/cia` (sirve el fichero).
4. En la 3DS:
   - **.3dsx**: copia `companion.3dsx` a `sdmc:/3ds/tvcat_companion/` y ejecuta desde el Homebrew Launcher (Luma). No necesita instalación.
   - **.cia**: genera el .cia con makerom (si está disponible) y usa FBI → Remote Install → Scan QR.

### Toolchain

- devkitPro (msys2) en `C:\devkitPro`.
- Paquetes: `devkitarm-rules`, `libctru`, `citro2d`, `citro3d` (vía dkp-pacman / pacman).
- `makerom` para .cia: descargar de 3DSGuy/Project_CTR releases, copiar a `C:\devkitPro\tools\bin\`.

### Emparejamiento (sin navegador)

El companion NO abre ninguna página. La URL corta `/3ds?token=X` es solo
una cadena compacta que transporta `servidor + token`. El companion la
obtiene del QR o del campo de texto, la parsea, y hace el `POST` de
handshake directamente contra la API.

## Protocolo (resumen)

| Acción | Endpoint | Método |
|--------|----------|--------|
| Pair (handshake) | `/api/installer/3ds/pair` | POST `{token, console_name, console_hwid}` |
| Heartbeat | `/api/installer/3ds/{id}/heartbeat` | POST `{token, state, progress, speed, free}` |
| Poll comandos | `/api/installer/3ds/{id}/commands?token=` | GET → `[{cmd:download, url, filename, size, hash}]` |
| Descarga | URL del comando con `Range: bytes=X-Y` | GET |

## TODO

- [ ] Escáner QR funcional (quirc + cam:u).
- [ ] GUI completa (citro2d): barra de progreso, lista de estados, teclado para manual.
- [ ] Verificación SHA-256 al finalizar descarga.
- [ ] Paquete `.cia` firmable (3dsx solo en Luma).
