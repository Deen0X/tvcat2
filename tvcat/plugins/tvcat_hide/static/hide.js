/* tvcat_hide — Ocultar elementos del catálogo (personal + parental).
 * heropage-action: botón Ocultar/Mostrar por item + gemelo parental (admin).
 * Tray: toggle personal, ocultar filtrados, ocultar filtrados parental.
 * Secciones core "Ocultos" y "Ocultos Parental" para revisar/recuperar.
 */
(function() {
    if (!window.pluginSystem) return;

    var _cfg = null;
    var _cfgTs = 0;

    function api(url, opts, cb) {
        opts = opts || {};
        var xhr = new XMLHttpRequest();
        xhr.open(opts.method || 'GET', url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            var b = {};
            try { b = JSON.parse(xhr.responseText || '{}'); } catch (e) {}
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

    function openModal(title, contentFn) {
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
    }

    function isAdmin() {
        try { return !!(window.Catalog && window.Catalog.currentUser && window.Catalog.currentUser.is_admin); }
        catch (e) { return false; }
    }

    function loadCfg(cb) {
        var now = Date.now();
        if (_cfg && (now - _cfgTs) < 15000) { if (cb) cb(_cfg); return; }
        api('/api/hide/config', {}, function(res) {
            _cfg = res || { show_parental: false, child_profile_id: 0, is_admin: false };
            _cfgTs = Date.now();
            if (cb) cb(_cfg);
        });
    }

    function parentalReady() {
        return isAdmin() && _cfg && _cfg.show_parental && (_cfg.child_profile_id > 0);
    }

    function itemIdOf(item) {
        return (item && (item.item_id || item.id)) || '';
    }

    function isCollectionItem(item) {
        var id = String(itemIdOf(item) || '');
        return (id.indexOf('COL-') === 0) || !!(item && item.is_collection);
    }

    function reloadGrid() {
        try { if (window.Catalog) window.Catalog.load(window.Catalog.currentCategory || 'home'); } catch (e) {}
    }

    // ─── Hero ───
    // Iconos desde static (mocks editables); si falta la imagen, emoji.
    function heroImg(file, emoji) {
        return '<img src="/plugin-static/tvcat_hide/' + file +
            '" style="width:100%;height:100%;object-fit:contain;" onerror="pluginIconFallback(this,\'' +
            emoji + '\',20)">';
    }

    function setHeroBtn(btn, hiddenBy) {
        if (!btn) return;
        var inner = '';
        var tip = '';
        if (hiddenBy === 'parental') {
            inner = '<span class="btn-emoji">' + heroImg('plugin_shield.png', '🛡️') + '</span>';
            tip = 'Bloqueado por parental';
        } else if (hiddenBy === 'own') {
            inner = '<span class="btn-emoji">' + heroImg('plugin_eye_off.png', '🙈') + '</span>';
            tip = 'Oculto (pulsa para mostrar)';
        } else {
            inner = '<span class="btn-emoji">' + heroImg('plugin_eye.png', '👁️') + '</span>';
            tip = 'Ocultar este item del catálogo';
        }
        btn.innerHTML = inner;
        btn.title = tip;
        btn.setAttribute('aria-label', tip);
    }

    function paintHeroState(itemId) {
        api('/api/hidden/state?item_id=' + encodeURIComponent(itemId), {}, function(st) {
            setHeroBtn(document.getElementById('btn-hide-item'), st && st.hidden_by);
        });
    }

    function getHeroButtons(itemData) {
        if (!itemData || !itemIdOf(itemData) || isCollectionItem(itemData)) return [];
        var id = itemIdOf(itemData);
        setTimeout(function() { paintHeroState(id); }, 300);
        var btns = [{
            id: 'btn-hide-item',
            icon: heroImg('plugin_eye.png', '👁️'),
            tooltip: 'Ocultar este item del catálogo',
            label: '',
            action: function() {
                api('/api/hidden/toggle', { method: 'POST', data: { item_id: id } }, function(r) {
                    var btn = document.getElementById('btn-hide-item');
                    if (r && (r.hidden === true || r.hidden === false)) {
                        setHeroBtn(btn, r.hidden ? 'own' : null);
                        showToast(r.hidden ? 'Ocultado' : 'Visible de nuevo');
                        reloadGrid();
                    } else {
                        var det = (r && r.detail) || '';
                        if (det && det.toLowerCase().indexOf('parental') !== -1) setHeroBtn(btn, 'parental');
                        showToast(det ? ('No se puede: ' + det) : 'Error al ocultar');
                    }
                });
            }
        }];
        if (parentalReady()) {
            btns.push({
                id: 'btn-hide-item-parental',
                icon: heroImg('plugin_shield.png', '🛡️'),
                tooltip: 'Ocultar este item para el perfil child (Parental)',
                label: '',
                action: function() {
                    if (!confirm('Ocultar "' + (itemData.title || id) + '" para el perfil child?')) return;
                    api('/api/hidden/block', { method: 'POST', data: { item_id: id, target_profile: _cfg.child_profile_id } }, function(r) {
                        if (r && r.success) { showToast('Bloqueado para child'); reloadGrid(); }
                        else showToast('Error parental');
                    });
                }
            });
        }
        return btns;
    }

    // ─── Toggle personal ───
    function paintTrayToggle(enabled) {
        try {
            var tray = document.getElementById('plugin-tray-icons');
            if (!tray) return;
            var btns = tray.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var oc = btns[i].getAttribute('onclick') || '';
                if (oc.indexOf('tvcat_hide') !== -1 && oc.indexOf(',0,') !== -1) {
                    if (enabled) btns[i].classList.add('tray-active');
                    else btns[i].classList.remove('tray-active');
                }
            }
        } catch (e) {}
    }

    function togglePersonal() {
        api('/api/hidden/status', {}, function(st) {
            var cur = !!(st && st.enabled);
            api('/api/hidden/enabled', { method: 'POST', data: { enabled: !cur } }, function(r) {
                paintTrayToggle(!cur);
                showToast(!cur ? 'Ocultos personales: ON' : 'Ocultos personales: OFF (ves todo)');
                reloadGrid();
            });
        });
    }

    // ─── Bulk: ocultar filtrados (o mostrar/desbloquear dentro de secciones) ───
    function showBulkHide(parental) {
        if (parental && !isAdmin()) { showToast('Solo admin'); return; }
        var section = '';
        try { section = (window.Catalog && window.Catalog.currentCategory) || ''; } catch (e) {}
        // Dentro de las secciones el bulk invierte: mostrar / desbloquear.
        var showMode = !parental && section === 'hidden';
        var unblockMode = !!parental && section === 'hidden_blocked';
        loadCfg(function(cfg) {
            if (parental && !unblockMode && !(cfg.show_parental)) { showParentalConfig(); return; }
            if (parental && !unblockMode && !(cfg.child_profile_id > 0)) { showParentalConfig(); return; }
            var items = ((window.Catalog && window.Catalog.currentItems) || []).filter(function(it) {
                return itemIdOf(it) && !isCollectionItem(it);
            });
            if (!items.length) { alert('No hay elementos (items) en el catálogo actual.'); return; }
            var title = showMode
                ? 'Mostrar filtrados (' + items.length + ')'
                : (unblockMode
                    ? 'Desbloquear filtrados (' + items.length + ')'
                    : (parental
                        ? 'Ocultar filtrados para child (' + items.length + ')'
                        : 'Ocultar filtrados (' + items.length + ')'));
            openModal(title, function(content, overlay) {
                var html = '<div style="display:flex;gap:8px;margin-bottom:8px;">' +
                    '<button class="hide-bulk-all" style="flex:1;padding:6px;background:#27272a;border:1px solid #3f3f46;color:#fff;border-radius:6px;cursor:pointer;">Marcar todo</button>' +
                    '<button class="hide-bulk-none" style="flex:1;padding:6px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;">Desmarcar todo</button></div>' +
                    '<div class="hide-bulk-list" style="max-height:50vh;overflow-y:auto;">';
                for (var i = 0; i < items.length; i++) {
                    var iid = itemIdOf(items[i]);
                    var t = (items[i].title || items[i].name || iid || '').toString().replace(/</g, '&lt;');
                    html += '<label style="display:flex;align-items:center;gap:8px;padding:6px;margin:3px 0;background:rgba(255,255,255,0.05);border-radius:6px;cursor:pointer;font-size:13px;">' +
                        '<input type="checkbox" class="hide-bulk-cb" value="' + iid.replace(/"/g, '&quot;') + '" checked style="accent-color:#eab308;">' +
                        '<span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + t + '</span></label>';
                }
                html += '</div>';
                content.innerHTML = html;
                var btnAll = content.querySelector('.hide-bulk-all');
                var btnNone = content.querySelector('.hide-bulk-none');
                if (btnAll) btnAll.onclick = function() { var c = content.querySelectorAll('.hide-bulk-cb'); for (var a = 0; a < c.length; a++) c[a].checked = true; };
                if (btnNone) btnNone.onclick = function() { var c = content.querySelectorAll('.hide-bulk-cb'); for (var a = 0; a < c.length; a++) c[a].checked = false; };
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
                var go = document.createElement('button');
                go.textContent = showMode ? 'Mostrar' : (unblockMode ? 'Desbloquear' : (parental ? 'Bloquear para child' : 'Ocultar'));
                go.style.cssText = 'flex:1;padding:8px;background:#eab308;border:none;color:#000;border-radius:6px;cursor:pointer;font-weight:600;';
                go.onclick = function() {
                    var ids = [];
                    var boxes = content.querySelectorAll('.hide-bulk-cb:checked');
                    for (var k = 0; k < boxes.length; k++) ids.push(boxes[k].value);
                    if (!ids.length) { alert('Marca al menos uno.'); return; }
                    var payload, okMsg;
                    if (showMode) {
                        payload = { item_ids: ids, mode: 'show' };
                        okMsg = function(r) { return 'Visibles: ' + (r.shown || 0); };
                    } else if (unblockMode) {
                        var pairs = [];
                        for (var p = 0; p < ids.length; p++) {
                            var prof = 0;
                            for (var q = 0; q < items.length; q++) {
                                if (String(itemIdOf(items[q])) === String(ids[p])) {
                                    prof = parseInt(items[q].blocked_profile || '0', 10) || 0;
                                    break;
                                }
                            }
                            pairs.push({ item_id: ids[p], profile: prof || _cfg.child_profile_id });
                        }
                        payload = { pairs: pairs, mode: 'unblock' };
                        okMsg = function(r) { return 'Desbloqueados: ' + (r.unblocked || 0); };
                    } else if (parental) {
                        payload = { item_ids: ids, mode: 'block', target_profile: _cfg.child_profile_id };
                        okMsg = function(r) { return 'Bloqueados: ' + (r.blocked || 0); };
                    } else {
                        payload = { item_ids: ids, mode: 'hide' };
                        okMsg = function(r) { return 'Ocultados: ' + (r.hidden || 0); };
                    }
                    api('/api/hidden/bulk', { method: 'POST', data: payload }, function(r) {
                        overlay.remove();
                        if (r && r.success) showToast(okMsg(r));
                        else showToast('Error');
                        reloadGrid();
                    });
                };
                var cancel = document.createElement('button');
                cancel.textContent = 'Cancelar';
                cancel.style.cssText = 'padding:8px 14px;background:none;border:1px solid #3f3f46;color:rgba(255,255,255,0.6);border-radius:6px;cursor:pointer;';
                cancel.onclick = function() { overlay.remove(); };
                row.appendChild(go); row.appendChild(cancel);
                content.appendChild(row);
            });
        });
    }

    // ─── Config parental (admin) ───
    function showParentalConfig() {
        if (!isAdmin()) { showToast('Solo admin'); return; }
        api('/api/hide/profiles', {}, function(pres) {
            var profiles = (pres && pres.profiles) || [];
            loadCfg(function(cfg) {
                openModal('Configuración Parental', function(content, overlay) {
                    var html = '<label style="display:flex;align-items:center;gap:8px;padding:10px;margin-bottom:8px;background:rgba(255,255,255,0.05);border-radius:6px;cursor:pointer;font-size:13px;">' +
                        '<input type="checkbox" id="hide-cfg-show" ' + (cfg.show_parental ? 'checked' : '') + ' style="accent-color:#eab308;">' +
                        '<span>Mostrar botones parentales</span></label>' +
                        '<div style="font-size:12px;color:#a1a1aa;margin-bottom:4px;">Perfil child:</div>' +
                        '<select id="hide-cfg-child" style="width:100%;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:6px;padding:8px;">' +
                        '<option value="0">(sin definir)</option>';
                    for (var i = 0; i < profiles.length; i++) {
                        var sel = (String(profiles[i].id) === String(cfg.child_profile_id)) ? ' selected' : '';
                        html += '<option value="' + profiles[i].id + '"' + sel + '>' + String(profiles[i].name || '').replace(/</g, '&lt;') + ' (#' + profiles[i].id + ')</option>';
                    }
                    html += '</select>';
                    content.innerHTML = html;
                    var row = document.createElement('div');
                    row.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
                    var save = document.createElement('button');
                    save.textContent = 'Guardar';
                    save.style.cssText = 'flex:1;padding:8px;background:#22c55e;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:600;';
                    save.onclick = function() {
                        var show = !!content.querySelector('#hide-cfg-show').checked;
                        var cpid = parseInt(content.querySelector('#hide-cfg-child').value || '0', 10) || 0;
                        api('/api/hide/config', { method: 'PUT', data: { show_parental: show, child_profile_id: cpid } }, function(r) {
                            _cfg = null;
                            overlay.remove();
                            showToast('Configuración guardada');
                            loadCfg(function() {});
                        });
                    };
                    row.appendChild(save);
                    content.appendChild(row);
                });
            });
        });
    }

    // ─── Tray ───
    window._hideTray = function(btnIndex) {
        if (btnIndex === 0) { togglePersonal(); return; }
        if (btnIndex === 1) { showBulkHide(false); return; }
        if (btnIndex === 2) {
            if (!isAdmin()) { showToast('Solo admin'); return; }
            loadCfg(function(cfg) {
                if (!cfg.show_parental || !(cfg.child_profile_id > 0)) { showParentalConfig(); return; }
                showBulkHide(true);
            });
            return;
        }
    };

    (function() {
        function setup() {
            if (typeof window.handleTrayAction === 'function') {
                var orig = window.handleTrayAction;
                window.handleTrayAction = function(pluginName, btnIndex, el) {
                    if (pluginName === 'tvcat_hide') {
                        window._hideTray(btnIndex);
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

    // Estado visual del tray: el botón 0 (on/off) lleva el borde tray-active
    // como fondo/bordes; los demás son acciones (sin estado).
    (function() {
        function fixTray() {
            var tray = document.getElementById('plugin-tray-icons');
            if (tray) {
                var btns = tray.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].getAttribute('onclick') && btns[i].getAttribute('onclick').indexOf('tvcat_hide') >= 0) {
                        btns[i].classList.remove('tray-active');
                    }
                }
            }
            api('/api/hidden/status', {}, function(st) {
                paintTrayToggle(!!(st && st.enabled));
            });
        }
        var origRender = window.renderPluginTray;
        if (origRender) {
            window.renderPluginTray = function() {
                origRender();
                fixTray();
            };
        }
        setTimeout(fixTray, 500);
    })();

    loadCfg(function() {});

    window.pluginSystem.registerPlugin({
        name: 'tvcat_hide',
        type: 'heropage-action',
        displayName: 'Ocultos',
        getHeroButtons: getHeroButtons
    });
})();
