"""把日报摘要推送到 webhook（钉钉 / 企业微信 / 通用）。"""
from __future__ import annotations

import logging

import requests

from .config import NotifyConfig
from .pipeline import DailyReport
from .report import fmt_pct

log = logging.getLogger(__name__)


def build_summary(report: DailyReport, max_anomalies: int = 8, max_recs: int = 5) -> str:
    o = report.overview
    lines = [
        f"## {report.date} 异动与建仓日报",
        f"覆盖 {o.total} 只：涨 {o.up} / 跌 {o.down}，涨停 {o.limit_up} / 跌停 {o.limit_down}，中位涨幅 {fmt_pct(o.median_pct)}",
        "",
        f"**异动 TOP{min(max_anomalies, len(report.anomalies))}**",
    ]
    for a in report.anomalies[:max_anomalies]:
        lines.append(f"- {a.name}({a.code}) {fmt_pct(a.pct_chg)} · {'/'.join(a.tags)}")
    lines += ["", f"**推荐建仓 TOP{min(max_recs, len(report.recommendations))}**"]
    if not report.recommendations:
        lines.append("- 今日无符合条件的标的")
    for r in report.recommendations[:max_recs]:
        lines.append(f"- {r.name}({r.code}) 评分 {r.score:.0f} · {r.setup} · 入场 {r.entry} 止损 {r.stop_loss} 目标 {r.target} · 仓位 {r.position_pct:.1f}%")
    lines += ["", "_仅供研究参考，不构成投资建议_"]
    return "\n".join(lines)


def send(report: DailyReport, cfg: NotifyConfig, session: requests.Session | None = None) -> bool:
    if not cfg.webhook_url:
        return False
    text = build_summary(report)
    kind = cfg.kind.lower()
    if kind == "dingtalk":
        payload = {"msgtype": "markdown", "markdown": {"title": f"{report.date} 日报", "text": text}}
    elif kind == "wecom":
        payload = {"msgtype": "markdown", "markdown": {"content": text[:4000]}}
    else:
        payload = {"title": f"{report.date} 异动与建仓日报", "text": text, "report": report.to_dict()}
    sess = session or requests.Session()
    resp = sess.post(cfg.webhook_url, json=payload, timeout=20)
    if resp.status_code >= 300:
        log.error("推送失败 %s: %s", resp.status_code, resp.text[:200])
        return False
    log.info("已推送到 %s webhook", kind)
    return True
