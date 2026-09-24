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
