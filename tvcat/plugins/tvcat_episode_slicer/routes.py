"""
tvcat_episode_slicer — Plugin heropage-action para cortar episodios.

Spec 2026-09-15 (Episode Slicer):
- Split-move estilo TGHirayi desde episodio 2.
- Titulo auto + hereda cat/sub; cover heredado.
- Mismo source='scan_X' => vida ligada al scan-item.
- Tabla slicer_cuts + re-apply post-parse (F2).

Endpoints (router auto-montado por plugin_loader):
- GET  /api/slicer/ping
- POST /api/slicer/preview {item_id, from_msg_id}
- POST /api/slicer/split   {item_id, from_msg_id}
- POST /api/slicer/unsplit {new_item_id}
- GET  /api/slicer/cuts?source=scan_X
"""
import os
import re
import sys
import time
import sqlite3

_TVCAT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TVCAT_DIR not in sys.path:
    sys.path.insert(0, _TVCAT_DIR)

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _tgindex_db_path() -> str:
    try:
        from plugins.tvcat_tgindex.scanner import get_plugin_db_path as _p
        return _p()
    except Exception:
        return os.path.join(_TVCAT_DIR, "plugins", "tvcat_tgindex", "data", "tvcat.db")


def _connect_plugin_db():
    path = _tgindex_db_path()
    if not os.path.exists(path):
        raise HTTPException(404, f"DB tgindex no encontrada: {path}")
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_slicer_table(conn=None):
    close = False
    if conn is None:
        conn = _connect_plugin_db()
        close = True
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS slicer_cuts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source TEXT NOT NULL,
              orig_item_id TEXT NOT NULL,
              new_item_id TEXT NOT NULL,
              cut_msg_id INTEGER NOT NULL,
              created INTEGER DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_slicer_source ON slicer_cuts(source)")
        conn.commit()
    finally:
        if close:
            try:
                conn.close()
            except Exception:
                pass


def _norm_flat(title: str) -> str:
    try:
        flat = re.sub(r"[^a-zA-Z0-9]", "", (title or "")).lower()
        return flat or "cut"
    except Exception:
        return "cut"


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


def _load_title(conn, item_id: str):
    row = conn.execute("SELECT * FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
    if row:
        return dict(row)
    # fallback por id interno (bug scanner: item_episodes guarda id INTEGER)
    try:
        row = conn.execute("SELECT * FROM unified_catalog WHERE id=?", (item_id,)).fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    return None


def _load_episodes(conn, cat_row: dict):
    vid = cat_row.get("item_id")
    iid = str(cat_row.get("id"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(item_episodes)").fetchall()]
    order = "episode_number ASC" if "episode_number" in cols else "telegram_msg_id ASC"
    rows = conn.execute(
        f"SELECT * FROM item_episodes WHERE item_id=? OR item_id=? ORDER BY {order}",
        (vid, iid)).fetchall()
    return [dict(r) for r in rows]


class PreviewReq(BaseModel):
    item_id: str
    from_msg_id: int


class SplitReq(BaseModel):
    item_id: str
    from_msg_id: int


class UnsplitReq(BaseModel):
    new_item_id: str


class ResyncReq(BaseModel):
    source: Optional[str] = None


def _fictitious_anchor(orig_link: str, from_msg_id: int, first_move_link: str = "") -> tuple:
    """Ancla ficticia tipo topo 4 para la parte nueva de un corte.

    La parte nueva NO hereda el ancla del original: compartir telegram_link/msg
    comparte la clave de cover (channelid_msgid) y editar una editaría ambas.
    Se usa el sentinela -1000 + link al primer episodio movido => clave propia,
    cover genérico por categoría hasta que se edite (igual que topo 4).
    Retorna (telegram_msg_id, telegram_link).
    """
    link = (first_move_link or "").strip()
    if not link:
        import re as _re
        m = _re.search(r"(https://t\.me/c/\d+(?:/\d+)?/)\d+", orig_link or "")
        link = f"{m.group(1)}{int(from_msg_id)}" if m else (orig_link or "")
    return (-1000, link)


def _build_proposal(cat: dict, eps: list, from_msg_id: int) -> dict:
    if len(eps) < 2:
        raise HTTPException(400, "El título necesita al menos 2 episodios para cortar")
    idx = next((i for i, e in enumerate(eps) if int(e.get("telegram_msg_id") or 0) == int(from_msg_id)), -1)
    if idx < 0:
        raise HTTPException(400, "Ese episodio no pertenece a este título (¿variante fusionada? recarga y reintenta)")
    if idx <= 0:
        raise HTTPException(400, "Corte inválido: debe ser desde el episodio 2 en adelante")
    keep = eps[:idx]
    move = eps[idx:]
    first = move[0]
    new_title = (first.get("file_name") or first.get("title") or first.get("caption") or "Corte")
    new_title = os.path.splitext(str(new_title))[0][:80]
    _fic_mid, _fic_link = _fictitious_anchor(cat.get("telegram_link") or "", int(from_msg_id), str(first.get("telegram_link") or ""))
    return {
        "orig": {"item_id": cat.get("item_id"), "title": cat.get("title"),
                 "keep": len(keep), "total": len(eps)},
        "new": {"title": new_title,
                "category": cat.get("category", ""),
                "subcategory": cat.get("subcategory", ""),
                "count": len(move),
                "cover_msg_id": _fic_mid,
                "cover_link": _fic_link,
                "from_msg_id": int(from_msg_id)},
        "keep_msg_ids": [int(e.get("telegram_msg_id")) for e in keep],
        "move_msg_ids": [int(e.get("telegram_msg_id")) for e in move],
    }


@router.get("/api/slicer/ping")
async def ping():
    return {"ok": True, "plugin": "tvcat_episode_slicer"}


def _get_loader():
    """Resuelve la instancia PluginLoader del gateway en ejecución.

    NO importa ningún módulo `gateway` por nombre: según el lanzador el
    gateway vive como `__main__` o como `tvcat.gateway`, e importar por
    nombre duplica el módulo (instancia sin registry). Se busca la
    instancia real barriendo sys.modules (mismo patrón que
    `gateway._plugin_refresher`).
    Devuelve (loader, cómo) o (None, motivo).
    """
    import sys as _sys
    main = _sys.modules.get("__main__")
    cand = getattr(main, "_plugin_loader", None)
    if cand is not None and type(cand).__name__ == "PluginLoader":
        return cand, "__main__._plugin_loader"
    for _name, _mod in list(_sys.modules.items()):
        try:
            _l = getattr(_mod, "_plugin_loader", None)
        except Exception:
            continue
        if _l is not None and type(_l).__name__ == "PluginLoader":
            return _l, f"{_name}._plugin_loader"
    return None, "no hay instancia PluginLoader en sys.modules"


def _refresh_central(tag: str, verify_item_id=None):
    """Un único camino robusto: sync() del módulo tgindex que usa el loader
    + sync_plugin_cache del core con ese mismo loader + verificación en
    central del título esperado.

    Devuelve (ok, detail). No lanza.
    """
    import traceback
    loader, how = _get_loader()
    if loader is None:
        return False, f"loader: {how}"
    try:
        sync_mod = (loader.registry.get("tvcat_tgindex") or {}).get("_sync_module")
    except Exception as ex:
        return False, f"registry tgindex: {ex}"
    if sync_mod is None or not hasattr(sync_mod, "sync"):
        return False, "tgindex sin _sync_module.sync en el registry (¿plugin deshabilitado?)"
    try:
        sync_mod.sync()
    except Exception as ex:
        print(f" [SLICER] tgindex sync() falló: {ex}\n{traceback.format_exc(limit=5)}")
        return False, f"tgindex sync(): {ex}"
    try:
        if _TVCAT_DIR not in sys.path:
            sys.path.insert(0, _TVCAT_DIR)
        from services.catalog_service import sync_plugin_cache, get_conn
        sync_plugin_cache(loader, "tvcat_tgindex")
    except Exception as ex:
        print(f" [SLICER] sync_plugin_cache falló: {ex}\n{traceback.format_exc(limit=5)}")
        return False, f"sync_plugin_cache: {ex}"
    if verify_item_id:
        try:
            c = get_conn()
            try:
                n = c.execute("SELECT COUNT(*) FROM unified_catalog WHERE item_id=?",
                              (verify_item_id,)).fetchone()[0]
            finally:
                try:
                    c.close()
                except Exception:
                    pass
            if not n:
                return False, (f"central sin {verify_item_id} tras sync "
                               f"(loader por {how}; ver log [TGINDEX SYNC])")
            return True, f"central OK ({how}, verificado {verify_item_id})"
        except Exception as ex:
            return False, f"verificación central: {ex}"
    return True, f"central OK ({how})"


@router.post("/api/slicer/preview")
async def preview(body: PreviewReq, request: Request):
    _require_user(request)
    conn = _connect_plugin_db()
    try:
        cat = _load_title(conn, body.item_id)
        if not cat:
            raise HTTPException(404, "Título no encontrado en tgindex")
        eps = _load_episodes(conn, cat)
        return _build_proposal(cat, eps, body.from_msg_id)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.post("/api/slicer/split")
async def split(body: SplitReq, request: Request):
    _require_user(request)
    conn = _connect_plugin_db()
    try:
        _ensure_slicer_table(conn)
        cat = _load_title(conn, body.item_id)
        if not cat:
            raise HTTPException(404, "Título no encontrado en tgindex")

        # Idempotencia PRIMERO (antes de validar episodios): si el corte ya
        # existe, reintenta el refresco de central y devuelve el existente.
        # Es la vía de recuperación cuando el split guardó pero la central falló.
        dup = conn.execute(
            "SELECT new_item_id FROM slicer_cuts WHERE orig_item_id=? AND cut_msg_id=?",
            (cat.get("item_id"), int(body.from_msg_id))).fetchone()
        if dup:
            moved = conn.execute("SELECT COUNT(*) FROM item_episodes WHERE item_id=?",
                                 (dup["new_item_id"],)).fetchone()[0]
            central_ok, central_detail = _refresh_central(
                f"slicer split-retry {dup['new_item_id']}",
                verify_item_id=dup["new_item_id"])
            out = {"ok": True, "new_item_id": dup["new_item_id"],
                   "moved": moved, "reused": True, "central_refreshed": central_ok}
            if not central_ok:
                out["warn"] = ("Corte ya existía pero la central no se actualizó: " + central_detail)
            return out

        eps = _load_episodes(conn, cat)
        prop = _build_proposal(cat, eps, body.from_msg_id)

        source = cat.get("source") or ""
        if not source:
            raise HTTPException(400, "El título no tiene source (no es de un scan-item)")
        flat = _norm_flat(prop["new"]["title"])
        new_item_id = f"USER-{flat[:15]}-{int(body.from_msg_id)}"
        exists = conn.execute("SELECT id FROM unified_catalog WHERE item_id=?", (new_item_id,)).fetchone()
        if exists:
            raise HTTPException(409, f"Ya existe el título cortado {new_item_id}")

        now = int(time.time())
        cols = [r[1] for r in conn.execute("PRAGMA table_info(unified_catalog)").fetchall()]

        def _g(name, default=""):
            return cat.get(name, default) if name in cols else default

        # Columnas mínimas compatibles con esquemas viejos (solo las que existan)
        insert_cols = ["item_id", "title", "category", "subcategory", "description",
                       "telegram_msg_id", "telegram_link", "group_title",
                       "group_title_flat", "source", "sync_status", "sync_timestamp"]
        insert_cols = [c for c in insert_cols if c in cols]
        # Cover ficticio tipo topo 4 (sentinela -1000 + link al primer movido):
        # NO heredar el ancla del original o ambas partes compartirían cover.
        _cut_ep = next((e for e in eps if int(e.get("telegram_msg_id") or 0) == int(body.from_msg_id)), None)
        _fic_mid, _fic_link = _fictitious_anchor(
            cat.get("telegram_link") or "", int(body.from_msg_id),
            str((_cut_ep or {}).get("telegram_link") or ""))
        vals = {
            "item_id": new_item_id,
            "title": prop["new"]["title"],
            "category": prop["new"]["category"],
            "subcategory": prop["new"]["subcategory"],
            "description": cat.get("description", ""),
            "telegram_msg_id": _fic_mid,
            "telegram_link": _fic_link,
            "group_title": prop["new"]["title"],
            "group_title_flat": flat,
            "source": source,
            "sync_status": "active",
            "sync_timestamp": now,
        }
        ph = ",".join("?" * len(insert_cols))
        conn.execute(f"INSERT INTO unified_catalog ({','.join(insert_cols)}) VALUES ({ph})",
                     [vals[c] for c in insert_cols])
        new_int = conn.execute("SELECT id FROM unified_catalog WHERE item_id=?", (new_item_id,)).fetchone()["id"]

        # Mueve episodios >= cut (re-asigna item_id + renumera)
        move_ids = set(prop["move_msg_ids"])
        ep_cols = [r[1] for r in conn.execute("PRAGMA table_info(item_episodes)").fetchall()]
        has_ep_sync = "sync_status" in ep_cols
        n = 0
        for e in eps:
            if int(e.get("telegram_msg_id") or 0) in move_ids:
                n += 1
                sets = ["item_id=?", "episode_number=?"]
                args = [new_item_id, n]
                if has_ep_sync:
                    sets.append("sync_status=?")
                    args.append("active")
                args.append(e["id"])
                conn.execute(f"UPDATE item_episodes SET {','.join(sets)} WHERE id=?", args)
        # Reordena el original que queda
        k = 0
        for e in eps:
            if int(e.get("telegram_msg_id") or 0) not in move_ids:
                k += 1
                try:
                    conn.execute("UPDATE item_episodes SET episode_number=? WHERE id=?", (k, e["id"]))
                except Exception:
                    pass

        conn.execute(
            "INSERT INTO slicer_cuts (source, orig_item_id, new_item_id, cut_msg_id, created) VALUES (?,?,?,?,?)",
            (source, cat.get("item_id"), new_item_id, int(body.from_msg_id), now))
        conn.commit()

        # Refresca export + central (igual que toggle: sync + sync_plugin_cache).
        # Si falla, el corte YA está guardado: se reintenta con POST /resync.
        central_ok, central_detail = _refresh_central(
            f"slicer split {new_item_id}", verify_item_id=new_item_id)

        _ = new_int
        out = {"ok": True, "new_item_id": new_item_id, "moved": n,
               "central_refreshed": central_ok}
        if not central_ok:
            out["warn"] = ("Corte guardado pero la central no se actualizó: " + central_detail
                           + ". Usa Re-sincronizar o reinicia el gateway.")
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.post("/api/slicer/unsplit")
async def unsplit(body: UnsplitReq, request: Request):
    _require_user(request)
    conn = _connect_plugin_db()
    try:
        cut = conn.execute("SELECT * FROM slicer_cuts WHERE new_item_id=?", (body.new_item_id,)).fetchone()
        if not cut:
            raise HTTPException(404, "Corte no registrado")
        cut = dict(cut)
        orig = _load_title(conn, cut["orig_item_id"])
        newc = _load_title(conn, cut["new_item_id"])
        if not orig or not newc:
            raise HTTPException(404, "Título origen o cortado no existe")
        eps_new = _load_episodes(conn, newc)
        eps_orig = _load_episodes(conn, orig)
        base = len(eps_orig)
        for i, e in enumerate(eps_new, start=1):
            conn.execute("UPDATE item_episodes SET item_id=?, episode_number=? WHERE id=?",
                         (orig.get("item_id"), base + i, e["id"]))
        conn.execute("DELETE FROM unified_catalog WHERE item_id=?", (cut["new_item_id"],))
        conn.execute("DELETE FROM item_episodes WHERE item_id=?", (cut["new_item_id"],))
        try:
            conn.execute("DELETE FROM item_episodes WHERE item_id=?", (str(newc.get("id")),))
        except Exception:
            pass
        conn.execute("DELETE FROM slicer_cuts WHERE new_item_id=?", (cut["new_item_id"],))
        # Limpieza del cover enriquecido propio de la parte (clave ficticia del corte).
        # Best effort: si nunca se editó, no hay fila y no pasa nada.
        # OJO: newc se cargó ANTES de los DELETE (el unified ya no tiene la fila).
        try:
            import re as _re2
            _nlk = str((newc or {}).get("telegram_link") or "")
            _km = _re2.search(r"/c/(\d+)/", _nlk)
            _tm = _re2.search(r"/c/\d+(?:/\d+)?/(\d+)", _nlk)
            if _km and _tm:
                _enr = os.path.normpath(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..", "tvcat_enricher", "data", "tvcat.db"))
                if os.path.isfile(_enr):
                    import sqlite3 as _sq2
                    _ec = _sq2.connect(_enr, timeout=10)
                    _ec.execute("DELETE FROM enriched_covers WHERE channelid_msgid=?",
                                (f"{_km.group(1)}_{_tm.group(1)}",))
                    _ec.commit()
                    _ec.close()
        except Exception:
            pass
        conn.commit()
        central_ok, central_detail = _refresh_central(
            f"slicer unsplit {body.new_item_id}",
            verify_item_id=cut["orig_item_id"])
        out = {"ok": True, "restored": len(eps_new), "central_refreshed": central_ok}
        if not central_ok:
            out["warn"] = ("Deshecho guardado pero la central no se actualizó: " + central_detail)
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.post("/api/slicer/resync")
async def resync(body: ResyncReq, request: Request):
    """Reintenta el refresco de export + central sin tocar los cortes.

    Para recuperar un split cuyo refresh falló (corte guardado en plugin DB
    pero invisible en catálogo). Opcionalmente re-aplica cortes del source.
    """
    _require_user(request)
    tag = f"slicer resync {body.source or 'all'}"
    if body.source:
        try:
            reapplied = reapply_slicer_cuts(body.source)
        except Exception as ex:
            return {"ok": False, "detail": f"reapply falló: {ex}"}
    else:
        reapplied = 0
    ok, detail = _refresh_central(tag)
    out = {"ok": ok, "detail": detail, "reapplied": reapplied}
    if not ok:
        out["hint"] = "Mira la consola del gateway ([SLICER]) para el traceback completo."
    return out


@router.get("/api/slicer/cuts")
async def list_cuts(request: Request, source: Optional[str] = None):
    _require_user(request)
    conn = _connect_plugin_db()
    try:
        _ensure_slicer_table(conn)
        if source:
            rows = conn.execute("SELECT * FROM slicer_cuts WHERE source=? ORDER BY id DESC", (source,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM slicer_cuts ORDER BY id DESC LIMIT 200").fetchall()
        return {"cuts": [dict(r) for r in rows]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/api/slicer/cut_of")
async def cut_of(request: Request, item_id: str):
    """Corte del que proviene un título partido (para la línea Unir)."""
    _require_user(request)
    conn = _connect_plugin_db()
    try:
        _ensure_slicer_table(conn)
        row = conn.execute("SELECT * FROM slicer_cuts WHERE new_item_id=?",
                           (str(item_id or ""),)).fetchone()
        if not row:
            raise HTTPException(404, "no es parte de un corte")
        cut = dict(row)
        orig = _load_title(conn, cut.get("orig_item_id"))
        if orig:
            cut["orig_title"] = orig.get("title") or cut.get("orig_item_id")
            cut["orig_link"] = orig.get("telegram_link") or ""
        return {"cut": cut}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def reapply_slicer_cuts(source_tag: str) -> int:
    """F2: re-aplica cortes guardados tras regenerar el original en un rescan.

    Llamar al final de _parse_loop / refresh_export_source del scan `source_tag`.
    Devuelve nº de cortes re-aplicados. Idempotente.
    """
    conn = sqlite3.connect(_tgindex_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    applied = 0
    try:
        _ensure_slicer_table(conn)
        cuts = conn.execute("SELECT * FROM slicer_cuts WHERE source=?", (source_tag,)).fetchall()
        for c in cuts:
            c = dict(c)
            # Si el nuevo ya existe con episodios, nada que hacer
            n = conn.execute("SELECT COUNT(*) FROM item_episodes WHERE item_id=?",
                             (c["new_item_id"],)).fetchone()[0]
            if n:
                continue
            # Si el original recuperó los mensajes cortados, moverlos de nuevo
            rows = conn.execute(
                "SELECT id FROM item_episodes WHERE (item_id=? AND telegram_msg_id>=?)",
                (c["orig_item_id"], int(c["cut_msg_id"]))).fetchall()
            if not rows:
                continue
            # Re-crea cabecera si el rescan la borró
            exists = conn.execute("SELECT id FROM unified_catalog WHERE item_id=?",
                                  (c["new_item_id"],)).fetchone()
            if not exists:
                o = conn.execute("SELECT * FROM unified_catalog WHERE item_id=?",
                                 (c["orig_item_id"],)).fetchone()
                if not o:
                    continue
                o = dict(o)
                cols = [r[1] for r in conn.execute("PRAGMA table_info(unified_catalog)").fetchall()]
                icols = [k for k in ("item_id", "title", "category", "subcategory", "description",
                                     "telegram_msg_id", "telegram_link", "group_title",
                                     "group_title_flat", "source", "sync_status", "sync_timestamp") if k in cols]
                # Título/cover se recuperan del corte previo si sigue la fila; si no, del original.
                # El ancla siempre es ficticia (-1000 + link al corte): nunca la del original.
                _cut_link_row = conn.execute(
                    "SELECT telegram_link FROM item_episodes WHERE item_id=? AND telegram_msg_id=? LIMIT 1",
                    (c["orig_item_id"], int(c["cut_msg_id"]))).fetchone()
                _rfic_mid, _rfic_link = _fictitious_anchor(
                    o.get("telegram_link") or "", int(c["cut_msg_id"]),
                    str((_cut_link_row["telegram_link"] if _cut_link_row else "") or ""))
                vals = [c["new_item_id"], o.get("title"), o.get("category", ""), o.get("subcategory", ""),
                        o.get("description", ""), _rfic_mid, _rfic_link,
                        o.get("title"), _norm_flat(o.get("title")), source_tag, "active", int(time.time())]
                colmap = {"item_id": 0, "title": 1, "category": 2, "subcategory": 3, "description": 4,
                          "telegram_msg_id": 5, "telegram_link": 6, "group_title": 7,
                          "group_title_flat": 8, "source": 9, "sync_status": 10, "sync_timestamp": 11}
                conn.execute(f"INSERT INTO unified_catalog ({','.join(icols)}) VALUES ({','.join('?'*len(icols))})",
                             [vals[colmap[k]] for k in icols])
            k = 0
            for r in conn.execute(
                    "SELECT id FROM item_episodes WHERE item_id=? AND telegram_msg_id>=? ORDER BY telegram_msg_id ASC",
                    (c["orig_item_id"], int(c["cut_msg_id"]))).fetchall():
                k += 1
                conn.execute("UPDATE item_episodes SET item_id=?, episode_number=? WHERE id=?",
                             (c["new_item_id"], k, r["id"]))
            applied += 1
        conn.commit()
    except Exception as ex:
        print(f" [SLICER] reapply {source_tag} falló: {ex}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return applied
