#!/usr/bin/env python3
"""Скачать исходные карты и легенды в data/raw/.

Источник — geokniga.org (оцифрованные листы ГГК-1000/3). Сайт .ru доступен только
мимо тоннеля: снимаем прокси-переменные и ходим с `--noproxy '*'` (см.
.claude/rules/sources.md). ВСЕГЕИ/Карпинский закрыты UTM-шлюзом (403) — не отсюда.

Файлы, которые уже есть, повторно не качаются. Запуск: `python src/fetch_sources.py`.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

GEOKNIGA = "https://www.geokniga.org"

# целевое имя -> (url, страница-источник для справки)
SOURCES: dict[str, tuple[str, str]] = {
    # --- ГГК-1000/3, карта четвертичных образований, СЕВЕР (Балтийская серия) ---
    # лист P-(35),36 (Петрозаводск): Карельский перешеек, Приладожье, север ЛО
    "ggk1000_P-35-36_quat.jpg": (
        f"{GEOKNIGA}/sites/geokniga/files/maps/"
        "p-3536-petrozavodsk-gosudarstvennaya-geologicheskaya-karta-rossiyskoy-feder_1.jpg",
        f"{GEOKNIGA}/maps/17329",
    ),
    "ggk1000_P-35-36_legend1.pdf": (f"{GEOKNIGA}/maps/additional/p-3536kqo1.pdf", f"{GEOKNIGA}/maps/17329"),
    "ggk1000_P-35-36_legend2.pdf": (f"{GEOKNIGA}/maps/additional/p-3536kqo2.pdf", f"{GEOKNIGA}/maps/17329"),
    "ggk1000_P-35-36_zapiska.pdf": (
        f"{GEOKNIGA}/sites/geokniga/files/mapcomments/"
        "p-3536-petrozavodsk-gosudarstvennaya-geologicheskaya-karta-rossiyskoy-feder.pdf",
        f"{GEOKNIGA}/maps/17329",
    ),
    # --- ГГК-1000/3, карта четвертичных отложений, ЮГ (Центрально-Европейская серия) ---
    # лист O-35,N-35,O-36 (Санкт-Петербург): СПб, Гатчина, Луга, Кингисепп, юг ЛО
    "ggk1000_O-35-36_quat.jpg": (
        f"{GEOKNIGA}/sites/geokniga/files/maps/"
        "o-35-pskov-n-35-o-36-sankt-peterburg-gosudarstvennaya-geologicheskaya-karta-ro_2.jpg",
        f"{GEOKNIGA}/maps/7869",
    ),
    "ggk1000_O-35-36_legend1.pdf": (f"{GEOKNIGA}/maps/additional/o-35-36n-35kqo1.pdf", f"{GEOKNIGA}/maps/7869"),
    "ggk1000_O-35-36_legend2.pdf": (f"{GEOKNIGA}/maps/additional/o-35-36n-35kqo2.pdf", f"{GEOKNIGA}/maps/7869"),
}

# снять прокси-окружение (тоннель/Tor), чтобы ходить напрямую
PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
UA = "Mozilla/5.0 (X11; Linux x86_64) Firefox/128.0"


def fetch(url: str, dest: Path) -> bool:
    env = {k: v for k, v in os.environ.items() if k not in PROXY_VARS}
    cmd = ["curl", "-sS", "--noproxy", "*", "-L", "--compressed", "--max-time", "180",
           "-A", UA, "-o", str(dest), url]
    return subprocess.run(cmd, env=env).returncode == 0 and dest.exists() and dest.stat().st_size > 0


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    ok = skip = fail = 0
    for name, (url, page) in SOURCES.items():
        dest = RAW / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  = {name} (есть, {dest.stat().st_size/1048576:.1f} МБ)")
            skip += 1
            continue
        print(f"  ↓ {name}  ←  {page}")
        if fetch(url, dest):
            print(f"    ok, {dest.stat().st_size/1048576:.1f} МБ")
            ok += 1
        else:
            print(f"    ОШИБКА: {url}", file=sys.stderr)
            dest.unlink(missing_ok=True)
            fail += 1
    print(f"\nскачано {ok}, пропущено {skip}, ошибок {fail}  →  {RAW}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
