<img width="128" height="128" alt="image" src="https://github.com/user-attachments/assets/98d5877f-8f37-4c92-a07c-3cf55f1316c1" />

# TVCat2 - Telegram Visual Catalog 2

TVCat2 es un servidor de catálogo multimedia y visor integrado multiplataforma. Permite indexar, organizar y reproducir contenidos directamente desde Telegram. Es un rediseño del proyecto original.

Al ser un sistema que utiliza credenciales de usuario, he decidido publicar este proyecto como código abierto, para que cualquier apueda examinarlo y asegurarse que no hay ningún uso de estas credenciales que no sean la implementación de la aplicación.


## Features

Se han incluído sistema de plugins para añadir funcionalidades que no impliquen modificar el core.

Sistema de Cache Relay, que permite subir escaneos de grupos para que luego sea posible descargarlos y con esto ahorrar tiempo en los escaneos.

Topologías: Ahora se compone de 4 tipos.

- Topología 1: Canal o grupo sin topics. Todos los títulos están secuenciales en el mismo chat.
- Topología 2: Grupo con Topics temáticos. Cada topic corresponde a un tema y dentro existen varios títulos secuenciales (como topología 1, pero en topics)
- Topología 3: Grupo con topics por título. Este es la topología recomendada. Cada topic corresponde a un título.
- Topología 4: Sirve para descubrir títulos en canales que no están ordeandos. Se basa por similitud de nombres.


### Plugins Disponibles:

<img width="693" height="1035" alt="image" src="https://github.com/user-attachments/assets/2e1e8bc6-1318-42a8-a6b1-e45603766b02" />

#### Orígenes

Plugins que generan mensajes de origen que serán utilizados en el catálogo.

- TGIndex : Plugin para configurar Scan Items que luego se transformarán en items que se mostrarán en el catálogo. Estos scan items son rangos de mensajes de grupos o canales donde el usuario telegram tiene acceso.


#### Catágolo

Plugins que afectan a la visualización del catálogo

- Efecto Blur : Hace que cada elemento muestre su cover con un efecto blur/difuminado.


#### Hero Page

<img width="807" height="269" alt="image" src="https://github.com/user-attachments/assets/e7013e5a-2720-4043-a9c4-c05e57010b32" />


La Hero Page es la pantalla de detalles que aparece cuando seleccionamos un título. En esta pantalla se pueden configurar botones de acción en función del contenido que se está mostrando, que se determina básicamente por su categoría y subcategoría (que se configuran en TGIndex o el plugin de orígen utilizado)

- Vídeo Players : Actualmente existen varios reproductores de vídeo. Se está desarollando paralelamente cada uno de estos para diferentes usos. entre los existentes tenemos:
   - Reproductor TVCat :  Player original del player. Soporta MP4 y MKV (este último depende de la codificación y algunas características mas)
   - Reproductor TVCat TV : Versión de Reproductor TVCat con soporte para smartTV antiguas (ES5)
   - Player Pro (Caché Local) : Versión experimental que intenta descargar en el caché local del navegador el tíutlo.
   - Player Pro 2 (Descarga Completa) : Versión alternativa de Player Pro (experimental)
   - Player HLS : Genera un stream m3u8 a partir de un contenido. Este player es capaz de reproducir casi cualquier tipo de vídeo (Avi, Mov, MKV, MP4, etc)
   - Player HLS SmartTV : Versión de Player HLS diseñado para SmartTV con soporte de Chrome.
   - Player HLS TV : Versión del Player HLS con soporte para SmartTV Antiguas (WebKit)
   - Player HLS SEQ : Nueva versión del Player HLS. En desarrollo.

- Comportamientos Generales
   - Mostrar en Telegram : Abre el mensaje original en telegram
   - Enriquecedor : Permite editar el cover del título y, si el mensaje original es del usuario, actualizar el mensaje en telegram, o guardar en local estas modificaciones

- Gestión de Contenidos / Bibliotecas
   - TGHirayi : Plugin que permite organizar una biblioteca personal a partir de los títulos del catálogo.


---

## Pre-Requisitos

Para que el programa funcione, utiliza un Userbot, esto es un **bot de telegram que se conecta con las credenciales de un usuario real**.

¿Por que se ha desarrollado de esta forma?

**Telegram no deja que un programa entre a tus canales con solo tu teléfono: exige identificar qué programa llama. Esa identidad son dos claves: api_id + api_hash.

TVCat lee tus canales privados (covers, vídeos, mensajes) con tu usuario, como si fueras tú desde otra app. Sin esas claves, Telegram rechaza la conexión.

Cada usuario crea las suyas (gratis, 1 minuto) para no depender de las de otro: si miles usaran la misma, Telegram la bloquearía por abuso y caería el servicio para todos.**

Por este motivo, cada usuario debe crear una aplicación telegram para poder configurar su propio servidor TVCat.

Con esto podrás acceder a los grupos y canales que como usuario tienes acceso. 

Nota: **Este software NO distribuye canales ni contenidos**. Soilo visualiza los canales y contenidos que el propio usuario tiene acceso.

Para conectar el Userbot, necesitas un API_ID y API_HASH, necesarios para dar identidad al bot dentro del econsistema de telegram, y que los consigues en la página oficial https://my.telegram.org/auth

Aquí ponemos nuestro teléfono, en formato internación +34123456789

En Telegram recibiremos un token que debemos copiar para introducir en la siguiente página

<img width="906" height="514" alt="{68E5BFCB-D0EA-4BB1-8B53-FEF5E27E88D5}" src="https://github.com/user-attachments/assets/008804ad-2424-4987-b6a3-9c3c408677c6" />

a continuación tenemos que elgir **API development tools**, y después de esto, se abrirá una pantalla para crear una aplicación en Telegram, la cual nos dará los datos que necesitamos añadir en la aplicación.

<img width="1156" height="716" alt="image" src="https://github.com/user-attachments/assets/efe579c4-6e8c-4588-8b6c-ee9bd0446609" />

Podemos rellenar con datos como:

- App title: TVCat
- Short name: tvcatclient
- URL: https://localhost
- Platform: Desktop
- Description: Telegram Visual Catalog.

Le damos a Create Application y ya nos muestra la pantalla con los datos api_id y api_hash que son los que nos interesan.

<img width="867" height="273" alt="image" src="https://github.com/user-attachments/assets/0ea53094-3c93-4016-8cbb-d3e1d42bf344" />

guardamos estos 2 datos en un lugar seguro (o podemos volver a venir a esta página para consultarlos nuevamente)

En la aplicación, necesitaremos estos datos para introducirlos en la Configuración/Credenciales

<img width="719" height="762" alt="{780C063B-464B-4161-93DB-CFE527AC1653}" src="https://github.com/user-attachments/assets/7dbfd60c-2efc-4dcf-a3aa-19256ceaec0d" />


ponemos el api_id, api_hash y teléfono en los campos, y le damos a guardar.


Finalmente necesitas un Session String. este string es muy sensible y es la principal razón por la que he decidido publicar el código completo en python, por que así es claramente analizable y estar seguros de que el programa no realiza ningún tipo de envío de estos datos a ninguna parte. Al ser datos tan sensibles el usuario que utilice el programa debe tener la confianza en que no hay vías alternativas donde se pueda estar sustrayendo esta información.

El programa genera los string de conexión (vía telegram oficial, el usuario debe proporcionar la clave que le llegará por telegram) y no muestra nunca el string de conexión. lo guarda cifrado en la base de datos.

Por mi parte he hecho todo lo posible por guardar lo mejor posible esta información y que no quede fácilmente accesible.


## 1. Ejecución en Docker (Recomendado para Linux)

Si deseas correr la aplicación dentro de un contenedor Docker pero manteniendo los archivos en tu directorio físico (para facilitar las copias de seguridad de la base de datos, configuraciones y actualizaciones automáticas), se incluye soporte para Docker Compose.

### Requisitos:
* Tener instalado **Docker** y **Docker Compose**.

### Pasos para iniciar:

1. Levanta el contenedor en segundo plano:
   ```bash
   docker compose up -d --build
   ```
2. La aplicación estará accesible en:
   ```
   http://localhost:8098
   ```

El archivo `docker-compose.yml` monta la carpeta física actual dentro del contenedor, por lo que cualquier base de datos que se genere en `tvcat/data/` o configuraciones en `config/` se guardarán directamente en tu almacenamiento físico local.

---

## 2. Ejecución Nativa en Linux

Si deseas ejecutar TVCat de forma directa en tu servidor Linux sin Docker, realiza los siguientes pasos:

### Requisitos del Sistema:
* **Python 3.10** o superior.
* **unrar** (versión oficial non-free para dar soporte completo a archivos `.rar` y `.cbr` en el visor de cómics).
* **ffmpeg** (opcional, para manipulación de vídeo si se añade soporte en el futuro).

### Instalación de dependencias del sistema (Debian/Ubuntu):
```bash
sudo apt-get update
sudo apt-get install -y unrar ffmpeg
```

### Instalación de dependencias de Python y ejecución:
1. Instala los requerimientos:
   ```bash
   pip install -r tvcat/requirements.txt
   ```
2. Inicia la aplicación:
   ```bash
   python tvcat/gateway.py
   ```

---

## 3. Ejecución en Windows

### Requisitos:
* **.NET 8.0 Desktop Runtime** instalado (para usar el Launcher de bandeja de sistema).
* **WinRAR** instalado en la ruta por defecto (para que el visor de cómics pueda descomprimir archivos `.rar`/`.cbr`).

### Pasos para iniciar:
1. Haz doble clic sobre `TVCatLauncher.exe` situado en la raíz o dentro de la carpeta `tvcat/`.
2. El launcher iniciará de forma automática el backend de Python en segundo plano y colocará un icono de TVCat en la bandeja del sistema (junto al reloj).
3. Haz clic derecho sobre el icono para abrir el panel de administración, el visor web, consultar el código QR de conexión móvil o apagar el servidor.

---

## 4. Estructura de Persistencia y Copias de Seguridad

* **`tvcat/data/tvcat.db`**: Base de datos del sistema (usuarios, perfiles, historial, canales).
* **`tvcat/plugins/tvcat_tgindex/data/tvcat.db`**: Catálogo de canales y mensajes indexados.
* **`config/tvcat_config.json`** y **`config/tvcat_tgindex_config.json`**: Configuraciones generales y tokens.


**NOTA** : Este proyecto está en desarrollo y muchas opciones son experimentales.
