(function() {
    "use strict";
    if (!window.pluginSystem) return;

    var PLUGIN_NAME = "tvcat_player_hls_tv";
    var LOG_PREFIX = "[PLAYER_HLS]";

    function log() {
        var args = [LOG_PREFIX].concat(Array.prototype.slice.call(arguments));
        console.log.apply(console, args);
    }
    // Carga bajo demanda de hls.min.js solo si hace falta (evita SyntaxError en WebKit 1.1 al registrar)
    function ensureHls(callback) {
        if (typeof Hls !== "undefined") { callback(); return; }
        var s = document.createElement("script");
        s.src = "/plugin-static/tvcat_player_hls_tv/hls.min.js?v=20260912";
        s.onload = callback;
        s.onerror = function() { log("hls.min.js no cargado, se usará nativo si es posible"); callback(); };
        document.head.appendChild(s);
    }

    function deriveEpisodeKey(ep) {
        if (ep.episode_key) return ep.episode_key;
        var link = ep.telegram_link || "";
        if (!link) return "";
        var m = link.match(/\/c\/(\d+)\/(?:(\d+)\/)?(\d+)/);
        if (!m) return "";
        return m[1] + "_" + m[3];
    }
    // Técnica test93/frontend/js/catalog.js:1723 — fullscreen real sobre pContainer (video+custom)
    function hlsRequestFullscreen(container, videoEl) {
        if (!container) return;
        try {
            var req = container.requestFullscreen || container.webkitRequestFullscreen || container.mozRequestFullScreen || container.msRequestFullscreen;
            if (req) { log("hlsRequestFullscreen -> container"); req.call(container); return; }
        } catch(e) { log("hlsRequestFullscreen error "+e); }
        try { if (videoEl && videoEl.webkitEnterFullscreen) { log("fallback webkitEnterFullscreen"); videoEl.webkitEnterFullscreen(); } } catch(e2) {}
    }
    // Técnica test93/frontend/js/catalog.js:1692 — limpiar video plane HW en contenedor + ancestros
    function applyTizenPlaneFixLocal(container) {
        if (!container) return;
        try {
            container.style.animation = 'none'; container.style.webkitAnimation = 'none';
            container.style.transform = 'none'; container.style.webkitTransform = 'none';
            container.style.opacity = '1'; container.style.filter = 'none'; container.style.webkitFilter = 'none';
            container.style.backdropFilter = 'none'; container.style.borderRadius = '0';
            container.style.border = 'none'; container.style.boxShadow = 'none';
            var anc = container.parentNode;
            while (anc && anc !== document.body) {
                anc.style.opacity = '1'; anc.style.transform = 'none'; anc.style.webkitTransform = 'none';
                anc.style.animation = 'none'; anc.style.webkitAnimation = 'none';
                anc.style.filter = 'none'; anc.style.webkitFilter = 'none'; anc.style.backdropFilter = 'none';
                anc = anc.parentNode;
            }
        } catch(e) {}
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

        // Helpers preferencias idioma (global por usuario, guardado en localStorage por core/js/app.js:2709)
        function getPref(key, def) {
            try {
                var raw = localStorage.getItem("tvcat_player_hls_" + key);
                if (raw !== null) return JSON.parse(raw);
            } catch(e2) {}
            return def;
        }
        var LANG_ALIASES = {
            spa: ["spa","es","esp","espanol","español","spanish","castellano"],
            eng: ["eng","en","english","ingles","inglés"],
            jpn: ["jpn","ja","japanese","japones","japonés"],
            kor: ["kor","ko","korean","coreano"],
            zho: ["zho","zh","chi","chinese","chino","cmn"],
            fra: ["fra","fre","fr","french","frances","francés"],
            deu: ["deu","ger","de","german","aleman","alemán"],
            ita: ["ita","it","italian","italiano"],
            por: ["por","pt","portuguese","portugues","portugués"]
        };
        function normLang(s) {
            if (!s) return "";
            var str = String(s).toLowerCase();
            // WebKit 1.1 (Tizen 2.4) no tiene String.normalize → fallback manual
            if (str.normalize) {
                try { str = str.normalize("NFD").replace(/[\u0300-\u036f]/g,""); } catch(e) {}
            } else {
                str = str.replace(/[àáâãäå]/g,"a").replace(/[èéêë]/g,"e").replace(/[ìíîï]/g,"i").replace(/[òóôõö]/g,"o").replace(/[ùúûü]/g,"u").replace(/[ñ]/g,"n").replace(/[ç]/g,"c");
            }
            // trim manual para WebKit sin String.trim
            if (str.trim) return str.trim();
            return str.replace(/^\s+|\s+$/g, "");
        }
        function langMatches(trackLang, pref) {
            if (!pref || pref === "none" || pref === "und") return false;
            var tl = normLang(trackLang);
            var aliases = LANG_ALIASES[pref] || [pref];
            for (var i=0;i<aliases.length;i++) if (tl.indexOf(normLang(aliases[i])) !== -1) return true;
            return tl === normLang(pref);
        }
        function isForcedTrack(trackLang) {
            return normLang(trackLang).indexOf("forzado") !== -1 || normLang(trackLang).indexOf("forced") !== -1;
        }
        function findBestTrackIndex(tracks, prio1, prio2) {
            if (!tracks || !tracks.length) return -1;
            for (var i=0;i<tracks.length;i++) if (!isForcedTrack(tracks[i].lang||tracks[i].name||"") && langMatches(tracks[i].lang || tracks[i].name || "", prio1)) return i;
            for (var i2=0;i2<tracks.length;i2++) if (langMatches(tracks[i2].lang || tracks[i2].name || "", prio1)) return i2;
            for (var j=0;j<tracks.length;j++) if (!isForcedTrack(tracks[j].lang||tracks[j].name||"") && langMatches(tracks[j].lang || tracks[j].name || "", prio2)) return j;
            for (var j2=0;j2<tracks.length;j2++) if (langMatches(tracks[j2].lang || tracks[j2].name || "", prio2)) return j2;
            return -1;
        }
        function applySubtitleStyle() {
            var sz = getPref("sub_font_size", 20);
            var col = getPref("sub_color", "#FFFF00");
            var outCol = getPref("sub_outline_color", "#000000");
            var bgCol = getPref("sub_bg_color", "#000000");
            var bgAlpha = getPref("sub_bg_alpha", 70);
            var bgRgba = bgCol;
            if (bgCol && bgCol.indexOf("#") === 0 && bgCol.length === 7) {
                var r = parseInt(bgCol.slice(1,3),16), g = parseInt(bgCol.slice(3,5),16), b = parseInt(bgCol.slice(5,7),16);
                var a = Math.max(0, Math.min(100, bgAlpha)) / 100;
                bgRgba = "rgba(" + r + "," + g + "," + b + "," + a + ")";
            }
            var css = "video::cue{color:" + col + ";font-size:" + sz + "px;background-color:" + bgRgba + ";text-shadow:1px 1px 2px " + outCol + ", -1px -1px 2px " + outCol + ";}";
            var el = document.getElementById("hls-cue-style");
            if (!el) { el = document.createElement("style"); el.id = "hls-cue-style"; document.head.appendChild(el); }
            el.textContent = css;
            log("sub style ::cue color=" + col + " size=" + sz + "px bg=" + bgRgba);
        }
        applySubtitleStyle();

        // Preferencias por título (central, tvcat_user_prefs.hls_title_prefs) — prevalecen sobre globales
        var currentItemId = item.item_id || item.id || "";
        window._hlsCurrentItemId = currentItemId;
        window._hlsTitlePrefs = window._hlsTitlePrefs || null;
        function loadTitlePrefs(cb){
            window.API.ajax({
                url: '/api/config',
                success: function(cfg){
                    try{
                        var p = cfg.hls_title_prefs;
                        if(typeof p === 'string') p = JSON.parse(p);
                        window._hlsTitlePrefs = p && typeof p === 'object' ? p : {};
                    }catch(e){ window._hlsTitlePrefs = {}; }
                    log("title prefs cargados: "+JSON.stringify(window._hlsTitlePrefs[currentItemId]||{}));
                    if(cb) cb();
                    // si ya hay tracks, re-aplicar auto-select con prefs de título
                    try{ if(window.__doAutoSelect) window.__doAutoSelect(); }catch(e){}
                    try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){}
                },
                error: function(){ window._hlsTitlePrefs = window._hlsTitlePrefs||{}; if(cb) cb(); }
            });
        }
        function saveTitlePrefs(audioIdx, subsIdx){
            if(!currentItemId) return;
            var prefs = window._hlsTitlePrefs || {};
            prefs[currentItemId] = {audio: audioIdx, subs: subsIdx};
            window._hlsTitlePrefs = prefs;
            window.API.ajax({
                method: 'POST',
                url: '/api/config',
                data: {hls_title_prefs: prefs},
                success: function(){ log("title prefs guardado "+currentItemId+" audio="+audioIdx+" subs="+subsIdx); },
                error: function(s,msg){ log("title prefs save error "+msg); }
            });
        }
        // cargar prefs de título en background
        loadTitlePrefs();

        var playlistUrl = "/api/hls/" + episodeKey + "/master.m3u8?prefetch=" + prefetchAhead;
        log("Reproduciendo HLS (master): " + playlistUrl);

        // Resume: buscar progreso previo (igual que tvcat_player)
        var resumeTime = 0;
        try{
            window.API.ajax({
                url: '/api/watch/history',
                success: function(hist){
                    try{
                        var list = hist.history || hist || [];
                        for(var hi=0; hi<list.length; hi++){
                            var h=list[hi];
                            if((h.episode_key && h.episode_key===episodeKey) || (h.episode_id && String(h.episode_id)===String(ep.id)) || (h.item_id && String(h.item_id)===String(item.item_id||item.id))){
                                resumeTime = h.progress || h.last_position || 0;
                                break;
                            }
                        }
                        if(resumeTime>5){
                            log("Resume detectado: "+resumeTime+"s");
                            var applyResume=function(){
                                try{ if(videoPlayer.duration && resumeTime > videoPlayer.duration-10) return; videoPlayer.currentTime=resumeTime; log("Reanudando en "+resumeTime); }catch(e){ log("resume error "+e); }
                            };
                            // intentar en varios eventos por si HLS aún no tiene duration
                            videoPlayer.addEventListener('loadedmetadata', applyResume, {once:true});
                            videoPlayer.addEventListener('canplay', applyResume, {once:true});
                            hls && hls.on && hls.on(Hls.Events.MANIFEST_PARSED, function(){ setTimeout(applyResume, 300); });
                            setTimeout(applyResume, 800);
                        }
                    }catch(e){ log("resume parse error "+e); }
                }
            });
        }catch(e){ log("resume fetch error "+e); }

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

        // === LOADER HLS (plugin.png rellenándose) ===
        var hlsLoader = document.getElementById("hls-loader");
        if(!hlsLoader){
            hlsLoader=document.createElement("div");
            hlsLoader.id="hls-loader";
            hlsLoader.style.cssText="position:absolute;top:0;left:0;width:100%;height:100%;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:100001;";
            var loaderImgWrap=document.createElement("div");
            loaderImgWrap.style.cssText="position:relative;width:160px;height:160px;";
            var imgGray=document.createElement("img");
            imgGray.src="/plugin-static/tvcat_player_hls/plugin_icon.png";
            imgGray.style.cssText="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;filter:grayscale(1) brightness(0.5);";
            imgGray.onerror=function(){ this.style.display="none"; var em=document.createElement("div"); em.textContent="📡"; em.style.cssText="position:absolute;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:80px;"; loaderImgWrap.appendChild(em); };
            var imgColorWrap=document.createElement("div");
            imgColorWrap.id="hls-loader-fill";
            imgColorWrap.style.cssText="position:absolute;bottom:0;left:0;width:100%;height:0%;overflow:hidden;transition:height 0.3s;";
            var imgColor=document.createElement("img");
            imgColor.src="/plugin-static/tvcat_player_hls/plugin_icon.png";
            imgColor.style.cssText="position:absolute;bottom:0;left:0;width:160px;height:160px;object-fit:contain;";
            imgColor.onerror=function(){ this.style.display="none"; var em2=document.createElement("div"); em2.textContent="📡"; em2.style.cssText="position:absolute;bottom:0;left:0;width:160px;height:160px;display:flex;align-items:center;justify-content:center;font-size:80px;color:#4a9eff;"; imgColorWrap.appendChild(em2); };
            imgColorWrap.appendChild(imgColor);
            loaderImgWrap.appendChild(imgColorWrap);
            hlsLoader.appendChild(loaderImgWrap);
            var loaderText=document.createElement("div");
            loaderText.id="hls-loader-text";
            loaderText.textContent="Cargando...";
            loaderText.style.cssText="margin-top:16px;color:#fff;font-size:14px;opacity:0.8;";
            hlsLoader.appendChild(loaderText);
            var loaderPct=document.createElement("div");
            loaderPct.id="hls-loader-pct";
            loaderPct.textContent="0%";
            loaderPct.style.cssText="margin-top:4px;color:#4a9eff;font-size:12px;";
            hlsLoader.appendChild(loaderPct);
            playerModal.appendChild(hlsLoader);
        } else {
            hlsLoader.style.display="flex";
            hlsLoader.style.position="absolute";
            if(hlsLoader.parentNode!==playerModal) try{ playerModal.appendChild(hlsLoader); }catch(e){}
            hlsLoader.style.top="0"; hlsLoader.style.left="0"; hlsLoader.style.width="100%"; hlsLoader.style.height="100%";
            hlsLoader.style.background="#000";
            hlsLoader.style.opacity="1";
            var fill=document.getElementById("hls-loader-fill"); if(fill) fill.style.height="0%";
            var pct=document.getElementById("hls-loader-pct"); if(pct) pct.textContent="0%";
        }
        // ocultar video hasta que esté listo (TV antigua: sin pantalla de carga, vídeo visible directo)
        var _isOldTv = false;
        try {
            var _capsTmp = window.detectDeviceCapabilities ? window.detectDeviceCapabilities() : (window.Catalog && window.Catalog.detectDeviceCapabilities ? window.Catalog.detectDeviceCapabilities() : null);
            _isOldTv = _capsTmp && _capsTmp.isOldSmartTV;
        } catch(e) {}
        var hlsLoaderVisible=true;
        if (_isOldTv) {
            try{ videoPlayer.style.visibility="visible"; }catch(e){}
            try{ if(hlsLoader) { hlsLoader.style.display="none"; hlsLoaderVisible=false; } }catch(e){}
        } else {
            try{ videoPlayer.style.visibility="hidden"; }catch(e){}
        }
        function updateLoaderFill(pct){
            var fill=document.getElementById("hls-loader-fill");
            var pctEl=document.getElementById("hls-loader-pct");
            if(fill) fill.style.height=Math.max(0,Math.min(100,pct))+"%";
            if(pctEl) pctEl.textContent=Math.round(pct)+"%";
            log("loader fill "+Math.round(pct)+"%");
        }
        function hideLoader(){
            if(!hlsLoaderVisible) return;
            hlsLoaderVisible=false;
            hlsLoader.style.opacity="0";
            hlsLoader.style.transition="opacity 0.3s";
            setTimeout(function(){ hlsLoader.style.display="none"; try{ videoPlayer.style.visibility="visible"; syncCustomLayerToVideo(); }catch(e){} }, 300);
            log("loader oculto, video visible");
        }
        function showLoaderOverlay(){
            if(!hlsLoader) return;
            hlsLoaderVisible=true;
            hlsLoader.style.display="flex";
            hlsLoader.style.opacity="1";
            hlsLoader.style.background="rgba(0,0,0,0.85)";
            // asegurar dentro del playerModal para overlay sobre video en seek
            if(hlsLoader.parentNode!==playerModal){
                try{ playerModal.appendChild(hlsLoader); hlsLoader.style.position="absolute"; hlsLoader.style.height="100%"; syncCustomLayerToVideo(); }catch(e){}
            }
        }

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

        // === CAPA CUSTOM (SmartTV-first) anclada al video ===
        // Limpiar capa previa (evita cierre sobre episodio anterior y handlers viejos)
        var _oldLayer=document.getElementById("hls-custom-layer"); if(_oldLayer) try{ _oldLayer.remove(); }catch(e){}
        var customLayer = null;
        var customHideTimer = null;
        var customTimeoutSec = 3.5;
        var customLayerReady = false;
        // Detección TV antigua (usada por syncCustomLayerToVideo)
        var _oldTvLayer = false;
        try { var _cL = window.detectDeviceCapabilities ? window.detectDeviceCapabilities() : (window.Catalog && window.Catalog.detectDeviceCapabilities ? window.Catalog.detectDeviceCapabilities() : null); _oldTvLayer = _cL && _cL.isOldSmartTV; } catch(e){}
        try { var ct = localStorage.getItem("tvcat_player_hls_custom_controls_timeout"); if(ct!==null) customTimeoutSec = parseFloat(JSON.parse(ct))||3.5; } catch(e){}
        function isCustomVisible() { return customLayer && parseFloat(customLayer.style.opacity||"0") >= 0.5; }
        function showCustomLayer() { if (!customLayer || !customLayerReady) return; syncCustomLayerToVideo(); customLayer.style.opacity="1"; customLayer.style.visibility="visible"; setLayerInteractive(true); resetCustomTimer(); }
        function hideCustomLayer() { if (!customLayer) return; customLayer.style.opacity="0"; setLayerInteractive(false); setTimeout(function(){ if(customLayer && customLayer.style.opacity==="0") customLayer.style.visibility="hidden"; }, 220); }
        function resetCustomTimer(){ if(customHideTimer) clearTimeout(customHideTimer); customHideTimer=setTimeout(hideCustomLayer, customTimeoutSec*1000); }
        function setLayerInteractive(on){
            if(!customLayer) return;
            var els=customLayer.querySelectorAll("[data-cc-interactive]");
            for(var i=0;i<els.length;i++) els[i].style.pointerEvents = on ? "auto" : "none";
        }
        function syncCustomLayerToVideo(){
            try{
                // TV antigua: capa fija a pantalla completa, sobre el video plane HW (z-index alto)
                if (_oldTvLayer) {
                    customLayer.style.position="fixed";
                    customLayer.style.left="0"; customLayer.style.top="0";
                    customLayer.style.width="100%"; customLayer.style.height="100%";
                    customLayer.style.zIndex="100003";
                    return;
                }
                // Si capa está dentro de pContainer (fullscreen), cubrir 100% del contenedor
                if (customLayer && pContainer && customLayer.parentNode === pContainer) {
                    customLayer.style.left="0"; customLayer.style.top="0";
                    customLayer.style.width="100%"; customLayer.style.height="100%";
                    return;
                }
                var r=videoPlayer.getBoundingClientRect(); var pr=playerModal.getBoundingClientRect();
                customLayer.style.left=(r.left-pr.left)+"px"; customLayer.style.top=(r.top-pr.top)+"px";
                customLayer.style.width=r.width+"px"; customLayer.style.height=r.height+"px";
            }catch(e){}
        }
        function createCustomBtn(id, leftPct, topPct, imgName, fallbackText, fallbackColor, fallbackSize, action){
            var btn=document.createElement("div"); btn.id=id;
            btn.setAttribute("data-cc-interactive","1");
            btn.style.cssText="position:absolute;left:"+leftPct+"%;top:"+topPct+"%;width:60px;height:60px;margin-left:-30px;margin-top:-30px;background:rgba(0,0,0,0.7);border:1px solid #888;text-align:center;line-height:60px;cursor:pointer;z-index:10;pointer-events:none;";
            var img=document.createElement("img"); img.src="/plugin-static/tvcat_player_hls/"+imgName;
            img.style.cssText="width:48px;height:48px;margin-top:6px;";
            img.onload=function(){ btn.style.background="transparent"; btn.style.border="none"; };
            img.onerror=function(){ this.style.display="none"; btn.textContent=fallbackText; btn.style.color=fallbackColor; btn.style.fontSize=fallbackSize; btn.style.fontWeight="600"; };
            btn.appendChild(img);
            btn.addEventListener("click", function(e){ e.stopPropagation(); if(!isCustomVisible()){ showCustomLayer(); return; } resetCustomTimer(); try{ action(); }catch(err){ log("custom btn error "+err); } });
            return btn;
        }
        if(!customLayer){
            customLayer=document.createElement("div"); customLayer.id="hls-custom-layer";
            customLayer.style.cssText="position:absolute;left:0;top:0;width:100%;height:100%;z-index:100003;opacity:0;visibility:hidden;pointer-events:none;transition:opacity 0.2s;";
            var btnClose=document.createElement("div"); btnClose.textContent="×"; btnClose.setAttribute("data-cc-interactive","1");
            btnClose.style.cssText="position:absolute;top:1%;right:2%;width:36px;height:36px;text-align:center;line-height:30px;font-size:22px;color:#fff;background:rgba(0,0,0,0.6);border:1px solid #888;border-radius:50%;cursor:pointer;z-index:11;pointer-events:none;";
            btnClose.addEventListener("click", function(e){
                e.stopPropagation(); e.preventDefault();
                log("close X clicked");
                try{
                    if(document.fullscreenElement){ try{ document.exitFullscreen(); }catch(err){} }
                    else if(document.webkitFullscreenElement){ try{ document.webkitExitFullscreen(); }catch(err){} }
                }catch(e2){}
                setTimeout(function(){
                    try{ if(window.closePlayer) window.closePlayer(); else { playerModal.style.display="none"; playerModal.classList.add("hidden"); } }catch(err){ log("close error "+err); try{ playerModal.style.display="none"; }catch(e2){} }
                }, 80);
            });
            customLayer.appendChild(btnClose);
            // (botón "Max" copia de la X eliminado — usar cc-max, tecla 8)
            // Icono + nombre del plugin arriba a la izquierda
            var titleWrap=document.createElement("div"); titleWrap.setAttribute("data-cc-interactive","1");
            titleWrap.style.cssText="position:absolute;top:1%;left:2%;display:flex;align-items:center;gap:8px;z-index:11;pointer-events:none;";
            var iconImg=document.createElement("img");
            iconImg.src="/plugin-static/tvcat_player_hls/plugin_icon.png";
            iconImg.style.cssText="width:28px;height:28px;border-radius:4px;object-fit:cover;";
            iconImg.onerror=function(){ this.style.display="none"; var em=document.createElement("span"); em.textContent="📡"; em.style.fontSize="22px"; titleWrap.insertBefore(em, titleWrap.firstChild); };
            titleWrap.appendChild(iconImg);
            var titleText=document.createElement("span"); titleText.textContent="Player HLS Nativo"; titleText.style.cssText="color:#fff;font-size:13px;font-weight:600;opacity:0.9;";
            titleWrap.appendChild(titleText);
            customLayer.appendChild(titleWrap);
            customLayer.appendChild(createCustomBtn("cc-ep-prev",20,10,"episode_prev.png","Anterior","#fff","11px", function(){ var idx=episodes.indexOf(ep); if(idx>0) hlsPlayMedia(item, episodes, idx-1); }));
            customLayer.appendChild(createCustomBtn("cc-max",50,10,"maximize.png","^","#ff0","16px", function(){ toggleFakeFullscreen(); }));
            var fileNameLabel=document.createElement("div"); fileNameLabel.id="cc-filename";
            fileNameLabel.style.cssText="position:absolute;left:50%;top:18%;width:60%;margin-left:-30%;text-align:center;color:#fff;font-size:22px;opacity:0.9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;z-index:11;pointer-events:none;";
            var _fname = ep.file_name || ep.title || ep.caption || item.title || "";
            // limpiar posible prefijo de caption largo
            if(_fname.length>80) _fname=_fname.slice(0,80)+"…";
            fileNameLabel.textContent=_fname;
            customLayer.appendChild(fileNameLabel);
            customLayer.appendChild(createCustomBtn("cc-ep-next",80,10,"episode_next.png","Next","#fff","11px", function(){ var idx2=episodes.indexOf(ep); if(idx2>=0&&idx2<episodes.length-1) hlsPlayMedia(item, episodes, idx2+1); }));
            // Fila única de saltos + play centrados (play a misma altura que saltos, y=46%)
            customLayer.appendChild(createCustomBtn("cc-play-pause",50,46,"play_pause.png","▶️","#fff","18px", function(){ try{ if(videoPlayer.paused) videoPlayer.play(); else videoPlayer.pause(); }catch(e){} }));
            customLayer.appendChild(createCustomBtn("cc-jump-back-long",6,46,"jump_back_long.png","<<","#f00","20px", function(){ var v=30; try{ var j=localStorage.getItem("tvcat_jump_long"); if(j) v=parseInt(JSON.parse(j),10)||30; }catch(e){} try{ videoPlayer.currentTime=Math.max(0,videoPlayer.currentTime-v); }catch(e){} }));
            customLayer.appendChild(createCustomBtn("cc-jump-back-short",14,46,"jump_back_short.png","<","#fff","20px", function(){ var v3=10; try{ var j3=localStorage.getItem("tvcat_jump_short"); if(j3) v3=parseInt(JSON.parse(j3),10)||10; }catch(e){} try{ videoPlayer.currentTime=Math.max(0,videoPlayer.currentTime-v3); }catch(e){} }));
            customLayer.appendChild(createCustomBtn("cc-jump-forw-short",86,46,"jump_forw_short.png",">","#fff","20px", function(){ var v5=10; try{ var j5=localStorage.getItem("tvcat_jump_short"); if(j5) v5=parseInt(JSON.parse(j5),10)||10; }catch(e){} try{ videoPlayer.currentTime=Math.min(videoPlayer.duration||1e9, videoPlayer.currentTime+v5); }catch(e){} }));
            customLayer.appendChild(createCustomBtn("cc-jump-forw-long",94,46,"jump_forw_long.png",">>","#f00","20px", function(){ var v2=30; try{ var j2=localStorage.getItem("tvcat_jump_long"); if(j2) v2=parseInt(JSON.parse(j2),10)||30; }catch(e){} try{ videoPlayer.currentTime=Math.min(videoPlayer.duration||1e9, videoPlayer.currentTime+v2); }catch(e){} }));
            var btnSkip=createCustomBtn("cc-skip-intro",50,62,"skip_intro.png","Skip Intro","#fff","11px", function(){ var v4=85; try{ var j4=localStorage.getItem("tvcat_skip_intro"); if(j4) v4=parseInt(JSON.parse(j4),10)||85; }catch(e){} try{ videoPlayer.currentTime=Math.min(videoPlayer.duration||1e9, videoPlayer.currentTime+v4); }catch(e){} });
            customLayer.appendChild(btnSkip);
            var comboAudioWrap=document.createElement("div"); comboAudioWrap.id="cc-audio-wrap"; comboAudioWrap.setAttribute("data-cc-interactive","1");
            comboAudioWrap.style.cssText="position:absolute;left:12%;top:70%;width:28%;text-align:center;z-index:11;pointer-events:none;";
            var lblA=document.createElement("div"); lblA.textContent="Audio:"; lblA.style.cssText="color:#fff;font-size:11px;margin-bottom:2px;"; comboAudioWrap.appendChild(lblA);
            var selA=document.createElement("select"); selA.id="cc-audio-sel"; selA.style.cssText="width:100%;padding:4px;background:rgba(0,0,0,0.85);color:#fff;border:1px solid #888;font-size:11px;";
            selA.addEventListener("click", function(e){ e.stopPropagation(); resetCustomTimer(); });
            selA.addEventListener("change", function(){ var v=this.value; var idx=parseInt(v,10); try{ var h=videoPlayer._hls; if(h&&h.audioTracks&&h.audioTracks.length>idx){ h.audioTrack=idx; log("cc audioTrack ->"+idx); var curSubs = h.subtitleTrack; saveTitlePrefs(idx, curSubs); } }catch(e){} resetCustomTimer(); });
            comboAudioWrap.appendChild(selA); customLayer.appendChild(comboAudioWrap);
            var comboSubsWrap=document.createElement("div"); comboSubsWrap.id="cc-subs-wrap"; comboSubsWrap.setAttribute("data-cc-interactive","1");
            comboSubsWrap.style.cssText="position:absolute;right:12%;top:70%;width:28%;text-align:center;z-index:11;pointer-events:none;";
            var lblS=document.createElement("div"); lblS.textContent="Subtitle:"; lblS.style.cssText="color:#fff;font-size:11px;margin-bottom:2px;"; comboSubsWrap.appendChild(lblS);
            var selS=document.createElement("select"); selS.id="cc-subs-sel"; selS.style.cssText="width:100%;padding:4px;background:rgba(0,0,0,0.85);color:#fff;border:1px solid #888;font-size:11px;";
            selS.addEventListener("click", function(e){ e.stopPropagation(); resetCustomTimer(); });
            selS.addEventListener("change", function(){ var v=this.value; var idx=parseInt(v,10); try{ var h2=videoPlayer._hls; if(h2){ h2.subtitleTrack=idx; log("cc subtitleTrack ->"+idx); var curAudio = h2.audioTrack; saveTitlePrefs(curAudio, idx); } }catch(e){} resetCustomTimer(); });
            comboSubsWrap.appendChild(selS); customLayer.appendChild(comboSubsWrap);
            // Técnica test93: capa dentro de pContainer para que viva en fullscreen
            var _layerParent = pContainer || playerModal;
            try { _layerParent.appendChild(customLayer); } catch(e) { try{ playerModal.appendChild(customLayer); }catch(e2){} }
            // Habilitar capa una vez creada (técnica plyr/html5 de test93)
            customLayerReady = true;
            try { showCustomLayer(); } catch(e) {}
            // CSS fullscreen para pContainer (asegura 100% en fullscreen)
            try {
                if (!document.getElementById("hls-tv-fs-style2")) {
                    var _fs2 = document.createElement("style");
                    _fs2.id = "hls-tv-fs-style2";
                    _fs2.textContent = ".player-container:-webkit-full-screen{width:100%!important;height:100%!important;max-width:100%!important;background:#000!important;border:none!important;transform:none!important;opacity:1!important} .player-container:fullscreen{width:100%!important;height:100%!important;max-width:100%!important;background:#000!important;border:none!important;transform:none!important;opacity:1!important} .player-container:-webkit-full-screen #tvcat-video-player,.player-container:fullscreen #tvcat-video-player{width:100%!important;height:100%!important;object-fit:contain}";
                    document.head.appendChild(_fs2);
                }
            } catch(e) {}
            // Integrar barra verde en el borde superior de la capa custom (2px)
            try{
                var topBar=document.getElementById("hls-download-bar");
                if(topBar){
                    topBar.style.position="absolute"; topBar.style.top="0"; topBar.style.bottom="auto";
                    topBar.style.left="0"; topBar.style.width="100%"; topBar.style.height="2px";
                    topBar.style.background="rgba(30,90,168,0.4)"; topBar.style.zIndex="12"; topBar.style.display="block";
                    if(topBar.parentNode!==customLayer) customLayer.appendChild(topBar);
                }
            }catch(e){}
            var onPlayerClick = function(e){ if(!customLayer) return; if(e.target && e.target.getAttribute && e.target.getAttribute("data-cc-interactive")) return; showCustomLayer(); };
            var onMouseMove = function(e){ if(!customLayer||playerModal.style.display==="none") return; showCustomLayer(); };
            var onTouchStart = function(e){ if(!customLayer||playerModal.style.display==="none") return; showCustomLayer(); };
            try{
                playerModal.addEventListener("click", onPlayerClick); videoPlayer.addEventListener("click", onPlayerClick);
                videoPlayer.addEventListener("mousemove", onMouseMove); playerModal.addEventListener("mousemove", onMouseMove);
                videoPlayer.addEventListener("touchstart", onTouchStart, {passive:true}); playerModal.addEventListener("touchstart", onTouchStart, {passive:true});
                videoPlayer.addEventListener("touchend", function(e){ if(e.target && e.target.getAttribute && e.target.getAttribute("data-cc-interactive")) return; }, {passive:true});
            }catch(e){}
            try{ window.addEventListener("resize", syncCustomLayerToVideo); document.addEventListener("fullscreenchange", syncCustomLayerToVideo); document.addEventListener("webkitfullscreenchange", syncCustomLayerToVideo); videoPlayer.addEventListener("loadedmetadata", syncCustomLayerToVideo); }catch(e){}
            var _fakeFs = false;
            var toggleFakeFullscreen = function(){
                _fakeFs = !_fakeFs;
                try{
                    var _target = pContainer || playerModal;
                    var _isFs = !!(document.fullscreenElement || document.webkitFullscreenElement);
                    if(!_isFs){
                        // Limpiar plane antes de entrar (test93)
                        var _a = _target;
                        while (_a && _a !== document.body) {
                            _a.style.transform="none"; _a.style.webkitTransform="none";
                            _a.style.opacity="1"; _a.style.animation="none"; _a.style.webkitAnimation="none";
                            _a.style.filter="none"; _a.style.webkitFilter="none";
                            _a.style.borderRadius="0"; _a.style.boxShadow="none";
                            _a = _a.parentNode;
                        }
                        hlsRequestFullscreen(_target, videoPlayer);
                        // Mostrar capa al entrar en fullscreen (técnica plyr/html5)
                        try { syncCustomLayerToVideo(); showCustomLayer(); } catch(e){}
                    } else {
                        if(document.exitFullscreen) document.exitFullscreen();
                        else if(document.webkitExitFullscreen) document.webkitExitFullscreen();
                    }
                }catch(e){ log("max error "+e); }
                var maxBtn=document.getElementById("cc-max");
                if(maxBtn){ var im=maxBtn.querySelector("img"); if(im && im.style.display==="none"){ maxBtn.childNodes.forEach(function(n){ if(n.nodeType===3) n.textContent=""; }); maxBtn.appendChild(document.createTextNode(_fakeFs?"Restaurar":"^")); maxBtn.style.color="#ff0"; } }
                resetCustomTimer();
                setTimeout(syncCustomLayerToVideo, 100);
            }
            window._hlsToggleFakeFullscreen = toggleFakeFullscreen;
            // (botón fijo Maximizar temporal eliminado — usar el de la capa custom: cc-max)
            // actualizar estado _fakeFs al salir con ESC
            try{
                document.addEventListener("fullscreenchange", function(){ _fakeFs=!!document.fullscreenElement; syncCustomLayerToVideo(); });
                document.addEventListener("webkitfullscreenchange", function(){ _fakeFs=!!document.webkitFullscreenElement; syncCustomLayerToVideo(); });
            }catch(e){}
            var onKeyDown = function(e){
                var curLayer = document.getElementById("hls-custom-layer");
                var curModal = document.getElementById("player-modal");
                log("onKeyDown raw kc="+(e.keyCode||e.which)+" key="+e.key+" curLayer="+(!!curLayer)+" modalDisplay="+(curModal?curModal.style.display:"?"));
                if(!curLayer||!curModal||curModal.style.display==="none") return;
                var d=null; try{ d=window.keyMapper?window.keyMapper.getVirtualDigit(e):null; }catch(err){}
                if(d===null){ var kc=e.keyCode||e.which; if(kc>=48&&kc<=57) d=String.fromCharCode(kc); else if(kc>=96&&kc<=105) d=String.fromCharCode(kc-48); }
                if(d===null) return;
                var vis = curLayer && parseFloat(curLayer.style.opacity||"0")>=0.5;
                log("key digit="+d+" kc="+(e.keyCode||e.which)+" visible="+vis);
                if(!vis){ try{ var r=curLayer; var vp=document.getElementById("tvcat-video-player"); if(vp&&r){ var rr=vp.getBoundingClientRect(); var pr=curModal.getBoundingClientRect(); r.style.left=(rr.left-pr.left)+"px"; r.style.top=(rr.top-pr.top)+"px"; r.style.width=rr.width+"px"; r.style.height=rr.height+"px"; } r.style.opacity="1"; r.style.visibility="visible"; var els=r.querySelectorAll("[data-cc-interactive]"); for(var i=0;i<els.length;i++) els[i].style.pointerEvents="auto"; }catch(e2){} if("7894561230".indexOf(d)!==-1) e.preventDefault(); return; }
                var map={"7":"cc-ep-prev","8":"cc-max","9":"cc-ep-next","4":"cc-jump-back-long","5":"cc-play-pause","6":"cc-jump-forw-long","1":"cc-jump-back-short","2":"cc-skip-intro","3":"cc-jump-forw-short","0":"cc-back"};
                if(d==="0"){ e.preventDefault(); try{ window.closePlayer(); }catch(err){} try{ if(customHideTimer) clearTimeout(customHideTimer); }catch(e2){} return; }
                var bid=map[d]; if(bid){ e.preventDefault(); var el=document.getElementById(bid); log("key map "+d+" -> "+bid+" found="+(!!el)); if(el) el.click(); else log("key element not found "+bid); try{ if(customHideTimer) clearTimeout(customHideTimer); customHideTimer=setTimeout(function(){ var cl=document.getElementById("hls-custom-layer"); if(cl){ cl.style.opacity="0"; var els2=cl.querySelectorAll("[data-cc-interactive]"); for(var k=0;k<els2.length;k++) els2[k].style.pointerEvents="none"; setTimeout(function(){ if(cl&&cl.style.opacity==="0") cl.style.visibility="hidden"; },220); } }, customTimeoutSec*1000); }catch(e2){} }
            }
            if(!window._hlsKeyHandlerRegistered){
                try{ window.addEventListener("keydown", onKeyDown); document.addEventListener("keydown", onKeyDown); window._hlsKeyHandlerRegistered=true; log("key handler registered"); }catch(e){}
            }
            window.__hlsSyncCustomCombos=function(){
                try{
                    var h=videoPlayer._hls;
                    var aSel=document.getElementById("cc-audio-sel"); var sSel=document.getElementById("cc-subs-sel");
                    var aWrap=document.getElementById("cc-audio-wrap"); var sWrap=document.getElementById("cc-subs-wrap");
                    if(aSel&&h&&h.audioTracks){
                        aSel.innerHTML=""; for(var i=0;i<h.audioTracks.length;i++){ var o=document.createElement("option"); o.value=String(i); o.textContent=h.audioTracks[i].name||h.audioTracks[i].lang||("Audio "+i); aSel.appendChild(o); }
                        aSel.value=String(h.audioTrack); if(aWrap) aWrap.style.display=h.audioTracks.length>1?"block":"none";
                    }
                    if(sSel&&h&&h.subtitleTracks){
                        sSel.innerHTML=""; var off=document.createElement("option"); off.value="-1"; off.textContent="Sin subs"; sSel.appendChild(off);
                        for(var j=0;j<h.subtitleTracks.length;j++){ var o2=document.createElement("option"); o2.value=String(j); o2.textContent=h.subtitleTracks[j].name||h.subtitleTracks[j].lang||("Sub "+j); sSel.appendChild(o2); }
                        sSel.value=String(h.subtitleTrack); if(sWrap) sWrap.style.display=h.subtitleTracks.length>0?"block":"none";
                    }
                }catch(e){}
            };
        }

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
            if (document.getElementById("hls-custom-layer")) {
                var oldBox=document.getElementById("hls-track-box"); if(oldBox) oldBox.style.display="none";
                try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){}
                return;
            }
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
                            try{ var curSubs2 = h.subtitleTrack; saveTitlePrefs(idx, curSubs2); }catch(e){}
                        } else if (h) {
                            var newUrl = "/api/hls/" + episodeKey + "/master.m3u8?prefetch=" + prefetchAhead + "&audio=" + idx;
                            log("Fallback loadSource " + newUrl + " cur=" + cur);
                            var onParsed = function(){ try{ videoPlayer.currentTime = cur; videoPlayer.play(); }catch(e){} try{ h.off(Hls.Events.MANIFEST_PARSED, onParsed); }catch(e){} };
                            h.on(Hls.Events.MANIFEST_PARSED, onParsed);
                            h.loadSource(newUrl);
                            try{ var curSubs3 = h.subtitleTrack; saveTitlePrefs(idx, curSubs3); }catch(e){}
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
                        log("BEFORE hls.subtitleTracks="+JSON.stringify((hlsInst.subtitleTracks||[]).map(function(t){return t.name||t.lang;}))+" curTrack="+hlsInst.subtitleTrack+" set to "+idx);
                        hlsInst.subtitleTrack = idx;
                        log("AFTER hls.subtitleTrack="+hlsInst.subtitleTrack);
                        try{ var curAudio2 = hlsInst.audioTrack; saveTitlePrefs(curAudio2, idx); }catch(e){}
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
                        try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){}
                        try {
                            var hlsInst = videoPlayer._hls;
                            var hasTracks = (data.audio_tracks && data.audio_tracks.length) || (data.sub_tracks && data.sub_tracks.length);
                            var hlsHasTracks = hlsInst && ((hlsInst.audioTracks && hlsInst.audioTracks.length) || (hlsInst.subtitleTracks && hlsInst.subtitleTracks.length));
                            if (hasTracks && !hlsHasTracks && !window.__hlsMasterReloaded) {
                                window.__hlsMasterReloaded = true;
                                var cur = videoPlayer.currentTime || 0;
                                log("master sin tracks al inicio, recargando master ahora que hay tracks");
                                var newUrl = "/api/hls/" + episodeKey + "/master.m3u8?prefetch=" + prefetchAhead;
                                if(window._autoSelDone){ window._autoSelDone.audio=false; window._autoSelDone.subs=false; }
                                hlsInst.loadSource(newUrl);
                                setTimeout(function(){ try{ videoPlayer.currentTime = cur; }catch(e){} }, 500);
                            } else if (hasTracks && hlsInst && window._autoSelDone) {
                                // intentar auto-select si aún no aplicado
                                try{ if(window.__doAutoSelect) window.__doAutoSelect(); }catch(e){}
                            }
                        } catch(e2) {}
                    }
                    // actualizar loader según bloques faltantes del segmento actual (X -> 0)
                    try{
                        log("cache-status loader seg="+(data.loader_seg||"-")+" miss="+(data.loader_missing||0)+"/"+(data.loader_initial||0)+" filled="+data.filled_blocks+"/"+data.total_blocks);
                        if(data && data.loader_initial && data.loader_initial>0){
                            var curMiss = data.loader_missing||0;
                            var initMiss = data.loader_initial||1;
                            var pct = Math.max(0, Math.min(100, ((initMiss - curMiss)/initMiss)*100));
                            if(curMiss===0) pct=100;
                            updateLoaderFill(pct);
                            var txt=document.getElementById("hls-loader-text");
                            if(txt) txt.textContent="Cargando segmento "+(data.loader_seg||0)+" ("+curMiss+" bloques restantes)";
                            if(curMiss===0 && hlsLoaderVisible) hideLoader();
                        } else if(data && data.total_blocks>0){
                            var pct2 = Math.min(100, (data.filled_blocks/data.total_blocks)*100);
                            if(pct2<5 && data.filled_blocks>0) pct2=5;
                            updateLoaderFill(pct2);
                            if(videoPlayer.readyState>=2 && hlsLoaderVisible && pct2>10) hideLoader();
                        }
                    }catch(e){ log("loader update error "+e); }
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
            customLayerReady=false;
            try{
                if(customLayer){
                    customLayer.style.opacity="0"; customLayer.style.visibility="hidden"; setLayerInteractive(false);
                    // quitar del DOM para no bloquear clicks en catálogo
                    setTimeout(function(){ try{ if(customLayer && customLayer.parentNode) customLayer.remove(); }catch(e){} }, 300);
                }
                // restaurar elementos ocultados al inicio
                var hideEls2=document.querySelectorAll("#detail-modal, #episodes-modal, #settings-modal, #filter-modal, #side-menu, #side-menu-overlay, .navbar");
                for(var hi=0; hi<hideEls2.length; hi++) try{ hideEls2[hi].style.display=""; }catch(e){}
                var bar2=document.getElementById("hls-download-bar"); if(bar2) bar2.style.display="none";
            }catch(e){}
            try { if (episodeKey) window.API.ajax({ method: 'POST', url: '/api/hls/' + episodeKey + '/leave' }); } catch(e) {}
            try { if (videoPlayer._hls) { videoPlayer._hls.stopLoad(); videoPlayer._hls.destroy(); videoPlayer._hls = null; } } catch(e) {}
            try { videoPlayer.pause(); } catch(e) {}
        }
        // envolver closePlayer una sola vez (evita spam de leave)
        try {
            if (!window.closePlayer._hlsWrapped) {
                var origClosePlayer = window.closePlayer;
                window.closePlayer = function() {
                    try{
                        var cl=document.getElementById("hls-custom-layer");
                        if(cl){ cl.style.opacity="0"; cl.style.visibility="hidden"; try{ cl.remove(); }catch(e){} }
                        var bar3=document.getElementById("hls-download-bar"); if(bar3) bar3.style.display="none";
                        var hideEls3=document.querySelectorAll("#detail-modal, #episodes-modal, #settings-modal, #filter-modal, #side-menu, #side-menu-overlay, .navbar");
                        for(var hi3=0; hi3<hideEls3.length; hi3++) try{ hideEls3[hi3].style.display=""; }catch(e){}
                    }catch(e){}
                    try { if (episodeKey) window.API.ajax({ method: 'POST', url: '/api/hls/' + episodeKey + '/leave' }); } catch(e) {}
                    try { if (videoPlayer._hls) { videoPlayer._hls.stopLoad(); videoPlayer._hls.destroy(); videoPlayer._hls = null; } } catch(e) {}
                    try { videoPlayer.pause(); } catch(e) {}
                    return origClosePlayer.apply(this, arguments);
                };
                window.closePlayer._hlsWrapped = true;
            }
        } catch(e) {}
        // WebKit antigua (Tizen 2.4) no tiene MutationObserver — guard para no romper registro del plugin
        try {
            if (typeof MutationObserver !== "undefined") {
                var observer = new MutationObserver(function() {
                    if (playerModal.classList.contains("hidden") || playerModal.style.display === "none") {
                        if (window.__hlsCachePollTimer) { clearInterval(window.__hlsCachePollTimer); window.__hlsCachePollTimer = null; }
                        var bar = document.getElementById("hls-download-bar");
                        if (bar) bar.style.display = "none";
                        notifyLeave();
                    }
                });
                observer.observe(playerModal, { attributes: true, attributeFilter: ["class", "style"] });
            }
        } catch(e) {}
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
        videoPlayer.oncanplay = function() { log("canplay readyState=" + videoPlayer.readyState + " video=" + videoPlayer.videoWidth + "x" + videoPlayer.videoHeight); if(hlsLoaderVisible) hideLoader(); };
        videoPlayer.onplaying = function() { log("playing video=" + videoPlayer.videoWidth + "x" + videoPlayer.videoHeight); customLayerReady=true; if(hlsLoaderVisible) hideLoader(); };
        videoPlayer.onstalled = function() { log("stalled"); };
        videoPlayer.onsuspend = function() { log("suspend"); };
        // Reset completo para segunda reproducción y seek
        try { videoPlayer.pause(); } catch(e) {}
        if (videoPlayer._hls) { try { videoPlayer._hls.destroy(); } catch(e) {} videoPlayer._hls = null; }
        try { videoPlayer.removeAttribute('src'); videoPlayer.load(); } catch(e) {}
        // _startPlayback: decisión de streaming re-ejecutable tras carga lazy de hls.min.js
        var _startPlayback = function() {
        var canHlsJs = (typeof Hls !== "undefined" && Hls.isSupported());
        var useNative = (canHls === "probably" || canHls === "maybe" || canHls2 === "probably" || canHls2 === "maybe");
        var _oldTV = false;
        try { var _c1 = window.detectDeviceCapabilities ? window.detectDeviceCapabilities() : (window.Catalog && window.Catalog.detectDeviceCapabilities ? window.Catalog.detectDeviceCapabilities() : null); _oldTV = _c1 && _c1.isOldSmartTV; } catch(e){}
        // TV antigua (WebKit 1.1): MSE de hls.js falla (internalException) → preferir HLS nativo del navegador
        if (_oldTV && useNative) {
            log("TV antigua: usando HLS NATIVO (MSE de hls.js no es fiable)");
            // FIX video plane HW (Tizen): limpiar CSS en contenedor, ancestros y video
            try { applyTizenPlaneFixLocal(pContainer || playerModal); } catch(e) {}
            try { applyTizenPlaneFixLocal(videoPlayer); } catch(e) {}
            videoPlayer.style.position = "fixed";
            videoPlayer.style.top = "0"; videoPlayer.style.left = "0";
            videoPlayer.style.width = "100%"; videoPlayer.style.height = "100%";
            videoPlayer.style.zIndex = "1";
            videoPlayer.style.objectFit = "contain";
            videoPlayer.style.background = "#000";
            videoPlayer.src = playlistUrl;
            videoPlayer.load();
            var _pn = null;
            try { _pn = videoPlayer.play(); } catch(e) { log("Error play: " + e); }
            if (_pn && _pn.then) { _pn.then(function(){ log("play() resolved"); }, function(e){ log("play() rejected: " + e); }); }
            setTimeout(function(){ try { applyTizenPlaneFixLocal(pContainer || playerModal); } catch(e){} }, 400);
        } else if (canHlsJs) {
            log("Usando hls.js (preferido)");
            var hls = new Hls({
                enableWorker: true,
                subtitleDisplay: true,
                lowLatencyMode: false,
                backBufferLength: 90,
                fragLoadingTimeOut: 60000,
                manifestLoadingTimeOut: 60000,
                levelLoadingTimeOut: 60000,
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
            window._autoSelDone = {audio:false, subs:false};
            window.__doAutoSelect = function(){
                try{
                    // Prio por título (central) prevalece sobre global
                    var titlePref = (window._hlsTitlePrefs && currentItemId && window._hlsTitlePrefs[currentItemId]) ? window._hlsTitlePrefs[currentItemId] : null;
                    if(titlePref){
                        log("auto-select titlePref "+currentItemId+" => "+JSON.stringify(titlePref)+" atracks="+(hls.audioTracks?hls.audioTracks.length:0)+" stracks="+(hls.subtitleTracks?hls.subtitleTracks.length:0));
                        if(hls.audioTracks&&hls.audioTracks.length&&!window._autoSelDone.audio && titlePref.audio!==undefined && titlePref.audio!==null){
                            var aiT = parseInt(titlePref.audio,10);
                            if(!isNaN(aiT) && aiT>=0 && aiT<hls.audioTracks.length){ hls.audioTrack=aiT; window._autoSelDone.audio=true; log("auto audioTrack (title) ->"+aiT+" ("+(hls.audioTracks[aiT].lang||hls.audioTracks[aiT].name)+")"); var aSel=document.getElementById("hls-audio-sel"); if(aSel) aSel.value=String(aiT); var caSel=document.getElementById("cc-audio-sel"); if(caSel) caSel.value=String(aiT); }
                        }
                        if(hls.subtitleTracks&&hls.subtitleTracks.length&&!window._autoSelDone.subs && titlePref.subs!==undefined && titlePref.subs!==null){
                            var siT = parseInt(titlePref.subs,10);
                            if(!isNaN(siT) && (siT===-1 || siT<hls.subtitleTracks.length)){ hls.subtitleTrack=siT; window._autoSelDone.subs=true; log("auto subtitleTrack (title) ->"+siT+(siT>=0?" ("+(hls.subtitleTracks[siT].lang||hls.subtitleTracks[siT].name)+")":" (desactivado)")); var sel=document.getElementById("hls-subs-sel"); if(sel) sel.value=String(siT); var csel=document.getElementById("cc-subs-sel"); if(csel) csel.value=String(siT); }
                        }
                        if(window._autoSelDone.audio && window._autoSelDone.subs){ try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){} return; }
                        // si título solo tenía una de las dos, dejar que global resuelva la otra
                    }
                    var p1a=getPref("prio1_audio","spa"), p2a=getPref("prio2_audio","eng");
                    var p1s=getPref("prio1_subs","spa"), p2s=getPref("prio2_subs","none");
                    log("auto-select attempt audio prio1="+p1a+" prio2="+p2a+" subs prio1="+p1s+" prio2="+p2s+" atracks="+(hls.audioTracks?hls.audioTracks.length:0)+" stracks="+(hls.subtitleTracks?hls.subtitleTracks.length:0));
                    if(hls.audioTracks&&hls.audioTracks.length&&!window._autoSelDone.audio){
                        var ai=findBestTrackIndex(hls.audioTracks,p1a,p2a);
                        if(ai>=0){ hls.audioTrack=ai; window._autoSelDone.audio=true; log("auto audioTrack ->"+ai+" ("+(hls.audioTracks[ai].lang||hls.audioTracks[ai].name)+")"); var aSel=document.getElementById("hls-audio-sel"); if(aSel) aSel.value=String(ai); var caSel=document.getElementById("cc-audio-sel"); if(caSel) caSel.value=String(ai); }
                    }
                    if(hls.subtitleTracks&&hls.subtitleTracks.length&&!window._autoSelDone.subs){
                        var si=-1; if(p1s!=="none") si=findBestTrackIndex(hls.subtitleTracks,p1s,p2s);
                        if(p1s==="none") si=-1; else if(si===-1&&p2s==="none") si=-1;
                        hls.subtitleTrack=si; window._autoSelDone.subs=true;
                        log("auto subtitleTrack ->"+si+(si>=0?" ("+(hls.subtitleTracks[si].lang||hls.subtitleTracks[si].name)+")":" (desactivado)"));
                        var sel=document.getElementById("hls-subs-sel"); if(sel) sel.value=String(si);
                        var csel=document.getElementById("cc-subs-sel"); if(csel) csel.value=String(si);
                    }
                    try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){}
                }catch(e3){ log("auto-select error: "+e3); }
            };
            hls.on(Hls.Events.MEDIA_ATTACHED, function(){ log("hls.js MEDIA_ATTACHED"); });
            hls.on(Hls.Events.MANIFEST_PARSED, function(ev, data){
                log("hls.js MANIFEST_PARSED levels=" + data.levels.length + " audioTracks=" + (hls.audioTracks ? hls.audioTracks.length : 0) + " subs=" + (hls.subtitleTracks ? hls.subtitleTracks.length : 0));
                window.__doAutoSelect();
                setTimeout(window.__doAutoSelect,500); setTimeout(window.__doAutoSelect,1500);
                try { videoPlayer.play(); } catch(e) { log("play error: " + e); }
            });
            hls.on(Hls.Events.AUDIO_TRACKS_UPDATED, function(){ log("AUDIO_TRACKS_UPDATED count=" + (hls.audioTracks?hls.audioTracks.length:0)); window.__doAutoSelect(); try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){} });
            hls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, function(){ log("SUBTITLE_TRACKS_UPDATED count=" + (hls.subtitleTracks?hls.subtitleTracks.length:0)); window.__doAutoSelect(); try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){} });
            hls.on(Hls.Events.AUDIO_TRACK_SWITCHED, function(ev,data){ log("AUDIO_TRACK_SWITCHED id="+data.id); var aS=document.getElementById("hls-audio-sel"); if(aS) aS.value=String(hls.audioTrack); try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){} });
            hls.on(Hls.Events.SUBTITLE_TRACK_SWITCH, function(ev,data){ log("SUBTITLE_TRACK_SWITCH id="+data.id); var sS=document.getElementById("hls-subs-sel"); if(sS) sS.value=String(hls.subtitleTrack); try{ if(window.__hlsSyncCustomCombos) window.__hlsSyncCustomCombos(); }catch(e){} });
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
            hls.on(Hls.Events.FRAG_LOADED, function(){ if(hlsLoaderVisible) hideLoader(); });
            hls.on(Hls.Events.FRAG_BUFFERED, function(){ if(hlsLoaderVisible) hideLoader(); });
            hls.loadSource(playlistUrl);
            hls.attachMedia(videoPlayer);
            // Auto fake-fullscreen al iniciar (PC/Android) — entra directamente maximizado
            try{ setTimeout(function(){ if(window._hlsToggleFakeFullscreen && !document.fullscreenElement && !document.webkitFullscreenElement){ window._hlsToggleFakeFullscreen(); } }, 500); }catch(e){}
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
        };
        // Arrancar ahora; si Hls faltaba, ensureHls lo carga lazy y re-ejecuta _startPlayback
        var _startPlaybackCalled = false;
        var needHls = (typeof Hls === "undefined");
        if (needHls) {
            ensureHls(function() {
                log("hls.min.js cargado lazy, reintentando");
                try { if(!_startPlaybackCalled){ _startPlayback(); _startPlaybackCalled=true; } } catch(e) { log("lazy err: "+e); }
            });
            setTimeout(function(){ try{ if(!_startPlaybackCalled){ _startPlayback(); _startPlaybackCalled=true; } }catch(e){ log("lazy timeout err: "+e); } }, 800);
        } else {
            try { _startPlayback(); _startPlaybackCalled=true; } catch(e) { log("start err: "+e); }
        }

        window.Catalog.currentMediaId = item.item_id || item.id;
        window.Catalog.currentPlayingItemId = item.item_id || item.id;
        window.Catalog.currentPlayingEpisodeId = ep.id || 0;
        window.Catalog.currentPlayingEpisodeKey = episodeKey;
        window.Catalog.currentPlayingVideoSrc = ep.video_src || "";
        // Guardar progreso cada 20s y al pausar/salir (igual que tvcat_player)
        try{
            var lastSavedPos=-1;
            var saveHlsProgress = function(completed){
                try{
                    var cur=Math.floor(videoPlayer.currentTime||0);
                    var dur=Math.floor(videoPlayer.duration||0);
                    if(completed){
                        window.API.updateHistory(window.Catalog.currentPlayingItemId, window.Catalog.currentPlayingVideoSrc, dur, dur, true, null, window.Catalog.currentPlayingEpisodeId, 0, window.Catalog.currentPlayingEpisodeKey);
                        log("progress guardado completed "+dur);
                        return;
                    }
                    if(dur>5 && cur>2 && cur!==lastSavedPos){
                        lastSavedPos=cur;
                        window.API.updateHistory(window.Catalog.currentPlayingItemId, window.Catalog.currentPlayingVideoSrc, cur, dur, false, null, window.Catalog.currentPlayingEpisodeId, 0, window.Catalog.currentPlayingEpisodeKey);
                        log("progress guardado "+cur+"/"+dur);
                    }
                }catch(e){}
            }
            if(window._hlsProgressTimer) clearInterval(window._hlsProgressTimer);
            window._hlsProgressTimer=setInterval(function(){ saveHlsProgress(false); }, 20000);
            videoPlayer.addEventListener("pause", function(){ saveHlsProgress(false); });
            videoPlayer.addEventListener("ended", function(){ saveHlsProgress(true); });
            // guardar al salir (envolver notifyLeave ya lo hace, añadir save)
            var _origNotifyLeave=notifyLeave;
            notifyLeave=function(){
                try{
                    var cur=Math.floor(videoPlayer.currentTime||0);
                    var dur=Math.floor(videoPlayer.duration||0);
                    if(dur>5 && cur>2){
                        window.API.updateHistory(window.Catalog.currentPlayingItemId, window.Catalog.currentPlayingVideoSrc, cur, dur, false, null, window.Catalog.currentPlayingEpisodeId, 0, window.Catalog.currentPlayingEpisodeKey);
                        log("progress guardado al salir "+cur+"/"+dur);
                    }
                }catch(e){}
                if(window._hlsProgressTimer){ clearInterval(window._hlsProgressTimer); window._hlsProgressTimer=null; }
                return _origNotifyLeave.apply(this, arguments);
            };
        }catch(e){ log("progress setup error "+e); }
    }

    function init() {
        log("Registrando player HLS");
        try {
            pluginSystem.registerPlugin({
            name: PLUGIN_NAME,
            type: "player",
            displayName: "Player HLS TV",
            playerType: "hls_tv",
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
        } catch(e) {
            log("HLS register error: " + e);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
