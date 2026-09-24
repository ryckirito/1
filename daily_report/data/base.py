from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

import pandas as pd

REQUIRED_COLUMNS = ["code", "name", "date", "open", "high", "low", "close", "volume", "amount"]
OPTIONAL_COLUMNS = ["turnover", "float_mcap", "industry"]


def normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    """校验并规范化历史行情长表。"""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"历史数据缺少列: {missing}")
    out = df.copy()
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["name"] = out["name"].astype(str)
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in OPTIONAL_COLUMNS:
        if col in out.columns and col != "industry":
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[out["close"] > 0]
    out = out.sort_values(["code", "date"]).drop_duplicates(["code", "date"], keep="last")
    return out.reset_index(drop=True)


class DataProvider(ABC):
    """数据源接口。"""

    name: str = "base"

    @abstractmethod
    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        """返回 [start, end] 区间内的历史行情长表（见 REQUIRED_COLUMNS）。"""

    def describe(self) -> str:
        return self.name
