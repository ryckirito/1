import datetime as dt

import numpy as np
import pandas as pd
import pytest


def make_history(code="AAPL", name="Apple", days=300, start_price=100.0, drift=0.0, vol=0.01, seed=1, end=None, sector="Technology"):
    """生成单只股票的历史行情（工作日）。"""
    rng = np.random.default_rng(seed)
    end = end or dt.date(2026, 9, 24)
    dates = []
    cur = end
    while len(dates) < days:
        if cur.weekday() < 5:
            dates.append(cur)
        cur -= dt.timedelta(days=1)
    dates = sorted(dates)
    rets = rng.normal(drift, vol, size=days)
    close = start_price * np.cumprod(1 + rets)
    open_ = close * (1 + rng.normal(0, 0.002, size=days))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    volume = np.full(days, 1e6) * np.exp(rng.normal(0, 0.1, size=days))
    df = pd.DataFrame(
        {
            "code": code,
            "name": name,
            "sector": sector,
            "date": pd.to_datetime(dates),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    df["amount"] = df["volume"] * df["close"]
    return df


@pytest.fixture
def history():
    return make_history()
