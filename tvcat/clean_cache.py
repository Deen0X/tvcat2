import sqlite3
import os
import glob
import sys

# Base de TVCat 2
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, 'data')
DB_PATH = os.path.join(DATA_DIR, 'tvcat.db')

# Directorios de caché HLS (definidos en gateway.py) — gateway usa PROJECT_ROOT/data (tvcat2/data)
# PROJECT_ROOT = tvcat2/ (padre de tvcat/)
PROJECT_ROOT = os.path.abspath(os.path.join(BASE, ".."))
HLS_DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
HLS_CACHE_DIR = os.path.join(HLS_DATA_DIR, 'cache')          # sparse .mp4 por episodio (gateway: _HLS_CACHE_DIR)
HLS_SEGMENTS_DIR = os.path.join(HLS_DATA_DIR, 'hls_segments') # segmentos .ts (gateway: _HLS_SEG_DIR)
HLS_SUBS_DIR = os.path.join(HLS_DATA_DIR, 'hls_subs')          # subtítulos (gateway: _HLS_SUBS_DIR)

# Directorios legacy (BASE/data) — mantener por compatibilidad
CACHE_DIR = os.path.join(DATA_DIR, 'cache')          # sparse .mp4 por episodio
SEGMENTS_DIR = os.path.join(DATA_DIR, 'hls_segments') # segmentos .ts generados
SUBS_DIR = os.path.join(DATA_DIR, 'hls_subs')          # subtítulos .srt/.vtt
NORM_DIR = os.path.join(SEGMENTS_DIR, 'norm')          # MP4 normalizados


def clean_all_cache():
    total_deleted = 0

    # 1. Limpiar la tabla hls_cache del sistema (fuente de verdad del bitmap)
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            n = cur.execute("DELETE FROM hls_cache").rowcount
            conn.commit()
            conn.close()
            total_deleted += n
            print(f"hls_cache: {n} filas eliminadas")
        except Exception as e:
            print(f"  (aviso) hls_cache: {e}")

    # 2. Limpiar ficheros sparse y sidecars en data/cache/ (AMBAS ubicaciones: HLS real y legacy)
    for _dir, _label in [(HLS_CACHE_DIR, "cache (HLS)"), (CACHE_DIR, "cache (legacy)")]:
        if os.path.isdir(_dir):
            removed = 0
            for f in glob.glob(os.path.join(_dir, '*')):
                try:
                    os.remove(f)
                    removed += 1
                except Exception as e:
                    print(f"  (aviso) no se pudo borrar {f}: {e}")
            total_deleted += removed
            print(f"{_label}: {removed} ficheros eliminados (sparse, .chunks, sidecars)")

    # 3. Limpiar segmentos generados en data/hls_segments/ (AMBAS ubicaciones)
    for _dir, _label in [(HLS_SEGMENTS_DIR, "hls_segments (HLS)"), (SEGMENTS_DIR, "hls_segments (legacy)")]:
        if os.path.isdir(_dir):
            removed = 0
            for f in glob.glob(os.path.join(_dir, '*')):
                try:
                    if os.path.isdir(f):
                        import shutil
                        shutil.rmtree(f)
                        removed += 1
                    else:
                        os.remove(f)
                        removed += 1
                except Exception as e:
                    print(f"  (aviso) no se pudo borrar {f}: {e}")
            total_deleted += removed
            print(f"{_label}: {removed} elementos eliminados")

    # 4. Limpiar subtítulos en data/hls_subs/ (AMBAS ubicaciones)
    for _dir, _label in [(HLS_SUBS_DIR, "hls_subs (HLS)"), (SUBS_DIR, "hls_subs (legacy)")]:
        if os.path.isdir(_dir):
            removed = 0
            for f in glob.glob(os.path.join(_dir, '*')):
                try:
                    os.remove(f)
                    removed += 1
                except Exception as e:
                    print(f"  (aviso) no se pudo borrar {f}: {e}")
            total_deleted += removed
            print(f"{_label}: {removed} ficheros eliminados")

    # 5. Limpiar MP4 normalizados (norm/)
    if os.path.isdir(NORM_DIR):
        removed = 0
        for f in glob.glob(os.path.join(NORM_DIR, '*')):
            try:
                os.remove(f)
                removed += 1
            except Exception as e:
                print(f"  (aviso) no se pudo borrar norm/{f}: {e}")
        total_deleted += removed
        print(f"hls_segments/norm/: {removed} ficheros eliminados")

    print(f"\nLimpieza completada: {total_deleted} elementos eliminados.")
    if total_deleted > 0:
        print("IMPORTANTE: Reinicia el gateway para que se descarten los mapas en memoria (_HLS_SPARSE/_HLS_SEG_CACHE).")
    else:
        print("No había caché residual. Reinicia el gateway igualmente para asegurar estado limpio.")


if __name__ == '__main__':
    # Acción: limpiar TODO (por defecto, sin argumento). Comodín global, sin título fijo.
    if len(sys.argv) > 1 and sys.argv[1] == '--dry-run':
        print("DRY-RUN: mostrar solo lo que se borraría.")
        for d in (CACHE_DIR, SEGMENTS_DIR, SUBS_DIR, NORM_DIR):
            if os.path.isdir(d):
                archivos = glob.glob(os.path.join(d, '*'))
                print(f"  {d}: {len(archivos)} elementos")
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            n = conn.execute("SELECT COUNT(*) FROM hls_cache").fetchone()[0]
            conn.close()
            print(f"  hls_cache: {n} filas")
    else:
        clean_all_cache()
