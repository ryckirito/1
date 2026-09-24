import numpy as np
import pandas as pd

from daily_report.indicators import enrich, rsi, sma, volume_ratio
from tests.conftest import make_history


def test_sma_and_volume_ratio():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert sma(s, 3).tolist()[-1] == 4.0
    v = pd.Series([100.0, 100.0, 100.0, 100.0, 300.0])
    vr = volume_ratio(v, 4)
    assert vr.iloc[-1] == 3.0
    assert np.isnan(vr.iloc[0])


def test_rsi_bounds_and_monotonic_up():
    up = pd.Series(np.linspace(10, 20, 40))
    r = rsi(up, 14)
    assert r.iloc[-1] == 100.0
    mixed = pd.Series(10 + np.sin(np.linspace(0, 20, 100)))
    r2 = rsi(mixed, 14).dropna()
    assert ((r2 >= 0) & (r2 <= 100)).all()


def test_enrich_columns():
    df = enrich(make_history())
    for col in ["pct_chg", "ma20", "ma60", "atr14", "rsi14", "vol_ratio", "hi_n", "lo_n", "amplitude", "ret_z", "ret20"]:
        assert col in df.columns
    assert not np.isnan(df["ma60"].iloc[-1])
    # hi_n 不含当日
    assert df["hi_n"].iloc[-1] <= df["high"].iloc[:-1].max() + 1e-9
