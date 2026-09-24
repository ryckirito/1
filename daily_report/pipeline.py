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
from .market import normalize_ticker
from .recommend import Recommendation, recommend_all

log = logging.getLogger(__name__)


@dataclass
class MarketOverview:
    date: str
    total: int
    up: int
    down: int
    flat: int
    big_up: int                   # 涨幅 >= big_move_pct
    big_down: int
    new_high_52w: int
    new_low_52w: int
    median_pct: float
    mean_pct: float
    total_amount: float           # 合计成交额（美元）
    amount_change_pct: float      # 成交额相对前一交易日变化
    above_ma50_pct: float         # 收盘站上 MA50 的比例
    above_ma200_pct: float        # 收盘站上 MA200 的比例（历史足够时）
    benchmarks: list[dict[str, Any]] = field(default_factory=list)   # SPY / QQQ 等
    top_gainers: list[dict[str, Any]] = field(default_factory=list)
    top_losers: list[dict[str, Any]] = field(default_factory=list)
    sectors: list[dict[str, Any]] = field(default_factory=list)      # 板块平均涨跌幅

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
        out[str(code)] = enrich(g, vr_window=a.volume_ratio_window, long_window=a.long_window, short_window=a.short_window, zscore_window=a.zscore_window)
    return out


def _rec(r: pd.Series) -> dict[str, Any]:
    return {"code": r["code"], "name": r["name"], "pct_chg": round(float(r["pct_chg"]), 2), "close": round(float(r["close"]), 2)}


def build_overview(enriched: dict[str, pd.DataFrame], date: pd.Timestamp, cfg: Config, benchmarks: set[str]) -> MarketOverview:
    rows = []
    bench_rows = []
    for code, df in enriched.items():
        last = df.iloc[-1]
        if pd.Timestamp(last["date"]) != date:
            continue
        if code in benchmarks:
            bench_rows.append({"code": code, "name": last["name"], "pct_chg": round(float(last["pct_chg"]), 2), "close": round(float(last["close"]), 2),
                               "ret5": round(float(last["ret5"]), 2) if not np.isnan(last["ret5"]) else None,
                               "ret20": round(float(last["ret20"]), 2) if not np.isnan(last["ret20"]) else None})
            continue
        rows.append(
            {
                "code": code,
                "name": last["name"],
                "sector": str(last.get("sector", "") or ""),
                "pct_chg": last["pct_chg"],
                "close": last["close"],
                "amount": last["amount"],
                "prev_amount": float(df["amount"].iloc[-2]) if len(df) > 1 else np.nan,
                "above_ma50": bool(last["close"] > last["ma50"]) if not np.isnan(last["ma50"]) else np.nan,
                "above_ma200": bool(last["close"] > last["ma200"]) if not np.isnan(last["ma200"]) else np.nan,
                "nh": bool(last["close"] > last["hi_long"]) if not np.isnan(last["hi_long"]) else False,
                "nl": bool(last["close"] < last["lo_long"]) if not np.isnan(last["lo_long"]) else False,
            }
        )
    snap = pd.DataFrame(rows)
    d = date.strftime("%Y-%m-%d")
    if snap.empty:
        return MarketOverview(d, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, benchmarks=bench_rows)
    pct = snap["pct_chg"].dropna()
    total_amount = float(snap["amount"].sum())
    prev_total = float(snap["prev_amount"].sum())
    amt_chg = (total_amount / prev_total - 1) * 100 if prev_total > 0 else 0.0
    a50, a200 = snap["above_ma50"].dropna(), snap["above_ma200"].dropna()
    big = cfg.anomaly.big_move_pct
    sectors = []
    sec = snap[snap["sector"].astype(bool)]
    if not sec.empty:
        g = sec.groupby("sector")["pct_chg"].agg(["mean", "count"]).sort_values("mean", ascending=False)
        sectors = [{"sector": s, "mean_pct": round(float(r["mean"]), 2), "count": int(r["count"])} for s, r in g.iterrows()]
    return MarketOverview(
        date=d,
        total=int(len(snap)),
        up=int((pct > 0).sum()),
        down=int((pct < 0).sum()),
        flat=int((pct == 0).sum()),
        big_up=int((pct >= big).sum()),
        big_down=int((pct <= -big).sum()),
        new_high_52w=int(snap["nh"].sum()),
        new_low_52w=int(snap["nl"].sum()),
        median_pct=round(float(pct.median()), 2) if len(pct) else 0.0,
        mean_pct=round(float(pct.mean()), 2) if len(pct) else 0.0,
        total_amount=total_amount,
        amount_change_pct=round(amt_chg, 2),
        above_ma50_pct=round(float(a50.mean()) * 100, 1) if len(a50) else 0.0,
        above_ma200_pct=round(float(a200.mean()) * 100, 1) if len(a200) else float("nan"),
        benchmarks=bench_rows,
        top_gainers=[_rec(r) for _, r in snap.nlargest(5, "pct_chg").iterrows()],
        top_losers=[_rec(r) for _, r in snap.nsmallest(5, "pct_chg").iterrows()],
        sectors=sectors,
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
    active = hist.groupby("code")["date"].max()
    hist = hist[hist["code"].isin(active[active == report_date].index)]

    enriched = enrich_panel(hist, cfg)
    benchmarks = {normalize_ticker(t) for t in cfg.data.benchmarks}
    log.info("共 %d 只标的参与计算（含基准 %d 只）", len(enriched), len(benchmarks & set(enriched)))
    anomalies = detect_all(enriched, cfg.anomaly, exclude=benchmarks)[: cfg.anomaly.max_items]
    recs = recommend_all(enriched, cfg.recommend, exclude=benchmarks)
    overview = build_overview(enriched, report_date, cfg, benchmarks)
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
