/*
 * TVCat Companion 3DS — main.c
 */
#include <3ds.h>
#include <citro2d.h>
#include <string.h>
#include <stdio.h>

#include "config.h"
#include "network.h"
#include "download.h"
#include "qr.h"

enum { SCREEN_INIT=0, SCREEN_PAIR, SCREEN_MAIN, SCREEN_DOWNLOAD };

static int g_screen = SCREEN_INIT;
static C3D_RenderTarget *top = NULL, *bottom = NULL;
static C2D_TextBuf g_textbuf = NULL;
static TVCAT_CONFIG g_cfg;
static bool g_paired = false;
static char g_status[256] = "Inicializando...";

static void draw_text(float x, float y, float z, float sx, float sy, u32 color, const char *str) {
    if (!str) return;
    if (!g_textbuf) g_textbuf = C2D_TextBufNew(4096);
    C2D_Text txt;
    C2D_TextParse(&txt, g_textbuf, str);
    C2D_TextOptimize(&txt);
    C2D_DrawText(&txt, C2D_AlignLeft, x, y, z, sx, sy, color);
}

int main(void) {
    gfxInitDefault();

    /* 1. Inicializar el subsistema de la Tarjeta SD ANTES de cualquier fopen/sdmc: */
    if (R_FAILED(fsInit())) {
        snprintf(g_status, sizeof(g_status), "Error: fsInit fallo");
    }

    C3D_Init(C3D_DEFAULT_CMDBUF_SIZE);
    C2D_Init(C2D_DEFAULT_MAX_OBJECTS);
    C2D_Prepare();
    top = C2D_CreateScreenTarget(GFX_TOP, GFX_LEFT);
    bottom = C2D_CreateScreenTarget(GFX_BOTTOM, GFX_LEFT);
    g_textbuf = C2D_TextBufNew(4096);

    /* 2. Ahora SI podemos acceder a la SD */
    config_load(&g_cfg, "sdmc:/tvcat_companion.cfg");

    /* 3. Inicializar red (socInit con buffer alineado) */
    if (network_init() != 0) {
        snprintf(g_status, sizeof(g_status), "Error: red SOC no disponible");
    }

    while (aptMainLoop()) {
        hidScanInput();
        u32 kDown = hidKeysDown();
        if (kDown & KEY_A) {
            qr_scan(&g_cfg);
            network_parse_short_url(&g_cfg);
            g_paired = true;
            snprintf(g_status, sizeof(g_status), "Emparejado: %s", g_cfg.console_id);
        }
        if (g_cfg.server_url[0] != '\0' && g_paired) {
            network_heartbeat(&g_cfg, g_status);
        }

        C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
        C2D_TargetClear(top, C2D_Color32(0x0d, 0x0d, 0x0f, 0xff));
        C2D_TargetClear(bottom, C2D_Color32(0x0d, 0x0d, 0x0f, 0xff));
        C2D_SceneBegin(top);
        draw_text(20, 20, 0.5f, 1.0f, 1.0f, C2D_Color32(0xff, 0xff, 0xff, 0xff), "TVCat Companion 3DS");
        draw_text(20, 50, 0.5f, 0.6f, 0.6f, C2D_Color32(0xa1, 0xa1, 0xaa, 0xff), g_status);
        draw_text(20, 80, 0.5f, 0.6f, 0.6f, C2D_Color32(0xa1, 0xa1, 0xaa, 0xff),
                  g_cfg.server_url);
        C2D_SceneBegin(bottom);
        draw_text(10, 10, 0.5f, 0.5f, 0.5f, C2D_Color32(0xa1, 0xa1, 0xaa, 0xff),
                  "A: Escanear QR    START: Salir");
        C3D_FrameEnd(0);
        C2D_TextBufClear(g_textbuf);
        gspWaitForVBlank();
    }

    /* Limpieza */
    network_cleanup();
    C2D_Fini(); C3D_Fini();
    fsExit();
    gfxExit();
    return 0;
}
