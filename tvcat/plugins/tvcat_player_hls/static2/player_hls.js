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
            return String(s).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").trim();
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

        // === CAPA CUSTOM (SmartTV-first) anclada al video ===
        var customLayer = document.getElementById("hls-custom-layer");
        var customHideTimer = null;
        var customTimeoutSec = 3.5;
        try { var ct = localStorage.getItem("tvcat_player_hls_custom_controls_timeout"); if(ct!==null) customTimeoutSec = parseFloat(JSON.parse(ct))||3.5; } catch(e){}
        function isCustomVisible() { return customLayer && parseFloat(customLayer.style.opacity||"0") >= 0.5; }
        function showCustomLayer() { if (!customLayer) return; syncCustomLayerToVideo(); customLayer.style.opacity="1"; customLayer.style.visibility="visible"; setLayerInteractive(true); resetCustomTimer(); }
        function hideCustomLayer() { if (!customLayer) return; customLayer.style.opacity="0"; setLayerInteractive(false); setTimeout(function(){ if(customLayer && customLayer.style.opacity==="0") customLayer.style.visibility="hidden"; }, 220); }
        function resetCustomTimer(){ if(customHideTimer) clearTimeout(customHideTimer); customHideTimer=setTimeout(hideCustomLayer, customTimeoutSec*1000); }
        function setLayerInteractive(on){
            if(!customLayer) return;
            var els=customLayer.querySelectorAll("[data-cc-interactive]");
            for(var i=0;i<els.length;i++) els[i].style.pointerEvents = on ? "auto" : "none";
        }
        function syncCustomLayerToVideo(){
            try{
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
            btnClose.addEventListener("click", function(e){ e.stopPropagation(); try{ window.closePlayer(); }catch(err){} });
            customLayer.appendChild(btnClose);
            customLayer.appendChild(createCustomBtn("cc-ep-prev",20,10,"episode_prev.png","Anterior","#fff","11px", function(){ var idx=episodes.indexOf(ep); if(idx>0) hlsPlayMedia(item, episodes, idx-1); }));
            customLayer.appendChild(createCustomBtn("cc-max",50,10,"maximize.png","^","#ff0","16px", function(){ toggleFakeFullscreen(); }));
            customLayer.appendChild(createCustomBtn("cc-ep-next",80,10,"episode_next.png","Siguiente","#fff","11px", function(){ var idx2=episodes.indexOf(ep); if(idx2>=0&&idx2<episodes.length-1) hlsPlayMedia(item, episodes, idx2+1); }));
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
            selA.addEventListener("change", function(){ var v=this.value; var idx=parseInt(v,10); try{ var h=videoPlayer._hls; if(h&&h.audioTracks&&h.audioTracks.length>idx){ h.audioTrack=idx; log("cc audioTrack ->"+idx);} }catch(e){} resetCustomTimer(); });
            comboAudioWrap.appendChild(selA); customLayer.appendChild(comboAudioWrap);
            var comboSubsWrap=document.createElement("div"); comboSubsWrap.id="cc-subs-wrap"; comboSubsWrap.setAttribute("data-cc-interactive","1");
            comboSubsWrap.style.cssText="position:absolute;right:12%;top:70%;width:28%;text-align:center;z-index:11;pointer-events:none;";
            var lblS=document.createElement("div"); lblS.textContent="Subtitle:"; lblS.style.cssText="color:#fff;font-size:11px;margin-bottom:2px;"; comboSubsWrap.appendChild(lblS);
            var selS=document.createElement("select"); selS.id="cc-subs-sel"; selS.style.cssText="width:100%;padding:4px;background:rgba(0,0,0,0.85);color:#fff;border:1px solid #888;font-size:11px;";
            selS.addEventListener("click", function(e){ e.stopPropagation(); resetCustomTimer(); });
            selS.addEventListener("change", function(){ var v=this.value; var idx=parseInt(v,10); try{ var h2=videoPlayer._hls; if(h2){ h2.subtitleTrack=idx; log("cc subtitleTrack ->"+idx);} }catch(e){} resetCustomTimer(); });
            comboSubsWrap.appendChild(selS); customLayer.appendChild(comboSubsWrap);
            playerModal.appendChild(customLayer);
            function onPlayerClick(e){ if(!customLayer) return; if(e.target && e.target.getAttribute && e.target.getAttribute("data-cc-interactive")) return; showCustomLayer(); }
            function onMouseMove(e){ if(!customLayer||playerModal.style.display==="none") return; showCustomLayer(); }
            try{ playerModal.addEventListener("click", onPlayerClick); videoPlayer.addEventListener("click", onPlayerClick); videoPlayer.addEventListener("mousemove", onMouseMove); playerModal.addEventListener("mousemove", onMouseMove); }catch(e){}
            try{ window.addEventListener("resize", syncCustomLayerToVideo); document.addEventListener("fullscreenchange", syncCustomLayerToVideo); document.addEventListener("webkitfullscreenchange", syncCustomLayerToVideo); videoPlayer.addEventListener("loadedmetadata", syncCustomLayerToVideo); }catch(e){}
            var _fakeFs = false;
            function toggleFakeFullscreen(){
                _fakeFs = !_fakeFs;
                try{
                    if(_fakeFs){
                        if(playerModal.requestFullscreen) playerModal.requestFullscreen();
                        else if(playerModal.webkitRequestFullscreen) playerModal.webkitRequestFullscreen();
                    } else {
                        if(document.fullscreenElement||document.webkitFullscreenElement){
                            if(document.exitFullscreen) document.exitFullscreen();
                            else if(document.webkitExitFullscreen) document.webkitExitFullscreen();
                        }
                    }
                }catch(e){ log("max error "+e); }
                var maxBtn=document.getElementById("cc-max");
                if(maxBtn){ var im=maxBtn.querySelector("img"); if(im && im.style.display==="none"){ maxBtn.childNodes.forEach(function(n){ if(n.nodeType===3) n.textContent=""; }); maxBtn.appendChild(document.createTextNode(_fakeFs?"Restaurar":"^")); maxBtn.style.color="#ff0"; } }
                resetCustomTimer();
                setTimeout(syncCustomLayerToVideo, 100);
            }
            // actualizar estado _fakeFs al salir con ESC
            try{
                document.addEventListener("fullscreenchange", function(){ _fakeFs=!!document.fullscreenElement; syncCustomLayerToVideo(); });
                document.addEventListener("webkitfullscreenchange", function(){ _fakeFs=!!document.webkitFullscreenElement; syncCustomLayerToVideo(); });
            }catch(e){}
            function onKeyDown(e){
                if(!customLayer||playerModal.style.display==="none") return;
                var d=null; try{ d=window.keyMapper?window.keyMapper.getVirtualDigit(e):null; }catch(err){}
                if(d===null){ var kc=e.keyCode||e.which; if(kc>=48&&kc<=57) d=String.fromCharCode(kc); else if(kc>=96&&kc<=105) d=String.fromCharCode(kc-48); }
                if(d===null) return;
                if(!isCustomVisible()){ showCustomLayer(); if("7894561230".indexOf(d)!==-1) e.preventDefault(); return; }
                var map={"7":"cc-ep-prev","8":"cc-max","9":"cc-ep-next","4":"cc-jump-back-long","5":"cc-play-pause","6":"cc-jump-forw-long","1":"cc-jump-back-short","2":"cc-skip-intro","3":"cc-jump-forw-short","0":"cc-back"};
                // fallback id for volver es btnBack sin id, usar close
                if(d==="0"){ e.preventDefault(); try{ window.closePlayer(); }catch(err){} resetCustomTimer(); return; }
                var bid=map[d]; if(bid){ e.preventDefault(); var el=document.getElementById(bid); if(el) el.click(); resetCustomTimer(); }
            }
            try{ window.addEventListener("keydown", onKeyDown); document.addEventListener("keydown", onKeyDown); }catch(e){}
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
                        log("BEFORE hls.subtitleTracks="+JSON.stringify((hlsInst.subtitleTracks||[]).map(function(t){return t.name||t.lang;}))+" curTrack="+hlsInst.subtitleTrack+" set to "+idx);
                        hlsInst.subtitleTrack = idx;
                        log("AFTER hls.subtitleTrack="+hlsInst.subtitleTrack);
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
