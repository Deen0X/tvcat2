"""
TVCat 2 Plugin Loader v3
=======================
Carga dinámica de plugins con manifiesto extendido.
Soporta tipos: source, grid-decorator, item-decorator, heropage-action, player.
"""

import os
import json
import importlib.util
import sys
from typing import Dict, Any, Optional, List

PLUGINS_DIR = os.path.join(os.path.dirname(__file__), "plugins")


class PluginLoader:
    def __init__(self, plugins_dir: str = PLUGINS_DIR):
        self.plugins_dir = plugins_dir
        self.registry: Dict[str, Any] = {}

    def scan(self):
        """Escanea plugins/ y registra todos los plugins disponibles."""
        if not os.path.isdir(self.plugins_dir):
            print(f" [PLUGIN LOADER] Carpeta de plugins no encontrada: {self.plugins_dir}")
            return

        for folder_name in sorted(os.listdir(self.plugins_dir)):
            plugin_dir = os.path.join(self.plugins_dir, folder_name)
            if not os.path.isdir(plugin_dir):
                continue

            manifest_path = os.path.join(plugin_dir, "plugin.json")
            if not os.path.exists(manifest_path):
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                plugin_name = manifest.get("name", folder_name)
                plugin_type = manifest.get("type", "source")

                state_path = os.path.join(plugin_dir, "state.json")
                enabled = manifest.get("defaultEnabled", False)
                if os.path.exists(state_path):
                    try:
                        with open(state_path, "r", encoding="utf-8") as f:
                            state = json.load(f)
                        enabled = state.get("enabled", enabled)
                    except:
                        pass

                entry = {
                    **manifest,
                    "name": plugin_name,
                    "type": plugin_type,
                    "enabled": enabled,
                    "_dir": plugin_dir,
                    "load_error": None,
                }

                if plugin_type == "source":
                    self._load_plugin_module(entry, plugin_dir, "sync")
                    self._load_plugin_module(entry, plugin_dir, "routes")

                else:
                    self._load_plugin_module(entry, plugin_dir, "routes")

                self.registry[plugin_name] = entry
                status = "OK" if not entry["load_error"] else f"ERROR: {entry['load_error']}"
                print(f" [PLUGIN LOADER] [{status}] {plugin_name} ({plugin_type}) enabled={enabled}")

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f" [PLUGIN LOADER] [ERROR] No se pudo cargar {folder_name}: {e}")

    def _load_plugin_module(self, entry: dict, plugin_dir: str, module_name: str):
        """Carga un módulo Python del plugin (routes.py, sync.py, etc.)."""
        module_path = os.path.join(plugin_dir, f"{module_name}.py")
        if not os.path.exists(module_path):
            return

        try:
            full_module = f"tvcat.plugins.{entry['name']}.{module_name}"
            plugin_parent = os.path.dirname(plugin_dir)
            grandparent = os.path.dirname(plugin_parent)
            if grandparent not in sys.path:
                sys.path.insert(0, grandparent)

            spec = importlib.util.spec_from_file_location(full_module, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[full_module] = module
            spec.loader.exec_module(module)

            if module_name == "routes" and hasattr(module, "router"):
                entry["_router"] = module.router
            if module_name == "sync":
                entry["_sync_module"] = module

        except Exception as e:
            entry["load_error"] = f"{module_name}: {e}"
            import traceback
            traceback.print_exc()

    def register_routers(self, app):
        """Registra los routers de todos los plugins en la app FastAPI."""
        for name, data in self.registry.items():
            router = data.get("_router")
            if router and data.get("enabled"):
                prefix = data.get("api_prefix", "")
                app.include_router(router, prefix=prefix)
                print(f" [PLUGIN LOADER] Router registrado: {name} (prefix='{prefix}')")

    def register_static(self, app, base_path: str = ""):
        """Registra las rutas estáticas de los plugins."""
        for name, data in self.registry.items():
            plugin_dir = data.get("_dir", "")
            static_dir = os.path.join(plugin_dir, "static")
            if os.path.isdir(static_dir):
                static_path = f"{base_path}/plugin-static/{name}"
                try:
                    from fastapi.staticfiles import StaticFiles
                    app.mount(static_path, StaticFiles(directory=static_dir), name=f"plugin_{name}")
                    print(f" [PLUGIN LOADER] Static montado: {name} -> {static_path}")
                except Exception as e:
                    print(f" [PLUGIN LOADER] Error montando static de {name}: {e}")

    # --- API de estado ---
    def is_enabled(self, plugin_name: str) -> bool:
        return self.registry.get(plugin_name, {}).get("enabled", False)

    def toggle(self, plugin_name: str) -> bool:
        if plugin_name not in self.registry:
            raise KeyError(f"Plugin no encontrado: {plugin_name}")
        current = self.registry[plugin_name]["enabled"]
        new_state = not current
        self.registry[plugin_name]["enabled"] = new_state
        self._persist_state(plugin_name, new_state)
        return new_state

    def set_enabled(self, plugin_name: str, enabled: bool):
        if plugin_name in self.registry:
            self.registry[plugin_name]["enabled"] = enabled
            self._persist_state(plugin_name, enabled)

    def _persist_state(self, plugin_name: str, enabled: bool):
        plugin_dir = self.registry[plugin_name].get("_dir", "")
        if not plugin_dir:
            return
        state_path = os.path.join(plugin_dir, "state.json")
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump({"enabled": enabled}, f)
        except Exception as e:
            print(f" [PLUGIN LOADER] Error persistiendo estado de {plugin_name}: {e}")

    def get_all(self) -> Dict[str, Any]:
        """Devuelve el registro limpio (sin claves internas) para la API."""
        result = {}
        for name, data in self.registry.items():
            result[name] = {k: v for k, v in data.items() if not k.startswith("_")}
        return result

    def get_frontend_manifest(self) -> List[Dict]:
        """Devuelve la lista de TODOS los plugins con sus recursos frontend."""
        result = []
        for name, data in self.registry.items():
            entry = {
                "name": name,
                "type": data.get("type"),
                "displayName": data.get("displayName", name),
                "description": data.get("description", ""),
                "icon": data.get("icon", ""),
                "iconEmoji": data.get("iconEmoji", ""),
                "enabled": data.get("enabled", False),
                "version": data.get("version", ""),
                "action_category": data.get("action_category", ""),
                "single_button": data.get("single_button", True),
                "js": data.get("js", []),
                "css": data.get("css", []),
                "priority": data.get("priority", 100),
                "applies_to": data.get("applies_to", []),
                "settings_schema": data.get("settings_schema", []),
                "settings_ui": data.get("settings_ui", ""),
                "has_interface": data.get("has_interface", False),
                "interface_icon": data.get("interface_icon", ""),
                "tray": data.get("tray", []),
                "access": data.get("access", {"admin": True, "user": True, "child": False}),
                "load_error": data.get("load_error"),
            }
            # Convertir rutas relativas a absolutas con base path
            base_static = f"/plugin-static/{name}"
            entry["js"] = [f"{base_static}/{f}" for f in entry["js"]]
            entry["css"] = [f"{base_static}/{f}" for f in entry["css"]]
            result.append(entry)
        return result

    # --- API de sincronización (source plugins) ---
    def sync_all(self, progress_callback=None):
        """Ejecuta sync() en todos los source plugins habilitados, en orden."""
        ordered = sorted(
            [p for p in self.registry.values()
             if p.get("type") == "source" and p.get("enabled")],
            key=lambda p: p.get("priority", 100)
        )
        total = len(ordered)
        for idx, plugin in enumerate(ordered):
            name = plugin["name"]
            sync_mod = plugin.get("_sync_module")
            if sync_mod and hasattr(sync_mod, "sync"):
                try:
                    if progress_callback:
                        progress_callback(name, idx, total, 0, 1)
                    sync_mod.sync()
                except Exception as e:
                    print(f" [PLUGIN LOADER] Error en sync de {name}: {e}")
            if progress_callback:
                progress_callback(name, idx, total, 1, 1)

    def check_updates(self) -> Dict[str, bool]:
        """Verifica qué source plugins tienen cambios."""
        changes = {}
        for name, data in self.registry.items():
            if data.get("type") == "source" and data.get("enabled"):
                sync_mod = data.get("_sync_module")
                if sync_mod and hasattr(sync_mod, "check_for_updates"):
                    try:
                        changes[name] = sync_mod.check_for_updates()
                    except:
                        changes[name] = False
        return changes
