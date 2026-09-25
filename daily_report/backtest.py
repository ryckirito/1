"""推荐信号回测：在历史上每个交易日按同样规则选股，统计之后 N 日的表现。

所有指标都只依赖过去数据，因此对每只股票只 enrich 一次，再按日期切片即可复现当日的推荐。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import Config
from .market import normalize_ticker
from .pipeline import attach_benchmark, enrich_panel
from .recommend import recommend_all

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    start: str
    end: str
    days: int                       # 回测的交易日数
    horizon: int                    # 持有天数
    n_signals: int                  # 推荐次数
    avg_ret: float                  # 平均收益 %
    median_ret: float
    win_rate: float                 # 收益 > 0 的比例 %
    avg_excess: float               # 相对基准的平均超额收益 %
    excess_win_rate: float          # 跑赢基准的比例 %
    stop_hit_rate: float            # 持有期内触及止损的比例 %
    target_hit_rate: float          # 持有期内触及目标的比例 %
    by_setup: list[dict[str, Any]] = field(default_factory=list)
    by_score: list[dict[str, Any]] = field(default_factory=list)
    trades: pd.DataFrame | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("trades", None)
        return d


def _forward_stats(df: pd.DataFrame, i: int, horizon: int, entry: float, stop: float, target: float) -> dict[str, float] | None:
    """从第 i 行之后持有 horizon 日：收益、是否触及止损/目标。"""
    fut = df.iloc[i + 1 : i + 1 + horizon]
    if len(fut) < horizon:
        return None
    exit_close = float(fut["close"].iloc[-1])
    ret = (exit_close / entry - 1) * 100
    hit_stop = bool((fut["low"] <= stop).any())
    hit_target = bool((fut["high"] >= target).any())
    # 简化：先触及止损则按止损价出场，否则按持有期末收盘
    if hit_stop:
        first_stop = int(np.argmax(fut["low"].values <= stop))
        first_target = int(np.argmax(fut["high"].values >= target)) if hit_target else horizon + 1
        if first_stop <= first_target:
            ret = (stop / entry - 1) * 100
    return {"ret": ret, "hit_stop": hit_stop, "hit_target": hit_target}


def run_backtest(cfg: Config, hist: pd.DataFrame, days: int = 120, horizon: int = 20, benchmark: str | None = None) -> BacktestResult:
    enriched = enrich_panel(hist, cfg)
    bench = normalize_ticker(benchmark or (cfg.data.benchmarks[0] if cfg.data.benchmarks else "SPY"))
    attach_benchmark(enriched, bench)
    bench_df = enriched.get(bench)
    etfs = {c for c, df in enriched.items() if "sector" in df.columns and str(df["sector"].iloc[-1]) == "ETF"}
    excluded = {normalize_ticker(t) for t in cfg.data.benchmarks} | etfs
    all_dates = sorted(hist["date"].unique())
    # 需要留出 horizon 日观察期
    usable = all_dates[: len(all_dates) - horizon]
    test_dates = usable[-days:]
    idx_of = {code: {d: i for i, d in enumerate(df["date"])} for code, df in enriched.items()}
    rows = []
    for d in test_dates:
        panel = {}
        for code, df in enriched.items():
            i = idx_of[code].get(d)
            if i is None or code in excluded:
                continue
            panel[code] = df.iloc[: i + 1]
        recs = recommend_all(panel, cfg.recommend, exclude=excluded)
        bench_ret = np.nan
        if bench_df is not None:
            bi = idx_of[bench].get(d)
            if bi is not None and bi + horizon < len(bench_df):
                bench_ret = (float(bench_df["close"].iloc[bi + horizon]) / float(bench_df["close"].iloc[bi]) - 1) * 100
        for r in recs:
            df = enriched[r.code]
            i = idx_of[r.code][d]
            st = _forward_stats(df, i, horizon, r.entry, r.stop_loss, r.target)
            if st is None:
                continue
            rows.append({"date": pd.Timestamp(d).strftime("%Y-%m-%d"), "code": r.code, "setup": r.setup, "score": r.score, "entry": r.entry, "bench_ret": bench_ret, **st})
    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError("回测期间没有产生任何推荐，请放宽阈值或延长历史")
    trades["excess"] = trades["ret"] - trades["bench_ret"]

    def _agg(g: pd.DataFrame) -> dict[str, Any]:
        return {
            "n": int(len(g)),
            "avg_ret": round(float(g["ret"].mean()), 2),
            "win_rate": round(float((g["ret"] > 0).mean() * 100), 1),
            "avg_excess": round(float(g["excess"].mean()), 2) if g["excess"].notna().any() else float("nan"),
            "stop_hit_rate": round(float(g["hit_stop"].mean() * 100), 1),
        }

    by_setup = [{"setup": s, **_agg(g)} for s, g in trades.groupby("setup")]
    bins = [0, 65, 75, 85, 101]
    labels = ["60-65", "65-75", "75-85", "85+"]
    trades["score_bin"] = pd.cut(trades["score"], bins=bins, labels=labels, right=False)
    by_score = [{"score": str(s), **_agg(g)} for s, g in trades.groupby("score_bin", observed=True)]
    ex = trades["excess"].dropna()
    return BacktestResult(
        start=trades["date"].min(),
        end=trades["date"].max(),
        days=len(test_dates),
        horizon=horizon,
        n_signals=int(len(trades)),
        avg_ret=round(float(trades["ret"].mean()), 2),
        median_ret=round(float(trades["ret"].median()), 2),
        win_rate=round(float((trades["ret"] > 0).mean() * 100), 1),
        avg_excess=round(float(ex.mean()), 2) if len(ex) else float("nan"),
        excess_win_rate=round(float((ex > 0).mean() * 100), 1) if len(ex) else float("nan"),
        stop_hit_rate=round(float(trades["hit_stop"].mean() * 100), 1),
        target_hit_rate=round(float(trades["hit_target"].mean() * 100), 1),
        by_setup=by_setup,
        by_score=by_score,
        trades=trades,
    )


def format_result(res: BacktestResult) -> str:
    lines = [
        f"回测区间 {res.start} ~ {res.end}（{res.days} 个交易日），持有 {res.horizon} 日，共 {res.n_signals} 次推荐",
        f"平均收益 {res.avg_ret:+.2f}%  中位数 {res.median_ret:+.2f}%  胜率 {res.win_rate:.1f}%",
        f"相对基准超额 {res.avg_excess:+.2f}%  跑赢基准比例 {res.excess_win_rate:.1f}%",
        f"触及止损 {res.stop_hit_rate:.1f}%  触及目标 {res.target_hit_rate:.1f}%",
        "",
        "按形态：",
    ]
    for r in res.by_setup:
        lines.append(f"  {r['setup']:<6} n={r['n']:<4} 平均 {r['avg_ret']:+.2f}%  胜率 {r['win_rate']:.1f}%  超额 {r['avg_excess']:+.2f}%  止损率 {r['stop_hit_rate']:.1f}%")
    lines.append("按评分：")
    for r in res.by_score:
        lines.append(f"  {r['score']:<6} n={r['n']:<4} 平均 {r['avg_ret']:+.2f}%  胜率 {r['win_rate']:.1f}%  超额 {r['avg_excess']:+.2f}%  止损率 {r['stop_hit_rate']:.1f}%")
    return "\n".join(lines)
