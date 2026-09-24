import datetime as dt
import json

import pandas as pd

from daily_report.config import Config, load_config
from daily_report.data.csv_provider import CsvProvider
from daily_report.data.demo import DemoProvider
from daily_report.notify import build_summary
from daily_report.pipeline import run_pipeline
from daily_report.report import render_html, render_markdown, write_report


def _cfg(**data):
    cfg = Config()
    cfg.data.source = "demo"
    cfg.data.demo_symbols = 40
    for k, v in data.items():
        setattr(cfg.data, k, v)
    return cfg


def test_pipeline_demo_end_to_end(tmp_path):
    cfg = _cfg()
    cfg.report.out_dir = str(tmp_path)
    report = run_pipeline(cfg, date=dt.date(2026, 9, 24))
    assert report.date == "2026-09-24"
    o = report.overview
    assert o.total == 40                      # 基准 SPY/QQQ 不计入
    assert {b["code"] for b in o.benchmarks} == {"SPY", "QQQ"}
    assert o.up + o.down + o.flat == 40
    assert o.sectors and all(s["count"] > 0 for s in o.sectors)
    assert report.anomalies and all(a.tags for a in report.anomalies)
    assert all(a.code not in ("SPY", "QQQ") for a in report.anomalies)
    for r in report.recommendations:
        assert r.code not in ("SPY", "QQQ")
        assert r.stop_loss < r.entry < r.target and r.entry <= r.close + 1e-9
    written = write_report(report, cfg.report)
    assert set(written) == {"md", "html", "json"}
    data = json.loads((tmp_path / "2026-09-24.json").read_text(encoding="utf-8"))
    assert data["date"] == "2026-09-24" and len(data["anomalies"]) == len(report.anomalies)
    assert (tmp_path / "latest.md").exists()
    md = render_markdown(report, cfg.report)
    assert "异动榜" in md and "推荐建仓" in md and "不构成投资建议" in md and "SPY" in md
    html = render_html(report, cfg.report)
    assert "<table" in html and report.anomalies[0].code in html
    assert report.anomalies[0].code in build_summary(report)


def test_non_trading_day_falls_back():
    report = run_pipeline(_cfg(), date=dt.date(2026, 9, 27))  # 周日
    assert report.date == "2026-09-25"


def test_csv_provider_roundtrip(tmp_path):
    end = dt.date(2026, 9, 24)
    hist = DemoProvider(n_symbols=5, benchmarks=[]).load_history(end=end, start=end - dt.timedelta(days=420))
    (tmp_path / "all.csv").write_text(hist.to_csv(index=False), encoding="utf-8")
    # Yahoo 导出格式单文件，无 amount 列
    one = hist[hist["code"] == hist["code"].iloc[0]].drop(columns=["code", "name", "sector", "amount"])
    one = one.rename(columns={"date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    one["Adj Close"] = one["Close"]
    one.to_csv(tmp_path / "ZZZ_Test Corp.csv", index=False)
    df = CsvProvider(tmp_path).load_history(end=end, start=end - dt.timedelta(days=420))
    assert df["code"].nunique() == 6 and "ZZZ" in set(df["code"])
    assert df[df["code"] == "ZZZ"]["name"].iloc[0] == "Test Corp"
    assert df["amount"].notna().all()
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    cfg = _cfg(source="csv", csv_dir=str(tmp_path), benchmarks=[])
    assert run_pipeline(cfg, date=end).overview.total == 6


def test_load_config_overrides_and_validation(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("data:\n  source: csv\nrecommend:\n  top_n: 3\n", encoding="utf-8")
    cfg = load_config(p, {"data": {"source": "demo", "max_symbols": None}})
    assert cfg.data.source == "demo" and cfg.recommend.top_n == 3
    p.write_text("recommend:\n  bogus: 1\n", encoding="utf-8")
    try:
        load_config(p)
    except ValueError as exc:
        assert "bogus" in str(exc)
    else:
        raise AssertionError("未知字段应报错")
    assert load_config("config.example.yaml").data.source == "yfinance"
