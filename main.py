import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Parse args ────────────────────────────────────────────────────────────────
PREVIEW = "--preview" in sys.argv
MARKET  = "us"  if "--us"  in sys.argv else \
          "asx" if "--asx" in sys.argv or "--au" in sys.argv else "th"

os.environ["MARKET"] = MARKET  # set before importing config

from config import CFG
from scanner import run_scan
from tracker import load_history, analyze_trends, classify
from reporter import send_report
from news import generate_briefing


def _print_table(title, stocks):
    if not stocks:
        print(f"  (none)")
        return
    print(title)
    for s in stocks:
        tech = s["technical"]
        ticker = s["ticker"].replace(".BK", "").replace(".AX", "")
        vol    = tech.get("volume_ratio",    0)
        prox   = tech.get("proximity_52w",   0)
        tight  = tech.get("tightness_score", 0)
        stretch= tech.get("stretch_factor",  0)
        vol_f  = "🔥" if vol   >= 1.5 else "  "
        prox_f = "⭐" if prox  >= 95  else "📍" if prox >= 85 else "  "
        tight_f= "☑️" if tight >= 70  else "  "
        str_f  = "❌" if stretch >= 7  else "  "
        print(
            f"  {ticker:<12} "
            f"RS:{tech['rs_rating']:>5.1f}  "
            f"MOM:{tech['rs_momentum']:>5.1f}  "
            f"STR:{stretch:>5.2f}{str_f} "
            f"VOL:{vol:>4.1f}x{vol_f} "
            f"52W:{prox:>5.1f}%{prox_f} "
            f"TIGHT:{tight:>4.0f}{tight_f}  "
            f"{str(s.get('sector',''))[:18]}"
        )


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    data_dir = f"data/{MARKET}"
    os.makedirs(data_dir, exist_ok=True)
    snapshot_path = f"{data_dir}/{today}.json"

    print(f"Market: {CFG['name']}  |  {'PREVIEW MODE' if PREVIEW else 'LIVE MODE'}")
    print("─" * 50)

    # ── Load or scan ───────────────────────────────────────────────────────────
    if os.path.exists(snapshot_path):
        print(f"Found today's snapshot — loading {snapshot_path}")
        with open(snapshot_path) as f:
            all_results = json.load(f)
        print(f"  → {len(all_results)} stocks loaded from file")
    else:
        print(f"No snapshot for {today} — running full scan...")
        all_results = run_scan()
        with open(snapshot_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"  Saved {len(all_results)} stocks → {snapshot_path}")

    # ── Trends ────────────────────────────────────────────────────────────────
    print("Analysing trends...")
    history = load_history(data_dir, days=6)
    trends  = analyze_trends(history, today)

    # ── Briefing (Gemini with web search) ────────────────────────────────────
    print("Generating market briefing...")
    briefing = generate_briefing(all_results, today)

    # ── Preview: print everything to terminal ─────────────────────────────────
    if PREVIEW:
        # Group by quadrant
        groups = {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []}
        for s in all_results:
            tech = s["technical"]
            q = classify(tech["rs_rating"], tech["rs_momentum"])
            groups[q].append(s)

        print("\n" + "=" * 60)
        print(f"📊 {CFG['name']} RS Report — {today}")
        print(f"🔎 {len(all_results)} stocks above SMA50")


        if briefing:
            print("\n" + "─" * 40)
            print(briefing)

        for label, emoji in [("Leading","🟢"), ("Improving","🔵"), ("Weakening","🟠")]:
            grp = sorted(groups[label], key=lambda x: -x["technical"]["rs_momentum"])
            print(f"\n{emoji} {label.upper()} — {len(grp)} stocks")
            _print_table("", grp)

        print("=" * 60)
        print("(Preview mode — nothing sent to Discord)")
        return

    # ── Live: send to Discord ─────────────────────────────────────────────────
    print("Sending report...")
    send_report(all_results, trends, today,
                briefing=briefing)
    print("Done ✅")


if __name__ == "__main__":
    main()