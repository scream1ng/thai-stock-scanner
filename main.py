import json
import os
from datetime import datetime

from scanner import run_scan
from tracker import load_history, analyze_trends
from reporter import send_report


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data", exist_ok=True)

    # 1. Scan market
    print("─" * 50)
    print(f"Running scan for {today}...")
    results = run_scan()

    # 2. Save today's snapshot
    snapshot_path = f"data/{today}.json"
    with open(snapshot_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} stocks → {snapshot_path}")

    # 3. Load history & detect trends
    print("Analysing trends...")
    history = load_history("data", days=6)
    trends = analyze_trends(history, today)

    # 4. Send Discord report
    print("Sending report...")
    send_report(results, trends, today)
    print("Done ✅")


if __name__ == "__main__":
    main()
