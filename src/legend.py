"""Stage ③ — авто-извлечение легенды листа ГГК-1000.

Детектирует цветовые свотчи в панели легенды (колонка слева), сэмплирует RGB заливки
и распознаёт индекс ВНУТРИ свотча (OCR), классифицирует по генезису. Возвращает палитру
{генезис: [RGB,...]} — для сегментации целевых песчаных единиц (f, v, lg).

Зона риска (ресёрч): OCR кириллических/кодовых индексов. Поэтому индекс нужен лишь для
КЛАССИФИКАЦИИ по первой букве генезиса (f/lg/g/l/…), а не для точного кода — это устойчиво.
"""
from __future__ import annotations
import re
import sys
import numpy as np
from PIL import Image
import pytesseract

from georef import map_bbox, _colorful

Image.MAX_IMAGE_PIXELS = None

# порядок важен: 'lg'/'la'/'al' проверяем раньше одиночных 'l'/'a'
GENESIS = ["lg", "la", "al", "gt", "f", "g", "l", "v", "e", "d", "m", "b", "a", "p", "t", "n"]
SAND = {"f", "v", "lg"}          # целевые песчаные (lg — ± только песчаные фации)
RATING = {"f": 3, "v": 3, "lg": 1}   # ★ боровика (см. legend.md)


def classify(ocr_text: str) -> str:
    """OCR-текст индекса -> буква генезиса по началу (f, lg, g, …) или '?'."""
    t = re.sub(r"[^a-z]", "", ocr_text.lower())
    for gen in GENESIS:
        if t.startswith(gen):
            return gen
    return "?"


def detect_swatches(A: np.ndarray, lx0: int):
    """Свотчи в легенде (x >= lx0): -> [(y0, y1, rgb, ocr_text)]."""
    W = A.shape[1]
    leg = A[:, lx0:W]
    col = _colorful(leg)
    colc = col.sum(axis=0)
    xs = np.where(colc > 0.25 * colc.max())[0]
    if len(xs) == 0:
        return []
    band = np.split(xs, np.where(np.diff(xs) > 30)[0] + 1)[0]   # первая колонка слева
    bx0, bx1 = int(band.min()), int(band.max())
    rowc = col[:, bx0:bx1].sum(axis=1)
    on = rowc > 0.5 * (bx1 - bx0)
    runs, s = [], None
    for y in range(len(on)):
        if on[y] and s is None:
            s = y
        elif not on[y] and s is not None:
            if y - s >= 40:
                runs.append((s, y))
            s = None
    if s is not None:
        runs.append((s, len(on)))

    out = []
    for y0, y1 in runs:
        sub = A[y0:y1, lx0 + bx0:lx0 + bx1]
        c = _colorful(sub)
        px = sub[c]
        if len(px) < 50:
            continue
        rgb = tuple(int(v) for v in np.median(px, axis=0))
        g = np.asarray(Image.fromarray(sub).convert("L"))
        up = Image.fromarray(g).resize((g.shape[1] * 3, g.shape[0] * 3), Image.LANCZOS)
        txt = pytesseract.image_to_string(up, config=r"--psm 7").strip().replace("\n", " ")
        out.append((y0, y1, rgb, txt))
    return out


def extract(path: str):
    """-> (palette {генезис: [RGB,...]}, swatches [(y0,y1,rgb,gen,ocr)])."""
    A = np.asarray(Image.open(path).convert("RGB"))
    _, mright, _, _ = map_bbox(A)
    sw = detect_swatches(A, mright + 30)
    palette: dict[str, list[tuple]] = {}
    rows = []
    for y0, y1, rgb, txt in sw:
        gen = classify(txt)
        rows.append((y0, y1, rgb, gen, txt))
        palette.setdefault(gen, []).append(rgb)
    return palette, rows


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/ggk1000_P-35-36_quat.jpg"
    palette, rows = extract(path)
    print(f"{len(rows)} свотчей; генезисы: "
          f"{ {g: len(v) for g, v in sorted(palette.items())} }")
    print("\nПесчаные целевые единицы (f/v/lg) — палитра для сегментации:")
    for gen in ("f", "v", "lg"):
        for rgb in palette.get(gen, []):
            print(f"  {gen:3s} RGB={rgb}  ★{RATING[gen]}")
