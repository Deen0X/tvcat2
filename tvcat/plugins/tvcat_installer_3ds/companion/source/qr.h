/*
 * TVCat Companion 3DS — qr.h
 * Escaneo de QR con la cámara (cam:u) + quirc (decodificador).
 */
#ifndef TVCAT_QR_H
#define TVCAT_QR_H

#include "config.h"

/* Captura un frame de la cámara trasera, lo decodifica (quirc),
 * extrae el JSON {server_url, pairing_token} y rellena cfg. */
int qr_scan(TVCAT_CONFIG *cfg);

#endif
