"""
TVCat Peers — Bridge Events
=============================
Notificaciones de eventos entre peers vía HTTP.
El estado online/offline se determina por el éxito del pull manifest.
"""

import json
import asyncio
import logging
from typing import Dict
from datetime import datetime

import httpx

from . import bridge_manager as mgr

logger = logging.getLogger("tvcat.peers.ws")

_ws_tasks: Dict[str, asyncio.Task] = {}


async def send_to_peer(peer_id: str, message: dict):
    """Envía un mensaje/evento al peer remoto vía HTTP."""
    peer = mgr.get_peer(peer_id)
    if not peer:
        return

    url = peer["url"].rstrip("/")
    headers = {"X-Bridge-Key": peer.get("our_api_key", "")}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{url}/api/peers/event",
                headers=headers,
                json=message
            )
    except Exception as e:
        logger.debug(f"Error enviando evento a {peer['name']}: {e}")


async def notify_catalog_updated(peer_id: str):
    """Notifica al peer remoto que nuestro catálogo cambió."""
    await send_to_peer(peer_id, {
        "type": "catalog_updated",
        "peer_id": mgr.get_instance_uuid(),
        "timestamp": datetime.utcnow().isoformat()
    })


async def notify_share_config_changed(peer_id: str):
    """Notifica al peer remoto que cambiamos lo que compartimos."""
    await send_to_peer(peer_id, {
        "type": "share_config_changed",
        "peer_id": mgr.get_instance_uuid(),
        "timestamp": datetime.utcnow().isoformat()
    })


async def _heartbeat_loop(peer_id: str):
    """Envía heartbeat periódico al peer remoto."""
    while True:
        try:
            await asyncio.sleep(60)
            peer = mgr.get_peer(peer_id)
            if not peer or peer["status"] in ("revoked",):
                break
            await send_to_peer(peer_id, {
                "type": "ping",
                "peer_id": mgr.get_instance_uuid(),
                "timestamp": datetime.utcnow().isoformat()
            })
        except asyncio.CancelledError:
            break
        except Exception:
            pass


def start_peer_ws(peer_id: str):
    """Inicia el heartbeat para un peer específico."""
    if peer_id in _ws_tasks and not _ws_tasks[peer_id].done():
        _ws_tasks[peer_id].cancel()
    _ws_tasks[peer_id] = asyncio.create_task(_heartbeat_loop(peer_id))


def stop_peer_ws(peer_id: str):
    """Detiene el heartbeat para un peer."""
    if peer_id in _ws_tasks:
        _ws_tasks[peer_id].cancel()
        del _ws_tasks[peer_id]


_ws_started = False

def start_all_peers_ws():
    """Inicia heartbeats para todos los peers activos."""
    global _ws_started
    if _ws_started:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _ws_started = True
    for p in mgr.get_peers():
        if p["status"] in ("active", "offline", "connecting"):
            start_peer_ws(p["id"])


def stop_all_peers_ws():
    """Detiene todos los heartbeats."""
    for pid, task in list(_ws_tasks.items()):
        task.cancel()
    _ws_tasks.clear()
