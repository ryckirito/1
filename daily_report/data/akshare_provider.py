"""akshare 数据源（可选依赖：pip install akshare）。"""
from __future__ import annotations

import datetime as dt
import logging
import time

import pandas as pd

from ._cache import HistoryCache
from .base import DataProvider, normalize_history

log = logging.getLogger(__name__)


class AkshareProvider(DataProvider):
    name = "akshare"

    def __init__(
        self,
        max_symbols: int = 300,
        watchlist: list[str] | None = None,
        cache_dir: str | None = None,
        request_interval: float = 0.1,
    ):
        try:
            import akshare  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError("使用 akshare 数据源需要先安装：pip install akshare") from exc
        self.max_symbols = max_symbols
        self.watchlist = [str(c).zfill(6) for c in (watchlist or [])]
        self.cache = HistoryCache(cache_dir)
        self.request_interval = request_interval

    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        import akshare as ak

        spot = ak.stock_zh_a_spot_em()
        spot = spot.rename(columns={"代码": "code", "名称": "name", "成交额": "amount", "涨跌幅": "pct_chg", "量比": "vol_ratio"})
        spot["code"] = spot["code"].astype(str).str.zfill(6)
        n, k = self.max_symbols, max(10, self.max_symbols // 10)
        picks = (
            spot.nlargest(n, "amount")["code"].tolist()
            + spot.nlargest(k, "pct_chg")["code"].tolist()
            + spot.nsmallest(k, "pct_chg")["code"].tolist()
            + self.watchlist
        )
        seen: set[str] = set()
        universe = [c for c in picks if not (c in seen or seen.add(c))]
        names = dict(zip(spot["code"], spot["name"]))
        frames = []
        for i, code in enumerate(universe):
            df = self.cache.get(code, end)
            if df is None:
                try:
                    raw = ak.stock_zh_a_hist(
                        symbol=code, period="daily", start_date=f"{start:%Y%m%d}", end_date=f"{end:%Y%m%d}", adjust="qfq"
                    )
                except Exception as exc:
                    log.warning("拉取 %s 失败: %s", code, exc)
                    continue
                if raw is None or raw.empty:
                    continue
                df = raw.rename(
                    columns={
                        "日期": "date",
                        "开盘": "open",
                        "收盘": "close",
                        "最高": "high",
                        "最低": "low",
                        "成交量": "volume",
                        "成交额": "amount",
                        "换手率": "turnover",
                    }
                )[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]
                df["code"] = code
                df["name"] = names.get(code, code)
                self.cache.put(code, end, df)
                if self.request_interval:
                    time.sleep(self.request_interval)
            frames.append(df)
            if (i + 1) % 50 == 0:
                log.info("已拉取 %d/%d", i + 1, len(universe))
        if not frames:
            raise RuntimeError("未获取到任何历史行情")
        return normalize_history(pd.concat(frames, ignore_index=True))
