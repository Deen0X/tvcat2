/* tvcat_indexator — modal de generación de índices por canal.
 * ES5. Usa Catalog.currentItems? NO: trabaja con canales (fuentes tgindex +
 * destinos TGHirayi) y topics en vivo del servicio central.
 */
(function() {
    if (!window.pluginSystem) return;

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

    function esc(s) {
        return String(s === undefined || s === null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function showToast(msg) {
        var t = document.getElementById('toast-container');
        if (!t) { t = document.createElement('div'); t.id = 'toast-container'; t.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999999;display:flex;flex-direction:column;gap:8px;'; document.body.appendChild(t); }
        var el = document.createElement('div');
        el.style.cssText = 'background:#18181b;border:1px solid #3f3f46;border-radius:8px;padding:10px 16px;color:#f4f4f5;font-size:13px;max-width:320px;box-shadow:0 4px 12px rgba(0,0,0,0.4);';
        el.textContent = msg;
        t.appendChild(el);
        setTimeout(function() { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(function() { el.remove(); }, 300); }, 3500);
    }

    var HELP_TAGS = [
        ['{letter}', 'Letra del grupo actual'],
        ['{currentletter} / {currentletterend}', 'Primera / última letra del chunk'],
        ['{total}', 'Nº títulos de la letra (o del chunk)'],
        ['{total_all}', 'Nº total de títulos'],
        ['{part} / {parts}', 'Parte actual / total ("1/3")'],
        ['{index}', 'Nº dentro de su letra'],
        ['{global_index}', 'Nº correlativo global'],
        ['{title}', 'Nombre del topic tal cual'],
        ['{title_link}', 'Título como enlace al topic'],
        ['{url}', 'URL t.me del topic'],
        ['{year}', 'Año tras 🗓'],
        ['{img:file}', 'Imagen (static/pack); si falta, se omite'],
        ['**x** __x__ `x` [t](u)', 'Negrita, itálica, código, enlace'],
        ['<b>x</b> <i>x</i> <code>x</code>', 'Igual en HTML (plantillas por defecto)']
    ];

    // URL t.me para un canal privado: t.me/c/<bare>/<msg>.
    // channel_id estilo "-100XXXX" -> bare = XXXX (sin el -100).
    function tgUrlForChannel(cid) {
        var s = String(cid || '').trim();
        if (!s) return '';
        var bare = s;
        if (bare.indexOf('-100') === 0) bare = bare.substring(4);
        else bare = bare.replace(/^-/, '');
        if (!bare) return '';
        return 'https://t.me/c/' + bare + '/1';
    }

    function channelOptions(channels) {
        var h = '';
        for (var i = 0; i < channels.length; i++) {
            var c = channels[i];
            var lock = (c.can_post === false) ? ' 🔒' : '';
            var stale = c.stale ? ' (…)' : '';
            h += '<option value="' + esc(c.channel_id) + '">' + esc(c.label || (c.channel_id + ' - ' + (c.name || ''))) + lock + stale + '</option>';
        }
        if (!h) h = '<option value="">(sin canales en las fuentes marcadas)</option>';
        return h;
    }

    // Reintenta traer nombres pendientes (el backend los resuelve en
    // segundo plano): hasta 3 pasadas, conservando la selección.
    function repollNames(box, left) {
        if (left <= 0) return;
        setTimeout(function() {
            if (!document.contains(box)) return;
            var keep = box.querySelector('#ix-channel').value;
            api('/api/indexator/channels', {}, function(chres) {
                if (!document.contains(box)) return;
                var all = (chres && chres.channels) || [];
                var sel = selectedSources(box);
                var filt = [];
                for (var k = 0; k < all.length; k++) {
                    var pl = all[k].plugins || [];
                    var ok = true;
                    if (sel.length) {
                        ok = false;
                        for (var j = 0; j < sel.length; j++) {
                            if (pl.indexOf(sel[j]) !== -1) { ok = true; break; }
                        }
                    }
                    if (ok) filt.push(all[k]);
                }
                box.querySelector('#ix-channel').innerHTML = channelOptions(filt);
                var chsel = box.querySelector('#ix-channel');
                for (var o = 0; o < chsel.options.length; o++) {
                    if (chsel.options[o].value === keep) { chsel.selectedIndex = o; break; }
                }
                var pend = 0;
                for (var p = 0; p < filt.length; p++) if (filt[p].stale) pend++;
                var note = box.querySelector('#ix-names-note');
                if (note) note.textContent = pend ? ('Resolviendo nombres… (' + pend + ')') : '';
                if (pend) repollNames(box, left - 1);
            });
        }, 8000);
    }

    function selectedSources(box) {
        var out = [];
        var cbs = box.querySelectorAll('.ix-src-cb:checked');
        for (var i = 0; i < cbs.length; i++) out.push(cbs[i].value);
        return out;
    }

    function openModal() {
        api('/api/indexator/sources', {}, function(sres) {
            var sources = (sres && sres.sources) || [];
            api('/api/indexator/channels', {}, function(chres) {
                var channels = (chres && chres.channels) || [];
                api('/api/indexator/config', {}, function(cfgres) {
                    var cfg = (cfgres && cfgres.config) || {};
                    renderModal(channels, sources, cfg, (cfgres && cfgres.packs) || []);
                });
            });
        });
    }

    function renderModal(channels, sources, cfg, packs) {
        var old = document.getElementById('indexator-overlay');
        if (old && old.parentNode) old.parentNode.removeChild(old);
        var o = document.createElement('div');
        o.id = 'indexator-overlay';
        o.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);z-index:50000;display:block;overflow:auto;';
        var box = document.createElement('div');
        box.style.cssText = 'background:#18181b;color:#f4f4f5;max-width:680px;margin:30px auto;padding:16px;border:1px solid #3f3f46;border-radius:8px;';
        var h = '<h3 style="margin:0 0 4px 0;display:flex;align-items:center;gap:8px;"><img src="/plugin-static/tvcat_indexator/plugin_icon.png" style="width:28px;height:28px;object-fit:contain;flex-shrink:0;" onerror="this.style.display=\'none\'"> Indexator — índice de topics</h3>';
        // Fuentes: plugins habilitados que aportan canales (checks = filtro).
        h += '<div style="font-size:0.8rem;color:#a1a1aa;margin-bottom:4px;">Fuentes (plugins con canales):</div>';
        h += '<div id="ix-sources" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">';
        if (!sources.length) {
            h += '<span style="font-size:0.8rem;color:#fbbf24;">Sin fuentes con canales (¿plugins apagados?).</span>';
        }
        for (var si = 0; si < sources.length; si++) {
            var sp = sources[si];
            h += '<label style="font-size:0.8rem;display:flex;gap:5px;align-items:center;cursor:pointer;">' +
                '<input type="checkbox" class="ix-src-cb" value="' + esc(sp.name) + '"' +
                (sp.selected === false ? '' : ' checked') + '> ' +
                esc(sp.display || sp.name) + ' (' + (sp.channels || 0) + ')</label>';
        }
        h += '</div>';
        h += '<label>Cuenta Telegram:<br><select id="ix-account" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;">';
        h += '<option value="">(automática: la activa)</option>';
        h += '</select></label>';
        h += '<div style="font-size:0.8rem;color:#a1a1aa;margin:6px 0;">La cuenta debe estar en el canal y ser admin para crear/vaciar el índice.</div>';
        h += '<div style="display:flex;gap:8px;align-items:flex-end;">';
        h += '<label style="flex:1;min-width:0;">Canal: <span id="ix-names-note" style="font-size:0.75rem;color:#a1a1aa;"></span><br><select id="ix-channel" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;">';
        h += channelOptions(channels);
        h += '</select></label>';
        h += '<button id="ix-open-tg" title="Abrir el canal en Telegram para comprobar datos" style="background:#229ED9;border:none;color:#fff;border-radius:6px;padding:10px 12px;cursor:pointer;white-space:nowrap;">Abrir en Telegram</button>';
        h += '</div>';
        h += '<div style="font-size:0.8rem;color:#a1a1aa;margin:6px 0;">Solo canales con topics (topología 3). Los topics se listan en vivo.</div>';
        h += '<label>Topic índice:<br><input id="ix-topic" value="' + esc(cfg.index_topic || 'TVCat-Index') + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;"></label>';
        h += '<label>Excluir topics (separados por coma):<br><input id="ix-excl" value="' + esc((cfg.exclude_topics || []).join(', ')) + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;"></label>';
        h += '<div style="display:flex;gap:8px;margin:8px 0;">';
        h += '<label style="flex:1;">Cabecera (no se repite):<br><textarea id="ix-header" rows="2" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;resize:vertical;"></textarea></label>';
        h += '</div>';
        h += '<label>Cuerpo (parte repetible, con {letters}/{entries}):<br><textarea id="ix-body" rows="6" style="width:100%;background:#09090b;border:1px solid #3f3f46;color:#f4f4f5;padding:10px;box-sizing:border-box;resize:vertical;font-family:monospace;font-size:0.8rem;"></textarea></label>';
        h += '<div style="display:flex;gap:8px;margin:8px 0;flex-wrap:wrap;align-items:center;">';
        h += '<label style="font-size:0.8rem;"><input type="checkbox" id="ix-noletras" ' + (cfg.noletras_mode === 'hash' ? 'checked' : '') + '> No-letras en #</label>';
        h += '<label style="font-size:0.8rem;" title="Une mayúsculas y minúsculas en la misma letra y ordena sin distinguirlas"><input type="checkbox" id="ix-unify" ' + (cfg.unify_case === false ? '' : 'checked') + '> Unificar mayús./minús.</label>';
        h += '<button id="ix-help" class="btn-secondary" style="padding:8px 12px;font-size:0.85rem;">Tags ❓</button>';
        h += '<span style="flex:1;"></span>';
        h += '<button id="ix-preview" class="btn-secondary" style="padding:10px 16px;font-size:0.9rem;">Previsualizar</button>';
        h += '<button id="ix-generate" class="btn-primary" style="padding:10px 16px;font-size:0.9rem;">Generar índice</button>';
        h += '</div>';
        h += '<div id="ix-helpbox" style="display:none;border:1px solid #27272a;border-radius:6px;padding:8px;margin-bottom:8px;font-size:0.78rem;"></div>';
        h += '<div id="ix-preview" style="border:1px solid #27272a;border-radius:6px;padding:8px;max-height:300px;overflow:auto;font-size:0.8rem;white-space:pre-wrap;"></div>';
        h += '<div style="text-align:right;margin-top:10px;"><button id="ix-close" class="btn-secondary" style="padding:10px 20px;">Cerrar</button></div>';
        box.innerHTML = h;
        o.appendChild(box);
        document.body.appendChild(o);
        o.onclick = function(e) { if (e.target === o) closeModal(); };
        box.querySelector('#ix-close').onclick = closeModal;
        // Cuentas Telegram (la activa por defecto; recordar última).
        (function() {
            var sel = box.querySelector('#ix-account');
            var keep = null;
            try { keep = localStorage.getItem('ix_account') || null; } catch (e) {}
            api('/api/indexator/accounts', {}, function(ares) {
                if (!document.contains(box)) return;
                var accs = (ares && ares.accounts) || [];
                var hh = '<option value="">(automática: la activa)</option>';
                for (var i = 0; i < accs.length; i++) {
                    var a = accs[i];
                    var v = String(a.tg_user_id || '');
                    if (!v) continue;
                    var lbl = (a.name ? a.name + ' ' : '') + '(' + v + ')' +
                        (a.client_type ? ' [' + a.client_type + ']' : '') +
                        (a.is_active ? '' : ' (inactiva)');
                    var seld = (keep && keep === v) ? ' selected' : '';
                    hh += '<option value="' + v + '"' + seld + '>' + esc(lbl) + '</option>';
                }
                sel.innerHTML = hh;
                sel.onchange = function() {
                    try { localStorage.setItem('ix_account', sel.value || ''); } catch (e) {}
                };
            });
        })();
        (function() {
            var b = box.querySelector('#ix-open-tg');
            if (!b) return;
            b.onclick = function() {
                var cid = '';
                try { cid = box.querySelector('#ix-channel').value || ''; } catch (e) {}
                if (!cid) { showToast('Elige canal'); return; }
                var url = tgUrlForChannel(cid);
                if (!url) { showToast('Canal sin enlace válido'); return; }
                try { window.open(url, '_blank'); } catch (e) {}
            };
        })();
        try {
            box.querySelector('#ix-header').value = cfg.header_template || '';
            box.querySelector('#ix-body').value = cfg.body_template || '';
        } catch (e) {}
        function vals() {
            var acc = '';
            try { acc = box.querySelector('#ix-account').value || ''; } catch (e) {}
            return {
                channel_id: box.querySelector('#ix-channel').value || '',
                header: box.querySelector('#ix-header').value || '',
                body: box.querySelector('#ix-body').value || '',
                tg_user_id: acc ? parseInt(acc, 10) : null
            };
        }
        function saveCfg(cb) {
            var excl = box.querySelector('#ix-excl').value || '';
            api('/api/indexator/config', { method: 'PUT', data: {
                index_topic: box.querySelector('#ix-topic').value || 'TVCat-Index',
                exclude_topics: excl.split(','),
                noletras_mode: box.querySelector('#ix-noletras').checked ? 'hash' : 'separado',
                unify_case: !!box.querySelector('#ix-unify').checked,
                header_template: box.querySelector('#ix-header').value || '',
                body_template: box.querySelector('#ix-body').value || '',
                sources: selectedSources(box)
            } }, cb || function() {});
        }
        // Cambiar fuentes re-filtra el combo sin cerrar el modal.
        (function() {
            var cbs = box.querySelectorAll('.ix-src-cb');
            function inSel(ch, sel) {
                if (!sel.length) return true;
                var pl = ch.plugins || (ch.plugin ? [ch.plugin] : []);
                for (var j = 0; j < sel.length; j++) {
                    if (pl.indexOf(sel[j]) !== -1) return true;
                }
                return false;
            }
            for (var i = 0; i < cbs.length; i++) {
                cbs[i].onchange = function() {
                    var keep = box.querySelector('#ix-channel').value;
                    api('/api/indexator/channels', {}, function(chres) {
                        var all = (chres && chres.channels) || [];
                        var sel = selectedSources(box);
                        var filt = [];
                        for (var k = 0; k < all.length; k++) {
                            if (inSel(all[k], sel)) filt.push(all[k]);
                        }
                        var chsel = box.querySelector('#ix-channel');
                        chsel.innerHTML = channelOptions(filt);
                        for (var o = 0; o < chsel.options.length; o++) {
                            if (chsel.options[o].value === keep) { chsel.selectedIndex = o; break; }
                        }
                        var pend = 0;
                        for (var p = 0; p < filt.length; p++) if (filt[p].stale) pend++;
                        var note = box.querySelector('#ix-names-note');
                        if (note) note.textContent = pend ? ('Resolviendo nombres… (' + pend + ')') : '';
                    });
                };
            }
        })();
        // Primera pasada: si hay nombres pendientes, reintentar para pintarlos.
        (function() {
            var pend0 = 0;
            try {
                var sel0 = box.querySelector('#ix-channel');
                for (var o = 0; o < sel0.options.length; o++) {
                    if ((sel0.options[o].text || '').indexOf('(…)') !== -1) { pend0++; break; }
                }
            } catch (e) {}
            var note0 = box.querySelector('#ix-names-note');
            if (note0 && pend0) note0.textContent = 'Resolviendo nombres…';
            repollNames(box, 3);
        })();
        box.querySelector('#ix-help').onclick = function() {
            var hb = box.querySelector('#ix-helpbox');
            if (!hb) return;
            if (hb.style.display !== 'none') { hb.style.display = 'none'; return; }
            var rh = '';
            for (var i = 0; i < HELP_TAGS.length; i++) {
                rh += '<div style="padding:3px 0;border-bottom:1px solid #1f1f22;"><code style="color:#93c5fd;">' +
                    esc(HELP_TAGS[i][0]) + '</code> <span style="color:#a1a1aa;">— ' + esc(HELP_TAGS[i][1]) + '</span></div>';
            }
            rh += '<div style="color:#a1a1aa;margin-top:6px;">Bloques: <code>{letters}…{/letters}</code> (opcional), <code>{entries}…{/entries}</code> (plantilla de entrada).</div>';
            hb.innerHTML = rh;
            hb.style.display = '';
        };
        box.querySelector('#ix-preview').onclick = function() {
            var v = vals();
            var pv = box.querySelector('#ix-preview');
            pv.textContent = 'Calculando…';
            api('/api/indexator/preview', { method: 'POST', data: v }, function(r) {
                if (!r || !r.parts) { pv.textContent = 'Error'; return; }
                var t = 'Partes: ' + r.parts.length + ' · Títulos: ' + r.total_all + ' · Letras: ' + (r.letters || []).join(' ') + '\n\n';
                for (var i = 0; i < Math.min(3, r.parts.length); i++) {
                    var p = r.parts[i];
                    t += '── Parte ' + p.part + '/' + p.parts + (p.letter ? ' [' + p.letter + ']' : '') +
                        (p.images && p.images.length ? ' [img]' : '') + ' (' + p.chars + ' ch)\n' +
                        (r.full && r.full[i] ? r.full[i].text : '').substring(0, 600) + '\n\n';
                }
                if (r.parts.length > 3) t += '… (' + (r.parts.length - 3) + ' partes más)\n';
                pv.textContent = t;
            });
        };
        box.querySelector('#ix-generate').onclick = function() {
            var v = vals();
            if (!v.channel_id) { showToast('Elige canal'); return; }
            if (!confirm('Vaciar el topic índice y generar ' + 'de nuevo?')) return;
            saveCfg(function() {
                showToast('Generando índice…');
                api('/api/indexator/generate', { method: 'POST', data: v }, function(r) {
                    if (r && r.success) showToast('Índice generado: ' + r.parts + ' mensajes');
                    else showToast('Error: ' + ((r && r.detail) || 'desconocido'));
                });
            });
        };
    }

    function closeModal() {
        var o = document.getElementById('indexator-overlay');
        if (o && o.parentNode) o.parentNode.removeChild(o);
    }

    // Toggle del botón rápido por flag (sin cambio core).
    function fixTray() {
        try {
            api('/api/indexator/config', {}, function(cfgres) {
                var show = true;
                try { show = (cfgres && cfgres.config && cfgres.config.show_tray) !== false; } catch (e) {}
                if (show) return;
                var tray = document.getElementById('plugin-tray-icons');
                if (!tray) return;
                var btns = tray.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var oc = btns[i].getAttribute('onclick') || '';
                    if (oc.indexOf('tvcat_indexator') !== -1 && btns[i].parentNode) {
                        btns[i].style.display = 'none';
                    }
                }
            });
        } catch (e) {}
    }

    (function() {
        function setup() {
            if (typeof window.handleTrayAction === 'function') {
                var orig = window.handleTrayAction;
                window.handleTrayAction = function(pluginName, btnIndex, el) {
                    if (pluginName === 'tvcat_indexator') {
                        openModal();
                        return;
                    }
                    orig(pluginName, btnIndex, el);
                };
            } else {
                setTimeout(setup, 100);
            }
        }
        setup();
        var origRender = window.renderPluginTray;
        if (origRender) {
            window.renderPluginTray = function() {
                origRender();
                fixTray();
            };
        }
        setTimeout(fixTray, 500);
    })();

    window.pluginSystem.registerPlugin({
        name: 'tvcat_indexator',
        type: 'general',
        displayName: 'Indexator',
        showIndexator: openModal
    });
})();
