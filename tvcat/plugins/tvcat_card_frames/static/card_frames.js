/**
 * TVCat Card Frames — grid-decorator de marcos PNG sobre el cover.
 * ES5 (compatible TV vieja: el JS debe parsear aunque los efectos no apliquen).
 * Prefs en servidor por usuario-dispositivo. Matching first-wins + default.
 */
(function() {
    console.log('[CardFrames] script cargado v1.0.1');
    var _sets = [];
    var _borders = {};
    var _defaultBorderId = null;
    var _prefs = { enabled: true, shine_enabled: true, shine_delay_ms: 800, shine_period_ms: 2600 };
    var _ready = false;
    var _pending = [];
    var _isOldTV = false;
    var _v = 0;

    try {
        var _ua = navigator.userAgent || '';
        _isOldTV = /NetCast|Opera TV|Maple|Obigo|CE-HTML|Tizen [123]\./i.test(_ua);
    } catch (e) {}

    function sanitize(s) {
        var v = String(s || '').trim();
        if (v === '*') return '*';
        return v.toLowerCase().replace(/[^a-z0-9]/g, '').trim();
    }
    function splitList(s) {
        var out = [];
        var parts = String(s || '').split(/[;\n,]+/);
        for (var i = 0; i < parts.length; i++) {
            var p = sanitize(parts[i]);
            if (p) out.push(p);
        }
        return out;
    }
    function setMatches(set, item) {
        var cats = splitList(set.categories);
        var subs = splitList(set.subcategories);
        var cat = sanitize(item && item.category);
        var sub = sanitize(item && item.subcategory);
        var catOk = true, subOk = true;
        if (cats.length) {
            catOk = false;
            for (var i = 0; i < cats.length; i++) if (cats[i] === '*' || cats[i] === cat) { catOk = true; break; }
        }
        if (subs.length) {
            subOk = false;
            for (var j = 0; j < subs.length; j++) if (subs[j] === '*' || subs[j] === sub) { subOk = true; break; }
        }
        return catOk && subOk;
    }
    function isCatchAll(set) {
        return splitList(set.categories).length === 0 && splitList(set.subcategories).length === 0;
    }
    function resolveBorderId(item) {
        var i, s;
        // 1) sets con filtros, por orden (el primero que casa gana)
        for (i = 0; i < _sets.length; i++) {
            s = _sets[i];
            if (!s || !s.enabled || isCatchAll(s)) continue;
            if (setMatches(s, item)) return s.border_id;
        }
        // 2) sets generales (sin filtros), por orden
        for (i = 0; i < _sets.length; i++) {
            s = _sets[i];
            if (!s || !s.enabled || !isCatchAll(s)) continue;
            return s.border_id;
        }
        // 3) borde default
        return _defaultBorderId;
    }
    function imgUrl(borderId, kind) {
        return '/api/cardframes/img/' + encodeURIComponent(borderId) + '/' + kind + '?v=' + _v;
    }
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

    function ensureInit(cb) {
        if (_ready) { if (cb) cb(); return; }
        if (cb) _pending.push(cb);
        if (_pending.length > 1) return;
        ajax({ method: 'GET', url: '/api/cardframes/sets',
            success: function(res) {
                console.log('[CardFrames] sets OK', res);
                _sets = (res && res.sets) || [];
                _sets.sort(function(a, b) { return (a.position || 0) - (b.position || 0); });
                _v = (res && res.v) || 0;
                _defaultBorderId = res && res.default_border_id;
                var bl = (res && res.borders) || [];
                for (var i = 0; i < bl.length; i++) _borders[bl[i].id] = bl[i];
                loadPrefs(function() {
                    _ready = true;
                    redecorateVisible();
                    flushPending();
                });
            },
            error: function(err) {
                console.log('[CardFrames] ERROR sets', err);
                _ready = true;
                flushPending();
            }
        });
    }
    function flushPending() {
        var q = _pending.slice(); _pending = [];
        for (var i = 0; i < q.length; i++) { try { q[i](); } catch (e) {} }
    }
    function loadPrefs(done) {
        var dev = getDeviceId();
        ajax({ method: 'GET', url: '/api/cardframes/prefs?device_id=' + encodeURIComponent(dev),
            success: function(res) {
                if (res && res.prefs) _prefs = res.prefs;
                if (done) done();
            },
            error: function() { if (done) done(); }
        });
    }
    function redecorateVisible() {
        if (!_prefs.enabled) return;
        try {
            var grid = document.getElementById('catalog-grid');
            if (!grid || !window.pluginSystem) return;
            var els = grid.querySelectorAll('.grid-item');
            for (var i = 0; i < els.length; i++) {
                var el = els[i];
                if (el.getAttribute('data-cf-done')) continue;
                var idx = parseInt(el.getAttribute('data-index') || '0', 10) || 0;
                var item = (window.Catalog && window.Catalog.currentItems && window.Catalog.currentItems[idx]) || {};
                try { decorateOne(el, item); } catch (e) {}
            }
        } catch (e) {}
    }

    function decorateOne(el, item) {
        if (!_prefs.enabled) return;
        if (el.getAttribute('data-cf-done')) return;
        var bid = resolveBorderId(item);
        if (!bid) return;
        var cover = el.querySelector ? el.querySelector('.grid-item-cover') : null;
        if (!cover) return;
        el.setAttribute('data-cf-done', '1');
        el.setAttribute('data-cf-border', bid);
        var fr = document.createElement('div');
        fr.className = 'card-frame';
        var im = document.createElement('img');
        im.alt = '';
        im.src = imgUrl(bid, 'idle');
        im.onerror = function() { try { fr.style.display = 'none'; } catch (e) {} };
        fr.appendChild(im);
        cover.appendChild(fr);
        var sh = null;
        if (!_isOldTV && _prefs.shine_enabled) {
            sh = document.createElement('div');
            sh.className = 'card-shine';
            cover.appendChild(sh);
        }
        function select() {
            if (!_prefs.enabled) return;
            try {
                el.className = (el.className + ' card-selected').replace(/\s+/g, ' ');
                im.src = imgUrl(bid, 'selected');
                if (sh) {
                    sh.className = 'card-shine';
                    var delay = Math.max(0, _prefs.shine_delay_ms || 0);
                    var period = Math.max(600, _prefs.shine_period_ms || 2600);
                    sh.style['animation-duration'] = period + 'ms';
                    sh.style['animation-delay'] = delay + 'ms';
                    setTimeout(function() {
                        try { if (el.className.indexOf('card-selected') !== -1) sh.className = 'card-shine shine-go'; } catch (e) {}
                    }, delay + 30);
                }
            } catch (e) {}
        }
        function deselect() {
            try {
                el.className = (' ' + el.className + ' ').split(' card-selected ').join(' ');
                im.src = imgUrl(bid, 'idle');
                if (sh) sh.className = 'card-shine';
            } catch (e) {}
        }
        if (el.addEventListener) {
            el.addEventListener('mouseover', select, false);
            el.addEventListener('mouseout', deselect, false);
            el.addEventListener('focus', select, false);
            el.addEventListener('blur', deselect, false);
        }
    }

    if (window.pluginSystem) {
        window.pluginSystem.registerPlugin({
            name: 'tvcat_card_frames',
            type: 'grid-decorator',
            displayName: 'Marcos de carta',
            onGridItem: function(element, itemData) {
                ensureInit(function() { try { decorateOne(element, itemData); } catch (e) {} });
            },
            refreshCardFrames: function() {
                _ready = false; _sets = []; _defaultBorderId = null; _v = 0;
                try {
                    var grid = document.getElementById('catalog-grid');
                    if (grid) {
                        var els = grid.querySelectorAll('.grid-item');
                        for (var i = 0; i < els.length; i++) {
                            els[i].removeAttribute('data-cf-done');
                            els[i].removeAttribute('data-cf-border');
                            els[i].className = (' ' + els[i].className + ' ').split(' card-selected ').join(' ');
                            var olds = els[i].querySelectorAll('.card-frame,.card-shine');
                            for (var k = olds.length - 1; k >= 0; k--) {
                                if (olds[k].parentNode) olds[k].parentNode.removeChild(olds[k]);
                            }
                        }
                    }
                } catch (e) {}
                ensureInit(null);
            }
        });
    }
})();
