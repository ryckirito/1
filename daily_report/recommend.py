"""推荐建仓：多因子评分 + 交易计划（入场 / 止损 / 目标 / 仓位）。

评分维度（满分 100）：
- 趋势 30：收盘 > MA20 > MA60 且 MA20 向上
- 动量 20：20 日涨幅落在健康区间（涨太多视为追高）
- 量能 15：当日量比 1.2~3 且收阳，或温和放量
- RSI  15：落在 rsi_low~rsi_high 区间
- 形态 20：回踩 MA20 附近（低吸）或放量突破 20 日新高（追强）
过滤：ST、涨停、流动性不足、波动过大、历史数据不足。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import RecommendConfig
from .market import is_st, limit_pct, board_of


@dataclass
class Recommendation:
    code: str
    name: str
    date: str
    close: float
    score: float
    setup: str                      # 回踩低吸 / 突破追强 / 趋势跟随
    entry: float
    stop_loss: float
    target: float
    risk_pct: float                 # (entry - stop)/entry * 100
    reward_risk: float
    shares: int                     # 建议股数（100 股整数倍）
    position_value: float           # 建议买入金额
    position_pct: float             # 占总资金百分比
    reasons: list[str] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)
    board: str = ""
    industry: str = ""
    ma20: float = 0.0
    ma60: float = 0.0
    rsi14: float = 0.0
    ret20: float = 0.0
    atr_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _clip_score(value: float, lo: float, hi: float, max_points: float) -> float:
    """value 在 [lo, hi] 内线性给分，越靠近 hi 分越高。"""
    if np.isnan(value):
        return 0.0
    if value <= lo:
        return 0.0
    if value >= hi:
        return max_points
    return max_points * (value - lo) / (hi - lo)


def score_symbol(df: pd.DataFrame, cfg: RecommendConfig) -> Recommendation | None:
    """df：单只股票 enrich 后的行情。返回评分与交易计划；不满足过滤条件时返回 None。"""
    if len(df) < cfg.min_history_days:
        return None
    row = df.iloc[-1]
    code, name = str(row["code"]), str(row["name"])
    if cfg.exclude_st and is_st(name):
        return None
    close = _f(row["close"])
    pct = _f(row["pct_chg"])
    if cfg.exclude_limit_up and pct >= limit_pct(code, name) * 0.98:
        return None
    if np.isnan(pct) or pct > cfg.max_daily_gain_pct or pct < -cfg.max_daily_loss_pct:
        return None
    if cfg.exclude_gap_down and _f(row['open']) < _f(row.get('prev_low')):
        return None
    ma20, ma60, ma5 = _f(row["ma20"]), _f(row["ma60"]), _f(row["ma5"])
    slope = _f(row["ma20_slope"])
    atr_pct = _f(row["atr_pct"])
    atr14 = _f(row["atr14"])
    rsi = _f(row["rsi14"])
    vr = _f(row["vol_ratio"])
    ret20 = _f(row["ret20"])
    avg_amt = _f(row["avg_amount20"])
    hi20 = _f(df["high"].iloc[-21:-1].max()) if len(df) > 21 else float("nan")
    low10 = _f(row["low10"])

    if np.isnan(ma60) or np.isnan(atr14) or np.isnan(rsi):
        return None
    if not np.isnan(avg_amt) and avg_amt < cfg.min_avg_amount:
        return None
    if atr_pct > cfg.max_atr_pct:
        return None

    factors: dict[str, float] = {}
    reasons: list[str] = []

    # 趋势 30
    trend = 0.0
    if close > ma20 > ma60:
        trend += 20
        reasons.append("多头排列：收盘 > MA20 > MA60")
    elif close > ma20 or close > ma60:
        trend += 8
    trend += _clip_score(slope, 0.0, 4.0, 10)
    if slope > 0:
        reasons.append(f"MA20 近 5 日上行 {slope:.1f}%")
    factors["trend"] = round(trend, 1)

    # 动量 20：区间内越靠近中点分越高（10~20 分），超过上限视为过热按超出幅度扣分
    if np.isnan(ret20) or ret20 < cfg.momentum_min_pct:
        momentum = 0.0
    elif ret20 > cfg.momentum_max_pct:
        momentum = max(0.0, 20 - (ret20 - cfg.momentum_max_pct))
    else:
        mid = (cfg.momentum_min_pct + cfg.momentum_max_pct) / 2
        half = max(mid - cfg.momentum_min_pct, 1e-9)
        momentum = 10 + 10 * (1 - abs(ret20 - mid) / half)
    if not np.isnan(ret20) and cfg.momentum_min_pct <= ret20 <= cfg.momentum_max_pct:
        reasons.append(f"20 日涨幅 {ret20:.1f}%，动量健康")
    factors["momentum"] = round(momentum, 1)

    # 量能 15
    volume_pts = 0.0
    if not np.isnan(vr):
        if pct > 0 and 1.2 <= vr <= 3.0:
            volume_pts = 15
            reasons.append(f"放量上涨，量比 {vr:.1f}")
        elif pct > 0 and 1.0 <= vr < 1.2:
            volume_pts = 8
        elif pct <= 0 and vr < 0.9:
            volume_pts = 9
            reasons.append(f"缩量回调，量比 {vr:.2f}")
        elif vr > 3.0 and pct > 0:
            volume_pts = 6
    factors["volume"] = round(volume_pts, 1)

    # RSI 15
    rsi_pts = 0.0
    if cfg.rsi_low <= rsi <= cfg.rsi_high:
        rsi_pts = 15
        reasons.append(f"RSI14 = {rsi:.0f}，未超买")
    elif cfg.rsi_low - 8 <= rsi < cfg.rsi_low or cfg.rsi_high < rsi <= cfg.rsi_high + 6:
        rsi_pts = 7
    factors["rsi"] = round(rsi_pts, 1)

    # 形态 20
    setup = "趋势跟随"
    pattern_pts = 0.0
    dist_ma20 = (close / ma20 - 1) * 100 if not np.isnan(ma20) else float("nan")
    if not np.isnan(dist_ma20) and -1.0 <= dist_ma20 <= cfg.pullback_band_pct and close > ma60 and slope > 0:
        pattern_pts = 20
        setup = "回踩低吸"
        reasons.append(f"收盘距 MA20 仅 {dist_ma20:+.1f}%，回踩均线支撑")
    elif not np.isnan(hi20) and close > hi20 and pct > 0 and not np.isnan(vr) and vr >= 1.3:
        pattern_pts = 18
        setup = "突破追强"
        reasons.append(f"放量突破 20 日高点 {hi20:.2f}")
    elif not np.isnan(dist_ma20) and 0 < dist_ma20 <= 8 and close > ma5:
        pattern_pts = 10
    factors["pattern"] = round(pattern_pts, 1)

    score = trend + momentum + volume_pts + rsi_pts + pattern_pts
    if score < cfg.min_score:
        return None

    # 交易计划
    entry = close if setup != "回踩低吸" else round(max(ma20, close * 0.99), 2)
    stop_atr = entry - cfg.stop_atr_mult * atr14
    stop = max(stop_atr, low10) if not np.isnan(low10) else stop_atr
    stop = min(stop, entry * 0.97)   # 止损至少 3%，避免过窄被震出
    risk = entry - stop
    if risk <= 0:
        return None
    target = entry + cfg.reward_risk * risk
    risk_budget = cfg.capital * cfg.risk_per_trade_pct / 100
    shares = int(risk_budget / risk // 100 * 100)
    max_value = cfg.capital * cfg.max_position_pct / 100
    if shares * entry > max_value:
        shares = int(max_value / entry // 100 * 100)
    position_value = shares * entry
    industry = str(row.get("industry", "") or "")
    if industry in ("nan", "None"):
        industry = ""
    return Recommendation(
        code=code,
        name=name,
        date=pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
        close=round(close, 2),
        score=round(score, 1),
        setup=setup,
        entry=round(entry, 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        risk_pct=round(risk / entry * 100, 2),
        reward_risk=cfg.reward_risk,
        shares=shares,
        position_value=round(position_value, 2),
        position_pct=round(position_value / cfg.capital * 100, 2) if cfg.capital else 0.0,
        reasons=reasons,
        factors=factors,
        board=board_of(code),
        industry=industry,
        ma20=round(ma20, 2),
        ma60=round(ma60, 2),
        rsi14=round(rsi, 1),
        ret20=round(ret20, 2) if not np.isnan(ret20) else float("nan"),
        atr_pct=round(atr_pct, 2),
    )


def recommend_all(enriched: dict[str, pd.DataFrame], cfg: RecommendConfig) -> list[Recommendation]:
    out: list[Recommendation] = []
    for _, df in enriched.items():
        r = score_symbol(df, cfg)
        if r is not None:
            out.append(r)
    out.sort(key=lambda r: (-r.score, r.risk_pct))
    return out[: cfg.top_n]
