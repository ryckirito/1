"""合成行情数据源：用于离线演示与测试。

使用内置股票池的代码与名称，生成带趋势与波动的随机游走，并在最后一个交易日注入
若干典型异动（暴涨放量、财报跳空、52 周新高突破、破位新低、缩量等）。
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from ..market import normalize_ticker
from .base import DataProvider, normalize_history
from .universe import load_builtin


def trading_days(end: dt.date, n: int) -> list[dt.date]:
    days: list[dt.date] = []
    cur = end
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur -= dt.timedelta(days=1)
    return sorted(days)


class DemoProvider(DataProvider):
    name = "demo"

    def __init__(self, n_symbols: int = 80, seed: int = 42, watchlist: list[str] | None = None, benchmarks: list[str] | None = None):
        self.n_symbols = n_symbols
        self.seed = seed
        self.watchlist = [normalize_ticker(t) for t in (watchlist or [])]
        self.benchmarks = [normalize_ticker(t) for t in (benchmarks or [])]

    def _symbols(self) -> list[tuple[str, str, str]]:
        uni = load_builtin()
        stocks = uni[uni["sector"] != "ETF"].head(self.n_symbols)
        out = [tuple(r) for r in stocks[["ticker", "name", "sector"]].itertuples(index=False)]
        have = {t for t, _, _ in out}
        for t in [*self.benchmarks, *self.watchlist]:
            if t in have:
                continue
            row = uni[uni["ticker"] == t]
            if len(row):
                out.append((t, row["name"].iloc[0], row["sector"].iloc[0]))
            else:
                out.append((t, t, ""))
            have.add(t)
        return out

    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        n_days = max(260, int((end - start).days * 5 / 7) + 1)
        days = trading_days(end, n_days)
        rng = np.random.default_rng(self.seed)
        frames = []
        for idx, (code, name, sector) in enumerate(self._symbols()):
            is_etf = sector == "ETF"
            price0 = float(rng.uniform(20, 400)) if not is_etf else float(rng.uniform(300, 600))
            drift = float(rng.normal(0.0004, 0.0010))
            vol = float(rng.uniform(0.010, 0.030)) if not is_etf else 0.008
            rets = rng.normal(drift, vol, size=len(days))
            if idx % 4 == 0:
                rets[-40:] += 0.003     # 部分股票近期明确上行
            if idx % 9 == 3:
                rets[-30:] -= 0.0035    # 部分股票近期走弱
            close = price0 * np.cumprod(1 + rets)
            open_ = close * (1 + rng.normal(0, 0.004, size=len(days)))
            spread = np.abs(rng.normal(0.010, 0.005, size=len(days)))
            high = np.maximum(open_, close) * (1 + spread)
            low = np.minimum(open_, close) * (1 - spread)
            base_vol = float(rng.uniform(1e6, 4e7))
            volume = base_vol * np.exp(rng.normal(0, 0.3, size=len(days)))
            df = pd.DataFrame(
                {
                    "code": code,
                    "name": name,
                    "sector": sector,
                    "date": pd.to_datetime(days),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )
            df["amount"] = df["volume"] * (df["open"] + df["close"]) / 2
            if not is_etf:
                self._inject_anomaly(df, idx)
            frames.append(df)
        return normalize_history(pd.concat(frames, ignore_index=True))

    @staticmethod
    def _inject_anomaly(df: pd.DataFrame, idx: int) -> None:
        """在最后一日注入典型异动。"""
        last = len(df) - 1
        prev_close = df.at[last - 1, "close"]
        vol_base = df["volume"].iloc[-21:-1].mean()
        kind = idx % 11
        if kind == 1:   # 财报后跳空高开 + 暴涨放量
            df.at[last, "open"] = df.at[last - 1, "high"] * 1.06
            df.at[last, "close"] = prev_close * 1.14
            df.at[last, "high"] = df.at[last, "close"] * 1.01
            df.at[last, "low"] = df.at[last, "open"] * 0.99
            df.at[last, "volume"] = vol_base * 5.0
        elif kind == 2:  # 财报后跳空低开 + 暴跌放量
            df.at[last, "open"] = df.at[last - 1, "low"] * 0.93
            df.at[last, "close"] = prev_close * 0.86
            df.at[last, "low"] = df.at[last, "close"] * 0.99
            df.at[last, "high"] = df.at[last, "open"] * 1.01
            df.at[last, "volume"] = vol_base * 4.0
        elif kind == 3:  # 放量突破 52 周新高（涨幅温和）
            hi = df["high"].iloc[:-1].max()
            df.at[last, "open"] = prev_close * 1.005
            df.at[last, "close"] = min(max(hi * 1.01, prev_close * 1.03), prev_close * 1.08)
            df.at[last, "high"] = df.at[last, "close"] * 1.004
            df.at[last, "low"] = prev_close * 0.998
            df.at[last, "volume"] = vol_base * 2.8
        elif kind == 4:  # 大振幅：冲高回落
            df.at[last, "open"] = prev_close * 1.01
            df.at[last, "high"] = prev_close * 1.07
            df.at[last, "low"] = prev_close * 0.97
            df.at[last, "close"] = prev_close * 0.975
            df.at[last, "volume"] = vol_base * 2.0
        elif kind == 5:  # 破 52 周新低
            lo = df["low"].iloc[:-1].min()
            df.at[last, "open"] = prev_close * 0.99
            df.at[last, "close"] = max(min(lo * 0.985, prev_close * 0.95), prev_close * 0.90)
            df.at[last, "low"] = df.at[last, "close"] * 0.995
            df.at[last, "high"] = prev_close * 1.0
            df.at[last, "volume"] = vol_base * 1.8
        elif kind == 6:  # 极度缩量
            df.at[last, "volume"] = vol_base * 0.25
        elif kind == 8:  # 温和大涨（6%）
            df.at[last, "open"] = prev_close * 1.01
            df.at[last, "close"] = prev_close * 1.06
            df.at[last, "high"] = df.at[last, "close"] * 1.005
            df.at[last, "low"] = prev_close * 1.0
            df.at[last, "volume"] = vol_base * 1.6
        df.at[last, "amount"] = df.at[last, "volume"] * (df.at[last, "open"] + df.at[last, "close"]) / 2
