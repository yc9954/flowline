"""Build ZIP-level establishment panels from Census ZIP Code Business Patterns (ZBP) bulk files.
usage: python -I prep_zip.py <cbp_x_dir> <out_dir>
Output: zbp_<year>.parquet-like CSVs with one row per ZIP: totals + establishment counts for
selected NAICS + 2-digit sectors. Cells with <3 establishments are not published from 2017 on;
for comparability we apply the same <3 suppression to 2014 (est<3 -> missing).
"""
import sys, os
import pandas as pd

xdir, out_dir = sys.argv[1], sys.argv[2]
os.makedirs(out_dir, exist_ok=True)

TARGETS = ["713940", "621111", "722515"]
EXTRA6 = ["722511", "722513", "445110", "812112", "812113", "611620", "713990", "621210",
          "621340", "446110", "448140", "451110", "531110", "541211", "561720", "812199"]
SIX = TARGETS + EXTRA6

for yy in ["14", "17", "20", "23"]:
    d = pd.read_csv(os.path.join(xdir, f"zbp{yy}detail.txt"), usecols=["zip", "naics", "est"],
                    dtype={"zip": str, "naics": str}, encoding="latin-1")
    d = d[d.est >= 3]  # harmonise suppression rule across years
    two = d[d.naics.str.match(r"^\d\d----$")].copy()
    two["col"] = "s" + two.naics.str[:2]
    w2 = two.pivot_table(index="zip", columns="col", values="est", aggfunc="sum")
    six = d[d.naics.isin(SIX)].copy()
    six["col"] = "n" + six.naics
    w6 = six.pivot_table(index="zip", columns="col", values="est", aggfunc="sum")
    for n in SIX:
        if "n" + n not in w6:
            w6["n" + n] = float("nan")
    t = pd.read_csv(os.path.join(xdir, f"zbp{yy}totals.txt"), dtype={"zip": str}, encoding="latin-1")
    t.columns = [c.lower() for c in t.columns]
    keep = ["zip", "emp", "ap", "est"] + [c for c in ["city", "stabbr", "cty_name"] if c in t]
    t = t[keep].rename(columns={"emp": "tot_emp", "ap": "tot_ap", "est": "tot_est"}).set_index("zip")
    out = t.join(w2, how="left").join(w6, how="left")
    out.to_csv(os.path.join(out_dir, f"zbp20{yy}.csv"))
    print(yy, out.shape, {n: int(out["n" + n].sum()) for n in TARGETS})
