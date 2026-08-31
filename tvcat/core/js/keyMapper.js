/**
 * TVCat KeyMapper Module
 * Traduce keycodes físicos en dígitos virtuales '0'-'9' y gestiona la calibración.
 */

(function() {
    var DEFAULT_PC_KEYCODES = {
        48: '0', 49: '1', 50: '2', 51: '3', 52: '4',
        53: '5', 54: '6', 55: '7', 56: '8', 57: '9',
        96: '0', 97: '1', 98: '2', 99: '3', 100: '4',
        101: '5', 102: '6', 103: '7', 104: '8', 105: '9'
    };

    var keyMapper = {
        customMap: {},

        init: function() {
            try {
                var saved = localStorage.getItem('tflix_key_map');
                if (saved) {
                    this.customMap = JSON.parse(saved);
                    console.log('[KEYMAP] Cargada calibración personalizada del mando:', this.customMap);
                }
            } catch (e) {
                console.error('[KEYMAP] Error cargando calibración:', e);
            }
        },

        getVirtualDigit: function(e) {
            var keyCode = e.keyCode || e.which;
            if (this.customMap && this.customMap[keyCode] !== undefined) {
                return this.customMap[keyCode];
            }
            if (DEFAULT_PC_KEYCODES[keyCode] !== undefined) {
                return DEFAULT_PC_KEYCODES[keyCode];
            }
            return null;
        },

        saveKeyMapping: function(keyCode, digit) {
            this.customMap[keyCode] = digit;
            try {
                localStorage.setItem('tflix_key_map', JSON.stringify(this.customMap));
            } catch (e) {
                console.error('[KEYMAP] Error al guardar en LocalStorage:', e);
            }
        },

        clearCalibration: function() {
            this.customMap = {};
            try {
                localStorage.removeItem('tflix_key_map');
            } catch (e) {
                console.error('[KEYMAP] Error al borrar de LocalStorage:', e);
            }
        },

        getProfileType: function() {
            return Object.keys(this.customMap).length > 0 ? 'custom' : 'default';
        }
    };

    // Expose globally
    window.keyMapper = keyMapper;
    keyMapper.init();
})();
