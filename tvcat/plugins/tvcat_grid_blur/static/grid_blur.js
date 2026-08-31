/**
 * TVCat 2 - Grid Decorator: Blur Effect
 * Aplica desenfoque a las carátulas del catálogo.
 */
(function() {
    if (window.pluginSystem) {
        window.pluginSystem.registerPlugin({
            name: 'tvcat_grid_blur',
            type: 'grid-decorator',
            displayName: 'Efecto Blur',

            onGridItem: function(element, itemData) {
                var cover = element.querySelector('.grid-item-cover');
                if (cover) {
                    cover.style.filter = 'blur(12px)';
                    cover.style.opacity = '0.5';
                }
            }
        });
    }
})();
