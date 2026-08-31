/*
 * TVCat Companion 3DS (modo puente)
 * Recibe ficheros desde TVCat y los guarda en la microSD (luego usa FBI).
 * Config: sdmc:/3ds/tvcat/config.cfg  (key=value)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <3ds.h>

static u8 __attribute__((aligned(0x1000))) socBuffer[0x80000];

typedef struct {
    char server_url[256], pairing_token[128], name[64], id[64], download_dir[256];
    long heartbeat_ms;
} Config;
static Config g_cfg;

static void trim(char *s) {
    char *p = s;
    while (*p && (*p==' '||*p=='\t'||*p=='\r'||*p=='\n')) p++;
    memmove(s, p, strlen(p)+1);
    p = s + strlen(s);
    while (p > s && (p[-1]==' '||p[-1]=='\t'||p[-1]=='\r'||p[-1]=='\n')) *--p = 0;
}

static void default_config(void) {
    strcpy(g_cfg.server_url, "http://192.168.1.10:8093");
    g_cfg.pairing_token[0] = 0;
    strcpy(g_cfg.name, "3DS de casa");
    snprintf(g_cfg.id, sizeof(g_cfg.id), "3ds-%08x", (unsigned)rand());
    strcpy(g_cfg.download_dir, "sdmc:/3ds/tvcat/downloads");
    g_cfg.heartbeat_ms = 10000;
}

static void load_config(void) {
    default_config();
    FILE *f = fopen("sdmc:/3ds/tvcat/config.cfg", "r");
    if (!f) return;
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = 0;
        char key[128], val[384];
        snprintf(key, sizeof(key), "%s", line);
        snprintf(val, sizeof(val), "%s", eq+1);
        trim(key); trim(val);
        if (!strcmp(key, "server_url")) snprintf(g_cfg.server_url, sizeof(g_cfg.server_url), "%s", val);
        else if (!strcmp(key, "pairing_token")) snprintf(g_cfg.pairing_token, sizeof(g_cfg.pairing_token), "%s", val);
        else if (!strcmp(key, "name")) snprintf(g_cfg.name, sizeof(g_cfg.name), "%s", val);
        else if (!strcmp(key, "id")) snprintf(g_cfg.id, sizeof(g_cfg.id), "%s", val);
        else if (!strcmp(key, "download_dir")) snprintf(g_cfg.download_dir, sizeof(g_cfg.download_dir), "%s", val);
        else if (!strcmp(key, "heartbeat_ms")) g_cfg.heartbeat_ms = atol(val);
    }
    fclose(f);
}

static void save_config(void) {
    FILE *f = fopen("sdmc:/3ds/tvcat/config.cfg", "w");
    if (!f) return;
    fprintf(f, "server_url=%s\n", g_cfg.server_url);
    fprintf(f, "pairing_token=%s\n", g_cfg.pairing_token);
    fprintf(f, "name=%s\n", g_cfg.name);
    fprintf(f, "id=%s\n", g_cfg.id);
    fprintf(f, "download_dir=%s\n", g_cfg.download_dir);
    fprintf(f, "heartbeat_ms=%ld\n", g_cfg.heartbeat_ms);
    fclose(f);
}

/* ---------- HTTP (SOC) ---------- */
static int http_connect(const char *host, int port) {
    struct hostent *hp = socGetHostByName(host, 0);
    if (!hp) return -1;
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) return -1;
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_port = htons((u16)port);
    memcpy(&sa.sin_addr, hp->h_addr_list[0], hp->h_length);
    if (connect(s, (struct sockaddr *)&sa, sizeof(sa)) < 0) { closesocket(s); return -1; }
    return s;
}

static int parse_url(const char *url, char *host, int *port, char *path) {
    char tmp[512];
    snprintf(tmp, sizeof(tmp), "%s", url);
    char *h = tmp;
    if (!strncmp(tmp, "http://", 7)) h = tmp + 7;
    else if (!strncmp(tmp, "https://", 8)) return -1;
    char *slash = strchr(h, '/');
    if (!slash) { strcpy(path, "/"); slash = h + strlen(h); }
    else { snprintf(path, 512, "%s", slash); *slash = 0; }
    char *colon = strchr(h, ':');
    if (colon) { *colon = 0; *port = atoi(colon+1); } else *port = 80;
    snprintf(host, 256, "%s", h);
    return 0;
}

static int http_request(const char *method, const char *url, const char *post_body,
                        const char *extra_header, const char *out_path) {
    char host[256], path[512];
    int port;
    if (parse_url(url, host, &port, path)) return 0;
    char req[1024];
    int n = snprintf(req, sizeof(req), "%s %s HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\n",
                     method, path, host, port);
    if (post_body) n += snprintf(req+n, sizeof(req)-n,
        "Content-Type: application/json\r\nContent-Length: %d\r\n", (int)strlen(post_body));
    if (extra_header) n += snprintf(req+n, sizeof(req)-n, "%s\r\n", extra_header);
    n += snprintf(req+n, sizeof(req)-n, "\r\n");
    if (post_body) n += snprintf(req+n, sizeof(req)-n, "%s", post_body);

    int s = http_connect(host, port);
    if (s < 0) return 0;
    int sent = 0;
    while (sent < n) {
        int r = send(s, req+sent, n-sent, 0);
        if (r <= 0) { closesocket(s); return 0; }
        sent += r;
    }
    FILE *out = out_path ? fopen(out_path, "ab") : NULL;
    int status = 0, body = 0, state = 0, hlen = 0;
    char buf[1024];
    while (1) {
        int r = recv(s, buf, sizeof(buf), 0);
        if (r <= 0) break;
        for (int i = 0; i < r; i++) {
            char c = buf[i];
            if (!body) {
                if (state == 0 && c == '\r') state = 1;
                else if (state == 1 && c == '\n') state = 2;
                else if (state == 2 && c == '\r') state = 3;
                else if (state == 3 && c == '\n') { body = 1; state = 0; continue; }
                else if (state == 2 && c != '\r') state = 0;
                else state = 0;
                if (!body && hlen < 1023) { if (hlen >= 9 && hlen < 12) { } buf[hlen] = c; hlen++; }
                continue;
            }
            if (out) fputc(c, out);
        }
    }
    /* intentar leer status */
    buf[hlen] = 0;
    char *st = strstr(buf, " ");
    if (st && hlen > 9) status = atoi(st + 1);
    if (out) fclose(out);
    closesocket(s);
    return status;
}

static int http_get_body(const char *url, char *out, int out_size) {
    char host[256], path[512];
    int port;
    if (parse_url(url, host, &port, path)) return 0;
    char req[1024];
    int n = snprintf(req, sizeof(req), "GET %s HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\n\r\n",
                     path, host, port);
    int s = http_connect(host, port);
    if (s < 0) return 0;
    send(s, req, n, 0);
    int body = 0, state = 0, total = 0;
    char b;
    while (recv(s, &b, 1, 0) == 1) {
        if (!body) {
            if (state == 0 && b == '\r') state = 1;
            else if (state == 1 && b == '\n') state = 2;
            else if (state == 2 && b == '\r') state = 3;
            else if (state == 3 && b == '\n') { body = 1; continue; }
            else if (state == 2 && b != '\r') state = 0;
            else state = 0;
            continue;
        }
        if (total < out_size - 1) out[total++] = b;
    }
    out[total] = 0;
    closesocket(s);
    return 200;
}

int main(void) {
    gfxInitDefault();
    consoleInit(GFX_TOP, NULL);
    printf("TVCat Companion 3DS (puente)\n");
    load_config();
    if (socInit(&socBuffer, sizeof(socBuffer)) != 0) {
        printf("SOC init fallo\n");
    }

    if (g_cfg.pairing_token[0] == 0) {
        printf("Configura sdmc:/3ds/tvcat/config.cfg\n");
        save_config();
        printf("con server_url y pairing_token\n");
    }

    time_t last = 0;
    while (aptMainLoop()) {
        hidScanInput();
        if (hidKeysDown() & KEY_START) break;
        time_t now = time(NULL);
        if (g_cfg.pairing_token[0] && now - last >= (time_t)(g_cfg.heartbeat_ms / 1000)) {
            last = now;
            char url[512], body[512];
            snprintf(url, sizeof(url), "%s/api/installer/%s/heartbeat", g_cfg.server_url, g_cfg.id);
            snprintf(body, sizeof(body), "{\"token\":\"%s\",\"state\":\"idle\"}", g_cfg.pairing_token);
            int st = http_request("POST", url, body, NULL, NULL);
            printf("hb:%d\n", st);
            /* Poll commands */
            snprintf(url, sizeof(url), "%s/api/installer/%s/commands?token=%s",
                     g_cfg.server_url, g_cfg.id, g_cfg.pairing_token);
            char resp[2048];
            http_get_body(url, resp, sizeof(resp));
            printf("cmds:%s\n", resp);
            /* TODO: parsear JSON de commands y descargar cada download a download_dir */
        }
        svcSleepThread(10000000);
    }
    socExit();
    gfxExit();
    return 0;
}
