"""Vendor quote PDFs for the packet skills (proposal_packet, reconcile_quotes).

Three vendors quote the three line items of pricing-sheet.ods.  Each run gets
fresh PDFs: two quotes equal the sheet, exactly one differs by a plausible delta
(5-20 %, rounded to $10).  The truth (which vendor, from what to what, the new
total) is returned with the PDF bytes and written by the skill to
data/runs/<id>/truth.json so the run can be verified without the model.

    uv run python assets/quotes.py --seed 7 --out /tmp/quotes     # preview locally
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import random
import sys
from dataclasses import asdict, dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# (sheet label, vendor, vendor address, quote line description)
VENDORS = [
    ("Memberships, 120 seats", "Downtown Athletic Club", "412 Congress Ave, Austin TX 78701",
     "Corporate memberships, 120 seats, 12 months"),
    ("Lunchtime classes, 8 / mo", "MoveWell Studio", "2100 S Lamar Blvd, Austin TX 78704",
     "On-site lunchtime classes, 8 per month"),
    ("Onboarding week", "Kickoff Coaching", "900 E 6th St, Austin TX 78702",
     "Onboarding week: assessments, kick-off sessions, plans"),
]
VENDORS_BY_PROPOSAL = {
    172: VENDORS,
    171: [("Physio sessions, 60", "Lakeside Physio Partners", "1801 Lavaca St, Austin TX 78701", "Physiotherapy sessions, block of 60"),
          ("Staff wellness classes, 6 / mo", "MoveWell Studio", "2100 S Lamar Blvd, Austin TX 78704", "On-site staff wellness classes, 6 per month"),
          ("Ergonomics audit", "Upright Ergonomics", "515 Congress Ave, Austin TX 78701", "Workplace ergonomics audit, clinic floors and front desk")],
    173: [("Team memberships, 45", "Downtown Athletic Club", "412 Congress Ave, Austin TX 78701", "Team memberships, 45 seats, 12 months"),
          ("Nutrition workshops, 4 / mo", "Greenplate Nutrition", "1100 E Cesar Chavez St, Austin TX 78702", "Nutrition workshops, 4 per month"),
          ("Opening-week trainers", "Northstar Trainers Co-op", "3300 Guadalupe St, Austin TX 78705", "Opening-week trainers, 5 days on site")],
}
CLIENT_BY_PROPOSAL = {172: ("Halden Logistics", 120), 171: ("Harbor Ridge Clinic", 60), 173: ("Kickoff Coaching", 45)}
CUSTOMER = "Northwind Fitness"
PROPOSAL = "Proposal #172 (Halden Logistics, 120 staff)"


def vendors_for(proposal: int | None) -> list[tuple[str, str, str, str]]:
    return VENDORS_BY_PROPOSAL[int(proposal or 172)]


def proposal_line(proposal: int | None) -> str:
    client, staff = CLIENT_BY_PROPOSAL[int(proposal or 172)]
    return f"Proposal #{int(proposal or 172)} ({client}, {staff} staff)"
DELTAS = (0.05, 0.08, 0.10, 0.12, 0.15, 0.20)


@dataclass
class Quote:
    file: str
    vendor: str
    item: str
    amount: int          # what the vendor quotes
    sheet_amount: int    # what the sheet says today
    differs: bool
    quote_no: str
    date: str


def quote_filename(vendor: str, item: str) -> str:
    short = item.split(",")[0].lower()
    return f"{vendor} - {short} quote.pdf"


def plan_quotes(sheet_items: list[tuple[str, int]], seed: int | None = None, changed_index: int | None = None,
                all_equal: bool = False, proposal: int = 172) -> dict:
    """Decide the amounts. Returns the truth dict (no PDFs yet)."""
    rng = random.Random(seed)
    vendors = vendors_for(proposal)
    by_label = {label: amt for label, amt in sheet_items}
    if changed_index is None:
        changed_index = rng.randrange(len(vendors))
    today = dt.date.today()
    quotes: list[Quote] = []
    changed = None
    for i, (label, vendor, _addr, _desc) in enumerate(vendors):
        sheet_amt = by_label.get(label)
        if sheet_amt is None:
            raise ValueError(f"sheet has no row {label!r}; rows are {list(by_label)}")
        amt = sheet_amt
        differs = (i == changed_index) and not all_equal
        if differs:
            pct = rng.choice(DELTAS) * rng.choice((-1, 1))
            amt = int(round(sheet_amt * (1 + pct) / 10.0)) * 10
            if amt == sheet_amt:
                amt = sheet_amt + (10 if pct > 0 else -10)
            changed = {"index": i, "vendor": vendor, "item": label, "from": sheet_amt, "to": amt, "delta": amt - sheet_amt}
        quotes.append(Quote(file=quote_filename(vendor, label), vendor=vendor, item=label, amount=amt, sheet_amount=sheet_amt,
                            differs=differs, quote_no=f"Q-{today.year}-{rng.randrange(1000, 9999)}",
                            date=(today - dt.timedelta(days=rng.randrange(1, 9))).isoformat()))
    sheet_after = [(label, next(q.amount for q in quotes if q.item == label)) for label, _ in sheet_items]
    return {
        "seed": seed,
        "proposal": int(proposal),
        "sheet_before": [list(x) for x in sheet_items],
        "total_before": sum(a for _, a in sheet_items),
        "quotes": [asdict(q) for q in quotes],
        "changed": changed,
        "sheet_after": [list(x) for x in sheet_after],
        "total_after": sum(a for _, a in sheet_after),
    }


def render_quote(q: dict, addr: str, desc: str, proposal: int = 172) -> bytes:
    """One-page Letter quote: vendor letterhead, one line item, a big 'Total quoted' amount."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"{q['vendor']} quote {q['quote_no']}")
    W, H = letter
    L = 0.9 * inch
    y = H - 1.0 * inch
    c.setFont("Helvetica-Bold", 24)
    c.drawString(L, y, q["vendor"])
    c.setFont("Helvetica", 10)
    c.setFillGray(0.35)
    c.drawString(L, y - 16, addr)
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(W - L, y, "QUOTE")
    c.setFont("Helvetica", 10)
    c.drawRightString(W - L, y - 16, f"No. {q['quote_no']}   Date {q['date']}")
    c.drawRightString(W - L, y - 30, "Valid for 30 days")

    y -= 0.9 * inch
    c.setStrokeGray(0.8)
    c.line(L, y, W - L, y)
    y -= 0.4 * inch
    c.setFont("Helvetica", 11)
    c.drawString(L, y, f"Prepared for: {CUSTOMER}")
    c.drawString(L, y - 16, f"Reference: {proposal_line(proposal)}")

    y -= 0.9 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(L, y, "Description")
    c.drawRightString(W - L, y, "Amount")
    c.line(L, y - 6, W - L, y - 6)
    y -= 0.4 * inch
    c.setFont("Helvetica", 12)
    c.drawString(L, y, desc)
    c.drawRightString(W - L, y, f"${q['amount']:,}")
    y -= 0.35 * inch
    c.line(L, y, W - L, y)

    y -= 0.7 * inch
    c.setFont("Helvetica-Bold", 20)
    c.drawString(L, y, "Total quoted")
    c.setFont("Helvetica-Bold", 30)
    c.drawRightString(W - L, y - 2, f"${q['amount']:,}")

    y -= 1.2 * inch
    c.setFont("Helvetica", 10)
    c.setFillGray(0.35)
    c.drawString(L, y, "Terms: net 30 from signature. Prices in USD, taxes not included.")
    c.drawString(L, y - 14, f"Questions: accounts@{q['vendor'].lower().replace(' ', '')}.example")
    c.setFillGray(0)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_quotes(sheet_items: list[tuple[str, int]], seed: int | None = None, changed_index: int | None = None,
                all_equal: bool = False, proposal: int = 172) -> tuple[dict, dict[str, bytes]]:
    """→ (truth, {filename: pdf bytes})."""
    truth = plan_quotes(sheet_items, seed, changed_index, all_equal, proposal)
    files = {}
    for q, (_label, _vendor, addr, desc) in zip(truth["quotes"], vendors_for(proposal)):
        files[q["file"]] = render_quote(q, addr, desc, proposal)
    return truth, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "quotes-preview"))
    ap.add_argument("--proposal", type=int, default=172)
    args = ap.parse_args()
    from make_assets import variant
    truth, files = make_quotes(variant(args.proposal)["items"], args.seed, proposal=args.proposal)
    os.makedirs(args.out, exist_ok=True)
    for name, data in files.items():
        open(os.path.join(args.out, name), "wb").write(data)
    import json
    print(json.dumps(truth, indent=1))
    print("wrote", len(files), "PDFs to", args.out)


if __name__ == "__main__":
    main()
