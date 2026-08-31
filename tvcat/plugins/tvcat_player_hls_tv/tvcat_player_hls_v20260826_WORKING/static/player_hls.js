(function() {
    "use strict";
    if (!window.pluginSystem) return;

    var PLUGIN_NAME = "tvcat_player_hls";
    var LOG_PREFIX = "[PLAYER_HLS]";

    function log() {
        var args = [LOG_PREFIX].concat(Array.prototype.slice.call(arguments));
        console.log.apply(console, args);
    }

    function deriveEpisodeKey(ep) {
        if (ep.episode_key) return ep.episode_key;
        var link = ep.telegram_link || "";
        if (!link) return "";
        var m = link.match(/\/c\/(\d+)\/(?:(\d+)\/)?(\d+)/);
        if (!m) return "";
        return m[1] + "_" + m[3];
    }

    function hlsPlayMedia(item, episodes, episodeIndex) {
        var ep = episodes[episodeIndex];
        if (!ep) return;

        var episodeKey = deriveEpisodeKey(ep);
        if (!episodeKey) {
            log("No se pudo resolver episode_key para este episodio");
            return;
        }

        // Leer prefetch configurado (settings_schema) — se envía al playlist como query param
        var prefetchAhead = 2;
        try {
            var savedPrefetch = localStorage.getItem("tvcat_player_hls_prefetch_ahead");
            if (savedPrefetch !== null) prefetchAhead = parseInt(JSON.parse(savedPrefetch), 10) || 0;
            log("prefetch_ahead configurado: " + prefetchAhead);
        } catch(e) { log("error leyendo prefetch_ahead: " + e); }

        var playlistUrl = "/api/hls/" + episodeKey + "/master.m3u8?prefetch=" + prefetchAhead;
        log("Reproduciendo HLS (master): " + playlistUrl);

        var detailModal = document.getElementById("detail-modal");
        if (detailModal) detailModal.style.display = "none";
        var episodesModal = document.getElementById("episodes-modal");
        if (episodesModal) episodesModal.style.display = "none";

        var playerModal = document.getElementById("player-modal");
        var videoPlayer = document.getElementById("tvcat-video-player");
        if (!playerModal || !videoPlayer) {
            log("player-modal o video no encontrado");
            return;
        }

        var hideEls = document.querySelectorAll("#detail-modal, #episodes-modal, #settings-modal, #filter-modal, #side-menu, #side-menu-overlay, .navbar");
        for (var i = 0; i < hideEls.length; i++) {
            hideEls[i].style.display = "none";
        }

        // Card sin transform (transform en ancestro del video desactiva el video plane en Chromium)
        playerModal.classList.remove("hidden");
        playerModal.style.display = "flex";
        playerModal.style.visibility = "visible";   // limpiar visibility:hidden que deja closePlayer del core
        playerModal.style.position = "fixed";
        playerModal.style.top = "0";
        playerModal.style.left = "0";
        playerModal.style.transform = "none";
        playerModal.style.width = "100%";
        playerModal.style.maxWidth = "100%";
        playerModal.style.height = "100vh";
        playerModal.style.maxHeight = "100vh";
        playerModal.style.background = "#000";
        playerModal.style.borderRadius = "0";
        playerModal.style.padding = "0";
        playerModal.style.margin = "0";
        playerModal.style.zIndex = "99999";
        playerModal.style.overflow = "hidden";
        playerModal.style.border = "none";
        playerModal.style.opacity = "1";
        playerModal.style.filter = "none";
        playerModal.style.alignItems = "center";
        playerModal.style.justifyContent = "center";

        var pContainer = playerModal.querySelector(".player-container");
        if (pContainer) {
            pContainer.style.display = "flex";
            pContainer.style.background = "#000";
            pContainer.style.width = "100%";
            pContainer.style.height = "100vh";
            pContainer.style.transform = "none";
            pContainer.style.opacity = "1";
            pContainer.style.borderRadius = "0";
            pContainer.style.padding = "0";
            pContainer.style.margin = "0";
            pContainer.style.border = "none";
            pContainer.style.overflow = "hidden";
            pContainer.style.alignItems = "center";
            pContainer.style.justifyContent = "center";
        }

        // Ocultar player-info (empujaba el video hacia abajo)
        var playerInfo = playerModal.querySelector("#player-info");
        if (playerInfo) playerInfo.style.display = "none";

        videoPlayer.style.display = "block";
        videoPlayer.style.visibility = "visible";  // limpiar visibility residual
        videoPlayer.style.width = "100%";
        videoPlayer.style.height = "auto";
        videoPlayer.style.maxHeight = "100vh";
        videoPlayer.style.background = "#000";
        videoPlayer.style.border = "none";
        videoPlayer.style.borderRadius = "0";
        videoPlayer.style.transform = "none";
        videoPlayer.style.opacity = "1";
        videoPlayer.style.filter = "none";
        videoPlayer.style.objectFit = "contain";
        videoPlayer.controls = true;

        // Barra de progreso de descarga del fichero sparse (arriba)
        var progressBar = document.getElementById("hls-download-bar");
        if (!progressBar) {
            progressBar = document.createElement("div");
            progressBar.id = "hls-download-bar";
            progressBar.style.cssText = "position:fixed;top:0;left:0;width:100%;height:4px;background:#1e5aa8;z-index:100001;opacity:1;";
            var islandsLayer = document.createElement("div");
            islandsLayer.id = "hls-download-islands";
            islandsLayer.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;";
            progressBar.appendChild(islandsLayer);
            // línea blanca de reproducción (1px)
            var playDot = document.createElement("div");
            playDot.id = "hls-play-dot";
            playDot.style.cssText = "position:absolute;top:0;left:0%;width:1px;height:100%;background:#fff;z-index:2;transition:left 0.5s;";
            progressBar.appendChild(playDot);
            document.body.appendChild(progressBar);
        } else {
            progressBar.style.display = "block";
        }
        var islandsLayer = document.getElementById("hls-download-islands");
        var playDot = document.getElementById("hls-play-dot");

        // Polling del estado de descarga + punto de reproducción + selectores
        var _audioSel = null, _subsSel = null;
        function setSubtitleTrack(hlsInst, idx) {
            try {
                if (!hlsInst || !hlsInst.subtitleTracks) return;
                if (idx < 0) { hlsInst.subtitleTrack = -1; return; }
                var found = -1;
                for (var s2=0;s2<hlsInst.subtitleTracks.length;s2++){
                    var td=hlsInst.subtitleTracks[s2];
                    if (String(td.id)===String(idx) || String(td.index)===String(idx) || s2===idx){ found=s2; break; }
                }
                if (found<0 && idx>=0 && idx<hlsInst.subtitleTracks.length) found=idx;
                hlsInst.subtitleTrack = found;
                log("setSubtitleTrack -> " + found);
            } catch(e){ log("setSubtitleTrack error: "+e); }
        }
        function ensureTrackSelectors(audioTracks, subTracks, extSubs) {
            var box = document.getElementById("hls-track-box");
            if (!box) {
                box = document.createElement("div");
                box.id = "hls-track-box";
                box.style.cssText = "position:absolute;top:8px;right:8px;z-index:100002;display:flex;gap:6px;";
                playerModal.appendChild(box);
            } else {
                if (_audioSel && _audioSel.parentNode !== box) box.appendChild(_audioSel);
                if (_subsSel && _subsSel.parentNode !== box) box.appendChild(_subsSel);
            }
            // evitar duplicados: comprobar DOM
            if (document.getElementById("hls-audio-sel")) _audioSel = document.getElementById("hls-audio-sel");
            if (document.getElementById("hls-subs-sel")) _subsSel = document.getElementById("hls-subs-sel");
            if (audioTracks && audioTracks.length > 1 && !_audioSel) {
                _audioSel = document.createElement("select");
                _audioSel.id = "hls-audio-sel";
                _audioSel.style.cssText = "background:rgba(0,0,0,0.85);color:#fff;border:1px solid #888;padding:4px 8px;font-size:12px;";
                _audioSel.onchange = function() {
                    var idx = parseInt(this.value, 10);
                    if (isNaN(idx)) idx = 0;
                    log("Audio seleccionado idx=" + idx);
                    try {
                        var h = videoPlayer._hls;
                        var cur = videoPlayer.currentTime || 0;
                        if (h && h.audioTracks && h.audioTracks.length > idx) {
                            h.audioTrack = idx;
                            log("hls.audioTrack=" + idx + " cur=" + cur);
                            setTimeout(function(){ try{ if(Math.abs(videoPlayer.currentTime - cur) > 0.5) videoPlayer.currentTime = cur; }catch(e){} }, 300);
                        } else if (h) {
                            var newUrl = "/api/hls/" + episodeKey + "/master.m3u8?prefetch=" + prefetchAhead + "&audio=" + idx;
                            log("Fallback loadSource " + newUrl + " cur=" + cur);
                            var onParsed = function(){ try{ videoPlayer.currentTime = cur; videoPlayer.play(); }catch(e){} try{ h.off(Hls.Events.MANIFEST_PARSED, onParsed); }catch(e){} };
                            h.on(Hls.Events.MANIFEST_PARSED, onParsed);
                            h.loadSource(newUrl);
                        }
                    } catch(e){ log("audio switch error: "+e); }
                };
                for (var i = 0; i < audioTracks.length; i++) {
                    var at = audioTracks[i];
                    var opt = document.createElement("option");
                    opt.value = at.idx;
                    opt.textContent = at.lang + " (" + at.codec + ")";
                    _audioSel.appendChild(opt);
                }
                box.appendChild(_audioSel);
            }
            if ((subTracks && subTracks.length > 0) || (extSubs && extSubs.length > 0)) {
                if (_subsSel) return;
                _subsSel = document.createElement("select");
                _subsSel.id = "hls-subs-sel";
                _subsSel.style.cssText = "background:rgba(0,0,0,0.85);color:#fff;border:1px solid #888;padding:4px 8px;font-size:12px;";
                _subsSel.onchange = function() {
                    var v = this.value;
                    log("Sub seleccionado (índice master): " + v);
                    try {
                        var hlsInst = videoPlayer._hls;
                        if (!hlsInst) return;
                        var idx = parseInt(v, 10);
                        hlsInst.subtitleTrack = idx;
                        log("hls.subtitleTrack set to " + idx);
                        // Asegurar renderizado
                        if (idx >= 0) {
                            for(var t=0;t<videoPlayer.textTracks.length;t++) try{videoPlayer.textTracks[t].mode='showing';}catch(e){}
                        }
                    } catch(e){ log("subs switch error: "+e); }
                };
                var off = document.createElement("option"); off.value="-1"; off.textContent="Sin subs"; _subsSel.appendChild(off);
                // Llenar combo usando el índice real de hls.subtitleTracks
                if (hlsInst && hlsInst.subtitleTracks) {
                    for (var s=0;s<hlsInst.subtitleTracks.length;s++){
                        var st=hlsInst.subtitleTracks[s];
                        var o=document.createElement("option");
                        o.value=String(s);
                        o.textContent=st.name || st.lang || ("Sub " + s);
                        _subsSel.appendChild(o);
                    }
                }
            }
        }
        function pollCacheStatus() {
            if (!episodeKey) return;
            // si el modal ya está cerrado, parar el polling
            if (playerModal.classList.contains("hidden") || playerModal.style.display === "none") {
                if (window.__hlsCachePollTimer) { clearInterval(window.__hlsCachePollTimer); window.__hlsCachePollTimer = null; }
                return;
            }
            window.API.ajax({
                url: "/api/hls/" + episodeKey + "/cache-status",
                success: function(data) {
                    // Pintar islas verdes de bloques descargados (mapa real)
                    if (islandsLayer && data && data.total_blocks > 0) {
                        var html = "";
                        var list = data.islands || [];
                        for (var i = 0; i < list.length; i++) {
                            var s = list[i][0], e = list[i][1];
                            var leftPct = (s / data.total_blocks) * 100;
                            var wPct = ((e - s) / data.total_blocks) * 100;
                            html += '<div style="position:absolute;left:' + leftPct + '%;width:' + wPct + '%;height:100%;background:#2ecc71;"></div>';
                        }
                        islandsLayer.innerHTML = html;
                    }
                    // poblar selectores una vez que hay tracks
                    if (data && (data.audio_tracks || data.sub_tracks || data.subs)) {
                        ensureTrackSelectors(data.audio_tracks, data.sub_tracks || [], data.subs || []);
                    }
                    // actualizar punto blanco de reproducción
                    var dur = videoPlayer.duration || 0;
                    var cur = videoPlayer.currentTime || 0;
                    if (dur > 0 && playDot) {
                        var pp = Math.min(100, Math.max(0, (cur / dur) * 100));
                        playDot.style.left = pp + "%";
                    }
                },
                error: function(e) { log("cache-status error: " + e); }
            });
        }
        pollCacheStatus();
        var cachePollTimer = setInterval(pollCacheStatus, 1000);
        // limpiar al cerrar el player (best effort)
        if (window.__hlsCachePollTimer) clearInterval(window.__hlsCachePollTimer);
        window.__hlsCachePollTimer = cachePollTimer;
        // parar polling y ocultar barra al cerrar el modal + notificar al worker para pausar descarga
        var _leaveSentFor = null;
        function notifyLeave() {
            if (_leaveSentFor === episodeKey) return;
            _leaveSentFor = episodeKey;
            try { if (episodeKey) window.API.ajax({ method: 'POST', url: '/api/hls/' + episodeKey + '/leave' }); } catch(e) {}
            try { if (videoPlayer._hls) { videoPlayer._hls.stopLoad(); videoPlayer._hls.destroy(); videoPlayer._hls = null; } } catch(e) {}
            try { videoPlayer.pause(); } catch(e) {}
        }
        // envolver closePlayer una sola vez (evita spam de leave)
        try {
            if (!window.closePlayer._hlsWrapped) {
                var origClosePlayer = window.closePlayer;
                window.closePlayer = function() {
                    try { if (episodeKey) window.API.ajax({ method: 'POST', url: '/api/hls/' + episodeKey + '/leave' }); } catch(e) {}
                    try { if (videoPlayer._hls) { videoPlayer._hls.stopLoad(); videoPlayer._hls.destroy(); videoPlayer._hls = null; } } catch(e) {}
                    try { videoPlayer.pause(); } catch(e) {}
                    return origClosePlayer.apply(this, arguments);
                };
                window.closePlayer._hlsWrapped = true;
            }
        } catch(e) {}
        var observer = new MutationObserver(function() {
            if (playerModal.classList.contains("hidden") || playerModal.style.display === "none") {
                if (window.__hlsCachePollTimer) { clearInterval(window.__hlsCachePollTimer); window.__hlsCachePollTimer = null; }
                var bar = document.getElementById("hls-download-bar");
                if (bar) bar.style.display = "none";
                notifyLeave();
            }
        });
        try { observer.observe(playerModal, { attributes: true, attributeFilter: ["class", "style"] }); } catch(e) {}
        // Diagnóstico HLS
        var canHls = "";
        var canHls2 = "";
        try {
            canHls = videoPlayer.canPlayType('application/vnd.apple.mpegurl');
            canHls2 = videoPlayer.canPlayType('application/x-mpegURL');
            log("canPlayType mpegurl: " + canHls + " x-mpegURL: " + canHls2);
        } catch(e) { log("canPlayType error: " + e); }

        // MODO SOLO DESCARGA (diagnóstico): no reproduce, solo descarga el sparse y muestra la barra
        var downloadOnly = false;
        try {
            downloadOnly = localStorage.getItem("tvcat_player_hls_download_only") === "true";
        } catch(e) {}
        if (downloadOnly) {
            log("MODO SOLO DESCARGA activo: no reproduce, solo rellena el sparse");
            videoPlayer.style.display = "none";
            // activar la barra (ya creada arriba)
            var progressBar2 = document.getElementById("hls-download-bar");
            if (progressBar2) progressBar2.style.display = "block";
            window.API.ajax({
                url: "/api/hls/" + episodeKey + "/warmup",
                success: function(d) { log("warmup iniciado: " + JSON.stringify(d)); },
                error: function(e) { log("warmup error: " + e); }
            });
            // ya hay polling de cache-status arriba; asegurar que sigue
            return;
        }
        // Listeners para debug
        videoPlayer.onerror = function() {
            var err = videoPlayer.error;
            log("VIDEO ERROR code=" + (err ? err.code : "?") + " msg=" + (err ? err.message : "?"));
            if (err) try { log("error detail: " + JSON.stringify(err)); } catch(e) {}
        };
        videoPlayer.onloadedmetadata = function() { log("loadedmetadata duration=" + videoPlayer.duration + " video=" + videoPlayer.videoWidth + "x" + videoPlayer.videoHeight); };
        videoPlayer.oncanplay = function() { log("canplay readyState=" + videoPlayer.readyState + " video=" + videoPlayer.videoWidth + "x" + videoPlayer.videoHeight); };
        videoPlayer.onplaying = function() { log("playing video=" + videoPlayer.videoWidth + "x" + videoPlayer.videoHeight); };
        videoPlayer.onstalled = function() { log("stalled"); };
        videoPlayer.onsuspend = function() { log("suspend"); };
        // Reset completo para segunda reproducción y seek
        try { videoPlayer.pause(); } catch(e) {}
        if (videoPlayer._hls) { try { videoPlayer._hls.destroy(); } catch(e) {} videoPlayer._hls = null; }
        try { videoPlayer.removeAttribute('src'); videoPlayer.load(); } catch(e) {}
        var canHlsJs = (typeof Hls !== "undefined" && Hls.isSupported());
        var useNative = (canHls === "probably" || canHls === "maybe" || canHls2 === "probably" || canHls2 === "maybe");
        // Preferir hls.js en PC (Chrome) aunque reporte maybe, porque nativo de Chrome falla con nuestros segmentos
        if (canHlsJs) {
            log("Usando hls.js (preferido)");
            var hls = new Hls({
                enableWorker: true,
                lowLatencyMode: false,
                backBufferLength: 90,
                fragLoadingMaxRetry: 1000,
                fragLoadingMaxRetryTimeout: 0,
                fragLoadingRetryDelay: 500,
                manifestLoadingMaxRetry: 1000,
                manifestLoadingMaxRetryTimeout: 0,
                manifestLoadingRetryDelay: 500,
                levelLoadingMaxRetry: 1000,
                levelLoadingMaxRetryTimeout: 0,
                levelLoadingRetryDelay: 500
            });
            videoPlayer._hls = hls;
            hls.on(Hls.Events.MEDIA_ATTACHED, function(){ log("hls.js MEDIA_ATTACHED"); });
            hls.on(Hls.Events.MANIFEST_PARSED, function(ev, data){
                log("hls.js MANIFEST_PARSED levels=" + data.levels.length + " subs=" + (hls.subtitleTracks ? hls.subtitleTracks.length : 0));
                try { videoPlayer.play(); } catch(e) { log("play error: " + e); }
            });
            hls.on(Hls.Events.ERROR, function(ev, data){
                log("hls.js ERROR type=" + data.type + " details=" + data.details + " fatal=" + data.fatal);
                if (data.fatal) {
                    log("fatal error, detalles: " + JSON.stringify(data));
                    if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                        log("Recuperando NETWORK_ERROR con startLoad()");
                        try { hls.startLoad(); } catch(e) { log("startLoad error: " + e); }
                    } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
                        log("Recuperando MEDIA_ERROR con recoverMediaError()");
                        try { hls.recoverMediaError(); } catch(e) { log("recoverMediaError error: " + e); }
                    }
                }
            });
            hls.loadSource(playlistUrl);
            hls.attachMedia(videoPlayer);
        } else if (useNative) {
            log("Usando HLS nativo");
            videoPlayer.src = playlistUrl;
            videoPlayer.load();
            var p = null;
            try { p = videoPlayer.play(); } catch(e) { log("Error play: " + e); }
            if (p && p.then) {
                p.then(function(){ log("play() resolved"); }, function(e){ log("play() rejected: " + e); });
            }
        } else {
            log("HLS no soportado ni nativo ni hls.js, intentando nativo de todos modos");
            videoPlayer.src = playlistUrl;
            videoPlayer.load();
            try { videoPlayer.play(); } catch(e) { log("Error play: " + e); }
        }

        window.Catalog.currentMediaId = item.item_id || item.id;
        window.Catalog.currentPlayingItemId = item.item_id || item.id;
        window.Catalog.currentPlayingEpisodeId = ep.id || 0;
        window.Catalog.currentPlayingEpisodeKey = episodeKey;
        window.Catalog.currentPlayingVideoSrc = ep.video_src || "";
    }

    function init() {
        log("Registrando player HLS");

        pluginSystem.registerPlugin({
            name: PLUGIN_NAME,
            type: "player",
            displayName: "Player HLS Nativo",
            playerType: "hls",
            version: "1.0.0",
            applies_to: ["media", "series", "video"],
            action_category: "playback",
            play: function(item) {
                log("play called");
                var episodes = item.episodes || [];
                if (episodes.length > 0) {
                    hlsPlayMedia(item, episodes, 0);
                    return;
                }
                // Sin episodes en el item: el telegram_link del item puede ser el cover.
                // Resolver por item_id directo (sin agrupar por group_title_flat).
                var itemId = item.item_id || item.id;
                if (!itemId) { log("sin item_id, no se puede reproducir"); return; }
                window.API.ajax({
                    url: "/api/movie/" + itemId,
                    success: function(data) {
                        var allEps = (data && data.episodes) || [];
                        if (allEps.length === 0) { log("sin episodios tras cargar por API"); return; }
                        hlsPlayMedia(item, allEps, 0);
                    },
                    error: function(e) { log("error cargando episodios: " + e); }
                });
            },
            onActivate: function() { log("Plugin activado"); },
            onDeactivate: function() { log("Plugin desactivado"); }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
