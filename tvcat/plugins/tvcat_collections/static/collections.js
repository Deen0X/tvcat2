/* tvcat_collections — Gestor de colecciones TVCatCollection.
 * heropage-action: "Añadir a colección" en títulos, "Editar colección" en colecciones.
 * ES5 estricto (SmartTV antigua): sin fetch/flex/arrow functions. */
(function() {
    function esc(s) {
        s = (s === undefined || s === null) ? '' : String(s);
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function chanOf(link) {
        var m = /\/c\/(\d+)\//.exec(link || '');
        return m ? m[1] : '';
    }
    function closeModal() {
        var o = document.getElementById('col-manager-overlay');
        if (o && o.parentNode) o.parentNode.removeChild(o);
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
    function rowHtml(e, i) {
        return '<div style="padding:6px;border-bottom:1px solid #27272a;" data-i="' + i + '">' +
            '<span style="display:inline-block;min-width:28px;color:#a1a1aa;">' + (i + 1) + '.</span> ' +
            '<b>' + esc(e.title) + '</b>' +
            (e.year ? ' <span style="color:#a1a1aa;">(' + esc(e.year) + ')</span>' : '') +
            (e.literal ? ' <span style="color:#fbbf24;">[literal]</span>' : '') +
            '<span style="float:right;">' +
            '<button data-act="up" style="margin-left:4px;">↑</button>' +
            '<button data-act="down" style="margin-left:4px;">↓</button>' +
            '<button data-act="del" style="margin-left:4px;">✕</button>' +
            '</span><div style="clear:both;"></div></div>';
    }
    // state: {mode, collection_item_id, name, channel_id, entries[], coverKind, coverItemId}
    function renderManager(st) {
        var box = overlay();
        var h = '<h3 style="margin:0 0 8px 0;">📚 ' + (st.mode === 'new' ? 'Nueva colección' : 'Editar colección') + '</h3>';
        h += '<label>Nombre:<br><input id="col-name" value="' + esc(st.name) + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:6px;"></label>';
        h += '<div style="color:#a1a1aa;font-size:0.8rem;margin:4px 0;">Canal: ' + esc(st.channel_id) + ' (solo títulos de este canal)</div>';
        h += '<div id="col-rows" style="margin:8px 0;max-height:300px;overflow:auto;border:1px solid #27272a;border-radius:4px;"></div>';
        h += '<div style="margin:8px 0;"><input id="col-search" placeholder="Buscar título para añadir…" style="width:70%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:6px;"> ' +
            '<button id="col-search-btn">Buscar</button></div>';
        h += '<div id="col-results" style="margin:8px 0;max-height:200px;overflow:auto;"></div>';
        h += '<div style="margin-top:12px;text-align:right;">' +
            '<button id="col-cancel">Cancelar</button> ' +
            '<button id="col-save" style="background:#16a34a;color:#fff;border:none;padding:8px 16px;border-radius:4px;">Guardar' +
            (st.mode === 'new' ? ' y publicar' : '') + '</button></div>';
        box.innerHTML = h;
        var rowsEl = box.querySelector('#col-rows');
        function paint() {
            var rh = '';
            for (var i = 0; i < st.entries.length; i++) rh += rowHtml(st.entries[i], i);
            rowsEl.innerHTML = rh || '<div style="padding:8px;color:#a1a1aa;">Sin títulos</div>';
        }
        paint();
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
        box.querySelector('#col-cancel').onclick = closeModal;
        function doSearch() {
            var q = box.querySelector('#col-search').value || '';
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
                        sh += '<div style="padding:4px;border-bottom:1px solid #27272a;">' + esc(it.title) +
                            (it.year ? ' (' + esc(it.year) + ')' : '') +
                            ' <button data-add="' + i + '">Añadir</button></div>';
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
            var payload = {
                collection_item_id: st.collection_item_id || '',
                name: st.name,
                channel_id: st.channel_id,
                entries: st.entries,
                cover: st.mode === 'new'
                    ? { kind: 'title', item_id: st.coverItemId || '' }
                    : { kind: 'keep' }
            };
            window.API.ajax({
                method: 'POST', url: '/api/collections/save', data: payload,
                success: function(r) {
                    var msg = 'Colección guardada (' + (r.mode === 'publish' ? 'publicada' : 'editada') + ').';
                    if (r.dropped && r.dropped.length) msg += '\nOmitidos (otro canal): ' + r.dropped.join(', ');
                    msg += '\nEl catálogo se actualizará en el próximo escaneo.';
                    alert(msg);
                    closeModal();
                    try { if (window.Catalog && window.Catalog.loadCollections) window.Catalog.loadCollections(); } catch (e) {}
                },
                error: function(s, body) {
                    var detail = '';
                    try { detail = (JSON.parse(body) || {}).detail || body || ''; } catch (e2) { detail = body || ''; }
                    alert('Error al guardar: ' + detail);
                }
            });
        };
    }
    function openForCollection(item) {
        window.API.ajax({
            url: '/api/collections/detail?item_id=' + encodeURIComponent(item.item_id || item.id),
            success: function(d) {
                renderManager({
                    mode: 'edit', collection_item_id: d.item_id, name: d.title,
                    channel_id: d.channel_id, entries: d.entries || [],
                    coverKind: 'keep', coverItemId: ''
                });
            },
            error: function() { alert('No se pudo cargar la colección.'); }
        });
    }
    function openAdd(item) {
        var ch = chanOf(item.telegram_link || '');
        if (!ch) { alert('Este título no tiene canal asociado.'); return; }
        window.API.ajax({
            url: '/api/collections/by-channel?channel_id=' + encodeURIComponent(ch),
            success: function(d) {
                var box = overlay();
                var h = '<h3 style="margin:0 0 8px 0;">📚 Añadir «' + esc(item.title) + '» a colección</h3>';
                h += '<div style="color:#a1a1aa;font-size:0.8rem;margin-bottom:8px;">Canal ' + esc(ch) + ' (mismo canal obligatorio)</div>';
                var cols = (d && d.collections) || [];
                for (var i = 0; i < cols.length; i++) {
                    h += '<div style="padding:6px;border-bottom:1px solid #27272a;">📚 ' + esc(cols[i].title) +
                        ' <span style="color:#a1a1aa;">(' + cols[i].entries + ')</span>' +
                        ' <button data-col="' + esc(cols[i].item_id) + '" data-title="' + esc(cols[i].title) + '">Añadir aquí</button></div>';
                }
                h += '<div style="margin-top:12px;">Nueva: <input id="col-new-name" placeholder="Nombre de la colección" style="background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:6px;"> ' +
                    '<button id="col-new-btn">Crear con este título</button></div>';
                h += '<div style="margin-top:12px;text-align:right;"><button id="col-x">Cerrar</button></div>';
                box.innerHTML = h;
                box.querySelector('#col-x').onclick = closeModal;
                box.onclick = function(e) {
                    var t = e.target || e.srcElement;
                    var cid = t.getAttribute ? t.getAttribute('data-col') : null;
                    if (!cid) return;
                    // Cargar la colección y añadir el título actual
                    window.API.ajax({
                        url: '/api/collections/detail?item_id=' + encodeURIComponent(cid),
                        success: function(dd) {
                            var st = {
                                mode: 'edit', collection_item_id: dd.item_id, name: dd.title,
                                channel_id: dd.channel_id, entries: dd.entries || [],
                                coverKind: 'keep', coverItemId: ''
                            };
                            st.entries.push({ title: item.title, year: item.year || '', literal: false, item_id: item.item_id || item.id });
                            renderManager(st);
                        }
                    });
                };
                box.querySelector('#col-new-btn').onclick = function() {
                    var nm = box.querySelector('#col-new-name').value || item.title;
                    renderManager({
                        mode: 'new', collection_item_id: '', name: nm, channel_id: ch,
                        entries: [{ title: item.title, year: item.year || '', literal: false, item_id: item.item_id || item.id }],
                        coverKind: 'title', coverItemId: item.item_id || item.id
                    });
                };
            },
            error: function() { alert('No se pudieron cargar las colecciones del canal.'); }
        });
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
                        return [{ id: 'btn-col-edit', icon: '✏️', tooltip: 'Editar colección', label: '', action: function() { openForCollection(itemData); } }];
                    }
                    if (itemData.telegram_link) {
                        return [{ id: 'btn-col-add', icon: '📚', tooltip: 'Añadir a colección', label: '', action: function() { openAdd(itemData); } }];
                    }
                } catch (e) {}
                return [];
            }
        });
    }
})();
