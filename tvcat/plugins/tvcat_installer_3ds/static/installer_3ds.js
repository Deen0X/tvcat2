(function() {
    if (!window.pluginSystem) return;

    var API = '/api/installer/3ds';

    function api(url, opts, cb) {
        opts = opts || {};
        var xhr = new XMLHttpRequest();
        xhr.open(opts.method || 'GET', url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            var b = {};
            try { b = JSON.parse(xhr.responseText || '{}'); } catch(e) {}
            if (cb) cb(b);
        };
        xhr.onerror = function() { if (cb) cb({}); };
        xhr.send(opts.data ? JSON.stringify(opts.data) : null);
    }

    function fileUrlFor(item) {
        var id = item.item_id || item.id;
        if (!id) return '';
        return '/api/stream/video/' + encodeURIComponent(id + ':0');
    }

    function enqueue(cid, item) {
        var filename = (item.title || 'download').replace(/[^\w.\-\u00f1\u00d1]+/g, '_') + '.cia';
        api(API + '/queue', { method: 'POST', data: {
            cid: cid, file_url: fileUrlFor(item), filename: filename, size: item.file_size || 0
        }}, function(r) {
            alert(r && r.ok ? 'Encolado (' + r.queued + ' en cola)' : 'Error al encolar');
        });
    }

    function pickConsole(item) {
        api(API + '/consoles', {}, function(res) {
            var consoles = (res && res.consoles) || [];
            var online = consoles.filter(function(c) { return c.status === 'online'; });
            if (online.length === 0) {
                alert('No hay consolas 3DS activas. Config\u00faralas en el plugin (Configurar).');
                return;
            }
            if (online.length === 1) { enqueue(online[0].id, item); return; }

            var overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999999;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;';
            var panel = document.createElement('div');
            panel.style.cssText = 'background:#1a1a1e;border:1px solid #3f3f46;border-radius:10px;padding:16px;min-width:300px;';
            panel.innerHTML = '<div style="font-weight:600;margin-bottom:10px;">Enviar a consola(s) 3DS:</div>';
            online.forEach(function(c) {
                var label = document.createElement('label');
                label.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;padding:10px;margin:4px 0;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:#fff;cursor:pointer;box-sizing:border-box;';
                label.innerHTML = '<input type="checkbox" value="' + c.id + '" style="accent-color:var(--accent);">' +
                    '<span style="flex:1;">\uD83D\uDFE2 ' + c.name + '</span>';
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
                for (var j = 0; j < ids.length; j++) enqueue(ids[j], item);
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

    window.pluginSystem.registerPlugin({
        name: 'tvcat_installer_3ds',
        type: 'player',
        displayName: 'Instalar en 3DS',
        playerType: 'installer_3ds',
        playLabel: 'Enviar a consola',
        playIcon: '\uD83D\uDCE5',
        applies_to: ['juego', '3ds'],
        action_category: 'playback',
        play: function(item) { pickConsole(item); }
    });
})();
