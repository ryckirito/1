"""本地 CSV 数据源。

目录下每只股票一个文件 `<TICKER>.csv`，列至少包含：date, open, high, low, close, volume。
amount 缺失时按 close*volume 估算。也可以放一个 `all.csv` 长表（含 code/ticker 列）。
兼容 Yahoo Finance 导出格式（Date, Open, High, Low, Close, Adj Close, Volume）。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from .base import DataProvider, normalize_history

_COLUMN_ALIASES = {
    "ticker": "code",
    "symbol": "code",
    "adj close": "adj_close",
    "adj_close": "adj_close",
}


def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"code": str, "ticker": str, "symbol": str})
    df = df.rename(columns={c: _COLUMN_ALIASES.get(str(c).strip().lower(), str(c).strip().lower()) for c in df.columns})
    if "amount" not in df.columns and {"close", "volume"} <= set(df.columns):
        df["amount"] = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df["volume"], errors="coerce")
    return df


class CsvProvider(DataProvider):
    name = "csv"

    def __init__(self, csv_dir: str | Path):
        self.csv_dir = Path(csv_dir)

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
            code, _, name = path.stem.partition("_")
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
