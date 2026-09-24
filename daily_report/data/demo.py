"""合成行情数据源：用于离线演示与测试。

生成带趋势与波动的随机游走，并在最后一个交易日注入若干典型异动
（涨停、放量突破、跳空低开、破位新低等），使报告有内容可看。
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from ..market import limit_pct
from .base import DataProvider, normalize_history

_NAMES = [
    "华锐科技", "中天新材", "长江电子", "恒远医药", "海通装备", "云帆软件", "远航物流", "启明半导",
    "金石能源", "北斗通信", "紫光新能", "天禾食品", "鹏程汽车", "翠微零售", "宏图建材", "银河传媒",
    "赛峰航空", "沃土农业", "凌云光电", "泰山钢铁", "明月家居", "青松环保", "东方数控", "海纳生物",
    "星辰旅游", "腾龙机械", "百川化工", "锦绣纺织", "飞跃电池", "润泽水务",
]


def _trading_days(end: dt.date, n: int) -> list[dt.date]:
    days: list[dt.date] = []
    cur = end
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur -= dt.timedelta(days=1)
    return sorted(days)


class DemoProvider(DataProvider):
    name = "demo"

    def __init__(self, n_symbols: int = 80, seed: int = 42, watchlist: list[str] | None = None):
        self.n_symbols = n_symbols
        self.seed = seed
        self.watchlist = list(watchlist or [])

    def _symbols(self) -> list[tuple[str, str]]:
        rng = np.random.default_rng(self.seed)
        prefixes = ["600", "000", "002", "300", "688"]
        out: list[tuple[str, str]] = []
        used: set[str] = set()
        i = 0
        while len(out) < self.n_symbols:
            pre = prefixes[i % len(prefixes)]
            code = f"{pre}{int(rng.integers(0, 1000)):03d}"
            if code in used:
                i += 1
                continue
            used.add(code)
            base = _NAMES[len(out) % len(_NAMES)]
            suffix = "" if len(out) < len(_NAMES) else chr(ord("A") + (len(out) // len(_NAMES)) - 1)
            name = f"{base}{suffix}"
            if len(out) % 23 == 7:
                name = f"ST{name[:3]}"
            out.append((code, name))
            i += 1
        for w in self.watchlist:
            w = str(w).zfill(6)
            if w not in used:
                out.append((w, f"自选{w[-3:]}"))
                used.add(w)
        return out

    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        n_days = max(80, int((end - start).days * 5 / 7) + 1)
        days = _trading_days(end, n_days)
        rng = np.random.default_rng(self.seed)
        frames = []
        symbols = self._symbols()
        for idx, (code, name) in enumerate(symbols):
            price0 = float(rng.uniform(5, 80))
            drift = float(rng.normal(0.0004, 0.0012))
            vol = float(rng.uniform(0.012, 0.035))
            rets = rng.normal(drift, vol, size=len(days))
            # 部分股票给一个明确趋势，便于推荐模块有候选
            if idx % 4 == 0:
                rets[-40:] += 0.0035
            if idx % 9 == 3:
                rets[-30:] -= 0.004
            close = price0 * np.cumprod(1 + rets)
            open_ = close * (1 + rng.normal(0, 0.004, size=len(days)))
            spread = np.abs(rng.normal(0.012, 0.006, size=len(days)))
            high = np.maximum(open_, close) * (1 + spread)
            low = np.minimum(open_, close) * (1 - spread)
            base_vol = float(rng.uniform(2e6, 5e7))
            volume = base_vol * np.exp(rng.normal(0, 0.35, size=len(days)))
            df = pd.DataFrame(
                {
                    "code": code,
                    "name": name,
                    "date": pd.to_datetime(days),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )
            df["amount"] = df["volume"] * (df["open"] + df["close"]) / 2
            self._inject_anomaly(df, idx, rng)
            frames.append(df)
        return normalize_history(pd.concat(frames, ignore_index=True))

    @staticmethod
    def _inject_anomaly(df: pd.DataFrame, idx: int, rng: np.random.Generator) -> None:
        """在最后一日注入典型异动。"""
        last = len(df) - 1
        prev_close = df.at[last - 1, "close"]
        lim = limit_pct(df.at[last, "code"], df.at[last, "name"]) / 100
        kind = idx % 11
        if kind == 1:  # 涨停 + 放量
            df.at[last, "open"] = prev_close * 1.02
            df.at[last, "close"] = prev_close * (1 + lim * 0.995)
            df.at[last, "high"] = df.at[last, "close"]
            df.at[last, "low"] = prev_close * 1.01
            df.at[last, "volume"] = df["volume"].iloc[-6:-1].mean() * 4.5
        elif kind == 2:  # 跌停
            df.at[last, "open"] = prev_close * 0.97
            df.at[last, "close"] = prev_close * (1 - lim * 0.995)
            df.at[last, "low"] = df.at[last, "close"]
            df.at[last, "high"] = prev_close * 0.985
            df.at[last, "volume"] = df["volume"].iloc[-6:-1].mean() * 3.2
        elif kind == 3:  # 放量突破 60 日新高
            hi = df["high"].iloc[:-1].max()
            df.at[last, "open"] = prev_close * 1.01
            df.at[last, "close"] = min(max(hi * 1.02, prev_close * 1.04), prev_close * (1 + lim * 0.9))
            df.at[last, "high"] = df.at[last, "close"] * 1.005
            df.at[last, "low"] = prev_close * 1.0
            df.at[last, "volume"] = df["volume"].iloc[-6:-1].mean() * 3.5
        elif kind == 4:  # 跳空低开 + 大振幅
            df.at[last, "open"] = df.at[last - 1, "low"] * 0.95
            df.at[last, "low"] = df.at[last, "open"] * 0.97
            df.at[last, "high"] = prev_close * 1.03
            df.at[last, "close"] = prev_close * 0.96
        elif kind == 5:  # 破 60 日新低
            lo = df["low"].iloc[:-1].min()
            df.at[last, "open"] = prev_close * 0.99
            df.at[last, "close"] = max(min(lo * 0.98, prev_close * 0.95), prev_close * (1 - lim * 0.9))
            df.at[last, "low"] = df.at[last, "close"] * 0.995
            df.at[last, "high"] = prev_close * 1.0
        elif kind == 6:  # 极度缩量
            df.at[last, "volume"] = df["volume"].iloc[-6:-1].mean() * 0.2
        df.at[last, "amount"] = df.at[last, "volume"] * (df.at[last, "open"] + df.at[last, "close"]) / 2
