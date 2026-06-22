"""Денежные агрегаты ЦБ (M0/M2/M2X) + фактор ЧТОГУ → SQLite.

Источники — xlsx в ШИРОКОМ формате (строка 1 = даты-колонки, строки = ряды),
скачиваем целиком и парсим openpyxl.

M0/M2/M2X — денежные агрегаты, месячные, млрд руб (блок «Результат»):
  https://www.cbr.ru/vfs/statistics/credit_statistics/monetary_agg.xlsx
  лист «Денежные агрегаты».
  ⚠ Ловушка: М0/М1/М2 — КИРИЛЛИЧЕСКАЯ «М» (U+041C); M2X — ЛАТИНСКАЯ «M» (U+004D).
  Метку M2X в файле записали с переводом строки → нормализуем пробелы.

ЧТОГУ — «Чистые требования банковской системы к органам гос. управления»,
фактор формирования денежной массы (бюджетный канал, блок «Газ»):
  https://www.cbr.ru/vfs/statistics/credit_statistics/survey/survey_dc_new.xlsx
  лист «Агрегированная форма обзора», месячные.
  ⚠ Единицы здесь — МЛН руб → делим на 1000 → млрд руб (сопоставимо с M2).
  Это СЫРОЙ ряд (stock). Производный «вклад в прирост M2» (gov_contrib_m2) —
  отдельный transform на шаге 5, не здесь.

Формат подтверждён напрямую 2026-06-23 (M2 ≈ 133,6 трлн ₽ — сходится с публикацией ЦБ).
К ЦБ — в обход прокси (cbr_session). openpyxl + requests-сессия из ingest.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import DB_PATH, upsert_series, write_observations  # noqa: E402
from ingest import cbr_session  # noqa: E402

MONETARY_AGG_URL = "https://www.cbr.ru/vfs/statistics/credit_statistics/monetary_agg.xlsx"
SURVEY_URL = "https://www.cbr.ru/vfs/statistics/credit_statistics/survey/survey_dc_new.xlsx"
SOURCE_AGG = "https://www.cbr.ru/statistics/macro_itm/dkfs/monetary_agg/"
SOURCE_SURVEY = "https://www.cbr.ru/statistics/macro_itm/dkfs/"


def _norm(s: object) -> str:
    """Нормализовать метку строки: убрать переводы строк, схлопнуть пробелы."""
    return " ".join(str(s).split()) if s is not None else ""


def _download(url: str) -> bytes:
    resp = cbr_session().get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def parse_wide(content: bytes, sheet: str, label: str, scale: float = 1.0) -> list[tuple[str, float]]:
    """Достать ряд `label` из широкого xlsx-листа → [(date 'YYYY-MM-DD', value*scale)].

    Берём только клетки, где заголовок колонки — дата, а значение — число
    (этот фильтр заодно отсекает колонку-метку, хвостовые сноски и пустые '').
    """
    wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    target = _norm(label)
    for r in rows:
        if _norm(r[0]) == target:
            out = [
                (h.date().isoformat(), float(v) * scale)
                for h, v in zip(header, r)
                if isinstance(h, datetime) and isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            if not out:
                raise RuntimeError(f"ряд {label!r} найден, но без числовых значений")
            out.sort(key=lambda x: x[0])
            return out
    raise RuntimeError(f"ряд {label!r} не найден в листе {sheet!r} (метки ЦБ могли измениться)")


def ingest(db_path: Path | str = DB_PATH) -> dict[str, int]:
    """Забрать M0/M2/M2X и ЧТОГУ, записать в SQLite. Возвращает {series_id: rows}."""
    agg = _download(MONETARY_AGG_URL)
    survey = _download(SURVEY_URL)
    written: dict[str, int] = {}

    # --- денежные агрегаты (млрд руб, месячные) ---
    agg_series = [
        ("m0", "Денежный агрегат М0", "Денежная масса M0 (наличные вне банков)", "result"),
        ("m2", "Денежный агрегат М2", "Денежная масса M2 (национальное определение)", "result"),
        ("m2x", "Денежный агрегат M2X (широкая денежная масса)", "Широкая денежная масса M2X", "result"),
    ]
    for sid, label, title, panel in agg_series:
        rows = parse_wide(agg, "Денежные агрегаты", label)
        upsert_series(
            sid, title=title, unit="млрд руб", freq="M", panel=panel,
            source_name="Банк России", source_url=SOURCE_AGG,
            notes=f"monetary_agg.xlsx, лист «Денежные агрегаты», метка {label!r}.",
            db_path=db_path,
        )
        written[sid] = write_observations(sid, rows, flag="final", db_path=db_path)

    # --- ЧТОГУ (фактор «Газ»): млн руб → млрд руб (÷1000) ---
    chtogu = parse_wide(
        survey, "Агрегированная форма обзора",
        "Чистые требования к органам государственного управления", scale=1 / 1000,
    )
    upsert_series(
        "net_gov_claims",
        title="Чистые требования банковской системы к гос. управлению (ЧТОГУ)",
        unit="млрд руб", freq="M", panel="gas",
        source_name="Банк России", source_url=SOURCE_SURVEY,
        notes="survey_dc_new.xlsx; млн→млрд (÷1000); сырой stock. "
              "Производный «вклад в прирост M2» (gov_contrib_m2) — на шаге 5.",
        db_path=db_path,
    )
    written["net_gov_claims"] = write_observations("net_gov_claims", chtogu, flag="final", db_path=db_path)
    return written


if __name__ == "__main__":
    res = ingest()
    for sid, n in res.items():
        print(f"{sid}: записано {n} наблюдений")
    print(f"→ {DB_PATH}")
