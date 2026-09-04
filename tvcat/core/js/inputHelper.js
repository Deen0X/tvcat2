/**
 * TVCat Input Helper — Centraliza mapeo de controles físicos a acciones A-J
 *
 * Dispositivos: keyboard | tv | gamepad
 * A-J: A=prev, B=max, C=next, D=salto corto-, E=play/pause, F=salto corto+, G=salto largo-, H=skip intro, I=salto largo+, J=salir
 * Layout:
 *  PC (789/456/123): 7→A 8→B 9→C / 4→D 5→E 6→F / 1→G 2→H 3→I / 0→J
 *  TV (123/456/789): 1→A 2→B 3→C / 4→D 5→E 6→F / 7→G 8→H 9→I / 0→J
 *  Invert toggle (tvcat_invert_keyboard) intercambia filas 1↔7,2↔8,3↔9
 */
(function(){
    var ACTION_MAP = {
        'A': {label: 'Episodio anterior', short: 'Prev'},
        'B': {label: 'Maximizar', short: 'Max'},
        'C': {label: 'Episodio siguiente', short: 'Next'},
        'D': {label: 'Salto corto atrás', short: '←10s'},
        'E': {label: 'Play/Pause', short: '▶'},
        'F': {label: 'Salto corto adelante', short: '→10s'},
        'G': {label: 'Salto largo atrás', short: '←30s'},
        'H': {label: 'Saltar intro', short: 'Intro'},
        'I': {label: 'Salto largo adelante', short: '→30s'},
        'J': {label: 'Salir', short: 'Salir'}
    };
    var PC_MAP = {'7':'A','8':'B','9':'C','4':'D','5':'E','6':'F','1':'G','2':'H','3':'I','0':'J'};
    var TV_MAP = {'1':'A','2':'B','3':'C','4':'D','5':'E','6':'F','7':'G','8':'H','9':'I','0':'J'};
    var INVERT_MAP = {'1':'7','7':'1','2':'8','8':'2','3':'9','9':'3'};

    var helper = {
        ACTION_MAP: ACTION_MAP,

        isInverted: function(){
            try { return localStorage.getItem('tvcat_invert_keyboard')==='1'; } catch(e){ return false; }
        },
        setInverted: function(v){
            try { localStorage.setItem('tvcat_invert_keyboard', v?'1':'0'); } catch(e){}
        },
        applyInvert: function(digit){
            if (!digit) return digit;
            if (!this.isInverted()) return digit;
            return INVERT_MAP[digit] || digit;
        },
        getDeviceType: function(e){
            // gamepad polling no pasa por evento teclado; se detecta aparte
            if (e && e._fromGamepad) return 'gamepad';
            // Heurística: si hay customMap activo y UA es SmartTV, es mando TV
            try {
                if (window.Catalog && window.Catalog.detectDeviceCapabilities) {
                    var caps = window.Catalog.detectDeviceCapabilities();
                    if (caps.isSmartTV) return 'tv';
                }
                if (window.keyMapper && window.keyMapper.getProfileType && window.keyMapper.getProfileType()==='custom') return 'tv';
            } catch(err){}
            return 'keyboard';
        },
        digitToPosition: function(digit, device){
            var d = this.applyInvert(digit);
            var map = (device==='tv') ? TV_MAP : PC_MAP;
            // gamepad usa mismo que keyboard por defecto (convención)
            if (device==='gamepad') map = PC_MAP;
            return map[d] || null;
        },
        positionToAction: function(pos){
            return ACTION_MAP[pos] || null;
        },
        digitToAction: function(digit, device){
            var pos = this.digitToPosition(digit, device||this.getDeviceType());
            return pos ? {position: pos, action: ACTION_MAP[pos]} : null;
        },
        eventToAction: function(e){
            var digit = null;
            try { digit = window.keyMapper ? window.keyMapper.getVirtualDigit(e) : null; } catch(err){}
            if (digit===null) return null;
            var device = this.getDeviceType(e);
            var r = this.digitToAction(digit, device);
            if (r) { r.digit = digit; r.device = device; }
            return r;
        },
        // Navegación flechas (5=select,0=back, 8/2 arriba/abajo invertido según device)
        isNavigationDigit: function(digit, device){
            var d = this.applyInvert(digit);
            // 8 arriba, 2 abajo para keyboard; tv invierte? Ya applyInvert lo hace
            return ['2','4','5','6','8','0'].indexOf(d)!==-1;
        }
    };
    window.inputHelper = helper;
})();
