"""命令行入口。

    python -m daily_report run --source demo
    python -m daily_report run --source yfinance --config config.yaml --date 2026-09-24
    python -m daily_report gen-demo --out data/csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

from . import __version__
from .config import load_config


def _parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"日期格式应为 YYYY-MM-DD: {s}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daily-report", description="美股每日异动与推荐建仓日报")
    p.add_argument("--version", action="version", version=f"daily-report {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="生成日报")
    run.add_argument("-c", "--config", help="YAML 配置文件路径")
    run.add_argument("-d", "--date", type=_parse_date, help="报告日期（默认今天；非交易日自动回退到最近交易日）")
    run.add_argument("-s", "--source", choices=["demo", "csv", "yfinance", "stooq"], help="数据源，覆盖配置文件")
    run.add_argument("-u", "--universe", help="股票池：builtin | nasdaq | 文件路径")
    run.add_argument("--csv-dir", help="csv 数据源目录")
    run.add_argument("-o", "--out", help="报告输出目录")
    run.add_argument("-f", "--formats", help="输出格式，逗号分隔，如 md,html,json")
    run.add_argument("--max-symbols", type=int, help="联网数据源最多拉取多少只股票")
    run.add_argument("--top-n", type=int, help="推荐条数")
    run.add_argument("--capital", type=float, help="账户总资金（美元），用于仓位计算")
    run.add_argument("--notify", action="store_true", help="生成后推送到配置的 webhook")
    run.add_argument("--print", dest="print_md", action="store_true", help="同时把 Markdown 打印到终端")

    gen = sub.add_parser("gen-demo", help="生成一份合成行情 CSV，便于试用 csv 数据源")
    gen.add_argument("-o", "--out", default="data/csv", help="输出目录")
    gen.add_argument("-n", "--symbols", type=int, default=60)
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("-d", "--date", type=_parse_date, help="最后一个交易日（默认今天）")
    return p


def cmd_run(args: argparse.Namespace) -> int:
    from .notify import send
    from .pipeline import run_pipeline
    from .report import render_markdown, write_report

    overrides = {
        "data": {"source": args.source, "csv_dir": args.csv_dir, "max_symbols": args.max_symbols, "universe": args.universe},
        "report": {"out_dir": args.out, "formats": args.formats.split(",") if args.formats else None},
        "recommend": {"top_n": args.top_n, "capital": args.capital},
    }
    cfg = load_config(args.config, overrides)
    report = run_pipeline(cfg, date=args.date)
    written = write_report(report, cfg.report)
    for fmt, path in written.items():
        print(f"[{fmt}] {path}")
    if args.print_md:
        print()
        print(render_markdown(report, cfg.report))
    if args.notify:
        ok = send(report, cfg.notify)
        print("推送成功" if ok else "未推送（未配置 webhook 或推送失败）")
    return 0


def cmd_gen_demo(args: argparse.Namespace) -> int:
    from .data.demo import DemoProvider

    end = args.date or dt.date.today()
    start = end - dt.timedelta(days=420)
    hist = DemoProvider(n_symbols=args.symbols, seed=args.seed).load_history(end=end, start=start)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "all.csv"
    hist.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"已写入 {path}：{hist['code'].nunique()} 只股票，{len(hist)} 行")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "gen-demo":
        return cmd_gen_demo(args)
    return 1
