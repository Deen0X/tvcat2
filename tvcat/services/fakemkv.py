"""
FakeMKV — empaquetado de rangos MKV para HLS SEQ.

Un MKV tiene esta estructura:
  [EBML][Segment [SeekHead][Info][Tracks][Chapters][Void]... [Cluster]*N [Cues][Tags]]

Los Cues (mapa tiempo->offset cluster) suelen estar AL FINAL del fichero.
Se obtienen del SeekHead (que apunta a su offset absoluto).

Flujo HLS SEQ:
  1. download_service descarga el sparse completo (rápido, 8 threads).
  2. parse_mkv_cues lee los Cues del final -> mapa tiempo(ms) -> offset cluster.
  3. Para remuxar [X, X+Δ]: localizar cluster de X, recortar clusters contiguos
     hasta X+Δ, construir un mini-MKV (header + clusters), ffmpeg -> .ts.

Este servicio es standalone: no importa gateway (evita side-effects uvicorn).
"""
import os
import struct


# ─── EBML helpers ────────────────────────────────────────────────────────────
def _read_vint(data: bytes, pos: int):
    """Lee un EBML vint en data[pos]. Retorna (value, length). None si mal."""
    if pos >= len(data):
        return None, 0
    first = data[pos]
    mask = 0x80
    length = 1
    while not (first & mask):
        mask >>= 1
        length += 1
        if length > 8:
            return None, 0
    value = first & (mask - 1)
    for i in range(1, length):
        if pos + i >= len(data):
            return None, length
        value = (value << 8) | data[pos + i]
    return value, length


def _write_vint(value: int) -> bytes:
    """Escribe un EBML vint (mínima longitud)."""
    if value < 0x7F:
        return bytes([value])
    # Longitud basada en el valor
    for length in range(1, 9):
        max_val = (1 << (7 * length)) - 1
        if value <= max_val:
            marker = 1 << (8 - length)
            out = bytearray()
            for i in range(length):
                shift = 8 * (length - 1 - i)
                out.append((value >> shift) & 0xFF)
            out[0] |= marker
            return bytes(out)
    raise ValueError("vint demasiado grande")


def _elem_id_bytes(elem_id: int) -> bytes:
    """Convierte un ID EBML (int) a bytes vint."""
    # IDs EBML tienen el bit de marcado del primer byte
    if elem_id <= 0x7F:
        return bytes([elem_id])
    for length in range(1, 5):
        max_val = (1 << (8 * length)) - 1
        if elem_id <= max_val:
            marker = 1 << (8 - length)
            out = bytearray()
            for i in range(length):
                shift = 8 * (length - 1 - i)
                out.append((elem_id >> shift) & 0xFF)
            out[0] |= marker
            return bytes(out)
    raise ValueError("elem id demasiado grande")


# ─── Parsing del MKV (lectura por offsets, sin cargar todo) ─────────────────
class MkvReader:
    """Lee elementos EBML de un fichero MKV sparse mediante seek, sin cargar todo."""

    def __init__(self, path: str):
        self.path = path
        self.size = os.path.getsize(path)
        self.seg_start = None
        self.seekhead_pos = None

    def _read(self, offset: int, length: int) -> bytes:
        with open(self.path, 'rb') as f:
            f.seek(offset)
            return f.read(length)

    def _read_elem_header(self, offset: int):
        """Lee un elemento EBML en offset: (elem_id, size, data_start)."""
        hdr = self._read(offset, 12)
        if len(hdr) < 2:
            return None
        # ID vint
        id_len = 1
        mask = 0x80
        while not (hdr[0] & mask):
            mask >>= 1
            id_len += 1
            if id_len > 4:
                return None
        elem_id = int.from_bytes(hdr[0:id_len], 'big')
        size, size_len = _read_vint(hdr, id_len)
        if size is None:
            return None
        data_start = offset + id_len + size_len
        return (elem_id, size, data_start)

    def scan_segment(self, max_scan=64 * 1024):
        """Escanea el header: EBML + Segment + SeekHead + Info + Tracks.
        Rellena self.seg_start, self.seekhead_pos, y localiza Cues via SeekHead."""
        # EBML en 0
        e = self._read_elem_header(0)
        if not e:
            return
        # Segment en 40 (tras EBML)
        pos = 40
        e = self._read_elem_header(pos)
        if not e or e[0] != 0x18538067:
            return
        self.seg_start = e[2]
        # Recorrer hijos del segment (primeros max_scan bytes)
        child = e[2]
        guard = 0
        while child < e[2] + max_scan and guard < 500:
            guard += 1
            ce = self._read_elem_header(child)
            if not ce:
                break
            cid, csize, cdata = ce
            if cid == 0x114D9B74:  # SeekHead
                self.seekhead_pos = child
            if cid == 0x1F43B675:  # Cluster - fin de metadata
                break
            child = cdata + csize
            if csize > 10 * 1024 * 1024:
                break

    def parse_seekhead(self) -> dict:
        """Parsea SeekHead: retorna {elem_id: abs_offset}."""
        result = {}
        if self.seekhead_pos is None or self.seg_start is None:
            return result
        e = self._read_elem_header(self.seekhead_pos)
        if not e:
            return result
        _, sh_size, sh_data = e
        body = self._read(sh_data, min(sh_size, 16 * 1024))
        sub = 0
        guard = 0
        while sub < len(body) - 4 and guard < 100:
            guard += 1
            # Buscar 0x4DBB (Seek)
            if body[sub] == 0x4D and body[sub+1] == 0xBB:
                ssz, ssl = _read_vint(body, sub + 2)
                if ssz is None:
                    break
                sbody = sub + 2 + ssl
                send = min(sbody + ssz, len(body))
                target_id = None
                target_pos = None
                p = sbody
                while p < send - 2:
                    sid = body[p]
                    slen = 1
                    mm = 0x80
                    while not (sid & mm):
                        mm >>= 1
                        slen += 1
                    full_sid = int.from_bytes(body[p:p+slen], 'big')
                    vsz, vsl = _read_vint(body, p+slen)
                    if vsz is None:
                        break
                    vdata = p + slen + vsl
                    if full_sid == 0x53AB:
                        target_id = int.from_bytes(body[vdata:vdata+vsz], 'big')
                    elif full_sid == 0x53AC:
                        target_pos = int.from_bytes(body[vdata:vdata+vsz], 'big')
                    p = vdata + vsz
                if target_id is not None and target_pos is not None:
                    result[target_id] = self.seg_start + target_pos
                sub = send
            else:
                sub += 1
        return result

    def read_cues(self) -> list:
        """Lee los Cues (mapa tiempo->offset). Retorna [(time_ms, cluster_abs), ...]."""
        seek = self.parse_seekhead()
        cues_off = seek.get(0x1C53BB6B)  # Cues
        if not cues_off:
            return []
        e = self._read_elem_header(cues_off)
        if not e:
            return []
        _, cues_size, cues_data = e
        read_len = min(cues_size, 8 * 1024 * 1024)
        body = self._read(cues_data, read_len)

        cues = []
        pos = 0
        guard = 0
        while pos < len(body) - 4 and guard < 100000:
            guard += 1
            if body[pos] == 0xBB:  # CuePoint
                s, ssl = _read_vint(body, pos + 1)
                if s is None:
                    break
                cbody = pos + 1 + ssl
                cend = min(cbody + s, len(body))
                ct = None
                clpos = None
                sub = cbody
                while sub < cend - 2:
                    sid = body[sub]
                    slen = 1
                    mm = 0x80
                    while not (sid & mm):
                        mm >>= 1
                        slen += 1
                    full_sid = int.from_bytes(body[sub:sub+slen], 'big')
                    vsz, vsl = _read_vint(body, sub + slen)
                    if vsz is None:
                        break
                    vdata = sub + slen + vsl
                    if full_sid == 0xB3:  # CueTime
                        ct = int.from_bytes(body[vdata:vdata+vsz], 'big') if vsz <= 4 else None
                    elif full_sid == 0xB7:  # CueTrackPositions
                        sub2 = vdata
                        v2end = min(vdata + vsz, len(body))
                        while sub2 < v2end - 2:
                            s2 = body[sub2]
                            s2len = 1
                            mm2 = 0x80
                            while not (s2 & mm2):
                                mm2 >>= 1
                                s2len += 1
                            f2 = int.from_bytes(body[sub2:sub2+s2len], 'big')
                            vsz2, vsl2 = _read_vint(body, sub2 + s2len)
                            if vsz2 is None:
                                break
                            vd2 = sub2 + s2len + vsl2
                            if f2 == 0xF1:  # CueClusterPosition
                                clpos = int.from_bytes(body[vd2:vd2+vsz2], 'big') if vsz2 <= 4 else None
                            sub2 = vd2 + vsz2
                    sub = vdata + vsz
                if ct is not None and clpos is not None:
                    cues.append((ct, self.seg_start + clpos))
                pos = cend
            else:
                pos += 1
        return sorted(cues)


# ─── API pública ─────────────────────────────────────────────────────────────
def parse_mkv_cues_from_file(path: str) -> list:
    """Retorna [(time_ms, cluster_abs), ...] del MKV en path."""
    r = MkvReader(path)
    r.scan_segment()
    return r.read_cues()


def get_cluster_for_time(cues: list, target_ms: int) -> int:
    """Dado cues y target en ms, retorna offset absoluto del cluster más cercano <= target."""
    if not cues:
        return None
    best = cues[0][1]
    for t, off in cues:
        if t <= target_ms:
            best = off
        else:
            break
    return best


def get_next_cue_time(cues: list, target_ms: int) -> int:
    """Retorna el tiempo del siguiente CuePoint tras target (o None)."""
    for t, off in cues:
        if t > target_ms:
            return t
    return None
