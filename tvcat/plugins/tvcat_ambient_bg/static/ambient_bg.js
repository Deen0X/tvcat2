/**
 * TVCat Ambient BG — fondo ambiental del item seleccionado.
 * ES5. Sin filter:blur (downscale por canvas = blur gratis). Doble buffer + crossfade.
 */
(function() {
    var _prefs = { enabled: true, mode: 'lava', crop: 'center', veil: 55, blur: 48, drift_s: 24 };
    var _ready = false;
    var _pending = [];
    var _layerA = null, _layerB = null, _veil = null, _front = null;
    var _currentEl = null, _currentKey = null;
    var _cache = {}, _cacheOrder = [];
    var _MAXCACHE = 60;

    function getDeviceId() {
        try {
            var d = localStorage.getItem('tvcat_device_id');
            if (!d) {
                d = 'dev-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
                localStorage.setItem('tvcat_device_id', d);
            }
            return d;
        } catch (e) { return 'default'; }
    }
    function ajax(opts) {
        if (window.API && window.API.ajax) return window.API.ajax(opts);
        var xhr = new XMLHttpRequest();
        xhr.open(opts.method || 'GET', opts.url, true);
        if (opts.data) xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function() {
            var b = {};
            try { b = JSON.parse(xhr.responseText || '{}'); } catch (e) {}
            if (xhr.status >= 200 && xhr.status < 300) { if (opts.success) opts.success(b); }
            else if (opts.error) opts.error(b);
        };
        xhr.onerror = function() { if (opts.error) opts.error({}); };
        xhr.send(opts.data ? JSON.stringify(opts.data) : null);
    }
    function ensureLayers() {
        if (_layerA) return;
        try {
            _layerA = document.createElement('div'); _layerA.id = 'amb-bg-a';
            _layerB = document.createElement('div'); _layerB.id = 'amb-bg-b';
            _veil = document.createElement('div'); _veil.id = 'amb-veil';
            document.body.appendChild(_layerA);
            document.body.appendChild(_layerB);
            document.body.appendChild(_veil);
            _front = _layerA;
            applyVeil();
        } catch (e) {}
    }
    function applyVeil() {
        if (!_veil) return;
        try { _veil.style.opacity = String((_prefs.veil || 0) / 100); } catch (e) {}
    }
    function ensureInit(cb) {
        if (_ready) { if (cb) cb(); return; }
        if (cb) _pending.push(cb);
        if (_pending.length > 1) return;
        ajax({ method: 'GET', url: '/api/ambient/prefs?device_id=' + encodeURIComponent(getDeviceId()),
            success: function(res) {
                if (res && res.prefs) _prefs = res.prefs;
                ensureLayers();
                _ready = true;
                flushPending();
            },
            error: function() {
                ensureLayers();
                _ready = true;
                flushPending();
            }
        });
    }
    function flushPending() {
        var q = _pending.slice(); _pending = [];
        for (var i = 0; i < q.length; i++) { try { q[i](); } catch (e) {} }
    }
    function coverUrl(item, cached) {
        var id = (item && (item.item_id || item.id)) || '';
        var u = (item && item.cover_url) || ('/api/cover/' + id);
        if (!id && !item.cover_url) return '';
        if (cached && u.indexOf('/api/cover/') === 0) {
            u += (u.indexOf('?') === -1 ? '?cached=1' : '&cached=1');
        }
        return u;
    }
    function cacheGet(k) { return _cache[k] || null; }
    function cachePut(k, v) {
        if (!_cache[k]) _cacheOrder.push(k);
        _cache[k] = v;
        while (_cacheOrder.length > _MAXCACHE) {
            var old = _cacheOrder.shift();
            try { delete _cache[old]; } catch (e) {}
        }
    }
    function loadImage(url, ok, fail) {
        try {
            var im = new Image();
            im.onload = function() { ok(im); };
            im.onerror = function() { fail(); };
            im.src = url;
        } catch (e) { fail(); }
    }
    function cropRect(w, h) {
        var side = Math.floor(Math.min(w, h) * 0.62);
        if (side < 8) return { x: 0, y: 0, w: w, h: h };
        var x, y;
        if (_prefs.crop === 'random') {
            x = Math.floor(Math.random() * Math.max(1, w - side));
            y = Math.floor(Math.random() * Math.max(1, h - side));
        } else {
            x = Math.floor((w - side) / 2);
            y = Math.floor((h - side) / 2);
        }
        return { x: x, y: y, w: side, h: side };
    }
    function buildEntry(item, done) {
        var key = (item && (item.item_id || item.id)) || '';
        if (!key) { done(null); return; }
        var hit = cacheGet(key);
        if (hit) { done(hit); return; }
        var url1 = coverUrl(item, true);
        function attempt(url, last) {
            loadImage(url, function(im) {
                try {
                    var bw = Math.max(16, _prefs.blur || 48);
                    var bh = Math.max(10, Math.round(bw * 0.62));
                    var r = cropRect(im.width || im.naturalWidth || 300, im.height || im.naturalHeight || 450);
                    var cv = document.createElement('canvas');
                    cv.width = bw; cv.height = bh;
                    var cx = cv.getContext('2d');
                    cx.drawImage(im, r.x, r.y, r.w, r.h, 0, 0, bw, bh);
                    var entry = { url: null, palette: null };
                    try { entry.url = cv.toDataURL('image/jpeg', 0.82); } catch (e) { entry.url = null; }
                    try { entry.palette = samplePalette(cx, bw, bh); } catch (e) { entry.palette = null; }
                    if (!entry.url && !entry.palette) throw new Error('empty');
                    cachePut(key, entry);
                    done(entry);
                } catch (e) {
                    if (!last) attempt(coverUrl(item, false), true);
                    else done(null);
                }
            }, function() {
                if (!last) attempt(coverUrl(item, false), true);
                else done(null);
            });
        }
        attempt(url1, url1.indexOf('cached=1') === -1);
    }
    function samplePalette(cx, w, h) {
        var d = cx.getImageData(0, 0, w, h).data;
        var buckets = {};
        var i, r, g, b, key;
        for (i = 0; i < d.length; i += 16) {
            r = d[i] - (d[i] % 32); g = d[i + 1] - (d[i + 1] % 32); b = d[i + 2] - (d[i + 2] % 32);
            var lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            if (lum < 18 || lum > 235) continue;
            key = r + ',' + g + ',' + b;
            buckets[key] = (buckets[key] || 0) + 1;
        }
        var arr = [];
        for (key in buckets) { if (buckets.hasOwnProperty(key)) arr.push([buckets[key], key]); }
        arr.sort(function(a, b2) { return b2[0] - a[0]; });
        var out = [];
        for (i = 0; i < arr.length && out.length < 3; i++) {
            var p = arr[i][1].split(',');
            var ok = true;
            for (var j = 0; j < out.length; j++) {
                var q = out[j];
                var dist = Math.abs(p[0] - q[0]) + Math.abs(p[1] - q[1]) + Math.abs(p[2] - q[2]);
                if (dist < 96) { ok = false; break; }
            }
            if (ok) out.push([parseInt(p[0], 10), parseInt(p[1], 10), parseInt(p[2], 10)]);
        }
        while (out.length < 3) out.push([40, 40, 60]);
        return out;
    }
    function rgb(c) { return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'; }
    function showEntry(entry) {
        if (!entry || !_layerA) return;
        try {
            var incoming = (_front === _layerA) ? _layerB : _layerA;
            // Limpiar contenido previo
            while (incoming.firstChild) incoming.removeChild(incoming.firstChild);
            incoming.style.backgroundImage = '';
            incoming.style.backgroundColor = '#000';
            if (_prefs.mode === 'lava' && entry.palette) {
                var p = entry.palette;
                var drift = document.createElement('div');
                drift.className = 'amb-lava-drift';
                try { drift.style['animation-duration'] = Math.max(8, _prefs.drift_s || 24) + 's'; } catch (e) {}
                drift.style.background =
                    'radial-gradient(circle at 25% 30%, ' + rgb(p[0]) + ' 0%, rgba(0,0,0,0) 55%),' +
                    'radial-gradient(circle at 75% 60%, ' + rgb(p[1]) + ' 0%, rgba(0,0,0,0) 55%),' +
                    'radial-gradient(circle at 50% 85%, ' + rgb(p[2]) + ' 0%, rgba(0,0,0,0) 60%),' +
                    '#0a0a0c';
                incoming.appendChild(drift);
            } else if (entry.url) {
                incoming.style.backgroundImage = "url('" + entry.url + "')";
            } else if (entry.palette) {
                incoming.style.backgroundColor = rgb(entry.palette[0]);
            } else {
                return;
            }
            incoming.style.opacity = '1';
            var outgoing = _front;
            _front = incoming;
            try { outgoing.style.opacity = '0'; } catch (e) {}
            applyVeil();
        } catch (e) {}
    }
    function fadeOut() {
        try {
            if (_layerA) _layerA.style.opacity = '0';
            if (_layerB) _layerB.style.opacity = '0';
            if (_veil) _veil.style.opacity = '0';
        } catch (e) {}
    }
    function select(el, item) {
        if (!_ready || !_prefs.enabled || _prefs.mode === 'off') return;
        // Last-wins también a nivel de fondo
        if (_currentEl && _currentEl !== el) { _currentEl = null; }
        _currentEl = el;
        var key = (item && (item.item_id || item.id)) || '';
        _currentKey = key;
        buildEntry(item, function(entry) {
            if (_currentEl !== el) return;
            if (entry) showEntry(entry);
        });
    }
    function deselect(el) {
        if (_currentEl !== el) return;
        _currentEl = null;
        _currentKey = null;
        setTimeout(function() {
            if (!_currentEl) fadeOut();
        }, 120);
    }
    if (window.pluginSystem) {
        window.pluginSystem.registerPlugin({
            name: 'tvcat_ambient_bg',
            type: 'grid-decorator',
            displayName: 'Fondo ambiental',
            onGridItem: function(element, itemData) {
                ensureInit(function() {
                    if (element.getAttribute('data-amb-done')) return;
                    element.setAttribute('data-amb-done', '1');
                    if (element.addEventListener) {
                        element.addEventListener('mouseover', function() { select(element, itemData); }, false);
                        element.addEventListener('mouseout', function() { deselect(element); }, false);
                        element.addEventListener('focus', function() { select(element, itemData); }, false);
                        element.addEventListener('blur', function() { deselect(element); }, false);
                    }
                });
            },
            refreshAmbient: function() {
                _ready = false;
                ensureInit(function() {
                    if (!_prefs.enabled || _prefs.mode === 'off' || !_currentEl) { fadeOut(); return; }
                    applyVeil();
                    _currentEl = null;
                    try {
                        var grid = document.getElementById('catalog-grid');
                        var sel = grid ? grid.querySelector('.grid-item.card-selected,.grid-item.focused') : null;
                        if (sel) {
                            var idx = parseInt(sel.getAttribute('data-index') || '0', 10) || 0;
                            var item = (window.Catalog && window.Catalog.currentItems && window.Catalog.currentItems[idx]) || {};
                            select(sel, item);
                        } else fadeOut();
                    } catch (e) { fadeOut(); }
                });
            }
        });
    }
})();
