"""异动检测：对每只股票最新交易日的行情打标签。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import AnomalyConfig
from .indicators import enrich


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
    sector: str = ""
    market_cap: float = float("nan")
    excess_pct: float = float("nan")   # 相对基准的超额涨跌幅
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


def detect_symbol(df: pd.DataFrame, cfg: AnomalyConfig) -> Anomaly | None:
    """df：单只股票按日期升序的行情（已 enrich 或原始）。返回最后一日的异动，没有异动时返回 None。"""
    if len(df) < 3:
        return None
    if "pct_chg" not in df.columns:
        df = enrich(df, vr_window=cfg.volume_ratio_window, long_window=cfg.long_window, short_window=cfg.short_window, zscore_window=cfg.zscore_window)
    row = df.iloc[-1]
    code, name = str(row["code"]), str(row["name"])
    pct = _f(row["pct_chg"])
    vr = _f(row["vol_ratio"])
    if np.isnan(pct):
        return None

    tags: list[str] = []
    details: list[str] = []
    score = 0.0

    # 涨跌幅
    if pct >= cfg.huge_move_pct:
        tags.append("暴涨")
        details.append(f"单日上涨 {pct:.2f}%")
        score += 30 + min(10, (pct - cfg.huge_move_pct) / 2)
    elif pct <= -cfg.huge_move_pct:
        tags.append("暴跌")
        details.append(f"单日下跌 {abs(pct):.2f}%")
        score += 30 + min(10, (abs(pct) - cfg.huge_move_pct) / 2)
    elif pct >= cfg.big_move_pct:
        tags.append("大涨")
        details.append(f"单日上涨 {pct:.2f}%")
        score += 15 + min(10, (pct - cfg.big_move_pct) * 2)
    elif pct <= -cfg.big_move_pct:
        tags.append("大跌")
        details.append(f"单日下跌 {abs(pct):.2f}%")
        score += 15 + min(10, (abs(pct) - cfg.big_move_pct) * 2)

    # 量能
    if not np.isnan(vr):
        if vr >= cfg.volume_spike_ratio:
            tags.append("放量")
            details.append(f"成交量为 {cfg.volume_ratio_window} 日均量的 {vr:.1f} 倍")
            score += 12 + min(13, (vr - cfg.volume_spike_ratio) * 3)
        elif vr <= cfg.volume_dry_ratio:
            tags.append("缩量")
            details.append(f"成交量仅为 {cfg.volume_ratio_window} 日均量的 {vr:.0%}")
            score += 5

    # 新高新低：52 周优先，否则看 20 日
    close = _f(row["close"])
    hi_l, lo_l = _f(row.get("hi_long")), _f(row.get("lo_long"))
    hi_s, lo_s = _f(row.get("hi_short")), _f(row.get("lo_short"))
    if not np.isnan(hi_l) and close > hi_l:
        tags.append("52周新高")
        details.append(f"收盘 {close:.2f} 创 52 周新高（前高 {hi_l:.2f}）")
        score += 18
    elif not np.isnan(hi_s) and close > hi_s:
        tags.append(f"{cfg.short_window}日新高")
        details.append(f"收盘 {close:.2f} 突破前 {cfg.short_window} 日最高 {hi_s:.2f}")
        score += 8
    if not np.isnan(lo_l) and close < lo_l:
        tags.append("52周新低")
        details.append(f"收盘 {close:.2f} 创 52 周新低（前低 {lo_l:.2f}）")
        score += 18
    elif not np.isnan(lo_s) and close < lo_s:
        tags.append(f"{cfg.short_window}日新低")
        details.append(f"收盘 {close:.2f} 跌破前 {cfg.short_window} 日最低 {lo_s:.2f}")
        score += 8

    # 跳空
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

    # 相对大盘：个股涨跌幅减去基准涨跌幅
    bench_pct = _f(row.get("bench_pct_chg"))
    excess = pct - bench_pct if not np.isnan(bench_pct) else float("nan")
    if not np.isnan(excess):
        if excess >= cfg.excess_pct:
            tags.append("跑赢大盘")
            details.append(f"跑赢基准 {excess:.2f} 个百分点")
            score += 8
        elif excess <= -cfg.excess_pct:
            tags.append("跑输大盘")
            details.append(f"跑输基准 {abs(excess):.2f} 个百分点")
            score += 8

    # 连涨 / 连跌
    st = int(_f(row.get("streak")) or 0)
    if st >= cfg.streak_days:
        tags.append(f"{st}连涨")
        details.append(f"已连续上涨 {st} 个交易日")
        score += 6 + min(6, st - cfg.streak_days)
    elif st <= -cfg.streak_days:
        tags.append(f"{-st}连跌")
        details.append(f"已连续下跌 {-st} 个交易日")
        score += 6 + min(6, -st - cfg.streak_days)

    if not tags or score < cfg.min_score:
        return None

    direction = "up" if pct > 0.5 else "down" if pct < -0.5 else "neutral"
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
        sector=_str(row.get("sector", "")),
        market_cap=_f(row.get("market_cap")),
        excess_pct=round(excess, 2) if not np.isnan(excess) else float("nan"),
        closes=[round(float(v), 2) for v in df["close"].iloc[-60:]],
    )


def detect_all(enriched: dict[str, pd.DataFrame], cfg: AnomalyConfig, exclude: set[str] | None = None) -> list[Anomaly]:
    """enriched: {ticker: 已 enrich 的单股 DataFrame}。按评分降序返回。"""
    out: list[Anomaly] = []
    for code, df in enriched.items():
        if exclude and code in exclude:
            continue
        a = detect_symbol(df, cfg)
        if a is not None:
            out.append(a)
    out.sort(key=lambda a: (-a.score, -abs(a.pct_chg)))
    return out
