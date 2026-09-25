import datetime as dt

from daily_report.backtest import format_result, run_backtest
from daily_report.config import Config
from daily_report.data.demo import DemoProvider
from daily_report.report import sparkline


def test_backtest_on_demo_data():
    cfg = Config()
    cfg.data.source = "demo"
    cfg.recommend.min_score = 0
    end = dt.date(2026, 9, 24)
    hist = DemoProvider(n_symbols=30).load_history(end=end, start=end - dt.timedelta(days=420))
    res = run_backtest(cfg, hist, days=15, horizon=5)
    assert res.days == 15 and res.horizon == 5 and res.n_signals > 0
    assert 0 <= res.win_rate <= 100 and 0 <= res.stop_hit_rate <= 100
    assert res.trades is not None and {"date", "code", "ret", "excess", "hit_stop"} <= set(res.trades.columns)
    # 推荐日期不能晚于可观察期末
    assert res.trades["date"].max() < end.isoformat()
    text = format_result(res)
    assert "回测区间" in text and "按形态" in text
    assert "trades" not in res.to_dict()


def test_sparkline_svg():
    svg = sparkline([10, 11, 12, 11.5, 13])
    assert svg.startswith("<svg") and 'class="spark up"' in svg and "<polyline" in svg and "<title>" in svg
    assert 'class="spark down"' in sparkline([13, 12, 11])
    assert sparkline([1]) == "" and sparkline([]) == ""
