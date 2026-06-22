# rumacro-dashboard

Публичный дашборд **«Две руки российской макро»**: противостояние фискального вливания (бюджет) и монетарного торможения (ЦБ) + датчики результата (инфляция официальная/наблюдаемая, денежные агрегаты).

Это **прокси и сопоставление рядов**, а не «настоящая инфляция». Подробности — в `PRD.md`, правила для разработки — в `CLAUDE.md`.

## Стек
Python 3.11+, Streamlit, SQLite (stdlib), pandas, plotly, requests, openpyxl. Деплой — Streamlit Community Cloud.

## Запуск (WSL2 / Ubuntu)
```bash
uv venv .venv                                         # python3 -m venv тут падает (нет ensurepip)
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/streamlit run app.py
```
Проект держать в файловой системе WSL (`~/projects/...`), не на `/mnt/c`.
При старте `app.py` сам населяет базу (см. «Данные»), так что отдельный прогон загрузчиков не нужен.

## Данные
- `db.py` — схема SQLite (long-format: `series` + `observations`) и хелперы чтения/записи.
- `ingest/*` — загрузчики «лёгких» источников ЦБ (ставка, курс, деньги, ИПЦ). Ходят к cbr.ru **в обход прокси** или через `CBR_PROXY` (см. ниже).
- `data/seed/*.csv` — «тяжёлые» источники (PDF/виджеты: наблюдаемая инфляция, ожидания, ставки по вкладам, бюджет, ФНБ), обновляются вручную раз в месяц. Грузятся `ingest/seed_loader.py`.
- `transforms.py` — производные на лету (YoY, разрыв инфляции, дефицит/план).
- `data/rumacro.db` — локальная база (в `.gitignore`, пересоздаётся при старте).

**Гибридная загрузка.** `app.py` при старте (`bootstrap()`, кэш 6 ч) грузит сиды из CSV и дотягивает ряды ЦБ. Фетч ЦБ — best-effort: если ЦБ недоступен, показываются seed-данные и предупреждение.

## cbr.ru и прокси
cbr.ru блокирует иностранные IP. Локально из РФ — прямое соединение (в обход системного прокси). Из-за границы / на облаке нужен **РФ-прокси** в переменной `CBR_PROXY` (`socks5h://…` или `http://…`, см. `.env.example`).

## Деплой (Streamlit Community Cloud)
1. Запушить репозиторий на GitHub (см. `gh repo create … --push`).
2. На [share.streamlit.io](https://share.streamlit.io) → **New app** → выбрать репозиторий, ветку `main`, файл `app.py`.
3. **Advanced settings → Secrets** добавить РФ-прокси:
   ```toml
   CBR_PROXY = "socks5h://USER:PASS@HOST:PORT"
   ```
4. Deploy. Облако стартует с пустой БД, `bootstrap()` населит её (сиды + фетч ЦБ через прокси). Каждый `git push` → авто-передеплой.

## Структура
```
app.py          Streamlit-приложение (overview + Газ/Тормоз/Результат + Методология)
db.py           схема + чтение/запись SQLite
transforms.py   производные ряды (YoY, разрыв, дефицит/план)
ingest/         загрузчики ЦБ (cbr_*) + seed_loader + общий cbr_session
data/seed/      ручные CSV (наблюдаемая инфляция, ожидания, вклады, бюджет, ФНБ)
```
