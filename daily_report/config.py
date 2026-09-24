"""配置加载。所有阈值都可以通过 YAML 覆盖，未指定的项使用默认值。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AnomalyConfig:
    big_move_pct: float = 7.0           # 单日涨跌幅绝对值 >= 该值视为大涨/大跌
    volume_ratio_window: int = 5        # 量比基准：过去 N 日均量
    volume_spike_ratio: float = 3.0     # 成交量 / 均量 >= 该值视为放量
    volume_dry_ratio: float = 0.35      # 成交量 / 均量 <= 该值视为极度缩量
    breakout_window: int = 60           # 新高/新低回看天数
    gap_pct: float = 3.0                # 跳空缺口：开盘相对前一日高/低点的百分比
    amplitude_pct: float = 8.0          # 振幅 (high-low)/prev_close 百分比
    zscore_window: int = 60             # 收益率 z-score 回看天数
    zscore_threshold: float = 3.0       # |z| >= 该值视为统计异常
    turnover_pct: float = 15.0          # 换手率 >= 该值视为异常（需要流通股本数据，可选）
    max_items: int = 40                 # 报告中最多展示多少条异动


@dataclass
class RecommendConfig:
    capital: float = 1_000_000.0        # 账户总资金，用于仓位计算
    risk_per_trade_pct: float = 1.0     # 单笔交易风险预算占总资金百分比
    max_position_pct: float = 20.0      # 单只标的最大仓位百分比
    top_n: int = 10                     # 推荐条数
    min_score: float = 60.0             # 低于该评分不推荐
    min_avg_amount: float = 5e7         # 20 日均成交额下限（元），过滤流动性差的股票
    min_history_days: int = 70          # 历史数据不足时跳过
    max_atr_pct: float = 6.0            # ATR/收盘价 上限，过滤波动过大的股票
    rsi_low: float = 45.0
    rsi_high: float = 72.0
    momentum_window: int = 20
    momentum_min_pct: float = 0.0
    momentum_max_pct: float = 30.0
    pullback_band_pct: float = 3.0      # 收盘价距 MA20 在该带宽内视为回踩支撑
    stop_atr_mult: float = 2.0          # 止损 = 收盘 - N*ATR（与 10 日最低价取高者）
    reward_risk: float = 2.0            # 目标价 = 入场 + reward_risk * 风险
    exclude_st: bool = True
    exclude_limit_up: bool = True       # 当日涨停的股票次日难以买入，排除
    max_daily_gain_pct: float = 7.0     # 当日涨幅超过该值视为追高，不推荐
    max_daily_loss_pct: float = 4.0     # 当日跌幅超过该值视为走弱，不推荐
    exclude_gap_down: bool = True       # 当日跳空低开（开盘低于昨日最低）不推荐


@dataclass
class DataConfig:
    source: str = "demo"                # demo | csv | eastmoney | akshare
    csv_dir: str = "data/csv"
    cache_dir: str = "data/cache"
    history_days: int = 160             # 拉取多少个自然日的历史
    max_symbols: int = 300              # 联网数据源最多拉取多少只股票的历史
    watchlist: list[str] = field(default_factory=list)
    demo_symbols: int = 80
    demo_seed: int = 42
    request_interval: float = 0.05      # 联网请求间隔（秒）


@dataclass
class ReportConfig:
    out_dir: str = "reports"
    formats: list[str] = field(default_factory=lambda: ["md", "html", "json"])
    title: str = "A 股每日异动与建仓日报"


@dataclass
class NotifyConfig:
    webhook_url: str = ""               # 钉钉 / 企业微信 / 自定义 webhook，为空则不推送
    kind: str = "generic"               # generic | dingtalk | wecom


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
