from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd


class HistoryCache:
    """按 (code, end 日期) 缓存历史行情，避免同一天重复联网。"""

    def __init__(self, cache_dir: str | Path | None):
        self.dir = Path(cache_dir) if cache_dir else None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, code: str, end: dt.date) -> Path | None:
        if not self.dir:
            return None
        return self.dir / f"{code}_{end:%Y%m%d}.csv"

    def get(self, code: str, end: dt.date) -> pd.DataFrame | None:
        p = self._path(code, end)
        if p and p.exists():
            try:
                return pd.read_csv(p, dtype={"code": str})
            except Exception:  # 缓存损坏则忽略
                return None
        return None

    def put(self, code: str, end: dt.date, df: pd.DataFrame) -> None:
        p = self._path(code, end)
        if p is not None and not df.empty:
            df.to_csv(p, index=False)
