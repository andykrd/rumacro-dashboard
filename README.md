# rumacro-dashboard

Публичный дашборд **«Две руки российской макро»**: противостояние фискального вливания (бюджет) и монетарного торможения (ЦБ) + датчики результата (инфляция официальная/наблюдаемая, денежные агрегаты).

Это **прокси и сопоставление рядов**, а не «настоящая инфляция». Подробности — в `PRD.md`, правила для разработки — в `CLAUDE.md`.

## Стек
Python 3.11+, Streamlit, SQLite (stdlib), pandas, plotly, requests, openpyxl. Деплой — Streamlit Community Cloud.

## Запуск (WSL2 / Ubuntu)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Проект держать в файловой системе WSL (`~/projects/...`), не на `/mnt/c`.

## Данные
- `db.py` — схема SQLite (long-format: `series` + `observations`) и хелперы чтения/записи.
- `ingest/*` — загрузка «лёгких» источников (ставка ЦБ, курс, деньги).
- `data/seed/*.csv` — «тяжёлые» источники (PDF: наблюдаемая инфляция, бюджет, ФНБ), обновляются вручную.
- `data/rumacro.db` — локальная база (в `.gitignore`).

## Структура
```
app.py          Streamlit-приложение
db.py           схема + чтение/запись SQLite
ingest/         загрузчики лёгких источников
transforms.py   производные ряды (YoY, MoM, velocity, ...) — позже
data/seed/      ручные CSV для тяжёлых источников
```
