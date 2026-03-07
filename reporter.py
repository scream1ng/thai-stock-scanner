import os
import io
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from datetime import datetime

from tracker import classify, get_sector_summary

WEBHOOK_URL    = os.getenv("DISCORD_WEBHOOK")
CHAR_LIMIT     = 1900
THRESHOLD      = 75
QUADRANT_ORDER = ["Leading", "Improving", "Weakening"]
QUADRANT_EMOJI = {"Leading": "🟢", "Improving": "🔵", "Weakening": "🟠"}
QUADRANT_COLOR = {"Leading": "#2ecc71", "Improving": "#3498db", "Weakening": "#e67e22", "Lagging": "#95a5a6"}


# ── Discord primitives ─────────────────────────────────────────────────────────

def _create_thread(thread_name: str, content: str) -> str | None:
    """Create a new forum thread. Returns thread_id for follow-up messages."""
    if not WEBHOOK_URL:
        print(f"[THREAD] {thread_name}\n{content}")
        return None
    resp = requests.post(
        f"{WEBHOOK_URL}?wait=true",
        json={"thread_name": thread_name, "content": content},
        timeout=15,
    )
    if not resp.ok:
        print(f"[ERROR] Failed to create thread: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    return resp.json().get("channel_id")


def _post(content: str, thread_id: str | None = None):
    """Send a text message into a thread (or stdout if no webhook)."""
    if not content or not content.strip():
        return
    if not WEBHOOK_URL:
        print(content)
        return
    url = f"{WEBHOOK_URL}?thread_id={thread_id}" if thread_id else WEBHOOK_URL
    resp = requests.post(url, json={"content": content}, timeout=15)
    if not resp.ok:
        print(f"[ERROR] {resp.status_code}: {resp.text}")
        resp.raise_for_status()


def _post_file(filename: str, file_bytes: bytes, content: str = "", thread_id: str | None = None):
    """Send a file attachment (e.g. image, txt) into a thread."""
    if not WEBHOOK_URL:
        print(f"[FILE] Would send: {filename}")
        return
    url = f"{WEBHOOK_URL}?wait=true"
    if thread_id:
        url += f"&thread_id={thread_id}"
    resp = requests.post(
        url,
        data={"content": content},
        files={"file": (filename, file_bytes)},
        timeout=30,
    )
    if not resp.ok:
        print(f"[ERROR] File upload failed: {resp.status_code}: {resp.text}")
        resp.raise_for_status()


def _send_chunked(header: str, lines: list, thread_id: str | None = None):
    """Send header then split lines into code blocks."""
    _post(header, thread_id)
    if not lines:
        _post("```(none)```", thread_id)
        return
    chunk = ""
    for line in lines:
        candidate = chunk + line + "\n"
        if len(candidate) + 6 > CHAR_LIMIT:
            _post(f"```\n{chunk}```", thread_id)
            chunk = line + "\n"
        else:
            chunk = candidate
    if chunk.strip():
        _post(f"```\n{chunk}```", thread_id)


# ── Row formatters ─────────────────────────────────────────────────────────────

def _stock_row(ticker, rs_rating, rs_momentum, stretch_factor, sector,
               volume_ratio=0, proximity_52w=0, tightness_score=0, **_):
    vol_flag   = "🔥" if volume_ratio   >= 1.5 else "  "
    near_flag  = "⭐" if proximity_52w >= 95 else "📍" if proximity_52w >= 85 else "  "
    tight_flag = "☑️" if tightness_score >= 70  else "  "
    str_flag   = "❌" if stretch_factor  >= 7   else "  "
    return (
        f"{ticker:<12} "
        f"RS:{rs_rating:>5.1f}  "
        f"MOM:{rs_momentum:>5.1f}  "
        f"STR:{stretch_factor:>5.2f}{str_flag} "
        f"VOL:{volume_ratio:>4.1f}x{vol_flag} "
        f"52W:{proximity_52w:>5.1f}%{near_flag} "
        f"TIGHT:{tightness_score:>4.0f}{tight_flag}  "
        f"{str(sector)[:18]}"
    )


def _streak_row(ticker, streak, rs_momentum, rs_rating, sector, **_):
    return (
        f"{ticker:<12} "
        f"🔥{streak}d  "
        f"MOM:{rs_momentum:>5.1f}  "
        f"RS:{rs_rating:>5.1f}  "
        f"{str(sector)[:22]}"
    )


def _change_row(ticker, from_q, to_q, rs_rating, rs_momentum, sector, **_):
    arrow = "↗" if to_q in ("Leading", "Improving") else "↘"
    return (
        f"{ticker:<12} "
        f"{from_q:<10} {arrow} {to_q:<10}  "
        f"RS:{rs_rating:>5.1f}  MOM:{rs_momentum:>5.1f}"
    )


def _crossing_row(ticker, metric, from_val, to_val, sector, **_):
    return (
        f"{ticker:<12} "
        f"{metric:<12} "
        f"{from_val:>5.1f} → {to_val:>5.1f}  "
        f"{str(sector)[:22]}"
    )


# ── Scatter chart ──────────────────────────────────────────────────────────────

def build_scatter_chart(results: list, today: str) -> bytes:
    """
    Plot RS Rating (x) vs RS Momentum (y) for all stocks.
    Returns PNG bytes.
    """
    fig, ax = plt.subplots(figsize=(12, 9))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    # Quadrant shading
    ax.axhspan(THRESHOLD, 100, xmin=(THRESHOLD/100), alpha=0.08, color="#2ecc71")   # Leading
    ax.axhspan(THRESHOLD, 100, xmax=(THRESHOLD/100), alpha=0.08, color="#3498db")   # Improving
    ax.axhspan(0, THRESHOLD,   xmin=(THRESHOLD/100), alpha=0.08, color="#e67e22")   # Weakening
    ax.axhspan(0, THRESHOLD,   xmax=(THRESHOLD/100), alpha=0.05, color="#95a5a6")   # Lagging

    # Threshold lines
    ax.axhline(THRESHOLD, color="#ffffff", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.axvline(THRESHOLD, color="#ffffff", linewidth=0.5, linestyle="--", alpha=0.4)

    # Plot Lagging first (background red dots — macro picture)
    for item in results:
        tech = item["technical"]
        x    = tech["rs_rating"]
        y    = tech["rs_momentum"]
        if classify(x, y) != "Lagging":
            continue
        ax.scatter(x, y, c="#c0392b", s=15, alpha=0.35, edgecolors="none")

    # Plot Leading / Improving / Weakening on top
    for item in results:
        tech = item["technical"]
        x    = tech["rs_rating"]
        y    = tech["rs_momentum"]
        q    = classify(x, y)
        if q == "Lagging":
            continue
        col          = QUADRANT_COLOR[q]
        volume_ratio = tech.get("volume_ratio", 1)
        size = max(20, min(300, volume_ratio * 60))

        ax.scatter(x, y, c=col, s=size, alpha=0.75, edgecolors="none")

        # Label only high-volume tickers
        if volume_ratio >= 1.5:
            label = item["ticker"].replace(".BK", "")
            ax.annotate(label, (x, y), fontsize=7, color="#ffffff",
                        fontweight="bold", alpha=0.95,
                        xytext=(5, 5), textcoords="offset points")

    # Quadrant labels
    label_cfg = dict(fontsize=11, fontweight="bold", alpha=0.35)
    ax.text(87, 97, "LEADING",   color="#2ecc71", ha="center", **label_cfg)
    ax.text(37, 97, "IMPROVING", color="#3498db", ha="center", **label_cfg)
    ax.text(87,  3, "WEAKENING", color="#e67e22", ha="center", **label_cfg)
    ax.text(37,  3, "LAGGING",   color="#95a5a6", ha="center", **label_cfg)

    # Legend (dot size = volume)
    legend_elements = [
        mpatches.Patch(color="#2ecc71", label="Leading"),
        mpatches.Patch(color="#3498db", label="Improving"),
        mpatches.Patch(color="#e67e22", label="Weakening"),
        mpatches.Patch(color="#95a5a6", label="Lagging"),
        plt.scatter([], [], s=40,  color="white", alpha=0.5, label="Normal volume"),
        plt.scatter([], [], s=100, color="white", alpha=0.5, label="High volume (1.5x+)"),
    ]
    ax.legend(handles=legend_elements, loc="lower right",
              facecolor="#1a1a2e", edgecolor="#444", labelcolor="white", fontsize=8)

    # Axes styling
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("RS Rating", color="#cccccc", fontsize=11)
    ax.set_ylabel("RS Momentum", color="#cccccc", fontsize=11)
    ax.set_title(f"Thai Market — RS Rating vs Momentum  |  {today}", color="white", fontsize=13, pad=12)
    ax.tick_params(colors="#888888")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── TradingView watchlist export ───────────────────────────────────────────────

def build_tradingview_watchlist(results: list) -> bytes:
    """
    Build a TradingView-compatible watchlist for Leading & Improving stocks.
    Format: SET:TICKER one per line.
    """
    lines = ["### Leading", ]
    leading   = [r for r in results if classify(r["technical"]["rs_rating"], r["technical"]["rs_momentum"]) == "Leading"]
    improving = [r for r in results if classify(r["technical"]["rs_rating"], r["technical"]["rs_momentum"]) == "Improving"]

    for item in sorted(leading, key=lambda x: -x["technical"]["rs_momentum"]):
        ticker_tv = "SET:" + item["ticker"].replace(".BK", "")
        lines.append(ticker_tv)

    lines.append("### Improving")
    for item in sorted(improving, key=lambda x: -x["technical"]["rs_momentum"]):
        ticker_tv = "SET:" + item["ticker"].replace(".BK", "")
        lines.append(ticker_tv)

    return "\n".join(lines).encode("utf-8")


# ── Sector rotation table ──────────────────────────────────────────────────────

def _sector_table(results: list) -> list:
    summary = get_sector_summary(results)
    rows = []
    for i, s in enumerate(summary[:10], 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f" {i}."
        tickers_str = ", ".join(s["tickers"])
        rows.append(
            f"{medal} {s['sector'][:24]:<24}  "
            f"MOM:{s['avg_mom']:>5.1f}  "
            f"RS:{s['avg_rs']:>5.1f}  "
            f"({tickers_str})"
        )
    return rows


# ── Main report ────────────────────────────────────────────────────────────────

def send_report(results: list, trends: dict, today: str, top_sectors: list | None = None):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Group by quadrant
    groups: dict = {q: [] for q in QUADRANT_ORDER}
    for item in results:
        tech = item["technical"]
        q = classify(tech["rs_rating"], tech["rs_momentum"])
        if q in groups:
            groups[q].append({
                "ticker":          item["ticker"],
                "sector":          item.get("sector", ""),
                "rs_rating":       tech["rs_rating"],
                "rs_momentum":     tech["rs_momentum"],
                "stretch_factor":  tech.get("stretch_factor", 0),
                "volume_ratio":    tech.get("volume_ratio", 0),
                "proximity_52w":   tech.get("proximity_52w", 0),
                "tightness_score": tech.get("tightness_score", 0),
            })

    total = sum(len(v) for v in groups.values())
    sector_note = f"  |  Sectors: {', '.join(top_sectors)}" if top_sectors else ""

    # ── Create forum thread ───────────────────────────────────────────────────
    thread_id = _create_thread(
        thread_name=f"RS Report · {today}",
        content=(
            f"📊 **Thai RS Report** — {date_str}\n"
            f"🔎 {total} stocks above SMA50{sector_note}\n"
            f"🔥 = Vol ≥1.5x  ⭐ = 52W High 95%+  📍 = 52W High 85%+  ☑️ = Tight Base  ❌ = Overstretched STR>7"
        ),
    )

    # ── Scatter chart ─────────────────────────────────────────────────────────
    try:
        chart_bytes = build_scatter_chart(results, today)
        _post_file(f"rs_scatter_{today}.png", chart_bytes,
                   content="📈 RS Rating vs Momentum", thread_id=thread_id)
    except Exception as e:
        print(f"  ⚠ Chart failed: {e}")

    # ── Sector rotation ───────────────────────────────────────────────────────
    sector_rows = _sector_table(results)
    _send_chunked("🏭 **Sector Rotation (Top 10 by Avg RS)**", sector_rows, thread_id)

    # ── Quadrant tables ───────────────────────────────────────────────────────
    for q in QUADRANT_ORDER:
        items = sorted(groups[q], key=lambda x: -x["rs_momentum"])
        if not items:
            continue
        header = f"{QUADRANT_EMOJI[q]} **{q.upper()}** — {len(items)} stocks"
        lines  = [_stock_row(**i) for i in items]
        _send_chunked(header, lines, thread_id)

    # ── TradingView watchlist ─────────────────────────────────────────────────
    try:
        wl_bytes = build_tradingview_watchlist(results)
        _post_file(
            f"watchlist_{today}.txt", wl_bytes,
            content="📋 **TradingView Watchlist** — import via Watchlist → Import",
            thread_id=thread_id,
        )
    except Exception as e:
        print(f"  ⚠ Watchlist failed: {e}")

    # ── Trend alerts ──────────────────────────────────────────────────────────
    _post("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📈 **Trend Alerts**", thread_id)

    if trends["entries"]:
        lines = [_stock_row(**e) for e in trends["entries"]]
        _send_chunked(f"🆕 **New Entries** — {len(trends['entries'])} stocks", lines, thread_id)

    if trends["exits"]:
        tickers = ", ".join(trends["exits"])
        _post(f"🚪 **Exits**: {tickers}", thread_id)

    if trends["momentum_streak"]:
        lines = [_streak_row(**s) for s in trends["momentum_streak"]]
        _send_chunked(
            f"🔥 **RS Momentum Rising ≥3 Days** — {len(trends['momentum_streak'])} stocks",
            lines, thread_id,
        )

    if trends["quadrant_changes"]:
        lines = [_change_row(**c) for c in trends["quadrant_changes"]]
        _send_chunked(
            f"🔄 **Quadrant Changes** — {len(trends['quadrant_changes'])} stocks",
            lines, thread_id,
        )

    if trends["threshold_crossings"]:
        lines = [_crossing_row(**c) for c in trends["threshold_crossings"]]
        _send_chunked(
            f"⚡ **Crossed Threshold ({THRESHOLD})** — {len(trends['threshold_crossings'])} events",
            lines, thread_id,
        )

    _post("✅ **End of report**", thread_id)