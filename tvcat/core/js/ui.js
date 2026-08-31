// TVCat UI Management Helper
window.getSVGIcon = function(emoji, size, color) {
    if (!size) size = 20;
    if (!color) color = 'currentColor';
    // Remove variation selector if present
    var cleanEmoji = emoji;
    if (typeof emoji === 'string') {
        cleanEmoji = emoji.replace(/[\uFE00-\uFE0F]/g, '');
    }
    var svgStyle = 'style="width:' + size + 'px; height:' + size + 'px; vertical-align: middle; fill:' + color + ';"';
    
    // User / profile 👤
    if (cleanEmoji === '👤') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>';
    }
    // Popcorn 🍿
    if (cleanEmoji === '🍿') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M7 2h10l1 5h-12z M5 9l.5 13h13l.5-13h-14z M9 11v8h2v-8h-2z M13 11v8h2v-8h-2z"/></svg>';
    }
    // Clapperboard 🎬
    if (cleanEmoji === '🎬') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/></svg>';
    }
    // Game controller 🎮
    if (cleanEmoji === '🎮') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M21.58 16c-.57-2.18-2.03-3.99-4.1-4.99L17 11H7l-.48.01c-2.07 1-3.53 2.81-4.1 4.99-.3 1.15.26 2.33 1.3 2.77l1.79.75c1.01.42 2.16-.06 2.59-1.07L9.3 16h5.4l1.22 2.46c.43 1.01 1.58 1.49 2.59 1.07l1.79-.75c1.04-.44 1.6-1.62 1.3-2.77z M7 15H5v-2h2v2zm3-3H9v3H8v-3H7v-1h3v1z M15 15h-2v-2h2v2zm3-3h-2v-1h2v1z"/></svg>';
    }
    // Stack of books 📚
    if (cleanEmoji === '📚') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H8V4h12v12z"/></svg>';
    }
    // Television 📺
    if (cleanEmoji === '📺') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M21 6h-7.59l3.29-3.29L16 2l-4 4-4-4-.71.71L10.59 6H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 14H3V8h18v12z"/></svg>';
    }
    // Headphones 🎧
    if (cleanEmoji === '🎧') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 2c-4.97 0-9 4.03-9 9v7c0 1.66 1.34 3 3 3h3v-8H5v-2c0-3.87 3.13-7 7-7s7 3.13 7 7v2h-4v8h3c1.66 0 3-1.34 3-3v-7c0-4.97-4.03-9-9-9z"/></svg>';
    }
    // Alien invader 👾
    if (cleanEmoji === '👾') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z"/></svg>';
    }
    // Cat face 🐱
    if (cleanEmoji === '🐱') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 3c-4.97 0-9 4.03-9 9 0 2.12.74 4.07 1.97 5.61L4.35 19.4c-.39.39-.39 1.02 0 1.41.39.39 1.02.39 1.41 0l1.9-1.9C9.07 19.62 10.47 20 12 20c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-3 9c-.83 0-1.5-.67-1.5-1.5S8.17 9 9 9s1.5.67 1.5 1.5S9.83 12 9 12zm6 0c-.83 0-1.5-.67-1.5-1.5S14.17 9 15 9s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/></svg>';
    }
    // Rocket 🚀
    if (cleanEmoji === '🚀') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 2s-3 3-3 8v3l-3 3v2h6v2h2v-2h6v-2l-3-3V10c0-5-3-8-3-8zm-1.5 7c-.83 0-1.5-.67-1.5-1.5S9.67 6 10.5 6s1.5.67 1.5 1.5S11.33 9 10.5 9z"/></svg>';
    }
    // Flame 🔥
    if (cleanEmoji === '🔥') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M13.5.67s.74 2.65.74 4.8c0 2.06-1.35 3.73-3.41 3.73-2.07 0-3.63-1.67-3.63-3.73C7.2 2.5 9 2.5 9 2.5S7.5 4.67 7.5 6c0 1.25.94 2 1.88 2s1.87-.75 1.87-2c0-2-.31-3.67-.31-3.67s2.5 1.5 3.44 3.67C15.2 7.75 15.5 9.75 15.5 11c0 3.31-2.69 6-6 6s-6-2.69-6-6c0-2.5 1.5-4.5 1.5-4.5S3.5 8 3.5 11c0 4.42 3.58 8 8 8s8-3.58 8-8c0-3.5-3-5.5-3-5.5s-1.5 1.5-3 5.5z"/></svg>';
    }
    // Party popper / Star 🎉 / ⭐
    if (cleanEmoji === '🎉' || cleanEmoji === '★' || cleanEmoji === '⭐') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/></svg>';
    }
    // Box/Other 📦
    if (cleanEmoji === '📦') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm-5 10H9v-2h6v2zm5-5H4V7h16v2z"/></svg>';
    }
    // Home 🏠
    if (cleanEmoji === '🏠') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>';
    }
    // Heart ❤️
    if (cleanEmoji === '❤️' || cleanEmoji === '♥') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>';
    }
    // Folder 🗂️
    if (cleanEmoji === '🗂' || cleanEmoji === '🗂️' || cleanEmoji === '📁') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>';
    }
    // Gear ⚙️
    if (cleanEmoji === '⚙' || cleanEmoji === '⚙️') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>';
    }
    // Sync 🔄
    if (cleanEmoji === '🔄') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M19 8l-4 4h3c0 3.31-2.69 6-6 6-1.01 0-1.97-.25-2.8-.7l-1.46 1.46C8.97 19.54 10.43 20 12 20c4.42 0 8-3.58 8-8h3l-4-4zM6 12c0-3.31 2.69-6 6-6 1.01 0 1.97.25 2.8.7l1.46-1.46C15.03 4.46 13.57 4 12 4c-4.42 0-8 3.58-8 8H1l4 4 4-4H6z"/></svg>';
    }
    // Logout 🚪
    if (cleanEmoji === '🚪') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M10.09 15.59L11.5 17l5-5-5-5-1.41 1.41L12.67 11H3v2h9.67l-2.58 2.59zM19 3H5c-1.11 0-2 .9-2 2v4h2V5h14v14H5v-4H3v4c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/></svg>';
    }
    // Search 🔍
    if (cleanEmoji === '🔍') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>';
    }
    // Lock 🔒
    if (cleanEmoji === '🔒') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>';
    }
    // Screen 🖥️
    if (cleanEmoji === '🖥' || cleanEmoji === '🖥&ufe0f;' || cleanEmoji === '🖥️') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M21 2H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h7l-2 3v1h8v-1l-2-3h7c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 12H3V4h18v10z"/></svg>';
    }
    // Users 👥
    if (cleanEmoji === '👥') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>';
    }
    // Key 🔑
    if (cleanEmoji === '🔑') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12.65 10C11.83 7.67 9.61 6 7 6c-3.31 0-6 2.69-6 6s2.69 6 6 6c2.61 0 4.83-1.67 5.65-4H17v4h4v-4h2v-4H12.65zM7 14c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>';
    }
    // Plus ➕
    if (cleanEmoji === '➕') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>';
    }
    // Open Book 📖
    if (cleanEmoji === '📖') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 11.55C9.64 9.35 6.48 8 3 8v11c3.48 0 6.64 1.35 9 3.55 2.36-2.2 5.52-3.55 9-3.55V8c-3.48 0-6.64 1.35-9 3.55zM12 8c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3z"/></svg>';
    }
    // Globe 🌐
    if (cleanEmoji === '🌐') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.53c-.26-.81-1-1.4-1.9-1.4h-1v-3c0-.55-.45-1-1-1h-6v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.4z"/></svg>';
    }
    // Mailbox 📭
    if (cleanEmoji === '📭') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm-2 0l-8 5-8-5h16zm0 12H4V8l8 5 8-5v10z"/></svg>';
    }
    // Cross ❌
    if (cleanEmoji === '❌') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>';
    }
    // Download/Cloud 📥
    if (cleanEmoji === '📥') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM17 13l-5 5-5-5h3V9h4v4h3z"/></svg>';
    }
    // Link 🔗
    if (cleanEmoji === '🔗') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>';
    }
    // Clipboard/List 📋
    if (cleanEmoji === '📋') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1c-1.3 0-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm5 14H7v-2h10v2zm0-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>';
    }
    // Telegram Send 📨 / 📤 / ✈️
    if (cleanEmoji === '📨' || cleanEmoji === '📤' || cleanEmoji === '✈️' || cleanEmoji === '✈' || cleanEmoji === '📨️') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
    }
    // Play ▶
    if (cleanEmoji === '▶' || cleanEmoji === '▷') {
        return '<svg viewBox="0 0 24 24" class="svg-icon" ' + svgStyle + '><path d="M8 5v14l11-7z"/></svg>';
    }
    
    // Fallback: simple text character or emoji itself
    return cleanEmoji;
};

var UI = {
    selectedAvatar: '👤',
    selectedColor: '#e11d48',
    avatarPresets: ['👤', '🍿', '🎬', '🎮', '📚', '📺', '🎧', '👾', '🐱', '🚀', '🔥', '🎉'],
    colorPresets: ['#e11d48', '#2563eb', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#4f46e5', '#db2777', '#ea580c', '#65a30d', '#27272a', '#1e293b'],

    // --- PROPIEDADES DE CALIBRACIÓN DE MANDO ---
    isCalibrating: false,
    currentCalibratingDigitIndex: 0,
    calibrationDigits: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    calibrationHandlerRef: null,

    // Alternar menú lateral
    toggleSideMenu: function() {
        var menu = document.getElementById('side-menu');
        var overlay = document.getElementById('menu-overlay');
        if (menu && overlay) {
            var opening = !menu.classList.contains('open');
            menu.classList.toggle('open');
            overlay.classList.toggle('open');
            
            if (opening) {
                // Guardar el elemento enfocado previamente
                this.lastFocusedCatalogItem = document.querySelector('#catalog-container .grid-item.focused') || document.activeElement;
                
                // Forzar enfoque en el primer link o botón del menú
                setTimeout(function() {
                    var firstEl = menu.querySelector('a, button');
                    if (firstEl && window.navEngine && typeof window.navEngine.focusElement === 'function') {
                        window.navEngine.focusElement(firstEl);
                    }
                }, 100);
            } else {
                // Al cerrar, restaurar el foco al último elemento del catálogo si existe
                var lastFocused = this.lastFocusedCatalogItem;
                setTimeout(function() {
                    if (lastFocused && document.body.contains(lastFocused)) {
                        if (window.navEngine && typeof window.navEngine.focusElement === 'function') {
                            window.navEngine.focusElement(lastFocused);
                        }
                    }
                }, 100);
            }
        }
    },

    // Abrir/Cerrar ventana de detalles
    toggleDetailModal: function(show) {
        if (show === undefined) show = true;
        var modal = document.getElementById('detail-modal');
        if (modal) {
            if (show) {
                // Guardar la tarjeta del catálogo que tenía el foco antes de abrir detalles
                this.lastFocusedCatalogItem = document.querySelector('#catalog-container .grid-item.focused') || document.activeElement;

                modal.classList.remove('hidden');
                // Limpiar estilos inline para permitir que se apliquen los fallbacks CSS (-webkit-box, -webkit-flex) del stylesheet
                modal.style.display = '';
                modal.style.visibility = '';
                modal.style.opacity = '';
                // Forzar reflow para asegurar que el modal se renderiza
                modal.offsetHeight;

                // Auto-enfocar el primer botón de acción del hero (con retry por si los botones no están renderizados aún)
                var focusAttempts = 0;
                var tryFocusHero = function() {
                    focusAttempts++;
                    var actionBtn = modal.querySelector('.hero-actions button');
                    if (actionBtn && window.navEngine) {
                        window.navEngine.focus(actionBtn);
                    } else if (focusAttempts < 10) {
                        setTimeout(tryFocusHero, 100);
                    }
                };
                setTimeout(tryFocusHero, 80);
            } else {
                modal.classList.add('hidden');
                modal.style.display = 'none';
                modal.style.visibility = 'hidden';
                modal.style.opacity = '0';

                // Restaurar el foco a la tarjeta del catálogo original
                var targetToFocus = this.lastFocusedCatalogItem;
                if (!targetToFocus || targetToFocus === document.body || targetToFocus === document.documentElement || !document.body.contains(targetToFocus)) {
                    var currentId = (window.Catalog && window.Catalog.currentVariantId) || (window.Catalog && window.Catalog.currentMediaId);
                    if (currentId) {
                        targetToFocus = document.querySelector('#catalog-container .grid-item[data-item-id="' + currentId + '"]');
                    }
                    if (!targetToFocus) {
                        targetToFocus = document.querySelector('#catalog-container .grid-item');
                    }
                }
                if (targetToFocus && window.navEngine) {
                    window.navEngine.focus(targetToFocus);
                }
            }
        }
    },

    // Alternar modal de configuración
    toggleSettingsModal: function() {
        var modal = document.getElementById('settings-modal');
        if (modal) {
            modal.classList.toggle('hidden');
            if (!modal.classList.contains('hidden')) {
                // Limpiar estilos inline para permitir fallbacks CSS
                modal.style.display = '';
                modal.style.visibility = '';
                modal.style.opacity = '';
                this.initSettingsModalContent();
            } else {
                modal.style.display = 'none';
                modal.style.visibility = 'hidden';
                modal.style.opacity = '0';
            }
        }
    },

    // Cambiar de pestaña en el modal
    switchSettingsTab: function(tabName) {
        var user = window.Catalog.currentUser;
        var isAdmin = user && (user.username === 'admin' || user.is_admin);
        if (tabName === 'admin' && !isAdmin) {
            tabName = 'profile';
        }
        if (tabName === 'plugins' && !isAdmin) {
            tabName = 'profile';
        }
        if (tabName === 'userbot' && !isAdmin) {
            tabName = 'profile';
        }
        var tabs = ['profile', 'security', 'screen', 'categories', 'remote', 'admin', 'plugins', 'version', 'userbot', 'mobile', 'logs'];
        for (var ti = 0; ti < tabs.length; ti++) {
            var t = tabs[ti];
            var btn = document.getElementById('tab-btn-' + t);
            var pane = document.getElementById('pane-' + t);
            if (btn) {
                if (t === tabName) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            }
            if (pane) {
                if (t === tabName) {
                    pane.classList.remove('hidden');
                } else {
                    pane.classList.add('hidden');
                }
            }
        }

        // Actualizar dinámicamente el título del modal en la cabecera
        var friendlyNames = {
            'profile': 'Mi Perfil',
            'security': 'Seguridad',
            'screen': 'Pantalla',
            'categories': 'Categorías',
            'remote': 'Mapeo Mando',
            'admin': 'Usuarios',
            'plugins': 'Plugins',
            'version': 'Versión',
            'userbot': 'Userbot'
        };
        var titleTextEl = document.getElementById('settings-title-text');
        if (titleTextEl) {
            titleTextEl.innerHTML = 'Configuración de TVCat - ' + (friendlyNames[tabName] || tabName);
        }

        // Si entramos en la pestaña admin, recargamos la lista de usuarios
        if (tabName === 'admin') {
            this.loadAdminUsersList();
        }

        // Si entramos en la pestaña plugins, recargamos la lista de plugins y la configuración global
        if (tabName === 'plugins') {
            this.loadPluginsList();
            this.loadGlobalPluginsConfig();
        }

        // Si entramos en la pestaña version, cargamos la información de versión
        if (tabName === 'version') {
            this.loadVersionInfo();
        }

        // Si entramos en la pestaña userbot, cargamos la configuración global de userbot
        if (tabName === 'userbot') {
            this.loadGlobalUserbotConfig();
            this.initGlobalUserbotEvents();
        }

        // Si entramos en la pestaña de mando, activar el tester en vivo y sincronizar toggle Forzar mando
        if (tabName === 'remote') {
            this.startKeyTester();
            this.renderKeyMapTable();
            var fr = document.getElementById('force-remote-toggle');
            if (fr) { try { fr.checked = localStorage.getItem('tvcat_force_remote') === 'true'; } catch(e) {} }
        } else {
            this.stopKeyTester();
        }

        // Si entramos en la pestaña de logs, cargar logs automáticamente
        if (tabName === 'logs') {
            this.refreshLogs();
        }

        // Mostrar el botón global de Guardar Cambios en todas las pestañas excepto en la de administración, plugins, userbot o logs
        var saveBtn = document.getElementById('save-profile-btn');
        if (saveBtn) {
            if (tabName === 'admin' || tabName === 'plugins' || tabName === 'userbot' || tabName === 'logs') {
                saveBtn.classList.add('hidden');
            } else {
                saveBtn.classList.remove('hidden');
            }
        }
    },

    loadGlobalUserbotConfig: function() {
        var statusDiv = document.getElementById('global-userbot-status');
        if (statusDiv) statusDiv.innerHTML = '';
        
        window.API.ajax({
            method: 'GET',
            url: '/api/userbot/global-config',
            success: function(res) {
                if (res) {
                    var apiIdEl = document.getElementById('global-userbot-api-id');
                    var apiHashEl = document.getElementById('global-userbot-api-hash');
                    var sessionStringEl = document.getElementById('global-userbot-session-string');
                    
                    if (apiIdEl) apiIdEl.value = res.api_id || '';
                    if (apiHashEl) apiHashEl.value = res.api_hash || '';
                    if (sessionStringEl) {
                        sessionStringEl.value = res.session_string || '';
                        sessionStringEl.placeholder = res.has_session ? 'Sesión guardada (usa "..." para mantener)' : 'Pega tu String Session aquí...';
                    }
                    if (statusDiv) {
                        if (res.has_session) {
                            statusDiv.innerHTML = '🟢 Userbot principal configurado y activo.';
                            statusDiv.style.color = '#4ade80';
                        } else {
                            statusDiv.innerHTML = '⚪ Sin sesión configurada.';
                            statusDiv.style.color = '#a1a1aa';
                        }
                    }
                }
            },
            error: function(err) {
                if (statusDiv) {
                    statusDiv.innerHTML = '🔴 Error al cargar la configuración global.';
                    statusDiv.style.color = '#f87171';
                }
            }
        });
    },

    initGlobalUserbotEvents: function() {
        var testBtn = document.getElementById('global-userbot-test-btn');
        var saveBtn = document.getElementById('global-userbot-save-btn');
        var generateBtn = document.getElementById('global-userbot-generate-btn');

        // Helper para leer los campos en pantalla
        var getFormValues = function() {
            return {
                apiId: (document.getElementById('global-userbot-api-id') || {}).value || '',
                apiHash: (document.getElementById('global-userbot-api-hash') || {}).value || '',
                sessionStr: (document.getElementById('global-userbot-session-string') || {}).value || ''
            };
        };

        // Helper para guardar la configuración
        var doSave = function(apiId, apiHash, sessionStr, statusDiv, onSuccess) {
            if (!apiId.trim() || !apiHash.trim()) {
                alert('API ID y API Hash son obligatorios.');
                return;
            }
            if (statusDiv) {
                statusDiv.innerHTML = '⏳ Guardando configuración...';
                statusDiv.style.color = '#facc15';
            }
            window.API.ajax({
                method: 'POST',
                url: '/api/userbot/global-config',
                headers: { 'Content-Type': 'application/json' },
                body: { api_id: apiId.trim(), api_hash: apiHash.trim(), session_string: sessionStr.trim() },
                success: function(res) {
                    if (res && res.success) {
                        if (statusDiv) {
                            statusDiv.innerHTML = '🟢 Configuración guardada correctamente.';
                            statusDiv.style.color = '#4ade80';
                        }
                        window.UI.loadGlobalUserbotConfig();
                        if (typeof onSuccess === 'function') onSuccess();
                    } else {
                        if (statusDiv) {
                            statusDiv.innerHTML = '🔴 Error al guardar: ' + (res ? res.error : 'Desconocido');
                            statusDiv.style.color = '#f87171';
                        }
                    }
                },
                error: function() {
                    if (statusDiv) {
                        statusDiv.innerHTML = '🔴 Error de red al guardar.';
                        statusDiv.style.color = '#f87171';
                    }
                }
            });
        };

        if (testBtn && !testBtn.dataset.bound) {
            testBtn.dataset.bound = "true";
            testBtn.onclick = function() {
                var statusDiv = document.getElementById('global-userbot-status');
                var vals = getFormValues();

                if (!vals.sessionStr) {
                    alert('Por favor, introduce o genera una sesión primero.');
                    return;
                }
                if (!vals.apiId.trim() || !vals.apiHash.trim()) {
                    alert('API ID y API Hash son obligatorios para probar la conexión.');
                    return;
                }

                if (statusDiv) {
                    statusDiv.innerHTML = '⏳ Probando conexión con Telegram...';
                    statusDiv.style.color = '#facc15';
                }

                window.API.ajax({
                    method: 'POST',
                    url: '/api/userbot/global-config/test',
                    headers: { 'Content-Type': 'application/json' },
                    // Enviamos las credenciales en pantalla para que el backend las use
                    body: {
                        session_string: vals.sessionStr,
                        api_id: vals.apiId.trim(),
                        api_hash: vals.apiHash.trim()
                    },
                    success: function(res) {
                        if (res && res.success) {
                            if (statusDiv) {
                                statusDiv.innerHTML = '🟢 Conexión exitosa: @' + (res.username || 'usuario') + ' — Guardando...';
                                statusDiv.style.color = '#4ade80';
                            }
                            // Si el test es exitoso, guardar automáticamente
                            var freshVals = getFormValues();
                            doSave(freshVals.apiId, freshVals.apiHash, freshVals.sessionStr, statusDiv, function() {
                                statusDiv.innerHTML = '🟢 Conectado como @' + (res.username || 'usuario') + ' — Configuración guardada.';
                                statusDiv.style.color = '#4ade80';
                            });
                        } else {
                            if (statusDiv) {
                                statusDiv.innerHTML = '🔴 Error de conexión: ' + (res ? res.error : 'Desconocido');
                                statusDiv.style.color = '#f87171';
                            }
                        }
                    },
                    error: function() {
                        if (statusDiv) {
                            statusDiv.innerHTML = '🔴 Error de red al probar.';
                            statusDiv.style.color = '#f87171';
                        }
                    }
                });
            };
        }

        if (saveBtn && !saveBtn.dataset.bound) {
            saveBtn.dataset.bound = "true";
            saveBtn.onclick = function() {
                var statusDiv = document.getElementById('global-userbot-status');
                var vals = getFormValues();
                doSave(vals.apiId, vals.apiHash, vals.sessionStr, statusDiv);
            };
        }

        if (generateBtn && !generateBtn.dataset.bound) {
            generateBtn.dataset.bound = "true";
            generateBtn.onclick = function() {
                window.UI.openSessionGeneratorModalGlobal();
            };
        }
    },


    openSessionGeneratorModalGlobal: function() {
        if (typeof window._openSessionGeneratorModal === 'function') {
            window._openSessionGeneratorModal(function() {
                window.UI.loadGlobalUserbotConfig();
            }, true);
        }
    },


    // --- TESTER DE TECLAS EN VIVO ---
    _keyTesterHandler: null,
    _keyTesterFlashTimers: {},

    renderKeyMapTable: function() {
        var container = document.getElementById('keymap-table-container');
        if (!container) return;
        var map = window.keyMapper ? window.keyMapper.customMap : {};
        var keys = Object.keys(map);
        if (keys.length === 0) {
            container.innerHTML = '<span style="color:#666;">Sin calibración personalizada — usando mapeo de PC por defecto (teclas 0-9 y teclado numérico)</span>';
            return;
        }
        var rows = '';
        var digitNames = {'0':'Atrás','1':'Prev/Salto-','2':'Skip intro / ↑TV','3':'Next/Salto+','4':'◀ Izq','5':'✓ Select','6':'▶ Der','7':'Salto grande -','8':'Pantalla completa / ↑PC','9':'Salto grande +'};
        keys.forEach(function(kc) {
            var digit = map[kc];
            var action = digitNames[digit] || '';
            rows += '<div style="display:flex;gap:8px;align-items:center;padding:3px 0;border-bottom:1px solid #222;">' +
                '<span style="color:#e11d48;min-width:55px;">KC ' + kc + '</span>' +
                '<span style="color:#fff;min-width:20px;font-weight:bold;">' + digit + '</span>' +
                '<span style="color:#888;">' + action + '</span>' +
                '</div>';
        });
        container.innerHTML = rows;
    },

    startKeyTester: function() {
        var self = this;
        self.stopKeyTester(); // limpiar si había uno anterior

        self._keyTesterHandler = function(e) {
            // No interferir con la calibración
            if (window.UI && window.UI.isCalibrating) return;

            var keyCode = e.keyCode || e.which;
            var digit = window.keyMapper ? window.keyMapper.getVirtualDigit(e) : null;

            var elKC = document.getElementById('tester-keycode');
            var elDigit = document.getElementById('tester-digit');
            var elName = document.getElementById('tester-keyname');

            if (elKC) elKC.textContent = keyCode;
            if (elDigit) elDigit.textContent = digit !== null ? digit : '—';
            if (elName) elName.textContent = e.key || '?';

            // Iluminar el botón correspondiente en el grid
            if (digit !== null) {
                var btn = document.getElementById('cal-btn-' + digit);
                if (btn) {
                    btn.style.background = '#e11d48';
                    btn.style.color = '#fff';
                    btn.style.borderColor = '#e11d48';
                    btn.style.boxShadow = '0 0 10px rgba(225,29,72,0.5)';
                    // Limpiar flash anterior si existe
                    if (self._keyTesterFlashTimers[digit]) clearTimeout(self._keyTesterFlashTimers[digit]);
                    self._keyTesterFlashTimers[digit] = setTimeout(function() {
                        btn.style.background = '#222';
                        btn.style.color = '#888';
                        btn.style.borderColor = '#444';
                        btn.style.boxShadow = 'none';
                    }, 500);
                }
            }
        };

        // Escuchar en capture para recibir ANTES que el globalKeydownHandler
        window.addEventListener('keydown', self._keyTesterHandler, true);
    },

    stopKeyTester: function() {
        if (this._keyTesterHandler) {
            window.removeEventListener('keydown', this._keyTesterHandler, true);
            this._keyTesterHandler = null;
        }
    },

    // Cargar configuraciones iniciales
    loadSettings: function() {
        try {
            // Cargar columnas guardadas para este dispositivo en el select
            var colsSetting = localStorage.getItem('tvcat_grid_columns') || 'auto';
            var select = document.getElementById('screen-columns-select');
            if (select) {
                select.value = colsSetting;
            }
            this.applyScreenColumns(colsSetting);

            // Cargar tipo de reproductor preferido
            var playerSetting = localStorage.getItem('tvcat_preferred_player') || 'auto';
            var playerSelect = document.getElementById('player-type-select');
            if (playerSelect) {
                playerSelect.value = playerSetting;
            }

            // Cargar tamaño de chunk preferido
            var chunkSetting = localStorage.getItem('tvcat_download_chunk_size') || '128';
            var chunkSelect = document.getElementById('player-chunk-size-select');
            if (chunkSelect) {
                chunkSelect.value = chunkSetting;
            }

            // Cargar preferencia de abrir última sección
            var openLastSetting = localStorage.getItem('tvcat_open_last_section') !== 'false';
            var openLastToggle = document.getElementById('screen-open-last-section-toggle');
            if (openLastToggle) {
                openLastToggle.checked = openLastSetting;
            }

            // Cargar preferencia de avatar a la derecha
            var avatarRightSetting = localStorage.getItem('tvcat_avatar_right') === 'true';
            var avatarRightToggle = document.getElementById('screen-avatar-right-toggle');
            if (avatarRightToggle) {
                avatarRightToggle.checked = avatarRightSetting;
            }

            // Cargar visibilidad de debug overlay
            var showDebug = localStorage.getItem('tvcat_show_debug_overlay') === 'true';
            var dbgToggle = document.getElementById('dbg-overlay-toggle');
            if (dbgToggle) {
                dbgToggle.checked = showDebug;
            }
            var dbgEl = document.getElementById('dbg-overlay');
            if (dbgEl) {
                dbgEl.style.display = showDebug ? 'block' : 'none';
            }



            // Cargar umbrales de visualización (preferencia central de usuario)
            if (window.API && window.API.getWatchThresholds) {
                window.API.getWatchThresholds(function(th) {
                    var minEl = document.getElementById('watch-threshold-min');
                    var maxEl = document.getElementById('watch-threshold-max');
                    if (minEl) minEl.value = th.min;
                    if (maxEl) maxEl.value = th.max;
                });
            } else {
                var minThresh = localStorage.getItem('tvcat_watch_threshold_min') || '5';
                var maxThresh = localStorage.getItem('tvcat_watch_threshold_max') || '85';
                var minEl = document.getElementById('watch-threshold-min');
                var maxEl = document.getElementById('watch-threshold-max');
                if (minEl) minEl.value = minThresh;
                if (maxEl) maxEl.value = maxThresh;
            }


            // Cargar máximo de elementos
            var maxElements = this.getMaxElements();
            var maxElInput = document.getElementById('screen-max-elements');
            if (maxElInput) {
                maxElInput.value = maxElements;
            }

            // Cargar caché de capítulos
            var cacheEnabled = localStorage.getItem('tvcat_episode_cache_enable') !== 'false';
            var cacheToggle = document.getElementById('screen-episode-cache-enable');
            if (cacheToggle) {
                cacheToggle.checked = cacheEnabled;
            }
            var cacheSize = localStorage.getItem('tvcat_episode_cache_size') || '5';
            var cacheSizeSelect = document.getElementById('screen-episode-cache-size');
            if (cacheSizeSelect) {
                cacheSizeSelect.value = cacheSize;
            }
            this.updateEpisodeCacheUI();

            // Cargar saltos personalizados y skip intro del reproductor
            var jumpShort = localStorage.getItem('tvcat_small_jump') || '5';
            var jumpLong = localStorage.getItem('tvcat_large_jump') || '20';
            var skipIntroVal = localStorage.getItem('tvcat_intro_jump') || '80';

            var jsInput = document.getElementById('player-jump-short');
            var jlInput = document.getElementById('player-jump-long');
            var siInput = document.getElementById('player-skip-intro');

            if (jsInput) jsInput.value = jumpShort;
            if (jlInput) jlInput.value = jumpLong;
            if (siInput) siInput.value = skipIntroVal;
        } catch (e) {
            console.error(" [UI ERROR] loadSettings:", e);
        }
    },

    // Inicializar presets y datos del usuario logueado al abrir la ventana
    initSettingsModalContent: function() {
        var self = this;
        var user = window.Catalog.currentUser;
        if (!user) return;

        // 1. Mostrar/Ocultar Pestaña Admin, Plugins y Userbot
        var isAdmin = user && (user.username === 'admin' || user.is_admin);
        var adminTab = document.getElementById('tab-btn-admin');
        var pluginsTab = document.getElementById('tab-btn-plugins');
        var userbotTab = document.getElementById('tab-btn-userbot');
        var contentsTab = document.getElementById('tab-btn-contents');
        if (adminTab) {
            adminTab.classList.toggle('hidden', !isAdmin);
        }
        if (pluginsTab) {
            pluginsTab.classList.toggle('hidden', !isAdmin);
        }
        if (userbotTab) {
            userbotTab.classList.toggle('hidden', !isAdmin);
        }
        if (contentsTab) {
            contentsTab.classList.toggle('hidden', !isAdmin);
        }

        // Regresar a la primera pestaña (Perfil)
        this.switchSettingsTab('profile');
        this.updateEpisodeCacheUI();

        // 2. Cargar Nombre
        var nameInput = document.getElementById('profile-display-name');
        if (nameInput) {
            nameInput.value = user.display_name || user.username || '';
        }

        // 3. Renderizar Presets de Avatar (Emojis)
        this.selectedAvatar = user.avatar || '👤';
        var avatarContainer = document.getElementById('avatar-presets');
        if (avatarContainer) {
            avatarContainer.innerHTML = '';
            this.avatarPresets.forEach(function(emoji) {
                var el = document.createElement('div');
                el.className = 'avatar-preset-item' + (emoji === self.selectedAvatar ? ' active' : '');
                el.innerHTML = window.getSVGIcon(emoji, 32);
                el.onclick = function() {
                    var items = avatarContainer.getElementsByClassName('avatar-preset-item');
                    for (var i = 0; i < items.length; i++) items[i].classList.remove('active');
                    el.classList.add('active');
                    self.selectedAvatar = emoji;
                    
                    // Limpiar inputs de URL y archivo ya que eligió emoji
                    var urlInput = document.getElementById('profile-avatar-url');
                    if (urlInput) urlInput.value = '';
                    var fileInput = document.getElementById('profile-avatar-file');
                    if (fileInput) fileInput.value = '';
                };
                avatarContainer.appendChild(el);
            });
        }

        // Cargar valor de URL/Archivo si aplica
        var urlInput = document.getElementById('profile-avatar-url');
        if (urlInput) {
            if (user.avatar_url) {
                urlInput.value = user.avatar_url;
            } else if (this.selectedAvatar.indexOf('http') === 0 || this.selectedAvatar.indexOf('data:image/') === 0) {
                if (this.selectedAvatar.indexOf('data:image/') !== 0) {
                    urlInput.value = this.selectedAvatar;
                } else {
                    urlInput.value = '(Imagen subida desde PC)';
                }
            } else {
                urlInput.value = '';
            }
        }
        var fileInput = document.getElementById('profile-avatar-file');
        if (fileInput) fileInput.value = '';

        // Auto-detectar y seleccionar la pestaña de avatar adecuada según su tipo
        var avatarVal = user.avatar_url || this.selectedAvatar || '👤';
        if (avatarVal.indexOf('http') === 0) {
            this.switchAvatarTab(null, 'url');
        } else if (avatarVal.indexOf('data:image/') === 0 || avatarVal.indexOf('/api/') === 0 || avatarVal.indexOf('/static/') === 0) {
            this.switchAvatarTab(null, 'upload');
        } else {
            this.switchAvatarTab(null, 'presets');
        }

        // 4. Renderizar Presets de Color
        this.selectedColor = user.color || '#e11d48';
        var colorContainer = document.getElementById('color-presets');
        if (colorContainer) {
            colorContainer.innerHTML = '';
            this.colorPresets.forEach(function(color) {
                var el = document.createElement('div');
                el.className = 'color-preset-item' + (color === self.selectedColor ? ' active' : '');
                el.style.background = color;
                el.setAttribute('data-color', color);
                el.onclick = function() {
                    var items = colorContainer.getElementsByClassName('color-preset-item');
                    for (var i = 0; i < items.length; i++) items[i].classList.remove('active');
                    el.classList.add('active');
                    self.selectedColor = color;
                };
                colorContainer.appendChild(el);
            });
        }

        // 5. Cargar Checkbox de Preferencias de Categorías Dinámicamente desde BD
        var checklistContainer = document.getElementById('user-preferences-checklist');
        if (checklistContainer) {
            checklistContainer.innerHTML = '<div style="color: var(--text-secondary); padding: 5px;">Cargando categorías...</div>';
            window.API.getCategories(function(catsDict) {
                try {
                    renderCategoryCheckboxes(catsDict, checklistContainer, user);
                } catch (e) {
                    // Fallback: render from appLabels if API returned empty
                    var fallback = {};
                    if (window.appLabels) {
                        for (var f in window.appLabels) {
                            if (window.appLabels.hasOwnProperty(f)) {
                                fallback[f] = window.appLabels[f].label || f;
                            }
                        }
                    }
                    if (Object.keys(fallback).length > 0) {
                        renderCategoryCheckboxes(fallback, checklistContainer, user);
                    } else {
                        checklistContainer.innerHTML = '<div style="color: var(--text-secondary); padding: 10px; text-align: center;">Error al cargar categorías <button onclick="window.UI.initSettingsModalContent()" style="margin-left:8px; padding:4px 12px; background:var(--accent); color:#fff; border:none; border-radius:6px; cursor:pointer;">Reintentar</button></div>';
                    }
                }
            });
        }
    },

    // Guardar cambios del Perfil en el Servidor
    saveUserProfileChanges: function() {
        var self = this;
        var nameInput = document.getElementById('profile-display-name');
        var displayName = nameInput ? nameInput.value.trim() : '';
        if (!displayName) {
            alert("El nombre de pantalla no puede estar vacío");
            return;
        }

        // Obtener preferencias de categorías dinámicas
        var prefs = {};
        var checkboxes = document.querySelectorAll('.pref-cat-checkbox');
        for (var i = 0; i < checkboxes.length; i++) {
            var cat = checkboxes[i].getAttribute('data-cat');
            prefs[cat] = checkboxes[i].checked;
        }

        var payload = {
            display_name: displayName,
            avatar: this.selectedAvatar,
            avatar_url: document.getElementById('profile-avatar-url') ? document.getElementById('profile-avatar-url').value.trim() : '',
            color: this.selectedColor,
            category_preferences: JSON.stringify(prefs)
        };

        window.API.updateProfile(payload, function(res) {
            if (res && res.success) {
                // Actualizar estado del usuario logueado en memoria
                var avatarUrl = document.getElementById('profile-avatar-url');
                window.Catalog.currentUser.display_name = displayName;
                window.Catalog.currentUser.avatar = self.selectedAvatar;
                window.Catalog.currentUser.avatar_url = avatarUrl ? avatarUrl.value.trim() : '';
                window.Catalog.currentUser.color = self.selectedColor;
                window.Catalog.currentUser.category_preferences = payload.category_preferences;

                // Actualizar visual de cabecera en sidebar
                window.Catalog.updateSidebarProfileUI();

                // Actualizar árbol de categorías para aplicar filtro de preferencias de inmediato
                if (window.Catalog && window.Catalog.initCategoriesTree) {
                    window.Catalog.initCategoriesTree();
                }

                // Recargar catálogo inicial considerando las nuevas exclusiones
                window.Catalog.load(window.Catalog.currentCategory);

                // UX: Cerrar el modal silenciosamente sin alertas molestas
                self.toggleSettingsModal();
            } else {
                alert("Error al actualizar el perfil.");
            }
        });
    },

    // Guardar cambios globales (Perfil, Categorías Preferidas y Contraseña si aplica)
    saveGlobalSettings: function() {
        var self = this;

        // Guardar valores de saltos del reproductor en localStorage
        var jsInput = document.getElementById('player-jump-short');
        var jlInput = document.getElementById('player-jump-long');
        var siInput = document.getElementById('player-skip-intro');

        if (jsInput) localStorage.setItem('tvcat_small_jump', parseInt(jsInput.value) || 5);
        if (jlInput) localStorage.setItem('tvcat_large_jump', parseInt(jlInput.value) || 20);
        if (siInput) localStorage.setItem('tvcat_intro_jump', parseInt(siInput.value) || 80);

        var nameInput = document.getElementById('profile-display-name');
        var displayName = nameInput ? nameInput.value.trim() : '';
        if (!displayName) {
            // Si no se está tocando el perfil, conservar el nombre actual en vez de bloquear
            // el guardado global (el campo solo exige valor cuando se edita la pestaña Perfil).
            displayName = (window.Catalog.currentUser && (window.Catalog.currentUser.display_name || window.Catalog.currentUser.username)) || '';
            if (!displayName) {
                alert("El nombre de pantalla no puede estar vacío");
                return;
            }
        }

        // 1. Obtener preferencias de categorías dinámicas
        var prefs = {};
        var checkboxes = document.querySelectorAll('.pref-cat-checkbox');
        for (var i = 0; i < checkboxes.length; i++) {
            var cat = checkboxes[i].getAttribute('data-cat');
            prefs[cat] = checkboxes[i].checked;
        }

        var payload = {
            display_name: displayName,
            avatar: this.selectedAvatar,
            avatar_url: document.getElementById('profile-avatar-url') ? document.getElementById('profile-avatar-url').value.trim() : '',
            color: this.selectedColor,
            category_preferences: JSON.stringify(prefs)
        };

        // Guardar perfil y categorías preferidas
        window.API.updateProfile(payload, function(profileRes) {
            if (profileRes && profileRes.success) {
                var avatarUrl = document.getElementById('profile-avatar-url');
                // Actualizar estado local del usuario en memoria
                window.Catalog.currentUser.display_name = displayName;
                window.Catalog.currentUser.avatar = self.selectedAvatar;
                window.Catalog.currentUser.avatar_url = avatarUrl ? avatarUrl.value.trim() : '';
                window.Catalog.currentUser.color = self.selectedColor;
                window.Catalog.currentUser.category_preferences = payload.category_preferences;

                // Actualizar UI
                window.Catalog.updateSidebarProfileUI();
                if (window.Catalog && window.Catalog.initCategoriesTree) {
                    window.Catalog.initCategoriesTree();
                }
                window.Catalog.load(window.Catalog.currentCategory);

                // 2. Procesar cambio de contraseña si se introdujo algún dato en los campos de seguridad
                var currentPassEl = document.getElementById('profile-current-password');
                var newPassEl = document.getElementById('profile-new-password');
                var confirmPassEl = document.getElementById('profile-confirm-password');

                var currentPassword = currentPassEl ? currentPassEl.value : '';
                var newPassword = newPassEl ? newPassEl.value : '';
                var confirmPassword = confirmPassEl ? confirmPassEl.value : '';

                if (currentPassword || newPassword || confirmPassword) {
                    if (!currentPassword || !newPassword || !confirmPassword) {
                        alert("Para cambiar tu contraseña debes rellenar los tres campos (Actual, Nueva y Confirmación)");
                        return;
                    }
                    if (newPassword !== confirmPassword) {
                        alert("La nueva contraseña y la confirmación no coinciden");
                        return;
                    }

                    window.API.changePassword(currentPassword, newPassword, function(passRes) {
                        if (passRes && passRes.success) {
                            alert("¡Configuración y contraseña actualizadas con éxito!");
                            if (currentPassEl) currentPassEl.value = '';
                            if (newPassEl) newPassEl.value = '';
                            if (confirmPassEl) confirmPassEl.value = '';
                            self.toggleSettingsModal();
                        } else {
                            alert("Error: " + (passRes.detail || "No se pudo cambiar la contraseña, pero el resto de cambios se guardaron con éxito"));
                        }
                    });
                } else {
                    // Sin cambio de contraseña: ¡guardado directo exitoso!
                    self.toggleSettingsModal();
                }
            } else {
                alert("Error al actualizar la configuración.");
            }
        });
    },

    // Aplicar cantidad de columnas del grid por dispositivo
    applyScreenColumns: function(value) {
        var classes = document.body.className.split(' ');
        var newClasses = [];
        for (var i = 0; i < classes.length; i++) {
            if (classes[i].slice(0, 5) !== 'cols-') {
                newClasses.push(classes[i]);
            }
        }
        document.body.className = newClasses.join(' ').trim();

        if (value === 'auto') {
            document.documentElement.style.setProperty('--grid-columns', '6');
            document.body.className = (document.body.className + ' cols-6').trim();
        } else {
            document.documentElement.style.setProperty('--grid-columns', value);
            document.body.className = (document.body.className + ' cols-' + value).trim();
        }
    },

    // Cambiar columnas e interactuar con localStorage
    changeScreenColumns: function(value) {
        localStorage.setItem('tvcat_grid_columns', value);
        this.applyScreenColumns(value);
    },

    // Cambiar tipo de reproductor (Plyr/Nativo/Auto)
    changePlayerType: function(value) {
        localStorage.setItem('tvcat_preferred_player', value);
        console.log('[UI] Tipo de reproductor cambiado a:', value);
        // Verify save
        var saved = localStorage.getItem('tvcat_preferred_player');
        console.log('[UI] Verificación localStorage: ' + saved);
        this.updateEpisodeCacheUI();
    },

    toggleEpisodeCacheEnable: function(checked) {
        localStorage.setItem('tvcat_episode_cache_enable', checked);
        this.updateEpisodeCacheUI();
    },

    changeEpisodeCacheSize: function(value) {
        localStorage.setItem('tvcat_episode_cache_size', value);
    },

    changeDownloadChunkSize: function(value) {
        localStorage.setItem('tvcat_download_chunk_size', value);
        console.log('[UI] Tamaño de chunk de descarga preferido cambiado a:', value);
    },

    updateEpisodeCacheUI: function() {
        var playerSelect = document.getElementById('player-type-select');
        var isBasic = playerSelect && playerSelect.value === 'basic';
        
        var group = document.getElementById('episode-cache-settings-group');
        if (group) {
            if (isBasic) {
                group.classList.remove('hidden');
            } else {
                group.classList.add('hidden');
            }
        }

        var cacheToggle = document.getElementById('screen-episode-cache-enable');
        var sizeContainer = document.getElementById('episode-cache-size-container');
        if (sizeContainer && cacheToggle) {
            if (cacheToggle.checked && isBasic) {
                sizeContainer.classList.remove('hidden');
            } else {
                sizeContainer.classList.add('hidden');
            }
        }
    },

    // Obtener tipo de reproductor preferido
    getPreferredPlayer: function() {
        var pref = localStorage.getItem('tvcat_preferred_player');
        if (!pref) return 'auto';
        return pref;
    },

    // Cambiar máximo de elementos en catálogo
    changeMaxElements: function(value) {
        var num = parseInt(value, 10);
        if (isNaN(num) || num < 10) num = 10;
        if (num > 200) num = 200;
        localStorage.setItem('tvcat_max_elements', num);
        var input = document.getElementById('screen-max-elements');
        if (input) input.value = num;
        console.log('[UI] Max elements cambiado a:', num);
        // Recargar catálogo para aplicar el cambio inmediatamente
        if (window.Catalog) {
            if (window.Catalog.currentCategory) {
                window.Catalog.load(window.Catalog.currentCategory);
            } else {
                window.Catalog.load('home');
            }
        }
    },

    // Obtener máximo de elementos configurado
    getMaxElements: function() {
        var stored = localStorage.getItem('tvcat_max_elements');
        if (stored) return parseInt(stored, 10);
        var ua = navigator.userAgent;
        var isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua) || window.innerWidth < 768;
        if (isMobile) {
            return 30;
        }
        var isSmartTV = /Tizen|WebOS|SmartTV|Android TV|Philips|SonyBravia|Roku|SamsungBrowser/i.test(ua);
        if (isSmartTV) {
            return 50;
        }
        return 200;
    },

    // Cargar y Renderizar tabla de usuarios registrados (Administración)
    loadAdminUsersList: function() {
        var container = document.getElementById('admin-users-list');
        if (!container) return;

        container.innerHTML = '<div style="color:var(--text-secondary); text-align:center; padding:10px;">Cargando usuarios...</div>';

        // Estilos dinámicos premium para los badges interactivos
        if (!document.getElementById('admin-cats-style')) {
            var style = document.createElement('style');
            style.id = 'admin-cats-style';
            style.innerHTML = 
                '.admin-cat-badge {' +
                    'display: inline-flex;' +
                    'align-items: center;' +
                    'gap: 6px;' +
                    'padding: 6px 12px;' +
                    'border-radius: 20px;' +
                    'font-size: 0.78rem;' +
                    'font-weight: 500;' +
                    'background-color: #18181b;' +
                    'border: 1px solid #27272a;' +
                    'color: var(--text-secondary);' +
                    'transition: all 0.2s ease;' +
                    'user-select: none;' +
                '}' +
                '.admin-cat-badge.active {' +
                    'background-color: rgba(16, 185, 129, 0.15);' +
                    'border-color: #10b981;' +
                    'color: #10b981;' +
                '}' +
                '.admin-cat-badge:hover:not([style*="not-allowed"]) {' +
                    'transform: translateY(-1px);' +
                    'border-color: var(--text-secondary);' +
                    'color: var(--text-primary);' +
                '}';
            document.head.appendChild(style);
        }

        window.API.getCategories(function(catsDict) {
            window.API.listUsers(function(res) {
                if (!res || !res.users) {
                    container.innerHTML = '<div style="color:#ff3344; text-align:center; padding:10px;">Error al cargar usuarios.</div>';
                    return;
                }

                container.innerHTML = '';
                for (var ui = 0; ui < res.users.length; ui++) {
                    var u = res.users[ui];
                    var card = document.createElement('div');
                    card.className = 'admin-user-card';
                    card.style.flexDirection = 'column';
                    card.style.alignItems = 'stretch';
                    card.style.gap = '12px';

                    // Determinar inicial o avatar
                    var avatarChar = u.avatar || '👤';
                    var avatarBg = u.color || '#a1a1aa';
                    var isSelfAdmin = u.id === 1;

                    var avatarHTML = avatarChar;
                    if (avatarChar.indexOf('http') === 0 || avatarChar.indexOf('data:image/') === 0) {
                        avatarHTML = '<img src="' + avatarChar + '" style="width:100%; height:100%; object-fit:cover; border-radius:50%; display:block;">';
                    } else {
                        avatarHTML = window.getSVGIcon(avatarChar, 24);
                    }

                    var checkedState = u.can_send_telegram === 1 ? 'checked' : '';
                    var disabledState = isSelfAdmin ? 'disabled' : '';

                    var toggleHTML = 
                        '<label class="switch">' +
                            '<input type="checkbox" ' + checkedState + ' ' + disabledState + ' onchange="window.UI.toggleUserTelegramPermission(' + u.id + ', this.checked)">' +
                            '<span class="slider round"></span>' +
                        '</label>';

                    // Parsear categorías permitidas del usuario
                    var allowed = [];
                    try {
                        allowed = JSON.parse(u.allowed_categories || '[]');
                    } catch(e){}

                    // Generar grid de badges de categorías
                    var catsHTML = '';
                    for (var cat in catsDict) {
                        if (catsDict.hasOwnProperty(cat)) {
                            var isAllowed = isSelfAdmin || allowed.length === 0;
                            if (!isSelfAdmin && allowed.length > 0) {
                                isAllowed = false;
                                for (var k = 0; k < allowed.length; k++) {
                                    if (allowed[k].toLowerCase().trim() === cat.toLowerCase().trim()) {
                                        isAllowed = true;
                                        break;
                                    }
                                }
                            }

                            // Buscar emoji y etiqueta
                            var catLabel = cat;
                            var catEmoji = '📦';
                            var catData = window.appLabels && window.appLabels[cat.toLowerCase()];
                            if (catData) {
                                catLabel = catData.label;
                                catEmoji = catData.emoji || '📦';
                            } else {
                                catLabel = cat.charAt(0).toUpperCase() + cat.slice(1);
                                if (cat.toLowerCase() === 'game') catLabel = 'Juegos';
                            }

                            var badgeClass = isAllowed ? 'admin-cat-badge active' : 'admin-cat-badge';
                            var badgeStyle = isSelfAdmin ? 'cursor: not-allowed; opacity: 0.8;' : 'cursor: pointer;';
                            var onclickAttr = isSelfAdmin ? '' : 'onclick="window.UI.toggleUserCategoryAccess(event, ' + u.id + ', \'' + cat + '\', ' + isAllowed + ')"';

                            catsHTML += 
                                '<div class="' + badgeClass + '" style="' + badgeStyle + '" ' + onclickAttr + ' title="Haga clic para alternar acceso">' +
                                    '<span>' + catEmoji + '</span> ' + catLabel +
                                '</div>';
                        }
                    }

                    card.innerHTML = 
                        '<div style="display:flex; align-items:center; justify-content:space-between; width:100%;">' +
                            '<div class="admin-user-info">' +
                                '<div class="admin-user-avatar" style="background-color:' + avatarBg + '; padding: 0;">' + avatarHTML + '</div>' +
                                '<div class="admin-user-details">' +
                                    '<span class="admin-user-name">' + u.display_name + ' (@' + u.username + ')</span>' +
                                    '<span class="admin-user-role">' + (isSelfAdmin ? 'Administrador Principal (Propietario)' : 'Usuario del Servidor') + '</span>' +
                                    '<span style="font-size:0.75rem; color:var(--text-secondary); margin-top:2px;">Telegram: ' + (u.can_send_telegram === 1 ? 'Permitido' : 'No permitido') + '</span>' +
                                    (isSelfAdmin ? '' : 
                                    '<div class="admin-user-actions" style="margin-top: 8px; display: flex; gap: 8px;">' +
                                        '<button class="btn-primary" style="padding: 4px 8px; font-size: 0.75rem; border-radius: 6px; cursor: pointer;" onclick="window.UI.promptAdminChangePassword(' + u.id + ', \'' + u.username + '\')">Cambiar Clave</button>' +
                                        '<button class="btn-dark" style="padding: 4px 8px; font-size: 0.75rem; border-radius: 6px; background-color: #ef4444; border-color: #ef4444; cursor: pointer;" onclick="window.UI.confirmAdminDeleteUser(' + u.id + ', \'' + u.username + '\')">Eliminar</button>' +
                                    '</div>') +
                                '</div>' +
                            '</div>' +
                            '<div>' + toggleHTML + '</div>' +
                        '</div>' +
                        '<div class="admin-user-categories" style="border-top: 1px solid #27272a; padding-top: 10px; margin-top: 4px; text-align: left;">' +
                            '<div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 8px; font-weight: 500;">Permiso de Categorías:</div>' +
                            '<div class="admin-cats-grid" style="display: flex; flex-wrap: wrap; gap: 8px;">' +
                                catsHTML +
                            '</div>' +
                        '</div>';

                    container.appendChild(card);
                }
            });
        });
    },

    loadGlobalPluginsConfig: function() {
        var intervalInput = document.getElementById('global-refresh-interval');
        var delaySelect = document.getElementById('global-telegram-delay');
        var statusDiv = document.getElementById('global-plugins-config-status');
        if (!intervalInput || !delaySelect) return;

        window.API.ajax({
            method: 'GET',
            url: '/api/plugins/global-config',
            success: function(res) {
                if (res) {
                    intervalInput.value = res.minutos_por_ciclo !== undefined ? res.minutos_por_ciclo : 60;
                    if (delaySelect) {
                        delaySelect.value = res.telegram_delay !== undefined ? res.telegram_delay : "3";
                    }
                }
            },
            error: function() {
                if (statusDiv) {
                    statusDiv.innerHTML = '<span style="color:#ef4444;">❌ Error al cargar configuración de sincronización.</span>';
                }
            }
        });
    },

    saveGlobalPluginsConfig: function() {
        var intervalInput = document.getElementById('global-refresh-interval');
        var delaySelect = document.getElementById('global-telegram-delay');
        var statusDiv = document.getElementById('global-plugins-config-status');
        if (!intervalInput || !delaySelect) return;

        var minutos = parseInt(intervalInput.value) || 0;
        var delay = parseFloat(delaySelect.value) || 3.0;

        if (statusDiv) {
            statusDiv.innerHTML = '<span style="color:var(--text-secondary);">⏳ Guardando...</span>';
        }

        window.API.ajax({
            method: 'POST',
            url: '/api/plugins/global-config',
            headers: { 'Content-Type': 'application/json' },
            body: {
                minutos_por_ciclo: minutos,
                telegram_delay: delay
            },
            success: function(res) {
                if (res && res.success) {
                    if (statusDiv) {
                        statusDiv.innerHTML = '<span style="color:#22c55e;">✅ Configuración guardada correctamente.</span>';
                        setTimeout(function() {
                            statusDiv.innerHTML = '';
                        }, 3000);
                    }
                } else {
                    if (statusDiv) {
                        statusDiv.innerHTML = '<span style="color:#ef4444;">❌ Error al guardar.</span>';
                    }
                }
            },
            error: function() {
                if (statusDiv) {
                    statusDiv.innerHTML = '<span style="color:#ef4444;">❌ Error de conexión al guardar.</span>';
                }
            }
        });
    },

    loadPluginsList: function() {
        var container = document.getElementById('plugins-list-container');
        if (!container) return;
        
        container.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.85rem; padding: 10px; text-align: center;">⏳ Cargando plugins...</div>';
        
        var self = this;
        window.API.getPlugins(function(plugins) {
            container.innerHTML = '';
            if (!plugins || Object.keys(plugins).length === 0) {
                container.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.85rem; padding: 10px; text-align: center;">📭 No hay plugins instalados.</div>';
                return;
            }
            
            for (var name in plugins) {
                if (plugins.hasOwnProperty(name)) {
                    var plugin = plugins[name];
                    var item = document.createElement('div');
                    item.className = 'plugin-item';
                    item.style.display = 'flex';
                    item.style.alignItems = 'center';
                    item.style.justifyContent = 'space-between';
                    item.style.padding = '14px 16px';
                    item.style.background = 'rgba(39, 39, 42, 0.4)';
                    item.style.border = '1px solid rgba(63, 63, 70, 0.4)';
                    item.style.borderRadius = '10px';
                    item.style.marginBottom = '8px';
                    
                    var isSystem = plugin.isSystem || plugin.is_system || (plugin.type === 'System');
                    
                    var leftDiv = document.createElement('div');
                    leftDiv.style.display = 'flex';
                    leftDiv.style.flexDirection = 'column';
                    leftDiv.style.gap = '4px';
                    
                    var titleDiv = document.createElement('div');
                    titleDiv.style.display = 'flex';
                    titleDiv.style.alignItems = 'center';
                    titleDiv.style.gap = '8px';
                    
                    var titleSp = document.createElement('span');
                    titleSp.style.fontWeight = '700';
                    titleSp.style.fontSize = '0.95rem';
                    titleSp.style.color = '#f4f4f5';
                    titleSp.textContent = plugin.displayName || plugin.display_name || plugin.name;
                    
                    var typeSp = document.createElement('span');
                    typeSp.style.fontSize = '0.75rem';
                    typeSp.style.padding = '2px 8px';
                    typeSp.style.borderRadius = '4px';
                    typeSp.style.fontWeight = '600';
                    if (isSystem) {
                        typeSp.style.background = 'rgba(59, 130, 246, 0.15)';
                        typeSp.style.color = '#60a5fa';
                        typeSp.textContent = 'Sistema';
                    } else {
                        typeSp.style.background = 'rgba(234, 179, 8, 0.15)';
                        typeSp.style.color = '#facc15';
                        typeSp.textContent = 'Usuario';
                    }
                    
                    titleDiv.appendChild(titleSp);
                    titleDiv.appendChild(typeSp);
                    
                    var descDiv = document.createElement('div');
                    descDiv.style.fontSize = '0.8rem';
                    descDiv.style.color = '#a1a1aa';
                    descDiv.style.lineHeight = '1.3';
                    descDiv.textContent = plugin.description;
                    
                    leftDiv.appendChild(titleDiv);
                    leftDiv.appendChild(descDiv);
                    
                    if (name === 'tvcat_tgindex') {
                        var configBtn = document.createElement('button');
                        configBtn.textContent = '⚙️ Configurar';
                        configBtn.style.padding = '4px 10px';
                        configBtn.style.fontSize = '0.75rem';
                        configBtn.style.borderRadius = '6px';
                        configBtn.style.background = 'rgba(168, 85, 247, 0.2)';
                        configBtn.style.border = '1px solid rgba(168, 85, 247, 0.5)';
                        configBtn.style.color = '#c084fc';
                        configBtn.style.cursor = 'pointer';
                        configBtn.style.marginTop = '6px';
                        configBtn.style.width = 'fit-content';
                        configBtn.style.fontWeight = '700';
                        configBtn.style.transition = 'all 0.2s';
                        
                        configBtn.onmouseover = function() {
                            configBtn.style.background = 'rgba(168, 85, 247, 0.4)';
                            configBtn.style.color = '#e9d5ff';
                        };
                        configBtn.onmouseout = function() {
                            configBtn.style.background = 'rgba(168, 85, 247, 0.2)';
                            configBtn.style.color = '#c084fc';
                        };
                        
                        if (plugin.enabled) {
                            leftDiv.appendChild(configBtn);
                            configBtn.onclick = function() {
                                window.openUserbotConfigModal();
                            };
                        }
                    }
                    
                    if (name === 'tvcat_peers') {
                        var configBtn = document.createElement('button');
                        configBtn.textContent = '⚙️ Configurar';
                        configBtn.style.padding = '4px 10px';
                        configBtn.style.fontSize = '0.75rem';
                        configBtn.style.borderRadius = '6px';
                        configBtn.style.background = 'rgba(168, 85, 247, 0.2)';
                        configBtn.style.border = '1px solid rgba(168, 85, 247, 0.5)';
                        configBtn.style.color = '#c084fc';
                        configBtn.style.cursor = 'pointer';
                        configBtn.style.marginTop = '6px';
                        configBtn.style.width = 'fit-content';
                        configBtn.style.fontWeight = '700';
                        configBtn.style.transition = 'all 0.2s';
                        
                        configBtn.onmouseover = function() {
                            configBtn.style.background = 'rgba(168, 85, 247, 0.4)';
                            configBtn.style.color = '#e9d5ff';
                        };
                        configBtn.onmouseout = function() {
                            configBtn.style.background = 'rgba(168, 85, 247, 0.2)';
                            configBtn.style.color = '#c084fc';
                        };
                        
                        if (plugin.enabled) {
                            leftDiv.appendChild(configBtn);
                            configBtn.onclick = function() {
                                window.openPeersConfigModal();
                            };
                        }
                    }
                    
                    // Controles a la derecha: Interruptor premium
                    var rightDiv = document.createElement('div');
                    
                    var label = document.createElement('label');
                    label.style.position = 'relative';
                    label.style.display = 'inline-block';
                    label.style.width = '44px';
                    label.style.height = '24px';
                    label.style.cursor = 'pointer';
                    
                    var input = document.createElement('input');
                    input.type = 'checkbox';
                    input.checked = plugin.enabled;
                    input.style.opacity = '0';
                    input.style.width = '0';
                    input.style.height = '0';
                    
                    var slider = document.createElement('span');
                    slider.style.position = 'absolute';
                    slider.style.top = '0';
                    slider.style.left = '0';
                    slider.style.right = '0';
                    slider.style.bottom = '0';
                    slider.style.backgroundColor = plugin.enabled ? '#22c55e' : '#3f3f46';
                    slider.style.transition = '0.3s';
                    slider.style.borderRadius = '24px';
                    
                    var knob = document.createElement('span');
                    knob.style.position = 'absolute';
                    knob.style.height = '18px';
                    knob.style.width = '18px';
                    knob.style.left = plugin.enabled ? '22px' : '4px';
                    knob.style.bottom = '3px';
                    knob.style.backgroundColor = 'white';
                    knob.style.transition = '0.3s';
                    knob.style.borderRadius = '50%';
                    
                    slider.appendChild(knob);
                    label.appendChild(input);
                    label.appendChild(slider);
                    
                    (function(pName, pInput, pSlider, pKnob) {
                        pInput.onchange = function() {
                            var checked = pInput.checked;
                            window.API.togglePlugin(pName, function(res) {
                                if (res && res.success) {
                                    pSlider.style.backgroundColor = checked ? '#22c55e' : '#3f3f46';
                                    pKnob.style.left = checked ? '22px' : '4px';
                                    // Recargar categorías y barra lateral después de alternar, y refrescar el catálogo
                                    window.Catalog.initCategoriesTree(function() {
                                        window.Catalog.load(window.Catalog.currentCategory || 'home');
                                    });
                                } else {
                                    pInput.checked = !checked;
                                    alert("Error al alternar el plugin.");
                                }
                            });
                        };
                    })(name, input, slider, knob);
                    
                    rightDiv.appendChild(label);
                    
                    item.appendChild(leftDiv);
                    item.appendChild(rightDiv);
                    container.appendChild(item);
                }
            }
        });
    },

    // Evento para toggle de permisos de Telegram
    toggleUserTelegramPermission: function(userId, isChecked) {
        var canSend = isChecked ? 1 : 0;
        window.API.toggleTelegramPermission(userId, canSend, function(res) {
            if (!res || !res.success) {
                alert("No se pudo actualizar el permiso.");
                // Recargar para restaurar estado real
                window.UI.loadAdminUsersList();
            }
        });
    },

    // Registrar nuevo usuario desde panel admin
    createUserFromAdmin: function() {
        var userEl = document.getElementById('admin-new-username');
        var passEl = document.getElementById('admin-new-password');

        var username = userEl ? userEl.value.trim() : '';
        var password = passEl ? passEl.value : '';

        if (!username || !password) {
            alert("Introduce usuario y contraseña válidos");
            return;
        }

        window.API.createUser(username, password, function(res) {
            if (res && res.success) {
                alert("¡Usuario registrado con éxito!");
                userEl.value = '';
                passEl.value = '';
                window.UI.loadAdminUsersList();
            } else {
                alert("Error: " + (res.detail || "No se pudo registrar el usuario"));
            }
        });
    },

    // Seleccionar URL manual
    selectAvatarUrl: function(url) {
        this.selectedAvatar = url.trim();
        // Desmarcar todos los emojis preset
        var avatarContainer = document.getElementById('avatar-presets');
        if (avatarContainer) {
            var items = avatarContainer.getElementsByClassName('avatar-preset-item');
            for (var i = 0; i < items.length; i++) items[i].classList.remove('active');
        }
    },

    // Subir archivo local (PC) y convertir a Base64 dataURL
    uploadAvatarFile: function(input) {
        var self = this;
        if (input.files && input.files[0]) {
            var reader = new FileReader();
            reader.onload = function(e) {
                self.selectedAvatar = e.target.result; // Base64 Data URL
                
                // Rellenar campo de texto para avisar
                var urlInput = document.getElementById('profile-avatar-url');
                if (urlInput) {
                    urlInput.value = '(Imagen subida desde PC)';
                }
                
                // Desmarcar emojis preset
                var avatarContainer = document.getElementById('avatar-presets');
                if (avatarContainer) {
                    var items = avatarContainer.getElementsByClassName('avatar-preset-item');
                    for (var i = 0; i < items.length; i++) items[i].classList.remove('active');
                }
            };
            reader.readAsDataURL(input.files[0]);
        }
    },

    // Cambiar contraseña de usuario actual
    changeUserPassword: function() {
        var currentPassEl = document.getElementById('profile-current-password');
        var newPassEl = document.getElementById('profile-new-password');
        var confirmPassEl = document.getElementById('profile-confirm-password');

        var currentPassword = currentPassEl ? currentPassEl.value : '';
        var newPassword = newPassEl ? newPassEl.value : '';
        var confirmPassword = confirmPassEl ? confirmPassEl.value : '';

        if (!currentPassword || !newPassword || !confirmPassword) {
            alert("Por favor, rellena todos los campos de contraseña");
            return;
        }

        if (newPassword !== confirmPassword) {
            alert("La nueva contraseña y la confirmación no coinciden");
            return;
        }

        window.API.changePassword(currentPassword, newPassword, function(res) {
            if (res && res.success) {
                alert("Contraseña cambiada con éxito");
                if (currentPassEl) currentPassEl.value = '';
                if (newPassEl) newPassEl.value = '';
                if (confirmPassEl) confirmPassEl.value = '';
            } else {
                alert("Error: " + (res.detail || "No se pudo cambiar la contraseña"));
            }
        });
    },

    // Alternar acceso de categoría para un usuario (solo para admin)
    toggleUserCategoryAccess: function(event, userId, category, currentAllowed) {
        var self = this;
        var badge = event.currentTarget || event.target;
        if (!badge) return;

        // Alternar visualmente de forma optimista e instantánea
        var isActive = badge.classList.contains('active');
        if (isActive) {
            badge.classList.remove('active');
        } else {
            badge.classList.add('active');
        }

        window.API.listUsers(function(res) {
            if (!res || !res.users) {
                // Revertir en caso de error
                if (isActive) badge.classList.add('active'); else badge.classList.remove('active');
                return;
            }
            var u = null;
            for (var fi = 0; fi < res.users.length; fi++) {
                if (res.users[fi].id === userId) {
                    u = res.users[fi];
                    break;
                }
            }
            if (!u) {
                if (isActive) badge.classList.add('active'); else badge.classList.remove('active');
                return;
            }

            var allowed = [];
            try {
                allowed = JSON.parse(u.allowed_categories || '[]');
            } catch(e){}

            window.API.getCategories(function(catsDict) {
                var allCats = Object.keys(catsDict);
                
                if (allowed.length === 0) {
                    // Acceso total por defecto. Al desactivar una, poblamos allowed con las demás.
                    for (var ci = 0; ci < allCats.length; ci++) {
                        var c = allCats[ci];
                        if (c.toLowerCase().trim() !== category.toLowerCase().trim()) {
                            allowed.push(c);
                        }
                    }
                } else {
                    // Modo restringido. Buscamos y alternamos.
                    var idx = -1;
                    for (var i = 0; i < allowed.length; i++) {
                        if (allowed[i].toLowerCase().trim() === category.toLowerCase().trim()) {
                            idx = i;
                            break;
                        }
                    }

                    if (idx !== -1) {
                        allowed.splice(idx, 1);
                    } else {
                        allowed.push(category);
                    }
                    
                    // Si vuelve a activar todas, dejamos en vacío para comportamiento por defecto.
                    if (allowed.length === allCats.length) {
                        allowed = [];
                    }
                }

                window.API.updateUserAllowedCategories(userId, JSON.stringify(allowed), function(saveRes) {
                    if (saveRes && saveRes.success) {
                        // Actualizar el atributo onclick dinámicamente para el próximo clic del usuario
                        var nextAllowed = !currentAllowed;
                        badge.setAttribute('onclick', 'window.UI.toggleUserCategoryAccess(event, ' + userId + ', \'' + category + '\', ' + nextAllowed + ')');
                    } else {
                        // Revertir estado visual en caso de error en el backend
                        if (isActive) badge.classList.add('active'); else badge.classList.remove('active');
                        alert("No se pudo actualizar la configuración de categorías.");
                    }
                });
            });
        });
    },

    // Cambiar de pestaña secundaria de avatar (OR visual)
    switchAvatarTab: function(event, tabName) {
        if (event) event.preventDefault();
        
        var buttons = document.querySelectorAll('.avatar-tab-btn');
        for (var bi = 0; bi < buttons.length; bi++) {
            buttons[bi].classList.remove('active');
        }
        
        var panes = document.querySelectorAll('.avatar-tab-pane');
        for (var pi = 0; pi < panes.length; pi++) {
            panes[pi].classList.add('hidden');
        }
        
        if (event && event.currentTarget) {
            event.currentTarget.classList.add('active');
        } else {
            // Activar botón correspondiente sin evento
            var activeBtn = null;
            for (var bi = 0; bi < buttons.length; bi++) {
                var clickAttr = buttons[bi].getAttribute('onclick') || '';
                if (clickAttr.indexOf("'" + tabName + "'") !== -1) {
                    activeBtn = buttons[bi];
                    break;
                }
            }
            if (activeBtn) activeBtn.classList.add('active');
        }
        
        var activePane = document.getElementById('avatar-pane-' + tabName);
        if (activePane) {
            activePane.classList.remove('hidden');
        }
    },

    toggleOpenLastSectionPreference: function(isChecked) {
        localStorage.setItem('tvcat_open_last_section', isChecked ? 'true' : 'false');
    },

    // --- Toggle avatar a la derecha ---
    toggleAvatarRight: function(isRight) {
        document.body.classList.toggle('avatar-right', isRight);
        localStorage.setItem('tvcat_avatar_right', isRight ? 'true' : 'false');
    },

    applyAvatarRight: function() {
        var stored = localStorage.getItem('tvcat_avatar_right');
        var isRight = stored === 'true';
        document.body.classList.toggle('avatar-right', isRight);
        var toggle = document.getElementById('screen-avatar-right-toggle');
        if (toggle) toggle.checked = isRight;
    },

    toggleDebugOverlay: function(isChecked) {
        localStorage.setItem('tvcat_show_debug_overlay', isChecked ? 'true' : 'false');
        var el = document.getElementById('dbg-overlay');
        if (el) {
            el.style.display = isChecked ? 'block' : 'none';
        }
    },



    promptAdminChangePassword: function(userId, username) {
        var newPass = prompt("Introduce la nueva contraseña para el usuario '" + username + "':");
        if (newPass === null) return; // cancelado
        window.API.adminChangePassword(userId, newPass, function(res) {
            if (res && res.success) {
                alert("¡Contraseña de '" + username + "' cambiada con éxito!");
            } else {
                alert("Error: " + (res.detail || "No se pudo cambiar la contraseña"));
            }
        });
    },

    confirmAdminDeleteUser: function(userId, username) {
        if (confirm("¿Estás seguro de que deseas eliminar permanentemente al usuario '" + username + "' y todos sus datos asociados? Esta acción no se puede deshacer.")) {
            window.API.adminDeleteUser(userId, function(res) {
                if (res && res.success) {
                    alert("El usuario '" + username + "' ha sido eliminado.");
                    window.UI.loadAdminUsersList();
                } else {
                    alert("Error: " + (res.detail || "No se pudo eliminar al usuario"));
                }
            });
        }
    }
};

// Reproductor: Handlers de cambios de tiempo de saltos y skip intro
window.changeWatchThresholdMin = function(val) {
    var v = parseInt(val) || 5;
    // Guardar en preferencia central de usuario (y en localStorage como respaldo/compatibilidad)
    localStorage.setItem('tvcat_watch_threshold_min', v);
    if (window.API && window.API.ajax) {
        window.API.ajax({ method: 'POST', url: '/api/config', data: { watch_threshold_min: v } });
    }
};
window.changeWatchThresholdMax = function(val) {
    var v = parseInt(val) || 85;
    localStorage.setItem('tvcat_watch_threshold_max', v);
    if (window.API && window.API.ajax) {
        window.API.ajax({ method: 'POST', url: '/api/config', data: { watch_threshold_max: v } });
    }
};
window.changePlayerJumpShort = function(val) {
    var v = parseInt(val) || 5;
    localStorage.setItem('tvcat_small_jump', v);
    console.log(" [CONFIG] tvcat_small_jump guardado:", v);
};

window.changePlayerJumpLong = function(val) {
    var v = parseInt(val) || 20;
    localStorage.setItem('tvcat_large_jump', v);
    console.log(" [CONFIG] tvcat_large_jump guardado:", v);
};

window.changePlayerSkipIntro = function(val) {
    var v = parseInt(val) || 80;
    localStorage.setItem('tvcat_intro_jump', v);
    console.log(" [CONFIG] tvcat_intro_jump guardado:", v);
};

// Helper: render category checkboxes from category data
function renderCategoryCheckboxes(apiResponse, container, user) {
    if (!apiResponse || !container) return;
    container.innerHTML = '';
    var prefs = {};
    try {
        prefs = JSON.parse(user.category_preferences || '{}');
    } catch(e){}

    var allowed = [];
    try {
        allowed = JSON.parse(user.allowed_categories || '[]');
    } catch(e){}

    var hasVisible = false;

    // La respuesta puede ser formato NUEVO (agrupado por plugin) o ANTIGUO (plano)
    // Detectar formato: si tiene keys con 'categories' anidados, es nuevo; si no, es antiguo
    var isNewFormat = false;
    for (var firstKey in apiResponse) {
        if (apiResponse.hasOwnProperty(firstKey)) {
            var firstVal = apiResponse[firstKey];
            if (firstVal && typeof firstVal === 'object' && firstVal.categories) {
                isNewFormat = true;
            }
            break;
        }
    }

    if (isNewFormat) {
        // FORMATO NUEVO: agrupado por plugin
        Object.keys(apiResponse).forEach(function(pluginName) {
            var pluginData = apiResponse[pluginName];
            if (!pluginData || !pluginData.enabled) return;
            var catsDict = pluginData.categories || {};
            var pluginCats = Object.keys(catsDict);
            if (pluginCats.length === 0) return;

            // Plugin section header
            var pluginHeader = document.createElement('div');
            pluginHeader.style.cssText = 'font-weight:700; font-size:0.85rem; color:#facc15; margin:12px 0 6px 0; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.06);';
            var shortName = (pluginData.displayName || pluginName).split('(')[0].trim();
            pluginHeader.textContent = shortName;
            container.appendChild(pluginHeader);

            pluginCats.forEach(function(cat) {
                var subcats = catsDict[cat] || [];

                if (allowed && allowed.length > 0) {
                    var isAllowed = false;
                    for (var k = 0; k < allowed.length; k++) {
                        if (allowed[k].toLowerCase().trim() === cat.toLowerCase().trim()) {
                            isAllowed = true;
                            break;
                        }
                    }
                    if (!isAllowed) return;
                }

                hasVisible = true;
                var isChecked = prefs[cat] !== false;

                var labelEl = document.createElement('label');
                labelEl.className = 'pref-check-item';

                var inputEl = document.createElement('input');
                inputEl.type = 'checkbox';
                inputEl.className = 'pref-cat-checkbox';
                inputEl.setAttribute('data-cat', cat);
                inputEl.checked = isChecked;

                var spanEl = document.createElement('span');
                spanEl.style.display = 'inline-block';
                spanEl.style.verticalAlign = 'middle';

                var catData = window.appLabels && window.appLabels[cat.toLowerCase()];
                if (catData) {
                    var icon = catData.image
                        ? '<img src="' + catData.image + '" style="width:16px; height:16px; object-fit:contain; border-radius:4px; display:inline-block; vertical-align:middle;" alt=""/>'
                        : (catData.emoji ? catData.emoji : '📦');
                    spanEl.innerHTML = icon + ' <span style="vertical-align:middle;">' + catData.label + '</span>';
                } else {
                    var displayCat = cat.charAt(0).toUpperCase() + cat.slice(1);
                    if (cat.toLowerCase() === 'game') displayCat = 'Juegos';
                    spanEl.innerHTML = '📦 <span style="vertical-align:middle;">' + displayCat + '</span>';
                }

                // Mostrar subcategorías como texto secundario
                if (subcats.length > 0) {
                    var subLabel = subcats.slice(0, 5).map(function(s) {
                        var sd = window.appLabels && window.appLabels[s.toLowerCase()];
                        return sd ? sd.label : s;
                    }).join(', ');
                    if (subcats.length > 5) subLabel += '...';
                    spanEl.innerHTML += ' <span style="color:#71717a; font-size:0.7rem;">(' + subLabel + ')</span>';
                }

                labelEl.appendChild(inputEl);
                labelEl.appendChild(spanEl);
                container.appendChild(labelEl);
            });
        });
    } else {
        // FORMATO ANTIGUO: plano (compatibilidad con legacy)
        for (var cat in apiResponse) {
            if (apiResponse.hasOwnProperty(cat)) {
                if (allowed && allowed.length > 0) {
                    var isAllowed = false;
                    for (var k = 0; k < allowed.length; k++) {
                        if (allowed[k].toLowerCase().trim() === cat.toLowerCase().trim()) {
                            isAllowed = true;
                            break;
                        }
                    }
                    if (!isAllowed) continue;
                }

                hasVisible = true;
                var isChecked = prefs[cat] !== false;

                var labelEl = document.createElement('label');
                labelEl.className = 'pref-check-item';

                var inputEl = document.createElement('input');
                inputEl.type = 'checkbox';
                inputEl.className = 'pref-cat-checkbox';
                inputEl.setAttribute('data-cat', cat);
                inputEl.checked = isChecked;

                var spanEl = document.createElement('span');
                spanEl.style.display = 'inline-block';
                spanEl.style.verticalAlign = 'middle';

                var catData = window.appLabels && window.appLabels[cat.toLowerCase()];
                if (catData) {
                    var icon = catData.image
                        ? '<img src="' + catData.image + '" style="width:16px; height:16px; object-fit:contain; border-radius:4px; display:inline-block; vertical-align:middle;" alt=""/>'
                        : (catData.emoji ? catData.emoji : '📦');
                    spanEl.innerHTML = icon + ' <span style="vertical-align:middle;">' + catData.label + '</span>';
                } else {
                    var displayCat = cat.charAt(0).toUpperCase() + cat.slice(1);
                    if (cat.toLowerCase() === 'game') displayCat = 'Juegos';
                    spanEl.innerHTML = '📦 <span style="vertical-align:middle;">' + displayCat + '</span>';
                }

                labelEl.appendChild(inputEl);
                labelEl.appendChild(spanEl);
                container.appendChild(labelEl);
            }
        }
    }

    if (!hasVisible) {
        container.innerHTML = '<div style="color: var(--text-secondary); padding: 10px; text-align: center;">No hay categorías disponibles</div>';
    }
}

// --- MÉTODOS DE CALIBRACIÓN INTERACTIVA DE MANDO ---

UI.startCalibration = function() {
    var self = this;
    self.isCalibrating = true;
    self.currentCalibratingDigitIndex = 0;
    
    var zone = document.getElementById('calibration-zone');
    if (zone) zone.classList.remove('hidden');

    self.calibrationDigits.forEach(function(d) {
        var el = document.getElementById('cal-btn-' + d);
        if (el) {
            el.style.background = '#222';
            el.style.borderColor = '#444';
            el.style.color = '#888';
            el.style.boxShadow = 'none';
        }
    });

    self.updateCalibrationUI();

    self.calibrationHandlerRef = function(e) { self.handleCalibrationKey(e); };
    window.addEventListener('keydown', self.calibrationHandlerRef, true);
};

UI.handleCalibrationKey = function(e) {
    var self = this;
    if (!self.isCalibrating) return;

    e.preventDefault();
    e.stopPropagation();

    var keyCode = e.keyCode || e.which;
    var currentTargetDigit = self.calibrationDigits[self.currentCalibratingDigitIndex];

    window.keyMapper.saveKeyMapping(keyCode, currentTargetDigit);
    console.log('[CALIBRATOR] Asignado keyCode ' + keyCode + ' al dígito virtual ' + currentTargetDigit);

    var el = document.getElementById('cal-btn-' + currentTargetDigit);
    if (el) {
        el.style.background = '#107c41';
        el.style.borderColor = '#107c41';
        el.style.color = '#fff';
        el.style.boxShadow = '0 0 10px rgba(16,124,65,0.5)';
    }

    self.currentCalibratingDigitIndex++;
    if (self.currentCalibratingDigitIndex < self.calibrationDigits.length) {
        self.updateCalibrationUI();
    } else {
        self.finishCalibration();
    }
};

UI.updateCalibrationUI = function() {
    var self = this;
    var currentTargetDigit = self.calibrationDigits[self.currentCalibratingDigitIndex];
    
    var promptSpan = document.getElementById('calibration-target-name');
    if (promptSpan) {
        promptSpan.textContent = currentTargetDigit;
    }

    self.calibrationDigits.forEach(function(d) {
        var btn = document.getElementById('cal-btn-' + d);
        if (btn && d === currentTargetDigit) {
            btn.style.background = '#e11d48';
            btn.style.borderColor = '#e11d48';
            btn.style.color = '#fff';
            btn.style.boxShadow = '0 0 12px rgba(225,29,72,0.6)';
        } else if (btn && self.calibrationDigits.indexOf(d) > self.currentCalibratingDigitIndex) {
            btn.style.background = '#222';
            btn.style.borderColor = '#444';
            btn.style.color = '#888';
            btn.style.boxShadow = 'none';
        }
    });
};

UI.finishCalibration = function() {
    var self = this;
    self.isCalibrating = false;
    
    if (self.calibrationHandlerRef) {
        window.removeEventListener('keydown', self.calibrationHandlerRef, true);
        self.calibrationHandlerRef = null;
    }

    var prompt = document.getElementById('calibration-prompt');
    if (prompt) {
        prompt.innerHTML = '🎉 <span style="color: #107c41; font-weight: bold;">¡Calibración completada con éxito!</span>';
    }

    setTimeout(function() {
        var zone = document.getElementById('calibration-zone');
        if (zone) zone.classList.add('hidden');
    }, 3000);
};

UI.clearCalibration = function() {
    var self = this;
    self.isCalibrating = false;
    if (self.calibrationHandlerRef) {
        window.removeEventListener('keydown', self.calibrationHandlerRef, true);
        self.calibrationHandlerRef = null;
    }

    window.keyMapper.clearCalibration();
    
    var zone = document.getElementById('calibration-zone');
    if (zone) zone.classList.add('hidden');

    alert('Se ha restaurado el mapeo numérico estándar de PC.');
};

window.toggleForceRemote = function(checked) {
    try { localStorage.setItem('tvcat_force_remote', checked ? 'true' : 'false'); } catch(e) {}
};

UI.loadVersionInfo = function() {
    var currentVerEl = document.getElementById('current-app-version');
    if (currentVerEl) {
        currentVerEl.textContent = '1.0.0';
    }
    var statusBadge = document.getElementById('update-status-badge');
    if (statusBadge) {
        statusBadge.textContent = 'Comprobando...';
        statusBadge.style.background = 'rgba(251, 191, 36, 0.1)';
        statusBadge.style.borderColor = 'rgba(251, 191, 36, 0.3)';
        statusBadge.style.color = '#fbbf24';
    }
    var newVerContainer = document.getElementById('new-version-container');
    if (newVerContainer) newVerContainer.classList.add('hidden');

    var applyBtn = document.getElementById('btn-apply-update');
    if (applyBtn) applyBtn.classList.add('hidden');
    
    window.API.checkUpdates(function(res) {
        if (currentVerEl && res.current_version) {
            currentVerEl.textContent = res.current_version;
        }
        if (res.update_available) {
            if (statusBadge) {
                statusBadge.textContent = 'Actualización Disponible';
                statusBadge.style.background = 'rgba(225, 29, 72, 0.1)';
                statusBadge.style.borderColor = 'rgba(225, 29, 72, 0.3)';
                statusBadge.style.color = '#e11d48';
            }
            var latestVerEl = document.getElementById('latest-app-version');
            if (latestVerEl) latestVerEl.textContent = res.latest_version;
            
            var changelogEl = document.getElementById('app-changelog');
            if (changelogEl) changelogEl.textContent = res.changelog || 'No hay descripción disponible.';
            
            if (newVerContainer) newVerContainer.classList.remove('hidden');
            if (applyBtn) {
                applyBtn.classList.remove('hidden');
                applyBtn.setAttribute('data-download-url', res.download_url);
            }
        } else {
            if (statusBadge) {
                statusBadge.textContent = 'Sistema Actualizado';
                statusBadge.style.background = 'rgba(16, 185, 129, 0.1)';
                statusBadge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
                statusBadge.style.color = '#10b981';
            }
        }
    });
};

UI.checkForUpdates = function() {
    var checkBtn = document.getElementById('btn-check-updates');
    if (checkBtn) {
        checkBtn.textContent = 'Buscando...';
        checkBtn.disabled = true;
    }
    
    window.API.checkUpdates(function(res) {
        if (checkBtn) {
            checkBtn.textContent = 'Buscar Actualizaciones';
            checkBtn.disabled = false;
        }
        
        var currentVerEl = document.getElementById('current-app-version');
        if (currentVerEl && res.current_version) {
            currentVerEl.textContent = res.current_version;
        }
        
        var statusBadge = document.getElementById('update-status-badge');
        var newVerContainer = document.getElementById('new-version-container');
        var applyBtn = document.getElementById('btn-apply-update');
        
        if (res.update_available) {
            if (statusBadge) {
                statusBadge.textContent = 'Actualización Disponible';
                statusBadge.style.background = 'rgba(225, 29, 72, 0.1)';
                statusBadge.style.borderColor = 'rgba(225, 29, 72, 0.3)';
                statusBadge.style.color = '#e11d48';
            }
            var latestVerEl = document.getElementById('latest-app-version');
            if (latestVerEl) latestVerEl.textContent = res.latest_version;
            
            var changelogEl = document.getElementById('app-changelog');
            if (changelogEl) changelogEl.textContent = res.changelog || 'No hay descripción disponible.';
            
            if (newVerContainer) newVerContainer.classList.remove('hidden');
            if (applyBtn) {
                applyBtn.classList.remove('hidden');
                applyBtn.setAttribute('data-download-url', res.download_url);
            }
            alert('¡Nueva versión ' + res.latest_version + ' disponible para descargar!');
        } else {
            if (statusBadge) {
                statusBadge.textContent = 'Sistema Actualizado';
                statusBadge.style.background = 'rgba(16, 185, 129, 0.1)';
                statusBadge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
                statusBadge.style.color = '#10b981';
            }
            if (newVerContainer) newVerContainer.classList.add('hidden');
            if (applyBtn) applyBtn.classList.add('hidden');
            alert('Estás utilizando la última versión de TVCat (' + (res.current_version || '1.0.0') + ').');
        }
    });
};

UI.triggerUpdate = function() {
    var applyBtn = document.getElementById('btn-apply-update');
    var downloadUrl = applyBtn ? applyBtn.getAttribute('data-download-url') : '';
    if (!downloadUrl) {
        alert('No se pudo encontrar la dirección de descarga de la actualización.');
        return;
    }
    
    if (!confirm('¿Estás seguro de que deseas actualizar TVCat ahora?\nSe creará una copia de seguridad y la aplicación se reiniciará automáticamente.')) {
        return;
    }
    
    if (window.Catalog && typeof window.Catalog.showGlobalLoader === 'function') {
        window.Catalog.showGlobalLoader('Descargando actualización y aplicando copia de seguridad...\nPor favor, no apagues el servidor.');
    }
    
    window.API.triggerUpdate(downloadUrl, function(res) {
        var count = 0;
        var checkReconnection = function() {
            count++;
            if (window.Catalog && typeof window.Catalog.showGlobalLoader === 'function') {
                window.Catalog.showGlobalLoader('Aplicando actualización y reiniciando el servicio...\nIntento de reconexión #' + count);
            }
            var xhr = new XMLHttpRequest();
            xhr.open('GET', '/api/version/check?t=' + Date.now(), true);
            xhr.timeout = 2500;
            xhr.onload = function() {
                if (xhr.status === 200) {
                    if (window.Catalog && typeof window.Catalog.hideGlobalLoader === 'function') {
                        window.Catalog.hideGlobalLoader();
                    }
                    alert('¡TVCat se ha actualizado y reiniciado con éxito!');
                    window.location.reload(true);
                } else {
                    setTimeout(checkReconnection, 3000);
                }
            };
            xhr.onerror = function() {
                setTimeout(checkReconnection, 3000);
            };
            xhr.ontimeout = function() {
                setTimeout(checkReconnection, 3000);
            };
            xhr.send();
        };
        setTimeout(checkReconnection, 4000);
        
    }, function(err) {
        if (window.Catalog && typeof window.Catalog.hideGlobalLoader === 'function') {
            window.Catalog.hideGlobalLoader();
        }
        alert('Error al disparar la actualización: ' + (err && err.detail ? err.detail : 'Desconocido'));
    });
};

window.UI = UI;

// Exportar globalmente para eventos en HTML
window.checkForUpdates = function() { UI.checkForUpdates(); };
window.triggerUpdate = function() { UI.triggerUpdate(); };

// Exportar globalmente para eventos en HTML
window.toggleSideMenu = function() { UI.toggleSideMenu(); };
window.toggleSettingsModal = function() { UI.toggleSettingsModal(); };
window.switchSettingsTab = function(t) { UI.switchSettingsTab(t); };
window.saveUserProfileChanges = function() { UI.saveUserProfileChanges(); };
window.saveGlobalSettings = function() { UI.saveGlobalSettings(); };
window.changeScreenColumns = function(v) { UI.changeScreenColumns(v); };
window.createUserFromAdmin = function() { UI.createUserFromAdmin(); };
window.changeUserPassword = function() { UI.changeUserPassword(); };
window.toggleUserCategoryAccess = function(uid, cat, allowed) { UI.toggleUserCategoryAccess(uid, cat, allowed); };
window.switchAvatarTab = function(ev, tab) { if (typeof ev === 'string' && tab === undefined) { tab = ev; ev = null; } UI.switchAvatarTab(ev, tab); };
window.selectAvatarUrl = function(url) { UI.selectAvatarUrl(url); };
window.promptAdminChangePassword = function(uid, uname) { UI.promptAdminChangePassword(uid, uname); };
window.confirmAdminDeleteUser = function(uid, uname) { UI.confirmAdminDeleteUser(uid, uname); };
window.toggleOpenLastSectionPreference = function(chk) { UI.toggleOpenLastSectionPreference(chk); };
window.toggleDebugOverlay = function(chk) { UI.toggleDebugOverlay(chk); };


// --- CONFIGURACIÓN DE USERBOT (TVCAT_USER) ---
function openUserbotConfigModal() {
    var modal = document.createElement('div');
    modal.id = 'tvcat-userbot-modal';
    modal.style.position = 'fixed';
    modal.style.top = '0';
    modal.style.left = '0';
    modal.style.width = '100vw';
    modal.style.height = '100vh';
    modal.style.background = 'rgba(9, 9, 11, 0.85)';
    modal.style.backdropFilter = 'blur(10px)';
    modal.style.zIndex = '99999';
    modal.style.display = 'flex';
    modal.style.alignItems = 'center';
    modal.style.justifyContent = 'center';
    modal.style.opacity = '0';
    modal.style.transition = 'opacity 0.25s ease';
    
    var dialog = document.createElement('div');
    dialog.style.background = 'rgba(24, 24, 27, 0.95)';
    dialog.style.border = '1px solid rgba(63, 63, 70, 0.6)';
    dialog.style.borderRadius = '16px';
    dialog.style.width = '90%';
    dialog.style.maxWidth = '680px';
    dialog.style.maxHeight = '85vh';
    dialog.style.boxShadow = '0 25px 50px -12px rgba(0, 0, 0, 0.5)';
    dialog.style.display = 'flex';
    dialog.style.flexDirection = 'column';
    dialog.style.overflow = 'hidden';
    dialog.style.transform = 'scale(0.95)';
    dialog.style.transition = 'transform 0.25s ease';
    
    dialog.innerHTML = '' +
        '<div style="flex-shrink: 0; background: rgba(24, 24, 27, 0.98); display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(63, 63, 70, 0.4); padding: 14px 24px 10px 24px;">' +
            '<div style="display: flex; align-items: center;">' +
                '<span style="font-size: 1.25rem; margin-right: 8px;">🌌</span>' +
                '<div>' +
                    '<h3 style="margin: 0; font-size: 1.1rem; font-weight: 800; color: #f4f4f5; font-family: &quot;Outfit&quot;, sans-serif;">TGIndex</h3>' +
                '</div>' +
            '</div>' +
            '<button id="userbot-modal-close" style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #f87171; border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; cursor: pointer; font-weight: bold; transition: all 0.2s; flex-shrink: 0; margin-left: 12px; line-height: 1;">&times;</button>' +
        '</div>' +
        '<div style="flex: 1; overflow-y: auto; padding: 20px 24px 24px 24px;">' +

        '<!-- Nota Informativa -->' +
        '<div style="font-size: 0.75rem; color: #a1a1aa; line-height: 1.4; background: rgba(39, 39, 42, 0.4); border: 1px solid rgba(63, 63, 70, 0.3); padding: 10px 12px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: center; gap: 8px;">' +
            '<span>ℹ️</span> <span>Indexa tu biblioteca personal de canales Telegram de forma autónoma.</span>' +
        '</div>' +

        '<!-- 1. Configuración General del Plugin -->' +
        '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px; margin-bottom: 20px;">' +
        '    <h4 style="margin: 0 0 12px 0; font-size: 0.95rem; font-weight: 700; color: #c084fc; display: flex; align-items: center;">⚙️ Configuración General del Plugin</h4>' +
        '    <div>' +
        '        <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(9, 9, 11, 0.4); padding: 10px 14px; border-radius: 8px; border: 1px solid rgba(63, 63, 70, 0.2); margin-bottom: 12px;">' +
        '            <div style="display: flex; flex-direction: column; gap: 2px;">' +
        '                <span style="font-size: 0.8rem; font-weight: 700; color: #e4e4e7;">Refresco automático por ciclos</span>' +
        '                <span style="font-size: 0.7rem; color: #71717a;">Activa el escaneo periódico automático según los ciclos configurados por canal.</span>' +
        '            </div>' +
        '            <label style="position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; margin-left: 16px;">' +
        '                <input type="checkbox" id="plugin-scan-enabled" style="opacity: 0; width: 0; height: 0;">' +
        '                <span id="plugin-scan-slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background: #3f3f46; border-radius: 24px; transition: 0.3s;"></span>' +
        '            </label>' +
        '        </div>' +
        '        <div id="plugin-cycle-config" style="display: flex; align-items: flex-end; background: rgba(9, 9, 11, 0.4); padding: 10px 14px; border-radius: 8px; border: 1px solid rgba(63, 63, 70, 0.2); margin-bottom: 12px;">' +
        '            <div style="flex: 1; margin-right: 10px;">' +
        '                <label style="display: block; font-size: 0.75rem; font-weight: 600; color: #e4e4e7; margin-bottom: 4px;">Minutos por Ciclo</label>' +
        '                <input type="number" id="plugin-cycle-minutes" min="1" placeholder="Ej: 30" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 0.8rem; box-sizing: border-box;">' +
        '                <span style="font-size: 0.65rem; color: #71717a; margin-top: 2px; display: block;">Intervalo mínimo entre ciclos de escaneo global. Mínimo recomendado: 30 minutos.</span>' +
        '            </div>' +
        '            <button id="plugin-config-save-btn" style="background: #a855f7; border: none; border-radius: 6px; padding: 8px 16px; color: white; font-weight: 700; font-size: 0.8rem; cursor: pointer; transition: background 0.2s; white-space: nowrap;">Guardar</button>' +
        '        </div>' +
        '        <div id="plugin-config-status" style="font-size: 0.75rem; font-weight: 600;"></div>' +
        '    </div>' +
        '</div>' +

        '<!-- 2. Credenciales Telegram (Colapsable) -->' +
        '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px; margin-bottom: 20px;">' +
        '    <div id="credentials-collapse-trigger" style="display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none;">' +
        '        <h4 style="margin: 0; font-size: 0.95rem; font-weight: 700; color: #c084fc; display: flex; align-items: center;">🔑 Credenciales Telegram</h4>' +
        '        <span id="credentials-collapse-indicator" style="font-size: 0.75rem; color: #a1a1aa;">▶</span>' +
        '    </div>' +
        '    <div id="credentials-collapse-body" style="display: none; margin-top: 14px;">' +
        '        <div style="font-size: 0.75rem; color: #a1a1aa; line-height: 1.6; background: rgba(168, 85, 247, 0.08); border-left: 3px solid #a855f7; padding: 8px 10px; border-radius: 4px; margin-bottom: 12px;">' +
        '            💡 Las credenciales <strong>API ID</strong> y <strong>API Hash</strong>, así como la sesión de la cuenta principal, se configuran ahora en la <strong>Configuración de TVCat &rarr; Userbot</strong>.' +
        '        </div>' +
        '        <div style="background: rgba(9, 9, 11, 0.4); padding: 12px; border-radius: 8px; border: 1px solid rgba(63, 63, 70, 0.2); margin-bottom: 12px;">' +
        '            <div style="margin-bottom: 10px;">' +
        '                <label style="display: block; font-size: 0.75rem; font-weight: 600; color: #e4e4e7; margin-bottom: 4px;">Pega una String Session existente</label>' +
        '                <textarea id="pasted-string-session" rows="2" placeholder="Pega tu String Session aquí..." style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 6px; padding: 8px 10px; color: #f4f4f5; font-size: 0.8rem; font-family: monospace; resize: vertical; box-sizing: border-box;"></textarea>' +
        '            </div>' +
        '            <div style="display: flex; margin-bottom: 8px;">' +
        '                <button id="session-test-btn" style="flex: 1; margin-right: 10px; background: rgba(168, 85, 247, 0.2); border: 1px solid #a855f7; border-radius: 6px; padding: 8px 12px; color: #c084fc; font-weight: 700; font-size: 0.8rem; cursor: pointer; transition: all 0.2s;">Probar</button>' +
        '                <button id="session-save-btn" disabled style="flex: 1; margin-right: 10px; background: #22c55e; border: none; border-radius: 6px; padding: 8px 12px; color: white; font-weight: 700; font-size: 0.8rem; cursor: not-allowed; opacity: 0.5; transition: all 0.2s;">Guardar</button>' +
        '                <button id="session-generate-btn" style="flex: 1; background: #a855f7; border: none; border-radius: 6px; padding: 8px 12px; color: white; font-weight: 700; font-size: 0.8rem; cursor: pointer; transition: background 0.2s;">Generar</button>' +
        '            </div>' +
        '            <div id="session-test-status" style="font-size: 0.75rem; font-weight: 600;"></div>' +
        '        </div>' +
        '        <div id="accounts-list" style="max-height: 120px; overflow-y: auto;">' +
        '        </div>' +
        '    </div>' +
        '</div>' +

        '<!-- 3. Gestión de Canales -->' +
        '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px; margin-bottom: 20px;">' +
        '    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">' +
        '        <h4 style="margin: 0; font-size: 0.95rem; font-weight: 700; color: #c084fc;">📡 Gestión de Canales</h4>' +
        '        <button id="add-channel-toggle-btn" style="background: #a855f7; border: none; border-radius: 6px; padding: 6px 14px; color: white; font-weight: bold; font-size: 0.75rem; cursor: pointer; transition: background 0.2s;">➕ Nuevo</button>' +
        '    </div>' +
        '    ' +
        '    <!-- Panel de añadir nuevo (oculto por defecto) -->' +
        '    <div id="add-channel-panel" style="display: none; background: rgba(9, 9, 11, 0.4); padding: 12px; border-radius: 8px; border: 1px solid rgba(63, 63, 70, 0.2); margin-bottom: 12px;">' +
        '        <div style="display: flex; margin-bottom: 10px;">' +
        '            <div style="flex: 1.2; margin-right: 10px;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Mensaje de Inicio (URL o nº)</label>' +
        '                <input type="text" id="new-channel-start" oninput="autofillNewChannelId()" placeholder="https://t.me/c/3949316267/2 o 2" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box;">' +
        '            </div>' +
        '            <div style="flex: 1; margin-right: 10px;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">ID del Canal (editable)</label>' +
        '                <input type="text" id="new-channel-id" placeholder="-1003949316267" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box;">' +
        '            </div>' +
        '            <div style="flex: 1;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Mensaje de Fin (Opcional)</label>' +
        '                <input type="text" id="new-channel-end" placeholder="URL o nº (vacío = hasta el último)" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box;">' +
        '            </div>' +
        '        </div>' +
        '        <div style="display: flex; margin-bottom: 10px;">' +
        '            <div style="flex: 1.2; margin-right: 10px;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Nombre en UI</label>' +
        '                <input type="text" id="new-channel-name" placeholder="Mi Serie / Canal" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box;">' +
        '            </div>' +
        '            <div style="flex: 1;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Topología</label>' +
        '                <select id="new-channel-topology" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 3px 6px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
        '                    <option value="1">Tipo 1: Plano (Secuencial)</option>' +
        '                    <option value="2">Tipo 2: Temas Temáticos</option>' +
        '                    <option value="3">Tipo 3: Tema por Título</option>' +
        '                </select>' +
        '            </div>' +
        '            <div style="flex: 1;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Contenido</label>' +
        '                <select id="new-channel-content-type" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 3px 6px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
        '                    <option value="media">Multimedia</option>' +
        '                    <option value="ebook">Ebook</option>' +
        '                    <option value="audiolibro">Audiolibro</option>' +
        '                    <option value="game">Juego</option>' +
        '                </select>' +
        '            </div>' +
        '            <div style="flex: 1;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Subcategoría (Opcional)</label>' +
        '                <input type="text" id="new-channel-subcategory" placeholder="Serie, Película..." style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
        '            </div>' +
        '            <div style="flex: 1;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Auto-refresh</label>' +
        '                <input type="text" id="new-channel-refresh" placeholder="Vacío = desc." style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
        '            </div>' +
        '        </div>' +
        '        ' +
        '        <div style="display: flex; align-items: flex-end; margin-top: 10px;">' +
        '            <div style="flex: 1.5; margin-right: 10px;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Cuenta de Telegram</label>' +
        '                <select id="new-channel-account" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 3px 6px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
        '                    <option value="">(Debe añadir una cuenta telegram)</option>' +
        '                </select>' +
        '            </div>' +
        '            <div style="flex: 1; margin-right: 10px;">' +
        '                <label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Ciclos de Refresco</label>' +
        '                <input type="number" id="new-channel-cycles" min="1" value="1" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
        '            </div>' +
        '            <button id="test-channel-btn" disabled style="margin-right: 10px; background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.4); border-radius: 4px; padding: 4px 12px; height: 26px; color: #c084fc; font-weight: bold; cursor: not-allowed; opacity: 0.5; transition: background 0.2s; font-size: 0.75rem;">Probar Canal</button>' +
        '            <button id="add-channel-btn" disabled style="background: #22c55e; border: none; border-radius: 4px; padding: 4px 16px; height: 26px; color: white; font-weight: bold; cursor: not-allowed; opacity: 0.5; transition: background 0.2s; font-size: 0.75rem;">Añadir</button>' +
        '        </div>' +
        '    </div>' +
        '    ' +
        '    <div id="channels-list" style="max-height: 480px; overflow-y: auto;">' +
        '    </div>' +
        '</div>' +
        '' +
        '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px;">' +
        '    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">' +
        '        <h4 style="margin: 0; font-size: 0.95rem; font-weight: 700; color: #c084fc;">🚀 Ejecución y Consola del Escáner</h4>' +
        '        <button id="start-scan-btn" style="background: #a855f7; border: none; border-radius: 6px; padding: 6px 12px; color: white; font-weight: bold; font-size: 0.75rem; cursor: pointer; transition: background 0.2s;">Actualizar todos los canales</button>' +
        '    </div>' +
        '    ' +
        '    <div id="scan-progress-container" style="display: none; margin-bottom: 10px;">' +
        '        <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: #e4e4e7; margin-bottom: 4px;">' +
        '            <span id="scan-status-text">Indexando biblioteca...</span>' +
        '            <span id="scan-percent-text">0%</span>' +
        '        </div>' +
        '        <div style="width: 100%; height: 6px; background: #27272a; border-radius: 3px; overflow: hidden;">' +
        '            <div id="scan-progress-bar" style="width: 0%; height: 100%; background: linear-gradient(90deg, #a855f7, #c084fc); transition: width 0.3s ease;"></div>' +
        '        </div>' +
        '    </div>' +
        '    ' +
        '    <div style="display: flex; align-items: flex-start;">' +
        '        <pre id="scanner-console" style="flex: 1; margin-right: 10px; background: #09090b; border: 1px solid #27272a; border-radius: 6px; padding: 10px; font-family: monospace; font-size: 0.7rem; color: #4ade80; max-height: 120px; overflow-y: auto; margin: 0; white-space: pre-wrap; line-height: 1.4;"></pre>' +
        '        <button id="copy-log-btn" style="background: #27272a; border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 10px; color: #a1a1aa; font-size: 0.7rem; cursor: pointer; transition: all 0.2s; white-space: nowrap; align-self: flex-start;" onclick="' +
        'var txt = document.getElementById(&quot;scanner-console&quot;).textContent;' +
        'var ta = document.createElement(&quot;textarea&quot;);' +
        'ta.value = txt;' +
        'ta.style.position = &quot;fixed&quot;;' +
        'ta.style.opacity = &quot;0&quot;;' +
        'document.body.appendChild(ta);' +
        'ta.select();' +
        'try { document.execCommand(&quot;copy&quot;); document.getElementById(&quot;copy-log-btn&quot;).textContent=&quot;✓ Copiado&quot;; } catch(e) { prompt(&quot;Copia manual:&quot;, txt); }' +
        'document.body.removeChild(ta);' +
        'setTimeout(function(){ document.getElementById(&quot;copy-log-btn&quot;).textContent=&quot;Copiar log&quot;; }, 2000);' +
        '">Copiar log</button>' +
        '    </div>' +
        '    <div style="display: flex; justify-content: flex-end; margin-top: 24px; border-top: 1px solid rgba(63, 63, 70, 0.4); padding-top: 16px;">' +
        '        <button id="userbot-modal-close-bottom" style="background: #27272a; border: 1px solid #3f3f46; border-radius: 6px; padding: 8px 20px; color: #f4f4f5; font-size: 0.85rem; font-weight: bold; cursor: pointer; transition: all 0.2s;">Cerrar Configuración</button>' +
        '    </div>' +
        '</div>' +
        '</div>';;
    
    modal.appendChild(dialog);
    document.body.appendChild(modal);
    
    setTimeout(function() {
        modal.style.opacity = '1';
        dialog.style.transform = 'scale(1)';
    }, 10);
    
    var closeModal = function() {
        modal.style.opacity = '0';
        dialog.style.transform = 'scale(0.95)';
        setTimeout(function() {
            modal.remove();
        }, 250);
        if (window.scannerPollInterval) {
            clearInterval(window.scannerPollInterval);
        }
    };
    
    document.getElementById('userbot-modal-close').onclick = closeModal;
    var closeBtnBottom = document.getElementById('userbot-modal-close-bottom');
    if (closeBtnBottom) closeBtnBottom.onclick = closeModal;
    
    var loadConfig = function() {
        // Los campos de API ID y API Hash ya no están en este modal.
        // La configuración global se gestiona desde la pestaña Userbot en Configuración de TVCat.
        // Mantenemos la función por compatibilidad pero no hace nada.
    };


    var updateToggleVisual = function(enabled) {
        var slider = document.getElementById('plugin-scan-slider');
        if (!slider) return;
        if (enabled) {
            slider.style.background = '#a855f7';
            slider.style.setProperty('--knob-x', '20px');
            slider.style.boxShadow = 'inset 20px 0 0 0 transparent';
        } else {
            slider.style.background = '#3f3f46';
        }
        // Knob via pseudo-element: use a child span trick
        var knob = slider.querySelector('span');
        if (!knob) {
            knob = document.createElement('span');
            knob.style.cssText = 'position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:white;border-radius:50%;transition:0.3s;';
            slider.appendChild(knob);
        }
        knob.style.transform = enabled ? 'translateX(20px)' : 'translateX(0)';
    };

    var loadPluginConfig = function() {
        window.API.ajax({
            url: '/api/plugin/config',
            success: function(res) {
                if (res) {
                    var cycleInput = document.getElementById('plugin-cycle-minutes');
                    var toggle = document.getElementById('plugin-scan-enabled');
                    if (cycleInput) cycleInput.value = res.cycle_minutes || 30;
                    if (toggle) {
                        toggle.checked = res.scan_enabled !== false;
                        updateToggleVisual(toggle.checked);
                    }
                }
            }
        });
    };

    var loadAccountsForSelect = function() {
        window.API.ajax({
            url: '/api/admin/telegram/accounts',
            success: function(res) {
                var selectEl = document.getElementById('new-channel-account');
                var addBtn = document.getElementById('add-channel-btn');
                var testBtn = document.getElementById('test-channel-btn');
                if (selectEl && res) {
                    if (res.length > 0) {
                        selectEl.innerHTML = '';
                        res.forEach(function(acc) {
                            var opt = document.createElement('option');
                            opt.value = acc.id;
                            opt.textContent = acc.display_name;
                            selectEl.appendChild(opt);
                        });
                        if (addBtn) {
                            addBtn.disabled = false;
                            addBtn.style.cursor = 'pointer';
                            addBtn.style.opacity = '1';
                        }
                        if (testBtn) {
                            testBtn.disabled = false;
                            testBtn.style.cursor = 'pointer';
                            testBtn.style.opacity = '1';
                        }
                    } else {
                        selectEl.innerHTML = '<option value="">(Debe añadir una cuenta telegram)</option>';
                        if (addBtn) {
                            addBtn.disabled = true;
                            addBtn.style.cursor = 'not-allowed';
                            addBtn.style.opacity = '0.5';
                        }
                        if (testBtn) {
                            testBtn.disabled = true;
                            testBtn.style.cursor = 'not-allowed';
                            testBtn.style.opacity = '0.5';
                        }
                    }
                }
            }
        });
    };

    var loadAccountsList = function() {
        window.API.ajax({
            url: '/api/admin/telegram/accounts',
            success: function(res) {
                var listEl = document.getElementById('accounts-list');
                if (listEl && res) {
                    listEl.innerHTML = '';
                    if (res.length === 0) {
                        listEl.innerHTML = '<div style="font-size: 0.75rem; color: #71717a; text-align: center; padding: 10px;">No hay cuentas de Telegram vinculadas adicionales.</div>';
                        return;
                    }
                    res.forEach(function(acc) {
                        var accRow = document.createElement('div');
                        accRow.style.display = 'flex';
                        accRow.style.alignItems = 'center';
                        accRow.style.justifyContent = 'space-between';
                        accRow.style.background = 'rgba(9, 9, 11, 0.3)';
                        accRow.style.border = '1px solid rgba(63, 63, 70, 0.3)';
                        accRow.style.borderRadius = '6px';
                        accRow.style.padding = '6px 10px';
                        
                         accRow.innerHTML = 
                            '<div style="display: flex; align-items: center; flex: 1;">' +
                                '<span style="font-size: 0.8rem; font-weight: 700; color: #f4f4f5;">' + acc.display_name + '</span>' +
                            '</div>' +
                            '<div style="display: flex; gap: 6px;">' +
                                '<button class="edit-acc-btn" data-id="' + acc.id + '" style="background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.4); border-radius: 4px; color: #c084fc; font-size: 0.7rem; padding: 2px 6px; cursor: pointer; transition: all 0.2s;">✏️ Editar</button>' +
                                (acc.id !== -1 ? '<button class="delete-acc-btn" data-id="' + acc.id + '" style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 4px; color: #f87171; font-size: 0.7rem; padding: 2px 6px; cursor: pointer; transition: all 0.2s;">🗑️ Eliminar</button>' : '') +
                            '</div>';
                        
                        accRow.querySelector('.edit-acc-btn').onclick = function() {
                            var newName = prompt('Introduce el nuevo pseudónimo para esta cuenta:', acc.display_name);
                            if (newName === null) return;
                            newName = newName.trim();
                            if (!newName) {
                                alert('El pseudónimo no puede estar vacío.');
                                return;
                            }
                            window.API.ajax({
                                method: 'POST',
                                url: '/api/admin/telegram/accounts/' + acc.id + '/display_name',
                                headers: { 'Content-Type': 'application/json' },
                                body: { display_name: newName },
                                success: function(editRes) {
                                    if (editRes && editRes.success) {
                                        loadAccountsList();
                                        loadAccountsForSelect();
                                    } else {
                                        alert('Error al actualizar el pseudónimo.');
                                    }
                                }
                            });
                        };

                         var delBtn = accRow.querySelector('.delete-acc-btn');
                         if (delBtn) {
                             delBtn.onclick = function() {
                                 if (!confirm('¿Estás seguro de que deseas desvincular la cuenta "' + acc.display_name + '"?')) {
                                     return;
                                 }
                                 window.API.ajax({
                                     method: 'DELETE',
                                     url: '/api/admin/telegram/accounts/' + acc.id,
                                     success: function(delRes) {
                                         loadAccountsList();
                                         loadAccountsForSelect();
                                     }
                                 });
                             };
                         }
                         listEl.appendChild(accRow);
                    });
                }
            }
        });
    };

    // openSessionGeneratorModal ha sido extraída al ámbito global

    var lastTestedSession = null;

    document.getElementById('session-test-btn').onclick = function() {
        var sessionStr = document.getElementById('pasted-string-session').value.trim();
        var statusDiv = document.getElementById('session-test-status');
        var saveBtn = document.getElementById('session-save-btn');
        
        if (!sessionStr) {
            alert('Por favor pega una String Session.');
            return;
        }
        
        statusDiv.innerHTML = '⏳ Verificando String Session con Telegram...';
        statusDiv.style.color = '#facc15';
        saveBtn.disabled = true;
        saveBtn.style.cursor = 'not-allowed';
        saveBtn.style.opacity = '0.5';
        lastTestedSession = null;
        
        window.API.ajax({
            method: 'POST',
            url: '/api/admin/telegram/accounts/test_session',
            headers: { 'Content-Type': 'application/json' },
            body: { session_string: sessionStr },
            success: function(res) {
                if (res && res.success) {
                    statusDiv.innerHTML = '✅ Conectado con éxito como @' + res.username;
                    statusDiv.style.color = '#4ade80';
                    saveBtn.disabled = false;
                    saveBtn.style.cursor = 'pointer';
                    saveBtn.style.opacity = '1';
                    lastTestedSession = {
                        username: res.username,
                        phone: res.phone || 'Manual',
                        session_string: sessionStr
                    };
                } else {
                    statusDiv.innerHTML = '🔴 Fallo: ' + (res ? res.error : 'Error desconocido');
                    statusDiv.style.color = '#f87171';
                }
            },
            error: function(err) {
                statusDiv.innerHTML = '🔴 Error de red al verificar la sesión.';
                statusDiv.style.color = '#f87171';
            }
        });
    };

    document.getElementById('session-save-btn').onclick = function() {
        var statusDiv = document.getElementById('session-test-status');
        var saveBtn = document.getElementById('session-save-btn');
        
        if (!lastTestedSession) {
            alert('Por favor prueba la sesión con éxito antes de guardar.');
            return;
        }
        
        statusDiv.innerHTML = '⏳ Guardando cuenta de Telegram...';
        statusDiv.style.color = '#facc15';
        
        window.API.ajax({
            method: 'POST',
            url: '/api/admin/telegram/accounts/save',
            headers: { 'Content-Type': 'application/json' },
            body: lastTestedSession,
            success: function(res) {
                if (res && res.success) {
                    statusDiv.innerHTML = '✅ Cuenta @' + lastTestedSession.username + ' guardada y vinculada.';
                    statusDiv.style.color = '#4ade80';
                    document.getElementById('pasted-string-session').value = '';
                    saveBtn.disabled = true;
                    saveBtn.style.cursor = 'not-allowed';
                    saveBtn.style.opacity = '0.5';
                    lastTestedSession = null;
                    
                    loadAccountsList();
                    loadAccountsForSelect();
                } else {
                    statusDiv.innerHTML = '🔴 Error al guardar en base de datos.';
                    statusDiv.style.color = '#f87171';
                }
            },
            error: function(err) {
                statusDiv.innerHTML = '🔴 Error de red al guardar.';
                statusDiv.style.color = '#f87171';
            }
        });
    };

     // Evento para colapsar/expandir Credenciales Telegram
     var credTrigger = document.getElementById('credentials-collapse-trigger');
     var credBody = document.getElementById('credentials-collapse-body');
     var credIndicator = document.getElementById('credentials-collapse-indicator');
     if (credTrigger && credBody && credIndicator) {
         credTrigger.onclick = function() {
             if (credBody.style.display === 'none') {
                 credBody.style.display = 'block';
                 credIndicator.textContent = '▼';
             } else {
                 credBody.style.display = 'none';
                 credIndicator.textContent = '▶';
             }
         };
     }

     // Evento para mostrar/ocultar panel de añadir canal ("Nuevo")
     var addChannelToggleBtn = document.getElementById('add-channel-toggle-btn');
     var addChannelPanel = document.getElementById('add-channel-panel');
     if (addChannelToggleBtn && addChannelPanel) {
         addChannelToggleBtn.onclick = function() {
             if (addChannelPanel.style.display === 'none') {
                 addChannelPanel.style.display = 'block';
                 addChannelToggleBtn.textContent = 'Cancelar';
                 addChannelToggleBtn.style.background = 'rgba(239, 68, 68, 0.2)';
                 addChannelToggleBtn.style.color = '#f87171';
                 addChannelToggleBtn.style.border = '1px solid rgba(239, 68, 68, 0.4)';
             } else {
                 addChannelPanel.style.display = 'none';
                 addChannelToggleBtn.textContent = '➕ Nuevo';
                 addChannelToggleBtn.style.background = '#a855f7';
                 addChannelToggleBtn.style.color = 'white';
                 addChannelToggleBtn.style.border = 'none';
             }
         };
     }

     // Toggle visual del plugin-scan-enabled
     document.getElementById('plugin-scan-enabled').onchange = function() {
         updateToggleVisual(this.checked);
     };

     // Guardar configuración del plugin
     document.getElementById('plugin-config-save-btn').onclick = function() {
         var cycleMinutes = parseInt(document.getElementById('plugin-cycle-minutes').value, 10) || 30;
         var scanEnabled = document.getElementById('plugin-scan-enabled').checked;
         var statusDiv = document.getElementById('plugin-config-status');

         window.API.ajax({
             method: 'POST',
             url: '/api/plugin/config',
             headers: { 'Content-Type': 'application/json' },
             body: { cycle_minutes: cycleMinutes, scan_enabled: scanEnabled },
             success: function(res) {
                 if (res && res.success) {
                     statusDiv.innerHTML = '✅ Configuración del plugin guardada.';
                     statusDiv.style.color = '#4ade80';
                     setTimeout(function() { statusDiv.innerHTML = ''; }, 3000);
                 } else {
                     statusDiv.innerHTML = '❌ Error al guardar la configuración.';
                     statusDiv.style.color = '#f87171';
                 }
             },
             error: function() {
                 statusDiv.innerHTML = '❌ Error de red al guardar.';
                 statusDiv.style.color = '#f87171';
             }
         });
     };
    
    var loadChannels = function() {
        var listDiv = document.getElementById('channels-list');
        listDiv.innerHTML = '<div style="color: #a1a1aa; font-size: 0.75rem; text-align: center;">Cargando canales...</div>';
        
        window.API.ajax({
            url: '/api/admin/telegram/accounts',
            success: function(accountsRes) {
                var accountsList = accountsRes || [];
                
                window.API.ajax({
                    url: '/api/user/channels',
                    success: function(res) {
                        listDiv.innerHTML = '';
                        if (!res || res.length === 0) {
                            listDiv.innerHTML = '<div style="color: #71717a; font-size: 0.75rem; text-align: center; padding: 10px;">No hay canales configurados todavía.</div>';
                            return;
                        }
                        
                        res.forEach(function(ch) {
                            var chRow = document.createElement('div');
                            chRow.style.display = 'flex';
                            chRow.style.flexDirection = 'column';
                            chRow.style.background = 'rgba(24, 24, 27, 0.6)';
                            chRow.style.border = '1px solid rgba(63, 63, 70, 0.5)';
                            chRow.style.borderRadius = '8px';
                            chRow.style.padding = '12px 14px';
                            chRow.style.cursor = 'grab';
                            chRow.style.marginBottom = '10px';
                            chRow.draggable = true;
                            chRow.setAttribute('data-channel-id', ch.id);
                            
                            chRow.ondragstart = function(e) {
                                e.dataTransfer.setData('text/plain', ch.id);
                                chRow.style.opacity = '0.5';
                                chRow.style.border = '1px dashed #a855f7';
                            };
                            
                            chRow.ondragend = function(e) {
                                chRow.style.opacity = '1';
                                chRow.style.border = '1px solid rgba(63, 63, 70, 0.5)';
                            };
                            
                            chRow.ondragover = function(e) {
                                e.preventDefault();
                            };
                            
                            chRow.ondrop = function(e) {
                                e.preventDefault();
                                var draggedId = e.dataTransfer.getData('text/plain');
                                if (!draggedId || draggedId == ch.id) return;
                                
                                var listDiv = document.getElementById('channels-list');
                                var children = Array.from(listDiv.children);
                                var draggedEl = children.find(function(el) {
                                    return el.getAttribute('data-channel-id') === draggedId;
                                });
                                if (!draggedEl) return;
                                
                                var draggedIdx = children.indexOf(draggedEl);
                                var thisIdx = children.indexOf(chRow);
                                
                                if (draggedIdx < thisIdx) {
                                    listDiv.insertBefore(draggedEl, chRow.nextSibling);
                                } else {
                                    listDiv.insertBefore(draggedEl, chRow);
                                }
                                
                                var newIds = Array.from(listDiv.children).map(function(el) {
                                    return parseInt(el.getAttribute('data-channel-id'), 10);
                                }).filter(function(id) { return !isNaN(id); });
                                
                                window.API.ajax({
                                    method: 'POST',
                                    url: '/api/user/channels/reorder',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: { ids: newIds },
                                    success: function(res) {
                                        if (res && res.success) {
                                            console.log('Orden de canales guardado:', newIds);
                                        }
                                    }
                                });
                            };
                            
                            // Verificar si la cuenta asignada al canal sigue existiendo
                            var assignedAccountId = ch.telegram_account_id;
                            var accountStillExists = !assignedAccountId || accountsList.some(function(acc) {
                                return acc.id === assignedAccountId;
                            });

                            var accSelectStyle = 'width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;';
                            var accInvalidWarning = '';

                            if (assignedAccountId && !accountStillExists) {
                                // Cuenta eliminada: marcar en rojo y desactivar el canal silenciosamente
                                accSelectStyle = 'width: 100%; background: #09090b; border: 1px solid #ef4444; border-radius: 4px; padding: 4px 8px; color: #f87171; font-size: 0.75rem; box-sizing: border-box; height: 26px;';
                                accInvalidWarning = '<div style="font-size: 0.65rem; color: #f87171; margin-top: 2px;">⚠️ Cuenta eliminada o no válida</div>';

                                // Desactivar silenciosamente el canal en la BD
                                window.API.ajax({
                                    method: 'POST',
                                    url: '/api/user/channels',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: {
                                        id: ch.id,
                                        channel_id: ch.channel_id,
                                        display_name: ch.display_name,
                                        topology_type: ch.topology_type,
                                        end_channel_id: ch.end_msg_id || null,
                                        content_type: ch.content_type || 'media',
                                        custom_subcategory: ch.custom_subcategory || null,
                                        auto_refresh_interval: null,
                                        telegram_account_id: null,
                                        refresh_cycles: ch.refresh_cycles || 1,
                                        enabled: 0
                                    }
                                });
                            }

                            var accSelectHTML = '<select class="edit-ch-account" style="' + accSelectStyle + '">';
                            if (accountsList.length === 0) {
                                accSelectHTML += '<option value="">(Debe añadir una cuenta telegram)</option>';
                            } else {
                                accountsList.forEach(function(acc) {
                                    var selected = (acc.id === ch.telegram_account_id) ? ' selected' : '';
                                    accSelectHTML += '<option value="' + acc.id + '"' + selected + '>' + acc.display_name + '</option>';
                                });
                                if (assignedAccountId && !accountStillExists) {
                                    accSelectHTML += '<option value="" selected>⚠️ Cuenta eliminada (ID: ' + assignedAccountId + ')</option>';
                                }
                            }
                            accSelectHTML += '</select>';
                            if (accInvalidWarning) {
                                accSelectHTML += accInvalidWarning;
                            }

                            
                            var rangeLabel = "";
                            if (ch.start_msg_id) {
                                rangeLabel += ' | Inic: #' + ch.start_msg_id;
                            }
                            if (ch.topic_id) {
                                rangeLabel += ' | Topic: #' + ch.topic_id;
                            }
                            
                              chRow.innerHTML = '' +
                                '<!-- Cabecera del Accordion -->' +
                                '<div class="ch-row-header" style="display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none; padding: 4px 0;">' +
                                    '<div style="display: flex; align-items: center; flex: 1;">' +
                                        '<span class="ch-collapse-icon" style="font-size: 0.75rem; color: #a1a1aa; margin-right: 8px; transition: transform 0.2s;">▶</span>' +
                                        '<span class="ch-header-title" style="font-size: 0.85rem; font-weight: 800; color: #c084fc;">' + (ch.display_name || '(Sin nombre)') + '</span>' +
                                        '<span class="ch-header-subtitle" style="font-size: 0.7rem; color: #71717a; margin-left: 8px;">(ID Fuente: ' + ch.channel_id + rangeLabel + ')</span>' +
                                    '</div>' +
                                    '<div style="display: flex; align-items: center;" class="ch-toggle-label">' +
                                        '<label style="position: relative; display: inline-block; width: 34px; height: 20px; cursor: pointer; margin-right: 4px;">' +
                                            '<input type="checkbox" class="ch-toggle-enabled" ' + (ch.enabled !== 0 ? 'checked' : '') + ' style="opacity: 0; width: 0; height: 0;">' +
                                            '<span style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; background-color: #3f3f46; transition: .3s; border-radius: 20px; border: 1px solid #52525b; ' + (ch.enabled !== 0 ? 'background-color: #a855f7; border-color: #c084fc;' : '') + '" class="toggle-slider">' +
                                                '<span style="position: absolute; content: \'\'; height: 12px; width: 12px; left: 3px; bottom: 3px; background-color: #f4f4f5; transition: .3s; border-radius: 50%; ' + (ch.enabled !== 0 ? 'transform: translateX(14px);' : '') + '" class="toggle-knob"></span>' +
                                            '</span>' +
                                        '</label>' +
                                    '</div>' +
                                '</div>' +
                                
                                '<!-- Cuerpo Colapsable -->' +
                                '<div class="ch-row-body" style="display: none; margin-top: 12px; border-top: 1px solid rgba(63, 63, 70, 0.3); padding-top: 10px;">' +
                                    '<div style="display: flex; margin-bottom: 10px;">' +
                                        '<div style="flex: 1; margin-right: 10px;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Nombre en UI</label>' +
                                            '<input type="text" class="edit-ch-name" value="' + ch.display_name + '" placeholder="Ej: Mi Serie" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
                                        '</div>' +
                                        '<div style="flex: 1;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Enlace/Msg de Fin (Opcional)</label>' +
                                            '<input type="text" class="edit-ch-end" value="' + (ch.end_msg_id ? ch.end_msg_id : '') + '" placeholder="Ej: https://t.me/.../3500 o ID de Msg" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
                                        '</div>' +
                                    '</div>' +
                                    
                                    '<div style="display: flex; margin-bottom: 10px;">' +
                                        '<div style="flex: 1; margin-right: 10px;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Cuenta de Telegram</label>' +
                                            accSelectHTML +
                                        '</div>' +
                                        '<div style="flex: 1;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Contenido</label>' +
                                            '<select class="edit-ch-content-type" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
                                                '<option value="media"' + (ch.content_type === 'media' ? ' selected' : '') + '>Multimedia</option>' +
                                                '<option value="ebook"' + (ch.content_type === 'ebook' ? ' selected' : '') + '>Ebook</option>' +
                                                '<option value="audiolibro"' + (ch.content_type === 'audiolibro' ? ' selected' : '') + '>Audiolibro</option>' +
                                                '<option value="game"' + (ch.content_type === 'game' ? ' selected' : '') + '>Juego</option>' +
                                            '</select>' +
                                        '</div>' +
                                    '</div>' +
                                    
                                    '<div style="display: flex; margin-bottom: 10px;">' +
                                        '<div style="flex: 1.2; margin-right: 10px;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Subcategoría (Opcional)</label>' +
                                            '<input type="text" class="edit-ch-subcat" value="' + (ch.custom_subcategory || '') + '" placeholder="Ej: Películas" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
                                        '</div>' +
                                        '<div style="flex: 1; margin-right: 10px;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Auto-refresh</label>' +
                                            '<input type="text" class="edit-ch-refresh" value="' + (ch.auto_refresh_interval || '') + '" placeholder="Ej: 30m" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
                                        '</div>' +
                                        '<div style="flex: 1;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Ciclos de Refresco</label>' +
                                            '<input type="number" class="edit-ch-cycles" min="1" value="' + (ch.refresh_cycles || 1) + '" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
                                        '</div>' +
                                    '</div>' +
                                    
                                    '<div style="display: flex; align-items: flex-end; margin-bottom: 10px;">' +
                                        '<div style="flex: 1; margin-right: 10px;">' +
                                            '<label style="display: block; font-size: 0.7rem; color: #a1a1aa; margin-bottom: 2px;">Topología</label>' +
                                            '<select class="edit-ch-topology" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 8px; color: #f4f4f5; font-size: 0.75rem; box-sizing: border-box; height: 26px;">' +
                                                '<option value="1"' + (ch.topology_type === 1 ? ' selected' : '') + '>Tipo 1: Plano (Secuencial)</option>' +
                                                '<option value="2"' + (ch.topology_type === 2 ? ' selected' : '') + '>Tipo 2: Temas Temáticos</option>' +
                                                '<option value="3"' + (ch.topology_type === 3 ? ' selected' : '') + '>Tipo 3: Tema por Título</option>' +
                                            '</select>' +
                                        '</div>' +
                                        '<button class="parse-ch-btn" title="Parsear ahora (generar catálogo desde telegram_scan)" style="background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 4px; color: #60a5fa; font-size: 0.75rem; padding: 4px 12px; height: 26px; cursor: pointer; transition: all 0.2s; font-weight: bold;">▶ Parsear</button>' +
                                    '</div>' +
                                    
                                    '<div style="display: flex; flex-wrap: wrap; margin-top: 6px; border-top: 1px solid rgba(63, 63, 70, 0.2); padding-top: 8px;">' +
                                        '<button class="save-ch-btn" style="background: #22c55e; border: none; border-radius: 4px; color: white; font-size: 0.75rem; padding: 4px 10px; cursor: pointer; font-weight: bold; transition: all 0.2s; margin-right: 6px; margin-bottom: 4px;">💾 Guardar</button>' +
                                        '<button class="revert-ch-btn" style="background: rgba(161, 161, 170, 0.15); border: 1px solid rgba(161, 161, 170, 0.4); border-radius: 4px; color: #e4e4e7; font-size: 0.75rem; padding: 4px 10px; cursor: pointer; transition: all 0.2s; margin-right: 6px; margin-bottom: 4px;">🔄 Volver</button>' +
                                        '<div style="flex: 1;"></div>' +
                                        '<button class="update-ch-btn" title="Actualizar (buscar nuevos)" style="background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.4); border-radius: 4px; color: #c084fc; font-size: 0.75rem; padding: 4px 10px; cursor: pointer; transition: all 0.2s; margin-right: 6px; margin-bottom: 4px;">🔄 Act</button>' +
                                        '<button class="rescan-ch-btn" title="Reescanear desde cero" style="background: rgba(234, 179, 8, 0.15); border: 1px solid rgba(234, 179, 8, 0.4); border-radius: 4px; color: #facc15; font-size: 0.75rem; padding: 4px 10px; cursor: pointer; transition: all 0.2s; margin-right: 6px; margin-bottom: 4px;">🧼 Reesc</button>' +
                                        '<button class="clean-ch-btn" title="Limpiar registros (solo borra catálogo)" style="background: rgba(251, 191, 36, 0.15); border: 1px solid rgba(251, 191, 36, 0.4); border-radius: 4px; color: #fbbf24; font-size: 0.75rem; padding: 4px 10px; cursor: pointer; transition: all 0.2s; margin-right: 6px; margin-bottom: 4px;">🧹 Limpiar</button>' +
                                        '<button class="delete-ch-btn" title="Eliminar fuente" style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 4px; color: #f87171; font-size: 0.75rem; padding: 4px 10px; cursor: pointer; transition: all 0.2s; font-weight: bold; margin-bottom: 4px;">🗑️ Eliminar</button>' +
                                    '</div>' +
                                '</div>';
                            
                            // Toggle Collapse/Expand logic
                            var chHeader = chRow.querySelector('.ch-row-header');
                            var chBody = chRow.querySelector('.ch-row-body');
                            var chCollapseIcon = chRow.querySelector('.ch-collapse-icon');
                            
                            chHeader.onclick = function(e) {
                                // Si hizo clic en el toggle de enabled o su etiqueta, no colapsar/expandir
                                if (e.target.closest('.ch-toggle-label') || e.target.classList.contains('ch-toggle-enabled')) {
                                    return;
                                }
                                if (chBody.style.display === 'none') {
                                    chBody.style.display = 'block';
                                    chCollapseIcon.textContent = '▼';
                                    chCollapseIcon.style.color = '#c084fc';
                                } else {
                                    chBody.style.display = 'none';
                                    chCollapseIcon.textContent = '▶';
                                    chCollapseIcon.style.color = '#a1a1aa';
                                }
                            };

                             // Guardar el estado enabled en tiempo real al cambiar el checkbox
                             chRow.querySelector('.ch-toggle-enabled').onchange = function(e) {
                                 var checkbox = this;
                                 var isEnabled = checkbox.checked ? 1 : 0;
                                 var slider = checkbox.parentNode.querySelector('.toggle-slider');
                                 var knob = checkbox.parentNode.querySelector('.toggle-knob');
                                 
                                 // Feedback visual instantaneo
                                 if (isEnabled) {
                                     slider.style.backgroundColor = '#a855f7';
                                     slider.style.borderColor = '#c084fc';
                                     knob.style.transform = 'translateX(14px)';
                                 } else {
                                     slider.style.backgroundColor = '#3f3f46';
                                     slider.style.borderColor = '#52525b';
                                     knob.style.transform = '';
                                 }

                                 window.API.ajax({
                                     method: 'POST',
                                     url: '/api/user/channels',
                                     headers: { 'Content-Type': 'application/json' },
                                     body: {
                                         id: ch.id,
                                         channel_id: ch.channel_id,
                                         display_name: ch.display_name,
                                         topology_type: ch.topology_type,
                                         end_channel_id: ch.end_msg_id || null,
                                         content_type: ch.content_type || 'media',
                                         custom_subcategory: ch.custom_subcategory || null,
                                         auto_refresh_interval: ch.auto_refresh_interval || null,
                                         telegram_account_id: ch.telegram_account_id,
                                         refresh_cycles: ch.refresh_cycles || 1,
                                         enabled: isEnabled
                                     },
                                     success: function(res) {
                                         if (res && res.success) {
                                             console.log('Canal ' + ch.display_name + ' toggled enabled:', isEnabled);
                                             // Actualizar el objeto ch localmente para mantener consistencia
                                             ch.enabled = isEnabled;
                                             // Refrescar árbol de categorías del sidebar sin recargar página
                                             if (window.Catalog && window.Catalog.initCategoriesTree) {
                                                 window.Catalog.initCategoriesTree();
                                             }
                                         } else {
                                             checkbox.checked = !checkbox.checked;
                                             // Deshacer visual
                                             if (checkbox.checked) {
                                                 slider.style.backgroundColor = '#a855f7';
                                                 slider.style.borderColor = '#c084fc';
                                                 knob.style.transform = 'translateX(14px)';
                                             } else {
                                                 slider.style.backgroundColor = '#3f3f46';
                                                 slider.style.borderColor = '#52525b';
                                                 knob.style.transform = '';
                                             }
                                             alert('No se pudo guardar el estado de habilitación.');
                                         }
                                     },
                                     error: function() {
                                         checkbox.checked = !checkbox.checked;
                                         // Deshacer visual
                                         if (checkbox.checked) {
                                             slider.style.backgroundColor = '#a855f7';
                                             slider.style.borderColor = '#c084fc';
                                             knob.style.transform = 'translateX(14px)';
                                         } else {
                                             slider.style.backgroundColor = '#3f3f46';
                                             slider.style.borderColor = '#52525b';
                                             knob.style.transform = '';
                                         }
                                         alert('Error de red al actualizar estado del canal.');
                                     }
                                 });
                             };
                            
                            // Realtime update header title on name input change
                            var nameInput = chRow.querySelector('.edit-ch-name');
                            var headerTitle = chRow.querySelector('.ch-header-title');
                            nameInput.oninput = function() {
                                headerTitle.textContent = nameInput.value.trim() || '(Sin nombre)';
                            };

                            // Save Button logic
                            chRow.querySelector('.save-ch-btn').onclick = function() {
                                var nameVal = chRow.querySelector('.edit-ch-name').value.trim();
                                var endVal = chRow.querySelector('.edit-ch-end').value.trim();
                                var accountVal = chRow.querySelector('.edit-ch-account').value;
                                var contentTypeVal = chRow.querySelector('.edit-ch-content-type').value;
                                var subcatVal = chRow.querySelector('.edit-ch-subcat').value.trim();
                                var refreshVal = chRow.querySelector('.edit-ch-refresh').value.trim();
                                var cyclesVal = parseInt(chRow.querySelector('.edit-ch-cycles').value, 10) || 1;
                                var topologyVal = parseInt(chRow.querySelector('.edit-ch-topology').value, 10) || 1;
                                
                                if (!nameVal) {
                                    alert('El nombre en UI es obligatorio.');
                                    return;
                                }
                                
                                window.API.ajax({
                                    method: 'POST',
                                    url: '/api/user/channels',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: {
                                        id: ch.id,
                                        channel_id: ch.channel_id,
                                        display_name: nameVal,
                                        topology_type: topologyVal,
                                        end_channel_id: endVal || null,
                                        content_type: contentTypeVal,
                                        custom_subcategory: subcatVal || null,
                                        auto_refresh_interval: refreshVal || null,
                                        telegram_account_id: accountVal ? parseInt(accountVal, 10) : null,
                                        refresh_cycles: cyclesVal
                                    },
                                    success: function(saveRes) {
                                        if (saveRes && saveRes.success) {
                                            alert('✅ Canal guardado correctamente.');
                                            loadChannels();
                                            if (window.Catalog && window.Catalog.initCategoriesTree) {
                                                window.Catalog.initCategoriesTree();
                                            }
                                        } else {
                                            alert('❌ Error al guardar el canal.');
                                        }
                                    },
                                    error: function(err) {
                                        alert('❌ Error de red al guardar.');
                                    }
                                });
                            };
                            
                            // Revert Button logic
                            chRow.querySelector('.revert-ch-btn').onclick = function() {
                                loadChannels();
                            };
                            
                            // Update Button
                            chRow.querySelector('.update-ch-btn').onclick = function() {
                                window.API.ajax({
                                    method: 'POST',
                                    url: '/api/user/scan/start',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: { id: ch.id, mode: 'normal' },
                                    success: function(res) {
                                        if (res && res.success) {
                                            pollScanner();
                                            if (window.Catalog && typeof window.Catalog.startScanPolling === 'function') {
                                                window.Catalog.startScanPolling();
                                            }
                                        } else {
                                            alert('Error: ' + (res ? res.error : 'No se pudo iniciar el escaneo.'));
                                        }
                                    },
                                    error: function(err) {
                                        alert('Error de red al iniciar escaneo: ' + err);
                                    }
                                });
                            };
                            
                            // Rescan Button
                            chRow.querySelector('.rescan-ch-btn').onclick = function() {
                                var overlay = document.createElement('div');
                                overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:999999;display:flex;align-items:center;justify-content:center;';
                                var box = document.createElement('div');
                                box.style.cssText = 'background:rgba(24,24,27,0.97);border:1px solid rgba(63,63,70,0.6);border-radius:16px;padding:28px;max-width:440px;width:90%;text-align:center;box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);';
                                box.innerHTML = '<div style="font-size:2rem;margin-bottom:8px;">🔄</div><h3 style="margin:0 0 4px;color:#f4f4f5;font-size:1rem;">Reescanear: "' + ch.display_name + '"</h3><p style="color:#a1a1aa;font-size:0.8rem;margin:0 0 20px;">¿Cómo quieres proceder?</p><div style="display:flex;flex-direction:column;gap:8px;"><button id="rs-clean" style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);border-radius:8px;padding:10px 16px;color:#f87171;font-size:0.8rem;cursor:pointer;font-weight:700;">🧹 Clean & Re-scan</button><button id="rs-incremental" style="background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.4);border-radius:8px;padding:10px 16px;color:#4ade80;font-size:0.8rem;cursor:pointer;font-weight:700;">📥 INSERT OR REPLACE</button><button id="rs-cancel" style="background:transparent;border:none;padding:8px;color:#71717a;font-size:0.75rem;cursor:pointer;margin-top:4px;">Cancelar</button></div><p style="color:#52525b;font-size:0.65rem;margin:12px 0 0;">Clean: borra catálogo y telegram_scan, re-fetch y re-parsea todo.<br>INSERT OR REPLACE: re-fetch todo, pero conserva items existentes (solo añade/actualiza).</p>';
                                overlay.appendChild(box);
                                document.body.appendChild(overlay);
                                overlay.querySelector('#rs-cancel').onclick = function() { overlay.remove(); };
                                overlay.querySelector('#rs-clean').onclick = function() {
                                    overlay.remove();
                                    window.API.ajax({
                                        method: 'POST',
                                        url: '/api/user/scan/start',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: { id: ch.id, mode: 'clean' },
                                        success: function(res) {
                                            if (res && res.success) {
                                                pollScanner();
                                                if (window.Catalog && typeof window.Catalog.startScanPolling === 'function') {
                                                    window.Catalog.startScanPolling();
                                                }
                                            } else {
                                                alert('Error: ' + (res ? res.error : 'No se pudo iniciar el escaneo.'));
                                            }
                                        },
                                        error: function(err) {
                                            alert('Error de red al iniciar clean: ' + err);
                                        }
                                    });
                                };
                                overlay.querySelector('#rs-incremental').onclick = function() {
                                    overlay.remove();
                                    window.API.ajax({
                                        method: 'POST',
                                        url: '/api/user/scan/start',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: { id: ch.id, mode: 'incremental' },
                                        success: function(res) {
                                            if (res && res.success) {
                                                pollScanner();
                                                if (window.Catalog && typeof window.Catalog.startScanPolling === 'function') {
                                                    window.Catalog.startScanPolling();
                                                }
                                            } else {
                                                alert('Error: ' + (res ? res.error : 'No se pudo iniciar el escaneo.'));
                                            }
                                        },
                                        error: function(err) {
                                            alert('Error de red al iniciar incremental: ' + err);
                                        }
                                    });
                                };
                            };
                            
                            // Clean Button
                            chRow.querySelector('.clean-ch-btn').onclick = function() {
                                if (confirm('¿Limpiar registros del catálogo para "' + ch.display_name + '"? No se elimina la fuente, solo los items indexados.')) {
                                    window.API.ajax({
                                        method: 'POST',
                                        url: '/api/user/channels/' + ch.id + '/clean-records',
                                        success: function(res) {
                                            if (res && res.success) {
                                                if (window.Catalog) window.Catalog.load(window.Catalog.currentCategory);
                                                alert('Registros limpiados correctamente.');
                                            } else {
                                                alert('Error: ' + (res ? res.error : 'No se pudo limpiar.'));
                                            }
                                        },
                                        error: function(xhr) {
                                            alert('Error de red: ' + (xhr.statusText || 'desconocido'));
                                        }
                                    });
                                }
                            };
                            
                            // Parse Button
                            chRow.querySelector('.parse-ch-btn').onclick = function() {
                                var btn = this;
                                btn.textContent = '⏳ Parseando...';
                                btn.disabled = true;
                                btn.style.opacity = '0.5';
                                window.API.ajax({
                                    method: 'POST',
                                    url: '/api/user/parse/' + ch.id,
                                    success: function(res) {
                                        if (res && res.success) {
                                            if (window.Catalog) window.Catalog.load(window.Catalog.currentCategory || 'home');
                                        } else {
                                            alert('Error: ' + (res ? res.error : 'Falló el parseo.'));
                                        }
                                        btn.textContent = '▶ Parsear';
                                        btn.disabled = false;
                                        btn.style.opacity = '1';
                                    },
                                    error: function(err) {
                                        alert('Error de red al parsear: ' + err);
                                        btn.textContent = '▶ Parsear';
                                        btn.disabled = false;
                                        btn.style.opacity = '1';
                                    }
                                });
                            };
                            
                            // Delete Button con modal de confirmación inline para Android
                            chRow.querySelector('.delete-ch-btn').onclick = function() {
                                var overlay = document.createElement('div');
                                overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:999999;display:flex;align-items:center;justify-content:center;';
                                var box = document.createElement('div');
                                box.style.cssText = 'background:rgba(24,24,27,0.97);border:1px solid rgba(63,63,70,0.6);border-radius:16px;padding:24px;max-width:380px;width:90%;text-align:center;box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);';
                                box.innerHTML = '<div style="font-size:2rem;margin-bottom:8px;">⚠️</div><h3 style="margin:0 0 10px;color:#f4f4f5;font-size:1rem;">¿Eliminar canal?</h3><p style="color:#a1a1aa;font-size:0.8rem;margin:0 0 20px;">¿Estás seguro de que deseas eliminar el canal "' + ch.display_name + '"?</p><div style="display:flex;justify-content:center;gap:12px;"><button id="del-confirm" style="background:#ef4444;border:none;border-radius:8px;padding:8px 16px;color:white;font-size:0.8rem;cursor:pointer;font-weight:700;">Eliminar</button><button id="del-cancel" style="background:rgba(161,161,170,0.15);border:1px solid rgba(161,161,170,0.4);border-radius:8px;padding:8px 16px;color:#e4e4e7;font-size:0.8rem;cursor:pointer;">Cancelar</button></div>';
                                overlay.appendChild(box);
                                document.body.appendChild(overlay);
                                
                                overlay.querySelector('#del-cancel').onclick = function() { overlay.remove(); };
                                overlay.querySelector('#del-confirm').onclick = function() {
                                    overlay.remove();
                                    window.API.ajax({
                                        method: 'DELETE',
                                        url: '/api/user/channels/' + ch.id,
                                        success: function() {
                                            loadChannels();
                                        },
                                        error: function(xhr) {
                                            alert('Error de red: ' + (xhr.statusText || 'desconocido'));
                                        }
                                    });
                                };
                            };
                            
                            listDiv.appendChild(chRow);
                        });
                    }
                });
            }
        });
    };
    
    document.getElementById('add-channel-btn').onclick = function() {
        var chId = document.getElementById('new-channel-id').value;
        var startId = document.getElementById('new-channel-start').value;
        var endId = document.getElementById('new-channel-end').value;
        var name = document.getElementById('new-channel-name').value;
        var topo = parseInt(document.getElementById('new-channel-topology').value, 10);
        var contentType = document.getElementById('new-channel-content-type').value;
        var subcat = document.getElementById('new-channel-subcategory').value.trim();
        var autoRefresh = document.getElementById('new-channel-refresh').value.trim();
        var accountVal = document.getElementById('new-channel-account').value;
        var accountId = accountVal ? parseInt(accountVal, 10) : null;
        var cycles = parseInt(document.getElementById('new-channel-cycles').value, 10) || 1;
        
        if (!chId || !name) {
            alert('Por favor introduce el ID del canal y un nombre descriptivo.');
            return;
        }
        
        window.API.ajax({
            method: 'POST',
            url: '/api/user/channels',
            data: { 
                channel_id: chId, 
                start_msg: startId,
                end_msg: endId,
                display_name: name, 
                topology_type: topo, 
                content_type: contentType, 
                custom_subcategory: subcat, 
                auto_refresh_interval: autoRefresh,
                telegram_account_id: accountId,
                refresh_cycles: cycles
            },
             success: function(res) {
                 if (res && res.success) {
                     document.getElementById('new-channel-id').value = '';
                     document.getElementById('new-channel-end').value = '';
                     document.getElementById('new-channel-name').value = '';
                     document.getElementById('new-channel-subcategory').value = '';
                     document.getElementById('new-channel-refresh').value = '';
                     document.getElementById('new-channel-cycles').value = '1';
                     
                     // Ocultar el panel de añadir tras añadir el canal correctamente
                     var panel = document.getElementById('add-channel-panel');
                     var btn = document.getElementById('add-channel-toggle-btn');
                     if (panel && btn) {
                         panel.style.display = 'none';
                         btn.textContent = '➕ Nuevo';
                         btn.style.background = '#a855f7';
                         btn.style.color = 'white';
                         btn.style.border = 'none';
                     }
                     
                     loadChannels();
                 } else {
                     alert('Error al añadir el canal.');
                 }
             }
        });
    };

    window.autofillNewChannelId = function() {
        var startEl = document.getElementById('new-channel-start');
        var idEl = document.getElementById('new-channel-id');
        if (!startEl || !idEl) return;
        var val = startEl.value.trim();
        var m = val.match(/t\.me\/c\/(\d+)/);
        if (m) { idEl.value = '-100' + m[1]; }
    };

    document.getElementById('test-channel-btn').onclick = function() {
        var chId = document.getElementById('new-channel-id').value.trim();        var accountVal = document.getElementById('new-channel-account').value;
        var accountId = accountVal ? parseInt(accountVal, 10) : null;
        
        if (!chId) {
            alert('Por favor introduce el enlace del canal para probar la conectividad.');
            return;
        }
        if (!accountId) {
            alert('Por favor selecciona una cuenta de Telegram para realizar la prueba.');
            return;
        }
        
        var btn = this;
        var oldText = btn.textContent;
        btn.textContent = '⏳ Probando...';
        btn.disabled = true;
        btn.style.opacity = '0.5';
        
        window.API.ajax({
            method: 'POST',
            url: '/api/user/channels/test',
            headers: { 'Content-Type': 'application/json' },
            body: { channel_url: chId, telegram_account_id: accountId },
            success: function(res) {
                btn.textContent = oldText;
                btn.disabled = false;
                btn.style.opacity = '1';
                if (res && res.success) {
                    alert('✅ Conectividad exitosa con el canal. Nombre del canal: ' + res.title);
                } else {
                    alert('🔴 Error al conectar con el canal: ' + (res ? res.error : 'Error desconocido'));
                }
            },
            error: function(err) {
                btn.textContent = oldText;
                btn.disabled = false;
                btn.style.opacity = '1';
                alert('🔴 Error de red al probar conexión con el canal.');
            }
        });
    };
    
    var pollScanner = function() {
        window.API.ajax({
            url: '/api/user/scan/status',
            success: function(res) {
                if (res) {
                    var consoleDiv = document.getElementById('scanner-console');
                    if (res.logs && res.logs.length > 0) {
                        consoleDiv.textContent = res.logs.join('\n');
                        consoleDiv.scrollTop = consoleDiv.scrollHeight;
                    } else {
                        consoleDiv.textContent = 'Consola inactiva. Esperando inicio de escaneo...';
                    }
                    
                    var progressContainer = document.getElementById('scan-progress-container');
                    var progressBar = document.getElementById('scan-progress-bar');
                    var percentText = document.getElementById('scan-percent-text');
                    var statusText = document.getElementById('scan-status-text');
                    var startBtn = document.getElementById('start-scan-btn');
                    
                    if (res.status === 'scanning') {
                        progressContainer.style.display = 'flex';
                        progressBar.style.width = res.progress_percent + '%';
                        percentText.textContent = res.progress_percent + '%';
                        statusText.textContent = res.current_item || 'Indexando...';
                        startBtn.disabled = true;
                        startBtn.style.opacity = '0.5';
                        startBtn.textContent = 'Escaneando...';
                    } else {
                        if (res.status === 'idle') {
                            if (res.progress_percent === 100) {
                                progressContainer.style.display = 'flex';
                                progressBar.style.width = '100%';
                                percentText.textContent = '100%';
                                statusText.textContent = 'Indexación completada.';
                            } else {
                                progressContainer.style.display = 'none';
                            }
                        }
                        startBtn.disabled = false;
                        startBtn.style.opacity = '1';
                        startBtn.textContent = 'Actualizar todos los canales';
                    }
                }
            }
        });
    };
    
    document.getElementById('start-scan-btn').onclick = function() {
        window.API.ajax({
            method: 'POST',
            url: '/api/user/scan/start',
            success: function(res) {
                if (res && res.success) {
                    pollScanner();
                    if (window.Catalog && typeof window.Catalog.startScanPolling === 'function') {
                        window.Catalog.startScanPolling();
                    }
                } else {
                    alert(res ? res.error : 'No se pudo iniciar el escaneo.');
                }
            },
            error: function(err) {
                alert('Error de red al iniciar escaneo global: ' + err);
            }
        });
    };
    
    // openSessionGeneratorModal ahora está definida en el ámbito global

    loadConfig();
    loadPluginConfig();
    loadAccountsForSelect();
    loadAccountsList();
    loadChannels();
    pollScanner();
    window.scannerPollInterval = setInterval(pollScanner, 2000);
}

window.openUserbotConfigModal = openUserbotConfigModal;

function openPeersConfigModal() {
    var modal = document.createElement('div');
    modal.id = 'tvcat-peers-modal';
    modal.style.position = 'fixed';
    modal.style.top = '0';
    modal.style.left = '0';
    modal.style.width = '100vw';
    modal.style.height = '100vh';
    modal.style.background = 'rgba(9, 9, 11, 0.85)';
    modal.style.backdropFilter = 'blur(10px)';
    modal.style.zIndex = '99999';
    modal.style.display = 'flex';
    modal.style.alignItems = 'center';
    modal.style.justifyContent = 'center';
    modal.style.opacity = '0';
    modal.style.transition = 'opacity 0.25s ease';
    
    var dialog = document.createElement('div');
    dialog.style.background = 'rgba(24, 24, 27, 0.95)';
    dialog.style.border = '1px solid rgba(63, 63, 70, 0.6)';
    dialog.style.borderRadius = '16px';
    dialog.style.width = '90%';
    dialog.style.maxWidth = '720px';
    dialog.style.maxHeight = '85vh';
    dialog.style.boxShadow = '0 25px 50px -12px rgba(0, 0, 0, 0.5)';
    dialog.style.display = 'flex';
    dialog.style.flexDirection = 'column';
    dialog.style.overflow = 'hidden';
    dialog.style.transform = 'scale(0.95)';
    dialog.style.transition = 'transform 0.25s ease';
    
    dialog.innerHTML = '' +
        '<div style="flex-shrink: 0; background: rgba(24, 24, 27, 0.98); display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(63, 63, 70, 0.4); padding: 14px 24px 10px 24px;">' +
            '<div style="display: flex; align-items: center;">' +
                '<span style="font-size: 1.25rem; margin-right: 8px;">🔗</span>' +
                '<div>' +
                    '<h3 style="margin: 0; font-size: 1.1rem; font-weight: 800; color: #f4f4f5; font-family: &quot;Outfit&quot;, sans-serif;">Configuración de TVCat Peers (Remoto)</h3>' +
                '</div>' +
            '</div>' +
            '<button id="peers-modal-close" style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #f87171; border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; cursor: pointer; font-weight: bold; transition: all 0.2s; flex-shrink: 0; margin-left: 12px; line-height: 1;">&times;</button>' +
        '</div>' +
        '<div style="flex: 1; overflow-y: auto; padding: 20px 24px 24px 24px;">' +
            '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px; margin-bottom: 16px;">' +
                '<h4 style="margin: 0 0 4px 0; font-size: 0.95rem; font-weight: 700; color: #c084fc;">🎫 Nombre de esta instancia</h4>' +
                '<p style="margin:0 0 10px 0; font-size:0.75rem; color:var(--text-secondary);">Este nombre lo verán los peers al recibir tu invitación.</p>' +
                '<div style="display: flex; gap: 10px;">' +
                    '<input type="text" id="peer-instance-name" placeholder="Mi TVCat" style="flex:1; background:#09090b; border:1px solid #3f3f46; border-radius:6px; padding:6px 10px; color:#f4f4f5; font-size:0.8rem; height:32px;">' +
                    '<button id="peer-save-instance-name" style="background:#27272a; border:1px solid #3f3f46; border-radius:6px; padding:6px 16px; color:white; font-size:0.8rem; cursor:pointer; height:32px;">Guardar</button>' +
                '</div>' +
            '</div>' +
            '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px; margin-bottom: 16px;">' +
                '<h4 style="margin: 0 0 12px 0; font-size: 0.95rem; font-weight: 700; color: #34d399;">📨 Generar Invitación</h4>' +
                '<p style="margin:0 0 10px 0; font-size:0.75rem; color:var(--text-secondary);">Genera un enlace de invitación para enviar al administrador del TVCat remoto.</p>' +
                '<input type="text" id="peer-invite-name" placeholder="Nombre del futuro peer (ej. Cine de Paco)" style="width:100%; background:#09090b; border:1px solid #3f3f46; border-radius:6px; padding:6px 10px; color:#f4f4f5; font-size:0.8rem; margin-bottom:8px; height:32px; box-sizing:border-box;">' +
                '<div id="peer-invite-categories" style="margin-bottom:8px; max-height:120px; overflow-y:auto; border:1px solid #27272a; border-radius:6px; padding:6px 8px; background:#09090b;"></div>' +
                '<div style="display:flex; gap:8px;">' +
                    '<button id="peer-generate-invite" style="background:#10b981; border:none; border-radius:6px; padding:6px 16px; color:white; font-weight:700; font-size:0.8rem; cursor:pointer; height:32px;">Generar Invitación</button>' +
                    '<button id="peer-copy-invite" style="background:#27272a; border:1px solid #3f3f46; border-radius:6px; padding:6px 16px; color:white; font-size:0.8rem; cursor:pointer; height:32px; display:none;">Copiar Enlace</button>' +
                '</div>' +
                '<div id="peer-invite-result" style="margin-top:8px; font-size:0.75rem;"></div>' +
            '</div>' +
            '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px; margin-bottom: 16px;">' +
                '<h4 style="margin: 0 0 12px 0; font-size: 0.95rem; font-weight: 700; color: #fbbf24;">📩 Aceptar Invitación</h4>' +
                '<p style="margin:0 0 10px 0; font-size:0.75rem; color:var(--text-secondary);">Pega aquí el enlace de invitación que te ha enviado el administrador del TVCat remoto.</p>' +
                '<div id="peer-accept-categories" style="margin-bottom:8px;"></div>' +
                '<div style="display: flex; gap: 10px;">' +
                    '<input type="text" id="peer-invite-link" placeholder="Enlace de invitación (ej. http://192.168.1.50:8098/api/peers/invite/TOKEN)" style="flex:1; background:#09090b; border:1px solid #3f3f46; border-radius:6px; padding:6px 10px; color:#f4f4f5; font-size:0.8rem; height:32px;">' +
                    '<button id="peer-accept-invite-btn" style="background:#f59e0b; border:none; border-radius:6px; padding:6px 16px; color:white; font-weight:700; font-size:0.8rem; cursor:pointer; height:32px;">Aceptar</button>' +
                '</div>' +
                '<div id="peer-accept-result" style="margin-top:8px; font-size:0.75rem;"></div>' +
            '</div>' +
            '<div style="background: rgba(39, 39, 42, 0.3); border: 1px solid rgba(63, 63, 70, 0.3); border-radius: 10px; padding: 16px;">' +
                '<h4 style="margin: 0 0 12px 0; font-size: 0.95rem; font-weight: 700; color: #f4f4f5;">Peers Conectados</h4>' +
                '<div id="peers-list-container" style="display: flex; flex-direction: column; gap: 12px;">' +
                    '<div style="color:var(--text-secondary);font-size:0.85rem;">Cargando peers...</div>' +
                '</div>' +
            '</div>' +
            '<div style="display: flex; justify-content: flex-end; margin-top: 24px; border-top: 1px solid rgba(63, 63, 70, 0.4); padding-top: 16px;">' +
                '<button id="peers-modal-close-bottom" style="background: #27272a; border: 1px solid #3f3f46; border-radius: 6px; padding: 8px 20px; color: #f4f4f5; font-size: 0.85rem; font-weight: bold; cursor: pointer; transition: all 0.2s;">Cerrar</button>' +
            '</div>' +
        '</div>';
        
    modal.appendChild(dialog);
    document.body.appendChild(modal);
    
    setTimeout(function() {
        modal.style.opacity = '1';
        dialog.style.transform = 'scale(1)';
    }, 10);
    
    var closeModal = function() {
        if (window._peersPollTimer) {
            clearInterval(window._peersPollTimer);
            window._peersPollTimer = null;
        }
        modal.style.opacity = '0';
        dialog.style.transform = 'scale(0.95)';
        setTimeout(function() {
            modal.remove();
        }, 250);
    };
    
    document.getElementById('peers-modal-close').onclick = closeModal;
    var closeBtnBottom = document.getElementById('peers-modal-close-bottom');
    if (closeBtnBottom) closeBtnBottom.onclick = closeModal;
    
    // Cargar nombre de instancia y generar nombre aleatorio para peer
    window.API.ajax({
        url: '/api/peers/instance-info',
        success: function(info) {
            var inp = document.getElementById('peer-instance-name');
            if (inp && info.name) inp.value = info.name;
            // Auto-generar nombre para el peer
            var nameInput = document.getElementById('peer-invite-name');
            if (nameInput && !nameInput.value) {
                var rand = Math.random().toString(36).substring(2, 10);
                nameInput.value = 'Peer-' + rand;
            }
            // Guardar LAN URL para usar en el enlace
            if (info.lan_url) {
                window._tvcLanUrl = info.lan_url;
            }
        }
    });
    
    // Guardar nombre de instancia
    document.getElementById('peer-save-instance-name').onclick = function() {
        var name = document.getElementById('peer-instance-name').value.trim();
        if (!name) return;
        window.API.ajax({
            method: 'PUT',
            url: '/api/peers/instance-name',
            headers: { 'Content-Type': 'application/json' },
            body: { name: name },
            success: function() {
                document.getElementById('peer-invite-result').textContent = '✅ Nombre actualizado';
            }
        });
    };
    
    // -- Árbol de selección de subcategorías para compartir --
    window.UI.renderShareTree = function(cats, container, selectedSet, onChange) {
        var html = '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:4px;">Selecciona qué compartir:</div>';
        html += '<div style="max-height:200px; overflow-y:auto; border:1px solid #27272a; border-radius:6px; padding:6px 8px; background:#09090b;">';
        Object.keys(cats).forEach(function(plugin) {
            if (plugin === 'tvcat_peers') return;
            var pData = cats[plugin];
            if (!pData || !pData.enabled) return;
            var dName = pData.displayName || plugin;
            var pCats = pData.categories || {};
            var cKeys = Object.keys(pCats);
            html += '<div style="margin:2px 0;">';
            html += '<label style="display:flex; align-items:center; gap:4px; font-weight:600; color:#e4e4e7; cursor:pointer; padding:2px 0; font-size:0.75rem;"><input type="checkbox" class="tree-plugin" data-plugin="' + plugin + '"> ' + dName + '</label>';
            cKeys.forEach(function(cat) {
                var subs = pCats[cat] || [];
                html += '<div style="margin-left:14px;">';
                html += '<label style="display:flex; align-items:center; gap:4px; font-weight:500; color:#d4d4d8; cursor:pointer; padding:2px 0; font-size:0.7rem;"><input type="checkbox" class="tree-cat" data-plugin="' + plugin + '" data-cat="' + cat + '"> ' + cat + '</label>';
                subs.forEach(function(sub) {
                    if (sub === '__none__') return;
                    var val = cat + '/' + sub;
                    var chk = selectedSet.has(val) ? 'checked' : '';
                    html += '<div style="margin-left:14px;">';
                    html += '<label style="display:flex; align-items:center; gap:4px; font-size:0.7rem; color:#a1a1aa; cursor:pointer; padding:1px 0;"><input type="checkbox" class="tree-sub" data-val="' + val + '" ' + chk + '> ' + sub + '</label>';
                    html += '</div>';
                });
                html += '</div>';
            });
            html += '</div>';
        });
        html += '</div>';
        container.innerHTML = html;

        function getSelected() {
            var catsSet = new Set();
            var subsArr = [];
            container.querySelectorAll('.tree-sub:checked').forEach(function(cb) {
                subsArr.push(cb.getAttribute('data-val'));
                var parts = cb.getAttribute('data-val').split('/');
                catsSet.add(parts[0]);
            });
            return { categories: Array.from(catsSet), subcategories: subsArr };
        }

        function syncParents() {
            container.querySelectorAll('.tree-cat').forEach(function(cb) {
                var parent = cb.closest('div').parentNode;
                var subs = parent.querySelectorAll('.tree-sub');
                var allChk = subs.length > 0 && Array.from(subs).every(function(s) { return s.checked; });
                cb.checked = allChk;
            });
            container.querySelectorAll('.tree-plugin').forEach(function(cb) {
                var plugin = cb.getAttribute('data-plugin');
                var catsUnder = container.querySelectorAll('.tree-cat[data-plugin="' + plugin + '"]');
                var allChk = catsUnder.length > 0 && Array.from(catsUnder).every(function(c) { return c.checked; });
                cb.checked = allChk;
            });
        }

        container.querySelectorAll('.tree-sub').forEach(function(cb) {
            cb.addEventListener('change', function() {
                syncParents();
                if (onChange) onChange(getSelected());
            });
        });
        container.querySelectorAll('.tree-cat').forEach(function(cb) {
            cb.addEventListener('change', function() {
                var parent = cb.closest('div').parentNode;
                parent.querySelectorAll('.tree-sub').forEach(function(s) { s.checked = cb.checked; });
                syncParents();
                if (onChange) onChange(getSelected());
            });
        });
        container.querySelectorAll('.tree-plugin').forEach(function(cb) {
            cb.addEventListener('change', function() {
                var plugin = cb.getAttribute('data-plugin');
                container.querySelectorAll('.tree-cat[data-plugin="' + plugin + '"]').forEach(function(c) {
                    c.checked = cb.checked;
                    var catParent = c.closest('div').parentNode;
                    catParent.querySelectorAll('.tree-sub').forEach(function(s) { s.checked = cb.checked; });
                });
                syncParents();
                if (onChange) onChange(getSelected());
            });
        });

        container._catTreeGet = getSelected;
        syncParents();
    }

    // Cargar categorías para el selector de invite
    window.API.getCategories(function(cats) {
        var catContainer = document.getElementById('peer-invite-categories');
        if (!catContainer) return;
        window.UI.renderShareTree(cats, catContainer, new Set());
    });
    // También para el selector de "Aceptar invitación"
    window.API.getCategories(function(cats) {
        var accContainer = document.getElementById('peer-accept-categories');
        if (!accContainer) return;
        window.UI.renderShareTree(cats, accContainer, new Set());
    });
    
    // Generar invitación
    document.getElementById('peer-generate-invite').onclick = function() {
        var peerName = document.getElementById('peer-invite-name').value.trim();
        if (!peerName) { alert('Indica un nombre para el futuro peer'); return; }
        var sel = { categories: [], subcategories: [] };
        var inviteContainer = document.getElementById('peer-invite-categories');
        if (inviteContainer._catTreeGet) {
            sel = inviteContainer._catTreeGet();
        }
        window.API.ajax({
            method: 'POST',
            url: '/api/peers/invite',
            headers: { 'Content-Type': 'application/json' },
            body: { peer_name: peerName, categories: sel.categories, subcategories: sel.subcategories, ttl_hours: 72 },
            success: function(res) {
                var link = res.invite_link || window.location.origin + '/api/peers/invite/' + res.token;
                var resultDiv = document.getElementById('peer-invite-result');
                resultDiv.innerHTML = '✅ Invitación generada<br><code style="font-size:0.7rem; word-break:break-all; color:#34d399;">' + link + '</code>';
                var copyBtn = document.getElementById('peer-copy-invite');
                copyBtn.style.display = 'inline-block';
                copyBtn.onclick = function() {
                    navigator.clipboard.writeText(link).then(function() {
                        resultDiv.innerHTML += '<br>📋 Enlace copiado al portapapeles';
                    });
                };
            },
            error: function(err) {
                document.getElementById('peer-invite-result').textContent = '❌ Error: ' + err;
            }
        });
    };
    
    // Aceptar invitación remota
    document.getElementById('peer-accept-invite-btn').onclick = function() {
        var link = document.getElementById('peer-invite-link').value.trim();
        if (!link) { alert('Pega el enlace de invitación'); return; }

        var resultDiv = document.getElementById('peer-accept-result');
        resultDiv.textContent = '⏳ Contactando servidor remoto...';

        var ourName = document.getElementById('peer-instance-name').value.trim() || 'TVCat';
        // Usar la IP LAN detectada por el servidor para que el peer remoto pueda contactarnos correctamente.
        // Si no está disponible aún, se usa window.location.origin como fallback.
        var ourUrl = window._tvcLanUrl || window.location.origin;

        var sel = { categories: [], subcategories: [] };
        var accContainer = document.getElementById('peer-accept-categories');
        if (accContainer && accContainer._catTreeGet) {
            sel = accContainer._catTreeGet();
        }

        var acceptBtn = this;
        acceptBtn.disabled = true;

        window.API.ajax({
            method: 'POST',
            url: '/api/peers/accept-remote-invite',
            headers: { 'Content-Type': 'application/json' },
            body: {
                invite_link: link,
                my_name: ourName,
                my_url: ourUrl,
                shared_config: { categories: sel.categories, subcategories: sel.subcategories }
            },
            success: function(res) {
                resultDiv.innerHTML = '✅ Conexión establecida con <strong>' + (res.peer_name || 'Remoto') + '</strong>';
                document.getElementById('peer-invite-link').value = '';
                UI.loadPeersList();
                acceptBtn.disabled = false;
            },
            error: function(err) {
                var msg = typeof err === 'string' ? err : (err.detail || JSON.stringify(err));
                resultDiv.textContent = '❌ ' + msg;
                acceptBtn.disabled = false;
            }
        });
    };
    
    window.UI.loadPeersList();
    // Auto-refresh cada 5s mientras el modal esté abierto
    if (window._peersPollTimer) clearInterval(window._peersPollTimer);
    window._peersPollTimer = setInterval(window.UI.loadPeersList, 5000);
}

window.openPeersConfigModal = openPeersConfigModal;

// --- Sincronización Global (Sync Catalog) ---
window.UI.startRefreshPolling = function() {
    var emojiEl = document.getElementById('sync-progress-emoji');
    var fillEl = document.getElementById('sync-progress-fill');
    var container = document.getElementById('sync-progress');
    if (!fillEl || !container) return;
    
    container.style.display = 'flex';
    var refreshBtn = document.getElementById('btn-refresh-catalog');
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.style.opacity = '0.5';
        refreshBtn.style.pointerEvents = 'none';
    }
    
    var startTime = Date.now();
    var pollCount = 0;
    var stopped = false;
    var timer = null;
    
    function poll() {
        if (stopped) return;
        pollCount++;
        window.API.ajax({
            url: '/api/sync/refresh-status?_=' + Date.now(),
            success: function(res) {
                if (stopped || !res) return;
                console.log('[SYNC POLL]', JSON.stringify(res));
                var progress = res.global_progress || 0;
                fillEl.style.width = Math.min(progress, 100) + '%';
                
                emojiEl.textContent = res.trigger === 'auto' ? '🕐' : '🔄';
                
                var done = progress >= 100;
                var minTime = (Date.now() - startTime) > 2000;
                var minPolls = pollCount >= 2;
                
                if (done && minPolls && minTime) {
                    stopped = true;
                    clearTimeout(timer);
                    container.style.display = 'none';
                    fillEl.style.width = '0%';
                    if (refreshBtn) {
                        refreshBtn.disabled = false;
                        refreshBtn.style.opacity = '1';
                        refreshBtn.style.pointerEvents = 'auto';
                    }
                    if (window.Catalog) window.Catalog.load(window.Catalog.currentCategory);
                } else if (done) {
                    timer = setTimeout(poll, 500);
                } else {
                    timer = setTimeout(poll, 2000);
                }
            },
            error: function() {
                stopped = true;
                clearTimeout(timer);
                container.style.display = 'none';
                if (refreshBtn) {
                    refreshBtn.disabled = false;
                    refreshBtn.style.opacity = '1';
                    refreshBtn.style.pointerEvents = 'auto';
                }
            }
        });
    }
    timer = setTimeout(poll, 500);
};

// --- Generador de Sesión de Telegram (Ámbito Global) ---
function openSessionGeneratorModal(onSuccessCallback, isGlobal) {
    var subModal = document.createElement('div');
    subModal.id = 'tvcat-submodal-generator';
    subModal.style.position = 'fixed';
    subModal.style.top = '0';
    subModal.style.left = '0';
    subModal.style.width = '100vw';
    subModal.style.height = '100vh';
    subModal.style.background = 'rgba(9, 9, 11, 0.9)';
    subModal.style.backdropFilter = 'blur(8px)';
    subModal.style.zIndex = '999999';
    subModal.style.display = 'flex';
    subModal.style.alignItems = 'center';
    subModal.style.justifyContent = 'center';
    subModal.style.opacity = '0';
    subModal.style.transition = 'opacity 0.2s ease';
    
    var subDialog = document.createElement('div');
    subDialog.style.background = 'rgba(24, 24, 27, 0.98)';
    subDialog.style.border = '1px solid rgba(168, 85, 247, 0.4)';
    subDialog.style.borderRadius = '12px';
    subDialog.style.width = '90%';
    subDialog.style.maxWidth = '450px';
    subDialog.style.padding = '20px';
    subDialog.style.boxShadow = '0 25px 50px -12px rgba(0, 0, 0, 0.8)';
    subDialog.style.display = 'flex';
    subDialog.style.flexDirection = 'column';
    subDialog.style.gap = '16px';
    subDialog.style.transform = 'scale(0.95)';
    subDialog.style.transition = 'transform 0.2s ease';
    
    var generatorTitle = isGlobal ? 'Generador de Sesión Global (Cuenta Principal)' : 'Generador de String Session';
    var generatorConfirmLabel = isGlobal ? 'Generar Sesión Global' : 'Generar e Insertar Cuenta';
    subDialog.innerHTML = 
        '<div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(63, 63, 70, 0.4); padding-bottom: 10px;">' +
            '<h3 style="margin: 0; font-size: 1.1rem; font-weight: 700; color: #f4f4f5; font-family: &quot;Outfit&quot;, sans-serif;">' + generatorTitle + '</h3>' +
            '<button id="generator-modal-close" style="background: none; border: none; color: #a1a1aa; font-size: 1rem; cursor: pointer;">✕</button>' +
        '</div>' +
        '<div style="display: flex; flex-direction: column; gap: 12px;">' +
            '<div>' +
                '<label style="display: block; font-size: 0.75rem; color: #a1a1aa; margin-bottom: 4px;">Número de Teléfono</label>' +
                '<input type="text" id="gen-phone" placeholder="Ej: +34600000000" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 0.8rem; box-sizing: border-box;">' +
            '</div>' +
            '<button id="gen-send-code-btn" style="background: #a855f7; border: none; border-radius: 6px; padding: 8px 12px; color: white; font-weight: 700; font-size: 0.8rem; cursor: pointer;">Enviar Código de Verificación</button>' +
            
            '<div id="gen-verification-section" style="display: none; flex-direction: column; gap: 12px; margin-top: 6px;">' +
                '<div>' +
                    '<label style="display: block; font-size: 0.75rem; color: #a1a1aa; margin-bottom: 4px;">Código SMS de Telegram</label>' +
                    '<input type="text" id="gen-code" placeholder="Digita el código aquí..." style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 0.8rem; box-sizing: border-box;">' +
                '</div>' +
                '<div id="gen-2fa-section" style="display: none;">' +
                    '<label style="display: block; font-size: 0.75rem; color: #a1a1aa; margin-bottom: 4px;">Contraseña 2FA (Verificación en dos pasos)</label>' +
                    '<input type="password" id="gen-password" placeholder="Tu contraseña de dos pasos" style="width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 6px; padding: 6px 10px; color: #f4f4f5; font-size: 0.8rem; box-sizing: border-box;">' +
                '</div>' +
                '<div style="font-size: 0.7rem; color: #fbbf24; background: rgba(251, 191, 36, 0.08); padding: 6px 8px; border-radius: 4px; border-left: 2px solid #fbbf24;">' +
                    '⚠️ <strong>Importante:</strong> Digita el código directamente. Telegram invalida los códigos copiados y pegados en la misma máquina.' +
                '</div>' +
                '<button id="gen-confirm-btn" style="background: #22c55e; border: none; border-radius: 6px; padding: 8px 12px; color: white; font-weight: 700; font-size: 0.8rem; cursor: pointer;">' + generatorConfirmLabel + '</button>' +
            '</div>' +
            '<div id="gen-status" style="font-size: 0.75rem; font-weight: 600; margin-top: 4px;"></div>' +
        '</div>';
        
    subModal.appendChild(subDialog);
    document.body.appendChild(subModal);
    
    setTimeout(function() {
        subModal.style.opacity = '1';
        subDialog.style.transform = 'scale(1)';
    }, 10);
    
    var closeSubModal = function() {
        subModal.style.opacity = '0';
        subDialog.style.transform = 'scale(0.95)';
        setTimeout(function() {
            subModal.remove();
        }, 200);
    };
    
    document.getElementById('generator-modal-close').onclick = closeSubModal;
    
    document.getElementById('gen-send-code-btn').onclick = function() {
        var phone = document.getElementById('gen-phone').value.trim();
        var statusDiv = document.getElementById('gen-status');
        if (!phone) {
            alert('Introduce el número de teléfono.');
            return;
        }
        statusDiv.innerHTML = '⏳ Enviando código de autenticación...';
        statusDiv.style.color = '#facc15';
        
        window.API.ajax({
            method: 'POST',
            url: '/api/admin/telegram/auth/send_code',
            headers: { 'Content-Type': 'application/json' },
            body: { phone: phone },
            success: function(res) {
                if (res && res.success) {
                    statusDiv.innerHTML = '🟢 Código enviado. Revisa tu aplicación de Telegram.';
                    statusDiv.style.color = '#4ade80';
                    document.getElementById('gen-verification-section').style.display = 'flex';
                    document.getElementById('gen-send-code-btn').style.display = 'none';
                    var codeInput = document.getElementById('gen-code');
                    if (codeInput) {
                        codeInput.focus();
                    }
                } else {
                    statusDiv.innerHTML = '🔴 Error: ' + (res ? res.error : 'No se pudo enviar el código');
                    statusDiv.style.color = '#f87171';
                }
            },
            error: function(err) {
                statusDiv.innerHTML = '🔴 Error de red.';
                statusDiv.style.color = '#f87171';
            }
        });
    };
    
    document.getElementById('gen-confirm-btn').onclick = function() {
        var phone = document.getElementById('gen-phone').value.trim();
        var code = document.getElementById('gen-code').value.trim();
        var password = document.getElementById('gen-password').value.trim();
        var statusDiv = document.getElementById('gen-status');
        if (!code) {
            alert('Por favor introduce el código recibido.');
            return;
        }
        statusDiv.innerHTML = '⏳ Generando sesión...';
        statusDiv.style.color = '#facc15';
        
        window.API.ajax({
            method: 'POST',
            url: '/api/admin/telegram/auth/confirm_code',
            headers: { 'Content-Type': 'application/json' },
            body: { phone: phone, code: code, password: password || null, is_global: !!isGlobal },
            success: function(res) {
                if (res && res.success) {
                    var successMsg = isGlobal ? '✅ Sesión global generada y guardada.' : '✅ Cuenta @' + res.username + ' generada e insertada.';
                    statusDiv.innerHTML = successMsg;
                    statusDiv.style.color = '#4ade80';
                    setTimeout(function() {
                        closeSubModal();
                        if (typeof onSuccessCallback === 'function') {
                            onSuccessCallback();
                        }
                    }, 1500);
                } else if (res && res.needs_2fa) {
                    statusDiv.innerHTML = '🔑 Se requiere contraseña de verificación de dos pasos (2FA).';
                    statusDiv.style.color = '#facc15';
                    document.getElementById('gen-2fa-section').style.display = 'block';
                } else {
                    statusDiv.innerHTML = '🔴 Error: ' + (res ? res.error : 'Código incorrecto');
                    statusDiv.style.color = '#f87171';
                }
            },
            error: function(err) {
                statusDiv.innerHTML = '🔴 Error de red al confirmar.';
                statusDiv.style.color = '#f87171';
            }
        });
    };
}
window._openSessionGeneratorModal = openSessionGeneratorModal;

// Añadir refreshLogs y copyLogs al objeto UI (para los botones de pane-logs)
UI.refreshLogs = function() {
    var pre = document.getElementById('logs-console');
    if (pre) pre.textContent = 'Cargando logs...';
    window.API.ajax({
        url: '/api/admin/logs?tail=1000',
        success: function(res) {
            if (!pre) pre = document.getElementById('logs-console');
            var text = (res && res.logs) ? res.logs : '(Sin logs disponibles)';
            if (pre) {
                pre.textContent = text;
                pre.scrollTop = pre.scrollHeight;
            }
        },
        error: function(err) {
            if (pre) pre.textContent = 'Error al cargar logs: ' + err;
        }
    });
};

UI.copyLogs = function() {
    var pre = document.getElementById('logs-console');
    if (!pre) return;
    var text = pre.textContent;
    var btn = document.getElementById('logs-copy-btn');
    try {
        navigator.clipboard.writeText(text).then(function() {
            if (btn) { btn.textContent = '✅ Copiado'; setTimeout(function() { btn.textContent = 'Copiar'; }, 2000); }
        }).catch(function() {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            if (btn) { btn.textContent = '✅ Copiado'; setTimeout(function() { btn.textContent = 'Copiar'; }, 2000); }
        });
    } catch(e) {
        if (btn) { btn.textContent = '⚠️ Error'; setTimeout(function() { btn.textContent = 'Copiar'; }, 2000); }
    }
};

window._refreshLogs = function(tail) {
    // Compatibilidad legacy - redirige a UI.refreshLogs
    UI.refreshLogs();
};

window._refreshLogs_full = function(tail) {
    var pre = document.getElementById('logs-console') || document.getElementById('logs-modal-content');
    var sizeEl = document.getElementById('logs-modal-size');
    var selectEl = document.getElementById('logs-tail-select');
    
    if (!tail) {
        tail = selectEl ? selectEl.value : '1000';
    } else if (selectEl) {
        selectEl.value = tail;
    }
    
    if (pre) pre.textContent = 'Cargando logs...';
    window.API.ajax({
        url: '/api/admin/logs?tail=' + tail,
        success: function(res) {
            if (!pre) return;
            var text = (res && res.logs) ? res.logs : '(Sin logs disponibles)';
            pre.textContent = text;
            if (sizeEl) {
                var lines = text.split('\n').length;
                sizeEl.textContent = lines + ' lineas - ' + Math.round(text.length / 1024 * 10) / 10 + ' KB';
            }
            // Auto-scroll al final
            pre.scrollTop = pre.scrollHeight;
        },
        error: function(err) {
            if (pre) pre.textContent = 'Error al cargar logs: ' + err;
        }
    });
};

window._copyLogs = function() {
    var pre = document.getElementById('logs-modal-content');
    if (!pre) return;
    var text = pre.textContent;
    var btn = document.getElementById('logs-copy-btn');
    try {
        navigator.clipboard.writeText(text).then(function() {
            if (btn) { btn.textContent = '✅ Copiado'; setTimeout(function() { btn.textContent = '📋 Copiar'; }, 2000); }
        }).catch(function() {
            // Fallback para Android WebView sin clipboard API
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            if (btn) { btn.textContent = '✅ Copiado'; setTimeout(function() { btn.textContent = '📋 Copiar'; }, 2000); }
        });
    } catch(e) {
        if (btn) { btn.textContent = '⚠️ Error'; setTimeout(function() { btn.textContent = '📋 Copiar'; }, 2000); }
    }
};

window.closeLogs = function() {
    var overlay = document.getElementById('logs-modal-overlay');
    if (overlay) overlay.style.display = 'none';
};

UI.loadPeersList = function() {
    var container = document.getElementById('peers-list-container');
    if (!container) return;
    if (!window._peersPollGen) window._peersPollGen = 0;
    var gen = ++window._peersPollGen;
    
    if (window._peersListLoading) return;
    window._peersListLoading = true;
    
    // Solo mostrar "Cargando..." si el contenedor está vacío para evitar parpadeos molestos
    if (container.children.length === 0 || container.innerHTML.indexOf('No hay peers') !== -1 || container.innerHTML.indexOf('Error') !== -1) {
        container.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;">Cargando peers...</div>';
    }
    
    // Guardar cuáles ids estaban expandidos
    var expandedIds = new Set();
    container.querySelectorAll('.peer-header').forEach(function(hdr) {
        var details = hdr.nextElementSibling;
        if (details && details.style.display === 'block') {
            expandedIds.add(hdr.getAttribute('data-peer-id'));
        }
    });
    window._peersExpandedIds = expandedIds;
    
    window.API.ajax({
        url: '/api/peers',
        success: function(res) {
            window._peersListLoading = false;
            if (gen !== window._peersPollGen) return;
            container.innerHTML = '';
            var peers = res || [];
            if (peers.length === 0) {
                container.innerHTML = '<div style="color:var(--text-secondary);font-size:0.85rem;">No hay peers remotos configurados.</div>';
                return;
            }
            
            // Cargar categorías UNA SOLA VEZ y cachearlas
            if (window._peersCats) {
                renderPeersList(container, peers, window._peersCats, gen);
            } else {
                window.API.getCategories(function(allCats) {
                    window._peersCats = allCats;
                    if (gen !== window._peersPollGen) return;
                    renderPeersList(container, peers, allCats, gen);
                });
            }
        },
        error: function(err) {
            window._peersListLoading = false;
            container.innerHTML = '<div style="color:#f87171;font-size:0.85rem;">Error al cargar peers.</div>';
        }
    });
};

function renderPeersList(container, peers, allCats, gen) {
    peers.forEach(function(peer) {
                    var peerId = peer.id;
                    var statusMap = { 'active': '🟢 Online', 'offline': '🔴 Offline', 'pending': '🟡 Pendiente' };
                    var statusText = statusMap[peer.status] || '🔘 ' + peer.status;
                    var isOnline = peer.is_online || peer.status === 'active';
                    
                    var card = document.createElement('div');
                    card.style.cssText = 'background:rgba(255,255,255,0.02); border:1px solid #27272a; border-radius:8px; padding:10px 12px;';
                    
                    var headerHtml = '' +
                        '<div style="display:flex; align-items:center; justify-content:space-between; cursor:pointer;" class="peer-header" data-peer-id="' + peerId + '">' +
                            '<div style="display:flex; flex-direction:column; gap:2px;">' +
                                '<div style="font-weight:600; font-size:0.9rem; color:#fff;">' + (isOnline ? '🟢' : '🔴') + ' ' + peer.name + '</div>' +
                                '<div style="font-size:0.75rem; color:var(--text-secondary);">' + peer.url + ' · ' + statusText + '</div>' +
                            '</div>' +
                            '<div style="font-size:0.8rem; color:var(--text-secondary); transition:transform 0.2s;" class="peer-expand-icon">▼</div>' +
                        '</div>' +
                        '<div class="peer-details" style="display:none; margin-top:10px; padding-top:10px; border-top:1px solid #27272a;">' +
                            '<div style="display:flex; gap:12px; margin-bottom:8px; flex-wrap:wrap;">' +
                                '<label style="display:flex; align-items:center; gap:6px; font-size:0.8rem; color:#d4d4d8; cursor:pointer;"><input type="checkbox" class="peer-toggle-share" data-peer="' + peerId + '" ' + (peer.share_enabled ? 'checked' : '') + '> Compartir local</label>' +
                                '<label style="display:flex; align-items:center; gap:6px; font-size:0.8rem; color:#d4d4d8; cursor:pointer;"><input type="checkbox" class="peer-toggle-receive" data-peer="' + peerId + '" ' + (peer.receive_enabled ? 'checked' : '') + '> Recibir remoto</label>' +
                            '</div>' +
                            '<div style="margin-bottom:8px;">' +
                                '<div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:4px;">Compartir categorías (lo que ve este peer de mí):</div>' +
                                '<div id="peer-share-cats-' + peerId + '" style="max-height:100px; overflow-y:auto; border:1px solid #27272a; border-radius:4px; padding:4px 6px; background:#09090b;"></div>' +
                            '</div>' +
                            '<div style="margin-bottom:8px;">' +
                                '<input type="text" class="peer-alias-input" data-peer="' + peerId + '" placeholder="Alias local (opcional)" value="' + (peer.alias || '') + '" style="width:100%; background:#09090b; border:1px solid #3f3f46; border-radius:6px; padding:4px 8px; color:#f4f4f5; font-size:0.75rem; height:28px; box-sizing:border-box;">' +
                            '</div>' +
                            '<div style="display:flex; gap:8px; justify-content:flex-end;">' +
                                '<button class="peer-request-sync" data-peer="' + peerId + '" style="background:#6366f1; border:none; color:white; padding:4px 10px; border-radius:4px; font-size:0.75rem; cursor:pointer;">🔄 Sincronizar</button>' +
                                '<button class="peer-delete-btn" data-peer="' + peerId + '" style="background:#ef4444; border:none; color:white; padding:4px 10px; border-radius:4px; font-size:0.75rem; cursor:pointer;">Eliminar</button>' +
                            '</div>' +
                        '</div>';
                    
                    card.innerHTML = headerHtml;
                    container.appendChild(card);
                    
                    // Poblar selector de categorías para compartir (árbol)
                    var catContainer = document.getElementById('peer-share-cats-' + peerId);
                    if (catContainer) {
                        try {
                            var selectedSet = new Set();
                            var cfg = peer.shared_config || {};
                            var subcats = cfg.subcategories || [];
                            subcats.forEach(function(s) { selectedSet.add(s); });
                            
                            window.UI.renderShareTree(allCats, catContainer, selectedSet, function(sel) {
                                window.API.ajax({
                                    method: 'PUT',
                                    url: '/api/peers/' + peerId + '/share-config',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: { categories: sel.categories, subcategories: sel.subcategories }
                                });
                            });
                        } catch(e) {
                            catContainer.innerHTML = '<span style="font-size:0.7rem; color:var(--text-secondary);">Error al cargar categorías</span>';
                        }
                    }
                    
                    // Toggle expand/collapse
                    var header = card.querySelector('.peer-header');
                    var detailsDiv = card.querySelector('.peer-details');
                    var expandIcon = card.querySelector('.peer-expand-icon');
                    
                    if (window._peersExpandedIds && window._peersExpandedIds.has(peerId)) {
                        detailsDiv.style.display = 'block';
                        expandIcon.style.transform = 'rotate(180deg)';
                    }
                    
                    header.addEventListener('click', function(e) {
                        if (detailsDiv.style.display === 'none') {
                            detailsDiv.style.display = 'block';
                            expandIcon.style.transform = 'rotate(180deg)';
                        } else {
                            detailsDiv.style.display = 'none';
                            expandIcon.style.transform = '';
                        }
                    });
                    
                    // Toggle compartir
                    card.querySelector('.peer-toggle-share').addEventListener('change', function() {
                        window.API.ajax({
                            method: 'PUT',
                            url: '/api/peers/' + peerId + '/toggle-share',
                            headers: { 'Content-Type': 'application/json' },
                            body: { enabled: this.checked },
                            error: function() { UI.loadPeersList(); }
                        });
                    });
                    
                    // Toggle recibir
                    card.querySelector('.peer-toggle-receive').addEventListener('change', function() {
                        window.API.ajax({
                            method: 'PUT',
                            url: '/api/peers/' + peerId + '/toggle-receive',
                            headers: { 'Content-Type': 'application/json' },
                            body: { enabled: this.checked },
                            success: function() {
                                setTimeout(UI.loadPeersList, 500);
                            },
                            error: function() { UI.loadPeersList(); }
                        });
                    });
                    
                    // Category share checkboxes
                    card.querySelectorAll('.share-cat-chk').forEach(function(cb) {
                        cb.addEventListener('change', function() {
                            var cats = [];
                            var parent = this.closest('.peer-details');
                            parent.querySelectorAll('.share-cat-chk:checked').forEach(function(c) {
                                cats.push(c.value);
                            });
                            window.API.ajax({
                                method: 'PUT',
                                url: '/api/peers/' + peerId + '/share-config',
                                headers: { 'Content-Type': 'application/json' },
                                body: { categories: cats, subcategories: [] }
                            });
                        });
                    });
                    
                    // Alias input
                    card.querySelector('.peer-alias-input').addEventListener('change', function() {
                        window.API.ajax({
                            method: 'PUT',
                            url: '/api/peers/' + peerId,
                            headers: { 'Content-Type': 'application/json' },
                            body: { alias: this.value.trim() }
                        });
                    });
                    
                    // Sync
                    card.querySelector('.peer-request-sync').addEventListener('click', function() {
                        this.textContent = '🔄 Sincronizando...';
                        this.disabled = true;
                        window.API.ajax({
                            method: 'POST',
                            url: '/api/peers/' + peerId + '/request-sync',
                            success: function() {
                                setTimeout(UI.loadPeersList, 1000);
                            },
                            error: function() {
                                UI.loadPeersList();
                            }
                        });
                    });
                    
                    // Delete
                    card.querySelector('.peer-delete-btn').addEventListener('click', function() {
                        if (!confirm('¿Eliminar peer "' + peer.name + '"? Se romperá la conexión en ambos sentidos.')) return;
                        window.API.ajax({
                            method: 'DELETE',
                            url: '/api/peers/' + peerId,
                            success: function() { UI.loadPeersList(); },
                            error: function(err) { alert('Error: ' + err); }
                        });
                    });
                });
}

window.downloadServerLogs = function() {
    // Abre el modal de configuración en la pestaña de Logs
    var modal = document.getElementById('settings-modal');
    if (!modal) return;
    if (modal.classList.contains('hidden')) {
        window.UI.toggleSettingsModal();
    }
    // Mostrar la pestaña de logs (puede estar oculta para no-admin, la hacemos visible temporalmente)
    var logsTabBtn = document.getElementById('tab-btn-logs');
    if (logsTabBtn) logsTabBtn.classList.remove('hidden');
    window.UI.switchSettingsTab('logs');
};
