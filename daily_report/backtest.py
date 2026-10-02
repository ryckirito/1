"""推荐信号回测：在历史上每个交易日按同样规则选股，统计之后 N 日的表现。

两层统计：
1. 信号层：每次推荐持有 horizon 日（先触及止损按止损价出场）的收益、胜率、相对基准超额；
2. 组合层：每天把当日推荐等权放进一个"批次"，批次占资金 1/horizon，持有 horizon 日后退出；
   合成每日资金曲线，计算年化收益、波动、夏普、最大回撤，并与基准买入持有比较。
另按时间分段（blocks）给出每段的超额收益，用于检查策略是否只在某一段行情有效。

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
class PortfolioStats:
    total_return: float          # 组合区间总收益 %
    annual_return: float         # 年化收益 %
    annual_vol: float            # 年化波动 %
    sharpe: float                # 夏普（无风险利率按 0）
    max_drawdown: float          # 最大回撤 %
    avg_exposure: float          # 平均仓位 %
    bench_total_return: float    # 基准买入持有总收益 %
    bench_annual_return: float
    bench_max_drawdown: float
    equity: pd.Series | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("equity", None)
        return d


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
    by_period: list[dict[str, Any]] = field(default_factory=list)
    portfolio: PortfolioStats | None = None
    trades: pd.DataFrame | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("trades", None)
        if self.portfolio is not None:
            d["portfolio"] = self.portfolio.to_dict()
        return d


def _forward_stats(df: pd.DataFrame, i: int, horizon: int, entry: float, stop: float, target: float) -> dict[str, float] | None:
    """从第 i 行之后持有 horizon 日：收益、是否触及止损/目标。"""
    fut = df.iloc[i + 1 : i + 1 + horizon]
    if len(fut) < horizon:
        return None
    exit_close = float(fut["close"].iloc[-1])
    ret = (exit_close / entry - 1) * 100
    lows, highs = fut["low"].values, fut["high"].values
    hit_stop = bool((lows <= stop).any())
    hit_target = bool((highs >= target).any())
    if hit_stop:
        first_stop = int(np.argmax(lows <= stop))
        first_target = int(np.argmax(highs >= target)) if hit_target else horizon + 1
        if first_stop <= first_target:
            ret = (stop / entry - 1) * 100
    return {"ret": ret, "hit_stop": hit_stop, "hit_target": hit_target}


def _agg(g: pd.DataFrame) -> dict[str, Any]:
    ex = g["excess"].dropna()
    return {
        "n": int(len(g)),
        "avg_ret": round(float(g["ret"].mean()), 2),
        "win_rate": round(float((g["ret"] > 0).mean() * 100), 1),
        "avg_excess": round(float(ex.mean()), 2) if len(ex) else float("nan"),
        "excess_win_rate": round(float((ex > 0).mean() * 100), 1) if len(ex) else float("nan"),
        "stop_hit_rate": round(float(g["hit_stop"].mean() * 100), 1),
    }


def simulate_portfolio(trades: pd.DataFrame, enriched: dict[str, pd.DataFrame], idx_of: dict, dates: list, horizon: int, bench_df: pd.DataFrame | None) -> PortfolioStats:
    """重叠批次组合：每个推荐日一个批次，占资金 1/horizon，批次内等权；触及止损当日按止损价出场。"""
    date_pos = {d: k for k, d in enumerate(dates)}
    n_days = len(dates)
    daily = np.zeros(n_days)        # 组合当日收益（小数）
    exposure = np.zeros(n_days)     # 当日持仓占比
    per_day_counts = trades.groupby("date").size().to_dict()
    for t in trades.itertuples(index=False):
        df = enriched[t.code]
        i = idx_of[t.code][pd.Timestamp(t.date)]
        w = 1.0 / horizon / per_day_counts[t.date]
        closes, lows = df["close"].values, df["low"].values
        prev = float(t.entry)
        for k in range(1, horizon + 1):
            j = i + k
            if j >= len(df):
                break
            d = df["date"].iloc[j]
            pos = date_pos.get(d)
            if pos is None:
                break
            if lows[j] <= t.stop_loss:
                r = t.stop_loss / prev - 1
                daily[pos] += w * r
                exposure[pos] += w
                break
            r = closes[j] / prev - 1
            daily[pos] += w * r
            exposure[pos] += w
            prev = closes[j]
    equity = pd.Series(np.cumprod(1 + daily), index=pd.to_datetime(dates))
    total = (equity.iloc[-1] - 1) * 100
    years = max(n_days / 252, 1e-9)
    ann = ((equity.iloc[-1]) ** (1 / years) - 1) * 100
    vol = float(np.std(daily, ddof=1) * np.sqrt(252) * 100) if n_days > 1 else 0.0
    sharpe = (ann / vol) if vol > 0 else 0.0
    dd = float(((equity / equity.cummax()) - 1).min() * 100)
    b_total = b_ann = b_dd = float("nan")
    if bench_df is not None:
        bc = bench_df.set_index("date")["close"].reindex(pd.to_datetime(dates)).ffill()
        if bc.notna().all():
            b_total = (bc.iloc[-1] / bc.iloc[0] - 1) * 100
            b_ann = ((bc.iloc[-1] / bc.iloc[0]) ** (1 / years) - 1) * 100
            b_dd = float(((bc / bc.cummax()) - 1).min() * 100)
    return PortfolioStats(
        total_return=round(float(total), 2),
        annual_return=round(float(ann), 2),
        annual_vol=round(vol, 2),
        sharpe=round(float(sharpe), 2),
        max_drawdown=round(dd, 2),
        avg_exposure=round(float(exposure.mean() * 100), 1),
        bench_total_return=round(float(b_total), 2),
        bench_annual_return=round(float(b_ann), 2),
        bench_max_drawdown=round(float(b_dd), 2),
        equity=equity,
    )


def run_backtest(cfg: Config, hist: pd.DataFrame, days: int = 120, horizon: int = 20, benchmark: str | None = None, blocks: int = 4) -> BacktestResult:
    enriched = enrich_panel(hist, cfg)
    bench = normalize_ticker(benchmark or (cfg.data.benchmarks[0] if cfg.data.benchmarks else "SPY"))
    attach_benchmark(enriched, bench)
    bench_df = enriched.get(bench)
    etfs = {c for c, df in enriched.items() if "sector" in df.columns and str(df["sector"].iloc[-1]) == "ETF"}
    excluded = {normalize_ticker(t) for t in cfg.data.benchmarks} | etfs
    all_dates = sorted(hist["date"].unique())
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
            rows.append({"date": pd.Timestamp(d), "code": r.code, "setup": r.setup, "score": r.score, "entry": r.entry,
                         "stop_loss": r.stop_loss, "target": r.target, "bench_ret": bench_ret, **st})
    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError("回测期间没有产生任何推荐，请放宽阈值或延长历史")
    trades["excess"] = trades["ret"] - trades["bench_ret"]

    by_setup = [{"setup": s, **_agg(g)} for s, g in trades.groupby("setup")]
    bins = [0, 65, 75, 85, 101]
    labels = ["60-65", "65-75", "75-85", "85+"]
    trades["score_bin"] = pd.cut(trades["score"], bins=bins, labels=labels, right=False)
    by_score = [{"score": str(s), **_agg(g)} for s, g in trades.groupby("score_bin", observed=True)]
    # 时间分段
    by_period = []
    if blocks > 1 and len(test_dates) >= blocks:
        edges = np.linspace(0, len(test_dates), blocks + 1, dtype=int)
        for k in range(blocks):
            lo, hi = test_dates[edges[k]], test_dates[edges[k + 1] - 1]
            g = trades[(trades["date"] >= lo) & (trades["date"] <= hi)]
            if len(g):
                by_period.append({"period": f"{pd.Timestamp(lo):%Y-%m-%d}~{pd.Timestamp(hi):%Y-%m-%d}", **_agg(g)})
    # 组合模拟：资金曲线覆盖 test_dates 之后 horizon 日
    sim_dates = all_dates[all_dates.index(test_dates[0]) : all_dates.index(test_dates[-1]) + horizon + 1]
    portfolio = simulate_portfolio(trades, enriched, idx_of, sim_dates, horizon, bench_df)

    ex = trades["excess"].dropna()
    trades["date"] = trades["date"].dt.strftime("%Y-%m-%d")
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
        by_period=by_period,
        portfolio=portfolio,
        trades=trades,
    )


def format_result(res: BacktestResult) -> str:
    lines = [
        f"回测区间 {res.start} ~ {res.end}（{res.days} 个交易日），持有 {res.horizon} 日，共 {res.n_signals} 次推荐",
        f"平均收益 {res.avg_ret:+.2f}%  中位数 {res.median_ret:+.2f}%  胜率 {res.win_rate:.1f}%",
        f"相对基准超额 {res.avg_excess:+.2f}%  跑赢基准比例 {res.excess_win_rate:.1f}%",
        f"触及止损 {res.stop_hit_rate:.1f}%  触及目标 {res.target_hit_rate:.1f}%",
    ]
    if res.portfolio:
        p = res.portfolio
        lines += [
            "",
            f"组合（每日批次等权，批次占资金 1/{res.horizon}）：总收益 {p.total_return:+.1f}%  年化 {p.annual_return:+.1f}%  波动 {p.annual_vol:.1f}%  夏普 {p.sharpe:.2f}  最大回撤 {p.max_drawdown:.1f}%  平均仓位 {p.avg_exposure:.0f}%",
            f"基准买入持有：总收益 {p.bench_total_return:+.1f}%  年化 {p.bench_annual_return:+.1f}%  最大回撤 {p.bench_max_drawdown:.1f}%",
        ]
    lines += ["", "按时间分段："]
    for r in res.by_period:
        lines.append(f"  {r['period']} n={r['n']:<4} 平均 {r['avg_ret']:+.2f}%  胜率 {r['win_rate']:.1f}%  超额 {r['avg_excess']:+.2f}%  跑赢 {r['excess_win_rate']:.1f}%")
    lines.append("按形态：")
    for r in res.by_setup:
        lines.append(f"  {r['setup']:<6} n={r['n']:<4} 平均 {r['avg_ret']:+.2f}%  胜率 {r['win_rate']:.1f}%  超额 {r['avg_excess']:+.2f}%  止损率 {r['stop_hit_rate']:.1f}%")
    lines.append("按评分：")
    for r in res.by_score:
        lines.append(f"  {r['score']:<6} n={r['n']:<4} 平均 {r['avg_ret']:+.2f}%  胜率 {r['win_rate']:.1f}%  超额 {r['avg_excess']:+.2f}%  止损率 {r['stop_hit_rate']:.1f}%")
    return "\n".join(lines)
