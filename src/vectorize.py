"""Stage ④–⑤ — сегментация ВСЕХ единиц легенды по цвету + полигонизация в GeoJSON.

Цель map-vectorize — векторизовать ВСЕ разделы легенды (не только пески). Модель класса —
**свотч легенды**: каждый свотч = центроид цвета. Свотчи с распознанным генезисом
группируются под общим label=генезис (несколько оттенков одного генезиса — одна единица);
свотчи с провалом OCR генезиса (`?`) держатся РАЗДЕЛЬНО по цвету (label `?N`), иначе
разноцветные неизвестные единицы схлопнулись бы в одну (на листе O таких ~⅓).

Пиксель относится к классу ближайшего по Lab центроида среди ВСЕХ свотчей (nearest-centroid,
убирает бликование лучше порога). descreening (median) гасит растр CMYK; морфология чинит
оверпринт; `features.shapes` даёт полигоны сразу в lon/lat; shapely упрощает/фильтрует.
Результат — `output/<key>_<tag>.geojson` (EPSG:4326), атрибуты: unit (генезис), label
(id класса), index (OCR-текст), rating (★ боровика — линза потребителя), color.

Осознанно приближённо (см. pipeline.md): цвет ≠ генетический индекс. Единицы РАЗНОГО цвета
разделяются; ОДНОГО цвета, разного индекса — нет (подтверждённый ресёрчем открытый фронт:
OCR индексов на теле карты, см. docs/research-sota-full-vectorization.md).
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
from skimage.morphology import closing, disk, remove_small_objects
from scipy.ndimage import median_filter
from shapely.geometry import shape, mapping

from georef import SHEETS, georef
from legend import RATING, extract


def _lab(rgb_u8):
    return rgb2lab(np.asarray(rgb_u8, float).reshape(1, 1, 3) / 255.0)[0, 0]


def _round_coords(obj, nd=5):
    """Округлить координаты геометрии до nd знаков (~1 м на 5) — режет вес GeoJSON.

    Хранить ~15 знаков бессмысленно: геопривязка точна до сотен метров — км (см.
    pipeline.md), 5 знаков уже на 2 порядка точнее данных.
    """
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(c), nd) for c in obj]
        return [_round_coords(x, nd) for x in obj]
    return obj


def build_classes(rows, merge_eps=3.0):
    """rows [(y0,y1,rgb,gen,txt)] -> (labels, cents, meta, order).

    Каждый свотч -> центроид (Lab). Известный генезис -> общий label=генезис (несколько
    центроидов под одним label). `?` -> свой label `?N` на свотч. Свотчи почти одного
    цвета (Lab < merge_eps) сливаются в уже добавленный класс — не плодим дубль-маски
    (это и есть принятый предел «цвет ≠ индекс»).

    -> labels[list[str]] и cents[list[np.ndarray]] (параллельны, по центроидам),
       meta{label: {genesis, index, rgb}}, order[list[str]] (уникальные label по чтению).
    """
    labels, cents, meta, order = [], [], {}, []
    qn = 0
    for _y0, _y1, rgb, gen, txt in rows:
        lab = _lab(rgb)
        if any(((lab - c) ** 2).sum() < merge_eps ** 2 for c in cents):
            continue                                   # почти-дубль цвета — пропустить
        key = gen if gen != "?" else f"?{(qn := qn + 1)}"
        labels.append(key)
        cents.append(lab)
        if key not in meta:
            meta[key] = {"genesis": gen, "index": txt.strip(),
                         "rgb": tuple(int(v) for v in rgb)}
            order.append(key)
    return labels, cents, meta, order


def classify_pixels(lab_img, labels, cents, max_tol):
    """Каждому пикселю — label ближайшего по Lab центроида (в пределах max_tol).

    -> (label_px[str-array], ok_mask). ok=False у фона/текста/оверпринта (дальше max_tol).
    """
    best = np.full(lab_img.shape[:2], 1e18)
    idx = np.full(lab_img.shape[:2], -1, int)
    for i, t in enumerate(cents):
        d = ((lab_img - t) ** 2).sum(axis=2)
        u = d < best
        best[u] = d[u]
        idx[u] = i
    ok = best < (max_tol ** 2)
    lab_arr = np.array(labels, dtype=object)
    label_px = np.where(idx >= 0, lab_arr[idx.clip(0)], "")
    return label_px, ok


def vectorize(key, units=None, downscale=2, max_tol=28.0,
              min_area_km2=0.5, simplify_m=150.0):
    """units=None -> ВСЕ единицы легенды; units=("f","lg") -> только эти генезисы."""
    raw = SHEETS[key]["raw"]
    _palette, rows = extract(raw)
    labels, cents, meta, order = build_classes(rows)
    if units is None:
        targets, tag = order, "all"
    else:
        targets = [lb for lb in order if meta[lb]["genesis"] in units]
        tag = "_".join(units)

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
    label_px, ok = classify_pixels(lab, labels, cents, max_tol)

    feats = []
    print(f"[{key}] классов на вывод: {len(targets)} из {len(order)} "
          f"(генезисы: {sorted({meta[lb]['genesis'] for lb in order})})")
    for lb in targets:
        m = (label_px == lb) & ok
        m = closing(m, disk(2))
        m = remove_small_objects(m, max_size=min_px - 1)   # удалить объекты < min_px px
        g = meta[lb]
        n = 0
        for geom, _val in shapes(m.astype(np.uint8), mask=m, transform=T):
            poly = shape(geom).simplify(simplify_deg)
            if poly.is_empty or poly.area * deg2_km2 < min_area_km2:
                continue
            geojson_geom = mapping(poly)
            geojson_geom["coordinates"] = _round_coords(geojson_geom["coordinates"])
            feats.append({"type": "Feature",
                          "properties": {"unit": g["genesis"], "label": lb,
                                         "index": g["index"],
                                         "rating": RATING.get(g["genesis"]),
                                         "color": "%d,%d,%d" % g["rgb"]},
                          "geometry": geojson_geom})
            n += 1
        if int(m.sum()) or n:
            print(f"  [{lb:4s} {g['genesis']:2s}] RGB={g['rgb']} "
                  f"маска {int(m.sum())}px -> {n} полигонов")

    fc = {"type": "FeatureCollection",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
          "features": feats}
    out = f"output/{key}_{tag}.geojson"
    with open(out, "w") as f:
        json.dump(fc, f)
    area = sum(shape(ft["geometry"]).area * deg2_km2 for ft in feats)
    print(f"ИТОГО: {len(feats)} полигонов, ~{area:.0f} км² -> {out}")
    return out


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "P-35-36"
    arg = sys.argv[2] if len(sys.argv) > 2 else "all"
    units = None if arg in ("all", "") else tuple(arg.split(","))
    vectorize(key, units)
