import numpy as np

from daily_report.anomaly import detect_all, detect_symbol
from daily_report.config import AnomalyConfig
from daily_report.indicators import enrich
from tests.conftest import make_history


def _last(df, **kw):
    last = len(df) - 1
    for k, v in kw.items():
        df.at[last, k] = v
    return df


def test_quiet_day_has_no_anomaly(history):
    assert detect_symbol(enrich(history), AnomalyConfig()) is None


def test_limit_up_with_volume_spike(history):
    prev = history["close"].iloc[-2]
    df = _last(history, open=prev * 1.02, close=prev * 1.0995, high=prev * 1.0995, low=prev * 1.01, volume=5e6)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None
    assert "涨停" in a.tags and "放量" in a.tags and "60日新高" in a.tags
    assert a.direction == "up"
    assert a.score >= 50


def test_limit_pct_depends_on_board():
    df = make_history(code="300001")
    prev = df["close"].iloc[-2]
    df = _last(df, open=prev * 1.02, close=prev * 1.0995, high=prev * 1.0995, low=prev)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None and "大涨" in a.tags and "涨停" not in a.tags


def test_gap_down_and_new_low(history):
    prev_low = history["low"].iloc[-2]
    lo = history["low"].iloc[:-1].min()
    df = _last(history, open=prev_low * 0.95, close=min(lo * 0.97, prev_low * 0.94), low=min(lo * 0.96, prev_low * 0.93), high=prev_low * 0.96)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None
    assert "跳空低开" in a.tags and "60日新低" in a.tags
    assert a.direction == "down"


def test_volume_dry(history):
    df = _last(history, volume=1e5)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None and a.tags == ["缩量"]


def test_detect_all_sorted():
    quiet = enrich(make_history(code="600001"))
    hot = make_history(code="600002", seed=2)
    prev = hot["close"].iloc[-2]
    hot = enrich(_last(hot, open=prev * 1.02, close=prev * 1.0995, high=prev * 1.0995, low=prev * 1.01, volume=5e6))
    out = detect_all({"600001": quiet, "600002": hot}, AnomalyConfig())
    assert [a.code for a in out] == ["600002"]
    assert not np.isnan(out[0].vol_ratio)
