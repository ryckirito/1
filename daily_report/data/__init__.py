"""数据源。统一输出长表 DataFrame：code, name, date, open, high, low, close, volume, amount[, turnover]。"""
from __future__ import annotations

from ..config import DataConfig
from .base import DataProvider, REQUIRED_COLUMNS, normalize_history


def make_provider(cfg: DataConfig) -> DataProvider:
    src = cfg.source.lower()
    if src == "demo":
        from .demo import DemoProvider

        return DemoProvider(n_symbols=cfg.demo_symbols, seed=cfg.demo_seed, watchlist=cfg.watchlist)
    if src == "csv":
        from .csv_provider import CsvProvider

        return CsvProvider(cfg.csv_dir, watchlist=cfg.watchlist)
    if src == "eastmoney":
        from .eastmoney import EastmoneyProvider

        return EastmoneyProvider(
            max_symbols=cfg.max_symbols,
            watchlist=cfg.watchlist,
            cache_dir=cfg.cache_dir,
            request_interval=cfg.request_interval,
        )
    if src == "akshare":
        from .akshare_provider import AkshareProvider

        return AkshareProvider(
            max_symbols=cfg.max_symbols,
            watchlist=cfg.watchlist,
            cache_dir=cfg.cache_dir,
            request_interval=cfg.request_interval,
        )
    raise ValueError(f"未知数据源: {cfg.source}（可选 demo/csv/eastmoney/akshare）")


__all__ = ["DataProvider", "REQUIRED_COLUMNS", "normalize_history", "make_provider"]
