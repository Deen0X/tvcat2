/*
 * TVCat Companion 3DS — qr.c
 * Escaneo de QR con cámara (cam:u). Requiere quirc para decodificar.
 * Nota: necesita el payload CAMCORDER_... o acceso a la cámara del sistema.
 */
#include <3ds.h>
#include <stdio.h>
#include <string.h>
#include "qr.h"

int qr_scan(TVCAT_CONFIG *cfg) {
    (void)cfg;
    /* TODO: abrir cámara trasera (cam:u), capturar frame (CAMU_StartCapture +
     * CAMU_GetFrame) y pasar el buffer a quirc_decode.
     * Extraer JSON {server_url, pairing_token} y rellenar cfg.
     * Luego hacer network_pair(cfg) en main. */
    return -1;
}
