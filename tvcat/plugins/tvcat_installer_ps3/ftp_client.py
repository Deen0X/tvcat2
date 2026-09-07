"""
TVCat Installer PS3 — Cliente FTP
=================================
Cliente FTP mínimo (stdlib ftplib) para enviar ficheros (ISO/PKG) a una PS3
con servidor FTP activo (webMAN / multiMAN / Irisman).

Todas las funciones son síncronas y se ejecutan desde asyncio.to_thread.
Soporta reanudación por REST si el remoto existe y es más corto que el local.
"""

import os
import time
from ftplib import FTP, error_perm

BLOCK_SIZE = 262144  # 256 KB


def _login(ftp: FTP, console: dict):
    user = (console.get("username") or "").strip()
    password = console.get("password") or ""
    if not user:
        user = "anonymous"
    ftp.login(user, password)


def connect(console: dict) -> FTP:
    """Conecta, hace login, activa modo pasivo y cambia al directorio destino."""
    host = (console.get("host") or "").strip()
    if not host:
        raise ValueError("Host vacío")
    port = int(console.get("port") or 21)
    timeout = int(console.get("timeout") or 20)
    ftp = FTP()
    ftp.connect(host, port, timeout=timeout)
    _login(ftp, console)
    ftp.set_pasv(True)
    _cwd_or_create(ftp, console.get("destination") or "/")
    return ftp


def _cwd_or_create(ftp: FTP, destination: str):
    destination = (destination or "/").strip()
    if not destination or destination == "/":
        return
    try:
        ftp.cwd(destination)
    except error_perm:
        try:
            ftp.mkd(destination)
        except error_perm:
            pass
        ftp.cwd(destination)


def test(console: dict) -> dict:
    """Prueba conectividad: login + acceso al destino."""
    try:
        ftp = connect(console)
        try:
            ftp.pwd()
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()
        return {"ok": True, "error": ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def remote_size(ftp: FTP, filename: str) -> int:
    """Tamaño del fichero remoto, o 0 si no existe / no soporta SIZE."""
    try:
        return int(ftp.size(filename) or 0)
    except Exception:
        return 0


def store(console: dict, local_path: str, remote_filename: str, progress_cb=None) -> int:
    """Sube local_path a destination/remote_filename con reanudación.

    progress_cb(done_bytes, total_bytes) se llama periódicamente.
    Devuelve el tamaño final en el remoto.
    """
    ftp = connect(console)
    total = os.path.getsize(local_path)
    try:
        existing = remote_size(ftp, remote_filename)
        offset = 0
        if 0 < existing < total:
            offset = existing
        if existing >= total:
            return existing

        sent = offset
        start_time = time.time()

        def cb(block):
            nonlocal sent, start_time
            sent += len(block)
            if progress_cb:
                progress_cb(sent, total)

        with open(local_path, "rb") as f:
            f.seek(offset)
            if offset > 0:
                try:
                    ftp.voidcmd(f"REST {offset}")
                except error_perm:
                    f.seek(0)
                    sent = 0
            ftp.storbinary(f"STOR {remote_filename}", f, blocksize=BLOCK_SIZE, callback=cb)

        return total
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
