"""把日报摘要推送到 webhook（Slack / Discord / 钉钉 / 企业微信 / 通用）。"""
from __future__ import annotations

import logging

import requests

from .config import NotifyConfig
from .pipeline import DailyReport
from .report import fmt_pct, fmt_shares

log = logging.getLogger(__name__)


def build_summary(report: DailyReport, max_anomalies: int = 8, max_recs: int = 5) -> str:
    o = report.overview
    bench = "，".join(f"{b['code']} {fmt_pct(b['pct_chg'])}" for b in o.benchmarks)
    lines = [
        f"## {report.date} 美股异动与建仓日报",
        f"覆盖 {o.total} 只：涨 {o.up} / 跌 {o.down}，涨超5% {o.big_up} / 跌超5% {o.big_down}，52周新高 {o.new_high_52w} / 新低 {o.new_low_52w}，中位涨幅 {fmt_pct(o.median_pct)}",
    ]
    if bench:
        lines.append(f"基准：{bench}")
    lines += ["", f"**异动 TOP{min(max_anomalies, len(report.anomalies))}**"]
    for a in report.anomalies[:max_anomalies]:
        lines.append(f"- {a.code} {a.name} {fmt_pct(a.pct_chg)} · {'/'.join(a.tags)}")
    lines += ["", f"**推荐建仓 TOP{min(max_recs, len(report.recommendations))}**"]
    if not report.recommendations:
        lines.append("- 今日无符合条件的标的")
    for r in report.recommendations[:max_recs]:
        lines.append(
            f"- {r.code} {r.name} 评分 {r.score:.0f} · {r.setup} · 入场 ${r.entry} 止损 ${r.stop_loss} 目标 ${r.target} · {fmt_shares(r.shares)} 股 / {r.position_pct:.1f}%"
        )
    lines += ["", "_仅供研究参考，不构成投资建议_"]
    return "\n".join(lines)


def send(report: DailyReport, cfg: NotifyConfig, session: requests.Session | None = None) -> bool:
    if not cfg.webhook_url:
        return False
    text = build_summary(report)
    kind = cfg.kind.lower()
    if kind == "slack":
        payload = {"text": text}
    elif kind == "discord":
        payload = {"content": text[:1990]}
    elif kind == "dingtalk":
        payload = {"msgtype": "markdown", "markdown": {"title": f"{report.date} 美股日报", "text": text}}
    elif kind == "wecom":
        payload = {"msgtype": "markdown", "markdown": {"content": text[:4000]}}
    else:
        payload = {"title": f"{report.date} 美股异动与建仓日报", "text": text, "report": report.to_dict()}
    sess = session or requests.Session()
    resp = sess.post(cfg.webhook_url, json=payload, timeout=20)
    if resp.status_code >= 300:
        log.error("推送失败 %s: %s", resp.status_code, resp.text[:200])
        return False
    log.info("已推送到 %s webhook", kind)
    return True
