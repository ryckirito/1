"""A 股市场规则相关的小工具。"""
from __future__ import annotations


def board_of(code: str) -> str:
    """根据代码判断板块。"""
    code = str(code).zfill(6)
    if code.startswith("68"):
        return "科创板"
    if code.startswith("30"):
        return "创业板"
    if code.startswith(("4", "8", "92")):
        return "北交所"
    if code.startswith(("60", "00")):
        return "主板"
    return "其他"


def limit_pct(code: str, name: str = "") -> float:
    """涨跌停幅度（百分比）。"""
    if "ST" in str(name).upper():
        return 5.0
    board = board_of(code)
    if board in ("科创板", "创业板"):
        return 20.0
    if board == "北交所":
        return 30.0
    return 10.0


def is_st(name: str) -> bool:
    return "ST" in str(name).upper()


def exchange_of(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("0", "2", "3")):
        return "sz"
    return "bj"


def eastmoney_secid(code: str) -> str:
    """东方财富 secid：沪市 1.xxxxxx，深市 / 北交所 0.xxxxxx。"""
    code = str(code).zfill(6)
    market = "1" if exchange_of(code) == "sh" else "0"
    return f"{market}.{code}"
