"""Exporta polígonos de lagunas SWOT + indicadores de nivel + series temporales a lagunas.js.

Replica la lógica de operational.ipynb (filtros y build_status_layer) a partir de
04 - SWOT\\output\\wse_water_shapes_10_ha.nc. Los originales no se modifican.
Ejecutar: python exportar_lagunas.py   (lee ~12 GB, tarda unos minutos)
"""
import json
import warnings
from pathlib import Path

import geopandas as gpd
import netCDF4 as nc
import numpy as np
import pandas as pd

SWOT = Path(r"C:\Users\joako\OneDrive\1 - Posgrado\Workspace\04 - SWOT")
NC_PATH = SWOT / "output" / "wse_water_shapes_10_ha.nc"
SHP_PATH = SWOT / "shp" / "water_shapes" / "water_shapes.shp"
SALIDA = Path(__file__).parent / "lagunas.js"

MIN_AREA_HA = 10
MAX_HEIGHT, MIN_DENSITY, MAX_STD = 300, 3, 0.2
SIMPLIFICAR_M = 15
CHUNK = 250
EPOCH = pd.Timestamp("2024-01-01")

warnings.filterwarnings("ignore")

# --- Polígonos (mismo filtrado que el notebook; el índice es el id de 'polygon' del .nc)
gdf = gpd.read_file(SHP_PATH).to_crs(5346)
gdf["area_ha"] = gdf.area * 1e-4
gdf = gdf[gdf["area_ha"] >= MIN_AREA_HA]
print("polígonos:", len(gdf))

# --- Observaciones válidas desde el .nc, por bloques de tiempo
ds = nc.Dataset(NC_PATH)
poly_ids = ds["polygon"][:].data
assert len(poly_ids) == len(gdf) and (poly_ids == gdf.index.to_numpy()).all(), "ids no coinciden con el .nc"

tiempo = pd.to_datetime(
    nc.num2date(ds["time"][:], ds["time"].units, only_use_cftime_datetimes=False, only_use_python_datetimes=True)
)
n_t = len(tiempo)
filas_t, filas_p, filas_v = [], [], []
for a in range(0, n_t, CHUNK):
    b = min(a + CHUNK, n_t)
    get = lambda v: np.ma.filled(ds[v][a:b, :].astype("float64"), np.nan)
    m, s, c, ar = get("mean"), get("std"), get("count"), get("area_ha")
    with np.errstate(invalid="ignore", divide="ignore"):
        ok = (m < MAX_HEIGHT) & (c / ar > MIN_DENSITY) & (s < MAX_STD) & np.isfinite(m)
    t, p = np.nonzero(ok)
    filas_t.append(t + a)
    filas_p.append(p)
    filas_v.append(m[ok])
    print(f"{b}/{n_t}", end="\r")
ds.close()

obs = pd.DataFrame({
    "t": np.concatenate(filas_t), "p": np.concatenate(filas_p), "v": np.concatenate(filas_v),
})
obs["fecha"] = tiempo[obs["t"].to_numpy()]
print("\nobservaciones válidas:", len(obs), " lagunas con datos:", obs["p"].nunique())

# --- Indicadores (idénticos a build_status_layer)
obs["mes"] = obs["fecha"].dt.to_period("M").dt.to_timestamp()
mensual = obs.groupby(["mes", "p"])["v"].mean().unstack("p")
mensual = mensual.reindex(pd.date_range(mensual.index.min(), mensual.index.max(), freq="MS"))
mensual = mensual.reindex(columns=range(len(gdf)))

ref = mensual.index[-1]
nivel = lambda t: mensual.loc[t] if t in mensual.index else pd.Series(np.nan, index=mensual.columns)
ahora = nivel(ref)
props = pd.DataFrame({
    "area_ha": gdf["area_ha"].to_numpy().round(1),
    "wse_m": ahora,
    "d_month_m": ahora - nivel(ref - pd.DateOffset(months=1)),
    "d_3m_m": ahora - nivel(ref - pd.DateOffset(months=3)),
    "d_yoy_m": ahora - nivel(ref - pd.DateOffset(years=1)),
    "pctile": mensual.rank(pct=True).loc[ref] * 100,
    "n_months": mensual.notna().sum(),
}).round(3)
props.index = gdf.index

# --- Geometrías en EPSG:4326 simplificadas
con_datos = gdf.index[np.isin(np.arange(len(gdf)), obs["p"].unique())]  # sin datos no hay nada que mostrar
geo = gdf.loc[con_datos, ["geometry"]].copy()
geo["geometry"] = geo.geometry.simplify(SIMPLIFICAR_M, preserve_topology=True)
geo = geo.to_crs(4326)
geo["geometry"] = geo.geometry.set_precision(1e-5)
features = []
for pid, geom in geo.geometry.items():
    pr = {"id": int(pid)}
    for k, v in props.loc[pid].items():
        if pd.notna(v):
            pr[k] = float(v) if k not in ("n_months",) else int(v)
    features.append({"type": "Feature", "properties": pr, "geometry": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"]})

# --- Variaciones de medias mensuales; los meses sin comparación válida quedan vacíos
variacion_mensual = mensual - mensual.shift(1)
variacion_interanual = mensual - mensual.shift(12)
meses = ((mensual.index - EPOCH).days).tolist()
series = {}
for p in obs["p"].unique():
    series[int(poly_ids[p])] = [
        [round(float(v), 3) if pd.notna(v) else None for v in variacion_mensual[p]],
        [round(float(v), 3) if pd.notna(v) else None for v in variacion_interanual[p]],
    ]

def rango(col, q=0.95):
    return round(float(props[col].abs().quantile(q)), 2)

meta = {
    "ref_month": ref.strftime("%Y-%m"),
    "epoch": EPOCH.strftime("%Y-%m-%d"),
    "meses": meses,
    "rango": {"d_month_m": rango("d_month_m"), "d_3m_m": rango("d_3m_m"), "d_yoy_m": rango("d_yoy_m")},
    "wse": [round(float(props["wse_m"].quantile(q)), 1) for q in (0.02, 0.98)],
}
dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
SALIDA.write_text(
    f"const LAGUNAS_META = {dump(meta)};\n"
    f"const LAGUNAS = {dump({'type': 'FeatureCollection', 'features': features})};\n"
    f"const LAGUNAS_SERIES = {dump(series)};\n",
    encoding="utf-8",
)
print(meta)
print(f"{SALIDA} {SALIDA.stat().st_size / 1e6:.1f} MB")
