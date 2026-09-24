"""美股市场相关的小工具。"""
from __future__ import annotations

import re

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def normalize_ticker(ticker: str) -> str:
    """统一为大写、用 '-' 连接的 Yahoo 风格代码（BRK.B -> BRK-B）。"""
    t = str(ticker).strip().upper().replace(".", "-")
    return t


def is_valid_ticker(ticker: str) -> bool:
    return bool(_TICKER_RE.match(normalize_ticker(ticker)))


def stooq_symbol(ticker: str) -> str:
    """Stooq 的美股代码：小写 + .us（BRK-B -> brk-b.us）。"""
    return f"{normalize_ticker(ticker).lower()}.us"


def is_penny(price: float, min_price: float = 5.0) -> bool:
    return price < min_price


def fmt_usd(value: float) -> str:
    """美元金额：$1.23B / $456M / $78K。"""
    if value is None or value != value:  # NaN
        return "-"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e12:
        return f"{sign}${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"{sign}${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{sign}${v / 1e3:.0f}K"
    return f"{sign}${v:.2f}"
