/* TVCat Assistants — guías paso a paso sin manifiesto.
 * Convención: core/static/assistants/<id>/stepN.md (+ stepN.png/jpg/webp opcional).
 * Tags en el md: {step:N:etiqueta} salta a paso, {goto:tab:<id>:etiqueta} abre
 * pestaña de ajustes, {goto:section:<id>:etiqueta} abre sección del catálogo.
 * ES5 (SmartTV antigua). */
(function() {
    var _data = null;
    var _idx = 0;

    function esc(s) {
        s = (s === undefined || s === null) ? '' : String(s);
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function renderInline(t) {
        t = t.replace(/`([^`]+)`/g, '<code style="background:#27272a;padding:1px 5px;border-radius:4px;">$1</code>');
        t = t.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
        t = t.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<i>$2</i>');
        t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:var(--accent);">$1</a>');
        // {step:N:etiqueta} — la etiqueta puede contener ':' (se parte en 2).
        t = t.replace(/\{step:(\d+):([^}]*)\}/g,
            '<button class="btn-secondary" data-astep="$1" style="padding:4px 12px;font-size:0.8rem;margin:2px;">$2</button>');
        // {goto:tab:<id>:etiqueta} y {goto:section:<id>:etiqueta}
        t = t.replace(/\{goto:(tab|section):([^:}]+):([^}]*)\}/g,
            '<button class="btn-secondary" data-agoto="$1:$2" style="padding:4px 12px;font-size:0.8rem;margin:2px;">$3 🔗</button>');
        return t;
    }

    function renderMd(md) {
        var lines = String(md || '').split('\n');
        var html = '';
        var listOpen = false;
        var olOpen = false;
        function closeLists() {
            if (listOpen) { html += '</ul>'; listOpen = false; }
            if (olOpen) { html += '</ol>'; olOpen = false; }
        }
        for (var i = 0; i < lines.length; i++) {
            var raw = lines[i];
            var t = raw.trim();
            if (!t) { closeLists(); continue; }
            var h = t.match(/^(#{1,3})\s+(.*)$/);
            if (h) {
                closeLists();
                var lvl = h[1].length + 1;
                html += '<h' + lvl + ' style="margin:10px 0 6px;">' + renderInline(esc(h[2])) + '</h' + lvl + '>';
                continue;
            }
            var li = t.match(/^[-*]\s+(.*)$/);
            if (li) {
                if (olOpen) { html += '</ol>'; olOpen = false; }
                if (!listOpen) { html += '<ul style="margin:6px 0;padding-left:22px;">'; listOpen = true; }
                html += '<li>' + renderInline(esc(li[1])) + '</li>';
                continue;
            }
            var ol = t.match(/^\d+[.)]\s+(.*)$/);
            if (ol) {
                if (listOpen) { html += '</ul>'; listOpen = false; }
                if (!olOpen) { html += '<ol style="margin:6px 0;padding-left:22px;">'; olOpen = true; }
                html += '<li>' + renderInline(esc(ol[1])) + '</li>';
                continue;
            }
            closeLists();
            html += '<p style="margin:6px 0;line-height:1.5;">' + renderInline(esc(raw.trim())) + '</p>';
        }
        closeLists();
        return html;
    }

    function paint() {
        var ov = document.getElementById('assistant-overlay');
        if (!ov || !_data) return;
        var step = _data.steps[_idx];
        var title = document.getElementById('assistant-title');
        if (title) title.textContent = _data.title + ' — Paso ' + (_idx + 1) + '/' + _data.steps.length;
        var img = document.getElementById('assistant-img');
        if (img) {
            if (step.img) { img.src = step.img; img.style.display = 'block'; }
            else { img.removeAttribute('src'); img.style.display = 'none'; }
        }
        var body = document.getElementById('assistant-body');
        if (body) body.innerHTML = renderMd(step.md);
        var prev = document.getElementById('assistant-prev');
        var next = document.getElementById('assistant-next');
        if (prev) prev.disabled = (_idx <= 0);
        if (next) next.disabled = (_idx >= _data.steps.length - 1);
    }

    function doGoto(spec) {
        var parts = String(spec || '').split(':');
        var kind = parts[0], id = parts[1];
        closeAssistant();
        try {
            if (kind === 'tab' && typeof window.switchSettingsTab === 'function') {
                var modal = document.getElementById('settings-modal');
                if (modal && modal.classList.contains('hidden') && typeof window.toggleSettingsModal === 'function') {
                    window.toggleSettingsModal();
                }
                setTimeout(function() { try { window.switchSettingsTab(id); } catch (e) {} }, 150);
            } else if (kind === 'section' && typeof window.selectSection === 'function') {
                var el = document.querySelector('.side-menu-nav a[data-category="' + id + '"]');
                window.selectSection(id, el);
            }
        } catch (e) {}
    }

    function closeAssistant() {
        var ov = document.getElementById('assistant-overlay');
        if (ov && ov.parentNode) ov.parentNode.removeChild(ov);
        _data = null;
    }
    window.closeAssistant = closeAssistant;

    window.openAssistant = function(id) {
        closeAssistant();
        if (!id) return;
        window.API.ajax({
            url: '/api/assistants/' + encodeURIComponent(id),
            success: function(res) {
                if (!res || !res.steps || !res.steps.length) { assistantMissing(id); return; }
                _data = res;
                _idx = 0;
                var ov = document.createElement('div');
                ov.id = 'assistant-overlay';
                ov.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);z-index:60000;display:block;overflow:auto;';
                var bx = document.createElement('div');
                bx.style.cssText = 'background:#18181b;color:#f4f4f5;width:94vw;max-width:1100px;height:92vh;margin:4vh auto;padding:16px;border:1px solid #3f3f46;border-radius:8px;display:flex;flex-direction:column;box-sizing:border-box;overflow:hidden;';
                bx.innerHTML = '<h3 id="assistant-title" style="margin:0 0 8px 0;flex-shrink:0;"></h3>' +
                    '<img id="assistant-img" style="display:none;max-width:100%;flex:1;min-height:0;object-fit:contain;border-radius:6px;background:#09090b;margin:0 auto 8px;">' +
                    '<div id="assistant-body" style="font-size:0.88rem;overflow-y:auto;min-height:60px;"></div>' +
                    '<div style="display:flex;gap:8px;margin-top:12px;align-items:center;flex-shrink:0;">' +
                    '<button id="assistant-prev" class="btn-secondary" style="padding:8px 16px;">◀ Anterior</button>' +
                    '<span style="flex:1;"></span>' +
                    '<button id="assistant-next" class="btn-secondary" style="padding:8px 16px;">Siguiente ▶</button>' +
                    '<button id="assistant-close" class="btn-secondary" style="padding:8px 16px;">Cerrar</button></div>';
                ov.appendChild(bx);
                document.body.appendChild(ov);
                ov.onclick = function(e) { if (e.target === ov) closeAssistant(); };
                bx.querySelector('#assistant-prev').onclick = function() { if (_idx > 0) { _idx--; paint(); } };
                bx.querySelector('#assistant-next').onclick = function() { if (_data && _idx < _data.steps.length - 1) { _idx++; paint(); } };
                bx.querySelector('#assistant-close').onclick = closeAssistant;
                bx.querySelector('#assistant-body').onclick = function(e) {
                    var t = e.target || e.srcElement;
                    if (!t || !t.getAttribute) return;
                    var st = t.getAttribute('data-astep');
                    if (st) {
                        var n = parseInt(st, 10);
                        if (n >= 1 && _data && n <= _data.steps.length) { _idx = n - 1; paint(); }
                        return;
                    }
                    var go = t.getAttribute('data-agoto');
                    if (go) doGoto(go);
                };
                paint();
            },
            error: function() { assistantMissing(id); }
        });
    };

    function assistantMissing(id) {
        try { alert('Asistente "' + id + '" no disponible todavía.'); } catch (e) {}
    }
})();
