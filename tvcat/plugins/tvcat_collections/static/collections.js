/* tvcat_collections — Gestor de colecciones TVCatCollection.
 * heropage-action: "Añadir a colección" en títulos, "Editar colección" en colecciones.
 * Botones con clases globales btn-primary/btn-secondary/btn-danger.
 * ES5 estricto (SmartTV antigua): sin fetch/flex/arrow functions. */
(function() {
    try { console.log('[Collections] collections.js v1.1.6'); } catch (e) {}
    var ICON_HEAD = '<img src="/plugin-static/tvcat_collections/plugin_button.png" style="width:20px;height:20px;vertical-align:middle;" onerror="this.outerHTML=\'📚\'"> ';
    var HERO_ADD = '<img src="/plugin-static/tvcat_collections/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'📚\'">';
    var HERO_EDIT = '<img src="/plugin-static/tvcat_collections/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'✏️\'">';
    function esc(s) {
        s = (s === undefined || s === null) ? '' : String(s);
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function closeModal() {
        var o = document.getElementById('col-manager-overlay');
        if (o && o.parentNode) o.parentNode.removeChild(o);
    }
    function toast(msg) {
        try {
            var t = document.createElement('div');
            t.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:60000;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px 14px;font-size:0.9rem;max-width:320px;box-shadow:0 4px 15px rgba(0,0,0,0.5);';
            t.textContent = msg;
            document.body.appendChild(t);
            setTimeout(function() { if (t.parentNode) t.parentNode.removeChild(t); }, 3500);
        } catch (e) {}
    }
    function overlay() {
        closeModal();
        var o = document.createElement('div');
        o.id = 'col-manager-overlay';
        o.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);z-index:50000;display:block;overflow:auto;';
        var box = document.createElement('div');
        box.style.cssText = 'background:#18181b;color:#f4f4f5;max-width:640px;margin:40px auto;padding:16px;border:1px solid #3f3f46;border-radius:8px;';
        o.appendChild(box);
        document.body.appendChild(o);
        o.onclick = function(e) { if (e.target === o) closeModal(); };
        return box;
    }
    function thumbHtml(e, w, h) {
        w = w || 36; h = h || 54;
        if (!e.item_id) return '<span style="display:inline-block;width:' + w + 'px;height:' + h + 'px;background:#27272a;border-radius:4px;vertical-align:middle;"></span>';
        return '<img src="/api/cover/' + encodeURIComponent(e.item_id) + '" style="width:' + w + 'px;height:' + h + 'px;object-fit:cover;border-radius:4px;vertical-align:middle;background:#27272a;" onerror="this.style.display=\'none\'">';
    }
    function rowHtml(e, i) {
        return '<div draggable="true" style="padding:6px;border-bottom:1px solid #27272a;cursor:move;" data-i="' + i + '">' +
            '<span style="display:inline-block;min-width:24px;color:#a1a1aa;vertical-align:middle;">' + (i + 1) + '.</span> ' +
            thumbHtml(e) + ' ' +
            '<b style="vertical-align:middle;">' + esc(e.title) + '</b>' +
            (e.year ? ' <span style="color:#a1a1aa;">(' + esc(e.year) + ')</span>' : '') +
            (e.literal ? ' <span style="color:#fbbf24;">[literal]</span>' : '') +
            '<span style="float:right;">' +
            '<button class="btn-secondary" data-act="up" title="Subir" style="padding:8px 12px;font-size:0.95rem;margin-left:6px;">↑</button>' +
            '<button class="btn-secondary" data-act="down" title="Bajar" style="padding:8px 12px;font-size:0.95rem;margin-left:6px;">↓</button>' +
            '<button class="btn-danger" data-act="del" title="Quitar" style="padding:8px 12px;font-size:0.95rem;margin-left:6px;background:#d32f2f;color:#fff;border:none;border-radius:4px;cursor:pointer;">✕</button>' +
            '</span><div style="clear:both;"></div></div>';
    }
    // state: {mode, collection_item_id, name, serial, channel_id, description, entries[], cover:{kind,item_id,b64,url}}
    // mode: 'new' (siempre local) | 'edit' (escaneada) | 'edit-local'
    // cover.kind: 'keep' (conservar) | 'title' (de un título) | 'upload' (fichero) | 'url'
    function renderManager(st) {
        st.cover = st.cover || { kind: (st.mode === 'new' ? 'title' : 'keep'), item_id: st.coverItemId || '' };
        var box = overlay();
        var h = '<h3 style="margin:0 0 8px 0;">' + ICON_HEAD + (st.mode === 'new' ? 'Nueva colección' : 'Editar colección') + '</h3>';
        // Sección superior: cover (izq) + título/descripción (der). Conforma el mensaje de cover.
        // Sin overflow:hidden en el wrapper: recortaría el menú absoluto del cover
        // (el <div clear:both> ya contiene el float).
        h += '<div style="margin-bottom:8px;">' +
            '<div style="float:left;width:120px;margin-right:12px;text-align:center;position:relative;">' +
            '<div id="col-cover-click" title="Cambiar cover" style="cursor:pointer;width:120px;height:180px;border-radius:6px;background:#27272a;overflow:hidden;">' +
            '<img id="col-cover-img" src="" style="width:120px;height:180px;object-fit:cover;border-radius:6px;background:#27272a;display:none;pointer-events:none;" onerror="this.style.display=\'none\';var p=document.getElementById(\'col-cover-ph\');if(p)p.style.display=\'block\'">' +
            '<div id="col-cover-ph" style="width:120px;height:180px;border-radius:6px;background:#27272a;color:#a1a1aa;font-size:2rem;line-height:180px;pointer-events:none;">📚</div>' +
            '</div>' +
            '<div id="col-cover-menu" style="display:none;position:absolute;left:0;top:184px;z-index:10;background:#09090b;border:1px solid #3f3f46;border-radius:8px;padding:6px;width:148px;box-sizing:border-box;">' +
            '<button id="col-cover-title" class="btn-secondary" title="Usar el cover del primer título" style="display:block;width:100%;padding:8px 10px;font-size:0.85rem;margin:2px 0;text-align:left;">🖼️ Título</button>' +
            '<button id="col-cover-upload" class="btn-secondary" title="Subir imagen local" style="display:block;width:100%;padding:8px 10px;font-size:0.85rem;margin:2px 0;text-align:left;">⬆️ Subir</button>' +
            '<button id="col-cover-paste" class="btn-secondary" title="Pegar imagen del portapapeles" style="display:block;width:100%;padding:8px 10px;font-size:0.85rem;margin:2px 0;text-align:left;">📋 Pegar</button>' +
            '<button id="col-cover-url" class="btn-secondary" title="Imagen desde URL" style="display:block;width:100%;padding:8px 10px;font-size:0.85rem;margin:2px 0;text-align:left;">🔗 URL</button>' +
            '</div>' +
            '<input type="file" id="col-cover-file" accept="image/*" style="display:none;">' +
            '</div>' +
            '<div style="overflow:hidden;"><label>Nombre:<br><input id="col-name" value="' + esc(st.name) + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;"></label>' +
            '<label>Descripción:<br><textarea id="col-desc" rows="4" placeholder="Sinopsis, notas…" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;resize:vertical;">' + esc(st.description || '') + '</textarea></label></div>' +
            '<div style="clear:both;"></div></div>';
        h += '<div id="col-rows" style="margin:8px 0;max-height:300px;overflow:auto;border:1px solid #27272a;border-radius:4px;"></div>';
        h += '<div style="margin:8px 0;"><input id="col-search" placeholder="Buscar título para añadir…" style="width:60%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;"> ' +
            '<button id="col-search-btn" class="btn-secondary" style="padding:10px 20px;font-size:0.95rem;">Buscar</button></div>';
        h += '<div id="col-results" style="margin:8px 0;max-height:200px;overflow:auto;"></div>';
        h += '<div style="margin-top:12px;overflow:hidden;">' +
            (st.mode === 'new'
                ? ''
                : '<button id="col-del" class="btn-danger" style="display:inline-block;float:left;padding:10px 20px;font-size:0.95rem;background:#d32f2f;color:#fff;border:none;border-radius:4px;cursor:pointer;">Eliminar colección</button>') +
            '<div style="text-align:right;">' +
            '<button id="col-cancel" class="btn-secondary" style="display:inline-block;padding:10px 20px;font-size:0.95rem;">Cancelar</button> ' +
            '<button id="col-save" class="btn-primary" style="display:inline-block;padding:10px 20px;font-size:0.95rem;">Guardar</button></div></div>';
        box.innerHTML = h;
        // Preview del cover: asset actual, si no el primer título.
        function paintCover() {
            var img = box.querySelector('#col-cover-img'), ph = box.querySelector('#col-cover-ph');
            var src = '';
            if (st.cover && st.cover.kind === 'upload' && st.cover.b64) src = st.cover.b64;
            else if (st.cover && st.cover.kind === 'url' && st.cover.url) src = st.cover.url;
            else if (st.collection_item_id) src = '/api/cover/' + encodeURIComponent(st.collection_item_id);
            else if (st.cover && st.cover.kind === 'title' && st.cover.item_id) src = '/api/cover/' + encodeURIComponent(st.cover.item_id);
            else if (st.entries.length && st.entries[0].item_id) src = '/api/cover/' + encodeURIComponent(st.entries[0].item_id);
            if (src) { img.src = src; img.style.display = 'block'; if (ph) ph.style.display = 'none'; }
            else { img.style.display = 'none'; if (ph) ph.style.display = 'block'; }
        }
        paintCover();
        function hideCoverMenu() {
            var m = box.querySelector('#col-cover-menu');
            if (m) m.style.display = 'none';
        }
        function toggleCoverMenu(ev) {
            if (ev && ev.stopPropagation) ev.stopPropagation();
            var m = box.querySelector('#col-cover-menu');
            if (!m) return;
            m.style.display = (m.style.display === 'block') ? 'none' : 'block';
        }
        var coverClickEl = box.querySelector('#col-cover-click');
        if (coverClickEl) {
            // UN SOLO enganche (addEventListener y onclick a la vez = doble
            // toggle: abre y cierra en el mismo click).
            if (coverClickEl.addEventListener) coverClickEl.addEventListener('click', toggleCoverMenu);
            else coverClickEl.onclick = toggleCoverMenu;
        }
        // Cerrar el menú al pulsar en el resto del diálogo.
        box.addEventListener('click', function(e) {
            var m = box.querySelector('#col-cover-menu');
            if (!m || m.style.display !== 'block') return;
            var t = e.target || e.srcElement;
            var inside = false;
            try { inside = !!(t.closest && (t.closest('#col-cover-menu') || t.closest('#col-cover-click'))); } catch (e2) {}
            if (!inside) hideCoverMenu();
        });
        box.querySelector('#col-cover-title').onclick = function() {
            hideCoverMenu();
            var first = (st.entries.length && st.entries[0].item_id) ? st.entries[0].item_id : (st.coverItemId || '');
            if (!first) { toast('Añade primero un título a la colección.'); return; }
            st.cover = { kind: 'title', item_id: first };
            paintCover();
            toast('Cover: se usará el del primer título.');
        };
        box.querySelector('#col-cover-upload').onclick = function() { hideCoverMenu(); box.querySelector('#col-cover-file').click(); };
        var pasteBtn = box.querySelector('#col-cover-paste');
        if (pasteBtn) pasteBtn.onclick = function() {
            hideCoverMenu();
            try {
                if (!navigator.clipboard || !navigator.clipboard.read) { toast('Portapapeles no disponible: usa Subir o URL.'); return; }
                navigator.clipboard.read().then(function(items) {
                    var found = false;
                    for (var i = 0; i < (items || []).length && !found; i++) {
                        var types = items[i].types || [];
                        for (var t = 0; t < types.length; t++) {
                            if (types[t].indexOf('image/') === 0) {
                                found = true;
                                items[i].getType(types[t]).then(function(blob) {
                                    if (blob.size > 10 * 1024 * 1024) { toast('Imagen mayor de 10MB.'); return; }
                                    var rd = new FileReader();
                                    rd.onload = function() { st.cover = { kind: 'upload', b64: rd.result }; paintCover(); toast('Imagen pegada.'); };
                                    rd.readAsDataURL(blob);
                                }, function() { toast('No se pudo leer la imagen.'); });
                                break;
                            }
                        }
                    }
                    if (!found) toast('No hay imagen en el portapapeles (copia una imagen primero).');
                }, function() { toast('Permiso denegado: copia la imagen y reintenta, o usa Subir/URL.'); });
            } catch (e) { toast('Portapapeles no disponible: usa Subir o URL.'); }
        };
        box.querySelector('#col-cover-file').onchange = function() {
            var f = this.files && this.files[0];
            if (!f) return;
            if (f.size > 10 * 1024 * 1024) { toast('Imagen mayor de 10MB.'); return; }
            var rd = new FileReader();
            rd.onload = function() { st.cover = { kind: 'upload', b64: rd.result }; paintCover(); };
            rd.readAsDataURL(f);
        };
        box.querySelector('#col-cover-url').onclick = function() {
            hideCoverMenu();
            var u = prompt('URL de la imagen de portada:', (st.cover && st.cover.url) || 'https://');
            if (u === null) return;
            u = (u || '').trim();
            if (!u) return;
            st.cover = { kind: 'url', url: u };
            paintCover();
        };
        var rowsEl = box.querySelector('#col-rows');
        var dragIdx = -1;
        function paint() {
            var rh = '';
            for (var i = 0; i < st.entries.length; i++) rh += rowHtml(st.entries[i], i);
            rowsEl.innerHTML = rh || '<div style="padding:8px;color:#a1a1aa;">Sin títulos</div>';
        }
        paint();
        // Resolver item_id de las entradas (miniaturas) vía resolve de la colección.
        if (st.collection_item_id) {
            window.API.ajax({
                url: '/api/collection/resolve?item_id=' + encodeURIComponent(st.collection_item_id),
                success: function(d) {
                    try {
                        var map = {};
                        var items = (d && d.items) || [];
                        for (var k = 0; k < items.length; k++) map[String(items[k].position)] = items[k].item_id;
                        var changed = false;
                        for (var n = 0; n < st.entries.length; n++) {
                            if (!st.entries[n].item_id && map[String(n)]) { st.entries[n].item_id = map[String(n)]; changed = true; }
                        }
                        if (changed) paint();
                    } catch (e) {}
                }
            });
        }
        rowsEl.onclick = function(e) {
            var t = e.target || e.srcElement;
            if (!t.getAttribute) return;
            var act = t.getAttribute('data-act');
            if (!act) return;
            var row = t.parentNode.parentNode;
            var i = parseInt(row.getAttribute('data-i'), 10);
            if (act === 'del') st.entries.splice(i, 1);
            else if (act === 'up' && i > 0) { var a = st.entries[i - 1]; st.entries[i - 1] = st.entries[i]; st.entries[i] = a; }
            else if (act === 'down' && i < st.entries.length - 1) { var b = st.entries[i + 1]; st.entries[i + 1] = st.entries[i]; st.entries[i] = b; }
            paint();
        };
        // Arrastrar para reordenar (PC; en TV/mando se usan ↑↓).
        rowsEl.addEventListener('dragstart', function(e) {
            var row = e.target && e.target.closest ? e.target.closest('[data-i]') : null;
            dragIdx = row ? parseInt(row.getAttribute('data-i'), 10) : -1;
            try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(dragIdx)); } catch (e2) {}
        });
        rowsEl.addEventListener('dragover', function(e) { e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (e2) {} });
        rowsEl.addEventListener('drop', function(e) {
            e.preventDefault();
            var row = e.target && e.target.closest ? e.target.closest('[data-i]') : null;
            if (!row || dragIdx < 0) return;
            var to = parseInt(row.getAttribute('data-i'), 10);
            if (to === dragIdx || isNaN(to)) return;
            var mv = st.entries.splice(dragIdx, 1)[0];
            st.entries.splice(to, 0, mv);
            dragIdx = -1;
            paint();
        });
        rowsEl.addEventListener('dragend', function() { dragIdx = -1; });
        box.querySelector('#col-cancel').onclick = closeModal;
        function doSearch() {
            var q = box.querySelector('#col-search').value || '';
            try { q = window.sanitizeSearchText ? window.sanitizeSearchText(q) : q; } catch (e) {}
            if (q.trim().length < 2) return;
            window.API.ajax({
                url: '/api/catalog/home?search=' + encodeURIComponent(q) + '&limit=20',
                success: function(d) {
                    var res = box.querySelector('#col-results');
                    var items = (d && d.items) || [];
                    var sh = '';
                    for (var i = 0; i < items.length; i++) {
                        var it = items[i];
                        if (it.is_collection) continue;
                        sh += '<div style="padding:4px;border-bottom:1px solid #27272a;">' + thumbHtml(it, 28, 42) + ' ' + esc(it.title) +
                            (it.year ? ' (' + esc(it.year) + ')' : '') +
                            ' <button class="btn-secondary" data-add="' + i + '" style="padding:8px 14px;font-size:0.95rem;float:right;">Añadir</button><div style="clear:both;"></div></div>';
                    }
                    res.innerHTML = sh || '<div style="color:#a1a1aa;">Sin resultados</div>';
                    res.onclick = function(e2) {
                        var b = e2.target || e2.srcElement;
                        var ai = b.getAttribute ? b.getAttribute('data-add') : null;
                        if (ai === null || ai === undefined) return;
                        var pick = items[parseInt(ai, 10)];
                        st.entries.push({ title: pick.title, year: pick.year || '', literal: false, item_id: pick.item_id });
                        paint();
                    };
                }
            });
        }
        box.querySelector('#col-search-btn').onclick = doSearch;
        box.querySelector('#col-save').onclick = function() {
            st.name = box.querySelector('#col-name').value || st.name;
            st.description = box.querySelector('#col-desc').value || '';
            var isLocal = (st.mode === 'new') || (st.collection_item_id || '').indexOf('COL-') === 0;
            var cv = st.cover || { kind: (st.mode === 'new' ? 'title' : 'keep') };
            if (st.mode === 'new' && cv.kind === 'title' && !cv.item_id) {
                cv = { kind: 'title', item_id: (st.entries.length && st.entries[0].item_id) || st.coverItemId || '' };
            }
            var payload = {
                collection_item_id: isLocal ? (st.collection_item_id || '') : st.collection_item_id,
                name: st.name,
                serial: st.serial || '',
                description: st.description || '',
                channel_id: st.channel_id,
                entries: st.entries,
                cover: { kind: cv.kind || 'keep', item_id: cv.item_id || '', b64: cv.b64 || '', url: cv.url || '' }
            };
            window.API.ajax({
                method: 'POST', url: isLocal ? '/api/collections/local/save' : '/api/collections/save', data: payload,
                success: function(r) {
                    var msg = 'Colección guardada.';
                    if (r.dropped && r.dropped.length) msg += ' Omitidos: ' + r.dropped.join(', ');
                    // Si editamos la colección que estamos viendo, refrescar su
                    // página (fondo, título, descripción y lista) sin salir.
                    var savedId = r.item_id || st.collection_item_id || '';
                    var viewing = '';
                    try { viewing = (window._activeCollection && window._activeCollection.id) || ''; } catch (e) {}
                    closeModal();
                    toast(msg);
                    try {
                        if (viewing && savedId && viewing === savedId && window.Catalog && window.Catalog.openCollection) {
                            window.Catalog.openCollection(savedId, Date.now());
                        }
                    } catch (e2) {}
                },
                error: function(s, body) {
                    var detail = '';
                    try { detail = (JSON.parse(body) || {}).detail || body || ''; } catch (e2) { detail = body || ''; }
                    alert('Error al guardar: ' + detail);
                }
            });
        };
        var delBtn = box.querySelector('#col-del');
        if (delBtn) delBtn.onclick = function() {
            if (!confirm('¿Eliminar la colección «' + st.name + '»?' + (st.mode === 'edit-local' || (st.collection_item_id || '').indexOf('COL-') === 0 ? '' : '\nSe borrarán sus mensajes en Telegram.'))) return;
            window.API.ajax({
                method: 'DELETE', url: '/api/collections/delete?item_id=' + encodeURIComponent(st.collection_item_id),
                success: function() {
                    closeModal();
                    toast('Colección eliminada.');
                    try {
                        if (window.Catalog && window.Catalog.currentCategory === 'collections' && window.Catalog.loadCollections) window.Catalog.loadCollections();
                    } catch (e) {}
                },
                error: function(s, body) {
                    var detail = '';
                    try { detail = (JSON.parse(body) || {}).detail || body || ''; } catch (e2) { detail = body || ''; }
                    alert('No se pudo eliminar: ' + detail);
                }
            });
        };
    }
    function openForCollection(item) {
        window.API.ajax({
            url: '/api/collections/detail?item_id=' + encodeURIComponent(item.item_id || item.id),
            success: function(d) {
                renderManager({
                    mode: (d.local ? 'edit-local' : 'edit'),
                    collection_item_id: d.item_id, name: d.title, serial: d.serial || '',
                    channel_id: d.channel_id, description: d.description || '',
                    entries: d.entries || [],
                    cover: { kind: 'keep' }, coverItemId: ''
                });
            },
            error: function() { alert('No se pudo cargar la colección.'); }
        });
    }
    // Diálogo único: lista combinada (internamente local/escaneada, sin distinción visible).
    function openAdd(item) {
        var box = overlay();
        box.innerHTML = '<div style="color:#a1a1aa;">Cargando colecciones…</div>';
        var scanned = [], locals = [], pending = 2;
        function chanOf(link) {
            var m = /\/c\/(\d+)\//.exec(link || '');
            return m ? m[1] : '';
        }
        function done() { if (--pending === 0) paint(); }
        var ch = chanOf(item.telegram_link || '');
        if (ch) {
            window.API.ajax({
                url: '/api/collections/by-channel?channel_id=' + encodeURIComponent(ch),
                success: function(d) { scanned = (d && d.collections) || []; done(); },
                error: function() { done(); }
            });
        } else done();
        window.API.ajax({
            url: '/api/collections/local/list',
            success: function(d) { locals = (d && d.collections) || []; done(); },
            error: function() { done(); }
        });
        function paint() {
            var all = locals.concat(scanned);
            all.sort(function(a, b) {
                var ta = (a.title || '').toLowerCase(), tb = (b.title || '').toLowerCase();
                return ta < tb ? -1 : (ta > tb ? 1 : 0);
            });
            var h = '<h3 style="margin:0 0 8px 0;">' + ICON_HEAD + 'Añadir «' + esc(item.title) + '» a colección</h3>';
            if (!all.length) h += '<div style="color:#a1a1aa;font-size:0.8rem;margin-bottom:8px;">Aún no hay colecciones</div>';
            for (var i = 0; i < all.length; i++) {
                h += '<div style="padding:6px;border-bottom:1px solid #27272a;">' + thumbHtml(all[i], 28, 42) + ' ' + esc(all[i].title) +
                    ' <span style="color:#a1a1aa;">(' + all[i].entries + ')</span>' +
                    ' <button class="btn-secondary" data-col="' + esc(all[i].item_id) + '" style="padding:8px 14px;font-size:0.95rem;float:right;">Añadir aquí</button><div style="clear:both;"></div></div>';
            }
            h += '<div style="margin-top:12px;"><label>Nueva:<br><input id="col-new-name" placeholder="Nombre de la colección" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;"></label></div>';
            h += '<div style="margin-top:12px;text-align:right;">' +
                '<button id="col-new-btn" class="btn-primary" style="display:inline-block;padding:10px 20px;font-size:0.95rem;">Crear con este título</button> ' +
                '<button id="col-x" class="btn-secondary" style="display:inline-block;padding:10px 20px;font-size:0.95rem;">Cerrar</button></div>';
            box.innerHTML = h;
            box.querySelector('#col-x').onclick = closeModal;
            box.onclick = function(e) {
                var t = e.target || e.srcElement;
                var cid = t.getAttribute ? t.getAttribute('data-col') : null;
                if (!cid) return;
                window.API.ajax({
                    url: '/api/collections/detail?item_id=' + encodeURIComponent(cid),
                    success: function(dd) {
                        var st = {
                            mode: (dd.local ? 'edit-local' : 'edit'),
                            collection_item_id: dd.item_id, name: dd.title, serial: dd.serial || '',
                            channel_id: dd.channel_id, description: dd.description || '',
                            entries: dd.entries || [],
                            cover: { kind: 'keep' }, coverItemId: ''
                        };
                        st.entries.push({ title: item.title, year: item.year || '', literal: false, item_id: item.item_id || item.id });
                        renderManager(st);
                    }
                });
            };
            box.querySelector('#col-new-btn').onclick = function() {
                var nm = box.querySelector('#col-new-name').value || item.title;
                renderManager({
                    mode: 'new', collection_item_id: '', name: nm, serial: '',
                    channel_id: '', description: '', entries: [{ title: item.title, year: item.year || '', literal: false, item_id: item.item_id || item.id }],
                    cover: { kind: 'title', item_id: item.item_id || item.id }, coverItemId: item.item_id || item.id
                });
            };
        }
    }
    if (window.pluginSystem) {
        window.pluginSystem.registerPlugin({
            name: 'tvcat_collections',
            type: 'heropage-action',
            displayName: 'Colecciones',
            getHeroButtons: function(itemData) {
                if (!itemData) return [];
                try {
                    if (itemData.is_collection) {
                        return [{ id: 'btn-col-edit', icon: HERO_EDIT, tooltip: 'Editar colección', label: '', action: function() { openForCollection(itemData); } }];
                    }
                    return [{ id: 'btn-col-add', icon: HERO_ADD, tooltip: 'Añadir a colección', label: '', action: function() { openAdd(itemData); } }];
                } catch (e) {}
                return [];
            }
        });
        // Slot de página de colección (cabecera): Editar, a la izquierda de Cerrar.
        // Registro separado (el registry indexa por nombre): mismo JS, otro tipo.
        window.pluginSystem.registerPlugin({
            name: 'tvcat_collections_page',
            type: 'collectionpage-action',
            displayName: 'Colecciones (página)',
            getCollectionButtons: function(collectionData) {
                if (!collectionData || !collectionData.item_id) return [];
                return [{ id: 'btn-colpage-edit', icon: '✏️', label: 'Editar', tooltip: 'Editar colección',
                    action: function() { openForCollection(collectionData); } }];
            }
        });
    }
})();
