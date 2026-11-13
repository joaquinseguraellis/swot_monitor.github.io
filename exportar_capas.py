"""Convierte los shapefiles de APRHI-PIHC (y subcarpetas) a capas.js (GeoJSON en EPSG:4326).
Los originales no se modifican. Ejecutar: python exportar_capas.py
"""
import json
import warnings
from pathlib import Path

import geopandas as gpd

ORIGEN = Path(r"C:\Users\joako\OneDrive\1 - Posgrado\Workspace\00 - Datos\Informacion Geoespacial\APRHI-PIHC")
SALIDA = Path(__file__).parent / "capas.js"
TOLERANCIA_M = 25  # simplificación en el CRS original (metros)

# Estilo por tipo de geometría; orden = orden de apilado (primero abajo)
ORDEN = ["Unidades_de_gestion_hidrica", "Cuencas_interprovinciales", "Cuencas_Interprovinciales_en_Córdoba_1_1",
         "Subcuencas", "Subcuenca_Embalses", "Cuerpos_de_agua_naturales", "Embalses", "Cursos_de_agua_2021"]
COLORES = ["#7b3294", "#d95f02", "#e6ab02", "#1b9e77", "#666666", "#56b4e9", "#0072b2", "#08306b"]

warnings.filterwarnings("ignore")
archivos = sorted(ORIGEN.rglob("*.shp"), key=lambda f: ORDEN.index(f.stem) if f.stem in ORDEN else 99)
capas = []
for i, shp in enumerate(archivos):
    gdf = gpd.read_file(shp)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    gdf["geometry"] = gdf.geometry.simplify(TOLERANCIA_M, preserve_topology=True)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.set_precision(1e-5)
    gj = json.loads(gdf.to_json(drop_id=True))
    capas.append({
        "nombre": shp.stem.replace("_", " "),
        "tipo": "linea" if "Line" in gdf.geom_type.iloc[0] else "poligono",
        "color": COLORES[i % len(COLORES)],
        "datos": gj,
    })
    print(shp.stem, len(gdf))

SALIDA.write_text("const CAPAS = " + json.dumps(capas, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
print(f"{SALIDA} {SALIDA.stat().st_size / 1e6:.1f} MB")
