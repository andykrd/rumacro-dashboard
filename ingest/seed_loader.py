"""Загрузчик ручных «тяжёлых» рядов (PDF-источники) из data/seed/*.csv → SQLite.

Для v1 ряды, которые иначе требовали бы разбора PDF/сложных порталов
(наблюдаемая инфляция и ожидания ИнФОМ, дефицит бюджета, ликвидная часть ФНБ),
заполняются вручную в data/seed/*.csv и грузятся отсюда с flag='seed'.
Пользователь дополняет CSV помесячно (PRD §10). Метаданные рядов — в SEEDS ниже.

CSV-формат: UTF-8, строки-комментарии начинаются с '#', далее заголовок
`date,value` и строки `YYYY-MM-01,значение`.

Сырые ряды; производные (gap = наблюдаемая − ИПЦ, deficit_vs_plan) — transforms.py (шаг 5).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import DB_PATH, upsert_series, write_observations  # noqa: E402

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"

# series_id → метаданные + имя CSV. panel: result | gas (см. PRD §7).
SEEDS: dict[str, dict] = {
    "observed_infl": {
        "csv": "observed_inflation.csv",
        "title": "Наблюдаемая инфляция (опрос ИнФОМ)",
        "unit": "% (медиана, за 12 мес)",
        "freq": "M", "panel": "result",
        "source_name": "Банк России / ИнФОМ",
        "source_url": "https://www.cbr.ru/analytics/dkp/inflationary_expectations/",
        "notes": "Ручной seed из PDF/пресс-релизов ИнФОМ. Производная gap = observed − cpi_yoy — шаг 5.",
    },
    "infl_expect": {
        "csv": "infl_expect.csv",
        "title": "Инфляционные ожидания населения на год (ИнФОМ)",
        "unit": "% (медиана, на 12 мес вперёд)",
        "freq": "M", "panel": "result",
        "source_name": "Банк России / ИнФОМ",
        "source_url": "https://www.cbr.ru/analytics/dkp/inflationary_expectations/",
        "notes": "Ручной seed из PDF/пресс-релизов ИнФОМ.",
    },
    "deposit_rate": {
        "csv": "deposit_rate.csv",
        "title": "Макс. ставка по вкладам физлиц (топ-10 банков)",
        "unit": "% годовых",
        "freq": "D", "panel": "brake",
        "source_name": "Банк России",
        "source_url": "https://www.cbr.ru/statistics/avgprocstav/",
        "notes": "Декадные данные (виджет cbr.ru) — ручной seed. Трекает ключевую ставку.",
    },
    "budget_deficit": {
        "csv": "budget_deficit.csv",
        "title": "Дефицит федбюджета (накопл. с начала года)",
        "unit": "трлн ₽",
        "freq": "M", "panel": "gas",
        "source_name": "Минфин России",
        "source_url": "https://minfin.gov.ru/ru/press-center/",
        "notes": "Ручной seed. План-2026 = 3.786 трлн ₽. Производная deficit_vs_plan — шаг 5.",
    },
    "nwf_liquid": {
        "csv": "nwf_liquid.csv",
        "title": "Ликвидная часть ФНБ",
        "unit": "трлн ₽",
        "freq": "M", "panel": "gas",
        "source_name": "Минфин России",
        "source_url": "https://minfin.gov.ru/ru/perfomance/nationalwealthfund/",
        "notes": "Ручной seed. Снимок на 1-е число месяца.",
    },
}


def read_seed_csv(path: Path) -> list[tuple[str, float]]:
    """Прочитать seed-CSV (пропуская '#'-комментарии) → [(date, value)] по дате."""
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    rows = [(r["date"].strip(), float(r["value"])) for r in csv.DictReader(lines)]
    if not rows:
        raise RuntimeError(f"seed {path.name} пуст или без данных")
    rows.sort(key=lambda x: x[0])
    return rows


def load_seed(series_id: str, db_path: Path | str = DB_PATH) -> int:
    spec = SEEDS[series_id]
    rows = read_seed_csv(SEED_DIR / spec["csv"])
    upsert_series(
        series_id,
        title=spec["title"], unit=spec["unit"], freq=spec["freq"], panel=spec["panel"],
        source_name=spec["source_name"], source_url=spec["source_url"], notes=spec["notes"],
        db_path=db_path,
    )
    return write_observations(series_id, rows, flag="seed", db_path=db_path)


def load_all(db_path: Path | str = DB_PATH) -> dict[str, int]:
    return {sid: load_seed(sid, db_path) for sid in SEEDS}


if __name__ == "__main__":
    res = load_all()
    for sid, n in res.items():
        print(f"{sid}: загружено {n} наблюдений (seed)")
    print(f"→ {DB_PATH}")
