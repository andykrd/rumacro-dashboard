"""Утилиты загрузчиков ЦБ (ingest/*).

cbr_session() — единый requests.Session для cbr.ru с учётом гео-блокировки.

cbr.ru режет иностранные IP (TLS reset). Поэтому:
  - env CBR_PROXY задан (socks5://… или http://… с РФ-exit) → ходим через него;
  - не задан → идём НАПРЯМУЮ, игнорируя http_proxy / ALL_PROXY окружения
    (их exit иностранный). См. CLAUDE.md и memory cbr-direct-no-proxy.
socks5:// требует PySocks (зависимость requests[socks]).
"""
import os

import requests

# Браузерный UA: часть эндпоинтов ЦБ (xlsx/HTML) гейтят по User-Agent.
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def cbr_session() -> requests.Session:
    """Session для запросов к cbr.ru (прокси из CBR_PROXY либо прямое соединение)."""
    s = requests.Session()
    s.trust_env = False  # не наследовать http_proxy/ALL_PROXY (иностранный exit режется ЦБ)
    proxy = os.environ.get("CBR_PROXY")
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update({"User-Agent": _UA})
    return s
