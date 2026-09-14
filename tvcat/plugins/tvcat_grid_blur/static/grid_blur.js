/**
 * TVCat 2 - Grid Decorator: Blur Effect
 * Aplica desenfoque a las carátulas del catálogo.
 * El botón del tray conmuta el EFECTO (no la carga del plugin).
 * Estado del efecto por dispositivo (localStorage).
 */
(function() {
    var LS_KEY = 'tvcat_grid_blur_effect';

    // Efecto APAGADO por defecto en dispositivos nuevos (solo '1' lo enciende).
    function effectOn() {
        try {
            return localStorage.getItem(LS_KEY) === '1';
        } catch (e) { return false; }
    }
    function setEffect(on) {
        try { localStorage.setItem(LS_KEY, on ? '1' : '0'); } catch (e) {}
    }

    if (window.pluginSystem) {
        window.pluginSystem.registerPlugin({
            name: 'tvcat_grid_blur',
            type: 'grid-decorator',
            displayName: 'Efecto Blur',

            isEffectActive: function() { return effectOn(); },
            toggleEffect: function() {
                var on = !effectOn();
                setEffect(on);
                return on;
            },

            onGridItem: function(element, itemData) {
                if (!effectOn()) return;
                var cover = element.querySelector('.grid-item-cover');
                if (cover) {
                    cover.style.filter = 'blur(12px)';
                    cover.style.opacity = '0.5';
                }
            }
        });
    }
})();
