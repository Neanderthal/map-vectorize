"""Stage ④–⑤ — сегментация песчаных единиц по цвету + полигонизация в GeoJSON.

Использует палитру легенды (`legend.extract`) и привязанный растр (`georef`, nearest —
сохраняет точные цвета заливок). descreening (median) убирает растр CMYK; маска по
Lab-расстоянию к цветам целевого генезиса; морфология чинит оверпринт; `features.shapes`
даёт полигоны сразу в lon/lat; shapely упрощает/фильтрует по площади. Результат — в
`output/<sheet>_<genera>.geojson` (EPSG:4326), атрибуты: unit, rating (★ боровика).

Осознанно приближённо (см. pipeline.md): цвет ≠ генетический индекс.
"""
from __future__ import annotations
import json
import math
import sys
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import Resampling
from skimage.color import rgb2lab
from skimage.morphology import binary_closing, disk, remove_small_objects
from scipy.ndimage import median_filter
from shapely.geometry import shape, mapping

from georef import SHEETS, georef
from legend import RATING, extract


def _lab(rgb_u8):
    return rgb2lab(np.asarray(rgb_u8, float).reshape(1, 1, 3) / 255.0)[0, 0]


def classify_genera(lab, palette, max_tol):
    """Каждому пикселю — ближайший цвет среди ВСЕХ генезисов (nearest-centroid).

    Пиксель относится к генезису, только если тот ему БЛИЖЕ остальных — это убирает
    бликование (порог по расстоянию ловил чужие единицы). -> (gen_of_pixel[str|''], ok_mask).
    """
    cents, gens = [], []
    for g, cols in palette.items():
        if g == "?":
            continue
        for c in cols:
            cents.append(_lab(c))
            gens.append(g)
    gens = np.array(gens, dtype=object)
    best = np.full(lab.shape[:2], 1e18)
    idx = np.full(lab.shape[:2], -1, int)
    for i, t in enumerate(cents):
        d = ((lab - t) ** 2).sum(axis=2)
        u = d < best
        best[u] = d[u]
        idx[u] = i
    ok = best < (max_tol ** 2)                      # исключить фон/текст/оверпринт
    gen_px = np.where(idx >= 0, gens[idx.clip(0)], "")
    return gen_px, ok


def vectorize(key, genera=("f",), downscale=2, max_tol=28.0,
              min_area_km2=0.5, simplify_m=150.0):
    raw = SHEETS[key]["raw"]
    palette, _ = extract(raw)
    tif = georef(key, downscale=downscale, resampling=Resampling.nearest, out_suffix="_seg")
    ds = rasterio.open(tif)
    rgb = ds.read().transpose(1, 2, 0)
    T = ds.transform
    b = ds.bounds
    midlat = (b.bottom + b.top) / 2
    km_lat = 111.195
    km_lon = 111.195 * math.cos(math.radians(midlat))
    px_km2 = abs(T.a) * km_lon * abs(T.e) * km_lat
    deg2_km2 = km_lon * km_lat
    min_px = max(4, int(min_area_km2 / px_km2))
    simplify_deg = simplify_m / 111_000.0

    # descreening (median) — подавить полутоновый растр CMYK
    rgbf = np.dstack([median_filter(rgb[:, :, c], size=3) for c in range(3)])
    lab = rgb2lab(rgbf.astype(np.float64) / 255.0)
    gen_px, ok = classify_genera(lab, palette, max_tol)

    feats = []
    for gen in genera:
        if gen not in palette:
            print(f"  [{gen}] нет цветов в легенде — пропуск")
            continue
        m = (gen_px == gen) & ok
        m = binary_closing(m, disk(2))
        m = remove_small_objects(m, min_px)
        n = 0
        for geom, _val in shapes(m.astype(np.uint8), mask=m, transform=T):
            poly = shape(geom).simplify(simplify_deg)
            if poly.is_empty or poly.area * deg2_km2 < min_area_km2:
                continue
            feats.append({"type": "Feature",
                          "properties": {"unit": gen, "rating": RATING.get(gen)},
                          "geometry": mapping(poly)})
            n += 1
        print(f"  [{gen}] {len(palette[gen])} цветов, маска {int(m.sum())}px -> {n} полигонов")

    fc = {"type": "FeatureCollection",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
          "features": feats}
    out = f"output/{key}_{'_'.join(genera)}.geojson"
    with open(out, "w") as f:
        json.dump(fc, f)
    area = sum(shape(ft["geometry"]).area * deg2_km2 for ft in feats)
    print(f"ИТОГО: {len(feats)} полигонов, ~{area:.0f} км² -> {out}")
    return out


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "P-35-36"
    genera = tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else ("f",)
    vectorize(key, genera)
