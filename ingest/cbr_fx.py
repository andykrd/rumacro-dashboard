"""Курс USD/RUB (официальный курс ЦБ) → SQLite. Блок «Контекст».

Источник: ЦБ, динамика курса XML_dynamic.asp, VAL_NM_RQ=R01235 (доллар США).
  GET https://www.cbr.ru/scripts/XML_dynamic.asp
      ?date_req1=DD/MM/YYYY&date_req2=DD/MM/YYYY&VAL_NM_RQ=R01235
  Ответ — XML в windows-1251:
    <Record Date="DD.MM.YYYY"><Nominal>1</Nominal><Value>71,5532</Value>
            <VunitRate>71,5532</VunitRate></Record>
  Десятичная запятая. Берём VunitRate — курс за 1 единицу с учётом номинала.
  Частота — рабочие дни (D).

Формат подтверждён напрямую 2026-06-23 (HTTP 200). URL'ы госсайтов «плывут».
Только stdlib (xml.etree) + requests-сессия из ingest. К ЦБ — в обход прокси.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import DB_PATH, upsert_series, write_observations  # noqa: E402
from ingest import cbr_session  # noqa: E402

CBR_FX_URL = "https://www.cbr.ru/scripts/XML_dynamic.asp"
SOURCE_URL = "https://www.cbr.ru/currency_base/dynamics/"
USD_CODE = "R01235"
DEFAULT_FROM = "2024-01-01"


def _to_ddmmyyyy(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y")


def fetch_usdrub(from_date: str = DEFAULT_FROM, to_date: str | None = None) -> list[tuple[str, float]]:
    """Дневной ряд USD/RUB за [from_date, to_date] → [(date 'YYYY-MM-DD', rate)]."""
    to_date = to_date or date.today().isoformat()
    params = {
        "date_req1": _to_ddmmyyyy(from_date),
        "date_req2": _to_ddmmyyyy(to_date),
        "VAL_NM_RQ": USD_CODE,
    }
    resp = cbr_session().get(CBR_FX_URL, params=params, timeout=30)
    resp.raise_for_status()

    # resp.content — байты с объявленной кодировкой windows-1251; ET сам разберёт.
    root = ET.fromstring(resp.content)
    rows: list[tuple[str, float]] = []
    for rec in root.iter("Record"):
        d = rec.get("Date")  # 'DD.MM.YYYY'
        raw = rec.findtext("VunitRate") or rec.findtext("Value")
        if not d or raw is None:
            continue
        iso = datetime.strptime(d, "%d.%m.%Y").date().isoformat()
        rows.append((iso, float(raw.replace(",", "."))))
    if not rows:
        raise RuntimeError("ЦБ вернул пустой ряд курса USD/RUB — проверить формат/URL")
    rows.sort(key=lambda r: r[0])
    return rows


def ingest(from_date: str = DEFAULT_FROM, to_date: str | None = None, db_path: Path | str = DB_PATH) -> int:
    rows = fetch_usdrub(from_date, to_date)
    upsert_series(
        "usdrub",
        title="Курс доллара США (USD/RUB)",
        unit="руб. за $1",
        freq="D",
        panel="context",
        source_name="Банк России",
        source_url=SOURCE_URL,
        notes="XML_dynamic.asp R01235; VunitRate; запрос в обход прокси (РФ-IP).",
        db_path=db_path,
    )
    return write_observations("usdrub", rows, flag="final", db_path=db_path)


if __name__ == "__main__":
    n = ingest()
    print(f"usdrub: записано {n} наблюдений в {DB_PATH}")
