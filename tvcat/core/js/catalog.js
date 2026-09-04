(function() {
    var currentCategory = 'home';
    var currentItems = [];

    // Variants & Episodes state
    var currentVariantId = null;
    var currentEpisodes = {};
    var currentMediaId = null;
    var episodesModalWasOpen = false;
    var lastFocusedDetailsAction = null;

    function excludedGenres() {
        var out = [];
        if (window._activeFilters && window._activeFilters.categories) {
            for (var g in window._activeFilters.categories) {
                if (window._activeFilters.categories[g] !== false) continue;
                var tags = (window._tagDictionary && window._tagDictionary[g]) || [g];
                for (var i = 0; i < tags.length; i++) {
                    if (out.indexOf(tags[i]) === -1) out.push(tags[i]);
                }
            }
        }
        return out;
    }

    function buildFilterParams() {
        var params = [];
        if (window._activeFilters) {
            if (window._activeFilters.year_from) params.push('year_from=' + window._activeFilters.year_from);
            if (window._activeFilters.year_to) params.push('year_to=' + window._activeFilters.year_to);
        }
        var exg = excludedGenres();
        if (exg.length) params.push('genres=' + encodeURIComponent(exg.join(',')));
        return params;
    }

    // Coalescencia de refrescos: CUALQUIER llamada a load()/performSearch()
    // (navegación, arranque, guardados de config, rebuild, toggles) entra en
    // una ventana de 120 ms; si llega otra petición se reinicia el tiempo y
    // solo la ÚLTIMA dispara UNA petición de red + UN skeleton + UN pintado,
    // leyendo búsqueda/filtros vivos en el momento del disparo.
    // Además, por secuencia, si una petición anterior sigue en vuelo cuando
    // llega la respuesta nueva, la vieja se descarta y no pinta.
    var _loadSeq = 0;
    var _loadTimer = null;
    var _pendingReq = null;

    function load(category) {
        _pendingReq = { type: 'load', category: category || 'home' };
        _kickLoadTimer();
    }

    function performSearch(query) {
        if (!query || query.trim().length < 2) {
            load(currentCategory);
            return;
        }
        _pendingReq = { type: 'search', query: query };
        _kickLoadTimer();
    }

    function _kickLoadTimer() {
        if (_loadTimer) clearTimeout(_loadTimer);
        _loadTimer = setTimeout(function() {
            _loadTimer = null;
            var r = _pendingReq;
            _pendingReq = null;
            if (!r) return;
            if (r.type === 'search') _doSearch(r.query);
            else _doLoad(r.category);
        }, 120);
    }

    function _doLoad(category) {
        currentCategory = category || 'home';
        // Si hay búsqueda activa, delegar a búsqueda para respetar filtro de texto
        var si = document.getElementById('global-search');
        var st = si ? si.value.trim() : '';
        if (st.length >= 2) {
            _doSearch(st);
            return;
        }
        var url = '/api/catalog/' + currentCategory;
        var fp = buildFilterParams();
        if (fp.length) url += '?' + fp.join('&');

        var mySeq = ++_loadSeq;
        showLoading(true);
        window.API.ajax({
            url: url,
            success: function(data) {
                if (mySeq !== _loadSeq) return;
                currentItems = data.items || [];
                if (currentCategory === 'favorites') {
                    currentItems = currentItems.filter(function(it) { return it.fav === true; });
                }
                renderItems(currentItems);
                updateBadge(data.count !== undefined ? data.count : currentItems.length);
                showLoading(false);
            },
            error: function() {
                if (mySeq !== _loadSeq) return;
                showLoading(false);
                var grid = document.getElementById('catalog-grid');
                if (grid) grid.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:40px;">Error al cargar el catálogo</p>';
            }
        });
    }

    function _doSearch(query) {
        if (!query || query.trim().length < 2) {
            _doLoad(currentCategory);
            return;
        }

        var processed = parseWildcardSearch(query).join(' ');
        var url = '/api/catalog/' + currentCategory + '?search=' + encodeURIComponent(processed);

        var fields = [];
        if (window._activeFilters) {
            if (window._activeFilters.fields.title) fields.push('title');
            if (window._activeFilters.fields.alt_titles) fields.push('alt_titles');
            if (window._activeFilters.fields.description) fields.push('description');
            url += '&fields=' + encodeURIComponent(fields.join(','));
            if (window._activeFilters.year_from) url += '&year_from=' + window._activeFilters.year_from;
            if (window._activeFilters.year_to) url += '&year_to=' + window._activeFilters.year_to;
        }
        var exg = excludedGenres();
        if (exg.length) url += '&genres=' + encodeURIComponent(exg.join(','));

        var mySeq = ++_loadSeq;
        showLoading(true);
        window.API.ajax({
            url: url,
            success: function(data) {
                if (mySeq !== _loadSeq) return;
                currentItems = data.items || [];
                if (currentCategory === 'favorites') {
                    currentItems = currentItems.filter(function(it) { return it.fav === true; });
                }
                renderItems(currentItems);
                updateBadge(data.count || 0);
                showLoading(false);
            },
            error: function() {
                if (mySeq !== _loadSeq) return;
                showLoading(false);
            }
        });
    }

    function parseWildcardSearch(query) {
        var normalized = query.toLowerCase().trim().replace(/\s+/g, ' ');
        if (normalized.indexOf('*') === -1) {
            return [normalized];
        }
        var parts = normalized.split('*').filter(function(p) { return p.trim() !== ''; });
        return parts.length > 0 ? parts : [normalized];
    }

    function renderItems(items) {
        var grid = document.getElementById('catalog-grid');
        if (!grid) return;

        if (!items || items.length === 0) {
            grid.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:60px 20px;grid-column:1/-1;">No hay elementos disponibles</p>';
            return;
        }

        if (window.UI && window.UI.getMaxElements) {
            var maxEl = window.UI.getMaxElements();
            if (items.length > maxEl) {
                items = items.slice(0, maxEl);
            }
        }

        var html = '';
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var title = item.title || 'Sin título';
            var cat = item.category || '';
            var year = item.year || '';
            var repId = item.representative_id || item.item_id || '';
            var favActive = item.fav ? ' active' : '';
            var favFill = item.fav ? '#e11d48' : 'rgba(255, 255, 255, 0.4)';
            var _cid = item.item_id || '';
            var _src = item.cover_url || ('/api/cover/' + _cid);
            // 2026-09-04: genérico directo por categoría si falla (NO reintentar
            // /api/cover: duplicaba los 404 y quemaba tokens del throttle).
            var _cl = (cat || '').toLowerCase();
            var _sl = ((item.subcategory || '').toLowerCase());
            var _def = (/(juego|game|consola|ps3|3ds)/.test(_cl) || /(juego|game|consola|ps3|3ds)/.test(_sl)) ? -1
                : (/(comic|kiosko|book|ebook|manga)/.test(_cl) || /(comic|kiosko|book|ebook|manga)/.test(_sl)) ? -2 : -3;
            // Placeholder logo debajo (se ve mientras el cover real descarga);
            // el real se bombea con concurrencia máx 4 para no saturar las 6
            // conexiones del navegador (el XHR del hero necesita un slot libre).
            // 2026-09-04c: SIN loading=lazy (la bomba es la que dosifica; con lazy
            // las offscreen no resolvían nunca y la bomba se atascaba sin fase 2).
            var coverImg = '<img src="/static/TVCat.png" class="grid-cover-ph" alt="" onerror="this.style.display=\'none\'">' +
                '<img data-csrc="' + _src + '" data-cdef="' + _def + '" alt="">';

            html += '<div class="grid-item" tabindex="0" data-id="' + item.item_id + '" data-index="' + i + '" data-rep-id="' + repId + '">' +
                '<div class="grid-item-cover">' +
                coverImg +
                '<div class="grid-item-badge">' + cat.charAt(0).toUpperCase() + cat.slice(1) + '</div>' +
                (item.has_mkv ? '<div class="grid-item-badge-mkv"><img src="/static/mkv.png" onerror="this.parentNode.textContent=\'\uD83D\uDCE6\'"></div>' : '') +
                '<button class="grid-item-fav' + favActive + '" data-fav="' + (item.fav ? 'true' : 'false') + '" data-rep-id="' + repId + '" onclick="Catalog.toggleGridFavorite(event,\'' + item.item_id + '\',\'' + cat + '\')">' +
                '<svg viewBox="0 0 24 24" fill="' + favFill + '"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>' +
                '</button>' +
                '</div>' +
                '<div class="grid-item-info">' +
                '<div class="grid-item-title">' + escapeHtml(title) + '</div>' +
                (year ? '<div class="grid-item-year">' + year + '</div>' : '') +
                '</div>' +
                '</div>';
        }

        grid.innerHTML = html;
        var itemElements = grid.querySelectorAll('.grid-item');
        for (var di = 0; di < itemElements.length; di++) {
            var el = itemElements[di];
            var idx = parseInt(el.getAttribute('data-index')) || 0;
            var itemData = items[idx] || {};
            window.pluginSystem.applyGridDecorators(el, itemData);
        }
        _pumpCovers(grid);

        grid.onclick = function(e) {
            var t = e.target || e.srcElement;
            var item = closestClass(t, 'grid-item');
            if (item && !closestClass(t, 'grid-item-fav')) {
                var id = item.getAttribute('data-id');
                if (id) window.openDetails(id);
            }
        };
    }

    // Bomba de covers en 2 fases (2026-09-04): el navegador solo tiene ~6
    // conexiones; con máx 4 siempre quedan slots para interactuar. ES5.
    // Fase 1: ?cached=1 (solo caché, ms) pinta al instante lo disponible; los
    // 404 quedan en placeholder y pasan a fase 2 (JIT Telegram, visibles).
    function _pumpCovers(grid) {
        var list = grid.querySelectorAll('img[data-csrc]');
        var queue = [];
        for (var qi = 0; qi < list.length; qi++) queue.push(list[qi]);
        var active = 0;
        var MAXC = 4;
        function cachedUrl(u) {
            if (u.indexOf('/api/cover/') === 0) return u + (u.indexOf('?') === -1 ? '?cached=1' : '&cached=1');
            return u;
        }
        function phase2() {
            var miss = grid.querySelectorAll('img[data-cmiss="1"]');
            var q2 = [];
            for (var mi = 0; mi < miss.length; mi++) q2.push(miss[mi]);
            if (!q2.length) return;
            var a2 = 0;
            function nx2() {
                while (a2 < MAXC && q2.length) {
                    var im = q2.shift();
                    a2++;
                    (function(el) {
                        el.removeAttribute('data-cmiss');
                        var fin = function() { a2--; nx2(); };
                        el.onload = fin;
                        el.onerror = function() {
                            el.onerror = null;
                            el.src = '/api/cover-default/' + el.getAttribute('data-cdef');
                            fin();
                        };
                        el.src = el.getAttribute('data-csrc');
                    })(im);
                }
            }
            nx2();
        }
        function next() {
            while (active < MAXC && queue.length) {
                var im = queue.shift();
                active++;
                (function(el) {
                    var src = el.getAttribute('data-csrc');
                    var fin = function() {
                        active--;
                        if (!queue.length && active === 0) phase2();
                        else next();
                    };
                    el.onload = fin;
                    el.onerror = function() {
                        el.onerror = null;
                        el.setAttribute('data-cmiss', '1');
                        fin();
                    };
                    el.src = cachedUrl(src);
                })(im);
            }
        }
        next();
    }

    // Compatible closest() for old WebKit Smart TVs (no Element.closest)
    function closestClass(el, cls) {
        while (el) {
            if (el.className && ((' ' + el.className + ' ').indexOf(' ' + cls + ' ') !== -1)) return el;
            el = el.parentNode;
        }
        return null;
    }

    function escapeHtml(text) {
        if (!text) return '';
        var d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }

    function updateBadge(count) {
        var badge = document.getElementById('results-count');
        if (!badge) return;
        var maxEl = 999999;
        if (window.UI && window.UI.getMaxElements) {
            maxEl = window.UI.getMaxElements();
        }
        var displayCount = Math.min(count, maxEl);
        badge.textContent = displayCount + ' ítem' + (displayCount !== 1 ? 's' : '');
    }

    function showLoading(show) {
        var grid = document.getElementById('catalog-grid');
        if (!grid) return;
        if (show) {
            var items = [];
            for (var i = 0; i < 12; i++) {
                items.push('<div class="grid-item grid-item-skeleton"><div class="grid-item-cover" style="background:#18181b;background:var(--bg-surface);animation:pulse 1.5s infinite;"><img src="/static/TVCat.png" alt="" style="object-fit:contain;padding:25%;opacity:0.5;" onerror="this.style.display=\'none\'"></div></div>');
            }
            grid.innerHTML = items.join('');
        }
    }

    window.Catalog = {
        currentUser: {},
        load: load,
        performSearch: performSearch,
        renderItems: renderItems,
        updateSidebarProfileUI: function() {
            var u = this.currentUser || {};
            var nameEl = document.getElementById('side-profile-name');
            var avatarEl = document.getElementById('side-avatar');
            if (nameEl && u.display_name) nameEl.textContent = u.display_name;
            if (avatarEl) {
                if (u.avatar_url) {
                    avatarEl.innerHTML = '<img src="' + u.avatar_url + '" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">';
                } else if (u.avatar) {
                    avatarEl.textContent = u.avatar;
                }
                if (u.color) avatarEl.style.background = u.color;
            }
            if (typeof window.syncNavbarAvatar === 'function') window.syncNavbarAvatar();
        },
        get currentCategory() { return currentCategory; },
        set currentCategory(v) { currentCategory = v; },
        get currentItems() { return currentItems; },
        detectDeviceCapabilities: function() {
            if (typeof window.detectDeviceCapabilities === 'function') {
                return window.detectDeviceCapabilities();
            }
            var ua = navigator.userAgent;
            var isSmartTV = /Tizen|WebOS|SmartTV|Android TV|Philips|SonyBravia|Roku|SamsungBrowser|NetCast|SMART-TV|Smart-TV|Opera TV|Maple|Obigo|Espial|CE-HTML|DIRECTV|DuneHD|AppleTV|GoogleTV/i.test(ua);
            var isOldSmartTV = isSmartTV && (/NetCast|Opera TV|Maple|Obigo|CE-HTML|Tizen [123]\./i.test(ua) || (/WebOS/i.test(ua) && /Web0S\/[123]\./i.test(ua)));
            var supportsPlyr = typeof Plyr !== 'undefined';
            return { isSmartTV: isSmartTV, isOldSmartTV: isOldSmartTV, supportsPlyr: supportsPlyr };
        },
        getPlayerType: function() {
            if (typeof window.getPlayerType === 'function') {
                return window.getPlayerType();
            }
            var pref = localStorage.getItem('tvcat_preferred_player');
            if (!pref || pref === 'auto') {
                var caps = this.detectDeviceCapabilities();
                if (caps.isOldSmartTV) return 'basic';
                if (caps.isSmartTV || !caps.supportsPlyr) return 'native';
                return 'plyr';
            }
            return pref;
        }
    };
    window.Catalog.currentEpisodes = currentEpisodes;
    window.refreshCover = function(itemId) {
        if (!confirm('¿Refrescar cover desde Telegram? Se re-descargará la imagen del mensaje original.')) return;
        var btn = document.querySelector('.meta-cover-refresh');
        if (btn) { btn.textContent = '…'; btn.disabled = true; }
        window.API.ajax({
            method: 'POST',
            url: '/api/cover/' + encodeURIComponent(itemId) + '/refresh',
            success: function(res) {
                if (btn) { btn.textContent = '✓'; setTimeout(function(){ btn.textContent='🔄'; btn.disabled=false; }, 1500); }
                var gridImg = document.querySelector('.grid-item[data-id="' + itemId + '"] img');
                if (gridImg) gridImg.src = '/api/cover/' + encodeURIComponent(itemId) + '?v=' + Date.now();
                var detailBg = document.getElementById('detail-backdrop');
                if (detailBg) detailBg.style.backgroundImage = "url('/api/cover/" + encodeURIComponent(itemId) + "?v=" + Date.now() + "')";
                setTimeout(function(){ window.Catalog.load(window.Catalog.currentCategory); }, 800);
            },
            error: function(err) {
                if (btn) { btn.textContent = '✗'; btn.disabled=false; setTimeout(function(){ btn.textContent='🔄'; }, 1500); }
                var msg = (err && err.detail) ? err.detail : (err && err.error ? err.error : 'desconocido');
                alert('Error al refrescar cover: ' + msg);
            }
        });
    };

    // ====== SLIDESHOW ENGINE ======
    var _slideshowImages = [];
    var _currentSlideIndex = -1;
    var _activeBackdropEl = null;
    var _slideshowTimeout = null;

    function scheduleNextSlide(delay) {
        _slideshowTimeout = setTimeout(function() {
            transitionToNextSlide();
        }, delay);
    }

    function transitionToNextSlide() {
        if (!_slideshowImages || _slideshowImages.length <= 1) return;
        var backdrop1 = document.getElementById('detail-backdrop');
        var backdrop2 = document.getElementById('detail-backdrop-next');
        if (!backdrop1 || !backdrop2) return;

        _currentSlideIndex = (_currentSlideIndex + 1) % _slideshowImages.length;
        var nextSlide = _slideshowImages[_currentSlideIndex];

        var currentEl = _activeBackdropEl;
        var nextEl = (currentEl === backdrop1) ? backdrop2 : backdrop1;

        nextEl.style.backgroundImage = "url('" + nextSlide.url + "')";
        nextEl.style.backgroundSize = nextSlide.mode;
        nextEl.style.backgroundPosition = nextSlide.align;
        nextEl.style.backgroundRepeat = 'no-repeat';
        nextEl.style.opacity = '1';
        currentEl.style.opacity = '0';
        // El zoom (Ken Burns) SOLO se muestra al abrir el hero; las
        // transiciones del ciclo son fundidos sin zoom (como tvcat1)
        nextEl.classList.remove('zoom-active');
        currentEl.classList.remove('zoom-active');
        _activeBackdropEl = nextEl;
        scheduleNextSlide(3500);
    }

    // ====== OPEN DETAILS ======
    window.openDetails = function(itemId) {
        window.API.ajax({
            url: '/api/movie/' + itemId,
            success: function(data) {
                showDetails(data, false);
            },
            error: function() {
                alert('Error al cargar detalles');
            }
        });
    };

    // ====== SHOW DETAILS (with variant support) ======
    function showDetails(item, isVariantSwitch) {
    currentVariantId = item.item_id || item.id;

    if (!isVariantSwitch && item.suggested_variant_id && String(item.suggested_variant_id) !== String(currentVariantId)) {
        window.API.ajax({
            url: '/api/movie/' + item.suggested_variant_id,
            success: function(data) { showDetails(data, false); }
        });
        return;
    }

        var updateMetadataDOM = function() {
            // Title
            var titleEl = document.getElementById('detail-title');
            if (titleEl) titleEl.textContent = item.group_title || item.title || '';

            // Year, Rating, Category
            var tech = item.technical_info || {};
            var yearEl = document.getElementById('meta-year');
            if (yearEl) {
                var y = tech.year || item.year || '';
                yearEl.textContent = y || '';
                yearEl.style.display = y ? '' : 'none';
            }

            var ratingEl = document.getElementById('meta-rating');
            if (ratingEl) {
                var r = tech.rating || item.rating;
                if (r) {
                    ratingEl.textContent = '⭐ ' + (parseFloat(r) ? parseFloat(r).toFixed(1) : r);
                    ratingEl.style.display = '';
                } else {
                    ratingEl.style.display = 'none';
                }
            }

            var categoryEl = document.getElementById('meta-category');
            if (categoryEl) {
                var catParts = [];
                if (tech.type) catParts.push(tech.type);
                else if (item.category) catParts.push(item.category);
                var sourceBadge = tech.source || item.subcategory || '';
                categoryEl.textContent = catParts.join(' / ') || item.category || '';
            }

            // Tech badges
            var metaEl = document.querySelector('.detail-meta');
            if (metaEl) {
                var oldBadges = metaEl.querySelectorAll('.meta-tech-badge');
                for (var bi = oldBadges.length - 1; bi >= 0; bi--) oldBadges[bi].remove();

                if (tech.episodes) {
                    var epBadge = document.createElement('span');
                    epBadge.className = 'meta-badge meta-tech-badge';
                    epBadge.textContent = tech.episodes + (parseInt(tech.episodes) === 1 ? ' Episodio' : ' Episodios');
                    metaEl.appendChild(epBadge);
                }
                if (tech.votes) {
                    var vBadge = document.createElement('span');
                    vBadge.className = 'meta-badge meta-tech-badge';
                    vBadge.textContent = tech.votes + ' votos';
                    metaEl.appendChild(vBadge);
                }
                if (tech.source) {
                    var srcBadge = document.createElement('span');
                    srcBadge.className = 'meta-badge meta-tech-badge';
                    srcBadge.textContent = tech.source;
                    metaEl.appendChild(srcBadge);
                }
            }

            // Features pills
            var featuresEl = document.getElementById('detail-features');
            if (featuresEl) {
                featuresEl.innerHTML = '';
                var genresStr = tech.genres || item.genres || '';
                if (genresStr) {
                    genresStr.split(',').forEach(function(g) {
                        if (g.trim()) {
                            var pill = document.createElement('span');
                            pill.className = 'feature-pill';
                            pill.textContent = g.trim();
                            featuresEl.appendChild(pill);
                        }
                    });
                }
                // Also metadata_json info_messages
                try {
                    var meta = item.metadata_json ? JSON.parse(item.metadata_json) : {};
                    var info = meta.info_messages || '';
                    if (info) {
                        var parts = info.split(',');
                        for (var pi = 0; pi < parts.length; pi++) {
                            var p = parts[pi].trim();
                            if (p) {
                                var pill = document.createElement('span');
                                pill.className = 'feature-pill';
                                pill.textContent = p;
                                featuresEl.appendChild(pill);
                            }
                        }
                    }
                } catch(e) {}
            }

            // Original title
            var origTitleEl = document.getElementById('detail-original-title');
            if (origTitleEl) origTitleEl.textContent = item.group_title || item.title || '';

            // Description
            var descEl = document.getElementById('detail-desc');
            if (descEl) {
                descEl.style.whiteSpace = 'pre-line';
                var cleanDesc = (item.description || 'Sin descripción disponible.');
                cleanDesc = cleanDesc.replace(/\\n/g, '\n');
                cleanDesc = cleanDesc.replace(/\u00a0/g, ' ');
                cleanDesc = cleanDesc.replace(/\u25aa\ufe0f/g, '\n\u25aa\ufe0f');
                var keywords = ['Actualizaci\u00f3n:', 'Idioma:', 'Tama\u00f1o:', 'Partes:', 'Medicina:', 'Contenido Extra:', 'Sinopsis:', 'Serial:', 'Formato:', 'Discos:', 'Funciona desde:', 'Fecha de estreno:'];
                for (var ki = 0; ki < keywords.length; ki++) {
                    var kw = keywords[ki];
                    var safeKw = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    var kwRegex = new RegExp('([^\n])(' + safeKw + ')', 'g');
                    cleanDesc = cleanDesc.replace(kwRegex, '$1\n$2');
                }
                cleanDesc = cleanDesc.replace(/^\n/, '');
                descEl.textContent = cleanDesc;
            }

            // Extra specs
            var specsEl = document.getElementById('detail-extra-specs');
            if (specsEl) {
                specsEl.innerHTML = '<h3>Ficha Técnica</h3>';
                var specsHTML = '';
                var cat = (item.category || '').toLowerCase();
                if (cat === 'game') {
                    var devs = (item.developers && item.developers.length > 0) ? item.developers.join(', ') : null;
                    if (devs) specsHTML += '<div class="spec-item"><span class="spec-label">Desarrollador</span><span class="spec-value">' + devs + '</span></div>';
                    var displaySystem = (item.subcategory || '').toUpperCase();
                    if (displaySystem) specsHTML += '<div class="spec-item"><span class="spec-label">Sistema</span><span class="spec-value">' + displaySystem + '</span></div>';
                    if (item.age_rating && item.age_rating.trim() !== '') specsHTML += '<div class="spec-item"><span class="spec-label">Clasificación por Edad</span><span class="spec-value">' + item.age_rating + '</span></div>';
                    if (item.local_play && item.local_play > 0) specsHTML += '<div class="spec-item"><span class="spec-label">Cooperativo Local</span><span class="spec-value">Sí (' + item.local_play + ' jug.)</span></div>';
                    if (item.online_play === 1) specsHTML += '<div class="spec-item"><span class="spec-label">Cooperativo Online</span><span class="spec-value">Sí</span></div>';
                    if (item.splitscreen === 1) specsHTML += '<div class="spec-item"><span class="spec-label">Pantalla Dividida</span><span class="spec-value">Sí</span></div>';
                    if (item.release_date && item.release_date.trim() !== '') {
                        var formattedDate = item.release_date;
                        try {
                            var parts = item.release_date.split('-');
                            if (parts.length === 3) formattedDate = parts[2] + '/' + parts[1] + '/' + parts[0];
                        } catch(e){}
                        specsHTML += '<div class="spec-item"><span class="spec-label">Fecha de Lanzamiento</span><span class="spec-value">' + formattedDate + '</span></div>';
                    }
                } else {
                    if (item.subcategory) specsHTML += '<div class="spec-item"><span class="spec-label">Formato</span><span class="spec-value">' + item.subcategory.toUpperCase() + '</span></div>';
                    if (item.genres) specsHTML += '<div class="spec-item"><span class="spec-label">Géneros</span><span class="spec-value">' + item.genres + '</span></div>';
                    if (item.age_rating) specsHTML += '<div class="spec-item"><span class="spec-label">Clasificación</span><span class="spec-value">' + item.age_rating + '</span></div>';
                    if (item.release_date) specsHTML += '<div class="spec-item"><span class="spec-label">Estreno</span><span class="spec-value">' + item.release_date + '</span></div>';
                }
                specsEl.innerHTML += specsHTML;
            }

            // Variant selector
            var variantsContainer = document.getElementById('detail-variants-container');
            if (variantsContainer) {
                variantsContainer.innerHTML = '';
                if (item.variants && item.variants.length > 1) {
                    var labelSpan = document.createElement('span');
                    labelSpan.style.cssText = 'font-size: 0.85rem; color: rgba(255, 255, 255, 0.45); font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; margin-right: 12px; display: inline-block; vertical-align: middle;';
                    labelSpan.textContent = 'Variantes:';
                    variantsContainer.appendChild(labelSpan);

                    var variantSelect = document.createElement('select');
                    variantSelect.id = 'variant-selector';
                    variantSelect.className = 'variant-select';
                    variantSelect.style.cssText = 'vertical-align: middle;';
                    variantSelect.onchange = function() { Catalog.switchVariant(this.value); };

                    item.variants.forEach(function(v) {
                        var isSelected = (String(v.id) === String(item.item_id)) ? ' selected' : '';
                        var vLabel = v.season_display || v.title;
                        var opt = document.createElement('option');
                        opt.value = v.id;
                        if (isSelected) opt.selected = true;
                        opt.textContent = vLabel;
                        variantSelect.appendChild(opt);
                    });
                    variantsContainer.appendChild(variantSelect);
                }
            }

            // Actions — Plugin strip
            var actionsEl = document.getElementById('detail-actions');
            if (actionsEl) {
                actionsEl.innerHTML = '';
                var itemId = item.item_id || item.id;
                var hasEpisodes = item.episodes && item.episodes.length > 0;
                var subcat = (item.subcategory || '').toLowerCase();

                // 1. Player section (filtrado por applies_to: categoría o subcategoría, con '*')
                var players = [];
                try {
                    players = window.pluginSystem && window.pluginSystem.getPluginsByType
                        ? window.pluginSystem.getPluginsByType('player')
                        : [];
                } catch(e) {}
                var activePlayers = [];
                for (var pi = 0; pi < players.length; pi++) {
                    if (players[pi].enabled !== false && players[pi].playerType && Catalog.pluginAppliesToItem(players[pi], item)) {
                        activePlayers.push(players[pi]);
                    }
                }

                if (activePlayers.length > 0) {
                    var playerSection = document.createElement('div');
                    playerSection.className = 'hero-actions-section';

                    if (activePlayers.length === 1) {
                        var plugin = activePlayers[0];
                        var pBtn = document.createElement('button');
                        pBtn.className = 'btn-stacked btn-play';
                        var heroIcon = plugin.playIcon;
                        if (plugin.name && plugin.name.indexOf('tvcat_')===0) {
                            var hiRes = '/plugin-static/' + plugin.name + '/plugin.png';
                            heroIcon = '<img src="' + hiRes + '" style="width:100%;height:100%;object-fit:contain;" onerror="this.onerror=null;this.src=\'/plugin-static/' + plugin.name + '/plugin_icon.png\';">';
                        }
                        var label = plugin.playLabel || '';
                        pBtn.innerHTML = '<span class="btn-emoji">' + heroIcon + '</span>' + (label ? '<span style="font-size:0.7rem;margin-top:2px;">' + label + '</span>' : '');
                        var tip = plugin.tooltip || plugin.displayName || label || 'Reproducir';
                        pBtn.title = tip;
                        pBtn.setAttribute('aria-label', tip);
                        pBtn.onclick = (function(pl) {
                            return function() {
                                localStorage.setItem('tvcat_preferred_player', pl.playerType);
                                if (typeof pl.play === 'function') { pl.play(item); }
                                else { Catalog._playWithPlayer(item, itemId, hasEpisodes, subcat, pl); }
                            };
                        })(plugin);
                        playerSection.appendChild(pBtn);
                    } else {
                        var pBtn2 = document.createElement('button');
                        pBtn2.className = 'btn-stacked btn-play';
                        pBtn2.innerHTML = '<span class="btn-emoji"><img src="/static/player.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'\u25B6\'"></span>';
                        pBtn2.title = 'Reproducir';
                        pBtn2.setAttribute('aria-label', 'Reproducir');
                        pBtn2.onclick = function() {
                            Catalog._showPlayerSelector(item, itemId, hasEpisodes, subcat, activePlayers);
                        };
                        playerSection.appendChild(pBtn2);
                    }
                    actionsEl.appendChild(playerSection);
                }
                // Reintento para WebKit antigua: la hero puede haberse pintado antes de que HLS se registrara (carga async)
                (function(_actionsEl, _item, _itemId, _hasEpisodes, _subcat){
                    var tries = 0;
                    var t = setInterval(function(){
                        tries++;
                        try {
                            var pl2 = window.pluginSystem ? window.pluginSystem.getPluginsByType('player') : [];
                            var act2 = [];
                            for (var k=0;k<pl2.length;k++) if (pl2[k].enabled!==false && pl2[k].playerType && Catalog.pluginAppliesToItem(pl2[k], _item)) act2.push(pl2[k]);
                            if (act2.length > 0) {
                                clearInterval(t);
                                // Si no había botón, crearlo ahora
                                if (_actionsEl.querySelector('.hero-actions-section')===null || _actionsEl.querySelector('.btn-play')===null) {
                                    var sec=document.createElement('div'); sec.className='hero-actions-section';
                                    if (act2.length===1) {
                                        var pl=act2[0];
                                        var b=document.createElement('button'); b.className='btn-stacked btn-play';
                                        var lbl2 = pl.playLabel || '';
                                        b.innerHTML='<span class="btn-emoji">'+(pl.playIcon||'\u25B6')+'</span>'+(lbl2 ? lbl2 : '');
                                        var tip2 = pl.tooltip || pl.displayName || lbl2 || 'Reproducir';
                                        b.title = tip2; b.setAttribute('aria-label', tip2);
                                        b.onclick=(function(p){return function(){ localStorage.setItem('tvcat_preferred_player',p.playerType); if(typeof p.play==='function') p.play(_item); else Catalog._playWithPlayer(_item,_itemId,_hasEpisodes,_subcat,p); };})(pl);
                                        sec.appendChild(b);
                                    } else {
                                        var b2=document.createElement('button'); b2.className='btn-stacked btn-play';
                                        b2.innerHTML='<span class="btn-emoji"><img src="/static/player.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'\u25B6\'"></span>';
                                        b2.title='Reproducir'; b2.setAttribute('aria-label','Reproducir');
                                        b2.onclick=function(){ Catalog._showPlayerSelector(_item,_itemId,_hasEpisodes,_subcat,act2); };
                                        sec.appendChild(b2);
                                    }
                                    // insertar al principio
                                    if (_actionsEl.firstChild) _actionsEl.insertBefore(sec, _actionsEl.firstChild);
                                    else _actionsEl.appendChild(sec);
                                }
                            } else if (tries>8) {
                                clearInterval(t);
                            }
                        } catch(e) { clearInterval(t); }
                    }, 700);
                })(actionsEl, item, itemId, hasEpisodes, subcat);
                
                // 2. Episodes (hardcoded core feature) — normalized to hero standard
                if (hasEpisodes && subcat.match(/(anime|series|tv)/)) {
                    var epSection = document.createElement('div');
                    epSection.className = 'hero-actions-section';
                    var epBtn = document.createElement('button');
                    epBtn.id = 'btn-episodes';
                    epBtn.className = 'btn-stacked';
                    epBtn.innerHTML = '<span class="btn-emoji"><img src="/static/episode_list.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'\uD83D\uDCCB\'"></span>';
                    epBtn.title = 'Lista de Episodios';
                    epBtn.setAttribute('aria-label', 'Lista de Episodios');
                    epBtn.onclick = function() { Catalog.openEpisodesModal(itemId); };
                    epSection.appendChild(epBtn);
                    actionsEl.appendChild(epSection);
                }

                // 3. heropage-action plugins
                var heroButtons = [];
                try {
                    heroButtons = window.pluginSystem && window.pluginSystem.getHeroPageActions
                        ? window.pluginSystem.getHeroPageActions(item)
                        : [];
                } catch(e) {}

                if (heroButtons.length > 0) {
                    var genSection = document.createElement('div');
                    genSection.className = 'hero-actions-section';
                    for (var hi = 0; hi < heroButtons.length; hi++) {
                        var hb = heroButtons[hi];
                        var hBtn = document.createElement('button');
                        hBtn.className = 'btn-stacked';
                        if (hb.id) hBtn.id = hb.id;
                        var hIcon2 = hb.icon || '';
                        var hLabel2 = hb.label || '';
                        hBtn.innerHTML = '<span class="btn-emoji">' + hIcon2 + '</span>' + (hLabel2 ? '<span style="font-size:0.7rem;margin-top:2px;">' + hLabel2 + '</span>' : '');
                        var hTip2 = hb.tooltip || hb.label || '';
                        if (hTip2) { hBtn.title = hTip2.replace(/<br>/g,' '); hBtn.setAttribute('aria-label', hTip2.replace(/<br>/g,' ')); }
                        if (hb.action) {
                            hBtn.onclick = hb.action;
                        }
                        genSection.appendChild(hBtn);
                    }
                    actionsEl.appendChild(genSection);
                }
            }

            // Favorite button in metadata (tvcat1 style)
            var categoryEl = document.getElementById('meta-category');
            if (categoryEl) {
                var oldFavs = categoryEl.parentNode.querySelectorAll('.meta-fav-btn');
                for (var fi = 0; fi < oldFavs.length; fi++) { oldFavs[fi].remove(); }

                var metaFavBtn = document.createElement('button');
                var repId = item.representative_id || item.item_id || '';
                var favFill = item.favorite ? '#e11d48' : 'rgba(255, 255, 255, 0.4)';
                metaFavBtn.className = item.favorite ? 'meta-fav-btn favorited' : 'meta-fav-btn';
                metaFavBtn.setAttribute('data-rep-id', repId);
                metaFavBtn.title = item.favorite ? 'Quitar de Favoritos' : 'A\u00f1adir a Favoritos';
                metaFavBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="' + favFill + '"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>';
                metaFavBtn.onclick = function() {
                    Catalog.toggleMetadataFavorite(itemId, currentCategory);
                };
                categoryEl.parentNode.insertBefore(metaFavBtn, categoryEl.nextSibling);
                // Admin badge: refrescar cover desde Telegram (visible solo admin, case-insensitive)
                try {
                    var cu = window.Catalog.currentUser || {};
                    var uname = (cu.username || cu.display_name || '').toString().toLowerCase();
                    var isAdmin = (uname === 'admin') || !!cu.is_admin || cu.role === 'admin';
                    // fallback: si currentUser aún no cargado, intentar mostrar igual y validar en el endpoint
                    if (!cu.username && !cu.is_admin) isAdmin = true;
                    var oldRefresh = categoryEl.parentNode.querySelectorAll('.meta-cover-refresh');
                    for (var ri=0; ri<oldRefresh.length; ri++) oldRefresh[ri].remove();
                    var oldRefresh2 = document.querySelectorAll('.hero-cover-refresh');
                    for (var rj=0; rj<oldRefresh2.length; rj++) oldRefresh2[rj].remove();
                    if (isAdmin) {
                        var refreshBtn = document.createElement('button');
                        refreshBtn.className = 'meta-fav-btn meta-cover-refresh';
                        refreshBtn.title = 'Recargar cover desde telegram';
                        refreshBtn.setAttribute('aria-label', 'Recargar cover desde telegram');
                        refreshBtn.innerHTML = '🔄';
                        refreshBtn.onclick = (function(id){ return function(){ if (window.refreshCover) window.refreshCover(id); }; })(itemId);
                        categoryEl.parentNode.insertBefore(refreshBtn, metaFavBtn.nextSibling);
                    }
                } catch(e) { console.log('refresh badge err', e); }

                var existingMkvIcons = document.querySelectorAll('.meta-mkv-icon');
                for (var mkvI = 0; mkvI < existingMkvIcons.length; mkvI++) existingMkvIcons[mkvI].remove();
                if (item.has_mkv) {
                    var metaMkvIcon = document.createElement('span');
                    metaMkvIcon.className = 'meta-mkv-icon';
                    metaMkvIcon.title = 'Fichero MKV';
                    metaMkvIcon.innerHTML = '<img src="/static/mkv.png" onerror="this.parentNode.textContent=\'\uD83D\uDCE6\'">';
                    metaFavBtn.parentNode.insertBefore(metaMkvIcon, metaFavBtn.nextSibling);
                }
            }

            // Show modal
            var modal = document.getElementById('detail-modal');
            if (modal) {
                void modal.offsetWidth;
                modal.classList.remove('hidden');
            }
        };

        // If variant switch, just update metadata and backdrop
        if (isVariantSwitch) {
            updateMetadataDOM();
            // Reload slideshow
            var slides = buildSlides(item);
            _slideshowImages = slides;
            _currentSlideIndex = 0;
            var backdrop1 = document.getElementById('detail-backdrop');
            var backdrop2 = document.getElementById('detail-backdrop-next');
            if (slides.length > 0) {
                if (backdrop1) {
                    backdrop1.style.transition = 'none';
                    backdrop1.style.opacity = '1';
                    backdrop1.style.backgroundImage = "url('" + slides[0].url + "')";
                    backdrop1.style.backgroundSize = slides[0].mode;
                    backdrop1.style.backgroundPosition = slides[0].align;
                    backdrop1.classList.remove('zoom-active');
                    void backdrop1.offsetWidth;
                    backdrop1.style.transition = '';
                }
                if (backdrop2) {
                    backdrop2.style.opacity = '0';
                    backdrop2.style.backgroundImage = '';
                    backdrop2.classList.remove('zoom-active');
                }
                _activeBackdropEl = backdrop1;
            }
            try { startHeroThumbs(item.item_id || item.id, item.episodes && item.episodes.length > 0); } catch (e) {}
            return;
        }

        // Initial open
        if (_slideshowTimeout) {
            clearTimeout(_slideshowTimeout);
            _slideshowTimeout = null;
        }

        var slides = buildSlides(item);
        var initialSlide = slides.length > 0 ? slides[0] : { url: '/api/art/' + (item.item_id || item.id), mode: 'cover', align: 'center' };

        // Preload
        var totalToPreload = 0;
        var loadedCount = 0;
        var donePreload = false;

        var onPreloadComplete = function() {
            // Set backdrops
            var backdrop1 = document.getElementById('detail-backdrop');
            var backdrop2 = document.getElementById('detail-backdrop-next');
            if (backdrop1) {
                backdrop1.style.transition = 'none';
                backdrop1.style.opacity = '1';
                backdrop1.style.backgroundImage = "url('" + initialSlide.url + "')";
                backdrop1.style.backgroundSize = initialSlide.mode;
                backdrop1.style.backgroundPosition = initialSlide.align;
                backdrop1.style.backgroundRepeat = 'no-repeat';
                backdrop1.classList.remove('zoom-active');
                void backdrop1.offsetWidth;
                backdrop1.style.transition = '';
            }
            if (backdrop2) {
                backdrop2.style.opacity = '0';
                backdrop2.style.backgroundImage = '';
                backdrop2.classList.remove('zoom-active');
            }
            _activeBackdropEl = backdrop1;

            setTimeout(function() {
                if (backdrop1 && initialSlide.mode === 'cover') backdrop1.classList.add('zoom-active');
            }, 50);

            _slideshowImages = slides;
            // El slide 0 ya se muestra en estático: la primera transición debe
            // avanzar al 1 (antes iba al 0 y fundía la misma imagen consigo misma)
            _currentSlideIndex = 0;
            if (slides.length > 1) scheduleNextSlide(4000);
            try { startHeroThumbs(item.item_id || item.id, item.episodes && item.episodes.length > 0); } catch (e) {}

            // Logo / title animation
            var logoContainer = document.getElementById('detail-logo-container');
            var titleEl = document.getElementById('detail-title');
            if (titleEl) { titleEl.classList.remove('animate'); titleEl.style.display = 'none'; }
            if (logoContainer) { logoContainer.classList.remove('animate'); logoContainer.style.display = 'none'; logoContainer.innerHTML = ''; }

            var showTitleFallback = function(title) {
                if (titleEl) { titleEl.style.display = 'block'; titleEl.textContent = title; setTimeout(function() { titleEl.classList.add('animate'); }, 150); }
                if (logoContainer) logoContainer.style.display = 'none';
            };

            if (item.logo) {
                var img = document.createElement('img');
                img.alt = 'logo';
                var animated = false;
                img.onload = function() {
                    if (animated) return; animated = true;
                    if (logoContainer) { logoContainer.innerHTML = ''; logoContainer.appendChild(img); logoContainer.style.display = 'block'; setTimeout(function() { logoContainer.classList.add('animate'); }, 40); }
                };
                img.onerror = function() { showTitleFallback(item.title); };
                img.src = item.logo;
                if (img.complete) { if (!animated) { animated = true; if (logoContainer) { logoContainer.innerHTML = ''; logoContainer.appendChild(img); logoContainer.style.display = 'block'; setTimeout(function() { logoContainer.classList.add('animate'); }, 40); } } }
                if (titleEl) titleEl.style.display = 'none';
            } else {
                showTitleFallback(item.title);
            }

            updateMetadataDOM();
        };

        var triggerPreloadComplete = function() {
            if (donePreload) return;
            donePreload = true;
            onPreloadComplete();
        };

        var preloadTimeout = setTimeout(triggerPreloadComplete, 250);

        if (initialSlide && initialSlide.url) {
            totalToPreload++;
            var img1 = new Image();
            img1.onload = function() { loadedCount++; if (loadedCount >= totalToPreload) { clearTimeout(preloadTimeout); triggerPreloadComplete(); } };
            img1.onerror = function() { loadedCount++; if (loadedCount >= totalToPreload) { clearTimeout(preloadTimeout); triggerPreloadComplete(); } };
            img1.src = initialSlide.url;
        }
        if (item.logo) {
            totalToPreload++;
            var img2 = new Image();
            img2.onload = function() { loadedCount++; if (loadedCount >= totalToPreload) { clearTimeout(preloadTimeout); triggerPreloadComplete(); } };
            img2.onerror = function() { loadedCount++; if (loadedCount >= totalToPreload) { clearTimeout(preloadTimeout); triggerPreloadComplete(); } };
            img2.src = item.logo;
        }
        if (totalToPreload === 0) triggerPreloadComplete();
    }

    // Cola base del hero (fase 2): [cover-zoom, cover-full]. Los thumbs de
    // episodios se intercalan después vía heroCycle(): CZ, T1, CF, T2, CZ, T3...
    // (sin repetir thumb hasta agotar, máx 14). Sin fuente de art/screenshots
    // en el backend, el cover es el único slide garantizado.
    var _heroCoverZoom = null;
    var _heroCoverFull = null;
    var _heroItemId = null;
    var _heroThumbs = [];
    var _heroThumbTimer = null;
    var _heroThumbPending = {};

    function buildSlides(item) {
        var coverUrl = item.art ||
            ((item.screenshots && item.screenshots.length > 0) ? item.screenshots[item.screenshots.length - 1] : null) ||
            item.image ||
            ('/api/cover/' + (item.item_id || item.id));
        var fullUrl = item.image || coverUrl;
        // Dos slots aunque sea la misma URL: el modo (cover recortado vs
        // contain encajado) los hace visualmente distintos y deben alternar
        _heroCoverZoom = { url: coverUrl, mode: 'cover', align: 'center' };
        // Cover encajado (contain, mismo aspect ratio): alineado a la derecha,
        // pegado al borde del hero
        _heroCoverFull = { url: fullUrl, mode: 'contain', align: 'right center' };
        return [_heroCoverZoom, _heroCoverFull];
    }

    function heroCycle() {
        var n = _heroThumbs.length;
        var full = _heroCoverFull || _heroCoverZoom;
        var out = [];
        if (!n) return (full === _heroCoverZoom) ? [_heroCoverZoom] : [_heroCoverZoom, full];
        for (var k = 0; k < n; k++) {
            out.push((k % 2 === 0) ? _heroCoverZoom : full);
            out.push({ url: _heroThumbs[k].url, mode: 'cover', align: 'center' });
        }
        // Con n impar el último cover usado es CZ: añadir el CF para que el
        // cover-full encajado también aparezca en el ciclo (n=1: CZ,T1,CF)
        if (n % 2 !== 0) out.push(full);
        return out;
    }

    function heroRebuildCycle() {
        if (!_heroCoverZoom) return;
        _slideshowImages = heroCycle();
        if (_currentSlideIndex >= _slideshowImages.length) _currentSlideIndex = 0;
        // Si el ciclo no está en marcha (p. ej. la cola inicial era 1 slide
        // y los thumbs llegaron después), arrancarlo para que se vean
        if (_slideshowImages.length > 1 && !_slideshowTimeout) scheduleNextSlide(1500);
    }

    function stopHeroThumbs() {
        if (_heroThumbTimer) { clearInterval(_heroThumbTimer); _heroThumbTimer = null; }
        _heroItemId = null;
        _heroThumbs = [];
        _heroThumbPending = {};
    }

    function startHeroThumbs(itemId, hasEpisodes) {
        if (!itemId || !hasEpisodes) { stopHeroThumbs(); return; }
        // Si es el mismo ítem y ya hay progreso (doble showDetails por
        // variante sugerida), continuar sin borrar la cola
        if (_heroItemId === itemId && _heroThumbs.length > 0) {
            if (!_heroThumbTimer) heroPollThumbs(itemId);
            return;
        }
        stopHeroThumbs();
        _heroItemId = itemId;
        var fetchEps = currentEpisodes[itemId] && currentEpisodes[itemId].seasons
            ? Promise.resolve(currentEpisodes[itemId].seasons)
            : new Promise(function(resolve) {
                window.API.ajax({
                    url: '/api/media/' + itemId + '/episodes',
                    success: function(seasons) {
                        currentEpisodes[itemId] = { activeSeason: '', seasons: seasons || {} };
                        resolve(seasons || {});
                    },
                    error: function() { resolve({}); }
                });
            });
        fetchEps.then(function() {
            if (_heroItemId !== itemId) return;
            window.API.ajax({
                method: 'POST',
                url: '/api/hero/thumbs/warm',
                data: { item_id: itemId },
                success: function() { if (!_heroThumbTimer) heroPollThumbs(itemId); },
                error: function() {}
            });
            heroPollThumbs(itemId);
        });
    }

    function heroPollThumbs(itemId) {
        if (_heroThumbTimer) clearInterval(_heroThumbTimer);
        var poll = function() {
            if (_heroItemId !== itemId) { clearInterval(_heroThumbTimer); _heroThumbTimer = null; return; }
            window.API.ajax({
                url: '/api/hero/thumbs/status?item_id=' + encodeURIComponent(itemId),
                success: function(res) {
                    if (_heroItemId !== itemId) return;
                    var items = (res && res.items) || [];
                    var added = false;
                    var allReady = items.length > 0;
                    for (var i = 0; i < items.length; i++) {
                        if (!items[i].ready) { allReady = false; continue; }
                        var seen = false;
                        for (var j = 0; j < _heroThumbs.length; j++) {
                            if (_heroThumbs[j].mid === items[i].telegram_msg_id) { seen = true; break; }
                        }
                        if (!seen && !_heroThumbPending[items[i].telegram_msg_id]) {
                            (function(mid) {
                                _heroThumbPending[mid] = true;
                                var img = new Image();
                                img.onload = function() {
                                    delete _heroThumbPending[mid];
                                    if (_heroItemId !== itemId) return;
                                    var dup = false;
                                    for (var k = 0; k < _heroThumbs.length; k++) {
                                        if (_heroThumbs[k].mid === mid) { dup = true; break; }
                                    }
                                    if (!dup) {
                                        _heroThumbs.push({ mid: mid, url: '/api/media/episode/thumbnail/' + mid });
                                        try { console.log('[hero] thumb +' + mid + ' (' + _heroThumbs.length + ')'); } catch (e) {}
                                        heroRebuildCycle();
                                    }
                                };
                                img.onerror = function() { delete _heroThumbPending[mid]; };
                                img.src = '/api/media/episode/thumbnail/' + mid + '?t=' + Date.now();
                            })(items[i].telegram_msg_id);
                            added = true;
                        }
                    }
                    if (allReady && _heroThumbTimer) {
                        clearInterval(_heroThumbTimer); _heroThumbTimer = null;
                        try { console.log('[hero] thumbs completos (' + _heroThumbs.length + ')'); } catch (e) {}
                    }
                },
                error: function() {}
            });
        };
        poll();
        _heroThumbTimer = setInterval(poll, 2000);
    }

    // ====== VARIANT SWITCH ======
    Catalog.switchVariant = function(id) {
        window.API.ajax({
            url: '/api/movie/' + id,
            success: function(data) {
                showDetails(data, true);
            }
        });
    };

    // ====== CLOSE DETAILS ======
    window.closeDetails = function() {
        if (_slideshowTimeout) { clearTimeout(_slideshowTimeout); _slideshowTimeout = null; }
        try { stopHeroThumbs(); } catch (e) {}
        var modal = document.getElementById('detail-modal');
        if (modal) modal.classList.add('hidden');
        setTimeout(function() {
            var focused = document.querySelector('.grid-item.focused');
            if (!focused) {
                var first = document.querySelector('.grid-item');
                if (first && window.navEngine) window.navEngine.focus(first);
            }
        }, 100);
    };

    // ===== Filtro de plugins 'player' por contenido (categoría/subcategoría, con '*') =====
    // Un plugin aplica si su categoría/subcategoría saneada coincide con las listas editables (por plugin).
    // Saneado: minúsculas, trim, solo [a-z0-9] (sin espacios/_/-) para que "ps 3" == "ps3" == "playstation 3" -> "playstation3" según lista.
    function sanitizeForCompare(s){ var v=String(s||'').trim(); if(v==='*') return '*'; return v.toLowerCase().replace(/[^a-z0-9]/g,'').trim(); }
    Catalog.pluginAppliesToItem = function(plugin, item) {
        var hasEditable = plugin && (plugin._cats || plugin._subs);
        var cat = sanitizeForCompare(item && item.category);
        var sub = sanitizeForCompare(item && item.subcategory);
        if (hasEditable) {
            var cats = plugin._cats || [];
            var subs = plugin._subs || [];
            var catOk = false, subOk = false;
            if (!cats.length) catOk = true;
            else {
                for (var i=0;i<cats.length;i++) { var sc=sanitizeForCompare(cats[i]); if(sc==='*' || sc===cat) { catOk=true; break; } }
            }
            if (!subs.length) subOk = true;
            else {
                for (var j=0;j<subs.length;j++) { var ss=sanitizeForCompare(subs[j]); if(ss==='*' || ss===sub) { subOk=true; break; } }
            }
            return catOk && subOk;
        }
        var applies = plugin.applies_to;
        if (!applies || applies.length === 0) return true;
        for (var i = 0; i < applies.length; i++) {
            var a = sanitizeForCompare(applies[i]);
            if (a === '*' || a === cat || a === sub) return true;
        }
        return false;
    };

    Catalog.loadPluginCats = function() {
        window.API.ajax({
            url: '/api/plugins/cats',
            success: function(res) {
                if (!res) return;
                for (var name in res) {
                    if (!res.hasOwnProperty(name)) continue;
                    var data = res[name];
                    var cats = data.categories || [];
                    var subs = data.subcategories || [];
                    try {
                        var all = window.pluginSystem ? window.pluginSystem.getPluginsByType('player') : [];
                        for (var i=0;i<all.length;i++) if (all[i].name===name) {
                            all[i]._cats = cats.slice();
                            all[i]._subs = subs.slice();
                            var comb = [];
                            for (var c=0;c<cats.length;c++) if (comb.indexOf(cats[c])===-1) comb.push(cats[c]);
                            for (var s=0;s<subs.length;s++) if (comb.indexOf(subs[s])===-1) comb.push(subs[s]);
                            all[i].applies_to = comb;
                        }
                        if (window.pluginSystem && window.pluginSystem._plugins && window.pluginSystem._plugins[name]) {
                            var p = window.pluginSystem._plugins[name];
                            p._cats = cats.slice();
                            p._subs = subs.slice();
                            var comb2 = [];
                            for (var c2=0;c2<cats.length;c2++) if (comb2.indexOf(cats[c2])===-1) comb2.push(cats[c2]);
                            for (var s2=0;s2<subs.length;s2++) if (comb2.indexOf(subs[s2])===-1) comb2.push(subs[s2]);
                            p.applies_to = comb2;
                        }
                    } catch(e){}
                }
            }
        });
    };
    setTimeout(function(){ try{ Catalog.loadPluginCats(); }catch(e){} }, 800);

    // Un plugin aplica a "episodios" (series) si su applies_to incluye categorías de vídeo
    // (o '*'). Mantiene fuera a los plugins de consola en el selector de episodios.
    Catalog.pluginAppliesToEpisodes = function(plugin) {
        var applies = plugin.applies_to;
        if (!applies || applies.length === 0) return true;
        for (var i = 0; i < applies.length; i++) {
            var a = String(applies[i]).toLowerCase();
            if (a === '*' || a === 'series' || a === 'anime' || a === 'tv' || a === 'video' || a === 'media') return true;
        }
        return false;
    };

    // ====== EPISODES MODAL ======
    Catalog.openEpisodesModal = function(id) {
        var self = Catalog;
        currentMediaId = id;

        var modal = document.getElementById('episodes-modal');
        var seasonSelector = document.getElementById('season-selector');
        var grid = document.getElementById('episodes-list');
        var btn = document.getElementById('btn-episodes');

        if (!modal || !seasonSelector || !grid) return;

        lastFocusedDetailsAction = document.querySelector('#detail-modal .hero-actions button.focused') || document.activeElement;

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-emoji" style="width:100%;height:100%;"><span style="display:inline-block;animation:spin 1.2s linear infinite;font-size:1.8rem;line-height:1;">⏳</span></span>';
            btn.title = 'Solicitando...';
        }

        var _gotSeasons = function(seasons) {
            if (currentMediaId !== id) return;

            var activeSeasonName = '';
            if (currentVariantId && seasons) {
                for (var sName in seasons) {
                    if (seasons.hasOwnProperty(sName)) {
                        var epsList = seasons[sName];
                        if (epsList && epsList.length > 0) {
                            var firstEp = epsList[0];
                            if (String(firstEp.item_id) === String(currentVariantId) || String(firstEp.real_item_id) === String(currentVariantId)) {
                                activeSeasonName = sName;
                                break;
                            }
                        }
                    }
                }
            }

            currentEpisodes[id] = {
                activeSeason: activeSeasonName,
                seasons: seasons || {}
            };

            var mediaData = currentEpisodes[id];

            seasonSelector.innerHTML = '';
            var hasSeasons = false;
            for (var seasonName in mediaData.seasons) {
                if (mediaData.seasons.hasOwnProperty(seasonName)) {
                    hasSeasons = true;
                    var option = document.createElement('option');
                    option.value = seasonName;
                    option.text = seasonName;
                    if (!mediaData.activeSeason) mediaData.activeSeason = seasonName;
                    if (seasonName === mediaData.activeSeason) option.selected = true;
                    seasonSelector.appendChild(option);
                }
            }

            if (!hasSeasons) {
                grid.innerHTML = '<div style="text-align: center; color: var(--text-secondary); padding: 50px 20px;">' +
                    '<span style="font-size: 3rem;">📭</span>' +
                    '<div style="font-size: 1.1rem; font-weight: 600; color: #fff; margin-top: 15px;">No se encontraron capítulos</div>' +
                    '<span style="font-size: 0.85rem; opacity: 0.7; max-width: 320px; line-height: 1.4; display:block;margin:10px auto;">Este título no contiene enlaces de vídeo válidos o no ha sido indexado correctamente en Telegram.</span></div>';
                seasonSelector.innerHTML = '<option value="">Sin episodios</option>';
            } else {
                renderEpisodesGrid();
            }

            modal.classList.remove('hidden');
            setTimeout(function() {
                var target = modal.querySelector('.episode-card.next-to-play') || modal.querySelector('.episode-card');
                if (target && window.navEngine) window.navEngine.focus(target);
            }, 120);
        };

        var _resetEpBtn = function() {
            if (!btn) return;
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-emoji"><img src="/static/episode_list.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'📋\'"></span>';
            btn.title = 'Lista de Episodios';
            btn.setAttribute('aria-label', 'Lista de Episodios');
        };

        // Si el hero ya precargó los episodios, reutilizar sin nueva llamada
        if (currentEpisodes[id] && currentEpisodes[id].seasons) {
            _resetEpBtn();
            _gotSeasons(currentEpisodes[id].seasons);
            return;
        }

        window.API.ajax({
            url: '/api/media/' + id + '/episodes',
            success: function(seasons) {
                if (btn) { btn.disabled = false; btn.innerHTML = '<span class="btn-emoji"><img src="/static/episode_list.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'📋\'"></span>'; btn.title='Lista de Episodios'; btn.setAttribute('aria-label','Lista de Episodios'); }
                _gotSeasons(seasons);
            },
            error: function() {
                if (btn) { btn.disabled = false; btn.innerHTML = '<span class="btn-emoji"><img src="/static/episode_list.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'📋\'"></span>'; btn.title='Lista de Episodios'; btn.setAttribute('aria-label','Lista de Episodios'); }
                grid.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-secondary);">Error al cargar episodios</div>';
            }
        });
    };

    Catalog.closeEpisodesModal = function() {
        var modal = document.getElementById('episodes-modal');
        if (modal) modal.classList.add('hidden');
        // Restaurar el botón por si quedó en estado spinner
        try {
            var ebtn = document.getElementById('btn-episodes');
            if (ebtn) {
                ebtn.disabled = false;
                ebtn.innerHTML = '<span class="btn-emoji"><img src="/static/episode_list.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'📋\'"></span>';
                ebtn.title = 'Lista de Episodios';
                ebtn.setAttribute('aria-label', 'Lista de Episodios');
            }
        } catch (e) {}
        if (lastFocusedDetailsAction && document.body.contains(lastFocusedDetailsAction) && window.navEngine) {
            window.navEngine.focus(lastFocusedDetailsAction);
        } else {
            var fallbackBtn = document.querySelector('#detail-modal .hero-actions button');
            if (fallbackBtn && window.navEngine) window.navEngine.focus(fallbackBtn);
        }
    };

    Catalog.onSeasonChange = function() {
        var id = currentMediaId;
        var seasonSelector = document.getElementById('season-selector');
        if (!id || !currentEpisodes[id] || !seasonSelector) return;
        currentEpisodes[id].activeSeason = seasonSelector.value;
        renderEpisodesGrid();
        var modal = document.getElementById('episodes-modal');
        if (modal) {
            setTimeout(function() {
                var target = modal.querySelector('.episode-card.next-to-play') || modal.querySelector('.episode-card');
                if (target && window.navEngine) window.navEngine.focus(target);
            }, 120);
        }
    };

    function effectiveState(h, th) {
        if (!h) return 1;
        var ws = h.watched_state;
        if (ws && ws !== 0) return ws;
        var dur = h.duration || 0;
        if (dur <= 0) return 1;
        var pct = (h.progress || 0) / dur;
        var min = (th && th.min !== undefined) ? th.min : 0.05;
        var max = (th && th.max !== undefined) ? th.max : 0.85;
        if (pct > max) return 3;
        if (pct >= min) return 2;
        return 1;
    }

    function renderEpisodesGrid() {
        var id = currentMediaId;
        if (!id || !currentEpisodes[id]) return;

        var mediaData = currentEpisodes[id];
        var episodes = mediaData.seasons[mediaData.activeSeason] || [];
        var grid = document.getElementById('episodes-list');
        if (!grid) return;

        var scrollPos = grid.scrollTop;
        grid.innerHTML = '';

        window.API.ajax({
            url: '/api/watch/history',
            success: function(histRes) {
                var watchedMap = {};
                if (histRes && histRes.history) {
                    for (var j = 0; j < histRes.history.length; j++) {
                        var entry = histRes.history[j];
                        if (entry.episode_key) {
                            watchedMap['k:' + entry.episode_key] = entry;
                        } else {
                            watchedMap[entry.item_id + ':' + entry.episode_id] = entry;
                        }
                    }
                }
                function histKey(ep) {
                    return (ep.episode_key) ? ('k:' + ep.episode_key) : ((ep.item_id || id) + ':' + (ep.id || 0));
                }

                var nextKey = null;
                for (var k = 0; k < episodes.length; k++) {
                    var epTest = episodes[k];
                    var wk = histKey(epTest);
                    var hTest = watchedMap[wk];
                    var stTest = effectiveState(hTest, null);
                    if (stTest !== 3) {
                        nextKey = wk;
                        break;
                    }
                }

                window.API.getWatchThresholds(function(th) {
                    var minThresh = th.min / 100;
                    var maxThresh = th.max / 100;
                    for (var i = 0; i < episodes.length; i++) {
                        (function(idx) {
                            var ep = episodes[idx];
                            var wk = histKey(ep);
                            var h = watchedMap[wk];

                            var state = effectiveState(h, { min: minThresh, max: maxThresh });
                            var isWatched = state === 3;
                            var isStarted = state === 2;
                            var isNext = wk === nextKey;

                            var progressPercent = 0;
                            var eyeClass = 'unwatched';

                            if (isWatched) {
                                eyeClass = 'completed';
                            } else if (isStarted) {
                                eyeClass = 'started';
                                if (h && h.duration > 0) {
                                    progressPercent = Math.min(100, Math.floor((h.progress / h.duration) * 100));
                                }
                            }

                            var card = document.createElement('div');
                            card.className = 'episode-card' + (isWatched ? ' watched' : '') + (isNext ? ' next-to-play' : '');
                            card.setAttribute('tabindex', '0');
                            card.onclick = function() { Catalog.playEpisode(idx); };

                            var displayTitle = (ep.episode_number || (idx + 1)) + '. ' + (ep.title || 'Episodio ' + (ep.episode_number || (idx + 1)));

                            var thumbUrl = ep.telegram_msg_id ? ('/api/media/episode/thumbnail/' + ep.telegram_msg_id) : null;
                            var coverUrl = '/api/cover/' + id;
                            var initialSrc = (thumbUrl && ep.has_thumb) ? (thumbUrl + '?t=' + Date.now()) : coverUrl;

                            card.innerHTML =
                                '<div class="episode-thumb-container">' +
                                    '<img src="' + initialSrc + '" class="episode-thumb" alt="' + (ep.title || '') + '" data-thumb-src="' + (thumbUrl || '') + '" ' +
                                    'onerror="this.onerror=null;this.src=\'' + coverUrl + '\';this.removeAttribute(\'data-thumb-src\');" />' +
                                    '<div class="episode-progress-bar' + (progressPercent > 0 ? '' : ' hidden') + '">' +
                                        '<div class="episode-progress-fill" style="width: ' + progressPercent + '%;"></div>' +
                                    '</div>' +
                                '</div>' +
                                '<div class="episode-info">' +
                                    '<h3 class="episode-title">' + escapeHtml(displayTitle) + '</h3>' +
                                    (ep.caption ? '<p class="episode-overview" title="' + escapeHtml(ep.caption) + '">' + escapeHtml(ep.caption) + '</p>' : '') +
                                '</div>' +
                                '<div class="watched-toggle ' + eyeClass + '" onclick="event.stopPropagation();Catalog.toggleWatchedState(' + idx + ')">' +
                                    '<svg viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3" fill="' + (isWatched ? 'currentColor' : 'none') + '"/></svg>' +
                                '</div>';

                            grid.appendChild(card);
                        })(i);
                    }
                    grid.scrollTop = scrollPos;
                    loadThumbnailsBackground();
                });
            }
        });
    }

    function loadThumbnailsBackground() {
        var processNext = function() {
            var imgs = document.querySelectorAll('.episode-thumb[data-thumb-src]:not([data-failed-temp])');
            if (imgs.length === 0) {
                var anyPending = document.querySelectorAll('.episode-thumb[data-thumb-src]').length > 0;
                if (anyPending) setTimeout(processNext, 3000);
                return;
            }
            var img = imgs[0];
            var thumbSrc = img.getAttribute('data-thumb-src');
            if (!thumbSrc) { img.removeAttribute('data-thumb-src'); setTimeout(processNext, 100); return; }

            var retries = parseInt(img.getAttribute('data-retry') || '0');
            if (retries >= 6) { img.removeAttribute('data-thumb-src'); setTimeout(processNext, 100); return; }
            img.setAttribute('data-retry', retries + 1);

            var testImg = new Image();
            testImg.onload = function() {
                if (testImg.naturalWidth > 0 && testImg.naturalHeight > 0) {
                    img.src = thumbSrc + '?t=' + Date.now();
                    img.removeAttribute('data-thumb-src');
                    setTimeout(processNext, 100);
                } else {
                    img.setAttribute('data-failed-temp', 'true');
                    setTimeout(function() { img.removeAttribute('data-failed-temp'); }, 5000);
                    setTimeout(processNext, 100);
                }
            };
            testImg.onerror = function() {
                img.setAttribute('data-failed-temp', 'true');
                setTimeout(function() { img.removeAttribute('data-failed-temp'); }, 5000);
                setTimeout(processNext, 100);
            };
            testImg.src = thumbSrc + '?t=' + Date.now();
        };
        setTimeout(processNext, 1000);
    }

    Catalog.playEpisode = function(idx) {
        var id = currentMediaId;
        if (!id || !currentEpisodes[id]) return;

        var mediaData = currentEpisodes[id];
        var episodes = mediaData.seasons[mediaData.activeSeason] || [];
        var ep = episodes[idx];
        if (!ep) return;

        var episodesModal = document.getElementById('episodes-modal');
        episodesModalWasOpen = episodesModal && !episodesModal.classList.contains('hidden');
        Catalog.closeEpisodesModal();

        var itemArg = { item_id: id, title: ep.title || '' };

        // Obtener players activos
        var players = window.pluginSystem && window.pluginSystem.getPluginsByType
            ? window.pluginSystem.getPluginsByType('player')
            : [];
        var activePlayers = [];
        for (var pi = 0; pi < players.length; pi++) {
            if (players[pi].enabled !== false && players[pi].playerType && Catalog.pluginAppliesToEpisodes(players[pi])) {
                activePlayers.push(players[pi]);
            }
        }

        if (activePlayers.length <= 1) {
            if (activePlayers.length === 1) {
                var currentPref = localStorage.getItem('tvcat_preferred_player');
                if (!currentPref || currentPref === 'auto') {
                    localStorage.setItem('tvcat_preferred_player', window.getPlayerType ? window.getPlayerType() : activePlayers[0].playerType);
                }
            }
            Catalog.playMedia(itemArg, ep);
            return;
        }

        // Múltiples players: selector overlay
        var existing = document.getElementById('player-selector-overlay');
        if (existing) existing.remove();
        var overlay = document.createElement('div');
        overlay.id = 'player-selector-overlay';
        overlay.style.cssText = 'position:fixed;top:0;right:0;bottom:0;left:0;z-index:1000;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;';
        overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };
        var panel = document.createElement('div');
        panel.style.cssText = 'background:#1a1a1e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;min-width:260px;max-width:320px;box-shadow:0 8px 32px rgba(0,0,0,0.5);';
        var title = document.createElement('div');
        title.style.cssText = 'font-size:0.9rem;font-weight:600;margin-bottom:12px;color:var(--text-primary);';
        title.textContent = 'Selecciona un reproductor:';
        panel.appendChild(title);
        for (var pi = 0; pi < activePlayers.length; pi++) {
            (function(plugin) {
                var btn = document.createElement('button');
                btn.style.cssText = 'display:flex;align-items:center;gap:10px;width:100%;padding:10px 14px;margin:4px 0;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);border-radius:8px;color:#fff;font-size:0.9rem;cursor:pointer;transition:0.2s;text-align:left;';
                btn.onmouseenter = function() { this.style.background = 'rgba(225,29,72,0.15)'; };
                btn.onmouseleave = function() { this.style.background = 'rgba(255,255,255,0.05)'; };
                btn.innerHTML = '<span style="font-size:1.2rem;">\u25B6</span> <span>' + (plugin.displayName || plugin.name) + '</span>';
                btn.onclick = function() {
                    overlay.remove();
                    localStorage.setItem('tvcat_preferred_player', plugin.playerType);
                    Catalog.playMedia(itemArg, ep);
                };
                panel.appendChild(btn);
            })(activePlayers[pi]);
        }
        var cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Cancelar';
        cancelBtn.style.cssText = 'width:100%;padding:8px;margin-top:8px;background:transparent;border:none;color:rgba(255,255,255,0.4);font-size:0.8rem;cursor:pointer;';
        cancelBtn.onclick = function() { overlay.remove(); };
        panel.appendChild(cancelBtn);
        overlay.appendChild(panel);
        document.body.appendChild(overlay);
    };

    Catalog.playNextEpisode = function(id) {
        currentMediaId = id;
        window.API.ajax({
            url: '/api/media/' + id + '/episodes',
            success: function(seasons) {
                if (!seasons) return;
                var firstSeason = Object.keys(seasons)[0];
                if (!firstSeason) return;
                var episodes = seasons[firstSeason] || [];
                if (episodes.length === 0) return;

                currentEpisodes[id] = { activeSeason: firstSeason, seasons: seasons };

                window.API.ajax({
                    url: '/api/watch/history',
                    success: function(histRes) {
                        var watchedMap = {};
                        if (histRes && histRes.history) {
                            for (var j = 0; j < histRes.history.length; j++) {
                                var entry = histRes.history[j];
                                if (entry.episode_key) watchedMap['k:' + entry.episode_key] = entry;
                                else watchedMap[entry.item_id + ':' + entry.episode_id] = entry;
                            }
                        }

                        var targetEp = episodes[0];
                        window.API.getWatchThresholds(function(th) {
                            var minThresh = th.min / 100;
                            var maxThresh = th.max / 100;
                            for (var k = 0; k < episodes.length; k++) {
                                var epk = episodes[k].episode_key;
                                var wk = epk ? ('k:' + epk) : (String(id) + ':' + String(episodes[k].id));
                                var h = watchedMap[wk];
                                if (effectiveState(h, { min: minThresh, max: maxThresh }) !== 3) {
                                    targetEp = episodes[k];
                                    break;
                                }
                            }
                            Catalog.playMedia({ item_id: id, title: targetEp.title || '' }, targetEp);
                        });
                    }
                });
            }
        });
    };

    Catalog.toggleWatchedState = function(idx) {
        var id = currentMediaId;
        if (!id || !currentEpisodes[id]) return;

        var mediaData = currentEpisodes[id];
        var episodes = mediaData.seasons[mediaData.activeSeason] || [];
        var ep = episodes[idx];
        if (!ep) return;

        window.API.getWatchThresholds(function(th) {
            var minThresh = th.min / 100;
            var maxThresh = th.max / 100;
            window.API.getHistory(function(histRes) {
                var h = null;
                var epKey = ep.episode_key || '';

                if (histRes && histRes.history) {
                    for (var j = 0; j < histRes.history.length; j++) {
                        var entry = histRes.history[j];
                        if (epKey && entry.episode_key === epKey) { h = entry; break; }
                        if (!epKey && entry.item_id === (ep.item_id || id) && String(entry.episode_id) === String(ep.id || 0)) { h = entry; break; }
                    }
                }

                // Estado efectivo actual (forzado o deducido por porcentaje)
                var currentState = effectiveState(h, { min: minThresh, max: maxThresh });
                // Cicla 1 -> 2 -> 3 -> 1 (nunca vuelve a 0; 0 solo se restaura al reproducir/salir)
                var nextState = (currentState % 3) + 1;

                // NO se inventa posición: se conserva la posición real guardada
                var lastPos = (h && h.progress) ? h.progress : 0;
                var duration = (h && h.duration > 0) ? h.duration : 0;
                var completed = (nextState === 3) ? 1 : 0;

                window.API.updateHistory(id, ep.video_src || wk, lastPos, duration, completed, function() {
                    renderEpisodesGrid();
                }, ep.id, nextState, epKey);
            });
        });
    };

    // Stub playMedia - will be replaced by player plugin
    Catalog.playMedia = function(id, videoSrc, title) {
        console.log('[PLAY] Media:', id, 'Src:', videoSrc, 'Title:', title);
    };

    // PlayMedia - delegado a player.js (tvcat1)
    Catalog.playItem = function(data, episode) {
        console.log('[PLAY] Item:', data ? data.title : 'unknown', 'Episode:', episode ? episode.title : 'N/A');
    };

    // Helper: show player selection overlay when multiple players exist

    // Helper: show player selection overlay when multiple players exist
    Catalog._showPlayerSelector = function(item, itemId, hasEpisodes, subcat, activePlayers) {
        var existing = document.getElementById('player-selector-overlay');
        if (existing) existing.remove();

        var overlay = document.createElement('div');
        overlay.id = 'player-selector-overlay';
        overlay.style.cssText = 'position:fixed;top:0;right:0;bottom:0;left:0;z-index:1000;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;';
        overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

        var panel = document.createElement('div');
        panel.style.cssText = 'background:#1a1a1e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;min-width:260px;max-width:320px;box-shadow:0 8px 32px rgba(0,0,0,0.5);';

        var title = document.createElement('div');
        title.style.cssText = 'font-size:0.9rem;font-weight:600;margin-bottom:12px;color:var(--text-primary);';
        title.textContent = 'Selecciona un reproductor:';
        panel.appendChild(title);

        for (var pi = 0; pi < activePlayers.length; pi++) {
            var pl = activePlayers[pi];
            var btn = document.createElement('button');
            btn.style.cssText = 'display:flex;align-items:center;gap:10px;width:100%;padding:10px 14px;margin:4px 0;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);border-radius:8px;color:#fff;font-size:0.9rem;cursor:pointer;transition:0.2s;text-align:left;';
            btn.onmouseenter = function() { this.style.background = 'rgba(225,29,72,0.15)'; };
            btn.onmouseleave = function() { this.style.background = 'rgba(255,255,255,0.05)'; };
            var selIcon = pl.playIcon;
            if (pl.name && pl.name.indexOf('tvcat_')===0) {
                selIcon = '<img src="/plugin-static/' + pl.name + '/plugin.png" style="width:28px;height:28px;object-fit:contain;border-radius:4px;vertical-align:middle;" onerror="this.onerror=null;this.src=\'/plugin-static/' + pl.name + '/plugin_icon.png\';">';
            }
            var selLabel = pl.playLabel || pl.displayName || pl.name;
            // si playLabel está vacío (como PS3 ahora), usar displayName como label en el selector
            if (!selLabel && pl.displayName) selLabel = pl.displayName;
            btn.innerHTML = '<span style="font-size:1.2rem;display:inline-flex;align-items:center;">' + selIcon + '</span> <span>' + selLabel + '</span>';
            var selTip = pl.tooltip || pl.displayName || selLabel;
            btn.title = selTip;
            btn.onclick = (function(plugin) {
                return function() { overlay.remove(); localStorage.setItem('tvcat_preferred_player', plugin.playerType); if (typeof plugin.play === 'function') plugin.play(item); else Catalog._playWithPlayer(item, itemId, hasEpisodes, subcat, plugin); };
            })(pl);
            panel.appendChild(btn);
        }

        var cancelBtn = document.createElement('button');
        cancelBtn.textContent = 'Cancelar';
        cancelBtn.style.cssText = 'width:100%;padding:8px;margin-top:8px;background:transparent;border:none;color:rgba(255,255,255,0.4);font-size:0.8rem;cursor:pointer;';
        cancelBtn.onclick = function() { overlay.remove(); };
        panel.appendChild(cancelBtn);

        overlay.appendChild(panel);
        document.body.appendChild(overlay);
    };

    // Helper: play with a specific player plugin
    Catalog._playWithPlayer = function(item, itemId, hasEpisodes, subcat, playerPlugin) {
        if (!playerPlugin || !playerPlugin.play) return;

        if (hasEpisodes && subcat.match(/(anime|series|tv)/)) {
            // Series: find next unwatched episode, then play
            window.API.ajax({
                url: '/api/media/' + itemId + '/episodes',
                success: function(seasonsData) {
                    var allEps = [];
                    var activeSeason = '';
                    if (seasonsData) {
                        var keys = Object.keys(seasonsData);
                        for (var ki = 0; ki < keys.length; ki++) {
                            var sName = keys[ki];
                            if (!activeSeason) activeSeason = sName;
                            allEps = allEps.concat(seasonsData[sName]);
                        }
                    }
                    // Store for prev/next navigation
                    currentEpisodes[itemId] = {
                        activeSeason: activeSeason,
                        seasons: seasonsData || {}
                    };
                    if (allEps.length === 0) return;
                    window.API.ajax({
                        url: '/api/watch/history',
                        success: function(histRes) {
                            var history = (histRes && histRes.history) || [];
                            var watched = {};
                            for (var hi = 0; hi < history.length; hi++) {
                                var h = history[hi];
                                if (h.episode_key) watched['k:' + h.episode_key] = h;
                                else watched[String(h.item_id) + ':' + String(h.episode_id)] = h;
                            }
                            var target = null;
                            window.API.getWatchThresholds(function(th) {
                                var minThresh = th.min / 100;
                                var maxThresh = th.max / 100;
                                for (var ei = 0; ei < allEps.length; ei++) {
                                    var ek = allEps[ei].episode_key;
                                    var wk = ek ? ('k:' + ek) : (String(itemId) + ':' + String(allEps[ei].id));
                                    var w = watched[wk];
                                    if (effectiveState(w, { min: minThresh, max: maxThresh }) !== 3) {
                                        target = allEps[ei];
                                        break;
                                    }
                                }
                                if (!target) target = allEps[0];
                                Catalog.playMedia(item, target);
                            });
                        },
                        error: function() {
                            Catalog.playMedia(item, allEps[0]);
                        }
                    });
                },
                error: function() {
                    // Fallback to first episode from item data
                    if (item.episodes && item.episodes.length > 0) {
                        Catalog.playMedia(item, item.episodes[0]);
                    }
                }
            });
        } else if (hasEpisodes) {
            // Non-series with episodes — play first
            var ep = item.episodes[0];
            window.API.ajax({
                method: 'POST',
                url: '/api/watch/progress',
                data: { item_id: itemId, episode_id: ep.id || 0, progress: 0, duration: ep.duration || 0 }
            });
            Catalog.playMedia(item, ep);
        } else {
            // Standalone item (movie): play using item-level telegram_link
            var pseudoEp = {
                id: 0,
                title: '',
                telegram_link: item.telegram_link || '',
                telegram_msg_id: item.telegram_msg_id || null,
                video_src: itemId + ':0'
            };
            Catalog.playMedia(item, pseudoEp);
        }
    };

    function _updateFavUI(repId, isFav) {
        var buttons = document.querySelectorAll('.grid-item-fav, .meta-fav-btn');
        for (var bi = 0; bi < buttons.length; bi++) {
            var btn = buttons[bi];
            if (repId && repId !== 'undefined' && repId !== 'null' && btn.getAttribute('data-rep-id') !== repId) continue;
            if (btn.classList.contains('meta-fav-btn')) {
                btn.classList.toggle('favorited', isFav);
                btn.title = isFav ? 'Quitar de Favoritos' : 'A\u00f1adir a Favoritos';
            } else {
                btn.setAttribute('data-fav', isFav ? 'true' : 'false');
                btn.classList.toggle('active', isFav);
            }
            var svg = btn.querySelector('svg');
            if (svg) svg.setAttribute('fill', isFav ? '#e11d48' : 'rgba(255, 255, 255, 0.4)');
        }
    }

    function _removeGridItemByRepId(repId) {
        var items = document.querySelectorAll('.grid-item');
        for (var i = 0; i < items.length; i++) {
            if (items[i].getAttribute('data-rep-id') === repId) {
                items[i].style.transition = 'all 0.3s ease';
                items[i].style.opacity = '0';
                items[i].style.transform = 'scale(0.8)';
                setTimeout(function(el) {
                    if (el.parentNode) el.parentNode.removeChild(el);
                }, 300, items[i]);
                break;
            }
        }
    }

    Catalog.toggleGridFavorite = function(event, id, category) {
        if (event) event.stopPropagation();
        window.API.toggleFavorite(id, category || currentCategory, function(res) {
            var isFav = res && res.is_favorite;
            var repId = res && res.representative_id;
            if (repId) _updateFavUI(repId, isFav);
            if (currentCategory === 'favorites' && !isFav && repId) {
                _removeGridItemByRepId(repId);
            }
        });
    };

    Catalog.toggleMetadataFavorite = function(id, category) {
        window.API.toggleFavorite(id, category || currentCategory, function(res) {
            var isFav = res && res.is_favorite;
            var repId = res && res.representative_id;
            if (repId) _updateFavUI(repId, isFav);
            if (currentCategory === 'favorites' && !isFav && repId) {
                _removeGridItemByRepId(repId);
            }
        });
    };
})();
