"""本地 CSV 数据源。

目录下每只股票一个文件 `<code>.csv`（也支持 `<code>_<name>.csv`），列至少包含：
date, open, high, low, close, volume, amount。可选列 name / turnover。
也可以放一个 `all.csv` 长表，含 code 列。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from .base import DataProvider, normalize_history

_COLUMN_ALIASES = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "代码": "code",
    "名称": "name",
    "股票代码": "code",
    "股票名称": "name",
}


def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"code": str, "代码": str, "股票代码": str})
    df = df.rename(columns={c: _COLUMN_ALIASES.get(str(c).strip(), str(c).strip().lower()) for c in df.columns})
    return df


class CsvProvider(DataProvider):
    name = "csv"

    def __init__(self, csv_dir: str | Path, watchlist: list[str] | None = None):
        self.csv_dir = Path(csv_dir)
        self.watchlist = list(watchlist or [])

    def load_history(self, end: dt.date, start: dt.date) -> pd.DataFrame:
        if not self.csv_dir.exists():
            raise FileNotFoundError(f"CSV 目录不存在: {self.csv_dir}")
        frames: list[pd.DataFrame] = []
        all_file = self.csv_dir / "all.csv"
        if all_file.exists():
            frames.append(_read_csv(all_file))
        for path in sorted(self.csv_dir.glob("*.csv")):
            if path.name == "all.csv":
                continue
            stem = path.stem
            code, _, name = stem.partition("_")
            df = _read_csv(path)
            if "code" not in df.columns:
                df["code"] = code
            if "name" not in df.columns:
                df["name"] = name or code
            frames.append(df)
        if not frames:
            raise FileNotFoundError(f"CSV 目录中没有数据文件: {self.csv_dir}")
        df = normalize_history(pd.concat(frames, ignore_index=True))
        mask = (df["date"].dt.date >= start) & (df["date"].dt.date <= end)
        return df[mask].reset_index(drop=True)

    def describe(self) -> str:
        return f"csv:{self.csv_dir}"
