# Существующие open-source решения для оцифровки геокарт

> Исследование от 2026-10-04. Цель — найти открытые, локально запускаемые решения
> для векторизации растровых листов ГГК-1000/3 (четвертичные отложения) в полигоны
> GeoJSON песчаных единиц (`f`, `v`, `lg`). Метод: fan-out веб-поиск по 5 углам →
> выкачка 21 источника → 104 утверждения → состязательная проверка 25 из них
> (3 голоса, 2 «против» убивают факт) → синтез. Подтверждено 20, опровергнуто 5.
>
> Каждое утверждение помечено уровнем доверия и итогом голосования. Это
> аналитический срез, не истина в последней инстанции: цифры точности DL —
> самоотчётные (best-case), применимость к кириллическим легендам ВСЕГЕИ/Карпинского
> ни одним источником не проверена.

## Главный вывод

**Классический путь, уже выбранный проектом (цвет → маска → полигоны средствами
`rasterio`/`scikit-image`), — самый надёжный и единственный, полностью
удовлетворяющий ограничениям** (только open-source, локально, без платных облачных
API). Все наиболее релевантные DL-системы для геокарт спотыкаются об одно: ключевые
стадии (извлечение легенды, заголовка) висят на платном облачном **GPT-4o**.

---

## Угол 1 — Цвет → полигоны (классический raster-to-vector) ✅

**Задача «растровая маска → полигоны GeoJSON» полностью решена открытыми локальными
инструментами, часть из которых уже в стеке проекта.** (доверие: высокое; 3-0)

| Инструмент | Роль |
|---|---|
| `rasterio.features.shapes()` | маска (bool/uint8) → пары (полигон, значение) как GeoJSON-dict; принимает `transform` (сразу геокоординаты) и `mask` (False/0 = исключить пиксель оверпринта). Обёртка над `GDALPolygonize`. |
| `gdal_polygonize` | тот же алгоритм через CLI |
| GRASS `r.to.vect` | трассировка периметров уникальных областей → полигоны + центроиды; экспорт `v.out.ogr format=GeoJSON` |

- ⚠️ `shapes()` отдаёт координаты, но **не пишет CRS и не перепроецирует в
  EPSG:4326** — сборка FeatureCollection и работа с CRS остаются ручным (тривиальным)
  шагом.

**Морфология — подтверждённый стандарт очистки оверпринта перед векторизацией.**
(доверие: высокое; 3-0) Peller (2018), IASSIST Quarterly 42(3), DOI 10.29173/iq914,
дословно: *«erode убирает текст, нежелательные пересечения и перемычки; dilate
заполняет дыры и закрывает разрывы»*; opening (erode→dilate) и closing
(dilate→erode) — ровно то, что прописано в `pipeline.md`.
Оговорка: для бедных палитрой исторических линейных карт цвет — слабый признак и
выигрывают методы по рёбрам/DL (Chen et al. 2021, arXiv:2101.02144); но у ГГК
единицы — различимые цветозаливки, так что цветовой подход применим.

**Работа в Lab/HSV вместо RGB — верно.** (доверие: высокое; 3-0) SOTA-система
DIGMAPPER/TOPAZ использует **RGB + HSV + LAB + YUV совместно** для различения цветов
полигонов — подтверждает мультицветовую интуицию `pipeline.md` даже внутри классики.

### Ближайший готовый end-to-end: NYPL Map Vectorizer

(доверие: высокое; 3-0) [github.com/nypl-spacetime/map-vectorizer](https://github.com/nypl-spacetime/map-vectorizer)
— MIT, ~659★, локальный CLI (`python vectorize_map.py test.tif`), вывод Shapefile +
GeoJSON. Внутри оркестрирует OpenCV/PIL + `gdal_polygonize` + `ogr2ogr` + R (alphahull
для упрощения). Доказывает существование бесплатной локальной цепочки
raster → polygon → GeoJSON.
⚠️ Сделан под городские/страховые атласы XIX — начала XX в., ядро датируется 2013 г.
(низкая активность); пригодность к геологическим листам ГГК **не доказана** —
референс архитектуры, не drop-in. Утверждение, что его внутренний метод «совпадает»
с цветовым подходом проекта, **опровергнуто** (1-2).

---

## Угол 2 — DL-сегментация сканов карт ⚠️

### DIGMAPPER / TOPAZ (USGS + DARPA CriticalMAAS) — архитектурно точнее всех, но несовместимо

(доверие: высокое; 3-0) [arXiv:2506.16006](https://arxiv.org/html/2506.16006) (ACM
SIGSPATIAL 2025; Inferlink, USC ISI, U. Minnesota). Модульная, Docker-based,
Luigi-DAG система автоматической оцифровки геокарт (растр → векторные
полигоны/линии/точки), **внедрена в рабочие процессы USGS**.

Модуль извлечения полигонов **TOPAZ** (ViT + BERT + U-Net) совместно векторизует
полигоны, восстанавливает точные цвета и связывает их с единицами легенды по
мультицветовым (RGB/HSV/LAB/YUV) + маркировкам + тексту. **Явно решает проблему
«Цвет ≠ генетический индекс»**: дословно *«несколько единиц легенды могут делить один
цвет и различаются только по текстовым подписям»* → решается попиксельным
назначением «пиксель → единица легенды».

❌ **Не переиспользуем под ограничения проекта:** извлечение легенды и заголовка
висит на **GPT-4o** (платный облачный API), локального фолбэка нет. (доверие:
высокое; 3-0) Открытого кода/весов самого TOPAZ не подтверждено.

🟢 **Единственный переиспользуемый открытый компонент:** модуль **LARA**
(fine-tuned LayoutLMv3) сегментации областей легенды из
[DARPA-CRITICALMAAS/uncharted-ta1](https://github.com/DARPA-CRITICALMAAS/uncharted-ta1)
— MIT, выделяет классы Map / Legend-polygons / Legend-points+lines / Cross-section,
запускается локально (`run_pipeline.py` / `run_server.py` или Docker, веса с
локальной ФС). (доверие: высокое; 3-0)

### Saxton et al. 2024 — прямой академический аналог цели

(доверие: высокое; 3-0) MDPI Geosciences,
[10.3390/geosciences14110305](https://doi.org/10.3390/geosciences14110305), CC-BY.
Единицы легенды используются **как промпты для one-shot сегментации полигонов** (и
детекции точек) на сканах исторических геокарт. Median F1 **0.91** (полигоны) / 0.73
(точки) на бенчмарке **AI4CMA DARPA** при обилии размеченных данных. SAM-style
бинарная сегментация для полигонов + YOLO-OBB для точек; датасет 169 train / 82 val /
32 test. Парадигма «единица легенды как промпт» прямо аналогична превращению единиц
ГГК (`f`, `v`, `lg`) в полигоны.
⚠️ 0.91/0.73 — best-case при обилии данных на класс; по соревнованию в среднем сильно
ниже (0.77 полигоны / 0.56 линии / 0.35 точки — отдельная статья USGS lessons-learned),
т.е. на редких классах реально хуже. Открытый код/веса **не подтверждены**.

### topoDL — узкий прецедент U-Net

(доверие: высокое; 3-0) [github.com/maxwell-geospatial/topoDL](https://github.com/maxwell-geospatial/topoDL)
(MIT, 2020; Maxwell et al. 2020, Remote Sensing 12(24):4145). Модифицированный U-Net
(leaky ReLU, Adamax, Dice loss), но **бинарная** экстракция одного класса (контуры
старых шахт на топокартах), стек Keras + R + ArcGIS Pro (не Python/rasterio).
⚠️ Готовые веса (`final_model.hdf5`) переиспользовать без дообучения нельзя
(**опровергнуто** 0-3). Только как референс архитектуры/процесса U-Net.

### MapReader — не решает задачу

(доверие: высокое; 3-0) [github.com/Living-with-machines/MapReader](https://github.com/Living-with-machines/MapReader)
(переехал на `github.com/maps-as-data/MapReader`). Только два конвейера:
patch-классификация и text spotting. **Пиксельной семантической сегментации
цветозаливок нет** → сам по себе не даёт полигоны песчаных единиц. (Утверждение, что
он вообще не умеет вектор/GeoJSON/геореференс, **опровергнуто** 0-3 — геокоординаты
patch'ей он держит, но на суть непригодности это не влияет.)

---

## Угол 3 — OCR индексов (fIII, lgIIIos, gIIIos) и текста легенды ❌ пробел

(доверие: высокое; 3-0) **Подтверждённого открытого, локально запускаемого,
готового под кириллицу turnkey-решения не найдено.**

- Все утверждения про **mapKurator** (что это готовый MIT open-source локальный
  пайплайн OCR/геолокализации текста по картам; что он заточен под английский и
  коллекцию David Rumsey) — **опровергнуты** (0-3). Нет подтверждённых свидетельств
  ни за его пригодность, ни за то, что это тупик → применимость к кириллическим
  индексам ГГК остаётся **открытым вопросом**.
- Лучший метод линковки «единица легенды ↔ её описание»
  ([arXiv:2510.08385](https://arxiv.org/pdf/2510.08385), ACM SIGSPATIAL 2025):
  LayoutLMv3 + **GPT-4o** (in-context learning), 88% F1 / 85% IoU. Снова платный
  облачный API; к тому же связывает элементы внутри панели легенды, а не
  «текст легенды ↔ полигоны тела карты».
- Общие локальные движки (Tesseract / EasyOCR / PaddleOCR) кириллицу поддерживают,
  но **карт-специфичного проверенного бенчмарка на геологические индексы нет**.

---

## Угол 4 — End-to-end пайплайны и соревнования

- **DARPA CriticalMAAS / AI4CMA** — главная площадка (см. DIGMAPPER выше). Бенчмарк
  AI4CMA размечен USGS и DARPA.
- **NYPL Map Vectorizer** — единственный подтверждённо работающий open-source
  end-to-end raster → GeoJSON (см. угол 1), но не геологический.
- Прочие репозитории из поиска (к проверке по мере надобности): `Fandel-Lin/LOAM`,
  `DARPA-CRITICALMAAS/uiuc-pipeline`, `hhaeri/Semantic-Segmentation-for-Feature-Extraction`.

---

## Что это значит для проекта

1. **Не менять курс.** Классический конвейер (`rasterio.features.shapes` + морфология
   в Lab/HSV) — верное решение и единственное, проходящее по ограничениям. Ресёрч
   валидировал его против первоисточников и установленной библиотеки.
2. **Что подсмотреть у SOTA без нарушения ограничений:** совместные цветовые
   пространства (уже план), идею «легенда-как-промпт», модуль **LARA** — если дойдёт
   до автоматической нарезки панели легенды.
3. **OCR индексов** — закладываться на своё решение: Tesseract/EasyOCR с кириллицей +
   ручная привязка к полигонам. Готового нет.
4. **Потенциальный апгрейд цветового порога (открытый вопрос):** **SAM/SAM2
   локально** с промптами по цвету/единице легенды — возможно лучше чистого порога
   при малых данных и без обучения.

---

## Открытые вопросы (кандидаты на следующий ресёрч)

1. Выложены ли реально открытый код и веса для TOPAZ и метода Saxton et al., и
   запускаются ли они локально без GPT-4o?
2. Можно ли заменить GPT-4o-стадии (легенда/заголовок) в пайплайнах CriticalMAAS на
   локальную открытую VLM (Qwen2-VL, LLaVA) или модуль LARA, сохранив приемлемую
   точность?
3. Лучший открытый локальный OCR для кириллических генетических индексов
   (fIII, lgIIIos, gIIIos) поверх заливок ГГК — Tesseract/EasyOCR/PaddleOCR с
   кириллицей или дообученная модель? Как надёжно привязать распознанный индекс к
   охватывающему полигону?
4. Даёт ли **SAM/SAM2** (open-source, локально) с промптами по цвету/единице легенды
   практический выигрыш над чистым цветовым порогом для песчаных единиц ГГК при малых
   данных и без обучения?

---

## Опровергнутые утверждения (для протокола)

| Утверждение | Голоса | Источник |
|---|---|---|
| Внутренний метод NYPL Map Vectorizer «близко совпадает» с цветовым подходом проекта | 1-2 | nypl-spacetime/map-vectorizer |
| MapReader не умеет вектор/GeoJSON и геореференс | 0-3 | Living-with-machines/MapReader |
| topoDL поставляет переиспользуемые готовые веса (`final_model.hdf5`) | 0-3 | maxwell-geospatial/topoDL |
| mapKurator — готовый MIT open-source локальный пайплайн OCR по картам (`run.py`) | 0-3 | machines-reading-maps/mapkurator-system |
| mapKurator заточен под английский/David Rumsey, OSM-пост-коррекцию | 0-3 | machines-reading-maps/mapkurator-system |

---

## Источники

**Первоисточники (primary):**
- rasterio.features — https://rasterio.readthedocs.io/en/stable/api/rasterio.features.html
- GRASS r.to.vect — https://grass.osgeo.org/grass-stable/manuals/r.to.vect.html
- NYPL Map Vectorizer — https://github.com/nypl-spacetime/map-vectorizer
- Peller 2018, IASSIST Quarterly (DOI 10.29173/iq914) — https://iassistquarterly.com/index.php/iassist/article/download/914/925/147
- DIGMAPPER (arXiv:2506.16006) — https://arxiv.org/html/2506.16006
- Легенда-линковка LayoutLMv3+GPT-4o (arXiv:2510.08385) — https://arxiv.org/pdf/2510.08385
- Saxton et al. 2024, Geosciences — https://doi.org/10.3390/geosciences14110305
- DARPA-CRITICALMAAS/uncharted-ta1 (LARA) — https://github.com/DARPA-CRITICALMAAS/uncharted-ta1
- DARPA-CRITICALMAAS/uiuc-pipeline — https://github.com/DARPA-CRITICALMAAS/uiuc-pipeline
- MapReader — https://github.com/Living-with-machines/MapReader · https://github.com/maps-as-data/MapReader
- topoDL — https://github.com/maxwell-geospatial/topoDL · https://www.mdpi.com/2072-4292/12/24/4145
- mapKurator — https://github.com/machines-reading-maps/mapkurator-system
- Fandel-Lin/LOAM — https://github.com/Fandel-Lin/LOAM
- hhaeri/Semantic-Segmentation-for-Feature-Extraction — https://github.com/hhaeri/Semantic-Segmentation-for-Feature-Extraction
- ScienceBase (DARPA/USGS) — https://www.sciencebase.gov/catalog/item/63a100d6d34e0de3a1f2794f

**Блоги/вторичные (blog):**
- Fractal Geoanalytics, map vectorisation in Python — https://www.fractalgeoanalytics.com/articles/map-vectorisation-python/
- spatial-dev.guru, polygonize raster (rioxarray + geopandas) — https://spatial-dev.guru/2022/04/16/polygonize-raster-using-rioxarray-and-geopandas/
