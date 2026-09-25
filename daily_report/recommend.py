"""推荐建仓：多因子评分 + 交易计划（入场 / 止损 / 目标 / 仓位）。

每个因子先算成 0~1 的得分，再乘以配置里的权重求和（默认权重合计 100）：
- 趋势：收盘 > MA50 > MA200（多头排列）且 MA20 向上；历史不足 200 日时退化为 MA20/MA50
- 动量：20 日涨幅落在健康区间（涨太多视为追高）
- 相对强弱：rs_window 日内相对基准的超额收益（默认权重 0，可在回测后开启）
- 量能：当日温和放量收阳，或缩量回调
- RSI：落在 rsi_low~rsi_high 区间
- 形态：回踩 MA20 附近（低吸）或放量突破 20 日新高（追强）
过滤：仙股、流动性不足、波动过大、当日涨跌过大、跳空低开、历史数据不足。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import RecommendConfig


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
    shares: float                   # 建议股数
    position_value: float           # 建议买入金额（美元）
    position_pct: float             # 占总资金百分比
    reasons: list[str] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)
    sector: str = ""
    market_cap: float = float("nan")
    ma20: float = 0.0
    ma50: float = 0.0
    ma200: float = float("nan")
    rsi14: float = 0.0
    ret20: float = 0.0
    rs: float = float("nan")        # 相对基准超额收益 %
    atr_pct: float = 0.0
    closes: list[float] = field(default_factory=list)   # 近 60 日收盘，供走势小图

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _str(x: Any) -> str:
    s = "" if x is None else str(x)
    return "" if s in ("nan", "None") else s


def _ramp(value: float, lo: float, hi: float) -> float:
    """value 在 [lo, hi] 内线性映射到 0~1。"""
    if np.isnan(value) or value <= lo:
        return 0.0
    if value >= hi:
        return 1.0
    return (value - lo) / (hi - lo)


def score_symbol(df: pd.DataFrame, cfg: RecommendConfig, ranks: dict[str, dict[str, float]] | None = None) -> Recommendation | None:
    """df：单只股票 enrich 后的行情。返回评分与交易计划；不满足过滤条件时返回 None。

    ranks：rank_mode 下由 recommend_all 传入的当日截面百分位 {"rs": {code: 0~1}, "mom12": {...}}。
    """
    if len(df) < cfg.min_history_days:
        return None
    row = df.iloc[-1]
    code, name = str(row["code"]), str(row["name"])
    close = _f(row["close"])
    pct = _f(row["pct_chg"])
    if close < cfg.min_price:
        return None
    if np.isnan(pct) or pct > cfg.max_daily_gain_pct or pct < -cfg.max_daily_loss_pct:
        return None
    if cfg.exclude_gap_down and _f(row["open"]) < _f(row.get("prev_low")):
        return None
    ma20, ma50, ma200, ma5 = _f(row["ma20"]), _f(row["ma50"]), _f(row["ma200"]), _f(row["ma5"])
    slope20 = _f(row["ma20_slope"])
    atr_pct, atr14 = _f(row["atr_pct"]), _f(row["atr14"])
    rsi = _f(row["rsi14"])
    vr = _f(row["vol_ratio"])
    ret20 = _f(row["ret20"])
    avg_amt = _f(row["avg_amount20"])
    hi20 = _f(row.get("hi_short"))
    low10 = _f(row["low10"])

    if np.isnan(ma50) or np.isnan(atr14) or np.isnan(rsi):
        return None
    if not np.isnan(avg_amt) and avg_amt < cfg.min_avg_dollar_volume:
        return None
    if atr_pct > cfg.max_atr_pct:
        return None

    factors: dict[str, float] = {}
    reasons: list[str] = []

    # 趋势 0~1：排列 2/3 + 斜率 1/3
    trend = 0.0
    if not np.isnan(ma200):
        if close > ma50 > ma200:
            trend += 2 / 3
            reasons.append("多头排列：收盘 > MA50 > MA200")
        elif close > ma50 or close > ma200:
            trend += 0.27
    else:
        if close > ma20 > ma50:
            trend += 0.47
            reasons.append("短期多头排列：收盘 > MA20 > MA50")
        elif close > ma50:
            trend += 0.2
    trend += _ramp(slope20, 0.0, 4.0) / 3
    if slope20 > 0:
        reasons.append(f"MA20 近 5 日上行 {slope20:.1f}%")

    # 动量 0~1：区间内越靠近中点越高（0.5~1），超过上限按超出幅度递减
    if np.isnan(ret20) or ret20 < cfg.momentum_min_pct:
        momentum = 0.0
    elif ret20 > cfg.momentum_max_pct:
        momentum = max(0.0, 1 - (ret20 - cfg.momentum_max_pct) / 20)
    else:
        mid = (cfg.momentum_min_pct + cfg.momentum_max_pct) / 2
        half = max(mid - cfg.momentum_min_pct, 1e-9)
        momentum = 0.5 + 0.5 * (1 - abs(ret20 - mid) / half)
        reasons.append(f"20 日涨幅 {ret20:.1f}%，动量健康")

    # 相对强弱 0~1：rs_window 日超额收益，0% → 0.3，+10% → 1，负数递减到 0
    rs_col = "bench_ret60" if cfg.rs_window >= 60 else "bench_ret20"
    own_col = "ret60" if cfg.rs_window >= 60 else "ret20"
    rs = _f(row.get(own_col)) - _f(row.get(rs_col))
    if np.isnan(rs):
        rs_score = 0.0
    elif rs >= 0:
        rs_score = 0.3 + 0.7 * _ramp(rs, 0.0, 10.0)
    else:
        rs_score = 0.3 * (1 - _ramp(-rs, 0.0, 10.0))
    if ranks and cfg.rank_mode and code in ranks.get("rs", {}):
        rs_score = ranks["rs"][code]
    if not np.isnan(rs) and rs > 0 and cfg.w_rs > 0:
        reasons.append(f"{cfg.rs_window} 日跑赢基准 {rs:.1f}%")

    # 长期动量 0~1：12-1 个月涨幅，0% → 0.3，+40% → 1
    mom12 = _f(row.get("mom12_1"))
    if ranks and cfg.rank_mode and code in ranks.get("mom12", {}):
        mom12_s = ranks["mom12"][code]
    elif np.isnan(mom12):
        mom12_s = 0.0
    elif mom12 >= 0:
        mom12_s = 0.3 + 0.7 * _ramp(mom12, 0.0, 40.0)
    else:
        mom12_s = 0.3 * (1 - _ramp(-mom12, 0.0, 30.0))
    if cfg.w_mom12 > 0 and not np.isnan(mom12) and mom12 > 10:
        reasons.append(f"12 个月动量 {mom12:.0f}%")

    # 趋势平滑度 0~1：相关系数 0.5 → 0，0.95 → 1
    corr = _f(row.get("trend_corr60"))
    smooth_s = _ramp(corr, 0.5, 0.95)
    if cfg.w_smooth > 0 and corr >= 0.8:
        reasons.append(f"60 日趋势平滑（相关系数 {corr:.2f}）")

    # 接近 52 周高点 0~1：距高点 -15% → 0，0% → 1
    dist_hi = _f(row.get("dist_hi_long"))
    near_high_s = _ramp(dist_hi, -15.0, 0.0) if not np.isnan(dist_hi) else 0.0
    if cfg.w_near_high > 0 and not np.isnan(dist_hi) and dist_hi >= -3:
        reasons.append(f"距 52 周高点仅 {abs(dist_hi):.1f}%")

    # 量能 0~1
    volume_s = 0.0
    if not np.isnan(vr):
        if pct > 0 and 1.2 <= vr <= 3.0:
            volume_s = 1.0
            reasons.append(f"放量上涨，成交量为 20 日均量的 {vr:.1f} 倍")
        elif pct > 0 and 1.0 <= vr < 1.2:
            volume_s = 0.53
        elif pct <= 0 and vr < 0.9:
            volume_s = 0.6
            reasons.append(f"缩量回调，成交量为 20 日均量的 {vr:.0%}")
        elif vr > 3.0 and pct > 0:
            volume_s = 0.4

    # RSI 0~1
    rsi_s = 0.0
    if cfg.rsi_low <= rsi <= cfg.rsi_high:
        rsi_s = 1.0
        reasons.append(f"RSI14 = {rsi:.0f}，未超买")
    elif cfg.rsi_low - 8 <= rsi < cfg.rsi_low or cfg.rsi_high < rsi <= cfg.rsi_high + 6:
        rsi_s = 0.47

    # 形态 0~1
    setup = "趋势跟随"
    pattern_s = 0.0
    dist_ma20 = (close / ma20 - 1) * 100 if not np.isnan(ma20) else float("nan")
    if not np.isnan(dist_ma20) and -1.0 <= dist_ma20 <= cfg.pullback_band_pct and close > ma50 and slope20 > 0:
        pattern_s = 1.0
        setup = "回踩低吸"
        reasons.append(f"收盘距 MA20 仅 {dist_ma20:+.1f}%，回踩均线支撑")
    elif not np.isnan(hi20) and close > hi20 and pct > 0 and not np.isnan(vr) and vr >= 1.3:
        pattern_s = 0.9
        setup = "突破追强"
        reasons.append(f"放量突破 20 日高点 {hi20:.2f}")
    elif not np.isnan(dist_ma20) and 0 < dist_ma20 <= 8 and close > ma5:
        pattern_s = 0.5

    weights = {"trend": cfg.w_trend, "momentum": cfg.w_momentum, "rs": cfg.w_rs, "mom12": cfg.w_mom12, "smooth": cfg.w_smooth,
               "near_high": cfg.w_near_high, "volume": cfg.w_volume, "rsi": cfg.w_rsi, "pattern": cfg.w_pattern}
    raw = {"trend": trend, "momentum": momentum, "rs": rs_score, "mom12": mom12_s, "smooth": smooth_s, "near_high": near_high_s,
           "volume": volume_s, "rsi": rsi_s, "pattern": pattern_s}
    for k, w in weights.items():
        if w > 0:
            factors[k] = round(raw[k] * w, 1)
    score = sum(factors.values())
    if score < cfg.min_score:
        return None

    # 交易计划
    entry = close if (setup != "回踩低吸" or close <= ma20) else round(max(ma20, close * 0.99), 2)
    stop_atr = entry - cfg.stop_atr_mult * atr14
    stop = max(stop_atr, low10) if not np.isnan(low10) else stop_atr
    stop = min(stop, entry * (1 - cfg.min_stop_pct / 100))
    risk = entry - stop
    if risk <= 0:
        return None
    target = entry + cfg.reward_risk * risk
    closes = [round(float(v), 2) for v in df["close"].iloc[-60:]]
    rec = Recommendation(
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
        shares=0.0,
        position_value=0.0,
        position_pct=0.0,
        reasons=reasons,
        factors=factors,
        sector=_str(row.get("sector", "")),
        market_cap=_f(row.get("market_cap")),
        ma20=round(ma20, 2),
        ma50=round(ma50, 2),
        ma200=round(ma200, 2) if not np.isnan(ma200) else float("nan"),
        rsi14=round(rsi, 1),
        ret20=round(ret20, 2) if not np.isnan(ret20) else float("nan"),
        rs=round(rs, 2) if not np.isnan(rs) else float("nan"),
        atr_pct=round(atr_pct, 2),
        closes=closes,
    )
    return size_position(rec, cfg, cfg.max_position_pct)


def size_position(r: Recommendation, cfg: RecommendConfig, cap_pct: float) -> Recommendation:
    """按风险预算反推股数：min(风险预算 / 单股风险, 仓位上限 / 入场价)。"""
    risk = r.entry - r.stop_loss
    risk_budget = cfg.capital * cfg.risk_per_trade_pct / 100
    max_value = cfg.capital * cap_pct / 100
    raw_shares = min(risk_budget / risk, max_value / r.entry) if risk > 0 else 0.0
    shares = round(raw_shares, 2) if cfg.fractional_shares else float(int(raw_shares))
    r.shares = shares
    r.position_value = round(shares * r.entry, 2)
    r.position_pct = round(r.position_value / cfg.capital * 100, 2) if cfg.capital else 0.0
    return r


def market_regime(enriched: dict[str, pd.DataFrame]) -> bool | None:
    """基准是否处于多头环境（收盘 > MA200）。没有基准数据时返回 None。"""
    for df in enriched.values():
        if "bench_bull" in df.columns and len(df):
            v = df["bench_bull"].iloc[-1]
            return None if pd.isna(v) else bool(v)
    return None


def _cross_section_ranks(enriched: dict[str, pd.DataFrame], cfg: RecommendConfig, exclude: set[str]) -> dict[str, dict[str, float]]:
    """当日截面百分位（0~1）：相对强弱与长期动量。"""
    rs_col, own_col = ("bench_ret60", "ret60") if cfg.rs_window >= 60 else ("bench_ret20", "ret20")
    rows = []
    for code, df in enriched.items():
        if code in exclude or not len(df):
            continue
        last = df.iloc[-1]
        rows.append({"code": code, "rs": _f(last.get(own_col)) - _f(last.get(rs_col)), "mom12": _f(last.get("mom12_1"))})
    if not rows:
        return {}
    frame = pd.DataFrame(rows).set_index("code")
    out: dict[str, dict[str, float]] = {}
    for col in ("rs", "mom12"):
        pct = frame[col].rank(pct=True)
        out[col] = {c: float(v) for c, v in pct.dropna().items()}
    return out


def recommend_all(enriched: dict[str, pd.DataFrame], cfg: RecommendConfig, exclude: set[str] | None = None) -> list[Recommendation]:
    exclude = exclude or set()
    top_n = cfg.top_n
    if cfg.regime_filter != "off":
        bull = market_regime(enriched)
        if bull is False:
            if cfg.regime_filter == "skip":
                return []
            top_n = max(1, top_n // 2)
    ranks = _cross_section_ranks(enriched, cfg, exclude) if cfg.rank_mode else None
    scored: list[Recommendation] = []
    for code, df in enriched.items():
        if code in exclude:
            continue
        r = score_symbol(df, cfg, ranks)
        if r is not None:
            scored.append(r)
    scored.sort(key=lambda r: (-r.score, r.risk_pct))
    # 板块分散
    out: list[Recommendation] = []
    per_sector: dict[str, int] = {}
    for r in scored:
        if cfg.max_per_sector > 0 and r.sector:
            if per_sector.get(r.sector, 0) >= cfg.max_per_sector:
                continue
            per_sector[r.sector] = per_sector.get(r.sector, 0) + 1
        out.append(r)
        if len(out) >= top_n:
            break
    # 单只仓位上限：min(max_position_pct, 总仓位上限 / 推荐条数)
    cap = min(cfg.max_position_pct, cfg.max_total_exposure_pct / max(1, top_n))
    out = [size_position(r, cfg, cap) for r in out]
    return [r for r in out if r.shares > 0]
