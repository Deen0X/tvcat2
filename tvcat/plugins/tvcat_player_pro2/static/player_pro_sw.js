// TVCat Player Pro - Service Worker
var SW_DEBUG = true;
function log() { if (SW_DEBUG) console.log.apply(console, ['[PLAYER_PRO_SW]'].concat(Array.prototype.slice.call(arguments))); }

var CHUNK_SIZE = 1024 * 1024;
var DB_NAME = 'tvcat_player_pro_cache';
var DB_VERSION = 1;
var CHUNK_STORE = 'chunks';
var META_STORE = 'meta';

self.addEventListener('install', function(e) {
    log('Instalando');
    self.skipWaiting();
});
self.addEventListener('activate', function(e) {
    log('Activado');
    e.waitUntil(clients.claim());
});

function openDB() {
    return new Promise(function(resolve, reject) {
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
        req.onsuccess = function(e) { resolve(e.target.result); };
        req.onerror = function(e) { reject(e.target.error); };
    });
}
function getMeta(db, key) {
    return new Promise(function(resolve, reject) {
        var tx = db.transaction(META_STORE, 'readonly');
        var req = tx.objectStore(META_STORE).get(key);
        req.onsuccess = function(e) { resolve(e.target.result ? e.target.result.value : null); };
        req.onerror = function(e) { reject(e.target.error); };
    });
}
function getChunk(db, episodeId, chunkIndex) {
    return new Promise(function(resolve, reject) {
        var tx = db.transaction(CHUNK_STORE, 'readonly');
        var req = tx.objectStore(CHUNK_STORE).get([episodeId, chunkIndex]);
        req.onsuccess = function(e) { resolve(e.target.result ? e.target.result.data : null); };
        req.onerror = function(e) { reject(e.target.error); };
    });
}
function getMaxChunk(db, episodeId) {
    return new Promise(function(resolve, reject) {
        var tx = db.transaction(CHUNK_STORE, 'readonly');
        var index = tx.objectStore(CHUNK_STORE).index('episode_id');
        var cursorReq = index.openCursor(IDBKeyRange.only(episodeId), 'prev');
        cursorReq.onsuccess = function(e) {
            var cursor = e.target.result;
            resolve(cursor ? cursor.key[1] : -1);
        };
        cursorReq.onerror = function(e) { reject(e.target.error); };
    });
}

self.addEventListener('fetch', function(event) {
    var url = new URL(event.request.url);
    if (!url.pathname.match(/^\/api\/stream\/episode\/\d+/)) return;

    var rangeHeader = event.request.headers.get('Range');
    if (!rangeHeader) return;

    event.respondWith(handleStreamRequest(event.request, url.pathname, rangeHeader).catch(function(err) {
        log('Error crítico, fallback a fetch:', err.message);
        return fetch(event.request.clone());
    }));
});

function parseRange(header) {
    var m = header.match(/bytes=(\d+)-(\d*)/);
    if (!m) return null;
    return m[2] ? { start: parseInt(m[1]), end: parseInt(m[2]) } : { start: parseInt(m[1]), end: null };
}

function buildResponse(data, rangeStart, rangeEnd, contentLength, totalFileSize) {
    var total = totalFileSize || (rangeEnd + 1);
    return new Response(data, {
        status: 206,
        statusText: 'Partial Content',
        headers: {
            'Content-Type': 'video/mp4',
            'Content-Range': 'bytes ' + rangeStart + '-' + rangeEnd + '/' + total,
            'Content-Length': String(contentLength),
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache',
            'X-TVCat-Cache': 'HIT'
        }
    });
}

function handleStreamRequest(request, streamPath, rangeHeader) {
    var parsed = parseRange(rangeHeader);
    var reqStart = parsed ? parsed.start : 0;
    var reqEnd = parsed ? parsed.end : null;

    return openDB().then(function(db) {
        return getMeta(db, 'url_map:' + streamPath).then(function(episodeId) {
            if (!episodeId) {
                log('Sin mapeo para', streamPath, '— pasando al servidor');
                db.close();
                return fetch(request.clone());
            }

            return getMeta(db, episodeId + ':file_size').then(function(fileSize) {
                if (reqEnd === null) {
                    return serveOpenEnded(db, request, episodeId, reqStart, fileSize);
                }
                return serveFromCache(db, request, episodeId, reqStart, reqEnd, fileSize);
            });
        });
    });
}

function serveOpenEnded(db, request, episodeId, reqStart, fileSize) {
    return getMaxChunk(db, episodeId).then(function(maxChunk) {
        if (maxChunk < 0 || reqStart > (maxChunk + 1) * CHUNK_SIZE) {
            log('No cached data for open-ended range');
            db.close();
            return fetch(request.clone());
        }

        var MAX_INITIAL = 3 * CHUNK_SIZE;
        var maxEnd = Math.min(reqStart + MAX_INITIAL - 1, (maxChunk + 1) * CHUNK_SIZE - 1);
        if (fileSize) maxEnd = Math.min(maxEnd, fileSize - 1);

        log('Sirviendo rango abierto hasta byte', maxEnd, '(maxChunk=' + maxChunk + ')');
        return serveFromCache(db, request, episodeId, reqStart, maxEnd, fileSize);
    });
}

function serveFromCache(db, request, episodeId, reqStart, reqEnd, fileSize) {
    if (reqEnd < reqStart) { db.close(); return fetch(request.clone()); }

    var startChunk = Math.floor(reqStart / CHUNK_SIZE);
    var endChunk = Math.floor(reqEnd / CHUNK_SIZE);

    function fetchUntilGap(idx) {
        if (idx > endChunk) return Promise.resolve({ chunks: [], lastOk: startChunk - 1 });
        return getChunk(db, episodeId, idx).then(function(data) {
            if (!data) return { chunks: [], lastOk: idx - 1 };
            return fetchUntilGap(idx + 1).then(function(next) {
                next.chunks.unshift({ index: idx, data: data });
                next.lastOk = Math.max(next.lastOk, idx);
                return next;
            });
        });
    }

    return fetchUntilGap(startChunk).then(function(result) {
        db.close();
        var chunks = result.chunks;
        var lastOk = result.lastOk;

        if (chunks.length === 0) {
            log('Falta chunk', startChunk, '— fetch');
            return fetch(request.clone());
        }

        var totalBytes = 0;
        for (var i = 0; i < chunks.length; i++) totalBytes += chunks[i].data.byteLength;

        var actualEnd = Math.min(reqEnd, (lastOk + 1) * CHUNK_SIZE - 1);
        if (fileSize) actualEnd = Math.min(actualEnd, fileSize - 1);

        var combined = new Uint8Array(totalBytes);
        var offset = 0;
        for (var i = 0; i < chunks.length; i++) {
            combined.set(new Uint8Array(chunks[i].data), offset);
            offset += chunks[i].data.byteLength;
        }

        var relativeStart = reqStart - (startChunk * CHUNK_SIZE);
        var sliceEnd = Math.min(actualEnd - reqStart + 1 + relativeStart, totalBytes);
        var data = combined.slice(relativeStart, sliceEnd);

        log('Sirviendo', data.byteLength, 'bytes desde caché (chunks', startChunk + '-' + lastOk + ')');
        return buildResponse(data.buffer, reqStart, actualEnd, data.byteLength, fileSize);
    });
}
