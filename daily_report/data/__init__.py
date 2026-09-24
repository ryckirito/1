"""数据源。统一输出长表 DataFrame：code(ticker), name, date, open, high, low, close, volume, amount[, sector, market_cap]。"""
from __future__ import annotations

from ..config import DataConfig
from .base import DataProvider, REQUIRED_COLUMNS, normalize_history


def make_provider(cfg: DataConfig) -> DataProvider:
    src = cfg.source.lower()
    if src == "demo":
        from .demo import DemoProvider

        return DemoProvider(n_symbols=cfg.demo_symbols, seed=cfg.demo_seed, watchlist=cfg.watchlist, benchmarks=cfg.benchmarks)
    if src == "csv":
        from .csv_provider import CsvProvider

        return CsvProvider(cfg.csv_dir)
    if src == "yfinance":
        from .yfinance_provider import YFinanceProvider

        return YFinanceProvider(cfg)
    if src == "stooq":
        from .stooq import StooqProvider

        return StooqProvider(cfg)
    raise ValueError(f"未知数据源: {cfg.source}（可选 demo/csv/yfinance/stooq）")


__all__ = ["DataProvider", "REQUIRED_COLUMNS", "normalize_history", "make_provider"]
