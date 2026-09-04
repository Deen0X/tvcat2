/**
 * TVCat 2 - Plugin System Frontend
 * Registry de plugins, pipeline de decorators y carga dinámica.
 */
window.pluginSystem = (function() {
    var registry = {};
    var decoratorsOrder = [];
    var pluginOrder = [];
    var heroActions = [];
    var loadedScripts = {};
    var loadedStyles = {};
    var _booting = false;
    var _bootCallbacks = [];

    function registerPlugin(pluginDef) {
        var name = pluginDef.name;
        pluginDef.enabled = true;
        registry[name] = pluginDef;
        console.log('[PLUGIN SYSTEM] Plugin registrado:', name, pluginDef.type);

        if (pluginDef.type === 'grid-decorator') {
            decoratorsOrder.push(name);
        }
        if (pluginDef.type === 'heropage-action' || pluginDef.type === 'player') {
            heroActions.push(name);
        }
    }

    function getPlugin(name) {
        return registry[name] || null;
    }

    function getPluginsByType(type) {
        var result = [];
        for (var name in registry) {
            if (registry[name].type === type) {
                result.push(registry[name]);
            }
        }
        return sortByPluginOrder(result);
    }

    // Ordena los plugins por el orden guardado del usuario (plugins_order.json) para consistencia.
    // Los plugins sin entrada en pluginOrder van al final, manteniendo su orden relativo de
    // registro de forma ESTABLE (el sort nativo con índices iguales es inestable y reordena
    // de forma aleatoria los plugins nuevos no listados).
    function sortByPluginOrder(result) {
        if (pluginOrder.length > 0) {
            // Registrar orden de aparición original como tie-breaker estable
            var regIndex = {};
            for (var i = 0; i < result.length; i++) { regIndex[result[i].name] = i; }
            var indexMap = {};
            for (var i2 = 0; i2 < pluginOrder.length; i2++) { indexMap[pluginOrder[i2]] = i2; }
            result.sort(function(a, b) {
                var ia = indexMap.hasOwnProperty(a.name) ? indexMap[a.name] : 99999;
                var ib = indexMap.hasOwnProperty(b.name) ? indexMap[b.name] : 99999;
                if (ia !== ib) return ia - ib;
                // Mismo grupo (ambos listados o ambos no listados): mantener orden de registro
                return (regIndex[a.name] - regIndex[b.name]);
            });
        }
        return result;
    }

    function applyGridDecorators(element, itemData) {
        for (var i = 0; i < decoratorsOrder.length; i++) {
            var name = decoratorsOrder[i];
            var plugin = registry[name];
            if (plugin && plugin.onGridItem && plugin.enabled !== false) {
                try {
                    plugin.onGridItem(element, itemData);
                } catch (e) {
                    console.error('[PLUGIN SYSTEM] Error en decorator', name, e);
                }
            }
        }
    }

    function getActionsForCategory(category) {
        var actions = [];
        for (var name in registry) {
            var p = registry[name];
            if ((p.type === 'heropage-action' || p.type === 'player')
                && p.action_category === category
                && (!p.applies_to || p.applies_to.length === 0 || p.applies_to.indexOf(category) >= 0)) {
                actions.push(p);
            }
        }
        return actions;
    }

    function getHeroPageActions(itemData) {
        var buttons = [];
        var candidates = [];
        for (var name in registry) {
            var p = registry[name];
            if (p.type === 'heropage-action' && p.enabled !== false && p.getHeroButtons) {
                candidates.push(p);
            }
        }
        candidates = sortByPluginOrder(candidates);
        for (var i = 0; i < candidates.length; i++) {
            var p = candidates[i];
            try {
                var result = p.getHeroButtons(itemData);
                if (result && result.length) {
                    buttons = buttons.concat(result);
                }
            } catch (e) {
                console.error('[PLUGIN SYSTEM] Error en getHeroButtons de', p.name, e);
            }
        }
        return buttons;
    }

    function setDecoratorOrder(order) {
        decoratorsOrder = order;
    }

    function loadPluginResources(pluginList, onComplete) {
        var total = pluginList.length;
        var loaded = 0;

        if (total === 0) {
            if (onComplete) onComplete();
            return;
        }

        for (var i = 0; i < total; i++) {
            var plugin = pluginList[i];
            // Marcar como activo en el registry
            if (registry[plugin.name]) registry[plugin.name].enabled = true;
            // Cargar CSS
            var cssFiles = plugin.css || [];
            for (var c = 0; c < cssFiles.length; c++) {
                var cssUrl = cssFiles[c];
                if (!loadedStyles[cssUrl]) {
                    loadedStyles[cssUrl] = true;
                    var link = document.createElement('link');
                    link.rel = 'stylesheet';
                    link.href = cssUrl;
                    document.head.appendChild(link);
                }
            }
            // Cargar JS
            var jsFiles = plugin.js || [];
            var jsLoaded = 0;
            if (jsFiles.length === 0) {
                loaded++;
                checkComplete();
                continue;
            }
            for (var j = 0; j < jsFiles.length; j++) {
                var jsUrl = jsFiles[j];
                if (loadedScripts[jsUrl]) {
                    jsLoaded++;
                    if (jsLoaded >= jsFiles.length) {
                        loaded++;
                        checkComplete();
                    }
                    continue;
                }
                loadedScripts[jsUrl] = true;
                var script = document.createElement('script');
                script.src = jsUrl;
                (function(u){
                    script.onload = function() {
                        jsLoaded++;
                        if (jsLoaded >= jsFiles.length) {
                            loaded++;
                            checkComplete();
                        }
                    };
                    script.onerror = function() {
                        console.error('[PLUGIN SYSTEM] Error cargando:', u);
                        jsLoaded++;
                        if (jsLoaded >= jsFiles.length) {
                            loaded++;
                            checkComplete();
                        }
                    };
                })(jsUrl);
                document.body.appendChild(script);
            }
        }

        function checkComplete() {
            if (loaded >= total && onComplete) {
                onComplete();
            }
        }
    }

    function setPluginEnabled(name, enabled) {
        if (registry[name]) registry[name].enabled = enabled;
    }

    return {
        registerPlugin: registerPlugin,
        getPlugin: getPlugin,
        getPluginsByType: getPluginsByType,
        applyGridDecorators: applyGridDecorators,
        getActionsForCategory: getActionsForCategory,
        getHeroPageActions: getHeroPageActions,
        setDecoratorOrder: setDecoratorOrder,
        setPluginOrder: function(order) { pluginOrder = order || []; },
        loadPluginResources: loadPluginResources,
        setPluginEnabled: setPluginEnabled,
        get registry() { return registry; }
    };
})();
