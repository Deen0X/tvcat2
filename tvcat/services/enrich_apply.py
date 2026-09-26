"""
Propagación de títulos de covers enriquecidos al catálogo (SSOT: enriched_covers).

El guardado del enriquecedor propaga el título del tag (Title/Título/Nombre) y
las variantes (Title ES/Latam/Alt) al catálogo central + réplica en las DBs de
plugins. PERO rebuild_cache() regenera el central desde los sources con los
títulos originales y lo pierde. Por eso existe reapply_all_enriched(), que se
llama al final del rebuild: repasa la base con los covers guardados localmente.

Extraído verbatim de plugins/tvcat_enricher/routes.py (save_enriched) para no
duplicar lógica: el plugin delega aquí.
"""
import glob as _g
import json as _json
import os as _os
import re as _re
import sqlite3 as _sq

# Progreso del reapply por lotes para la barra azul del frontal.
_REAPPLY = {"running": False, "done": 0, "total": 0}


def reapply_progress() -> dict:
    """Snapshot {running, done, total} para /api/enricher/reapply/status."""
    try:
        return {"running": bool(_REAPPLY.get("running")),
                "done": int(_REAPPLY.get("done") or 0),
                "total": int(_REAPPLY.get("total") or 0)}
    except Exception:
        return {"running": False, "done": 0, "total": 0}


def _title_from_cover_text(text: str) -> str:
    """2026-09-04: extrae el título del tag como un mensaje nativo. Ignora
    placeholders, tags sin resolver ({...}) y líneas vacías.
    2026-09-10: las etiquetas de variante (Title Alt1, Title ES, Title Latam...)
    NO son el título principal (van a alt_titles vía _parse_cover_alt_titles).
    2026-09-12 (directiva usuario): PRIMERO "Original title" / "Título original"
    y después display (Title/Título/Nombre, sin variantes). El nombre visible
    es el original; si no hay original, el display.
    2026-09-20 (directiva usuario): PRIORIDAD INVERTIDA — PRIMERO display
    (Title/Título/Nombre) y después Original. El Title es el nombre "legible"
    (p.ej. títulos en chino/japonés llevan el original intraducible)."""
    def _scan(pattern: str) -> str:
        try:
            import re as _re2
            _await_hash = False
            for _line in (text or "").split("\n"):
                _l = _line.strip()
                if not _l:
                    continue
                if _await_hash and _l.startswith("#"):
                    _v = _l.lstrip("#").strip().replace("_", " ")
                    if len(_v) >= 2:
                        return _v[:200]
                    _await_hash = False
                    continue
                _await_hash = False
                _m = _re2.match(pattern, _l)
                if not _m:
                    continue
                _v = _m.group(2).strip()
                if not _v or _v in (":", "-", ""):
                    _await_hash = True
                    continue
                if "{" in _v or "}" in _v:
                    continue
                if len(_v) < 2:
                    continue
                return _v[:200]
        except Exception:
            pass
        return ""

    _disp = _scan(r"(?i)^(t[ií]tulo|titulo|title|nombre)(?!\s+(?:alt\d*|es(?:pa[ñn]a)?|latam|latin[oa]|mx|m[ée]xico|original)\b)\s*[:=\-]?\s*(.*?)\s*$")
    if _disp:
        return _disp
    return _scan(r"(?i)^(original\s+title|t[ií]tulo\s+original)\s*[:=\-]?\s*(.*?)\s*$")


# Mismo patrón que scanner._parse_alt_titles (canónico en
# plugins/tvcat_tgindex/scanner.py). Mantener sincronizado: líneas Title ES /
# Title Latam / Title Alt... del cover → variantes (columna alt_titles).
_COVER_ALT_RE = _re.compile(
    r"(?i)(?:title\s+alt\d*\b\.?|alt[\s.]*title|alt[\s.]*|alternative|syn[\s.]*"
    r"|sin[oó]nimo|synonym|(?:title|t[ií]tulo)\s+(?:alt\d*|es(?:pa[ñn]a)?|latam|latin[oa]|mx|m[ée]xico)\b\.?)"
    r"\s*[:=\s\-]\s*(.+)"
)


def _parse_cover_alt_titles(text: str) -> list:
    """Extrae variantes de título del caption (Title ES, Title Latam, Title Alt...)."""
    if not text:
        return []
    out = []
    for m in _COVER_ALT_RE.finditer(text):
        v = (m.group(1) or "").strip().rstrip(",")
        # Ignorar placeholders/tags sin resolver y valores triviales
        if not v or len(v) < 2 or "{" in v or "}" in v:
            continue
        if v not in out:
            out.append(v)
    return out


_YEAR_TAG_RE = _re.compile(r"(?i)(?:year|a[ñn]o)\s*[:=\s\-]\s*((?:19|20)\d{2})")
_YEAR_PAR_RE = _re.compile(r"\(((?:19|20)\d{2})\)\s*$")


def _year_from_cover_text(text: str) -> str:
    """Año del cover editado: tag Year:/Año: o (YYYY) al final de alguna de
    las 3 primeras líneas. Vacío si no hay dato (no se pisa nada)."""
    if not text:
        return ""
    try:
        m = _YEAR_TAG_RE.search(text)
        if m:
            return m.group(1)
        lines = [l.strip() for l in str(text).split("\n") if l.strip()][:3]
        for ln in lines:
            m = _YEAR_PAR_RE.search(ln)
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""


def apply_enriched_title(item_id: str, cover_text: str) -> dict:
    """Propaga título + variantes de un cover al catálogo central y réplica en
    las DBs de plugins (mismo modo que central). Retorna
    {title_applied, catalog_title, alts_applied}."""
    from services.catalog_service import get_conn as _cc, BASE_DIR as _bd
    _title_applied = False
    _catalog_title = ""
    _alts_applied = []
    _catalog_title_raw = _title_from_cover_text(cover_text or "")
    if not _catalog_title_raw:
        print(f" [Enricher] sin título extraíble del cover ({item_id}), catálogo intacto", flush=True)
    else:
        try:
            _c = _cc()
            _row = _c.execute("SELECT title, group_title, group_title_flat FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
            if _row and (_row["title"] or "") != _catalog_title_raw:
                print(f" [Enricher] título catálogo '{(_row['title'] or '')}' -> '{_catalog_title_raw}' ({item_id})", flush=True)
                _old_flat = (_row["group_title_flat"] or "")
                _others = _c.execute("SELECT COUNT(*) FROM unified_catalog WHERE group_title_flat=? AND item_id!=?", (_old_flat, item_id)).fetchone()[0] if _old_flat else 0
                _flat = _re.sub(r"[^a-zA-Z0-9]", "", _catalog_title_raw).lower()
                _mode = "all"
                if _flat != _old_flat and _others:
                    # Individualización: la parte editada SALE del grupo con grupo
                    # propio; el resto no se toca (editar una parte no modifica
                    # las demás). Evita arrastrar variantes a otra temporada.
                    _mode = "split"
                    _c.execute("UPDATE unified_catalog SET title=?, group_title=?, group_title_flat=? WHERE item_id=?", (_catalog_title_raw, _catalog_title_raw, _flat, item_id))
                elif _others and (_row["group_title"] or "") == (_row["title"] or ""):
                    # Miembro de grupo que lidera: renombrar grupo entero preserva variantes
                    _mode = "group"
                    _c.execute("UPDATE unified_catalog SET title=CASE WHEN item_id=? THEN ? ELSE title END, group_title=?, group_title_flat=? WHERE group_title_flat=?", (item_id, _catalog_title_raw, _catalog_title_raw, _flat, _old_flat))
                elif _others:
                    _mode = "title"
                    _c.execute("UPDATE unified_catalog SET title=? WHERE item_id=?", (_catalog_title_raw, item_id))
                else:
                    _c.execute("UPDATE unified_catalog SET title=?, group_title=?, group_title_flat=? WHERE item_id=?", (_catalog_title_raw, _catalog_title_raw, _flat, item_id))
                _c.commit()
                _title_applied = True
                _catalog_title = _catalog_title_raw
            elif _row:
                print(f" [Enricher] título sin cambios ({item_id}): catálogo ya '{(_row['title'] or '')}'", flush=True)
            else:
                print(f" [Enricher] item sin fila en catálogo ({item_id}), no se propaga título", flush=True)
            _c.close()
        except Exception as _e:
            print(f" [Enricher] title propagate error (central): {_e}")
        # Réplica en la DB del plugin origen (si la resuelve el core, no revierte en sync).
        # Replica el MISMO modo que central (split/group/title/all): si no, el
        # próximo rescan regenera central desde el plugin y resucita el bug.
        # Solo si central cambió (si no, _mode no existe y no hay nada que replicar).
        if _title_applied:
            try:
                for _pdb in _g.glob(_os.path.join(_bd, "plugins", "*", "data", "tvcat.db")):
                    try:
                        _pc = _sq.connect(_pdb, timeout=10)
                        _pr = _pc.execute("SELECT title FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
                        if _pr:
                            if _mode == "group":
                                _pc.execute("UPDATE unified_catalog SET group_title=?, group_title_flat=? WHERE group_title_flat=?", (_catalog_title_raw, _flat, _old_flat))
                                _pc.execute("UPDATE unified_catalog SET title=? WHERE item_id=?", (_catalog_title_raw, item_id))
                            elif _mode in ("split", "all"):
                                _pc.execute("UPDATE unified_catalog SET title=?, group_title=?, group_title_flat=? WHERE item_id=?", (_catalog_title_raw, _catalog_title_raw, _flat, item_id))
                            else:
                                _pc.execute("UPDATE unified_catalog SET title=? WHERE item_id=?", (_catalog_title_raw, item_id))
                            _pc.commit()
                        _pc.close()
                    except Exception:
                        pass
            except Exception:
                pass
    # 2026-09-10: propagar variantes (Title ES, Title Latam, Title Alt...) a la
    # columna alt_titles para que la búsqueda las encuentre sin re-escaneo.
    _cover_alts = _parse_cover_alt_titles(cover_text or "")
    if _cover_alts:
        try:
            from services.catalog_service import get_conn as _cc2
            _c2 = _cc2()
            _arow = _c2.execute("SELECT title, alt_titles FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
            if _arow:
                try:
                    _cur = _json.loads(_arow["alt_titles"] or "[]") or []
                except Exception:
                    _cur = []
                _have = {str(x).strip().lower() for x in _cur if str(x).strip()}
                if (_arow["title"] or "").strip():
                    _have.add((_arow["title"] or "").strip().lower())
                _merged = list(_cur)
                for _a in _cover_alts:
                    if _a.strip().lower() not in _have:
                        _merged.append(_a)
                        _have.add(_a.strip().lower())
                        _alts_applied.append(_a)
                if _alts_applied:
                    _c2.execute("UPDATE unified_catalog SET alt_titles=? WHERE item_id=?",
                                (_json.dumps(_merged, ensure_ascii=False), item_id))
                    _c2.commit()
            _c2.close()
        except Exception as _e:
            print(f" [Enricher] alts propagate error (central): {_e}")
        # Réplica en la DB del plugin origen
        if _alts_applied:
            try:
                from services.catalog_service import BASE_DIR as _bd2
                for _pdb in _g.glob(_os.path.join(_bd2, "plugins", "*", "data", "tvcat.db")):
                    try:
                        _pc2 = _sq.connect(_pdb, timeout=10)
                        _prow = _pc2.execute("SELECT alt_titles FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
                        if _prow is not None:
                            try:
                                _pcur = _json.loads(_prow["alt_titles"] or "[]") or []
                            except Exception:
                                _pcur = []
                            _phave = {str(x).strip().lower() for x in _pcur if str(x).strip()}
                            _pmerged = list(_pcur)
                            for _a in _alts_applied:
                                if _a.strip().lower() not in _phave:
                                    _pmerged.append(_a)
                                    _phave.add(_a.strip().lower())
                            _pc2.execute("UPDATE unified_catalog SET alt_titles=? WHERE item_id=?",
                                         (_json.dumps(_pmerged, ensure_ascii=False), item_id))
                            _pc2.commit()
                        _pc2.close()
                    except Exception:
                        pass
            except Exception:
                pass
    # Año del cover editado -> columna year (central + réplica en plugins).
    # Solo si el cover trae año (no se pisa un dato existente con vacío).
    _year_applied = ""
    _cover_year = _year_from_cover_text(cover_text or "")
    if _cover_year:
        try:
            from services.catalog_service import get_conn as _cc3
            _c3 = _cc3()
            _yrow = _c3.execute("SELECT year FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
            if _yrow is not None:
                _c3.execute("UPDATE unified_catalog SET year=? WHERE item_id=?", (_cover_year, item_id))
                _c3.commit()
                _year_applied = _cover_year
            _c3.close()
        except Exception as _e:
            print(f" [Enricher] year propagate error (central): {_e}")
        if _year_applied:
            try:
                from services.catalog_service import BASE_DIR as _bd3
                for _pdb in _g.glob(_os.path.join(_bd3, "plugins", "*", "data", "tvcat.db")):
                    try:
                        _pc3 = _sq.connect(_pdb, timeout=10)
                        try:
                            _pcols = [r[1] for r in _pc3.execute("PRAGMA table_info(unified_catalog)").fetchall()]
                        except Exception:
                            _pcols = []
                        if "year" not in _pcols:
                            try:
                                _pc3.execute("ALTER TABLE unified_catalog ADD COLUMN year TEXT")
                            except Exception:
                                pass
                        _prow3 = _pc3.execute("SELECT item_id FROM unified_catalog WHERE item_id=?", (item_id,)).fetchone()
                        if _prow3 is not None:
                            _pc3.execute("UPDATE unified_catalog SET year=? WHERE item_id=?", (_cover_year, item_id))
                            _pc3.commit()
                        _pc3.close()
                    except Exception:
                        pass
            except Exception:
                pass
    return {"title_applied": _title_applied,
            "catalog_title": _catalog_title if _title_applied else "",
            "alts_applied": _alts_applied,
            "year_applied": _year_applied}


def revert_enriched_title(item_id: str) -> dict:
    """Revierte el título/descripción central (y réplica en plugins) a los
    snapshots orig_* fijados antes del primer enriquecimiento. Para llamar al
    eliminar la copia local ("Volver a cover original"). Si no hay snapshot
    útil, no toca nada. Retorna {reverted, catalog_title, reason}."""
    from services.catalog_service import get_conn as _cc, BASE_DIR as _bd
    try:
        _c = _cc()
        _row = _c.execute(
            "SELECT title, description, group_title, group_title_flat,"
            " orig_title, orig_description FROM unified_catalog WHERE item_id=?",
            (item_id,)).fetchone()
        if not _row:
            _c.close()
            return {"reverted": False, "reason": "sin fila en catálogo"}
        _ot = (_row["orig_title"] or "").strip()
        _od = (_row["orig_description"] or "").strip()
        if not _ot or _ot == (_row["title"] or "").strip():
            _c.close()
            return {"reverted": False, "reason": "sin snapshot previo útil"}
        _flat = _re.sub(r"[^a-zA-Z0-9]", "", _ot).lower()
        _c.execute("UPDATE unified_catalog SET title=?, description=?,"
                   " group_title=?, group_title_flat=? WHERE item_id=?",
                   (_ot, _od, _ot, _flat, item_id))
        _c.commit()
        _c.close()
        print(f" [Enricher] título revertido a '{_ot}' ({item_id})", flush=True)
    except Exception as _e:
        print(f" [Enricher] revert error (central): {_e}")
        return {"reverted": False, "reason": str(_e)[:120]}
    try:
        for _pdb in _g.glob(_os.path.join(_bd, "plugins", "*", "data", "tvcat.db")):
            try:
                _pc = _sq.connect(_pdb, timeout=10)
                _pr = _pc.execute("SELECT title FROM unified_catalog WHERE item_id=?",
                                  (item_id,)).fetchone()
                if _pr:
                    _pc.execute("UPDATE unified_catalog SET title=?, description=?,"
                                " group_title=?, group_title_flat=? WHERE item_id=?",
                                (_ot, _od, _ot, _flat, item_id))
                    _pc.commit()
                _pc.close()
            except Exception:
                pass
    except Exception:
        pass
    return {"reverted": True, "catalog_title": _ot}


def reapply_all_enriched() -> dict:
    """Repasa la base con TODOS los covers guardados localmente (título +
    variantes). Para llamar al final de rebuild_cache(). Idempotente:
    segunda pasada no cambia nada. Retorna {covers, titles, alts}.

    Por lotes (2026-09-23): 1 conexión central + 1 SELECT masivo + 1 commit,
    y cada DB de plugin se abre UNA vez (antes: N títulos × M bases con
    commit por título). Sin logs por item (solo resumen). Progreso en
    _REAPPLY para la barra azul del frontal."""
    from services.catalog_service import BASE_DIR as _bd
    _edb = _os.path.join(_bd, "plugins", "tvcat_enricher", "data", "tvcat.db")
    if not _os.path.isfile(_edb):
        return {"covers": 0, "titles": 0, "alts": 0, "years": 0}
    try:
        _ec = _sq.connect(_edb, timeout=30)
        _ec.row_factory = _sq.Row
        _rows = _ec.execute(
            "SELECT item_id, cover_text FROM enriched_covers").fetchall()
        _ec.close()
    except Exception as e:
        print(f" [Enricher] reapply: no se pudo leer enriched_covers ({e})", flush=True)
        return {"covers": 0, "titles": 0, "alts": 0}
    _items = []
    for _r in (_rows or []):
        try:
            _iid, _ct = str(_r["item_id"] or ""), str(_r["cover_text"] or "")
            if not _iid or not _ct:
                continue
            _raw = _title_from_cover_text(_ct)
            _items.append((_iid, _ct, _raw))
        except Exception:
            continue
    _REAPPLY.update({"running": True, "done": 0, "total": len(_items)})
    _t, _a, _y = 0, 0, 0
    _years = {}
    if not _items:
        _REAPPLY.update({"running": False, "done": 0, "total": 0})
        print(" [Enricher] reapply: 0 covers", flush=True)
        return {"covers": 0, "titles": 0, "alts": 0, "years": 0}
    try:
        from services.catalog_service import get_conn as _cc
        _c = _cc()
        try:
            _ids = [i for i, _, _ in _items]
            _chunks, _sz = [], 500
            _central = {}
            for _k in range(0, len(_ids), _sz):
                _ch = _ids[_k:_k + _sz]
                _ph = ",".join("?" for _ in _ch)
                for _row in _c.execute(
                        "SELECT item_id, title, group_title, group_title_flat, alt_titles"
                        " FROM unified_catalog WHERE item_id IN (%s)" % _ph, _ch).fetchall():
                    _central[str(_row["item_id"])] = dict(_row)
            # Conteo por grupo (para _others) en una sola query.
            _flats = list({_r.get("group_title_flat") or ""
                           for _r in _central.values() if _r.get("group_title_flat")})
            _flatcount = {}
            if _flats:
                _ph = ",".join("?" for _ in _flats)
                for _fr in _c.execute(
                        "SELECT group_title_flat, COUNT(*) FROM unified_catalog"
                        " WHERE group_title_flat IN (%s) GROUP BY group_title_flat" % _ph,
                        _flats).fetchall():
                    _flatcount[str(_fr[0])] = int(_fr[1] or 0)
            _plan = []  # (item_id, mode, raw, flat, old_flat, alts_nuevas)
            for _iid, _ct, _raw in _items:
                _row = _central.get(_iid)
                if not _row or not _raw or (_row.get("title") or "") == _raw:
                    pass
                else:
                    _old_flat = (_row.get("group_title_flat") or "")
                    _others = int(_flatcount.get(_old_flat, 0) or 0)
                    if _old_flat and str(_row.get("group_title_flat") or "") == _old_flat:
                        _others = max(0, _others - 1)
                    _flat = _re.sub(r"[^a-zA-Z0-9]", "", _raw).lower()
                    _mode = "all"
                    if _flat != _old_flat and _others:
                        _mode = "split"
                    elif _others and (_row.get("group_title") or "") == (_row.get("title") or ""):
                        _mode = "group"
                    elif _others:
                        _mode = "title"
                    _plan.append((_iid, _mode, _raw, _flat, _old_flat, None))
                # Variantes (mismo merge que apply_enriched_title, sin prints).
                _cover_alts = _parse_cover_alt_titles(_ct)
                if _cover_alts and _row:
                    try:
                        _cur = _json.loads(_row.get("alt_titles") or "[]") or []
                    except Exception:
                        _cur = []
                    _have = {str(x).strip().lower() for x in _cur if str(x).strip()}
                    if (_row.get("title") or "").strip():
                        _have.add((_row.get("title") or "").strip().lower())
                    _new = [_x for _x in _cover_alts if _x.strip().lower() not in _have]
                    if _new:
                        _plan.append((_iid, "alts", None, None, None, _new))
                # Año del cover editado (se aplica con el resto tras el plan).
                try:
                    _yy = _year_from_cover_text(_ct)
                    if _yy:
                        _years[_iid] = _yy
                except Exception:
                    pass
                _REAPPLY["done"] += 1
            # Aplicar central en un solo commit.
            for _iid, _mode, _raw, _flat, _old_flat, _extra in _plan:
                try:
                    if _mode == "alts":
                        _mr = _central.get(_iid) or {}
                        try:
                            _mc = _json.loads(_mr.get("alt_titles") or "[]") or []
                        except Exception:
                            _mc = []
                        _mh = {str(x).strip().lower() for x in _mc if str(x).strip()}
                        for _x in (_extra or []):
                            if _x.strip().lower() not in _mh:
                                _mc.append(_x)
                                _mh.add(_x.strip().lower())
                        _c.execute("UPDATE unified_catalog SET alt_titles=? WHERE item_id=?",
                                   (_json.dumps(_mc, ensure_ascii=False), _iid))
                        _a += len(_extra or [])
                    elif _mode == "split":
                        _c.execute("UPDATE unified_catalog SET title=?, group_title=?, group_title_flat=? WHERE item_id=?",
                                   (_raw, _raw, _flat, _iid))
                        _t += 1
                    elif _mode == "group":
                        _c.execute("UPDATE unified_catalog SET title=CASE WHEN item_id=? THEN ? ELSE title END, group_title=?, group_title_flat=? WHERE group_title_flat=?",
                                   (_iid, _raw, _raw, _flat, _old_flat))
                        _t += 1
                    elif _mode == "title":
                        _c.execute("UPDATE unified_catalog SET title=? WHERE item_id=?", (_raw, _iid))
                        _t += 1
                    else:
                        _c.execute("UPDATE unified_catalog SET title=?, group_title=?, group_title_flat=? WHERE item_id=?",
                                   (_raw, _raw, _flat, _iid))
                        _t += 1
                except Exception:
                    continue
            # Año de covers editados (solo si el cover trae año).
            for _iid, _yy in _years.items():
                try:
                    _c.execute("UPDATE unified_catalog SET year=? WHERE item_id=?", (_yy, _iid))
                    _y += 1
                except Exception:
                    continue
            _c.commit()
            # Réplica en plugins: cada DB se abre UNA vez.
            try:
                _pdbs = [p for p in _g.glob(_os.path.join(_bd, "plugins", "*", "data", "tvcat.db"))
                         if _os.path.isfile(p)]
            except Exception:
                _pdbs = []
            _by_id = {}
            for _iid, _mode, _raw, _flat, _old_flat, _extra in _plan:
                _by_id.setdefault(_iid, []).append((_mode, _raw, _flat, _old_flat, _extra))
            for _pdb in _pdbs:
                try:
                    _pc = _sq.connect(_pdb, timeout=10)
                    try:
                        _cols = [r[1] for r in _pc.execute("PRAGMA table_info(unified_catalog)").fetchall()]
                    except Exception:
                        _pc.close()
                        continue
                    if "item_id" not in _cols or "title" not in _cols:
                        _pc.close()
                        continue
                    _has_alts = "alt_titles" in _cols
                    _ids2 = list(_by_id.keys())
                    _prows = {}
                    for _k in range(0, len(_ids2), 500):
                        _ch = _ids2[_k:_k + 500]
                        _ph = ",".join("?" for _ in _ch)
                        _sel = "item_id, title" + (", alt_titles" if _has_alts else "")
                        for _pr in _pc.execute(
                                "SELECT %s FROM unified_catalog WHERE item_id IN (%s)" % (_sel, _ph),
                                _ch).fetchall():
                            _prows[str(_pr[0])] = _pr
                    for _iid, _ops in _by_id.items():
                        if _iid not in _prows:
                            continue
                        # Año del cover editado (migra la columna si falta).
                        if _iid in _years:
                            try:
                                if "year" not in _cols:
                                    try:
                                        _pc.execute("ALTER TABLE unified_catalog ADD COLUMN year TEXT")
                                    except Exception:
                                        pass
                                _pc.execute("UPDATE unified_catalog SET year=? WHERE item_id=?", (_years[_iid], _iid))
                            except Exception:
                                pass
                        for (_mode, _raw, _flat, _old_flat, _extra) in _ops:
                            try:
                                if _mode == "alts":
                                    if not _has_alts:
                                        continue
                                    _prow = _prows[_iid]
                                    try:
                                        _pcur = _json.loads((_prow[2] if len(_prow) > 2 else None) or "[]") or []
                                    except Exception:
                                        _pcur = []
                                    _phave = {str(x).strip().lower() for x in _pcur if str(x).strip()}
                                    _pmerged = list(_pcur)
                                    for _x in (_extra or []):
                                        if _x.strip().lower() not in _phave:
                                            _pmerged.append(_x)
                                            _phave.add(_x.strip().lower())
                                    _pc.execute("UPDATE unified_catalog SET alt_titles=? WHERE item_id=?",
                                                (_json.dumps(_pmerged, ensure_ascii=False), _iid))
                                elif _mode == "group":
                                    _pc.execute("UPDATE unified_catalog SET group_title=?, group_title_flat=? WHERE group_title_flat=?",
                                                (_raw, _flat, _old_flat))
                                    _pc.execute("UPDATE unified_catalog SET title=? WHERE item_id=?", (_raw, _iid))
                                elif _mode in ("split", "all"):
                                    _pc.execute("UPDATE unified_catalog SET title=?, group_title=?, group_title_flat=? WHERE item_id=?",
                                                (_raw, _raw, _flat, _iid))
                                else:
                                    _pc.execute("UPDATE unified_catalog SET title=? WHERE item_id=?", (_raw, _iid))
                            except Exception:
                                continue
                    _pc.commit()
                    _pc.close()
                except Exception:
                    continue
            _c.close()
        except Exception as e:
            print(f" [Enricher] reapply error: {e}", flush=True)
    finally:
        _REAPPLY.update({"running": False})
    print(f" [Enricher] reapply: {len(_items)} covers, {_t} títulos, {_a} variantes, {_y} años",
          flush=True)
    return {"covers": len(_items), "titles": _t, "alts": _a, "years": _y}
