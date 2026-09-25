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


def test_earnings_gap_up_huge_move(history):
    prev_high = history["high"].iloc[-2]
    prev = history["close"].iloc[-2]
    close = max(history["high"].iloc[:-1].max() * 1.01, prev * 1.15)
    df = _last(history, open=prev_high * 1.05, close=close, high=close * 1.01, low=prev_high * 1.04, volume=6e6)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None
    assert {"暴涨", "放量", "52周新高", "跳空高开"} <= set(a.tags)
    assert a.direction == "up" and a.score >= 60 and a.sector == "Technology"


def test_big_move_below_huge(history):
    prev = history["close"].iloc[-2]
    df = _last(history, open=prev, close=prev * 1.06, high=prev * 1.065, low=prev)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None and "大涨" in a.tags and "暴涨" not in a.tags


def test_gap_down_and_new_low(history):
    prev_low = history["low"].iloc[-2]
    lo = history["low"].iloc[:-1].min()
    close = min(lo * 0.97, prev_low * 0.94)
    df = _last(history, open=prev_low * 0.95, close=close, low=close * 0.99, high=prev_low * 0.96)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None
    assert "跳空低开" in a.tags and "52周新低" in a.tags and a.direction == "down"


def test_short_window_new_high_when_history_short():
    df = make_history(days=80)
    hi20 = df["high"].iloc[-21:-1].max()
    prev = df["close"].iloc[-2]
    df = _last(df, open=prev, close=max(hi20 * 1.01, prev * 1.02), high=max(hi20 * 1.02, prev * 1.03), low=prev)
    a = detect_symbol(enrich(df), AnomalyConfig())
    assert a is not None and "20日新高" in a.tags and "52周新高" not in a.tags


def test_volume_dry(history):
    df = _last(history, volume=1e5)
    assert detect_symbol(enrich(df), AnomalyConfig()) is None  # 单独缩量低于强度门槛
    a = detect_symbol(enrich(df), AnomalyConfig(min_score=0))
    assert a is not None and a.tags == ["缩量"]


def test_detect_all_sorted_and_excludes_benchmarks():
    quiet = enrich(make_history(code="MSFT"))
    hot = make_history(code="NVDA", seed=2)
    prev = hot["close"].iloc[-2]
    hot = enrich(_last(hot, open=prev * 1.02, close=prev * 1.12, high=prev * 1.13, low=prev * 1.01, volume=5e6))
    spy = enrich(_last(make_history(code="SPY", seed=3), volume=1e5))
    out = detect_all({"MSFT": quiet, "NVDA": hot, "SPY": spy}, AnomalyConfig(), exclude={"SPY"})
    assert [a.code for a in out] == ["NVDA"]
    assert not np.isnan(out[0].vol_ratio)


def test_excess_vs_benchmark_and_streak():
    import pandas as pd
    from daily_report.pipeline import attach_benchmark

    stock = make_history(code="NVDA", seed=7)
    spy = make_history(code="SPY", seed=8, sector="ETF")
    prev = stock["close"].iloc[-2]
    stock = _last(stock, open=prev, close=prev * 1.06, high=prev * 1.065, low=prev)
    panel = {"NVDA": enrich(stock), "SPY": enrich(spy)}
    attach_benchmark(panel, "SPY")
    a = detect_symbol(panel["NVDA"], AnomalyConfig())
    assert a is not None and "跑赢大盘" in a.tags and a.excess_pct > 4 and len(a.closes) == 60

    # 连涨 6 日
    up = make_history(code="AAPL", seed=9)
    for k in range(6, 0, -1):
        i = len(up) - k
        up.at[i, "close"] = up.at[i - 1, "close"] * 1.004
        up.at[i, "high"] = up.at[i, "close"] * 1.005
        up.at[i, "low"] = up.at[i, "close"] * 0.995
    a2 = detect_symbol(enrich(up), AnomalyConfig(min_score=0))
    assert a2 is not None and "6连涨" in a2.tags
