/**
 * TVCat 2 - xTranslate Frontend
 * Sistema multi-idioma
 */
// Polyfills for old Smart TV WebKit (Tizen 1.x/2.x, webOS, etc.)
(function() {
    if (window.Element) {
        if (!Element.prototype.matches) {
            Element.prototype.matches = Element.prototype.msMatchesSelector || Element.prototype.webkitMatchesSelector || function(sel) {
                var matches = (this.document || this.ownerDocument).querySelectorAll(sel);
                var i = matches.length;
                while (--i >= 0 && matches.item(i) !== this) {}
                return i > -1;
            };
        }
        if (!Element.prototype.closest) {
            Element.prototype.closest = function(sel) {
                var el = this;
                while (el) {
                    if (el.matches && el.matches(sel)) return el;
                    el = el.parentElement;
                }
                return null;
            };
        }
    }
    if (!Array.prototype.includes) {
        Array.prototype.includes = function(item) {
            for (var i = 0; i < this.length; i++) { if (this[i] === item) return true; }
            return false;
        };
    }
    if (!String.prototype.startsWith) {
        String.prototype.startsWith = function(s) { return this.indexOf(s) === 0; };
    }
    if (!String.prototype.endsWith) {
        String.prototype.endsWith = function(s) { return this.slice(-s.length) === s; };
    }
})();

window.xTranslate = (function() {
    var _dict = {};
    var _idx = 0;

    function load(callback) {
        window.API.ajax({
            url: '/api/translations',
            success: function(data) {
                _dict = data.dict || {};
                _idx = data.idx || 0;
                if (callback) callback();
            },
            error: function() {
                if (callback) callback();
            }
        });
    }

    function t(text) {
        if (!text) return text;
        if (_dict[text]) {
            return _dict[text];
        }
        return text;
    }

    return {
        load: load,
        t: t
    };
})();
