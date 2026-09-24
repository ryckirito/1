"""Yahoo Finance 数据源（通过 yfinance 批量下载，可选依赖：pip install yfinance）。"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from ..config import DataConfig
from ._cache import HistoryCache
from .base import DataProvider, normalize_history
from .universe import Universe, build_universe

log = logging.getLogger(__name__)


def wide_to_long(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """把 yf.download(group_by='ticker') 的宽表转成长表。"""
    frames = []
    single = not isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            sub = raw if single else raw[t]
        except KeyError:
            continue
        sub = sub.dropna(subset=["Close"]) if "Close" in sub.columns else pd.DataFrame()
        if sub.empty:
            continue
        df = pd.DataFrame(
            {
                "code": t,
                "date": sub.index,
                "open": sub["Open"].values,
                "high": sub["High"].values,
                "low": sub["Low"].values,
                "close": sub["Close"].values,
                "volume": sub["Volume"].values,
            }
        )
        df["amount"] = df["close"] * df["volume"]
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def __init__(self, cfg: DataConfig, universe: Universe | None = None):
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError("使用 yfinance 数据源需要先安装：pip install yfinance") from exc
        self.cfg = cfg
        self.cache = HistoryCache(cfg.cache_dir)
        self._universe = universe

    def universe(self) -> Universe:
        if self._universe is None:
            self._universe = build_universe(
                self.cfg.universe,
                max_symbols=self.cfg.max_symbols,
                watchlist=self.cfg.watchlist,
                benchmarks=self.cfg.benchmarks,
                min_market_cap=self.cfg.min_market_cap,
            )
        return self._universe

    def download(self, tickers: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        import yfinance as yf

        raw = yf.download(
            tickers,
            start=start.isoformat(),
            end=(end + dt.timedelta(days=1)).isoformat(),
            group_by="ticker",
            auto_adjust=True,
            actions=False,
            threads=True,
            progress=False,
        )
        return wide_to_long(raw, tickers)

    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        uni = self.universe()
        tickers = uni.tickers
        log.info("Yahoo Finance 股票池 %d 只，开始批量下载", len(tickers))
        cached = self.cache.get("__all__", end)
        if cached is not None and set(cached["code"]) >= set(tickers):
            long_df = cached[cached["code"].isin(tickers)]
        else:
            long_df = self.download(tickers, start, end)
            if long_df.empty:
                raise RuntimeError("Yahoo Finance 未返回任何行情")
            self.cache.put("__all__", end, long_df)
        names, sectors, caps = uni.names(), uni.sectors(), uni.market_caps()
        long_df = long_df.copy()
        long_df["name"] = long_df["code"].map(names).fillna(long_df["code"])
        long_df["sector"] = long_df["code"].map(sectors).fillna("")
        if caps:
            long_df["market_cap"] = long_df["code"].map(caps)
        return normalize_history(long_df)

    def describe(self) -> str:
        return f"yfinance:{self.cfg.universe}"
