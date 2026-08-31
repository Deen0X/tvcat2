/*
 * TVCat Companion 3DS — config.h
 * Configuración persistente en SD (config.cfg).
 */
#ifndef TVCAT_CONFIG_H
#define TVCAT_CONFIG_H

#define MAX_STR 512

typedef struct {
    char server_url[MAX_STR];      /* http://ip:puerto (sin barra final) */
    char pairing_token[MAX_STR];   /* token corto (5-6 chars) */
    char console_id[MAX_STR];      /* id emparejado (hash hardware) */
    char console_name[MAX_STR];    /* FriendlyName de la 3DS */
    char console_hwid[MAX_STR];    /* hash hardware */
    char download_dir[MAX_STR];    /* ruta SD de descarga */
    int  heartbeat_ms;
} TVCAT_CONFIG;

void config_load(TVCAT_CONFIG *cfg, const char *path);
void config_save(const TVCAT_CONFIG *cfg);

/* Devuelve el FriendlyName del usuario 3DS (FRDU). */
void config_get_console_name(char *out, size_t len);

/* Devuelve un hash de hardware estable (MAC WiFi + modelo). */
void config_get_hardware_id(char *out, size_t len);

#endif
