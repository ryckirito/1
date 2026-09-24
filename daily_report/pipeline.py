"""日报流水线：取数 → 指标 → 异动 → 推荐 → 市场概览。"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from .anomaly import Anomaly, detect_all
from .config import Config
from .data import make_provider
from .indicators import enrich
from .market import limit_pct
from .recommend import Recommendation, recommend_all

log = logging.getLogger(__name__)


@dataclass
class MarketOverview:
    date: str
    total: int
    up: int
    down: int
    flat: int
    limit_up: int
    limit_down: int
    median_pct: float
    mean_pct: float
    total_amount: float
    amount_change_pct: float      # 成交额相对前一交易日变化
    above_ma20_pct: float         # 收盘站上 MA20 的比例
    top_gainers: list[dict[str, Any]] = field(default_factory=list)
    top_losers: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyReport:
    date: str
    generated_at: str
    source: str
    overview: MarketOverview
    anomalies: list[Anomaly]
    recommendations: list[Recommendation]
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "generated_at": self.generated_at,
            "source": self.source,
            "overview": self.overview.to_dict(),
            "anomalies": [a.to_dict() for a in self.anomalies],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "config": self.config,
        }


def enrich_panel(hist: pd.DataFrame, cfg: Config) -> dict[str, pd.DataFrame]:
    a = cfg.anomaly
    out: dict[str, pd.DataFrame] = {}
    for code, g in hist.groupby("code", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        out[str(code)] = enrich(g, vr_window=a.volume_ratio_window, breakout_window=a.breakout_window, zscore_window=a.zscore_window)
    return out


def build_overview(enriched: dict[str, pd.DataFrame], date: pd.Timestamp) -> MarketOverview:
    rows = []
    for code, df in enriched.items():
        last = df.iloc[-1]
        if pd.Timestamp(last["date"]) != date:
            continue
        prev_amount = float(df["amount"].iloc[-2]) if len(df) > 1 else np.nan
        rows.append(
            {
                "code": code,
                "name": last["name"],
                "pct_chg": last["pct_chg"],
                "close": last["close"],
                "amount": last["amount"],
                "prev_amount": prev_amount,
                "above_ma20": bool(last["close"] > last["ma20"]) if not np.isnan(last["ma20"]) else np.nan,
                "limit": limit_pct(code, str(last["name"])),
            }
        )
    snap = pd.DataFrame(rows)
    if snap.empty:
        return MarketOverview(date.strftime("%Y-%m-%d"), 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    pct = snap["pct_chg"].dropna()
    limit_up = int((snap["pct_chg"] >= snap["limit"] * 0.98).sum())
    limit_down = int((snap["pct_chg"] <= -snap["limit"] * 0.98).sum())
    total_amount = float(snap["amount"].sum())
    prev_total = float(snap["prev_amount"].sum())
    amt_chg = (total_amount / prev_total - 1) * 100 if prev_total > 0 else 0.0
    above = snap["above_ma20"].dropna()
    gainers = snap.nlargest(5, "pct_chg")[["code", "name", "pct_chg", "close"]]
    losers = snap.nsmallest(5, "pct_chg")[["code", "name", "pct_chg", "close"]]
    return MarketOverview(
        date=date.strftime("%Y-%m-%d"),
        total=int(len(snap)),
        up=int((pct > 0).sum()),
        down=int((pct < 0).sum()),
        flat=int((pct == 0).sum()),
        limit_up=limit_up,
        limit_down=limit_down,
        median_pct=round(float(pct.median()), 2) if len(pct) else 0.0,
        mean_pct=round(float(pct.mean()), 2) if len(pct) else 0.0,
        total_amount=total_amount,
        amount_change_pct=round(amt_chg, 2),
        above_ma20_pct=round(float(above.mean()) * 100, 1) if len(above) else 0.0,
        top_gainers=[{**r, "pct_chg": round(float(r["pct_chg"]), 2), "close": round(float(r["close"]), 2)} for r in gainers.to_dict("records")],
        top_losers=[{**r, "pct_chg": round(float(r["pct_chg"]), 2), "close": round(float(r["close"]), 2)} for r in losers.to_dict("records")],
    )


def run_pipeline(cfg: Config, date: dt.date | None = None, hist: pd.DataFrame | None = None) -> DailyReport:
    """执行完整流水线。hist 传入时跳过取数（用于测试或离线复算）。"""
    end = date or dt.date.today()
    start = end - dt.timedelta(days=cfg.data.history_days)
    provider = make_provider(cfg.data)
    source = provider.describe()
    if hist is None:
        log.info("从 %s 加载 %s ~ %s 行情", source, start, end)
        hist = provider.load_history(end=end, start=start)
    hist = hist[hist["date"].dt.date <= end]
    if hist.empty:
        raise RuntimeError("行情数据为空")
    report_date = pd.Timestamp(hist["date"].max())
    if report_date.date() != end:
        log.warning("请求日期 %s 无行情，使用最近交易日 %s", end, report_date.date())
    # 只保留在报告日有数据的股票（停牌 / 退市不参与）
    active = hist.groupby("code")["date"].max()
    hist = hist[hist["code"].isin(active[active == report_date].index)]

    enriched = enrich_panel(hist, cfg)
    log.info("共 %d 只股票参与计算", len(enriched))
    anomalies = detect_all(enriched, cfg.anomaly)[: cfg.anomaly.max_items]
    recs = recommend_all(enriched, cfg.recommend)
    overview = build_overview(enriched, report_date)
    log.info("异动 %d 条，推荐 %d 条", len(anomalies), len(recs))
    return DailyReport(
        date=report_date.strftime("%Y-%m-%d"),
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source=source,
        overview=overview,
        anomalies=anomalies,
        recommendations=recs,
        config=cfg.to_dict(),
    )
