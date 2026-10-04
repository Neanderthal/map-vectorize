# map-vectorize

Оцифровка (векторизация) растровых геологических и почвенных карт в GeoJSON.
Первая задача: карты **четвертичных отложений ГГК-1000/3** на Ленинградскую область →
полигоны **песчаных отложений** (`f` флювиогляциальные, `v` эоловые, `lg` озёрно-ледниковые)
для поиска боровых местообитаний. Результат питает проект `../mushrooms`.

## Структура

- `data/raw/` — исходные растры + PDF легенд (**не в git**; тянутся `src/fetch_sources.py`)
- `data/legend/` — извлечённые цвета легенды, таблицы единиц
- `src/` — скрипты конвейера
- `output/` — результат (GeoJSON) — **в git**

## Команды

```
pip install -r requirements.txt
python src/fetch_sources.py           # скачать исходники в data/raw/
python src/georef.py <sheet>          # привязка листа (коника → EPSG:3857)
python src/vectorize.py <sheet>       # сегментация по цвету → полигоны → GeoJSON
```

## Доступ к ру-источникам

geokniga.org доступна только мимо тоннеля (proxy-off + `--noproxy '*'`); ВСЕГЕИ закрыт
(403 за UTM-шлюзом). Детали — в `.claude/rules/sources.md`.

## Правила

- [sources.md](.claude/rules/sources.md) — источники, URL, доступ к .ru, модель данных
- [pipeline.md](.claude/rules/pipeline.md) — конвейер: геореференс, сегментация, полигонизация
- [legend.md](.claude/rules/legend.md) — единицы четвертички, цвета, пригодность для боровика
