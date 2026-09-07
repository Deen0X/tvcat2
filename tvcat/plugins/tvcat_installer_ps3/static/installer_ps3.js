(function() {
    if (!window.pluginSystem) return;

    var API = '/api/installer/ps3';

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

    function fileUrlFor(item) {
        var id = item.item_id || item.id;
        if (!id) return '';
        return '/api/stream/video/' + encodeURIComponent(id + ':0');
    }

    function extFor(destination) {
        var d = (destination || '').toLowerCase();
        if (d.indexOf('package') >= 0) return '.pkg';
        return '.iso';
    }

    function filenameFor(item, console) {
        var t = (item.title || 'download');
        var clean = t.replace(/[^\w.\-\u00f1\u00d1]+/g, '_');
        if (/\.(iso|pkg|rar|7z|zip)$/i.test(clean)) return clean;
        return clean + extFor(console.destination);
    }

    function enqueue(cid, item, console) {
        api(API + '/queue', { method: 'POST', data: {
            cid: cid, file_url: fileUrlFor(item), filename: filenameFor(item, console), size: item.file_size || 0
        }}, function(r) {
            alert(r && r.ok ? 'Encolado (' + r.queued + ' en cola)' : 'Error al encolar');
        });
    }

    function pickConsole(item) {
        api(API + '/consoles', {}, function(res) {
            var consoles = (res && res.consoles) || [];
            if (consoles.length === 0) {
                alert('No hay consolas PS3 configuradas. A\u00f1\u00e1delas en el plugin (Configurar).');
                return;
            }
            if (consoles.length === 1) { enqueue(consoles[0].id, item, consoles[0]); return; }

            var overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;';
            var panel = document.createElement('div');
            panel.style.cssText = 'background:#1a1a1e;border:1px solid #3f3f46;border-radius:10px;padding:16px;min-width:300px;';
            panel.innerHTML = '<div style="font-weight:600;margin-bottom:10px;">Enviar a consola(s) PS3:</div>';
            consoles.forEach(function(c) {
                var label = document.createElement('label');
                label.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;padding:10px;margin:4px 0;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:#fff;cursor:pointer;box-sizing:border-box;';
                label.innerHTML = '<input type="checkbox" value="' + c.id + '" style="accent-color:var(--accent);">' +
                    '<span style="flex:1;">\uD83C\uDFAE ' + c.name + ' <span style="color:#a1a1aa;font-size:12px;">(' + c.host + ')</span></span>';
                panel.appendChild(label);
            });
            var actions = document.createElement('div');
            actions.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
            var send = document.createElement('button');
            send.textContent = 'Enviar';
            send.style.cssText = 'flex:1;padding:8px;background:#e11d48;border:none;color:#fff;border-radius:6px;cursor:pointer;font-weight:600;';
            send.onclick = function() {
                var ids = [];
                var boxes = panel.querySelectorAll('input[type="checkbox"]:checked');
                for (var i = 0; i < boxes.length; i++) ids.push(boxes[i].value);
                if (ids.length === 0) { alert('Selecciona al menos una consola.'); return; }
                overlay.remove();
                for (var j = 0; j < ids.length; j++) {
                    for (var k = 0; k < consoles.length; k++) {
                        if (consoles[k].id === ids[j]) enqueue(ids[j], item, consoles[k]);
                    }
                }
            };
            var cancel = document.createElement('button');
            cancel.textContent = 'Cancelar';
            cancel.style.cssText = 'flex:1;padding:8px;background:none;border:none;color:rgba(255,255,255,0.4);cursor:pointer;';
            cancel.onclick = function() { overlay.remove(); };
            actions.appendChild(send);
            actions.appendChild(cancel);
            panel.appendChild(actions);
            overlay.appendChild(panel);
            document.body.appendChild(overlay);
        });
    }

    function sanitize(s){ return (s||'').toLowerCase().replace(/[_-]/g,' ').replace(/\s+/g,' ').trim(); }

    window.pluginSystem.registerPlugin({
        name: 'tvcat_installer_ps3',
        type: 'player',
        displayName: 'Enviar a PS3',
        playerType: 'installer_ps3',
        playLabel: '',
        playIcon: '<img src="/plugin-static/tvcat_installer_ps3/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="pluginIconFallback(this,\'\uD83C\uDFAE\',28)">',
        tooltip: 'Enviar a PS3',
        applies_to: ['juego', 'ps3'],
        action_category: 'playback',
        play: function(item) { pickConsole(item); }
    });

    // Cargar condiciones editables desde el backend (genérico) y actualizar applies_to dinámicamente
    function applyCats(cats, subs){
        try {
            var all = window.pluginSystem.getPluginsByType ? window.pluginSystem.getPluginsByType('player') : [];
            for (var i=0;i<all.length;i++) if (all[i].name==='tvcat_installer_ps3') {
                var combined = [];
                for (var c=0;c<cats.length;c++) if (combined.indexOf(cats[c])===-1) combined.push(cats[c]);
                for (var s=0;s<subs.length;s++) if (combined.indexOf(subs[s])===-1) combined.push(subs[s]);
                all[i].applies_to = combined;
                all[i]._cats = cats.slice();
                all[i]._subs = subs.slice();
            }
            if (window.pluginSystem._plugins && window.pluginSystem._plugins['tvcat_installer_ps3']) {
                var p = window.pluginSystem._plugins['tvcat_installer_ps3'];
                var comb2 = [];
                for (var c2=0;c2<cats.length;c2++) if (comb2.indexOf(cats[c2])===-1) comb2.push(cats[c2]);
                for (var s2=0;s2<subs.length;s2++) if (comb2.indexOf(subs[s2])===-1) comb2.push(subs[s2]);
                p.applies_to = comb2;
                p._cats = cats.slice();
                p._subs = subs.slice();
            }
        } catch(e){}
    }
    api('/api/plugin/tvcat_installer_ps3/cats', {}, function(res){
        if (res && res.categories) {
            applyCats(res.categories, res.subcategories||[]);
        } else {
            api(API + '/cats', {}, function(res2){
                if (res2 && res2.categories) applyCats(res2.categories, res2.subcategories||[]);
            });
        }
    });
})();
