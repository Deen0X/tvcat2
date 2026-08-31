(function() {
    if (!window.pluginSystem) return;

    function getSetting(key, def) {
        var v = localStorage.getItem('tvcat_player_' + key);
        return v !== null ? JSON.parse(v) : def;
    }

    window.pluginSystem.registerPlugin({
        name: 'tvcat_player',
        type: 'player',
        displayName: 'Reproductor TVCat',
        playerType: 'auto',
        applies_to: ['media', 'series', 'video', 'anime', 'tv', 'peliculas'],
        action_category: 'playback',
        play: function(item) {
            var mode = getSetting('mode', 'auto');
            localStorage.setItem('tvcat_preferred_player', mode);
            var id = item.item_id || item.id;
            var cat = (item.subcategory || '').toLowerCase();
            var hasEps = item.episodes && item.episodes.length > 0;
            Catalog._playWithPlayer(item, id, hasEps, cat, this);
        }
    });
})();
