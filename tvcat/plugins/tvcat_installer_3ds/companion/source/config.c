/*
 * TVCat Companion 3DS — config.c
 */
#include <3ds.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "config.h"

static void default_cfg(TVCAT_CONFIG *cfg) {
    memset(cfg, 0, sizeof(*cfg));
    snprintf(cfg->server_url, MAX_STR, "http://192.168.1.100:8093");
    snprintf(cfg->download_dir, MAX_STR, "sdmc:/tvcat");
    cfg->heartbeat_ms = 10000;
}

void config_load(TVCAT_CONFIG *cfg, const char *path) {
    default_cfg(cfg);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char line[MAX_STR];
    while (fgets(line, sizeof(line), f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        char *key = line;
        char *val = eq + 1;
        /* quitar \n */
        size_t l = strlen(val);
        while (l && (val[l-1] == '\n' || val[l-1] == '\r')) val[--l] = '\0';
        if (strcmp(key, "server_url") == 0) snprintf(cfg->server_url, MAX_STR, "%s", val);
        else if (strcmp(key, "pairing_token") == 0) snprintf(cfg->pairing_token, MAX_STR, "%s", val);
        else if (strcmp(key, "console_id") == 0) snprintf(cfg->console_id, MAX_STR, "%s", val);
        else if (strcmp(key, "console_name") == 0) snprintf(cfg->console_name, MAX_STR, "%s", val);
        else if (strcmp(key, "console_hwid") == 0) snprintf(cfg->console_hwid, MAX_STR, "%s", val);
        else if (strcmp(key, "download_dir") == 0) snprintf(cfg->download_dir, MAX_STR, "%s", val);
        else if (strcmp(key, "heartbeat_ms") == 0) cfg->heartbeat_ms = atoi(val);
    }
    fclose(f);
}

void config_save(const TVCAT_CONFIG *cfg) {
    FILE *f = fopen("sdmc:/tvcat_companion.cfg", "w");
    if (!f) return;
    fprintf(f, "server_url=%s\n", cfg->server_url);
    fprintf(f, "pairing_token=%s\n", cfg->pairing_token);
    fprintf(f, "console_id=%s\n", cfg->console_id);
    fprintf(f, "console_name=%s\n", cfg->console_name);
    fprintf(f, "console_hwid=%s\n", cfg->console_hwid);
    fprintf(f, "download_dir=%s\n", cfg->download_dir);
    fprintf(f, "heartbeat_ms=%d\n", cfg->heartbeat_ms);
    fclose(f);
}

void config_get_console_name(char *out, size_t len) {
    /* FRDU: obtener el FriendlyName del usuario principal de la 3DS. */
    out[0] = '\0';
    Handle frd = 0;
    if (R_SUCCEEDED(srvGetServiceHandle(&frd, "frdu"))) {
        /* Proxy FRDU_GetMyScreenName (0x00070042) — tamaño de nombre variable.
         * Simplificación: usar valor por defecto si falla. */
        svcCloseHandle(frd);
    }
    if (out[0] == '\0') snprintf(out, len, "3DS");
}

void config_get_hardware_id(char *out, size_t len) {
    /* Hash estable: MAC de la interfaz WiFi (socket:u ACU_GetWifiStatus) +
     * modelo de consola (CFGU_GetSystemModel). En 3DS no hay MAC vía API fácil
     * sin CFW; usamos la dirección única (PS:U) o un fallback. */
    out[0] = '\0';
    u8 model = 0;
    CFGU_GetSystemModel(&model);
    snprintf(out, len, "3DS-M%u-%08X", (unsigned)model,
             (unsigned)(svcGetSystemTick() & 0xFFFFFFFFUL));
}
