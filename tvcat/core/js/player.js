/**
 * TVCat 2 - Core Player
 * Importado textualmente de tvcat1 (catalog.js líneas 1767-2548)
 * Adaptaciones mínimas: construcción de videoSrc usando getStreamSrc()
 */
(function() {

// ===== Estado del reproductor =====
var plyrInstance = null;
var currentPlayerType = null;

// ===== Variables de estado de reproducción =====
var currentMediaId = null;
var currentPlayingItemId = null;
var currentPlayingEpisodeId = 0;
var currentPlayingEpisodeKey = '';
var currentPlayingVideoSrc = null;
var videoPlayerRef = null;
var lastSavedPosition = 0;
var nativeControlsTimer = null;
var _nativeControlsHandler = null;
var _nativeControlsLeaveHandler = null;
var episodesModalWasOpen = false;
var showTimeout = null;
var hideTimeout = null;

// ===== Construir videoSrc desde item/episode (adaptación tvcat2) =====
function getStreamSrc(itemData, episode) {
    if (!episode) return '';

    // Si video_src ya es una ruta del servidor (ej: /api/stream/episode/123), usarla directamente
    var vs = episode.video_src || '';
    if (vs && vs.indexOf('/') === 0) {
        console.log('[STREAM_SRC] video_src (ruta directa)=' + vs);
        return vs;
    }

    // Fallback: video_src en formato item_id:ep_id
    if (vs && vs.indexOf(':') > 0) {
        var url2 = '/api/stream/video/' + encodeURIComponent(vs);
        console.log('[STREAM_SRC] video_src=' + vs + ' -> URL=' + url2);
        return url2;
    }

    // Fallback: usar telegram_link (directo, sin DB lookup)
    var link = episode.telegram_link || (itemData ? itemData.telegram_link : '') || '';
    if (link) {
        var parts = link.split('/');
        var nums = [];
        for (var i = 0; i < parts.length; i++) {
            var n = parseInt(parts[i], 10);
            if (!isNaN(n)) nums.push(parts[i]);
        }
        if (nums.length >= 2) {
            var url = '/api/stream/direct?chat_id=' + nums[0] + '&msg_id=' + nums[nums.length - 1];
            console.log('[STREAM_SRC] telegram_link=' + link + ' -> URL=' + url);
            return url;
        }
    }
    console.log('[STREAM_SRC] No se pudo construir URL: link=' + link + ', video_src=' + vs);
    return '';
}

// ===== Detección de capacidades del dispositivo =====
function detectDeviceCapabilities() {
    var ua = navigator.userAgent;
    var isSmartTV = /Tizen|WebOS|SmartTV|Android TV|Philips|SonyBravia|Roku|SamsungBrowser|NetCast|SMART-TV|Smart-TV|Opera TV|Maple|Obigo|Espial|CE-HTML|DIRECTV|DuneHD|AppleTV|GoogleTV/i.test(ua);
    var isOldSmartTV = isSmartTV && (/NetCast|Opera TV|Maple|Obigo|CE-HTML|Tizen [123]\./i.test(ua) || ( /WebOS/i.test(ua) && /Web0S\/[123]\./i.test(ua) ));
    var supportsPlyr = typeof Plyr !== 'undefined';
    console.log('[PLAYER] Detecci\u00f3n - UA: ' + ua.substring(0, 80) + '..., isSmartTV: ' + isSmartTV + ', isOldSmartTV: ' + isOldSmartTV + ', supportsPlyr: ' + supportsPlyr);
    return { isSmartTV: isSmartTV, isOldSmartTV: isOldSmartTV, supportsPlyr: supportsPlyr };
}

// ===== Obtener tipo de reproductor =====
function getPlayerType() {
    var pref = localStorage.getItem('tvcat_preferred_player');
    if (!pref) pref = 'auto';
    console.log('[PLAYER] getPlayerType() - pref: ' + pref);
    if (pref === 'auto') {
        var caps = detectDeviceCapabilities();
        if (caps.isOldSmartTV) {
            console.log('[PLAYER] SmartTV antigua detectada, forzando reproductor b\u00e1sico.');
            return 'basic';
        }
        if (caps.isSmartTV || !caps.supportsPlyr) return 'native';
        return 'plyr';
    }
    return pref;
}

// ===== Inicializar reproductor =====
function initPlayer() {
    var videoEl = document.getElementById('tvcat-video-player');
    if (!videoEl) return null;

    var playerType = getPlayerType();
    var prevType = currentPlayerType;

    if (prevType === playerType && plyrInstance) {
        try { if (plyrInstance.destroy) plyrInstance.destroy(); } catch (e) { console.log('[PLAYER] Error destruyendo instancia anterior:', e); }
        plyrInstance = null;
    }

    currentPlayerType = playerType;
    console.log('[PLAYER] initPlayer - playerType: ' + playerType + ', prevType: ' + prevType + ', plyrInstance: ' + (plyrInstance ? 'yes' : 'null'));

    if (playerType === 'plyr' && detectDeviceCapabilities().supportsPlyr) {
        console.log('[PLAYER] Creando Plyr...');
        try {
            plyrInstance = new Plyr(videoEl, {
                controls: ['play-large', 'play', 'progress', 'current-time', 'mute', 'volume', 'settings', 'pip', 'fullscreen'],
                seekTime: parseInt(localStorage.getItem('tvcat_small_jump') || 5)
            });

            var injectControls = function() {
                var plyrRoot = document.querySelector('.plyr');
                if (!plyrRoot) return false;
                var elementsToInject = [
                    document.getElementById('skip-intro'),
                    document.getElementById('btn-prev-ep'),
                    document.getElementById('btn-next-ep'),
                    document.querySelector('.left-side'),
                    document.querySelector('.right-side'),
                    document.getElementById('player-title-overlay'),
                    document.getElementById('player-close-btn')
                ];
                var allInjected = true;
                elementsToInject.forEach(function(el) {
                    if (el) { if (!plyrRoot.contains(el)) plyrRoot.appendChild(el); }
                    else { allInjected = false; }
                });
                if (allInjected) console.log('[PLAYER] Controles personalizados inyectados en .plyr');
                return allInjected;
            };

            injectControls();
            plyrInstance.on('ready', injectControls);
            plyrInstance.on('enterfullscreen', injectControls);
            plyrInstance.on('timeupdate', function() { checkSkipIntro(); });

            var attempts = 0;
            var interval = setInterval(function() {
                if (injectControls() || attempts > 5) clearInterval(interval);
                attempts++;
            }, 1000);

            plyrInstance.on('controlsshown', function() { showCustomControls(true); });
            plyrInstance.on('controlshidden', function() { showCustomControls(false); });
            plyrInstance.on('play', function() { showCustomControls(false); });
            plyrInstance.on('pause', function() { showCustomControls(true); });

            return plyrInstance;
        } catch (e) {
            console.log('[PLAYER] Error inicializando Plyr, fallback a nativo:', e);
            currentPlayerType = 'native';
            return videoEl;
        }
    } else if (playerType === 'basic') {
        console.log('[PLAYER] Usando reproductor b\u00e1sico (stream directo).');
        currentPlayerType = 'basic';
        videoEl.controls = true;
        return videoEl;
    } else {
        console.log('[PLAYER] Usando reproductor nativo.');
        currentPlayerType = 'native';
        videoEl.controls = true;
        return videoEl;
    }
}

// ===== Destruir reproductor =====
function destroyPlayer() {
    if (plyrInstance) {
        try { if (plyrInstance.destroy) plyrInstance.destroy(); } catch (e) { console.log('[PLAYER] Error destruyendo Plyr:', e); }
        plyrInstance = null;
    }
    currentPlayerType = null;
}

// ===== Skip intro =====
function checkSkipIntro() {
    // Same visibility logic as other custom controls (no-op stub)
}

// ===== Controles custom =====
function showCustomControls(show) {
    if (showTimeout) clearTimeout(showTimeout);
    if (hideTimeout) clearTimeout(hideTimeout);
    var modal = document.getElementById('player-modal');
    if (!modal) return;
    if (show) {
        modal.classList.add('custom-controls-active');
    } else {
        modal.classList.remove('custom-controls-active');
    }
}

// ===== Mantener controles visibles =====
function keepControlsVisible() {
    var modal = document.getElementById('player-modal');
    if (!modal) return;
    modal.classList.add('custom-controls-active');
    if (hideTimeout) clearTimeout(hideTimeout);
    hideTimeout = setTimeout(function() {
        if (plyrInstance && plyrInstance.controlshidden) {
            modal.classList.remove('custom-controls-active');
        }
    }, 1500);
}

// ===== Saltos =====
function skipIntro() {
    var jumpTime = parseInt(localStorage.getItem('tvcat_intro_jump') || 80);
    if (plyrInstance) { plyrInstance.currentTime = plyrInstance.currentTime + jumpTime; }
    else { var v = document.getElementById('tvcat-video-player'); if (v) v.currentTime = (v.currentTime || 0) + jumpTime; }
    console.log('[PLAYER] Skip intro: +' + jumpTime + 's');
}

function jumpSmall(dir) {
    var amount = parseInt(localStorage.getItem('tvcat_small_jump') || 5);
    if (plyrInstance) { plyrInstance.currentTime = plyrInstance.currentTime + (dir * amount); }
    else { var v = document.getElementById('tvcat-video-player'); if (v) v.currentTime = (v.currentTime || 0) + (dir * amount); }
    console.log('[PLAYER] Jump small: ' + (dir * amount) + 's');
}

function jumpLarge(dir) {
    var amount = parseInt(localStorage.getItem('tvcat_large_jump') || 20);
    if (plyrInstance) { plyrInstance.currentTime = plyrInstance.currentTime + (dir * amount); }
    else { var v = document.getElementById('tvcat-video-player'); if (v) v.currentTime = (v.currentTime || 0) + (dir * amount); }
    console.log('[PLAYER] Jump large: ' + (dir * amount) + 's');
}

// ===== Navegación de episodios =====
function playNext() {
    var eps = (window.Catalog && window.Catalog.currentEpisodes) || {};
    var id = currentMediaId;
    if (!id || !eps[id]) return;
    var mediaData = eps[id];
    var episodes = mediaData.seasons[mediaData.activeSeason] || [];
    var currentSrc = currentPlayingVideoSrc;
    for (var i = 0; i < episodes.length; i++) {
        if (episodes[i].video_src === currentSrc) {
            if (i < episodes.length - 1) { _switchEpisode(id, episodes[i + 1].video_src, episodes[i + 1].title, episodes[i + 1].id, episodes[i + 1].episode_key); }
            return;
        }
    }
}

function playPrevious() {
    var eps = (window.Catalog && window.Catalog.currentEpisodes) || {};
    var id = currentMediaId;
    if (!id || !eps[id]) return;
    var mediaData = eps[id];
    var episodes = mediaData.seasons[mediaData.activeSeason] || [];
    var currentSrc = currentPlayingVideoSrc;
    for (var i = 0; i < episodes.length; i++) {
        if (episodes[i].video_src === currentSrc) {
            if (i > 0) { _switchEpisode(id, episodes[i - 1].video_src, episodes[i - 1].title, episodes[i - 1].id, episodes[i - 1].episode_key); }
            return;
        }
    }
}

function addChunkParam(url) {
    var chunk = localStorage.getItem('tvcat_download_chunk_size');
    if (chunk && url.indexOf('chunk=') < 0) {
        var sep = url.indexOf('?') >= 0 ? '&' : '?';
        return url + sep + 'chunk=' + chunk;
    }
    return url;
}

function _switchEpisode(id, videoSrc, title, episodeId, episodeKey) {
    // Save current episode progress before switching (SIEMPRE, sin filtro) y restaurar ojo a 0 (auto)
    var videoPlayer = document.getElementById('tvcat-video-player');
    if (videoPlayer && currentPlayingItemId) {
        var curTime = Math.floor(videoPlayer.currentTime);
        var duration = Math.floor(videoPlayer.duration || 0);
        var completed = (duration > 0 && curTime / duration > 0.85);
        window.API.updateHistory(currentPlayingItemId, currentPlayingVideoSrc, curTime, duration, completed, null, currentPlayingEpisodeId, 0, currentPlayingEpisodeKey);
    }
    currentPlayingVideoSrc = videoSrc;
    currentPlayingEpisodeId = episodeId || 0;
    currentPlayingEpisodeKey = episodeKey || '';
    var videoPlayer = document.getElementById('tvcat-video-player');
    var titleOverlay = document.getElementById('player-title-overlay');
    if (titleOverlay) {
        titleOverlay.innerText = "\u25B6 " + (title || "Reproduciendo...");
        titleOverlay.style.opacity = '1';
        setTimeout(function() { titleOverlay.style.opacity = '0'; }, 4000);
    }
    // FIX: asignar src directo al <video> (setter player.source de Plyr puede no aplicar si no está ready)
    if (videoPlayer) {
        videoPlayer.src = addChunkParam(videoSrc);
        try { videoPlayer.load(); } catch(e) {}
    }
    if (plyrInstance) {
        plyrInstance.play();
    } else if (videoPlayer) {
        try { videoPlayer.play(); } catch(e) {}
    }
    setTimeout(function() {
        if (videoPlayer) { window.API.updateHistory(id, videoSrc, 0, videoPlayer.duration || 0, false); }
    }, 1000);
}

// ===== PLAY MEDIA (función principal) =====
function playMedia(itemData, episode) {
    var self = this;
    console.time('[PLAY_MEDIA] duracion');

    // Cerrar modal de detalles antes de abrir el reproductor
    if (typeof window.closeDetails === 'function') {
        try { window.closeDetails(); } catch(e) {}
    }

    var videoSrc = getStreamSrc(itemData, episode);
    console.log('[PLAY_MEDIA] videoSrc=' + videoSrc + ', item=' + (itemData ? itemData.title : 'N/A') + ', ep=' + (episode ? episode.title : 'N/A'));
    console.log('[PLAY_MEDIA] episode.episode_key=' + (episode ? episode.episode_key : 'N/A') + ', episode.id=' + (episode ? episode.id : 'N/A'));
    if (!videoSrc) {
        var container = document.getElementById('player-container');
        if (container) container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary);font-size:0.9rem;">Fuente de video no disponible</div>';
        return;
    }

    var episodeTitle = episode ? episode.title : '';

    var playerModal = document.getElementById('player-modal');
    var videoPlayer = document.getElementById('tvcat-video-player');
    var titleOverlay = document.getElementById('player-title-overlay');

    if (!playerModal || !videoPlayer) return;

    // Guardar referencia persistente al elemento <video> (Plyr lo mueve dentro de .plyr y
    // getElementById puede dejar de encontrarlo al cerrar).
    videoPlayerRef = videoPlayer;

    var playerType = getPlayerType();
    var capturedVideoSrc = videoSrc;
    console.log('[PLAY_MEDIA] playerType=' + playerType + ', src=' + capturedVideoSrc + ', modal=' + (playerModal ? 'OK' : 'NULL') + ', video=' + (videoPlayer ? 'OK' : 'NULL'));

    // Mostrar modal
    playerModal.classList.remove('hidden');
    playerModal.style.display = '';
    playerModal.style.visibility = '';
    playerModal.style.opacity = '';

    // Forzar contenedor a llenar la pantalla
    var pContainer = playerModal.querySelector('.player-container');
    if (pContainer) {
        pContainer.style.width = '100%';
        pContainer.style.height = '100%';
        pContainer.style.maxWidth = '100%';
        pContainer.style.borderRadius = '0';
    }

    // 1. BASIC PLAYER (SmartTV antigua): modal simplificado + ocultar todo lo demas
    if (playerType === 'basic') {
        console.log('[PLAYER] Basic Player nativo, reproduciendo directo:', capturedVideoSrc);

        // IMPORTANTE: setear estado de reproducción (la rama basic retorna antes del bloque de otras ramas)
        currentMediaId = itemData ? (itemData.item_id || itemData.id) : null;
        currentPlayingItemId = currentMediaId;
        currentPlayingEpisodeId = episode ? (episode.id || 0) : 0;
        currentPlayingEpisodeKey = episode ? (episode.episode_key || '') : '';
        currentPlayingVideoSrc = capturedVideoSrc;
        if (window.Catalog) {
            window.Catalog.currentMediaId = currentMediaId;
            window.Catalog.currentPlayingItemId = currentPlayingItemId;
            window.Catalog.currentPlayingVideoSrc = capturedVideoSrc;
        }

        // Ocultar TODO excepto el player-modal (detalles, sidebar, navbar, otros modales)
        var hideEls = document.querySelectorAll('#detail-modal, #episodes-modal, #settings-modal, #filter-modal, #side-menu, #side-menu-overlay, .navbar');
        for (var hi = 0; hi < hideEls.length; hi++) {
            hideEls[hi].style.display = 'none';
        }

        // Simplificar el player-modal (sin flexbox ni animaciones)
        playerModal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:#000;z-index:99999;display:block;';
        playerModal.classList.remove('hidden');

        if (pContainer) {
            pContainer.style.cssText = 'width:100%;height:100%;max-width:100%;background:#000;overflow:hidden;position:relative;';
        }

        // Todos los controles custom como position:fixed directos en body (z-index maximo)
        // Todos con dimensiones explicitas + fondo + borde = area de click solida (la X funciona asi)
        // onclick inline (mismo mecanismo que la X, probado en WebKit 1.1)
        var injectCustomControlsPC = function() {
            var freshIds = ['basic-seekbar','player-close-btn','jump-large-back','jump-small-back','jump-small-fwd','jump-large-fwd','btn-prev-ep','btn-next-ep','skip-intro','player-title-overlay'];
            for (var fi = 0; fi < freshIds.length; fi++) {
                var old = document.getElementById(freshIds[fi]);
                if (old) old.parentNode.removeChild(old);
            }
            var makeEl = function(html) { var t=document.createElement('div'); t.innerHTML=html; return t.firstChild; };
            var h = function(id,html) { var el=makeEl(html); el.id=id; document.body.appendChild(el); return el; };

            // Close button (referencia: este SI funciona)
            var Xs = 'position:fixed;z-index:999999;top:20px;right:20px;width:44px;height:44px;border-radius:50%;background:rgba(0,0,0,0.7);border:1px solid rgba(255,255,255,0.5);color:#fff;font-size:24px;line-height:44px;text-align:center;cursor:pointer;padding:0;';
            h('player-close-btn', '<button style="'+Xs+'" onclick="window.Catalog.closePlayer()" title="Cerrar">&times;</button>');

            // Jump buttons: dimensiones explicitas SOLIDAS (igual que X pero rectangulares)
            var Js = 'position:fixed;z-index:999999;width:52px;height:52px;line-height:52px;text-align:center;font-size:28px;font-weight:bold;color:rgba(255,255,255,0.7);background:rgba(0,0,0,0.7);border:1px solid rgba(255,255,255,0.4);border-radius:8px;cursor:pointer;text-shadow:0 0 15px rgba(0,0,0,1);';
            h('jump-large-back', '<button style="'+Js+'top:50%;left:4%;margin-top:-26px;" onclick="window.Catalog.jumpLarge(-1)" title="Salto largo atr\u00e1s">&#171;</button>');
            h('jump-small-back', '<button style="'+Js+'top:50%;left:9%;margin-top:-26px;" onclick="window.Catalog.jumpSmall(-1)" title="Salto corto atr\u00e1s">&#8249;</button>');
            h('jump-small-fwd', '<button style="'+Js+'top:50%;right:9%;margin-top:-26px;" onclick="window.Catalog.jumpSmall(1)" title="Salto corto adelante">&#8250;</button>');
            h('jump-large-fwd', '<button style="'+Js+'top:50%;right:4%;margin-top:-26px;" onclick="window.Catalog.jumpLarge(1)" title="Salto largo adelante">&#187;</button>');

            // Navigation buttons
            var Ns = 'position:fixed;z-index:999999;top:20px;background:rgba(0,0,0,0.7);border:1px solid rgba(255,255,255,0.4);color:#fff;padding:12px 28px;font-size:14px;font-weight:600;border-radius:6px;cursor:pointer;';
            h('btn-prev-ep', '<button style="'+Ns+'left:20%;" onclick="window.Catalog.playPrevious()">Anterior</button>');
            h('btn-next-ep', '<button style="'+Ns+'right:20%;" onclick="window.Catalog.playNext()">Siguiente</button>');

            // Skip intro
            h('skip-intro', '<button style="display:none;position:fixed;z-index:999999;top:80px;left:50%;margin-left:-80px;background:rgba(0,0,0,0.8);border:1px solid rgba(255,255,255,0.4);color:#fff;padding:10px 25px;font-size:13px;font-weight:600;border-radius:6px;cursor:pointer;" onclick="window.Catalog.skipIntro()">Saltar Intro</button>');
            h('player-title-overlay','<div style="position:fixed;bottom:120px;left:50%;margin-left:-200px;width:400px;color:#fff;font-size:1.1rem;font-weight:500;z-index:999998;text-shadow:0 2px 4px rgba(0,0,0,0.8);white-space:nowrap;text-align:center;pointer-events:none;"></div>');
        };
        injectCustomControlsPC();

        if (videoPlayer) {
            videoPlayer.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;display:block;background:#000;opacity:1;transform:none;webkitTransform:none;z-index:1;';
            // Barra nativa OFF: en WebKit 1.1 el knob de seek nativo no captura el drag (vuelve a currentTime).
            // Se sustituye por barra custom que maneja mousedown/mousemove/mouseup correctamente.
            videoPlayer.controls = false;
            videoPlayer.removeAttribute('muted');
            videoPlayer.muted = false;
            videoPlayer.volume = 1.0;
            videoPlayer.src = addChunkParam(capturedVideoSrc);
            videoPlayer.load();
            try { videoPlayer.play(); } catch(e) {}
        }

        // === Barra de seek custom (funciona en WebKit 1.1 con ratón/mando) ===
        (function buildBasicSeekBar() {
            var v = document.getElementById('tvcat-video-player');
            if (!v) return;
            var bar = document.createElement('div');
            bar.id = 'basic-seekbar';
            bar.style.cssText = 'position:fixed;bottom:0;left:0;width:100%;height:48px;z-index:999999;background:rgba(0,0,0,0.75);';

            var playBtn = document.createElement('button');
            playBtn.id = 'basic-play';
            playBtn.innerHTML = '&#9654;';
            playBtn.style.cssText = 'position:absolute;left:8px;top:0;width:48px;height:48px;background:none;border:none;color:#fff;font-size:22px;cursor:pointer;';
            playBtn.onclick = function() {
                if (v.paused) { try { v.play(); } catch(e) {} playBtn.innerHTML = '&#10074;&#10074;'; }
                else { v.pause(); playBtn.innerHTML = '&#9654;'; }
            };

            var timeLabel = document.createElement('span');
            timeLabel.id = 'basic-time';
            timeLabel.style.cssText = 'position:absolute;left:64px;top:16px;color:#fff;font-size:14px;white-space:nowrap;';
            timeLabel.innerHTML = '0:00 / 0:00';

            var track = document.createElement('div');
            track.id = 'basic-track';
            track.style.cssText = 'position:absolute;left:190px;right:12px;top:21px;height:8px;background:rgba(255,255,255,0.25);border-radius:4px;cursor:pointer;';
            var fill = document.createElement('div');
            fill.id = 'basic-fill';
            fill.style.cssText = 'position:absolute;top:0;left:0;width:0%;height:100%;background:#e11d48;border-radius:4px;';
            track.appendChild(fill);

            bar.appendChild(playBtn);
            bar.appendChild(timeLabel);
            bar.appendChild(track);
            document.body.appendChild(bar);

            function fmt(t) {
                if (!isFinite(t) || t < 0) t = 0;
                var m = Math.floor(t / 60), s = Math.floor(t % 60);
                return m + ':' + (s < 10 ? '0' + s : s);
            }
            var seeking = false;
            function seekAt(clientX) {
                var rect = track.getBoundingClientRect();
                var w = rect.width || 1;
                var pct = (clientX - rect.left) / w;
                pct = Math.max(0, Math.min(1, pct));
                fill.style.width = (pct * 100) + '%';
                if (v.duration && isFinite(v.duration)) {
                    try { v.currentTime = pct * v.duration; } catch(e) {}
                }
            }
            track.onmousedown = function(e) {
                seeking = true;
                var cx = e.clientX || 0;
                if (cx === 0 && e.touches) cx = e.touches[0].clientX;
                seekAt(cx);
                return false;
            };
            document.onmousemove = function(e) {
                if (!seeking) return;
                var cx = e.clientX || 0;
                if (cx === 0 && e.touches) cx = e.touches[0].clientX;
                seekAt(cx);
            };
            document.onmouseup = function() { seeking = false; };

            v.ontimeupdate = function() {
                if (v.duration && isFinite(v.duration)) {
                    fill.style.width = ((v.currentTime / v.duration) * 100) + '%';
                    timeLabel.innerHTML = fmt(v.currentTime) + ' / ' + fmt(v.duration);
                }
                if (!v.paused) playBtn.innerHTML = '&#10074;&#10074;';
                else playBtn.innerHTML = '&#9654;';
            };
            v.onended = function() { playBtn.innerHTML = '&#9654;'; };
        })();

        // === Auto-hide de controles custom ===
        var ctrlIds = ['basic-seekbar','player-close-btn','jump-large-back','jump-small-back','jump-small-fwd','jump-large-fwd','btn-prev-ep','btn-next-ep','skip-intro','player-title-overlay'];
        var hideTimer = null;
        function showAll() {
            for (var i = 0; i < ctrlIds.length; i++) {
                var el = document.getElementById(ctrlIds[i]);
                if (el) el.style.visibility = 'visible';
            }
            if (hideTimer) clearTimeout(hideTimer);
            hideTimer = setTimeout(hideAll, 3500);
        }
        function hideAll() {
            for (var i = 0; i < ctrlIds.length; i++) {
                var el = document.getElementById(ctrlIds[i]);
                if (el) el.style.visibility = 'hidden';
            }
        }
        showAll();
        // Click en el video = mostrar custom controls (sin bloquear barra nativa)
        if (videoPlayer) videoPlayer.onclick = function() { showAll(); };
        // Teclado = mostrar
        var pk = function() { showAll(); };
        window.addEventListener('keydown', pk);
        document.addEventListener('keydown', pk);

        // Titulo overlay
        if (titleOverlay) {
            titleOverlay.innerText = "\u25B6 " + (episodeTitle || "Reproduciendo...");
        }

        return;
    }

    // 2. OTROS REPRODUCTORES (Plyr / Nativo)
    currentMediaId = itemData ? (itemData.item_id || itemData.id) : null;
    currentPlayingItemId = currentMediaId;
    currentPlayingEpisodeId = episode ? (episode.id || 0) : 0;
    currentPlayingEpisodeKey = episode ? (episode.episode_key || '') : '';
    currentPlayingVideoSrc = capturedVideoSrc;

    // Título overlay
    var titleText = episodeTitle || "Reproduciendo...";
    if (!episodeTitle) {
        var titleEl = document.getElementById('detail-title');
        if (titleEl) titleText = titleEl.innerText;
    }
    if (titleOverlay) {
        titleOverlay.innerText = "\u25B6 " + titleText;
        titleOverlay.style.opacity = '1';
        setTimeout(function() { titleOverlay.style.opacity = '0'; }, 4000);
    }

    // Cargar vídeo
    // FIX STREAMING: asignar el src DIRECTAMENTE al <video> ANTES de crear Plyr.
    // El setter player.source de Plyr no siempre aplica si la instancia aún no está 'ready',
    // dejando el placeholder blank.mp4 (duration=1). Asignar el src al elemento es lo más fiable.
    if (videoPlayer) {
        videoPlayer.src = addChunkParam(capturedVideoSrc);
    }
    var player = initPlayer();

    if (player) {
        if (videoPlayer) {
            try { videoPlayer.load(); } catch(e) {}
        }
        try { videoPlayer.focus(); } catch(e) {}

        var doFullscreen = function() {
            var applySizing = function() {
                var vw = window.innerWidth;
                var vh = window.innerHeight;
                var ratio = 16 / 9;
                var cw = Math.min(vw * 0.95, 1100);
                var ch = cw / ratio;
                if (ch > vh * 0.9) { ch = vh * 0.9; cw = ch * ratio; }
                if (pContainer) {
                    pContainer.style.width = cw + 'px';
                    pContainer.style.height = ch + 'px';
                    pContainer.style.maxWidth = cw + 'px';
                    pContainer.style.margin = 'auto';
                }
                showCustomControls(true);
            };
            try {
                var p = playerModal.requestFullscreen();
                if (p) { p.catch(function() { applySizing(); }); }
            } catch(e) { applySizing(); }
        };

        // Autoplay primero (usa el gesto del usuario).
        // FIX FULLSCREEN: requestFullscreen DEBE llamarse DENTRO del gesto del usuario.
        // Llamarlo en el .then() de play() pierde el gesto y falla con
        // "API can only be initiated by a user gesture" (en SmartTV nunca entraba en fullscreen).
        var doPlay = function() {
            var p;
            if (currentPlayerType === 'plyr' && plyrInstance) { p = plyrInstance.play(); }
            else { p = videoPlayer.play(); }
            if (p && p.catch) { p.catch(function() {}); }
            doFullscreen();
        };
        try { doPlay(); } catch(e) { doFullscreen(); }
    }

    // Inyectar controles custom
    var injectCustomControls = function() {
        var getOrCreateControl = function(id, html) {
            var el = document.getElementById(id);
            if (!el) { var temp = document.createElement('div'); temp.innerHTML = html; el = temp.firstChild; el.id = id; }
            return el;
        };
        var elementsToInject = [
            getOrCreateControl('skip-intro', '<button id="skip-intro" class="skip-btn" onclick="Catalog.skipIntro()">Saltar Intro</button>'),
            getOrCreateControl('btn-prev-ep', '<button class="nav-text-btn prev-ep-btn" id="btn-prev-ep" onclick="Catalog.playPrevious()">Anterior</button>'),
            getOrCreateControl('btn-next-ep', '<button class="nav-text-btn next-ep-btn" id="btn-next-ep" onclick="Catalog.playNext()">Siguiente</button>'),
            getOrCreateControl('left-side', '<div class="side-controls left-side"><button class="jump-btn jump-large" onclick="Catalog.jumpLarge(-1)" title="Salto Largo Atr\u00e1s">&lt;&lt;</button><button class="jump-btn jump-small" onclick="Catalog.jumpSmall(-1)" title="Salto Corto Atr\u00e1s">&lt;</button></div>'),
            getOrCreateControl('right-side', '<div class="side-controls right-side"><button class="jump-btn jump-small" onclick="Catalog.jumpSmall(1)" title="Salto Corto Adelante">&gt;</button><button class="jump-btn jump-large" onclick="Catalog.jumpLarge(1)" title="Salto Largo Adelante">&gt;&gt;</button></div>'),
            getOrCreateControl('player-title-overlay', '<div id="player-title-overlay" class="player-title-overlay"></div>'),
            getOrCreateControl('player-close-btn', '<button id="player-close-btn" class="player-ctrl-close" onclick="Catalog.closePlayer()" title="Cerrar">&times;</button>')
        ];
        var parentContainer = document.querySelector('.plyr') || document.getElementById('player-modal');
        if (!parentContainer) return;
        elementsToInject.forEach(function(el) { if (el && !parentContainer.contains(el)) parentContainer.appendChild(el); });
    };

    injectCustomControls();
    setTimeout(injectCustomControls, 100);
    setTimeout(injectCustomControls, 300);
    setTimeout(injectCustomControls, 500);

    showCustomControls(true);

    // Native mode: auto-hide
    if (currentPlayerType === 'native') {
        if (nativeControlsTimer) clearTimeout(nativeControlsTimer);
        nativeControlsTimer = setTimeout(function() { showCustomControls(false); }, 3000);
        var playerContainer = playerModal;
        var resetNativeTimer = function() {
            showCustomControls(true);
            if (nativeControlsTimer) clearTimeout(nativeControlsTimer);
            nativeControlsTimer = setTimeout(function() { showCustomControls(false); }, 3000);
        };
        if (_nativeControlsHandler) {
            playerContainer.removeEventListener('mousemove', _nativeControlsHandler);
            playerContainer.removeEventListener('click', _nativeControlsHandler);
            playerContainer.removeEventListener('touchstart', _nativeControlsHandler);
        }
        if (_nativeControlsLeaveHandler) {
            playerContainer.removeEventListener('mouseleave', _nativeControlsLeaveHandler);
        }
        _nativeControlsHandler = resetNativeTimer;
        _nativeControlsLeaveHandler = function() {
            if (nativeControlsTimer) clearTimeout(nativeControlsTimer);
            nativeControlsTimer = setTimeout(function() { showCustomControls(false); }, 800);
        };
        playerContainer.addEventListener('mousemove', resetNativeTimer);
        playerContainer.addEventListener('click', resetNativeTimer);
        playerContainer.addEventListener('touchstart', resetNativeTimer);
        playerContainer.addEventListener('mouseleave', _nativeControlsLeaveHandler);
    }

    // History tracking
    lastSavedPosition = 0;
    videoPlayer.ontimeupdate = function() {
        var curTime = Math.floor(videoPlayer.currentTime);
        var duration = Math.floor(videoPlayer.duration || 0);
        checkSkipIntro();
        // Guardado periódico ligero (cada 20s). El guardado definitivo se hace al salir/cambiar/terminar.
        if (curTime > 5 && duration > 10 && curTime % 20 === 0 && curTime !== lastSavedPosition) {
            lastSavedPosition = curTime;
            window.API.updateHistory(currentPlayingItemId, currentPlayingVideoSrc, curTime, duration, false, null, currentPlayingEpisodeId, 0, currentPlayingEpisodeKey);
        }
    };

    videoPlayer.onended = function() {
        var duration = Math.floor(videoPlayer.duration || 0);
        // Al terminar se guarda SIEMPRE (posición final) y el ojo vuelve a 0 (auto) para recalcular.
        if (duration > 10) { 
            window.API.updateHistory(currentPlayingItemId, currentPlayingVideoSrc, duration, duration, true, null, currentPlayingEpisodeId, 0, currentPlayingEpisodeKey);
        }
    };

    // Video eventos (debug)
    videoPlayer.onerror = function() {
        var err = videoPlayer.error;
        console.log('[VIDEO] Error code=' + (err ? err.code : 'unknown') + ', message=' + (err ? err.message : 'N/A'));
    };
    videoPlayer.oncanplay = function() {
        console.log('[VIDEO] canplay - src=' + videoPlayer.src + ', duration=' + videoPlayer.duration);
    };
    videoPlayer.onwaiting = function() {
        console.log('[VIDEO] waiting (buffering)... currentTime=' + videoPlayer.currentTime);
    };
    var _durLogged = false;
    videoPlayer.onplaying = function() {
        console.log('[VIDEO] playing - currentTime=' + videoPlayer.currentTime + ', readyState=' + videoPlayer.readyState);
        if (!_durLogged) { _durLogged = true; console.timeEnd('[PLAY_MEDIA] duracion'); }
    };
    videoPlayer.onloadedmetadata = function() {
        console.log('[VIDEO] loadedmetadata - duration=' + videoPlayer.duration + ', videoWidth=' + videoPlayer.videoWidth + 'x' + videoPlayer.videoHeight);
    };
    videoPlayer.onsuspend = function() {
        console.log('[VIDEO] suspend - descarga suspendida, buffered=' + (videoPlayer.buffered.length > 0 ? videoPlayer.buffered.end(0) : 0));
    };
    videoPlayer.onstalled = function() {
        console.log('[VIDEO] stalled - descarga estancada');
    };
    var _lastProgressLog = 0;
    videoPlayer.onprogress = function() {
        if (videoPlayer.buffered.length > 0) {
            var now = Date.now();
            if (now - _lastProgressLog > 5000) {
                _lastProgressLog = now;
                console.log('[VIDEO] progress - buffered=' + videoPlayer.buffered.end(0) + 's / ' + videoPlayer.duration + 's');
            }
        }
    };

    // Resume from history
    window.API.ajax({ url: '/api/watch/history', success: function(histRes) {
        var resumeTime = 0;
        if (histRes && histRes.history) {
            var epKey = episode ? (episode.episode_key || '') : '';
            var epId = episode ? (episode.id || 0) : 0;
            var key = (itemData ? (itemData.item_id || itemData.id) : '') + ':' + epId;
            for (var i = 0; i < histRes.history.length; i++) {
                var h = histRes.history[i];
                // Match por episode_key (clave natural) con prioridad
                if (epKey && h.episode_key === epKey) { resumeTime = h.progress || 0; break; }
                // Fallback: item_id:episode_id (legacy)
                if (h.item_id && h.episode_id !== undefined) {
                    var hKey = h.item_id + ':' + h.episode_id;
                    if (hKey === key) { resumeTime = h.progress || 0; break; }
                }
                // Fallback: match by video_src (for legacy data)
                if (h.video_src === currentPlayingVideoSrc) { resumeTime = h.last_position || h.progress || 0; break; }
            }
        }
        if (resumeTime > 5) {
            var applied = false;
            var applyResume = function() {
                if (applied) return;
                if (videoPlayer.readyState >= 1 || videoPlayer.currentTime > 0) {
                    applied = true;
                    console.log('[PLAYBACK] Reanudando posici\u00f3n en:', resumeTime);
                    videoPlayer.currentTime = resumeTime;
                    videoPlayer.removeEventListener('canplay', applyResume);
                    videoPlayer.removeEventListener('loadedmetadata', applyResume);
                    videoPlayer.removeEventListener('playing', applyResume);
                }
            };
            videoPlayer.addEventListener('canplay', applyResume);
            videoPlayer.addEventListener('loadedmetadata', applyResume);
            videoPlayer.addEventListener('playing', applyResume);
            applyResume();
            var retryCount = 0;
            var resumeInterval = setInterval(function() {
                retryCount++;
                if (applied || retryCount > 50) { clearInterval(resumeInterval); return; }
                if (videoPlayer.readyState >= 1 || videoPlayer.currentTime > 0) { applyResume(); clearInterval(resumeInterval); }
            }, 200);
        }
    }});
}

// ===== CLOSE PLAYER =====
function closePlayer() {
    var playerModal = document.getElementById('player-modal');
    // Usar la referencia persistente (Plyr mueve el <video> dentro de .plyr y getElementById
    // puede devolver null al cerrar). currentTime sigue siendo legible desde la referencia.
    var videoPlayer = videoPlayerRef || document.getElementById('tvcat-video-player');

    // Guardar SIEMPRE la posición ANTES de resetear el video (src='' resetea currentTime).
    if (videoPlayer && currentPlayingItemId) {
        var _curTime = Math.floor(videoPlayer.currentTime);
        var _duration = Math.floor(videoPlayer.duration || 0);
        var _completed = (_duration > 0 && _curTime / _duration > 0.85);
        console.log('[PLAYBACK] closePlayer -> guardando: item=' + currentPlayingItemId + ', epKey=' + currentPlayingEpisodeKey + ', curTime=' + _curTime + ', dur=' + _duration + ', completed=' + _completed);
        window.API.updateHistory(currentPlayingItemId, currentPlayingVideoSrc, _curTime, _duration, _completed, null, currentPlayingEpisodeId, 0, currentPlayingEpisodeKey);
    } else {
        console.log('[PLAYBACK] closePlayer -> NO se guarda (videoPlayer=' + (videoPlayer ? 'ok' : 'null') + ', item=' + currentPlayingItemId + ')');
    }

    var iframe = document.getElementById('basic-player-iframe');
    if (iframe) { iframe.remove(); }
    if (videoPlayer) {
        videoPlayer.style.display = '';
        videoPlayer.style.width = '';
        videoPlayer.style.height = '';
        videoPlayer.style.position = '';
        videoPlayer.style.top = '';
        videoPlayer.style.left = '';
        videoPlayer.style.opacity = '';
        videoPlayer.style.transform = '';
        videoPlayer.style.webkitTransform = '';
        videoPlayer.style.zIndex = '';
        videoPlayer.style.objectFit = '';
        videoPlayer.controls = false;
        videoPlayer.src = '';
    }
    var pContainer = playerModal ? playerModal.querySelector('.player-container') : null;
    if (pContainer) {
        pContainer.style.width = '';
        pContainer.style.height = '';
        pContainer.style.maxWidth = '';
        pContainer.style.position = '';
        pContainer.style.top = '';
        pContainer.style.left = '';
        pContainer.style.borderRadius = '';
    }
    if (playerModal) {
        playerModal.style.position = '';
        playerModal.style.top = '';
        playerModal.style.left = '';
        playerModal.style.width = '';
        playerModal.style.height = '';
        playerModal.style.zIndex = '';
        var parentNavs = playerModal.querySelectorAll('.nav-text-btn, .side-controls, #skip-intro, #player-title-overlay, #player-close-btn, .buffer-container, #cache-bar-container');
        for (var pi = 0; pi < parentNavs.length; pi++) { parentNavs[pi].style.display = ''; }
    }
    if (nativeControlsTimer) { clearTimeout(nativeControlsTimer); nativeControlsTimer = null; }
    var playerModal = document.getElementById('player-modal');
    if (playerModal) {
        if (_nativeControlsHandler) {
            playerModal.removeEventListener('mousemove', _nativeControlsHandler);
            playerModal.removeEventListener('click', _nativeControlsHandler);
            playerModal.removeEventListener('touchstart', _nativeControlsHandler);
            _nativeControlsHandler = null;
        }
        if (_nativeControlsLeaveHandler) {
            playerModal.removeEventListener('mouseleave', _nativeControlsLeaveHandler);
            _nativeControlsLeaveHandler = null;
        }
    }
    if (videoPlayer) {
        videoPlayer.ontimeupdate = null;
        videoPlayer.onended = null;
        videoPlayer.style.position = '';
        videoPlayer.style.top = '';
        videoPlayer.style.left = '';
        videoPlayer.style.zIndex = '';
        videoPlayer.pause();
        videoPlayer.src = "";
    }
    if (playerModal) {
        playerModal.classList.remove('custom-controls-active');
        playerModal.classList.add('hidden');
        playerModal.style.display = 'none';
        playerModal.style.visibility = 'hidden';
        if (document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement) {
            if (document.exitFullscreen) { document.exitFullscreen(); }
            else if (document.webkitExitFullscreen) { document.webkitExitFullscreen(); }
            else if (document.msExitFullscreen) { document.msExitFullscreen(); }
        }
    }
    // Limpiar controles custom inyectados en document.body (rama basic)
    var bodyCtrlIds = ['basic-seekbar','player-close-btn','jump-large-back','jump-small-back','jump-small-fwd','jump-large-fwd','btn-prev-ep','btn-next-ep','skip-intro','player-title-overlay'];
    for (var bci = 0; bci < bodyCtrlIds.length; bci++) {
        var be = document.getElementById(bodyCtrlIds[bci]);
        if (be && be.parentNode) be.parentNode.removeChild(be);
    }
    // Limpiar handlers globales de la barra de seek
    document.onmousemove = null;
    document.onmouseup = null;
    // hideGlobalLoader no esta disponible en tvcat2, ignorar
    // Restaurar elementos ocultados por el reproductor basic
    var restoreList = document.querySelectorAll('#detail-modal, #episodes-modal, #settings-modal, #filter-modal, #side-menu, #side-menu-overlay, .navbar');
    for (var ri = 0; ri < restoreList.length; ri++) {
        restoreList[ri].style.display = '';
    }
    var detail = document.getElementById('detail-modal');
    if (detail) detail.classList.remove('hidden');
    destroyPlayer();
    videoPlayerRef = null;
    if (episodesModalWasOpen) {
        episodesModalWasOpen = false;
        var episodesModal = document.getElementById('episodes-modal');
        if (episodesModal) {
            episodesModal.classList.remove('hidden');
            episodesModal.style.display = '';
            episodesModal.style.visibility = '';
            episodesModal.style.opacity = '';
            setTimeout(function() {
                var target = episodesModal.querySelector('.episode-card.next-to-play') || episodesModal.querySelector('.episode-card');
                if (target && window.navEngine) { window.navEngine.focus(target); }
            }, 150);
        }
    }
}

// ===== Exportar (funciones de detección para catalog.js) =====
window.detectDeviceCapabilities = detectDeviceCapabilities;
window.getPlayerType = getPlayerType;

// ===== Remote Control Route Player Key =====
function flashPlayerButton(actionType, dir) {
    var el = null;
    if (actionType === 'jump-small') {
        var btns = document.querySelectorAll('#player-modal .jump-small');
        el = (dir < 0) ? btns[0] : btns[1];
    } else if (actionType === 'jump-large') {
        var btns = document.querySelectorAll('#player-modal .jump-large');
        el = (dir < 0) ? btns[0] : btns[1];
    } else if (actionType === 'skip') {
        el = document.getElementById('skip-intro');
    } else if (actionType === 'play-pause') {
        el = document.querySelector('.plyr__control--toggle') || document.querySelector('#player-modal .plyr__control');
    }
    if (el) {
        el.style.transform = 'scale(0.92)';
        el.style.filter = 'brightness(1.5)';
        el.style.boxShadow = '0 0 15px rgba(225, 29, 72, 0.8)';
        setTimeout(function() {
            el.style.transform = '';
            el.style.filter = '';
            el.style.boxShadow = '';
        }, 180);
    }
}

function routePlayerKey(position) {
    if (position === 'J') {
        window.Catalog.closePlayer();
        return;
    }
    if (position === 'E') {
        var videoEl = document.getElementById('tvcat-video-player');
        var plyr = window.Catalog.plyrInstance;
        flashPlayerButton('play-pause');
        if (plyr) {
            plyr.togglePlay();
        } else if (videoEl) {
            if (videoEl.paused) videoEl.play();
            else videoEl.pause();
        }
        return;
    }
    if (position === 'D') {
        flashPlayerButton('jump-small', -1);
        window.Catalog.jumpSmall(-1);
        return;
    }
    if (position === 'F') {
        flashPlayerButton('jump-small', 1);
        window.Catalog.jumpSmall(1);
        return;
    }
    if (position === 'A') {
        window.Catalog.playPrevious();
        return;
    }
    if (position === 'C') {
        window.Catalog.skipIntro();
        return;
    }
    if (position === 'B') {
        toggleFullscreen();
        return;
    }
    if (position === 'G') {
        flashPlayerButton('jump-large', -1);
        window.Catalog.jumpLarge(-1);
        return;
    }
    if (position === 'I') {
        flashPlayerButton('jump-large', 1);
        window.Catalog.jumpLarge(1);
        return;
    }
    if (position === 'H') {
        window.Catalog.playNext();
        return;
    }
}

window.Catalog = window.Catalog || {};
window.Catalog.detectDeviceCapabilities = detectDeviceCapabilities;
window.Catalog.getPlayerType = getPlayerType;
window.Catalog.playMedia = playMedia;
window.Catalog.closePlayer = closePlayer;
window.Catalog.playNext = playNext;
window.Catalog.playPrevious = playPrevious;
window.Catalog.skipIntro = skipIntro;
window.Catalog.jumpSmall = jumpSmall;
window.Catalog.jumpLarge = jumpLarge;
window.Catalog.flashPlayerButton = flashPlayerButton;
window.routePlayerKey = routePlayerKey;
window.flashPlayerButton = flashPlayerButton;
// Compatibilidad con tvcat1
window.Catalog.plyrInstance = plyrInstance;
window.Catalog.currentPlayerType = currentPlayerType;
window.Catalog.currentMediaId = currentMediaId;
window.Catalog.currentPlayingItemId = currentPlayingItemId;
window.Catalog.currentPlayingVideoSrc = currentPlayingVideoSrc;
window.Catalog.currentEpisodes = window.Catalog.currentEpisodes || {};
window.Catalog.destroyPlayer = destroyPlayer;
window.Catalog.showCustomControls = showCustomControls;
window.Catalog.keepControlsVisible = keepControlsVisible;
window.Catalog.checkSkipIntro = checkSkipIntro;
window.Catalog._switchEpisode = _switchEpisode;

})();