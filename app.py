"""Дашборд «Две руки российской макро» — Streamlit-приложение.

Шаг 5: шапка-overview + три блока (Газ / Тормоз / Результат) + Контекст +
производные ряды (transforms.py) + секция «Методология» с дисклеймерами.

Принцип (PRD §2): это ПРОКСИ и сопоставление рядов, а не «настоящая инфляция».
Сырые ряды — в БД (ingest/*, data/seed/*); производные считаются на лету (transforms.py).
"""
import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import transforms as T
from db import get_series_meta, init_db, last_updated, read_series
from transforms import BUDGET_PLAN_2026

st.set_page_config(page_title="Две руки российской макро", page_icon="🤝", layout="wide")


@st.cache_data(ttl=6 * 3600, show_spinner="Загрузка данных…")
def bootstrap() -> list[str]:
    """Гибридная загрузка данных (раз в 6 ч на процесс).

    Сиды (наблюдаемая инфляция, бюджет, ФНБ, вклады) — всегда из data/seed/*.csv
    (в репозитории). Ряды ЦБ дотягиваем с cbr.ru. На облаке (иностранный IP) ЦБ
    доступен только через прокси — мостим секрет st.secrets['CBR_PROXY'] в env,
    его читает ingest.cbr_session. Фетч ЦБ — best-effort: если недоступен,
    показываем seed-данные и предупреждение (дашборд не падает).
    """
    try:
        proxy = st.secrets.get("CBR_PROXY")  # секретов может не быть локально
    except Exception:
        proxy = None
    if proxy:
        os.environ["CBR_PROXY"] = proxy

    init_db()
    from ingest.seed_loader import load_all
    load_all()

    from ingest import cbr_cpi, cbr_fx, cbr_inflexp, cbr_keyrate, cbr_money
    errors: list[str] = []
    for name, fn in [("ключевая ставка", cbr_keyrate.ingest), ("курс", cbr_fx.ingest),
                     ("денежные агрегаты", cbr_money.ingest), ("ИПЦ", cbr_cpi.ingest),
                     ("ИнФОМ (наблюдаемая/ожидания)", cbr_inflexp.ingest)]:
        try:
            fn()
        except Exception as exc:  # фетч не должен ронять дашборд
            errors.append(f"{name} ({type(exc).__name__})")
    return errors


_BOOT_ERRORS = bootstrap()

CPI_TARGET = 4.0           # цель ЦБ по инфляции, %
M2_TARGET_LO, M2_TARGET_HI = 5.0, 10.0  # ориентир ЦБ по приросту M2, % г/г
# Окна по умолчанию для длинных рядов. Интерактивный зум — встроенный в Plotly
# (тянуть рамкой по графику; двойной клик — сброс), поэтому отдельной панели нет.
MONEY_FROM = pd.Timestamp("2021-01-01")  # деньги/ЧТОГУ: видно удвоение M2 с 2021
RECENT = pd.Timestamp("2024-01-01")      # ставка/инфляция/курс: пик ставки и текущий цикл


# ─────────────────────────────── хелперы ────────────────────────────────────
def _fmt_updated(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def _since(df: pd.DataFrame, ts: pd.Timestamp) -> pd.DataFrame:
    """Окно отображения для длинных рядов (производные считать ДО обрезки).
    Короткие seed-ряды (бюджет/ФНБ — 2026) не режем. Зум — встроенный в Plotly."""
    return df if df.empty else df[df["date"] >= ts]


def _hover_tag(meta: dict, last_date) -> str:
    return f"<br><sub>{meta.get('source_name', '—')} · обновлено {last_date:%d.%m.%Y}</sub>"


def _source_caption(meta: dict, last_date) -> str:
    url = meta.get("source_url", "")
    flag_note = "ручной seed, дополняется помесячно" if meta.get("id") in _SEED_IDS else "автозагрузка"
    return (
        f"**Источник:** {meta.get('source_name', '—')} · [{url}]({url})  \n"
        f"**Единицы:** {meta.get('unit', '—')} · частота {meta.get('freq', '—')} · {flag_note}  \n"
        f"**Данные по:** {last_date:%d.%m.%Y} · загружено {_fmt_updated(last_updated(meta['id']))}"
    )


def _empty_hint(series_id: str, script: str) -> None:
    st.warning(f"Нет данных по `{series_id}`. Запустите загрузчик:\n\n`python {script}`")


def _last(df: pd.DataFrame):
    return df["value"].iloc[-1] if not df.empty else None


def _qlabel(ts) -> str:
    """Timestamp → 'Q1-26' (метка квартала, без хардкода)."""
    return f"Q{(ts.month - 1) // 3 + 1}-{ts.year % 100:02d}"


_SEED_IDS = {"deposit_rate", "budget_deficit", "nwf_liquid", "gdp_real_yoy"}


# ─────────────────────────────── overview ───────────────────────────────────
def render_overview() -> None:
    st.title("🤝 Две руки российской макро")
    st.caption(
        "Перетягивание каната: **фискальное вливание** (бюджет, рост денег) против "
        "**монетарного торможения** (ставка, вклады). Внизу — датчики результата "
        "(инфляция официальная/наблюдаемая). Это прокси и сопоставление рядов, "
        "а не «настоящая инфляция»."
    )

    kr = read_series("key_rate")
    cpi = read_series("cpi_yoy")
    obs = read_series("observed_infl")
    m2y = T.yoy(read_series("m2"))
    dvp = T.deficit_vs_plan(read_series("budget_deficit"))
    gdp = read_series("gdp_real_yoy")
    g = T.gap(obs, cpi)
    implied = (T.naive_qtm_infl(_last(m2y), _last(gdp))
               if not m2y.empty and not gdp.empty else None)

    cols = st.columns(7)
    cols[0].metric("🛑 Ключевая ставка", f"{_last(kr):g}%" if not kr.empty else "—",
                   help="Банк России")
    cols[1].metric("💸 M2, % г/г", f"{_last(m2y):.1f}%" if not m2y.empty else "—",
                   help=f"ориентир ЦБ {M2_TARGET_LO:g}–{M2_TARGET_HI:g}% — сейчас выше")
    cols[2].metric("💰 Дефицит / план", f"{_last(dvp):.0f}%" if not dvp.empty else "—",
                   help=f"накопл. дефицит ÷ годовой план {BUDGET_PLAN_2026} трлн ₽")
    cols[3].metric("🌡️ Официальная ИПЦ", f"{_last(cpi):.1f}%" if not cpi.empty else "—",
                   help="Росстат/ЦБ, измеренная корзина, % г/г")
    cols[4].metric("💵 По деньгам*", f"{implied:.1f}%" if implied is not None else "—",
                   help="M2 г/г − реальный ВВП г/г. *Прокси при допущении V=const → "
                        "сейчас ЗАВЫШАЕТ, для справки, не измеритель")
    cols[5].metric("👁️ Наблюдаемая", f"{_last(obs):.1f}%" if not obs.empty else "—",
                   help="опрос ИнФОМ, ощущаемая населением")
    cols[6].metric("↔️ Разрыв", f"+{_last(g):.1f} пп" if not g.empty else "—",
                   help=f"наблюдаемая − официальная, общий месяц {g['date'].iloc[-1]:%m.%Y}"
                   if not g.empty else "")


# ─────────────────────────────── Газ ────────────────────────────────────────
def render_gas() -> None:
    st.subheader("⛽ Газ · Фискальное вливание")
    bud = read_series("budget_deficit")
    nwf = read_series("nwf_liquid")
    chtogu = read_series("net_gov_claims")

    if bud.empty and nwf.empty and chtogu.empty:
        _empty_hint("budget_deficit/nwf_liquid", "ingest/seed_loader.py и ingest/cbr_money.py")
        return

    # Дефицит факт vs годовой план — главный график блока.
    if not bud.empty:
        dvp = T.deficit_vs_plan(bud)
        c1, c2 = st.columns([1, 1])
        c1.metric("Дефицит, накопл.", f"{_last(bud):g} трлн ₽")
        c2.metric("Это от годового плана", f"{_last(dvp):.0f}%",
                  help=f"план-2026 = {BUDGET_PLAN_2026} трлн ₽ (перекрыт уже в марте)")
        b = bud  # бюджет — короткий seed-ряд (2026), без обрезки
        meta = get_series_meta("budget_deficit") or {}
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=b["date"], y=b["value"], name="Дефицит (накопл. с начала года)",
            marker_color="#e76f51",
            hovertemplate="%{x|%m.%Y}<br>дефицит: %{y:.3f} трлн ₽"
                          + _hover_tag(meta, b["date"].iloc[-1]) + "<extra></extra>",
        ))
        fig.add_hline(y=BUDGET_PLAN_2026, line=dict(color="#c1121f", width=2, dash="dash"),
                      annotation_text=f"годовой план {BUDGET_PLAN_2026} трлн",
                      annotation_position="top left")
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="трлн ₽", hovermode="closest", showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption(_source_caption(meta, bud["date"].iloc[-1]))

    # ФНБ и ЧТОГУ — рядом.
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Ликвидная часть ФНБ** — подушка под дефицит")
        if nwf.empty:
            st.caption("нет данных")
        else:
            n = nwf  # короткий seed-ряд
            meta = get_series_meta("nwf_liquid") or {}
            fig = go.Figure(go.Scatter(
                x=n["date"], y=n["value"], mode="lines+markers",
                line=dict(width=2, color="#2a9d8f"),
                hovertemplate="%{x|%m.%Y}<br>ФНБ ликв.: %{y:.3f} трлн ₽"
                              + _hover_tag(meta, n["date"].iloc[-1]) + "<extra></extra>"))
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="трлн ₽", hovermode="closest", showlegend=False)
            st.plotly_chart(fig, width="stretch")
    with g2:
        st.markdown("**ЧТОГУ** — требования банков к госуправлению (бюджетный канал)")
        if chtogu.empty:
            st.caption("нет данных")
        else:
            ch = _since(chtogu, MONEY_FROM)
            meta = get_series_meta("net_gov_claims") or {}
            fig = go.Figure(go.Scatter(
                x=ch["date"], y=ch["value"], mode="lines",
                line=dict(width=2, color="#e9c46a"),
                hovertemplate="%{x|%m.%Y}<br>ЧТОГУ: %{y:,.0f} млрд ₽"
                              + _hover_tag(meta, ch["date"].iloc[-1]) + "<extra></extra>"))
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="млрд ₽", hovermode="closest", showlegend=False)
            st.plotly_chart(fig, width="stretch")
    st.caption(
        "ЧТОГУ — *прокси* бюджетного канала создания денег (сырой stock), не точный "
        "«вклад в прирост M2». Структура расходов бюджета засекречена с 2022 — см. «Методологию»."
    )


# ─────────────────────────────── Тормоз ─────────────────────────────────────
def render_brake() -> None:
    st.subheader("🛑 Тормоз · Монетарное торможение")
    kr = read_series("key_rate")
    dep = read_series("deposit_rate")
    if kr.empty and dep.empty:
        _empty_hint("key_rate/deposit_rate", "ingest/cbr_keyrate.py и ingest/seed_loader.py")
        return

    c1, c2 = st.columns(2)
    if not kr.empty:
        changed = kr["value"].ne(kr["value"].shift())
        eff = kr.loc[changed, "date"].iloc[-1]
        c1.metric("Ключевая ставка", f"{_last(kr):g}%", help=f"действует с {eff:%d.%m.%Y}")
    if not dep.empty:
        c2.metric("Макс. ставка по вкладам", f"{_last(dep):g}%",
                  help=f"топ-10 банков · {dep['date'].iloc[-1]:%d.%m.%Y}")

    fig = go.Figure()
    if not kr.empty:
        k = _since(kr, RECENT)
        m = get_series_meta("key_rate") or {}
        fig.add_trace(go.Scatter(
            x=k["date"], y=k["value"], mode="lines", name="Ключевая ставка",
            line=dict(shape="hv", width=2.5, color="#c1121f"),
            hovertemplate="%{x|%d.%m.%Y}<br>ставка: %{y:g}%"
                          + _hover_tag(m, k["date"].iloc[-1]) + "<extra></extra>"))
    if not dep.empty:
        d = _since(dep, RECENT)
        m = get_series_meta("deposit_rate") or {}
        fig.add_trace(go.Scatter(
            x=d["date"], y=d["value"], mode="lines+markers", name="Макс. ставка по вкладам",
            line=dict(width=2, color="#f4a261"),
            hovertemplate="%{x|%d.%m.%Y}<br>вклады: %{y:g}%"
                          + _hover_tag(m, d["date"].iloc[-1]) + "<extra></extra>"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="% годовых",
                      hovermode="closest",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0))
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Высокая ставка и доходность вкладов «морозят» деньги на депозитах — это тормоз. "
        "Ставка по вкладам — `seed` (декадные данные ЦБ)."
    )


# ─────────────────────────────── Результат ──────────────────────────────────
def render_result() -> None:
    st.subheader("🌡️ Результат · Инфляция и деньги")

    # 1) Официальная vs наблюдаемая + ожидания.
    cpi = read_series("cpi_yoy")
    obs = read_series("observed_infl")
    if not (cpi.empty and obs.empty):
        fig = go.Figure()
        fig.add_hline(y=CPI_TARGET, line=dict(color="#6c757d", width=1, dash="dot"),
                      annotation_text="цель ЦБ 4%", annotation_position="bottom right")
        if not cpi.empty:
            d = _since(cpi, RECENT)
            m = get_series_meta("cpi_yoy") or {}
            fig.add_trace(go.Scatter(
                x=d["date"], y=d["value"], mode="lines", name="Официальная ИПЦ",
                line=dict(width=2.5, color="#1d3557"),
                hovertemplate="%{x|%m.%Y}<br>ИПЦ: %{y:.1f}% г/г"
                              + _hover_tag(m, d["date"].iloc[-1]) + "<extra></extra>"))
        for sid, name, color in [("observed_infl", "Наблюдаемая (ИнФОМ)", "#e63946"),
                                 ("infl_expect", "Ожидания населения", "#f4a261")]:
            s = read_series(sid)
            if s.empty:
                continue
            sc = _since(s, RECENT)
            m = get_series_meta(sid) or {}
            fig.add_trace(go.Scatter(
                x=sc["date"], y=sc["value"], mode="lines+markers", name=name,
                line=dict(width=2, color=color),
                hovertemplate=f"{name}<br>%{{x|%m.%Y}}: %{{y:.1f}}%"
                              + _hover_tag(m, sc["date"].iloc[-1]) + "<extra></extra>"))
        fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="% г/г",
                          hovermode="closest",
                          legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0))
        st.plotly_chart(fig, width="stretch")
        # «Во сколько раз» считаем динамически (ряд авто-обновляется — не хардкодить).
        ratio = ""
        common = (set(cpi["date"]) & set(obs["date"])) if not (cpi.empty or obs.empty) else set()
        if common:
            dd = max(common)
            cc = cpi.loc[cpi["date"] == dd, "value"].iloc[0]
            oo = obs.loc[obs["date"] == dd, "value"].iloc[0]
            if cc:
                ratio = f" На {dd:%m.%Y} наблюдаемая в {oo / cc:.1f} раза выше официальной."
        st.caption(
            "Официальная ИПЦ (Росстат/ЦБ) и наблюдаемая/ожидания (опрос ИнФОМ) — `final`, "
            "тянутся с cbr.ru. Разрыв «ощущаемая vs официальная» — суть дашборда." + ratio
        )

    # «Три взгляда на инфляцию» (v1.5): вменённая «по деньгам» — для справки.
    gdp = read_series("gdp_real_yoy")
    m2y = T.yoy(read_series("m2"))
    if not (cpi.empty or obs.empty or m2y.empty or gdp.empty):
        implied = T.naive_qtm_infl(_last(m2y), _last(gdp))
        gdp_v, gdp_d = _last(gdp), gdp["date"].iloc[-1]
        st.markdown("**Три взгляда на инфляцию** — это *разные вещи*, а не три оценки одной")
        lenses = [
            (f"Официальная<br><sub>ИПЦ · {cpi['date'].iloc[-1]:%m.%Y}</sub>", _last(cpi), "#1d3557"),
            ("«По деньгам» ⚠<br><sub>M2−ВВП · V=const</sub>", implied, "#e76f51"),
            (f"Наблюдаемая<br><sub>ИнФОМ · {obs['date'].iloc[-1]:%m.%Y}</sub>", _last(obs), "#e63946"),
        ]
        fig = go.Figure()
        for label, val, color in lenses:
            fig.add_trace(go.Bar(
                x=[label], y=[val], marker_color=color, width=0.5,
                text=[f"{val:.1f}%"], textposition="outside", cliponaxis=False,
                hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=40, b=10),
                          yaxis_title="% г/г", showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption(
            f"⚠️ **«По деньгам» — НЕ измеритель, а грубый прокси.** = M2 г/г ({_last(m2y):.1f}%) − "
            f"реальный ВВП г/г ({gdp_v:+.1f}%, {_qlabel(gdp_d)}) при **допущении постоянной скорости "
            f"денег (V=const)**, которое сейчас ЗАВЫШАЕТ оценку (в РФ скорость денег падает) — «для "
            f"справки» (PRD §2). Официальная — измеренная корзина Росстата; наблюдаемая — медианная "
            f"оценка населения. Дашборд показывает РАЗРЫВЫ между подходами, а не «настоящую» инфляцию."
        )
        econ = (f"сокращается ({gdp_v:+.1f}% г/г)" if gdp_v < 0
                else f"растёт на {gdp_v:.1f}% г/г")
        st.caption(
            f"📉 Контекст: реальный ВВП в {_qlabel(gdp_d)} — экономика {econ}, а M2 растёт на "
            f"{_last(m2y):.1f}% г/г. Чем сильнее деньги обгоняют выпуск, тем выше монетарный прокси."
        )

    # 2) Денежная масса: уровни + темп г/г с полосой цели.
    st.markdown("**Денежная масса**")
    mcol1, mcol2 = st.columns([3, 2])
    with mcol1:
        fig = go.Figure()
        any_money = False
        for sid, name, color in [("m2", "M2", "#1d3557"), ("m2x", "M2X (широкая)", "#457b9d"),
                                 ("m0", "M0 (наличные)", "#8d99ae")]:
            s = read_series(sid)
            if s.empty:
                continue
            any_money = True
            sc = _since(s, MONEY_FROM)
            m = get_series_meta(sid) or {}
            fig.add_trace(go.Scatter(
                x=sc["date"], y=sc["value"], mode="lines", name=name,
                line=dict(width=2, color=color),
                hovertemplate=f"{name}<br>%{{x|%m.%Y}}: %{{y:,.0f}} млрд ₽"
                              + _hover_tag(m, sc["date"].iloc[-1]) + "<extra></extra>"))
        if any_money:
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="млрд ₽", hovermode="closest",
                              legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0))
            st.plotly_chart(fig, width="stretch")
            st.caption("Уровни (номинал). M2 более чем удвоилась с 2021 — это «вливание».")
        else:
            _empty_hint("m2/m0/m2x", "ingest/cbr_money.py")
    with mcol2:
        m2y = T.yoy(read_series("m2"))
        if not m2y.empty:
            y = _since(m2y, MONEY_FROM)
            m = get_series_meta("m2") or {}
            fig = go.Figure()
            fig.add_hrect(y0=M2_TARGET_LO, y1=M2_TARGET_HI, fillcolor="#2a9d8f", opacity=0.12,
                          line_width=0, annotation_text="цель ЦБ 5–10%",
                          annotation_position="top left")
            fig.add_trace(go.Scatter(
                x=y["date"], y=y["value"], mode="lines", name="M2 г/г",
                line=dict(width=2.5, color="#c1121f"),
                hovertemplate="%{x|%m.%Y}<br>M2: %{y:.1f}% г/г"
                              + _hover_tag(m, y["date"].iloc[-1]) + "<extra></extra>"))
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="% г/г", hovermode="closest", showlegend=False)
            st.plotly_chart(fig, width="stretch")
            st.caption("Темп M2 г/г против ориентира ЦБ 5–10%.")


# ─────────────────────────────── Контекст ───────────────────────────────────
def render_context() -> None:
    df = read_series("usdrub")
    meta = get_series_meta("usdrub") or {}
    with st.expander("💱 Контекст · Курс USD/RUB", expanded=False):
        if df.empty:
            _empty_hint("usdrub", "ingest/cbr_fx.py")
            return
        d = _since(df, RECENT)
        st.metric("USD/RUB", f"{_last(df):,.2f} ₽".replace(",", " "))
        fig = go.Figure(go.Scatter(
            x=d["date"], y=d["value"], mode="lines", line=dict(width=2, color="#264653"),
            hovertemplate="%{x|%d.%m.%Y}<br>%{y:.2f} ₽ за $1"
                          + _hover_tag(meta, df["date"].iloc[-1]) + "<extra></extra>"))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="руб. за $1", hovermode="x unified", showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption(_source_caption(meta, df["date"].iloc[-1]))


# ─────────────────────────────── Методология ────────────────────────────────
def render_methodology() -> None:
    with st.expander("📐 Методология, оговорки и источники", expanded=False):
        st.markdown(
            f"""
**Прокси, не оракул.** Дашборд не вычисляет «настоящую инфляцию». Он показывает
*силы* (бюджет vs ЦБ) и *разрывы* между официальными рядами. Любое расхождение —
повод задуматься, а не готовая цифра.

**Флаги данных.** `final` — автозагрузка с первоисточника (ставка, курс, деньги, ИПЦ,
наблюдаемая инфляция и ожидания ИнФОМ); `seed` — ручной ввод из виджетов/пресс-релизов
(ставки по вкладам, дефицит бюджета, ФНБ), дополняется помесячно; `prelim`/`revised` —
для предварительных/пересмотренных значений. Частоту храним исходную (D/M), не апсемплим.

**Формулы (производные считаются на лету, не хранятся):**
- `YoY` = значение[t] / значение[t − 12 мес] − 1.
- `Разрыв инфляции` = наблюдаемая (ИнФОМ) − официальная ИПЦ, пп (по общим месяцам).
- `Дефицит / план` = накопленный дефицит ÷ годовой план ({BUDGET_PLAN_2026} трлн ₽).

**«Инфляция по деньгам» (наивный QTM) — показываем «для справки».**
`naive_qtm` = M2 г/г − реальный ВВП г/г (из уравнения обмена MV=PY при **V=const**).
Это монетарный ПРОКСИ, не измеритель: допущение V=const сейчас **завышает** оценку,
т.к. скорость денег в РФ падает (M2 растёт быстрее номинального ВВП). Реальный ВВП —
квартальный seed (Росстат). Скорость денег (velocity = номинальный ВВП ÷ M2) пока не
считаем — нужен квартальный номинальный ВВП (отложено).

**НДС не используем как измеритель инфляции.** Ставка НДС повышена 20 → 22 % с
01.01.2026 (плюс снижен порог УСН) — это структурный разрыв, а не инфляция спроса.
Добавлять такой ряд можно лишь с явной аннотацией разрыва.

**Засекреченность.** Структура расходов федбюджета закрыта с 2022 г. Поэтому «Газ»
показывает агрегаты (дефицит, ФНБ, ЧТОГУ как прокси бюджетного канала), а не разбивку
расходов. Непрозрачность — часть картины, мы её не маскируем.

**Источники:** Банк России (ставка, деньги, курс, ИПЦ, ИнФОМ), Минфин (бюджет, ФНБ),
Росстат (ИПЦ). Каждый график несёт источник, единицы и дату обновления в тултипе.
"""
        )


# ─────────────────────────────── сборка ─────────────────────────────────────
render_overview()
if _BOOT_ERRORS:
    st.warning(
        "⚠️ Не удалось обновить с ЦБ: " + ", ".join(_BOOT_ERRORS)
        + ". Показаны последние доступные / seed-данные. "
        "На облаке проверьте секрет `CBR_PROXY` (нужен РФ-прокси)."
    )
st.divider()
render_gas()
st.divider()
render_brake()
st.divider()
render_result()
st.divider()
render_context()
st.divider()
render_methodology()
