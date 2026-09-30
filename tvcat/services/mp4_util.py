"""Utilidades MP4 compartidas (servicio central).

Localizar el box `moov` sin descargar el fichero entero: lo usan la sonda
media, HLS y cualquiera que necesite metadatos MP4. Todo el I/O entra por
`fetch_fn(offset, length) -> bytes` inyectado (cada llamador usa su carril).
"""
import asyncio

MAX_MOOV_SIZE = 200 * 1024 * 1024
HUNT_STEP = 1048576
HUNT_MAX_BACK = 32 * 1048576


def iter_boxes(buf):
    """Genera (typ, off, size|None) caminando boxes. size None = cortado o
    largesize sin bytes / tamaño-0 (hasta EOF)."""
    try:
        b = bytes(buf or b"")
    except Exception:
        return
    n = len(b)
    off = 0
    while off + 8 <= n:
        try:
            size = int.from_bytes(b[off:off + 4], "big")
            typ = b[off + 4:off + 8].decode("latin1")
        except Exception:
            return
        if size == 1:
            if off + 16 > n:
                yield (typ, off, None)
                return
            try:
                size = int.from_bytes(b[off + 8:off + 16], "big")
            except Exception:
                return
        if size == 0:
            yield (typ, off, None)
            return
        if size < 8:
            return
        yield (typ, off, size)
        off += size


def locate_moov_in_head(head):
    """(kind, off, size): kind = 'inhead' (moov completo en head),
    'extend' (moov empieza en off, falta tamaño size), 'after' (el moov
    vendría tras pos: fin de mdat conocido), 'unknown'."""
    try:
        boxes = list(iter_boxes(head or b""))
    except Exception:
        return ("unknown", 0, 0)
    n = len(bytes(head or b""))
    for typ, off, size in boxes:
        if typ == "moov":
            if size is None:
                return ("unknown", 0, 0)
            if off + size <= n:
                return ("inhead", off, size)
            return ("extend", off, size)
    # Sin moov: si hay mdat con fin conocido, el moov suele ir después.
    for typ, off, size in boxes:
        if typ == "mdat" and size is not None:
            return ("after", off + size, 0)
    return ("unknown", 0, 0)


def find_moov_in_tail(tail, base_offset=0):
    """Busca 'moov' validado (tamaño sano + mvhd cerca) de atrás adelante.
    Devuelve (abs_off, size) o None. base_offset = offset en fichero del
    inicio de tail."""
    try:
        b = bytes(tail or b"")
        pos = b.rfind(b"moov")
        while pos >= 4:
            try:
                size = int.from_bytes(b[pos - 4:pos], "big")
            except Exception:
                break
            if 8 <= size <= MAX_MOOV_SIZE:
                try:
                    window = b[pos:pos + min(size, 4096)]
                except Exception:
                    window = b""
                if b"mvhd" in window:
                    return (base_offset + pos - 4, size)
            pos = b.rfind(b"moov", 0, pos)
        return None
    except Exception:
        return None


def extract_ftyp(head) -> bytes:
    """Primer box ftyp del head (para ensamblar init-segment ftyp+moov).
    b"" si no hay uno completo."""
    try:
        for typ, off, size in iter_boxes(head or b""):
            if typ != "ftyp":
                continue
            if size is None:
                return b""
            b = bytes(head or b"")
            if off + size <= len(b):
                return b[off:off + size]
            return b""
        return b""
    except Exception:
        return b""


async def fetch_moov(fetch_fn, fsize, head, log=None):
    """Orquesta la localización+descarga del moov. Devuelve
    (moov_bytes|b"", pos|0, size|0). Estrategia:
    1) walk del head (moov dentro / extend / after-mdat exacto),
    2) caza hacia atrás en ventanas de 1MB (hasta 32MB),
    3) b"" si no aparece.
    `fetch_fn(offset, length)` -> bytes. `log` opcional(msg)."""
    def _log(m):
        try:
            if log:
                log(m)
        except Exception:
            pass

    try:
        total = int(fsize or 0)
    except Exception:
        total = 0
    if total <= 0:
        return b"", 0, 0

    async def _get(off, ln):
        try:
            data = await fetch_fn(max(0, off), max(0, ln))
            return bytes(data or b"")
        except Exception:
            return b""

    # 1) Walk del head.
    try:
        kind, off, size = locate_moov_in_head(head)
    except Exception:
        kind, off, size = "unknown", 0, 0
    _log("walk head: %s" % kind)
    if kind == "inhead":
        return b"", 0, 0  # ya está en el head, nada que traer
    if kind == "extend" and size:
        _log("moov se extiende, completando (%dKB)" % (size // 1024))
        extra = await _get(off + len(bytes(head or b"")), size - (len(bytes(head or b"")) - off))
        # Devolver el moov COMPLETO (trozo del head + resto), no solo el extra.
        _hb = bytes(head or b"")
        return _hb[off:] + bytes(extra or b""), off, size
    if kind == "after":
        _log("moov tras mdat en %d, leyendo 1MB" % off)
        win = await _get(off, HUNT_STEP)
        if win:
            found = find_moov_in_tail(win, off)
            if found:
                mo, ms = found
                _log("moov localizado (%dKB)" % (ms // 1024))
                full = await _get(mo, min(ms, total - mo))
                if full:
                    return full, mo, ms
    # 2) Caza hacia atrás con solape (el marcador puede partirse entre ventanas).
    _log("caza hacia atrás (últimos 32MB)")
    back = HUNT_STEP
    overlap = 16
    while back <= HUNT_MAX_BACK and back < total:
        start = max(0, total - back)
        win = await _get(start, min(HUNT_STEP + overlap, total - start))
        if not win:
            return b"", 0, 0
        pos = win.rfind(b"moov")
        while pos >= 4:
            size = _valid_moov_at(win, pos)
            if size:
                mo = start + pos - 4
                _log("moov localizado (%dKB)" % (size // 1024))
                full = await _get(mo, min(size, total - mo))
                if full:
                    return full, mo, size
                return b"", 0, 0
            pos = win.rfind(b"moov", 0, pos)
        back += HUNT_STEP
    # 3) Muestreo medio (moov ni al inicio ni al final).
    _log("muestreo medio (25/50/75%)")
    for frac in (0.25, 0.5, 0.75):
        try:
            start = int(total * frac)
            win = await _get(start, HUNT_STEP)
            if not win:
                continue
            pos = win.find(b"moov")
            while 4 <= pos:
                size = _valid_moov_at(win, pos)
                if size:
                    mo = start + pos - 4
                    _log("moov en muestreo %d%% (%dKB)" % (int(frac * 100), size // 1024))
                    full = await _get(mo, min(size, total - mo))
                    if full:
                        return full, mo, size
                pos = win.find(b"moov", pos + 1)
        except Exception:
            pass
    _log("moov no localizado")
    return b"", 0, 0


def _valid_moov_at(win, pos) -> int:
    """Tamaño si hay un moov válido en pos (tamaño sano + mvhd en 64KB)."""
    try:
        size = int.from_bytes(win[pos - 4:pos], "big")
    except Exception:
        return 0
    if not (8 <= size <= MAX_MOOV_SIZE):
        return 0
    try:
        if b"mvhd" in win[pos:pos + min(size, 65536)]:
            return size
    except Exception:
        pass
    return 0
