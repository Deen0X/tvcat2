/**
 * TVCat 2 Plugin Template
 * Ejemplo de plugin frontend
 */
(function() {
    // Auto-registrarse en el sistema de plugins
    if (window.pluginSystem) {
        window.pluginSystem.registerPlugin({
            name: 'my_plugin',
            type: 'heropage-action',
            action_category: 'utility',
            onHeroPage: function(itemData) {
                console.log('Hero page opened for:', itemData.title);
            }
        });
    }
})();
