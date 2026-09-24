"""东方财富数据源（直接调用公开行情接口，无需 akshare）。

流程：
1. 拉取全市场 A 股实时快照（一次请求即可拿到涨跌幅、量比、换手率等）；
2. 从快照中挑选候选池：成交额最大的前 N 只 + 当日涨跌幅/量比靠前的股票 + 自选股；
3. 逐只拉取候选池的日 K 线（前复权）。
"""
from __future__ import annotations

import datetime as dt
import logging
import time

import pandas as pd
import requests

from ..market import eastmoney_secid
from ._cache import HistoryCache
from .base import DataProvider, normalize_history

log = logging.getLogger(__name__)

_SPOT_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report/0.1"}

_SPOT_FIELDS = {
    "f12": "code",
    "f14": "name",
    "f2": "close",
    "f3": "pct_chg",
    "f5": "volume",
    "f6": "amount",
    "f7": "amplitude",
    "f8": "turnover",
    "f10": "vol_ratio",
    "f15": "high",
    "f16": "low",
    "f17": "open",
    "f18": "prev_close",
    "f21": "float_mcap",
    "f100": "industry",
}


class EastmoneyProvider(DataProvider):
    name = "eastmoney"

    def __init__(
        self,
        max_symbols: int = 300,
        watchlist: list[str] | None = None,
        cache_dir: str | None = None,
        request_interval: float = 0.05,
        session: requests.Session | None = None,
    ):
        self.max_symbols = max_symbols
        self.watchlist = [str(c).zfill(6) for c in (watchlist or [])]
        self.cache = HistoryCache(cache_dir)
        self.request_interval = request_interval
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)
        self.spot: pd.DataFrame | None = None

    # ---------- 快照 ----------
    def fetch_spot(self) -> pd.DataFrame:
        params = {
            "pn": 1,
            "pz": 10000,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f6",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": ",".join(_SPOT_FIELDS),
        }
        resp = self.session.get(_SPOT_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        rows = data.get("diff") or []
        df = pd.DataFrame(rows).rename(columns=_SPOT_FIELDS)
        if df.empty:
            raise RuntimeError("东方财富快照接口返回为空")
        df["code"] = df["code"].astype(str).str.zfill(6)
        for col in df.columns:
            if col not in ("code", "name", "industry"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # 停牌或无价数据行
        df = df[df["close"].notna() & (df["close"] > 0)]
        self.spot = df.reset_index(drop=True)
        return self.spot

    def select_universe(self, spot: pd.DataFrame) -> list[str]:
        """候选池：成交额前 N + 涨跌幅前后各 10% N + 量比前 10% N + 自选股。"""
        n = self.max_symbols
        k = max(10, n // 10)
        picks: list[str] = []
        picks += spot.nlargest(n, "amount")["code"].tolist()
        picks += spot.nlargest(k, "pct_chg")["code"].tolist()
        picks += spot.nsmallest(k, "pct_chg")["code"].tolist()
        if "vol_ratio" in spot.columns:
            picks += spot.nlargest(k, "vol_ratio")["code"].tolist()
        picks += self.watchlist
        seen: set[str] = set()
        ordered = [c for c in picks if not (c in seen or seen.add(c))]
        return ordered

    # ---------- K 线 ----------
    def fetch_kline(self, code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        cached = self.cache.get(code, end)
        if cached is not None:
            return cached
        params = {
            "secid": eastmoney_secid(code),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101,
            "fqt": 1,
            "beg": f"{start:%Y%m%d}",
            "end": f"{end:%Y%m%d}",
        }
        resp = self.session.get(_KLINE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        klines = data.get("klines") or []
        name = data.get("name", code)
        rows = []
        for line in klines:
            parts = line.split(",")
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "date": parts[0],
                    "open": parts[1],
                    "close": parts[2],
                    "high": parts[3],
                    "low": parts[4],
                    "volume": parts[5],
                    "amount": parts[6],
                    "turnover": parts[10] if len(parts) > 10 else None,
                }
            )
        df = pd.DataFrame(rows)
        self.cache.put(code, end, df)
        return df

    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        spot = self.fetch_spot()
        universe = self.select_universe(spot)
        log.info("东方财富候选池 %d 只，开始拉取日 K", len(universe))
        frames = []
        for i, code in enumerate(universe):
            try:
                df = self.fetch_kline(code, start, end)
                if not df.empty:
                    frames.append(df)
            except Exception as exc:  # 单只失败不影响整体
                log.warning("拉取 %s 失败: %s", code, exc)
            if self.request_interval:
                time.sleep(self.request_interval)
            if (i + 1) % 50 == 0:
                log.info("已拉取 %d/%d", i + 1, len(universe))
        if not frames:
            raise RuntimeError("未获取到任何历史行情")
        hist = normalize_history(pd.concat(frames, ignore_index=True))
        # 用快照中的行业 / 流通市值补充（字段缺失时跳过）
        extra_cols = [c for c in ("industry", "float_mcap") if c in spot.columns]
        if extra_cols:
            hist = hist.merge(spot[["code", *extra_cols]].drop_duplicates("code"), on="code", how="left")
        return hist
