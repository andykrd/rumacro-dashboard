"""Производные ряды (PRD §8). Считаем на лету из сырых рядов БД — не храним.

Все функции принимают/возвращают DataFrame со столбцами [date, value]
(date — datetime). Сырые ряды отделены от производных (CLAUDE.md).

НЕ считаем в v1 (нужен квартальный номинальный ВВП Росстата — в v1.5 не загружен):
  velocity_proxy   = ВВП(annualized) / M2
  naive_qtm_infl   = M2 YoY − реальный ВВП YoY
Формулы и обязательная оговорка «V = const → сейчас завышает, для справки» —
в секции «Методология» приложения, не здесь (чтобы не плодить непротестированный код).
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
