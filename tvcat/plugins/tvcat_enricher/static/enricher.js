(function () {
    if (!window.pluginSystem) return;

    function apiFetch(path, body, cb) {
        var url = path;
        var opts = {
            method: body ? 'POST' : 'GET',
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        fetch(url, opts)
            .then(function (r) { return r.json(); })
            .then(function (j) { cb(j); })
            .catch(function () { cb(null); });
    }

    function getHeroButtons(itemData) {
        if (!itemData || !itemData.item_id) return [];
        // Color del botón según autoría (verde si es mío -> edita Telegram, azul si ajeno -> solo local)
        setTimeout(function(){
            try {
                fetch('/api/enricher/item/' + encodeURIComponent(itemData.item_id) + '/authorship').then(function(r){ return r.ok ? r.json() : null; }).then(function(auth){
                    var btn = document.getElementById('btn-enricher');
                    if (!btn || !auth) return;
                    if (auth.is_mine) {
                        btn.style.background = 'rgba(34,197,94,0.18)';
                        btn.style.borderColor = '#22c55e';
                        btn.style.borderWidth = '1px';
                    } else {
                        btn.style.background = 'rgba(59,130,246,0.15)';
                        btn.style.borderColor = '#3b82f6';
                        btn.style.borderWidth = '1px';
                    }
                }).catch(function(){});
            } catch(e){}
        }, 400);
        return [{
            id: 'btn-enricher',
            icon: '<img src="/plugin-static/tvcat_enricher/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="pluginIconFallback(this,\'✨\',20)">',
            tooltip: 'Enriquecer',
            label: '',
            action: function () {
                try { console.log('[Enricher] click', itemData); } catch(e) {}
                openEnricher(itemData);
            }
        }];
    }

    function openEnricher(itemData, opts) {
        try { console.log('[Enricher] open', itemData); } catch(e) {}
        var itemId = itemData.item_id;
        var _opts = opts || {};
        // Customs frescos en cada apertura (si se editaron en Configuración,
        // la caché de la SPA estaría rancia hasta recargar).
        try { if (window.refreshCustomTags) window.refreshCustomTags(function(){}); } catch(eR) {}
        // Fetch estado + authorship en paralelo
        Promise.all([
            fetch('/api/enricher/item/' + encodeURIComponent(itemId)).then(function (r) { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); }).catch(function (e) { try { console.error('[Enricher] /item err', e); } catch(ex) {} return null; }),
            fetch('/api/enricher/item/' + encodeURIComponent(itemId) + '/authorship').then(function (r) { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); }).catch(function (e) { try { console.error('[Enricher] /authorship err', e); } catch(ex) {} return null; })
        ]).then(function (vals) {
            var data = vals[0];
            var auth = vals[1] || { is_mine: false, author_user_id: null, reason: '' };
            if (!data) { alert('No se pudo cargar el item (¿gateway reiniciado?)'); return; }
            buildModal(data, auth, itemData, _opts);
        }).catch(function(e){ try { console.error('[Enricher] open err', e); } catch(ex) {} alert('Error: '+e); });
    }

    function buildModal(data, auth, itemData, opts) {
        opts = opts || {};
        var itemId = data.item_id;
        var original = data.original || {};
        // localOnly (cola TGHirayi): lo compartido no existe aquí; todo sale del job.
        var enriched = opts.localOnly ? null : (data.enriched || null);
        var hasEnriched = !!enriched;
        var category = original.category || itemData.category || '';
        var subcategory = original.subcategory || itemData.subcategory || '';
        var episodeCount = (function () { try { return itemData.episodes && itemData.episodes.length ? itemData.episodes.length : 0; } catch (e) { return 0; } })();
        var initialText = (opts.localOnly && opts.initialText != null) ? String(opts.initialText) : (hasEnriched ? (enriched.cover_text || '') : (original.description || ''));
        // Caption inicial en localOnly: texto ya resuelto del job (lo guardado, no la plantilla).
        var initialCaption = (opts.localOnly && opts.initialCaption != null) ? String(opts.initialCaption) : initialText;
        var initialDetails = opts.localOnly ? (opts.details || null) : (hasEnriched ? (enriched.enrich_details || {}) : null);
        // Póster propio del job (b64 sin prefijo) para preview inicial en localOnly.
        var localPosterB64 = (opts.localOnly && opts.posterB64) ? String(opts.posterB64) : '';
        if (localPosterB64.indexOf('data:') === 0 && localPosterB64.indexOf(',') !== -1) localPosterB64 = localPosterB64.split(',').slice(1).join(',');
        var posterB64 = null; // de la imagen actual o del candidato
        var posterMime = 'image/jpeg';
        var selectedDetails = initialDetails;
        var selectedProvider = null;
        var selectedProviderTab = 'auto';  // override manual de proveedor
        var selectedId = null;
        var selectedPosterUrl = null; // URL del póster del candidato (el servidor la descarga si el b64 falla)
        var selectedSeason = null; // temporada detectada en la búsqueda (T1/S01/temporada N) para details

        // Overlay
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;';
        overlay.onclick = function (e) { if (e.target === overlay) { try { if (typeof _esClearEditing === 'function') _esClearEditing(); } catch (_eoc) {} overlay.remove(); } };
        var panel = document.createElement('div');
        panel.style.cssText = 'background:#0d0d0f;border:1px solid #3f3f46;border-radius:10px;padding:16px;width:92vw;max-width:720px;max-height:94vh;overflow-y:auto;color:#f4f4f5;box-sizing:border-box;';
        panel.onclick = function (e) { e.stopPropagation(); };
        var html = '';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">';
        html += '<div style="font-weight:700;font-size:0.95rem;">' + (opts.localOnly ? 'Cover propio (solo este partido)' : '✨ Enriquecer cover') + '</div>';
        html += '<button id="enricher-close" style="width:32px;height:32px;border-radius:50%;background:#27272a;border:1px solid #3f3f46;color:#a1a1aa;cursor:pointer;font-size:18px;line-height:1;">×</button>';
        html += '</div>';

        // Badge de estado (localOnly: solo cola, sin autoría compartida)
        var badge = '';
        if (opts.localOnly) {
            badge = '<span style="display:inline-block;padding:2px 8px;background:#06b6d422;color:#22d3ee;border-radius:999px;font-size:0.68rem;border:1px solid #164e63;">Solo cola — no toca catálogo</span>';
        } else {
        if (hasEnriched) badge = '<span style="display:inline-block;padding:2px 8px;background:#22c55e22;color:#4ade80;border-radius:999px;font-size:0.68rem;border:1px solid #14532d;">Enriquecido</span> ';
        if (auth.is_mine) badge += '<span style="display:inline-block;padding:2px 8px;background:#06b6d422;color:#22d3ee;border-radius:999px;font-size:0.68rem;border:1px solid #164e63;">Tuyo — editable en Telegram</span>';
        else badge += '<span style="display:inline-block;padding:2px 8px;background:#f59e0b22;color:#fbbf24;border-radius:999px;font-size:0.68rem;border:1px solid #78350f;">Ajeno — solo local</span>';
        }
        html += '<div style="margin-bottom:10px;">' + badge + '<span style="font-size:0.68rem;color:#71717a;margin-left:6px;">' + (opts.localOnly ? '' : (auth.reason || '')) + '</span></div>';
        // Título del job (solo localOnly): editable, con sugerido del candidato.
        if (opts.localOnly) {
            var _jt0 = (opts.jobTitle != null ? String(opts.jobTitle) : '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
            html += '<label style="font-size:0.75rem;color:#a1a1aa;">Título del job</label>';
            html += '<div style="display:flex;gap:6px;margin-top:4px;margin-bottom:10px;">';
            html += '<input type="text" id="enricher-job-title" value="' + _jt0 + '" style="flex:1;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;">';
            html += '</div>';
            html += '<div id="enricher-title-sugg" style="display:none;font-size:0.72rem;color:#a1a1aa;margin:-6px 0 10px;">Sugerido: <span id="enricher-title-sugg-v" style="color:#22d3ee;"></span> <a href="#" id="enricher-title-use" style="color:#22d3ee;">usar</a></div>';
        }

        // Imagen + busqueda lado a lado
        html += '<div style="display:flex;gap:12px;margin-bottom:12px;align-items:flex-start;flex-wrap:wrap;">';
        html += '<div style="flex-shrink:0;width:160px;max-width:38%;">';
        if (localPosterB64) {
            // Póster propio del job (localOnly): preview directo, sin registry.
            html += '<img id="enricher-img" src="data:image/jpeg;base64,' + localPosterB64 + '" style="width:100%;border-radius:8px;border:1px solid #3f3f46;display:block;max-height:220px;object-fit:cover;">';
        } else if (hasEnriched && data.enriched && data.enriched.poster_blob) {
            // servido desde /api/enricher/item/{id}/cover para preview
            html += '<img id="enricher-img" src="/api/enricher/item/' + encodeURIComponent(itemId) + '/cover?v=' + Date.now() + '" style="width:100%;border-radius:8px;border:1px solid #3f3f46;display:block;max-height:220px;object-fit:cover;">';
        } else {
            html += '<img id="enricher-img" src="/api/cover/' + encodeURIComponent(itemId) + '" style="width:100%;border-radius:8px;border:1px solid #3f3f46;display:block;max-height:220px;object-fit:cover;" onerror="this.style.display=\'none\';document.getElementById(\'enricher-img-placeholder\').style.display=\'flex\';">';
            html += '<div id="enricher-img-placeholder" style="display:none;width:100%;height:140px;border-radius:8px;border:1px dashed #3f3f46;align-items:center;justify-content:center;font-size:0.7rem;color:#71717a;background:#18181b;">sin imagen</div>';
        }
        html += '<label style="display:flex;align-items:center;gap:6px;margin-top:8px;font-size:0.72rem;color:#a1a1aa;cursor:pointer;"><input type="checkbox" id="enricher-use-poster" checked> Usar imagen descargada</label>';
        html += '<div style="display:flex;align-items:center;gap:6px;margin-top:6px;font-size:0.72rem;color:#a1a1aa;"><span style="white-space:nowrap;">Traer<br>versión</span>' +
            '<select id="enricher-poster-lang" class="variant-select" style="background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:4px 6px;color:#f4f4f5;font-size:0.72rem;flex:0 0 auto;max-width:110px;">' +
            '<option value="">Cualquiera</option>' +
            '<option value="es">ES - Español</option>' +
            '<option value="en">EN - English</option>' +
            '<option value="ja">JA - Japonés</option>' +
            '<option value="ko">KO - Coreano</option>' +
            '<option value="zh">ZH - Chino</option>' +
            '</select>' +
            '</div>';
        html += '<div style="position:relative;">';
        html += '<div id="enricher-cover-menu" style="display:none;position:absolute;left:0;top:100%;z-index:20;background:#09090b;border:1px solid #3f3f46;border-radius:8px;padding:6px;width:170px;box-sizing:border-box;">';
        html += '<div id="enricher-cover-obt" style="display:none;"></div>';
        html += '<button id="enricher-cover-orig" style="display:block;width:100%;padding:8px 10px;font-size:0.8rem;margin:2px 0;text-align:left;background:#27272a;border:1px solid #3f3f46;color:#f4f4f5;border-radius:6px;cursor:pointer;">🖼️ Original</button>';
        html += '<button id="enricher-cover-url" style="display:block;width:100%;padding:8px 10px;font-size:0.8rem;margin:2px 0;text-align:left;background:#27272a;border:1px solid #3f3f46;color:#f4f4f5;border-radius:6px;cursor:pointer;">🔗 URL</button>';
        html += '<button id="enricher-cover-paste" style="display:block;width:100%;padding:8px 10px;font-size:0.8rem;margin:2px 0;text-align:left;background:#27272a;border:1px solid #3f3f46;color:#f4f4f5;border-radius:6px;cursor:pointer;">📋 Pegar</button>';
        html += '<button id="enricher-cover-upload" style="display:block;width:100%;padding:8px 10px;font-size:0.8rem;margin:2px 0;text-align:left;background:#27272a;border:1px solid #3f3f46;color:#f4f4f5;border-radius:6px;cursor:pointer;">⬆️ Subir</button>';
        html += '</div>';
        html += '<input type="file" id="enricher-cover-file" accept="image/*" style="display:none;">';
        html += '</div>';
        html += '</div>';
        html += '<div style="flex:1;min-width:260px;">';
        // Busqueda enriquecedor
        html += '<label style="font-size:0.75rem;color:#a1a1aa;">Buscar en enriquecedor</label>';
        html += '<div style="display:flex;gap:6px;margin-top:4px;">';
        var defaultQuery = (original.title || itemData.title || '').trim();
        html += '<input type="text" id="enricher-query" value="' + defaultQuery.replace(/"/g, '&quot;') + '" placeholder="Titulo o URL directa (TMDB/IGDB/Books/ComicVine)" style="flex:1;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;">';
        html += '<button id="enricher-search" style="padding:6px 12px;background:#06b6d4;border:none;color:#fff;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:700;">Buscar</button>';
        html += '</div>';
        // Pestañas de proveedor: override manual (auto = según categoría).
        html += '<div id="enricher-prov-tabs" style="display:flex;gap:4px;margin-top:6px;flex-wrap:wrap;">';
        var _provs = [['auto', 'Auto'], ['tmdb', 'TMDB'], ['igdb', 'IGDB'], ['books', 'Books'], ['comicvine', 'ComicVine']];
        for (var _pi = 0; _pi < _provs.length; _pi++) {
            html += '<button data-prov="' + _provs[_pi][0] + '" class="enricher-prov-tab" style="padding:3px 10px;font-size:0.7rem;border-radius:12px;cursor:pointer;border:1px solid #3f3f46;background:' + (_pi === 0 ? '#06b6d4;color:#fff;border-color:#06b6d4;' : '#27272a;color:#a1a1aa;') + '">' + _provs[_pi][1] + '</button>';
        }
        html += '</div>';
        html += '<div id="enricher-extlinks" style="margin-top:4px;font-size:0.68rem;color:#71717a;"></div>';
        html += '<div id="enricher-cands" style="margin-top:8px;max-height:140px;overflow-y:auto;"></div>';
        html += '</div></div>';

        // Selector de plantilla (combo con todas las plantillas, auto-seleccion mas parecida a cat/sub)
        html += '<label style="font-size:0.75rem;color:#a1a1aa;display:block;margin-top:8px;">Plantilla</label>';
        html += '<div style="display:flex;gap:6px;align-items:center;margin-top:4px;">';
        html += '<select id="enricher-tpl-select" class="variant-select" style="flex:1;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"><option value="">Cargando plantillas...</option></select>';
        html += '<button id="enricher-tpl-apply" style="padding:6px 12px;background:#06b6d4;border:none;color:#fff;border-radius:6px;cursor:pointer;font-size:0.75rem;font-weight:600;white-space:nowrap;">Aplicar</button>';
        html += '</div>';
        html += '<label style="font-size:0.7rem;color:var(--text-secondary);display:block;margin-top:6px;">Contenido de la plantilla (con tags, editable):</label>';
        html += '<textarea id="enricher-tpl-raw" rows="3" placeholder="Ej: {title} ({year}) {ftitle}..." style="width:100%;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:0.75rem;box-sizing:border-box;resize:vertical;white-space:pre-wrap;"></textarea>';
        // Textarea de edicion (7.3: edicion libre + tags)
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">';
        html += '<label style="font-size:0.75rem;color:#a1a1aa;display:block;">Caption (editable, con tags del enriquecedor)</label>';
        html += '<span style="display:flex;gap:4px;align-items:center;">';
        html += '<button id="enricher-copy-title" title="Copiar topic formateado (Title🗓Year)" style="padding:4px 8px;font-size:0.7rem;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer;white-space:nowrap;">Title</button>';
        html += '<button id="enricher-copy-title-season" title="Copiar topic con temporada (Título - Season X🗓AAAA)" style="padding:4px 8px;font-size:0.7rem;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer;white-space:nowrap;">TitleSeason</button>';
        html += '<button id="enricher-copy-image" title="Copiar la URL de la imagen actual" style="padding:4px 8px;font-size:0.7rem;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer;white-space:nowrap;">Image</button>';
        html += '<button id="enricher-copy-desc" title="Copiar la descripción actual al portapapeles" style="padding:4px 8px;font-size:0.7rem;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer;white-space:nowrap;">Desc</button>';
        html += '<button id="enricher-tags-btn" style="padding:4px 8px;font-size:0.7rem;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer;white-space:nowrap;">Tags ▾</button>';
        html += '</span></div>';
        html += '<div style="font-size:0.68rem;color:#71717a;margin:2px 0 4px;">Escribe {title} y al cerrar } se expande · o usa Tags</div>';
        html += '<textarea id="enricher-text" style="width:100%;height:140px;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;resize:vertical;white-space:pre-wrap;">' + (initialCaption || '').replace(/</g, '&lt;') + '</textarea>';
        html += '<div id="enricher-tags-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;z-index:1000000;background:rgba(0,0,0,0.7);align-items:center;justify-content:center;"><div style="background:#0d0d0f;border:1px solid #3f3f46;border-radius:8px;padding:12px;width:90vw;max-width:560px;max-height:80vh;overflow:hidden;display:flex;flex-direction:column;"><div style="font-weight:600;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;"><span>Tags</span><button id="enricher-tags-close" style="width:28px;height:28px;border-radius:50%;background:#27272a;border:1px solid #3f3f46;color:#a1a1aa;cursor:pointer;">×</button></div><div id="enricher-tags-table" style="overflow-y:auto;flex:1;border:1px solid #27272a;border-radius:6px;"></div></div></div>';

        // Poster actual (hidden, se sube como base64 en el payload, reutiliza el del candidato si hay)
        html += '<input type="hidden" id="enricher-poster-b64" value="' + (localPosterB64 ? 'data:image/jpeg;base64,' + localPosterB64 : '') + '">';
        // Botones
        html += '<div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;">';
        html += '<button id="enricher-save-local" style="flex:1;min-width:120px;padding:9px;background:#3f3f46;border:none;color:#f4f4f5;border-radius:6px;cursor:pointer;font-weight:600;">Guardar local</button>';
        if (auth.is_mine) {
            html += '<button id="enricher-apply" style="flex:1;min-width:150px;padding:9px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:700;">Aplicar en Telegram</button>';
        }
        html += '</div>';
        // hasEnriched es falso en localOnly (enriched=null): el Revertir (borra lo
        // COMPARTIDO) nunca se pinta en la cola.
        if (hasEnriched) html += '<button id="enricher-revert" style="width:100%;margin-top:8px;padding:6px;background:transparent;border:1px solid #ef4444;color:#f87171;border-radius:6px;cursor:pointer;font-size:0.8rem;">Volver a cover original</button>';
        html += '<div id="enricher-status" style="margin-top:8px;font-size:0.75rem;color:#a1a1aa;min-height:1.2em;"></div>';
        panel.innerHTML = html;
        overlay.appendChild(panel);
        document.body.appendChild(overlay);
        document.getElementById('enricher-close').onclick = function () { try { _esClearEditing(); } catch (e) {} overlay.remove(); };
        // Copiar texto al portapapeles (Clipboard API + fallback legacy).
        function copyText(t, okMsg) {
            if (!t) { setStatus('Nada que copiar', true); return; }
            function done() { setStatus(okMsg || 'Copiado'); }
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(t).then(done, function() { legacyCopy(t); done(); });
                } else legacyCopy(t), done();
            } catch (e) { try { legacyCopy(t); done(); } catch (e2) {} }
        }
        function legacyCopy(t) {
            var ta = document.createElement('textarea');
            ta.value = t;
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); } catch (e) {}
            ta.remove();
        }
        // Title: topic formateado (Title🗓Year) listo para crear el topic a mano.
        var _cpTitle = document.getElementById('enricher-copy-title');
        if (_cpTitle) _cpTitle.onclick = function() {
            var t = currentTopicName();
            if (!t) { setStatus('Sin topic todavía (aplica la plantilla primero)', true); return; }
            copyText(t, 'Topic copiado: ' + t);
        };
        // TitleSeason: igual + " - Season X" si hay temporada (Título - Season X🗓AAAA).
        var _cpTitleS = document.getElementById('enricher-copy-title-season');
        if (_cpTitleS) _cpTitleS.onclick = function() {
            var t = currentTopicSeasonName();
            if (!t) { setStatus('Sin topic todavía (aplica la plantilla primero)', true); return; }
            copyText(t, 'Topic copiado: ' + t);
        };
        // Image: la URL de la imagen actual como texto (el blob binario no se
        // puede copiar al portapapeles en HTTP/CORS).
        var _cpImg = document.getElementById('enricher-copy-image');
        if (_cpImg) _cpImg.onclick = function() {
            var url = selectedPosterUrl || '';
            if (!url || url.indexOf('http') !== 0) {
                try {
                    var det = selectedDetails || {};
                    var cl = det.api_cover;
                    if (typeof cl === 'string') { try { cl = JSON.parse(cl); } catch (e) { cl = [cl]; } }
                    if (cl && cl.length) url = cl[0] || '';
                } catch (e) {}
            }
            if (!url || url.indexOf('http') !== 0) {
                var img = document.getElementById('enricher-img');
                var src = (img && img.src) || '';
                if (src && src.indexOf('http') === 0) url = src;
            }
            if (!url) { setStatus('Sin URL de imagen (elige candidato)', true); return; }
            copyText(url, 'URL copiada');
        };
        // Desc: copia literal del contenido actual de la caja de caption.
        var _cpDesc = document.getElementById('enricher-copy-desc');
        if (_cpDesc) _cpDesc.onclick = function() {
            var t = (document.getElementById('enricher-text') || {}).value || '';
            if (!t.trim()) { setStatus('La caja está vacía', true); return; }
            copyText(t, 'Caption copiado');
        };
        // EditSync standby: publicar item en edición (debounce) y limpiar al
        // guardar/cerrar. Servidor guarda por usuario con TTL (import decide).
        var _esEditTimer = null;
        function _esPublishEditing() {
            try {
                var iid = (typeof itemId !== 'undefined') ? itemId : '';
                if (!iid) return;
                fetch('/api/editsync/editing', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_id: iid })
                }).catch(function() {});
            } catch (e) {}
        }
        function _esClearEditing() {
            try {
                if (_esEditTimer) { clearTimeout(_esEditTimer); _esEditTimer = null; }
                fetch('/api/editsync/editing', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_id: null })
                }).catch(function() {});
            } catch (e) {}
        }
        try {
            var _capEdit = document.getElementById('enricher-text');
            if (_capEdit) {
                var _onEditInput = function() {
                    if (_esEditTimer) clearTimeout(_esEditTimer);
                    _esEditTimer = setTimeout(_esPublishEditing, 1500);
                };
                if (_capEdit.addEventListener) _capEdit.addEventListener('input', _onEditInput, false);
                else _capEdit.oninput = _onEditInput;
            }
        } catch (e3) {}
        // Topic en vivo al editar el caption + clic para copiar.
        try {
            var _cap = document.getElementById('enricher-text');
            if (_cap) {
                if (_cap.addEventListener) _cap.addEventListener('input', updateTopicName, false);
                else _cap.oninput = updateTopicName;
            }
            var _trow = document.getElementById('enricher-topic-name');
            if (_trow) _trow.onclick = function() {
                try {
                    var _t = document.getElementById('enricher-topic-name').textContent || '';
                    if (!_t || _t === '—') return;
                    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(_t);
                    else { var _ta = document.createElement('textarea'); _ta.value = _t; document.body.appendChild(_ta); _ta.select(); document.execCommand('copy'); _ta.remove(); }
                    setStatus('Topic copiado: ' + _t);
                } catch (e) {}
            };
            updateTopicName();
        } catch (e2) {}
        // Toggle preview original vs descargada
        (function(){
            var chk = document.getElementById('enricher-use-poster');
            var img = document.getElementById('enricher-img');
            var ph = document.getElementById('enricher-img-placeholder');
            if (!chk || !img) return;
            var origSrc = '/api/cover/' + encodeURIComponent(itemId) + '?v=' + Date.now();
            var enrichedSrc = hasEnriched && data.enriched && data.enriched.poster_blob ? ('/api/enricher/item/' + encodeURIComponent(itemId) + '/cover?v=' + Date.now()) : null;
            // localOnly: el "descargado" es el póster propio del job.
            if (!enrichedSrc && localPosterB64) enrichedSrc = 'data:image/jpeg;base64,' + localPosterB64;
            // Si hay poster seleccionado de búsqueda, usar ese b64 como enriched
            chk.onchange = function(){
                if (chk.checked) {
                    var b64 = document.getElementById('enricher-poster-b64');
                    var curB64 = b64 ? b64.value : null;
                    if (curB64 && curB64.indexOf('data:')===0) {
                        img.src = curB64;
                    } else if (enrichedSrc) {
                        img.src = enrichedSrc;
                    } else {
                        img.src = origSrc;
                    }
                    img.style.display = 'block';
                    if (ph) ph.style.display = 'none';
                } else {
                    img.src = origSrc;
                    img.style.display = 'block';
                    if (ph) ph.style.display = 'none';
                    img.onerror = function(){ this.style.display='none'; if (ph) ph.style.display='flex'; };
                }
            };
        })();

        // Menú de portada (click en la imagen): Original / Obtenidas / URL / Pegar / Subir
        (function(){
            var img = document.getElementById('enricher-img');
            var menu = document.getElementById('enricher-cover-menu');
            if (!img || !menu) return;
            img.style.cursor = 'pointer';
            img.title = 'Cambiar carátula';
            img.onclick = function (ev) {
                if (ev && ev.stopPropagation) ev.stopPropagation();
                menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
            };
            document.addEventListener('click', function (e) {
                if (menu.style.display !== 'block') return;
                var t = e.target || e.srcElement;
                var inside = false;
                try {
                    var el = t;
                    while (el) {
                        if (el === menu || el === img) { inside = true; break; }
                        el = el.parentNode;
                    }
                } catch (ex) {}
                if (!inside) hideEnricherCoverMenu();
            });
            function setCustomPoster(src, b64, url) {
                hideEnricherCoverMenu();
                var chk = document.getElementById('enricher-use-poster');
                if (chk && !chk.checked) chk.checked = true;
                selectedPosterUrl = url || null;
                img.src = src;
                img.style.display = 'block';
                var ph = document.getElementById('enricher-img-placeholder');
                if (ph) ph.style.display = 'none';
                if (b64 !== undefined) {
                    document.getElementById('enricher-poster-b64').value = b64 || '';
                }
            }
            var bOrig = document.getElementById('enricher-cover-orig');
            if (bOrig) bOrig.onclick = function () {
                hideEnricherCoverMenu();
                var chk = document.getElementById('enricher-use-poster');
                if (chk) {
                    chk.checked = false;
                    if (typeof chk.onchange === 'function') chk.onchange();
                }
                setStatus('Carátula: original (sin imagen descargada)');
            };
            var bUrl = document.getElementById('enricher-cover-url');
            if (bUrl) bUrl.onclick = function () {
                function ask(def) {
                    var u = prompt('URL de la imagen de portada:', def || 'https://');
                    if (u === null) return;
                    u = (u || '').trim();
                    if (!u) return;
                    // Sin b64: el servidor la descarga vía poster_url al guardar
                    setCustomPoster(u, '', u);
                    setStatus('Carátula: URL personalizada (se descarga al guardar)');
                }
                // Si el portapapeles trae una URL, pre-rellenar con ella.
                try {
                    if (navigator.clipboard && navigator.clipboard.readText) {
                        navigator.clipboard.readText().then(function (t) {
                            t = (t || '').trim();
                            if (/^https?:\/\/\S+$/i.test(t) && t.length < 2000) ask(t);
                            else ask('https://');
                        }, function () { ask('https://'); });
                    } else ask('https://');
                } catch (e) { ask('https://'); }
            };
            // Pegado por evento (Ctrl+V en el modal): funciona donde
            // navigator.clipboard.read() está bloqueado (http remoto, iframes,
            // permisos). Se auto-elimina al cerrar el editor.
            function onPasteEvent(e) {
                try {
                    try {
                        if (!overlay || !document.contains(overlay)) {
                            document.removeEventListener('paste', onPasteEvent);
                            return;
                        }
                    } catch (e0) { return; }
                    var cd = e.clipboardData || window.clipboardData;
                    if (!cd || !cd.items) return;
                    for (var i = 0; i < cd.items.length; i++) {
                        var it = cd.items[i];
                        if (it.type && it.type.indexOf('image/') === 0) {
                            var blob = it.getAsFile ? it.getAsFile() : null;
                            if (!blob) continue;
                            if (blob.size > 10 * 1024 * 1024) { setStatus('Imagen mayor de 10MB', true); return; }
                            try { e.preventDefault(); } catch (e2) {}
                            var rd = new FileReader();
                            rd.onload = function () { setCustomPoster(rd.result, rd.result, null); setStatus('Carátula: imagen pegada (Ctrl+V)'); };
                            rd.readAsDataURL(blob);
                            return;
                        }
                    }
                } catch (ex) {}
            }
            try { document.addEventListener('paste', onPasteEvent); } catch (e2) {}
            var bPaste = document.getElementById('enricher-cover-paste');
            if (bPaste) bPaste.onclick = function () {
                hideEnricherCoverMenu();
                try {
                    // Sin clipboard.read (http remoto/iframe): abrir el selector
                    // de fichero como alternativa inmediata (equivale a pegar
                    // la imagen guardada; viaja en b64 sin pasar por Telegram).
                    if (!navigator.clipboard || !navigator.clipboard.read) {
                        var fAlt = document.getElementById('enricher-cover-file');
                        if (fAlt) {
                            setStatus('Portapapeles directo no disponible: elige la imagen');
                            fAlt.click();
                            return;
                        }
                        setStatus('Portapapeles no disponible: usa Subir o URL', true);
                        return;
                    }
                    navigator.clipboard.read().then(function (items) {
                        var done = false;
                        for (var i = 0; i < (items || []).length && !done; i++) {
                            var types = items[i].types || [];
                            for (var t = 0; t < types.length; t++) {
                                if (types[t].indexOf('image/') === 0) {
                                    done = true;
                                    items[i].getType(types[t]).then(function (blob) {
                                        if (!blob || blob.size > 10 * 1024 * 1024) { setStatus('Imagen mayor de 10MB', true); return; }
                                        var rd = new FileReader();
                                        rd.onload = function () { setCustomPoster(rd.result, rd.result, null); setStatus('Carátula: imagen pegada'); };
                                        rd.readAsDataURL(blob);
                                    }, function () { setStatus('No se pudo leer la imagen', true); });
                                    break;
                                }
                            }
                        }
                        if (!done) setStatus('No hay imagen en el portapapeles', true);
                    }, function () { setStatus('Permiso denegado: usa Subir o URL', true); });
                } catch (e) { setStatus('Portapapeles no disponible: usa Subir o URL', true); }
            };
            var bUp = document.getElementById('enricher-cover-upload');
            var fUp = document.getElementById('enricher-cover-file');
            if (bUp && fUp) {
                bUp.onclick = function () { hideEnricherCoverMenu(); fUp.click(); };
                fUp.onchange = function () {
                    var f = fUp.files && fUp.files[0];
                    if (!f) return;
                    if (f.size > 10 * 1024 * 1024) { setStatus('Imagen mayor de 10MB', true); return; }
                    var rd = new FileReader();
                    rd.onload = function () { setCustomPoster(rd.result, rd.result, null); setStatus('Carátula: imagen subida'); };
                    rd.readAsDataURL(f);
                };
            }
            // Tira inicial (cover ya enriquecido con varias carátulas)
            try { renderPosterStrip(); } catch (e) {}
            // Combo "Traer versión": filtra las Obtenidas por idioma (persistente)
            try {
                var langSel = document.getElementById('enricher-poster-lang');
                if (langSel) {
                    var savedLang = '';
                    try { savedLang = localStorage.getItem('enricher_poster_lang') || ''; } catch (e2) {}
                    if (savedLang) langSel.value = savedLang;
                    langSel.onchange = function () {
                        try { localStorage.setItem('enricher_poster_lang', langSel.value || ''); } catch (e3) {}
                        renderPosterStrip();
                    };
                }
            } catch (e4) {}
        })();

        // Enlaces externos por proveedor configurado (texto pequeño junto a Buscar)
        (function(){
            var box = document.getElementById('enricher-extlinks');
            var qEl = document.getElementById('enricher-query');
            if (!box) return;
            function renderLinks(providers) {
                var q = qEl ? qEl.value.trim() : '';
                var links = [];
                for (var i = 0; i < providers.length; i++) {
                    var p = providers[i];
                    if (!p.configured || !p.search_url) continue;
                    var url = p.search_url.split('{q}').join(encodeURIComponent(q));
                    links.push('<a href="' + url.replace(/"/g, '&quot;') + '" target="_blank" rel="noopener" style="color:#67e8f9;font-size:0.68rem;text-decoration:underline;white-space:nowrap;">' + String(p.label || p.name).replace(/</g, '&lt;') + '</a>');
                }
                box.innerHTML = links.length ? ('buscar en: ' + links.join(' · ')) : '';
            }
            fetch('/api/enricher/providers').then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
                if (!j || !j.providers) return;
                renderLinks(j.providers);
                if (qEl) {
                    var t = null;
                    qEl.addEventListener('input', function () {
                        if (t) clearTimeout(t);
                        t = setTimeout(function () { renderLinks(j.providers); }, 400);
                    });
                }
            }).catch(function(){});
        })();

        // Customs del servidor (motor unificado CORE): espejo JS de
        // services/enrich_tags.resolve. visited-set anticiclos, vacío
        // contagioso, \n explícitos, tagtitle solo con título.
        window._customTagsCache = window._customTagsCache || null;
        window.fetchCustomTags = function(cb) {
            if (window._customTagsCache) { if (cb) cb(window._customTagsCache); return; }
            window.refreshCustomTags(cb);
        };
        window.refreshCustomTags = function(cb) {
            fetch('/api/enricher/custom-tags').then(function(r){ return r.json(); }).then(function(d){
                window._customTagsCache = (d && d.custom) || {};
                if (cb) cb(window._customTagsCache);
            }).catch(function(){ if (cb) cb(window._customTagsCache || {}); });
        };
        window.resolveCustomText = function(text, base) {
            var customs = window._customTagsCache || {};
            base = base || {};
            var hasTitle = (String(text || '').indexOf('{title}') !== -1) || (String(text || '').indexOf('{ftitle}') !== -1);
            function tokenVal(token, visited) {
                if (visited.indexOf(token) !== -1) return '';
                // Tags media (_*): NO se resuelven en el enriquecedor (solo en
                // la subida del fichero); se dejan literales para la copia.
                if (token.charAt(0) === '_') return '{' + token + '}';
                if (token === 'tagtitle' && !hasTitle) return '';
                if (customs.hasOwnProperty(token)) {
                    var r = expandBody(customs[token] || '', visited.concat([token]));
                    return r.ok ? r.text : '';
                }
                if (base.hasOwnProperty(token)) return base[token] || '';
                return '{' + token + '}';
            }
            function expandBody(body, visited) {
                var ok = true;
                var out = String(body || '').replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, function(m0, token) {
                    if (token.charAt(0) === '_') return m0;
                    if (customs.hasOwnProperty(token) || base.hasOwnProperty(token) || token === 'tagtitle') {
                        var r = tokenVal(token, visited);
                        if (r === '') ok = false;
                        return r;
                    }
                    return m0;
                });
                return { text: out, ok: ok };
            }
            var result = String(text || '').replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, function(m0, token) {
                if (token.charAt(0) === '_') return m0;
                if (customs.hasOwnProperty(token)) {
                    var r = expandBody(customs[token] || '', [token]);
                    return r.ok ? r.text : '';
                }
                if (base.hasOwnProperty(token) || token === 'tagtitle') return tokenVal(token, []);
                return m0;
            });
            return result.replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '').replace(/\s+$/, '');
        };
        window.fetchCustomTags(function(){});
        // Tags picker + auto-expansión al cerrar }
        (function(){
            function jv(v){ if(!v) return ''; if(Array.isArray(v)) return v.join(', '); if(typeof v==='string'){ try{ var a=JSON.parse(v); if(Array.isArray(a)) return a.join(', '); }catch(e){} } return String(v); }
            function getTagMap(){
                var d = selectedDetails || {};
                var orig = original.description || '';
                // rorder: valor original del cover si existe, sino season_number de la variante
                var rorderVal = original.rorder || (original.season_number ? String(original.season_number) : '');
                // tagtitle es sanitizado como en TGHirayi
                var tagtitleVal = (d.api_title || '').toString().trim().replace(/\s+/g, ' ');
                var m = {
                    'tagtitle': tagtitleVal,
                    'title': d.api_title || '',
                    'title_en': d.api_title_en || '',
                    'original_title': d.api_original_title || '',
                    'titulo_original': d.api_original_title || '',
                    'title_es': d.api_title_es || '',
                    'titulo_espana': d.api_title_es || '',
                    'title_latam': d.api_title_latam || '',
                    'title_mx': d.api_title_latam || '',
                    'titulo_latino': d.api_title_latam || '',
                    'alt_titles': jv(d.api_alt_titles),
                    'titulos_alt': jv(d.api_alt_titles),
                    'cast': jv(d.api_cast),
                    'reparto': jv(d.api_cast),
                    'actores': jv(d.api_cast),
                    'actors': jv(d.api_cast),
                    'year': d.api_year || '',
                    'release_year': d.api_year || '',
                    'rating': d.api_rating ? ('★ ' + d.api_rating) : '',
                    'rating_count': d.api_rating_count ? String(d.api_rating_count) : '',
                    'genres': jv(d.api_genres),
                    'generos': jv(d.api_genres),
                    'themes': jv(d.api_themes),
                    'temas': jv(d.api_themes),
                    'author': d.api_author || '',
                    'autor': d.api_author || '',
                    'director': d.api_director || d.api_author || '',
                    'directores': d.api_director || d.api_author || '',
                    'release_date': d.api_release_date || '',
                    'fecha': d.api_release_date || '',
                    'category': d.api_category || category || '',
                    'categoria': d.api_category || category || '',
                    'id': d.api_id || '',
                    'cover': jv(d.api_cover),
                    'episodes': (function(){ try { if (itemData && itemData.episodes && itemData.episodes.length) return String(itemData.episodes.length); } catch (e) { } return ''; })(),
                    'season': (d.api_season_number !== undefined && d.api_season_number !== null && String(d.api_season_number) !== '') ? String(d.api_season_number) : ((d.api_seasons !== undefined && d.api_seasons !== null && String(d.api_seasons) !== '') ? String(d.api_seasons) : ''),
                    'temporada': (d.api_season_number !== undefined && d.api_season_number !== null && String(d.api_season_number) !== '') ? String(d.api_season_number) : ((d.api_seasons !== undefined && d.api_seasons !== null && String(d.api_seasons) !== '') ? String(d.api_seasons) : ''),
                    'season_episodes': (d.api_season_episodes !== undefined && d.api_season_episodes !== null && String(d.api_season_episodes) !== '') ? String(d.api_season_episodes) : '',
                    'ext': '',
                    'extension': '',
                    'description': d.api_description || '',
                    'sinopsis': d.api_description || '',
                    'overview': d.api_description || '',
                    'originalmsg': orig || '',
                    'rorder': rorderVal,
                    'roder': rorderVal
                };
                var fm = {};
                (function(){
                    var cc = _customTagsCache || {};
                    for (var cname in cc) {
                        if (!cc.hasOwnProperty(cname)) continue;
                        fm[cname] = resolveCustomText('{' + cname + '}', m);
                    }
                })();
                for (var kk in fm) m[kk] = fm[kk];
                // foreignname: especial, sin ftag (después del merge fm).
                m['foreignname'] = foreignNameValue(d.api_title, d.api_original_title, d);
                m['foreignnameseason'] = (function(){
                    var n = d.api_season_number;
                    if (n === undefined || n === null || String(n) === '') n = d.api_seasons;
                    n = String(n === undefined || n === null ? '' : n).trim();
                    return foreignNameValue(d.api_title, d.api_original_title, d, n ? (' - Season ' + n) : '');
                })();
                return m;
            }
            var captionEl = document.getElementById('enricher-text');
            var tagsBtn = document.getElementById('enricher-tags-btn');
            var tagsModal = document.getElementById('enricher-tags-modal');
            var tagsTable = document.getElementById('enricher-tags-table');
            var tagsClose = document.getElementById('enricher-tags-close');
            if (tagsBtn && tagsModal && tagsTable) {
                tagsBtn.onclick = function(){
                    window.fetchCustomTags(function(){
                    var map = getTagMap();
                    var rows = '';
                    var keys = Object.keys(map).sort();
                    for (var i=0;i<keys.length;i++){
                        var k = keys[i];
                        var v = String(map[k]||'').replace(/\n/g,' ').trim();
                        var vEsc = v.replace(/</g,'&lt;').replace(/>/g,'&gt;');
                        if (v.length>80) vEsc = vEsc.substring(0,80) + '…';
                        var tagLabel = '{' + k + '}';
                        rows += '<div style="display:flex;gap:8px;padding:6px 8px;border-bottom:1px solid #27272a;cursor:pointer;align-items:center;" data-tag="' + tagLabel.replace(/"/g,'&quot;') + '" data-value="' + v.replace(/"/g,'&quot;').replace(/\n/g,' ') + '"><span style="font-family:monospace;font-size:0.75rem;color:var(--accent);min-width:120px;flex-shrink:0;">' + tagLabel + '</span><span style="font-size:0.75rem;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;">' + (vEsc || '<span style=\"color:#71717a;font-style:italic;\">vacío</span>') + '</span></div>';
                    }
                    tagsTable.innerHTML = rows || '<div style="padding:12px;text-align:center;color:var(--text-secondary);font-size:0.8rem;">Sin datos (busca un título primero)</div>';
                    // Click en fila inserta el valor (si tiene) o el tag
                    var rowEls = tagsTable.querySelectorAll('div[data-tag]');
                    for (var r=0;r<rowEls.length;r++) (function(el){
                        el.onclick = function(){
                            var tag = el.getAttribute('data-tag');
                            var val = el.getAttribute('data-value') || '';
                            var toInsert = (val && String(val).trim() !== '') ? val : tag;
                            tagsModal.style.display='none';
                            if (!captionEl) return;
                            var start = captionEl.selectionStart || 0, end = captionEl.selectionEnd || 0;
                            var txt = captionEl.value;
                            captionEl.value = txt.substring(0, start) + toInsert + txt.substring(end);
                            captionEl.focus();
                            captionEl.selectionStart = captionEl.selectionEnd = start + toInsert.length;
                        };
                    })(rowEls[r]);
                    tagsModal.style.display='flex';
                    });
                };
                if (tagsClose) tagsClose.onclick = function(){ tagsModal.style.display='none'; };
                tagsModal.onclick = function(e){ if(e.target===tagsModal) tagsModal.style.display='none'; };
            }
            // Auto-expansión al cerrar } en el caption
            if (captionEl) {
                captionEl.addEventListener('input', function(e){
                    var val = captionEl.value;
                    var pos = captionEl.selectionStart;
                    if (!pos || val[pos-1] !== '}') return;
                    // Buscar el { más cercano hacia atrás
                    var start = val.lastIndexOf('{', pos-1);
                    if (start === -1) return;
                    var tag = val.substring(start, pos); // incluye { y }
                    // Validar formato {xxx} sin espacios internos excesivos ni saltos
                    if (!/^\{[a-zA-Z0-9_]+\}$/.test(tag)) return;
                    var map2 = getTagMap();
                    var key = tag.slice(1,-1); // sin llaves
                    var resolved = map2[key];
                    if (resolved === undefined || resolved === null || String(resolved).trim() === '') return; // sin dato, dejar tag
                    var before = val.substring(0, start);
                    var after = val.substring(pos);
                    captionEl.value = before + resolved + after;
                    var newPos = start + String(resolved).length;
                    captionEl.selectionStart = captionEl.selectionEnd = newPos;
                });
            }
        })();

        // Poblar combo de plantillas y auto-seleccionar la mas parecida a cat/sub
        (function(){
            var sel = document.getElementById('enricher-tpl-select');
            if (!sel) return;
            function sanitize(s){ var v=String(s||'').trim(); if(v==='*') return '*'; return v.toLowerCase().replace(/[^a-z0-9]/g,'').trim(); }
            function splitCats(s){ return String(s||'').split(';').map(function(x){ return x.trim(); }).filter(function(x){ return x; }); }
            function pickBest(tpls, cat, sub){
                var catN = sanitize(cat), subN = sanitize(sub);
                // Nuevo formato: templates[] con categories/subcategories
                if (Array.isArray(tpls.templates) && tpls.templates.length) {
                    for (var i=0;i<tpls.templates.length;i++){
                        var t = tpls.templates[i]||{};
                        var tcats = splitCats(t.categories||'').map(sanitize);
                        var tsubs = splitCats(t.subcategories||'').map(sanitize);
                        if (tcats.indexOf(catN)!==-1 || tsubs.indexOf(subN)!==-1 || tcats.indexOf('*')!==-1 || tsubs.indexOf('*')!==-1) {
                            // coincidencia en alguna lista
                            if (tcats.length===0 && tsubs.length===0) continue; // genérica vacía al final
                            return 'tpl_' + i;
                        }
                    }
                    // genérica vacía como último recurso
                    for (var j=0;j<tpls.templates.length;j++){
                        var tj = tpls.templates[j]||{};
                        if (!String(tj.categories||'').trim() && !String(tj.subcategories||'').trim() && tj.content) return 'tpl_' + j;
                    }
                }
                // Compat: formato antiguo categories { "cat|sub": "..." }
                var cats = tpls.categories || {};
                var keys = Object.keys(cats);
                var k1 = catN + '|' + subN;
                var k1raw = (cat||'').trim().toLowerCase() + '|' + (sub||'').trim().toLowerCase();
                for (var a=0;a<keys.length;a++) if (keys[a].toLowerCase()===k1raw || sanitize(keys[a])===sanitize(k1)) return keys[a];
                for (var b=0;b<keys.length;b++) if (sanitize(keys[b])===catN || keys[b].toLowerCase()===(cat||'').trim().toLowerCase()) return keys[b];
                for (var c=0;c<keys.length;c++) if (sanitize(keys[c])===subN) return keys[c];
                return '__fallback__';
            }
            fetch('/api/enricher/templates').then(function(r){ return r.json(); }).then(function(tpls){
                if (!tpls) throw new Error('no templates');
                sel.innerHTML = '';
                var optF = document.createElement('option'); optF.value='__fallback__'; optF.textContent='Default (fallback)'; optF.setAttribute('data-tpl', tpls.fallback||''); sel.appendChild(optF);
                if (Array.isArray(tpls.templates) && tpls.templates.length) {
                    for (var i=0;i<tpls.templates.length;i++){
                        var t = tpls.templates[i]||{};
                        var o=document.createElement('option'); o.value='tpl_' + i; o.textContent=t.name||('Plantilla '+(i+1)); o.setAttribute('data-tpl', t.content||''); sel.appendChild(o);
                    }
                } else {
                    var cats = tpls.categories || {};
                    for (var k in cats){ var o2=document.createElement('option'); o2.value=k; o2.textContent=k; o2.setAttribute('data-tpl', cats[k]||''); sel.appendChild(o2); }
                }
                var best = pickBest(tpls, category, subcategory);
                sel.value = best;
                // Sincronizar campo raw con la plantilla seleccionada
                var rawEl = document.getElementById('enricher-tpl-raw');
                if (rawEl) {
                    var bestOpt = sel.options[sel.selectedIndex];
                    rawEl.value = bestOpt ? (bestOpt.getAttribute('data-tpl') || '') : (tpls.fallback||'');
                }
                // localOnly: respetar la plantilla guardada del job (no la primera del combo).
                if (opts.localOnly && initialText) {
                    try {
                        rawEl.value = initialText;
                        var _matched = false;
                        for (var _oi = 0; _oi < sel.options.length; _oi++) {
                            if ((sel.options[_oi].getAttribute('data-tpl') || '') === initialText) { sel.value = sel.options[_oi].value; _matched = true; break; }
                        }
                        if (!_matched) {
                            var _oc = document.createElement('option'); _oc.value = '__job__'; _oc.textContent = 'Del job'; _oc.setAttribute('data-tpl', initialText);
                            sel.insertBefore(_oc, sel.firstChild); sel.value = '__job__';
                        }
                    } catch (_eTj) {}
                }
                sel.onchange = function(){
                    var curTpl = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].getAttribute('data-tpl') : '';
                    var rawEl2 = document.getElementById('enricher-tpl-raw');
                    if (rawEl2) rawEl2.value = curTpl;
                };
                // Si el usuario edita el raw, actualizar el option (no auto-aplicar, espera a Aplicar)
                if (rawEl) {
                    rawEl.addEventListener('input', function(){
                        var curOpt = sel.options[sel.selectedIndex];
                        if (curOpt) curOpt.setAttribute('data-tpl', rawEl.value);
                    });
                }
                // Botón Aplicar: renderiza la plantilla seleccionada con la fuente activa
                var applyTplBtn = document.getElementById('enricher-tpl-apply');
                if (applyTplBtn) {
                    applyTplBtn.onclick = function(){
                        if (!selectedDetails) { setStatus('Selecciona un título de la lista primero', true); return; }
                        var curTpl2 = rawEl ? rawEl.value : (sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].getAttribute('data-tpl') : '');
                        var rendered = renderTpl(selectedDetails, category, subcategory, original.description||'', curTpl2);
                        document.getElementById('enricher-text').value = rendered;
                        updateTopicName();
                        // Tags {AI:...}: se resuelven en servidor (con {title} etc.
                        // ya sustituidos por el contexto del detalle activo).
                        if (rendered.indexOf('{AI:') !== -1) {
                            setStatus('Resolviendo IA…');
                            resolveAiTags(rendered, selectedDetails);
                        } else {
                            setStatus('Plantilla aplicada · edita el caption si quieres');
                        }
                    };
                }
            }).catch(function(){
                sel.innerHTML = '<option value="__fallback__">Default (fallback)</option>';
            });
        })();

        // ─── Resolución de {AI:...} vía servicio central ───
        function aiContextFromDetails(d) {
            if (!d) return {};
            function jv(v) {
                if (!v) return '';
                if (Array.isArray(v)) return v.join(', ');
                if (typeof v === 'string') {
                    try { var arr = JSON.parse(v); if (Array.isArray(arr)) return arr.join(', '); } catch (e) { }
                }
                return String(v);
            }
            return {
                Title: d.api_title || '', title: d.api_title || '',
                Year: String(d.api_year || ''), year: String(d.api_year || ''),
                Description: d.api_description || '', description: d.api_description || '',
                Sinopsis: d.api_description || '', sinopsis: d.api_description || '',
                Genres: jv(d.api_genres), genres: jv(d.api_genres),
                Director: d.api_director || d.api_author || '', director: d.api_director || d.api_author || '',
                Cast: jv(d.api_cast), cast: jv(d.api_cast),
                Original_Title: d.api_original_title || ''
            };
        }
        function resolveAiTags(rendered, details) {
            apiFetch('/api/ai/resolve-tags', {
                text: rendered,
                context: aiContextFromDetails(details)
            }, function(res) {
                if (!res) { setStatus('IA sin respuesta (¿proveedores configurados?)', true); return; }
                var box = document.getElementById('enricher-text');
                if (box && typeof res.text === 'string') box.value = res.text;
                if (res.resolved) setStatus('Plantilla aplicada · IA resolvió ' + res.resolved + ' tag(s)');
                else if (res.errors && res.errors.length) setStatus('IA falló: ' + (res.errors[0].error || 'error'), true);
                else setStatus('Plantilla aplicada · edita el caption si quieres');
            });
        }

        function setStatus(msg, isErr) {
            var el = document.getElementById('enricher-status');
            if (el) { el.textContent = msg; el.style.color = isErr ? '#f87171' : '#a1a1aa'; }
        }

        function renderTpl(details, cat, sub, originalMsg, forcedTpl) {
            var sel = document.getElementById('enricher-tpl-select');
            var tpl = forcedTpl;
            if (tpl === undefined) tpl = (sel && sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].getAttribute('data-tpl') : null);
            if (!tpl) tpl = '{title} ({year})\n{rating}\n{genres}\n{description}';
            try { if (details && details._template && !forcedTpl && !(sel && sel.value)) tpl = details._template; } catch (e) { }
            function jv(v) {
                if (!v) return '';
                if (Array.isArray(v)) return v.join(', ');
                if (typeof v === 'string') {
                    try { var arr = JSON.parse(v); if (Array.isArray(arr)) return arr.join(', '); } catch (e) { }
                }
                return String(v);
            }
            var year = String(details.api_year || '');
            var desc = details.api_description || '';
            var epCount = '';
            try { if (itemData && itemData.episodes && itemData.episodes.length) epCount = String(itemData.episodes.length); } catch (e) { }
            // localOnly (cola): la cola pasa los episodios EN SCOPE del job.
            try { if (!epCount && opts.epCount) epCount = String(opts.epCount); } catch (e2) { }
            var map = {
                '{title}': details.api_title || '',
                '{title_en}': details.api_title_en || '',
                '{foreignname}': foreignNameValue(details.api_title, details.api_original_title, details),
                '{foreignnameseason}': (function(){
                    var n = details.api_season_number;
                    if (n === undefined || n === null || String(n) === '') n = details.api_seasons;
                    n = String(n === undefined || n === null ? '' : n).trim();
                    return foreignNameValue(details.api_title, details.api_original_title, details, n ? (' - Season ' + n) : '');
                })(),
                '{original_title}': details.api_original_title || '',
                '{titulo_original}': details.api_original_title || '',
                '{title_es}': details.api_title_es || '',
                '{titulo_espana}': details.api_title_es || '',
                '{title_latam}': details.api_title_latam || '',
                '{title_mx}': details.api_title_latam || '',
                '{titulo_latino}': details.api_title_latam || '',
                '{alt_titles}': jv(details.api_alt_titles),
                '{titulos_alt}': jv(details.api_alt_titles),
                '{cast}': jv(details.api_cast),
                '{reparto}': jv(details.api_cast),
                '{actores}': jv(details.api_cast),
                '{actors}': jv(details.api_cast),
                '{release_year}': year,
                '{year}': year,
                '{description}': desc,
                '{sinopsis}': desc,
                '{overview}': desc,
                '{rating}': details.api_rating ? ('★ ' + details.api_rating) : '',
                '{rating_count}': details.api_rating_count ? String(details.api_rating_count) : '',
                '{genres}': jv(details.api_genres),
                '{generos}': jv(details.api_genres),
                '{themes}': jv(details.api_themes),
                '{temas}': jv(details.api_themes),
                '{author}': details.api_author || '',
                '{autor}': details.api_author || '',
                '{director}': details.api_director || details.api_author || '',
                '{directores}': details.api_director || details.api_author || '',
                '{release_date}': details.api_release_date || '',
                '{fecha}': details.api_release_date || '',
                '{category}': details.api_category || '',
                '{categoria}': details.api_category || '',
                '{id}': details.api_id || '',
                '{cover}': jv(details.api_cover),
                '{episodes}': epCount,
                '{season}': (details.api_season_number !== undefined && details.api_season_number !== null && String(details.api_season_number) !== '') ? String(details.api_season_number) : ((details.api_seasons !== undefined && details.api_seasons !== null && String(details.api_seasons) !== '') ? String(details.api_seasons) : ''),
                '{temporada}': (details.api_season_number !== undefined && details.api_season_number !== null && String(details.api_season_number) !== '') ? String(details.api_season_number) : ((details.api_seasons !== undefined && details.api_seasons !== null && String(details.api_seasons) !== '') ? String(details.api_seasons) : ''),
                '{season_episodes}': (details.api_season_episodes !== undefined && details.api_season_episodes !== null && String(details.api_season_episodes) !== '') ? String(details.api_season_episodes) : '',
                '{originalmsg}': originalMsg || '',
            };
            // Customs del servidor (window.resolveCustomText); sin FTAGS locales.
            var plainBase = {};
            Object.keys(map).forEach(function(k){
                var nk = k.replace(/^\{|\}$/g, '');
                plainBase[nk] = map[k];
            });
            plainBase['tagtitle'] = (details.api_title || '').toString().trim().replace(/\s+/g, ' ');
            return window.resolveCustomText(tpl, plainBase);
        }

        function fetchPosterAsB64(posterUrl, cb) {
            if (!posterUrl) { cb(null, null); return; }
            fetch(posterUrl)
                .then(function (r) { return r.blob(); })
                .then(function (b) {
                    if (!b || !b.size) { cb(null, null); return; }
                    var reader = new FileReader();
                    reader.onloadend = function () {
                        // reader.result = data:image/jpeg;base64,...
                        cb(reader.result, b.type);
                    };
                    reader.readAsDataURL(b);
                })
                .catch(function () { cb(null, null); });
        }

        function usePosterUrl(posterUrl) {
            // Carátula activa: preview + b64 en segundo plano + URL para el servidor
            selectedPosterUrl = posterUrl || null;
            var chkPrev = document.getElementById('enricher-use-poster');
            if (chkPrev && !chkPrev.checked) chkPrev.checked = true;
            if (posterUrl) {
                document.getElementById('enricher-img').src = posterUrl;
                document.getElementById('enricher-img').style.display = 'block';
                var phPrev = document.getElementById('enricher-img-placeholder');
                if (phPrev) phPrev.style.display = 'none';
                fetchPosterAsB64(posterUrl, function (b64) {
                    if (b64) {
                        document.getElementById('enricher-poster-b64').value = b64;
                    }
                });
            }
        }

        function posterList(det) {
            var l = det && det.api_cover;
            if (typeof l === 'string') { try { l = JSON.parse(l); } catch (e) { l = l ? [l] : []; } }
            if (!Array.isArray(l)) l = l ? [l] : [];
            return l.filter(function (u) { return !!u; });
        }

        function posterLang() {
            var sel = document.getElementById('enricher-poster-lang');
            return sel ? (sel.value || '') : '';
        }

        function posterAllList(det) {
            var l = det && det.api_covers_all;
            if (typeof l === 'string') { try { l = JSON.parse(l); } catch (e) { l = []; } }
            if (Array.isArray(l) && l.length) {
                return l.filter(function (p) { return p && p.url; });
            }
            // Sin lista con idioma: las de api_cover como neutras
            return posterList(det).map(function (u) { return { url: u, lang: '' }; });
        }

        function posterLangMatch(p, code) {
            if (!code) return true;
            var pl = String((p && p.lang) || '').toLowerCase();
            return !pl || pl === String(code).toLowerCase();
        }

        function renderPosterStrip() {
            // Solo rellena las entradas Obtenida N del menú (con miniatura),
            // filtradas por "Traer versión". Sin tira visible: descuadraba el diseño.
            var obt = document.getElementById('enricher-cover-obt');
            if (!obt) return;
            var code = posterLang();
            var list = posterAllList(selectedDetails).filter(function (p) { return posterLangMatch(p, code); });
            if (list.length > 1) {
                var mh = '';
                for (var j = 0; j < list.length; j++) {
                    mh += '<button data-obt-url="' + String(list[j].url).replace(/"/g, '&quot;') + '" style="display:flex;align-items:center;gap:8px;width:100%;padding:6px 8px;font-size:0.8rem;margin:2px 0;text-align:left;background:#27272a;border:1px solid #3f3f46;color:#f4f4f5;border-radius:6px;cursor:pointer;">' +
                        '<img src="' + String(list[j].url).replace(/"/g, '&quot;') + '" style="width:24px;height:36px;object-fit:cover;border-radius:3px;flex-shrink:0;">' +
                        '<span>Obtenida ' + (j + 1) + '</span></button>';
                }
                obt.innerHTML = mh;
                obt.style.display = 'block';
                var mels = obt.querySelectorAll('button[data-obt-url]');
                Array.prototype.forEach.call(mels, function (mel) {
                    mel.onclick = function () { hideEnricherCoverMenu(); usePosterUrl(mel.getAttribute('data-obt-url')); };
                });
            } else {
                obt.innerHTML = '';
                obt.style.display = 'none';
            }
        }

        function hideEnricherCoverMenu() {
            var m = document.getElementById('enricher-cover-menu');
            if (m) m.style.display = 'none';
        }

        // Nombre final del topic desde el caption (misma prioridad que el
        // servidor: Original title → Title + Year). Sin tags aún, del detalle.
        function currentTopicName() {
            try {
                var cap = (document.getElementById('enricher-text') || {}).value || '';
                var name = titleFromCaption(cap);
                if (!name && selectedDetails) {
                    var t = selectedDetails.api_original_title || selectedDetails.api_title || '';
                    var m = String(selectedDetails.api_year || '').match(/(\d{4})/);
                    if (t) name = t + (m ? ('🗓' + m[1]) : '');
                }
                return name || '';
            } catch (e) { return ''; }
        }
        function updateTopicName() { /* display eliminado: el badge Title copia directo */ }
        // Nombre del topic con temporada: "Título - Season X🗓AAAA" (o como Title si no hay).
        function currentTopicSeasonName() {
            try {
                var base = currentTopicName();
                if (!base) return '';
                var n = null;
                try {
                    var d = selectedDetails || {};
                    if (d.api_season_number !== undefined && d.api_season_number !== null && String(d.api_season_number) !== '') n = String(d.api_season_number);
                } catch (e) {}
                if (n === null) return base;
                var cal = base.indexOf('🗓');
                if (cal !== -1) return base.substring(0, cal) + ' - Season ' + n + base.substring(cal);
                return base + ' - Season ' + n;
            } catch (e) { return ''; }
        }
        // Sugerencia de título del job (solo localOnly): Original + año desde los datos.
        var jobTitleDirty = false;
        function suggestedJobTitle(det) {
            try {
                det = det || {};
                var t = det.api_original_title || det.api_title || '';
                if (!t) return '';
                var y = '';
                var m = String(det.api_year || '').match(/(\d{4})/);
                if (m) y = m[1];
                return y ? (t + '🗓' + y) : t;
            } catch (e) { return ''; }
        }
        // foreignname: si hay caracteres CJK / hangul / cirílico / devanagari /
        // tailandés / árabe, expande a 2 líneas (Title + Original Title);
        // si no, solo "Original Title:". Sin ftag.
        function hasSpecialChars(s) {
            return /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af\u0400-\u04ff\u0900-\u097f\u0e00-\u0e7f\u0600-\u06ff]/.test(String(s || ''));
        }
            function foreignNameValue(apiTitle, apiOriginal, det, seasonSuffix) {
                det = det || {};
                seasonSuffix = seasonSuffix || '';
                function latin(s) {
                s = (s || '').toString();
                return (s && !hasSpecialChars(s)) ? s : '';
            }
            var disp = (apiTitle || '').toString();
            var orig = (apiOriginal || '').toString();
            var special = hasSpecialChars(orig) ? orig : (hasSpecialChars(disp) ? disp : '');
            if (special) {
                // Title legible: inglés → español → cualquiera latino → original.
                var cands = [det.api_title_en, det.api_title_es, disp,
                             det.api_title_latam, det.api_title_mx, det.api_title_latino];
                try {
                    var al = det.api_alt_titles;
                    if (typeof al === 'string') { try { al = JSON.parse(al); } catch (e) { al = []; } }
                    if (al && al.length !== undefined) {
                        for (var i = 0; i < al.length; i++) cands.push(al[i]);
                    }
                } catch (e2) {}
                cands.push(orig);
                var t = '';
                for (var j = 0; j < cands.length; j++) {
                    var v = latin(cands[j]);
                    if (v) { t = v; break; }
                }
                    return 'Title: ' + (t ? (t + seasonSuffix) : special) + '\nOriginal Title: ' + special + '\n';
                }
                var o = orig || disp;
                return o ? ('Original Title: ' + o + seasonSuffix + '\n') : '';
        }
        // Nombre desde el caption guardado: Title primero, luego Original title
        // (misma prioridad que el servidor), + año de Year/Año. Sin tags crudos.
        function titleFromCaption(txt) {
            try {
                var orig = '', disp = '', year = '';
                var lines = String(txt || '').split('\n');
                for (var i = 0; i < lines.length; i++) {
                    var ln = lines[i].replace(/^\s+|\s+$/g, '');
                    if (!ln || ln.length < 2) continue;
                    var mO = ln.match(/^(original\s+title|t[ií]tulo\s+original)\s*[:=\-]?\s*(.+?)\s*$/i);
                    if (mO && !orig) {
                        var vO = mO[2].replace(/^\s+|\s+$/g, '');
                        if (vO.length >= 2 && vO.indexOf('{') === -1 && vO.indexOf('}') === -1) orig = vO.slice(0, 200);
                    }
                    var mD = ln.match(/^(t[ií]tulo|titulo|title|nombre)(?!\s+(?:alt\d*|es(?:pa[ñn]a)?|latam|latin[oa]|mx|m[ée]xico|original)\b)\s*[:=\-]?\s*(.+?)\s*$/i);
                    if (mD && !disp) {
                        var vD = mD[2].replace(/^\s+|\s+$/g, '');
                        if (vD.length >= 2 && vD !== ':' && vD !== '-' && vD.indexOf('{') === -1 && vD.indexOf('}') === -1) disp = vD.slice(0, 200);
                    }
                    if (!year) {
                        var mY = ln.match(/^(?:year|a[ñn]o)\s*[:=\-]?\s*(\d{4})/i);
                        if (mY) year = mY[1];
                    }
                    if ((orig || disp) && year) break;
                }
                var t = disp || orig;
                return t ? (t + (year ? '🗓' + year : '')) : '';
            } catch (e) { return ''; }
        }
        function updateTitleSuggestion() {
            if (!opts.localOnly) return;
            try {
                var box = document.getElementById('enricher-title-sugg');
                var v = document.getElementById('enricher-title-sugg-v');
                var inp = document.getElementById('enricher-job-title');
                if (!box || !v) return;
                var s = suggestedJobTitle(selectedDetails);
                var cur = inp ? inp.value : '';
                if (s && s !== cur) {
                    v.textContent = s;
                    box.style.display = 'block';
                } else {
                    box.style.display = 'none';
                }
            } catch (e) {}
        }

        document.getElementById('enricher-search').onclick = function () {
            var q = document.getElementById('enricher-query').value.trim();
            if (!q) { setStatus('Escribe un titulo', true); return; }
            setStatus('Buscando…');
            var box = document.getElementById('enricher-cands');
            box.innerHTML = '<div style="font-size:0.72rem;color:#71717a;">…</div>';
            fetch('/api/enricher/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: q, category: category, subcategory: subcategory, episode_count: episodeCount, provider: selectedProviderTab !== 'auto' ? selectedProviderTab : null })
            })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                var cands = (j && (j.candidates || j.results || j.items)) || (Array.isArray(j) ? j : []);
                selectedSeason = (j && j.season !== undefined && j.season !== null) ? j.season : null;
                if (!cands.length) { box.innerHTML = '<div style="font-size:0.72rem;color:#71717a;">Sin resultados (proveedor: ' + (j.provider || j.source || '?') + ')</div>'; setStatus(''); return; }
                box.innerHTML = cands.slice(0, 10).map(function (c, i) {
                    var t = c.title || c.api_title || c.name || '—';
                    var y = c.year || c.api_year || '';
                    var prov = c.provider || '';
                    var origT = (c.original_title || '').trim();
                    var origHtml = (origT && origT !== t) ? ' · <span title="Título original" style="color:#a1a1aa;">orig: ' + origT.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</span>' : '';
                    var poster = c.poster || (c.api_cover && c.api_cover[0]) || '';
                    return '<div class="enricher-cand" data-idx="' + i + '" data-provider="' + (prov || '') + '" data-cid="' + (c.id || c.api_id || '') + '" data-media-type="' + (c.media_type || '') + '" data-sub-provider="' + (c.sub_provider || '') + '" data-poster="' + (poster || '').replace(/"/g, '&quot;') + '" style="padding:6px 8px;border-radius:6px;cursor:pointer;border:1px solid transparent;display:flex;gap:8px;align-items:center;"><div style="width:16px;height:16px;border-radius:50%;border:1px solid #71717a;flex-shrink:0;display:flex;align-items:center;justify-content:center;"><div class="enricher-cand-dot" style="width:8px;height:8px;border-radius:50%;background:#06b6d4;display:none;"></div></div><div style="width:28px;height:40px;background:#18181b;border-radius:4px;flex-shrink:0;overflow:hidden;">' + (poster ? '<img src="' + poster + '" style="width:100%;height:100%;object-fit:cover;">' : '') + '</div><div style="flex:1;min-width:0;"><div style="font-size:0.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + t + '</div><div style="font-size:0.68rem;color:#71717a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + (y || '') + (prov ? ' · ' + prov : '') + origHtml + '</div></div></div>';
                }).join('');
                if (cands.length > 10) box.innerHTML += '<div style="font-size:0.68rem;color:#71717a;margin-top:4px;">Hay mas (refina la busqueda)</div>';
                setStatus(cands.length + ' candidatos · ' + (j.provider || '') + (selectedSeason !== null ? ' · temporada ' + selectedSeason + ' detectada' : '') + (cands.length===1 ? ' · auto-seleccionado' : ' · selecciona uno como fuente activa'));
                var candEls = box.querySelectorAll('.enricher-cand');
                function setActiveCand(el){
                    for (var a=0;a<candEls.length;a++){ candEls[a].style.borderColor='transparent'; candEls[a].style.background='transparent'; var d=candEls[a].querySelector('.enricher-cand-dot'); if(d) d.style.display='none'; }
                    if (el){ el.style.borderColor='#06b6d4'; el.style.background='rgba(6,182,212,0.12)'; var dot=el.querySelector('.enricher-cand-dot'); if(dot) dot.style.display='block'; }
                }
                Array.prototype.forEach.call(candEls, function (el) {
                    el.onclick = function () {
                        setActiveCand(el);
                        var prov = el.getAttribute('data-provider') || 'tmdb';
                        var cid = el.getAttribute('data-cid');
                        var mt = el.getAttribute('data-media-type') || '';
                        var subp = el.getAttribute('data-sub-provider') || '';
                        var posterUrl = el.getAttribute('data-poster');
                        if (!cid) return;
                        selectedProvider = prov; selectedId = cid;
                        selectedPosterUrl = posterUrl || null;
                        setStatus('Cargando detalle…');
                        fetch('/api/enricher/details', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ provider: prov, id: String(cid), media_type: mt, sub_provider: subp, season: selectedSeason })
                        })
                        .then(function (r) { return r.json(); })
                        .then(function (det) {
                            if (!det || det.error) { setStatus((det && det.error) || 'Sin detalle', true); return; }
                            selectedDetails = det;
                            renderPosterStrip();
                            // Preview inmediato: manda la primera carátula del detalle
                            // (el servidor pone la de la temporada primero); si no hay,
                            // la del candidato. Antes el candidato pisaba a la temporada.
                            var firstCover = null;
                            try {
                                var cl = det.api_cover;
                                if (typeof cl === 'string') { try { cl = JSON.parse(cl); } catch (e) { cl = [cl]; } }
                                if (cl && cl.length) firstCover = cl[0];
                            } catch (e) {}
                            if (firstCover) {
                                usePosterUrl(firstCover);
                            } else if (posterUrl) {
                                usePosterUrl(posterUrl);
                            }
                            updateTitleSuggestion();
                            updateTopicName();
                            setStatus('Fuente activa: ' + (det.api_title || det.title || '—') + ' · pulsa Aplicar para usar la plantilla');
                        })
                        .catch(function () { setStatus('Error al cargar detalle', true); });
                    };
                });
                // Auto-selección si solo hay 1
                if (candEls.length === 1) candEls[0].click();
            })
            .catch(function () { box.innerHTML = ''; setStatus('Error de red', true); });
        };

        // Pestañas de proveedor: override manual (pintar activa + relanzar si hay query).
        (function() {
            var tabs = document.querySelectorAll('#enricher-prov-tabs .enricher-prov-tab');
            function paintTabs() {
                for (var i = 0; i < tabs.length; i++) {
                    var on = tabs[i].getAttribute('data-prov') === selectedProviderTab;
                    tabs[i].style.background = on ? '#06b6d4' : '#27272a';
                    tabs[i].style.color = on ? '#fff' : '#a1a1aa';
                    tabs[i].style.borderColor = on ? '#06b6d4' : '#3f3f46';
                }
            }
            for (var k = 0; k < tabs.length; k++) {
                tabs[k].onclick = function() {
                    selectedProviderTab = this.getAttribute('data-prov') || 'auto';
                    paintTabs();
                };
            }
            paintTabs();
        })();

        document.getElementById('enricher-save-local').onclick = function () {
            doSave(false);
        };
        var applyBtn = document.getElementById('enricher-apply');
        if (applyBtn) applyBtn.onclick = function () { doSave(true); };
        // Modo local (partido TGHirayi): no hay item compartido al que aplicar.
        if (opts.localOnly && applyBtn) applyBtn.style.display = 'none';
        // Sugerido inicial (datos propios del job) + botón usar + dirty tracking.
        if (opts.localOnly) {
            try {
                var _jtInp = document.getElementById('enricher-job-title');
                if (_jtInp) _jtInp.oninput = function () { jobTitleDirty = true; };
                var _useL = document.getElementById('enricher-title-use');
                if (_useL) _useL.onclick = function (e) {
                    try { if (e && e.preventDefault) e.preventDefault(); } catch (_eU) {}
                    try {
                        var s = suggestedJobTitle(selectedDetails);
                        if (s) document.getElementById('enricher-job-title').value = s;
                        jobTitleDirty = true;
                        updateTitleSuggestion();
                    } catch (_eU2) {}
                    return false;
                };
            } catch (_eU3) {}
            updateTitleSuggestion();
        }

        // Vuelve a la hero del mismo título, actualizada (sin recargar la página).
        function backToHero() {
            try { overlay.remove(); } catch (e) {}
            try { if (window.openDetails) window.openDetails(itemId); } catch (e2) {}
            // El H1 prefiere group_title: si el guardado cambió el título, forzarlo
            // desde la respuesta (cinturón para cualquier ruta stale del detalle).
            try {
                var _ft = (window._enricherFreshTitle && window._enricherFreshTitle.id === itemId)
                    ? window._enricherFreshTitle.title : null;
                window._enricherFreshTitle = null;
                if (_ft) {
                    var _tries = 0;
                    var _forceT = setInterval(function() {
                        try {
                            _tries++;
                            var tel = document.getElementById('detail-title');
                            var dmodal = document.getElementById('detail-modal');
                            if (tel && dmodal && dmodal.classList.contains('hidden') === false) {
                                if (tel.textContent !== _ft) tel.textContent = _ft;
                                clearInterval(_forceT);
                            } else if (_tries > 10 || (dmodal && dmodal.classList.contains('hidden'))) {
                                clearInterval(_forceT);
                            }
                        } catch (ee) { clearInterval(_forceT); }
                    }, 300);
                }
            } catch (e3) {}
            // Romper caché del cover en hero y grid (el blob cambió con la misma URL).
            setTimeout(function () {
                try {
                    var v = Date.now();
                    var bg = document.getElementById('detail-backdrop');
                    if (bg) bg.style.backgroundImage = "url('/api/cover/" + encodeURIComponent(itemId) + "?v=" + v + "')";
                    var gridImg = document.querySelector('.grid-item[data-id="' + itemId + '"] img');
                    if (gridImg) gridImg.src = '/api/cover/' + encodeURIComponent(itemId) + '?v=' + v;
                } catch (e3) {}
            }, 1500);
        }

        function doSave(applyTelegram) {
            var text = document.getElementById('enricher-text').value || '';
            var usePoster = document.getElementById('enricher-use-poster');
            var posterB64 = null;
            if (usePoster && usePoster.checked) posterB64 = document.getElementById('enricher-poster-b64').value || null;
            // Si hay candidato seleccionado con poster URL pero no se ha pasado a base64 aún, la imagen del preview ya está
            // pero el payload usa poster_b64; si está vacío y la UI muestra /api/cover original, no mandamos poster (solo caption)
            // Fallback: si preview es data: lo usamos; si es /api/..., ignoramos (no cubrirá la foto, solo el caption)
            var imgEl = document.getElementById('enricher-img');
            if (!posterB64 && imgEl && imgEl.src && imgEl.src.indexOf('data:') === 0) posterB64 = imgEl.src;
            var posterUrl = null;
            if (usePoster && usePoster.checked) posterUrl = selectedPosterUrl;
            // Modo local (partido TGHirayi): sin POST al registry; devolver datos al callback.
            if (opts.localOnly) {
                var _jt = '';
                try { _jt = (document.getElementById('enricher-job-title') || {}).value || ''; } catch (_eJ) {}
                _jt = String(_jt).replace(/^\s+|\s+$/g, '');
                // Título: el manual si se tocó; si no, el derivado del caption
                // (Original title → Title + año). Así Guardar renombra solo.
                if (!jobTitleDirty) {
                    var _autoT = titleFromCaption(text);
                    if (_autoT) _jt = _autoT;
                }
                var _tplRaw = '';
                try { _tplRaw = (document.getElementById('enricher-tpl-raw') || {}).value || ''; } catch (_eT) {}
                var _loc = {
                    cover_text: text,
                    template: _tplRaw,
                    poster_b64: posterB64,
                    poster_url: posterUrl,
                    use_poster: !!(usePoster && usePoster.checked),
                    details: selectedDetails || null,
                    title: _jt
                };
                setStatus('Cover propio listo');
                try { if (typeof opts.onDone === 'function') opts.onDone(_loc); } catch (_eL) {}
                try { overlay.remove(); } catch (_eL2) {}
                return;
            }
            var payload = {
                cover_text: text,
                enrich_details: selectedDetails || enriched && enriched.enrich_details || null,
                poster_b64: posterB64,
                poster_url: posterUrl
            };
            var path = applyTelegram
                ? '/api/enricher/item/' + encodeURIComponent(itemId) + '/apply'
                : '/api/enricher/item/' + encodeURIComponent(itemId) + '/save';
            setStatus(applyTelegram ? 'Aplicando en Telegram…' : 'Guardando…');
            fetch(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
            .then(function (res) {
                if (!res.ok) { setStatus((res.j && (res.j.detail || res.j.error)) || 'Error', true); return; }
                try {
                    // El backend ya propagó el título al catálogo: reflejar título
                    // y cover en el grid en memoria y en el DOM, sin recargar.
                    var _rj = res.j || {};
                    var _nt = (_rj.title_applied && _rj.catalog_title) ? _rj.catalog_title : null;
                    if (_nt) { try { window._enricherFreshTitle = { id: itemId, title: _nt }; } catch (_e0) {} }
                    try {
                        if (window.Catalog && typeof window.Catalog.refreshGridCover === 'function') window.Catalog.refreshGridCover(itemId, _nt);
                        else if (_nt && window.Catalog && window.Catalog.currentItems) {
                            var _items = window.Catalog.currentItems;
                            for (var _k = 0; _k < _items.length; _k++) {
                                if (String(_items[_k].item_id) === String(itemId)) { _items[_k].title = _nt; break; }
                            }
                            var _node = document.querySelector('.grid-item[data-id="' + itemId + '"] .grid-item-title');
                            if (_node) _node.textContent = _nt;
                        }
                    } catch (_e) {}
                } catch (_e) {}
                var _msg = applyTelegram ? 'Aplicado en Telegram y guardado local' : 'Guardado local';
                try {
                    var _rj2 = res.j || {};
                    if (_rj2.title_applied && _rj2.catalog_title) _msg += ' · Título catálogo: ' + _rj2.catalog_title;
                } catch (_e2) {}
                setStatus(_msg);
                try { if (window.Enricher && window.Enricher.refreshLocalEdits) window.Enricher.refreshLocalEdits(); } catch (_eR) {}
                // Llamada externa (p.ej. cola TGHirayi): devolver el resultado al
                // callback en vez de reabrir la hero. El guardado en el registry
                // compartido ya se ha hecho (propaga a catálogo).
                if (opts && typeof opts.onDone === 'function') {
                    var _donePayload = { item_id: itemId, cover_text: text,
                        catalog_title: null, title_applied: false };
                    try {
                        var _rj3 = res.j || {};
                        _donePayload.title_applied = !!_rj3.title_applied;
                        _donePayload.catalog_title = _rj3.catalog_title || null;
                    } catch (_e3) {}
                    try { opts.onDone(_donePayload); } catch (_e4) {}
                    try { overlay.remove(); } catch (_e5) {}
                    setTimeout(function () {
                        try {
                            var _nt2 = null;
                            try {                             var _rjj = res.j || {}; if (_rjj.title_applied && _rjj.catalog_title) _nt2 = _rjj.catalog_title; } catch (_e7) {}
                            if (window.Catalog && typeof window.Catalog.refreshGridCover === 'function') window.Catalog.refreshGridCover(itemId, _nt2);
                        } catch (_e6) {}
                    }, 1500);
                    return;
                }
                setTimeout(backToHero, 900);
            })
            .catch(function () { setStatus('Error de red', true); });
        }

        var revertBtn = document.getElementById('enricher-revert');
        if (revertBtn) revertBtn.onclick = function () {
            if (!confirm('Eliminar el enriquecimiento local de este titulo?')) return;
            fetch('/api/enricher/item/' + encodeURIComponent(itemId), { method: 'DELETE' })
                .then(function (r) { return r.json(); })
                .then(function () { setStatus('Revertido'); try { if (window.Enricher && window.Enricher.refreshLocalEdits) window.Enricher.refreshLocalEdits(); } catch (_eR2) {} setTimeout(backToHero, 600); })
                .catch(function () { setStatus('Error al revertir', true); });
        }
    }

    // API pública: permite abrir el mismo editor desde otras vistas
    // (p.ej. cola TGHirayi). opts.onDone({item_id, cover_text, catalog_title,
    // title_applied}) se llama tras guardar, en vez de reabrir la hero.
    window.Enricher = window.Enricher || {};
    window.Enricher.open = openEnricher;
    // Tras guardar/aplicar/revertir: la sección Ediciones locales puede
    // aparecer, desaparecer o cambiar (el apply borra la fila local).
    window.Enricher.refreshLocalEdits = function () {
        try { if (window.refreshLocalEditsNav) window.refreshLocalEditsNav(); } catch (e) {}
        try {
            if (window.Catalog && window.Catalog.currentCategory === 'local_edits'
                && typeof selectSection === 'function') {
                var cur = document.querySelector('[data-category="local_edits"]');
                setTimeout(function () { selectSection('local_edits', cur); }, 400);
            }
        } catch (e2) {}
    };

    window.pluginSystem.registerPlugin({
        name: 'tvcat_enricher',
        type: 'heropage-action',
        displayName: 'Enriquecedor',
        getHeroButtons: getHeroButtons
    });
})();
