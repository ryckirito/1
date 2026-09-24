"""联网数据源的解析与股票池逻辑（用假 session，不联网）。"""
import datetime as dt

import numpy as np
import pandas as pd

from daily_report.config import DataConfig
from daily_report.data.stooq import StooqProvider, parse_stooq_csv
from daily_report.data.universe import build_universe, fetch_nasdaq_screener, load_builtin, load_file
from daily_report.data.yfinance_provider import YFinanceProvider, wide_to_long


class _Resp:
    def __init__(self, payload=None, text=""):
        self._p, self.text, self.status_code = payload, text, 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _Session:
    headers = {}

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        if "nasdaq" in url:
            rows = [
                {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology", "marketCap": "3000000000000"},
                {"symbol": "TINY", "name": "Tiny Co", "sector": "Industrials", "marketCap": "50000000"},
                {"symbol": "BRK/B", "name": "Berkshire", "sector": "Finance", "marketCap": "900000000000"},
                {"symbol": "XYZ^A", "name": "Pref", "sector": "", "marketCap": "5000000000"},
            ]
            return _Resp({"data": {"rows": rows}})
        s = params["s"]
        if s == "bad.us":
            return _Resp(text="No data")
        lines = ["Date,Open,High,Low,Close,Volume"]
        for d in range(1, 25):
            day = dt.date(2026, 9, d)
            if day.weekday() < 5:
                lines.append(f"{day},10,11,9,10.5,1000")
        return _Resp(text="\n".join(lines))


def test_builtin_universe_and_file(tmp_path):
    uni = build_universe("builtin", max_symbols=10, watchlist=["nvda", "zzzz"], benchmarks=["SPY"])
    assert len(uni.tickers) == 13
    builtin = load_builtin()["ticker"]
    assert uni.tickers[:10] == builtin[~builtin.isin(["NVDA", "SPY"])].head(10).tolist()
    assert {"NVDA", "ZZZZ", "SPY"} <= set(uni.tickers)
    assert uni.names()["SPY"].startswith("SPDR") and uni.names()["ZZZZ"] == "ZZZZ"
    f = tmp_path / "u.txt"
    f.write_text("# 自选\nAAPL\nmsft # 微软\n\n", encoding="utf-8")
    assert load_file(f)["ticker"].tolist() == ["AAPL", "msft"]
    assert build_universe(str(f), max_symbols=5).tickers == ["AAPL", "MSFT"]
    c = tmp_path / "u.csv"
    c.write_text("Symbol,Name\nGOOGL,Alphabet\n", encoding="utf-8")
    u2 = build_universe(str(c), max_symbols=5)
    assert u2.tickers == ["GOOGL"] and u2.names()["GOOGL"] == "Alphabet"


def test_nasdaq_screener_parse():
    sess = _Session()
    df = fetch_nasdaq_screener(min_market_cap=1e9, session=sess)
    assert df["ticker"].tolist() == ["AAPL", "BRK/B"] or df["ticker"].tolist() == ["AAPL"]
    uni = build_universe("nasdaq", max_symbols=5, min_market_cap=1e9, session=sess)
    assert uni.tickers[0] == "AAPL" and uni.market_caps()["AAPL"] == 3e12


def test_stooq_provider(tmp_path):
    cfg = DataConfig(source="stooq", universe="builtin", max_symbols=2, watchlist=["BAD"], benchmarks=[], cache_dir=str(tmp_path), request_interval=0)
    sess = _Session()
    p = StooqProvider(cfg, session=sess)
    hist = p.load_history(end=dt.date(2026, 9, 24), start=dt.date(2026, 9, 1))
    assert set(hist["code"]) == {"AAPL", "MSFT"}
    assert hist[hist["code"] == "AAPL"]["name"].iloc[0] == "Apple"
    assert (hist["amount"] == hist["close"] * hist["volume"]).all()
    n = len(sess.calls)
    p.fetch_one("AAPL", dt.date(2026, 9, 1), dt.date(2026, 9, 24))
    assert len(sess.calls) == n  # 命中缓存
    assert parse_stooq_csv("", "X").empty


def test_yfinance_wide_to_long():
    idx = pd.to_datetime(["2026-09-22", "2026-09-23", "2026-09-24"])
    cols = pd.MultiIndex.from_product([["AAPL", "MSFT"], ["Open", "High", "Low", "Close", "Volume"]])
    raw = pd.DataFrame(np.ones((3, 10)), index=idx, columns=cols)
    raw.loc[idx[2], ("MSFT", "Close")] = np.nan
    long_df = wide_to_long(raw, ["AAPL", "MSFT", "GONE"])
    assert len(long_df) == 5 and set(long_df["code"]) == {"AAPL", "MSFT"}
    assert set(long_df.columns) >= {"code", "date", "open", "high", "low", "close", "volume", "amount"}


def test_yfinance_provider_uses_cache(tmp_path, monkeypatch):
    cfg = DataConfig(source="yfinance", universe="builtin", max_symbols=2, benchmarks=["SPY"], cache_dir=str(tmp_path))
    p = YFinanceProvider(cfg)
    calls = []

    def fake_download(tickers, start, end):
        calls.append(tickers)
        days = pd.bdate_range("2025-08-01", "2026-09-24")
        frames = []
        for t in tickers:
            frames.append(pd.DataFrame({"code": t, "date": days, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1e6, "amount": 1.05e7}))
        return pd.concat(frames, ignore_index=True)

    monkeypatch.setattr(p, "download", fake_download)
    hist = p.load_history(end=dt.date(2026, 9, 24), start=dt.date(2025, 8, 1))
    assert set(hist["code"]) == {"AAPL", "MSFT", "SPY"}
    assert hist[hist["code"] == "AAPL"]["sector"].iloc[0] == "Technology"
    p.load_history(end=dt.date(2026, 9, 24), start=dt.date(2025, 8, 1))
    assert len(calls) == 1
