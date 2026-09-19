"""
Servicio central de IA (LLM) para TVCat2.

- Lista de proveedores configurables ordenados por prioridad (menor = antes).
- Tipos: `gemini` (Google AI Studio, API key) y `openai` (endpoint compatible
  OpenAI: OpenAI, Ollama local, etc. con base_url + api_key opcional).
- `complete()` prueba en orden y ROTA SIEMPRE ante cualquier fallo
  (saturación, timeout, clave inválida...): directiva de usuario.
- `resolve_ai_tags()` expande `{AI:prompt}` en textos (plantillas cover,
  descripciones), sustituyendo antes los `{tags}` internos con el contexto.
"""
import json
import re
import time

SETTINGS_KEY = "ai_providers"
PROMPTS_KEY = "ai_prompts"

DEFAULT_TIMEOUT_S = 60
# Sin techo en código (directiva): max_tokens solo se envía a la API si se
# indica explícito (llamada o proveedor); si no, manda el máximo del modelo
# y la longitud la controla el prompt.
DEFAULT_MAX_TOKENS = None
MAX_TAGS_PER_TEXT = 5

# Plantillas de prompt editables (placeholders: {titles}, {name}, {count}).
# La lista de títulos la añade el código al renderizar.
DEFAULT_PROMPTS = {
    "collection_name": (
        "Sugiere un nombre corto en español para una colección que contiene "
        "estos {count} títulos:\n{titles}\n"
        "Responde SOLO con el nombre, sin comillas ni explicaciones."
    ),
    "collection_desc": (
        "Genera una descripción breve en español, sin spoilers, para una "
        "colección llamada \"{name}\" que contiene estos {count} títulos:\n{titles}\n"
        "Responde SOLO con la descripción (2-4 frases), sin comillas ni explicaciones."
    ),
}


def get_prompts():
    try:
        conn = _conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (PROMPTS_KEY,)).fetchone()
        conn.close()
        d = json.loads((row["value"] if isinstance(row, dict) else row[0]) or "{}") if row else {}
    except Exception:
        d = {}
    out = dict(DEFAULT_PROMPTS)
    for k in out:
        if isinstance(d.get(k), str) and d[k].strip():
            out[k] = d[k]
    return out


def save_prompts(prompts):
    d = {}
    for k in DEFAULT_PROMPTS:
        v = (prompts or {}).get(k, "")
        d[k] = v if isinstance(v, str) and v.strip() else DEFAULT_PROMPTS[k]
    conn = _conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)",
                 (PROMPTS_KEY, json.dumps(d, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {"success": True}


def render_prompt(key, titles=(), name=""):
    """Rellena la plantilla con la lista de títulos (máx 40)."""
    tpl = get_prompts().get(key) or DEFAULT_PROMPTS.get(key, "")
    lst = ["- " + str(t) for t in (titles or [])[:40] if str(t).strip()]
    return tpl.replace("{titles}", "\n".join(lst)).replace("{name}", str(name or "")) \
              .replace("{count}", str(len(lst)))


def _conn():
    from services.catalog_service import get_conn
    return get_conn()


def list_providers(masked=True):
    """Lista ordenada por prioridad. masked=True oculta api_key (solo flag)."""
    try:
        conn = _conn()
        row = conn.execute("SELECT value FROM tvcat_settings WHERE key=?", (SETTINGS_KEY,)).fetchone()
        conn.close()
        items = json.loads((row["value"] if isinstance(row, dict) else row[0]) or "[]") if row else []
    except Exception:
        items = []
    out = []
    for p in (items or []):
        if not isinstance(p, dict):
            continue
        q = dict(p)
        if masked and q.get("api_key"):
            q["api_key"] = ""
            q["configured"] = True
        else:
            q["configured"] = bool(q.get("api_key")) if q.get("kind") != "openai" else True
        out.append(q)
    try:
        out.sort(key=lambda p: (int(p.get("priority", 100)), str(p.get("name") or "")))
    except Exception:
        pass
    return out


def save_providers(providers):
    """Guarda la lista (solo admin). Los api_key vacíos conservan el anterior."""
    old = {str(p.get("id")): p for p in list_providers(masked=False) if p.get("id")}
    clean = []
    for i, p in enumerate(providers or []):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or f"ai-{int(time.time())}-{i}")
        prev = old.get(pid, {})
        key = (p.get("api_key") or "").strip()
        if not key and prev.get("api_key"):
            key = prev["api_key"]
        kind = (p.get("kind") or "gemini").strip().lower()
        if kind not in ("gemini", "openai"):
            kind = "gemini"
        try:
            prio = int(p.get("priority", (i + 1) * 10))
        except Exception:
            prio = (i + 1) * 10
        try:
            to = max(10, min(300, int(p.get("timeout_s", DEFAULT_TIMEOUT_S))))
        except Exception:
            to = DEFAULT_TIMEOUT_S
        try:
            mt = p.get("max_tokens")
            mt = int(mt) if mt else None
        except Exception:
            mt = None
        clean.append({
            "id": pid,
            "name": (p.get("name") or kind).strip()[:80] or kind,
            "kind": kind,
            "api_key": key,
            "base_url": (p.get("base_url") or "").strip().rstrip("/"),
            "model": (p.get("model") or "").strip()[:120],
            "priority": prio,
            "timeout_s": to,
            "max_tokens": mt,
            "enabled": bool(p.get("enabled", True)),
        })
    conn = _conn()
    conn.execute("INSERT OR REPLACE INTO tvcat_settings (key, value) VALUES (?,?)",
                 (SETTINGS_KEY, json.dumps(clean, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {"success": True, "count": len(clean)}


def _gemini_base(provider):
    base = (provider.get("base_url") or "https://generativelanguage.googleapis.com").strip().rstrip("/")
    # El usuario puede pegar la URL completa con /v1beta: no duplicarla.
    low = base.lower()
    if low.endswith("/v1beta"):
        base = base[: -len("/v1beta")]
    return base or "https://generativelanguage.googleapis.com"


def _gemini_complete(provider, prompt, timeout_s, max_tokens):
    import httpx
    # Alias estable por defecto (2.x retirado para claves nuevas; el modelo
    # exacto depende de la antigüedad de la key: ver /v1beta/models).
    model = provider.get("model") or "gemini-flash-latest"
    base = _gemini_base(provider)
    url = f"{base}/v1beta/models/{model}:generateContent"
    params = {"key": provider.get("api_key") or ""}
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if max_tokens:
        body["generationConfig"] = {"maxOutputTokens": max_tokens, "temperature": 0.7}
    else:
        body["generationConfig"] = {"temperature": 0.7}
    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(url, params=params, json=body)
        if r.status_code in (400, 401, 403):
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {(r.text or '')[:150]}")
        if r.status_code == 429:
            raise RuntimeError(f"Gemini saturado (429): {(r.text or '')[:150]}")
        if r.status_code >= 500:
            raise RuntimeError(f"Gemini error servidor ({r.status_code}): {(r.text or '')[:150]}")
        r.raise_for_status()
        d = r.json()
    try:
        parts = (d.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    except Exception:
        text = ""
    if not text:
        raise RuntimeError(f"Gemini respuesta vacía: {str(d)[:150]}")
    return text


def _openai_complete(provider, prompt, timeout_s, max_tokens):
    import httpx
    base = (provider.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = provider.get("model") or "gpt-4o-mini"
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(f"{base}/chat/completions", headers=headers, json=body)
        if r.status_code in (400, 401, 403):
            raise RuntimeError(f"OpenAI HTTP {r.status_code}: {(r.text or '')[:150]}")
        if r.status_code == 429:
            raise RuntimeError(f"OpenAI saturado (429): {(r.text or '')[:150]}")
        if r.status_code >= 500:
            raise RuntimeError(f"OpenAI error servidor ({r.status_code}): {(r.text or '')[:150]}")
        r.raise_for_status()
        d = r.json()
    try:
        text = ((d.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception:
        text = ""
    if not text:
        raise RuntimeError(f"OpenAI respuesta vacía: {str(d)[:150]}")
    return text


def complete(prompt, max_tokens=None, timeout_s=None):
    """Completa un prompt rotando proveedores por prioridad. Rota SIEMPRE ante
    fallo (directiva). Retorna {ok, text, provider, provider_name, tried}."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "Prompt vacío", "tried": []}
    providers = [p for p in list_providers(masked=False) if p.get("enabled")]
    if not providers:
        return {"ok": False, "error": "Sin proveedores de IA configurados", "tried": []}
    tried = []
    for p in providers:
        to = timeout_s or p.get("timeout_s") or DEFAULT_TIMEOUT_S
        mt = max_tokens or p.get("max_tokens") or DEFAULT_MAX_TOKENS
        try:
            if p.get("kind") == "openai":
                text = _openai_complete(p, prompt, to, mt)
            else:
                if not p.get("api_key"):
                    raise RuntimeError("Sin api_key configurada")
                text = _gemini_complete(p, prompt, to, mt)
            print(f" [AI] OK via {p.get('name')} ({p.get('kind')})", flush=True)
            return {"ok": True, "text": text, "provider": p.get("id"),
                    "provider_name": p.get("name"), "tried": tried}
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
            print(f" [AI] fallo {p.get('name')}: {err} -> siguiente", flush=True)
            tried.append({"provider": p.get("id"), "name": p.get("name"), "error": err})
    return {"ok": False, "error": "; ".join(t.get("error", "?") for t in tried) or "Sin respuesta",
            "tried": tried}


def _sub_context_tags(prompt, context):
    """Sustituye {tags} internos (case-insensitive) con el contexto dado."""
    if not context:
        return prompt
    lowered = {str(k).lower(): str(v) for k, v in (context or {}).items() if v is not None}

    def _rep(m):
        return lowered.get(m.group(1).strip().lower(), m.group(0))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _rep, prompt)


def find_ai_tags(text):
    """Extrae el contenido de cada `{AI:...}` con balanceo de llaves (admite
    `{tags}` anidados como `{Title}` dentro del prompt)."""
    out = []
    s = text or ""
    i = 0
    while True:
        j = s.lower().find("{ai:", i)
        if j < 0:
            break
        depth = 0
        k = j
        closed = False
        while k < len(s):
            if s[k] == "{":
                depth += 1
            elif s[k] == "}":
                depth -= 1
                if depth == 0:
                    out.append(s[j + 4:k])
                    closed = True
                    break
            k += 1
        if not closed:
            break  # sin cierre: se ignora el resto
        i = k + 1
    return out


def resolve_ai_tags(text, context=None, max_tokens=None):
    """Expande hasta MAX_TAGS_PER_TEXT `{AI:prompt}` (los `{tags}` internos se
    resuelven primero con `context`). Los fallidos se dejan intactos y se
    reportan en `errors`. Retorna {text, resolved, errors}."""
    text = text or ""
    tags = find_ai_tags(text)
    if not tags:
        return {"text": text, "resolved": 0, "errors": []}
    errors = []
    resolved = 0
    for raw in tags[:MAX_TAGS_PER_TEXT]:
        prompt = _sub_context_tags(raw.strip(), context)
        r = complete(prompt, max_tokens=max_tokens)
        if r.get("ok"):
            text = text.replace("{AI:" + raw + "}", r["text"], 1)
            resolved += 1
        else:
            errors.append({"prompt": raw[:120], "error": r.get("error", "?")})
    return {"text": text, "resolved": resolved, "errors": errors}


def test_provider(provider_id, prompt="Responde exactamente: OK"):
    """Prueba UN proveedor (sin rotar)."""
    providers = [p for p in list_providers(masked=False) if str(p.get("id")) == str(provider_id)]
    if not providers:
        return {"ok": False, "error": "Proveedor no encontrado"}
    p = providers[0]
    try:
        if p.get("kind") == "openai":
            text = _openai_complete(p, prompt, p.get("timeout_s") or DEFAULT_TIMEOUT_S,
                                    p.get("max_tokens") or DEFAULT_MAX_TOKENS)
        else:
            if not p.get("api_key"):
                return {"ok": False, "error": "Sin api_key configurada"}
            text = _gemini_complete(p, prompt, p.get("timeout_s") or DEFAULT_TIMEOUT_S,
                                    p.get("max_tokens") or DEFAULT_MAX_TOKENS)
        return {"ok": True, "text": text, "provider": p.get("id"), "provider_name": p.get("name")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
