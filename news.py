import time




# ── Gemini briefing ────────────────────────────────────────────────────────────

import os
from collections import defaultdict

try:
    import google.generativeai as genai
    _api_key = os.getenv("GEMINI_API_KEY")
    if _api_key:
        genai.configure(api_key=_api_key)
        _model = None
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite"]:
            try:
                _model = genai.GenerativeModel(model_name)
                _model_name = model_name
                break
            except Exception:
                continue
    else:
        _model = None
        _model_name = None
except ImportError:
    _model = None
    _model_name = None


def _summarize(stocks: list) -> dict:
    quadrants   = {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []}
    sector_data = defaultdict(list)

    for s in stocks:
        tech   = s["technical"]
        rs, mom = tech["rs_rating"], tech["rs_momentum"]
        ticker = s["ticker"].replace(".BK", "")

        if   rs >= 75 and mom >= 75: q = "Leading"
        elif rs <  75 and mom >= 75: q = "Improving"
        elif rs >= 75 and mom <  75: q = "Weakening"
        else:                        q = "Lagging"

        entry = {
            "ticker": ticker, "rs": rs, "mom": mom,
            "vol":   tech.get("volume_ratio",    0),
            "prox":  tech.get("proximity_52w",   0),
            "tight": tech.get("tightness_score", 0),
            "str":   tech.get("stretch_factor",  0),
        }
        quadrants[q].append(entry)
        sector_data[s.get("sector", "Unknown")].append(entry)

    def top(group, n=5):
        return sorted(
            [s for s in group if s["vol"] >= 1.0 and s["str"] < 7],
            key=lambda x: -x["mom"]
        )[:n]

    stretched = sorted(
        [s for s in quadrants["Leading"] + quadrants["Improving"] if s["str"] >= 7],
        key=lambda x: -x["str"]
    )

    sector_ranked = []
    for sec, stks in sector_data.items():
        if len(stks) < 2:
            continue
        avg_mom     = round(sum(s["mom"] for s in stks) / len(stks), 1)
        top_tickers = [s["ticker"] for s in sorted(stks, key=lambda x: -x["mom"])[:4]]
        sector_ranked.append((sec, avg_mom, top_tickers))
    sector_ranked.sort(key=lambda x: -x[1])

    return {
        "counts":        {k: len(v) for k, v in quadrants.items()},
        "top_leading":   top(quadrants["Leading"]),
        "top_improving": top(quadrants["Improving"]),
        "overstretched": stretched,
        "top_sectors":   sector_ranked[:5],
    }


def _build_prompt(summary: dict, date: str) -> str:

    def fmt(stocks, n=6):
        rows = []
        for s in stocks[:n]:
            flags = []
            if s["prox"] >= 95:   flags.append("AT 52W HIGH")
            elif s["prox"] >= 85: flags.append("NEAR 52W HIGH")
            if s["tight"] >= 70:  flags.append("TIGHT BASE")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            rows.append(
                f"  {s['ticker']:<12} RS:{s['rs']:>5.1f}  MOM:{s['mom']:>5.1f}  "
                f"VOL:{s['vol']:>4.1f}x  52W:{s['prox']:>5.1f}%  STR:{s['str']:>5.2f}{flag_str}"
            )
        return "\n".join(rows) or "  (none)"

    sectors   = "\n".join(
        f"  {s[0]:<30} MOM: {s[1]}  tickers: {', '.join(s[2])}"
        for s in summary["top_sectors"]
    )
    stretched = "\n".join(
        f"  {s['ticker']:<12} STR:{s['str']:>5.2f}  VOL:{s['vol']:>4.1f}x  52W:{s['prox']:>5.1f}%"
        for s in summary["overstretched"]
    ) or "  (none)"

    # Build sector context from top sectors
    sector_context = ""
    for sec, avg_mom, tickers in summary["top_sectors"][:5]:
        # Find stocks in this sector from leading/improving
        sec_stocks = [s for s in summary["top_leading"] + summary["top_improving"] if True]
        sector_context += f"- {sec}: MOM {avg_mom} | tickers: {', '.join(tickers)}\n"

    return f"""
คุณคือนักวิเคราะห์หุ้นอาวุโสที่ผสมการวิเคราะห์ทางเทคนิคกับข่าวเศรษฐกิจ
วันที่ {date}

กฎเด็ดขาด:
- ตอบเป็นภาษาไทยเท่านั้น
- ห้ามใช้ ** หรือ ## หรือ markdown ใดๆ ทั้งสิ้น
- ห้ามพูดถึง RSI, MACD, Overbought, Oversold
- ห้ามใช้ประโยคซ้ำกันระหว่างหุ้น
- ใช้ความรู้เกี่ยวกับแต่ละเซกเตอร์เพื่อสนับสนุนการวิเคราะห์
- ต้องใช้รูปแบบตัวอย่างด้านล่างเป๊ะทุกอย่าง ห้ามเพิ่มหัวข้อหรือเปลี่ยนโครงสร้าง
- ความยาวรวมทั้งหมดต้องไม่เกิน 1800 ตัวอักษร
- หุ้นในกลุ่ม Leading ให้แสดง RS, หุ้นในกลุ่ม Improving ให้แสดง MOM แทน RS เพราะ MOM สะท้อน momentum ระยะสั้นได้ดีกว่า

## ข้อมูลเทคนิค (คัดกรองเฉพาะหุ้นที่ราคา > SMA50)

Top Leading — VOL≥1.0x, STR<7:
{fmt(summary['top_leading'])}

Top Improving — VOL≥1.0x, STR<7:
{fmt(summary['top_improving'])}

Top Sectors by MOM:
{sector_context}
Overstretched — STR≥7 ห้ามแนะนำเด็ดขาด:
{stretched}

---

ตัวอย่างรูปแบบที่ต้องการ (ใช้โครงสร้างนี้เป๊ะ):

🌍 Macro & Sector Drive
* 🛢️ Energy & Refinery (RS 90+): UAE/คูเวตลดผลิต + ฮอร์มุซโดนปิด ดันค่าการกลั่นพุ่ง
   * Picks: PTTEP, SPRC, BCP
* 🚢 Logistics & Marine (RS 85+): ค่าระวางเรือ BDI ขยับแรงตามความเสี่ยงภูมิรัฐศาสตร์
   * Picks: SEAOIL, PSL, RCL
* 🏗️ Infrastructure (RS 98): งานประมูลรัฐ 5 แสนล้านเริ่มเดินเครื่อง Backlog แน่น
   * Picks: STECON, PYLON

🏆 Top Pick Stocks
1. THCOM (RS 91.5): 🛰️ จ่อส่งดาวเทียมดวงใหม่ + รุกตลาดอินเดียเต็มตัว
2. STECON (RS 98.0): 🏗️ เป้างานใหม่ปีนี้ 5 หมื่นล้าน การเมืองนิ่งหนุนโปรเจกต์ยักษ์
3. SEAOIL (RS 94.5): ⛽ วิ่งแรงตามราคาน้ำมัน + ค่าขนส่งทางเรือทำ High ในรอบปี
4. HANA (MOM 90.4): 🔬 รับอานิสงส์บาทอ่อน + ดีมานด์ชิป AI พุ่ง

⚠️ Avoid Today
* BIZ (STR 10.01) / MCOT (STR 8.39) — วิ่งไกลเกินฐาน ระวังแรงขายทำกำไร

---

ตอนนี้สร้างรายงานจริงสำหรับวันที่ {date} โดยใช้ข้อมูลเทคนิคที่ให้มา
- Macro & Sector Drive: 3 เซกเตอร์ แต่ละเซกเตอร์ 1 บรรทัดสั้น + Picks 2-3 ตัว
- Top Pick Stocks: 4 ตัวที่ดีที่สุด ห้ามใส่หุ้นจาก Overstretched
- Avoid Today: หุ้น STR >= 7 เท่านั้น
- ความยาวรวมทั้งหมดต้องไม่เกิน 1800 ตัวอักษร
- หุ้นในกลุ่ม Leading ให้แสดง RS, หุ้นในกลุ่ม Improving ให้แสดง MOM แทน RS เพราะ MOM สะท้อน momentum ระยะสั้นได้ดีกว่า

""".strip()


def _build_rotation_alert(summary: dict) -> str:
    """Build Rotation Alert section directly from data."""
    lines = ["Rotation Alert:"]
    for sec, avg_mom, tickers in summary["top_sectors"][:3]:
        lines.append(f"- {sec} MOM {avg_mom} — {', '.join(tickers)}")
    return "\n".join(lines)


def _build_avoid_today(summary: dict) -> str:
    """Build Avoid Today section directly from data."""
    if not summary["overstretched"]:
        return ""
    lines = ["Avoid Today:"]
    for s in summary["overstretched"]:
        lines.append(f"- {s['ticker']} STR {s['str']:.2f} — ราคาวิ่งไกลเกินฐาน ไม่คุ้มเสี่ยงไล่ราคา")
    return "\n".join(lines)


def generate_briefing(stocks: list, date: str) -> str:
    """Generate market briefing using Gemini with model fallback."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠ No GEMINI_API_KEY — skipping briefing")
        return ""

    summary = _summarize(stocks)
    prompt  = _build_prompt(summary, date)

    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            print(f"  Trying model: {model_name}")
            model    = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            print(f"  ✓ Briefing generated by {model_name}")
            return response.text.strip()[:1900]
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                print(f"  ⚠ {model_name} quota exceeded — trying next model")
                continue
            print(f"  ⚠ {model_name} failed: {e}")
            return ""

    print("  ⚠ All models quota exceeded — skipping briefing")
    return ""