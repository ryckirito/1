from daily_report.config import RecommendConfig
from daily_report.indicators import enrich
from daily_report.recommend import recommend_all, score_symbol
from tests.conftest import make_history


def _uptrend(code="AAPL", name="Apple", seed=3, start_price=150.0):
    df = make_history(code=code, name=name, drift=0.0025, vol=0.008, seed=seed, start_price=start_price)
    df["volume"] = 5e6
    df["amount"] = df["volume"] * df["close"]
    return df


def test_uptrend_gets_recommended():
    cfg = RecommendConfig(min_score=50)
    r = score_symbol(enrich(_uptrend()), cfg)
    assert r is not None
    assert r.score >= 50
    assert r.stop_loss < r.entry < r.target
    assert r.entry <= r.close + 1e-9
    assert abs((r.target - r.entry) - cfg.reward_risk * (r.entry - r.stop_loss)) < 0.03
    assert float(r.shares).is_integer() and r.shares > 0
    assert r.position_pct <= cfg.max_position_pct + 1e-9
    assert r.shares * (r.entry - r.stop_loss) <= cfg.capital * cfg.risk_per_trade_pct / 100 + 1e-6
    assert r.ma200 == r.ma200  # not NaN


def test_fractional_shares():
    cfg = RecommendConfig(min_score=0, fractional_shares=True, capital=1000)
    r = score_symbol(enrich(_uptrend(start_price=800)), cfg)
    assert r is not None and 0 < r.shares < 1


def test_penny_and_big_moves_excluded():
    cfg = RecommendConfig(min_score=0, min_avg_dollar_volume=0)
    assert score_symbol(enrich(_uptrend(start_price=2.0)), cfg) is None
    df = _uptrend()
    last = len(df) - 1
    prev = df["close"].iloc[-2]
    df.at[last, "close"] = prev * 1.08
    df.at[last, "high"] = prev * 1.09
    assert score_symbol(enrich(df), cfg) is None
    df2 = _uptrend()
    df2.at[last, "close"] = prev * 0.94
    df2.at[last, "low"] = prev * 0.93
    df2.at[last, "open"] = prev * 0.99
    assert score_symbol(enrich(df2), cfg) is None


def test_gap_down_excluded_unless_disabled():
    cfg = RecommendConfig(min_score=0, min_avg_dollar_volume=0)
    df = _uptrend()
    last = len(df) - 1
    prev_low = df["low"].iloc[-2]
    df.at[last, "open"] = prev_low * 0.99
    df.at[last, "low"] = prev_low * 0.98
    df.at[last, "close"] = prev_low * 0.995
    assert score_symbol(enrich(df), cfg) is None
    assert score_symbol(enrich(df), RecommendConfig(min_score=0, min_avg_dollar_volume=0, exclude_gap_down=False)) is not None


def test_low_liquidity_and_short_history_excluded():
    df = _uptrend()
    df["volume"] = 1000
    df["amount"] = df["volume"] * df["close"]
    assert score_symbol(enrich(df), RecommendConfig(min_score=0)) is None
    short = _uptrend().iloc[-60:].reset_index(drop=True)
    assert score_symbol(enrich(short), RecommendConfig(min_score=0, min_avg_dollar_volume=0)) is None


def test_ma200_missing_uses_short_trend():
    df = _uptrend().iloc[-150:].reset_index(drop=True)
    r = score_symbol(enrich(df), RecommendConfig(min_score=0, min_avg_dollar_volume=0))
    assert r is not None and r.ma200 != r.ma200  # NaN
    assert any("MA20 > MA50" in x for x in r.reasons)


def test_downtrend_not_recommended():
    df = make_history(drift=-0.003, vol=0.01, seed=5)
    df["volume"] = 5e6
    df["amount"] = df["volume"] * df["close"]
    assert score_symbol(enrich(df), RecommendConfig()) is None


def test_recommend_all_top_n_and_exclude():
    cfg = RecommendConfig(min_score=0, top_n=2)
    panel = {c: enrich(_uptrend(code=c, seed=i)) for i, c in enumerate(["AAPL", "MSFT", "GOOGL", "SPY"])}
    out = recommend_all(panel, cfg, exclude={"SPY"})
    assert len(out) == 2 and out[0].score >= out[1].score and all(r.code != "SPY" for r in out)


def test_sector_cap_and_total_exposure():
    cfg = RecommendConfig(min_score=0, top_n=4, max_per_sector=1, max_total_exposure_pct=40, max_position_pct=15)
    panel = {c: enrich(_uptrend(code=c, seed=i)) for i, c in enumerate(["AAPL", "MSFT", "GOOGL", "AMZN"])}
    out = recommend_all(panel, cfg)
    # 全部同板块（Technology），只能留 1 只
    assert len(out) == 1
    # 单只仓位上限 = min(15, 40/4) = 10%
    assert out[0].position_pct <= 10.0 + 1e-9
    cfg2 = RecommendConfig(min_score=0, top_n=4, max_total_exposure_pct=100, max_position_pct=15)
    out2 = recommend_all(panel, cfg2)
    assert len(out2) == 4 and all(r.position_pct <= 15.0 + 1e-9 for r in out2)
    assert all(len(r.closes) == 60 for r in out2)
