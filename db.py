"""SQLite-слой дашборда «Две руки российской макро».

Схема — long-format (см. PRD §6):
  series        — метаданные ряда (id, заголовок, единицы, частота, панель, источник)
  observations  — наблюдения (series_id, date, value, fetched_at, flag)

Правила (CLAUDE.md):
  - храним ИСХОДНУЮ частоту (D/M/Q), не апсемплим молча;
  - у каждого наблюдения есть fetched_at и flag (final|prelim|seed|revised);
  - сырые ряды отделяем от производных (производные считаем на лету в transforms.py).

Только stdlib + pandas. Без ORM.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

# data/rumacro.db — относительно корня проекта; сама БД в .gitignore.
DB_PATH = Path(__file__).resolve().parent / "data" / "rumacro.db"

VALID_FREQ = {"D", "M", "Q"}
VALID_PANEL = {"gas", "brake", "result", "context"}
VALID_FLAG = {"final", "prelim", "seed", "revised"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    id          TEXT PRIMARY KEY,   -- 'key_rate', 'm2', 'budget_deficit', ...
    title       TEXT,
    unit        TEXT,
    freq        TEXT,               -- 'D' | 'M' | 'Q'
    panel       TEXT,               -- 'gas' | 'brake' | 'result' | 'context'
    source_name TEXT,
    source_url  TEXT,
    transform   TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    series_id  TEXT NOT NULL,
    date       TEXT NOT NULL,       -- ISO 'YYYY-MM-DD'
    value      REAL,
    fetched_at TEXT,                -- ISO 8601 UTC, когда забрали
    flag       TEXT,                -- 'final' | 'prelim' | 'seed' | 'revised'
    PRIMARY KEY (series_id, date),
    FOREIGN KEY (series_id) REFERENCES series(id)
);

CREATE INDEX IF NOT EXISTS idx_obs_series ON observations(series_id);
"""


def get_conn(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Соединение с включёнными внешними ключами."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str = DB_PATH) -> None:
    """Создать таблицы, если их нет. Идемпотентно."""
    with get_conn(db_path) as conn:
        conn.executescript(_SCHEMA)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_series(
    series_id: str,
    *,
    title: str = "",
    unit: str = "",
    freq: str = "",
    panel: str = "",
    source_name: str = "",
    source_url: str = "",
    transform: str = "",
    notes: str = "",
    db_path: Path | str = DB_PATH,
) -> None:
    """Создать/обновить метаданные ряда."""
    if freq and freq not in VALID_FREQ:
        raise ValueError(f"freq={freq!r}, ожидается одно из {sorted(VALID_FREQ)}")
    if panel and panel not in VALID_PANEL:
        raise ValueError(f"panel={panel!r}, ожидается одно из {sorted(VALID_PANEL)}")
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO series (id, title, unit, freq, panel,
                                source_name, source_url, transform, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, unit=excluded.unit, freq=excluded.freq,
                panel=excluded.panel, source_name=excluded.source_name,
                source_url=excluded.source_url, transform=excluded.transform,
                notes=excluded.notes;
            """,
            (series_id, title, unit, freq, panel,
             source_name, source_url, transform, notes),
        )


def write_observations(
    series_id: str,
    rows: Iterable[Sequence],
    *,
    flag: str = "final",
    fetched_at: str | None = None,
    db_path: Path | str = DB_PATH,
) -> int:
    """Записать наблюдения ряда (upsert по (series_id, date)).

    rows — итерируемое из (date, value) или (date, value, flag).
    date — строка ISO 'YYYY-MM-DD'. Возвращает число записанных строк.
    """
    if flag not in VALID_FLAG:
        raise ValueError(f"flag={flag!r}, ожидается одно из {sorted(VALID_FLAG)}")
    fetched_at = fetched_at or _utcnow()
    payload = []
    for row in rows:
        if len(row) == 3:
            date, value, row_flag = row
        else:
            date, value = row
            row_flag = flag
        payload.append((series_id, str(date), value, fetched_at, row_flag))
    if not payload:
        return 0
    with get_conn(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO observations (series_id, date, value, fetched_at, flag)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(series_id, date) DO UPDATE SET
                value=excluded.value, fetched_at=excluded.fetched_at, flag=excluded.flag;
            """,
            payload,
        )
    return len(payload)


def read_series(series_id: str, db_path: Path | str = DB_PATH) -> pd.DataFrame:
    """Наблюдения одного ряда как DataFrame [date, value, flag], date → datetime, сортировка по дате."""
    with get_conn(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date, value, flag FROM observations "
            "WHERE series_id = ? ORDER BY date;",
            conn,
            params=(series_id,),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def get_series_meta(series_id: str, db_path: Path | str = DB_PATH) -> dict | None:
    """Метаданные ряда как dict или None, если ряда нет."""
    with get_conn(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM series WHERE id = ?;", (series_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def last_updated(series_id: str, db_path: Path | str = DB_PATH) -> str | None:
    """Когда ряд забирали последний раз (max fetched_at) — для индикатора свежести в шапке."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "SELECT MAX(fetched_at) FROM observations WHERE series_id = ?;",
            (series_id,),
        )
        result = cur.fetchone()[0]
    return result


if __name__ == "__main__":
    # Ручной прогон: создать схему в data/rumacro.db.
    init_db()
    print(f"Схема инициализирована: {DB_PATH}")
