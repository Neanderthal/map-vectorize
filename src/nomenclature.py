"""Signal A — разграфка/номенклатура IMW (СССР/РФ) 1:1 000 000.

Из обозначения листа (напр. ``P-(35),36``) детерминированно выводит градусную рамку:
широтный пояс по букве ряда (4° на ряд), долготный диапазон по номеру(ам) колонны
(6° на колонну, отсчёт от 180°). Поддерживает сдвоенные/составные листы (несколько
ячеек через запятую, скобки у частичной колонны) и кириллические омоглифы букв рядов.

Это ТЕОРЕТИЧЕСКАЯ рамка из номенклатуры. Реальный печатный лист может быть обрезан
(напр. запад по госгранице) — фактические подписи градусов снимает сигнал C (OCR),
а номенклатура служит опорой/проверкой диапазона.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# Кириллические омоглифы -> латиница (буквы рядов IMW латинские A..V)
_CYR2LAT = {"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
            "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "U", "Х": "X"}


def _row_band(letter: str) -> tuple[int, int]:
    """Буква ряда -> (lat_min, lat_max), северное полушарие. A=0-4°, B=4-8°, ... P=60-64°."""
    idx = ord(letter) - ord("A") + 1          # A -> 1
    if not 1 <= idx <= 22:                      # A..V покрывают 0..88°N
        raise ValueError(f"ряд вне диапазона A..V: {letter!r}")
    return (idx - 1) * 4, idx * 4


def _col_band(col: int) -> tuple[int, int]:
    """Номер колонны -> (lon_min, lon_max). Колонна k: [(k-31)*6, (k-30)*6]."""
    if not 1 <= col <= 60:
        raise ValueError(f"колонна вне 1..60: {col}")
    return (col - 31) * 6, (col - 30) * 6


@dataclass
class SheetFrame:
    sheet_id: str
    lon_min: int
    lon_max: int
    lat_min: int
    lat_max: int
    cells: list[tuple[str, int]]          # [(row_letter, column), ...]

    @property
    def meridians(self) -> list[int]:
        return list(range(self.lon_min, self.lon_max + 1))

    @property
    def parallels(self) -> list[int]:
        return list(range(self.lat_min, self.lat_max + 1))

    @property
    def is_rectangular(self) -> bool:
        """Union ячеек образует один прямоугольник (иначе — сложный составной лист)."""
        cols = {c for _, c in self.cells}
        rows = {r for r, _ in self.cells}
        return len(self.cells) == len(cols) * len(rows)


def parse_sheet(sheet_id: str) -> SheetFrame:
    """``P-(35),36`` -> SheetFrame(lon 24..36, lat 60..64).

    Токены через запятую; номер колонны без буквы наследует ряд предыдущего токена.
    Скобки у частичной колонны игнорируются (номенклатурная рамка — полный диапазон).
    """
    s = sheet_id.strip().upper()
    s = "".join(_CYR2LAT.get(ch, ch) for ch in s)
    s = s.replace("(", "").replace(")", "")
    cells: list[tuple[str, int]] = []
    last_row: str | None = None
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        m = re.search(r"([A-V])?\D*?(\d{1,2})", tok)
        if not m:
            raise ValueError(f"не разобран токен номенклатуры: {tok!r}")
        row = m.group(1) or last_row
        if row is None:
            raise ValueError(f"нет буквы ряда для токена {tok!r}")
        last_row = row
        cells.append((row, int(m.group(2))))
    if not cells:
        raise ValueError(f"пустая номенклатура: {sheet_id!r}")

    lon0 = min(_col_band(c)[0] for _, c in cells)
    lon1 = max(_col_band(c)[1] for _, c in cells)
    lat0 = min(_row_band(r)[0] for r, _ in cells)
    lat1 = max(_row_band(r)[1] for r, _ in cells)
    return SheetFrame(sheet_id, lon0, lon1, lat0, lat1, cells)


if __name__ == "__main__":
    for sid in ["P-(35),36", "P-36", "P-35,36", "O-35,N-35,O-36", "O-36", "Q-37"]:
        try:
            f = parse_sheet(sid)
            print(f"{sid:18s} -> lon {f.lon_min}..{f.lon_max}E  lat {f.lat_min}..{f.lat_max}N  "
                  f"cells={f.cells}  rect={f.is_rectangular}")
        except ValueError as e:
            print(f"{sid:18s} -> ОШИБКА: {e}")
