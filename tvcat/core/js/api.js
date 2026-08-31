/**
 * TVCat 2 - API Client
 */
window.API = (function() {
    function ajax(opts) {
        var xhr = new XMLHttpRequest();
        var url = opts.url || '';
        var method = opts.method || 'GET';
        var data = opts.data || null;
        var success = opts.success || function() {};
        var error = opts.error || function() {};

        xhr.open(method, url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.withCredentials = true;
        var token = localStorage.getItem('tvcat_token');
        if (token) { xhr.setRequestHeader('Authorization', 'Bearer ' + token); }

        xhr.onload = function() {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    success(JSON.parse(xhr.responseText));
                } catch (e) {
                    success(xhr.responseText);
                }
            } else {
                error(xhr.status, xhr.responseText);
            }
        };

        xhr.onerror = function() {
            error(0, 'Network error');
        };

        xhr.send(data ? JSON.stringify(data) : null);
    }

    function getPlugins(callback) {
        ajax({
            url: '/api/plugins',
            success: callback
        });
    }

    function getTranslations(callback) {
        ajax({
            url: '/api/translations',
            success: callback
        });
    }

    function updateProfile(data, callback) {
        ajax({
            method: 'POST',
            url: '/api/config',
            data: data,
            success: callback
        });
    }

    function getHistory(callback) {
        ajax({
            url: '/api/watch/history',
            success: callback,
            error: function() { if (callback) callback({ history: [] }); }
        });
    }

    function updateHistory(itemId, videoSrc, lastPosition, duration, completed, callback, episodeId, watchedState, episodeKey) {
        ajax({
            method: 'POST',
            url: '/api/watch/progress',
            data: {
                item_id: itemId,
                video_src: videoSrc,
                episode_id: episodeId || 0,
                episode_key: episodeKey || '',
                progress: lastPosition,
                duration: duration,
                completed: completed ? 1 : 0,
                watched_state: (watchedState === undefined || watchedState === null) ? 0 : watchedState
            },
            success: function(res) { if (callback) callback(res); },
            error: function() { if (callback) callback({ success: false }); }
        });
    }

    function toggleFavorite(id, category, callback) {
        ajax({
            method: 'POST',
            url: '/api/favorites/toggle',
            data: { item_id: id, category: category },
            success: function(res) { if (callback) callback(res); },
            error: function() { if (callback) callback({ success: false, is_favorite: false }); }
        });
    }

    // Umbrales de visualización centralizados (preferencia de usuario).
    // Devuelve { min, max } como enteros de porcentaje. Fallback a localStorage (compatibilidad).
    var _thresholdsCache = null;
    var _thresholdsLoading = false;
    function _loadThresholds(callback) {
        if (_thresholdsCache) { callback(_thresholdsCache); return; }
        if (_thresholdsLoading) { setTimeout(function() { _loadThresholds(callback); }, 50); return; }
        _thresholdsLoading = true;
        ajax({
            url: '/api/config',
            success: function(cfg) {
                _thresholdsCache = {
                    min: (cfg && cfg.watch_threshold_min !== undefined && cfg.watch_threshold_min !== null) ? Number(cfg.watch_threshold_min) : null,
                    max: (cfg && cfg.watch_threshold_max !== undefined && cfg.watch_threshold_max !== null) ? Number(cfg.watch_threshold_max) : null
                };
                _thresholdsLoading = false;
                callback(_thresholdsCache);
            },
            error: function() {
                _thresholdsLoading = false;
                callback({ min: null, max: null });
            }
        });
    }
    function getWatchThresholds(callback) {
        _loadThresholds(function(t) {
            var min = t.min;
            var max = t.max;
            if (min === null || min === undefined) min = parseFloat(localStorage.getItem('tvcat_watch_threshold_min')) || 5;
            if (max === null || max === undefined) max = parseFloat(localStorage.getItem('tvcat_watch_threshold_max')) || 85;
            callback({ min: min, max: max });
        });
    }

    return {
        ajax: ajax,
        getPlugins: getPlugins,
        getTranslations: getTranslations,
        updateProfile: updateProfile,
        getHistory: getHistory,
        updateHistory: updateHistory,
        toggleFavorite: toggleFavorite,
        getWatchThresholds: getWatchThresholds
    };
})();
