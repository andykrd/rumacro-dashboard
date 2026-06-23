"""Производные ряды (PRD §8). Считаем на лету из сырых рядов БД — не храним.

Все функции принимают/возвращают DataFrame со столбцами [date, value]
(date — datetime). Сырые ряды отделены от производных (CLAUDE.md).

v1.5 (§5 lead/lag): корреляции считаем ТОЛЬКО на стационарных преобразованиях
(темпы роста), скользящим окном, по заранее заданным гипотезам — см. функции ниже
и оговорки в приложении. velocity_proxy (номинальный ВВП / M2) не считаем —
нужен квартальный номинальный ВВП (не загружен).
"""
from __future__ import annotations

import pandas as pd

# Плановый дефицит федбюджета на 2026 г. (закон о бюджете), трлн ₽. PRD §8.
BUDGET_PLAN_2026 = 3.786


def yoy(df: pd.DataFrame) -> pd.DataFrame:
    """Темп прироста г/г, %: value[t] / value[t−12 мес] − 1.

    Сопоставление по ТОЧНОЙ дате (та же дата минус год) — устойчиво к пропускам
    и не зависит от того, есть ли строго 12 строк между точками.
    """
    if df.empty:
        return df[["date", "value"]].copy()
    cur = df[["date", "value"]].copy()
    prev = cur.assign(date=cur["date"] + pd.DateOffset(years=1)).rename(columns={"value": "_prev"})
    m = cur.merge(prev, on="date", how="inner")
    m["value"] = (m["value"] / m["_prev"] - 1.0) * 100.0
    return m[["date", "value"]].reset_index(drop=True)


def gap(observed: pd.DataFrame, official: pd.DataFrame) -> pd.DataFrame:
    """Разрыв «наблюдаемая − официальная», пп, по общим датам."""
    m = observed[["date", "value"]].merge(
        official[["date", "value"]], on="date", suffixes=("_obs", "_off")
    )
    m["value"] = m["value_obs"] - m["value_off"]
    return m[["date", "value"]].reset_index(drop=True)


def deficit_vs_plan(df: pd.DataFrame, plan: float = BUDGET_PLAN_2026) -> pd.DataFrame:
    """Накопленный дефицит в % от годового плана (план — в тех же единицах, трлн ₽)."""
    out = df[["date", "value"]].copy()
    out["value"] = out["value"] / plan * 100.0
    return out


def naive_qtm_infl(m2_yoy: float, gdp_real_yoy: float) -> float:
    """«Вменённая инфляция по деньгам» = M2 г/г − реальный ВВП г/г (QTM при V=const).

    Из уравнения обмена MV = PY в темпах: %P = %M − %Y + %V. При допущении
    V = const (%V = 0) получаем %P ≈ M2 г/г − реальный ВВП г/г.

    ⚠ ДОПУЩЕНИЕ V = const. В РФ скорость денег падает (M2 растёт быстрее
    номинального ВВП), поэтому оценка СЕЙЧАС ЗАВЫШАЕТ инфляцию. Это монетарный
    ПРОКСИ «для справки», НЕ измеритель инфляции (PRD §2, §8). Берём последние
    доступные значения (M2 г/г — месячный, ВВП г/г — квартальный, периоды слегка
    разные — указывать в подписи).
    """
    return m2_yoy - gdp_real_yoy


# ───────────────────── v1.5: стационарность, корреляции, индекс ──────────────

def mom(df: pd.DataFrame) -> pd.DataFrame:
    """Темп прироста месяц-к-месяцу, % (стационарное преобразование)."""
    d = df[["date", "value"]].dropna().sort_values("date").copy()
    d["value"] = d["value"].pct_change() * 100.0
    return d.dropna().reset_index(drop=True)


def cumulative_index(df: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """Накопленный индекс от первой точки ряда (базис = base). Для «своей корзины»."""
    d = df[["date", "value"]].dropna().sort_values("date").copy()
    if d.empty or d["value"].iloc[0] == 0:
        return d.reset_index(drop=True)
    d["value"] = d["value"] / d["value"].iloc[0] * base
    return d.reset_index(drop=True)


def rolling_corr(a: pd.DataFrame, b: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    """Скользящая корреляция Пирсона двух рядов (окно `window`), по общим датам.

    ВАЖНО (§5): подавать СТАЦИОНАРНЫЕ ряды (yoy/mom), не уровни — иначе ложная связь.
    Возвращает [date, value=corr]; первые window−1 точек отбрасываются.
    """
    m = a[["date", "value"]].merge(b[["date", "value"]], on="date",
                                   suffixes=("_a", "_b")).sort_values("date")
    m["value"] = m["value_a"].rolling(window).corr(m["value_b"])
    return m[["date", "value"]].dropna().reset_index(drop=True)


def cross_corr(x: pd.DataFrame, y: pd.DataFrame, max_lag: int = 6) -> dict:
    """Кросс-корреляция на лагах k=−max_lag..+max_lag (x опережает y при k>0).

    ВАЖНО (§5): подавать СТАЦИОНАРНЫЕ ряды. corr(x[t], y[t+k]). Возвращает
    {lags:[(k,corr)], best_lag, best_corr, n}. n — число общих точек (эффективная
    выборка на лаге меньше; мощность низкая → индикативно, не доказательство).
    """
    m = x[["date", "value"]].merge(y[["date", "value"]], on="date",
                                   suffixes=("_x", "_y")).sort_values("date").reset_index(drop=True)
    n = len(m)
    lags = []
    for k in range(-max_lag, max_lag + 1):
        c = m["value_x"].corr(m["value_y"].shift(-k))
        lags.append((k, None if pd.isna(c) else round(float(c), 3)))
    valid = [(k, c) for k, c in lags if c is not None]
    best_lag, best_corr = max(valid, key=lambda kc: abs(kc[1])) if valid else (0, None)
    return {"lags": lags, "best_lag": best_lag, "best_corr": best_corr, "n": n}


def percentile_history(df: pd.DataFrame, value: float | None = None) -> float | None:
    """Перцентиль (0–100) значения в собственной истории ряда — для адаптивных алертов.

    value=None → берём последнее значение. Доля исторических значений строго ниже.
    """
    s = df["value"].dropna()
    if s.empty:
        return None
    v = s.iloc[-1] if value is None else value
    return float((s < v).mean() * 100.0)
