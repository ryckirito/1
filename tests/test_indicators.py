import numpy as np
import pandas as pd

from daily_report.indicators import enrich, rsi, sma, volume_ratio
from daily_report.market import fmt_usd, is_valid_ticker, normalize_ticker, stooq_symbol
from tests.conftest import make_history


def test_sma_and_volume_ratio():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert sma(s, 3).tolist()[-1] == 4.0
    v = pd.Series([100.0] * 10 + [300.0])
    vr = volume_ratio(v, 10)
    assert vr.iloc[-1] == 3.0
    assert np.isnan(vr.iloc[0])


def test_rsi_bounds_and_monotonic_up():
    up = pd.Series(np.linspace(10, 20, 40))
    assert rsi(up, 14).iloc[-1] == 100.0
    mixed = pd.Series(10 + np.sin(np.linspace(0, 20, 100)))
    r2 = rsi(mixed, 14).dropna()
    assert ((r2 >= 0) & (r2 <= 100)).all()


def test_enrich_columns():
    df = enrich(make_history())
    for col in ["pct_chg", "ma20", "ma50", "ma200", "atr14", "rsi14", "vol_ratio", "hi_long", "lo_long", "hi_short", "amplitude", "ret_z", "ret20"]:
        assert col in df.columns
    assert not np.isnan(df["ma200"].iloc[-1])
    assert df["hi_long"].iloc[-1] <= df["high"].iloc[:-1].max() + 1e-9
    # 历史不足 125 日时 52 周高低点为 NaN
    short = enrich(make_history(days=100))
    assert np.isnan(short["hi_long"].iloc[-1]) and not np.isnan(short["hi_short"].iloc[-1])


def test_market_helpers():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert is_valid_ticker("AAPL") and is_valid_ticker("BRK-B") and not is_valid_ticker("AAPL^A") and not is_valid_ticker("")
    assert stooq_symbol("BRK.B") == "brk-b.us"
    assert fmt_usd(1.23e9) == "$1.23B" and fmt_usd(4.5e6) == "$4.5M" and fmt_usd(float("nan")) == "-"
