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

    function openEnricher(itemData) {
        try { console.log('[Enricher] open', itemData); } catch(e) {}
        var itemId = itemData.item_id;
        // Fetch estado + authorship en paralelo
        Promise.all([
            fetch('/api/enricher/item/' + encodeURIComponent(itemId)).then(function (r) { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); }).catch(function (e) { try { console.error('[Enricher] /item err', e); } catch(ex) {} return null; }),
            fetch('/api/enricher/item/' + encodeURIComponent(itemId) + '/authorship').then(function (r) { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); }).catch(function (e) { try { console.error('[Enricher] /authorship err', e); } catch(ex) {} return null; })
        ]).then(function (vals) {
            var data = vals[0];
            var auth = vals[1] || { is_mine: false, author_user_id: null, reason: '' };
            if (!data) { alert('No se pudo cargar el item (¿gateway reiniciado?)'); return; }
            buildModal(data, auth, itemData);
        }).catch(function(e){ try { console.error('[Enricher] open err', e); } catch(ex) {} alert('Error: '+e); });
    }

    function buildModal(data, auth, itemData) {
        var itemId = data.item_id;
        var original = data.original || {};
        var enriched = data.enriched || null;
        var hasEnriched = !!enriched;
        var category = original.category || itemData.category || '';
        var subcategory = original.subcategory || itemData.subcategory || '';
        var initialText = hasEnriched ? (enriched.cover_text || '') : (original.description || '');
        var initialDetails = hasEnriched ? (enriched.enrich_details || {}) : null;
        var posterB64 = null; // de la imagen actual o del candidato
        var posterMime = 'image/jpeg';
        var selectedDetails = initialDetails;
        var selectedProvider = null;
        var selectedId = null;
        var selectedPosterUrl = null; // URL del póster del candidato (el servidor la descarga si el b64 falla)

        // Overlay
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;';
        overlay.onclick = function (e) { if (e.target === overlay) overlay.remove(); };
        var panel = document.createElement('div');
        panel.style.cssText = 'background:#0d0d0f;border:1px solid #3f3f46;border-radius:10px;padding:16px;width:92vw;max-width:720px;max-height:94vh;overflow-y:auto;color:#f4f4f5;box-sizing:border-box;';
        panel.onclick = function (e) { e.stopPropagation(); };
        var html = '';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">';
        html += '<div style="font-weight:700;font-size:0.95rem;">✨ Enriquecer cover</div>';
        html += '<button id="enricher-close" style="width:32px;height:32px;border-radius:50%;background:#27272a;border:1px solid #3f3f46;color:#a1a1aa;cursor:pointer;font-size:18px;line-height:1;">×</button>';
        html += '</div>';

        // Badge de estado
        var badge = '';
        if (hasEnriched) badge = '<span style="display:inline-block;padding:2px 8px;background:#22c55e22;color:#4ade80;border-radius:999px;font-size:0.68rem;border:1px solid #14532d;">Enriquecido</span> ';
        if (auth.is_mine) badge += '<span style="display:inline-block;padding:2px 8px;background:#06b6d422;color:#22d3ee;border-radius:999px;font-size:0.68rem;border:1px solid #164e63;">Tuyo — editable en Telegram</span>';
        else badge += '<span style="display:inline-block;padding:2px 8px;background:#f59e0b22;color:#fbbf24;border-radius:999px;font-size:0.68rem;border:1px solid #78350f;">Ajeno — solo local</span>';
        html += '<div style="margin-bottom:10px;">' + badge + '<span style="font-size:0.68rem;color:#71717a;margin-left:6px;">' + (auth.reason || '') + '</span></div>';

        // Imagen + busqueda lado a lado
        html += '<div style="display:flex;gap:12px;margin-bottom:12px;align-items:flex-start;flex-wrap:wrap;">';
        html += '<div style="flex-shrink:0;width:160px;max-width:38%;">';
        if (hasEnriched && data.enriched && data.enriched.poster_blob) {
            // servido desde /api/enricher/item/{id}/cover para preview
            html += '<img id="enricher-img" src="/api/enricher/item/' + encodeURIComponent(itemId) + '/cover?v=' + Date.now() + '" style="width:100%;border-radius:8px;border:1px solid #3f3f46;display:block;max-height:220px;object-fit:cover;">';
        } else {
            html += '<img id="enricher-img" src="/api/cover/' + encodeURIComponent(itemId) + '" style="width:100%;border-radius:8px;border:1px solid #3f3f46;display:block;max-height:220px;object-fit:cover;" onerror="this.style.display=\'none\';document.getElementById(\'enricher-img-placeholder\').style.display=\'flex\';">';
            html += '<div id="enricher-img-placeholder" style="display:none;width:100%;height:140px;border-radius:8px;border:1px dashed #3f3f46;align-items:center;justify-content:center;font-size:0.7rem;color:#71717a;background:#18181b;">sin imagen</div>';
        }
        html += '<label style="display:flex;align-items:center;gap:6px;margin-top:8px;font-size:0.72rem;color:#a1a1aa;cursor:pointer;"><input type="checkbox" id="enricher-use-poster" checked> Usar imagen descargada</label>';
        html += '</div>';
        html += '<div style="flex:1;min-width:260px;">';
        // Busqueda enriquecedor
        html += '<label style="font-size:0.75rem;color:#a1a1aa;">Buscar en enriquecedor</label>';
        html += '<div style="display:flex;gap:6px;margin-top:4px;">';
        var defaultQuery = (original.title || itemData.title || '').trim();
        html += '<input type="text" id="enricher-query" value="' + defaultQuery.replace(/"/g, '&quot;') + '" placeholder="Titulo" style="flex:1;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;">';
        html += '<button id="enricher-search" style="padding:6px 12px;background:#06b6d4;border:none;color:#fff;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:700;">Buscar</button>';
        html += '</div>';
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
        html += '<button id="enricher-tags-btn" style="padding:4px 8px;font-size:0.7rem;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;cursor:pointer;white-space:nowrap;">Tags ▾</button>';
        html += '</div>';
        html += '<div style="font-size:0.68rem;color:#71717a;margin:2px 0 4px;">Escribe {title} y al cerrar } se expande · o usa Tags</div>';
        html += '<textarea id="enricher-text" style="width:100%;height:140px;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;resize:vertical;white-space:pre-wrap;">' + (initialText || '').replace(/</g, '&lt;') + '</textarea>';
        html += '<div id="enricher-tags-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;z-index:1000000;background:rgba(0,0,0,0.7);align-items:center;justify-content:center;"><div style="background:#0d0d0f;border:1px solid #3f3f46;border-radius:8px;padding:12px;width:90vw;max-width:560px;max-height:80vh;overflow:hidden;display:flex;flex-direction:column;"><div style="font-weight:600;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;"><span>Tags</span><button id="enricher-tags-close" style="width:28px;height:28px;border-radius:50%;background:#27272a;border:1px solid #3f3f46;color:#a1a1aa;cursor:pointer;">×</button></div><div id="enricher-tags-table" style="overflow-y:auto;flex:1;border:1px solid #27272a;border-radius:6px;"></div></div></div>';

        // Poster actual (hidden, se sube como base64 en el payload, reutiliza el del candidato si hay)
        html += '<input type="hidden" id="enricher-poster-b64">';
        // Botones
        html += '<div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;">';
        html += '<button id="enricher-save-local" style="flex:1;min-width:120px;padding:9px;background:#3f3f46;border:none;color:#f4f4f5;border-radius:6px;cursor:pointer;font-weight:600;">Guardar local</button>';
        if (auth.is_mine) {
            html += '<button id="enricher-apply" style="flex:1;min-width:150px;padding:9px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:700;">Aplicar en Telegram</button>';
        }
        html += '</div>';
        if (hasEnriched) html += '<button id="enricher-revert" style="width:100%;margin-top:8px;padding:6px;background:transparent;border:1px solid #ef4444;color:#f87171;border-radius:6px;cursor:pointer;font-size:0.8rem;">Revertir enriquecimiento</button>';
        html += '<div id="enricher-status" style="margin-top:8px;font-size:0.75rem;color:#a1a1aa;min-height:1.2em;"></div>';
        panel.innerHTML = html;
        overlay.appendChild(panel);
        document.body.appendChild(overlay);
        document.getElementById('enricher-close').onclick = function () { overlay.remove(); };
        // Toggle preview original vs descargada
        (function(){
            var chk = document.getElementById('enricher-use-poster');
            var img = document.getElementById('enricher-img');
            var ph = document.getElementById('enricher-img-placeholder');
            if (!chk || !img) return;
            var origSrc = '/api/cover/' + encodeURIComponent(itemId) + '?v=' + Date.now();
            var enrichedSrc = hasEnriched && data.enriched && data.enriched.poster_blob ? ('/api/enricher/item/' + encodeURIComponent(itemId) + '/cover?v=' + Date.now()) : null;
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

        // Tags picker + auto-expansión al cerrar }
        (function(){
            function jv(v){ if(!v) return ''; if(Array.isArray(v)) return v.join(', '); if(typeof v==='string'){ try{ var a=JSON.parse(v); if(Array.isArray(a)) return a.join(', '); }catch(e){} } return String(v); }
            function getTagMap(){
                var d = selectedDetails || {};
                var orig = original.description || '';
                // tagtitle es sanitizado como en TGHirayi
                var tagtitleVal = (d.api_title || '').toString().trim().replace(/\s+/g, ' ');
                var m = {
                    'tagtitle': tagtitleVal,
                    'title': d.api_title || '',
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
                    'director': d.api_author || '',
                    'release_date': d.api_release_date || '',
                    'fecha': d.api_release_date || '',
                    'category': d.api_category || category || '',
                    'categoria': d.api_category || category || '',
                    'id': d.api_id || '',
                    'cover': jv(d.api_cover),
                    'episodes': (function(){ try { if (itemData && itemData.episodes && itemData.episodes.length) return String(itemData.episodes.length); } catch (e) { } return ''; })(),
                    'ext': '',
                    'extension': '',
                    'description': d.api_description || '',
                    'sinopsis': d.api_description || '',
                    'overview': d.api_description || '',
                    'originalmsg': orig || ''
                };
                var FTAG_FORMATS = {
                    // ftagtitle no existe, solo ftitle
                    "title": "Title: {value}",
                    "year": "Year: {value}",
                    "release_year": "Year: {value}",
                    "description": "Description:\n{value}",
                    "sinopsis": "Sinopsis:\n{value}",
                    "overview": "Overview:\n{value}",
                    "rating": "Rating: {value}",
                    "rating_count": "Rating count: {value}",
                    "genres": "Genres: {value}",
                    "author": "Author: {value}",
                    "originalmsg": "{value}"
                };
                var fm = {};
                for (var k in m) {
                    if (k === 'tagtitle') continue; // ftagtitle no existe, solo ftitle
                    var fmt = FTAG_FORMATS[k];
                    if (fmt) fm['f' + k] = m[k] ? fmt.replace("{value}", m[k]) : "";
                    else fm['f' + k] = m[k];
                }
                for (var kk in fm) m[kk] = fm[kk];
                return m;
            }
            var captionEl = document.getElementById('enricher-text');
            var tagsBtn = document.getElementById('enricher-tags-btn');
            var tagsModal = document.getElementById('enricher-tags-modal');
            var tagsTable = document.getElementById('enricher-tags-table');
            var tagsClose = document.getElementById('enricher-tags-close');
            if (tagsBtn && tagsModal && tagsTable) {
                tagsBtn.onclick = function(){
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
                        document.getElementById('enricher-text').value = renderTpl(selectedDetails, category, subcategory, original.description||'', curTpl2);
                        setStatus('Plantilla aplicada · edita el caption si quieres');
                    };
                }
            }).catch(function(){
                sel.innerHTML = '<option value="__fallback__">Default (fallback)</option>';
            });
        })();

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
            var map = {
                '{title}': details.api_title || '',
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
                '{director}': details.api_author || '',
                '{release_date}': details.api_release_date || '',
                '{fecha}': details.api_release_date || '',
                '{category}': details.api_category || '',
                '{categoria}': details.api_category || '',
                '{id}': details.api_id || '',
                '{cover}': jv(details.api_cover),
                '{episodes}': epCount,
                '{originalmsg}': originalMsg || '',
            };
            var FTAGS = {
                "title": "Title: {value}",
                "year": "Year: {value}",
                "release_year": "Year: {value}",
                "rating": "Rating: {value}",
                "rating_count": "Rating count: {value}",
                "genres": "Genres: {value}",
                "generos": "Genres: {value}",
                "themes": "Themes: {value}",
                "temas": "Themes: {value}",
                "author": "Author: {value}",
                "autor": "Author: {value}",
                "director": "Director: {value}",
                "release_date": "Release date: {value}",
                "fecha": "Release date: {value}",
                "category": "Category: {value}",
                "categoria": "Category: {value}",
                "id": "ID: {value}",
                "cover": "Cover: {value}",
                "episodes": "Episodes: {value}",
                "ext": "Ext: {value}",
                "extension": "Ext: {value}",
                "description": "Description:\n{value}",
                "sinopsis": "Sinopsis:\n{value}",
                "overview": "Overview:\n{value}",
                "originalmsg": "{value}"
            };
            var out = tpl;
            // Raw tags {title} -> valor crudo (sin formato)
            Object.keys(map).forEach(function (k) {
                var v = map[k];
                if (k === '{tagtitle}') {
                    var has_title = (tpl.indexOf('{title}') !== -1) || (tpl.indexOf('{ftitle}') !== -1);
                    if (!has_title) v = '';
                }
                out = out.split(k).join(v);
            });
            // Formateados {ftitle} -> con plantilla FTAGS (con salto y omisión si vacío)
            for (var fk in FTAGS) {
                var rawKey = '{' + fk + '}';
                var rawVal = map[rawKey] || '';
                var fForm = '{f' + fk + '}';
                if (out.indexOf(fForm) !== -1) {
                    var rendered = rawVal ? FTAGS[fk].replace('{value}', rawVal) : '';
                    out = out.split(fForm).join(rendered ? (rendered + '\n') : '');
                }
            }
            return out.replace(/\n{3,}/g, '\n\n').trim();
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

        document.getElementById('enricher-search').onclick = function () {
            var q = document.getElementById('enricher-query').value.trim();
            if (!q) { setStatus('Escribe un titulo', true); return; }
            setStatus('Buscando…');
            var box = document.getElementById('enricher-cands');
            box.innerHTML = '<div style="font-size:0.72rem;color:#71717a;">…</div>';
            fetch('/api/enricher/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: q, category: category, subcategory: subcategory })
            })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                var cands = (j && (j.candidates || j.results || j.items)) || (Array.isArray(j) ? j : []);
                if (!cands.length) { box.innerHTML = '<div style="font-size:0.72rem;color:#71717a;">Sin resultados (proveedor: ' + (j.provider || j.source || '?') + ')</div>'; setStatus(''); return; }
                box.innerHTML = cands.slice(0, 10).map(function (c, i) {
                    var t = c.title || c.api_title || c.name || '—';
                    var y = c.year || c.api_year || '';
                    var prov = c.provider || '';
                    var poster = c.poster || (c.api_cover && c.api_cover[0]) || '';
                    return '<div class="enricher-cand" data-idx="' + i + '" data-provider="' + (prov || '') + '" data-cid="' + (c.id || c.api_id || '') + '" data-poster="' + (poster || '').replace(/"/g, '&quot;') + '" style="padding:6px 8px;border-radius:6px;cursor:pointer;border:1px solid transparent;display:flex;gap:8px;align-items:center;"><div style="width:16px;height:16px;border-radius:50%;border:1px solid #71717a;flex-shrink:0;display:flex;align-items:center;justify-content:center;"><div class="enricher-cand-dot" style="width:8px;height:8px;border-radius:50%;background:#06b6d4;display:none;"></div></div><div style="width:28px;height:40px;background:#18181b;border-radius:4px;flex-shrink:0;overflow:hidden;">' + (poster ? '<img src="' + poster + '" style="width:100%;height:100%;object-fit:cover;">' : '') + '</div><div style="flex:1;min-width:0;"><div style="font-size:0.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + t + '</div><div style="font-size:0.68rem;color:#71717a;">' + (y || '') + (prov ? ' · ' + prov : '') + '</div></div></div>';
                }).join('');
                if (cands.length > 10) box.innerHTML += '<div style="font-size:0.68rem;color:#71717a;margin-top:4px;">Hay mas (refina la busqueda)</div>';
                setStatus(cands.length + ' candidatos · ' + (j.provider || '') + (cands.length===1 ? ' · auto-seleccionado' : ' · selecciona uno como fuente activa'));
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
                        var posterUrl = el.getAttribute('data-poster');
                        if (!cid) return;
                        selectedProvider = prov; selectedId = cid;
                        selectedPosterUrl = posterUrl || null;
                        setStatus('Cargando detalle…');
                        fetch('/api/enricher/details', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ provider: prov, id: String(cid) })
                        })
                        .then(function (r) { return r.json(); })
                        .then(function (det) {
                            if (!det || det.error) { setStatus((det && det.error) || 'Sin detalle', true); return; }
                            selectedDetails = det;
                            // Preview inmediato con la URL directa (sin esperar base64, evita CORS del fetch)
                            if (posterUrl) {
                                var chkPrev = document.getElementById('enricher-use-poster');
                                if (!chkPrev || chkPrev.checked) {
                                    document.getElementById('enricher-img').src = posterUrl;
                                    document.getElementById('enricher-img').style.display = 'block';
                                    var phPrev = document.getElementById('enricher-img-placeholder');
                                    if (phPrev) phPrev.style.display = 'none';
                                }
                                fetchPosterAsB64(posterUrl, function (b64) {
                                    if (b64) {
                                        document.getElementById('enricher-poster-b64').value = b64;
                                        // Si sigue marcado, asegurar que el preview sea el b64 ya cacheado para el guardado
                                        var chk2b = document.getElementById('enricher-use-poster');
                                        if (chk2b && chk2b.checked) {
                                            // Mantener la URL directa como preview (más rápido), el b64 queda para el POST
                                        }
                                    }
                                });
                            }
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

        document.getElementById('enricher-save-local').onclick = function () {
            doSave(false);
        };
        var applyBtn = document.getElementById('enricher-apply');
        if (applyBtn) applyBtn.onclick = function () { doSave(true); };

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
                setStatus(applyTelegram ? 'Aplicado en Telegram y guardado local' : 'Guardado local');
                setTimeout(function () { overlay.remove(); location.reload(); }, 900);
            })
            .catch(function () { setStatus('Error de red', true); });
        }

        var revertBtn = document.getElementById('enricher-revert');
        if (revertBtn) revertBtn.onclick = function () {
            if (!confirm('Eliminar el enriquecimiento local de este titulo?')) return;
            fetch('/api/enricher/item/' + encodeURIComponent(itemId), { method: 'DELETE' })
                .then(function (r) { return r.json(); })
                .then(function () { setStatus('Revertido'); setTimeout(function () { overlay.remove(); location.reload(); }, 600); })
                .catch(function () { setStatus('Error al revertir', true); });
        }
    }

    window.pluginSystem.registerPlugin({
        name: 'tvcat_enricher',
        type: 'heropage-action',
        displayName: 'Enriquecedor',
        getHeroButtons: getHeroButtons
    });
})();
