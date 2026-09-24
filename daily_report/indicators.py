"""技术指标。所有函数均接受单只股票按日期升序排列的 DataFrame，返回 Series。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    return true_range(df).rolling(window, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    # 没有下跌时 RSI = 100
    out = out.where(avg_loss != 0, 100.0)
    return out


def volume_ratio(volume: pd.Series, window: int = 5) -> pd.Series:
    """量比：当日成交量 / 过去 window 日均量（不含当日）。"""
    base = volume.shift(1).rolling(window, min_periods=window).mean()
    return volume / base.replace(0, np.nan)


def pct_change(close: pd.Series) -> pd.Series:
    return close.pct_change() * 100.0


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """当日值相对过去 window 日（不含当日）的 z-score。"""
    hist = series.shift(1)
    mean = hist.rolling(window, min_periods=max(10, window // 2)).mean()
    std = hist.rolling(window, min_periods=max(10, window // 2)).std()
    return (series - mean) / std.replace(0, np.nan)


def enrich(df: pd.DataFrame, *, vr_window: int = 5, breakout_window: int = 60, zscore_window: int = 60) -> pd.DataFrame:
    """为单只股票的历史行情追加常用指标列。输入需按 date 升序。"""
    out = df.copy()
    close = out["close"]
    out["pct_chg"] = pct_change(close)
    out["prev_close"] = close.shift(1)
    out["prev_high"] = out["high"].shift(1)
    out["prev_low"] = out["low"].shift(1)
    out["ma5"] = sma(close, 5)
    out["ma10"] = sma(close, 10)
    out["ma20"] = sma(close, 20)
    out["ma60"] = sma(close, 60)
    out["ma20_slope"] = (out["ma20"] / out["ma20"].shift(5) - 1) * 100.0
    out["atr14"] = atr(out, 14)
    out["atr_pct"] = out["atr14"] / close * 100.0
    out["rsi14"] = rsi(close, 14)
    out["vol_ratio"] = volume_ratio(out["volume"], vr_window)
    out["avg_amount20"] = out["amount"].rolling(20, min_periods=10).mean()
    out["hi_n"] = out["high"].shift(1).rolling(breakout_window, min_periods=max(20, breakout_window // 2)).max()
    out["lo_n"] = out["low"].shift(1).rolling(breakout_window, min_periods=max(20, breakout_window // 2)).min()
    out["amplitude"] = (out["high"] - out["low"]) / out["prev_close"] * 100.0
    out["ret_z"] = rolling_zscore(out["pct_chg"], zscore_window)
    out["ret20"] = (close / close.shift(20) - 1) * 100.0
    out["ret5"] = (close / close.shift(5) - 1) * 100.0
    out["low10"] = out["low"].rolling(10, min_periods=5).min()
    if "turnover" not in out.columns:
        out["turnover"] = np.nan
    return out
