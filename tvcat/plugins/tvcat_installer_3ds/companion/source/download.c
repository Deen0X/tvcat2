/*
 * TVCat Companion 3DS — download.c
 * Descarga por rangos con reanudación y hash SHA-256 (TODO).
 */
#include <3ds.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "download.h"
#include "network.h"

static DOWNLOAD_JOB g_job;

int download_pending(TVCAT_CONFIG *cfg) {
    (void)cfg;
    return g_job.active;
}

void download_process(TVCAT_CONFIG *cfg, char *status_out) {
    if (!g_job.active) return;
    /* Rango por chunk (1 MB). Reanuda desde g_job.downloaded. */
    long start = g_job.downloaded;
    long end = start + 1024 * 1024 - 1;
    if (g_job.total_size > 0 && end >= g_job.total_size) end = g_job.total_size - 1;

    unsigned char buf[1024 * 1024];
    size_t got = 0;
    if (network_get_range(g_job.url, start, end, buf, sizeof(buf), &got) != 0) {
        snprintf(status_out ? status_out : (char*)"", 256, "Error de descarga (rango %ld)", start);
        return;
    }
    /* append al fichero en SD */
    char full[MAX_STR];
    snprintf(full, sizeof(full), "%s/%s", cfg->download_dir, g_job.filename);
    mkdir(cfg->download_dir, 0777);
    FILE *f = fopen(full, "ab");
    if (f) {
        fwrite(buf, 1, got, f);
        fclose(f);
    }
    g_job.downloaded += got;
    if (g_job.total_size > 0 && g_job.downloaded >= g_job.total_size) {
        /* TODO: verificar SHA-256 (g_job.hash_hex). */
        snprintf(status_out ? status_out : (char*)"", 256, "Descarga completa: %s", g_job.filename);
        g_job.active = 0;
    } else {
        snprintf(status_out ? status_out : (char*)"", 256, "Descargando %ld/%ld", g_job.downloaded, g_job.total_size);
    }
}
