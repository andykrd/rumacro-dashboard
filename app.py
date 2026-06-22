"""Дашборд «Две руки российской макро» — Streamlit-приложение.

Шаг 2: первый лёгкий источник end-to-end — ключевая ставка ЦБ (SQLite → линия).
Блоки Газ / Тормоз / Результат и шапка-overview добавляются на следующих шагах (PRD §11).
"""
from datetime import datetime

import plotly.graph_objects as go
import streamlit as st

from db import get_series_meta, init_db, last_updated, read_series

st.set_page_config(
    page_title="Две руки российской макро",
    page_icon="🤝",
    layout="wide",
)

# Схема SQLite создаётся при старте, если её ещё нет (идемпотентно).
init_db()

st.title("🤝 Две руки российской макро")
st.caption(
    "Фискальное вливание против монетарного торможения. "
    "Прокси и сопоставление рядов, а не «настоящая инфляция»."
)


def _fmt_updated(iso: str | None) -> str:
    """ISO fetched_at (UTC) → 'дд.мм.гггг' для подписи о свежести."""
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def render_key_rate() -> None:
    """Блок «Тормоз»: ключевая ставка ЦБ — пошаговая линия + текущее значение."""
    df = read_series("key_rate")
    meta = get_series_meta("key_rate") or {}

    st.subheader("Тормоз · Ключевая ставка Банка России")

    if df.empty:
        st.warning(
            "Нет данных по ключевой ставке. Запустите загрузчик:\n\n"
            "`python ingest/cbr_keyrate.py`"
        )
        return

    last = df.iloc[-1]
    current_rate = last["value"]
    # Дата вступления текущего значения в силу = последняя точка СМЕНЫ ставки,
    # а не первое историческое появление значения: ставка циклична (напр. 16.0 была
    # и в 2023-12, и в 2025-12) — иначе «Действует с» соскочит на старую дату.
    changed = df["value"].ne(df["value"].shift())
    effective_from = df.loc[changed, "date"].iloc[-1]

    col_metric, col_meta = st.columns([1, 3])
    col_metric.metric(
        "Ставка сейчас",
        f"{current_rate:g}%",
        help=f"Действует с {effective_from:%d.%m.%Y}",
    )
    col_meta.caption(
        f"**Источник:** {meta.get('source_name', '—')} · "
        f"[{meta.get('source_url', '')}]({meta.get('source_url', '')})  \n"
        f"**Единицы:** {meta.get('unit', '—')} · частота {meta.get('freq', '—')} (дневная)  \n"
        f"**Данные по:** {last['date']:%d.%m.%Y} · загружено {_fmt_updated(last_updated('key_rate'))}"
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["value"],
            mode="lines",
            line=dict(shape="hv", width=2, color="#c1121f"),  # шаговая (held until next change)
            name="Ключевая ставка",
            hovertemplate="%{x|%d.%m.%Y}<br>Ставка: %{y:g}% годовых<extra></extra>",
        )
    )
    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="% годовых",
        xaxis_title=None,
        hovermode="x unified",
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")


render_key_rate()

st.divider()
st.caption("Блоки «Газ» и «Результат» — на следующих шагах сборки (PRD §11).")
