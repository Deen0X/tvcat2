"""
TVCat 2 Plugin Template - Sync
Ejemplo de módulo de sincronización para source plugins
"""


def sync():
    """Actualiza la base de datos del plugin."""
    print(" [PLUGIN TEMPLATE] Sync ejecutado")
    return True


def check_for_updates() -> bool:
    """Retorna True si hay cambios desde la última consulta."""
    return False
