import numpy as np

from daily_report.config import RecommendConfig
from daily_report.indicators import enrich
from daily_report.recommend import recommend_all, score_symbol
from tests.conftest import make_history


def _uptrend(code="600001", name="趋势股", seed=3):
    # 稳定上行 + 低波动 → 多头排列、动量健康、RSI 适中
    df = make_history(code=code, name=name, drift=0.004, vol=0.008, seed=seed, start_price=30.0)
    df["volume"] = 5e6
    df["amount"] = df["volume"] * df["close"]
    return df


def test_uptrend_gets_recommended():
    cfg = RecommendConfig(min_score=50, min_avg_amount=1e6)
    r = score_symbol(enrich(_uptrend()), cfg)
    assert r is not None
    assert r.score >= 50
    assert r.stop_loss < r.entry < r.target
    assert abs((r.target - r.entry) - cfg.reward_risk * (r.entry - r.stop_loss)) < 0.03  # 价格保留两位小数
    assert r.shares % 100 == 0 and r.shares > 0
    assert r.position_pct <= cfg.max_position_pct + 1e-9
    # 单笔风险不超过预算
    assert r.shares * (r.entry - r.stop_loss) <= cfg.capital * cfg.risk_per_trade_pct / 100 + 1e-6


def test_st_and_limit_up_excluded():
    cfg = RecommendConfig(min_score=0, min_avg_amount=0)
    st = _uptrend(name="ST趋势")
    assert score_symbol(enrich(st), cfg) is None
    lu = _uptrend()
    last = len(lu) - 1
    prev = lu["close"].iloc[-2]
    lu.at[last, "close"] = prev * 1.0995
    lu.at[last, "high"] = prev * 1.10
    assert score_symbol(enrich(lu), cfg) is None


def test_big_drop_and_gap_down_excluded():
    cfg = RecommendConfig(min_score=0, min_avg_amount=0)
    df = _uptrend()
    last = len(df) - 1
    prev = df["close"].iloc[-2]
    df.at[last, "close"] = prev * 0.94
    df.at[last, "low"] = prev * 0.93
    df.at[last, "open"] = prev * 0.99
    assert score_symbol(enrich(df), cfg) is None
    df2 = _uptrend()
    prev_low = df2["low"].iloc[-2]
    df2.at[last, "open"] = prev_low * 0.99
    df2.at[last, "low"] = prev_low * 0.98
    df2.at[last, "close"] = prev_low * 0.995
    assert score_symbol(enrich(df2), cfg) is None
    assert score_symbol(enrich(df2), RecommendConfig(min_score=0, min_avg_amount=0, exclude_gap_down=False)) is not None


def test_low_liquidity_and_short_history_excluded():
    cfg = RecommendConfig(min_score=0)
    df = _uptrend()
    df["volume"] = 1000
    df["amount"] = df["volume"] * df["close"]
    assert score_symbol(enrich(df), cfg) is None
    short = _uptrend().iloc[-40:].reset_index(drop=True)
    assert score_symbol(enrich(short), RecommendConfig(min_score=0, min_avg_amount=0)) is None


def test_downtrend_not_recommended():
    df = make_history(drift=-0.004, vol=0.01, seed=5)
    df["volume"] = 5e6
    df["amount"] = df["volume"] * df["close"]
    assert score_symbol(enrich(df), RecommendConfig(min_avg_amount=0)) is None


def test_recommend_all_top_n():
    cfg = RecommendConfig(min_score=0, min_avg_amount=0, top_n=2)
    panel = {c: enrich(_uptrend(code=c, seed=i)) for i, c in enumerate(["600001", "600002", "600003"])}
    out = recommend_all(panel, cfg)
    assert len(out) == 2
    assert out[0].score >= out[1].score
