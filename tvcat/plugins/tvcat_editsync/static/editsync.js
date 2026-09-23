/* tvcat_editsync — página propia en sección "General" (solo config).
 * Sin botones hero ni tray en F1. La UI vive en config.html standalone.
 */
(function() {
    if (!window.pluginSystem) return;
    window.pluginSystem.registerPlugin({
        name: 'tvcat_editsync',
        type: 'general',
        displayName: 'EditSync'
    });
})();
