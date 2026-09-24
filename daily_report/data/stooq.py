"""Stooq 数据源：免费日线 CSV，无需 API key，逐只请求。"""
from __future__ import annotations

import datetime as dt
import io
import logging
import time

import pandas as pd
import requests

from ..config import DataConfig
from ..market import stooq_symbol
from ._cache import HistoryCache
from .base import DataProvider, normalize_history
from .universe import Universe, build_universe

log = logging.getLogger(__name__)

_URL = "https://stooq.com/q/d/l/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report/0.2"}


def parse_stooq_csv(text: str, ticker: str) -> pd.DataFrame:
    if not text or text.strip().lower().startswith("no data") or "Date" not in text.splitlines()[0]:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(text))
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    df["code"] = ticker
    df["amount"] = df["close"] * df["volume"]
    return df[["code", "date", "open", "high", "low", "close", "volume", "amount"]]


class StooqProvider(DataProvider):
    name = "stooq"

    def __init__(self, cfg: DataConfig, universe: Universe | None = None, session: requests.Session | None = None):
        self.cfg = cfg
        self.cache = HistoryCache(cfg.cache_dir)
        self._universe = universe
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)

    def universe(self) -> Universe:
        if self._universe is None:
            self._universe = build_universe(
                self.cfg.universe,
                max_symbols=self.cfg.max_symbols,
                watchlist=self.cfg.watchlist,
                benchmarks=self.cfg.benchmarks,
                min_market_cap=self.cfg.min_market_cap,
                session=self.session,
            )
        return self._universe

    def fetch_one(self, ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        cached = self.cache.get(ticker, end)
        if cached is not None:
            return cached
        params = {"s": stooq_symbol(ticker), "d1": f"{start:%Y%m%d}", "d2": f"{end:%Y%m%d}", "i": "d"}
        resp = self.session.get(_URL, params=params, timeout=30)
        resp.raise_for_status()
        df = parse_stooq_csv(resp.text, ticker)
        self.cache.put(ticker, end, df)
        return df

    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        uni = self.universe()
        names, sectors, caps = uni.names(), uni.sectors(), uni.market_caps()
        frames = []
        tickers = uni.tickers
        log.info("Stooq 股票池 %d 只，开始逐只拉取", len(tickers))
        for i, t in enumerate(tickers):
            try:
                df = self.fetch_one(t, start, end)
                if not df.empty:
                    frames.append(df)
            except Exception as exc:
                log.warning("拉取 %s 失败: %s", t, exc)
            if self.cfg.request_interval:
                time.sleep(self.cfg.request_interval)
            if (i + 1) % 50 == 0:
                log.info("已拉取 %d/%d", i + 1, len(tickers))
        if not frames:
            raise RuntimeError("Stooq 未返回任何行情")
        long_df = pd.concat(frames, ignore_index=True)
        long_df["name"] = long_df["code"].map(names).fillna(long_df["code"])
        long_df["sector"] = long_df["code"].map(sectors).fillna("")
        if caps:
            long_df["market_cap"] = long_df["code"].map(caps)
        return normalize_history(long_df)

    def describe(self) -> str:
        return f"stooq:{self.cfg.universe}"
