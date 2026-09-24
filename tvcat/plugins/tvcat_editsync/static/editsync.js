/* tvcat_editsync — registro + botón tray auto-aceptar (toggle-effect).
 * El estado vive en el servidor (config auto_accept/show_tray); aquí solo
 * espejo para pintar el borde activo y ocultar el botón si show_tray es OFF.
 * Sin imagen en static -> emoji (lo resuelve el core).
 */
(function() {
    if (!window.pluginSystem) return;

    var _auto = false;

    function refreshAuto() {
        try {
            fetch('/api/editsync/config').then(function(r) { return r.json(); }).then(function(cfg) {
                _auto = !!(cfg && cfg.auto_accept);
            }).catch(function() {});
        } catch (e) {}
    }

    // Botón visible solo si el plugin está habilitado (lo hace el core) Y
    // show_tray está activo en config (patrón indexator, sin cambio core).
    function fixTray() {
        try {
            fetch('/api/editsync/config').then(function(r) { return r.json(); }).then(function(cfg) {
                var show = true;
                try { show = !cfg || cfg.show_tray !== false; } catch (e) {}
                if (show) return;
                var tray = document.getElementById('plugin-tray-icons');
                if (!tray) return;
                var btns = tray.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var oc = btns[i].getAttribute('onclick') || '';
                    if (oc.indexOf('tvcat_editsync') !== -1 && btns[i].parentNode) {
                        btns[i].style.display = 'none';
                    }
                }
            }).catch(function() {});
        } catch (e) {}
    }

    window.pluginSystem.registerPlugin({
        name: 'tvcat_editsync',
        type: 'general',
        displayName: 'EditSync',
        isEffectActive: function() { return _auto; },
        toggleEffect: function() {
            _auto = !_auto;
            try {
                fetch('/api/editsync/config', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ auto_accept: _auto })
                }).then(function() { refreshAuto(); }).catch(function() { refreshAuto(); });
            } catch (e) { refreshAuto(); }
        }
    });

    refreshAuto();
    (function() {
        var origRender = window.renderPluginTray;
        if (origRender) {
            window.renderPluginTray = function() {
                origRender();
                fixTray();
            };
        }
        setTimeout(fixTray, 500);
    })();
})();
