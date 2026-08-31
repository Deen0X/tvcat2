// Polyfill de Array.prototype.indexOf para navegadores antiguos de SmartTV
if (!Array.prototype.indexOf) {
    Array.prototype.indexOf = function(elt /*, from*/) {
        var len = this.length >>> 0;
        var from = Number(arguments[1]) || 0;
        from = (from < 0) ? Math.ceil(from) : Math.floor(from);
        if (from < 0) from += len;
        for (; from < len; from++) {
            if (from in this && this[from] === elt) return from;
        }
        return -1;
    };
}

(function() {
    var activeElement = null;
    var focusObserver = null;

    var navEngine = {
        FOCUS_CLASS: 'focused', // Reusar clase existente de TVCat

        init: function() {
            this.injectGlobalStyles();
            this.startFocusObserver();
        },

        injectGlobalStyles: function() {
            if (document.getElementById('tflix-nav-styles')) return;
            var styles = document.createElement('style');
            styles.id = 'tflix-nav-styles';
            styles.innerHTML = '\
                .' + this.FOCUS_CLASS + ' {\
                    outline: 3px solid #e11d48 !important;\
                    border-color: #e11d48 !important;\
                    background-color: rgba(225, 29, 72, 0.15) !important;\
                    box-shadow: 0 0 15px rgba(225, 29, 72, 0.6) !important;\
                    transform: scale(1.04) !important;\
                    transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.2s ease !important;\
                    z-index: 50 !important;\
                }\
                .grid-item, .btn-primary, .btn-dark, .episode-card, .profile-header-btn, .settings-input, .tab-btn {\
                    transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), outline 0.15s ease, box-shadow 0.15s ease;\
                }\
            ';
            document.head.appendChild(styles);
        },

        startFocusObserver: function() {
        },

        applyProfileColorToFocused: function() {
            var focused = document.querySelector('.' + this.FOCUS_CLASS);
            if (!focused) return;
            var sideProfileIcon = document.getElementById('side-profile-icon');
            var profileColor = '#e11d48';
            if (sideProfileIcon && sideProfileIcon.style.backgroundColor) {
                profileColor = sideProfileIcon.style.backgroundColor;
            }
            focused.style.outlineColor = profileColor;
            focused.style.setProperty('outline-color', profileColor, 'important');
            focused.style.boxShadow = '0 0 15px ' + profileColor;
        },

        getActiveContext: function() {
            var playerModal = document.getElementById('player-modal');
            var settingsModal = document.getElementById('settings-modal');
            var episodesModal = document.getElementById('episodes-modal');
            var detailModal = document.getElementById('detail-modal');
            var sideMenu = document.getElementById('side-menu');

            if (playerModal && !playerModal.classList.contains('hidden')) return 'player';
            if (settingsModal && !settingsModal.classList.contains('hidden')) return 'settings_modal';
            if (episodesModal && !episodesModal.classList.contains('hidden')) return 'episode_modal';
            if (detailModal && !detailModal.classList.contains('hidden')) return 'detail_modal';
            if (sideMenu && sideMenu.classList.contains('open')) return 'side_menu';
            return 'catalog';
        },

        getFocusableElements: function() {
            var context = this.getActiveContext();
            var selector = '';
            switch (context) {
                case 'settings_modal':
                    selector = '#settings-modal .tab-btn, #settings-modal input, #settings-modal select, #settings-modal button:not([disabled])';
                    break;
                case 'player':
                    // Controles custom del reproductor (incluye rama basic con botones inline)
                    selector = '#player-modal button, #player-modal .side-controls button';
                    break;
                case 'episode_modal':
                    selector = '#episodes-modal .episode-card, #episodes-modal .close-btn-mini';
                    break;
                case 'detail_modal':
                    selector = '#detail-modal .hero-actions button, #detail-modal .close-btn';
                    break;
                case 'side_menu':
                    selector = '#side-menu a, #side-menu button, #side-menu .close-menu';
                    break;
                case 'catalog':
                default:
                    // Priorizar los items de catálogo (.grid-item) sobre el perfil (excluyendo el buscador superior para evitar trampas con el mando)
                    var items = Array.prototype.slice.call(document.querySelectorAll('#catalog-container .grid-item'));
                    var others = Array.prototype.slice.call(document.querySelectorAll('#header-profile-btn'));
                    var elements = items.concat(others);
                    return elements.filter(function(el) {
                        var style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        
                        // Si es un item del catálogo principal, siempre considerarlo navegable
                        if (el.classList.contains('grid-item')) return true;

                        var rect = el.getBoundingClientRect();
                        return (rect.width > 0 && rect.height > 0) || (el.offsetWidth > 0 || el.offsetHeight > 0);
                    });
            }
            return Array.prototype.slice.call(document.querySelectorAll(selector)).filter(function(el) {
                var style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;

                // Si es un elemento principal de episodios, siempre considerarlo navegable
                if (el.classList.contains('episode-card')) return true;

                var rect = el.getBoundingClientRect();
                return (rect.width > 0 && rect.height > 0) || (el.offsetWidth > 0 || el.offsetHeight > 0);
            });
        },

        focus: function(el) {
            var self = this;
            if (!el || !document.body.contains(el)) return;
            if (el === document.body || el === document.documentElement || el.id === 'catalog-container') return;
            var oldFocused = document.querySelectorAll('.' + self.FOCUS_CLASS);
            for (var i = 0; i < oldFocused.length; i++) {
                var node = oldFocused[i];
                node.classList.remove(self.FOCUS_CLASS);
                node.style.outline = '';
                node.style.boxShadow = '';
            }
            activeElement = el;
            el.classList.add(self.FOCUS_CLASS);
            try {
                if (typeof el.focus === 'function') {
                    el.focus();
                }
            } catch(e) {}

            // Evitar scroll forzado en elementos dentro de modales (evita que la pantalla se desplace hacia arriba en SmartTVs)
            var isInsideModal = false;
            var isEpisodeCard = false;
            var parent = el.parentNode;
            while (parent && parent !== document.body) {
                if (parent.classList && parent.classList.contains('episode-card')) {
                    isEpisodeCard = true;
                }
                if (parent.classList && (parent.classList.contains('modal') || parent.id === 'side-menu')) {
                    isInsideModal = true;
                    break;
                }
                parent = parent.parentNode;
            }

            if (isInsideModal) {
                // Si es una tarjeta de episodio, desplazar programáticamente solo su contenedor #episodes-list
                if (el.classList.contains('episode-card') || isEpisodeCard) {
                    var card = el.classList.contains('episode-card') ? el : el.closest('.episode-card');
                    var container = document.getElementById('episodes-list');
                    if (card && container) {
                        var containerRect = container.getBoundingClientRect();
                        var cardRect = card.getBoundingClientRect();
                        
                        if (cardRect.bottom > containerRect.bottom) {
                            container.scrollTop += (cardRect.bottom - containerRect.bottom) + 10;
                        } else if (cardRect.top < containerRect.top) {
                            container.scrollTop -= (containerRect.top - cardRect.top) + 10;
                        }
                    }
                }
            } else {
                // Elementos normales del catálogo principal: usar scrollIntoView seguro
                try {
                    if (typeof el.scrollIntoView === 'function') {
                        el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
                    }
                } catch (scrollErr) {
                    try {
                        el.scrollIntoView(false);
                    } catch (e2) {}
                }
            }
            self.applyProfileColorToFocused();
        },

        move: function(direction) {
            var elements = this.getFocusableElements();
            if (elements.length === 0) return;

            // Sincronizar activeElement dinámicamente con el DOM para evitar desincronizaciones por ratón/puntero
            var focusedNode = document.querySelector('.' + this.FOCUS_CLASS);
            if (focusedNode) {
                activeElement = focusedNode;
            } else if (document.activeElement && document.activeElement !== document.body) {
                activeElement = document.activeElement;
            }

            var activeIndex = -1;
            if (activeElement) {
                for (var k = 0; k < elements.length; k++) {
                    if (elements[k] === activeElement) {
                        activeIndex = k;
                        break;
                    }
                }
            }

            if (activeIndex === -1) {
                this.focus(elements[0]);
                return;
            }
            var currRect = activeElement.getBoundingClientRect();
            var currX = currRect.left + currRect.width / 2;
            var currY = currRect.top + currRect.height / 2;

            var bestCandidate = null;
            var bestScore = Infinity;
            var WEIGHT = 3.5;

            for (var i = 0; i < elements.length; i++) {
                var target = elements[i];
                if (target === activeElement) continue;
                var tgtRect = target.getBoundingClientRect();
                var tgtX = tgtRect.left + tgtRect.width / 2;
                var tgtY = tgtRect.top + tgtRect.height / 2;
                var dX = tgtX - currX;
                var dY = tgtY - currY;
                var isHeadingCorrectDirection = false;
                var score = 0;

                switch (direction) {
                    case 'UP':
                        if (dY < -5) { isHeadingCorrectDirection = true; score = Math.sqrt(Math.pow(dX * WEIGHT, 2) + Math.pow(dY, 2)); }
                        break;
                    case 'DOWN':
                        if (dY > 5) { isHeadingCorrectDirection = true; score = Math.sqrt(Math.pow(dX * WEIGHT, 2) + Math.pow(dY, 2)); }
                        break;
                    case 'LEFT':
                        if (dX < -5) { isHeadingCorrectDirection = true; score = Math.sqrt(Math.pow(dX, 2) + Math.pow(dY * WEIGHT, 2)); }
                        break;
                    case 'RIGHT':
                        if (dX > 5) { isHeadingCorrectDirection = true; score = Math.sqrt(Math.pow(dX, 2) + Math.pow(dY * WEIGHT, 2)); }
                        break;
                }
                if (isHeadingCorrectDirection && score < bestScore) {
                    bestScore = score;
                    bestCandidate = target;
                }
            }
            if (bestCandidate) this.focus(bestCandidate);
        },

        select: function() {
            if (activeElement) activeElement.click();
        },

        back: function() {
            var context = this.getActiveContext();
            switch (context) {
                case 'settings_modal':
                    if (typeof window.toggleSettingsModal === 'function') {
                        window.toggleSettingsModal();
                    }
                    break;
                case 'episode_modal':
                    if (window.Catalog && typeof window.Catalog.closeEpisodesModal === 'function') {
                        window.Catalog.closeEpisodesModal();
                    }
                    break;
                case 'detail_modal':
                    if (typeof window.closeDetails === 'function') {
                        window.closeDetails();
                    }
                    break;
                case 'side_menu':
                    if (typeof window.toggleSideMenu === 'function') {
                        window.toggleSideMenu();
                    }
                    break;
            }
        }
    };

    // Expose globally
    window.navEngine = navEngine;
})();
