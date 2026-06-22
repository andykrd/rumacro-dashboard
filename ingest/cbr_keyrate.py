"""Загрузчик ключевой ставки Банка России → SQLite.

Источник: ЦБ, SOAP-сервис DailyInfoWebServ, метод KeyRate.
  POST https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx
  SOAP 1.2, namespace http://web.cbr.ru/, параметры fromDate / ToDate (datetime).
  Ответ — diffgram с по-дневными строками:
    <KR><DT>2026-06-22T00:00:00+03:00</DT><Rate>14.25</Rate></KR>
  Частота — дневная (D): значение на каждый календарный день.

Формат подтверждён напрямую 2026-06-23 (HTTP 200). URL'ы госсайтов «плывут» —
перед правкой свериться с живым ответом (CLAUDE.md).

ВАЖНО про сеть (CLAUDE.md / окружение разработки):
  cbr.ru блокирует иностранные IP. В сессии выставлен HTTP/SOCKS-прокси
  (http_proxy / ALL_PROXY → 172.19.176.1:10808) с иностранным exit'ом — через него
  TLS к ЦБ рвётся (reset на Client Hello). Поэтому к ЦБ ходим НАПРЯМУЮ, в обход
  прокси (requests.Session с trust_env=False), с рабочего РФ-IP.
  На деплое (Streamlit Cloud, иностранный IP) авто-фетч, скорее всего, не пройдёт —
  это вопрос шага 6 (стратегия обновления), не ломает локальный прогон.

Только stdlib (xml.etree) + requests. Без HTML-парсеров (lxml/bs4).
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

# db.py лежит в корне проекта — кладём корень в путь, чтобы модуль запускался
# и как скрипт (python ingest/cbr_keyrate.py), и как пакет (python -m ingest.cbr_keyrate).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import DB_PATH, upsert_series, write_observations  # noqa: E402
from ingest import cbr_session  # noqa: E402

CBR_SOAP_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
# Дата, на которую формат ответа сверялся с живым сервисом.
SOURCE_URL = "https://www.cbr.ru/hd_base/KeyRate/"
DEFAULT_FROM = "2023-01-01"  # ловим весь цикл: подъём до 21% и текущее смягчение

_SOAP_TEMPLATE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap12:Envelope'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
    "<soap12:Body>"
    '<KeyRate xmlns="http://web.cbr.ru/">'
    "<fromDate>{from_date}T00:00:00</fromDate>"
    "<ToDate>{to_date}T00:00:00</ToDate>"
    "</KeyRate>"
    "</soap12:Body>"
    "</soap12:Envelope>"
)

_HEADERS = {"Content-Type": "application/soap+xml; charset=utf-8"}


def fetch_key_rate(from_date: str = DEFAULT_FROM, to_date: str | None = None) -> list[tuple[str, float]]:
    """Забрать дневной ряд ключевой ставки за [from_date, to_date].

    Возвращает список (date 'YYYY-MM-DD', rate) по возрастанию даты.
    """
    to_date = to_date or date.today().isoformat()
    body = _SOAP_TEMPLATE.format(from_date=from_date, to_date=to_date)
    resp = cbr_session().post(CBR_SOAP_URL, data=body.encode("utf-8"), headers=_HEADERS, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    rows: list[tuple[str, float]] = []
    # Элементы <KR> внутри diffgram идут с пустым namespace (xmlns="") → ищем по локальному тегу.
    for kr in root.iter("KR"):
        dt = kr.findtext("DT")
        rate = kr.findtext("Rate")
        if dt is None or rate is None:
            continue
        rows.append((dt[:10], float(rate)))  # 'YYYY-MM-DD' из ISO-datetime
    if not rows:
        raise RuntimeError("ЦБ вернул пустой ряд ключевой ставки — проверить формат ответа/URL")
    rows.sort(key=lambda r: r[0])
    return rows


def ingest(from_date: str = DEFAULT_FROM, to_date: str | None = None, db_path: Path | str = DB_PATH) -> int:
    """Забрать ставку и записать в SQLite (series + observations). Возвращает число строк."""
    rows = fetch_key_rate(from_date, to_date)
    upsert_series(
        "key_rate",
        title="Ключевая ставка Банка России",
        unit="% годовых",
        freq="D",
        panel="brake",
        source_name="Банк России",
        source_url=SOURCE_URL,
        notes="SOAP DailyInfoWebServ/KeyRate; дневной ряд; запрос в обход прокси (РФ-IP).",
        db_path=db_path,
    )
    n = write_observations("key_rate", rows, flag="final", db_path=db_path)
    return n


if __name__ == "__main__":
    n = ingest()
    print(f"key_rate: записано {n} наблюдений в {DB_PATH}")
