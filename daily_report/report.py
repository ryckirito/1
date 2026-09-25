"""报告渲染：Markdown / HTML / JSON。"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ReportConfig
from .market import fmt_usd
from .pipeline import DailyReport

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _is_nan(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_num(value: float, digits: int = 2) -> str:
    if _is_nan(value):
        return "-"
    return f"{value:.{digits}f}"


def fmt_pct(value: float, digits: int = 2) -> str:
    if _is_nan(value):
        return "-"
    return f"{value:+.{digits}f}%"


def fmt_shares(value: float) -> str:
    if _is_nan(value):
        return "-"
    return f"{value:g}" if float(value).is_integer() else f"{value:.2f}"


def sparkline(closes: list[float], width: int = 120, height: int = 32) -> str:
    """近 N 日收盘价走势的内联 SVG：2px 折线 + 淡面积 + 终点标记，颜色按区间涨跌取语义色。"""
    vals = [float(v) for v in (closes or []) if v == v]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pad = 3
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = pad + (width - 2 * pad) * i / (n - 1)
        y = pad + (height - 2 * pad) * (1 - (v - lo) / span)
        pts.append((round(x, 1), round(y, 1)))
    line = " ".join(f"{x},{y}" for x, y in pts)
    area = f"{pts[0][0]},{height - pad} " + line + f" {pts[-1][0]},{height - pad}"
    cls = "up" if vals[-1] >= vals[0] else "down"
    chg = (vals[-1] / vals[0] - 1) * 100 if vals[0] else 0.0
    title = f"近 {n} 日：{vals[0]:.2f} → {vals[-1]:.2f}（{chg:+.1f}%），区间 {lo:.2f}~{hi:.2f}"
    ex, ey = pts[-1]
    return (
        f'<svg class="spark {cls}" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
        f"<title>{title}</title>"
        f'<polygon class="area" points="{area}"/>'
        f'<polyline class="line" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="{line}"/>'
        f'<circle class="dot" cx="{ex}" cy="{ey}" r="3"/></svg>'
    )


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["usd"] = fmt_usd
    env.filters["num"] = fmt_num
    env.filters["pct"] = fmt_pct
    env.filters["shares"] = fmt_shares
    env.filters["spark"] = sparkline
    return env


def render_markdown(report: DailyReport, cfg: ReportConfig) -> str:
    return _env().get_template("report.md.j2").render(r=report, title=cfg.title)


def render_html(report: DailyReport, cfg: ReportConfig) -> str:
    return _env().get_template("report.html.j2").render(r=report, title=cfg.title)


def _strip_nan(obj: Any) -> Any:
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _strip_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_nan(v) for v in obj]
    return obj


def render_json(report: DailyReport) -> str:
    return json.dumps(_strip_nan(report.to_dict()), ensure_ascii=False, indent=2, default=str)


def write_report(report: DailyReport, cfg: ReportConfig) -> dict[str, Path]:
    """按配置格式写出报告文件，返回 {format: path}。同时更新 latest.* 副本。"""
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    renderers = {"md": lambda: render_markdown(report, cfg), "html": lambda: render_html(report, cfg), "json": lambda: render_json(report)}
    for fmt in cfg.formats:
        fmt = fmt.lower().strip()
        if fmt not in renderers:
            raise ValueError(f"不支持的报告格式: {fmt}")
        content = renderers[fmt]()
        path = out_dir / f"{report.date}.{fmt}"
        path.write_text(content, encoding="utf-8")
        (out_dir / f"latest.{fmt}").write_text(content, encoding="utf-8")
        written[fmt] = path
    return written
