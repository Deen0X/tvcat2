"""Servicio de auto-actualización de TVCat2 (solo submódulo tvcat2, público).

Dos canales:
  - stable: última release de GitHub (si no hay releases, se está al día).
  - dev: ZIP de la rama main (commit SHA como versión).

Flujo apply: descargar a staging -> verificar ZIP -> backup con timestamp ->
copiar encima excluyendo protegidos (DBs activas, config, sesiones, logs) ->
registrar versión -> restart del proceso (lo supervisa el launcher/Docker).

Sin tokens: el repo es público (API 60 req/h, de sobra para checks manuales).
"""
import io
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

GITHUB_OWNER = "Deen0X"
GITHUB_REPO = "tvcat2"
API = "https://api.github.com/repos/%s/%s" % (GITHUB_OWNER, GITHUB_REPO)
ZIPBALL_MAIN = "https://codeload.github.com/%s/%s/zip/refs/heads/main" % (GITHUB_OWNER, GITHUB_REPO)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TVCAT_DIR = BASE_DIR  # contiene gateway.py, core/, services/, plugins/, data/

# Patrones (relativos a TVCAT_DIR) que el swap JAMÁS toca.
PROTECTED_RES = [
    re.compile(r"^data/(?!.*_default\.db$).*$"),
    re.compile(r"^config/.*$"),
    re.compile(r"^logs/.*$"),
    re.compile(r".*\.session.*$"),
    re.compile(r"(^|/)state\.json$"),
    re.compile(r"(^|/)plugins_order\.json$"),
]

# Si el paquete trae alguno de estos fuera de *_default.db, abortar.
FORBIDDEN_RES = [
    re.compile(r"(^|/)tvcat\.db$"),
    re.compile(r"(^|/)session.*$"),
]


def _is_protected(rel: str) -> bool:
    rel = (rel or "").replace("\\", "/")
    return any(p.search(rel) for p in PROTECTED_RES)


def _is_forbidden(rel: str) -> bool:
    rel = (rel or "").replace("\\", "/")
    if rel.endswith("_default.db"):
        return False
    return any(p.search(rel) for p in FORBIDDEN_RES)


def current_version() -> dict:
    """Lee __version__ de gateway.py sin importarlo (evita circulares)."""
    ver, code = "?", ""
    try:
        with open(os.path.join(TVCAT_DIR, "gateway.py"), encoding="utf-8") as f:
            src = f.read()
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', src)
        if m:
            ver = m.group(1)
        m2 = re.search(r'__codename__\s*=\s*["\']([^"\']+)["\']', src)
        if m2:
            code = m2.group(1)
    except Exception:
        pass
    return {"version": ver, "codename": code}


def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:3])
    except Exception:
        return ()


def _http_get(url: str, timeout: int = 20):
    import httpx
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "TVCat2-updater",
                               "Accept": "application/vnd.github+json"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r


def check(channel: str = "stable") -> dict:
    """Compara versión local con remota. Nunca lanza."""
    cur = current_version()
    channel = (channel or "stable").strip().lower()
    if channel == "dev":
        try:
            r = _http_get("https://api.github.com/repos/%s/%s/commits/main?per_page=1"
                          % (GITHUB_OWNER, GITHUB_REPO))
            sha = (r.json() or {}).get("sha", "")[:7]
        except Exception as e:
            return {"ok": False, "error": "Sin acceso a GitHub: %s" % str(e)[:120],
                    "current": cur["version"], "remote": None, "update": False}
        try:
            from services.catalog_service import get_conn
            conn = get_conn()
            row = conn.execute("SELECT value FROM tvcat_settings WHERE key='update_dev_sha'").fetchone()
            conn.close()
            local_sha = row[0] if row else ""
        except Exception:
            local_sha = ""
        return {"ok": True, "current": cur["version"], "codename": cur.get("codename", ""),
                "remote": sha or None, "update": bool(sha and sha != local_sha)}
    # stable: última release; sin releases => al día (D4).
    try:
        r = _http_get(API + "/releases/latest")
        rel = r.json() or {}
    except Exception as e:
        return {"ok": False, "error": "Sin acceso a GitHub: %s" % str(e)[:120],
                "current": cur["version"], "remote": None, "update": False}
    tag = str(rel.get("tag_name") or "")
    assets = rel.get("assets") or []
    zip_url = ""
    for a in assets:
        n = str(a.get("name") or "")
        if n.lower().endswith(".zip"):
            zip_url = a.get("browser_download_url") or ""
            break
    rv, cv = _ver_tuple(tag), _ver_tuple(cur["version"])
    upd = bool(rv and cv and rv > cv)
    return {"ok": True, "current": cur["version"], "codename": cur.get("codename", ""),
            "remote": tag or None, "notes": rel.get("body") or "",
            "zip_url": zip_url, "update": upd}


def _find_app_root(staged: str):
    """Localiza dentro del staging el dir que contiene gateway.py."""
    for root, _dirs, files in os.walk(staged):
        if "gateway.py" in files:
            return root
    return None


def _sync_tree(src: str, dst: str):
    """Copia src->dst excluyendo protegidos. Retorna (copiados, omitidos, abortado)."""
    copied, skipped = 0, []
    for root, _dirs, files in os.walk(src):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src)
            if _is_forbidden(rel):
                return copied, skipped, rel
            if _is_protected(rel):
                skipped.append(rel)
                continue
            tgt = os.path.join(dst, rel)
            try:
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                shutil.copy2(full, tgt)
                copied += 1
            except Exception:
                skipped.append(rel + " (error)")
    return copied, skipped, None


def apply_update(channel: str = "stable") -> dict:
    """Descarga y aplica. Retorna dict; el restart lo hace el llamante.
    En dev, si el check falla (p.ej. rate limit de la API), se descarga
    igualmente el ZIP de main (la API y las descargas tienen límites
    distintos): la versión registrada queda como 'desconocida'."""
    channel = (channel or "stable").strip().lower()
    chk = check(channel)
    if not chk.get("ok"):
        if channel == "dev":
            cur = current_version()
            chk = {"ok": True, "current": cur["version"], "codename": cur.get("codename", ""),
                   "remote": None, "update": True, "forced": True}
        else:
            return {"ok": False, "error": chk.get("error") or "check fallido"}
    if channel == "stable" and not chk.get("update"):
        return {"ok": False, "error": "Ya estás en la última versión publicada"}
    url = chk.get("zip_url") if channel == "stable" else ZIPBALL_MAIN
    if not url:
        return {"ok": False, "error": "Sin URL de descarga (¿release sin asset ZIP?)"}
    tmp = tempfile.mkdtemp(prefix="tvcat_upd_")
    try:
        import httpx
        with httpx.Client(timeout=120, follow_redirects=True,
                          headers={"User-Agent": "TVCat2-updater"}) as c:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                data = b"".join(chunk for chunk in r.iter_bytes(1024 * 256))
        if len(data) < 1024:
            return {"ok": False, "error": "Descarga vacía o corrupta"}
        zp = os.path.join(tmp, "pkg.zip")
        with open(zp, "wb") as f:
            f.write(data)
        if not zipfile.is_zipfile(zp):
            return {"ok": False, "error": "No es un ZIP válido"}
        staged = os.path.join(tmp, "stage")
        os.makedirs(staged, exist_ok=True)
        with zipfile.ZipFile(zp) as z:
            z.extractall(staged)
        approot = _find_app_root(staged)
        if not approot:
            return {"ok": False, "error": "El ZIP no contiene gateway.py"}
        # Backup con timestamp (solo lo que se va a sustituir: espejo de approot
        # excluyendo protegidos).
        bak = os.path.join(os.path.dirname(TVCAT_DIR.rstrip(os.sep)),
                           "tvcat_backup_%s" % time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(bak, exist_ok=True)
        for root, _dirs, files in os.walk(approot):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), approot)
                if _is_protected(rel):
                    continue
                src_f = os.path.join(TVCAT_DIR, rel)
                if os.path.isfile(src_f):
                    tgt = os.path.join(bak, rel)
                    os.makedirs(os.path.dirname(tgt), exist_ok=True)
                    shutil.copy2(src_f, tgt)
        copied, skipped, aborted = _sync_tree(approot, TVCAT_DIR)
        if aborted:
            return {"ok": False, "error": "Paquete trae fichero protegido: %s (abortado)" % aborted,
                    "backup": bak}
        # Registrar versión aplicada.
        try:
            from services.catalog_service import get_conn
            conn = get_conn()
            if channel == "dev":
                conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?, ?)",
                             ("update_dev_sha", chk.get("remote") or ""))
                conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
        return {"ok": True, "backup": bak, "copied": copied,
                "skipped": len(skipped), "version": chk.get("remote")}
    except Exception as e:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
