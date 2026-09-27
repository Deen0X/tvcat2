"""Banderas globales de parada cooperativa (F1 QueuePriority).

El plugin TGHirayi las activa al Detener/Detener+; los servicios de
transferencia las consultan por chunk/parte (lectura barata). Módulo hoja:
sin imports, sin ciclos.
"""

STOP_DOWNLOAD = False
STOP_UPLOAD = False
YIELD_DOWNLOAD = False


def set_stop_download(flag=True):
    global STOP_DOWNLOAD
    STOP_DOWNLOAD = bool(flag)


def set_stop_upload(flag=True):
    global STOP_UPLOAD
    STOP_UPLOAD = bool(flag)


def set_yield_download(flag=True):
    """Cesión temporal al reproductor (la gestiona el árbitro; al cesar,
    las descargas continúan por sidecar)."""
    global YIELD_DOWNLOAD
    YIELD_DOWNLOAD = bool(flag)


def clear():
    global STOP_DOWNLOAD, STOP_UPLOAD, YIELD_DOWNLOAD
    STOP_DOWNLOAD = False
    STOP_UPLOAD = False
    YIELD_DOWNLOAD = False


def should_abort_download():
    return STOP_DOWNLOAD or YIELD_DOWNLOAD


def should_abort_upload():
    return STOP_UPLOAD


class DownloadAborted(Exception):
    """La descarga se canceló por parada (no es fallo: no reintentar aquí,
    no borrar el parcial; el sidecar permite continuar)."""


class UploadAborted(Exception):
    """La subida se canceló por parada (no es fallo: no reintentar)."""
