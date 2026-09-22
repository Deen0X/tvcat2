/* tvcat_episode_slicer — Modal de corte estilo TGHirayi (ES5, SmartTV-safe) */
(function() {
  var API = '/api/slicer';

  function ajax(url, opts, cb) {
    var method = (opts && opts.method) || 'GET';
    var data = opts && opts.data;
    if (window.API && window.API.ajax) {
      // api.js hace JSON.stringify(data) internamente: pasar OBJETO, no string.
      window.API.ajax({ url: url, method: method, data: data || null,
        success: function(r) { cb(null, r); },
        error: function(status, raw) { cb(normErr(raw, status, null)); } });
      return;
    }
    var x = new XMLHttpRequest();
    x.open(method, url, true);
    x.setRequestHeader('Content-Type', 'application/json');
    x.onreadystatechange = function() {
      if (x.readyState !== 4) return;
      if (x.status >= 200 && x.status < 300) {
        try { cb(null, JSON.parse(x.responseText)); } catch (e) { cb(null, x.responseText); }
      } else { cb(normErr(x.responseText, x.status, x)); }
    };
    x.send(data ? JSON.stringify(data) : null);
  }

  function normErr(e, status, xhr) {
    var code = status || (xhr && xhr.status) || (e && e.status) || 0;
    var detail = '';
    try {
      var raw = (xhr && xhr.responseText) || (typeof e === 'string' ? e : (e && e.responseText)) || '';
      if (raw) {
        var j = JSON.parse(raw);
        detail = j.detail || j.message || raw.slice(0, 200);
      } else if (e && e.detail) { detail = e.detail; }
      else if (e && e.message) { detail = e.message; }
    } catch (ex) { detail = String((e && e.responseText) || e || ''); }
    var err = new Error('HTTP ' + code + (detail ? ': ' + detail : ''));
    err.code = code; err.detail = detail;
    return err;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function toast(msg) {
    try {
      if (window._tgcopyToast) { window._tgcopyToast(msg); return; }
      alert(msg);
    } catch (e) { alert(msg); }
  }

  function openModal(title, bodyHtml, onMount) {
    var ov = document.createElement('div');
    ov.setAttribute('style', 'position:fixed;top:0;right:0;bottom:0;left:0;background:rgba(0,0,0,0.7);z-index:999999;');
    ov.onclick = function(e) { if (e.target === ov) { document.body.removeChild(ov); } };
    var panel = document.createElement('div');
    panel.setAttribute('style', 'position:fixed;top:5%;left:0;right:0;margin:0 auto;width:640px;max-width:94%;box-sizing:border-box;max-height:86%;overflow:auto;background:#18181b;color:#f4f4f5;border:1px solid #333;border-radius:10px;padding:16px;');
    var h = document.createElement('h3');
    h.appendChild(document.createTextNode(title));
    var x = document.createElement('button');
    x.appendChild(document.createTextNode('X'));
    x.setAttribute('style', 'float:right;width:32px;height:32px;background:#333;color:#fff;border:1px solid #555;border-radius:8px;');
    x.onclick = function() { document.body.removeChild(ov); };
    panel.appendChild(x);
    panel.appendChild(h);
    var body = document.createElement('div');
    body.innerHTML = bodyHtml;
    panel.appendChild(body);
    ov.appendChild(panel);
    document.body.appendChild(ov);
    if (onMount) { onMount(body, function() { try { document.body.removeChild(ov); } catch (e) {} }); }
  }

  function flattenSeasons(seasons) {
    var out = [];
    var names = Object.keys(seasons || {});
    for (var i = 0; i < names.length; i++) {
      var arr = seasons[names[i]] || [];
      for (var j = 0; j < arr.length; j++) { out.push(arr[j]); }
    }
    out.sort(function(a, b) { return (a.episode_number || 0) - (b.episode_number || 0); });
    return out;
  }

  function refreshAfterSplit(origItemId, newItemId) {
    // Tras un corte: invalidar caché de episodios (el modal reutiliza caché),
    // recargar la vista ACTUAL (load() solo recarga 'home') y si el modal de
    // episodios del original sigue abierto, recargarlo sin caché.
    try {
      if (window.Catalog) {
        if (window.Catalog.currentEpisodes) {
          try { delete window.Catalog.currentEpisodes[origItemId]; } catch (e) {}
          try { if (newItemId) delete window.Catalog.currentEpisodes[newItemId]; } catch (e2) {}
        }
        try { window.Catalog.load(window.Catalog.currentCategory || 'home'); } catch (e3) {}
        try {
          var epModal = document.getElementById('episodes-modal');
          if (epModal && !epModal.classList.contains('hidden') && window.Catalog.openEpisodesModal) {
            window.Catalog.openEpisodesModal(origItemId);
          }
        } catch (e4) {}
      }
    } catch (e) {}
  }

  // Patrón collections: imagen del plugin con fallback a emoji si no hay arte.
  var HERO_ICON = '<img src="/plugin-static/tvcat_episode_slicer/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="this.outerHTML=\'✂️\'">';

  function openSlicerModal(itemData) {
    var itemId = itemData.item_id || itemData.id;
    if (!itemId) { toast('Sin item_id'); return; }
    var url = '/api/media/' + encodeURIComponent(itemId) + '/episodes';
    var fetch = function(cb) {
      if (window.API && window.API.ajax) {
        window.API.ajax({ url: url, success: function(r) { cb(null, r); },
          error: function(s, r) { cb(normErr(r, s, null)); } });
      } else { ajax(url, {}, cb); }
    };
    fetch(function(err, seasons) {
      if (err) { toast('No se pudo cargar episodios'); return; }
      var eps = flattenSeasons(seasons);
      if (!eps.length) { toast('Sin episodios'); return; }
      // ¿Es parte de un corte? Línea "Unir con original" sobre el listado.
      ajax(API + '/cut_of?item_id=' + encodeURIComponent(itemId), { method: 'GET' }, function(eCut, cutRes) {
        var cut = (!eCut && cutRes && cutRes.cut) ? cutRes.cut : null;
        buildList(eps, cut);
      });
    });
    function buildList(eps, cut) {
      var html = '';
      if (cut) {
        var origTitle = esc(cut.orig_title || cut.orig_item_id || 'original');
        var origCover = '/api/cover/' + encodeURIComponent(cut.orig_item_id || '');
        var origLink = cut.orig_link
          ? '<a href="' + esc(cut.orig_link) + '" target="_blank" style="color:#a855f7;">' + origTitle + '</a>'
          : origTitle;
        html += '<div style="display:flex;align-items:center;gap:10px;background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.4);border-radius:8px;padding:8px 10px;margin-bottom:10px;">'
          + '<img src="' + origCover + '" style="width:48px;height:72px;object-fit:cover;border-radius:4px;" onerror="this.style.display=\'none\'">'
          + '<div style="flex:1;font-size:0.8rem;color:#f4f4f5;">Parte de<br><b>' + origLink + '</b></div>'
          + '<button class="slicer-unsplit" style="background:#a855f7;border:none;border-radius:6px;padding:8px 12px;color:#fff;font-weight:700;font-size:0.8rem;cursor:pointer;white-space:nowrap;">Unir con original</button>'
          + '</div>';
      }
      html += '<p>Episodios: ' + eps.length + '. Toca ✂️ para cortar desde ese episodio:</p>'
        + '<div style="display:flex;flex-direction:column;gap:8px;">';
      for (var i = 0; i < eps.length; i++) {
        var ep = eps[i];
        var n = ep.episode_number || (i + 1);
        var nm = ep.file_name || ep.title || ('E' + n);
        var title = n + '. ' + nm;
        var thumbUrl = ep.telegram_msg_id ? ('/api/media/episode/thumbnail/' + ep.telegram_msg_id) : null;
        var coverUrl = '/api/cover/' + encodeURIComponent(itemId);
        var src = (thumbUrl && ep.has_thumb) ? thumbUrl : coverUrl;
        var cap = ep.caption ? '<p class="episode-overview" title="' + esc(ep.caption) + '">' + esc(ep.caption) + '</p>' : '';
        var btn = (i === 0)
          ? '<div class="watched-toggle" title="El original siempre conserva el primero" style="opacity:0.3;cursor:default;color:rgba(255,255,255,0.3);">✂️</div>'
          : '<div class="watched-toggle slicer-cut" data-cut="' + ep.telegram_msg_id + '" data-item="' + esc(ep.item_id || itemId) + '" title="Cortar desde aquí" '
          + 'style="color:#22c55e;border-color:#22c55e;background:rgba(34,197,94,0.1);font-size:18px;cursor:pointer;">✂️</div>';
        html += '<div class="episode-card" style="cursor:default;">'
          + '<div class="episode-thumb-container"><img src="' + src + '" class="episode-thumb" alt="" loading="lazy" '
          + 'onerror="this.onerror=null;this.src=\'' + coverUrl + '\';" /></div>'
          + '<div class="episode-info"><h3 class="episode-title">' + esc(title) + '</h3>' + cap + '</div>'
          + btn + '</div>';
      }
      html += '</div>';
      openModal('Episode Slicer · ' + (itemData.title || itemId), html, function(body, close) {
        var btns = body.querySelectorAll('.slicer-cut[data-cut]');
        for (var k = 0; k < btns.length; k++) {
          (function(btn) {
            btn.onclick = function(ev) {
              if (ev && ev.stopPropagation) { ev.stopPropagation(); }
              var fromMsg = parseInt(btn.getAttribute('data-cut'), 10);
              // La lista fusiona variantes: cortar sobre el título REAL del episodio,
              // no sobre el mostrado (si no, el msg no existe ahí → 400).
              var realItem = btn.getAttribute('data-item') || itemId;
              ajax(API + '/preview', { method: 'POST', data: { item_id: realItem, from_msg_id: fromMsg } }, function(e2, prev) {
                if (e2) { toast('Preview falló: ' + (e2.message || e2)); return; }
                var ok = confirm('Crear "' + prev.new.title + '" con ' + prev.new.count + ' episodios?\nOriginal queda con ' + prev.orig.keep + '.');
                if (!ok) return;
                ajax(API + '/split', { method: 'POST', data: { item_id: realItem, from_msg_id: fromMsg } }, function(e3, res) {
                  if (e3) { toast('Split falló: ' + (e3.message || e3)); return; }
                  if (res && res.central_refreshed === false) {
                    var go = confirm('Corte guardado (' + res.new_item_id + ') pero la central no se actualizó.\n'
                      + (res.warn || '') + '\n\n¿Reintentar sincronización ahora?');
                    if (go) {
                      ajax(API + '/resync', { method: 'POST', data: {} }, function(e4, rr) {
                        toast((rr && rr.ok) ? 'Central sincronizada. Busca el nuevo título.' : 'Resync falló: ' + ((rr && (rr.detail || rr.hint)) || (e4 && e4.message) || 'ver log gateway'));
                        close();
                        refreshAfterSplit(itemId, res.new_item_id);
                      });
                    }
                    return;
                  }
                  toast('Corte creado: ' + res.new_item_id + ' (' + res.moved + ' eps)');
                  close();
                  refreshAfterSplit(realItem, res.new_item_id);
                });
              });
            };
          })(btns[k]);
        }
        var un = body.querySelector('.slicer-unsplit');
        if (un) un.onclick = function() {
          var origName = (cut && (cut.orig_title || cut.orig_item_id)) || 'el original';
          if (!confirm('Unir esta parte con "' + origName + '"?\nLos episodios vuelven al título original.')) return;
          un.disabled = true;
          ajax(API + '/unsplit', { method: 'POST', data: { new_item_id: itemId } }, function(eU, res) {
            un.disabled = false;
            if (eU) { toast('Unir falló: ' + (eU.message || eU)); return; }
            toast('Unido: ' + (res.restored || 0) + ' episodios devueltos'
              + (res.central_refreshed === false ? ' (central pendiente: ' + (res.warn || '') + ')' : ''));
            close();
            try {
              if (window.Catalog && window.Catalog.currentCategory === 'local_edits'
                && typeof selectSection === 'function') selectSection('local_edits', document.querySelector('[data-category="local_edits"]'));
              else if (window.Catalog && typeof window.Catalog.refreshGridCover === 'function' && cut && cut.orig_item_id) window.Catalog.refreshGridCover(cut.orig_item_id);
            } catch (eR) {}
          });
        };
      });
    }
  }

  if (window.pluginSystem) {
    window.pluginSystem.registerPlugin({
      name: 'tvcat_episode_slicer',
      type: 'heropage-action',
      displayName: 'Episode Slicer',
      getHeroButtons: function(itemData) {
        if (!itemData) return [];
        return [{ id: 'btn-slicer', icon: HERO_ICON, tooltip: 'Cortar episodios (Episode Slicer)', label: '',
          action: function() { openSlicerModal(itemData); } }];
      }
    });
  }
})();
