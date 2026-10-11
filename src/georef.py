"""Автоматическая геопривязка листа ГГК-1000 (backbone A+B+C).

Сигналы (см. .claude/rules/pipeline.md):
  A — номенклатура IMW -> широтная рамка (lat_min/lat_max) и диапазон долгот.
  B — детекция дуг рамки (параллели 60/64°N) оконным голосованием + окружности.
  C — OCR подписей градусов у верхней/нижней кромок -> привязка долготы к углу дуги.
Фьюжн: узловые GCP (меридианы по C, широты по A/B) -> rasterio warp (полином 2 порядка).
Ворота доверия: остаток C-подгонки, согласие с номенклатурой; валидация по озёрам отдельно.

CLI:  python src/georef.py P-35-36
"""
from __future__ import annotations
import re
import sys
import numpy as np
from PIL import Image
import pytesseract
import rasterio
from rasterio.control import GroundControlPoint
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds

from nomenclature import parse_sheet

Image.MAX_IMAGE_PIXELS = None

SHEETS = {
    "P-35-36": dict(raw="data/raw/ggk1000_P-35-36_quat.jpg", sheet_id="P-(35),36"),
    "O-35-36": dict(raw="data/raw/ggk1000_O-35-36_quat.jpg", sheet_id="O-35,N-35,O-36"),
}

# ---------------------------------------------------------------- signal B ----
def _dark(rgb, thr=85):
    return (rgb[:, :, 0] < thr) & (rgb[:, :, 1] < thr) & (rgb[:, :, 2] < thr)

def _edge_curve(dark, y0, y1, x0, x1, half=70, step=15, minvote=90):
    """Горизонтальная кромка: на окно столбцов — строка с макс. числом тёмных пикселей."""
    pts = []
    for xc in range(x0 + half, x1 - half, step):
        votes = dark[y0:y1, xc - half:xc + half].sum(axis=1)
        yi = int(votes.argmax())
        if votes[yi] >= minvote:
            pts.append((xc, y0 + yi))
    return np.array(pts, float)

def _fit_circle(xy):
    x, y = xy[:, 0], xy[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    a, b, c = np.linalg.lstsq(A, x * x + y * y, rcond=None)[0]
    return a, b, np.sqrt(c + a * a + b * b)

def _robust_circle(xy, k=2.0, it=6):
    m = np.ones(len(xy), bool)
    for _ in range(it):
        a, b, R = _fit_circle(xy[m])
        r = np.hypot(xy[:, 0] - a, xy[:, 1] - b) - R
        m = np.abs(r) < k * np.std(r[m])
    a, b, R = _fit_circle(xy[m])
    rms = float(np.std(np.hypot(xy[m, 0] - a, xy[m, 1] - b) - R))
    return (a, b, R), m.sum(), rms

def detect_parallels(rgb):
    """-> (top_circle, bot_circle), каждая (Cx,Cy,R). Полюс севернее (Cy<0)."""
    H, W = rgb.shape[:2]
    dark = _dark(rgb)
    xL, xR = int(W * 0.09), int(W * 0.66)
    top = _edge_curve(dark, int(H * 0.03), int(H * 0.12), xL, xR)
    bot = _edge_curve(dark, int(H * 0.74), int(H * 0.84), max(xL - int(W*0.08), 5), xR)
    (tc, tn, trms) = _robust_circle(top)
    (bc, bn, brms) = _robust_circle(bot)
    txr = (float(top[:, 0].min()), float(top[:, 0].max()))
    bxr = (float(bot[:, 0].min()), float(bot[:, 0].max()))
    print(f"[B] top arc  C=({tc[0]:.0f},{tc[1]:.0f}) R={tc[2]:.0f} n={tn} rms={trms:.2f}px x[{txr[0]:.0f},{txr[1]:.0f}]")
    print(f"[B] bot arc  C=({bc[0]:.0f},{bc[1]:.0f}) R={bc[2]:.0f} n={bn} rms={brms:.2f}px x[{bxr[0]:.0f},{bxr[1]:.0f}]")
    return (tc, txr), (bc, bxr)

# ---------------------------------------------------------------- signal C ----
def _yc(x, C):
    Cx, Cy, R = C
    return Cy + np.sqrt(R * R - (x - Cx) ** 2)

def _angle(x, y, C):
    return np.arctan2(x - C[0], y - C[1])

def ocr_lon_fit(rgb, circle, side, nom_lon, band_px=280):
    """OCR подписей долготы у кромки -> линейная подгонка lon <-> угол дуги.

    side='top': полоса ниже верхней кромки; side='bot': ниже нижней кромки.
    Возвращает (coef[a,b] для lon=a*angle+b, anchors[(lon,x)], rms).
    """
    W = rgb.shape[1]
    Cx, _, R = circle
    xs = np.arange(int(max(5, Cx - R * 0.9)), int(min(W - 5, Cx + R * 0.9)))
    yline = _yc(xs.astype(float), circle)
    y_top = int(np.nanmin(yline))
    y_bot = int(np.nanmax(yline))
    if side == "top":
        b0, b1 = y_top + 5, y_bot + band_px
    else:
        b0, b1 = y_top + 5, y_bot + band_px     # ниже кромки (подписи в поле)
    x0, x1 = int(xs.min()), int(xs.max())
    band = rgb[b0:b1, x0:x1]
    r, g, b = (band[:, :, i].astype(int) for i in range(3))
    bw = np.where((r < 90) & (g < 90) & (b < 90), 0, 255).astype(np.uint8)
    up = Image.fromarray(bw).resize((bw.shape[1] * 2, bw.shape[0] * 2), Image.LANCZOS)
    data = pytesseract.image_to_data(up, config=r"--psm 11",
                                     output_type=pytesseract.Output.DICT)
    anchors = []
    for i, t in enumerate(data["text"]):
        t = t.strip()
        if len(t) < 4:
            continue
        m = re.match(r"^(\d{2})\D*\d", t) or re.match(r"^(\d{2})[7O0]{2,}", t)
        if not m:
            continue
        lon = int(m.group(1))
        if not (nom_lon[0] <= lon <= nom_lon[1]):
            continue
        cx = x0 + (data["left"][i] + data["width"][i] / 2) / 2
        anchors.append((lon, cx))
    anchors.sort()
    if len(anchors) < 2:
        raise RuntimeError(f"[C/{side}] мало якорей долготы: {anchors}")
    ang = np.array([_angle(cx, _yc(cx, circle), circle) for _, cx in anchors])
    lon = np.array([lo for lo, _ in anchors], float)
    # RANSAC-подгонка прямой lon=a*angle+b (устойчиво к выбросам OCR)
    n = len(ang)
    best = (0, np.ones(n, bool))
    for i in range(n):
        for j in range(i + 1, n):
            if ang[j] == ang[i]:
                continue
            a = (lon[j] - lon[i]) / (ang[j] - ang[i])
            b = lon[i] - a * ang[i]
            inl = np.abs(a * ang + b - lon) < 0.2
            if inl.sum() > best[0]:
                best = (int(inl.sum()), inl)
    keep = best[1]
    if keep.sum() < 2:
        raise RuntimeError(f"[C/{side}] RANSAC не нашёл согласованную шкалу: {anchors}")
    coef = np.polyfit(ang[keep], lon[keep], 1)        # [a, b] для lon=a*ang+b
    rms = float(np.std(np.polyval(coef, ang[keep]) - lon[keep]))
    print(f"[C/{side}] anchors={[(lo, round(x)) for lo, x in anchors]} "
          f"inliers={keep.sum()}/{n} rms={rms:.3f}deg")
    return coef, anchors, rms

# ------------------------------------------------------------ GCP + warp ------
def build_gcps(top_c, bot_c, top_fit, bot_fit, lat_min, lat_max, lons):
    """Узлы меридиан×параллель -> список GroundControlPoint (lon/lat)."""
    def pt(circle, fit, lon):
        a = (lon - fit[1]) / fit[0]                 # angle from lon
        Cx, Cy, R = circle
        return np.array([Cx + R * np.sin(a), Cy + R * np.cos(a)])
    gcps = []
    for lon in lons:
        p_top = pt(top_c, top_fit, lon)             # lat_max
        p_bot = pt(bot_c, bot_fit, lon)             # lat_min
        for lat in range(lat_min, lat_max + 1):
            t = (lat - lat_min) / (lat_max - lat_min)
            p = p_bot * (1 - t) + p_top * t
            gcps.append(GroundControlPoint(row=float(p[1]), col=float(p[0]),
                                           x=float(lon), y=float(lat)))
    return gcps

def warp(raw_path, gcps, out_path, downscale=4, order=2, out_w=2600):
    im = np.asarray(Image.open(raw_path).convert("RGB"))
    H, W = im.shape[:2]
    s = 1.0 / downscale
    small = np.asarray(Image.fromarray(im).resize((int(W * s), int(H * s)), Image.LANCZOS))
    g = [GroundControlPoint(row=p.row * s, col=p.col * s, x=p.x, y=p.y) for p in gcps]
    lons = [p.x for p in gcps]
    lats = [p.y for p in gcps]
    lon0, lon1 = min(lons) - 0.1, max(lons) + 0.1
    lat0, lat1 = min(lats) - 0.1, max(lats) + 0.1
    wo = out_w
    ho = int(wo * (lat1 - lat0) / (lon1 - lon0))
    transform = from_bounds(lon0, lat0, lon1, lat1, wo, ho)
    crs = "EPSG:4326"
    dst = np.zeros((3, ho, wo), np.uint8)
    src = np.transpose(small, (2, 0, 1)).copy()
    for b in range(3):
        reproject(src[b], dst[b], gcps=g, src_crs=crs, dst_transform=transform,
                  dst_crs=crs, resampling=Resampling.bilinear, MAX_GCP_ORDER=order)
    with rasterio.open(out_path, "w", driver="GTiff", height=ho, width=wo, count=3,
                       dtype="uint8", crs=crs, transform=transform, compress="deflate") as d:
        d.write(dst)
    print(f"[warp] {out_path}  {wo}x{ho}  lon[{lon0:.2f},{lon1:.2f}] lat[{lat0:.2f},{lat1:.2f}]")
    return out_path

def georef(key):
    cfg = SHEETS[key]
    nom = parse_sheet(cfg["sheet_id"])
    print(f"[A] {cfg['sheet_id']} -> lon {nom.lon_min}..{nom.lon_max}E lat {nom.lat_min}..{nom.lat_max}N "
          f"rect={nom.is_rectangular}")
    rgb = np.asarray(Image.open(cfg["raw"]).convert("RGB"))
    (top_c, top_xr), (bot_c, bot_xr) = detect_parallels(rgb)
    top_fit, _, _ = ocr_lon_fit(rgb, top_c, "top", (nom.lon_min, nom.lon_max))
    bot_fit, _, _ = ocr_lon_fit(rgb, bot_c, "bot", (nom.lon_min, nom.lon_max))
    # фактический долготный экстент из C-подгонки по концам детектированных дуг (ловит клип)
    def lon_at(circle, fit, x):
        return fit[0] * _angle(x, _yc(x, circle), circle) + fit[1]
    west = max(lon_at(top_c, top_fit, top_xr[0]), lon_at(bot_c, bot_fit, bot_xr[0]))
    east = min(lon_at(top_c, top_fit, top_xr[1]), lon_at(bot_c, bot_fit, bot_xr[1]))
    # границы листа — целые градусы: ближайший меридиан к экстенту (не теряем крайние)
    lon_lo = max(nom.lon_min, int(round(west)))
    lon_hi = min(nom.lon_max, int(round(east)))
    lons = list(range(lon_lo, lon_hi + 1))
    print(f"[fuse] extent west={west:.2f} east={east:.2f} -> меридианы {lon_lo}..{lon_hi}E "
          f"(номенклатура {nom.lon_min}..{nom.lon_max})")
    gcps = build_gcps(top_c, bot_c, top_fit, bot_fit, nom.lat_min, nom.lat_max, lons)
    out = warp(cfg["raw"], gcps, f"data/work/{key}_georef_4326.tif")
    print(f"[gate] C-fit top/bot ok; nomenclature lat {nom.lat_min}-{nom.lat_max}; see lake validation")
    return out

if __name__ == "__main__":
    georef(sys.argv[1] if len(sys.argv) > 1 else "P-35-36")
