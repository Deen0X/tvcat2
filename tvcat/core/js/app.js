/**
 * TVCat 2 - Main Entry Point & Boot Sequence
 */

// --- Sidebar Toggle ---
window.toggleSideMenu = function() {
    var menu = document.getElementById('side-menu');
    var overlay = document.getElementById('side-menu-overlay');
    if (!menu) return;
    var isOpen = menu.classList.toggle('open');
    if (overlay) overlay.classList.toggle('open', isOpen);
};

// --- Section Selection ---
window.selectSection = function(category, element) {
    var menuLinks = document.querySelectorAll('.side-menu-nav a');
    for (var i = 0; i < menuLinks.length; i++) {
        menuLinks[i].classList.remove('active');
    }
    if (element) element.classList.add('active');

    window.Catalog.currentCategory = category;
    localStorage.setItem('tvcat_last_section', category);

    var searchInput = document.getElementById('global-search');
    var searchText = searchInput ? searchInput.value.trim() : '';
    if (searchText.length >= 2) {
        window.Catalog.performSearch(searchText);
    } else if (category === 'favorites') {
        loadFavorites();
    } else if (category === 'continue') {
        loadContinueWatching();
    } else if (category === 'completed') {
        loadCompleted();
    } else {
        window.Catalog.load(category);
    }
};

// --- Search with wildcards ---
function parseWildcardSearch(query) {
    var normalized = query.toLowerCase().trim().replace(/\s+/g, ' ');
    if (normalized.indexOf('*') === -1) {
        return [normalized];
    }
    var parts = normalized.split('*').filter(function(p) { return p.trim() !== ''; });
    return parts.length > 0 ? parts : [normalized];
}

window.handleSearch = function(value) {
    var clearBtn = document.getElementById('clear-search-btn');
    if (clearBtn) {
        clearBtn.classList.toggle('hidden', value.trim().length === 0);
    }
    var input = document.getElementById('global-search');
    saveSearchState();
    if (value.trim().length >= 2) {
        window.Catalog.performSearch(value.trim());
    } else if (value.trim().length === 0) {
        window.Catalog.load(window.Catalog.currentCategory || 'home');
    }
    // Mantener foco en el buscador
    if (input) input.focus();
};

window.clearSearch = function() {
    var input = document.getElementById('global-search');
    if (input) {
        input.value = '';
        handleSearch('');
        input.focus();
    }
};

// --- Favorites ---
function loadFavorites() {
    window.Catalog.load('favorites');
}

// --- Continue Watching ---
function loadContinueWatching() {
    showLoading(true);
    window.API.ajax({
        url: '/api/catalog/continue',
        success: function(data) {
            window.Catalog.renderItems(data.items || []);
            updateBadge(data.count || 0);
            showLoading(false);
        },
        error: function() { showLoading(false); }
    });
}

// --- Completed ---
function loadCompleted() {
    showLoading(true);
    window.API.ajax({
        url: '/api/catalog/completed',
        success: function(data) {
            window.Catalog.renderItems(data.items || []);
            updateBadge(data.count || 0);
            showLoading(false);
        },
        error: function() { showLoading(false); }
    });
}

// --- Helpers ---
function showLoading(show) {
    var grid = document.getElementById('catalog-grid');
    if (!grid) return;
    if (show) {
        var items = [];
        for (var i = 0; i < 12; i++) {
            items.push('<div class="grid-item grid-item-skeleton"><div class="grid-item-cover" style="background:var(--bg-surface);animation:pulse 1.5s infinite;"></div></div>');
        }
        grid.innerHTML = items.join('');
    }
}

function updateBadge(count) {
    var badge = document.getElementById('results-count');
    if (badge) {
        badge.textContent = count + ' \u00EDtem' + (count !== 1 ? 's' : '');
    }
}

// --- Refresh (respeta búsqueda activa + filtros del modal) ---
window.refreshCatalog = function() {
    var searchInput = document.getElementById('global-search');
    var text = searchInput ? searchInput.value.trim() : '';
    if (text.length >= 2) {
        window.Catalog.performSearch(text);
    } else {
        var cat = window.Catalog.currentCategory || 'home';
        window.Catalog.load(cat);
    }
};

// --- Logout ---
window.logout = function() {
    localStorage.removeItem('tvcat_token');
    window.API.ajax({
        url: '/api/auth/logout',
        method: 'POST',
        success: function() {
            window.location.href = '/login';
        }
    });
};

// --- Persistencia del estado de b\u00FAsqueda ---
function saveSearchState() {
    var input = document.getElementById('global-search');
    var text = input ? input.value : '';
    try {
        localStorage.setItem('tvcat_search_state', JSON.stringify({
            search_text: text,
            filters: _activeFilters
        }));
    } catch(e) {}
}

function loadSearchState() {
    try {
        var raw = localStorage.getItem('tvcat_search_state');
        if (!raw) return;
        var state = JSON.parse(raw);
        // Restaurar texto
        var input = document.getElementById('global-search');
        if (input && state.search_text) {
            input.value = state.search_text;
            var clearBtn = document.getElementById('clear-search-btn');
            if (clearBtn) clearBtn.classList.toggle('hidden', state.search_text.trim().length === 0);
        }
        // Restaurar filtros
        if (state.filters) {
            if (state.filters.fields) {
                _activeFilters.fields = state.filters.fields;
            }
            // Estado de géneros: se resetea siempre (checked = incluir, por defecto todos marcados)
            _activeFilters.categories = {};
            _activeFilters.year_from = state.filters.year_from || null;
            _activeFilters.year_to = state.filters.year_to || null;
            // Actualizar checkboxes del modal si existen
            var titleChk = document.getElementById('filter-title');
            var altChk = document.getElementById('filter-alt-titles');
            var descChk = document.getElementById('filter-description');
            if (titleChk) titleChk.checked = _activeFilters.fields.title !== false;
            if (altChk) altChk.checked = _activeFilters.fields.alt_titles === true;
            if (descChk) descChk.checked = _activeFilters.fields.description === true;
            var yearFrom = document.getElementById('filter-year-from');
            var yearTo = document.getElementById('filter-year-to');
            if (yearFrom) yearFrom.value = _activeFilters.year_from || '';
            if (yearTo) yearTo.value = _activeFilters.year_to || '';
            // Actualizar bot\u00F3n de filtro
            var hasGenreFilter = false;
            for (var g in _activeFilters.categories) {
                if (_activeFilters.categories[g] === false) { hasGenreFilter = true; break; }
            }
            var hasFilters = !_activeFilters.fields.title || _activeFilters.fields.alt_titles ||
                _activeFilters.fields.description || _activeFilters.year_from || _activeFilters.year_to || hasGenreFilter;
            var filterBtn = document.getElementById('filter-btn');
            if (filterBtn) filterBtn.classList.toggle('active', hasFilters);
        }
    } catch(e) {}
}

// --- Filter Modal ---
var _activeFilters = {
    fields: { title: true, alt_titles: false, description: false },
    categories: {},
    year_from: null,
    year_to: null
};

window.toggleFilterModal = function() {
    var modal = document.getElementById('filter-modal');
    if (modal) {
        modal.classList.toggle('hidden');
        if (!modal.classList.contains('hidden')) {
            applyFilterGenresCollapse();
            loadFilterCategories();
        }
    }
};

function loadFilterCategories() {
    var container = document.getElementById('filter-categories-container');
    if (!container) return;
    window.API.ajax({
        url: '/api/genres',
        success: function(data) {
            var terms = data.terms || [];
            window._tagDictionary = {};
            for (var i = 0; i < terms.length; i++) {
                window._tagDictionary[terms[i].term] = terms[i].tags || [];
            }
            if (terms.length === 0) {
                container.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem;">Sin g\u00E9neros disponibles (se rellenar\u00E1n con datos reales)</p>';
                return;
            }
            // Resetear estado de géneros si no coincide con el diccionario actual
            var stale = false;
            for (var g in _activeFilters.categories) {
                if (window._tagDictionary[g] === undefined) { stale = true; break; }
            }
            if (stale) _activeFilters.categories = {};
            var html = '';
            for (var j = 0; j < terms.length; j++) {
                var term = terms[j].term;
                var checked = _activeFilters.categories[term] !== false;
                html += '<label class="filter-checkbox">' +
                    '<input type="checkbox" data-cat="' + term + '" ' + (checked ? 'checked' : '') + ' onchange="toggleFilterCategory(this)"> ' +
                    term +
                    '</label>';
            }
            container.innerHTML = html;
        },
        error: function() {
            container.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem;">Sin g\u00E9neros disponibles</p>';
        }
    });
}

window.toggleFilterCategory = function(el) {
    var cat = el.getAttribute('data-cat');
    _activeFilters.categories[cat] = el.checked;
};

window.selectAllGenres = function() {
    var cb = document.querySelectorAll('#filter-categories-container input[type="checkbox"]');
    for (var i = 0; i < cb.length; i++) {
        cb[i].checked = true;
        _activeFilters.categories[cb[i].getAttribute('data-cat')] = true;
    }
};

window.deselectAllGenres = function() {
    var cb = document.querySelectorAll('#filter-categories-container input[type="checkbox"]');
    for (var i = 0; i < cb.length; i++) {
        cb[i].checked = false;
        _activeFilters.categories[cb[i].getAttribute('data-cat')] = false;
    }
};

window.toggleFilterGenres = function(e) {
    if (e) e.stopPropagation();
    var body = document.getElementById('filter-genres-body');
    var ind = document.getElementById('filter-genres-indicator');
    if (!body) return;
    var collapsed = body.style.display === 'none';
    body.style.display = collapsed ? '' : 'none';
    if (ind) ind.style.transform = collapsed ? '' : 'rotate(-90deg)';
    try { localStorage.setItem('tvcat_filter_genres_collapsed', collapsed ? '0' : '1'); } catch(err) {}
};

function applyFilterGenresCollapse() {
    var body = document.getElementById('filter-genres-body');
    var ind = document.getElementById('filter-genres-indicator');
    if (!body) return;
    var collapsed = false;
    try { collapsed = localStorage.getItem('tvcat_filter_genres_collapsed') === '1'; } catch(err) {}
    body.style.display = collapsed ? 'none' : '';
    if (ind) ind.style.transform = collapsed ? 'rotate(-90deg)' : '';
}

window.applyFilters = function() {
    _activeFilters.fields.title = document.getElementById('filter-title').checked;
    _activeFilters.fields.alt_titles = document.getElementById('filter-alt-titles').checked;
    _activeFilters.fields.description = document.getElementById('filter-description').checked;

    var yearFrom = document.getElementById('filter-year-from').value;
    var yearTo = document.getElementById('filter-year-to').value;
    _activeFilters.year_from = yearFrom ? parseInt(yearFrom) : null;
    _activeFilters.year_to = yearTo ? parseInt(yearTo) : null;

    var filterBtn = document.getElementById('filter-btn');
    var hasGenreFilter = false;
    for (var g in _activeFilters.categories) {
        if (_activeFilters.categories[g] === false) { hasGenreFilter = true; break; }
    }
    var hasFilters = !_activeFilters.fields.title || _activeFilters.fields.alt_titles ||
        _activeFilters.fields.description || _activeFilters.year_from || _activeFilters.year_to || hasGenreFilter;
    if (filterBtn) filterBtn.classList.toggle('active', hasFilters);

    saveSearchState();
    toggleFilterModal();

    var searchInput = document.getElementById('global-search');
    var text = searchInput ? searchInput.value.trim() : '';
    if (text.length >= 2) {
        window.Catalog.performSearch(text);
    } else {
        window.Catalog.load(window.Catalog.currentCategory || 'home');
    }
};

window.clearYearFilter = function() {
    document.getElementById('filter-year-from').value = '';
    document.getElementById('filter-year-to').value = '';
};

// --- Settings Modal ---
window.toggleSettingsModal = function() {
    var modal = document.getElementById('settings-modal');
    if (!modal) return;
    var wasHidden = modal.classList.contains('hidden');
    modal.classList.toggle('hidden');
    if (!wasHidden) {
        // Cerrando el modal: resetear estado de plugin config para evitar bloqueos
        window._pluginConfigOpen = false;
        exitPluginFullScreen();
    }
    if (!modal.classList.contains('hidden')) {
        // Limpiar estilos inline heredados de cierres previos con UI.toggleSettingsModal
        // (dejaba display/visibility/opacity inline y bloqueaba la reapertura)
        modal.style.display = '';
        modal.style.visibility = '';
        modal.style.opacity = '';
        loadSettings();
        if (window.UI) window.UI.loadSettings();
        setTimeout(fixSettingsHeight, 100);
    }
};

function fixSettingsHeight() {
    var content = document.querySelector('.settings-content');
    var container = document.querySelector('.settings-tab-container');
    if (!content || !container) return;
    // Si ya tiene altura fija, no recalcular
    if (content.style.height) return;
    // Medir altura actual del contenido (pesta\u00F1a perfil, que es la m\u00E1s grande)
    var h = content.offsetHeight;
    if (h > 0) {
        content.style.height = h + 'px';
    }
}

function switchSettingsTab(tab) {
    if (window._pluginConfigOpen && tab !== 'plugins') {
        alert('Guarda o cancela la configuraci\u00F3n del plugin antes de cambiar de secci\u00F3n.');
        return;
    }
    var tabs = document.querySelectorAll('.tab-btn');
    for (var i = 0; i < tabs.length; i++) {
        tabs[i].classList.remove('active');
    }
    var activeTab = document.querySelector('.tab-btn[onclick*="' + tab + '"]');
    if (activeTab) activeTab.classList.add('active');

    var panes = document.querySelectorAll('.tab-pane');
    for (var i = 0; i < panes.length; i++) {
        panes[i].classList.add('hidden');
    }
    var pane = document.getElementById('pane-' + tab);
    if (pane) pane.classList.remove('hidden');

    var ua = document.getElementById('userbot-footer-actions');
    if (ua) ua.style.display = tab === 'userbot' ? 'flex' : 'none';

    if (tab === 'plugins') loadPluginsList();
    if (tab === 'admin') loadAdminUsers();
    if (tab === 'cache') setTimeout(updateCacheStats, 100);
    if (tab === 'mobile') loadMobileConfig();
    if (tab === 'contents') loadContentsTrees();
    if (tab === 'administration') window.adminLoadLog();
}

window.switchSettingsTab = switchSettingsTab;

// --- Userbot Session List ---
var _userbotVisible = false;

function maskValue(val) {
    if (!val) return '';
    return '\u2022'.repeat(Math.min(val.length, 20));
}

function getUserbotField(fieldId) {
    var el = document.getElementById(fieldId);
    if (!el) return '';
    if (el.getAttribute('data-real')) return el.getAttribute('data-real');
    return el.value;
}

function loadUserbotConfig() {
    window.API.ajax({
        url: '/api/config',
        success: function(config) {
            window._userbotHostname = config.hostname || 'unknown';
            var fields = [
                { id: 'userbot-api-id', val: config.telegram_api_id || '' },
                { id: 'userbot-api-hash', val: config.telegram_api_hash || '' },
                { id: 'userbot-phone', val: config.telegram_phone || '' }
            ];
            for (var i = 0; i < fields.length; i++) {
                var el = document.getElementById(fields[i].id);
                if (!el) continue;
                el.setAttribute('data-real', fields[i].val);
                el.value = _userbotVisible ? fields[i].val : maskValue(fields[i].val);
                el.oninput = function() {
                    this.setAttribute('data-real', this.value);
                };
                el.onfocus = function() {
                    if (!_userbotVisible && this.getAttribute('data-real')) {
                        this.value = this.getAttribute('data-real');
                        this.setSelectionRange(this.value.length, this.value.length);
                    }
                };
                el.onblur = function() {
                    if (!_userbotVisible && this.getAttribute('data-real')) {
                        this.value = maskValue(this.getAttribute('data-real'));
                    }
                };
            }
        }
    });

    window.API.ajax({
        url: '/api/settings',
        success: function(settings) {
            var interval = settings.jit_cover_interval || '1.0';
            var sel = document.getElementById('setting-jit-cover-interval');
            if (sel) sel.value = interval;
        }
    });

    // Cargar configuración de Google (client_id/secret/redirect del sistema)
    window.API.ajax({
        url: '/api/auth/google/config',
        success: function(cfg) {
            var ri = document.getElementById('google-redirect-uri-input');
            if (ri && cfg && cfg.redirect_uri) ri.value = cfg.redirect_uri;
            var red = document.getElementById('google-redirect-uri');
            if (red) red.textContent = (cfg && cfg.redirect_uri) || (location.origin + '/api/auth/google/callback');
        }
    });
    window.API.ajax({
        url: '/api/settings',
        success: function(settings) {
            var cid = document.getElementById('google-client-id');
            var csec = document.getElementById('google-client-secret');
            var ri = document.getElementById('google-redirect-uri-input');
            if (cid) cid.value = settings.google_client_id || '';
            if (csec) csec.value = settings.google_client_secret || '';
            if (ri) ri.value = settings.google_redirect_uri || '';
        }
    });

    // Guardar configuración de Google (admin)
    window.saveGoogleConfig = function() {
        var cid = document.getElementById('google-client-id');
        var csec = document.getElementById('google-client-secret');
        var ri = document.getElementById('google-redirect-uri-input');
        var st = document.getElementById('google-config-status');
        window.API.ajax({
            method: 'POST',
            url: '/api/auth/google/config',
            data: {
                client_id: cid ? cid.value.trim() : '',
                client_secret: csec ? csec.value.trim() : '',
                redirect_uri: ri ? ri.value.trim() : ''
            },
            success: function(r) {
                if (r && r.ok) {
                    if (st) st.textContent = 'Guardado. ' + ((cid && cid.value.trim()) ? 'Login con Google habilitado.' : 'Login con Google deshabilitado.');
                } else if (st) { st.textContent = 'Error al guardar'; }
            },
            error: function() { if (st) st.textContent = 'Error al guardar'; }
        });
    };

    // Cargar configuración del enriquecedor (admin)
    window.loadEnrichConfig = function() {
        window.API.ajax({
            url: '/api/enrich/config',
            success: function(cfg) {
                if (!cfg) return;
                if (cfg.threshold !== undefined && cfg.threshold !== null) {
                    var th = document.getElementById('enrich-threshold');
                    if (th) th.value = cfg.threshold;
                }
                // No se muestran secretos en claro; solo se informa si está configurado
                var creds = cfg.credentials || {};
                function badge(prov, elId) {
                    var el = document.getElementById(elId);
                    if (!el) return;
                    if (creds[prov] && creds[prov].configured) {
                        el.placeholder = '✓ configurado (dejar vacío para mantener)';
                    }
                }
                badge('tmdb', 'enrich-tmdb-key');
                badge('igdb', 'enrich-igdb-id');
                badge('igdb', 'enrich-igdb-secret');
                badge('comicvine', 'enrich-comicvine-key');
                // Plantillas de cover
                var tpls = cfg.templates || {};
                var fallbackEl = document.getElementById('enrich-tpl-fallback');
                if (fallbackEl) fallbackEl.value = tpls.fallback || '';
                renderEnrichTemplates(tpls.categories || {});
            }
        });
    };

    function renderEnrichTemplates(cats) {
        var list = document.getElementById('enrich-tpl-list');
        if (!list) return;
        var keys = Object.keys(cats || {}).sort();
        if (!keys.length) { list.innerHTML = '<div style="font-size:0.7rem;color:var(--text-secondary);">Sin plantillas específicas</div>'; return; }
        var html = '';
        for (var i = 0; i < keys.length; i++) {
            html += '<div style="display:flex;gap:6px;align-items:flex-start;margin-bottom:4px;">' +
                '<span style="font-size:0.7rem;color:var(--accent);min-width:90px;padding-top:6px;word-break:break-word;">' + keys[i] + '</span>' +
                '<textarea data-tpl-key="' + keys[i] + '" rows="3" style="flex:1;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 6px;font-size:0.75rem;box-sizing:border-box;resize:vertical;">' + (cats[keys[i]] || '') + '</textarea>' +
                '<button class="btn-secondary" onclick="removeEnrichTemplate(this)" style="padding:4px 8px;font-size:0.75rem;" title="Quitar">&times;</button>' +
                '</div>';
        }
        list.innerHTML = html;
    }

    window.addEnrichTemplate = function() {
        var keyEl = document.getElementById('enrich-tpl-key');
        var list = document.getElementById('enrich-tpl-list');
        if (!keyEl || !list) return;
        var key = (keyEl.value || '').trim();
        if (!key) return;
        keyEl.value = '';
        // Evitar duplicados: reutilizar textarea existente
        var existing = list.querySelector('textarea[data-tpl-key="' + key + '"]');
        if (existing) { existing.focus(); return; }
        var div = document.createElement('div');
        div.style.cssText = 'display:flex;gap:6px;align-items:flex-start;margin-bottom:4px;';
        div.innerHTML =
            '<span style="font-size:0.7rem;color:var(--accent);min-width:90px;padding-top:6px;word-break:break-word;">' + key + '</span>' +
            '<textarea data-tpl-key="' + key + '" rows="3" style="flex:1;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 6px;font-size:0.75rem;box-sizing:border-box;resize:vertical;"></textarea>' +
            '<button class="btn-secondary" onclick="removeEnrichTemplate(this)" style="padding:4px 8px;font-size:0.75rem;" title="Quitar">&times;</button>';
        list.appendChild(div);
        list.querySelector('textarea[data-tpl-key="' + key + '"]').focus();
    };

    window.removeEnrichTemplate = function(btn) {
        var row = btn.parentElement;
        if (row && row.parentElement) row.parentElement.removeChild(row);
    };

    function collectEnrichTemplates() {
        var tpls = { fallback: (document.getElementById('enrich-tpl-fallback') || {}).value || '', categories: {} };
        var list = document.getElementById('enrich-tpl-list');
        if (!list) return tpls;
        var rows = list.querySelectorAll('textarea[data-tpl-key]');
        for (var i = 0; i < rows.length; i++) {
            var k = rows[i].getAttribute('data-tpl-key');
            if (k) tpls.categories[k] = rows[i].value;
        }
        return tpls;
    }

    // Guardar configuración del enriquecedor (admin)
    window.saveEnrichConfig = function() {
        var st = document.getElementById('enrich-config-status');
        var creds = {
            tmdb: { api_key: (document.getElementById('enrich-tmdb-key') || {}).value || '' },
            igdb: {
                client_id: (document.getElementById('enrich-igdb-id') || {}).value || '',
                client_secret: (document.getElementById('enrich-igdb-secret') || {}).value || ''
            },
            comicvine: { api_key: (document.getElementById('enrich-comicvine-key') || {}).value || '' }
        };
        var threshold = parseFloat((document.getElementById('enrich-threshold') || {}).value || '0.95');
        if (isNaN(threshold)) threshold = 0.95;
        window.API.ajax({
            method: 'POST',
            url: '/api/enrich/config',
            data: { credentials: creds, threshold: threshold, templates: collectEnrichTemplates() },
            success: function(r) {
                if (r && r.threshold !== undefined) { if (st) st.textContent = 'Guardado.'; }
                else if (st) st.textContent = 'Error al guardar';
                window.loadEnrichConfig();
            },
            error: function() { if (st) st.textContent = 'Error al guardar'; }
        });
    };

    // Cargar usuarios Telegram + sesiones
    window.loadUserbotSessions = function() {
    var container = document.getElementById('userbot-sessions-list');
    if (!container) return;

    function renderTelegramUsers(users) {
        var html = '';
        for (var u = 0; u < users.length; u++) {
            var user = users[u];
            var checked = user.is_default ? '\u25CB' : '\u25C9';
            html += '<div class="plugin-item" style="flex-wrap:wrap;margin-top:8px;" data-tg="' + user.tg_user_id + '">' +
                '<div style="flex:1;display:flex;align-items:center;gap:8px;min-width:0;">' +
                '<span class="user-radio" onclick="toggleDefaultUser(' + user.tg_user_id + ')" ' +
                'style="cursor:pointer;font-size:1.2rem;user-select:none;width:1.2rem;text-align:center;color:var(--accent);">' + checked + '</span>' +
                '<span class="user-name" style="font-weight:600;">' + user.name + '</span>' +
                '</div>' +
                '<div style="display:flex;align-items:center;gap:4px;margin-left:auto;">' +
                '<span class="test-t" id="test-t-' + user.tg_user_id + '" style="font-size:0.8rem;color:var(--text-secondary);font-family:monospace;display:none;"></span>' +
                '<span class="test-p" id="test-p-' + user.tg_user_id + '" style="font-size:0.8rem;color:var(--text-secondary);font-family:monospace;display:none;"></span>' +
                '<button class="plugin-config-btn" onclick="testUserSessions(' + user.tg_user_id + ')" title="Probar">\u25B6</button>' +
                '<button class="plugin-config-btn" onclick="editUserSessions(' + user.tg_user_id + ')" title="Editar sesiones">\u270E</button>' +
                '<button class="plugin-config-btn" onclick="deleteTelegramUser(' + user.tg_user_id + ')" title="Eliminar usuario" style="color:var(--accent);">\u2715</button>' +
                '</div></div>';

            // Sub-info: selector cliente activo + sesiones
            html += '<div style="padding:2px 12px 4px 40px;display:flex;align-items:center;gap:12px;font-size:0.75rem;color:var(--text-secondary);">' +
                'Cliente: ' +
                '<select onchange="setActiveClient(' + user.tg_user_id + ', this.value)" ' +
                'style="background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:1px 4px;font-size:0.75rem;">' +
                '<option value="telethon"' + (user.active_client === 'telethon' ? ' selected' : '') + '>Telethon</option>' +
                '<option value="pyrogram"' + (user.active_client === 'pyrogram' ? ' selected' : '') + '>Pyrogram</option>' +
                '</select>';
            var sessList = user.sessions || [];
            for (var j = 0; j < sessList.length; j++) {
                var sess = sessList[j];
                html += ' &middot; ' + sess.name +
                    ' <button class="plugin-config-btn" onclick="editSession(' + sess.id + ')" title="Editar" style="font-size:0.7rem;padding:0 4px;">\u270E</button>' +
                    ' <button class="plugin-config-btn" onclick="deleteSession(' + sess.id + ')" title="Eliminar" style="font-size:0.7rem;padding:0 4px;color:var(--accent);">\u2715</button>';
            }
            html += '</div>';
        }
        if (!html) html = '<p style="color:var(--text-secondary);font-size:0.85rem;">Sin usuarios Telegram. Crea una sesi\u00F3n primero.</p>';
        container.innerHTML = html;
    }

    window.API.ajax({
        url: '/api/telegram/users',
        success: function(data) {
            var users = data.users || [];
            if (users.length > 0) {
                renderTelegramUsers(users);
            } else {
                // Fallback a sessions planas
                window.API.ajax({
                    url: '/api/userbot/sessions',
                    success: function(data) {
                        var sessions = data.sessions || [];
                        var html = '';
                        var groups = { telethon: [], pyrogram: [] };
                        for (var i = 0; i < sessions.length; i++) {
                            var s = sessions[i];
                            if (groups[s.client_type]) groups[s.client_type].push(s);
                        }
                        var clientLabels = { telethon: 'Telethon', pyrogram: 'Pyrogram' };
                        for (var type in groups) {
                            var list = groups[type];
                            if (list.length === 0) continue;
                            html += '<div class="plugin-section-title">' + (clientLabels[type] || type) + '</div>';
                            for (var j = 0; j < list.length; j++) {
                                var sess = list[j];
                                var isActive = sess.is_active ? ' \u25C9' : ' \u25CB';
                                html += '<div class="plugin-item">' +
                                    '<div style="flex:1;min-width:0;">' +
                                    '<div class="plugin-item-name">' + isActive + ' ' + sess.name + '</div></div>' +
                                    '<div class="plugin-item-status">' +
                                    '<button class="plugin-config-btn" onclick="testSingleSession(' + sess.id + ')" title="Probar">\u25B6</button>' +
                                    '<button class="plugin-config-btn" onclick="editSession(' + sess.id + ')" title="Editar">\u270E</button>' +
                                    '<button class="plugin-config-btn" onclick="deleteSession(' + sess.id + ')" title="Eliminar" style="color:var(--accent);">\u2715</button>' +
                                    '</div></div>';
                            }
                        }
                        if (!html) html = '<p style="color:var(--text-secondary);font-size:0.85rem;">Sin sesiones. Crea una nueva.</p>';
                        container.innerHTML = html;
                    }
                });
            }
        }
    });
}
}

window.setActiveClient = function(tgUserId, clientType) {
    window.API.ajax({
        method: 'PUT',
        url: '/api/telegram/users/' + tgUserId,
        data: { active_client: clientType },
        success: function() { loadUserbotSessions(); }
    });
}

window.toggleDefaultUser = function(tgUserId) {
    window.API.ajax({
        method: 'PUT',
        url: '/api/telegram/users/' + tgUserId,
        data: { is_default: true },
        success: function() { loadUserbotSessions(); }
    });
}

window.toggleUserbotVisibility = function() {
    _userbotVisible = !_userbotVisible;
    var btn = document.getElementById('userbot-eye-btn');
    if (btn) btn.textContent = _userbotVisible ? '\uD83D\uDC41' : '\uD83D\uDC41';
    ['userbot-api-id', 'userbot-api-hash', 'userbot-phone'].forEach(function(id) {
        var el = document.getElementById(id);
        if (!el) return;
        var real = el.getAttribute('data-real');
        if (_userbotVisible) {
            el.value = real || '';
        } else {
            el.value = maskValue(real);
        }
    });
};

window.saveTelegramSettings = function() {
    var interval = document.getElementById('setting-jit-cover-interval');
    if (!interval) return;
    window.API.ajax({
        method: 'POST',
        url: '/api/settings',
        data: { jit_cover_interval: interval.value },
        success: function() { console.log('Settings guardados'); }
    });
};

window.saveCacheConfig = function() {
    var input = document.getElementById('cache-max-size');
    if (!input) return;
    var gb = parseInt(input.value, 10) || 5;
    localStorage.setItem('tvcat_cache_max_size_gb', JSON.stringify(gb));
    var status = document.getElementById('cache-status');
    if (status) status.textContent = '\u2705 Guardado (' + gb + ' GB)';
    setTimeout(function() { if (status) status.textContent = ''; }, 2000);
    updateCacheStats();
};

window.clearVideoCache = function() {
    if (!confirm('\u00BFVaciar todo el cach\u00E9 de v\u00EDdeos? Se perder\u00E1n los v\u00EDdeos descargados localmente.')) return;
    // Abrir la base de datos del Player Pro y limpiarla
    var req = indexedDB.open('tvcat_player_pro_cache', 1);
    req.onsuccess = function(e) {
        var db = e.target.result;
        var tx = db.transaction('chunks', 'readwrite');
        tx.objectStore('chunks').clear();
        tx.oncomplete = function() {
            var status = document.getElementById('cache-status');
            if (status) status.textContent = '\u2705 Cach\u00E9 vaciado';
            setTimeout(function() { if (status) status.textContent = ''; }, 3000);
            updateCacheStats();
        };
    };
    req.onerror = function() {
        var status = document.getElementById('cache-status');
        if (status) status.textContent = '\u274C Error al vaciar cach\u00E9';
    };
};

function updateCacheStats() {
    var statsDiv = document.getElementById('cache-stats');
    if (!statsDiv) return;
    var maxGB = JSON.parse(localStorage.getItem('tvcat_cache_max_size_gb') || '5');
    var maxBytes = maxGB * 1024 * 1024 * 1024;
    var req = indexedDB.open('tvcat_player_pro_cache', 1);
    req.onsuccess = function(e) {
        var db = e.target.result;
        try {
            var tx = db.transaction('chunks', 'readonly');
            var cursorReq = tx.objectStore('chunks').openCursor();
            var total = 0;
            cursorReq.onsuccess = function(ev) {
                var cursor = ev.target.result;
                if (cursor) { total += cursor.value.size || 0; cursor.continue(); }
                else {
                    var usedGB = (total / (1024*1024*1024)).toFixed(2);
                    var pct = maxBytes > 0 ? ((total / maxBytes) * 100).toFixed(1) : 0;
                    statsDiv.innerHTML = 'Usado: <strong>' + usedGB + ' GB</strong> de <strong>' + maxGB + ' GB</strong> (' + pct + '%)';
                    // Actualizar input con valor guardado
                    var input = document.getElementById('cache-max-size');
                    if (input) input.value = maxGB;
                }
            };
        } catch(e) {
            statsDiv.innerHTML = 'No hay datos de cach\u00E9 disponibles.';
        }
    };
    req.onerror = function() {
        statsDiv.innerHTML = 'No hay datos de cach\u00E9 disponibles.';
    };
}

window.updateProCacheStats = function() {
    var statsDiv = document.getElementById('pro-cache-stats');
    if (!statsDiv) return;
    var maxGB = JSON.parse(localStorage.getItem('tvcat_cache_max_size_gb') || '5');
    var maxBytes = maxGB * 1024 * 1024 * 1024;
    var req = indexedDB.open('tvcat_player_pro_cache', 1);
    req.onsuccess = function(e) {
        var db = e.target.result;
        try {
            var tx = db.transaction('chunks', 'readonly');
            var cursorReq = tx.objectStore('chunks').openCursor();
            var total = 0;
            var epCount = 0;
            cursorReq.onsuccess = function(ev) {
                var cursor = ev.target.result;
                if (cursor) { total += cursor.value.size || 0; epCount++; cursor.continue(); }
                else {
                    var usedGB = (total / (1024*1024*1024)).toFixed(2);
                    var pct = maxBytes > 0 ? ((total / maxBytes) * 100).toFixed(1) : 0;
                    statsDiv.innerHTML = 'Usado: <strong>' + usedGB + ' GB</strong> de <strong>' + maxGB + ' GB</strong> (' + pct + '%) \u00B7 ' + epCount + ' chunks';
                }
            };
        } catch(e) {
            statsDiv.innerHTML = 'No hay datos.';
        }
    };
};

window.clearProCache = function() {
    if (!confirm('\u00BFVaciar todo el cach\u00E9 de v\u00EDdeos? Se perder\u00E1n los v\u00EDdeos descargados localmente.')) return;
    var status = document.getElementById('pro-clear-status');
    if (status) status.textContent = 'Vaciando...';
    var req = indexedDB.open('tvcat_player_pro_cache', 1);
    req.onsuccess = function(e) {
        var db = e.target.result;
        var tx = db.transaction('chunks', 'readwrite');
        tx.objectStore('chunks').clear();
        tx.oncomplete = function() {
            if (status) status.textContent = '\u2705 Cach\u00E9 vaciado';
            setTimeout(function() { if (status) status.textContent = ''; }, 3000);
            updateProCacheStats();
        };
    };
};

window.saveUserbotDefaults = function() {
    window.API.ajax({
        method: 'POST',
        url: '/api/config',
        data: {
            telegram_api_id: getUserbotField('userbot-api-id'),
            telegram_api_hash: getUserbotField('userbot-api-hash'),
            telegram_phone: getUserbotField('userbot-phone')
        },
        success: function() {
            // Re-enmascarar
            _userbotVisible = false;
            ['userbot-api-id', 'userbot-api-hash', 'userbot-phone'].forEach(function(id) {
                var el = document.getElementById(id);
                if (el && el.getAttribute('data-real')) el.value = maskValue(el.getAttribute('data-real'));
            });
        }
    });
};

window.testUserSessions = function(tgUserId) {
    var tSpan = document.getElementById('test-t-' + tgUserId);
    var pSpan = document.getElementById('test-p-' + tgUserId);

    window.API.ajax({
        url: '/api/telegram/users',
        success: function(data) {
            var users = data.users || [];
            var user = null;
            for (var i = 0; i < users.length; i++) {
                if (users[i].tg_user_id == tgUserId) { user = users[i]; break; }
            }
            if (!user) {
                if (tSpan) { tSpan.style.display = 'inline'; tSpan.textContent = 'T:\u274C'; }
                if (pSpan) { pSpan.style.display = 'inline'; pSpan.textContent = 'P:\u274C'; }
                return;
            }
            var sessions = user.sessions || [];
            var tSess = null, pSess = null;
            for (var i = 0; i < sessions.length; i++) {
                if (sessions[i].client_type === 'telethon') tSess = sessions[i];
                if (sessions[i].client_type === 'pyrogram') pSess = sessions[i];
            }

            if (tSpan) { tSpan.style.display = 'inline'; tSpan.textContent = 'T:\u23F3'; }
            if (pSpan) { pSpan.style.display = 'inline'; pSpan.textContent = 'P:\u23F3'; }

            var tDone = false, pDone = false;

            function checkDone() {
                if (tDone && pDone) {
                    if (!tSess && tSpan) tSpan.textContent = 'T:\u2B1C';
                    if (!pSess && pSpan) pSpan.textContent = 'P:\u2B1C';
                }
            }

            if (tSess) {
                (function(s) {
                    window.API.ajax({
                        method: 'POST', url: '/api/userbot/test/' + s.id,
                        success: function(res) {
                            if (tSpan) tSpan.textContent = 'T:' + (res && res.success ? '\u2705' : '\u274C');
                            tDone = true;
                            checkDone();
                        },
                        error: function() {
                            if (tSpan) tSpan.textContent = 'T:\u274C';
                            tDone = true;
                            checkDone();
                        }
                    });
                })(tSess);
            } else {
                tDone = true;
                checkDone();
            }

            if (pSess) {
                (function(s) {
                    window.API.ajax({
                        method: 'POST', url: '/api/userbot/test/' + s.id,
                        success: function(res) {
                            if (pSpan) pSpan.textContent = 'P:' + (res && res.success ? '\u2705' : '\u274C');
                            pDone = true;
                            checkDone();
                        },
                        error: function() {
                            if (pSpan) pSpan.textContent = 'P:\u274C';
                            pDone = true;
                            checkDone();
                        }
                    });
                })(pSess);
            } else {
                pDone = true;
                checkDone();
            }
        },
        error: function() {
            if (tSpan) { tSpan.style.display = 'inline'; tSpan.textContent = 'T:\u274C'; }
            if (pSpan) { pSpan.style.display = 'inline'; pSpan.textContent = 'P:\u274C'; }
        }
    });
};

window.editUserSessions = function(tgUserId) {
    window.API.ajax({
        url: '/api/userbot/sessions',
        success: function(data) {
            var sessions = data.sessions || [];
            var userSessions = [];
            for (var i = 0; i < sessions.length; i++) {
                if (sessions[i].tg_user_id === tgUserId) {
                    userSessions.push(sessions[i]);
                }
            }
            if (userSessions.length === 0) { alert('No hay sesiones para este usuario.'); return; }
            var msg = userSessions.map(function(s) {
                return s.id + ' - ' + s.name + ' (' + s.client_type + ')';
            }).join('\n');
            var sessId = prompt('Introduce el ID de la sesion a editar:\n' + msg);
            if (sessId) editSession(parseInt(sessId));
        }
    });
};

window.deleteTelegramUser = function(tgUserId) {
    if (!confirm('\u00BFEliminar este usuario y todas sus sesiones?')) return;
    window.API.ajax({
        method: 'DELETE',
        url: '/api/telegram/users/' + tgUserId,
        success: function() { loadUserbotSessions(); }
    });
};

window.testSingleSession = function(id) {
    var container = document.getElementById('userbot-sessions-list');
    if (!container) return;
    var oldDiv = container.querySelector('.test-results');
    if (oldDiv) oldDiv.remove();
    var div = document.createElement('div');
    div.className = 'test-results';
    div.style.cssText = 'padding:8px 12px;font-size:0.8rem;border-top:1px solid var(--border);margin-top:8px;';
    div.innerHTML = '\uD83D\uDD1E Probando...';
    container.appendChild(div);
    window.API.ajax({
        method: 'POST', url: '/api/userbot/test/' + id,
        success: function(res) {
            div.innerHTML = (res && res.success ? '\u2705 ' : '\u274C ') + (res && res.message ? res.message : (res && res.error ? res.error : 'Error'));
        },
        error: function() { div.innerHTML = '\u274C Error de red'; }
    });
};

window.saveUserbot = function() { /* deprecated */ };

window.editSession = function(id) {
    window.API.ajax({
        url: '/api/userbot/sessions',
        success: function(data) {
            var sessions = data.sessions || [];
            var sess = null;
            for (var i = 0; i < sessions.length; i++) {
                if (sessions[i].id === id) { sess = sessions[i]; break; }
            }
            if (!sess) return;
            var alias = sess.name;
            if (alias.startsWith('T_') || alias.startsWith('P_')) alias = alias.substring(2);
            var newAlias = prompt('Editar alias de la sesion:', alias);
            if (newAlias && newAlias.trim()) {
                window.API.ajax({
                    method: 'PUT',
                    url: '/api/userbot/sessions/' + id,
                    data: { name: newAlias.trim() },
                    success: function(res) {
                        if (res && !res.success) { alert('Error: ' + res.error); return; }
                        loadUserbotConfig();
                    }
                });
            }
        }
    });
};

window.deleteSession = function(id) {
    if (!confirm('\u00BFEliminar esta sesi\u00f3n de Telegram?')) return;
    window.API.ajax({
        method: 'DELETE',
        url: '/api/userbot/sessions/' + id,
        success: function() { loadUserbotConfig(); loadUserbotSessions(); }
    });
};

// --- Generate Dual Session (Telethon + Pyrofork, dos codigos SMS independientes) ---
window.openSessionGenerator = function() {
    var _state = { password: '', telethonDone: false };

    var subModal = document.createElement('div');
    subModal.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(9,9,11,0.9);z-index:999999;display:flex;align-items:center;justify-content:center;';
    var subDialog = document.createElement('div');
    subDialog.style.cssText = 'background:rgba(24,24,27,0.98);border:1px solid rgba(168,85,247,0.4);border-radius:12px;width:90%;max-width:450px;padding:20px;box-shadow:0 25px 50px -12px rgba(0,0,0,0.8);display:flex;flex-direction:column;';

    var dName = window._userbotHostname || 'unknown';
    var apiId = getUserbotField('userbot-api-id') || '';
    var apiHash = getUserbotField('userbot-api-hash') || '';
    var phone = getUserbotField('userbot-phone') || '';

    var h = '<div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(63,63,70,0.4);padding-bottom:10px;">';
    h += '<h3 style="margin:0;font-size:1.1rem;color:#f4f4f5;">Nueva Sesion Dual</h3>';
    h += '<button id="gen-modal-close" style="background:none;border:none;color:#a1a1aa;font-size:1.2rem;cursor:pointer;">X</button></div>';
    h += '<div style="display:flex;flex-direction:column;gap:8px;padding-top:8px;">';
    h += '<div style="font-size:0.75rem;color:#fbbf24;background:rgba(251,191,36,0.08);padding:6px 8px;border-radius:4px;">Se generaran ambas sesiones (Telethon + Pyrofork) de forma independiente. Recibiras DOS codigos SMS.</div>';
    h += '<div><label style="font-size:0.75rem;color:#a1a1aa;">Nombre base</label><input type="text" id="gen-name" value="' + dName + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>';
    h += '<div style="display:flex;gap:8px;"><div style="flex:1;"><label style="font-size:0.75rem;color:#a1a1aa;">API ID</label><input type="text" id="gen-api-id" value="' + apiId + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>';
    h += '<div style="flex:2;"><label style="font-size:0.75rem;color:#a1a1aa;">API Hash</label><input type="text" id="gen-api-hash" value="' + apiHash + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div></div>';
    h += '<div><label style="font-size:0.75rem;color:#a1a1aa;">Telefono</label><input type="text" id="gen-phone" value="' + phone + '" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>';

    // --- Paso 1: Telethon ---
    h += '<div style="border:1px solid rgba(63,63,70,0.5);border-radius:8px;padding:10px;margin-top:4px;">';
    h += '<div style="font-size:0.8rem;font-weight:700;color:#a855f7;margin-bottom:6px;">1. Sesion Telethon</div>';
    h += '<button id="gen-send-code-btn" style="background:#a855f7;border:none;border-radius:6px;padding:8px;color:white;font-weight:700;font-size:0.8rem;cursor:pointer;">Enviar Codigo SMS</button>';
    h += '<div id="gen-verification" style="display:none;flex-direction:column;gap:8px;margin-top:8px;">';
    h += '<div><label style="font-size:0.75rem;color:#a1a1aa;">Codigo SMS (Telethon)</label><input type="text" id="gen-code" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>';
    h += '<div id="gen-2fa" style="display:none;"><label style="font-size:0.75rem;color:#a1a1aa;">2FA</label><input type="password" id="gen-password" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>';
    h += '<button id="gen-confirm-btn" style="background:#22c55e;border:none;border-radius:6px;padding:8px;color:white;font-weight:700;font-size:0.8rem;cursor:pointer;">Confirmar Telethon</button>';
    h += '</div></div>';

    // --- Paso 2: Pyrofork ---
    h += '<div id="gen-pyro-step" style="display:none;border:1px solid rgba(63,63,70,0.5);border-radius:8px;padding:10px;margin-top:4px;">';
    h += '<div style="font-size:0.8rem;font-weight:700;color:#06b6d4;margin-bottom:6px;">2. Sesion Pyrofork</div>';
    h += '<button id="gen-pyro-send-btn" style="background:#06b6d4;border:none;border-radius:6px;padding:8px;color:white;font-weight:700;font-size:0.8rem;cursor:pointer;">Enviar Codigo SMS</button>';
    h += '<div id="gen-pyro-verification" style="display:none;flex-direction:column;gap:8px;margin-top:8px;">';
    h += '<div><label style="font-size:0.75rem;color:#a1a1aa;">Codigo SMS (Pyrofork)</label><input type="text" id="gen-pyro-code" style="width:100%;background:#09090b;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>';
    h += '<button id="gen-pyro-confirm-btn" style="background:#22c55e;border:none;border-radius:6px;padding:8px;color:white;font-weight:700;font-size:0.8rem;cursor:pointer;">Confirmar Pyrofork</button>';
    h += '</div></div>';

    h += '<div id="gen-status" style="font-size:0.75rem;"></div></div>';
    subDialog.innerHTML = h;
    subModal.appendChild(subDialog);
    document.body.appendChild(subModal);

    setTimeout(function() { subModal.style.opacity = '1'; subDialog.style.transform = 'scale(1)'; }, 10);
    setTimeout(function() { var el = document.getElementById('gen-name'); if (el) el.select(); }, 150);

    var closeGen = function() {
        subModal.style.opacity = '0'; subDialog.style.transform = 'scale(0.95)';
        setTimeout(function() { subModal.remove(); }, 200);
    };
    document.getElementById('gen-modal-close').onclick = closeGen;
    subModal.addEventListener('click', function(e) { if (e.target === subModal) closeGen(); });

    subDialog.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') { closeGen(); return; }
        if (e.key === 'Enter') {
            var sendBtn = document.getElementById('gen-send-code-btn');
            var confirmBtn = document.getElementById('gen-confirm-btn');
            var pyroSend = document.getElementById('gen-pyro-send-btn');
            var pyroConfirm = document.getElementById('gen-pyro-confirm-btn');
            if (pyroConfirm && pyroConfirm.style.display !== 'none') { pyroConfirm.click(); }
            else if (pyroSend && pyroSend.style.display !== 'none') { pyroSend.click(); }
            else if (sendBtn && sendBtn.style.display !== 'none') { sendBtn.click(); }
            else if (confirmBtn && confirmBtn.style.display !== 'none') { confirmBtn.click(); }
        }
    });

    // Paso 1: Enviar codigo SMS (Telethon)
    document.getElementById('gen-send-code-btn').onclick = function() {
        var phone = document.getElementById('gen-phone').value.trim();
        var apiId = document.getElementById('gen-api-id').value.trim();
        var apiHash = document.getElementById('gen-api-hash').value.trim();
        var status = document.getElementById('gen-status');
        if (!phone) { alert('Introduce el telefono.'); return; }
        if (!apiId || !apiHash) { alert('API ID y API Hash requeridos.'); return; }
        status.innerHTML = '\u27A1 Enviando codigo a tu telefono...';
        document.getElementById('gen-send-code-btn').disabled = true;
        window.API.ajax({
            method: 'POST', url: '/api/userbot/auth/send_code',
            data: { phone: phone, client_type: 'telethon', api_id: apiId, api_hash: apiHash },
            success: function(res) {
                document.getElementById('gen-send-code-btn').disabled = false;
                if (res && res.success) {
                    _state.phoneCodeHashTelethon = res.phone_code_hash || '';
                    status.innerHTML = '\u2705 Codigo enviado. Revisa Telegram e introducelo abajo.';
                    document.getElementById('gen-verification').style.display = 'flex';
                    document.getElementById('gen-send-code-btn').style.display = 'none';
                    document.getElementById('gen-code').focus();
                } else {
                    status.innerHTML = '\u274C Error: ' + (res ? res.error : 'Error');
                }
            },
            error: function() { document.getElementById('gen-send-code-btn').disabled = false; status.innerHTML = '\u274C Error de red'; }
        });
    };

    // Paso 2: Confirmar codigo Telethon
    document.getElementById('gen-confirm-btn').onclick = function() {
        var name = document.getElementById('gen-name').value.trim() || dName;
        var phone = document.getElementById('gen-phone').value.trim();
        var apiId = document.getElementById('gen-api-id').value.trim();
        var apiHash = document.getElementById('gen-api-hash').value.trim();
        var code = document.getElementById('gen-code').value.trim();
        var password = document.getElementById('gen-password').value.trim();
        var status = document.getElementById('gen-status');
        if (!code) { alert('Introduce el codigo.'); return; }

        status.innerHTML = '\u23F3 Generando sesion Telethon...';
        document.getElementById('gen-confirm-btn').disabled = true;

        window.API.ajax({
            method: 'POST', url: '/api/userbot/auth/confirm_code',
            data: {
                name: name, client_type: 'telethon', phone: phone,
                api_id: apiId, api_hash: apiHash,
                code: code, password: password || null,
                phone_code_hash: _state.phoneCodeHashTelethon || ''
            },
            success: function(res) {
                if (res && res.success) {
                    if (password) _state.password = password;
                    status.innerHTML = '\u2705 Telethon generada. Ahora genera Pyrofork (Paso 2).';
                    document.getElementById('gen-confirm-btn').disabled = false;
                    _state.telethonDone = true;
                    document.getElementById('gen-pyro-step').style.display = 'block';
                    document.getElementById('gen-pyro-send-btn').focus();
                } else if (res && res.needs_2fa) {
                    if (password) _state.password = password;
                    status.innerHTML = '\uD83D\uDD10 Se requiere 2FA - introduce la contrasena';
                    document.getElementById('gen-2fa').style.display = 'block';
                    document.getElementById('gen-password').focus();
                    document.getElementById('gen-confirm-btn').disabled = false;
                } else {
                    status.innerHTML = '\u274C Error Telethon: ' + (res ? res.error : 'Error');
                    document.getElementById('gen-confirm-btn').disabled = false;
                }
            },
            error: function() { status.innerHTML = '\u274C Error de red'; document.getElementById('gen-confirm-btn').disabled = false; }
        });
    };

    // Paso 3: Enviar codigo SMS (Pyrofork) — nuevo SMS independiente
    document.getElementById('gen-pyro-send-btn').onclick = function() {
        var phone = document.getElementById('gen-phone').value.trim();
        var apiId = document.getElementById('gen-api-id').value.trim();
        var apiHash = document.getElementById('gen-api-hash').value.trim();
        var status = document.getElementById('gen-status');
        status.innerHTML = '\u27A1 Enviando codigo a tu telefono (Pyrofork)...';
        document.getElementById('gen-pyro-send-btn').disabled = true;
        window.API.ajax({
            method: 'POST', url: '/api/userbot/auth/send_code',
            data: { phone: phone, client_type: 'pyrogram', api_id: apiId, api_hash: apiHash },
            success: function(res) {
                document.getElementById('gen-pyro-send-btn').disabled = false;
                if (res && res.success) {
                    _state.phoneCodeHashPyrogram = res.phone_code_hash || '';
                    status.innerHTML = '\u2705 Codigo enviado (2do SMS). Revisa Telegram e introducelo.';
                    document.getElementById('gen-pyro-verification').style.display = 'flex';
                    document.getElementById('gen-pyro-send-btn').style.display = 'none';
                    document.getElementById('gen-pyro-code').focus();
                } else {
                    status.innerHTML = '\u274C Error: ' + (res ? res.error : 'Error');
                }
            },
            error: function() { document.getElementById('gen-pyro-send-btn').disabled = false; status.innerHTML = '\u274C Error de red'; }
        });
    };

    // Paso 4: Confirmar codigo Pyrofork (reutiliza password 2FA de memoria si fue necesaria)
    document.getElementById('gen-pyro-confirm-btn').onclick = function() {
        var name = document.getElementById('gen-name').value.trim() || dName;
        var phone = document.getElementById('gen-phone').value.trim();
        var apiId = document.getElementById('gen-api-id').value.trim();
        var apiHash = document.getElementById('gen-api-hash').value.trim();
        var code = document.getElementById('gen-pyro-code').value.trim();
        var status = document.getElementById('gen-status');
        if (!code) { alert('Introduce el codigo.'); return; }

        status.innerHTML = '\u23F3 Generando sesion Pyrofork...';
        document.getElementById('gen-pyro-confirm-btn').disabled = true;

        function doConfirm(password) {
            window.API.ajax({
                method: 'POST', url: '/api/userbot/auth/confirm_code',
                data: {
                    name: name, client_type: 'pyrogram', phone: phone,
                    api_id: apiId, api_hash: apiHash,
                    code: code, password: password || null,
                    phone_code_hash: _state.phoneCodeHashPyrogram || ''
                },
                success: function(res) {
                    if (res && res.success) {
                        status.innerHTML = '\u2705\u2705 Telethon + Pyrofork generadas correctamente';
                        document.getElementById('gen-pyro-confirm-btn').disabled = false;
                        setTimeout(function() { closeGen(); loadUserbotConfig(); loadUserbotSessions(); }, 2000);
                    } else if (res && res.needs_2fa) {
                        if (_state.password) {
                            // Reutilizar la password 2FA ya capturada en el paso de Telethon
                            doConfirm(_state.password);
                        } else {
                            var pw = prompt('Se requiere contrasena 2FA:');
                            if (pw) { _state.password = pw; doConfirm(pw); }
                            else { status.innerHTML = '\u274C 2FA requerida'; document.getElementById('gen-pyro-confirm-btn').disabled = false; }
                        }
                    } else {
                        status.innerHTML = '\u274C Error Pyrofork: ' + (res ? res.error : 'Error');
                        document.getElementById('gen-pyro-confirm-btn').disabled = false;
                    }
                },
                error: function() { status.innerHTML = '\u274C Error de red'; document.getElementById('gen-pyro-confirm-btn').disabled = false; }
            });
        }

        doConfirm(_state.password || null);
    };
};

function loadSettings() {
    loadUserbotConfig();
    loadUserbotSessions();
    window.loadEnrichConfig();
    window.API.ajax({
        url: '/api/auth/me',
        success: function(session) {
            var nameEl = document.getElementById('profile-display-name');
            if (nameEl) nameEl.value = session.username || '';
            // Actualizar estado de cuenta Google asociada (si existe la sección)
            setTimeout(function() { window.updateGoogleAccountBox(); }, 200);
            // Cargar config guardada
            window.API.ajax({
                url: '/api/config',
                success: function(config) {
                    // Poblar currentUser para initSettingsModalContent
                    window.Catalog.currentUser = {
                        display_name: config.display_name || session.username || '',
                        username: session.username || '',
                        role: session.role || '',
                        is_admin: (session.role === 'admin'),
                        avatar: config.avatar || '',
                        avatar_url: config.avatar_url || '',
                        color: config.color || '#e11d48',
                        category_preferences: config.category_preferences || {}
                    };
                    // Re-renderizar formulario de perfil si el modal est\u00E1 visible
                    if (!document.getElementById('settings-modal').classList.contains('hidden')) {
                        if (window.UI) window.UI.initSettingsModalContent();
                    }
                    if (config.display_name) {
                        if (nameEl) nameEl.value = config.display_name;
                        var sideName = document.getElementById('side-profile-name');
                        if (sideName) sideName.textContent = config.display_name;
                    }
                    if (config.avatar) {
                        document.getElementById('side-avatar').textContent = config.avatar;
                        syncNavbarAvatar();
                    }
                    if (config.avatar_url) {
                        document.getElementById('side-avatar').innerHTML = '<img src="' + config.avatar_url + '" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">';
                        syncNavbarAvatar();
                    }
                    if (config.color) {
                        document.querySelector('#side-avatar').style.background = config.color;
                        syncNavbarAvatar();
                    }
                }
            });
        }
    });
}

var _pluginListCache = [];

var PLUGIN_SECTIONS = {
    'source': 'Or\u00EDgenes',
    'grid-decorator': 'Cat\u00E1logo',
    'item-decorator': 'Cat\u00E1logo',
    'player': 'Hero Page',
    'heropage-action': 'Hero Page'
};

function loadPluginsList() {
    if (window._tghirayiSaving) return;
    var container = document.getElementById('plugins-list-container');
    if (!container) return;
    exitPluginFullScreen();
    window.API.ajax({
        url: '/api/plugins',
        success: function(data) {
            var plugins = data.plugins || [];
            // Cargar orden guardado y ordenar
            window.API.ajax({
                url: '/api/plugins/order',
                success: function(orderData) {
                    var savedOrder = orderData.order || [];
                    if (savedOrder.length > 0) {
                        var ordered = [];
                        var unordered = [];
                        for (var i = 0; i < plugins.length; i++) {
                            var idx = savedOrder.indexOf(plugins[i].name);
                            if (idx >= 0) {
                                ordered[idx] = plugins[i];
                            } else {
                                unordered.push(plugins[i]);
                            }
                        }
                        plugins = ordered.filter(Boolean).concat(unordered);
                    }
                    _pluginListCache = plugins;
                    renderPluginList(container, plugins);
                },
                error: function() {
                    _pluginListCache = plugins;
                    renderPluginList(container, plugins);
                }
            });
        },
        error: function() {
            container.innerHTML = '<p style="color:var(--text-secondary);">Error cargando plugins</p>';
        }
    });
}

function renderPluginList(container, plugins) {
    // Agrupar por secci\u00F3n
    var sections = {};
    for (var i = 0; i < plugins.length; i++) {
        var p = plugins[i];
        var section = PLUGIN_SECTIONS[p.type] || p.type;
        if (!sections[section]) sections[section] = [];
        sections[section].push(p);
    }

    var html = '';
    var sectionKeys = Object.keys(sections);
    for (var s = 0; s < sectionKeys.length; s++) {
        var secName = sectionKeys[s];
        var secPlugins = sections[secName];
        html += '<div class="plugin-section-title">' + secName + '</div>';

        // Check if this section has player plugins
        var playerPlugins = secPlugins.filter(function(p) { return p.type === 'player'; });
        var hasPlayerGroup = playerPlugins.length > 0 && secName === 'Hero Page';

        var playerEntryRendered = false;
        for (var i = 0; i < secPlugins.length; i++) {
            var p = secPlugins[i];

            // Player type: render as individual items (draggable, configurable)
            if (p.type === 'player') {
                var isOn = p.enabled;
                html += '<div class="plugin-item" draggable="true" data-name="' + p.name + '">' +
                    '<span class="plugin-drag-handle">\u2630\u2630</span>' +
                    pluginIconHtml(p, 20) +
                    '<div class="plugin-item-name">' + (p.displayName || p.name) + '</div>' +
                    '<div class="plugin-item-status">' +
                    '<button class="plugin-info-btn" onclick="event.stopPropagation();showPluginInfo(\'' + p.name + '\')" title="Informaci\u00F3n">\u2139\uFE0F</button>' +
                    '<button class="plugin-config-btn" onclick="event.stopPropagation();showPluginInfo(\'' + p.name + '\')" title="Configurar">' +
                    '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor;"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>' +
                    '</button>' +
                    '<div class="plugin-toggle" onclick="event.stopPropagation();togglePlugin(\'' + p.name + '\', this)">' +
                    '<span class="plugin-toggle-slider' + (isOn ? ' on' : '') + '"></span>' +
                    '</div></div></div>';
                continue;
            }

            var isOn = p.enabled;
            var hasError = !!p.load_error;
            html += '<div class="plugin-item" draggable="true" data-name="' + p.name + '">' +
                '<span class="plugin-drag-handle">\u2630\u2630</span>' +
                pluginIconHtml(p, 20) +
                '<div class="plugin-item-name">' + (p.displayName || p.name) + '</div>' +
                '<div class="plugin-item-status">' +
                '<button class="plugin-info-btn" onclick="event.stopPropagation();showPluginInfo(\'' + p.name + '\')" title="Informaci\u00F3n">\u2139\uFE0F</button>' +
                (hasError ? '<span style="color:var(--accent);font-size:0.75rem;">Error</span>' : '') +
                '<button class="plugin-config-btn" onclick="event.stopPropagation();showPluginConfig(\'' + p.name + '\')" title="Configurar">' +
                '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor;"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>' +
                '</button>' +
                '<div class="plugin-toggle" onclick="event.stopPropagation();togglePlugin(\'' + p.name + '\', this)">' +
                '<span class="plugin-toggle-slider' + (isOn ? ' on' : '') + '"></span>' +
                '</div></div></div>';
        }
    }
    container.innerHTML = html;
}

function getPluginByName(name) {
    for (var i = 0; i < _pluginListCache.length; i++) {
        if (_pluginListCache[i].name === name) return _pluginListCache[i];
    }
    return null;
}

// HTML de fallback de un icono: emoji del plugin (iconEmoji) o icono por defecto del core.
function pluginIconFallbackHtml(emoji, size) {
    size = size || 20;
    if (emoji) {
        return '<span style="width:' + size + 'px;height:' + size + 'px;line-height:' + size + 'px;text-align:center;font-size:' + Math.round(size * 0.7) + 'px;display:inline-block;flex-shrink:0;">' + emoji + '</span>';
    }
    return '<img src="/static/plugin_default_icon.png" style="width:' + size + 'px;height:' + size + 'px;border-radius:4px;object-fit:cover;vertical-align:middle;flex-shrink:0;">';
}

// Reemplaza un <img> de icono por su fallback (emoji o default) cuando la imagen no carga.
window.pluginIconFallback = function(img, emoji, size) {
    img.outerHTML = pluginIconFallbackHtml(emoji, size);
};

// Icono de plugin: path (imagen), emoji, o fallback (iconEmoji o icono por defecto del core).
function pluginIconHtml(p, size) {
    size = size || 20;
    var icon = p && p.icon;
    var fallbackEmoji = p && p.iconEmoji;
    if (icon && icon.indexOf('.') !== -1) {
        var rel = (icon.indexOf('/') === 0 || icon.indexOf('http') === 0) ? icon : ('/plugin-static/' + p.name + '/' + icon.replace(/^static\//, ''));
        return '<img src="' + rel + '" style="width:' + size + 'px;height:' + size + 'px;border-radius:4px;object-fit:cover;vertical-align:middle;flex-shrink:0;" onerror="pluginIconFallback(this,\'' + (fallbackEmoji || '') + '\',' + size + ')">';
    }
    if (icon && icon.length <= 4) {
        return pluginIconFallbackHtml(icon, size);
    }
    return pluginIconFallbackHtml(fallbackEmoji, size);
}

// --- Plugin Icons Tray (panel izquierdo) ---

// Estado runtime del plugin: registry (JS) o _pluginListCache (plugin.json).
function isPluginEnabled(name) {
    if (window.pluginSystem) {
        var reg = window.pluginSystem.getPlugin(name);
        if (reg && typeof reg.enabled === 'boolean') return reg.enabled;
    }
    for (var i = 0; i < _pluginListCache.length; i++) {
        if (_pluginListCache[i].name === name) return !!_pluginListCache[i].enabled;
    }
    return false;
}

// Icono del botón de tray: path (imagen), emoji, o emoji del plugin. Fallback al emoji si la imagen no carga.
function trayIconHtml(icon, pluginName, fallbackEmoji) {
    if (icon && icon.indexOf('.') !== -1) {
        var rel = (icon.indexOf('/') === 0 || icon.indexOf('http') === 0) ? icon : ('/plugin-static/' + pluginName + '/' + icon.replace(/^static\//, ''));
        return '<img src="' + rel + '" style="width:16px;height:16px;object-fit:cover;" onerror="pluginIconFallback(this,\'' + (fallbackEmoji || '') + '\',16)">';
    }
    return (icon || fallbackEmoji || '\u2699\ufe0f');
}

// Renderiza los botones de tray de los plugins que definan `tray` en plugin.json.
function renderPluginTray() {
    var tray = document.getElementById('plugin-tray-icons');
    if (!tray) return;
    var html = '';
    for (var i = 0; i < _pluginListCache.length; i++) {
        var p = _pluginListCache[i];
        if (!p.tray || !p.tray.length) continue;
        for (var j = 0; j < p.tray.length; j++) {
            var btn = p.tray[j];
            var active = isPluginEnabled(p.name) && p.tray[j].action === 'toggle-plugin';
            html += '<button class="plugin-tray-btn' + (active ? ' tray-active' : '') + '" title="' + (btn.label || p.displayName || p.name) + '" ' +
                (btn.color ? 'style="color:' + btn.color + ';"' : '') +
                ' onclick="handleTrayAction(\'' + p.name + '\',' + j + ', this)">' +
                trayIconHtml(btn.icon || p.icon, p.name, btn.iconEmoji || p.iconEmoji) + '</button>';
        }
    }
    tray.innerHTML = html;
}

// AcciÃƒÂ³n al pulsar un botÃƒÂ³n de tray.
window.handleTrayAction = function(pluginName, btnIndex, el) {
    var p = null;
    for (var i = 0; i < _pluginListCache.length; i++) {
        if (_pluginListCache[i].name === pluginName) { p = _pluginListCache[i]; break; }
    }
    if (!p || !p.tray || !p.tray[btnIndex]) return;
    var btn = p.tray[btnIndex];
    if (btn.action === 'toggle-plugin') {
        togglePlugin(pluginName, el);
        return;
    }
    if (btn.action === 'config') {
        if (typeof showPluginConfig === 'function') showPluginConfig(pluginName);
        return;
    }
    if (btn.action === 'category' && btn.category) {
        if (window.Catalog) window.Catalog.load(btn.category);
        return;
    }
    if (btn.onTrayClick && typeof btn.onTrayClick === 'function') {
        btn.onTrayClick(btn);
    }
};

// --- Contenidos (nivel 1 · Acceso del admin por perfil) ---
var _contentsProfile = 0;
var _contentsTree = [];

function loadContentsTrees() {
    window.API.ajax({
        url: '/api/admin/profiles',
        success: function(res) {
            var sel = document.getElementById('contents-profile-select');
            if (!sel) return;
            var html = '';
            for (var i = 0; i < (res.profiles || []).length; i++) {
                var p = res.profiles[i];
                if (p.is_admin) continue;
                html += '<option value="' + p.id + '">' + p.name + '</option>';
            }
            sel.innerHTML = html;
            _contentsProfile = sel.value ? parseInt(sel.value, 10) : 0;
            loadContentAccessTree();
        }
    });
}

function loadContentAccessTree() {
    var sel = document.getElementById('contents-profile-select');
    if (sel) _contentsProfile = sel.value ? parseInt(sel.value, 10) : 0;
    var container = document.getElementById('contents-access-tree');
    if (!container) return;
    if (!_contentsProfile) {
        container.innerHTML = '<div style="padding:8px;font-size:0.8rem;color:var(--text-secondary);">No hay perfiles de usuario</div>';
        return;
    }
    window.API.ajax({ url: '/api/catalog/tree', success: function(data) {
        _contentsTree = data.tree || [];
        window.API.ajax({ url: '/api/content/access?profile=' + _contentsProfile, success: function(filt) {
            renderContentAccessTree(container, filt);
        } });
    } });
}

function renderContentAccessTree(container, filt) {
    var tree = _contentsTree;
    if (tree.length === 0) {
        container.innerHTML = '<div style="padding:8px;font-size:0.8rem;color:var(--text-secondary);">Sin categor\u00EDas</div>';
        return;
    }
    filt.plugins = filt.plugins || {};
    filt.categories = filt.categories || {};
    filt.subcategories = filt.subcategories || {};
    var html = '';
    for (var s = 0; s < tree.length; s++) {
        var src = tree[s];
        var plugState = pluginNodeState(src, filt);
        html += '<div class="tree-source">' +
            '<label class="tree-item tree-source-label">' +
            '<input type="checkbox" ' + (plugState.checked ? 'checked' : '') + (plugState.indet ? ' data-indet="1"' : '') + ' onchange="toggleAccessPlugin(\'' + src.source + '\', this)"> ' +
            src.source + '</label></div>';
        for (var c = 0; c < src.categories.length; c++) {
            var cat = src.categories[c];
            var catState = categoryNodeState(cat, filt);
            html += '<div style="padding-left:16px;">' +
                '<label class="tree-item">' +
                '<input type="checkbox" ' + (catState.checked ? 'checked' : '') + (catState.indet ? ' data-indet="1"' : '') + ' onchange="toggleAccessCategory(\'' + cat.name + '\', this)"> ' +
                cat.name + '</label></div>';
            for (var u = 0; u < cat.subcategories.length; u++) {
                var sub = cat.subcategories[u];
                var subKey = cat.name + '||' + sub;
                var subChecked = filt.subcategories[subKey] !== false;
                html += '<div style="padding-left:32px;">' +
                    '<label class="tree-item" style="font-size:0.75rem;">' +
                    '<input type="checkbox" ' + (subChecked ? 'checked' : '') + ' onchange="toggleAccessSubcategory(\'' + subKey + '\', this)"> ' +
                    sub + '</label></div>';
            }
        }
    }
    container.innerHTML = html;
    var boxes = container.querySelectorAll('input[type="checkbox"]');
    for (var b = 0; b < boxes.length; b++) {
        if (boxes[b].getAttribute('data-indet') === '1') boxes[b].indeterminate = true;
    }
}

function pluginNodeState(src, filt) {
    var cats = src.categories || [];
    if (filt.plugins[src.source] === true) return { checked: true, indet: false };
    if (filt.plugins[src.source] === false) return { checked: false, indet: false };
    if (cats.length === 0) return { checked: true, indet: false };
    var hasChecked = false, hasUnchecked = false;
    for (var i = 0; i < cats.length; i++) {
        if (filt.categories[cats[i].name] === false) hasUnchecked = true; else hasChecked = true;
    }
    if (hasChecked && hasUnchecked) return { checked: false, indet: true };
    return { checked: hasChecked, indet: false };
}

function categoryNodeState(cat, filt) {
    if (filt.categories[cat.name] === false) return { checked: false, indet: false };
    if (filt.categories[cat.name] === true) return { checked: true, indet: false };
    var subs = cat.subcategories || [];
    if (subs.length === 0) return { checked: true, indet: false };
    var hasChecked = false, hasUnchecked = false;
    for (var i = 0; i < subs.length; i++) {
        if (filt.subcategories[cat.name + '||' + subs[i]] === false) hasUnchecked = true; else hasChecked = true;
    }
    if (hasChecked && hasUnchecked) return { checked: false, indet: true };
    return { checked: hasChecked, indet: false };
}

function saveAccess(handler) {
    window.API.ajax({ url: '/api/content/access?profile=' + _contentsProfile, success: function(filt) {
        filt.plugins = filt.plugins || {};
        filt.categories = filt.categories || {};
        filt.subcategories = filt.subcategories || {};
        handler(filt);
        window.API.ajax({
            method: 'POST',
            url: '/api/content/access',
            data: { profile: _contentsProfile, data: filt },
            success: function() {
                loadContentAccessTree();
                var st = document.getElementById('contents-status');
                if (st) { st.textContent = 'Guardado'; setTimeout(function(){ st.textContent = ''; }, 1500); }
            }
        });
    } });
}

window.toggleAccessPlugin = function(source, cb) {
    saveAccess(function(filt) {
        filt.plugins[source] = cb.checked;
        for (var s = 0; s < _contentsTree.length; s++) {
            if (_contentsTree[s].source !== source) continue;
            for (var c = 0; c < _contentsTree[s].categories.length; c++) {
                var cat = _contentsTree[s].categories[c];
                filt.categories[cat.name] = cb.checked;
                for (var u = 0; u < cat.subcategories.length; u++) {
                    filt.subcategories[cat.name + '||' + cat.subcategories[u]] = cb.checked;
                }
            }
            break;
        }
    });
};

window.toggleAccessCategory = function(catName, cb) {
    saveAccess(function(filt) {
        filt.categories[catName] = cb.checked;
        for (var s = 0; s < _contentsTree.length; s++) {
            for (var c = 0; c < _contentsTree[s].categories.length; c++) {
                var cat = _contentsTree[s].categories[c];
                if (cat.name !== catName) continue;
                for (var u = 0; u < cat.subcategories.length; u++) {
                    filt.subcategories[cat.name + '||' + cat.subcategories[u]] = cb.checked;
                }
            }
        }
    });
};

window.toggleAccessSubcategory = function(key, cb) {
    saveAccess(function(filt) {
        filt.subcategories[key] = cb.checked;
        if (cb.checked) {
            filt.categories[key.split('||')[0]] = true;
        }
    });
};
window._pluginConfigOpen = false;

function pluginConfigHeader(plugin) {
    var title = (plugin && (plugin.displayName || plugin.name)) || 'Plugin';
    return '<div style="display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--border-color);background:var(--bg-surface,#18181b);position:sticky;top:0;z-index:10;margin:-10px -10px 12px -10px;border-radius:8px 8px 0 0;">' +
        pluginIconHtml(plugin, 25) +
        '<span style="font-weight:700;font-size:0.95rem;flex:1;">' + title + '</span>' +
        '<button onclick="loadPluginsList()" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:0.82rem;font-family:Outfit,sans-serif;padding:4px 8px;">\u2190 Volver</button>' +
        '<button onclick="toggleSettingsModal()" title="Cerrar" style="background:none;border:none;color:#a1a1aa;cursor:pointer;font-size:1.3rem;line-height:1;padding:0 4px;">&times;</button>' +
        '</div>';
}

function enterPluginFullScreen() {
    window._pluginConfigOpen = true;
    var tabs = document.getElementById('settings-tabs-container');
    var footer = document.querySelector('.settings-footer');
    if (tabs) tabs.style.display = 'none';
    if (footer) footer.style.display = 'none';
}

function exitPluginFullScreen() {
    window._pluginConfigOpen = false;
    var tabs = document.getElementById('settings-tabs-container');
    var footer = document.querySelector('.settings-footer');
    if (tabs) tabs.style.removeProperty('display');
    if (footer) footer.style.removeProperty('display');
    var content = document.querySelector('.settings-content');
    if (content) content.style.removeProperty('height');
}

window.showPluginConfig = function(name) {
    var plugin = getPluginByName(name);
    if (!plugin) return;

    enterPluginFullScreen();
    var header = pluginConfigHeader(plugin);

    if (plugin.name === 'tvcat_player_pro') {
        var container = document.getElementById('plugins-list-container');
        if (!container) return;
        var strategy = localStorage.getItem('tvcat_player_pro_cache_strategy') || 'forward';
        var threshold = localStorage.getItem('tvcat_player_pro_cache_cleanup_threshold');
        if (threshold === null) threshold = '30';
        var strategyHtml = '<option value="forward"' + (strategy === 'forward' ? ' selected' : '') + '>Adelante (desde posici\u00F3n actual)</option>';
        strategyHtml += '<option value="full"' + (strategy === 'full' ? ' selected' : '') + '>Completo (descargar todo el archivo)</option>';
        container.innerHTML = header + '<div class="settings-section" style="padding:14px;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-color);">' +
            '<h4 style="margin-bottom:12px;font-size:0.95rem;">\u2699\uFE0F Player Pro \u2014 Cach\u00E9 Local</h4>' +
            '<div style="margin-bottom:12px;"><label style="font-size:0.85rem;display:block;margin-bottom:4px;color:var(--text-secondary);">Estrategia de cach\u00E9:</label>' +
            '<select id="pro-cache-strategy" style="width:100%;background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border-color);border-radius:6px;padding:8px 10px;font-size:0.85rem;font-family:Outfit,sans-serif;">' + strategyHtml + '</select></div>' +
            '<div style="margin-bottom:12px;"><label style="font-size:0.85rem;display:block;margin-bottom:4px;color:var(--text-secondary);">Limpiar cach\u00E9 del episodio anterior al alcanzar (%):</label>' +
            '<input type="number" id="pro-cache-threshold" value="' + threshold + '" min="-1" max="100" style="width:100%;background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border-color);border-radius:6px;padding:8px 10px;font-size:0.85rem;font-family:Outfit,sans-serif;">' +
            '<span style="font-size:0.75rem;color:var(--text-secondary);margin-top:2px;display:block;">-1 = desactivado (el cleanup global se encargar\u00E1)</span></div>' +
            '<button class="btn-primary" onclick="saveProPlayerConfig()" style="padding:8px 20px;font-size:0.85rem;">\uD83D\uDCBE Guardar</button>' +
            '<span id="pro-cache-status" style="margin-left:8px;font-size:0.8rem;"></span>' +
            '<hr style="border-color:var(--border-color);margin:14px 0;">' +
            '<div style="margin-bottom:8px;"><label style="font-size:0.85rem;display:block;margin-bottom:4px;color:var(--text-secondary);">\uD83D\uDCCA Espacio usado:</label>' +
            '<div id="pro-cache-stats" style="font-size:0.85rem;padding:4px 0;">Calculando...</div></div>' +
            '<button class="btn-danger" onclick="clearProCache()" style="padding:8px 20px;font-size:0.85rem;background:#d32f2f;color:#fff;border:none;border-radius:6px;cursor:pointer;">\uD83D\uDDD1\uFE0F Vaciar todo el cach\u00E9</button>' +
            '<span id="pro-clear-status" style="margin-left:8px;font-size:0.8rem;"></span></div>';
        setTimeout(updateProCacheStats, 100);
        return;
    }

    if (plugin.name === 'tvcat_tgindex') {
        showTgindexConfig();
        return;
    }

    var container = document.getElementById('plugins-list-container');
    if (!container) return;
    if (plugin.settings_ui) {
        container.innerHTML = header + '<iframe src="' + plugin.settings_ui + '" style="width:100%;min-height:70vh;border:none;border-radius:6px;"></iframe>';
    } else {
        container.innerHTML = header + '<p style="color:var(--text-secondary);font-size:0.85rem;padding:12px;">Este plugin no tiene configuraci\u00F3n disponible.</p>';
    }
    return;
}

window.showTgindexConfig = function() {
    var container = document.getElementById('plugins-list-container');
    if (!container) return;
    enterPluginFullScreen();
    var plugin = getPluginByName('tvcat_tgindex');
    var header = pluginConfigHeader(plugin);
    var html = header + '<div style="margin-bottom:10px;"></div>' +

        // Secci\u00f3n: General
        '<div class="settings-section" style="margin-bottom:12px;padding:10px;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-color);">' +
        '<h4 style="margin:0 0 8px;font-size:0.9rem;">\u2699\ufe0f General</h4>' +
        '<div style="margin-bottom:8px;"><label style="display:flex;align-items:center;gap:8px;font-size:0.8rem;cursor:pointer;">' +
        '<input type="checkbox" id="cfg-scan-enabled" style="accent-color:var(--accent);"> Escaneo autom\u00e1tico activado</label></div>' +
        '<div style="margin-bottom:8px;"><label style="font-size:0.8rem;">Intervalo entre ciclos (min):</label>' +
        '<input type="number" id="cfg-cycle-minutes" min="1" style="width:110px;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:0.8rem;margin-left:8px;box-sizing:border-box;"></div>' +
        '<button class="btn-primary" onclick="saveTgindexGeneralConfig()" style="padding:5px 12px;font-size:0.8rem;">\uD83D\uDCBE Guardar</button>' +
        '<span id="cfg-status" style="margin-left:8px;font-size:0.8rem;"></span></div>' +

        // Secci\u00f3n: Scan Items
        '<div class="settings-section" style="margin-bottom:12px;padding:10px;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-color);">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">' +
        '<h4 style="margin:0;font-size:0.9rem;">\uD83D\uDCE1 Scan Items</h4>' +
        '<button class="btn-secondary" onclick="openTgindexEditModal(null)" style="padding:4px 10px;font-size:0.75rem;">+ Nuevo scan item</button></div>' +
        '<div id="channels-list" style="font-size:0.8rem;">Cargando...</div></div>' +

        // Sección: CacheRelay (config auxiliar + backup completo)
        '<div class="settings-section" style="margin-bottom:12px;padding:10px;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-color);">' +
        '<h4 style="margin:0 0 8px;font-size:0.9rem;">\uD83D\uDCE6 CacheRelay (backup completo)</h4>' +
        '<label style="font-size:0.8rem;">Chat auxiliar (@username o id):</label>' +
        '<input type="text" id="cache-relay-chat-aux" placeholder="@mi_canal_auxiliar" style="width:100%;background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:0.8rem;margin-top:4px;box-sizing:border-box;">' +
        '<label style="display:flex;align-items:center;gap:8px;font-size:0.8rem;margin-top:8px;cursor:pointer;">' +
        '<input type="checkbox" id="cache-relay-overwrite" style="accent-color:var(--accent);"> Sobrescribir registros existentes</label>' +
        '<div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">' +
        '<button class="btn-secondary" onclick="saveCacheRelayConfig()" style="padding:5px 12px;font-size:0.8rem;">Guardar config</button>' +
        '<button class="btn-secondary" onclick="cacheRelayUploadFull()" style="padding:5px 12px;font-size:0.8rem;">\u2B06 Backup completo</button>' +
        '<button class="btn-secondary" onclick="cacheRelayDownloadFull()" style="padding:5px 12px;font-size:0.8rem;">\u2B07 Obtener backup completo</button></div>' +
        '<span id="cache-relay-status" style="font-size:0.8rem;color:var(--text-secondary);"></span></div>' +

        // Secci\u00f3n: Escaneo + Logs
        '<div class="settings-section" style="margin-bottom:12px;padding:10px;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-color);">' +
        '<h4 style="margin:0 0 8px;font-size:0.9rem;">\uD83D\uDEE0\ufe0f Escaneo</h4>' +
        '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
        '<select id="scan-mode" style="background:var(--bg-card);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:4px 8px;font-size:0.8rem;">' +
        '<option value="normal">Normal (solo nuevos)</option>' +
        '<option value="clean">Clean (re-escanear todo)</option>' +
        '<option value="incremental">Incremental</option></select>' +
        '<button class="btn-primary" onclick="startTgindexScan()" style="padding:6px 14px;font-size:0.85rem;">\u25B6 Escanear ahora</button>' +
        '<span id="scan-status" style="font-size:0.8rem;color:var(--text-secondary);"></span></div>' +
        '<div id="scan-progress" style="margin-top:6px;height:4px;background:var(--bg-card);border-radius:2px;overflow:hidden;"><div id="scan-progress-bar" style="width:0%;height:100%;background:var(--accent);"></div></div>' +

        // Logs (persistente)
        '<div style="margin-top:8px;display:flex;align-items:center;">' +
        '<button onclick="toggleTgindexLogs()" id="tgindex-logs-toggle" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:0.8rem;font-family:Outfit,sans-serif;padding:4px 0;">\u25BC Log de escaneo</button>' +
        '<button onclick="clearTgindexLogs()" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:0.75rem;margin-left:12px;font-family:Outfit,sans-serif;padding:4px 0;">Limpiar</button></div>' +
        '<div id="scan-log" style="margin-top:4px;max-height:180px;overflow-y:auto;font-size:0.72rem;color:var(--text-secondary);font-family:monospace;padding:6px;background:var(--bg-card);border-radius:4px;white-space:pre-wrap;border:1px solid var(--border-color);"></div></div>' +

        // Bot\u00f3n Guardar cambios
        '<div style="display:flex;gap:8px;align-items:center;padding:8px;border-top:1px solid var(--border-color);margin-top:8px;">' +
        '<button class="btn-primary" onclick="saveTgindexAll()" style="padding:8px 20px;">\uD83D\uDCBE Guardar cambios</button>' +
        '<span id="save-tgindex-status" style="font-size:0.8rem;color:var(--text-secondary);"></span></div>';

    container.innerHTML = html;
    loadTgindexGeneralConfig();
    loadTgindexChannels();
    loadCacheRelayConfig();
    startTgindexLogPolling();
};

// --- Player Pro Config Functions ---

window.saveProPlayerConfig = function() {
    var strategyEl = document.getElementById('pro-cache-strategy');
    var thresholdEl = document.getElementById('pro-cache-threshold');
    var statusEl = document.getElementById('pro-cache-status');
    if (!strategyEl || !thresholdEl) return;
    var strategy = strategyEl.value;
    var threshold = parseInt(thresholdEl.value, 10);
    if (isNaN(threshold)) threshold = 30;
    localStorage.setItem('tvcat_player_pro_cache_strategy', JSON.stringify(strategy));
    localStorage.setItem('tvcat_player_pro_cache_cleanup_threshold', JSON.stringify(threshold));
    if (statusEl) {
        statusEl.textContent = '\u2705 Guardado';
        setTimeout(function() { statusEl.textContent = ''; }, 2000);
    }
};

// --- TGIndex Config Functions ---

function loadTgindexGeneralConfig() {
    window.API.ajax({
        url: '/api/plugin/config',
        success: function(res) {
            var cycleEl = document.getElementById('cfg-cycle-minutes');
            var toggle = document.getElementById('cfg-scan-enabled');
            if (cycleEl) cycleEl.value = res.cycle_minutes || 30;
            if (toggle) toggle.checked = res.scan_enabled !== false;
        }
    });
}

window.saveTgindexGeneralConfig = function() {
    var cycle = parseInt(document.getElementById('cfg-cycle-minutes').value, 10) || 30;
    var enabled = document.getElementById('cfg-scan-enabled').checked;
    var status = document.getElementById('cfg-status');
    if (status) status.textContent = 'Guardando...';
    window.API.ajax({
        method: 'POST',
        url: '/api/plugin/config',
        data: { cycle_minutes: cycle, scan_enabled: enabled },
        success: function(res) {
            if (status) status.textContent = res && res.success ? '\u2705 Guardado' : '\u274C Error';
        },
        error: function() { if (status) status.textContent = '\u274C Error de red'; }
    });
};

// --- Refresh catálogo + árbol lateral tras una sincronización del plugin ---
function refreshTgindexAfterSync() {
    if (window.Catalog && window.Catalog.load) {
        window.Catalog.load(window.Catalog.currentCategory || 'home');
    }
    if (typeof buildCategoryTree === 'function') buildCategoryTree();
    if (typeof loadContentsTrees === 'function') loadContentsTrees();
}

window.saveTgindexAll = function() {
    var status = document.getElementById('save-tgindex-status');
    if (status) status.textContent = 'Sincronizando datos del plugin...';
    window.API.ajax({
        method: 'POST',
        url: '/api/plugin/save',
        data: {},
        success: function(syncRes) {
            if (syncRes && syncRes.success) {
                if (status) status.textContent = 'Actualizando cach\u00E9 central (' + (syncRes.items || 0) + ' \u00EDtems)...';
                window.API.ajax({
                    method: 'POST',
                    url: '/api/cache/refresh',
                    data: { plugin: 'tvcat_tgindex' },
                    success: function(cacheRes) {
                        if (status) status.textContent = cacheRes && cacheRes.success ? '\u2705 Guardado y cach\u00e9 actualizado' : '\u26a0\ufe0f Error en cach\u00e9';
                        if (cacheRes && cacheRes.success) {
                            refreshTgindexAfterSync();
                            loadPluginsList();
                        }
                    },
                    error: function() {
                        if (status) status.textContent = '\u274C Error al actualizar cach\u00E9';
                    }
                });
            } else {
                if (status) status.textContent = '\u274C Error en sync: ' + (syncRes && syncRes.error ? syncRes.error : 'desconocido');
            }
        },
        error: function() {
            if (status) status.textContent = '\u274C Error de red al sincronizar';
        }
    });
};

function loadTgindexChannels() {
    var list = document.getElementById('channels-list');
    if (!list) return;
    window.API.ajax({
        url: '/api/user/channels',
        success: function(data) {
            var channels = Array.isArray(data) ? data : (data.channels || []);
            if (channels.length === 0) {
                list.innerHTML = '<div style="color:var(--text-secondary);padding:6px 0;">Sin scan items. Pulsa "+ Nuevo scan item".</div>';
                return;
            }
            var html = '';
            for (var i = 0; i < channels.length; i++) {
                var ch = channels[i];
                var id = ch.id;
                var cat = ch.category || (ch.content_type || 'media');
                var sub = ch.custom_subcategory || '';
                var chip = (cat || 'media') + (sub ? ' \u00b7 ' + sub : '');
                // Enlace al canal Telegram (t.me/c/{bare}/{start_msg})
                var chLink = '';
                if (ch.channel_id) {
                    var bare = String(ch.channel_id).replace('-100', '').replace(/^-/, '');
                    var startMsg = ch.start_msg_id || 1;
                    chLink = 'https://t.me/c/' + bare + '/' + startMsg;
                }
                var nameHtml = chLink
                    ? '<a href="' + chLink + '" target="_blank" rel="noopener" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;color:var(--accent);text-decoration:none;">' + (ch.display_name || 'Sin nombre') + '</a>'
                    : '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;">' + (ch.display_name || 'Sin nombre') + '</span>';

                // Botones compactos del mismo tamaño (paquete con flecha superpuesta)
                var btnStyle = 'padding:4px 8px;font-size:0.75rem;line-height:1;white-space:nowrap;flex-shrink:0;';
                html += '<div data-cache-channel="' + (ch.channel_id || '') + '" style="border:1px solid var(--border-color);border-radius:6px;margin-bottom:6px;background:var(--bg-card);overflow:hidden;">' +
                    '<div style="display:flex;align-items:center;gap:6px;padding:6px 8px;">' +
                    '<label class="ch-toggle" style="cursor:pointer;display:inline-block;position:relative;width:34px;height:18px;margin:0;flex-shrink:0;" onclick="event.stopPropagation();toggleChannelEnabled(' + id + ',' + (ch.enabled ? 'false' : 'true') + ')">' +
                    '<input type="checkbox"' + (ch.enabled ? ' checked' : '') + ' style="opacity:0;width:0;height:0;position:absolute;"><span class="ch-toggle-slider" style="position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:' + (ch.enabled ? '#22c55e' : '#3f3f46') + ';border-radius:18px;transition:0.3s;"></span></label>' +
                    '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;">' +
                    nameHtml +
                    '<span style="font-size:0.7rem;color:var(--text-secondary);white-space:nowrap;">' + chip + '</span>' +
                    '</div>' +
                    '<button class="btn-secondary cache-upload-btn" data-upload-btn="' + (ch.channel_id || '') + '" onclick="cacheRelayUpload(\'' + (ch.channel_id || '') + '\', this)" title="Subir cache de este canal" style="' + btnStyle + 'display:none;">\uD83D\uDCE6\u2B06</button>' +
                    '<button class="btn-secondary" onclick="cacheRelayDownload(\'' + (ch.channel_id || '') + '\', this)" title="Recuperar cache de este canal" style="' + btnStyle + '">\uD83D\uDCE6\u2B07</button>' +
                    '<button class="btn-secondary" onclick="openTgindexEditModal(' + id + ')" title="Editar" style="' + btnStyle + '">\u270f\ufe0f</button>' +
                    '</div>' +
                    '<div style="height:2px;background:#27272a;width:100%;"><div class="scan-progress-fill" style="height:100%;width:0%;background:#22c55e;transition:width 0.3s;"></div></div>' +
                    '</div>';
            }
            list.innerHTML = html;
            // Mostrar el botón de subir SOLO en canales donde se puede escribir (can_post=true).
            // Oculto por defecto; se muestra cuando el backend confirma permisos (con caché en DB).
            window.API.ajax({
                url: '/api/cache-relay/channels',
                success: function(relay) {
                    var rl = (relay && relay.channels) || [];
                    for (var k = 0; k < rl.length; k++) {
                        if (rl[k].can_post) {
                            var btns = list.querySelectorAll('[data-upload-btn="' + rl[k].channel_id + '"]');
                            for (var b = 0; b < btns.length; b++) btns[b].style.display = '';
                        }
                    }
                }
            });
        },
        error: function() {
            var list = document.getElementById('channels-list');
            if (list) list.innerHTML = '<div style="color:var(--accent);">Error cargando scan items</div>';
        }
    });
}

// --- CacheRelay ---

function loadCacheRelayConfig() {
    window.API.ajax({
        url: '/api/cache-relay/config',
        success: function(cfg) {
            var aux = document.getElementById('cache-relay-chat-aux');
            var ow = document.getElementById('cache-relay-overwrite');
            if (aux && cfg.chat_aux) aux.value = cfg.chat_aux;
            if (ow) ow.checked = !!cfg.overwrite;
        }
    });
}

function saveCacheRelayConfig() {
    var aux = document.getElementById('cache-relay-chat-aux');
    var ow = document.getElementById('cache-relay-overwrite');
    var st = document.getElementById('cache-relay-status');
    var raw = aux ? aux.value.trim() : '';
    var chatAux = cacheRelayParseChat(raw);
    window.API.ajax({
        method: 'POST',
        url: '/api/cache-relay/config',
        data: { chat_aux: chatAux, overwrite: ow ? ow.checked : false },
        success: function() {
            if (st) st.textContent = 'Config guardada.' + (chatAux !== raw ? ' (chat: ' + chatAux + ')' : '');
            if (aux && chatAux !== raw) aux.value = chatAux;
        },
        error: function() { if (st) st.textContent = 'Error guardando config.'; }
    });
}

function cacheRelayParseChat(raw) {
    // Acepta: @username, id numérico, -100..., o enlace t.me (canal/mensaje). Devuelve la entidad.
    if (!raw) return '';
    var s = raw.trim();
    // Enlace t.me/c/{id}/... o t.me/{username}/...
    var m = s.match(/t\.me\/c\/(\d+)(?:\/(\d+))?/);
    if (m) return '-100' + m[1];
    var m2 = s.match(/t\.me\/([a-zA-Z0-9_]+)(?:\/\d+)?/);
    if (m2 && m2[1] !== 'c') return m2[1];
    // @username
    if (s.charAt(0) === '@') return s;
    return s;
}

function cacheRelayToast(msg) {
    var t = document.getElementById('cache-relay-toast-container');
    if (!t) {
        t = document.createElement('div');
        t.id = 'cache-relay-toast-container';
        t.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999999;display:flex;flex-direction:column;gap:8px;';
        document.body.appendChild(t);
    }
    var el = document.createElement('div');
    el.style.cssText = 'background:#18181b;border:1px solid #3f3f46;border-radius:8px;padding:10px 16px;color:#f4f4f5;font-size:13px;max-width:340px;box-shadow:0 4px 12px rgba(0,0,0,0.4);';
    el.textContent = msg;
    t.appendChild(el);
    setTimeout(function() { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(function() { el.remove(); }, 300); }, 4000);
}

function cacheRelayUpload(channelId, btn) {
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span style="display:inline-block;animation:spin 1.2s linear infinite;">\u23F3</span>';
    }
    var st = document.getElementById('cache-relay-status');
    if (st) st.textContent = 'Subiendo cache...';
    var progressBar = null;
    if (channelId) {
        var items = document.querySelectorAll('[data-cache-channel]');
        for (var k = 0; k < items.length; k++) {
            if (items[k].getAttribute('data-cache-channel') === channelId) {
                progressBar = items[k].querySelector('.scan-progress-fill');
                break;
            }
        }
    }

    var pollTimer = setInterval(function() {
        window.API.ajax({
            url: '/api/cache-relay/status',
            success: function(p) {
                if (p && p.running) {
                    var pct = (p.total > 0) ? Math.round((p.current / p.total) * 100) : 0;
                    if (btn) btn.innerHTML = pct + '%';
                    if (progressBar) progressBar.style.width = pct + '%';
                }
            }
        });
    }, 800);

    window.API.ajax({
        method: 'POST',
        url: '/api/cache-relay/' + encodeURIComponent(channelId) + '/upload',
        success: function(r) {
            clearInterval(pollTimer);
            if (btn) { btn.disabled = false; btn.innerHTML = '\uD83D\uDCE6\u2B06'; }
            if (progressBar) progressBar.style.width = '100%';
            if (r && r.ok) {
                cacheRelayToast('Cache subido: ' + (r.count || 0) + ' mensajes guardados.');
                if (st) st.textContent = 'Subido: ' + (r.count || 0) + ' msgs.';
            } else {
                cacheRelayToast('Error subiendo cache: ' + (r && r.error ? r.error : 'desconocido'));
                if (st) st.textContent = 'Error: ' + (r && r.error ? r.error : 'desconocido');
            }
            loadTgindexChannels();
        },
        error: function() {
            clearInterval(pollTimer);
            if (btn) { btn.disabled = false; btn.innerHTML = '\uD83D\uDCE6\u2B06'; }
            cacheRelayToast('Error de red al subir cache.');
            if (st) st.textContent = 'Error de red al subir.';
        }
    });
}

function cacheRelayDownload(channelId, btn) {
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span style="display:inline-block;animation:spin 1.2s linear infinite;">\u23F3</span>';
    }
    var st = document.getElementById('cache-relay-status');
    if (st) st.textContent = 'Recuperando cache...';
    var progressBar = null;
    if (channelId) {
        // Localizar la barra de progreso del scan item (por channel_id del item en la lista)
        var items = document.querySelectorAll('[data-cache-channel]');
        for (var k = 0; k < items.length; k++) {
            if (items[k].getAttribute('data-cache-channel') === channelId) {
                progressBar = items[k].querySelector('.scan-progress-fill');
                break;
            }
        }
    }

    var pollTimer = setInterval(function() {
        window.API.ajax({
            url: '/api/cache-relay/status',
            success: function(p) {
                if (p && p.running) {
                    var pct = (p.total > 0) ? Math.round((p.current / p.total) * 100) : 0;
                    if (btn) btn.innerHTML = pct + '%';
                    if (progressBar) progressBar.style.width = pct + '%';
                }
            }
        });
    }, 800);

    window.API.ajax({
        method: 'POST',
        url: '/api/cache-relay/' + encodeURIComponent(channelId) + '/download',
        data: { source: 'auto' },
        success: function(r) {
            clearInterval(pollTimer);
            if (btn) { btn.disabled = false; btn.innerHTML = '\uD83D\uDCE6\u2B07'; }
            if (progressBar) progressBar.style.width = '100%';
            if (r && r.ok) {
                if (r.skipped) {
                    cacheRelayToast('Cache ya actualizado.');
                    if (st) st.textContent = 'Ya actualizado.';
                } else {
                    var total = r.total || r.imported || 0;
                    cacheRelayToast('Cache recuperado: ' + (r.imported || 0) + ' de ' + total + ' mensajes incorporados.');
                    if (st) st.textContent = 'Importado ' + (r.imported || 0) + ' de ' + total + ' msgs.';
                }
            } else {
                cacheRelayToast('Error recuperando cache: ' + (r && r.error ? r.error : 'desconocido'));
                if (st) st.textContent = 'Error: ' + (r && r.error ? r.error : 'desconocido');
            }
            loadTgindexChannels();
        },
        error: function() {
            clearInterval(pollTimer);
            if (btn) { btn.disabled = false; btn.innerHTML = '\uD83D\uDCE6\u2B07'; }
            cacheRelayToast('Error de red al recuperar cache.');
            if (st) st.textContent = 'Error de red al recuperar.';
        }
    });
}

function cacheRelayUploadFull() {
    var st = document.getElementById('cache-relay-status');
    if (st) st.textContent = 'Subiendo backup completo...';
    window.API.ajax({
        method: 'POST',
        url: '/api/cache-relay/upload-full',
        success: function(r) {
            if (st) st.textContent = (r && r.ok) ? 'Backup completo subido.' : ('Error: ' + (r && r.error ? r.error : 'desconocido'));
        },
        error: function() { if (st) st.textContent = 'Error de red al subir.'; }
    });
}

function cacheRelayDownloadFull() {
    var st = document.getElementById('cache-relay-status');
    if (st) st.textContent = 'Obteniendo backup completo...';
    window.API.ajax({
        method: 'POST',
        url: '/api/cache-relay/download-full',
        success: function(r) {
            if (st) st.textContent = (r && r.ok)
                ? ((r.skipped ? 'Ya actualizado.' : 'Importado ' + (r.imported || 0) + ' msgs.'))
                : ('Error: ' + (r && r.error ? r.error : 'desconocido'));
            loadCacheRelayChannels();
        },
        error: function() { if (st) st.textContent = 'Error de red al obtener backup.'; }
    });
}

var _tgindex_categories = [];
var _tgindex_subcategories = {};
var _tgindex_logs_timer = null;

window.loadTgindexCategoryOptions = function(selId, subSelId, currentCat, currentSub) {
    var catSel = document.getElementById(selId);
    var subSel = document.getElementById(subSelId);
    if (!catSel) return;
    function fillCat() {
        var catVal = currentCat || '';
        var opts = '<option value="">(seleccionar)</option>';
        for (var i = 0; i < _tgindex_categories.length; i++) {
            var c = _tgindex_categories[i];
            opts += '<option value="' + c + '"' + (c === catVal ? ' selected' : '') + '>' + c + '</option>';
        }
        opts += '<option value="__custom__"' + (catVal && _tgindex_categories.indexOf(catVal) === -1 ? ' selected' : '') + '>\u270d\ufe0f Personalizada...</option>';
        catSel.innerHTML = opts;
        var customInput = document.getElementById('tgindex-cat-custom');
        if (customInput) customInput.style.display = (catSel.value === '__custom__' || (catVal && _tgindex_categories.indexOf(catVal) === -1)) ? 'block' : 'none';
        if (catVal && _tgindex_categories.indexOf(catVal) === -1 && customInput) customInput.value = catVal;
    }
    window.API.ajax({
        url: '/api/categories/all',
        success: function(res) {
            _tgindex_categories = (res && res.categories) || [];
            _tgindex_subcategories = (res && res.subcategories) || {};
            fillCat();
            fillSub();
        },
        error: function() { fillCat(); fillSub(); }
    });
    function fillSub() {
        if (!subSel) return;
        var subVal = currentSub || '';
        var subs = _tgindex_subcategories[catSel ? catSel.value : ''] || [];
        var opts = '<option value="">(vac\u00edo)</option>';
        for (var i = 0; i < subs.length; i++) {
            opts += '<option value="' + subs[i] + '"' + (subs[i] === subVal ? ' selected' : '') + '>' + subs[i] + '</option>';
        }
        opts += '<option value="__custom__"' + (subVal && subs.indexOf(subVal) === -1 ? ' selected' : '') + '>\u270d\ufe0f Personalizada...</option>';
        subSel.innerHTML = opts;
        var customInput = document.getElementById('tgindex-subcat-custom');
        if (customInput) customInput.style.display = (subSel.value === '__custom__' || (subVal && subs.indexOf(subVal) === -1)) ? 'block' : 'none';
        if (subVal && subs.indexOf(subVal) === -1 && customInput) customInput.value = subVal;
    }
    catSel.onchange = function() {
        var customInput = document.getElementById('tgindex-cat-custom');
        if (customInput) customInput.style.display = (catSel.value === '__custom__') ? 'block' : 'none';
        fillSub();
    };
    if (subSel) subSel.onchange = function() {
        var customInput = document.getElementById('tgindex-subcat-custom');
        if (customInput) customInput.style.display = (subSel.value === '__custom__') ? 'block' : 'none';
    };
}

window.openTgindexEditModal = function(id) {
    var isNew = (id === null || id === undefined);
    var existing = document.getElementById('tgindex-edit-modal');
    if (existing) existing.parentNode.removeChild(existing);

    var overlay = document.createElement('div');
    overlay.id = 'tgindex-edit-modal';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:99999;display:flex;align-items:flex-start;justify-content:center;overflow-y:auto;padding:30px 12px;';
    overlay.innerHTML = '<div style="background:#111113;border:1px solid var(--border-color,#3f3f46);border-radius:10px;max-width:640px;width:100%;padding:16px;box-sizing:border-box;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
        '<h3 style="margin:0;font-size:1rem;">' + (isNew ? '\u2795 Nuevo scan item' : '\u270f\ufe0f Editar scan item') + '</h3>' +
        '<button onclick="closeTgindexEditModal()" style="background:none;border:none;color:#a1a1aa;font-size:1.4rem;cursor:pointer;line-height:1;padding:0 4px;">&times;</button></div>' +

        '<div style="margin-bottom:8px;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:3px;">Nombre en UI</label>' +
        '<input type="text" id="tgindex-name" value="" placeholder="Mi Serie / Canal" style="width:100%;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>' +

        '<div style="display:flex;gap:8px;margin-bottom:8px;">' +
        '<div style="flex:1;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:3px;">Mensaje de Inicio (URL o n\u00ba)</label>' +
        '<input type="text" id="tgindex-start" value="" oninput="autofillTgindexId()" placeholder="https://t.me/c/123/5 o 5" style="width:100%;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>' +
        '<div style="flex:1;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:3px;">Mensaje de Fin (opcional)</label>' +
        '<input type="text" id="tgindex-end" value="" placeholder="URL o n\u00ba (vac\u00edo = \u00faltimo)" style="width:100%;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div></div>' +

        '<div style="margin-bottom:8px;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:3px;">ID del Canal (se auto-rellena desde el inicio)</label>' +
        '<input type="text" id="tgindex-channel-id" value="" placeholder="-100123456789" style="width:100%;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>' +

        // Secci\u00F3n Topic
        '<div style="margin-bottom:10px;padding:8px;background:#18181b;border:1px solid #3f3f46;border-radius:4px;">' +
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;">' +
        '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:0.75rem;color:#f4f4f5;">' +
        '<input type="checkbox" id="tgindex-topic-only" onchange="tgindexTopicOnlyChange()" style="accent-color:var(--accent);">' +
        'Obtener solo t\u00edtulos de este topic</label></div>' +
        '<div style="display:flex;gap:8px;">' +
        '<div style="flex:1;"><label style="display:block;font-size:0.65rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:2px;">ID del Topic</label>' +
        '<input type="text" id="tgindex-topic-id" value="" placeholder="1201" style="width:100%;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div>' +
        '<div style="flex:2;"><label style="display:block;font-size:0.65rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:2px;">Nombre del Topic</label>' +
        '<input type="text" id="tgindex-topic-name" value="" placeholder="3DS" style="width:100%;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;"></div></div></div>' +

        '<div style="display:flex;gap:8px;margin-bottom:8px;">' +
        '<div style="flex:1;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:3px;">Cuenta de Telegram</label>' +
        '<select id="tgindex-account" style="width:100%;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;font-size:0.8rem;box-sizing:border-box;height:32px;"><option value="-1">Cuenta Principal (Global)</option></select></div>' +
        '<div style="flex:1;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:3px;">Topolog\u00eda</label>' +
        '<select id="tgindex-topo" onchange="onTgindexTopoChange()" style="width:100%;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;font-size:0.8rem;box-sizing:border-box;height:32px;">' +
        '<option value="4">Tipo 4: Autom\u00e1tica (patr\u00f3n fichero 75%)</option>' +
        '<option value="1">Tipo 1: Plano (Secuencial)</option>' +
        '<option value="2">Tipo 2: Temas Tem\u00e1ticos</option>' +
        '<option value="3">Tipo 3: Tema por T\u00edtulo</option></select>' +
        '<span id="tgindex-topo-count" style="font-size:0.7rem;color:#a1a1aa;margin-top:3px;display:block;"></span></div></div>' +

        '<div style="display:flex;gap:8px;margin-bottom:8px;">' +
        '<div style="flex:1;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:3px;">Categor\u00eda</label>' +
        '<select id="tgindex-cat" style="width:100%;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;font-size:0.8rem;box-sizing:border-box;height:32px;"><option value="">(seleccionar)</option></select>' +
        '<input type="text" id="tgindex-cat-custom" value="" placeholder="Nueva categor\u00eda..." style="display:none;width:100%;background:#0a0a0c;border:1px solid #22c55e;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;margin-top:4px;"></div>' +
        '<div style="flex:1;"><label style="display:block;font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;margin-bottom:3px;">Subcategor\u00eda</label>' +
        '<select id="tgindex-subcat" style="width:100%;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:4px;padding:6px 8px;font-size:0.8rem;box-sizing:border-box;height:32px;"><option value="">(vac\u00edo)</option></select>' +
        '<input type="text" id="tgindex-subcat-custom" value="" placeholder="Nueva subcategor\u00eda..." style="display:none;width:100%;background:#0a0a0c;border:1px solid #22c55e;border-radius:4px;padding:6px 8px;color:#f4f4f5;font-size:0.8rem;box-sizing:border-box;margin-top:4px;"></div></div>' +

        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;border-top:1px solid var(--border-color,#3f3f46);padding-top:10px;">' +
        '<button class="btn-primary" onclick="saveTgindexChannel()" style="padding:6px 14px;font-size:0.8rem;">\ud83d\udcbe Guardar</button>' +
        '<button class="btn-secondary" onclick="closeTgindexEditModal()" style="padding:6px 14px;font-size:0.8rem;">\u2190 Volver</button>' +
        '<button class="btn-secondary" onclick="updateScanChannel(modalTgindexId)" style="padding:6px 12px;font-size:0.8rem;">\u21bb Actualizar</button>' +
        '<button class="btn-secondary" onclick="rescanChannel(modalTgindexId)" style="padding:6px 12px;font-size:0.8rem;">\u267b\ufe0f Reescanear</button>' +
        '<button class="btn-secondary" onclick="cleanRecordsChannel(modalTgindexId)" style="padding:6px 12px;font-size:0.8rem;">\ud83d\uddd1\ufe0f Limpiar</button>' +
        '<button class="btn-danger" onclick="deleteTgindexChannel(modalTgindexId)" style="padding:6px 12px;font-size:0.8rem;background:#d32f2f;color:#fff;border:none;border-radius:6px;cursor:pointer;">\u274c Eliminar</button></div>' +
        '<div id="tgindex-modal-status" style="font-size:0.75rem;color:var(--text-secondary);margin-top:8px;"></div></div>';

    document.body.appendChild(overlay);
    window.modalTgindexId = isNew ? null : id;

    var name = document.getElementById('tgindex-name');
    var start = document.getElementById('tgindex-start');
    var end = document.getElementById('tgindex-end');
    var cid = document.getElementById('tgindex-channel-id');
    var acc = document.getElementById('tgindex-account');
    var topo = document.getElementById('tgindex-topo');

    if (isNew) {
        topo.value = '1';
        acc.value = '-1';
        loadTgindexCategoryOptions('tgindex-cat', 'tgindex-subcat', '', '');
        return;
    }

    window.API.ajax({
        url: '/api/user/channels',
        success: function(data) {
            var channels = Array.isArray(data) ? data : (data.channels || []);
            for (var i = 0; i < channels.length; i++) {
                if (channels[i].id === id) {
                    var ch = channels[i];
                    if (name) name.value = ch.display_name || '';
                    if (start) start.value = ch.start_msg_id || '';
                    if (end) end.value = ch.end_msg_id || '';
                    if (cid) cid.value = ch.channel_id || '';
                    if (acc) acc.value = (ch.telegram_account_id !== null && ch.telegram_account_id !== undefined) ? ch.telegram_account_id : -1;
                    if (topo) topo.value = String(ch.topology_type !== undefined && ch.topology_type !== null ? ch.topology_type : 1);
                    loadTgindexCategoryOptions('tgindex-cat', 'tgindex-subcat', ch.category || ch.content_type || '', ch.custom_subcategory || '');
                    // Topic
                    var topicIdEl = document.getElementById('tgindex-topic-id');
                    var topicOnlyEl = document.getElementById('tgindex-topic-only');
                    var topicNameEl = document.getElementById('tgindex-topic-name');
                    if (topicIdEl && ch.topic_id) topicIdEl.value = ch.topic_id;
                    if (topicNameEl && ch.topic_name) topicNameEl.value = ch.topic_name;
                    if (topicOnlyEl) topicOnlyEl.checked = (ch.topic_only ? true : false);
                    tgindexTopicOnlyChange();
                    break;
                }
            }
        },
        error: function() {}
    });
};

window.autofillTgindexId = function() {
    var startEl = document.getElementById('tgindex-start');
    var idEl = document.getElementById('tgindex-channel-id');
    var topicEl = document.getElementById('tgindex-topic-id');
    if (!startEl) return;
    var val = startEl.value.trim();
    var m = val.match(/t\.me\/c\/(\d+)/);
    if (m && idEl) idEl.value = '-100' + m[1];
    // Detectar topic: t.me/c/223/1201/1203 \u2192 topic 1201, start 1203
    var tm = val.match(/t\.me\/c\/\d+\/(\d+)\/(\d+)/);
    if (tm && topicEl) {
        if (!topicEl.value) topicEl.value = tm[1];
    }
};

window.closeTgindexEditModal = function() {
    var el = document.getElementById('tgindex-edit-modal');
    if (el) el.parentNode.removeChild(el);
};

window.tgindexTopicOnlyChange = function() {
    var checked = document.getElementById('tgindex-topic-only');
    var topicId = document.getElementById('tgindex-topic-id');
    var topicName = document.getElementById('tgindex-topic-name');
    if (!topicId || !topicName) return;
    var active = checked ? checked.checked : false;
    topicId.style.opacity = active ? '1' : '0.5';
    topicName.style.opacity = active ? '1' : '0.5';
};

function _tgindexModalPayload() {
    var name = document.getElementById('tgindex-name').value.trim();
    var cid = document.getElementById('tgindex-channel-id').value.trim();
    var start = document.getElementById('tgindex-start').value.trim();
    var end = document.getElementById('tgindex-end').value.trim();
    var topo = parseInt(document.getElementById('tgindex-topo').value, 10) || 1;
    var account = parseInt(document.getElementById('tgindex-account').value, 10) || -1;
    var catSel = document.getElementById('tgindex-cat');
    var cat = catSel.value === '__custom__' ? (document.getElementById('tgindex-cat-custom').value.trim() || '') : catSel.value;
    var subSel = document.getElementById('tgindex-subcat');
    var sub = subSel.value === '__custom__' ? (document.getElementById('tgindex-subcat-custom').value.trim() || '') : subSel.value;
    var payload = {
        display_name: name,
        channel_id: cid,
        topology_type: topo,
        category: cat || 'media',
        custom_subcategory: sub || null,
        telegram_account_id: account,
        enabled: 1
    };
    if (start) payload.start_msg = start;
    if (end) payload.end_msg = end;
    var topicIdEl = document.getElementById('tgindex-topic-id');
    var topicOnlyEl = document.getElementById('tgindex-topic-only');
    if (topicIdEl) {
        var tid = topicIdEl.value.trim();
        if (tid) payload.topic_id = parseInt(tid, 10) || null;
    }
    if (topicOnlyEl) payload.topic_only = topicOnlyEl.checked ? 1 : 0;
    var topicNameEl = document.getElementById('tgindex-topic-name');
    if (topicNameEl && topicNameEl.value.trim()) payload.topic_name = topicNameEl.value.trim();
    if (window.modalTgindexId) payload.id = window.modalTgindexId;
    return { payload: payload, name: name, cid: cid };
}

window.onTgindexTopoChange = function() {
    var countEl = document.getElementById('tgindex-topo-count');
    var id = window.modalTgindexId;
    if (!id) {
        if (countEl) countEl.textContent = 'Guarda el scan item para analizar.';
        return;
    }
    var built = _tgindexModalPayload();
    if (countEl) countEl.textContent = 'Analizando...';
    window.API.ajax({
        method: 'POST', url: '/api/user/channels',
        data: built.payload,
        success: function() {
            window.API.ajax({
                method: 'POST', url: '/api/user/parse/' + id,
                success: function(res) {
                    if (countEl) countEl.textContent = (res && res.new_items ? '+' + res.new_items + ' t\u00edtulo(s) descubiertos' : '0 t\u00edtulos descubiertos');
                    loadTgindexChannels();
                },
                error: function() { if (countEl) countEl.textContent = 'Error al analizar'; }
            });
        },
        error: function() { if (countEl) countEl.textContent = 'Error al guardar'; }
    });
};

window.saveTgindexChannel = function() {
    var status = document.getElementById('tgindex-modal-status');
    var built = _tgindexModalPayload();
    if (!built.name) { alert('Introduce el nombre visible.'); return; }
    if (!built.cid) { alert('Introduce el ID del canal (o un mensaje de inicio con t.me/c/...).'); return; }

    if (status) status.textContent = 'Guardando...';
    window.API.ajax({
        method: 'POST', url: '/api/user/channels',
        data: built.payload,
        success: function(res) {
            if (status) status.textContent = '\u2705 Guardado';
            // Import automático desde CacheRelay (si el canal tenía backup publicado)
            if (res && res.cache_relay && res.cache_relay.found) {
                var cr = res.cache_relay;
                if (cr.skipped) {
                    cacheRelayToast('CacheRelay: ya actualizado.');
                } else {
                    cacheRelayToast('CacheRelay: ' + (cr.imported || 0) + ' de ' + (cr.total || 0) + ' mensajes incorporados.');
                }
            }
            setTimeout(function() {
                closeTgindexEditModal();
                loadTgindexChannels();
                saveTgindexAll();
            }, 400);
        },
        error: function() { if (status) status.textContent = '\u274c Error al guardar'; }
    });
};

window.toggleChannelEnabled = function(id, enableNow) {
    var enabled = (enableNow === 'true' || enableNow === true) ? 1 : 0;
    window.API.ajax({
        method: 'POST',
        url: '/api/user/channels/' + id + '/toggle',
        data: { enabled: enabled },
        success: function() {
            loadTgindexChannels();
            refreshTgindexAfterSync();
        },
        error: function() { loadTgindexChannels(); }
    });
};

window.deleteTgindexChannel = function(id) {
    if (!confirm('\u00bfEliminar este scan item y todos sus registros?')) return;
    window.API.ajax({
        method: 'DELETE', url: '/api/user/channels/' + id,
        success: function() { closeTgindexEditModal(); loadTgindexChannels(); }
    });
};

window.updateScanChannel = function(id) {
    var status = document.getElementById('tgindex-modal-status');
    if (!id) { if (status) status.textContent = 'Guarda primero el scan item.'; return; }
    if (status) status.textContent = 'Actualizando canal ' + id + '...';
    window.API.ajax({
        method: 'POST', url: '/api/user/scan/update/' + id,
        success: function(res) {
            if (status) status.textContent = res && res.success ? '\u2705 Canal actualizado' : '\u274c ' + (res ? res.error : 'Error');
            setTimeout(function() { saveTgindexAll(); }, 300);
        },
        error: function() { if (status) status.textContent = '\u274c Error de red'; }
    });
};

window.rescanChannel = function(id) {
    if (!id) { alert('Guarda primero el scan item.'); return; }
    if (!confirm('\u00bfRe-escanear este canal completo (rebuild)?')) return;
    var status = document.getElementById('tgindex-modal-status');
    if (status) status.textContent = 'Re-escaneando canal ' + id + '...';
    window.API.ajax({
        method: 'POST', url: '/api/user/scan/start',
        data: { mode: 'clean', id: id },
        success: function(res) {
            if (status) status.textContent = res && res.success ? '\u2705 Re-escaneo iniciado' : '\u274c ' + (res ? res.error : 'Error');
            setTimeout(function() { saveTgindexAll(); }, 500);
        },
        error: function() { if (status) status.textContent = '\u274c Error de red'; }
    });
};

window.cleanRecordsChannel = function(id) {
    if (!id) { alert('Guarda primero el scan item.'); return; }
    if (!confirm('\u00bfLimpiar los registros del cat\u00e1logo para este scan (sin borrar el scan item)?')) return;
    var status = document.getElementById('tgindex-modal-status');
    if (status) status.textContent = 'Limpiando registros del canal ' + id + '...';
    window.API.ajax({
        method: 'POST', url: '/api/user/channels/' + id + '/clean-records',
        success: function(res) {
            if (status) status.textContent = res && res.success ? '\u2705 Registros limpiados' : '\u274c ' + (res ? res.error : 'Error');
            setTimeout(function() { saveTgindexAll(); }, 300);
        },
        error: function() { if (status) status.textContent = '\u274c Error de red'; }
    });
};

window.startTgindexScan = function() {
    var mode = document.getElementById('scan-mode').value;
    var status = document.getElementById('scan-status');
    var bar = document.getElementById('scan-progress-bar');
    if (status) status.textContent = 'Escaneando...';
    if (bar) bar.style.width = '0%';

    window.API.ajax({
        method: 'POST',
        url: '/api/user/scan/start',
        data: { mode: mode },
        success: function(res) {
            if (status) status.textContent = res && res.success ? '\u2705 Escaneo iniciado' : '\u274c ' + (res ? res.error : 'Error');
            pollScanStatus();
        },
        error: function() { if (status) status.textContent = '\u274c Error de red'; }
    });
};

function pollScanStatus() {
    var status = document.getElementById('scan-status');
    var bar = document.getElementById('scan-progress-bar');
    var log = document.getElementById('scan-log');
    window.API.ajax({
        url: '/api/user/scan/status',
        success: function(res) {
            if (res.status === 'scanning') {
                if (status) status.textContent = 'Escaneando... ' + (res.progress_percent || 0) + '%';
                if (bar) bar.style.width = (res.progress_percent || 0) + '%';
                if (res.logs && log) { log.innerHTML = res.logs.slice(-30).join('\n'); log.scrollTop = log.scrollHeight; }
                setTimeout(pollScanStatus, 2000);
            } else {
                if (status) status.textContent = '\u2705 Escaneo completado';
                if (bar) bar.style.width = '100%';
                if (res.logs && log) { log.innerHTML = res.logs.slice(-30).join('\n'); log.scrollTop = log.scrollHeight; }
            }
        },
        error: function() {
            if (status) status.textContent = '\u274c Error consultando estado';
        }
    });
}

window.toggleTgindexLogs = function() {
    var log = document.getElementById('scan-log');
    if (!log) return;
    var toggle = document.getElementById('tgindex-logs-toggle');
    if (log.style.display === 'none') {
        log.style.display = 'block';
        if (toggle) toggle.textContent = '\u25bc Log de escaneo';
    } else {
        log.style.display = 'none';
        if (toggle) toggle.textContent = '\u25b6 Log de escaneo';
    }
};

window.clearTgindexLogs = function() {
    var log = document.getElementById('scan-log');
    if (log) log.innerHTML = '';
};

function startTgindexLogPolling() {
    if (_tgindex_logs_timer) clearInterval(_tgindex_logs_timer);
    _tgindex_logs_timer = setInterval(function() {
        var log = document.getElementById('scan-log');
        var bar = document.getElementById('scan-progress-bar');
        var status = document.getElementById('scan-status');
        if (!log) { clearInterval(_tgindex_logs_timer); _tgindex_logs_timer = null; return; }
        window.API.ajax({
            url: '/api/user/scan/status',
            success: function(res) {
                if (res.logs && log) {
                    var wasScrolled = (log.scrollTop + log.clientHeight >= log.scrollHeight - 10);
                    log.innerHTML = res.logs.slice(-40).join('\n');
                    if (wasScrolled) log.scrollTop = log.scrollHeight;
                }
                if (bar && res.status === 'scanning') bar.style.width = (res.progress_percent || 0) + '%';
                if (status && res.status === 'scanning') status.textContent = 'Escaneando... ' + (res.progress_percent || 0) + '%';
            }
        });
    }, 2500);
}

window.showPluginInfo = function(name) {
    var plugin = getPluginByName(name);
    if (!plugin) return;
    var container = document.getElementById('plugins-list-container');
    if (!container) return;
    // Config UI personalizada (iframe) si el plugin la define
    if (plugin.settings_ui) {
        container.innerHTML = '<div style="margin-bottom:8px;"><button onclick="loadPluginsList()" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:0.85rem;font-family:Outfit,sans-serif;">\u2190 Volver a lista</button></div><iframe src="' + plugin.settings_ui + '" style="width:100%;min-height:400px;border:none;border-radius:6px;"></iframe>';
        return;
    }
    var html = '<div style="margin-bottom:8px;">' +
        '<button onclick="loadPluginsList()" style="background:none;border:none;color:var(--accent,#e91e63);cursor:pointer;font-size:0.85rem;font-family:Outfit,sans-serif;outline:none;padding:4px 0;">\u2190 Volver</button>' +
        '</div>' +
        '<div style="padding:12px;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border-color);">' +
        '<h3 style="margin-bottom:4px;">' + (plugin.displayName || plugin.name) + '</h3>' +
        '<p style="font-size:0.85rem;color:var(--text-primary);margin:8px 0;line-height:1.4;">' + (plugin.description || 'Sin descripci\u00F3n') + '</p>' +
        '<div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:12px;">' +
        '<div>Tipo: ' + plugin.type + '</div>' +
        '<div>Versi\u00F3n: ' + (plugin.version || plugin.name) + '</div>' +
        (plugin.load_error ? '<div style="color:var(--accent);margin-top:4px;">Error: ' + plugin.load_error + '</div>' : '') +
        '</div>';

    // Renderizar settings_schema si existe
    if (plugin.settings_schema && plugin.settings_schema.length > 0) {
        html += '<div style="border-top:1px solid var(--border-color,rgba(255,255,255,0.1));padding-top:12px;">';
        html += '<div style="font-size:0.9rem;font-weight:600;margin-bottom:10px;">Configuraci\u00F3n</div>';
        for (var si = 0; si < plugin.settings_schema.length; si++) {
            var s = plugin.settings_schema[si];
            var key = plugin.name + '_' + s.id;
            var saved = localStorage.getItem(key);
            var val = saved !== null ? JSON.parse(saved) : s.default;

            if (s.type === 'select' && s.options) {
                html += '<div style="margin-bottom:10px;">';
                html += '<label style="display:block;font-size:0.8rem;font-weight:500;margin-bottom:3px;">' + s.label + '</label>';
                html += '<select id="setting-' + key + '" style="width:100%;padding:12px 42px 12px 16px;border-radius:12px;background:rgba(255,255,255,0.08);color:#fff;border:1px solid rgba(255,255,255,0.15);font-size:0.85rem;font-family:inherit;cursor:pointer;outline:none;appearance:none;-webkit-appearance:none;background-image:url(\'data:image/svg+xml;utf8,<svg xmlns=\\\\\\"http://www.w3.org/2000/svg\\\\\\" width=\\\\\\"16\\\\\\" height=\\\\\\"16\\\\\\" viewBox=\\\\\\"0 0 24 24\\\\\\" fill=\\\\\\"none\\\\\\" stroke=\\\\\\"white\\\\\\" stroke-width=\\\\\\"2\\\\\\"><polyline points=\\\\\\"6 9 12 15 18 9\\\\\\"></polyline></svg>\');background-repeat:no-repeat;background-position:right 16px center;background-size:16px;">';
                for (var oi = 0; oi < s.options.length; oi++) {
                    var opt = s.options[oi];
                    html += '<option value="' + opt.value + '"' + (String(val) === String(opt.value) ? ' selected' : '') + '>' + opt.label + '</option>';
                }
                html += '</select>';
                if (s.description) html += '<div style="font-size:0.72rem;color:var(--text-secondary,#999);margin-top:3px;">' + s.description + '</div>';
                html += '</div>';
            } else if (s.type === 'number') {
                html += '<div style="margin-bottom:10px;">';
                html += '<label style="display:block;font-size:0.8rem;font-weight:500;margin-bottom:3px;">' + s.label + '</label>';
                html += '<input type="number" id="setting-' + key + '" value="' + val + '" min="' + (s.min || 0) + '" max="' + (s.max || 999) + '" style="width:120px;padding:12px 16px;border-radius:12px;background:rgba(255,255,255,0.08);color:#fff;border:1px solid rgba(255,255,255,0.15);font-size:0.85rem;font-family:inherit;outline:none;" />';
                if (s.description) html += '<div style="font-size:0.72rem;color:var(--text-secondary,#999);margin-top:3px;">' + s.description + '</div>';
                html += '</div>';
            } else if (s.type === 'checkbox') {
                html += '<div style="margin-bottom:10px;">';
                html += '<label style="display:flex;align-items:center;gap:6px;font-size:0.8rem;cursor:pointer;">';
                html += '<input type="checkbox" id="setting-' + key + '"' + (val ? ' checked' : '') + ' style="cursor:pointer;" />';
                html += s.label;
                html += '</label>';
                if (s.description) html += '<div style="font-size:0.72rem;color:var(--text-secondary,#999);margin-top:2px;margin-left:22px;">' + s.description + '</div>';
                html += '</div>';
            }
        }
        html += '<button onclick="savePluginSettings(\'' + plugin.name + '\')" style="margin-top:4px;padding:8px 16px;border:none;border-radius:6px;background:var(--accent,#4a9eff);color:#fff;cursor:pointer;font-size:0.85rem;">Guardar configuraci\u00F3n</button>';
        html += '</div>';
    }

    html += '</div>';
    container.innerHTML = html;
};

window.savePluginSettings = function(pluginName) {
    var plugin = getPluginByName(pluginName);
    if (!plugin || !plugin.settings_schema) return;
    for (var si = 0; si < plugin.settings_schema.length; si++) {
        var s = plugin.settings_schema[si];
        var key = plugin.name + '_' + s.id;
        var el = document.getElementById('setting-' + key);
        if (!el) continue;
        var val;
        if (s.type === 'checkbox') {
            val = el.checked;
        } else if (s.type === 'number') {
            val = parseInt(el.value, 10) || s.default;
        } else {
            val = el.value;
        }
        localStorage.setItem(key, JSON.stringify(val));
    }
    // Si es un player, actualizar tvcat_preferred_player para que el cambio sea inmediato
    var modeKey = plugin.name + '_mode';
    var modeVal = localStorage.getItem(modeKey);
    if (modeVal !== null) {
        localStorage.setItem('tvcat_preferred_player', JSON.parse(modeVal));
    }
    alert('Configuraci\u00F3n guardada.');
};

// Drag & Drop para reordenar plugins
var _dragSource = null;

document.addEventListener('dragstart', function(e) {
    var item = e.target.closest('.plugin-item');
    if (item) {
        _dragSource = item;
        item.style.opacity = '0.4';
        e.dataTransfer.effectAllowed = 'move';
    }
});

document.addEventListener('dragover', function(e) {
    var item = e.target.closest('.plugin-item');
    if (item && item !== _dragSource) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
    }
});

document.addEventListener('drop', function(e) {
    var target = e.target.closest('.plugin-item');
    if (target && _dragSource && target !== _dragSource) {
        e.preventDefault();
        var parent = target.parentNode;
        var items = Array.prototype.slice.call(parent.children);
        var srcIdx = items.indexOf(_dragSource);
        var tgtIdx = items.indexOf(target);
        if (srcIdx < tgtIdx) {
            parent.insertBefore(_dragSource, target.nextSibling);
        } else {
            parent.insertBefore(_dragSource, target);
        }
        savePluginOrder();
    }
});

function savePluginOrder() {
    var container = document.getElementById('plugins-list-container');
    if (!container) return;
    var items = container.querySelectorAll('.plugin-item[data-name]');
    var order = [];
    for (var i = 0; i < items.length; i++) {
        var name = items[i].getAttribute('data-name');
        if (name) order.push(name);
    }
    if (order.length === 0) return;
    window.API.ajax({
        method: 'POST',
        url: '/api/plugins/order',
        data: { order: order },
        success: function() {
            // Tambi\u00E9n actualizar decoratorsOrder en pluginSystem
            if (window.pluginSystem) {
                var decorators = [];
                for (var i = 0; i < order.length; i++) {
                    var p = getPluginByName(order[i]);
                    if (p && p.type === 'grid-decorator') {
                        decorators.push(order[i]);
                    }
                }
                window.pluginSystem.setDecoratorOrder(decorators);
            }
        }
    });
}

document.addEventListener('dragend', function(e) {
    var item = e.target.closest('.plugin-item');
    if (item) item.style.opacity = '';
    _dragSource = null;
});

window.togglePlugin = function(name, el) {
    var slider = el ? el.querySelector('.plugin-toggle-slider') : null;
    var isCurrentlyOn = slider ? slider.classList.contains('on') : isPluginEnabled(name);
    if (slider) slider.classList.toggle('on');
    window.API.ajax({
        method: 'POST',
        url: '/api/plugins/toggle',
        data: { name: name },
        success: function(res) {
            if (slider) slider.classList.toggle('on', res.enabled === true);
            if (window.pluginSystem) {
                window.pluginSystem.setPluginEnabled(name, res.enabled === true);
            }
            // Actualizar estado en _pluginListCache
            for (var i = 0; i < _pluginListCache.length; i++) {
                if (_pluginListCache[i].name === name) _pluginListCache[i].enabled = res.enabled === true;
            }
            renderPluginTray();
            if (res.enabled) {
                var plugin = getPluginByName(name);
                if (plugin && ((plugin.js || []).length > 0 || (plugin.css || []).length > 0)) {
                    window.pluginSystem.loadPluginResources([plugin], function() {
                        window.Catalog.load(window.Catalog.currentCategory || 'home');
                    });
                    return;
                }
            }
            window.Catalog.load(window.Catalog.currentCategory || 'home');
        },
        error: function() {
            if (slider) slider.classList.toggle('on', isCurrentlyOn);
            renderPluginTray();
        }
    });
};

function loadAdminUsers() {
    var container = document.getElementById('admin-users-container');
    if (!container) return;
    window.API.ajax({
        url: '/api/auth/me',
        success: function(session) {
            if (session.role !== 'admin') {
                container.innerHTML = '<p style="color:var(--text-secondary);">Solo el admin puede gestionar usuarios</p>';
                return;
            }
            window.API.ajax({ url: '/api/admin/profiles', success: function(pres) {
                var profiles = pres.profiles || [];
                var profHtml = '';
                for (var pi = 0; pi < profiles.length; pi++) {
                    profHtml += '<option value="' + profiles[pi].id + '">' + profiles[pi].name + '</option>';
                }
                window.API.ajax({
                    url: '/api/admin/users',
                    success: function(data) {
                        var users = data.users || [];
                        var html = '<div style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">' +
                            '<input type="text" id="new-username" placeholder="Usuario" style="flex:1;min-width:100px;padding:8px 10px;border-radius:6px;border:1px solid var(--border-color);background:rgba(24,24,27,0.6);color:var(--text-primary);font-size:0.85rem;font-family:Outfit,sans-serif;">' +
                            '<input type="password" id="new-password" placeholder="Contrase\u00F1a" style="flex:1;min-width:100px;padding:8px 10px;border-radius:6px;border:1px solid var(--border-color);background:rgba(24,24,27,0.6);color:var(--text-primary);font-size:0.85rem;font-family:Outfit,sans-serif;">' +
                            '<select id="new-profile" style="padding:8px 10px;border-radius:6px;border:1px solid var(--border-color);background:rgba(24,24,27,0.6);color:var(--text-primary);font-size:0.85rem;">' + profHtml + '</select>' +
                            '<button onclick="openProfilesManager()" title="Gesti\u00F3n de perfiles" style="padding:8px 10px;border-radius:6px;border:1px solid var(--border-color);background:transparent;color:var(--text-primary);cursor:pointer;font-size:0.85rem;font-family:Outfit,sans-serif;line-height:1;">' +
                            '<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor;vertical-align:middle;"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>' +
                            '</button>' +
                            '<button onclick="createUser()" style="padding:8px 16px;border-radius:6px;border:none;background:var(--accent);color:#fff;cursor:pointer;font-family:Outfit,sans-serif;">Crear</button></div>';
                        html += '<div style="display:flex;flex-direction:column;gap:4px;">';
                        for (var i = 0; i < users.length; i++) {
                            var u = users[i];
                            var roleBadge = u.role === 'admin' ? 'style="color:var(--accent);font-weight:600;"' : '';
                            var sel = '<select onchange="assignProfile(' + u.id + ', this)" style="padding:4px 6px;border-radius:4px;border:1px solid var(--border-color);background:rgba(24,24,27,0.6);color:var(--text-primary);font-size:0.78rem;">';
                            for (var pj = 0; pj < profiles.length; pj++) {
                                sel += '<option value="' + profiles[pj].id + '"' + (u.profile_id === profiles[pj].id ? ' selected' : '') + '>' + profiles[pj].name + '</option>';
                            }
                            sel += '</select>';
                            html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--bg-surface);border-radius:6px;border:1px solid var(--border-color);">' +
                                '<div><span ' + roleBadge + '>' + u.username + '</span> <span style="font-size:0.75rem;color:var(--text-secondary);margin-left:6px;">(' + u.role + ')</span></div>' +
                                '<div style="display:flex;align-items:center;gap:8px;">' + sel +
                                (u.role !== 'admin' ? '<button onclick="deleteUser(' + u.id + ',\'' + u.username + '\')" style="padding:4px 10px;border-radius:4px;border:1px solid var(--accent);background:transparent;color:var(--accent);cursor:pointer;font-size:0.8rem;font-family:Outfit,sans-serif;">Eliminar</button>' : '') +
                                '</div></div>';
                        }
                        html += '</div>';
                        container.innerHTML = html;
                    }
                });
            }});
        }
    });
}

window.openProfilesManager = function() {
    window.API.ajax({
        url: '/api/admin/profiles',
        success: function(res) {
            renderProfilesManager(res.profiles || []);
        }
    });
};

function renderProfilesManager(profiles) {
    var ov = document.getElementById('profiles-overlay');
    if (!ov) {
        ov = document.createElement('div');
        ov.id = 'profiles-overlay';
        ov.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.65);z-index:1000;display:flex;align-items:center;justify-content:center;';
        ov.onclick = function(e) { if (e.target === ov) closeProfilesManager(); };
        document.body.appendChild(ov);
    }
    var rows = '';
    for (var i = 0; i < profiles.length; i++) {
        var p = profiles[i];
        var adminTag = p.is_admin ? ' <span style="color:var(--accent);font-size:0.7rem;">(admin)</span>' : '';
        var delBtn = p.is_admin ? '' : '<button onclick="deleteProfile(' + p.id + ')" style="padding:6px 12px;border-radius:6px;border:1px solid var(--accent);background:transparent;color:var(--accent);cursor:pointer;font-size:0.8rem;">Eliminar</button>';
        rows += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
            '<input type="text" id="pf-name-' + p.id + '" value="' + p.name + '" style="flex:1;padding:6px 8px;border-radius:6px;border:1px solid var(--border-color);background:rgba(24,24,27,0.6);color:var(--text-primary);font-size:0.8rem;font-family:Outfit,sans-serif;">' + adminTag +
            '<button onclick="renameProfile(' + p.id + ')" style="padding:6px 12px;border-radius:6px;border:1px solid var(--border-color);background:transparent;color:var(--text-primary);cursor:pointer;font-size:0.8rem;">Guardar</button>' + delBtn +
            '</div>';
    }
    ov.innerHTML = '<div style="background:var(--bg-surface);border:1px solid var(--border-color);border-radius:12px;padding:20px;width:420px;max-width:90%;max-height:80vh;overflow-y:auto;">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">' +
        '<h3 style="margin:0;">Gesti\u00F3n de perfiles</h3>' +
        '<button onclick="closeProfilesManager()" style="background:none;border:none;color:var(--text-secondary);font-size:1.4rem;cursor:pointer;">\u00D7</button></div>' +
        '<div style="font-size:0.78rem;color:var(--text-secondary);margin-bottom:10px;">Cada perfil tiene un c\u00F3digo interno: puedes renombrarlo sin afectar a los usuarios. No se puede eliminar un perfil que tenga usuarios asignados; reas\u00EDgnalos primero.</div>' +
        rows +
        '<div style="display:flex;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border-color);">' +
        '<input type="text" id="pf-new-name" placeholder="Nuevo perfil..." style="flex:1;padding:6px 8px;border-radius:6px;border:1px solid var(--border-color);background:rgba(24,24,27,0.6);color:var(--text-primary);font-size:0.8rem;font-family:Outfit,sans-serif;" onkeydown="if(event.key===\'Enter\')createProfile()">' +
        '<button onclick="createProfile()" style="padding:6px 14px;border-radius:6px;border:1px solid var(--border-color);background:transparent;color:var(--text-primary);cursor:pointer;font-size:0.8rem;">+ A\u00F1adir</button></div>' +
        '<div id="pf-status" style="font-size:0.78rem;color:var(--accent);margin-top:8px;min-height:14px;"></div>' +
        '<div style="display:flex;justify-content:flex-end;margin-top:12px;">' +
        '<button onclick="closeProfilesManager()" style="padding:8px 18px;border-radius:6px;border:none;background:var(--accent);color:#fff;cursor:pointer;font-family:Outfit,sans-serif;">Cerrar</button></div></div>';
    ov.style.display = 'flex';
    var inp = document.getElementById('pf-new-name');
    if (inp) inp.focus();
}

window.closeProfilesManager = function() {
    var ov = document.getElementById('profiles-overlay');
    if (ov) ov.style.display = 'none';
    loadAdminUsers();
};

window.createProfile = function() {
    var name = document.getElementById('pf-new-name');
    if (!name || !name.value.trim()) return;
    window.API.ajax({
        method: 'POST', url: '/api/admin/profiles/create',
        data: { name: name.value.trim() },
        success: function() {
            window.API.ajax({ url: '/api/admin/profiles', success: function(res) { renderProfilesManager(res.profiles || []); } });
        }
    });
};

window.renameProfile = function(id) {
    var inp = document.getElementById('pf-name-' + id);
    if (!inp || !inp.value.trim()) return;
    window.API.ajax({
        method: 'POST', url: '/api/admin/profiles/rename',
        data: { id: id, name: inp.value.trim() },
        success: function() {
            window.API.ajax({ url: '/api/admin/profiles', success: function(res) { renderProfilesManager(res.profiles || []); } });
        }
    });
};

window.deleteProfile = function(id) {
    window.API.ajax({
        method: 'POST', url: '/api/admin/profiles/delete',
        data: { id: id },
        success: function() {
            var st = document.getElementById('pf-status');
            if (st) st.textContent = 'Perfil eliminado';
            window.API.ajax({ url: '/api/admin/profiles', success: function(res) { renderProfilesManager(res.profiles || []); } });
        },
        error: function(status, msg) {
            var st = document.getElementById('pf-status');
            if (st) st.textContent = msg;
        }
    });
};

window.assignProfile = function(userId, el) {
    window.API.ajax({
        method: 'POST', url: '/api/admin/users/assign-profile',
        data: { user_id: userId, profile_id: parseInt(el.value, 10) },
        success: function() {}
    });
};

window.createUser = function() {
    var user = document.getElementById('new-username');
    var pass = document.getElementById('new-password');
    var profile = document.getElementById('new-profile');
    if (!user || !pass || !user.value.trim() || !pass.value) return;
    window.API.ajax({
        method: 'POST',
        url: '/api/admin/users/create',
        data: { username: user.value.trim(), password: pass.value, profile_id: profile ? parseInt(profile.value, 10) : null },
        success: function() {
            user.value = '';
            pass.value = '';
            loadAdminUsers();
        },
        error: function(status, msg) {
            alert('Error: ' + msg);
        }
    });
};

window.deleteUser = function(id, name) {
    if (!confirm('\u00BFEliminar usuario "' + name + '"?')) return;
    window.API.ajax({
        method: 'POST',
        url: '/api/admin/users/delete',
        data: { user_id: id },
        success: function() {
            loadAdminUsers();
        }
    });
};

// --- Build Category Tree ---
var _visTree = [];
var _visAvailable = { plugins: {}, categories: {}, subcategories: {} };
var _treeBuildSeq = 0;

function buildCategoryTree() {
    var container = document.getElementById('categories-tree-container');
    if (!container) return;
    var seq = ++_treeBuildSeq;
    window.API.ajax({
        url: '/api/catalog/visibility',
        success: function(vis) {
            if (seq !== _treeBuildSeq) return;
            if (typeof vis === 'string') { try { vis = JSON.parse(vis); } catch (e) { vis = {}; } }
            window.API.ajax({
                url: '/api/content/available',
                success: function(avail) {
                    if (seq !== _treeBuildSeq) return;
                    if (typeof avail === 'string') { try { avail = JSON.parse(avail); } catch (e) { avail = {}; } }
                    _visAvailable.plugins = avail.plugins || {};
                    _visAvailable.categories = avail.categories || {};
                    _visAvailable.subcategories = avail.subcategories || {};
                    window.API.ajax({
                        url: '/api/catalog/tree',
                        success: function(data) {
                            if (seq !== _treeBuildSeq) return;
                            if (typeof data === 'string') { try { data = JSON.parse(data); } catch (e) { data = null; } }
                            if (!data) {
                                container.innerHTML = '<div style="padding:8px;font-size:0.8rem;color:var(--text-secondary);">Error cargando \u00E1rbol</div>';
                                return;
                            }
                            _visTree = data.tree || [];
                            if (_visTree.length === 0) {
                                container.innerHTML = '<div style="padding:8px;font-size:0.8rem;color:var(--text-secondary);">Sin categor\u00EDas</div>';
                                return;
                            }
                            var html = '';
                            for (var s = 0; s < _visTree.length; s++) {
                                var src = _visTree[s];
                                if (_visAvailable.plugins[src.source] === false) continue;
                                var plugState = visPluginState(src, vis);
                                html += '<div class="tree-source">' +
                                    '<label class="tree-item tree-source-label">' +
                                    '<input type="checkbox" ' + (plugState.checked ? 'checked' : '') + (plugState.indet ? ' data-indet="1"' : '') + ' onchange="toggleSourceVis(\'' + src.source + '\', this)"> ' +
                                    src.source + '</label></div>';
                                for (var c = 0; c < src.categories.length; c++) {
                                    var cat = src.categories[c];
                                    if (_visAvailable.categories[cat.name] === false) continue;
                                    var catState = visCategoryState(cat, vis);
                                    html += '<div style="padding-left:16px;">' +
                                        '<label class="tree-item">' +
                                        '<input type="checkbox" ' + (catState.checked ? 'checked' : '') + (catState.indet ? ' data-indet="1"' : '') + ' onchange="toggleCategoryVis(\'' + cat.name + '\', this)"> ' +
                                        cat.name + '</label></div>';
                                    for (var u = 0; u < cat.subcategories.length; u++) {
                                        var sub = cat.subcategories[u];
                                        var subKey = cat.name + '||' + sub;
                                        if (_visAvailable.subcategories[subKey] === false) continue;
                                        var subChecked = (vis.subcategories || {})[subKey] !== false;
                                        html += '<div style="padding-left:32px;">' +
                                            '<label class="tree-item" style="font-size:0.75rem;">' +
                                            '<input type="checkbox" ' + (subChecked ? 'checked' : '') + ' onchange="toggleSubcategoryVis(\'' + subKey + '\', this)"> ' +
                                            sub + '</label></div>';
                                    }
                                }
                            }
                            container.innerHTML = html;
                            var boxes = container.querySelectorAll('input[type="checkbox"]');
                            for (var b = 0; b < boxes.length; b++) {
                                if (boxes[b].getAttribute('data-indet') === '1') boxes[b].indeterminate = true;
                            }
                        },
                        error: function(s, b) { if (seq === _treeBuildSeq) { console.error('Error cargando /api/catalog/tree:', s, b); container.innerHTML = '<div style="padding:8px;font-size:0.8rem;color:var(--text-secondary);">Error cargando \u00E1rbol</div>'; } }
                    });
                },
                error: function(s, b) { if (seq === _treeBuildSeq) console.error('Error /api/content/available:', s, b); }
            });
        },
        error: function(s, b) { if (seq === _treeBuildSeq) console.error('Error /api/catalog/visibility:', s, b); }
    });
}

function visPluginState(src, vis) {
    vis = vis || {};
    vis.plugins = vis.plugins || {};
    vis.categories = vis.categories || {};
    vis.subcategories = vis.subcategories || {};
    var cats = src.categories || [];
    if (vis.plugins[src.source] === true) return { checked: true, indet: false };
    if (vis.plugins[src.source] === false) return { checked: false, indet: false };
    if (cats.length === 0) return { checked: true, indet: false };
    var hasChecked = false, hasUnchecked = false;
    for (var i = 0; i < cats.length; i++) {
        if (vis.categories[cats[i].name] === false) hasUnchecked = true; else hasChecked = true;
    }
    if (hasChecked && hasUnchecked) return { checked: false, indet: true };
    return { checked: hasChecked, indet: false };
}

function visCategoryState(cat, vis) {
    vis = vis || {};
    vis.categories = vis.categories || {};
    vis.subcategories = vis.subcategories || {};
    if (vis.categories[cat.name] === false) return { checked: false, indet: false };
    if (vis.categories[cat.name] === true) return { checked: true, indet: false };
    var subs = cat.subcategories || [];
    if (subs.length === 0) return { checked: true, indet: false };
    var hasChecked = false, hasUnchecked = false;
    for (var i = 0; i < subs.length; i++) {
        if (vis.subcategories[cat.name + '||' + subs[i]] === false) hasUnchecked = true; else hasChecked = true;
    }
    if (hasChecked && hasUnchecked) return { checked: false, indet: true };
    return { checked: hasChecked, indet: false };
}

function saveVisibility(handler) {
    window.API.ajax({
        url: '/api/catalog/visibility',
        success: function(vis) {
            vis.plugins = vis.plugins || {};
            vis.categories = vis.categories || {};
            vis.subcategories = vis.subcategories || {};
            handler(vis);
            window.API.ajax({
                method: 'POST',
                url: '/api/catalog/visibility',
                data: vis,
                success: function() {
                    buildCategoryTree();
                    if (window.Catalog) window.Catalog.load(window.Catalog.currentCategory || 'home');
                }
            });
        }
    });
}

window.toggleSourceVis = function(source, cb) {
    saveVisibility(function(vis) {
        vis.plugins[source] = cb.checked;
        for (var s = 0; s < _visTree.length; s++) {
            if (_visTree[s].source !== source) continue;
            for (var c = 0; c < _visTree[s].categories.length; c++) {
                var cat = _visTree[s].categories[c];
                vis.categories[cat.name] = cb.checked;
                for (var u = 0; u < cat.subcategories.length; u++) {
                    vis.subcategories[cat.name + '||' + cat.subcategories[u]] = cb.checked;
                }
            }
            break;
        }
    });
};

window.toggleCategoryVis = function(catName, cb) {
    saveVisibility(function(vis) {
        vis.categories[catName] = cb.checked;
        for (var s = 0; s < _visTree.length; s++) {
            for (var c = 0; c < _visTree[s].categories.length; c++) {
                var cat = _visTree[s].categories[c];
                if (cat.name !== catName) continue;
                for (var u = 0; u < cat.subcategories.length; u++) {
                    vis.subcategories[cat.name + '||' + cat.subcategories[u]] = cb.checked;
                }
            }
        }
    });
};

window.toggleSubcategoryVis = function(key, cb) {
    saveVisibility(function(vis) {
        vis.subcategories[key] = cb.checked;
        if (cb.checked) {
            vis.categories[key.split('||')[0]] = true;
        }
    });
};

// --- Mobile Settings (QR, interfaces, DNS) ---

function loadMobileConfig() {
    var listEl = document.getElementById('mobile-iface-list');
    if (!listEl) return;
    window.API.ajax({
        url: '/api/network/interfaces',
        success: function(res) {
            var ifaces = res.interfaces || [];
            var pref = res.preferred || '';
            var dns = res.dns_custom || '';
            var html = '';
            for (var i = 0; i < ifaces.length; i++) {
                var f = ifaces[i];
                var icon = f.type === 'wifi' ? '\ud83d\udcf6' : '\ud83d\udd0c';
                html += '<label style="display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer;font-size:0.85rem;">' +
                    '<input type="radio" name="mobile-ip" value="' + f.ip + '"' + (f.ip === pref ? ' checked' : '') + ' onchange="saveMobilePref(this.value)" style="accent-color:var(--accent);">' +
                    '<span>' + icon + ' ' + f.name + '</span>' +
                    '<span style="color:var(--text-secondary);font-size:0.8rem;">' + f.ip + ':8093</span></label>';
            }
            listEl.innerHTML = html;
            var dnsEl = document.getElementById('mobile-dns-custom');
            if (dnsEl) dnsEl.value = dns;
            updateMobileQR();
        },
        error: function() {
            if (listEl) listEl.innerHTML = '<span style="color:var(--text-secondary);">No se detectaron interfaces.</span>';
        }
    });
    // QR auth toggle
    var authCb = document.getElementById('mobile-qr-auth');
    if (authCb) {
        authCb.checked = localStorage.getItem('tvcat_mobile_qr_auth') === '1';
        authCb.onchange = function() {
            localStorage.setItem('tvcat_mobile_qr_auth', authCb.checked ? '1' : '0');
            updateMobileQR();
        };
    }
}

window.saveMobilePref = function(ip) {
    window.API.ajax({
        method: 'POST',
        url: '/api/mobile/config',
        data: { preferred: ip },
        success: function() { updateMobileQR(); }
    });
};

window.scanNetworkServers = function() {
    var statusEl = document.getElementById('mobile-scan-status');
    var resEl = document.getElementById('mobile-scan-results');
    var portEl = document.getElementById('mobile-scan-port');
    var port = parseInt(portEl ? portEl.value : '8098', 10) || 8098;
    if (statusEl) statusEl.textContent = 'Escaneando red local (puerto ' + port + ')...';
    if (resEl) resEl.innerHTML = '';
    window.API.ajax({
        method: 'POST',
        url: '/api/network/scan',
        data: { port: port },
        success: function(res) {
            var hosts = (res && res.hosts) || [];
            if (statusEl) statusEl.textContent = hosts.length ? hosts.length + ' encontrado(s)' : 'Ninguno';
            if (!resEl) return;
            if (!hosts.length) { resEl.innerHTML = '<span style="color:var(--text-secondary);font-size:0.78rem;">Sin servidores TVCat en la red local (puerto ' + port + ').</span>'; return; }
            var html = '';
            for (var i = 0; i < hosts.length; i++) {
                var h = hosts[i];
                html += '<div style="display:flex;align-items:center;gap:8px;padding:4px 6px;border:1px solid var(--border-color);border-radius:6px;margin-bottom:4px;font-size:0.8rem;">' +
                    '<span>' + h.name + '</span><span style="color:var(--text-secondary);">' + h.ip + ':' + h.port + '</span>' +
                    '<a href="' + h.url + '" style="color:var(--accent);margin-left:auto;text-decoration:none;" target="_blank">Abrir</a></div>';
            }
            resEl.innerHTML = html;
        },
        error: function() { if (statusEl) statusEl.textContent = 'Error al escanear'; }
    });
};

window.testMobileDns = function() {
    var dnsEl = document.getElementById('mobile-dns-custom');
    var statusEl = document.getElementById('mobile-dns-status');
    if (!dnsEl) return;
    var val = dnsEl.value.trim();
    if (!val) { if (statusEl) statusEl.textContent = 'Introduce una URL'; return; }
    if (statusEl) statusEl.textContent = 'Probando...';
    window.API.ajax({
        method: 'POST',
        url: '/api/mobile/config',
        data: { dns_custom: val },
        success: function() {
            window.API.ajax({
                method: 'POST',
                url: '/api/mobile/test-dns',
                data: { url: val },
                success: function(res) {
                    if (statusEl) statusEl.textContent = res && res.success ? '\u2705 Conectado' : ('\u274C ' + (res.error || 'No accesible'));
                    updateMobileQR();
                },
                error: function() { if (statusEl) statusEl.textContent = '\u274C Error'; }
            });
        },
        error: function() { if (statusEl) statusEl.textContent = '\u274C Error al guardar'; }
    });
};

function updateMobileQR() {
    var container = document.getElementById('mobile-qr-container');
    if (!container) return;
    var prefRadio = document.querySelector('input[name="mobile-ip"]:checked');
    var dnsEl = document.getElementById('mobile-dns-custom');
    var useAuth = document.getElementById('mobile-qr-auth');
    useAuth = useAuth ? useAuth.checked : false;
    var base = (dnsEl && dnsEl.value.trim()) ? dnsEl.value.trim().replace(/\/+$/, '') : ('http://' + (prefRadio ? prefRadio.value : '127.0.0.1') + ':8093');
    if (useAuth) {
        // Generar token QR
        window.API.ajax({
            method: 'POST',
            url: '/api/auth/qr-token',
            success: function(res) {
                if (res && res.token) {
                    var url = base + '/?t=' + res.token;
                    container.innerHTML = '<p style="font-size:0.75rem;color:var(--text-secondary);margin-bottom:6px;">' + url + '</p><img src="/api/qr?data=' + encodeURIComponent(url) + '&size=5" style="max-width:200px;border-radius:8px;" alt="QR">';
                } else {
                    container.innerHTML = '<img src="/api/qr?data=' + encodeURIComponent(base) + '&size=5" style="max-width:200px;border-radius:8px;" alt="QR">';
                }
            },
            error: function() {
                container.innerHTML = '<img src="/api/qr?data=' + encodeURIComponent(base) + '&size=5" style="max-width:200px;border-radius:8px;" alt="QR">';
            }
        });
    } else {
        container.innerHTML = '<p style="font-size:0.75rem;color:var(--text-secondary);margin-bottom:6px;">' + base + '</p><img src="/api/qr?data=' + encodeURIComponent(base) + '" style="max-width:240px;border-radius:8px;" alt="QR">';
    }
}

window.changePassword = function() {
    var current = document.getElementById('profile-current-password');
    var newPass = document.getElementById('profile-new-password');
    var confirmPass = document.getElementById('profile-confirm-password');
    if (!current || !newPass || !confirmPass) return;
    if (newPass.value !== confirmPass.value) {
        alert('Las contrase\u00F1as no coinciden');
        return;
    }
    if (newPass.value.length < 4) {
        alert('La contrase\u00F1a debe tener al menos 4 caracteres');
        return;
    }
    window.API.ajax({
        method: 'POST',
        url: '/api/auth/change-password',
        data: { current: current.value, new_password: newPass.value },
        success: function() {
            alert('Contrase\u00F1a cambiada');
            current.value = '';
            newPass.value = '';
            confirmPass.value = '';
        },
        error: function(status, msg) {
            alert('Error: ' + msg);
        }
    });
};

// ─── Administración (Log tail + Reinicio) ───
window.adminLoadLog = function(){
    var ta=document.getElementById("admin-log-textarea");
    if(!ta) return;
    ta.value="Cargando...";
    window.API.ajax({
        url: '/api/admin/log/tail?lines=1000',
        success: function(r){ ta.value=(r.lines||[]).join("\n"); ta.scrollTop=ta.scrollHeight; },
        error: function(s,msg){ ta.value="Error: "+msg; }
    });
};
window.adminRestart = function(isCustom){
    function showCountdownAndReload(){
        var overlay=document.createElement("div");
        overlay.style.cssText="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:999999;font-family:monospace;";
        var msg=document.createElement("div"); msg.textContent="Reiniciando servidor..."; msg.style.cssText="font-size:18px;margin-bottom:12px;";
        var cnt=document.createElement("div"); cnt.style.cssText="font-size:48px;font-weight:700;";
        overlay.appendChild(msg); overlay.appendChild(cnt); document.body.appendChild(overlay);
        var n=10; cnt.textContent=n;
        var iv=setInterval(function(){
            n--; cnt.textContent=n;
            if(n<=0){ clearInterval(iv); location.reload(); }
        }, 1000);
    }
    var cmd=null;
    if(isCustom){
        var inp=document.getElementById("admin-custom-cmd");
        cmd=(inp?inp.value.trim():"")||"docker restart tvcat2";
        if(!confirm("¿Reiniciar con comando custom?\n"+cmd)) return;
        window.API.ajax({ method:'POST', url:'/api/admin/restart-custom', data:{command:cmd}, success:function(){ showCountdownAndReload(); }, error:function(s,msg){ alert("Error: "+msg); } });
    } else {
        if(!confirm("¿Reiniciar servidor Python?")) return;
        window.API.ajax({ method:'POST', url:'/api/admin/restart', data:{}, success:function(){ showCountdownAndReload(); }, error:function(s,msg){ alert("Error: "+msg); } });
    }
};
// ─── Cuenta Google (asociación en el perfil) ───
window.updateGoogleAccountBox = function() {
    var box = document.getElementById('google-account-box');
    if (!box) return;
    window.API.ajax({
        url: '/api/auth/me',
        success: function(s) {
            var linked = !!(s && s.google_email);
            var unlinkBtn = document.getElementById('google-unlink-btn');
            var emailInput = document.getElementById('profile-google-email');
            var linkBtn = box.querySelector('button[onclick*="linkGoogleAccount"]');
            if (linked) {
                if (linkBtn) linkBtn.style.display = 'none';
                if (unlinkBtn) unlinkBtn.style.display = 'inline-block';
                if (emailInput) emailInput.value = s.google_email;
                var st = document.getElementById('google-account-status');
                if (st) st.innerHTML = '<span style="color:#22c55e;">Asociada a: ' + s.google_email + '</span>';
            } else {
                if (linkBtn) linkBtn.style.display = 'inline-block';
                if (unlinkBtn) unlinkBtn.style.display = 'none';
                var st = document.getElementById('google-account-status');
                if (st) st.innerHTML = '';
            }
        }
    });
};

window.linkGoogleEmailManual = function() {
    var input = document.getElementById('profile-google-email');
    var st = document.getElementById('google-account-status');
    var email = input ? input.value.trim() : '';
    if (!email) { if (st) st.innerHTML = '<span style="color:#f87171;">Introduce tu correo Google.</span>'; return; }
    window.API.ajax({
        method: 'POST',
        url: '/api/auth/google/link-email',
        data: { email: email },
        success: function(r) {
            if (r && r.success) {
                if (st) st.innerHTML = '<span style="color:#22c55e;">Correo asociado: ' + r.email + '</span>';
                window.updateGoogleAccountBox();
            }
        },
        error: function(status, msg) {
            if (st) st.innerHTML = '<span style="color:#f87171;">' + msg + '</span>';
        }
    });
};

window.linkGoogleAccount = function() {
    var st = document.getElementById('google-account-status');
    window.API.ajax({
        url: '/api/auth/google/config',
        success: function(cfg) {
            if (!(cfg && cfg.enabled)) {
                if (st) st.innerHTML = '<span style="color:#f87171;">El login con Google no est\u00e1 habilitado (el administrador debe configurar client_id/secret en Ajustes del sistema).</span>';
                return;
            }
            // Redirect directo a Google para asociar la cuenta (vuelve a /api/auth/google/callback con action=link)
            window.location.href = '/api/auth/google/start?action=link';
        },
        error: function() {
            if (st) st.innerHTML = '<span style="color:#f87171;">Error consultando la configuraci\u00f3n de Google.</span>';
        }
    });
};

window.unlinkGoogleAccount = function() {
    window.API.ajax({
        method: 'POST',
        url: '/api/auth/google/unlink',
        success: function() {
            window.updateGoogleAccountBox();
        }
    });
};

window.changeScreenColumns = function(val) {
    if (window.UI && window.UI.changeScreenColumns) {
        window.UI.changeScreenColumns(val);
    } else {
        if (val === 'auto') {
            document.documentElement.style.removeProperty('--grid-columns');
        } else {
            document.documentElement.style.setProperty('--grid-columns', val);
        }
        localStorage.setItem('tvcat_columns', val);
    }
};

function syncNavbarAvatar() {
    var avatarEl = document.getElementById('side-avatar');
    var navBtn = document.getElementById('header-profile-icon');
    if (!navBtn || !avatarEl) return;
    // Copiar el contenido del avatar del sidebar al navbar
    navBtn.innerHTML = avatarEl.innerHTML;
    if (avatarEl.style.background) {
        navBtn.style.background = avatarEl.style.background;
    }
    var headerName = document.getElementById('header-profile-name');
    var sideName = document.getElementById('side-profile-name');
    if (headerName && sideName) headerName.textContent = sideName.textContent || 'Usuario';
}

// --- Restore saved profile on boot ---
function restoreProfile() {
    window.API.ajax({
        url: '/api/config',
        success: function(config) {
            if (!config || !config.display_name) return;
            var nameEl = document.getElementById('side-profile-name');
            if (nameEl && config.display_name) nameEl.textContent = config.display_name;
            var avatarEl = document.getElementById('side-avatar');
            if (avatarEl) {
                if (config.avatar_url) {
                    avatarEl.innerHTML = '<img src="' + config.avatar_url + '" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">';
                } else if (config.avatar) {
                    avatarEl.textContent = config.avatar;
                }
                if (config.color) {
                    avatarEl.style.background = config.color;
                }
            }
            syncNavbarAvatar();
        }
    });
}

// --- Keyboard / TV Remote Control Navigation System ---
function dbgUpdate(fields) {
    try {
        for (var k in fields) {
            var el = document.getElementById('dbg-' + k);
            if (el) el.textContent = fields[k];
        }
    } catch(e) {}
}

function globalKeydownHandler(e) {
    var keyCode = e.keyCode || e.which;
    var digit = window.keyMapper ? window.keyMapper.getVirtualDigit(e) : null;
    var activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : 'none';
    var focusedEl = document.querySelector('.focused');
    var ctx = window.navEngine ? window.navEngine.getActiveContext() : '?';

    dbgUpdate({
        kc: keyCode,
        key: e.key || '?',
        digit: digit !== null ? digit : '\u2014',
        ctx: ctx,
        ae: activeTag + (document.activeElement && document.activeElement.id ? '#' + document.activeElement.id : ''),
        focused: focusedEl ? (focusedEl.className.split(' ')[0] + (focusedEl.id ? '#' + focusedEl.id : '')) : 'ninguno',
        handler: 'recibido'
    });

    if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') {
        if (window.UI && window.UI.isCalibrating) return;
        var key = e.key;
        var isTextarea = (activeTag === 'textarea');
        var isBackKey = (key === 'Escape' || key === 'Backspace' || key === 'Back' || key === 'BrowserBack' || keyCode === 10009 || keyCode === 461);
        if (isBackKey) {
            // En textarea el Backspace debe borrar texto (no actuar como "back")
            var handleBack = (key === 'Escape' || keyCode === 10009 || keyCode === 461 || (activeTag === 'select' && (key === 'Backspace' || key === 'Escape')));
            if (!isTextarea && handleBack) {
                e.preventDefault();
                e.stopPropagation();
                document.activeElement.blur();
                dbgUpdate({ handler: 'back-nativo\u2192' + key });
                if (window.navEngine) window.navEngine.back();
                return;
            }
        }
        // Enter en textarea = salto de línea; en input/select = confirmar (blur)
        if (e.key === 'Enter' && !isTextarea) {
            document.activeElement.blur();
        }
        dbgUpdate({ handler: 'BLOQ:input-nativo' });
        return;
    }

    if (window.UI && window.UI.isCalibrating) {
        dbgUpdate({ handler: 'BLOQ:calibrando' });
        return;
    }

    var getInteractiveAncestor = function(el) {
        if (!el || el === document.body || el === document.documentElement) return null;
        var tag = el.tagName ? el.tagName.toLowerCase() : '';
        if (el.classList && (
            el.classList.contains('grid-item') ||
            el.classList.contains('episode-card') ||
            el.classList.contains('jump-btn') ||
            el.classList.contains('watched-toggle') ||
            el.classList.contains('season-combo') ||
            el.classList.contains('close-btn-mini') ||
            el.classList.contains('close-btn') ||
            tag === 'button' || tag === 'a' || tag === 'select' || tag === 'input'
        )) {
            return el;
        }
        return getInteractiveAncestor(el.parentNode);
    };

    if (digit !== null) {
        e.preventDefault();
        e.stopPropagation();
        dbgUpdate({ handler: 'digit\u2192' + digit });
        handleVirtualDigit(digit);
        return;
    }

    if (ctx === 'player' && e.key === 'Enter') {
        var aeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
        if (aeTag === 'button' || aeTag === 'a' || aeTag === 'input' || aeTag === 'select' || aeTag === 'textarea') {
            dbgUpdate({ handler: 'Enter\u2192player nativo (' + aeTag + ')' });
        } else {
            e.preventDefault();
            e.stopPropagation();
            dbgUpdate({ handler: 'Enter\u2192player play/pause' });
            routePlayerKey('E');
            return;
        }
    }

    var key = e.key;
    var isBackKey = (key === 'Escape' || key === 'Backspace' || key === 'Back' || key === 'BrowserBack' || keyCode === 10009 || keyCode === 461);
    var focusedTag = focusedEl ? focusedEl.tagName.toLowerCase() : '';
    var focusedIsSelect = (focusedTag === 'select');

    if (key === 'ArrowUp' || key === 'ArrowDown' || key === 'ArrowLeft' || key === 'ArrowRight') {
        if (!focusedIsSelect) {
            if (ctx === 'episode_modal' && (key === 'ArrowLeft' || key === 'ArrowRight')) {
                e.preventDefault();
                e.stopPropagation();
                var dir = (key === 'ArrowLeft') ? -1 : 1;
                changeSeasonCycle(dir);
                return;
            }

            e.preventDefault();
            e.stopPropagation();
            dbgUpdate({ handler: 'arrow\u2192' + key });
            if (key === 'ArrowUp') window.navEngine.move('UP');
            else if (key === 'ArrowDown') window.navEngine.move('DOWN');
            else if (key === 'ArrowLeft') window.navEngine.move('LEFT');
            else if (key === 'ArrowRight') window.navEngine.move('RIGHT');
        } else {
            dbgUpdate({ handler: 'arrow\u2192select(nativo)' });
        }
    } else if (key === 'Enter' && focusedEl && !focusedIsSelect) {
        e.preventDefault();
        e.stopPropagation();
        dbgUpdate({ handler: 'Enter\u2192select()' });
        window.navEngine.select();
    } else if (isBackKey) {
        e.preventDefault();
        e.stopPropagation();
        dbgUpdate({ handler: 'back\u2192' + key });
        window.navEngine.back();
    } else {
        dbgUpdate({ handler: 'sin-acci\u00f3n(key=' + key + ')' });
    }
}

function getPositionalLetter(digit, isTVLayout) {
    if (digit === null || digit === undefined) return null;
    var pcMap = {
        '7': 'A', '8': 'B', '9': 'C',
        '4': 'D', '5': 'E', '6': 'F',
        '1': 'G', '2': 'H', '3': 'I',
        '0': 'J'
    };
    var tvMap = {
        '1': 'A', '2': 'B', '3': 'C',
        '4': 'D', '5': 'E', '6': 'F',
        '7': 'G', '8': 'H', '9': 'I',
        '0': 'J'
    };
    return isTVLayout ? tvMap[digit] : pcMap[digit];
}

function changeSeasonCycle(dir) {
    var seasonSelector = document.getElementById('season-selector');
    if (!seasonSelector) return;
    var options = seasonSelector.options;
    if (!options || options.length <= 1) return;
    var currentIndex = seasonSelector.selectedIndex;
    var newIndex = currentIndex + dir;
    if (newIndex < 0) newIndex = 0;
    if (newIndex >= options.length) newIndex = options.length - 1;
    if (newIndex !== currentIndex) {
        seasonSelector.selectedIndex = newIndex;
        if (window.Catalog && typeof window.Catalog.onSeasonChange === 'function') {
            window.Catalog.onSeasonChange();
        }
    }
}

function handleVirtualDigit(digit) {
    var context = window.navEngine.getActiveContext();
    var isTVLayout = window.keyMapper.getProfileType() === 'custom';
    var position = getPositionalLetter(digit, isTVLayout);
    if (!position) return;

    if (context === 'player') {
        routePlayerKey(position);
        return;
    }

    if (context === 'episode_modal') {
        if (position === 'I') {
            var focusedEl = document.querySelector('.focused');
            if (focusedEl && focusedEl.classList.contains('episode-card')) {
                var eyeBtn = focusedEl.querySelector('.watched-toggle');
                if (eyeBtn) eyeBtn.click();
                return;
            }
        }
        if (position === 'D') {
            changeSeasonCycle(-1);
            return;
        }
        if (position === 'F') {
            changeSeasonCycle(1);
            return;
        }
    }

    if (position === 'C' && (context === 'catalog' || context === 'side_menu')) {
        if (typeof window.toggleSideMenu === 'function') {
            window.toggleSideMenu();
            return;
        }
    }

    if (position === 'B') {
        window.navEngine.move('UP');
    } else if (position === 'H') {
        window.navEngine.move('DOWN');
    } else if (position === 'D') {
        window.navEngine.move('LEFT');
    } else if (position === 'F') {
        window.navEngine.move('RIGHT');
    } else if (position === 'E') {
        window.navEngine.select();
    } else if (position === 'J') {
        window.navEngine.back();
    }
}

function toggleFullscreen() {
    var playerModal = document.getElementById('player-modal');
    var videoEl = document.getElementById('tvcat-video-player');
    if (!playerModal) return;

    var isFs = !!(document.fullscreenElement || document.webkitFullscreenElement ||
                  document.mozFullScreenElement || document.msFullscreenElement);

    if (isFs) {
        if (document.exitFullscreen) document.exitFullscreen();
        else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
        else if (document.mozCancelFullScreen) document.mozCancelFullScreen();
        else if (document.msExitFullscreen) document.msExitFullscreen();
    } else {
        if (playerModal.requestFullscreen) {
            playerModal.requestFullscreen();
        } else if (playerModal.webkitRequestFullscreen) {
            playerModal.webkitRequestFullscreen();
        } else if (playerModal.mozRequestFullScreen) {
            playerModal.mozRequestFullScreen();
        } else if (playerModal.msRequestFullscreen) {
            playerModal.msRequestFullscreen();
        } else if (videoEl) {
            if (videoEl.webkitRequestFullscreen) videoEl.webkitRequestFullscreen();
            else if (videoEl.requestFullscreen) videoEl.requestFullscreen();
        }
    }
}

// --- Boot Sequence ---
document.addEventListener('DOMContentLoaded', function() {
    var bootEl = document.getElementById('boot-screen');

    // Capturar token de URL (fallback Smart TV sin cookies)
    (function() {
        var search = window.location.search;
        if (search) {
            var match = search.match(/[?&]t=([^&]*)/);
            if (match) {
                var t = decodeURIComponent(match[1]);
                try { localStorage.setItem('tvcat_token', t); } catch(e) {}
                if (window.history && window.history.replaceState) {
                    window.history.replaceState({}, '', '/');
                }
            }
        }
    })();

    // 1. Verificar autenticaci\u00F3n
    window.API.ajax({
        url: '/api/auth/me',
        success: function(session) {
            if (!session.logged_in) {
                window.location.href = '/login';
                return;
            }

            // Actualizar sidebar con info del usuario
            updateSidebarUser(session);

            // 2. Cargar traducciones
            window.xTranslate.load(function() {
                // 3. Obtener plugins
            window.API.getPlugins(function(data) {
                var allPlugins = data.plugins || [];
                // Solo cargar JS/CSS de plugins habilitados
                var enabledPlugins = [];
                for (var pi = 0; pi < allPlugins.length; pi++) {
                    if (allPlugins[pi].enabled) {
                        enabledPlugins.push(allPlugins[pi]);
                    }
                }

                // 4. Cargar recursos de plugins habilitados
                window.pluginSystem.loadPluginResources(enabledPlugins, function() {
                    // 5. Cargar orden guardado de plugins
                    window.API.ajax({
                        url: '/api/plugins/order',
                        success: function(orderData) {
                            applyPluginOrder(orderData.order || [], allPlugins);
                            initApp();
                        },
                        error: function() {
                            initApp();
                        }
                    });
                });
                });
            });
        },
        error: function() {
            window.location.href = '/login';
        }
    });

    function applyPluginOrder(savedOrder, allPlugins) {
        if (savedOrder.length === 0) return;
        var ordered = [];
        var unordered = [];
        for (var i = 0; i < allPlugins.length; i++) {
            var idx = savedOrder.indexOf(allPlugins[i].name);
            if (idx >= 0) {
                ordered[idx] = allPlugins[i];
            } else {
                unordered.push(allPlugins[i]);
            }
        }
        allPlugins.length = 0;
        Array.prototype.push.apply(allPlugins, ordered.filter(Boolean).concat(unordered));
        _pluginListCache = allPlugins;
        if (window.pluginSystem) {
            // Aplicar el orden a getPluginsByType (lista de reproductores, acciones, etc.)
            window.pluginSystem.setPluginOrder(savedOrder);
            var decorators = [];
            for (var i = 0; i < savedOrder.length; i++) {
                for (var j = 0; j < allPlugins.length; j++) {
                    if (allPlugins[j].name === savedOrder[i] && allPlugins[j].type === 'grid-decorator') {
                        decorators.push(savedOrder[i]);
                        break;
                    }
                }
            }
            window.pluginSystem.setDecoratorOrder(decorators);
        }
    }

    function updateSidebarUser(session) {
        var avatar = document.getElementById('side-avatar');
        var nameEl = document.getElementById('side-profile-name');
        if (avatar) avatar.textContent = (session.username || 'U').charAt(0).toUpperCase();
        if (nameEl) nameEl.textContent = session.username || 'Usuario';
    }

    function initApp() {
        if (bootEl) bootEl.classList.add('hidden');

        // Cerrar el panel lateral al tocar/hacer clic fuera de él
        // (cubre ratón, táctil y mando; solo cierra, nunca abre)
        var closeSideMenuOnOutside = function(e) {
            var menu = document.getElementById('side-menu');
            if (!menu || !menu.classList.contains('open')) return;
            var target = e.target;
            if (target && menu.contains(target)) return;
            var trigger = document.querySelector('.profile-header-btn');
            if (trigger && target && trigger.contains(target)) return;
            toggleSideMenu();
        };
        document.addEventListener('click', closeSideMenuOnOutside);
        document.addEventListener('touchend', closeSideMenuOnOutside);

        // Construir \u00E1rbol de categor\u00EDas
        buildCategoryTree();

        // Renderizar botones de tray de plugins (panel izquierdo)
        renderPluginTray();

        // Cerrar modal de detalle al hacer clic fuera del contenido
        var detailModal = document.getElementById('detail-modal');
        if (detailModal) {
            detailModal.addEventListener('click', function(e) {
                if (e.target === detailModal) {
                    var content = detailModal.querySelector('.detail-content');
                    if (content) {
                        var rect = content.getBoundingClientRect();
                        if (e.clientX >= rect.left && e.clientX <= rect.right &&
                            e.clientY >= rect.top && e.clientY <= rect.bottom) {
                            return;
                        }
                    }
                    if (typeof window.closeDetails === 'function') {
                        window.closeDetails();
                    }
                }
            });
        }

        // Restaurar perfil guardado
        restoreProfile();
        // Restaurar columnas
        if (window.UI && window.UI.applyScreenColumns) {
            var savedCols = localStorage.getItem('tvcat_grid_columns') || 'auto';
            window.UI.applyScreenColumns(savedCols);
        }

        // Restaurar preferencia de posición del avatar
        if (window.UI && window.UI.applyAvatarRight) {
            window.UI.applyAvatarRight();
        }

        // Inicializar navegaci\u00F3n espacial
        if (window.navEngine) {
            window.navEngine.init();
            // Enfocar primer item despu\u00E9s de cargar cat\u00E1logo
            var origLoad = window.Catalog.load;
            window.Catalog.load = function(cat) {
                origLoad.call(window.Catalog, cat);
                setTimeout(function() {
                    var searchInput = document.getElementById('global-search');
                    // No robar foco si el usuario est\u00E1 escribiendo en el buscador
                    if (searchInput && document.activeElement === searchInput) return;
                    var first = document.querySelector('.grid-item');
                    if (first && window.navEngine) {
                        window.navEngine.focus(first);
                    }
                }, 200);
            };
        }

        // Restaurar estado de b\u00FAsqueda (texto y filtros)
        loadSearchState();

        // Restaurar \u00FAltima secci\u00F3n si est\u00E1 activada la preferencia
        var openLastSection = localStorage.getItem('tvcat_open_last_section') !== 'false';
        var lastSection = localStorage.getItem('tvcat_last_section');
        if (openLastSection && lastSection && lastSection !== 'home') {
            var menuLink = document.querySelector('.side-menu-nav a[data-category="' + lastSection + '"]');
            if (menuLink) menuLink.classList.add('active');
            window.Catalog.currentCategory = lastSection;
        }

        // Cargar cat\u00E1logo inicial y ejecutar b\u00FAsqueda si hay texto guardado
        var savedSearchText = (document.getElementById('global-search') || {}).value || '';
        if (savedSearchText.trim().length >= 2) {
            window.Catalog.performSearch(savedSearchText.trim());
        } else if (openLastSection && lastSection && lastSection !== 'home') {
            if (lastSection === 'favorites') {
                loadFavorites();
            } else if (lastSection === 'continue') {
                loadContinueWatching();
            } else if (lastSection === 'completed') {
                loadCompleted();
            } else {
                window.Catalog.load(lastSection);
            }
        } else {
            window.Catalog.load('home');
        }

        console.log('[TVCAT2] App lista');

        // Polling del estado de reconstrucción de la caché central (arranque asíncrono).
        // Si la reconstrucción aún está en curso cuando la web ya cargó, se refresca el catálogo al terminar.
        (function pollRebuild() {
            if (!window.API || !window.API.ajax) return;
            window.API.ajax({
                url: '/api/cache/rebuild-status',
                success: function(res) {
                    if (res && res.running) {
                        setTimeout(pollRebuild, 1500);
                    } else if (res && res.done) {
                        if (typeof window.refreshCatalog === 'function') window.refreshCatalog();
                    }
                },
                error: function() { /* no reintentar si el endpoint no está disponible */ }
            });
        })();

        // Registrar el manejador global de teclado en window y document para soporte Smart TV fullscreen
        window.addEventListener('keydown', globalKeydownHandler, true);
        document.addEventListener('keydown', globalKeydownHandler, true);
    }
});
