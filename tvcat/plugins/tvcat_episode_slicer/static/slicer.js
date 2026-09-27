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
      // Nunca alert(): toasts propios no bloqueantes.
      var t = document.getElementById('slicer-toast');
      if (!t) {
        t = document.createElement('div');
        t.id = 'slicer-toast';
        t.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#27272a;border:1px solid #52525b;color:#f4f4f5;font-size:0.8rem;padding:8px 16px;border-radius:8px;z-index:1000000;max-width:90vw;';
        document.body.appendChild(t);
      }
      t.textContent = msg;
      t.style.display = 'block';
      if (t._to) clearTimeout(t._to);
      t._to = setTimeout(function() { try { t.style.display = 'none'; } catch (e) {} }, 3500);
    } catch (e) {}
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

  // Detección temporada/episodio sobre file_name||title. Cascada:
  // SxxEyy, TxxExx/TxxCxx, NxN con fronteras. Devuelve {s,e} o null.
  function detectSeasonEp(name) {
    var s = String(name || '').replace(/[._\- ]+/g, ' ');
    var m = s.match(/[Ss](\d{1,2})[Ee](\d{1,3})/);
    if (m) return { s: parseInt(m[1], 10), e: parseInt(m[2], 10), fam: 'S' };
    m = s.match(/[Tt](\d{1,2})[EeCc](\d{1,3})/);
    if (m) return { s: parseInt(m[1], 10), e: parseInt(m[2], 10), fam: 'T' };
    m = s.match(/[Tt](\d{1,2})\s+[CcEe](\d{1,3})/);
    if (m) return { s: parseInt(m[1], 10), e: parseInt(m[2], 10), fam: 'T' };
    m = s.match(/(^|[^0-9])(\d{1,2})[x×](\d{1,3})([^0-9]|$)/);
    if (m) return { s: parseInt(m[2], 10), e: parseInt(m[3], 10), fam: 'X' };
    return null;
  }

  // Consenso: la familia con más matches manda para todo el título.
  function detectFamily(eps) {
    var counts = { S: 0, T: 0, X: 0 };
    for (var i = 0; i < eps.length; i++) {
      var d = detectSeasonEp(eps[i].file_name || eps[i].title || '');
      if (d) counts[d.fam]++;
    }
    var best = null, bestN = 0;
    for (var f in counts) {
      if (counts[f] > bestN) { bestN = counts[f]; best = f; }
    }
    return bestN > 0 ? best : null;
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
      // Solo el título abierto: el endpoint fusiona variantes hermanas
      // (mismo group_title_flat) y mezclarlas descuadra cortes, números y Auto.
      // Si ninguna coincide (fallback de plugins), se conserva la lista completa.
      var own = [];
      for (var fi = 0; fi < eps.length; fi++) {
        if (String(eps[fi].item_id || '') === String(itemId)) own.push(eps[fi]);
      }
      if (own.length) eps = own;
      // ¿Es parte de un corte? Línea "Unir" sobre el listado + vecino siguiente.
      ajax(API + '/cut_of?item_id=' + encodeURIComponent(itemId), { method: 'GET' }, function(eCut, cutRes) {
        var cut = (!eCut && cutRes && cutRes.cut) ? cutRes.cut : null;
        ajax(API + '/neighbors?item_id=' + encodeURIComponent(itemId), { method: 'GET' }, function(eN, nRes) {
          var nb = (!eN && nRes) ? nRes : { prev: null, next: null };
          buildList(eps, cut, nb);
        });
      });
    });
    function buildList(eps, cut, neighbors) {
      neighbors = neighbors || { prev: null, next: null };
      var html = '';
      // Offset = temporada del propio título (la del primer fichero; 1 si no
      // hay patrón). El primer check es offset+1 y la numeración sigue
      // secuencial; el Auto omite la temporada del título (titleSeason).
      var fam = detectFamily(eps);
      var titleSeason = null;
      var firstSeason = 1;
      try {
        var d0 = detectSeasonEp(eps[0].file_name || eps[0].title || '');
        if (d0 && (!fam || d0.fam === fam)) { titleSeason = d0.s; firstSeason = d0.s; }
      } catch (eFS) {}
      // Trozo anterior (del que se cortó) y/o siguiente (hijo directo).
      // Mitades: izquierda anterior, derecha siguiente.
      var _prevT = (cut && (cut.orig_title || cut.orig_item_id)) || (neighbors.prev && neighbors.prev.title) || null;
      var _prevId = (cut && cut.orig_item_id) || (neighbors.prev && neighbors.prev.item_id) || null;
      var _nextT = (neighbors.next && neighbors.next.title) || null;
      var _nextId = (neighbors.next && neighbors.next.item_id) || null;
      if (_prevId || _nextId) {
        html += '<div style="display:flex;gap:8px;margin-bottom:10px;">';
        if (_prevId) {
          var _prevCover = '/api/cover/' + encodeURIComponent((cut && (cut.orig_item_id || '')) || _prevId);
          html += '<div style="flex:1;display:flex;align-items:center;gap:10px;background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.4);border-radius:8px;padding:8px 10px;">'
            + '<img src="' + _prevCover + '" style="width:48px;height:72px;object-fit:cover;border-radius:4px;" onerror="this.style.display=\'none\'">'
            + '<div style="flex:1;font-size:0.8rem;color:#f4f4f5;">Parte de<br><b>' + esc(_prevT || _prevId) + '</b></div>'
            + '<button class="slicer-unsplit" title="Unir con ' + esc(_prevT || _prevId) + '" style="background:#a855f7;border:none;border-radius:6px;padding:8px 12px;color:#fff;font-weight:700;font-size:1rem;cursor:pointer;white-space:nowrap;">◀</button>'
            + '</div>';
        }
        if (_nextId) {
          var _nextCover = '/api/cover/' + encodeURIComponent(_nextId);
          html += '<div style="flex:1;display:flex;align-items:center;gap:10px;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.4);border-radius:8px;padding:8px 10px;">'
            + '<div style="flex:1;font-size:0.8rem;color:#f4f4f5;">Siguiente<br><b>' + esc(_nextT || _nextId) + '</b></div>'
            + '<button class="slicer-unsplit-next" data-id="' + esc(_nextId) + '" data-name="' + esc(_nextT || _nextId) + '" title="Unir con ' + esc(_nextT || _nextId) + '" style="background:#22c55e;border:none;border-radius:6px;padding:8px 12px;color:#fff;font-weight:700;font-size:1rem;cursor:pointer;white-space:nowrap;">▶</button>'
            + '<img src="' + _nextCover + '" style="width:48px;height:72px;object-fit:cover;border-radius:4px;" onerror="this.style.display=\'none\'">'
            + '</div>';
        }
        html += '</div>';
      }
      html += '<label style="display:flex;gap:8px;align-items:center;font-size:0.8rem;color:#f4f4f5;background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.4);border-radius:8px;padding:8px 10px;margin-bottom:10px;cursor:pointer;">'
        + '<input type="checkbox" class="slicer-use-orig" style="accent-color:#a855f7;">'
        + '<span>Utilizar el nombre del título original para el nuevo título<br><span style="color:#a1a1aa;font-size:0.72rem;">Marcado: «título original_nombre del fichero». Desmarcado: nombre del fichero.</span></span></label>';
        html += '<p>Episodios: ' + eps.length + '. Marca checks y usa Slice / Season Slicer, o Auto para marcar inicios de temporada:</p>'
        + '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.4);border-radius:8px;padding:8px 10px;margin-bottom:10px;">'
        + '<label style="font-size:0.75rem;color:#a1a1aa;">Inicio secuencia:</label>'
        + '<input type="number" class="slicer-offset" value="' + firstSeason + '" min="1" style="width:64px;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:4px 6px;color:#f4f4f5;font-size:0.8rem;">'
        + '<button class="slicer-master" data-on="1" style="background:#27272a;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.75rem;cursor:pointer;">Todos</button>'
        + '<button class="slicer-master" data-on="0" style="background:#27272a;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.75rem;cursor:pointer;">Ninguno</button>'
        + '<button class="slicer-auto" style="background:#0e7490;border:none;border-radius:6px;padding:6px 10px;color:#fff;font-size:0.75rem;cursor:pointer;">Auto</button>'
        + '<button class="slicer-goslice" style="background:#22c55e;border:none;border-radius:6px;padding:6px 10px;color:#fff;font-weight:700;font-size:0.75rem;cursor:pointer;">Slice</button>'
        + '<button class="slicer-goseason" style="background:#a855f7;border:none;border-radius:6px;padding:6px 10px;color:#fff;font-weight:700;font-size:0.75rem;cursor:pointer;">Season Slicer</button>'
        + '<button class="slicer-epeditor" title="episode editor: episodios por temporada (autofill TMDB)" style="background:#27272a;border:1px solid #3f3f46;border-radius:6px;padding:6px 10px;color:#f4f4f5;font-size:0.75rem;cursor:pointer;">🔢</button>'
        + '</div>'
        // Lista compacta propia (NO .episode-card del reproductor: esa fila
        // mide ~90px + la fila superior de controles = ~140px por episodio).
        // Fila única: thumb 70px + título + controles al final.
        + '<div style="display:flex;flex-direction:column;gap:4px;">';
      for (var i = 0; i < eps.length; i++) {
        var ep = eps[i];
        var n = ep.episode_number || (i + 1);
        var nm = ep.file_name || ep.title || ('E' + n);
        // Título como enlace al mensaje original (verificación).
        var tlink = ep.telegram_link || '';
        var titleHtml = esc(n + '. ' + nm);
        if (tlink) {
          titleHtml = '<a href="' + esc(tlink) + '" target="_blank" rel="noopener noreferrer" title="Abrir en el chat original" style="color:inherit;text-decoration:underline dotted;">' + esc(n + '. ' + nm) + '</a>';
        }
        var thumbUrl = ep.telegram_msg_id ? ('/api/media/episode/thumbnail/' + ep.telegram_msg_id) : null;
        var coverUrl = '/api/cover/' + encodeURIComponent(itemId);
        var src = (thumbUrl && ep.has_thumb) ? thumbUrl : coverUrl;
        var ctrls;
        if (i === 0) {
          ctrls = '<span title="El original siempre conserva el primero" style="opacity:0.3;color:rgba(255,255,255,0.3);flex-shrink:0;">✂️</span>';
        } else {
          ctrls = '<input type="number" class="slicer-season" data-msg="' + ep.telegram_msg_id + '" value="" placeholder="—" title="Temporada de este corte (vacío = sin temporada)" style="width:48px;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:3px 4px;color:#f4f4f5;font-size:0.75rem;flex-shrink:0;">'
            + '<input type="checkbox" class="slicer-check" data-msg="' + ep.telegram_msg_id + '" style="accent-color:#a855f7;width:16px;height:16px;cursor:pointer;flex-shrink:0;">'
            + '<button class="slicer-cutone" data-msg="' + ep.telegram_msg_id + '" data-idx="' + i + '" title="Cortar aquí y mover a un título nuevo" style="background:none;border:1px solid #3f3f46;border-radius:4px;color:#f4f4f5;font-size:0.8rem;padding:2px 5px;cursor:pointer;flex-shrink:0;">✂️</button>';
        }
        // Fila compacta en UNA línea: thumb + título + controles al final.
        // El indicador T/E va SOBRE la caja de temporada + checkbox.
        html += '<div class="slicer-row" style="display:flex;align-items:center;gap:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:6px;padding:4px 8px;min-height:44px;box-sizing:border-box;">'
        + '<img src="' + src + '" alt="" loading="lazy" style="width:70px;height:40px;object-fit:cover;border-radius:4px;flex-shrink:0;background:#141414;" '
        + 'onerror="this.onerror=null;this.src=\'' + coverUrl + '\';" />'
        + '<span style="flex:1;min-width:0;font-size:0.8rem;font-weight:600;color:#f4f4f5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(nm) + '">' + titleHtml + '</span>'
        + '<span style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0;"><span class="slicer-te" style="font-size:0.65rem;color:#a1a1aa;font-family:monospace;white-space:nowrap;"></span><span style="display:flex;align-items:center;gap:6px;flex-shrink:0;">' + ctrls + '</span></span>'
        + '</div>';
      }
      html += '</div>';
      openModal('Episode Slicer · ' + (itemData.title || itemId), html, function(body, close) {
        // Estado "trabajando": línea con puntos animados (sin CSS keyframes,
        // TV-safe) + botones desactivados. Las operaciones (preview/split/
        // unsplit/resync) tardan segundos por el sync a central.
        var busyTimer = null;
        function setBusy(msg) {
          var st = body.querySelector('[data-slicer-status]');
          if (!st) {
            st = document.createElement('div');
            st.setAttribute('data-slicer-status', '1');
            st.style.cssText = 'display:none;margin-bottom:10px;background:rgba(168,85,247,0.12);border:1px solid rgba(168,85,247,0.5);border-radius:8px;padding:8px 10px;font-size:0.8rem;color:#e9d5ff;';
            body.insertBefore(st, body.firstChild);
          }
          if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
          var btns = body.querySelectorAll('.slicer-cut, .slicer-unsplit');
          if (!msg) {
            st.style.display = 'none';
            for (var k = 0; k < btns.length; k++) btns[k].style.opacity = '';
            body.style.pointerEvents = '';
            return;
          }
          st.style.display = 'block';
          body.style.pointerEvents = 'none';
          var dots = 0;
          var base = '⏳ ' + msg;
          st.textContent = base;
          busyTimer = setInterval(function() {
            dots = (dots + 1) % 4;
            var d = '';
            for (var i = 0; i < dots; i++) d += '.';
            st.textContent = base + d;
          }, 400);
        }
        var useOrigBox = body.querySelector('.slicer-use-orig');
        try {
          var saved = null;
          try { saved = localStorage.getItem('tvcat_slicer_use_orig_title'); } catch (eLS) {}
          if (useOrigBox) useOrigBox.checked = (saved === null) ? true : (saved === '1');
          if (useOrigBox) useOrigBox.onchange = function() {
            try { localStorage.setItem('tvcat_slicer_use_orig_title', useOrigBox.checked ? '1' : '0'); } catch (eLS2) {}
          };
        } catch (e) {}
        var useOrigTitle = function() {
          try { return !!(useOrigBox && useOrigBox.checked); } catch (e3) { return true; }
        };
        // ---- Multi-corte por temporadas ----
        var getOffset = function() {
          try {
            var v = parseInt(body.querySelector('.slicer-offset').value, 10);
            return (isNaN(v) || v < 1) ? 1 : v;
          } catch (eO) { return 1; }
        };
        var rowState = function() {
          // [{msg, checked, season|null}] en orden de lista (sin la fila 1).
          var out = [];
          var checks = body.querySelectorAll('.slicer-check');
          for (var ri = 0; ri < checks.length; ri++) {
            var c = checks[ri];
            var inp = body.querySelector('.slicer-season[data-msg="' + c.getAttribute('data-msg') + '"]');
            var sv = inp ? parseInt(inp.value, 10) : NaN;
            out.push({ msg: parseInt(c.getAttribute('data-msg'), 10),
              checked: !!c.checked, season: (isNaN(sv) ? null : sv) });
          }
          return out;
        };
        var renumber = function() {
          // Secuencial desde el offset+1: el offset es la temporada del
          // título (primer bloque) y cada check marcado es off+1+k.
          // No toca ediciones manuales (data-manual).
          var off = getOffset(), k = 0;
          var checks = body.querySelectorAll('.slicer-check');
          for (var ni = 0; ni < checks.length; ni++) {
            var inp = body.querySelector('.slicer-season[data-msg="' + checks[ni].getAttribute('data-msg') + '"]');
            if (!inp) continue;
            if (checks[ni].checked && inp.getAttribute('data-manual') !== '1') {
              inp.value = off + 1 + k;
              k++;
            }
          }
        };
        var markManual = function() {
          var inps = body.querySelectorAll('.slicer-season');
          for (var mi = 0; mi < inps.length; mi++) {
            (function(inp) {
              inp.onchange = function() { inp.setAttribute('data-manual', '1'); };
            })(inps[mi]);
          }
        };
        markManual();
        // Indicador T/E por fila: temporada resultante + episodio dentro de
        // ella. Base = temporada del título (si se detectó) u offset.
        var pad3 = function(v) { v = String(v); while (v.length < 3) v = '0' + v; return v; };
        var updateTE = function() {
          try {
            var base = (titleSeason !== null && titleSeason !== undefined) ? titleSeason : getOffset();
            if (!(base >= 1)) base = 1;
            var rows = body.querySelectorAll('.slicer-row');
            var block = 0, e = 0;
            for (var ri = 0; ri < rows.length; ri++) {
              var cb = rows[ri].querySelector('.slicer-check');
              if (ri > 0 && cb && cb.checked) { block++; e = 0; }
              e++;
              var te = rows[ri].querySelector('.slicer-te');
              if (te) te.textContent = 'T=' + pad3(base + block) + ' E=' + pad3(e);
            }
          } catch (eT) {}
        };
        updateTE();
        // Marcar/desmarcar a mano asigna/limpia número (sin tocar al resto).
        try {
          var checksAll = body.querySelectorAll('.slicer-check');
          for (var ha = 0; ha < checksAll.length; ha++) {
            (function(c) {
              c.onchange = function() {
                var inp = body.querySelector('.slicer-season[data-msg="' + c.getAttribute('data-msg') + '"]');
                if (!inp) return;
                if (c.checked) {
                  if (!inp.value) renumber();
                } else {
                  inp.value = '';
                  inp.removeAttribute('data-manual');
                }
                updateTE();
              };
            })(checksAll[ha]);
          }
        } catch (eHa) {}
        try {
          body.querySelector('.slicer-offset').onchange = function() {
            // Al cambiar el offset se recalcula todo (pierde ediciones manuales).
            var inps = body.querySelectorAll('.slicer-season');
            for (var ci = 0; ci < inps.length; ci++) inps[ci].removeAttribute('data-manual');
            renumber();
            updateTE();
          };
        } catch (eOff) {}
        var masters = body.querySelectorAll('.slicer-master');
        for (var mi2 = 0; mi2 < masters.length; mi2++) {
          (function(btn) {
              btn.onclick = function() {
              var on = btn.getAttribute('data-on') === '1';
              var checks = body.querySelectorAll('.slicer-check');
              for (var ci = 0; ci < checks.length; ci++) checks[ci].checked = on;
              renumber();
              updateTE();
            };
          })(masters[mi2]);
        }
        try {
          body.querySelector('.slicer-auto').onclick = function() {
            // Solo marca inicios de temporada (familia consenso); no corta.
            var off = getOffset(), marked = 0, prevS = null, first = true;
            var checks = body.querySelectorAll('.slicer-check');
            // Mapa msg -> episodio para detectar.
            var byMsg = {};
            for (var bi = 0; bi < eps.length; bi++) byMsg[String(eps[bi].telegram_msg_id)] = eps[bi];
            for (var ci = 0; ci < checks.length; ci++) {
              var c = checks[ci];
              var ep = byMsg[c.getAttribute('data-msg')] || {};
              var d = detectSeasonEp(ep.file_name || ep.title || '');
              if (d && (!fam || d.fam === fam)) {
                // La temporada del propio título no se marca: el corte
                // empezaría dentro de ella. Solo cambios posteriores.
                if ((first || d.s !== prevS) && (titleSeason === null || d.s !== titleSeason)) {
                  c.checked = true;
                  marked++;
                } else {
                  c.checked = false;
                }
                prevS = d.s;
                first = false;
              } else {
                c.checked = false;
              }
            }
            void off;
            renumber();
            updateTE();
            toast(marked ? ('Auto: ' + marked + ' inicios marcados') : 'Auto: sin patrón de temporada');
          };
        } catch (eAuto) {}
        var runBatch = function(mode) {
          var rows = rowState();
          var cuts = [];
          for (var ci = 0; ci < rows.length; ci++) {
            if (rows[ci].checked && rows[ci].msg > 0) {
              cuts.push({ from_msg_id: rows[ci].msg, season: rows[ci].season });
            }
          }
          if (!cuts.length) { toast('Marca al menos un corte'); return; }
          cuts.sort(function(a, b) { return a.from_msg_id - b.from_msg_id; });
          // Preview local: título + nº eps por trozo.
          var byMsg2 = {};
          for (var bi = 0; bi < eps.length; bi++) byMsg2[String(eps[bi].telegram_msg_id)] = eps[bi];
          var lines = [], startIdx = 0;
          var msgOrder = [];
          for (var oi = 0; oi < eps.length; oi++) msgOrder.push(parseInt(eps[oi].telegram_msg_id, 10));
          for (var pi = 0; pi < cuts.length; pi++) {
            var fromIdx = msgOrder.indexOf(cuts[pi].from_msg_id);
            if (fromIdx < 0) continue;
            var nextFrom = (pi + 1 < cuts.length) ? msgOrder.indexOf(cuts[pi + 1].from_msg_id) : eps.length;
            if (nextFrom < 0) nextFrom = eps.length;
            var cnt = nextFrom - fromIdx;
            var nm;
            if (mode === 'season' && cuts[pi].season !== null) {
              nm = (itemData.title || itemId) + ' - Season ' + cuts[pi].season;
            } else {
              var f0 = byMsg2[String(cuts[pi].from_msg_id)] || {};
              var stem = String(f0.file_name || f0.title || 'Corte').replace(/\.[^.]+$/, '');
              nm = stem.slice(0, 80);
            }
            lines.push('· "' + nm + '" (' + cnt + ' eps)');
          }
          if (!lines.length) { toast('Cortes inválidos'); return; }
          var ok = confirm('Crear ' + lines.length + ' título(s) [modo ' + mode + ']:\n' + lines.join('\n'));
          if (!ok) return;
          setBusy('Cortando ' + lines.length + ' parte(s) y sincronizando');
          ajax(API + '/batch', { method: 'POST', data: { item_id: itemId, cuts: cuts, mode: mode, use_orig_title: useOrigTitle() } }, function(eB, res) {
            setBusy(null);
            if (eB) { toast('Batch falló: ' + (eB.message || eB)); return; }
            var parts = (res && res.parts) || [];
            close();
            refreshAfterSplit(itemId, parts.length ? parts[parts.length - 1].new_item_id : null);
            var msg = 'Creados ' + parts.length + ' título(s)' + (((res && res.central_refreshed) === false) ? ' (central pendiente: usa Re-sincronizar)' : '');
            toast(msg);
          });
        };
        try {
          body.querySelector('.slicer-goslice').onclick = function() { runBatch('slice'); };
          body.querySelector('.slicer-goseason').onclick = function() { runBatch('season'); };
        } catch (eGo) {}
        // ---- Editor de episodios por temporada (conteos + autofill TMDB) ----
        var openEpEditor = function() {
          var ov2 = document.createElement('div');
          ov2.setAttribute('style', 'position:fixed;top:0;right:0;bottom:0;left:0;background:rgba(0,0,0,0.7);z-index:1000000;');
          ov2.onclick = function(e) { if (e.target === ov2) { try { document.body.removeChild(ov2); } catch (ex) {} } };
          var panel2 = document.createElement('div');
          panel2.setAttribute('style', 'position:fixed;top:8%;left:0;right:0;margin:0 auto;width:440px;max-width:92%;box-sizing:border-box;max-height:80%;overflow:auto;background:#18181b;color:#f4f4f5;border:1px solid #333;border-radius:10px;padding:16px;');
          var h2 = document.createElement('h3');
          h2.appendChild(document.createTextNode('Editor de episodios'));
          var x2 = document.createElement('button');
          x2.appendChild(document.createTextNode('X'));
          x2.setAttribute('style', 'float:right;width:32px;height:32px;background:#333;color:#fff;border:1px solid #555;border-radius:8px;');
          x2.onclick = function() { try { document.body.removeChild(ov2); } catch (ex) {} };
          panel2.appendChild(x2);
          panel2.appendChild(h2);
          var info = document.createElement('p');
          info.style.cssText = 'font-size:0.75rem;color:#a1a1aa;';
          info.textContent = 'Una línea por temporada = nº de episodios. Se marcan los inicios (reemplaza los checks).';
          panel2.appendChild(info);
          var rowTop = document.createElement('div');
          rowTop.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;';
          var lblS = document.createElement('label');
          lblS.style.cssText = 'font-size:0.75rem;color:#a1a1aa;';
          lblS.textContent = 'Temporada inicial:';
          var inpS = document.createElement('input');
          inpS.type = 'number'; inpS.min = '0'; inpS.value = String(getOffset());
          inpS.style.cssText = 'width:64px;background:#0a0a0c;border:1px solid #3f3f46;border-radius:4px;padding:4px 6px;color:#f4f4f5;font-size:0.8rem;';
          var btnGet = document.createElement('button');
          btnGet.textContent = 'Obtener episodios';
          btnGet.style.cssText = 'background:#0e7490;border:none;border-radius:6px;padding:6px 10px;color:#fff;font-size:0.75rem;cursor:pointer;display:none;';
          rowTop.appendChild(lblS); rowTop.appendChild(inpS); rowTop.appendChild(btnGet);
          panel2.appendChild(rowTop);
          var found = document.createElement('div');
          found.style.cssText = 'font-size:0.75rem;color:#a1a1aa;margin-bottom:8px;display:none;';
          panel2.appendChild(found);
          var ta = document.createElement('textarea');
          ta.rows = 8;
          ta.placeholder = '15\n20\n18\n22';
          ta.style.cssText = 'width:100%;box-sizing:border-box;background:#0a0a0c;border:1px solid #3f3f46;border-radius:6px;padding:8px;color:#f4f4f5;font-size:0.8rem;font-family:monospace;';
          panel2.appendChild(ta);
          var rowBtn = document.createElement('div');
          rowBtn.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:10px;';
          var btnCancel = document.createElement('button');
          btnCancel.textContent = 'Cancelar';
          btnCancel.style.cssText = 'background:#27272a;border:1px solid #3f3f46;border-radius:6px;padding:6px 12px;color:#f4f4f5;font-size:0.8rem;cursor:pointer;';
          btnCancel.onclick = function() { try { document.body.removeChild(ov2); } catch (ex) {} };
          var btnApply = document.createElement('button');
          btnApply.textContent = 'Aplicar';
          btnApply.style.cssText = 'background:#22c55e;border:none;border-radius:6px;padding:6px 12px;color:#fff;font-weight:700;font-size:0.8rem;cursor:pointer;';
          rowBtn.appendChild(btnCancel); rowBtn.appendChild(btnApply);
          panel2.appendChild(rowBtn);
          ov2.appendChild(panel2);
          document.body.appendChild(ov2);
          ajax(API + '/tmdb-status', { method: 'GET' }, function(eS, rS) {
            if (!eS && rS && rS.has_key) {
              btnGet.style.display = '';
              // Con API key: obtener automáticamente al abrir (temporada
              // inicial = inicio de secuencia). El botón reintenta si se edita.
              doFetch();
            }
          });
          var doFetch = function() {
            var sv = parseInt(inpS.value, 10);
            if (isNaN(sv) || sv < 0) sv = getOffset();
            found.style.display = 'none';
            btnGet.textContent = 'Buscando…';
            ajax(API + '/tmdb-seasons', { method: 'POST', data: { title: (itemData.title || itemId), from_season: sv } }, function(eT, rT) {
              btnGet.textContent = 'Obtener episodios';
              if (eT) { found.style.display = 'block'; found.textContent = 'TMDB: ' + (eT.message || eT); return; }
              var seasons = (rT && rT.seasons) || [];
              if (!seasons.length) { found.style.display = 'block'; found.textContent = 'TMDB: sin temporadas desde ' + sv; return; }
              var lines = [];
              for (var si = 0; si < seasons.length; si++) lines.push(String(seasons[si].episodes));
              ta.value = lines.join('\n');
              var sr = (rT.series || {});
              found.style.display = 'block';
              found.textContent = 'TMDB: ' + (sr.title || '') + (sr.year ? ' (' + sr.year + ')' : '') + ' · T' + sv + '–T' + (sv + seasons.length - 1);
            });
          };
          btnGet.onclick = function() { doFetch(); };
          btnApply.onclick = function() {
            var counts = [];
            var rawLines = String(ta.value || '').split('\n');
            for (var li = 0; li < rawLines.length; li++) {
              var nv = parseInt(String(rawLines[li]).trim(), 10);
              if (!isNaN(nv) && nv > 0) counts.push(nv);
            }
            var checks = body.querySelectorAll('.slicer-check');
            var inps = body.querySelectorAll('.slicer-season');
            for (var ci = 0; ci < checks.length; ci++) checks[ci].checked = false;
            for (var cj = 0; cj < inps.length; cj++) { inps[cj].value = ''; inps[cj].removeAttribute('data-manual'); }
            var cum = 0;
            for (var ck = 0; ck < counts.length; ck++) {
              cum += counts[ck];
              // checks[ci] ↔ eps[ci+1]: el inicio en eps[cum] es checks[cum-1].
              // Si excede el total, se deja de marcar (el resto = última temporada).
              if (cum >= 1 && cum < eps.length && checks[cum - 1]) checks[cum - 1].checked = true;
            }
            renumber();
            updateTE();
            try { document.body.removeChild(ov2); } catch (ex) {}
            toast('Editor: checks aplicados');
          };
        };
        try {
          var epEdBtn = body.querySelector('.slicer-epeditor');
          if (epEdBtn) epEdBtn.onclick = function() { openEpEditor(); };
        } catch (eEp) {}
        // ---- Tijera por fila: cortar aquí y mover a título nuevo ----
        try {
          var cutones = body.querySelectorAll('.slicer-cutone');
          for (var co = 0; co < cutones.length; co++) {
            (function(btn) {
              btn.onclick = function() {
                var idx = parseInt(btn.getAttribute('data-idx'), 10);
                var msg = parseInt(btn.getAttribute('data-msg'), 10);
                if (isNaN(idx) || idx < 1 || !msg) return;
                var fromN = idx + 1, toN = eps.length;
                if (!confirm('¿Cortar aquí y mover ' + fromN + '..' + toN + ' a un título nuevo?')) return;
                setBusy('Generando vista previa');
                ajax(API + '/preview', { method: 'POST', data: { item_id: itemId, from_msg_id: msg, use_orig_title: useOrigTitle() } }, function(e2, prev) {
                  setBusy(null);
                  if (e2) { toast('Preview falló: ' + (e2.message || e2)); return; }
                  var newName = (prev && prev.new && prev.new.title) || 'nuevo título';
                  var newCnt = (prev && prev.new && prev.new.count) || (toN - fromN + 1);
                  var keepCnt = (prev && prev.orig && prev.orig.keep) || (fromN - 1);
                  if (!confirm('Crear "' + newName + '" con ' + newCnt + ' episodios?\nOriginal queda con ' + keepCnt + '.')) return;
                  setBusy('Cortando y sincronizando (puede tardar unos segundos)');
                  ajax(API + '/split', { method: 'POST', data: { item_id: itemId, from_msg_id: msg, use_orig_title: useOrigTitle() } }, function(e3, res) {
                    setBusy(null);
                    if (e3) { toast('Split falló: ' + (e3.message || e3)); return; }
                    var nid = (res && res.new_item_id) || null;
                    var afterSplit = function() {
                      close();
                      try { openSlicerModal({ item_id: itemId, title: (itemData.title || itemId) }); } catch (eR) {}
                      refreshAfterSplit(itemId, nid);
                      toast('Corte creado: ' + newName);
                    };
                    if (res && res.central_refreshed === false) {
                      ajax(API + '/resync', { method: 'POST', data: {} }, function() { afterSplit(); });
                    } else {
                      afterSplit();
                    }
                  });
                });
              };
            })(cutones[co]);
          }
        } catch (eCut1) {}
        // ---- Unir con el trozo siguiente (el hijo vuelve a este título) ----
        try {
          var unNext = body.querySelector('.slicer-unsplit-next');
          if (unNext) unNext.onclick = function() {
            var nid2 = unNext.getAttribute('data-id');
            var nname = unNext.getAttribute('data-name') || nid2;
            if (!nid2) return;
            if (!confirm('Unir "' + nname + '" con este título?\nLos episodios vuelven aquí.')) return;
            setBusy('Uniendo y sincronizando (puede tardar unos segundos)');
            ajax(API + '/unsplit', { method: 'POST', data: { new_item_id: nid2 } }, function(eU, res) {
              setBusy(null);
              if (eU) { toast('Unir falló: ' + (eU.message || eU)); return; }
              close();
              try { openSlicerModal({ item_id: itemId, title: (itemData.title || itemId) }); } catch (eR3) {}
              refreshAfterSplit(itemId, null);
              toast('Unido con ' + nname);
            });
          };
        } catch (eUn2) {}
        var btns = body.querySelectorAll('.slicer-cut[data-cut]');
        for (var k = 0; k < btns.length; k++) {
          (function(btn) {
            btn.onclick = function(ev) {
              if (ev && ev.stopPropagation) { ev.stopPropagation(); }
              var fromMsg = parseInt(btn.getAttribute('data-cut'), 10);
              // La lista fusiona variantes: cortar sobre el título REAL del episodio,
              // no sobre el mostrado (si no, el msg no existe ahí → 400).
              var realItem = btn.getAttribute('data-item') || itemId;
              setBusy('Generando vista previa');
              ajax(API + '/preview', { method: 'POST', data: { item_id: realItem, from_msg_id: fromMsg, use_orig_title: useOrigTitle() } }, function(e2, prev) {
                setBusy(null);
                if (e2) { toast('Preview falló: ' + (e2.message || e2)); return; }
                var warnTxt = '';
                try {
                  var _wl = (prev && prev.local_edit_warnings) || [];
                  if (_wl.length) {
                    warnTxt = '\n\n⚠️ Estos episodios tienen ediciones locales:';
                    for (var _wi = 0; _wi < _wl.length; _wi++) {
                      warnTxt += '\n· msg ' + _wl[_wi].msg_id + ' (' + (_wl[_wi].title || _wl[_wi].item_id || '?') + ')';
                    }
                    warnTxt += '\nSi cortas, esas copias quedarán huérfanas (límpialas en Ediciones locales).';
                  }
                } catch (eW) {}
                var ok = confirm('Crear "' + prev.new.title + '" con ' + prev.new.count + ' episodios?\nOriginal queda con ' + prev.orig.keep + '.' + warnTxt);
                if (!ok) return;
                setBusy('Cortando y sincronizando (puede tardar unos segundos)');
                ajax(API + '/split', { method: 'POST', data: { item_id: realItem, from_msg_id: fromMsg, use_orig_title: useOrigTitle() } }, function(e3, res) {
                  if (e3) { toast('Split falló: ' + (e3.message || e3)); return; }
                  var nid = (res && res.new_item_id) || null;
                  var newName = (prev && prev.new && prev.new.title) || nid || 'nuevo título';
                  var finish = function(centralOk) {
                    if (!centralOk) {
                      // Sin pregunta inútil: el item no cargaría en el editor.
                      toast('Corte guardado pero la central no se actualizó (ver log gateway). Reintenta desde Unir/Re-sincronizar más tarde.');
                      close();
                      refreshAfterSplit(realItem, nid);
                      return;
                    }
                    // Única pregunta: ¿editar el título recién generado?
                    var edit = confirm('Corte creado: "' + newName + '"\n¿Editar el nuevo título ahora?');
                    close();
                    refreshAfterSplit(realItem, nid);
                    if (edit) {
                      setTimeout(function() {
                        try {
                          if (window.Enricher && window.Enricher.open) window.Enricher.open({ item_id: nid, title: newName });
                          else toast('Editor no disponible');
                        } catch (eE) { toast('No se pudo abrir el editor'); }
                      }, 300);
                    } else {
                      toast('Corte creado: ' + nid + ' (' + ((prev && prev.new && prev.new.count) || '?') + ' eps)');
                    }
                  };
                  if (res && res.central_refreshed === false) {
                    // Sin mensaje intermedio: reintento directo y se sigue.
                    ajax(API + '/resync', { method: 'POST', data: {} }, function(e4, rr) {
                      finish(!!(rr && rr.ok));
                    });
                  } else {
                    finish(true);
                  }
                });
              });
            };
          })(btns[k]);
        }
        var un = body.querySelector('.slicer-unsplit');
        if (un) un.onclick = function() {
          var origId = (cut && cut.orig_item_id) || null;
          var origName = (cut && (cut.orig_title || cut.orig_item_id)) || 'el original';
          if (!confirm('Unir esta parte con "' + origName + '"?\nLos episodios vuelven al título original.')) return;
          setBusy('Uniendo y sincronizando (puede tardar unos segundos)');
          ajax(API + '/unsplit', { method: 'POST', data: { new_item_id: itemId } }, function(eU, res) {
            setBusy(null);
            if (eU) { toast('Unir falló: ' + (eU.message || eU)); return; }
            close();
            // Recarga completa como tras el split (si no, la parte unida sigue visible).
            refreshAfterSplit(origId || itemId, itemId);
            // Ir al hero del título destino: la parte ya no existe.
            setTimeout(function() {
              try { if (origId && window.openDetails) window.openDetails(origId); } catch (eO) {}
            }, 400);
            if (res.central_refreshed === false) {
              toast('Unido pero la central no se actualizó (ver log gateway).');
              return;
            }
            var edit = confirm('Unido con "' + origName + '" (' + (res.restored || 0) + ' episodios).\n¿Editar el título unido ahora?');
            if (edit) {
              setTimeout(function() {
                try {
                  if (window.Enricher && window.Enricher.open) window.Enricher.open({ item_id: origId, title: origName });
                  else toast('Editor no disponible');
                } catch (eE) { toast('No se pudo abrir el editor'); }
              }, 600);
            } else {
              toast('Unido con ' + origName);
            }
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
