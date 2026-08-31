"""
TVCat Peers — FastAPI Routes
============================
Endpoints completos siguiendo el diseño del brainstorming:
- Invite flow (generate, accept)
- Sync Manifest protocol
- Streaming directo (no proxy)
- Catálogo y categorías de peers
- Configuración de compartición por peer
"""

import os
import json
import uuid
import asyncio
import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from . import bridge_manager as mgr
from . import bridge_sync
from . import bridge_ws

logger = logging.getLogger("tvcat.peers")
router = APIRouter()


def _is_plugin_enabled() -> bool:
    """Verifica si tvcat_peers está habilitado en el PluginLoader."""
    try:
        from tvcat.gateway import is_plugin_enabled
        return is_plugin_enabled("tvcat_peers")
    except Exception:
        return True  # fallback permisivo si no se puede importar

def get_global_semaphore():
    try:
        from tvcat.gateway import GLOBAL_STREAM_SEMAPHORE
        return GLOBAL_STREAM_SEMAPHORE
    except (ImportError, AttributeError):
        return asyncio.Semaphore(5)


# ─── Modelos ────────────────────────────────────────────────────
class InviteRequest(BaseModel):
    peer_name: str
    categories: List[str] = []
    subcategories: List[str] = []
    ttl_hours: int = 72


class InviteAcceptRequest(BaseModel):
    name: str
    url: str
    shared_config: dict
    api_key: str
    uuid: str = ""


class ManifestRequest(BaseModel):
    peer_id: str
    manifest: List[dict] = []


class PullDetailsRequest(BaseModel):
    peer_id: str
    bridge_ids: List[str] = []


class ShareConfigUpdate(BaseModel):
    categories: List[str] = []
    subcategories: List[str] = []


class PeerUpdateRequest(BaseModel):
    name: Optional[str] = None
    alias: Optional[str] = None
    url: Optional[str] = None


# ─── Instance Info ──────────────────────────────────────────────
@router.get("/api/peers/instance-info")
async def get_instance_info(request: Request = None):
    lan_url = ""
    if request:
        host = request.headers.get("host", "")
        port = host.split(":")[1] if ":" in host else "8090"
        lan_ip = mgr.get_lan_ip()
        if lan_ip:
            lan_url = f"http://{lan_ip}:{port}"
    return {
        "uuid": mgr.get_instance_uuid(),
        "name": mgr.get_instance_name(),
        "lan_url": lan_url,
    }


@router.put("/api/peers/instance-name")
async def set_instance_name(payload: dict):
    name = payload.get("name", "").strip()
    if name:
        mgr.set_instance_name(name)
    return {"success": True, "name": mgr.get_instance_name()}


# ─── Invites ────────────────────────────────────────────────────
@router.post("/api/peers/invite")
async def create_invite(payload: InviteRequest, request: Request = None):
    shared_config = {
        "categories": payload.categories,
        "subcategories": payload.subcategories,
    }
    invite = mgr.create_invite(
        peer_name=payload.peer_name.strip(),
        shared_config=shared_config,
        ttl_hours=payload.ttl_hours
    )
    our_url = os.environ.get("TVCAT_URL", "")
    if not our_url and request:
        host = request.headers.get("host", "")
        scheme = request.headers.get("x-forwarded-proto", "http")
        # Extraer puerto del Host y construir URL con IP LAN detectada
        port = "8090"
        if ":" in host:
            port = host.split(":")[1]
        lan_ip = mgr.get_lan_ip()
        if lan_ip:
            our_url = f"{scheme}://{lan_ip}:{port}"
        elif host:
            our_url = f"{scheme}://{host}"
    invite_link = f"{our_url}/api/peers/invite/{invite['token']}" if our_url else ""
    return {
        "success": True,
        "token": invite["token"],
        "peer_id": invite["peer_id"],
        "invite_link": invite_link,
        "expires_at": invite["expires_at"],
    }


@router.get("/api/peers/invite/{token}")
async def get_invite_info(token: str):
    invite = mgr.get_invite(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invitación no encontrada o expirada")
    return {
        "token": token,
        "peer_name": invite["peer_name"],
        "shared_config": invite["shared_config"],
        "expires_at": invite["expires_at"],
        "bound": invite["bound_peer_uuid"] is not None,
    }


@router.post("/api/peers/invite/{token}/accept")
async def accept_invite(token: str, payload: InviteAcceptRequest, request: Request = None):
    logger.info(f"accept_invite: token={token}, payload.uuid='{payload.uuid}', payload.name='{payload.name}', payload.url='{payload.url}'")
    remote_uuid = payload.uuid or str(uuid.uuid4())
    logger.info(f"accept_invite: usando remote_uuid={remote_uuid}")

    # Si la URL enviada apunta a localhost, sustituir por la IP real del cliente
    peer_url = payload.url.strip().rstrip("/")
    if peer_url and request:
        import re as _re
        local_patterns = [r"127\.", r"localhost", r"0\.0\.0\.0"]
        is_local = any(_re.search(p, peer_url) for p in local_patterns)
        if is_local:
            client_ip = request.client.host if request.client else None
            if client_ip and not client_ip.startswith("127."):
                # Preservar el puerto de la URL original
                port_match = _re.search(r":(\d+)$", peer_url)
                port = port_match.group(1) if port_match else "8090"
                scheme = "http"
                peer_url = f"{scheme}://{client_ip}:{port}"
                logger.info(f"accept_invite: URL de cliente ajustada de '{payload.url}' a '{peer_url}' usando IP real del cliente")

    remote = {
        "uuid": remote_uuid,
        "name": payload.name.strip(),
        "url": peer_url,
        "api_key": payload.api_key,
        "our_api_key": str(uuid.uuid4()),
        "shared_config": payload.shared_config,
    }
    invite = mgr.accept_invite(token, remote)
    if not invite:
        raise HTTPException(status_code=400, detail="Invitación inválida, expirada o ya usada")

    peer_id = remote["uuid"]
    bridge_ws.start_peer_ws(peer_id)
    mgr.start_sync_scheduler()

    try:
        from tvcat.gateway import get_refresh_queue
        get_refresh_queue().put_nowait({"plugin": "tvcat_peers", "trigger": "auto", "peer_id": peer_id})
        logger.info(f"Encolado sync inicial en cola central para peer {peer_id}")
    except Exception:
        asyncio.ensure_future(_initial_sync(peer_id))

    return {
        "success": True,
        "peer_id": peer_id,
        "peer_name": invite["peer_name"],
        "our_uuid": mgr.get_instance_uuid(),
        "our_name": mgr.get_instance_name(),
        "our_api_key": remote["our_api_key"],
        "their_name": invite["peer_name"],
        "their_shared_config": invite["shared_config"],
    }


@router.post("/api/peers/accept-remote-invite")
async def accept_remote_invite(payload: dict):
    """
    Endpoint llamado por el frontend LOCAL para aceptar un invite
    de un servidor REMOTO. Este backend contacta al remoto,
    acepta la invitación y crea el peer local.
    """
    import httpx

    invite_link = payload.get("invite_link", "").strip()
    my_name = payload.get("my_name", "TVCat").strip()
    my_url = payload.get("my_url", "").strip().rstrip("/")
    my_shared_config = payload.get("shared_config", {})

    if not invite_link:
        raise HTTPException(status_code=400, detail="Enlace de invitación requerido")

    # Extraer base_url y token del enlace
    match = __import__("re").search(r"(https?://[^/]+)/api/peers/invite/([a-f0-9-]+)", invite_link)
    if not match:
        raise HTTPException(status_code=400, detail="Enlace de invitación inválido")

    remote_url = match.group(1)
    token = match.group(2)

    # 1. Validar la invitación en el remoto
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{remote_url}/api/peers/invite/{token}")
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Invitación no encontrada o expirada en el remoto")
            invite_info = resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="No se pudo conectar con el servidor remoto")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout al conectar con el servidor remoto")

    if invite_info.get("bound"):
        raise HTTPException(status_code=400, detail="Esta invitación ya ha sido utilizada")

    # 2. Generar clave para el remoto y aceptar la invitación
    my_api_key_for_them = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{remote_url}/api/peers/invite/{token}/accept",
                json={
                    "name": my_name,
                    "url": my_url,
                    "api_key": my_api_key_for_them,
                    "shared_config": my_shared_config,
                    "uuid": mgr.get_instance_uuid(),
                }
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"El remoto rechazó la conexión: {resp.text}")
            result = resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="No se pudo conectar con el servidor remoto al aceptar")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Timeout al aceptar la invitación en el remoto")

    # 3. Crear peer local con los datos del remoto
    # shared_config = lo que B quiere compartir con A (su propia selección)
    remote_peer_id = result.get("our_uuid", invite_info.get("peer_id", token))
    try:
        mgr.add_peer(
            peer_id=remote_peer_id,
            name=result.get("our_name", invite_info.get("peer_name", "Remoto")),
            url=remote_url,
            our_key=result.get("our_api_key", ""),
            his_key=my_api_key_for_them,
            shared_config=my_shared_config
        )
        bridge_ws.start_peer_ws(remote_peer_id)
        mgr.start_sync_scheduler()
    except ValueError:
        # Ya existe localmente → actualizar datos y seguir
        mgr.update_peer(remote_peer_id,
            url=remote_url,
            his_api_key=my_api_key_for_them,
            shared_config=json.dumps(my_shared_config))
        bridge_ws.start_peer_ws(remote_peer_id)
        mgr.start_sync_scheduler()

    # 4. Disparar sync inicial (pull del catálogo del remoto)
    try:
        from tvcat.gateway import get_refresh_queue
        get_refresh_queue().put_nowait({"plugin": "tvcat_peers", "trigger": "auto", "peer_id": remote_peer_id})
        logger.info(f"Encolado sync inicial remoto en cola central para peer {remote_peer_id}")
    except Exception:
        asyncio.ensure_future(_initial_sync(remote_peer_id))

    return {
        "success": True,
        "peer_id": remote_peer_id,
        "peer_name": result.get("our_name", invite_info.get("peer_name", "Remoto")),
    }


async def _initial_sync(peer_id: str):
    """Sync inicial tras aceptar un invite: pull del catálogo remoto con reintentos.
    Espera 3s antes del primer intento para dar tiempo al peer remoto
    a procesar el accept_invite y registrarnos en su BD.
    """
    await asyncio.sleep(3)
    for attempt in range(6):
        await bridge_sync.run_sync(peer_id)
        peer = mgr.get_peer(peer_id)
        if peer and peer["status"] == "active":
            logger.info(f"Sync inicial completado para peer {peer['name']} (intento {attempt + 1})")
            try:
                await bridge_ws.notify_catalog_updated(peer_id)
            except Exception:
                pass
            return
        if attempt < 5:
            logger.info(f"Sync inicial: peer aún no disponible, reintento en 5s (intento {attempt + 1})")
            await asyncio.sleep(5)
    logger.warning(f"Sync inicial falló tras 6 intentos para peer {peer_id}")


# ─── Peer CRUD Legacy (compatibilidad con frontend actual) ─────
@router.get("/api/peers")
async def list_peers():
    if not _is_plugin_enabled():
        return []
    peers = mgr.get_peers()
    result = []
    for p in peers:
        result.append({
            "id": p["id"],
            "name": p.get("alias") or p["name"],
            "url": p["url"],
            "status": p["status"],
            "share_enabled": p.get("share_enabled", 1),
            "receive_enabled": p.get("receive_enabled", 1),
            "last_seen": p.get("last_seen", ""),
            "last_sync": p.get("last_sync", ""),
            "is_online": 1 if p["status"] == "active" else 0,
            "shared_config": p.get("shared_config", {}),
        })
    return result


@router.get("/api/peers/{peer_id}")
async def get_peer_detail(peer_id: str):
    peer = mgr.get_peer(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer no encontrado")
    return peer


@router.put("/api/peers/{peer_id}")
async def update_peer(peer_id: str, payload: PeerUpdateRequest):
    peer = mgr.get_peer(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer no encontrado")
    updates = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.alias is not None:
        updates["alias"] = payload.alias.strip()
    if payload.url is not None:
        updates["url"] = payload.url.strip().rstrip("/")
    if updates:
        mgr.update_peer(peer_id, **updates)
    return {"success": True}


@router.delete("/api/peers/{peer_id}")
async def delete_peer(peer_id: str):
    peer = mgr.get_peer(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer no encontrado")

    bridge_ws.stop_peer_ws(peer_id)
    await bridge_ws.send_to_peer(peer_id, {
        "type": "peer_disconnected",
        "peer_id": mgr.get_instance_uuid(),
    })
    # Eliminar cualquier registro previo de revocación por si deciden reconectarse inmediatamente
    conn = mgr.get_connection()
    try:
        conn.execute("DELETE FROM tvcat_bridge_revoked WHERE peer_uuid = ?", (peer_id,))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
        
    mgr.delete_peer(peer_id)
    return {"success": True}


# ─── Toggles de compartición ────────────────────────────────────
@router.put("/api/peers/{peer_id}/toggle-share")
async def toggle_share(peer_id: str, payload: dict):
    enabled = payload.get("enabled", True)
    mgr.update_peer(peer_id, share_enabled=1 if enabled else 0)
    if enabled:
        await bridge_ws.notify_share_config_changed(peer_id)
    return {"success": True, "share_enabled": enabled}


@router.put("/api/peers/{peer_id}/toggle-receive")
async def toggle_receive(peer_id: str, payload: dict):
    enabled = payload.get("enabled", True)
    mgr.update_peer(peer_id, receive_enabled=1 if enabled else 0)
    return {"success": True, "receive_enabled": enabled}


@router.put("/api/peers/{peer_id}/share-config")
async def update_share_config(peer_id: str, payload: ShareConfigUpdate):
    mgr.update_peer(peer_id, shared_config=json.dumps({
        "categories": payload.categories,
        "subcategories": payload.subcategories,
    }))
    await bridge_ws.notify_share_config_changed(peer_id)
    return {"success": True}


# ─── Sync Manifest ──────────────────────────────────────────────
@router.post("/api/peers/manifest")
async def receive_manifest_request(request: Request):
    """El peer remoto solicita nuestro manifest.
    Lo filtramos según lo que compartimos con él.
    Busca el peer primero por UUID y como fallback por api_key.
    """
    body = await request.json()
    requester_id = body.get("peer_id", "")
    api_key = request.headers.get("X-Bridge-Key", "")

    logger.info(f"receive_manifest_request: requester_id={requester_id}, api_key={api_key[:16] if api_key else ''}...")
    peer = mgr.get_peer(requester_id) if requester_id else None

    # Fallback: buscar por api_key si no se encontró por UUID
    # Esto resuelve race conditions donde el accept aún no se propagó
    if not peer and api_key:
        peer = mgr.get_peer_by_api_key(api_key)
        if peer:
            logger.info(f"receive_manifest_request: peer encontrado por api_key: {peer['name']} (id={peer['id']})")
            requester_id = peer["id"]

    if not peer:
        all_peers = mgr.get_peers()
        logger.warning(f"Peer {requester_id} no encontrado. Peers actuales: {[(p['id'], p['name'], p['url']) for p in all_peers]}")
        return JSONResponse(status_code=403, content={"reason": "peer_not_found"})
    if mgr.is_revoked(requester_id):
        return JSONResponse(status_code=403, content={"reason": "peer_revoked"})

    manifest = mgr.generate_manifest(requester_id)
    return {"manifest": manifest, "peer_id": mgr.get_instance_uuid()}


@router.post("/api/peers/sync-manifest")
async def receive_sync_manifest(payload: ManifestRequest):
    """Recibe el manifest de un peer remoto, computa delta y devuelve qué necesita."""
    api_key = None
    requester_id = payload.peer_id

    peer = mgr.get_peer(requester_id)
    if not peer:
        return {"required_ids": []}

    delta = await bridge_sync.compute_delta(payload.manifest, requester_id)

    await mgr.remove_catalog_items_not_in_manifest(
        requester_id,
        set(m["bridge_id"] for m in payload.manifest)
    )

    return {"required_ids": [m["bridge_id"] for m in delta["to_add"]]}


@router.post("/api/peers/pull-details")
async def serve_pull_details(payload: PullDetailsRequest):
    """Sirve detalles completos de items solicitados por un peer remoto."""
    items = await bridge_sync.serve_pull_details(payload.peer_id, payload.bridge_ids)
    return {"items": items}


@router.post("/api/peers/{peer_id}/request-sync")
async def request_sync(peer_id: str):
    """Fuerza una sincronización inmediata con un peer."""
    mgr.start_sync_scheduler()
    await bridge_sync.run_sync(peer_id)
    return {"success": True}


# ─── Catálogo de Peers ──────────────────────────────────────────
@router.get("/api/peers/{peer_id}/categories")
async def get_peer_categories(peer_id: str):
    """Retorna estructura de categorías de un peer."""
    if not _is_plugin_enabled():
        return {}
    peer = mgr.get_peer(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer no encontrado")

    if peer["status"] != "active":
        return {}

    categories = mgr.get_peer_catalog_categories(peer_id)
    return categories


@router.get("/api/peers/{peer_id}/catalog")
async def get_peer_catalog(peer_id: str, category: str = "",
                           subcategory: str = "", limit: int = 100,
                           offset: int = 0):
    """Retorna items del catálogo de un peer."""
    peer = mgr.get_peer(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer no encontrado")
    if peer["status"] != "active":
        return {"items": [], "total": 0}

    cat = category if category else None
    sub = subcategory if subcategory else None
    items, total = mgr.get_peer_catalog_items(
        peer_id, category=cat, subcategory=sub,
        limit=limit, offset=offset
    )
    return {"items": items, "total": total}


# ─── Streaming Directo ──────────────────────────────────────────
@router.get("/api/peers/play/{peer_id}/{item_id}")
async def get_play_url(peer_id: str, item_id: str):
    """
    Retorna la URL y headers para que el frontend reproduzca
    DIRECTAMENTE desde el peer remoto (sin proxy local).
    """
    peer = mgr.get_peer(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer no encontrado")
    if peer["status"] != "active":
        raise HTTPException(status_code=503, detail="Peer no disponible")

    conn = mgr.get_connection()
    try:
        row = conn.execute(
            "SELECT original_item_id FROM tvcat_bridge_catalog WHERE bridge_id = ? AND peer_id = ?",
        (f"PEER-{peer_id[:8]}-{item_id[-16:]}", peer_id)
        ).fetchone()
    finally:
        conn.close()

    orig_id = row["original_item_id"] if row else item_id

    remote_url = peer["url"].rstrip("/")
    stream_url = f"{remote_url}/stream/user/episode/{orig_id}"

    return {
        "stream_url": stream_url,
        "headers": {
            "X-Bridge-Key": peer.get("our_api_key", ""),
        }
    }


@router.get("/api/peers/stream/{peer_id}/{item_id}")
async def stream_peer_content(peer_id: str, item_id: str, request: Request):
    """
    Endpoint proxy (segundo plano). Si el frontend no puede conectar
    directamente al remoto (CORS, NAT), este endpoint sirve como fallback
    haciendo de proxy.
    """
    import httpx
    from fastapi.responses import StreamingResponse

    peer = mgr.get_peer(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer no encontrado")
    if peer["status"] != "active":
        raise HTTPException(status_code=503, detail="Peer no disponible")

    global_sem = get_global_semaphore()
    peer_sem = mgr.get_peer_semaphore(peer_id)

    async with global_sem:
        async with peer_sem:
            remote_url = peer["url"].rstrip("/")
            client = httpx.AsyncClient()
            headers = dict(request.headers)
            headers.pop("host", None)
            headers["X-Bridge-Key"] = peer.get("his_api_key", "")

            try:
                req = client.build_request(
                    "GET",
                    f"{remote_url}/stream/user/episode/{item_id}",
                    headers=headers
                )
                resp = await client.send(req, stream=True)

                if resp.status_code == 451:
                    body = await resp.aread()
                    try:
                        data = json.loads(body)
                    except:
                        data = {"reason": "content_revoked", "episode_id": item_id}
                    await resp.aclose()
                    await client.aclose()
                    _cleanup_revoked_item(peer_id, item_id)
                    return JSONResponse(status_code=451, content=data)

                async def stream_gen():
                    try:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
                    finally:
                        await resp.aclose()
                        await client.aclose()

                return StreamingResponse(
                    stream_gen(),
                    status_code=resp.status_code,
                    headers=dict(resp.headers)
                )
            except Exception as e:
                await client.aclose()
                raise HTTPException(status_code=502, detail=f"Error conectando al peer: {e}")


def _cleanup_revoked_item(peer_id: str, item_or_episode_id: str):
    """Elimina el item de la base de datos local y sus portadas cacheadas si ha sido revocado."""
    conn = mgr.get_connection()
    try:
        bridge_id = None
        # 1. Si es un item_id (suele empezar por USER- o TFX- o simplemente ser un string del item)
        if isinstance(item_or_episode_id, str) and ("USER-" in item_or_episode_id or "TFX-" in item_or_episode_id):
            row = conn.execute(
                "SELECT bridge_id FROM tvcat_bridge_catalog WHERE peer_id = ? AND (bridge_id = ? OR original_item_id = ?)",
                (peer_id, item_or_episode_id, item_or_episode_id)
            ).fetchone()
            if row:
                bridge_id = row["bridge_id"]
        else:
            # 2. Si es un episode_id, buscar en tvcat_bridge_catalog_episodes
            row = conn.execute(
                "SELECT bridge_id FROM tvcat_bridge_catalog_episodes WHERE original_episode_id = ?",
                (item_or_episode_id,)
            ).fetchone()
            if row:
                bridge_id = row["bridge_id"]
                
        if bridge_id:
            logger.info(f"Revocado detectado. Limpiando item bridge_id={bridge_id} (referencia: {item_or_episode_id})")
            # Borrar de catalog_assets (portadas)
            conn.execute("DELETE FROM catalog_assets WHERE asset_type = ?", (bridge_id,))
            # Borrar de tvcat_bridge_catalog (cascadeará a tvcat_bridge_catalog_episodes)
            conn.execute("DELETE FROM tvcat_bridge_catalog WHERE bridge_id = ?", (bridge_id,))
            conn.commit()
    except Exception as e:
        logger.warning(f"Error en _cleanup_revoked_item: {e}")
    finally:
        conn.close()


# ─── WebSocket Endpoint ─────────────────────────────────────────
@router.websocket("/api/peers/ws")
async def peers_websocket(websocket):
    await websocket.accept()
    headers = dict(websocket.headers)
    api_key = headers.get("x-bridge-key", "")
    peer_id = headers.get("x-peer-id", "")

    if not peer_id:
        await websocket.close(code=4001)
        return

    peer = mgr.get_peer(peer_id)
    if not peer:
        await websocket.close(code=4003)
        return

    logger.info(f"WS conexión entrante de peer {peer['name']}")
    mgr.update_peer(peer_id, status="active",
                    last_seen=datetime.utcnow().isoformat())

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg.get("type") == "catalog_updated":
                    logger.info(f"Peer {peer['name']}: catalog_updated")
                    await bridge_sync.run_sync(peer_id)
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    finally:
        logger.info(f"WS desconectado de peer {peer['name']}")
        mgr.update_peer(peer_id, status="offline",
                        last_seen=datetime.utcnow().isoformat())


# ─── Event endpoint (recibir eventos vía HTTP) ──────────────────
@router.post("/api/peers/event")
async def receive_event(request: Request):
    """
    Recibe eventos de un peer remoto cuando WS no está disponible.
    """
    body = await request.json()
    api_key = request.headers.get("X-Bridge-Key", "")
    peer_id = body.get("peer_id", "")

    peer = mgr.get_peer(peer_id)
    if not peer:
        return {"success": False, "reason": "peer_not_found"}

    event_type = body.get("type", "")
    if event_type in ("catalog_updated", "share_config_changed"):
        try:
            from tvcat.gateway import get_refresh_queue
            get_refresh_queue().put_nowait({"plugin": "tvcat_peers", "trigger": "auto", "peer_id": peer_id})
            logger.info(f"Encolada sync por evento '{event_type}' en cola central para peer {peer_id}")
        except Exception:
            asyncio.ensure_future(bridge_sync.run_sync(peer_id))
    elif event_type == "peer_disconnected":
        mgr.update_peer(peer_id, status="offline",
                        last_seen=datetime.utcnow().isoformat())

    return {"success": True}


# ─── Inicialización ─────────────────────────────────────────────
mgr.start_sync_scheduler()
bridge_ws.start_all_peers_ws()

# Registrar en el motor de catálogo del gateway
_peers_refresh_status = {"progress": 100, "status": "idle", "current": ""}

def _get_peers_refresh_status():
    return _peers_refresh_status

async def _run_peers_refresh(item_or_trigger):
    peer_id = None
    if isinstance(item_or_trigger, dict):
        peer_id = item_or_trigger.get("peer_id")
    
    _peers_refresh_status["status"] = "syncing"
    
    if peer_id:
        peer = mgr.get_peer(peer_id)
        if not peer:
            _peers_refresh_status["status"] = "idle"
            _peers_refresh_status["progress"] = 100
            return
        
        peer_name = peer.get("name", peer_id)
        _peers_refresh_status["progress"] = 50
        _peers_refresh_status["current"] = f"Sincronizando {peer_name}..."
        print(f" [SYNC PEERS] Sincronizando peer específico: {peer_name}")
        try:
            await bridge_sync.run_sync(peer_id)
        except Exception as e:
            print(f" [SYNC PEERS ERROR] Error sincronizando peer {peer_name}: {e}")
    else:
        peers = mgr.get_peers()
        active_peers = [p for p in peers if p.get("receive_enabled")]
        total_peers = len(active_peers)
        if total_peers == 0:
            print(" [SYNC PEERS] No hay peers activos para sincronizar.")
            _peers_refresh_status["status"] = "idle"
            _peers_refresh_status["progress"] = 100
            _peers_refresh_status["current"] = "Completado"
            return
        
        for idx, peer in enumerate(active_peers):
            p_id = peer["id"]
            p_name = peer.get("name", p_id)
            _peers_refresh_status["progress"] = int((idx / total_peers) * 100)
            _peers_refresh_status["current"] = f"Sincronizando {p_name} ({idx+1}/{total_peers})..."
            print(f" [SYNC PEERS] Sincronizando peer {idx+1}/{total_peers}: {p_name}")
            try:
                await bridge_sync.run_sync(p_id)
            except Exception as e:
                print(f" [SYNC PEERS ERROR] Error sincronizando peer {p_name}: {e}")
                
    _peers_refresh_status["status"] = "idle"
    _peers_refresh_status["progress"] = 100
    _peers_refresh_status["current"] = "Completado"

try:
    from tvcat.gateway import register_plugin_refresher
    register_plugin_refresher("tvcat_peers", _run_peers_refresh, _get_peers_refresh_status, start_delay=15)
except Exception as e:
    print(f" [SYNC PEERS ERROR] Error al registrar refresher en gateway: {e}")
