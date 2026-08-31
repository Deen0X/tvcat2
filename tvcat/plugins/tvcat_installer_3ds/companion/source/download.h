/*
 * TVCat Companion 3DS — download.h
 * Descarga por rangos con reanudación y verificación SHA-256.
 */
#ifndef TVCAT_DOWNLOAD_H
#define TVCAT_DOWNLOAD_H

#include "config.h"

typedef struct {
    char url[MAX_STR];
    char filename[MAX_STR];
    long total_size;
    long downloaded;
    char hash_hex[65];
    int  active;
} DOWNLOAD_JOB;

/* true si hay un comando de descarga pendiente. */
int download_pending(TVCAT_CONFIG *cfg);

/* Procesa la descarga activa (un chunk por llamada). */
void download_process(TVCAT_CONFIG *cfg, char *status_out);

#endif
