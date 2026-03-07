import requests
import pandas as pd
import yfinance as yf
import numpy as np
import time

BENCHMARK = "^SET.BK"


# ── Core math ─────────────────────────────────────────────────────────────────

def rma(series, length):
    return series.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def f_calc_final_rating(score):
    score = float(score)
    if score >= 195.93: return 99.0
    if score <= 24.86:  return 1.0
    if score >= 117.11: up, dn, rUp, rDn, w = 195.93, 117.11, 98, 90, 0.33
    elif score >= 99.04: up, dn, rUp, rDn, w = 117.11, 99.04, 89, 70, 2.1
    elif score >= 91.66: up, dn, rUp, rDn, w = 99.04, 91.66, 69, 50, 0
    elif score >= 80.96: up, dn, rUp, rDn, w = 91.66, 80.96, 49, 30, 0
    elif score >= 53.64: up, dn, rUp, rDn, w = 80.96, 53.64, 29, 10, 0
    else:                up, dn, rUp, rDn, w = 53.64, 24.86,  9,  2, 0
    sum_val = score + (score - dn) * w
    if sum_val > (up - 1): sum_val = up - 1
    k1 = dn / rDn
    k2 = (up - 1) / rUp
    k3 = (k1 - k2) / (up - 1 - dn)
    rating = sum_val / (k1 - k3 * (score - dn))
    return float(np.clip(rating, rDn, rUp))


# ── Step 1: TradingView scan ──────────────────────────────────────────────────

def get_thailand_stocks():
    print("Fetching stock list from TradingView...")
    url = "https://scanner.tradingview.com/thailand/scan"
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "columns": [
            "name", "description", "sector",
            "close", "average_volume_10d_calc",
            "SMA10", "SMA20", "SMA50", "SMA200",
            "ATR", "volume",
        ],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "range": [0, 3000],
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()

    rows = []
    for item in resp.json().get("data", []):
        d = item["d"]
        ticker  = d[0];  desc = d[1];  sector = d[2]
        price   = d[3] or 0;  avg_vol = d[4] or 0
        sma10, sma20, sma50, sma200, atr = d[5], d[6], d[7], d[8], d[9]
        volume  = d[10] or 0

        if ".F" in ticker or ".R" in ticker:
            continue
        if price * avg_vol < 5_000_000:
            continue
        if sma50 and price < sma50:
            continue

        rows.append({
            "ticker_bk": f"{ticker}.BK",
            "sector":    sector or "Unknown",
            "desc":      desc or ticker,
            "tv": {
                "price":        round(price,  2),
                "sma10":        round(sma10,  2) if sma10  else None,
                "sma20":        round(sma20,  2) if sma20  else None,
                "sma50":        round(sma50,  2) if sma50  else None,
                "sma200":       round(sma200, 2) if sma200 else None,
                "atr":          round(atr,    4) if atr    else None,
                "volume":       int(volume),
                "volume_avg":   int(avg_vol),
                "volume_ratio": round(volume / avg_vol, 2) if avg_vol else 0,
            },
        })

    print(f"  → {len(rows)} stocks pass pre-screen")
    return rows


# ── Step 2: yfinance history + technical analysis ─────────────────────────────

def _download_closes(ticker, period="2y"):
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(ticker, axis=1, level=1)
    return df["Close"].dropna()


_bench_closes = None


def get_bench_closes():
    global _bench_closes
    if _bench_closes is None:
        print(f"  Downloading benchmark ({BENCHMARK})...")
        _bench_closes = _download_closes(BENCHMARK)
    return _bench_closes


def run_technical_analysis(stock):
    ticker_bk = stock["ticker_bk"]
    sector    = stock["sector"]
    tv        = stock["tv"]

    s_close = _download_closes(ticker_bk)
    b_close = get_bench_closes()

    if len(s_close) < 253 or len(b_close) < 253:
        return None

    price  = tv["price"]
    sma50  = tv["sma50"]  or float(s_close.rolling(50).mean().iloc[-1])
    sma10  = tv["sma10"]  or float(s_close.rolling(10).mean().iloc[-1])
    sma20  = tv["sma20"]  or float(s_close.rolling(20).mean().iloc[-1])
    sma200 = tv["sma200"] or float(s_close.rolling(200).mean().iloc[-1])

    if price < sma50:
        return None

    # ATR
    atr_val = tv["atr"]
    if atr_val is None:
        df_full = yf.download(ticker_bk, period="2y", interval="1d", progress=False)
        if isinstance(df_full.columns, pd.MultiIndex):
            df_full = df_full.xs(ticker_bk, axis=1, level=1)
        tr = pd.concat([
            (df_full["High"] - df_full["Low"]),
            (df_full["High"] - df_full["Close"].shift(1)).abs(),
            (df_full["Low"]  - df_full["Close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr_val = float(rma(tr, 14).iloc[-1])
        low_63  = float(df_full["Low"].rolling(63).min().iloc[-1])
    else:
        atr_val = float(atr_val)
        low_63  = float(s_close.rolling(63).min().iloc[-1])

    atrp           = 100 * (atr_val / price)
    stretch_factor = ((price - sma50) / sma50 * 100) / atrp if atrp else 0
    atr_mult_low   = (price - low_63) / atr_val if atr_val else 0

    # 52W proximity & tightness
    high_52w        = float(s_close.iloc[-253:].max())
    proximity_52w   = round((price / high_52w) * 100, 1) if high_52w else 0
    range_pct       = ((float(s_close.iloc[-10:].max()) - float(s_close.iloc[-10:].min())) / price * 100) if price else 0
    tightness_score = round(max(0, min(100, (15 - range_pct) / 15 * 100)), 1)

    # RS
    def _rs(c):
        return (0.4*(c.iloc[-1]/c.iloc[-64]) + 0.2*(c.iloc[-1]/c.iloc[-127]) +
                0.2*(c.iloc[-1]/c.iloc[-189]) + 0.2*(c.iloc[-1]/c.iloc[-253]))

    rs_rating   = f_calc_final_rating((_rs(s_close) / _rs(b_close)) * 100)
    rs_momentum = f_calc_final_rating(
        (s_close.iloc[-1]/s_close.iloc[-22]) / (b_close.iloc[-1]/b_close.iloc[-22]) * 100
    )

    return {
        "ticker": ticker_bk,
        "sector": sector,
        "technical": {
            "price":           round(price,           2),
            "sma10":           round(sma10,           2),
            "sma20":           round(sma20,           2),
            "sma50":           round(sma50,           2),
            "sma200":          round(sma200,          2),
            "rs_rating":       round(rs_rating,       1),
            "rs_momentum":     round(rs_momentum,     1),
            "stretch_factor":  round(stretch_factor,  2),
            "atr_pct":         round(atrp,            2),
            "atr_mult_low":    round(atr_mult_low,    2),
            "volume_ratio":    tv["volume_ratio"],
            "proximity_52w":   proximity_52w,
            "tightness_score": tightness_score,
        },
    }


# ── Public entry point ─────────────────────────────────────────────────────────

def run_scan():
    stock_list = get_thailand_stocks()
    results    = []
    total      = len(stock_list)

    for i, stock in enumerate(stock_list):
        try:
            print(f"  [{i+1}/{total}] {stock['ticker_bk']:<14}", end="\r")
            data = run_technical_analysis(stock)
            if data:
                results.append(data)
            time.sleep(0.3)
        except Exception as e:
            print(f"\n  ⚠ {stock['ticker_bk']}: {e}")
            continue

    print(f"\n  → {len(results)} stocks passed all filters")
    return results