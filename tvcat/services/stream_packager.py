"""
StreamPackager — servicio de empaquetado HLS para TVCat.

Convierte documentos de Telegram en segmentos HLS servibles por la SmartTV.
El servidor NUNCA re-codifica video (ffmpeg -c copy). Solo demux/remux.

Flujo:
  1. Metadata (ffprobe) -> cacheada en BD.
  2. Indice tiempo->byte (ffprobe packet output) -> cacheado en memoria.
  3. Segmento bajo demanda: ffmpeg seek + extract -> .ts -> sirve -> limpia.
"""

import os
import json
import subprocess
import logging
import asyncio
from typing import Optional, Dict, List, Tuple

log = logging.getLogger("packager")

SEGMENT_DURATION = 6
SEGMENT_DIR = "hls_segments"
INDEX_CACHE: Dict[int, list] = {}
METADATA_CACHE: Dict[int, dict] = {}


def _find_ffmpeg():
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    # Ruta del plugin (relativa a este fichero: services/ -> raiz tvcat/)
    plugin_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "plugins", "tvcat_TGHirayi", "ffmpeg", "ffmpeg.exe"
    )
    if os.path.isfile(plugin_dir):
        return plugin_dir
    # Fallback: buscar ffmpeg.exe en cualquier plugins/tvcat_TGHirayi/ffmpeg/ alcanzable
    _here = os.path.dirname(os.path.abspath(__file__))
    for _root in [os.path.dirname(_here), _here, os.path.dirname(os.path.dirname(_here))]:
        _try = os.path.join(_root, "plugins", "tvcat_TGHirayi", "ffmpeg", "ffmpeg.exe")
        if os.path.isfile(_try):
            return _try
    return None


def _find_ffprobe():
    import shutil
    p = shutil.which("ffprobe")
    if p:
        return p
    plugin_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "plugins", "tvcat_TGHirayi", "ffmpeg", "ffprobe.exe"
    )
    if os.path.isfile(plugin_dir):
        return plugin_dir
    _here = os.path.dirname(os.path.abspath(__file__))
    for _root in [os.path.dirname(_here), _here, os.path.dirname(os.path.dirname(_here))]:
        _try = os.path.join(_root, "plugins", "tvcat_TGHirayi", "ffmpeg", "ffprobe.exe")
        if os.path.isfile(_try):
            return _try
    return None


def _get_segments_dir(data_dir):
    d = os.path.join(data_dir, SEGMENT_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _cleanup_segment(seg_path):
    try:
        if seg_path and os.path.isfile(seg_path):
            os.remove(seg_path)
    except OSError:
        pass


def extract_metadata_from_file(file_path):
    ffprobe = _find_ffprobe()
    if not ffprobe:
        log.warning("ffprobe no encontrado")
        return {"audio": [], "subs": []}
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries",
             "stream=index,codec_name,codec_type,"
             "stream_tags=language,title:"
             "stream_disposition=default,forced",
             "-of", "json", file_path],
            capture_output=True, timeout=120
        )
        d = json.loads((r.stdout or b"{}").decode("utf-8", errors="replace"))
    except Exception as e:
        log.warning("ffprobe metadata error: %s", e)
        return {"audio": [], "subs": []}

    audio, subs = [], []
    for s in d.get("streams", []):
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        entry = {
            "index": s.get("index", 0),
            "language": tags.get("language", ""),
            "title": tags.get("title", ""),
            "codec": s.get("codec_name", ""),
            "default": bool(disp.get("default")),
        }
        ct = s.get("codec_type", "")
        if ct == "audio":
            audio.append(entry)
        elif ct == "subtitle":
            subs.append(entry)
    return {"audio": audio, "subs": subs}


def get_duration(file_path):
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return 0.0
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             file_path],
            capture_output=True, timeout=60
        )
        return float((r.stdout or b"0").decode("utf-8", errors="replace").strip() or "0")
    except Exception:
        return 0.0


def build_index_from_file(file_path):
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return []
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries", "packet=pts_time,offset",
             "-of", "json", file_path],
            capture_output=True, timeout=600
        )
        data = json.loads((r.stdout or b"{}").decode("utf-8", errors="replace"))
    except Exception as e:
        log.warning("build_index error: %s", e)
        return []

    index = []
    for pkt in data.get("packets", []):
        pts = pkt.get("pts_time")
        off = pkt.get("offset")
        if pts is not None and off is not None:
            try:
                index.append((float(pts), int(off)))
            except (ValueError, TypeError):
                continue
    index.sort(key=lambda x: x[0])
    return index


async def ensure_index(episode_id, file_path):
    if episode_id in INDEX_CACHE:
        return INDEX_CACHE[episode_id]
    loop = asyncio.get_event_loop()
    index = await loop.run_in_executor(None, build_index_from_file, file_path)
    if index:
        INDEX_CACHE[episode_id] = index
        log.info("Indice generado: episodio %d, %d paquetes", episode_id, len(index))
    return index


async def get_metadata(episode_id, file_path):
    if episode_id in METADATA_CACHE:
        return METADATA_CACHE[episode_id]
    loop = asyncio.get_event_loop()
    meta = await loop.run_in_executor(None, extract_metadata_from_file, file_path)
    if meta.get("audio") or meta.get("subs"):
        METADATA_CACHE[episode_id] = meta
    return meta


def _find_nearest_packet(index, target_time):
    if not index:
        return 0
    best_idx = 0
    for i, (t, _) in enumerate(index):
        if t <= target_time:
            best_idx = i
        else:
            break
    return best_idx


def cleanup_episode_segments(episode_id, data_dir):
    seg_dir = os.path.join(data_dir, SEGMENT_DIR)
    if not os.path.isdir(seg_dir):
        return
    prefix = "seg_%d_" % episode_id
    for fname in os.listdir(seg_dir):
        if fname.startswith(prefix):
            try:
                os.remove(os.path.join(seg_dir, fname))
            except OSError:
                pass


async def generate_segment(episode_id, segment_num, file_path, file_size, data_dir):
    seg_dir = _get_segments_dir(data_dir)
    seg_path = os.path.join(seg_dir, "seg_%d_%d.ts" % (episode_id, segment_num))

    if os.path.isfile(seg_path):
        return seg_path

    index = await ensure_index(episode_id, file_path)
    duration = await asyncio.get_event_loop().run_in_executor(
        None, get_duration, file_path
    )

    target_time = segment_num * SEGMENT_DURATION
    if target_time >= duration and duration > 0:
        return None

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        log.error("ffmpeg no encontrado")
        return None

    cmd = [
        ffmpeg, "-y",
        "-ss", str(target_time),
        "-i", file_path,
        "-t", str(SEGMENT_DURATION),
        "-c", "copy",
        "-f", "mpegts",
        seg_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0 and os.path.isfile(seg_path):
            return seg_path
    except Exception as e:
        log.warning("Segmento error: %s", e)

    _cleanup_segment(seg_path)
    return None


def generate_playlist(episode_id, duration, audio_tracks=None):
    total_segments = max(1, int(duration / SEGMENT_DURATION) + 1)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:%d" % SEGMENT_DURATION,
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]

    if audio_tracks and len(audio_tracks) > 1:
        for at in audio_tracks:
            lang = at.get("language", "und")
            title = at.get("title", lang)
            idx = at.get("index", 0)
            default = ' DEFAULT' if at.get("default") else ''
            lines.append(
                '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",'
                'LANGUAGE="%s",NAME="%s",URI="segment.m3u8?audio=%d"%s'
                % (lang, title, idx, default)
            )

    for i in range(total_segments):
        lines.append("#EXTINF:%.3f," % SEGMENT_DURATION)
        lines.append("segment/%d/%d.ts" % (episode_id, i))

    return "\n".join(lines)
