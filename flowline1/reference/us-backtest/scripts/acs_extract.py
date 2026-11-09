"""Extract ACS 2015-2019 5-year variables for ZCTAs (sumlevel 860) and counties (050)
from the Census Summary File (sequence-based) bulk files.
usage: python -I acs_extract.py <acs_dir> <out_dir>
"""
import sys, os
import pandas as pd

acs_dir, out_dir = sys.argv[1], sys.argv[2]
x = os.path.join(acs_dir, "x")

geo = pd.read_csv(os.path.join(acs_dir, "g20195us.csv"), header=None, dtype=str, encoding="latin-1")
geo = geo[[2, 3, 4, 48]].rename(columns={2: "sumlev", 3: "comp", 4: "logrecno", 48: "geoid"})
geo = geo[(geo.comp == "00") & (geo.sumlev.isin(["860", "050"]))]

# (sequence, start position of table (1-based col), table) -> needed line numbers
SPEC = {
    "B01001": ("0001", 7, [1] + list(range(8, 15)) + list(range(32, 39))),
    "B08301": ("0027", 157, [1, 3, 10, 19, 21]),
    "B15003": ("0042", 125, [1, 22, 23, 24, 25]),
    "B19013": ("0058", 177, [1]),
    "B23025": ("0078", 38, [1, 2, 4]),
}
frames = []
for tab, (seq, start, lines) in SPEC.items():
    e = pd.read_csv(os.path.join(x, f"e20195us{seq}000.txt"), header=None, dtype=str, encoding="latin-1")
    cols = {start - 1 + (ln - 1): f"{tab}_{ln:03d}" for ln in lines}
    sub = e[[5] + list(cols)].rename(columns={5: "logrecno", **cols})
    sub = sub.set_index("logrecno")
    frames.append(sub.apply(pd.to_numeric, errors="coerce"))
acs = pd.concat(frames, axis=1).reset_index()
acs = geo.merge(acs, on="logrecno", how="left")

out = pd.DataFrame({"sumlev": acs.sumlev, "geoid": acs.geoid.str.split("US").str[1]})
pop = acs.B01001_001
out["pop"] = pop
m = lambda a, b: acs[[f"B01001_{i:03d}" for i in range(a, b + 1)]].sum(axis=1)
out["sh_age25_44"] = (m(11, 14) + m(35, 38)) / pop
out["sh_age20_34"] = (m(8, 12) + m(32, 36)) / pop
w = acs.B08301_001
out["workers"] = w
out["sh_drive_alone"] = acs.B08301_003 / w
out["sh_transit"] = acs.B08301_010 / w
out["sh_walk"] = acs.B08301_019 / w
out["sh_wfh"] = acs.B08301_021 / w
out["sh_bachelor_plus"] = acs[["B15003_022", "B15003_023", "B15003_024", "B15003_025"]].sum(axis=1) / acs.B15003_001
mhi = acs.B19013_001
out["median_hh_income"] = mhi.where(mhi > 0)
out["emp_pop_ratio"] = acs.B23025_004 / acs.B23025_001
out = out.replace([float("inf"), -float("inf")], float("nan"))
os.makedirs(out_dir, exist_ok=True)
out[out.sumlev == "860"].drop(columns="sumlev").rename(columns={"geoid": "zip"}).to_csv(os.path.join(out_dir, "acs2019_zcta.csv"), index=False)
out[out.sumlev == "050"].drop(columns="sumlev").rename(columns={"geoid": "fips"}).to_csv(os.path.join(out_dir, "acs2019_county.csv"), index=False)
print(out.groupby("sumlev").size(), out.describe().T.to_string())
