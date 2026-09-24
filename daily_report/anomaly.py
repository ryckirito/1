"""异动检测：对每只股票最新交易日的行情打标签。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import AnomalyConfig
from .indicators import enrich
from .market import limit_pct, board_of


@dataclass
class Anomaly:
    code: str
    name: str
    date: str
    close: float
    pct_chg: float
    vol_ratio: float
    amount: float
    tags: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    score: float = 0.0
    direction: str = "neutral"   # up | down | neutral
    board: str = ""
    industry: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v


def detect_symbol(df: pd.DataFrame, cfg: AnomalyConfig) -> Anomaly | None:
    """df：单只股票按日期升序的行情（已 enrich 或原始）。返回最后一日的异动，没有异动时返回 None。"""
    if len(df) < 3:
        return None
    if "pct_chg" not in df.columns:
        df = enrich(df, vr_window=cfg.volume_ratio_window, breakout_window=cfg.breakout_window, zscore_window=cfg.zscore_window)
    row = df.iloc[-1]
    code, name = str(row["code"]), str(row["name"])
    pct = _f(row["pct_chg"])
    vr = _f(row["vol_ratio"])
    if np.isnan(pct):
        return None

    tags: list[str] = []
    details: list[str] = []
    score = 0.0

    lim = limit_pct(code, name)
    # 涨停 / 跌停：涨跌幅达到限制的 98% 以上视为封板
    if pct >= lim * 0.98:
        tags.append("涨停")
        details.append(f"涨幅 {pct:.2f}% 触及 {lim:.0f}% 涨停板")
        score += 30
    elif pct <= -lim * 0.98:
        tags.append("跌停")
        details.append(f"跌幅 {pct:.2f}% 触及 {lim:.0f}% 跌停板")
        score += 30
    elif pct >= cfg.big_move_pct:
        tags.append("大涨")
        details.append(f"单日上涨 {pct:.2f}%")
        score += 15 + min(10, pct - cfg.big_move_pct)
    elif pct <= -cfg.big_move_pct:
        tags.append("大跌")
        details.append(f"单日下跌 {abs(pct):.2f}%")
        score += 15 + min(10, abs(pct) - cfg.big_move_pct)

    if not np.isnan(vr):
        if vr >= cfg.volume_spike_ratio:
            tags.append("放量")
            details.append(f"量比 {vr:.1f}（成交量为 {cfg.volume_ratio_window} 日均量的 {vr:.1f} 倍）")
            score += 12 + min(13, (vr - cfg.volume_spike_ratio) * 3)
        elif vr <= cfg.volume_dry_ratio:
            tags.append("缩量")
            details.append(f"量比仅 {vr:.2f}，成交极度萎缩")
            score += 5

    hi_n, lo_n = _f(row.get("hi_n")), _f(row.get("lo_n"))
    close = _f(row["close"])
    if not np.isnan(hi_n) and close > hi_n:
        tags.append(f"{cfg.breakout_window}日新高")
        details.append(f"收盘 {close:.2f} 突破前 {cfg.breakout_window} 日最高 {hi_n:.2f}")
        score += 15
    if not np.isnan(lo_n) and close < lo_n:
        tags.append(f"{cfg.breakout_window}日新低")
        details.append(f"收盘 {close:.2f} 跌破前 {cfg.breakout_window} 日最低 {lo_n:.2f}")
        score += 15

    open_, prev_high, prev_low = _f(row["open"]), _f(row.get("prev_high")), _f(row.get("prev_low"))
    if not np.isnan(prev_high) and open_ > prev_high * (1 + cfg.gap_pct / 100):
        gap = (open_ / prev_high - 1) * 100
        tags.append("跳空高开")
        details.append(f"开盘高于昨日最高价 {gap:.2f}%")
        score += 10
    if not np.isnan(prev_low) and open_ < prev_low * (1 - cfg.gap_pct / 100):
        gap = (1 - open_ / prev_low) * 100
        tags.append("跳空低开")
        details.append(f"开盘低于昨日最低价 {gap:.2f}%")
        score += 10

    amp = _f(row.get("amplitude"))
    if not np.isnan(amp) and amp >= cfg.amplitude_pct:
        tags.append("大振幅")
        details.append(f"日内振幅 {amp:.2f}%")
        score += 8

    z = _f(row.get("ret_z"))
    if not np.isnan(z) and abs(z) >= cfg.zscore_threshold:
        tags.append("统计异常")
        details.append(f"当日收益率 z-score {z:+.1f}（相对近 {cfg.zscore_window} 日）")
        score += 8

    turnover = _f(row.get("turnover"))
    if not np.isnan(turnover) and turnover >= cfg.turnover_pct:
        tags.append("高换手")
        details.append(f"换手率 {turnover:.1f}%")
        score += 6

    if not tags:
        return None

    direction = "up" if pct > 0.5 else "down" if pct < -0.5 else "neutral"
    industry = str(row.get("industry", "") or "")
    if industry in ("nan", "None"):
        industry = ""
    return Anomaly(
        code=code,
        name=name,
        date=pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
        close=round(close, 2),
        pct_chg=round(pct, 2),
        vol_ratio=round(vr, 2) if not np.isnan(vr) else float("nan"),
        amount=_f(row["amount"]),
        tags=tags,
        details=details,
        score=round(score, 1),
        direction=direction,
        board=board_of(code),
        industry=industry,
    )


def detect_all(enriched: dict[str, pd.DataFrame], cfg: AnomalyConfig) -> list[Anomaly]:
    """enriched: {code: 已 enrich 的单股 DataFrame}。按评分降序返回。"""
    out: list[Anomaly] = []
    for _, df in enriched.items():
        a = detect_symbol(df, cfg)
        if a is not None:
            out.append(a)
    out.sort(key=lambda a: (-a.score, -abs(a.pct_chg)))
    return out
