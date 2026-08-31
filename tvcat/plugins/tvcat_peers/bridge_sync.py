"""
TVCat Peers — Bridge Sync
==========================
Protocolo Sync Manifest: generación de manifiestos, comparación de deltas,
pull de detalles en batches, y actualización de catálogo local.
"""

import os
import json
import hashlib
import sqlite3
import logging
import asyncio
import httpx
from typing import List, Dict, Optional
from datetime import datetime

from . import bridge_manager as mgr

logger = logging.getLogger("tvcat.peers.sync")

BATCH_SIZE = 500


async def pull_manifest(peer: dict) -> List[dict]:
    """Solicita el manifest completo del peer remoto."""
    url = peer["url"].rstrip("/")
    headers = {"X-Bridge-Key": peer.get("our_api_key", "")}
    my_uuid = mgr.get_instance_uuid()
    logger.info(f"pull_manifest: pulling from {url}/api/peers/manifest, my_uuid={my_uuid}, api_key={peer.get('our_api_key', '')[:16]}...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{url}/api/peers/manifest",
                headers=headers,
                json={"peer_id": my_uuid}
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("manifest", [])
            elif resp.status_code == 403:
                data = resp.json()
                reason = data.get("reason", "unknown")
                logger.warning(f"pull_manifest: 403 de {peer['name']} — reason={reason}")
                if reason == "peer_revoked":
                    logger.info(f"Peer {peer['name']} revocó nuestra conexión. Limpiando...")
                    mgr.delete_peer(peer["id"])
                elif reason == "peer_not_found":
                    # El peer aún no nos conoce — no borrar nada, es esperado
                    logger.info(f"Peer {peer['name']} aún no nos conoce (peer_not_found). No se borra el peer local.")
                else:
                    logger.warning(f"pull_manifest: reason desconocido '{reason}' de {peer['name']}")
                return []
            else:
                logger.warning(f"Error obteniendo manifest de {peer['name']}: HTTP {resp.status_code}")
                return []
    except httpx.ConnectError:
        logger.info(f"Peer {peer['name']} no disponible (ConnectError)")
        return []
    except httpx.TimeoutException:
        logger.info(f"Peer {peer['name']} timeout")
        return []
    except Exception as e:
        logger.warning(f"Error pulling manifest de {peer['name']}: {e}")
        return []


async def compute_delta(manifest: List[dict], peer_id: str) -> dict:
    """
    Compara el manifest remoto con la caché local y devuelve:
    - to_add: bridge_ids que no tenemos o tienen updated_at más reciente
    - to_remove: bridge_ids que tenemos pero ya no están en manifest
    - to_keep: bridge_ids que ya tenemos actualizados
    """
    def _sync():
        conn = mgr.get_connection()
        try:
            local_rows = conn.execute(
                "SELECT bridge_id, dedup_key FROM tvcat_bridge_catalog WHERE peer_id = ?",
                (peer_id,)
            ).fetchall()
        finally:
            conn.close()

        local_map = {r["bridge_id"]: r["dedup_key"] for r in local_rows}
        manifest_map = {m["bridge_id"]: m for m in manifest}

        manifest_ids = set(manifest_map.keys())
        local_ids = set(local_map.keys())

        to_remove = list(local_ids - manifest_ids)
        to_add_ids = manifest_ids - local_ids

        to_add = []
        for mid in to_add_ids:
            to_add.append(manifest_map[mid])

        for mid in manifest_ids & local_ids:
            mm = manifest_map[mid]
            if local_map.get(mid) != mm.get("dedup_key"):
                to_add.append(mm)

        return {
            "to_add": to_add,
            "to_remove": to_remove,
        }
    return await asyncio.to_thread(_sync)


async def pull_details(peer: dict, bridge_ids: List[str]) -> List[dict]:
    """Solicita los detalles completos de items específicos al peer remoto."""
    if not bridge_ids or not peer:
        return []

    url = peer["url"].rstrip("/")
    headers = {"X-Bridge-Key": peer.get("our_api_key", "")}
    all_items = []

    for i in range(0, len(bridge_ids), BATCH_SIZE):
        batch = bridge_ids[i:i + BATCH_SIZE]
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{url}/api/peers/pull-details",
                    headers=headers,
                    json={"peer_id": mgr.get_instance_uuid(), "bridge_ids": batch}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    all_items.extend(data.get("items", []))
                else:
                    logger.warning(f"Error pulling details batch: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Error pulling details batch: {e}")

    return all_items


async def run_sync(peer_id: str):
    """Ejecuta el ciclo completo de sync para un peer: manifest → delta → update."""
    peer = mgr.get_peer(peer_id)
    if not peer:
        return
    if not peer.get("receive_enabled"):
        logger.info(f"run_sync: peer {peer_id} tiene receive_enabled=False — omitiendo")
        return

    # 1. Pull manifest del remoto (contiene datos completos)
    manifest = await pull_manifest(peer)
    print(f" [SYNC] run_sync para peer '{peer.get('name', peer_id)}': manifest recibido con {len(manifest)} items")
    logger.info(f"run_sync: peer={peer.get('name')}, manifest={len(manifest)} items")

    if not manifest:
        print(f" [SYNC]   → manifest vacío. Status actual: {peer.get('status')}")
        if peer.get("status") != "active":
            mgr.update_peer(peer_id, status="connecting",
                            last_seen=datetime.utcnow().isoformat())
        return

    # Mostrar muestra de categorías recibidas
    cats_recibidas = {}
    for item in manifest:
        c = item.get("category", "")
        s = item.get("subcategory", "")
        cats_recibidas.setdefault(c, set()).add(s)
    print(f" [SYNC]   Categorías recibidas: {dict((k, list(v)) for k, v in cats_recibidas.items())}")

    # 2. Computar delta y actualizar catálogo local directamente
    delta = await compute_delta(manifest, peer_id)
    print(f" [SYNC]   Delta: {len(delta['to_add'])} a insertar, {len(delta['to_remove'])} a eliminar")

    # 3. Eliminar items que ya no están en manifest
    # IMPORTANTE: remove_catalog_items_not_in_manifest hace "DELETE WHERE bridge_id NOT IN (...)"
    # por eso necesita el conjunto de IDs del manifest (los que HAY que conservar), no los a eliminar.
    manifest_ids = {m["bridge_id"] for m in manifest}
    if delta["to_remove"]:
        await mgr.remove_catalog_items_not_in_manifest(peer_id, manifest_ids)
        await _delete_cached_covers(delta["to_remove"])
        logger.info(f"Peer {peer['name']}: eliminados {len(delta['to_remove'])} items obsoletos")
        print(f" [SYNC]   Eliminados {len(delta['to_remove'])} items obsoletos")

    # 4. Insertar items nuevos/modificados directamente desde el manifest
    if delta["to_add"]:
        await mgr.add_catalog_items(peer_id, delta["to_add"])
        logger.info(f"Peer {peer['name']}: sincronizados {len(delta['to_add'])} items nuevos/modificados")
        print(f" [SYNC]   Insertados/actualizados {len(delta['to_add'])} items")
    else:
        print(f" [SYNC]   No hay items nuevos para insertar (ya están actualizados o manifest filtrado)")

    # 5. Marcar como online
    mgr.update_peer(peer_id, status="active",
                    last_sync=datetime.utcnow().isoformat(),
                    last_seen=datetime.utcnow().isoformat())
    print(f" [SYNC]   Peer '{peer.get('name')}' marcado como active")




async def serve_pull_details(peer_id: str, bridge_ids: List[str]) -> List[dict]:
    """
    Sirve detalles completos de items solicitados por un peer remoto.
    Busca en el catálogo local y plugins activos.
    """
    from tvcat.gateway import get_enabled_plugin_dbs_with_names

    dbs = get_enabled_plugin_dbs_with_names()
    items_map = {}

    for db_path, pname in dbs:
        if pname == "tvcat_peers":
            continue
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
            conn.row_factory = sqlite3.Row

            # Mapear bridge_ids a original_item_ids desde el manifest
            for bid in bridge_ids:
                try:
                    conn2 = mgr.get_connection()
                    orig = conn2.execute(
                        "SELECT original_item_id FROM tvcat_bridge_catalog WHERE bridge_id = ? AND peer_id = ?",
                        (bid, peer_id)
                    ).fetchone()
                    conn2.close()
                    if not orig:
                        continue
                    orig_id = orig["original_item_id"]

                    row = conn.execute(
                        "SELECT * FROM unified_catalog WHERE item_id = ?",
                        (orig_id,)
                    ).fetchone()
                    if row:
                        item = dict(row)
                        episodes = conn.execute(
                            "SELECT * FROM item_episodes WHERE item_id = ?",
                            (orig_id,)
                        ).fetchall()
                        items_map[bid] = {
                            "bridge_id": bid,
                            "original_item_id": orig_id,
                            "dedup_key": hashlib.sha256(
                                f"{row.get('channel_id', '')}:{row.get('msg_id', '')}".encode()
                            ).hexdigest()[:12],
                            "title": item.get("title", ""),
                            "category": item.get("category", ""),
                            "subcategory": item.get("subcategory", ""),
                            "year": item.get("api_year", ""),
                            "description": item.get("description", ""),
                            "metadata": {
                                "api_cover": item.get("api_cover", ""),
                                "info_messages": item.get("info_messages", ""),
                            },
                            "episodes": [dict(ep) for ep in episodes],
                        }
                except Exception:
                    continue
            conn.close()
        except Exception as e:
            logger.warning(f"Error serving pull details from {db_path}: {e}")

    return list(items_map.values())


async def _delete_cached_covers(bridge_ids: list):
    """Elimina las portadas cacheadas de bridge_ids de catalog_assets (en hilo separado)."""
    if not bridge_ids:
        return
    def _sync():
        conn = mgr.get_connection()
        try:
            for bid in bridge_ids:
                conn.execute(
                    "DELETE FROM catalog_assets WHERE asset_type = ?", (bid,)
                )
            conn.commit()
        except Exception as e:
            logger.warning(f"_delete_cached_covers: {e}")
        finally:
            conn.close()
    await asyncio.to_thread(_sync)
