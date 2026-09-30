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
    // Orden canónico = manifiesto del servidor (estable entre arranques).
    // Sin esto, el orden lo dictaba la llegada de red de cada script.
    var manifestOrder = [];
    var manifestIndex = {};

    function setManifestOrder(names) {
        manifestOrder = [];
        manifestIndex = {};
        for (var i = 0; i < (names || []).length; i++) {
            var n = names[i];
            if (!manifestIndex.hasOwnProperty(n)) {
                manifestIndex[n] = manifestOrder.length;
                manifestOrder.push(n);
            }
        }
        // Reordenar acumulados según el canónico (por si ya registraron).
        decoratorsOrder.sort(cmpNames);
    }

    function cmpNames(a, b) {
        var ia = manifestIndex.hasOwnProperty(a) ? manifestIndex[a] : 99999;
        var ib = manifestIndex.hasOwnProperty(b) ? manifestIndex[b] : 99999;
        if (ia !== ib) return ia - ib;
        return String(a) < String(b) ? -1 : (String(a) > String(b) ? 1 : 0);
    }

    // Nombres del registry en orden canónico (para iterar en vez de for..in).
    function registryOrdered() {
        var names = [];
        for (var name in registry) {
            if (registry.hasOwnProperty(name)) names.push(name);
        }
        names.sort(cmpNames);
        return names;
    }

    function registerPlugin(pluginDef) {
        var name = pluginDef.name;
        pluginDef.enabled = true;
        registry[name] = pluginDef;
        console.log('[PLUGIN SYSTEM] Plugin registrado:', name, pluginDef.type);

        if (pluginDef.type === 'grid-decorator') {
            decoratorsOrder.push(name);
            decoratorsOrder.sort(cmpNames);
        }
        if (pluginDef.type === 'heropage-action' || pluginDef.type === 'player') {
            heroActions.push(name);
            heroActions.sort(cmpNames);
        }
    }

    function getPlugin(name) {
        return registry[name] || null;
    }

    function getPluginsByType(type) {
        var result = [];
        var names = registryOrdered();
        for (var i = 0; i < names.length; i++) {
            if (registry[names[i]].type === type) {
                result.push(registry[names[i]]);
            }
        }
        return sortByPluginOrder(result);
    }

    // Ordena los plugins por el orden guardado del usuario (plugins_order.json) para consistencia.
    // Base y desempate: orden canónico del manifiesto (estable entre arranques),
    // nunca el orden de llegada de red.
    function sortByPluginOrder(result) {
        if (pluginOrder.length > 0) {
            var indexMap = {};
            for (var i2 = 0; i2 < pluginOrder.length; i2++) { indexMap[pluginOrder[i2]] = i2; }
            result.sort(function(a, b) {
                var ia = indexMap.hasOwnProperty(a.name) ? indexMap[a.name] : 99999;
                var ib = indexMap.hasOwnProperty(b.name) ? indexMap[b.name] : 99999;
                if (ia !== ib) return ia - ib;
                return cmpNames(a.name, b.name);
            });
        } else {
            result.sort(function(a, b) { return cmpNames(a.name, b.name); });
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
        var names = registryOrdered();
        for (var i = 0; i < names.length; i++) {
            var p = registry[names[i]];
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
        var names = registryOrdered();
        for (var i = 0; i < names.length; i++) {
            var p = registry[names[i]];
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

    // Anti-caché de JS/CSS de plugins por versión del plugin.json: sin esto el
    // navegador congela el JS viejo (los plugins no llevan ?v= como el core).
    function versionedUrl(url, version) {
        if (!url) return url;
        var v = version || '1.0.0';
        return url + (url.indexOf('?') === -1 ? '?v=' : '&v=') + encodeURIComponent(v);
    }

    // Acciones de página de colección (cabecera de colección abierta):
    // plugins tipo 'collectionpage-action' con getCollectionButtons(collectionData),
    // o 'heropage-action' que ADEMÁS exponga getCollectionButtons (hero, colección
    // o ambas según qué funciones declare cada plugin).
    function getCollectionPageActions(collectionData) {
        var buttons = [];
        var candidates = [];
        var cnames = registryOrdered();
        for (var ci = 0; ci < cnames.length; ci++) {
            var p = registry[cnames[ci]];
            if ((p.type === 'collectionpage-action' || p.type === 'heropage-action') && p.enabled !== false && p.getCollectionButtons) {
                candidates.push(p);
            }
        }
        candidates = sortByPluginOrder(candidates);
        for (var i = 0; i < candidates.length; i++) {
            var q = candidates[i];
            try {
                var result = q.getCollectionButtons(collectionData);
                if (result && result.length) {
                    buttons = buttons.concat(result);
                }
            } catch (e) {
                console.error('[PLUGIN SYSTEM] Error en getCollectionButtons de', q.name, e);
            }
        }
        return buttons;
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
            // Cargar CSS (anti-caché por versión del plugin.json)
            var cssFiles = plugin.css || [];
            for (var c = 0; c < cssFiles.length; c++) {
                var cssUrl = cssFiles[c];
                if (!loadedStyles[cssUrl]) {
                    loadedStyles[cssUrl] = true;
                    var link = document.createElement('link');
                    link.rel = 'stylesheet';
                    link.href = versionedUrl(cssUrl, plugin.version);
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
                script.src = versionedUrl(jsUrl, plugin.version);
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
        getCollectionPageActions: getCollectionPageActions,
        setDecoratorOrder: setDecoratorOrder,
        setPluginOrder: function(order) { pluginOrder = order || []; },
        setManifestOrder: setManifestOrder,
        loadPluginResources: loadPluginResources,
        setPluginEnabled: setPluginEnabled,
        get registry() { return registry; }
    };
})();
