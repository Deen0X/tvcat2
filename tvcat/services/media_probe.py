"""Sonda ffprobe de ficheros locales (CORE, sin Telegram).

`probe_file(path)` devuelve el dict `media` que consume
`enrich_tags.get_base_tags(..., media)` para los tags `_*` al crear el cover
en TGHirayi (first-only). Tolera ficheros truncados (moov parcial): parsea lo
que ffprobe alcance a leer aunque el returncode sea != 0.
"""
import json
import math
import os
import shutil
import subprocess


def find_ffprobe():
    """Localiza ffprobe: stream_packager → PATH → tools/ de TGHirayi."""
    try:
        from services.stream_packager import _find_ffprobe as _f
        p = _f()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    try:
        from tvcat.services.stream_packager import _find_ffprobe as _f2
        p = _f2()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    p = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if p:
        return p
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (
            os.path.join(here, "..", "plugins", "tvcat_TGHirayi_v2", "ffmpeg", "ffprobe.exe"),
            os.path.join(here, "..", "plugins", "tvcat_TGHirayi", "ffmpeg", "ffprobe.exe"),
        ):
            if os.path.isfile(cand):
                return cand
    except Exception:
        pass
    return ""


def quality_label(h) -> str:
    try:
        h = int(h or 0)
    except Exception:
        return ""
    if h >= 2160:
        return "4K"
    if h >= 1080:
        return "FullHD"
    if h >= 720:
        return "HD"
    if h >= 480:
        return "SD"
    if h > 0:
        return "LD"
    return ""


def aspect_label(w, h) -> str:
    try:
        w, h = int(w or 0), int(h or 0)
    except Exception:
        return ""
    if not w or not h:
        return ""
    g = math.gcd(w, h) or 1
    return f"{w // g}:{h // g}"


def fmt_duration(sec) -> str:
    try:
        s = int(float(sec or 0))
    except Exception:
        return ""
    if s <= 0:
        return ""
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n) -> str:
    try:
        n = int(n or 0)
    except Exception:
        return ""
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return ""


def _lang(code) -> str:
    c = (code or "").strip().lower()
    return c or "und"


def _fps(rate) -> str:
    try:
        s = str(rate or "").strip()
        if "/" in s:
            a, b = s.split("/", 1)
            v = float(a) / float(b or 1)
        else:
            v = float(s)
        if v <= 0:
            return ""
        return str(round(v, 2)).rstrip("0").rstrip(".")
    except Exception:
        return ""


def _channels(ch) -> str:
    try:
        n = int(ch or 0)
        return f"{n}ch" if n > 0 else ""
    except Exception:
        return ""


def probe_file(path: str, timeout: int = 30) -> dict:
    """Sonda un fichero local. Siempre devuelve dict (vacío si falla)."""
    out = {}
    try:
        if not path or not os.path.isfile(path):
            return out
        ff = find_ffprobe()
        if not ff:
            print("[MEDIA PROBE] ffprobe no encontrado", flush=True)
            return out
        try:
            r = subprocess.run(
                [ff, "-v", "error", "-show_format", "-show_streams",
                 "-of", "json", path],
                capture_output=True, timeout=timeout)
            data = json.loads((r.stdout or b"{}").decode("utf-8", "replace"))
        except Exception as e:
            print(f"[MEDIA PROBE] ffprobe fallo ({path}): {e}", flush=True)
            return out
        streams = data.get("streams") or []
        fmt = data.get("format") or {}
        videos = [s for s in streams if (s.get("codec_type") or "") == "video"]
        audios = [s for s in streams if (s.get("codec_type") or "") == "audio"]
        subs = [s for s in streams if (s.get("codec_type") or "") == "subtitle"]
        v = videos[0] if videos else {}
        try:
            w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        except Exception:
            w, h = 0, 0
        if w and h:
            out["resolution"] = f"{w}x{h}"
            out["resolutionx"] = str(w)
            out["resolutiony"] = str(h)
            out["aspectratio"] = aspect_label(w, h)
            out["quality"] = quality_label(h)
        if v.get("codec_name"):
            out["vcodec"] = str(v["codec_name"]).lower()
        _f = _fps(v.get("r_frame_rate") or v.get("avg_frame_rate"))
        if _f:
            out["fps"] = _f
        if audios:
            a0 = audios[0]
            if a0.get("codec_name"):
                out["acodec"] = str(a0["codec_name"]).lower()
            full, simple, seen = [], [], set()
            for a in audios:
                lang = _lang((a.get("tags") or {}).get("language"))
                if lang not in seen:
                    seen.add(lang)
                    simple.append(lang)
                parts = [lang]
                if a.get("codec_name"):
                    parts[0] = f"{lang} ({a['codec_name'].lower()}"
                    ch = _channels(a.get("channels"))
                    parts[0] += (f", {ch}" if ch else "") + ")"
                full.append(parts[0])
            # Forzados/por defecto se marcan igual que subs si aplica
            out["audiotracks"] = ", ".join(simple)
            out["fullaudiotracks"] = ", ".join(full)
        if subs:
            sl = []
            for s in subs:
                lang = _lang((s.get("tags") or {}).get("language"))
                try:
                    if int(s.get("disposition", {}).get("forced") or 0):
                        lang += " (forced)"
                except Exception:
                    pass
                sl.append(lang)
            out["subtitles"] = ", ".join(sl)
        _fmt = str(fmt.get("format_name") or "").split(",")[0].strip().lower()
        if _fmt:
            out["container"] = _fmt
        _ext = os.path.splitext(path)[1].lstrip(".").lower()
        if _ext:
            out["extension"] = _ext
        _dur = fmt.get("duration")
        if _dur:
            out["duration"] = fmt_duration(_dur)
            try:
                out["durationm"] = str(int(float(_dur) // 60))
            except Exception:
                pass
        try:
            _br = int(float(fmt.get("bit_rate") or 0) // 1000)
            if _br > 0:
                out["bitrate"] = str(_br)
        except Exception:
            pass
        try:
            _sz = int(fmt.get("size") or os.path.getsize(path) or 0)
            if _sz > 0:
                out["filesize"] = fmt_size(_sz)
        except Exception:
            pass
    except Exception as e:
        print(f"[MEDIA PROBE] error ({path}): {e}", flush=True)
    return out
