"""股票池：内置大盘股名单 / Nasdaq 筛选器 / 自定义文件。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from ..market import is_valid_ticker, normalize_ticker

log = logging.getLogger(__name__)

_BUILTIN = Path(__file__).parent / "universe_builtin.csv"
_NASDAQ_URL = "https://api.nasdaq.com/api/screener/stocks"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) daily-report/0.2",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Universe:
    frame: pd.DataFrame  # 列：ticker, name, sector[, market_cap]

    @property
    def tickers(self) -> list[str]:
        return self.frame["ticker"].tolist()

    def names(self) -> dict[str, str]:
        return dict(zip(self.frame["ticker"], self.frame["name"]))

    def sectors(self) -> dict[str, str]:
        return dict(zip(self.frame["ticker"], self.frame["sector"]))

    def market_caps(self) -> dict[str, float]:
        if "market_cap" not in self.frame.columns:
            return {}
        return dict(zip(self.frame["ticker"], self.frame["market_cap"]))


def _finalize(df: pd.DataFrame, max_symbols: int, watchlist: list[str], benchmarks: list[str]) -> Universe:
    df = df.copy()
    df["ticker"] = df["ticker"].map(normalize_ticker)
    df = df[df["ticker"].map(is_valid_ticker)]
    if "name" not in df.columns:
        df["name"] = df["ticker"]
    if "sector" not in df.columns:
        df["sector"] = ""
    df["name"] = df["name"].fillna(df["ticker"]).astype(str)
    df["sector"] = df["sector"].fillna("").astype(str)
    df = df.drop_duplicates("ticker")
    extra = [normalize_ticker(t) for t in [*watchlist, *benchmarks]]
    head = df[~df["ticker"].isin(extra)].head(max_symbols)
    tail = df[df["ticker"].isin(extra)]
    missing = [t for t in extra if t not in set(df["ticker"])]
    if missing:
        tail = pd.concat([tail, pd.DataFrame({"ticker": missing, "name": missing, "sector": ""})], ignore_index=True)
    return Universe(pd.concat([head, tail], ignore_index=True).drop_duplicates("ticker").reset_index(drop=True))


def load_builtin() -> pd.DataFrame:
    return pd.read_csv(_BUILTIN, dtype=str)


def load_file(path: str | Path) -> pd.DataFrame:
    """支持：每行一个代码的 txt，或含 ticker[,name,sector] 列的 csv。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"股票池文件不存在: {p}")
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        if "ticker" not in df.columns:
            if "symbol" in df.columns:
                df = df.rename(columns={"symbol": "ticker"})
            else:
                df = df.rename(columns={df.columns[0]: "ticker"})
        return df
    tickers = [line.strip() for line in p.read_text(encoding="utf-8").splitlines()]
    tickers = [t.split("#")[0].strip() for t in tickers if t and not t.startswith("#")]
    return pd.DataFrame({"ticker": [t for t in tickers if t]})


def fetch_nasdaq_screener(min_market_cap: float = 0.0, session: requests.Session | None = None) -> pd.DataFrame:
    """Nasdaq 股票筛选器：一次拿到全美股代码、名称、板块、市值。按市值降序。"""
    sess = session or requests.Session()
    params = {"tableonly": "true", "limit": "10000", "download": "true"}
    resp = sess.get(_NASDAQ_URL, params=params, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    rows = ((resp.json() or {}).get("data") or {}).get("rows") or []
    if not rows:
        raise RuntimeError("Nasdaq 筛选器返回为空")
    df = pd.DataFrame(rows)
    df = df.rename(columns={"symbol": "ticker", "marketCap": "market_cap"})
    df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
    df = df[df["ticker"].map(is_valid_ticker)]
    # 排除权证、优先股等（含 ^ / 空格）
    df = df[~df["ticker"].str.contains(r"[\^ ]", regex=True)]
    df = df[df["market_cap"].fillna(0) >= min_market_cap]
    df = df.sort_values("market_cap", ascending=False)
    return df[["ticker", "name", "sector", "market_cap"]].reset_index(drop=True)


def build_universe(
    kind: str,
    *,
    max_symbols: int,
    watchlist: list[str] | None = None,
    benchmarks: list[str] | None = None,
    min_market_cap: float = 0.0,
    session: requests.Session | None = None,
) -> Universe:
    kind = (kind or "builtin").strip()
    if kind == "builtin":
        df = load_builtin()
    elif kind == "nasdaq":
        df = fetch_nasdaq_screener(min_market_cap, session=session)
    else:
        df = load_file(kind)
    return _finalize(df, max_symbols, list(watchlist or []), list(benchmarks or []))
