(function() {
    if (!window.pluginSystem) return;

    var TV_DEBUG = true;
    function log() { if (TV_DEBUG) console.log.apply(console, ['[PLAYER_TV]'].concat(Array.prototype.slice.call(arguments))); }

    function getSetting(key, def) {
        var v = localStorage.getItem('tvcat_player_tv_' + key);
        return v !== null ? JSON.parse(v) : def;
    }

    // ===== Detección de Smart TV =====
    function isSmartTV() {
        try {
            if (window.Catalog && window.Catalog.detectDeviceCapabilities) {
                var caps = window.Catalog.detectDeviceCapabilities();
                if (caps && caps.isSmartTV) return true;
            }
        } catch(e) {}
        var ua = navigator.userAgent;
        return /Tizen|WebOS|SmartTV|Android TV|Philips|SonyBravia|Roku|SamsungBrowser|NetCast|SMART-TV|Smart-TV|Opera TV|Maple|Obigo|Espial|CE-HTML|DIRECTV|DuneHD|AppleTV|GoogleTV/i.test(ua);
    }

    // ===== Fix video plane HW (Tizen 4.0+): estilos "limpios" en el <video> y todos sus ancestros =====
    // El plane HW se desactiva con transform, opacity<1, animation, border-radius, box-shadow o filter.
    function applyTizenPlaneFix() {
        try {
            var videoEl = document.getElementById('tvcat-video-player');
            if (!videoEl) return;
            var el = videoEl;
            while (el && el !== document.body) {
                el.style.animation = 'none';
                el.style.transform = 'none';
                el.style.filter = 'none';
                el.style.backdropFilter = 'none';
                el.style.webkitBackdropFilter = 'none';
                if (el.id === 'player-modal') {
                    el.style.opacity = '1';
                    el.style.transition = 'none';
                }
                el = el.parentElement;
            }
            var container = document.getElementById('player-container');
            if (container) {
                container.style.borderRadius = '0';
                container.style.boxShadow = 'none';
                container.style.border = 'none';
                container.style.overflow = 'visible';
                container.style.animation = 'none';
                container.style.transform = 'none';
            }
            var playerContent = document.querySelector('.player-content');
            if (playerContent) {
                playerContent.style.borderRadius = '0';
                playerContent.style.boxShadow = 'none';
                playerContent.style.transform = 'none';
                playerContent.style.animation = 'none';
                playerContent.style.filter = 'none';
            }
            log('applyTizenPlaneFix aplicado');
        } catch(e) { log('applyTizenPlaneFix error:', e.message); }
    }

    // ===== Bloquear el fullscreen del MODAL SOLO en SmartTV NUEVA (Tizen 4.0+) =====
    // La TV antigua (WebKit 1.1) compone en SW → el fullscreen del modal funciona.
    // La TV nueva (Chromium 56) → modal no activa el plane → necesitamos fullscreen del video.
    var _modalBlocked = false;
    function isNewSmartTV() {
        try {
            if (window.Catalog && window.Catalog.detectDeviceCapabilities) {
                var caps = window.Catalog.detectDeviceCapabilities();
                return caps.isSmartTV && !caps.isOldSmartTV;
            }
        } catch(e) {}
        return false;
    }
    function blockModalFullscreen() {
        if (_modalBlocked) return;
        if (!isNewSmartTV()) return;
        try {
            var modal = document.getElementById('player-modal');
            if (modal) {
                var noop = function() { log('Fullscreen del modal bloqueado (SmartTV nueva)'); return null; };
                if (modal.requestFullscreen) modal.requestFullscreen = noop;
                if (modal.webkitRequestFullscreen) modal.webkitRequestFullscreen = noop;
                if (modal.mozRequestFullScreen) modal.mozRequestFullScreen = noop;
                if (modal.msRequestFullscreen) modal.msRequestFullscreen = noop;
                _modalBlocked = true;
                log('Fullscreen del modal bloqueado');
            }
        } catch(e) { log('blockModalFullscreen error:', e.message); }
    }

    // ===== Fullscreen NATIVO del <video> (webkitEnterFullscreen) =====
    // Es el que fuerza el plane HW. Se reintenta hasta que el video tiene datos y el plane arranca.
    function tryVideoFullscreen() {
        var videoEl = document.getElementById('tvcat-video-player');
        if (!videoEl || !isNewSmartTV()) return;
        var enter = function() {
            try {
                if (videoEl.webkitEnterFullscreen) {
                    videoEl.webkitEnterFullscreen();
                    log('Fullscreen nativo del video (webkitEnterFullscreen)');
                } else if (videoEl.requestFullscreen) {
                    var p = videoEl.requestFullscreen();
                    if (p && p.catch) p.catch(function() {});
                }
            } catch(e) { log('tryVideoFullscreen enter error:', e.message); }
        };
        // Intentar ahora
        enter();
        // Reintentar mientras llega 'playing' / datos
        var attempts = 0;
        var retry = setInterval(function() {
            attempts++;
            if (attempts > 20) { clearInterval(retry); return; }
            if (videoEl.readyState >= 1 || videoEl.currentTime > 0 || (videoEl.webkitDecodedFrameCount && videoEl.webkitDecodedFrameCount > 0)) {
                clearInterval(retry);
                enter();
            }
        }, 500);
    }

    // ===== Override de Catalog.playMedia =====
    // En SmartTV: bloquea fullscreen del modal, limpia el CSS del plane, y fuerza fullscreen nativo del video.
    // En el resto de dispositivos: comportamiento idéntico al reproductor normal (pass-through).
    var _wrapped = false;
    function overridePlayMedia() {
        if (_wrapped) return;
        if (!window.Catalog || !window.Catalog.playMedia) return;
        var _original = window.Catalog.playMedia;
        window.Catalog.playMedia = function(itemData, episode) {
            if (isSmartTV()) {
                try {
                    blockModalFullscreen();
                    applyTizenPlaneFix();
                    _original(itemData, episode);
                    setTimeout(applyTizenPlaneFix, 150);
                    setTimeout(applyTizenPlaneFix, 500);
                    setTimeout(tryVideoFullscreen, 200);
                } catch(e) {
                    log('playMedia override error:', e.message);
                    _original(itemData, episode);
                }
            } else {
                _original(itemData, episode);
            }
        };
        _wrapped = true;
        log('Catalog.playMedia override activado (isSmartTV=' + isSmartTV() + ')');
    }

    // Aplicar el override al cargar. Si catalog.js aún no expuso playMedia, reintentar.
    function ensureOverride() {
        if (_wrapped) return;
        if (window.Catalog && window.Catalog.playMedia) { overridePlayMedia(); return; }
        setTimeout(ensureOverride, 200);
    }
    ensureOverride();
    // Aplicar también al DOMContentLoaded (el modal ya está en el DOM)
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        blockModalFullscreen();
    } else {
        document.addEventListener('DOMContentLoaded', blockModalFullscreen);
    }

    // ===== Registro del plugin (igual que el reproductor normal) =====
    window.pluginSystem.registerPlugin({
        name: 'tvcat_player_tv',
        type: 'player',
        displayName: 'Reproductor TVCat TV',
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
