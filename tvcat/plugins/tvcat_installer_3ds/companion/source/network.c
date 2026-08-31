/*
 * TVCat Companion 3DS — network.c
 * Cliente HTTP mínimo (socket:u). Solo HTTP (no TLS) para LAN.
 * Enviar JSON y parsear respuestas simples.
 */
#include <3ds.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <malloc.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>

#include "network.h"
#include "download.h"

static int g_sockfd = -1;
static void *soc_buffer = NULL;

int network_init(void) {
    /* socInit requiere un buffer alineado (1 MB) para la pila de red de la 3DS. */
    soc_buffer = memalign(0x1000, 0x100000);
    if (!soc_buffer) return -1;
    Result res = socInit((u32*)soc_buffer, 0x100000);
    if (R_FAILED(res)) {
        free(soc_buffer);
        soc_buffer = NULL;
        return -1;
    }
    return 0;
}

void network_cleanup(void) {
    if (g_sockfd >= 0) { close(g_sockfd); g_sockfd = -1; }
    if (soc_buffer) {
        socExit();
        free(soc_buffer);
        soc_buffer = NULL;
    }
}

/* http://host:port/3ds?token=ABC123 → server_url + pairing_token */
int network_parse_short_url(TVCAT_CONFIG *cfg) {
    const char *token = strstr(cfg->server_url, "?token=");
    if (!token) return 0;
    token += 7;
    char tmp[MAX_STR];
    strncpy(tmp, token, MAX_STR - 1); tmp[MAX_STR - 1] = '\0';
    char *amp = strchr(tmp, '&');
    if (amp) *amp = '\0';
    snprintf(cfg->pairing_token, MAX_STR, "%s", tmp);
    /* Quitar el path "/3ds" y el query: dejar solo http://host:port */
    char *q = strstr(cfg->server_url, "/3ds");
    if (q) *q = '\0';
    return 1;
}

/* Divide "http://host:port/path" en host, port, path. */
static void parse_url(const char *url, char *host, int *port, const char **path) {
    *port = 80;
    const char *p = strstr(url, "://");
    p = p ? p + 3 : url;
    const char *slash = strchr(p, '/');
    size_t hlen = slash ? (size_t)(slash - p) : strlen(p);
    if (hlen > 255) hlen = 255;
    memcpy(host, p, hlen); host[hlen] = '\0';
    *path = slash ? slash : "/";
    /* puerto en host */
    char *colon = strchr(host, ':');
    if (colon) { *colon = '\0'; *port = atoi(colon + 1); }
}

/* Envía una petición HTTP y devuelve el body (malloc) tras las cabeceras. */
static char *http_request(const char *method, const char *url, const char *body,
                          const char *extra_headers, long *http_code, size_t *body_len) {
    char host[256]; int port; const char *path;
    parse_url(url, host, &port, &path);

    struct hostent *he = gethostbyname(host);
    if (!he) return NULL;
    struct sockaddr_in saddr;
    memset(&saddr, 0, sizeof(saddr));
    saddr.sin_family = AF_INET;
    saddr.sin_port = htons((u16)port);
    memcpy(&saddr.sin_addr, he->h_addr_list[0], he->h_length);

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return NULL;
    if (connect(fd, (struct sockaddr*)&saddr, sizeof(saddr)) < 0) { close(fd); return NULL; }

    char req[2048];
    int blen = body ? (int)strlen(body) : 0;
    snprintf(req, sizeof(req),
        "%s %s HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\nUser-Agent: TVCat3DS/1.0\r\n%s%s%s",
        method, path, host, port,
        extra_headers ? extra_headers : "",
        blen > 0 ? "Content-Length: " : "",
        blen > 0 ? "X" : "");
    /* sobreescribir Content-Length numérico */
    if (blen > 0) {
        char cl[32];
        snprintf(cl, sizeof(cl), "Content-Length: %d\r\n", blen);
        char *pos = strstr(req, "Content-Length: X");
        if (pos) { memcpy(pos, cl, strlen(cl)); }
    }
    strncat(req, "\r\n", sizeof(req) - strlen(req) - 1);
    write(fd, req, strlen(req));
    if (body) write(fd, body, blen);

    /* leer respuesta */
    static char buf[65536];
    size_t got = 0;
    long total = 0;
    int header_done = 0;
    long code = 0;
    size_t hdr_end = 0;
    while (1) {
        int n = read(fd, buf + got, sizeof(buf) - 1 - got);
        if (n <= 0) break;
        got += (size_t)n;
        buf[got] = '\0';
        if (!header_done) {
            char *sep = strstr(buf, "\r\n\r\n");
            if (sep) {
                header_done = 1;
                hdr_end = (size_t)(sep - buf) + 4;
                char line[128]; line[0] = '\0';
                sscanf(buf, "HTTP/1.%*c %ld", &code);
                (void)line;
                if (http_code) *http_code = code;
            }
        }
        if (got >= sizeof(buf) - 1) break;
    }
    close(fd);
    (void)total;
    if (!header_done) return NULL;
    if (body_len) *body_len = got - hdr_end;
    char *out = malloc(got - hdr_end + 1);
    if (!out) return NULL;
    memcpy(out, buf + hdr_end, got - hdr_end);
    out[got - hdr_end] = '\0';
    return out;
}

/* Extrae el valor de un campo JSON simple: {"key":"value"} */
static void json_str(const char *json, const char *key, char *out, size_t len) {
    out[0] = '\0';
    char pat[128];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p) return;
    p = strchr(p + strlen(pat), '"');
    if (!p) return;
    p++;
    const char *e = strchr(p, '"');
    if (!e) return;
    size_t n = (size_t)(e - p);
    if (n >= len) n = len - 1;
    memcpy(out, p, n); out[n] = '\0';
}

int network_pair(TVCAT_CONFIG *cfg) {
    char url[MAX_STR];
    char body[1024];
    config_get_hardware_id(cfg->console_hwid, sizeof(cfg->console_hwid));
    config_get_console_name(cfg->console_name, sizeof(cfg->console_name));
    snprintf(url, sizeof(url), "%s/api/installer/3ds/pair", cfg->server_url);
    snprintf(body, sizeof(body),
             "{\"token\":\"%s\",\"console_name\":\"%s\",\"console_hwid\":\"%s\",\"download_dir\":\"%s\"}",
             cfg->pairing_token, cfg->console_name, cfg->console_hwid, cfg->download_dir);
    long code = 0; size_t blen = 0;
    char *resp = http_request("POST", url, body, NULL, &code, &blen);
    if (!resp) return -1;
    /* buscar "id" en la respuesta ({"ok":true,"id":"..."}) */
    json_str(resp, "id", cfg->console_id, sizeof(cfg->console_id));
    free(resp);
    if (code == 200 && cfg->console_id[0] != '\0') return 0;
    return -1;
}

void network_heartbeat(TVCAT_CONFIG *cfg, char *status_out) {
    static u64 last = 0;
    if (svcGetSystemTick() - last < (cfg->heartbeat_ms * 268123480ULL) / 1000) return;
    last = svcGetSystemTick();
    char url[MAX_STR], body[512];
    snprintf(url, sizeof(url), "%s/api/installer/3ds/%s/heartbeat", cfg->server_url, cfg->console_id);
    snprintf(body, sizeof(body), "{\"token\":\"%s\",\"state\":\"idle\",\"progress\":0,\"free\":0}", cfg->pairing_token);
    long code = 0; size_t blen = 0;
    char *resp = http_request("POST", url, body, NULL, &code, &blen);
    if (resp) free(resp);
    if (status_out) {
        if (code == 200) snprintf(status_out, 256, "Online: %s", cfg->server_url);
        else snprintf(status_out, 256, "Heartbeat fall\u00f3 (%ld)", code);
    }
}

void network_poll_commands(TVCAT_CONFIG *cfg) {
    char url[MAX_STR];
    snprintf(url, sizeof(url), "%s/api/installer/3ds/%s/commands?token=%s", cfg->server_url, cfg->console_id, cfg->pairing_token);
    long code = 0; size_t blen = 0;
    char *resp = http_request("GET", url, NULL, NULL, &code, &blen);
    if (!resp || code != 200) { if (resp) free(resp); return; }
    /* Si hay commands con cmd=download, almacenar el primero como descarga pendiente. */
    if (strstr(resp, "download")) {
        /* TODO: poblar DOWNLOAD_JOB y marcarlo activo. */
    }
    free(resp);
}

int network_get_range(const char *url, long start, long end, unsigned char *buf, size_t bufsize, size_t *out_len) {
    char range[64];
    snprintf(range, sizeof(range), "Range: bytes=%ld-%ld\r\n", start, end);
    long code = 0; size_t blen = 0;
    char *resp = http_request("GET", url, NULL, range, &code, &blen);
    if (!resp || code != 206) { if (resp) free(resp); return -1; }
    size_t n = blen;
    if (n > bufsize) n = bufsize;
    memcpy(buf, resp, n);
    *out_len = n;
    free(resp);
    return 0;
}
