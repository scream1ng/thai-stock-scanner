import requests
import pandas as pd
import yfinance as yf
import numpy as np
import time

BENCHMARK = "^SET.BK"


# ── Helpers ────────────────────────────────────────────────────────────────────

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


# ── Step 1: fetch stock list from TradingView ──────────────────────────────────

def get_thailand_stocks():
    print("Fetching stock list from TradingView...")
    url = "https://scanner.tradingview.com/thailand/scan"
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "columns": [
            "name", "description", "sector",
            "close", "average_volume_10d_calc",
            "SMA10", "SMA20", "SMA50", "SMA200",
            "ATR",
        ],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "range": [0, 3000],
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()

    rows = []
    for item in resp.json().get("data", []):
        d = item["d"]
        ticker, desc, sector = d[0], d[1], d[2]
        price    = d[3] or 0
        avg_vol  = d[4] or 0
        sma10, sma20, sma50, sma200, atr = d[5], d[6], d[7], d[8], d[9]

        # Liquidity filter & exclude warrants / rights
        if ".F" in ticker or ".R" in ticker:
            continue
        if price * avg_vol < 5_000_000:
            continue
        # Above SMA50 filter (pre-screen before downloading history)
        if sma50 and price < sma50:
            continue

        rows.append({
            "ticker_bk": f"{ticker}.BK",
            "sector":    sector or "Unknown",
            "desc":      desc or ticker,
            "tv": {
                "price":  round(price,  2),
                "sma10":  round(sma10,  2) if sma10  else None,
                "sma20":  round(sma20,  2) if sma20  else None,
                "sma50":  round(sma50,  2) if sma50  else None,
                "sma200": round(sma200, 2) if sma200 else None,
                "atr":    round(atr,    4) if atr    else None,
            },
        })

    print(f"  → {len(rows)} stocks pass pre-screen")
    return rows


# ── Step 2: download close history & compute RS metrics ───────────────────────

def _download_closes(ticker, period="2y"):
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(ticker, axis=1, level=1)
    return df["Close"].dropna()


_bench_closes = None  # cache benchmark within a single run


def get_bench_closes():
    global _bench_closes
    if _bench_closes is None:
        print(f"Downloading benchmark ({BENCHMARK})...")
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

    # Use TradingView values for SMAs / ATR where available, else compute
    price  = tv["price"]
    sma50  = tv["sma50"]  or float(s_close.rolling(50).mean().iloc[-1])
    sma10  = tv["sma10"]  or float(s_close.rolling(10).mean().iloc[-1])
    sma20  = tv["sma20"]  or float(s_close.rolling(20).mean().iloc[-1])
    sma200 = tv["sma200"] or float(s_close.rolling(200).mean().iloc[-1])

    # Double-check above SMA50 with live data
    if price < sma50:
        return None

    # ATR (use TV value if available)
    atr_val = tv["atr"]
    if atr_val is None:
        # Need OHLC — fall back to yfinance full download
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
        low_63  = float(s_close.rolling(63).min().iloc[-1])  # approximate with close

    atrp           = 100 * (atr_val / price)
    price_dist_pct = ((price - sma50) / sma50) * 100
    stretch_factor = price_dist_pct / atrp if atrp else 0
    atr_mult_low   = (price - low_63) / atr_val if atr_val else 0

    # RS Rating (weighted 3/6/9/12-month performance vs benchmark)
    def _rs(closes, ref):
        return (0.4 * (closes.iloc[-1] / closes.iloc[-64])  +
                0.2 * (closes.iloc[-1] / closes.iloc[-127]) +
                0.2 * (closes.iloc[-1] / closes.iloc[-189]) +
                0.2 * (closes.iloc[-1] / closes.iloc[-253]))

    rs_stock = _rs(s_close, None)
    rs_ref   = _rs(b_close, None)
    rs_rating = f_calc_final_rating((rs_stock / rs_ref) * 100)

    # RS Momentum (1-month)
    rs_mom_stock = s_close.iloc[-1] / s_close.iloc[-22]
    rs_mom_ref   = b_close.iloc[-1] / b_close.iloc[-22]
    rs_momentum  = f_calc_final_rating((rs_mom_stock / rs_mom_ref) * 100)

    return {
        "ticker": ticker_bk,
        "sector": sector,
        "technical": {
            "price":          round(price,          2),
            "sma10":          round(sma10,          2),
            "sma20":          round(sma20,          2),
            "sma50":          round(sma50,          2),
            "sma200":         round(sma200,         2),
            "rs_rating":      round(rs_rating,      1),
            "rs_momentum":    round(rs_momentum,    1),
            "stretch_factor": round(stretch_factor, 2),
            "atr_pct":        round(atrp,           2),
            "atr_mult_low":   round(atr_mult_low,   2),
        },
    }


# ── Public entry point ─────────────────────────────────────────────────────────

def run_scan():
    stock_list = get_thailand_stocks()
    results = []
    total = len(stock_list)

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
