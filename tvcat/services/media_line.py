"""Línea MediaLine v1: sonda compacta embebida en el cover.

Gramática (10 tokens / 9 pipes; token 0 marcador, token 9 sello):
  🎞️ M1|res|codec.Perfil.pix|fps|lang:codec:ch:ratekHz+...|lang[!]+...|dur_s|cont|br|😺
Vacíos donde no hay dato. Sin `😺` de cierre la línea se descarta.
"""
import re

MARK = "\U0001F39E\uFE0F M1"
SEAL = "\U0001F63A"

_LINE_RE = re.compile(
    "\U0001F39E\uFE0F?\\sM1\\|([^\n" + SEAL + "]{1,400})\\|" + SEAL)
_RES_RE = re.compile(r"^(\d{1,5})x(\d{1,5})$")
_AUD_RE = re.compile(r"^([a-z]{2,4}):([a-z0-9?]+):(\d{1,2}ch|\?):([\d.?]+)$")
_SUB_RE = re.compile(r"^([a-z]{2,4})(!)?$")
_NUM_RE = re.compile(r"^\d{1,7}$")


def _khz(rate) -> str:
    """48000 -> '48', 44100 -> '44.1'."""
    try:
        v = float(str(rate or "").strip())
        if v <= 0:
            return ""
        k = v / 1000.0
        s = ("%.3f" % k).rstrip("0").rstrip(".")
        return s
    except Exception:
        return ""


def _pix(pix_fmt) -> str:
    """yuv420p -> '420', yuv420p10le -> '42010', '' si desconocido."""
    try:
        s = str(pix_fmt or "").lower().replace("yuv", "")
        m = re.match(r"^(\d{3})(?:p(?:(\d+)le)?)?$", s)
        if not m:
            return ""
        base, depth = m.group(1), m.group(2)
        if base not in ("420", "422", "444"):
            return ""
        if depth and depth not in ("8",):
            return base + depth
        return base
    except Exception:
        return ""


def _profile_letter(profile) -> str:
    """'High 4:4:4 Predictive' -> 'H'. Primera letra en mayúsculas."""
    try:
        s = str(profile or "").strip()
        if not s:
            return ""
        c = s[0].upper()
        return c if "A" <= c <= "Z" else ""
    except Exception:
        return ""


def _dur_seconds(media: dict) -> str:
    """Segundos enteros desde 'duration' (H:MM:SS) o durationm."""
    try:
        d = str((media or {}).get("duration") or "")
        parts = d.split(":")
        if len(parts) in (2, 3):
            nums = [float(p) for p in parts]
            if len(nums) == 2:
                return str(int(nums[0] * 60 + nums[1]))
            return str(int(nums[0] * 3600 + nums[1] * 60 + nums[2]))
    except Exception:
        pass
    try:
        m = int(float(str((media or {}).get("durationm") or 0)))
        if m > 0:
            return str(m * 60)
    except Exception:
        pass
    return ""


def _raw_tracks(media: dict):
    """(videos, audios, subs) del raw `_streams` (o [],[],[])."""
    try:
        streams = (media or {}).get("_streams") or []
        if not isinstance(streams, list):
            return [], [], []
        v = [s for s in streams if (s or {}).get("codec_type") == "video"]
        a = [s for s in streams if (s or {}).get("codec_type") == "audio"]
        s = [s for s in streams if (s or {}).get("codec_type") == "subtitle"]
        return v, a, s
    except Exception:
        return [], [], []


def _lang_of(stream) -> str:
    try:
        lang = ((stream or {}).get("tags") or {}).get("language") or "und"
        lang = str(lang).lower()
        return lang if re.match(r"^[a-z]{2,4}$", lang) else "und"
    except Exception:
        return "und"


def encode_line(media: dict) -> str:
    """>80-95 chars con la sonda, o '' si no hay datos mínimos."""
    try:
        m = media or {}
        if not isinstance(m, dict):
            return ""
        videos, audios, subs = _raw_tracks(m)

        res = str(m.get("resolution") or "")
        if not _RES_RE.match(res):
            res = ""
            if videos:
                try:
                    w, h = int(videos[0].get("width") or 0), int(videos[0].get("height") or 0)
                    if w and h:
                        res = f"{w}x{h}"
                except Exception:
                    pass

        vid = ""
        vcode = str(m.get("vcodec") or "").lower()
        if not vcode and videos and videos[0].get("codec_name"):
            vcode = str(videos[0]["codec_name"]).lower()
        if vcode:
            vid = vcode
            prof = _profile_letter((videos[0] if videos else {}).get("profile"))
            px = _pix((videos[0] if videos else {}).get("pix_fmt"))
            if prof:
                vid += "." + prof
                if px:
                    vid += "." + px
            elif px:
                vid += ".." + px

        fps = str(m.get("fps") or "")

        atoks = []
        if audios:
            for a in audios:
                try:
                    lang = _lang_of(a)
                    ac = str(a.get("codec_name") or "").lower() or "?"
                    try:
                        ch = int(a.get("channels") or 0)
                        chs = f"{ch}ch" if ch > 0 else "?"
                    except Exception:
                        chs = "?"
                    khz = _khz(a.get("sample_rate")) or "?"
                    atoks.append(f"{lang}:{ac}:{chs}:{khz}")
                except Exception:
                    pass
        if not atoks:
            # Fallback a claves normalizadas (filas antiguas sin raw).
            try:
                import re as _re2
                full = str(m.get("fullaudiotracks") or "")
                for mm in _re2.finditer(
                        r"([a-z]{2,4})(?: \(([a-z0-9]+)(?:, (\d{1,2}ch))?\))?",
                        full):
                    lang = mm.group(1)
                    atoks.append(
                        f"{lang}:{mm.group(2) or '?'}:{mm.group(3) or '?'}:?")
                if not atoks and str(m.get("audiotracks") or "").strip():
                    atoks.append("und:?:?:?")
            except Exception:
                pass

        stoks = []
        if subs:
            for s in subs:
                try:
                    lang = _lang_of(s)
                    forced = int((s.get("disposition") or {}).get("forced") or 0)
                    stoks.append(lang + ("!" if forced else ""))
                except Exception:
                    pass
        if not stoks and str(m.get("subtitles") or "").strip():
            try:
                for part in str(m.get("subtitles")).split(","):
                    lang = part.strip().split(" ")[0].lower()
                    if re.match(r"^[a-z]{2,4}$", lang):
                        stoks.append(lang + ("!" if "forced" in part.lower() else ""))
            except Exception:
                pass

        dur = _dur_seconds(m)
        # Extensión primero: es lo que realmente viaja (mp4, no 'mov').
        cont = str(m.get("extension") or m.get("container") or "").lower()
        try:
            br = int(float(str(m.get("bitrate") or 0)))
            brs = str(br) if br > 0 else ""
        except Exception:
            brs = ""

        if not res and not atoks:
            return ""  # sin datos mínimos
        toks = [MARK, res, vid, fps, "+".join(atoks), "+".join(stoks),
                dur, cont, brs, SEAL]
        return "|".join(toks)
    except Exception:
        return ""


def parse_media_line(text: str):
    """Dict normalizado (listo para episode_media) o None si ausente/inválida."""
    try:
        if not text or MARK not in text:
            return None
        m = _LINE_RE.search(text)
        if not m:
            return None
        inner = m.group(1)
        toks = inner.split("|")
        if len(toks) != 8:
            return None
        res, vid, fps, aud, sub, dur, cont, br = toks
        if res and not _RES_RE.match(res):
            return None
        out = {}
        if res:
            w, h = _RES_RE.match(res).groups()
            out["resolution"] = res
            out["resolutionx"], out["resolutiony"] = w, h
            try:
                from services.media_probe import aspect_label as _al, quality_label as _ql
            except Exception:
                try:
                    from tvcat.services.media_probe import aspect_label as _al, quality_label as _ql
                except Exception:
                    _al = _ql = None
            try:
                if _al:
                    out["aspectratio"] = _al(int(w), int(h))
                if _ql:
                    out["quality"] = _ql(int(h))
            except Exception:
                pass
        vcode, vprof, vpix = "", "", ""
        if vid:
            if vid.endswith("."):
                return None
            parts = vid.split(".")
            if len(parts) > 3 or not re.match(r"^[a-z0-9]+$", parts[0]):
                return None
            vcode = parts[0]
            if len(parts) >= 2:
                if parts[1] and not re.match(r"^[A-Z]$", parts[1]):
                    return None
                vprof = parts[1]
            if len(parts) == 3:
                if not re.match(r"^\d{3}(?:10|12)?$", parts[2]):
                    return None
                vpix = parts[2]
            out["vcodec"] = vcode
            if vprof:
                out["_vprofile"] = vprof
            if vpix:
                out["_pixfmt"] = vpix
        if fps:
            out["fps"] = fps
        if aud:
            full, simple, seen, chl = [], [], set(), []
            for item in aud.split("+"):
                am = _AUD_RE.match(item)
                if not am:
                    return None
                lang, ac, chs, _khz = am.groups()
                if lang not in seen:
                    seen.add(lang)
                    simple.append(lang)
                if chs != "?":
                    chl.append(chs)
                if ac != "?" and chs != "?":
                    full.append(f"{lang} ({ac}, {chs})")
                elif ac != "?":
                    full.append(f"{lang} ({ac})")
                else:
                    full.append(lang)
            out["audiotracks"] = ", ".join(simple)
            out["fullaudiotracks"] = ", ".join(full)
            out["audiocount"] = str(len(full))
            if out["audiocount"] == "0":
                return None
            if chl:
                out["achannels"] = "+".join(chl)
            try:
                _m0 = _AUD_RE.match(aud.split("+")[0])
                if _m0 and _m0.group(2) != "?":
                    out["acodec"] = _m0.group(2)
            except Exception:
                pass
        else:
            out["audiocount"] = ""
        if sub:
            sl = []
            for item in sub.split("+"):
                sm = _SUB_RE.match(item)
                if not sm:
                    return None
                lang, forced = sm.groups()
                sl.append(lang + (" (forced)" if forced else ""))
            out["subtitles"] = ", ".join(sl)
            out["subcount"] = str(len(sl))
        else:
            out["subcount"] = ""
        if dur:
            if not _NUM_RE.match(dur):
                return None
            try:
                from services.media_probe import fmt_duration as _fd
            except Exception:
                try:
                    from tvcat.services.media_probe import fmt_duration as _fd
                except Exception:
                    _fd = None
            try:
                out["duration"] = _fd(dur) if _fd else ""
                out["durationm"] = str(int(int(dur) // 60))
            except Exception:
                pass
        if cont:
            out["container"] = cont
            out["extension"] = cont
        if br:
            if not _NUM_RE.match(br):
                return None
            out["bitrate"] = br
        out["_streams"] = []
        out["_format"] = {}
        return out
    except Exception:
        return None
