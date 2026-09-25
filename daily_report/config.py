"""配置加载。所有阈值都可以通过 YAML 覆盖，未指定的项使用默认值。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AnomalyConfig:
    big_move_pct: float = 5.0           # 单日涨跌幅绝对值 >= 该值视为大涨/大跌
    huge_move_pct: float = 10.0         # 超过该值视为暴涨/暴跌
    volume_ratio_window: int = 20       # 量比基准：过去 N 日均量
    volume_spike_ratio: float = 2.5     # 成交量 / 均量 >= 该值视为放量
    volume_dry_ratio: float = 0.4       # 成交量 / 均量 <= 该值视为极度缩量
    long_window: int = 250              # 52 周新高/新低回看交易日数
    short_window: int = 20              # 20 日新高/新低回看交易日数
    gap_pct: float = 2.0                # 跳空缺口：开盘相对前一日高/低点的百分比
    amplitude_pct: float = 6.0          # 振幅 (high-low)/prev_close 百分比
    zscore_window: int = 60             # 收益率 z-score 回看天数
    zscore_threshold: float = 3.0       # |z| >= 该值视为统计异常
    excess_pct: float = 4.0             # 相对基准超额涨跌幅 >= 该值视为显著跑赢/跑输大盘
    streak_days: int = 5                # 连涨/连跌达到该天数打标签
    min_score: float = 10.0             # 强度低于该值的异动不展示（单个 20 日新高/新低或缩量约 5~8 分）
    max_items: int = 40                 # 报告中最多展示多少条异动


@dataclass
class RecommendConfig:
    capital: float = 100_000.0          # 账户总资金（美元），用于仓位计算
    risk_per_trade_pct: float = 1.0     # 单笔交易风险预算占总资金百分比
    max_position_pct: float = 15.0      # 单只标的最大仓位百分比
    top_n: int = 10                     # 推荐条数
    min_score: float = 70.0             # 低于该评分不推荐（回测：70 分以上超额收益明显更好）
    min_price: float = 5.0              # 股价下限（美元），过滤仙股
    min_avg_dollar_volume: float = 2e7  # 20 日均成交额下限（美元）
    min_history_days: int = 120         # 历史数据不足时跳过
    max_atr_pct: float = 7.0            # ATR/收盘价 上限，过滤波动过大的股票（回测：5% 会把强势高波动股全部剔除）
    rsi_low: float = 45.0
    rsi_high: float = 72.0
    momentum_window: int = 20
    momentum_min_pct: float = 0.0
    momentum_max_pct: float = 40.0      # 20 日涨幅超过该值视为过热（回测：25 太紧，会错过强势股）
    pullback_band_pct: float = 3.0      # 收盘价距 MA20 在该带宽内视为回踩支撑
    # 各因子权重（0~1 的因子得分乘以权重，合计即总分；默认合计 100）
    w_trend: float = 25.0
    w_momentum: float = 15.0
    w_rs: float = 15.0                  # 相对基准强弱（rs_window 日超额收益）
    w_volume: float = 15.0
    w_rsi: float = 10.0
    w_pattern: float = 20.0
    rs_window: int = 20                 # 相对强弱回看天数（20 或 60）
    w_mom12: float = 0.0                # 长期动量（12 个月剔除最近 1 个月）
    w_smooth: float = 0.0               # 趋势平滑度（60 日 log 价格与时间的相关系数）
    w_near_high: float = 0.0            # 接近 52 周高点
    rank_mode: bool = False             # True：相对强弱 / 长期动量按当日截面百分位打分，而非绝对阈值
    regime_filter: str = "off"          # off | halve | skip：基准跌破 MA200 时推荐条数减半 / 不推荐
    max_per_sector: int = 0             # 每个板块最多推荐几只，0 不限制
    max_total_exposure_pct: float = 100.0  # 全部推荐合计仓位上限，用于给单只仓位封顶
    stop_atr_mult: float = 3.0          # 止损 = 收盘 - N*ATR（与 10 日最低价取高者）
    min_stop_pct: float = 6.0           # 止损距离下限（%）。回测：3% 止损在 20 日持有期内一半会被震出
    reward_risk: float = 2.0            # 目标价 = 入场 + reward_risk * 风险
    max_daily_gain_pct: float = 6.0     # 当日涨幅超过该值视为追高，不推荐
    max_daily_loss_pct: float = 4.0     # 当日跌幅超过该值视为走弱，不推荐
    exclude_gap_down: bool = True       # 当日跳空低开（开盘低于昨日最低）不推荐
    fractional_shares: bool = False     # 是否允许碎股（True 时股数保留两位小数）


@dataclass
class DataConfig:
    source: str = "demo"                # demo | csv | yfinance | stooq
    csv_dir: str = "data/csv"
    cache_dir: str = "data/cache"
    history_days: int = 420             # 拉取多少个自然日的历史（约 290 个交易日，覆盖 52 周与 MA200）
    universe: str = "builtin"           # builtin | nasdaq | <文件路径>
    max_symbols: int = 300              # 联网数据源最多拉取多少只股票
    min_market_cap: float = 2e9         # universe=nasdaq 时的市值下限（美元）
    watchlist: list[str] = field(default_factory=list)
    benchmarks: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    demo_symbols: int = 80
    demo_seed: int = 42
    request_interval: float = 0.2       # 联网请求间隔（秒），仅 stooq 逐只请求时生效


@dataclass
class ReportConfig:
    out_dir: str = "reports"
    formats: list[str] = field(default_factory=lambda: ["md", "html", "json"])
    title: str = "美股每日异动与建仓日报"


@dataclass
class NotifyConfig:
    webhook_url: str = ""               # Slack / Discord / 钉钉 / 企业微信 / 自定义 webhook，为空则不推送
    kind: str = "generic"               # generic | slack | discord | dingtalk | wecom


@dataclass
class Config:
    data: DataConfig = field(default_factory=DataConfig)
    anomaly: AnomalyConfig = field(default_factory=AnomalyConfig)
    recommend: RecommendConfig = field(default_factory=RecommendConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECTIONS = {
    "data": DataConfig,
    "anomaly": AnomalyConfig,
    "recommend": RecommendConfig,
    "report": ReportConfig,
    "notify": NotifyConfig,
}


def _merge_section(cls, raw: dict[str, Any] | None):
    raw = raw or {}
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"配置节 {cls.__name__} 含未知字段: {sorted(unknown)}")
    return cls(**raw)


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> Config:
    """从 YAML 文件加载配置；path 为空时使用默认值。overrides 形如 {"data": {"source": "csv"}}。"""
    raw: dict[str, Any] = {}
    if path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"配置文件不存在: {p}")
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    if overrides:
        for section, values in overrides.items():
            raw.setdefault(section, {})
            raw[section].update({k: v for k, v in values.items() if v is not None})
    unknown = set(raw) - set(_SECTIONS)
    if unknown:
        raise ValueError(f"配置含未知节: {sorted(unknown)}")
    return Config(**{name: _merge_section(cls, raw.get(name)) for name, cls in _SECTIONS.items()})
