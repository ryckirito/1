"""东方财富数据源解析逻辑测试（用假 session，不联网）。"""
import datetime as dt

import pandas as pd

from daily_report.data.eastmoney import EastmoneyProvider
from daily_report.market import eastmoney_secid


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _Session:
    headers = {}

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if "clist" in url:
            diff = [
                {"f12": "600519", "f14": "贵州茅台", "f2": 1500.0, "f3": 1.2, "f5": 30000, "f6": 4.5e9, "f10": 1.1, "f100": "白酒"},
                {"f12": "000001", "f14": "平安银行", "f2": 10.0, "f3": -8.0, "f5": 900000, "f6": 9e8, "f10": 3.5, "f100": "银行"},
                {"f12": "300750", "f14": "宁德时代", "f2": "-", "f3": "-", "f5": "-", "f6": "-", "f10": "-", "f100": "电池"},
            ]
            return _Resp({"data": {"diff": diff}})
        secid = params["secid"]
        code = secid.split(".")[1]
        klines = [f"2026-09-{d:02d},10,11,12,9,1000,11000,5,1,1,0.5" for d in range(1, 25) if dt.date(2026, 9, d).weekday() < 5]
        return _Resp({"data": {"name": f"股票{code}", "klines": klines}})


def test_secid():
    assert eastmoney_secid("600519") == "1.600519"
    assert eastmoney_secid("000001") == "0.000001"
    assert eastmoney_secid("830799") == "0.830799"


def test_eastmoney_parse(tmp_path):
    sess = _Session()
    p = EastmoneyProvider(max_symbols=1, watchlist=["300001"], cache_dir=str(tmp_path), request_interval=0, session=sess)
    spot = p.fetch_spot()
    assert len(spot) == 2  # 无价数据行被剔除
    universe = p.select_universe(spot)
    assert universe[0] == "600519" and "300001" in universe and "000001" in universe
    hist = p.load_history(end=dt.date(2026, 9, 24), start=dt.date(2026, 9, 1))
    assert set(hist["code"]) == {"600519", "000001", "300001"}
    assert "turnover" in hist.columns and hist["turnover"].iloc[0] == 0.5
    assert hist[hist["code"] == "600519"]["industry"].iloc[0] == "白酒"
    assert pd.api.types.is_datetime64_any_dtype(hist["date"])
    # 第二次读取命中缓存，不再请求 K 线
    n_calls = len(sess.calls)
    p.fetch_kline("600519", dt.date(2026, 9, 1), dt.date(2026, 9, 24))
    assert len(sess.calls) == n_calls
