"""Build the test documents from flat-XML ODF written by Python.

  pricing-sheet.ods  Item / Amount sheet with a Total row (=SUM formula)
  proposal-172.odp   11 slides; slide 6 "Investment" has a 4-row table with
                     labels filled and amount cells empty

Flat .fods/.fodp are written locally, pushed to the desk container, converted
there with `soffice --headless --convert-to`, copied to /config/Documents on the
container and back into executor/assets/.

    uv run python assets/make_assets.py [--container desk1]
"""
from __future__ import annotations

import argparse
import os
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

ITEMS = [("Memberships, 120 seats", 2600), ("Lunchtime classes, 8 / mo", 1150), ("Onboarding week", 540)]
TOTAL = sum(a for _, a in ITEMS)  # 4290
FONT = "DejaVu Sans"  # Instrument Sans is not installed in the image; DejaVu Sans is.

# Proposal variants for the six-desk wall (inputs.proposal). 172 is the original and stays byte-identical.
VARIANTS = {
    172: {"client": "Halden Logistics", "staff": 120, "items": ITEMS, "blurb": "Corporate wellness programme for Halden Logistics",
          "sheet": "pricing-sheet.ods", "deck": "proposal-172.odp"},
    171: {"client": "Harbor Ridge Clinic", "staff": 60,
          "items": [("Physio sessions, 60", 3900), ("Staff wellness classes, 6 / mo", 1320), ("Ergonomics audit", 780)],
          "blurb": "Staff wellness and physio programme for Harbor Ridge Clinic", "sheet": "pricing-sheet-171.ods", "deck": "proposal-171.odp"},
    173: {"client": "Kickoff Coaching", "staff": 45,
          "items": [("Team memberships, 45", 1750), ("Nutrition workshops, 4 / mo", 920), ("Opening-week trainers", 610)],
          "blurb": "Team fitness programme for Kickoff Coaching", "sheet": "pricing-sheet-173.ods", "deck": "proposal-173.odp"},
}


def variant(n: int | None) -> dict:
    v = VARIANTS.get(int(n or 172))
    if v is None:
        raise KeyError(f"no proposal variant {n}; have {sorted(VARIANTS)}")
    return {"n": int(n or 172), **v, "total": sum(a for _, a in v["items"])}

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
      'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
      'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
      'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
      'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" '
      'office:version="1.3"')


def fods(items=ITEMS) -> str:
    total = sum(a for _, a in items)

    def row(label, cell):
        return (f'<table:table-row table:style-name="ro1"><table:table-cell office:value-type="string">'
                f'<text:p>{escape(label)}</text:p></table:table-cell>{cell}</table:table-row>')

    def money(v, formula=None):
        f = f' table:formula="{formula}"' if formula else ""
        return (f'<table:table-cell{f} table:style-name="ce1" office:value-type="currency" office:currency="USD" '
                f'office:value="{v}"><text:p>${v:,}</text:p></table:table-cell>')

    rows = [f'<table:table-row table:style-name="ro1"><table:table-cell table:style-name="ceh" office:value-type="string"><text:p>Item</text:p></table:table-cell>'
            f'<table:table-cell table:style-name="ceh" office:value-type="string"><text:p>Amount</text:p></table:table-cell></table:table-row>']
    for label, amt in items:
        rows.append(row(label, money(amt)))
    rows.append(row("Total", money(total, "of:=SUM([.B2:.B4])")))
    seats = [f'<table:table-row><table:table-cell office:value-type="string"><text:p>{escape(a)}</text:p></table:table-cell>'
             f'<table:table-cell office:value-type="float" office:value="{b}"><text:p>{b}</text:p></table:table-cell></table:table-row>'
             for a, b in [("Club", "Seats"), ("Downtown", 60), ("Mueller", 40), ("South Lamar", 20)]]
    seats[0] = seats[0].replace('office:value-type="float" office:value="Seats"', 'office:value-type="string"')
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document {NS} office:mimetype="application/vnd.oasis.opendocument.spreadsheet">
<office:font-face-decls><style:font-face style:name="{FONT}" svg:font-family="'{FONT}'"/></office:font-face-decls>
<office:automatic-styles>
 <number:currency-style style:name="N1"><number:currency-symbol number:language="en" number:country="US">$</number:currency-symbol>
  <number:number number:decimal-places="0" number:min-integer-digits="1" number:grouping="true"/></number:currency-style>
 <style:style style:name="co1" style:family="table-column"><style:table-column-properties style:column-width="6.2cm"/></style:style>
 <style:style style:name="co2" style:family="table-column"><style:table-column-properties style:column-width="3.2cm"/></style:style>
 <style:style style:name="ro1" style:family="table-row"><style:table-row-properties style:row-height="0.55cm"/></style:style>
 <style:style style:name="ce1" style:family="table-cell" style:data-style-name="N1"><style:text-properties style:font-name="{FONT}" fo:font-size="11pt"/></style:style>
 <style:style style:name="ceh" style:family="table-cell"><style:text-properties style:font-name="{FONT}" fo:font-size="11pt" fo:font-weight="bold"/></style:style>
</office:automatic-styles>
<office:body><office:spreadsheet>
<table:table table:name="Pricing">
<table:table-column table:style-name="co1"/><table:table-column table:style-name="co2"/>
{''.join(rows)}
</table:table>
<table:table table:name="Seats">
<table:table-column table:style-name="co1"/><table:table-column table:style-name="co2"/>
{''.join(seats)}
</table:table>
</office:spreadsheet></office:body></office:document>
'''


SLIDES = ["Proposal #172", "About Northwind Fitness", "What Halden asked for", "Our approach",
          "Programme", "Investment", "Timeline", "Team", "Results elsewhere", "Terms", "Next steps"]


def slides_for(v: dict) -> list[str]:
    short = v["client"].split()[0]
    return [f"Proposal #{v['n']}", "About Northwind Fitness", f"What {short} asked for", "Our approach",
            "Programme", "Investment", "Timeline", "Team", "Results elsewhere", "Terms", "Next steps"]


def fodp(v: dict | None = None) -> str:
    v = v or variant(172)
    items, slides = v["items"], slides_for(v)
    W, H = 28.0, 15.75  # cm, 16:9
    eyebrow = f"PROPOSAL #{v['n']} · {v['client'].upper()}, {v['staff']} STAFF"
    footer = "NORTHWIND FITNESS"

    def textbox(x, y, w, h, text, pstyle):
        return (f'<draw:frame draw:style-name="gr1" svg:width="{w}cm" svg:height="{h}cm" svg:x="{x}cm" svg:y="{y}cm">'
                f'<draw:text-box><text:p text:style-name="{pstyle}">{escape(text)}</text:p></draw:text-box></draw:frame>')

    pages = []
    for i, title in enumerate(slides, start=1):
        body = [textbox(2.0, 1.2, 24.0, 0.9, eyebrow, "P_eyebrow"),
                textbox(2.0, 2.6, 24.0, 2.0, title, "P_title"),
                textbox(2.0, 14.3, 12.0, 0.8, footer, "P_footer"),
                textbox(24.0, 14.3, 2.0, 0.8, str(i), "P_num")]
        if title == "Investment":
            rows = []
            for label, _ in items:
                rows.append(f'<table:table-row table:style-name="ro1"><table:table-cell table:style-name="ce_l">'
                            f'<text:p text:style-name="P_cell">{escape(label)}</text:p></table:table-cell>'
                            f'<table:table-cell table:style-name="ce_r"><text:p text:style-name="P_cell_r"/></table:table-cell></table:table-row>')
            rows.append('<table:table-row table:style-name="ro1"><table:table-cell table:style-name="ce_lb">'
                        '<text:p text:style-name="P_cell_b">Total</text:p></table:table-cell>'
                        '<table:table-cell table:style-name="ce_rb"><text:p text:style-name="P_cell_rb"/></table:table-cell></table:table-row>')
            body.append(f'<draw:frame draw:style-name="gr_tbl" svg:width="22cm" svg:height="7.2cm" svg:x="3cm" svg:y="5.6cm">'
                        f'<table:table table:style-name="ta1"><table:table-column table:style-name="co_l"/>'
                        f'<table:table-column table:style-name="co_r"/>{"".join(rows)}</table:table></draw:frame>')
        elif i == 1:
            body.append(textbox(2.0, 5.2, 24.0, 1.2, v["blurb"], "P_body"))
        else:
            body.append(textbox(2.0, 5.2, 24.0, 1.2, f"Slide {i} of {len(slides)} — placeholder text for the storyboard.", "P_body"))
        pages.append(f'<draw:page draw:name="page{i}" draw:style-name="dp1" draw:master-page-name="Default">{"".join(body)}</draw:page>')

    def para(name, size, color="#111111", weight="normal", align="start", spacing="0"):
        return (f'<style:style style:name="{name}" style:family="paragraph"><style:paragraph-properties fo:text-align="{align}"/>'
                f'<style:text-properties style:font-name="{FONT}" fo:font-size="{size}pt" fo:color="{color}" fo:font-weight="{weight}" fo:letter-spacing="{spacing}"/></style:style>')

    cell = lambda name, align, weight="normal": (  # noqa: E731
        f'<style:style style:name="{name}" style:family="table-cell"><style:graphic-properties draw:fill="none" '
        f'fo:border-bottom="0.03cm solid #d9d9d9" fo:border-top="none" fo:border-left="none" fo:border-right="none" fo:padding="0.25cm"/>'
        f'<style:paragraph-properties fo:text-align="{align}"/><style:text-properties style:font-name="{FONT}" fo:font-size="20pt" fo:font-weight="{weight}"/></style:style>')

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document {NS} office:mimetype="application/vnd.oasis.opendocument.presentation">
<office:font-face-decls><style:font-face style:name="{FONT}" svg:font-family="'{FONT}'"/></office:font-face-decls>
<office:styles>
 <style:default-style style:family="graphic"><style:text-properties style:font-name="{FONT}" fo:font-size="18pt"/></style:default-style>
</office:styles>
<office:automatic-styles>
 <style:page-layout style:name="PM1"><style:page-layout-properties fo:margin-top="0cm" fo:margin-bottom="0cm" fo:margin-left="0cm" fo:margin-right="0cm" fo:page-width="{W}cm" fo:page-height="{H}cm" style:print-orientation="landscape"/></style:page-layout>
 <style:style style:name="dp1" style:family="drawing-page"><style:drawing-page-properties draw:background-size="border" draw:fill="solid" draw:fill-color="#ffffff" presentation:background-visible="true" presentation:background-objects-visible="true" presentation:display-footer="false" presentation:display-page-number="false" presentation:display-date-time="false"/></style:style>
 <style:style style:name="gr1" style:family="graphic"><style:graphic-properties draw:stroke="none" draw:fill="none" draw:auto-grow-height="true" fo:min-height="0.5cm" fo:padding-top="0.1cm" fo:padding-bottom="0.1cm" fo:padding-left="0.1cm" fo:padding-right="0.1cm" draw:textarea-vertical-align="top"/></style:style>
 <style:style style:name="gr_tbl" style:family="graphic"><style:graphic-properties draw:stroke="none" draw:fill="none"/></style:style>
 <style:style style:name="ta1" style:family="table"><style:table-properties style:width="22cm" fo:background-color="#ffffff"/></style:style>
 <style:style style:name="co_l" style:family="table-column"><style:table-column-properties style:column-width="15cm"/></style:style>
 <style:style style:name="co_r" style:family="table-column"><style:table-column-properties style:column-width="7cm"/></style:style>
 <style:style style:name="ro1" style:family="table-row"><style:table-row-properties style:row-height="1.8cm"/></style:style>
 {cell("ce_l", "start")}{cell("ce_r", "end")}{cell("ce_lb", "start", "bold")}{cell("ce_rb", "end", "bold")}
 {para("P_eyebrow", 11, "#6b6b6b", spacing="0.05cm")}
 {para("P_title", 40, "#111111", "bold")}
 {para("P_body", 18, "#333333")}
 {para("P_footer", 11, "#6b6b6b", spacing="0.05cm")}
 {para("P_num", 11, "#6b6b6b", align="end")}
 {para("P_cell", 20)}{para("P_cell_r", 20, align="end")}{para("P_cell_b", 20, weight="bold")}{para("P_cell_rb", 20, weight="bold", align="end")}
</office:automatic-styles>
<office:master-styles>
 <style:master-page style:name="Default" style:page-layout-name="PM1" draw:style-name="dp1"/>
</office:master-styles>
<office:body><office:presentation>
{''.join(pages)}
</office:presentation></office:body></office:document>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="desk1")
    ap.add_argument("--local-only", action="store_true", help="only write the flat XML files")
    ap.add_argument("--proposal", type=int, default=172, help="variant: 172 (default, original files), 171, 173")
    args = ap.parse_args()

    v = variant(args.proposal)
    sheet_name, deck_name = v["sheet"], v["deck"]
    fods_path = os.path.join(HERE, sheet_name.replace(".ods", ".fods"))
    fodp_path = os.path.join(HERE, deck_name.replace(".odp", ".fodp"))
    open(fods_path, "w", encoding="utf-8").write(fods(v["items"]))
    open(fodp_path, "w", encoding="utf-8").write(fodp(v))
    print("wrote", fods_path, fodp_path)
    if args.local_only:
        return

    from desktop import DockerDesktop
    d = DockerDesktop(args.container)
    d.sh("mkdir -p /tmp/assets /config/Documents")
    fods_name, fodp_name = os.path.basename(fods_path), os.path.basename(fodp_path)
    d.put_file(fods_path, f"/tmp/assets/{fods_name}")
    d.put_file(fodp_path, f"/tmp/assets/{fodp_name}")
    # A separate user profile so the headless conversion never talks to a running GUI instance.
    prof = "-env:UserInstallation=file:///tmp/lo_headless_profile"
    for src, fmt in ((fods_name, "ods"), (fodp_name, "odp")):
        rc, out = d.sh(f"cd /tmp/assets && soffice {prof} --headless --convert-to {fmt} --outdir /tmp/assets {src} 2>&1", timeout=180)
        print(fmt, rc, out.strip()[-300:])
        if rc != 0:
            raise SystemExit(f"conversion of {src} failed")
    rc, out = d.sh(f"cp /tmp/assets/{sheet_name} /tmp/assets/{deck_name} /config/Documents/ && ls -la /config/Documents")
    print(out)
    for name in (sheet_name, deck_name):
        data = d.get_file(f"/config/Documents/{name}")
        open(os.path.join(HERE, name), "wb").write(data)
        print("fetched", name, len(data), "bytes")
    d.close()


if __name__ == "__main__":
    main()
