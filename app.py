"""Дашборд «Две руки российской макро» — Streamlit-приложение.

Шаг 3: лёгкие источники ЦБ end-to-end — ключевая ставка, деньги (M0/M2/M2X),
курс USD/RUB. Производные ряды (YoY, цель по M2, разрывы) и шапка-overview —
на шаге 5 (PRD §11).
"""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import get_series_meta, init_db, last_updated, read_series

st.set_page_config(
    page_title="Две руки российской макро",
    page_icon="🤝",
    layout="wide",
)

# Денежные ряды тянутся с 1993/2001 — для читаемости графика показываем недавнее.
MONEY_FROM = pd.Timestamp("2021-01-01")
# Инфляция: наблюдаемая засидена с весны 2026 — показываем недавнее окно.
INFL_FROM = pd.Timestamp("2025-01-01")
CPI_TARGET = 4.0  # цель ЦБ по инфляции, %

# Схема SQLite создаётся при старте, если её ещё нет (идемпотентно).
init_db()

st.title("🤝 Две руки российской макро")
st.caption(
    "Фискальное вливание против монетарного торможения. "
    "Прокси и сопоставление рядов, а не «настоящая инфляция»."
)


def _fmt_updated(iso: str | None) -> str:
    """ISO fetched_at (UTC) → 'дд.мм.гггг'."""
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def _source_caption(meta: dict, last_date) -> str:
    """Подпись под графиком: источник, единицы, частота, дата данных и загрузки."""
    url = meta.get("source_url", "")
    return (
        f"**Источник:** {meta.get('source_name', '—')} · [{url}]({url})  \n"
        f"**Единицы:** {meta.get('unit', '—')} · частота {meta.get('freq', '—')}  \n"
        f"**Данные по:** {last_date:%d.%m.%Y} · "
        f"загружено {_fmt_updated(last_updated(meta['id']))}"
    )


def _hover_tag(meta: dict, last_date) -> str:
    """Хвост для тултипа: источник + дата обновления (PRD §9 — в тултипе)."""
    return f"<br><sub>{meta.get('source_name', '—')} · обновлено {last_date:%d.%m.%Y}</sub>"


def _empty_hint(series_id: str, script: str) -> None:
    st.warning(f"Нет данных по `{series_id}`. Запустите загрузчик:\n\n`python {script}`")


def render_key_rate() -> None:
    """Блок «Тормоз»: ключевая ставка ЦБ — пошаговая линия + текущее значение."""
    df = read_series("key_rate")
    meta = get_series_meta("key_rate") or {}
    st.subheader("🛑 Тормоз · Ключевая ставка Банка России")
    if df.empty:
        _empty_hint("key_rate", "ingest/cbr_keyrate.py")
        return

    last = df.iloc[-1]
    current_rate = last["value"]
    # Дата вступления текущего значения в силу = последняя точка СМЕНЫ ставки
    # (не первое появление значения: ставка циклична, 16.0 была в 2023-12 и 2025-12).
    changed = df["value"].ne(df["value"].shift())
    effective_from = df.loc[changed, "date"].iloc[-1]

    c1, c2 = st.columns([1, 3])
    c1.metric("Ставка сейчас", f"{current_rate:g}%", help=f"Действует с {effective_from:%d.%m.%Y}")
    c2.caption(_source_caption(meta, last["date"]))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"], mode="lines",
        line=dict(shape="hv", width=2, color="#c1121f"),  # шаговая: держится до след. изменения
        hovertemplate="%{x|%d.%m.%Y}<br>Ставка: %{y:g}% годовых"
                      + _hover_tag(meta, last["date"]) + "<extra></extra>",
    ))
    fig.update_layout(
        height=400, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="% годовых", hovermode="x unified", showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")


def render_inflation() -> None:
    """Блок «Результат» (хедлайн): официальная ИПЦ против наблюдаемой + ожидания."""
    cpi = read_series("cpi_yoy")
    obs = read_series("observed_infl")
    exp = read_series("infl_expect")
    st.subheader("🌡️ Результат · Инфляция: официальная против наблюдаемой")
    if cpi.empty and obs.empty:
        _empty_hint("cpi_yoy/observed_infl", "ingest/cbr_cpi.py и ingest/seed_loader.py")
        return

    c1, c2, c3 = st.columns(3)
    if not cpi.empty:
        c1.metric("Официальная ИПЦ, % г/г", f"{cpi['value'].iloc[-1]:g}%",
                  help=f"Росстат/ЦБ · {cpi['date'].iloc[-1]:%m.%Y}")
    if not obs.empty:
        c2.metric("Наблюдаемая (ИнФОМ)", f"{obs['value'].iloc[-1]:g}%",
                  help=f"опрос ИнФОМ · {obs['date'].iloc[-1]:%m.%Y}")
    # Разрыв считаем на ПОСЛЕДНИЙ ОБЩИЙ месяц (не мешаем разные месяцы рядов).
    if not cpi.empty and not obs.empty:
        common = set(cpi["date"]) & set(obs["date"])
        if common:
            d = max(common)
            gap = (obs.loc[obs["date"] == d, "value"].iloc[0]
                   - cpi.loc[cpi["date"] == d, "value"].iloc[0])
            c3.metric("Разрыв (набл. − офиц.)", f"+{gap:.1f} пп",
                      help=f"на общий месяц {d:%m.%Y}")

    fig = go.Figure()
    fig.add_hline(y=CPI_TARGET, line=dict(color="#6c757d", width=1, dash="dot"),
                  annotation_text="цель ЦБ 4%", annotation_position="bottom right")
    if not cpi.empty:
        d = cpi[cpi["date"] >= INFL_FROM]
        m = get_series_meta("cpi_yoy") or {}
        fig.add_trace(go.Scatter(
            x=d["date"], y=d["value"], mode="lines", name="Официальная ИПЦ",
            line=dict(width=2.5, color="#1d3557"),
            hovertemplate="%{x|%m.%Y}<br>ИПЦ: %{y:g}% г/г"
                          + _hover_tag(m, d["date"].iloc[-1]) + "<extra></extra>",
        ))
    for sid, name, color in [("observed_infl", "Наблюдаемая (ИнФОМ)", "#e63946"),
                             ("infl_expect", "Ожидания населения", "#f4a261")]:
        s = read_series(sid)
        if s.empty:
            continue
        s = s[s["date"] >= INFL_FROM]
        m = get_series_meta(sid) or {}
        fig.add_trace(go.Scatter(
            x=s["date"], y=s["value"], mode="lines+markers", name=name,
            line=dict(width=2, color=color),
            hovertemplate=f"{name}<br>%{{x|%m.%Y}}: %{{y:g}}%"
                          + _hover_tag(m, s["date"].iloc[-1]) + "<extra></extra>",
        ))
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="% г/г", hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Официальная ИПЦ — `final` (Росстат/ЦБ); наблюдаемая и ожидания — `seed` "
        "(ручной ввод из отчётов ИнФОМ, дополняются помесячно). "
        "Разрыв «ощущаемая vs официальная» — суть дашборда, не «настоящая инфляция»."
    )


def render_money() -> None:
    """Блок «Результат»: денежные агрегаты M2 / M2X / M0 (уровни, млрд руб)."""
    st.subheader("📈 Результат · Денежная масса")
    series = [
        ("m2", "M2 (нац. определение)", "#1d3557"),
        ("m2x", "M2X (широкая)", "#457b9d"),
        ("m0", "M0 (наличные)", "#8d99ae"),
    ]
    fig = go.Figure()
    any_data = False
    last_date = None
    base_meta = {}
    for sid, name, color in series:
        df = read_series(sid)
        if df.empty:
            continue
        df = df[df["date"] >= MONEY_FROM]
        any_data = True
        last_date = df["date"].iloc[-1]
        base_meta = get_series_meta(sid) or {}
        # hover «closest» (см. ниже) → тултип самодостаточен: дата+значение+единицы+источник.
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["value"], mode="lines", name=name,
            line=dict(width=2, color=color),
            hovertemplate=f"{name}<br>%{{x|%d.%m.%Y}}: %{{y:,.0f}} млрд ₽"
                          + _hover_tag(base_meta, last_date) + "<extra></extra>",
        ))
    if not any_data:
        _empty_hint("m2/m0/m2x", "ingest/cbr_money.py")
        return

    m2 = read_series("m2")
    if not m2.empty:
        st.metric("M2 сейчас", f"{m2['value'].iloc[-1] / 1000:,.1f} трлн ₽".replace(",", " "))
    # Подпись источника берём от M2 (у всех трёх — один источник/единицы/частота).
    base_meta.setdefault("id", "m2")
    st.caption(_source_caption(get_series_meta("m2") or base_meta, last_date))
    st.caption(
        "ℹ️ Уровни денежных агрегатов. Темп M2 г/г и полоса цели ЦБ 5–10% — на шаге 5."
    )
    fig.update_layout(
        height=400, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="млрд руб", hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
    )
    st.plotly_chart(fig, width="stretch")


def render_fx() -> None:
    """Блок «Контекст»: курс USD/RUB (опционально, v1.5)."""
    df = read_series("usdrub")
    meta = get_series_meta("usdrub") or {}
    with st.expander("💱 Контекст · Курс USD/RUB", expanded=False):
        if df.empty:
            _empty_hint("usdrub", "ingest/cbr_fx.py")
            return
        last = df.iloc[-1]
        st.metric("USD/RUB", f"{last['value']:,.2f} ₽".replace(",", " "))
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["value"], mode="lines",
            line=dict(width=2, color="#2a9d8f"),
            hovertemplate="%{x|%d.%m.%Y}<br>%{y:.2f} ₽ за $1"
                          + _hover_tag(meta, last["date"]) + "<extra></extra>",
        ))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="руб. за $1", hovermode="x unified", showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(_source_caption(meta, last["date"]))


render_key_rate()
st.divider()
render_inflation()
st.divider()
render_money()
st.divider()
render_fx()

st.divider()
st.caption(
    "Данные бюджета и ФНБ (seed) уже в базе — блок «Газ» (дефицит vs план, ФНБ, ЧТОГУ) "
    "и шапка-overview собираются на шаге 5 (PRD §11)."
)
