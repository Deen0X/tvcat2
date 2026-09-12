(function() {
    if (!window.pluginSystem) return;

    var API = '/api/telegram-copy-v2';
    var LS_KEY = 'TGHirayi_v2_last_destinations';
    // Referencia al modal de cola abierto (para refrescar tras acciones)
    var _queue_modal = null;

    function api(url, opts, cb) {
        opts = opts || {};
        var xhr = new XMLHttpRequest();
        xhr.open(opts.method || 'GET', url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            var b = {};
            try { b = JSON.parse(xhr.responseText || '{}'); } catch(e) {}
            if (cb) cb(b, xhr.status);
        };
        xhr.onerror = function() { if (cb) cb({}, 0); };
        xhr.send(opts.data ? JSON.stringify(opts.data) : null);
    }

    function showToast(msg) {
        var t = document.getElementById('toast-container');
        if (!t) { t = document.createElement('div'); t.id = 'toast-container'; t.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999999;display:flex;flex-direction:column;gap:8px;'; document.body.appendChild(t); }
        var el = document.createElement('div');
        el.style.cssText = 'background:#18181b;border:1px solid #3f3f46;border-radius:8px;padding:10px 16px;color:#f4f4f5;font-size:13px;max-width:300px;box-shadow:0 4px 12px rgba(0,0,0,0.4);';
        el.textContent = msg;
        t.appendChild(el);
        setTimeout(function() { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(function() { el.remove(); }, 300); }, 3000);
    }

    function openModal(title, contentFn, width) {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;';
        var panel = document.createElement('div');
        panel.style.cssText = 'background:#0d0d0f;border:1px solid #3f3f46;border-radius:10px;padding:16px;width:95vw;max-width:600px;max-height:85vh;overflow-y:auto;color:#f4f4f5;';
        panel.innerHTML = '<div style="font-weight:600;margin-bottom:12px;font-size:15px;">' + title + '</div>';
        var content = document.createElement('div');
        panel.appendChild(content);
        var close = document.createElement('button');
        close.textContent = 'Cerrar';
        close.style.cssText = 'margin-top:10px;padding:6px 14px;background:#27272a;border:1px solid #3f3f46;color:#fff;border-radius:6px;cursor:pointer;float:right;';
        close.onclick = function() { overlay.remove(); };
        panel.appendChild(close);
        overlay.appendChild(panel);
        document.body.appendChild(overlay);
        contentFn(content, overlay);
        return { overlay: overlay, content: content, panel: panel };
    }

    // ─── Modal de selección de destinos y encolado ───
    function showDestinationPicker(item) {
        api(API + '/destinations', {}, function(res) {
            var dests = (res && res.destinations) || [];

            if (dests.length === 0) {
                alert('No hay destinos configurados. Ve a Configuraci\u00f3n del plugin TGHirayi_v2 para a\u00f1adir destinos.');
                return;
            }

            api(API + '/config', {}, function(cfgRes) {
                var cfg = (cfgRes && cfgRes.config) || {};
                var skipDef = !!cfg.skip_if_exists_topo3;

                if (dests.length === 1) {
                    // Un solo destino: encolar directamente con el default de config
                    doEnqueue(item, [dests[0].id], skipDef);
                    return;
                }

                var lastSel = {};
                try { lastSel = JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch(e) {}

                var modal = openModal('Enviar a Canal Telegram', function(content, overlay) {
                    var html = '<div class="muted" style="margin-bottom:8px;font-size:12px;color:#a1a1aa;">Selecciona los canales destino para <b>' + (item.title || item.name || '') + '</b></div>';
                    for (var i = 0; i < dests.length; i++) {
                        var d = dests[i];
                        var checked = lastSel[d.id] ? 'checked' : '';
                        html += '<label style="display:flex;align-items:center;gap:8px;padding:10px;margin:4px 0;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:6px;cursor:pointer;">' +
                            '<input type="checkbox" class="tgcopy2-dest-cb" value="' + d.id + '" ' + checked + ' style="accent-color:#22c55e;">' +
                            '<span style="flex:1;">' + d.name + '</span>' +
                            '<span style="font-size:11px;color:#a1a1aa;">' + (d.channel_title || '') + '</span>' +
                            '</label>';
                    }
                    html += '<label style="display:flex;align-items:center;gap:8px;padding:10px;margin:8px 0 0 0;background:rgba(234,179,8,0.08);border:1px solid rgba(234,179,8,0.3);border-radius:6px;cursor:pointer;">' +
                        '<input type="checkbox" class="tgcopy2-skip-cb" ' + (skipDef ? 'checked' : '') + ' style="accent-color:#eab308;">' +
                        '<span style="flex:1;font-size:12px;">Omitir subida si el topic ya existe en el destino</span></label>';
                    var btnRow = document.createElement('div');
                    btnRow.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
                    content.innerHTML = html;
                    var enqueue = document.createElement('button');
                    enqueue.textContent = 'A\u00f1adir a la cola';
                    enqueue.style.cssText = 'flex:1;padding:8px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:600;';
                    enqueue.onclick = function() {
                        var ids = [];
                        var boxes = content.querySelectorAll('.tgcopy2-dest-cb:checked');
                        for (var j = 0; j < boxes.length; j++) ids.push(boxes[j].value);
                        if (ids.length === 0) { alert('Selecciona al menos un destino.'); return; }
                        var sel = {};
                        for (var k = 0; k < dests.length; k++) sel[dests[k].id] = ids.indexOf(dests[k].id) >= 0;
                        localStorage.setItem(LS_KEY, JSON.stringify(sel));
                        var skipBox = content.querySelector('.tgcopy2-skip-cb');
                        doEnqueue(item, ids, !!(skipBox && skipBox.checked));
                        overlay.remove();
                    };
                    var cancel = document.createElement('button');
                    cancel.textContent = 'Cancelar';
                    cancel.style.cssText = 'padding:8px 14px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;';
                    cancel.onclick = function() { overlay.remove(); };
                    btnRow.appendChild(enqueue);
                    btnRow.appendChild(cancel);
                    content.appendChild(btnRow);
                });
            });
        });
    }

    function doEnqueue(item, destIds, skipFlag) {
        api(API + '/queue', { method: 'POST', data: {
            item_id: item.item_id || item.id,
            title: item.title || item.name || '',
            category: item.category || '',
            subcategory: item.subcategory || '',
            destination_ids: destIds,
            total_episodes: (item.episodes && item.episodes.length) || 0,
            telegram_link: item.telegram_link || '',
            skip_if_exists_topo3: !!skipFlag
        }}, function(r) {
            if (r && r.ok) {
                showToast('A\u00f1adido a la cola (Job #' + r.job_id + ')');
            } else {
                alert('Error al encolar: ' + (r && r.detail ? r.detail : 'Error desconocido'));
            }
        });
    }

    // ─── Envío masivo: todos los elementos del catálogo filtrado ───
    function showBulkSendModal(itemsOverride, titleOverride) {
        var items = itemsOverride || ((window.Catalog && window.Catalog.currentItems) || []);
        if (!items.length) { alert('No hay elementos en el catálogo actual.'); return; }
        api(API + '/queue', {}, function(qres) {
            var queuedIds = {};
            var q = (qres && qres.queue) || [];
            for (var qi = 0; qi < q.length; qi++) {
                var qs = q[qi].status || '';
                if (qs !== 'completed' && qs !== 'error' && qs !== 'skipped') {
                    queuedIds[String(q[qi].item_id)] = true;
                }
            }
            api(API + '/destinations', {}, function(res) {
                var dests = (res && res.destinations) || [];
                if (!dests.length) { alert('No hay destinos configurados. Ve a Configuración del plugin TGHirayi_v2 para añadir destinos.'); return; }
                openModal(titleOverride || ('Enviar todos a Canal Telegram (' + items.length + ')'), function(content, overlay) {
                    var html = '<div style="display:flex;gap:8px;margin-bottom:8px;">' +
                        '<button class="tgcopy2-bulk-all" style="flex:1;padding:6px;background:#27272a;border:1px solid #3f3f46;color:#fff;border-radius:6px;cursor:pointer;">Marcar todo</button>' +
                        '<button class="tgcopy2-bulk-none" style="flex:1;padding:6px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;">Desmarcar todo</button></div>' +
                        '<div class="tgcopy2-bulk-list" style="max-height:50vh;overflow-y:auto;">';
                    for (var i = 0; i < items.length; i++) {
                        var it = items[i];
                        var iid = String(it.item_id || it.id || '');
                        var checked = queuedIds[iid] ? '' : 'checked';
                        var cover = it.cover_url || ('/api/cover/' + encodeURIComponent(iid));
                        var t = escHtml(it.title || it.name || iid);
                        html += '<label style="display:flex;align-items:center;gap:8px;padding:6px;margin:4px 0;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:6px;cursor:pointer;">' +
                            '<input type="checkbox" class="tgcopy2-bulk-cb" value="' + iid + '" data-idx="' + i + '" ' + checked + ' style="accent-color:#22c55e;">' +
                            '<img src="' + cover + '" style="width:32px;height:48px;object-fit:cover;border-radius:4px;background:#18181b;" onerror="this.style.display=\'none\';">' +
                            '<span style="flex:1;font-size:13px;">' + t +
                            (it._isCollection ? ' <span title="Se copiará la colección (cover + mensaje)" style="background:rgba(34,197,94,0.15);color:#4ade80;border:1px solid rgba(34,197,94,0.3);border-radius:4px;font-size:9px;padding:1px 5px;white-space:nowrap;">📚 Colección</span>' : '') +
                            '</span>' +
                            (queuedIds[iid] ? '<span style="font-size:11px;color:#eab308;">en cola</span>' : '') +
                            '</label>';
                    }
                    html += '</div>';
                    content.innerHTML = html;
                    var btnRow = document.createElement('div');
                    btnRow.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
                    var btnAll = content.querySelector('.tgcopy2-bulk-all');
                    var btnNone = content.querySelector('.tgcopy2-bulk-none');
                    if (btnAll) btnAll.onclick = function() { var cbs = content.querySelectorAll('.tgcopy2-bulk-cb'); for (var a = 0; a < cbs.length; a++) cbs[a].checked = true; };
                    if (btnNone) btnNone.onclick = function() { var cbs = content.querySelectorAll('.tgcopy2-bulk-cb'); for (var a = 0; a < cbs.length; a++) cbs[a].checked = false; };
                    var send = document.createElement('button');
                    send.textContent = 'Enviar';
                    send.style.cssText = 'flex:1;padding:8px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:600;';
                    send.onclick = function() {
                        var boxes = content.querySelectorAll('.tgcopy2-bulk-cb:checked');
                        if (!boxes.length) { alert('Selecciona al menos un elemento.'); return; }
                        var sel = [];
                        for (var j = 0; j < boxes.length; j++) {
                            var idx = parseInt(boxes[j].getAttribute('data-idx'), 10);
                            if (items[idx]) sel.push(items[idx]);
                        }
                        overlay.remove();
                        showBulkDestinationPicker(sel, dests);
                    };
                    var cancel = document.createElement('button');
                    cancel.textContent = 'Cancelar';
                    cancel.style.cssText = 'padding:8px 14px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;';
                    cancel.onclick = function() { overlay.remove(); };
                    btnRow.appendChild(send);
                    btnRow.appendChild(cancel);
                    content.appendChild(btnRow);
                });
            });
        });
    }

    function showBulkDestinationPicker(items, dests) {
        api(API + '/config', {}, function(cfgRes) {
            var skipDef = !!((cfgRes && cfgRes.config) || {}).skip_if_exists_topo3;
            if (dests.length === 1) { bulkEnqueue(items, [dests[0].id], skipDef); return; }
            var lastSel = {};
            try { lastSel = JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch(e) {}
            openModal('Enviar ' + items.length + ' títulos a Canal Telegram', function(content, overlay) {
            var html = '<div class="muted" style="margin-bottom:8px;font-size:12px;color:#a1a1aa;">Se añadirán ' + items.length + ' títulos a la cola con los mismos destinos.</div>';
            for (var i = 0; i < dests.length; i++) {
                var d = dests[i];
                var checked = lastSel[d.id] ? 'checked' : '';
                html += '<label style="display:flex;align-items:center;gap:8px;padding:10px;margin:4px 0;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:6px;cursor:pointer;">' +
                    '<input type="checkbox" class="tgcopy2-dest-cb" value="' + d.id + '" ' + checked + ' style="accent-color:#22c55e;">' +
                    '<span style="flex:1;">' + d.name + '</span>' +
                    '<span style="font-size:11px;color:#a1a1aa;">' + (d.channel_title || '') + '</span></label>';
            }
            html += '<label style="display:flex;align-items:center;gap:8px;padding:10px;margin:8px 0 0 0;background:rgba(234,179,8,0.08);border:1px solid rgba(234,179,8,0.3);border-radius:6px;cursor:pointer;">' +
                '<input type="checkbox" class="tgcopy2-skip-cb" ' + (skipDef ? 'checked' : '') + ' style="accent-color:#eab308;">' +
                '<span style="flex:1;font-size:12px;">Omitir subida si el topic ya existe en el destino</span></label>';
            content.innerHTML = html;
            var btnRow = document.createElement('div');
            btnRow.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
            var enqueue = document.createElement('button');
            enqueue.textContent = 'Añadir a la cola';
            enqueue.style.cssText = 'flex:1;padding:8px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:600;';
            enqueue.onclick = function() {
                var ids = [];
                var boxes = content.querySelectorAll('.tgcopy2-dest-cb:checked');
                for (var j = 0; j < boxes.length; j++) ids.push(boxes[j].value);
                if (!ids.length) { alert('Selecciona al menos un destino.'); return; }
                var sel = {};
                for (var k = 0; k < dests.length; k++) sel[dests[k].id] = ids.indexOf(dests[k].id) >= 0;
                localStorage.setItem(LS_KEY, JSON.stringify(sel));
                overlay.remove();
                var skipBox2 = content.querySelector('.tgcopy2-skip-cb');
                bulkEnqueue(items, ids, !!(skipBox2 && skipBox2.checked));
            };
            var cancel = document.createElement('button');
            cancel.textContent = 'Cancelar';
            cancel.style.cssText = 'padding:8px 14px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;';
            cancel.onclick = function() { overlay.remove(); };
            btnRow.appendChild(enqueue);
            btnRow.appendChild(cancel);
            content.appendChild(btnRow);
            });
        });
    }

    function bulkEnqueue(items, destIds, skipFlag) {
        var i = 0, ok = 0, fail = 0;
        showToast('Encolando ' + items.length + ' títulos...');
        function next() {
            if (i >= items.length) { showToast('Añadidos ' + ok + ' a la cola' + (fail ? ' (' + fail + ' fallos)' : '')); return; }
            var it = items[i++];
            api(API + '/queue', { method: 'POST', data: {
                item_id: it.item_id || it.id,
                title: it.title || it.name || '',
                category: it.category || '',
                subcategory: it.subcategory || '',
                destination_ids: destIds,
                total_episodes: (it.episodes && it.episodes.length) || 0,
                telegram_link: it.telegram_link || '',
                skip_if_exists_topo3: !!skipFlag
            }}, function(r) { if (r && r.ok) { ok++; } else { fail++; } next(); });
        }
        next();
    }

    function escHtml(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function jobTitleHtml(j) {
        var t = j.title || '';
        var link = j.telegram_link || '';
        var titleEsc = escHtml(t);
        if (!link) return titleEsc;
        return '<a href="' + escHtml(link) + '" target="_blank" rel="noopener noreferrer" title="Abrir mensaje original en Telegram" style="color:#60a5fa;text-decoration:none;border-bottom:1px dashed rgba(96,165,250,0.4);">' + titleEsc + '</a>';
    }

    // ─── Modal de cola de trabajos ───
    function showQueueModal() {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.85);display:block;text-align:center;overflow-y:auto;padding:4vh 0;display:flex;align-items:center;justify-content:center;';
        var panel = document.createElement('div');
        panel.id = 'tgcopy2-queue-panel';
        panel.style.cssText = 'background:#0d0d0f;border:1px solid #3f3f46;border-radius:10px;padding:16px;width:95vw;max-width:640px;max-height:90vh;overflow-y:auto;color:#f4f4f5;position:relative;display:inline-block;text-align:left;vertical-align:middle;margin:0 auto;';
        // Feedback de pulsación para todos los botones del modal de cola
        var pressCss = document.createElement('style');
        pressCss.textContent = '#tgcopy2-queue-panel button{transition:transform .06s ease,box-shadow .06s ease,border-color .06s ease,background .12s ease,color .12s ease;}'
            + '#tgcopy2-queue-panel button:active{transform:scale(.94);box-shadow:inset 0 0 0 2px rgba(250,204,21,.85);}'
            + '#tgcopy2-queue-panel button.tgcopy2-loading{opacity:.85;transform:scale(.97);}'
            + '#tgcopy2-queue-panel .tgcopy2-presskey:active{border-color:#facc15;color:#facc15;}';
        panel.appendChild(pressCss);
        panel.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;padding-right:40px;"><span style="font-weight:600;font-size:15px;flex:1;">Cola de copia (TGHirayi_v2)</span></div>' +
            '<span class="close-btn" style="top:12px;right:12px;" title="Cerrar" onclick="var o=this.parentNode.parentNode; o.parentNode.removeChild(o)">&times;</span>';
        var content = document.createElement('div');
        panel.appendChild(content);
        overlay.appendChild(panel);
        document.body.appendChild(overlay);

        // Cerrar al hacer clic fuera del modal
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) {
                overlay.remove();
            }
        });

        _queue_modal = { content: content, overlay: overlay };
        window._tgcopy2RefreshQueue = function() {
            if (_queue_modal && _queue_modal.overlay && _queue_modal.overlay.parentNode) {
                refreshQueue2(_queue_modal.content, _queue_modal.overlay);
            }
        };

        // Datalist de códigos de idioma (audio/subs) para los combotext
        if (!document.getElementById('tgcopy2-langs')) {
            var dl = document.createElement('datalist');
            dl.id = 'tgcopy2-langs';
            var langs = ['spa','eng','jpn','kor','chi','fra','deu','ita','por','rus','ara','hin','tur','pol','nld','swe','nor','dan','fin','ces','ell','hun','heb','tha','vie','ind','zho'];
            for (var i = 0; i < langs.length; i++) {
                var opt = document.createElement('option');
                opt.value = langs[i];
                dl.appendChild(opt);
            }
            document.body.appendChild(dl);
        }

        refreshQueue2(content, overlay);
    }

    function refreshQueue2(content, overlay) {
        api(API + '/queue', {}, function(res) {
            // Si el usuario está editando campos (siguiente episodio, audio/subs), posponer el render
            // para no pisar su escritura (el refresh cada 2.5s reconstruiría el input).
            var activeEl = document.activeElement;
            if (activeEl && activeEl.classList &&
                (activeEl.classList.contains('tgcopy2-next-input') || activeEl.classList.contains('tgcopy2-norm-input'))) {
                if (overlay && overlay.parentNode) {
                    setTimeout(function() { refreshQueue2(content, overlay); }, 2500);
                }
                return;
            }
            var queue = (res && res.queue) || [];
            var current = res && res.current_job;
            var paused = res && res.worker_paused;
            var html = '';

            // ─── Estado del worker ───
            html += '<div style="display:flex;align-items:center;gap:8px;padding:8px;background:rgba(255,255,255,0.04);border-radius:6px;margin-bottom:8px;">';
            html += '<span style="width:10px;height:10px;border-radius:50%;background:' + (paused ? '#eab308' : '#22c55e') + ';"></span>';
            html += '<span style="flex:1;font-size:13px;">Worker: ' + (paused ? 'Pausado' : 'Activo') + '</span>';
            html += '<button onclick="window._tgcopy2ToggleWorker()" style="padding:4px 10px;background:' + (paused ? '#22c55e' : '#eab308') + ';border:none;color:#fff;border-radius:4px;cursor:pointer;font-size:12px;">' + (paused ? 'Reanudar' : 'Pausar') + '</button>';
            html += '</div>';
            // ─── Estado de archives (procesado en paralelo) ───
            var pArch = res.pending_archives || 0;
            if (pArch > 0) {
                var slotOwner = res.archive_slot_owner || null;
                var archList = res.pending_archives_info || [];
                var archTitles = [];
                for (var ai = 0; ai < archList.length; ai++) {
                    var a = archList[ai];
                    var aPhase = { processing: 'Procesando', ready_upload: 'Listo subir', uploading: 'Subiendo' }[a.phase] || a.phase || '';
                    archTitles.push('#' + a.id + ' ' + (a.title || '') + (aPhase ? ' (' + aPhase + ')' : ''));
                }
                html += '<div style="display:flex;align-items:center;gap:6px;padding:4px 8px 8px;font-size:11px;color:#fbbf24;">';
                html += '<span title="' + archTitles.join('\n') + '">\uD83D\uDCE6 Archives en proceso/por subir: ' + pArch + (archTitles.length ? ' (' + archTitles.join(' · ') + ')' : '') + '</span>';
                if (slotOwner) html += '<span>·</span><span style="color:#a1a1aa;">Recodificando: #' + slotOwner + '</span>';
                html += '</div>';
            }

            // ─── Job actual ───
            if (current && current.status === 'processing') {
                var ep = current.current_episode || 0;
                var total = current.total_episodes || 1;
                var pctGeneral = Math.round(current.progress || 0);
                var pctDownload = Math.round(current.download_progress || 0);
                var pctUpload = Math.round(current.upload_progress || 0);
                var dlSpeed = current.download_speed || 0;
                var ulSpeed = current.upload_speed || 0;
                var destCount = (current.destination_ids || []).length;
                var dests = current.destinations_detail || [];

                function fmtSpeed(bps) {
                    if (!bps || bps <= 0) return '—';
                    var mb = bps / (1024 * 1024);
                    if (mb >= 1) return mb.toFixed(1) + ' MB/s';
                    return (bps / 1024).toFixed(0) + ' KB/s';
                }
                function fmtElapsed(started, finished) {
                    // Tiempo transcurrido de la fase; congelado al llegar al 100%
                    if (!started) return '';
                    var end = finished || (Date.now() / 1000);
                    var s = Math.max(0, Math.floor(end - started));
                    var h = Math.floor(s / 3600);
                    var m = Math.floor((s % 3600) / 60);
                    var sec = s % 60;
                    if (h > 0) return (h < 10 ? '0' + h : h) + ':' + (m < 10 ? '0' + m : m) + ':' + (sec < 10 ? '0' + sec : sec);
                    return (m < 10 ? '0' + m : m) + ':' + (sec < 10 ? '0' + sec : sec);
                }
                function fmtBytes(b) {
                    if (!b || b <= 0) return '—';
                    var gb = b / (1024 * 1024 * 1024);
                    if (gb >= 1) return gb.toFixed(2) + ' GB';
                    var mb = b / (1024 * 1024);
                    if (mb >= 1) return mb.toFixed(1) + ' MB';
                    return (b / 1024).toFixed(1) + ' KB';
                }
                function _tgClientLabel(c) {
                    if (c === 'pyrogram') return 'Pyrogram';
                    if (c === 'telethon') return 'Telethon';
                    if (c === 'cache') return 'Caché';
                    return c;
                }

                html += '<div style="background:#18181b;border:1px solid #27272a;border-radius:8px;padding:12px;margin-bottom:10px;">';
                html += '<div style="font-weight:600;font-size:13px;margin-bottom:6px;">' + jobTitleHtml(current) + '</div>';

                // Info episodio
                html += '<div style="font-size:12px;color:#a1a1aa;margin-bottom:6px;">Episodio ' + ep + '/' + total + ' | ' + destCount + ' destino(s)</div>';

                // Barra general (todos los capitulos * todos los destinos)
                html += '<div style="font-size:11px;color:#a1a1aa;margin-bottom:2px;">Progreso general</div>';
                html += '<div style="background:#27272a;border-radius:4px;height:10px;overflow:hidden;margin-bottom:8px;position:relative;">';
                html += '<div style="width:' + pctGeneral + '%;height:100%;background:linear-gradient(90deg,#3b82f6,#22c55e);border-radius:4px;transition:width 0.3s;"></div>';
                html += '<span style="position:absolute;right:4px;top:0;font-size:9px;color:#fff;line-height:10px;">' + pctGeneral + '%</span>';
                html += '</div>';

                // Estado de actividad (recodificación, extracción, descarga...)
                // Durante la recodificación se muestra SOLO la barra con su % (evita duplicar texto)
                var encodePct = current.encode_progress;
                var recoding = (typeof encodePct === 'number' && encodePct > 0 && encodePct < 100);
                if (current.status_text && !recoding) {
                    html += '<div style="font-size:11px;color:#eab308;margin-bottom:8px;">' + escHtml(current.status_text) + '</div>';
                }

                // Barra de recodificación (ffmpeg 2-pass) en vivo
                if (recoding) {
                    // Métricas reales de ffmpeg (del fichero -progress)
                    var encSize = current.encode_size || 0;
                    var encSpeed = current.encode_speed || 0;
                    var encMeta = [];
                    if (encSize > 0) encMeta.push(fmtBytes(encSize));
                    if (encSpeed > 0) encMeta.push(encSpeed.toFixed(1) + 'x');
                    html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">';
                    html += '<span style="font-size:11px;color:#eab308;white-space:nowrap;font-weight:600;">Recodificando ' + Math.round(encodePct) + '%</span>';
                    if (encMeta.length) html += '<span style="font-size:10px;color:#a1a1aa;white-space:nowrap;">(' + encMeta.join(' · ') + ')</span>';
                    html += '<span style="flex:1;"></span>';
                    if (res.encode_active && res.encode_job_id && String(res.encode_job_id) === String(current.id)) {
                        html += '<button onclick="window._tgcopy2KillEncode(\'' + current.id + '\')" title="Mata el proceso ffmpeg actual. Se descarta el pase en curso y luego se re-encoda." style="background:none;border:1px solid #ef4444;color:#ef4444;border-radius:4px;cursor:pointer;font-size:10px;padding:2px 8px;white-space:nowrap;">✕ Matar encode</button>';
                    }
                    html += '</div>';
                    html += '<div style="background:#27272a;border-radius:3px;height:6px;overflow:hidden;margin-bottom:8px;">';
                    html += '<div style="width:' + encodePct + '%;height:100%;background:#eab308;border-radius:3px;transition:width 0.5s;"></div>';
                    html += '</div>';
                }

                // Barra de descarga (azul)
                html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">';
                var dlMeta = [];
                if (current.dl_client) dlMeta.push(escHtml(_tgClientLabel(current.dl_client)));
                dlMeta.push(fmtSpeed(dlSpeed));
                var dlElapsed = fmtElapsed(current.download_started, current.download_finished);
                if (dlElapsed) dlMeta.push(dlElapsed);
                html += '<span style="font-size:11px;color:#60a5fa;">\u2193 Descarga (' + dlMeta.join(' \u2022 ') + ')</span>';
                html += '<span style="flex:1;"></span>';
                html += '<span style="font-size:11px;color:#a1a1aa;">' + pctDownload + '%</span>';
                html += '</div>';
                html += '<div style="background:#27272a;border-radius:4px;height:6px;overflow:hidden;margin-bottom:6px;">';
                html += '<div style="width:' + pctDownload + '%;height:100%;background:#3b82f6;border-radius:4px;transition:width 0.3s;"></div>';
                html += '</div>';

                // Barra de subida (verde) con marcadores por destino
                html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">';
                var ulMeta = [];
                if (current.ul_client) ulMeta.push(escHtml(_tgClientLabel(current.ul_client)));
                ulMeta.push(fmtSpeed(ulSpeed));
                var ulElapsed = fmtElapsed(current.upload_started, current.upload_finished);
                if (ulElapsed) ulMeta.push(ulElapsed);
                html += '<span style="font-size:11px;color:#4ade80;">\u2191 Subida (' + ulMeta.join(' \u2022 ') + ')</span>';
                html += '<span style="flex:1;"></span>';
                html += '<span style="font-size:11px;color:#a1a1aa;">' + pctUpload + '%</span>';
                html += '</div>';
                html += '<div style="background:#27272a;border-radius:4px;height:6px;overflow:hidden;margin-bottom:4px;position:relative;">';
                html += '<div style="width:' + pctUpload + '%;height:100%;background:#22c55e;border-radius:4px;transition:width 0.3s;"></div>';
                // Marcadores por destino
                if (dests.length > 1) {
                    for (var di = 0; di < dests.length; di++) {
                        var d = dests[di];
                        if (d.uploaded) {
                            var left = ((di + 1) / (dests.length + 1)) * 100;
                            html += '<div style="position:absolute;left:' + left + '%;top:0;width:3px;height:100%;background:#fff;border-radius:1px;opacity:0.7;"></div>';
                        }
                    }
                }
                html += '</div>';
                // Nombres de destinos
                if (dests.length > 1) {
                    html += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:2px;">';
                    for (var di = 0; di < dests.length; di++) {
                        var d = dests[di];
                        var dotColor = d.uploaded ? '#22c55e' : '#52525b';
                        html += '<span style="font-size:10px;color:#a1a1aa;display:flex;align-items:center;gap:3px;"><span style="width:6px;height:6px;border-radius:50%;background:' + dotColor + ';display:inline-block;"></span>' + (d.name || '#' + (di+1)) + '</span>';
                    }
html += '</div>';
            }
            }
            var active = [];
            var done = [];
            for (var i = 0; i < queue.length; i++) {
                var st = queue[i].status;
                if (st === 'completed' || st === 'error' || st === 'skipped') {
                    done.push(queue[i]);
                } else {
                    active.push(queue[i]);
                }
            }

            if (active.length > 0) {
                html += '<div style="font-size:12px;color:#a1a1aa;margin-bottom:4px;">Pendientes (' + active.length + ')</div>';
                for (var i = 0; i < active.length; i++) {
                    html += renderJobRow(active[i], current);
                }
            } else {
                html += '<div style="color:#a1a1aa;text-align:center;padding:12px;font-size:13px;">No hay trabajos pendientes.</div>';
            }

            // Finalizados (collapsible, estado persistente entre refrescos)
            if (done.length > 0) {
                var doneId = 'tgcopy2-done-list';
                var doneOpen = window._queue_done_expanded;
                html += '<div style="margin-top:8px;cursor:pointer;font-size:12px;color:#a1a1aa;display:flex;align-items:center;gap:4px;" onclick="var d=document.getElementById(\'' + doneId + '\');var open=(d.style.display==\'none\');d.style.display=open?\'block\':\'none\';var s=this.querySelector(\'span\');s.textContent=open?\'\u25BC \':\'\u25B6 \';window._queue_done_expanded=open;">';
                html += '<span>' + (doneOpen ? '&#x25BC; ' : '&#x25B6; ') + '</span>Finalizados (' + done.length + ')</div>';
                html += '<div style="text-align:right;margin:2px 0 4px;"><button onclick="window._tgcopy2CleanCompleted()" style="background:none;border:1px solid #ef4444;color:#ef4444;border-radius:4px;cursor:pointer;font-size:11px;padding:3px 8px;">Limpiar finalizados</button></div>';
                html += '<div id="' + doneId + '" style="display:' + (doneOpen ? 'block' : 'none') + ';">';
                for (var i = 0; i < done.length; i++) {
                    html += renderJobRow(done[i], current, true);
                }
                html += '</div>';
            }

            content.innerHTML = html;
            if (overlay && overlay.parentNode) {
                setTimeout(function() { refreshQueue2(content, overlay); }, 2500);
            }
        });
    }

    // Helper compartido (scope de módulo) para formatear bytes
    function fmtBytes(b) {
        if (!b || b <= 0) return '—';
        var gb = b / (1024 * 1024 * 1024);
        if (gb >= 1) return gb.toFixed(2) + ' GB';
        var mb = b / (1024 * 1024);
        if (mb >= 1) return mb.toFixed(1) + ' MB';
        return (b / 1024).toFixed(1) + ' KB';
    }

    // ─── Helper para renderizar fila de job ───
    function renderJobRow(j, current, isDone) {
        var isCurrent = current && current.id === j.id;
        var pausedCls = j.paused ? 'opacity:0.5;' : '';
        var bgCls = isCurrent ? 'background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);' : 'background:rgba(255,255,255,0.04);';
        if (j.status === 'completed') bgCls += 'border-left:3px solid #22c55e;';
        if (j.status === 'skipped') bgCls += 'border-left:3px solid #eab308;';
        if (j.status === 'error') bgCls += 'border-left:3px solid #ef4444;';

        var h = '';
        h += '<div style="display:flex;align-items:center;gap:6px;padding:8px;margin:3px 0;border-radius:6px;' + bgCls + pausedCls + '">';

        if (!isDone) {
            h += '<div style="display:flex;flex-direction:column;gap:1px;flex-shrink:0;">';
            h += '<button onclick="window._tgcopy2Move(\'' + j.id + '\',\'top\')" title="Al inicio" style="background:none;border:none;color:#a1a1aa;cursor:pointer;font-size:9px;padding:0;line-height:1;">&#9650;&#9650;</button>';
            h += '<button onclick="window._tgcopy2Move(\'' + j.id + '\',\'up\')" title="Subir" style="background:none;border:none;color:#a1a1aa;cursor:pointer;font-size:9px;padding:0;line-height:1;">&#9650;</button>';
            h += '<button onclick="window._tgcopy2Move(\'' + j.id + '\',\'down\')" title="Bajar" style="background:none;border:none;color:#a1a1aa;cursor:pointer;font-size:9px;padding:0;line-height:1;">&#9660;</button>';
            h += '<button onclick="window._tgcopy2Move(\'' + j.id + '\',\'bottom\')" title="Al final" style="background:none;border:none;color:#a1a1aa;cursor:pointer;font-size:9px;padding:0;line-height:1;">&#9660;&#9660;</button>';
            h += '</div>';
        }

        h += '<div style="flex:1;min-width:0;">';
        h += '<div style="display:flex;align-items:center;gap:6px;font-size:13px;">';
        h += '<span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;">' + jobTitleHtml(j) + '</span>';
        if ((j.total_episodes || 0) > 1) {
            h += '<span onclick="window._tgcopy2Episodes(\'' + j.id + '\')" title="Ver episodios y elegir cuáles copiar" style="cursor:pointer;font-size:11px;background:rgba(59,130,246,0.15);color:#93c5fd;border:1px solid rgba(59,130,246,0.4);border-radius:4px;padding:1px 5px;white-space:nowrap;">🎞️ ' + j.total_episodes + '</span>';
        }
        if (j.is_archive) {
            h += '<span title="Job de archives comprimidos" style="background:rgba(251,191,36,0.15);color:#fbbf24;border:1px solid rgba(251,191,36,0.3);border-radius:4px;font-size:9px;padding:1px 5px;white-space:nowrap;">\uD83D\uDCE6 Archive</span>';
            var phase = j.archive_phase;
            var phaseLabels = { download: 'Descargando', processing: 'Procesando', ready_upload: 'Listo subir', uploading: 'Subiendo' };
            if (phaseLabels[phase]) {
                var pcolor = '#fbbf24';
                if (phase === 'processing') pcolor = '#a78bfa';
                else if (phase === 'uploading' || phase === 'ready_upload') pcolor = '#4ade80';
                h += '<span style="background:rgba(0,0,0,0.35);color:' + pcolor + ';border:1px solid ' + pcolor + ';border-radius:4px;font-size:9px;padding:1px 5px;white-space:nowrap;">' + phaseLabels[phase] + '</span>';
            }
        }
        if (!isDone) {
            h += '<button onclick="window._tgcopy2EditCover(\'' + j.id + '\')" title="Editar cover" class="tgcopy2-presskey" style="background:none;border:1px solid #3f3f46;color:#a1a1aa;border-radius:4px;cursor:pointer;font-size:10px;padding:1px 5px;white-space:nowrap;">Cover</button>';
        }
        h += '</div>';
        if (j.progress > 0 && j.progress < 100) {
            var p = Math.round(j.progress);
            h += '<div style="background:#27272a;border-radius:3px;height:4px;overflow:hidden;margin-top:3px;"><div style="width:' + p + '%;height:100%;background:linear-gradient(90deg,#3b82f6,#22c55e);border-radius:3px;"></div></div>';
        }
        // Métricas de encode en vivo para archives en procesado en 2º plano
        if (j.archive_phase === 'processing') {
            var ep = j.encode_progress || 0;
            var rem = [];
            if (j.encode_size > 0) rem.push(fmtBytes(j.encode_size));
            if (j.encode_speed > 0) rem.push(j.encode_speed.toFixed(1) + 'x');
            h += '<div style="display:flex;align-items:center;gap:4px;margin-top:2px;">';
            h += '<span style="font-size:10px;color:#a78bfa;white-space:nowrap;">\uD83D\uDD1F Recodificando ' + Math.round(ep) + '%</span>';
            if (rem.length) h += '<span style="font-size:10px;color:#a1a1aa;white-space:nowrap;">(' + rem.join(' · ') + ')</span>';
            h += '</div>';
            h += '<div style="background:#27272a;border-radius:3px;height:5px;overflow:hidden;margin-top:2px;"><div style="width:' + Math.min(ep, 100) + '%;height:100%;background:#a78bfa;border-radius:3px;transition:width 0.5s;"></div></div>';
        }
        if (j.status === 'completed') h += '<div style="font-size:10px;color:#22c55e;">Completado</div>';
        if (j.status === 'skipped') h += '<div style="font-size:10px;color:#eab308;">' + escHtml(j.status_text || 'Omitido') + '</div>';
        if (j.status === 'error') h += '<div style="font-size:10px;color:#ef4444;">Error: ' + (j.error || '') + '</div>';

        // Información de episodios: total y siguiente a procesar (editable en jobs activos)
        var processed = (j.current_episode && j.current_episode > 0) ? (j.current_episode - 1) : 0;
        var totalEps = j.total_episodes || '?';
        h += '<div style="display:flex;align-items:center;gap:6px;margin-top:3px;font-size:11px;color:#a1a1aa;">';
        h += '<span>Total: ' + totalEps + '</span>';
        h += '<span>·</span>';
        h += '<span>Procesados: ' + processed + '</span>';
        h += '<span>·</span>';
        h += '<label title="Omitir subida si el topic ya existe en el destino" style="display:flex;align-items:center;gap:4px;cursor:pointer;"><input type="checkbox" ' + (j.skip_if_exists_topo3 ? 'checked' : '') + ' onchange="window._tgcopy2SetSkip(\'' + j.id + '\',this.checked)" style="accent-color:#eab308;"><span>Omitir si existe</span></label>';
        if (!isDone) {
            var nextVal = (typeof j.next_episode === 'number' && j.next_episode > 0) ? j.next_episode : 'auto';
            h += '<span>·</span><span>Siguiente:</span>';
            h += '<input type="text" class="tgcopy2-next-input" value="' + nextVal + '" onfocus="this.select()" onchange="window._tgcopy2SetNext(\'' + j.id + '\',this.value)" onkeydown="if(event.key===\'Enter\'){this.blur();return false;}" style="width:52px;background:#18181b;border:1px solid #3f3f46;color:#f4f4f5;border-radius:4px;padding:1px 4px;font-size:11px;">';
        }
        h += '</div>';

        // Audio / subtítulos de la normalización MP4 (combotext editable + lista)
        if (!isDone) {
            var audioVal = j.audio_lang || '';
            var subVal = j.sub_lang || '';
            h += '<div style="display:flex;align-items:center;gap:6px;margin-top:3px;font-size:11px;color:#a1a1aa;">';
            h += '<span>Audio:</span><input type="text" list="tgcopy2-langs" class="tgcopy2-norm-input" value="' + audioVal + '" placeholder="original" onchange="window._tgcopy2SetNorm(\'' + j.id + '\',\'audio_lang\',this.value)" style="width:64px;background:#18181b;border:1px solid #3f3f46;color:#f4f4f5;border-radius:4px;padding:1px 4px;font-size:11px;">';
            h += '<span>Subs:</span><input type="text" list="tgcopy2-langs" class="tgcopy2-norm-input" value="' + subVal + '" placeholder="ninguno" onchange="window._tgcopy2SetNorm(\'' + j.id + '\',\'sub_lang\',this.value)" style="width:64px;background:#18181b;border:1px solid #3f3f46;color:#f4f4f5;border-radius:4px;padding:1px 4px;font-size:11px;">';
            h += '</div>';
        }
        // Archive protegido con contraseña: campo password + reintentar
        if (j.status === 'awaiting_password') {
            h += '<div style="display:flex;align-items:center;gap:6px;margin-top:3px;font-size:11px;color:#fbbf24;">';
            h += '<span>Contrase&ntilde;a:</span>';
            h += '<input type="text" class="tgcopy2-pwd-input" placeholder="contrase&ntilde;a" onchange="window._tgcopy2SetPassword(\'' + j.id + '\',this.value)" style="flex:1;background:#18181b;border:1px solid #fbbf24;color:#f4f4f5;border-radius:4px;padding:1px 4px;font-size:11px;">';
            h += '<button onclick="window._tgcopy2RetryPassword(\'' + j.id + '\')" title="Reintentar con la contrase&ntilde;a" style="background:none;border:1px solid #fbbf24;color:#fbbf24;border-radius:4px;cursor:pointer;font-size:11px;padding:2px 6px;">Reintentar</button>';
            h += '</div>';
        }
        h += '</div>';

        if (!isDone) {
            var dCount = (j.destination_ids || []).length;
            h += '<span onclick="window._tgcopy2ShowDestinos(\'' + j.id + '\')" title="Ver/editar destinos" style="font-size:11px;color:#a1a1aa;cursor:pointer;padding:2px 6px;border:1px solid #3f3f46;border-radius:4px;white-space:nowrap;">' + dCount + ' dest</span>';
            if (j.paused) h += '<span style="font-size:10px;color:#eab308;font-weight:600;">PAUSADO</span>';
            if (j.archive_phase === 'processing') h += '<button onclick="window._tgcopy2KillEncode(\'' + j.id + '\')" title="Matar el ffmpeg en curso y re-encodar" style="background:none;border:1px solid #ef4444;color:#ef4444;border-radius:4px;cursor:pointer;font-size:10px;padding:2px 6px;white-space:nowrap;">✕ Kill</button>';
            h += '<button onclick="window._tgcopy2TogglePause(\'' + j.id + '\',' + (!j.paused) + ')" title="' + (j.paused ? 'Reanudar' : 'Pausar') + '" style="background:none;border:1px solid #3f3f46;color:#fff;border-radius:4px;cursor:pointer;font-size:11px;padding:2px 6px;">' + (j.paused ? '&#9654;' : '&#10074;&#10074;') + '</button>';
        }
        if (isDone) {
            h += '<button onclick="window._tgcopy2Requeue(\'' + j.id + '\')" title="Volver a meter en la cola" style="background:none;border:1px solid #22c55e;color:#22c55e;border-radius:4px;cursor:pointer;font-size:11px;padding:2px 6px;">&#8635;</button>';
        }
        if (j.is_archive) {
            h += '<button onclick="window._tgcopy2OpenLog(\'' + j.id + '\')" title="Ver el log (terminal) del reprocesamiento del archive" style="background:none;border:1px solid #3f3f46;color:#a1a1aa;border-radius:4px;cursor:pointer;font-size:11px;padding:2px 6px;">&#8981; Log</button>';
        }
        h += '<button onclick="window._tgcopy2Remove(\'' + j.id + '\')" style="background:none;border:1px solid #ef4444;color:#ef4444;border-radius:4px;cursor:pointer;font-size:11px;padding:2px 6px;">&#10005;</button>';
        h += '</div>';
        return h;
    }
    window._tgcopy2ShowDestinos = function(jobId) {
        api(API + '/queue', {}, function(res) {
            var queue = (res && res.queue) || [];
            var job = null;
            for (var i = 0; i < queue.length; i++) {
                if (queue[i].id === jobId) { job = queue[i]; break; }
            }
            if (!job) return;
            api(API + '/destinations', {}, function(res2) {
                var allDests = (res2 && res2.destinations) || [];
                var ids = job.destination_ids || [];
                var html = '<div style="font-weight:600;margin-bottom:8px;">Destinos para: ' + (job.title || '') + '</div>';
                for (var i = 0; i < allDests.length; i++) {
                    var d = allDests[i];
                    var checked = ids.indexOf(d.id) >= 0 ? 'checked' : '';
                    html += '<label style="display:flex;align-items:center;gap:8px;padding:6px;margin:2px 0;background:rgba(255,255,255,0.04);border-radius:4px;cursor:pointer;">' +
                        '<input type="checkbox" class="tgcopy2-jobdest-cb" value="' + d.id + '" ' + checked + ' style="accent-color:#22c55e;">' +
                        '<span style="flex:1;font-size:13px;">' + d.name + '</span>' +
                        '</label>';
                }
                html += '<button onclick="window._tgcopy2SaveJobDestinos(\'' + jobId + '\')" style="margin-top:8px;padding:6px 14px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-size:13px;width:100%;">Guardar</button>';
                var overlay = document.createElement('div');
                overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;';
                var panel = document.createElement('div');
                panel.style.cssText = 'background:#0d0d0f;border:1px solid #3f3f46;border-radius:10px;padding:16px;min-width:300px;color:#f4f4f5;';
                panel.innerHTML = html;
                var close = document.createElement('button');
                close.textContent = 'Cerrar';
                close.style.cssText = 'margin-top:8px;padding:4px 10px;background:#27272a;border:1px solid #3f3f46;color:#fff;border-radius:4px;cursor:pointer;float:right;';
                close.onclick = function() { overlay.remove(); };
                panel.appendChild(close);
                overlay.appendChild(panel);
                document.body.appendChild(overlay);
            });
        });
    };

    window._tgcopy2SaveJobDestinos = function(jobId) {
        var ids = [];
        var boxes = document.querySelectorAll('.tgcopy2-jobdest-cb:checked');
        for (var i = 0; i < boxes.length; i++) ids.push(boxes[i].value);
        api(API + '/queue/' + jobId + '/destinations', { method: 'PUT', data: { destination_ids: ids } }, function(r) {
            if (r && r.ok) showToast('Destinos actualizados');
        });
    };

    // ─── Funciones globales para botones inline ───
    window._tgcopy2ToggleWorker = function() {
        api(API + '/worker/toggle', { method: 'POST' }, function() {});
    };

    window._tgcopy2Move = function(jobId, dir) {
        api(API + '/queue/' + jobId + '/move', { method: 'PUT', data: { direction: dir } }, function() {});
    };

    window._tgcopy2TogglePause = function(jobId, paused) {
        api(API + '/queue/' + jobId + '/pause', { method: 'PUT', data: { paused: paused } }, function() {});
    };

    // Matar el ffmpeg en curso de un job (solo admin; exige confirmación)
    window._tgcopy2KillEncode = function(jobId) {
        var ok = confirm('¿Matar el proceso de recodificación del job #' + jobId + '?\n\nSe descarta el pase en curso (no se pierde nada persistido) y se volverá a encodar desde el inicio al retomar. Solo para problemas de rendimiento/cuelgues.');
        if (!ok) return;
        api(API + '/queue/' + jobId + '/kill-encode', { method: 'POST' }, function(r) {
            showToast((r && r.ok) ? 'Proceso ffmpeg terminado' : 'No había proceso activo para ese job');
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    window._tgcopy2Remove = function(jobId) {
        api(API + '/queue/' + jobId, { method: 'DELETE' }, function() {
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    // Ver el log (terminal) del reprocesamiento de un archive
    window._tgcopy2OpenLog = function(jobId) {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;';
        var panel = document.createElement('div');
        panel.style.cssText = 'background:#0d0d0f;border:1px solid #3f3f46;border-radius:10px;padding:16px;min-width:360px;max-width:640px;width:90%;max-height:80vh;color:#f4f4f5;display:flex;flex-direction:column;';
        panel.innerHTML = '<div style="font-weight:600;margin-bottom:8px;">Log del job #' + jobId + '</div>' +
            '<div id="tgcopy2-log-content" style="flex:1;overflow-y:auto;background:#09090b;border:1px solid #27272a;border-radius:6px;padding:8px;font-family:Consolas,monospace;font-size:11px;white-space:pre-wrap;word-break:break-word;color:#a1f7a1;min-height:200px;max-height:60vh;">Cargando...</div>' +
            '<div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center;">' +
            '<span style="font-size:10px;color:#71717a;">En memoria (últimas 800 líneas) &middot; se vacía al reiniciar el gateway</span>' +
            '<button id="tgcopy2-log-close" style="padding:4px 12px;background:#27272a;border:1px solid #3f3f46;color:#fff;border-radius:4px;cursor:pointer;">Cerrar</button></div>';
        overlay.appendChild(panel);
        document.body.appendChild(overlay);
        var content = panel.querySelector('#tgcopy2-log-content');
        var closed = false;
        var timer = setInterval(function() {
            if (closed) { clearInterval(timer); return; }
            api(API + '/queue/' + jobId + '/log', {}, function(r) {
                if (closed || !r) return;
                var lines = (r.lines || []).join('\n') || '(sin log para este job)';
                content.textContent = lines;
                content.scrollTop = content.scrollHeight;
            });
        }, 2000);
        panel.querySelector('#tgcopy2-log-close').onclick = function() { closed = true; clearInterval(timer); overlay.remove(); };
        overlay.onclick = function(e) { if (e.target === overlay) { closed = true; clearInterval(timer); overlay.remove(); } };
        api(API + '/queue/' + jobId + '/log', {}, function(r) {
            if (closed || !r) return;
            var lines = (r.lines || []).join('\n') || '(sin log para este job)';
            content.textContent = lines;
            content.scrollTop = content.scrollHeight;
        });
    };

    // Guardar audio/sub de normalización de un job
    window._tgcopy2SetNorm = function(jobId, field, value) {
        var v = String(value || '').trim();
        var data = {};
        data[field] = v;
        api(API + '/queue/' + jobId + '/normalize', { method: 'PUT', data: data }, function(r) {
            if (r && r.ok) showToast((field === 'audio_lang' ? 'Audio' : 'Subs') + ': ' + (v || 'original'));
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    window._tgcopy2SetSkip = function(jobId, value) {
        api(API + '/queue/' + jobId + '/skip-exists', { method: 'PUT', data: { skip_if_exists_topo3: !!value } }, function(r) {
            if (r && r.ok) showToast(value ? 'Omitir si existe: activado' : 'Omitir si existe: desactivado');
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    // ─── Modal de episodios: ver, elegir cuáles copiar y cortar desde uno ───
    window._tgcopy2Episodes = function(jobId) {
        api(API + '/queue/' + jobId + '/episodes', {}, function(res) {
            if (!res || !res.ok) { showToast('No se pudieron cargar los episodios'); return; }
            var eps = res.episodes || [];
            var isArch = !!res.is_archive;
            var stateColor = { pendiente: '#a1a1aa', 'en curso': '#60a5fa', procesado: '#22c55e', omitido: '#eab308', fallido: '#ef4444' };
            var resumeFrom = parseInt(res.resume_from || 0, 10) || 0;
            var nextOv = parseInt(res.next_episode || 0, 10) || 0;
            window._tgcopy2EpModal = openModal('Episodios · ' + (res.title || ('Job #' + jobId)) + ' (' + eps.length + ')' + (nextOv > 0 ? ' · Reanuda desde ep. ' + nextOv : ''), function(content, overlay) {
                var html = '<div style="max-height:50vh;overflow-y:auto;">';
                for (var i = 0; i < eps.length; i++) {
                    var e = eps[i];
                    var cb = '';
                    if (!isArch) {
                        cb = '<input type="checkbox" class="tgcopy2-ep-cb" value="' + e.msg_id + '" ' + (e.in_scope ? 'checked' : '') + ' style="accent-color:#22c55e;">';
                    }
                    var isPrev = resumeFrom > 0 && e.n < resumeFrom;
                    var dispState = isPrev ? '⏭ previo' : (e.state || '');
                    var dispColor = isPrev ? '#71717a' : (stateColor[e.state] || '#a1a1aa');
                    var prevTitle = isPrev ? ' title="Anterior al inicio efectivo: no se procesará salvo que bajes el Siguiente"' : '';
                    html += '<div style="display:flex;align-items:center;gap:8px;padding:6px;margin:4px 0;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:6px;' + (isPrev ? 'opacity:0.45;' : '') + '">' +
                        cb +
                        '<span style="font-size:11px;color:#a1a1aa;min-width:34px;">#' + e.n + '</span>' +
                        '<span style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escHtml(e.file_name || '') + '">' + escHtml(e.file_name || ('Episodio ' + e.n)) + '</span>' +
                        '<span style="font-size:11px;color:#a1a1aa;white-space:nowrap;">' + fmtBytes(e.file_size) + '</span>' +
                        '<span style="font-size:10px;color:' + dispColor + ';white-space:nowrap;"' + prevTitle + '>' + escHtml(dispState) + '</span>' +
                        '<button title="Cortar desde aquí: crea job pausado al final con este episodio en adelante y lo quita de este" onclick="window._tgcopy2Split(\'' + jobId + '\',' + e.msg_id + ',' + e.n + ')" style="background:none;border:1px solid #3f3f46;color:#f4f4f5;border-radius:4px;cursor:pointer;font-size:11px;padding:2px 6px;white-space:nowrap;">✂️</button>' +
                        '</div>';
                }
                html += '</div>';
                content.innerHTML = html;
                var btnRow = document.createElement('div');
                btnRow.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
                if (!isArch) {
                    var save = document.createElement('button');
                    save.textContent = 'Guardar selección';
                    save.style.cssText = 'flex:1;padding:8px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:600;';
                    save.onclick = function() {
                        var ids = [];
                        var boxes = content.querySelectorAll('.tgcopy2-ep-cb:checked');
                        for (var j = 0; j < boxes.length; j++) ids.push(boxes[j].value);
                        api(API + '/queue/' + jobId + '/episodes', { method: 'PUT', data: { checked_msg_ids: ids } }, function(r) {
                            if (r && r.ok) showToast('Selección guardada');
                            else showToast('Error al guardar');
                            overlay.remove();
                            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
                        });
                    };
                    btnRow.appendChild(save);
                }
                var close = document.createElement('button');
                close.textContent = 'Cerrar';
                close.style.cssText = 'padding:8px 14px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;';
                close.onclick = function() { overlay.remove(); };
                btnRow.appendChild(close);
                content.appendChild(btnRow);
            });
        });
    };

    window._tgcopy2Split = function(jobId, msgId, epNum) {
        if (!confirm('Cortar desde el episodio ' + epNum + ':\ncrea un job pausado al final con ese episodio en adelante (título = primer fichero, cover genérico) y lo quita de este job.')) return;
        api(API + '/queue/' + jobId + '/split', { method: 'POST', data: { from_msg_id: msgId } }, function(r) {
            if (r && r.ok) showToast('Job #' + r.job_id + ' creado al final (pausado)');
            else showToast('Error al cortar: ' + ((r && r.detail) || 'desconocido'));
            try {
                if (window._tgcopy2EpModal && window._tgcopy2EpModal.overlay && window._tgcopy2EpModal.overlay.parentNode) {
                    window._tgcopy2EpModal.overlay.parentNode.removeChild(window._tgcopy2EpModal.overlay);
                }
                window._tgcopy2EpModal = null;
            } catch (e) {}
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    // Editar cover de un job (modal con plantilla editable arriba y resultado resuelto abajo)
    window._tgcopy2EditCover = function(jobId) {
        var btn = event && event.target;
        var clock = null;
        var secs = 0;
        if (btn && btn.tagName === 'BUTTON') {
            btn.classList.add('tgcopy2-loading');
            btn.disabled = true;
            btn.textContent = 'Cover...';
            clock = setInterval(function() {
                secs++;
                btn.textContent = 'Cover... ' + secs + 's';
            }, 1000);
        }
        var done = function() {
            if (clock) clearInterval(clock);
            if (btn && btn.parentNode) {
                btn.classList.remove('tgcopy2-loading');
                btn.disabled = false;
                btn.textContent = 'Cover';
            }
        };
        api(API + '/queue/' + jobId + '/cover', {}, function(res) {
            done();
            if (!res) { showToast('No se pudo obtener el cover'); return; }
            // Mismo editor que el enriquecedor: propaga al registry compartido
            // (catálogo/hero) y al volver se deja snapshot en el job.
            var _iid2 = res.item_id || '';
            if (_iid2 && _iid2.indexOf('COL-') !== 0 && window.Enricher && window.Enricher.open) {
                window.Enricher.open(
                    { item_id: _iid2, category: res.category || '', subcategory: res.subcategory || '', title: res.title || '' },
                    { onDone: function(r) {
                        var payload = { cover_text: (r && r.cover_text) || '' };
                        if (r && r.catalog_title) payload.title = r.catalog_title;
                        api(API + '/queue/' + jobId + '/cover', { method: 'PUT', data: payload }, function(rr) {
                            if (rr && rr.ok) showToast('Cover guardado' + (r && r.catalog_title ? '. Título: ' + r.catalog_title : ''));
                            else showToast('Error al guardar cover en el job');
                            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
                        });
                    } }
                );
                return;
            }
            // Fallback: editor simple de la cola (enriquecedor deshabilitado o job COL-).
            var template = res.template || '';
            var preview = res.text || '';
            var imageB64 = res.image || null;
            var category = res.category || '';
            var subcategory = res.subcategory || '';
            var title = res.title || '';
            var useEnricherCover = res.use_enricher_cover !== false;
            var savedDetails = (res.details && typeof res.details === 'object') ? res.details : null;
            var selectedTitle = null;  // título del candidato elegido en el enriquecedor
            var selectedDetails = savedDetails;  // detalles completos del candidato (para resolver tags al enviar)

            var overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;';
            var panel = document.createElement('div');
            panel.style.cssText = 'background:#0d0d0f;border:1px solid #3f3f46;border-radius:10px;padding:16px;width:90vw;max-width:680px;max-height:92vh;overflow-y:auto;color:#f4f4f5;';
            var html = '<div style="font-weight:600;margin-bottom:10px;">Editar cover</div>';

            // Imagen actual (cover original), a la izquierda si hay espacio
            if (imageB64) {
                html += '<div style="display:flex;gap:12px;margin-bottom:10px;align-items:flex-start;">';
                html += '<div style="flex-shrink:0;width:140px;max-width:35%;">';
                html += '<img id="cover-img" src="data:image/jpeg;base64,' + imageB64 + '" style="width:100%;border-radius:8px;border:1px solid #3f3f46;display:block;">';
                html += '<label id="cover-use-enricher-label" style="display:flex;align-items:center;gap:6px;margin-top:8px;font-size:0.72rem;color:#a1a1aa;cursor:pointer;user-select:none;"><input type="checkbox" id="cover-use-enricher" ' + (useEnricherCover ? 'checked' : '') + '> Usar cover descargado</label>';
                html += '</div>';
                html += '<div style="flex:1;min-width:0;">';
            } else {
                html += '<div style="display:flex;gap:12px;margin-bottom:10px;align-items:flex-start;">';
                html += '<div style="flex-shrink:0;width:140px;max-width:35%;">';
                html += '<div id="cover-img-box" style="display:none;"><img id="cover-img" style="width:100%;border-radius:8px;border:1px solid #3f3f46;"></div>';
                html += '<label id="cover-use-enricher-label" style="display:flex;align-items:center;gap:6px;margin-top:8px;font-size:0.72rem;color:#a1a1aa;cursor:pointer;user-select:none;"><input type="checkbox" id="cover-use-enricher" ' + (useEnricherCover ? 'checked' : '') + '> Usar cover descargado</label>';
                html += '</div>';
                html += '<div style="flex:1;min-width:0;">';
            }

            // Búsqueda en enriquecedor
            html += '<label style="font-size:0.75rem;color:#a1a1aa;">Buscar en enriquecedor</label>';
            html += '<div style="display:flex;gap:6px;margin-top:4px;">';
            html += '<input type="text" id="cover-search-query" value="' + title + '" placeholder="Titulo a buscar" style="flex:1;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;">';
            html += '<button id="cover-search-btn" style="padding:6px 12px;background:#06b6d4;border:none;color:#fff;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:600;white-space:nowrap;">Buscar</button>';
            html += '</div>';
            html += '<div id="cover-candidates" style="margin-top:6px;"></div>';

            // Plantilla (editable, con tags)
            html += '<label style="font-size:0.75rem;color:#a1a1aa;margin-top:10px;display:block;">Plantilla</label>';
            html += '<div style="font-size:0.7rem;color:#71717a;margin:2px 0 4px;">Tags: {title} {tagtitle} {episodes} · f-tags: {ftitle} {ftagtitle} {fyear} {frating} {fgenres} {fsinopsis} {fepisodes} (solo si hay dato) · Enter para saltos de l&iacute;nea</div>';
            html += '<textarea id="cover-template" style="width:100%;height:120px;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;resize:vertical;">' + template + '</textarea>';

            // Resultado (resuelto en vivo, solo lectura)
            html += '<label style="font-size:0.75rem;color:#a1a1aa;margin-top:10px;display:block;">Resultado</label>';
            html += '<textarea id="cover-preview" readonly style="width:100%;height:130px;background:#18181b;border:1px solid #3f3f46;border-radius:6px;padding:8px;color:#a1a1aa;font-size:0.8rem;box-sizing:border-box;resize:vertical;margin-top:4px;white-space:pre-wrap;">' + preview + '</textarea>';
            html += '<div style="margin-top:6px;">';
            html += '<label style="font-size:0.7rem;color:#71717a;cursor:pointer;user-select:none;"><input type="checkbox" id="cover-debug"> Debug: n&uacute;mero por tag</label>';
            html += '</div>';
            html += '<div id="cover-debug-list" style="display:none;margin-top:6px;background:#09090b;border:1px solid #27272a;border-radius:6px;padding:8px;font-size:0.7rem;color:#a1a1aa;"></div>';
            html += '</div></div>';  // cierre del flex
            panel.innerHTML = html;

            var btnRow = document.createElement('div');
            btnRow.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
            var save = document.createElement('button');
            save.textContent = 'Guardar';
            save.style.cssText = 'flex:1;padding:8px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:600;';
            save.onclick = function() {
                var val = document.getElementById('cover-template').value;
                var payload = { cover_text: val };
                var cb = document.getElementById('cover-use-enricher');
                if (cb) payload.use_enricher_cover = cb.checked;
                if (selectedTitle) payload.title = selectedTitle;
                if (selectedDetails) payload.details = selectedDetails;
                api(API + '/queue/' + jobId + '/cover', { method: 'PUT', data: payload }, function(r) {
                    if (r && r.ok) showToast('Cover guardado' + (selectedTitle ? '. Título: ' + selectedTitle : ''));
                    else showToast('Error al guardar cover');
                    overlay.remove();
                });
            };
            var cancel = document.createElement('button');
            cancel.textContent = 'Cancelar';
            cancel.style.cssText = 'padding:8px 14px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;';
            cancel.onclick = function() { overlay.remove(); };
            btnRow.appendChild(save);
            btnRow.appendChild(cancel);
            panel.appendChild(btnRow);
            overlay.appendChild(panel);
            document.body.appendChild(overlay);

            // Resolución en vivo de la plantilla (debounce 300ms)
            var previewTimer = null;
            function renderCoverImage() {
                var imgEl = document.getElementById('cover-img');
                if (!imgEl) return;
                var boxImg = document.getElementById('cover-img-box');
                var useEnr = !!(document.getElementById('cover-use-enricher') || {}).checked;
                var poster = null;
                if (useEnr && selectedDetails && selectedDetails.api_cover) {
                    try {
                        var covers = JSON.parse(selectedDetails.api_cover);
                        if (covers && covers.length) poster = covers[0];
                    } catch(e) {}
                }
                if (poster) {
                    imgEl.src = poster;
                    if (boxImg) boxImg.style.display = 'block';
                } else if (imageB64) {
                    imgEl.src = 'data:image/jpeg;base64,' + imageB64;
                    if (boxImg) boxImg.style.display = 'block';
                } else if (boxImg) {
                    boxImg.style.display = 'none';
                }
            }
            function updateCoverUseLabel() {
                // El check "Usar cover descargado" solo tiene sentido si se ha usado el enriquecedor
                // (dados con api_cover), es decir, tras pulsar "Usar seleccionado".
                var label = document.getElementById('cover-use-enricher-label');
                if (!label) return;
                var hasApi = !!(selectedDetails && (selectedDetails.api_cover || ''));
                label.style.display = hasApi ? 'flex' : 'none';
            }
            function renderDebugList(rows) {
                var el = document.getElementById('cover-debug-list');
                if (!el) return;
                if (!rows || !rows.length) { el.innerHTML = '<span style="color:#71717a;">Sin tags en la plantilla</span>'; return; }
                var html = '';
                for (var i = 0; i < rows.length; i++) {
                    var r = rows[i];
                    var color = r.has ? '#22c55e' : '#ef4444';
                    var val = r.has ? (r.value || '(vac&iacute;o)') : '(vac&iacute;o)';
                    html += '<div style="display:flex;gap:8px;padding:2px 0;align-items:flex-start;">' +
                        '<span style="min-width:20px;color:#71717a;">' + r.n + '.</span>' +
                        '<span style="min-width:90px;color:#06b6d4;">' + r.tag + '</span>' +
                        '<span style="color:' + color + ';word-break:break-word;flex:1;">' + val + '</span>' +
                        '</div>';
                }
                el.innerHTML = html;
            }
            function refreshPreview() {
                var tplVal = document.getElementById('cover-template').value;
                var debugOn = !!(document.getElementById('cover-debug') || {}).checked;
                var data = { template: tplVal };
                if (selectedDetails) data.details = selectedDetails;
                if (debugOn) data.debug = true;
                window.API.ajax({
                    method: 'POST', url: API + '/queue/' + jobId + '/cover/preview',
                    data: data,
                    success: function(r) {
                        var pv = document.getElementById('cover-preview');
                        if (pv && r && r.text !== undefined) pv.value = r.text;
                        if (debugOn && r && r.debug) renderDebugList(r.debug);
                    },
                    error: function() { /* ignorar errores: dejar el último preview */ }
                });
            }
            document.getElementById('cover-template').addEventListener('input', function() {
                if (previewTimer) clearTimeout(previewTimer);
                previewTimer = setTimeout(refreshPreview, 300);
            });
            document.getElementById('cover-debug').addEventListener('change', function() {
                var el = document.getElementById('cover-debug-list');
                if (el) el.style.display = this.checked ? 'block' : 'none';
                refreshPreview();
            });
            var useBox = document.getElementById('cover-use-enricher');
            if (useBox) {
                useBox.addEventListener('change', function() {
                    renderCoverImage();
                    refreshPreview();
                });
            }
            renderCoverImage();
            updateCoverUseLabel();

            // Búsqueda en enriquecedor (manual)
            document.getElementById('cover-search-btn').onclick = function() {
                var q = document.getElementById('cover-search-query').value.trim();
                if (!q) { showToast('Introduce un título para buscar'); return; }
                var box = document.getElementById('cover-candidates');
                box.innerHTML = '<span style="font-size:0.75rem;color:#a1a1aa;">Buscando...</span>';
                window.API.ajax({
                    method: 'POST', url: '/api/enrich/search',
                    data: { query: q, category: category, subcategory: subcategory },
                    success: function(r) {
                        if (!r || !r.candidates || r.candidates.length === 0) {
                            var msg = (r && r.configured === false)
                                ? 'Proveedor no configurado. Configúralo en Ajustes → Enriquecedor.'
                                : 'Sin resultados.';
                            box.innerHTML = '<span style="font-size:0.75rem;color:#a1a1aa;">' + msg + '</span>';
                            return;
                        }
                        var h = '<select id="cover-cand-select" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px;color:#f4f4f5;font-size:0.8rem;">';
                        for (var i = 0; i < r.candidates.length; i++) {
                            var c = r.candidates[i];
                            var yr = c.year ? (' (' + c.year + ')') : '';
                            h += '<option value="' + i + '">' + c.title + yr + '</option>';
                        }
                        h += '</select>';
                        if (r.has_more) {
                            h += '<div style="font-size:0.7rem;color:#fbbf24;margin-top:2px;">Hay más resultados: refina la búsqueda.</div>';
                        }
                        h += '<button id="cover-cand-use" style="margin-top:6px;padding:6px 12px;background:#2563eb;border:none;color:#fff;border-radius:6px;cursor:pointer;font-size:0.8rem;">Usar seleccionado</button>';
                        box.innerHTML = h;

                        document.getElementById('cover-cand-use').onclick = function() {
                            var idx = parseInt(document.getElementById('cover-cand-select').value, 10);
                            var cand = r.candidates[idx];
                            box.innerHTML = '<span style="font-size:0.75rem;color:#a1a1aa;">Obteniendo detalles...</span>';
                            window.API.ajax({
                                method: 'POST', url: '/api/enrich/details',
                                data: { provider: cand.provider, id: cand.id, category: category, subcategory: subcategory, media_type: (cand.media_type || '') },
                                success: function(dr) {
                                    var det = (dr && dr.details) || {};
                                    if (det.api_title) {
                                        selectedTitle = det.api_title;
                                        selectedDetails = det;
                                        var cb = document.getElementById('cover-use-enricher');
                                        if (cb) cb.checked = true;
                                        updateCoverUseLabel();
                                        renderCoverImage();
                                        refreshPreview();
                                        showToast('Información cargada');
                                    } else {
                                        showToast('Sin detalles para este candidato');
                                    }
                                    box.innerHTML = '<span style="font-size:0.75rem;color:#22c55e;">Detalle aplicado. Puedes editar la plantilla antes de guardar.</span>';
                                },
                                error: function() { box.innerHTML = '<span style="font-size:0.75rem;color:#ef4444;">Error al obtener detalles</span>'; }
                            });
                        };
                    },
                    error: function() { box.innerHTML = '<span style="font-size:0.75rem;color:#ef4444;">Error de red</span>'; }
                });
            };
        });
    };

    // Guardar la contraseña de un job archive en espera
    window._tgcopy2SetPassword = function(jobId, value) {
        api(API + '/queue/' + jobId + '/password', { method: 'PUT', data: { password: value || '' } }, function(r) {
            if (r && r.ok) showToast('Contraseña guardada. Pulsa Reintentar.');
            else showToast('Error guardando contraseña');
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    // Reintentar un job archive con la contraseña guardada
    window._tgcopy2RetryPassword = function(jobId) {
        api(API + '/queue/' + jobId + '/password/retry', { method: 'POST' }, function(r) {
            if (r && r.ok) showToast('Reintentando archive...');
            else showToast('Error al reintentar');
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    // Definir el siguiente episodio a procesar (número) o 'auto'
    window._tgcopy2SetNext = function(jobId, value) {
        var v = String(value || '').trim();
        if (v === '' || v.toLowerCase() === 'auto') {
            api(API + '/queue/' + jobId + '/next-episode/auto', { method: 'PUT' }, function() {
                if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
            });
            return;
        }
        var n = parseInt(v, 10);
        if (isNaN(n) || n < 1) {
            showToast('Valor inválido: usa un número o "auto"');
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
            return;
        }
        api(API + '/queue/' + jobId + '/next-episode', { method: 'PUT', data: { next_episode: n } }, function(r) {
            if (r && r.ok) showToast('Siguiente episodio: ' + n);
            // Aviso si el episodio apuntado está desmarcado en el modal (se saltará)
            api(API + '/queue/' + jobId + '/episodes', {}, function(res) {
                try {
                    var eps = (res && res.episodes) || [];
                    for (var i = 0; i < eps.length; i++) {
                        if (parseInt(eps[i].n, 10) === n && !eps[i].in_scope) {
                            showToast('Ojo: el ep. ' + n + ' está desmarcado, se saltará');
                            break;
                        }
                    }
                } catch (e) {}
            });
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    // Volver a meter un trabajo finalizado en la cola
    window._tgcopy2Requeue = function(jobId) {
        api(API + '/queue/' + jobId + '/requeue', { method: 'POST' }, function(r) {
            if (r && r.ok) showToast('Re-encolado');
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    window._tgcopy2CleanCompleted = function() {
        api(API + '/queue/completed/clean', { method: 'DELETE' }, function(r) {
            if (r && r.removed) showToast('Eliminados ' + r.removed + ' finalizados');
            if (window._tgcopy2RefreshQueue) window._tgcopy2RefreshQueue();
        });
    };

    // ─── Tray action handler ───
    window._tgcopy2TrayQueue = function() {
        showQueueModal();
    };

    // Interceptar handleTrayAction para TGHirayi_v2 (cola vs envío masivo)
    (function() {
        function setup() {
            if (typeof window.handleTrayAction === 'function') {
                var orig = window.handleTrayAction;
                window.handleTrayAction = function(pluginName, btnIndex, el) {
                    if (pluginName === 'tvcat_TGHirayi_v2') {
                        if (btnIndex === 1) { showBulkSendModal(); } else { showQueueModal(); }
                        return;
                    }
                    orig(pluginName, btnIndex, el);
                };
            } else {
                setTimeout(setup, 100);
            }
        }
        setup();
    })();

    // Eliminar clase tray-active de los botones de TGHirayi_v2 (no es toggle)
    (function() {
        function fixTray() {
            var tray = document.getElementById('plugin-tray-icons');
            if (tray) {
                var btns = tray.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].getAttribute('onclick') && btns[i].getAttribute('onclick').indexOf('tvcat_TGHirayi_v2') >= 0) {
                        btns[i].classList.remove('tray-active');
                    }
                }
            }
        }
        // Ejecutar cada vez que se renderice el tray
        var origRender = window.renderPluginTray;
        if (origRender) {
            window.renderPluginTray = function() {
                origRender();
                fixTray();
            };
        }
        setTimeout(fixTray, 500);
    })();

    // ─── Enviar colección: la propia colección primero + sus títulos ───
    function showCollectionPicker(colRef) {
        var colId = (colRef && (colRef.item_id || colRef.id)) || '';
        var colTitle = (colRef && colRef.title) || '';
        if (!colId) { alert('Colección sin identificador.'); return; }
        api('/api/collection/resolve?item_id=' + encodeURIComponent(colId), {}, function(res) {
            var items = (res && res.items) || [];
            var col = (res && res.collection) || {};
            var all = [];
            if (col.item_id || colId) {
                all.push({ item_id: col.item_id || colId, title: col.title || colTitle || 'Colección',
                    cover_url: col.cover_url || '', category: '', subcategory: '',
                    telegram_link: '', _isCollection: true });
            }
            for (var i = 0; i < items.length; i++) all.push(items[i]);
            if (!all.length) { alert('Esta colección no tiene títulos resolvibles en tu catálogo.'); return; }
            showBulkSendModal(all, 'Enviar colección a Canal Telegram (' + all.length + ')');
        });
    }

    // ─── Registrar plugin ───
    window.pluginSystem.registerPlugin({
        name: 'tvcat_TGHirayi_v2',
        type: 'heropage-action',
        displayName: 'TGHirayi_v2 (Enviar a Canal Telegram)',
        playerType: 'TGHirayi_v2',
        playLabel: 'Enviar a Canal',
        playIcon: '\uD83D\uDCE4',
        applies_to: ['*'],
        action_category: 'playback',
        play: function(item) { showDestinationPicker(item); },
        getHeroButtons: function(itemData) {
            return [{
                id: 'btn-tghirayi-v2',
                icon: '<img src="/plugin-static/tvcat_TGHirayi_v2/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.onerror=null;this.src=\'/plugin-static/tvcat_TGHirayi_v2/plugin_icon.png\';">',
                tooltip: 'Enviar a Canal Telegram',
            label: '',
                action: function() { showDestinationPicker(itemData); }
            }];
        },
        getCollectionButtons: function(colData) {
            return [{
                id: 'btn-tghirayi-v2-collection',
                icon: '<img src="/plugin-static/tvcat_TGHirayi_v2/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.onerror=null;this.src=\'/plugin-static/tvcat_TGHirayi_v2/plugin_icon.png\';">',
                tooltip: 'Enviar títulos de la colección a Canal Telegram',
                label: 'Enviar a Telegram',
                action: function(ref) { showCollectionPicker(ref || colData); }
            }];
        }
    });
})();