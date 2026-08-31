(function() {
var PRO_DEBUG = true;
function log() { if (PRO_DEBUG) console.log.apply(console, ['[PRO2]'].concat(Array.prototype.slice.call(arguments))); }

function getSetting(key, def) {
    var v = localStorage.getItem('tvcat_player_pro2_' + key);
    if (v !== null) return JSON.parse(v);
    if (key === 'cache_size_gb') {
        var g = localStorage.getItem('tvcat_cache_max_size_gb');
        if (g !== null) return JSON.parse(g);
    }
    return def;
}

// Añadir ?chunk=KB al stream (tamaño de búfer configurado en Pantalla)
function addChunkParam(url) {
    var chunk = localStorage.getItem('tvcat_download_chunk_size');
    if (chunk && url.indexOf('chunk=') < 0) {
        var sep = url.indexOf('?') >= 0 ? '&' : '?';
        return url + sep + 'chunk=' + chunk;
    }
    return url;
}

// ===== Constants =====
var CHUNK_SIZE = 1024 * 1024;  // 1MB
var MAX_PARALLEL = 2;
var DB_NAME = 'tvcat_player_pro_cache';
var DB_VERSION = 1;
var CHUNK_STORE = 'chunks';
var META_STORE = 'meta';

// ===== IndexedDB (CacheDB) =====
var CacheDB = {
    _db: null, _pending: null,
    open: function() {
        var self = this;
        if (self._db) return Promise.resolve(self._db);
        if (self._pending) return self._pending;
        self._pending = new Promise(function(resolve, reject) {
            var req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = function(e) {
                var db = e.target.result;
                if (!db.objectStoreNames.contains(CHUNK_STORE)) {
                    var cs = db.createObjectStore(CHUNK_STORE, { keyPath: ['episode_id', 'chunk_index'] });
                    cs.createIndex('episode_id', 'episode_id', { unique: false });
                    cs.createIndex('timestamp', 'timestamp', { unique: false });
                }
                if (!db.objectStoreNames.contains(META_STORE)) {
                    db.createObjectStore(META_STORE, { keyPath: 'key' });
                }
            };
            req.onsuccess = function(e) { self._db = e.target.result; resolve(self._db); };
            req.onerror = function(e) { reject(e.target.error); };
        });
        return self._pending;
    },
    getChunk: function(episodeId, chunkIndex) {
        return this.open().then(function(db) {
            return new Promise(function(resolve, reject) {
                var tx = db.transaction(CHUNK_STORE, 'readonly');
                var req = tx.objectStore(CHUNK_STORE).get([episodeId, chunkIndex]);
                req.onsuccess = function(e) { resolve(e.target.result ? e.target.result.data : null); };
                req.onerror = function(e) { reject(e.target.error); };
            });
        });
    },
    putChunk: function(episodeId, chunkIndex, data) {
        return this.open().then(function(db) {
            return new Promise(function(resolve, reject) {
                var tx = db.transaction([CHUNK_STORE, META_STORE], 'readwrite');
                tx.objectStore(CHUNK_STORE).put({ episode_id: episodeId, chunk_index: chunkIndex, data: data, timestamp: Date.now(), size: data.byteLength });
                var metaStore = tx.objectStore(META_STORE);
                var getReq = metaStore.get('_total_size');
                getReq.onsuccess = function(e) {
                    var current = e.target.result ? e.target.result.value : 0;
                    metaStore.put({ key: '_total_size', value: current + data.byteLength });
                };
                tx.oncomplete = function() { resolve(); };
                tx.onerror = function(e) { reject(e.target.error); };
            });
        });
    },
    getEpisodeChunks: function(episodeId) {
        return this.open().then(function(db) {
            return new Promise(function(resolve, reject) {
                var tx = db.transaction(CHUNK_STORE, 'readonly');
                var index = tx.objectStore(CHUNK_STORE).index('episode_id');
                var range = IDBKeyRange.only(episodeId);
                var req = index.openCursor(range);
                var chunks = [];
                req.onsuccess = function(e) {
                    var cursor = e.target.result;
                    if (cursor) { chunks.push(cursor.value.chunk_index); cursor.continue(); }
                    else resolve(chunks);
                };
                req.onerror = function(e) { reject(e.target.error); };
            });
        });
    },
    deleteEpisode: function(episodeId) {
        return this.open().then(function(db) {
            return new Promise(function(resolve, reject) {
                var tx = db.transaction([CHUNK_STORE, META_STORE], 'readwrite');
                var store = tx.objectStore(CHUNK_STORE);
                var metaStore = tx.objectStore(META_STORE);
                var range = IDBKeyRange.only(episodeId);
                var req = store.index('episode_id').openCursor(range);
                var deletedSize = 0;
                req.onsuccess = function(e) {
                    var cursor = e.target.result;
                    if (cursor) {
                        deletedSize += cursor.value.size || 0;
                        store.delete(cursor.primaryKey);
                        cursor.continue();
                    } else {
                        if (deletedSize > 0) {
                            var getReq = metaStore.get('_total_size');
                            getReq.onsuccess = function(e2) {
                                var current = e2.target.result ? e2.target.result.value : 0;
                                metaStore.put({ key: '_total_size', value: Math.max(0, current - deletedSize) });
                            };
                        }
                        resolve();
                    }
                };
                req.onerror = function(e) { reject(e.target.error); };
            });
        });
    },
    clearAll: function() {
        return this.open().then(function(db) {
            var tx = db.transaction([CHUNK_STORE, META_STORE], 'readwrite');
            var p1 = new Promise(function(resolve, reject) {
                var req = tx.objectStore(CHUNK_STORE).clear();
                req.onsuccess = function() { resolve(); };
                req.onerror = function(e) { reject(e.target.error); };
            });
            var p2 = new Promise(function(resolve, reject) {
                var req = tx.objectStore(META_STORE).put({ key: '_total_size', value: 0 });
                req.onsuccess = function() { resolve(); };
                req.onerror = function(e) { reject(e.target.error); };
            });
            return Promise.all([p1, p2]);
        });
    },
    getTotalSize: function() {
        return this.open().then(function(db) {
            return new Promise(function(resolve, reject) {
                var req = db.transaction(META_STORE, 'readonly').objectStore(META_STORE).get('_total_size');
                req.onsuccess = function(e) { resolve(e.target.result ? e.target.result.value : 0); };
                req.onerror = function(e) { reject(e.target.error); };
            });
        });
    },
    evictLRU: function(targetBytes) {
        return this.open().then(function(db) {
            return new Promise(function(resolve, reject) {
                var tx = db.transaction(CHUNK_STORE, 'readwrite');
                var store = tx.objectStore(CHUNK_STORE);
                var req = store.index('timestamp').openCursor(null, 'next');
                var deleted = 0;
                req.onsuccess = function(e) {
                    var cursor = e.target.result;
                    if (!cursor || deleted >= targetBytes) { resolve(deleted); return; }
                    store.delete(cursor.primaryKey);
                    deleted += cursor.value.size || 0;
                    cursor.continue();
                };
                req.onerror = function(e) { reject(e.target.error); };
            });
        });
    },
    putMeta: function(key, value) {
        return this.open().then(function(db) {
            return new Promise(function(resolve, reject) {
                var tx = db.transaction(META_STORE, 'readwrite');
                var req = tx.objectStore(META_STORE).put({ key: key, value: value });
                req.onsuccess = function() { resolve(); };
                req.onerror = function(e) { reject(e.target.error); };
            });
        });
    },
    _ensureCounter: 0,
    ensureSpace: function(neededBytes) {
        this._ensureCounter = (this._ensureCounter || 0) + 1;
        if (this._ensureCounter % 10 !== 0) return Promise.resolve();
        return this.getTotalSize().then(function(total) {
            var maxBytes = getSetting('cache_size_gb', 5) * 1024 * 1024 * 1024;
            var overflow = (total + neededBytes) - maxBytes;
            if (overflow > 0) return CacheDB.evictLRU(overflow + neededBytes);
        });
    }
};

// ===== UI Mode detection (same as before) =====
function getUIMode() {
    var mode = getSetting('ui_mode', 'auto');
    if (mode !== 'auto') return mode;
    var ua = navigator.userAgent;
    var isSmartTV = /Tizen|WebOS|SmartTV|Android TV|SamsungBrowser|NetCast|Opera TV|CE-HTML/i.test(ua);
    var isOldSmartTV = isSmartTV && (/NetCast|Opera TV|CE-HTML|Tizen [123]\./i.test(ua) || (/WebOS/i.test(ua) && /Web0S\/[123]\./i.test(ua)));
    if (isOldSmartTV) return 'basic';
    if (isSmartTV || typeof Plyr === 'undefined') return 'native';
    return 'plyr';
}

// ===== Background Cache =====
function BackgroundCache(url, episodeId, fileSize) {
    this.url = url;
    this.episodeId = episodeId;
    this.fileSize = fileSize || 0;
    this.totalChunks = fileSize > 0 ? Math.ceil(fileSize / CHUNK_SIZE) : Infinity;
    this.stopped = false;
    this.nextIndex = 0;
    this.cachedSet = {};
    this.cachedRanges = [];
    this.onProgress = null;
    this.onChunk = null;
    this._fetching = false;
    this._inFlight = 0;
    this._completeStrategy = getSetting('cache_strategy', 'forward');
    this._completed = false;
    this._abortController = null;
    this._generation = 0;
}
BackgroundCache.prototype.loadCached = function() {
    var self = this;
    return CacheDB.getEpisodeChunks(this.episodeId).then(function(chunks) {
        for (var i = 0; i < chunks.length; i++) self.cachedSet[chunks[i]] = true;
        chunks.sort(function(a, b) { return a - b; });
        self._rebuildRanges(chunks);
        log('Cargados ' + chunks.length + ' chunks cacheados previos');
    });
};
BackgroundCache.prototype._rebuildRanges = function(chunks) {
    this.cachedRanges = [];
    if (chunks.length === 0) return;
    var start = chunks[0], end = chunks[0];
    for (var i = 1; i < chunks.length; i++) {
        if (chunks[i] === end + 1) { end = chunks[i]; }
        else { this.cachedRanges.push([start, end]); start = chunks[i]; end = chunks[i]; }
    }
    this.cachedRanges.push([start, end]);
};
BackgroundCache.prototype._addChunkToRanges = function(idx) {
    // Insert idx into the sorted ranges
    for (var i = 0; i < this.cachedRanges.length; i++) {
        var r = this.cachedRanges[i];
        if (idx >= r[0] && idx <= r[1]) return; // already covered
        if (idx === r[1] + 1) { r[1] = idx; this._mergeRanges(i); return; }
        if (idx === r[0] - 1) { r[0] = idx; this._mergeRanges(i - 1); return; }
        if (idx < r[0]) { this.cachedRanges.splice(i, 0, [idx, idx]); return; }
    }
    this.cachedRanges.push([idx, idx]);
};
BackgroundCache.prototype._mergeRanges = function(i) {
    if (i < 0 || i >= this.cachedRanges.length - 1) return;
    var a = this.cachedRanges[i], b = this.cachedRanges[i + 1];
    if (a[1] + 1 >= b[0]) { a[1] = b[1]; this.cachedRanges.splice(i + 1, 1); }
};
BackgroundCache.prototype.start = function(fromChunk) {
    var self = this;
    if (this._abortController) { this._abortController.abort(); }
    this._abortController = new AbortController();
    this._generation++;
    this.nextIndex = fromChunk || 0;
    this.stopped = false;
    this._completed = false;
    this._fetching = false;
    this._inFlight = 0;
    this.loadCached().then(function() {
        self._reportProgress();
        if (!self.stopped) self._fetchLoop();
    });
};
BackgroundCache.prototype.restartFrom = function(chunkIndex) {
    if (this.stopped || chunkIndex < 0) return;
    log('Restart cache from chunk', chunkIndex);
    this.nextIndex = chunkIndex;
    this._completed = false;
    this._fetching = false;
    // No abortamos fetchs en curso — solo 1MB c/u, terminan rapido.
    // Cuando terminen, _fetchLoop usara el nuevo nextIndex.
    if (this._inFlight === 0 && !this.stopped) this._fetchLoop();
};
BackgroundCache.prototype.stop = function() {
    this.stopped = true;
    this._fetching = false;
    if (this._abortController) { this._abortController.abort(); this._abortController = null; }
};
BackgroundCache.prototype._fetchLoop = function() {
    if (this.stopped) return;
    while (this._inFlight < MAX_PARALLEL) {
        // Saltar chunks ya cacheados
        while (this.nextIndex < (this.totalChunks || Infinity) && this.cachedSet[this.nextIndex]) {
            this.nextIndex++;
        }
        if (this.totalChunks > 0 && this.isFiniteTotal() && this.nextIndex >= this.totalChunks) {
            if (this._inFlight === 0) {
                log('Descarga completa (forward)');
                this._reportProgress();
                this._completed = true;
                this._fillMissing();
            } else {
                log('Esperando', this._inFlight, 'vuelos pendientes antes de completar');
            }
            return;
        }
        this._fetchNext();
    }
};
BackgroundCache.prototype._fetchNext = function() {
    var self = this;
    if (this.stopped) return;
    var gen = this._generation;
    var signal = this._abortController ? this._abortController.signal : null;
    var idx = this.nextIndex;
    this.nextIndex = idx + 1;
    this._inFlight++;
    var start = idx * CHUNK_SIZE;
    var end = (this.totalChunks > 0 && this.isFiniteTotal()) ? Math.min(start + CHUNK_SIZE - 1, this.fileSize - 1) : start + CHUNK_SIZE - 1;
    log('Fetch chunk', idx, 'bytes', start + '-' + end, 'totalChunks', this.totalChunks, 'inFlight:', this._inFlight);
    var opts = { headers: { 'Range': 'bytes=' + start + '-' + end } };
    if (signal) opts.signal = signal;
    fetch(addChunkParam(this.url), opts).then(function(res) {
        if (gen !== self._generation) return;
        if (!self.fileSize && res.status === 206) {
            var cr = res.headers.get('Content-Range');
            log('Content-Range:', cr);
            if (cr) {
                var m = cr.match(/\/(\d+)/);
                if (m) { self.fileSize = parseInt(m[1], 10); self.totalChunks = Math.ceil(self.fileSize / CHUNK_SIZE); log('FileSize detected:', self.fileSize, 'totalChunks:', self.totalChunks); }
                else {
                    var em = cr.match(/bytes\s+\d+-(\d+)/);
                    if (em) { self.fileSize = parseInt(em[1], 10) + 1; self.totalChunks = Math.ceil(self.fileSize / CHUNK_SIZE); log('FileSize estimated:', self.fileSize); }
                }
            }
        }
        // Store file_size in IDB meta so SW can use it
        if (self.fileSize && !self._fileSizeStored) {
            self._fileSizeStored = true;
            CacheDB.putMeta(self.episodeId + ':file_size', self.fileSize);
        }
        return res.arrayBuffer();
    }).then(function(data) {
        if (self.stopped || gen !== self._generation) return;
        log('Chunk', idx, 'descargado:', data.byteLength, 'bytes');
        CacheDB.ensureSpace(data.byteLength).then(function() {
            CacheDB.putChunk(self.episodeId, idx, data).then(function() {
                log('Chunk', idx, 'guardado en IDB');
                if (self.onChunk) self.onChunk(idx, data);
            });
        });
        if (!self.cachedSet[idx]) {
            self.cachedSet[idx] = true;
            self._addChunkToRanges(idx);
        }
        self._inFlight--;
        self._reportProgress();
        if (!self.stopped) self._fetchLoop();
    }).catch(function(err) {
        if (err.name === 'AbortError') { log('Fetch chunk', idx, 'abortado'); self._inFlight--; return; }
        log('Error fetch chunk', idx, ':', err.message);
        self._inFlight--;
        // Retry the same chunk (don't skip forward)
        if (idx < self.nextIndex) self.nextIndex = idx;
        if (!self.stopped) setTimeout(function() { if (!self.stopped && gen === self._generation) self._fetchLoop(); }, 2000);
    });
};
BackgroundCache.prototype.isFiniteTotal = function() {
    return isFinite(this.totalChunks) && this.totalChunks > 0;
};
BackgroundCache.prototype._reportProgress = function() {
    if (this.onProgress) this.onProgress(this.cachedRanges, this.totalChunks, this.fileSize);
};
BackgroundCache.prototype._fillMissing = function() {
    var self = this;
    // Find first gap from 0
    var missing = 0;
    for (var i = 0; i < this.cachedRanges.length; i++) {
        if (this.cachedRanges[i][0] > missing) break;
        missing = this.cachedRanges[i][1] + 1;
    }
    if (this.totalChunks > 0 && missing >= this.totalChunks) {
        log('Caché completa (full)');
        this._completed = true;
        return;
    }
    log('Fill missing from chunk', missing);
    this.nextIndex = missing;
    this._fetching = false;
    this._fetchLoop();
};

// ===== Service Worker Registration =====
function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw-player-pro.js', { scope: '/' }).then(function(reg) {
            log('SW registrado, scope:', reg.scope);
            // Verificar si está controlando la página
            if (!navigator.serviceWorker.controller) {
                log('⚠️ SW registrado PERO NO controla esta página. Recarga la página.');
            } else {
                log('✅ SW controlando página:', navigator.serviceWorker.controller.scriptURL);
            }
        }).catch(function(err) {
            log('❌ SW no disponible (HTTP o safari):', err.message);
        });
        navigator.serviceWorker.addEventListener('controllerchange', function() {
            log('✅ SW ahora controla la página (controllerchange)');
        });
    } else {
        log('❌ SW no soportado por el navegador');
    }
}
try { registerServiceWorker(); } catch(e) { log('Error registro SW:', e.message); }

// ===== Descarga Completa (Tarea 2) =====
// Descarga el fichero en una sola secuencia continua (Range-resume) y guarda en IDB
// por registros de CHUNK_SIZE, reutilizando el mismo store que la tarea 1.
function contiguousChunks(cache) {
    var c = 0;
    while (cache.cachedSet[c]) c++;
    return c;
}

function storeChunkToCache(cache, idx, data) {
    cache.cachedSet[idx] = true;
    cache._addChunkToRanges(idx);
    return CacheDB.putChunk(cache.episodeId, idx, data).then(function() {
        if (cache.onChunk) cache.onChunk(idx, data);
        cache._reportProgress();
    });
}

function finishFullDownload(cache) {
    log('Descarga completa terminada. Chunks contiguos:', contiguousChunks(cache));
    cache._completed = true;
    cache._reportProgress();
}

function startFullDownload(cache, url, startChunk) {
    var byteStart = startChunk * CHUNK_SIZE;
    var fetchUrl = addChunkParam(url);
    log('Full download desde byte ' + byteStart + ' (chunk ' + startChunk + ')');
    var opts = { headers: { 'Range': 'bytes=' + byteStart + '-' } };
    if (_fullDownloadAbort) { try { _fullDownloadAbort.abort(); } catch(e) {} }
    _fullDownloadAbort = new AbortController();
    opts.signal = _fullDownloadAbort.signal;
    fetch(fetchUrl, opts).then(function(res) {
        if (!res.ok) { log('Full download HTTP error:', res.status); throw new Error('HTTP ' + res.status); }
        var cr = res.headers.get('Content-Range');
        if (cr) {
            var m = cr.match(/\/(\d+)/);
            if (m) {
                cache.fileSize = parseInt(m[1], 10);
                cache.totalChunks = Math.ceil(cache.fileSize / CHUNK_SIZE);
                log('Full download: file_size=' + cache.fileSize + ' bytes, totalChunks=' + cache.totalChunks);
            }
        }
        if (!res.body || typeof res.body.getReader !== 'function') {
            // Fallback navegadores antiguos: ArrayBuffer completo
            return res.arrayBuffer().then(function(buf) {
                var data = new Uint8Array(buf);
                var idx = startChunk, offset = 0;
                while (offset < data.length) {
                    var len = Math.min(CHUNK_SIZE, data.length - offset);
                    storeChunkToCache(cache, idx, data.subarray(offset, offset + len));
                    idx++; offset += len;
                }
                finishFullDownload(cache);
            });
        }
        var reader = res.body.getReader();
        var buffer = new Uint8Array(0);
        var chunkIndex = startChunk;
        function pump() {
            return reader.read().then(function(r) {
                if (r.done) {
                    if (buffer.length > 0) storeChunkToCache(cache, chunkIndex, buffer);
                    finishFullDownload(cache);
                    return;
                }
                var merged = new Uint8Array(buffer.length + r.value.length);
                merged.set(buffer);
                merged.set(r.value, buffer.length);
                buffer = merged;
                while (buffer.length >= CHUNK_SIZE) {
                    var slice = new Uint8Array(buffer.subarray(0, CHUNK_SIZE));
                    storeChunkToCache(cache, chunkIndex, slice);
                    chunkIndex++;
                    buffer = buffer.subarray(CHUNK_SIZE);
                }
                return pump();
            });
        }
        return pump();
    }).catch(function(e) {
        if (e && e.name === 'AbortError') { log('Full download abortado'); return; }
        log('Full download error:', e.message);
        // Si falla, reanudar la descarga por chunks desde el siguiente pendiente
        cache.start(contiguousChunks(cache));
    });
}

// Orquestación: tarea 1 (chunks) mide velocidad, calcula N, y al llegar a N
// entrega el control a la tarea 2 (descarga completa en una sola secuencia).
function setupDualDownload(cache, url, episodeId) {
    var MEASURE_CHUNKS = 5;
    var chunkTimes = [];
    var fullStarted = false;
    var P_BYTES = 400 * 1024; // ~0.4 MB/s playback estimado (500MB / 22min)

    var origOnChunk = cache.onChunk || function() {};
    cache.onChunk = function(idx, data) {
        origOnChunk(idx, data);
        chunkTimes.push({ idx: idx, t: Date.now() });
        if (fullStarted || chunkTimes.length < MEASURE_CHUNKS) return;
        var first = chunkTimes[0], last = chunkTimes[chunkTimes.length - 1];
        var elapsed = (last.t - first.t) / 1000;
        var bytes = Math.max(1, (chunkTimes.length - 1)) * CHUNK_SIZE;
        var R = elapsed > 0 ? bytes / elapsed : 0; // bytes/seg
        var S = cache.fileSize || 0;
        var N = 10;
        if (R > 0 && S > 0) {
            N = Math.ceil(S * P_BYTES / (R + P_BYTES) * 1.5);
            N = Math.max(10, Math.min(100, N));
        }
        log('R=' + (R/1048576).toFixed(2) + ' MB/s, S=' + (S/1048576).toFixed(1) + ' MB, N=' + N + ' chunks');
        // Esperar hasta tener N chunks contiguos y luego entregar a tarea 2
        var check = function() {
            if (fullStarted || cache.stopped) return;
            var c = contiguousChunks(cache);
            var total = cache.totalChunks || Infinity;
            if (c >= total) {
                log('Fichero ya completo por tarea 1 (' + c + ' chunks), tarea 2 no necesaria');
                return;
            }
            if (c >= N) {
                fullStarted = true;
                log('Handoff a descarga completa en chunk ' + c);
                cache.stop();
                startFullDownload(cache, url, c);
            } else {
                setTimeout(check, 250);
            }
        };
        check();
    };
}

// ===== Prefetch (siguientes episodios) =====
var _prefetchCaches = [];

function getSettingRaw(key, def) {
    var v = localStorage.getItem('tvcat_player_pro2_' + key);
    return v !== null ? JSON.parse(v) : def;
}

function startPrefetch(currentEpisodeId) {
    // No hacer nada si no hay lista de episodios
    if (!window.Catalog || !window.Catalog.currentEpisodes) return;
    var num = getSettingRaw('prefetch_episodes', 2);
    if (num === 0) return;

    var eps = window.Catalog.currentEpisodes;
    var mediaId = window.Catalog.currentMediaId;
    if (!mediaId || !eps[mediaId]) return;
    var mediaData = eps[mediaId];
    var seasons = mediaData.seasons || {};
    var activeSeason = mediaData.activeSeason;
    if (!activeSeason || !seasons[activeSeason]) return;
    var episodes = seasons[activeSeason];

    // Encontrar el índice del episodio actual
    var currentIdx = -1;
    for (var i = 0; i < episodes.length; i++) {
        var eid = String(mediaId) + ':' + String(episodes[i].id || 0);
        if (eid === currentEpisodeId) { currentIdx = i; break; }
    }
    if (currentIdx < 0) return;

    // Determinar cuántos precargar
    var limit = num > 0 ? Math.min(num, episodes.length - currentIdx - 1) : (num === -1 ? episodes.length - currentIdx - 1 : 0);
    if (limit <= 0) return;

    log('Precargando', limit, 'episodio(s)...');
    for (var j = 1; j <= limit; j++) {
        (function(idx) {
            var nextEp = episodes[currentIdx + idx];
            if (!nextEp || !nextEp.video_src) return;
            var nextId = String(mediaId) + ':' + String(nextEp.id || 0);
            var nextUrl = nextEp.video_src;
            var nextFileSize = nextEp.file_size || 0;
            var pc = new BackgroundCache(nextUrl, nextId, nextFileSize);
            _prefetchCaches.push(pc);
            pc.onProgress = function(ranges, totalChunks, fs) {
                if (ranges.length > 0) {
                    var pct = totalChunks > 0 ? Math.round((ranges[0][1] + 1) / totalChunks * 100) : 0;
                    if (pct % 25 === 0) log('Prefetch', nextId, ':', pct + '%');
                }
            };
            pc.start(0);
            log('Prefetch iniciado:', nextUrl, '(' + nextId + ')');
        })(j);
    }
}
var _cacheBlobUrl = null;
var _blobModeActive = false;
var _blobChunksAtCreation = 0;

function switchToBlob(videoPlayer, episodeId, savedTime) {
    log('Cambiando a modo Blob (offline)...');
    // Force full reset of video element before loading new source
    videoPlayer.src = '';
    videoPlayer.load();
    // Revoke any existing blob URL
    if (_cacheBlobUrl) { try { URL.revokeObjectURL(_cacheBlobUrl); } catch(e) {} _cacheBlobUrl = null; }
    CacheDB.getEpisodeChunks(episodeId).then(function(indices) {
        if (indices.length === 0) { log('Sin datos cacheados'); return; }
        indices.sort(function(a, b) { return a - b; });
        var loadAll = function(i, acc) {
            if (i >= indices.length) {
                var blob = new Blob(acc, { type: 'video/mp4' });
                _cacheBlobUrl = URL.createObjectURL(blob);
                _blobChunksAtCreation = indices.length;
                videoPlayer.src = _cacheBlobUrl;
                _blobModeActive = true;
                log('Blob cargado:', blob.size, 'bytes');
                var playIt = function() {
                    if (videoPlayer.readyState >= 2) {
                        if (savedTime > 0) videoPlayer.currentTime = savedTime;
                        videoPlayer.play().catch(function(){});
                    } else {
                        videoPlayer.addEventListener('canplay', playIt, { once: true });
                    }
                };
                playIt();
                return;
            }
            CacheDB.getChunk(episodeId, indices[i]).then(function(data) {
                if (data) { acc.push(data); loadAll(i + 1, acc); }
                else { log('Chunk faltante', indices[i]); if (acc.length > 0) loadAll(Infinity, acc); }
            });
        };
        loadAll(0, []);
    });
}
var _currentCache = null;
var _fullDownloadAbort = null;
var _previousEpisodeId = null;
var _currentEpisodeId = null;
var _currentPlayingEpisodeId = 0;
var _currentPlayingEpisodeKey = '';
var _cleanedPrevious = false;
var _originalPlayMedia = null;
var currentPlayingItemId = null;

// ===== Cache Bar =====
function createCacheBar() {
    var container = document.getElementById('cache-bar-container');
    if (container) { log('Cache bar ya existe'); return container; }
    container = document.createElement('div');
    container.id = 'cache-bar-container';
    container.className = 'cache-bar-container';
    container.innerHTML = '<div id="cache-bar-fills" class="cache-bar-fills"></div>';
    var parent = document.querySelector('.plyr') || document.getElementById('player-modal');
    if (parent) { parent.appendChild(container); log('Cache bar creada en', parent.id || parent.className); }
    if (!document.querySelector('.plyr')) {
        setTimeout(function() {
            var p = document.querySelector('.plyr') || document.getElementById('player-modal');
            if (p && container.parentElement !== p) { p.appendChild(container); }
        }, 500);
    }
    return container;
}

function getCurrentChunk(fileSize) {
    var player = document.getElementById('tvcat-video-player');
    if (!player || !player.duration || player.duration <= 0 || !fileSize) return -1;
    var seekByte = (player.currentTime / player.duration) * fileSize;
    return Math.floor(seekByte / CHUNK_SIZE);
}

function updateCacheBar(ranges, totalChunks, fileSize) {
    var fills = document.getElementById('cache-bar-fills');
    if (!fills) { log('ERROR: cache-bar-fills no encontrado'); return; }
    if (!isFinite(totalChunks) || totalChunks <= 0) {
        totalChunks = 0;
        for (var i = 0; i < ranges.length; i++) {
            if (ranges[i][1] + 1 > totalChunks) totalChunks = ranges[i][1] + 1;
        }
        if (totalChunks <= 0) totalChunks = 1;
    }
    var currentChunk = getCurrentChunk(fileSize);
    var html = '';
    for (var i = 0; i < ranges.length; i++) {
        var rs = ranges[i][0];
        var re = ranges[i][1];
        if (currentChunk >= 0 && currentChunk >= rs && currentChunk <= re) {
            if (currentChunk > rs) {
                var left = (rs / totalChunks) * 100;
                var width = ((currentChunk - rs) / totalChunks) * 100;
                if (width < 0.5) width = 0.5;
                html += '<div class="cache-bar-fill" style="left:' + left + '%;width:' + width + '%;"></div>';
            }
            var left = (currentChunk / totalChunks) * 100;
            var width = (1 / totalChunks) * 100;
            if (width < 0.5) width = 0.5;
            html += '<div class="cache-bar-fill cache-bar-fill-current" style="left:' + left + '%;width:' + width + '%;"></div>';
            if (currentChunk < re) {
                var left = ((currentChunk + 1) / totalChunks) * 100;
                var width = ((re - currentChunk) / totalChunks) * 100;
                if (width < 0.5) width = 0.5;
                html += '<div class="cache-bar-fill" style="left:' + left + '%;width:' + width + '%;"></div>';
            }
        } else {
            var left = (rs / totalChunks) * 100;
            var width = ((re - rs + 1) / totalChunks) * 100;
            if (width < 0.5) width = 0.5;
            html += '<div class="cache-bar-fill" style="left:' + left + '%;width:' + width + '%;"></div>';
        }
    }
    fills.innerHTML = html;
    log('Cache bar actualizada: ' + ranges.length + ' rangos, ' + Math.round(totalChunks) + ' chunks');
}

var _playMediaProBusy = false;

// ===== Play Media Pro =====
function playMediaPro(itemData, episode) {
    if (_playMediaProBusy) { log('playMediaPro ya en ejecución'); return; }
    _playMediaProBusy = true;
    try {
    var _blobUpgraded = false;

    if (_currentCache) { _currentCache.stop(); _currentCache = null; }
    if (_fullDownloadAbort) { try { _fullDownloadAbort.abort(); } catch(e) {} _fullDownloadAbort = null; }
    if (_cacheBlobUrl) {
        try { URL.revokeObjectURL(_cacheBlobUrl); } catch(e) {}
        _cacheBlobUrl = null;
    }
    _blobModeActive = false;

    var videoSrc = episode && episode.video_src;

    if (!videoSrc || videoSrc.indexOf('/') !== 0) {
        log('video_src no es ruta de servidor, fallback');
        return _originalPlayMedia(itemData, episode);
    }

    var playerModal = document.getElementById('player-modal');
    var videoPlayer = document.getElementById('tvcat-video-player');
    if (!playerModal || !videoPlayer) return;

    // Reuse standard player modal setup
    playerModal.classList.remove('hidden');
    playerModal.style.display = '';
    playerModal.style.visibility = '';
    playerModal.style.opacity = '';

    var uiMode = getUIMode();

    if (uiMode === 'basic') {
        playerModal.style.width = '100%';
        playerModal.style.height = '100%';
        playerModal.style.borderRadius = '0';
        var pc = playerModal.querySelector('.player-container');
        if (pc) { pc.style.width = '100%'; pc.style.height = '100%'; pc.style.maxWidth = '100%'; pc.style.borderRadius = '0'; }
        var closeBtn = playerModal.querySelector('.close-player-btn');
        if (closeBtn) closeBtn.style.display = 'none';
    }
    videoPlayer.controls = (uiMode !== 'basic');
    videoPlayer.style.width = '100%';
    videoPlayer.style.height = '100%';

    var episodeId = String(itemData.item_id || itemData.id) + ':' + String(episode.id || 0);
    _currentPlayingEpisodeId = episode ? (episode.id || 0) : 0;
    _currentPlayingEpisodeKey = episode ? (episode.episode_key || '') : '';
    currentPlayingItemId = itemData ? (itemData.item_id || itemData.id) : null;
    if (window.Catalog) {
        window.Catalog.currentMediaId = currentPlayingItemId;
        window.Catalog.currentPlayingVideoSrc = videoSrc;
    }

    // Store URL→episodeId mapping para el Service Worker ANTES de empezar a cachear
    var absUrl = videoSrc.indexOf('://') > 0 ? videoSrc : window.location.origin + (videoSrc.indexOf('/') === 0 ? '' : '/') + videoSrc;
    var streamPath = new URL(absUrl).pathname;

    // Cleanup cache from previous episode
    var threshold = getSetting('cache_cleanup_threshold', 30);
    _cleanedPrevious = false;
    _previousEpisodeId = _currentEpisodeId;
    _currentEpisodeId = episodeId;

    // Create cache bar (se actualizará cuando loadCached() termine)
    createCacheBar();

    // Init Plyr if needed
    if (uiMode === 'plyr' && typeof Plyr !== 'undefined') {
        try {
            var plyrInstance = new Plyr(videoPlayer, { controls: ['play-large', 'play', 'progress', 'current-time', 'mute', 'volume', 'pip', 'fullscreen'], seekTime: 5 });
            plyrInstance.on('controlsshown', function() { if (window.Catalog && window.Catalog.showCustomControls) window.Catalog.showCustomControls(true); });
            plyrInstance.on('controlshidden', function() { if (window.Catalog && window.Catalog.showCustomControls) window.Catalog.showCustomControls(false); });
            plyrInstance.on('play', function() { if (window.Catalog && window.Catalog.showCustomControls) window.Catalog.showCustomControls(false); });
            plyrInstance.on('pause', function() { if (window.Catalog && window.Catalog.showCustomControls) window.Catalog.showCustomControls(true); });
        } catch(e) { log('Plyr init error:', e); }
    }

    // Show custom controls
    if (window.Catalog && window.Catalog.showCustomControls) {
        window.Catalog.showCustomControls(true);
    }

    // Cache + Play: guardar mapeo, cachear, esperar chunks iniciales, luego reproducir
    var fileSize = episode.file_size || 0;
    var _blobUpgraded = false;
    var cache = new BackgroundCache(videoSrc, episodeId, fileSize);
    _currentCache = cache;
    cache.onProgress = function(ranges, totalChunks, fs) {
        updateCacheBar(ranges, totalChunks, fs);
        if (_blobModeActive) {
            var currentChunks = Object.keys(cache.cachedSet).length;
            if (cache._completed || (currentChunks - _blobChunksAtCreation >= 30)) {
                _blobChunksAtCreation = currentChunks;
                log('Caché creció, actualizando Blob...');
                switchToBlob(videoPlayer, episodeId, videoPlayer.currentTime || 0);
            }
        }
        // Iniciar precarga de siguientes episodios cuando el actual esté completo
        if (cache._completed && _prefetchCaches.length === 0) {
            log('Episodio completado, iniciando precarga...');
            startPrefetch(episodeId);
        }
    };

    CacheDB.putMeta('url_map:' + streamPath, episodeId).then(function() {
        log('Mapeo URL→episodeId guardado:', streamPath, '→', episodeId);
        log('Iniciando caché desde chunk 0 (total:', cache.totalChunks, ')');
        cache.start(0);
        // Tarea 2: descarga completa. Mide velocidad con tarea 1 y entrega el control.
        setupDualDownload(cache, videoSrc, episodeId);
    });

    // Esperar a que 10 chunks estén cacheados antes de reproducir (para un Blob inicial de ~30s)
    var INIT_CHUNKS = 10;
    (function waitForInit(cache, done, needed) {
        if (needed === 0) { done(); return; }
        var timeout = setTimeout(function() { log('Timeout esperando chunks iniciales, reproduciendo igual'); done(); }, 15000);
        var poll = function() {
            if (cache.stopped) { clearTimeout(timeout); done(); return; }
            var ok = true;
            for (var i = 0; i < needed; i++) { if (!cache.cachedSet[i]) { ok = false; break; } }
            if (ok) { clearTimeout(timeout); done(); return; }
            setTimeout(poll, 200);
        };
        poll();
    })(cache, function() {
        var isComplete = cache._completed;
        var isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true;
        if (isComplete || (!isOnline && cache.totalChunks > 0)) {
            log(isComplete ? 'Caché completo, reproduciendo desde Blob' : 'Offline con caché parcial, reproduciendo desde Blob');
            switchToBlob(videoPlayer, episodeId, 0);
            try { var fsEl = document.querySelector('.plyr') || document.getElementById('player-modal'); if (fsEl.requestFullscreen) fsEl.requestFullscreen(); else if (videoPlayer.webkitEnterFullscreen) videoPlayer.webkitEnterFullscreen(); else if (videoPlayer.webkitRequestFullscreen) videoPlayer.webkitRequestFullscreen(); } catch(e) {}
        } else {
            log('Iniciando streaming directo (caché en segundo plano)');
            videoPlayer.src = addChunkParam(videoSrc);
            videoPlayer.load();
            try { videoPlayer.play().then(function() {
                try { var fsEl = document.querySelector('.plyr') || document.getElementById('player-modal'); if (fsEl.requestFullscreen) fsEl.requestFullscreen(); else if (videoPlayer.webkitEnterFullscreen) videoPlayer.webkitEnterFullscreen(); else if (videoPlayer.webkitRequestFullscreen) videoPlayer.webkitRequestFullscreen(); } catch(e) {}
            }).catch(function() {
                try { var fsEl = document.querySelector('.plyr') || document.getElementById('player-modal'); if (fsEl.requestFullscreen) fsEl.requestFullscreen(); else if (videoPlayer.webkitEnterFullscreen) videoPlayer.webkitEnterFullscreen(); else if (videoPlayer.webkitRequestFullscreen) videoPlayer.webkitRequestFullscreen(); } catch(e) {}
            }); } catch(e) {
                try { var fsEl = document.querySelector('.plyr') || document.getElementById('player-modal'); if (fsEl.requestFullscreen) fsEl.requestFullscreen(); else if (videoPlayer.webkitEnterFullscreen) videoPlayer.webkitEnterFullscreen(); else if (videoPlayer.webkitRequestFullscreen) videoPlayer.webkitRequestFullscreen(); } catch(e) {}
            }
        }
    });

    // Inject custom controls (misma lógica que player.js)
    (function injectControls() {
        var getOrCreate = function(id, html) {
            var el = document.getElementById(id);
            if (!el) { var temp = document.createElement('div'); temp.innerHTML = html; el = temp.firstChild; el.id = id; }
            return el;
        };
        var toInject = [
            getOrCreate('skip-intro', '<button id="skip-intro" class="skip-btn" onclick="Catalog.skipIntro()">Saltar Intro</button>'),
            getOrCreate('btn-prev-ep', '<button class="nav-text-btn prev-ep-btn" id="btn-prev-ep" onclick="Catalog.playPrevious()">Anterior</button>'),
            getOrCreate('btn-next-ep', '<button class="nav-text-btn next-ep-btn" id="btn-next-ep" onclick="Catalog.playNext()">Siguiente</button>'),
            getOrCreate('left-side', '<div class="side-controls left-side"><button class="jump-btn jump-large" onclick="Catalog.jumpLarge(-1)" title="Salto Largo Atr\u00e1s">&lt;&lt;</button><button class="jump-btn jump-small" onclick="Catalog.jumpSmall(-1)" title="Salto Corto Atr\u00e1s">&lt;</button></div>'),
            getOrCreate('right-side', '<div class="side-controls right-side"><button class="jump-btn jump-small" onclick="Catalog.jumpSmall(1)" title="Salto Corto Adelante">&gt;</button><button class="jump-btn jump-large" onclick="Catalog.jumpLarge(1)" title="Salto Largo Adelante">&gt;&gt;</button></div>'),
            getOrCreate('player-title-overlay', '<div id="player-title-overlay" class="player-title-overlay"></div>'),
            getOrCreate('player-close-btn', '<button id="player-close-btn" class="player-ctrl-close" onclick="Catalog.closePlayer()" title="Cerrar">&times;</button>')
        ];
        var parent = document.querySelector('.plyr') || document.getElementById('player-modal');
        if (parent) { for (var i = 0; i < toInject.length; i++) { if (toInject[i] && !parent.contains(toInject[i])) parent.appendChild(toInject[i]); } }
    })();

    // Detección automática de pérdida de conexión
    videoPlayer.addEventListener('stalled', function() {
        if (!_blobModeActive && _currentCache) {
            log('Stream stalled, cambiando a caché...');
            switchToBlob(videoPlayer, _currentEpisodeId, videoPlayer.currentTime || 0);
        }
    });

    // Seek handling: restart cache from new position + margen
    videoPlayer.onseeked = function() {
        if (_currentCache) {
            var seekTime = videoPlayer.currentTime;
            var dur = videoPlayer.duration || 1;
            var seekByte = Math.floor((seekTime / dur) * (_currentCache.fileSize || 1));
            // Añadir margen de 3 chunks para no competir con el stream al buscar
            var seekChunk = Math.floor(seekByte / CHUNK_SIZE) + 3;
            if (seekChunk >= (_currentCache.totalChunks || Infinity)) seekChunk = _currentCache.totalChunks - 1;
            if (seekChunk < 0) seekChunk = 0;
            _currentCache.restartFrom(seekChunk);
        }
    };

    // History tracking
    var lastSavedPosition = 0;
    var completed = false;
    videoPlayer.ontimeupdate = function() {
        var curTime = Math.floor(videoPlayer.currentTime);
        var duration = Math.floor(videoPlayer.duration || 0);
        // Cleanup cache from previous episode
        if (!_cleanedPrevious && _previousEpisodeId && threshold > 0 && duration > 0) {
            var pct = (videoPlayer.currentTime / duration) * 100;
            if (pct >= threshold) {
                _cleanedPrevious = true;
                CacheDB.deleteEpisode(_previousEpisodeId).then(function() {
                    log('Cache del episodio anterior eliminado al ' + pct.toFixed(0) + '%');
                });
            }
        }
        // History save cada 20s (si la función existe). El guardado definitivo se hace al salir/cambiar/terminar.
        if (typeof window.API.updateHistory === 'function' && curTime > 5 && duration > 10 && curTime % 20 === 0 && curTime !== lastSavedPosition) {
            lastSavedPosition = curTime;
            window.API.updateHistory(currentPlayingItemId, videoSrc, curTime, duration, false, null, _currentPlayingEpisodeId, 0, _currentPlayingEpisodeKey);
        }
        if (typeof window.API.updateHistory === 'function' && !completed && curTime > 5 && duration > 10 && (curTime / duration) > 0.90) {
            completed = true;
            window.API.updateHistory(currentPlayingItemId, videoSrc, duration, duration, true, null, _currentPlayingEpisodeId, 0, _currentPlayingEpisodeKey);
        }
    };
    videoPlayer.onended = function() {
        var duration = Math.floor(videoPlayer.duration || 0);
        if (typeof window.API.updateHistory === 'function' && duration > 10) {
            window.API.updateHistory(currentPlayingItemId, videoSrc, duration, duration, true, null, _currentPlayingEpisodeId, 0, _currentPlayingEpisodeKey);
        }
        // If playing from partial Blob and cache has grown, rebuild with more chunks
        if (_blobModeActive && _currentCache) {
            var currentChunks = Object.keys(_currentCache.cachedSet).length;
            if (currentChunks > _blobChunksAtCreation) {
                _blobChunksAtCreation = currentChunks;
                log('Blob finalizado, reconstruyendo con', currentChunks, 'chunks...');
                switchToBlob(videoPlayer, episodeId, videoPlayer.currentTime || 0);
            }
        }
    };

    // Resume from history (via API.ajax directo)
    function _doResume() {
        if (!window.API || !window.API.ajax) { log('API.ajax no disponible para reanudar'); return; }
        window.API.ajax({
            url: '/api/watch/history',
            success: function(histRes) {
                if (!histRes || !histRes.history) return;
                var resumeTime = 0;
                var epId = episode ? (episode.id || 0) : 0;
                var epKey = episode ? (episode.episode_key || '') : '';
                var key = (itemData.item_id || itemData.id) + ':' + epId;
                for (var i = 0; i < histRes.history.length; i++) {
                    var h = histRes.history[i];
                    if (epKey && h.episode_key === epKey) { resumeTime = h.progress || 0; break; }
                    if (h.item_id && h.episode_id !== undefined) {
                        if ((h.item_id + ':' + h.episode_id) === key) { resumeTime = h.progress || 0; break; }
                    }
                }
                if (resumeTime > 5) {
                    var applied = false;
                    var apply = function() {
                        if (applied) return;
                        if (videoPlayer.readyState >= 1 || videoPlayer.currentTime > 0) {
                            applied = true;
                            videoPlayer.currentTime = resumeTime;
                            videoPlayer.removeEventListener('canplay', apply);
                            videoPlayer.removeEventListener('loadedmetadata', apply);
                            videoPlayer.removeEventListener('playing', apply);
                        }
                    };
                    videoPlayer.addEventListener('canplay', apply);
                    videoPlayer.addEventListener('loadedmetadata', apply);
                    videoPlayer.addEventListener('playing', apply);
                    apply();
                }
            },
            error: function() { log('Error al obtener historial'); }
        });
    }
    _doResume();
    } catch(e) { log('playMediaPro error:', e.message, e.stack); }
    _playMediaProBusy = false;
}

function overridePlayMedia() {
    if (window.Catalog && window.Catalog.playMedia && window.Catalog.playMedia !== playMediaPro) {
        _originalPlayMedia = window.Catalog.playMedia;
        window.Catalog.playMedia = function(itemData, episode) {
            if (localStorage.getItem('tvcat_preferred_player') === 'pro2') playMediaPro(itemData, episode);
            else if (_originalPlayMedia) _originalPlayMedia(itemData, episode);
        };

        var _origPlayNext = window.Catalog.playNext;
        var _origPlayPrev = window.Catalog.playPrevious;
        window.Catalog.playNext = function() {
            if (localStorage.getItem('tvcat_preferred_player') !== 'pro2') return _origPlayNext();
            var eps = window.Catalog.currentEpisodes || {};
            var id = window.Catalog.currentMediaId;
            if (!id || !eps[id]) return;
            var mediaData = eps[id];
            var episodes = mediaData.seasons[mediaData.activeSeason] || [];
            for (var i = 0; i < episodes.length; i++) {
                if (episodes[i].video_src === window.Catalog.currentPlayingVideoSrc) {
                    if (i < episodes.length - 1) { playMediaPro({ item_id: id }, episodes[i + 1]); }
                    return;
                }
            }
        };
        window.Catalog.playPrevious = function() {
            if (localStorage.getItem('tvcat_preferred_player') !== 'pro2') return _origPlayPrev();
            var eps = window.Catalog.currentEpisodes || {};
            var id = window.Catalog.currentMediaId;
            if (!id || !eps[id]) return;
            var mediaData = eps[id];
            var episodes = mediaData.seasons[mediaData.activeSeason] || [];
            for (var i = 0; i < episodes.length; i++) {
                if (episodes[i].video_src === window.Catalog.currentPlayingVideoSrc) {
                    if (i > 0) { playMediaPro({ item_id: id }, episodes[i - 1]); }
                    return;
                }
            }
        };

        if (!window.Catalog.__proCloseOverride) {
            var _origClose = window.Catalog.closePlayer;
            window.Catalog.closePlayer = function() {
                // Guardar SIEMPRE al cerrar (sin filtro de segundos) y restaurar el ojo a 0 (auto)
                var videoPlayer = document.getElementById('tvcat-video-player');
                if (videoPlayer && currentPlayingItemId && typeof window.API.updateHistory === 'function') {
                    var curTime = Math.floor(videoPlayer.currentTime);
                    var duration = Math.floor(videoPlayer.duration || 0);
                    var completed = (duration > 0 && curTime / duration > 0.85);
                    window.API.updateHistory(currentPlayingItemId, window.Catalog.currentPlayingVideoSrc || '', curTime, duration, completed, null, _currentPlayingEpisodeId, 0, _currentPlayingEpisodeKey);
                }
                if (_currentCache) { _currentCache.stop(); _currentCache = null; }
                if (_fullDownloadAbort) { try { _fullDownloadAbort.abort(); } catch(e) {} _fullDownloadAbort = null; }
                if (_cacheBlobUrl) {
                    try { URL.revokeObjectURL(_cacheBlobUrl); } catch(e) {}
                    _cacheBlobUrl = null;
                }
                _blobModeActive = false;
                if (_origClose) _origClose();
            };
            window.Catalog.__proCloseOverride = true;
        }
        log('Override activo');
    } else {
        setTimeout(overridePlayMedia, 100);
    }
}
overridePlayMedia();

// ===== Plugin Registration =====
if (window.pluginSystem) {
    window.pluginSystem.registerPlugin({
        name: 'tvcat_player_pro2',
        type: 'player',
        displayName: 'Player Pro 2 (Descarga Completa)',
        playerType: 'pro2',
        applies_to: ['media', 'series', 'video', 'anime', 'tv', 'peliculas'],
        action_category: 'playback',
        play: function(item) {
            localStorage.setItem('tvcat_preferred_player', 'pro2');
            var id = item.item_id || item.id;
            var cat = (item.subcategory || '').toLowerCase();
            var hasEps = item.episodes && item.episodes.length > 0;
            if (window.Catalog && window.Catalog.playMedia !== playMediaPro) overridePlayMedia();
            Catalog._playWithPlayer(item, id, hasEps, cat, this);
        }
    });
    log('Plugin Pro registrado');
}

})();
