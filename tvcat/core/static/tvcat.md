# TVCat2 — Telegram Visual Catalog 2

Servidor de catálogo multimedia y visor integrado multiplataforma.
Indexa, organiza y reproduce contenidos directamente desde Telegram.
Rediseño del proyecto original TVCat.

Al usar credenciales de usuario, el proyecto es código abierto para que
cualquiera pueda examinarlo y asegurarse de que esas credenciales solo se
usan para la implementación de la aplicación.

## Qué hace

- **Catálogo local**: tus canales y grupos de Telegram convertidos en un
  videoclub personal navegable, con covers, temporadas y episodios.
- **Streaming directo**: reproduce sin intermediarios, en PC, móvil y SmartTV.
- **Covers enriquecidos**: edita el cover de un título y, si el mensaje es
  tuyo, actualízalo en Telegram; si no, guárdalo en local.
- **Sistema de plugins**: funcionalidades sin modificar el core (orígenes,
  renderizado, reproductores, acciones de hero, copias entre canales).
- **Cache Relay**: sube escaneos para descargarlos después y ahorrar tiempo.
- **Colecciones**: agrupa títulos en colecciones propias.
- **Multi-perfil y control parental**: perfiles, filtros de acceso, ocultos.

## Topologías (cómo se organizan los canales)

- **Tipo 1**: canal o grupo sin topics. Títulos secuenciales en el chat.
- **Tipo 2**: grupo con topics temáticos. Cada topic es un tema con varios
  títulos secuenciales dentro.
- **Tipo 3** (recomendada): un topic por título.
- **Tipo 4**: descubre títulos en canales desordenados por similitud de nombres.

## Reproductores

Player TVCat (y versión TV), Player Pro y Pro 2 (caché local, experimental),
Player HLS / HLS SmartTV / HLS TV / HLS SEQ (stream adaptativo, casi
cualquier formato: AVI, MOV, MKV, MP4…).

## Requisitos

Funciona con un **userbot**: un cliente de Telegram con tus credenciales de
usuario real (Telegram exige identificar el programa con `api_id` + `api_hash`,
que cada usuario crea gratis en https://my.telegram.org/auth). Sin esas
claves, Telegram rechaza la conexión.

**Este software NO distribuye canales ni contenidos**: solo muestra aquello a
lo que tu usuario ya tiene acceso. Tu `session string` se guarda cifrado en
la base de datos local y nunca sale de tu servidor.

## Ejecución

- **Docker** (recomendado en Linux): `docker compose up -d --build`,
  en `http://localhost:8098`.
- **Linux nativo**: Python 3.10+, `pip install -r tvcat/requirements.txt`,
  `python tvcat/gateway.py`.
- **Windows**: `TVCatLauncher.exe` (bandeja del sistema, .NET 8).

## Datos

- `tvcat/data/tvcat.db`: sistema (usuarios, perfiles, historial, canales).
- `tvcat/plugins/tvcat_tgindex/data/tvcat.db`: catálogo indexado.
- `config/`: configuraciones y tokens. Haz copia de `tvcat/data/` y
  `config/` antes de actualizar.

Proyecto en desarrollo: muchas opciones son experimentales.
Código: https://github.com/Deen0X/tvcat2
