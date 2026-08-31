/*
 * TVCat Companion 3DS — network.h
 * Cliente HTTP mínimo sobre sockets 3DS (socket:u).
 */
#ifndef TVCAT_NETWORK_H
#define TVCAT_NETWORK_H

#include "config.h"

/* Devuelve 0 si OK. Inicializa socInit (red) con buffer alineado. */
int network_init(void);
void network_cleanup(void);

/* Si cfg->server_url es una URL corta de pairing (http://server/3ds?token=X),
 * la separa en server_url + pairing_token. Devuelve 1 si se aplicó. */
int network_parse_short_url(TVCAT_CONFIG *cfg);

/* POST JSON {token,...} a /api/installer/3ds/{cid}/pair. */
int network_pair(TVCAT_CONFIG *cfg);

/* POST heartbeat. */
void network_heartbeat(TVCAT_CONFIG *cfg, char *status_out);

/* GET commands (FIFO) → lanza descarga si hay comando. */
void network_poll_commands(TVCAT_CONFIG *cfg);

/* GET un rango de bytes de una URL → devuelve bytes. (usado por download) */
int network_get_range(const char *url, long start, long end, unsigned char *buf, size_t bufsize, size_t *out_len);

#endif
