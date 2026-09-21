"""
tvcat_indexator — Genera índices de topics por canal (topología 3).

Depende de otros plugins SIN hardcodear carpetas: resuelve rutas vía
registry (`_dir`) + `is_enabled`. Orígenes = tgindex (canales con acceso),
destinos = TGHirayi_v2 (destinations con channel_id).

Endpoints (router auto-montado por plugin_loader):
- GET  /api/indexator/ping
- GET  /api/indexator/channels          → [{kind, id, name, channel_id, topics}]
- GET  /api/indexator/topics?channel_id= → [{id, title}] en vivo (refresco)
- GET  /api/indexator/config            → config + packs
- PUT  /api/indexator/config            → {index_topic, exclude_topics, noletras_mode, norm_*, packs...}
- POST /api/indexator/preview           → {channel_id, header, body} → partes calculadas
- POST /api/indexator/generate          → vacía TVCat-Index + postea
- POST /api/indexator/packs/upload      → zip de imágenes
"""
import os
import re
import sys
import time
import json as _json
import sqlite3

_TVCAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TVCAT_DIR not in sys.path:
    sys.path.insert(0, _TVCAT_DIR)

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")


def _session(request: Request):
    try:
        from services.auth_service import get_session
        return get_session(request.cookies.get("tvcat_session", ""))
    except Exception:
        return None


def _require_user(request: Request):
    sess = _session(request)
    if not sess:
        raise HTTPException(401)
    return sess


def _loader():
    """Plugin loader global (gateway lo expone en sys.modules)."""
    try:
        from tvcat.gateway import _plugin_loader as _pl
        return _pl
    except Exception:
        pass
    try:
        import tvcat.gateway as _gw
        for k in ("_plugin_loader", "plugin_loader", "_loader", "loader"):
            _pl = getattr(_gw, k, None)
            if _pl is not None and hasattr(_pl, "registry"):
                return _pl
    except Exception:
        pass
    return None


def _plugin_entry(name: str):
    try:
        pl = _loader()
        if pl is None:
            return None
        return (pl.registry or {}).get(name)
    except Exception:
        return None


def _plugin_enabled(name: str) -> bool:
    try:
        e = _plugin_entry(name)
        return bool(e and e.get("enabled"))
    except Exception:
        return False


def _plugin_dir(name: str) -> str:
    e = _plugin_entry(name) or {}
    d = e.get("_dir") or ""
    if d and os.path.isdir(d):
        return d
    # Fallback por convención (el registry manda; esto es último recurso).
    fb = os.path.join(_TVCAT_DIR, "plugins", name)
    return fb if os.path.isdir(fb) else ""


def _cfg_path() -> str:
    return os.path.join(_DATA_DIR, "indexator.json")


def _load_cfg() -> dict:
    cfg = {
        "index_topic": "TVCat-Index",
        "exclude_topics": ["General", "charla"],
        "noletras_mode": "separado",
        "norm_capital_first": False,
        "norm_capital_words": False,
        "norm_keep_upper": True,
        "norm_unaccent": False,
        "special_allow": "",
        "special_replace": "?",
        "header_template": "<b>Índice</b> ({total_all} títulos)",
        "body_template": "{letters}<b>{letter}</b> ({total})\n{entries}{index}. {title_link}\n{/letters}",
        "header_image": "",
        "show_tray": True,
    }
    try:
        if os.path.isfile(_cfg_path()):
            with open(_cfg_path(), "r", encoding="utf-8") as f:
                d = _json.load(f) or {}
            for k in cfg:
                if k in d:
                    cfg[k] = d[k]
    except Exception:
        pass
    return cfg


def _save_cfg(cfg: dict) -> dict:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_cfg_path(), "w", encoding="utf-8") as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


class ConfigUpdate(BaseModel):
    index_topic: Optional[str] = None
    exclude_topics: Optional[List[str]] = None
    noletras_mode: Optional[str] = None
    norm_capital_first: Optional[bool] = None
    norm_capital_words: Optional[bool] = None
    norm_keep_upper: Optional[bool] = None
    norm_unaccent: Optional[bool] = None
    special_allow: Optional[str] = None
    special_replace: Optional[str] = None
    header_template: Optional[str] = None
    body_template: Optional[str] = None
    header_image: Optional[str] = None
    show_tray: Optional[bool] = None


# ─── Motor de plantilla (F2) ──────────────────────────────────────────
# Límites Telegram: texto 4096, caption con imagen 1024.
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"__(.+?)__")
_MD_CODE = re.compile(r"`(.+?)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _plain_len(s: str) -> int:
    """Longitud visible (sin tags de formato propio)."""
    s = _MD_BOLD.sub(r"\1", s)
    s = _MD_ITALIC.sub(r"\1", s)
    s = _MD_CODE.sub(r"\1", s)
    s = _MD_LINK.sub(r"\1", s)
    s = re.sub(r"\{img:[^}]*\}", "", s)
    return len(s)


def _resolve_entities(text: str):
    """Mini-sintaxis **bold** __italic__ `code` [txt](url) → (texto, entidades MTProto).

    Devuelve (clean_text, entities) con offsets sobre el texto limpio.
    Las entidades usan dicts serializables (el llamador las convierte al tipo
    de cliente: telethon MessageEntity* / pyro raw types).
    """
    out = []
    ents = []

    def _push(seg, kind=None, url=None):
        if not seg:
            return
        start = sum(len(x) for x in out)
        out.append(seg)
        if kind:
            e = {"offset": start, "length": len(seg), "type": kind}
            if url:
                e["url"] = url
            ents.append(e)

    # Links primero (pueden contener ** dentro).
    parts = _MD_LINK.split(text)
    for i, part in enumerate(parts):
        if i % 3 == 0:
            _resolve_inline(part, _push)
        elif i % 3 == 1:
            _link_txt = part
            _link_url = parts[i + 1] if i + 1 < len(parts) else ""
            _push(_link_txt, "text_url", _link_url)
    return "".join(out), ents


def _resolve_inline(seg: str, push):
    import re as _re2
    # Orden: code > bold > italic (no anidados).
    tokens = _re2.split(r"(\*\*.+?\*\*|__.+?__|`[^`]+?`)", seg)
    for t in tokens:
        if t.startswith("**") and t.endswith("**") and len(t) > 4:
            push(t[2:-2], "bold")
        elif t.startswith("__") and t.endswith("__") and len(t) > 4:
            push(t[2:-2], "italic")
        elif t.startswith("`") and t.endswith("`") and len(t) > 2:
            push(t[1:-1], "code")
        else:
            push(t)


def _norm_text(s: str, cfg: dict) -> str:
    """Normalización SOLO render (no muta datos)."""
    import unicodedata
    t = s or ""
    if cfg.get("norm_unaccent"):
        t = "".join(c for c in unicodedata.normalize("NFD", t)
                     if unicodedata.category(c) != "Mn")
    allow = cfg.get("special_allow") or ""
    repl = cfg.get("special_replace", "?")
    if repl is None:
        repl = "?"
    if allow or repl:
        keep = set(allow)
        buf = []
        for ch in t:
            o = ord(ch)
            if o < 128 or ch in keep or ch in ("🗓",):
                buf.append(ch)
            else:
                buf.append(repl)
        t = "".join(buf)
    words = t.split(" ")
    if cfg.get("norm_capital_words"):
        keep_up = bool(cfg.get("norm_keep_upper", True))
        out = []
        for w in words:
            if not w:
                out.append(w)
                continue
            if keep_up and w.isupper() and len(w) > 1:
                out.append(w)
            else:
                out.append(w[:1].upper() + w[1:])
        t = " ".join(out)
    elif cfg.get("norm_capital_first") and t:
        t = t[:1].upper() + t[1:]
    return t


def _letter_key(title: str, cfg: dict) -> str:
    t = (title or "").strip()
    if not t:
        return "#"
    ch = t[0]
    if cfg.get("noletras_mode") == "hash" and not ch.isalpha():
        return "#"
    return ch


def _topic_url(channel_id: str, topic_id: int) -> str:
    bare = str(channel_id or "").lstrip("-")
    if bare.startswith("100"):
        bare = bare[3:]
    return f"https://t.me/c/{bare}/{int(topic_id)}"


def build_parts(channel_id: str, topics: list, cfg: dict, header: str = None,
                body: str = None) -> dict:
    """Agrupa topics por letra y parte el render en chunks con presupuesto.
    Retorna {parts: [{text, entities, images, letter, letter_end, part, parts}],
    total_all, letters}. Sin efectos laterales (preview y generate comparten)."""
    header = cfg.get("header_template", "") if header is None else (header or "")
    body = cfg.get("body_template", "") if body is None else (body or "")
    total_all = len(topics)
    # Exclusiones (case-insensitive) + auto-excluir el índice.
    excl = {str(x or "").strip().lower() for x in (cfg.get("exclude_topics") or [])}
    idx_name = str(cfg.get("index_topic") or "TVCat-Index").strip().lower()
    excl.add(idx_name)
    usable = [t for t in (topics or [])
              if str(t.get("title") or "").strip().lower() not in excl]
    # Orden alfabético por título mostrado en crudo + global_index.
    usable.sort(key=lambda t: str(t.get("title") or ""))
    for gi, t in enumerate(usable, 1):
        t["_gi"] = gi
    # Grupos por letra (primer carácter verbatim).
    groups = {}
    order = []
    for t in usable:
        lk = _letter_key(str(t.get("title") or ""), cfg)
        if lk not in groups:
            groups[lk] = []
            order.append(lk)
        t["_letter"] = lk
        groups[lk].append(t)

    def _ctx_global():
        return {"total_all": str(total_all)}

    def _render_entry(tpl: str, t: dict, idx_in_letter: int) -> str:
        title = _norm_text(str(t.get("title") or ""), cfg)
        url = _topic_url(channel_id, t.get("id"))
        year = ""
        if "🗓" in str(t.get("title") or ""):
            year = str(t.get("title")).rsplit("🗓", 1)[-1].strip()
        rep = {
            "{index}": str(idx_in_letter),
            "{global_index}": str(t.get("_gi", "")),
            "{title}": title,
            "{title_link}": f"[{title}]({url})",
            "{url}": url,
            "{year}": year,
            "{letter}": t.get("_letter", ""),
        }
        out = tpl
        for k, v in rep.items():
            out = out.replace(k, v)
        return out

    def _split_letters_block(tpl: str, entries_tpl: str, letters_here: list) -> list:
        """Renderiza el bloque {letters} por letra. El contenido del bloque
        {entries} se IGNORA (la plantilla de entrada va en entries_tpl):
        solo marca dónde van las entradas. Devuelve (letter, texto)."""
        m = re.search(r"\{letters\}(.*?)\{/letters\}", tpl, re.DOTALL)
        if not m:
            return [(None, tpl)]
        inner = m.group(1)
        # Posición del bloque (se sustituye por las entradas ya renderizadas).
        # La plantilla de entrada viaja en entries_tpl (parámetro); el bloque
        # {entries} solo marca la posición (su contenido se ignora).
        em = re.search(r"\{entries\}.*?\{\/entries\}", inner, re.DOTALL)
        chunks = []
        for lk in letters_here:
            rendered = []
            for i, t in enumerate(groups[lk], 1):
                rendered.append(_render_entry(entries_tpl, t, i))
            # Cabecera de letra: inner hasta el bloque + total (sin duplicar).
            head = (inner[:em.start()] if em else inner).rstrip("\n")
            head = head.replace("{letter}", lk).replace("{total}", str(len(groups[lk])))
            for k, v in _ctx_global().items():
                head = head.replace("{entries}", "").replace("{%s}" % k, v)
            chunks.append((lk, head, rendered))
        # Reconstruir por letra: prefijo + cabecera + entradas + sufijo
        # (prefijo/sufijo = lo de fuera del bloque, ya con tags globales).
        # El cuerpo se SUSTITUYE por el render: el bloque {letters} ya cumplió
        # (las entradas van renderizadas, no el texto original).
        prefix = tpl[:m.start()]
        suffix = tpl[m.end():]
        for k, v in _ctx_global().items():
            prefix = prefix.replace("{entries}", "").replace("{%s}" % k, v)
            suffix = suffix.replace("{entries}", "").replace("{%s}" % k, v)
        out = []
        for lk, h, r in chunks:
            out.append((lk, prefix + h + ("\n" if h and r else "") + "\n".join(r) + suffix))
        return out

    # Plantilla de entrada: {entries}...{/entries} a nivel de cuerpo.
    # Si el cuerpo NO trae bloque letters pero SÍ entries, las entradas se
    # renderizan con esa plantilla y el resto del cuerpo queda literal.
    bem = re.search(r"\{entries\}(.*?)\{/entries\}", body, re.DOTALL)
    entries_tpl = bem.group(1) if bem else "{index}. {title_link}"
    has_letters = "{letters}" in body
    # Si no hay bloque letters: un solo grupo con todo (lista simple).
    if not has_letters:
        rendered_all = []
        for lk in order:
            for i, t in enumerate(groups[lk], 1):
                rendered_all.append(_render_entry(entries_tpl, t, i))
        if bem:
            core = (body[:bem.start()] + "\n".join(rendered_all) + body[bem.end():]).replace("{entries}", "")
        else:
            core = body + ("\n" if body and not body.endswith("\n") else "") + "\n".join(rendered_all)
        for k, v in _ctx_global().items():
            core = core.replace("{%s}" % k, v)
        letter_chunks = [(None, core)]
    else:
        letter_chunks = []
        for lk, text in _split_letters_block(body, entries_tpl, order):
            letter_chunks.append((lk, text))

    # Partir cada chunk por presupuesto (con/sin imagen).
    parts = []
    n_letter_chunks = len(letter_chunks)
    for lk, text in letter_chunks:
        # Imágenes del chunk: {img:file} (primera que resuelva; sin álbum).
        imgs = re.findall(r"\{img:([^}]+)\}", text)
        img = ""
        for cand in imgs:
            name = cand.replace("{letter}", lk or "").replace("{currentletter}", lk or "")
            p = _resolve_image(name)
            if p:
                img = p
                break
        clean = re.sub(r"\{img:[^}]*\}", "", text).strip()
        limit = CAPTION_LIMIT if img else TEXT_LIMIT
        # Partir por líneas sin romper entradas (corte por longitud visible).
        lines = clean.split("\n")
        cur, cur_len = [], 0
        buckets = []
        for ln in lines:
            ln_len = _plain_len(ln) + 1
            if cur and cur_len + ln_len > limit:
                buckets.append(cur)
                cur, cur_len = [], 0
            cur.append(ln)
            cur_len += ln_len
        if cur:
            buckets.append(cur)
        nb = len(buckets)
        for bi, blines in enumerate(buckets, 1):
            chunk_text = "\n".join(blines).strip()
            # {part}/{parts}/{currentletter}/{currentletterend}/{total}
            chunk_letters = [lk] if lk else []
            first_l = chunk_letters[0] if chunk_letters else ""
            last_l = chunk_letters[-1] if chunk_letters else ""
            # Si el chunk agrupa varias letras (lista simple), deducir del texto.
            if not lk:
                seen = []
                for _t in usable:
                    _l = _t.get("_letter", "")
                    if _l and _l not in seen:
                        seen.append(_l)
                # Aproximación: primera/última letra global del índice.
                if seen:
                    first_l, last_l = seen[0], seen[-1]
            chunk_text = chunk_text.replace("{part}", str(bi)).replace("{parts}", str(nb))
            chunk_text = chunk_text.replace("{currentletter}", first_l).replace("{currentletterend}", last_l)
            chunk_text = chunk_text.replace("{total}", str(len(groups.get(lk, []) or usable)) if lk else str(total_all))
            chunk_text = re.sub(r"\{entries\}", "", chunk_text)
            for k, v in _ctx_global().items():
                chunk_text = chunk_text.replace("{%s}" % k, v)
            clean_text, entities = _resolve_entities(chunk_text)
            parts.append({
                "text": clean_text, "entities": entities,
                "images": [img] if (img and bi == 1) else [],
                "letter": lk or first_l, "letter_end": last_l,
                "part": bi, "parts": nb,
            })
    # Cabecera global (no repetible): se antepone a la primera parte.
    htext = (header or "").strip()
    if htext and parts:
        for k, v in _ctx_global().items():
            htext = htext.replace("{%s}" % k, v)
        hclean, hents = _resolve_entities(htext)
        # La cabecera va como primera parte propia si trae imagen, si no se
        # fusiona con la primera parte cuando quepa.
        himgs = re.findall(r"\{img:([^}]+)\}", htext)
        himg = ""
        for cand in himgs:
            p = _resolve_image(cand)
            if p:
                himg = p
                break
        hclean = re.sub(r"\{img:[^}]*\}", "", hclean).strip()
        if himg or _plain_len(hclean) + 1 + _plain_len(parts[0]["text"]) + 1 > (CAPTION_LIMIT if (himg or parts[0]["images"]) else TEXT_LIMIT):
            parts.insert(0, {"text": hclean, "entities": hents,
                             "images": [himg] if himg else [],
                             "letter": "", "letter_end": "",
                             "part": 0, "parts": 0})
        else:
            parts[0]["text"] = (hclean + "\n" + parts[0]["text"]).strip()
            parts[0]["entities"] = hents + [
                {"offset": e["offset"] + len(hclean) + 1, "length": e["length"],
                 "type": e["type"], **({"url": e["url"]} if e.get("url") else {})}
                for e in parts[0]["entities"]
            ]
            if himg and not parts[0]["images"]:
                parts[0]["images"] = [himg]
    return {"parts": parts, "total_all": total_all, "letters": order}


def _resolve_image(name: str) -> str:
    """Resuelve una imagen del static del plugin o de packs. "" si falta."""
    name = (name or "").strip().lstrip("/").replace("\\", "/")
    if not name or ".." in name:
        return ""
    cands = [
        os.path.join(_PLUGIN_DIR, "static", name),
        os.path.join(_DATA_DIR, "packs", name),
    ]
    # packs/<pack>/<file>
    try:
        pdir = os.path.join(_DATA_DIR, "packs")
        if os.path.isdir(pdir):
            for pack in sorted(os.listdir(pdir)):
                fp = os.path.join(pdir, pack, os.path.basename(name))
                if os.path.isfile(fp):
                    return fp
    except Exception:
        pass
    for p in cands:
        if os.path.isfile(p):
            return p
    return ""


class PreviewReq(BaseModel):
    channel_id: str = ""
    header: Optional[str] = None
    body: Optional[str] = None


class GenerateReq(BaseModel):
    channel_id: str = ""
    header: Optional[str] = None
    body: Optional[str] = None


@router.post("/api/indexator/preview")
async def preview_index(request: Request, body: PreviewReq):
    _require_user(request)
    if not body.channel_id:
        raise HTTPException(400, "channel_id requerido")
    cfg = _load_cfg()
    try:
        from services.telegram_service import get_telegram_service
        svc = get_telegram_service()
        items = await svc.list_forum_topics(str(body.channel_id))
    except Exception as e:
        raise HTTPException(502, f"No se pudieron listar topics: {e}")
    topics = [{"id": int(t.get("id")), "title": t.get("title") or ""}
              for t in (items or []) if t.get("id")]
    res = build_parts(str(body.channel_id), topics, cfg,
                      header=body.header, body=body.body)
    prev = []
    for p in res["parts"]:
        prev.append({k: p[k] for k in ("text", "letter", "letter_end", "part", "parts")
                     } | {"images": [os.path.basename(i) for i in p["images"]],
                          "entities": len(p["entities"]), "chars": len(p["text"])})
    return {"parts": prev, "total_all": res["total_all"], "letters": res["letters"],
            "full": [{"text": p["text"], "entities": p["entities"],
                      "images": p["images"]} for p in res["parts"]]}


@router.post("/api/indexator/generate")
async def generate_index(request: Request, body: GenerateReq):
    _require_user(request)
    if not body.channel_id:
        raise HTTPException(400, "channel_id requerido")
    cfg = _load_cfg()
    try:
        from services.telegram_service import get_telegram_service
        svc = get_telegram_service()
        items = await svc.list_forum_topics(str(body.channel_id))
    except Exception as e:
        raise HTTPException(502, f"No se pudieron listar topics: {e}")
    topics = [{"id": int(t.get("id")), "title": t.get("title") or ""}
              for t in (items or []) if t.get("id")]
    res = build_parts(str(body.channel_id), topics, cfg,
                      header=body.header, body=body.body)
    # Topic índice: buscar o crear.
    idx_name = str(cfg.get("index_topic") or "TVCat-Index")
    idx_id = None
    for t in topics:
        if str(t.get("title") or "").strip().lower() == idx_name.strip().lower():
            idx_id = int(t["id"])
            break
    try:
        if idx_id is None:
            idx_id = await svc.create_forum_topic(str(body.channel_id), idx_name)
            idx_id = int(idx_id) if idx_id else None
    except Exception as e:
        raise HTTPException(502, f"No se pudo crear el topic índice: {e}")
    if not idx_id:
        raise HTTPException(502, "Sin topic índice (¿permisos?)")
    # Vaciar (DeleteTopicHistory raw; telethon/peers según cliente).
    try:
        await _clear_topic(svc, str(body.channel_id), int(idx_id))
    except Exception as e:
        raise HTTPException(502, f"No se pudo vaciar el índice (¿permiso de borrado?): {e}")
    # Postear partes.
    posted = []
    try:
        for p in res["parts"]:
            mid = await _post_part(svc, str(body.channel_id), int(idx_id), p)
            posted.append(mid)
    except Exception as e:
        raise HTTPException(502, f"Fallo posteando (subidas {len(posted)}): {e}")
    return {"success": True, "topic_id": idx_id, "posted": posted,
            "parts": len(res["parts"]), "total_all": res["total_all"]}


async def _clear_topic(svc, channel_id: str, topic_id: int):
    """Vacía un topic (DeleteTopicHistory). Nunca toca otros topics."""
    # Vía pool central con el cliente preferido: intentamos pyro raw y
    # telethon request; el servicio expone _get_temp_or_pool_client.
    chan = int(channel_id)
    # 1) pyro raw
    try:
        from services.userbot_service import get_active_client
        wrapper = await get_active_client("pyrogram")
        raw = getattr(wrapper, "_client", None)
        if raw is not None:
            from pyrogram.raw import functions as _rf
            try:
                peer = await raw.resolve_peer(chan)
            except Exception:
                peer = chan
            await raw.invoke(_rf.channels.DeleteTopicHistory(
                channel=peer, top_msg_id=int(topic_id)))
            return
    except Exception as e:
        print(f"[Indexator] DeleteTopicHistory pyro: {e}", flush=True)
    # 2) telethon request
    try:
        from services.userbot_service import get_active_client as _gac2
        wrapper = await _gac2("telethon")
        raw = getattr(wrapper, "_client", None)
        if raw is not None:
            from telethon.tl.functions.channels import DeleteTopicHistoryRequest
            await raw(DeleteTopicHistoryRequest(
                channel=chan, top_msg_id=int(topic_id)))
            return
    except Exception as e:
        print(f"[Indexator] DeleteTopicHistory telethon: {e}", flush=True)
        raise RuntimeError(f"Sin método de vaciado disponible: {e}")


async def _post_part(svc, channel_id: str, topic_id: int, part: dict):
    """Postea una parte (texto o foto+caption) dentro del topic índice."""
    text = part.get("text") or ""
    images = part.get("images") or []
    entities = part.get("entities") or []
    # El servicio send_* no acepta entidades custom: enviamos markdown
    # equivalente reconstruido (solo bold/italic/code/link que generamos).
    md = _entities_to_markdown(text, entities)
    if images:
        with open(images[0], "rb") as f:
            blob = f.read()
        # caption 1024: ya presupuestado en build_parts.
        return await svc.send_photo(str(channel_id), photo_bytes=blob,
                                    caption=md[:CAPTION_LIMIT],
                                    reply_to_msg_id=int(topic_id))
    # En topic: reply al id del topic (los topics direccionan por reply).
    return await svc.send_text(str(channel_id), text=md[:TEXT_LIMIT],
                               reply_to_msg_id=int(topic_id))


def _entities_to_markdown(text: str, entities: list) -> str:
    """Reconstruye markdown Telegram desde nuestras entidades (sin solapes)."""
    if not entities:
        return text
    ents = sorted(entities, key=lambda e: (e.get("offset", 0), -(e.get("length", 0))))
    out = []
    pos = 0
    for e in ents:
        try:
            st, ln = int(e.get("offset", 0)), int(e.get("length", 0))
        except Exception:
            continue
        if st < pos:
            continue
        out.append(text[pos:st])
        seg = text[st:st + ln]
        t = e.get("type")
        if t == "bold":
            out.append(f"**{seg}**")
        elif t == "italic":
            out.append(f"__{seg}__")
        elif t == "code":
            out.append(f"`{seg}`")
        elif t == "text_url" and e.get("url"):
            out.append(f"[{seg}]({e['url']})")
        else:
            out.append(seg)
        pos = st + ln
    out.append(text[pos:])
    return "".join(out)


class PackUpload(BaseModel):
    name: str = ""
    filename: str = ""
    content_b64: str = ""


@router.post("/api/indexator/packs/upload")
async def upload_pack(body: PackUpload, request: Request):
    _require_user(request)
    name = re.sub(r"[^a-z0-9_-]", "", (body.name or "").strip().lower())
    if not name:
        raise HTTPException(400, "nombre de pack requerido")
    if not (body.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "solo .zip")
    import base64
    import zipfile
    import io as _io
    try:
        raw = base64.b64decode(body.content_b64 or "")
    except Exception:
        raise HTTPException(400, "zip inválido")
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(400, "zip mayor de 50MB")
    dest = os.path.join(_DATA_DIR, "packs", name)
    os.makedirs(dest, exist_ok=True)
    try:
        zf = zipfile.ZipFile(_io.BytesIO(raw))
        saved = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            if not base.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            if ".." in base or "/" in base or "\\" in base:
                continue
            with zf.open(info) as fh:
                data = fh.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                continue
            with open(os.path.join(dest, base), "wb") as f:
                f.write(data)
            saved.append(base)
    except Exception as e:
        raise HTTPException(400, f"zip inválido: {e}")
    return {"success": True, "pack": name, "images": sorted(saved)}


@router.get("/api/indexator/ping")
async def ping():
    return {"ok": True, "deps": {
        "tgindex": _plugin_enabled("tvcat_tgindex"),
        "tghirayi_v2": _plugin_enabled("tvcat_TGHirayi_v2"),
    }}


@router.get("/api/indexator/channels")
async def list_channels(request: Request):
    _require_user(request)
    out = []
    # Fuentes tgindex (canales con acceso).
    if _plugin_enabled("tvcat_tgindex"):
        try:
            tdir = _plugin_dir("tvcat_tgindex")
            db = os.path.join(tdir, "data", "tvcat.db")
            if os.path.isfile(db):
                conn = sqlite3.connect(db, timeout=10)
                conn.row_factory = sqlite3.Row
                cols = [r[1] for r in conn.execute("PRAGMA table_info(tvcat_scanned_channels)").fetchall()]
                if cols:
                    sel = []
                    for want in ("id", "channel_id", "display_name", "title", "name", "topology_type"):
                        if want in cols:
                            sel.append(want)
                    rows = conn.execute(
                        f"SELECT {', '.join(sel)} FROM tvcat_scanned_channels").fetchall()
                    for r in rows:
                        d = dict(r)
                        out.append({
                            "kind": "fuente",
                            "id": f"tgindex:{d.get('id')}",
                            "name": d.get("display_name") or d.get("title") or d.get("name") or d.get("channel_id"),
                            "channel_id": str(d.get("channel_id") or ""),
                            "topology": d.get("topology_type"),
                        })
                conn.close()
        except Exception as e:
            print(f"[Indexator] canales tgindex: {e}", flush=True)
    # Destinos TGHirayi_v2.
    if _plugin_enabled("tvcat_TGHirayi_v2"):
        try:
            hdir = _plugin_dir("tvcat_TGHirayi_v2")
            jf = os.path.join(hdir, "data", "TGHirayi_v2.json")
            if os.path.isfile(jf):
                with open(jf, "r", encoding="utf-8") as f:
                    jd = _json.load(f) or {}
                for did, d in ((jd.get("destinations") or {}).items()):
                    if not isinstance(d, dict):
                        continue
                    out.append({
                        "kind": "destino",
                        "id": f"tghirayi:{did}",
                        "name": d.get("name") or did,
                        "channel_id": str(d.get("channel_id") or ""),
                        "topology": d.get("topology"),
                    })
        except Exception as e:
            print(f"[Indexator] destinos tghirayi: {e}", flush=True)
    missing = []
    if not _plugin_enabled("tvcat_tgindex"):
        missing.append("tvcat_tgindex")
    if not _plugin_enabled("tvcat_TGHirayi_v2"):
        missing.append("tvcat_TGHirayi_v2")
    return {"channels": out, "missing": missing}


@router.get("/api/indexator/topics")
async def list_topics(request: Request, channel_id: str = ""):
    """Topics EN VIVO del canal (refresco: otras fuentes pueden haber creado)."""
    _require_user(request)
    if not channel_id:
        raise HTTPException(400, "channel_id requerido")
    try:
        from services.telegram_service import get_telegram_service
        svc = get_telegram_service()
        items = await svc.list_forum_topics(str(channel_id))
    except Exception as e:
        raise HTTPException(502, f"No se pudieron listar topics: {e}")
    return {"topics": [{"id": int(t.get("id")), "title": t.get("title") or ""}
                        for t in (items or []) if t.get("id")],
            "count": len(items or [])}


@router.get("/api/indexator/config")
async def get_config(request: Request):
    _require_user(request)
    cfg = _load_cfg()
    packs = []
    try:
        pdir = os.path.join(_DATA_DIR, "packs")
        if os.path.isdir(pdir):
            for name in sorted(os.listdir(pdir)):
                fp = os.path.join(pdir, name)
                if os.path.isdir(fp):
                    imgs = sorted(f for f in os.listdir(fp)
                                  if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
                    packs.append({"name": name, "images": imgs})
    except Exception:
        pass
    return {"config": cfg, "packs": packs,
            "deps": {"tgindex": _plugin_enabled("tvcat_tgindex"),
                     "tghirayi_v2": _plugin_enabled("tvcat_TGHirayi_v2")}}


@router.put("/api/indexator/config")
async def save_config(body: ConfigUpdate, request: Request):
    _require_user(request)
    cfg = _load_cfg()
    data = body.dict(exclude_unset=True)
    for k, v in data.items():
        if k in cfg and v is not None:
            cfg[k] = v
    _save_cfg(cfg)
    return {"success": True, "config": cfg}
