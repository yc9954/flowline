"""County-level unit-economics backtest (County Business Patterns bulk files).
Outcome (test): employees per establishment and annual payroll per establishment of the target
NAICS in 2023, from features measured in 2020 (lag 2017). Model trained on 2017 features ->
2020 outcomes. Geography holdout: 5 folds over whole states.
Two tasks:
  existing : counties with >=3 target units in 2020 and 2023 (persistence baseline available)
  cold     : counties with <3 units in 2020 that had >=3 by 2023 (no own-industry history);
             model trained WITHOUT own-industry unit-economics features.
usage: python -I backtest_county.py <cbpco_x_dir> <popest_csv> <out_dir>
"""
import sys, os, json
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

xdir, pop_path, out_dir = sys.argv[1:4]
os.makedirs(out_dir, exist_ok=True)
TARGETS = {"713940": "fitness", "621111": "physicians", "722515": "coffee_snack"}
SIX = ["713940", "621111", "722515", "722511", "722513", "445110", "812112", "812113", "611620",
       "713990", "621210", "621340", "531110", "541211", "561720", "812199"]

pe = pd.read_csv(pop_path, encoding="latin-1", dtype={"STATE": str, "COUNTY": str})
pe = pe[pe.SUMLEV == 50]
pe["fips"] = pe.STATE + pe.COUNTY
pe = pe.set_index("fips")

C = {}
for y in [17, 20, 23]:
    d = pd.read_csv(os.path.join(xdir, f"cbp{y}co.txt"), usecols=["fipstate", "fipscty", "naics", "emp", "ap", "est"],
                    dtype={"fipstate": str, "fipscty": str, "naics": str}, encoding="latin-1")
    d["fips"] = d.fipstate + d.fipscty
    d = d[d.fipscty != "999"]
    C[2000 + y] = d

def wide(y):
    d = C[y]
    tot = d[d.naics == "------"].set_index("fips")[["emp", "ap", "est"]].add_prefix("tot_")
    s2 = d[d.naics.str.match(r"^\d\d----$")].assign(col=lambda v: "sector_" + v.naics.str[:2]) \
        .pivot_table(index="fips", columns="col", values="est", aggfunc="sum")
    s6 = d[d.naics.isin(SIX)]
    e6 = s6.pivot_table(index="fips", columns="naics", values="est").add_prefix("est_")
    m6 = s6.pivot_table(index="fips", columns="naics", values="emp").add_prefix("emp_")
    a6 = s6.pivot_table(index="fips", columns="naics", values="ap").add_prefix("ap_")
    return tot.join(s2).join(e6).join(m6).join(a6)

W = {y: wide(y) for y in C}

def build(y0, yl, y3, n):
    w0, wl, w3 = W[y0], W[yl], W[y3]
    idx = w0.index.intersection(w3.index).intersection(pe.index)
    f = pd.DataFrame(index=idx)
    pop = pe.loc[idx, f"POPESTIMATE{y0}"].astype(float)
    popl = pe.loc[idx, f"POPESTIMATE{min(yl, 2020)}"].astype(float)
    f["pop"] = pop; f["pop_growth_lag"] = pop / popl - 1
    f["jobs_per_resident"] = w0.loc[idx, "tot_emp"] / pop
    f["payroll_per_job"] = w0.loc[idx, "tot_ap"] / w0.loc[idx, "tot_emp"].replace(0, np.nan)
    f["estab_per_1k"] = w0.loc[idx, "tot_est"] / pop * 1e3
    f["estab_growth_lag"] = w0.loc[idx, "tot_est"] / wl.reindex(idx)["tot_est"] - 1
    for c in [c for c in w0.columns if c.startswith("sector_")]:
        f[c + "_per_1k"] = w0.loc[idx, c].fillna(0) / pop * 1e3
    for s in SIX:
        if s == n:
            continue
        f[f"est_{s}_per_100k"] = w0.reindex(idx)[f"est_{s}"].fillna(0) / pop * 1e5
    own0 = w0.reindex(idx)[[f"est_{n}", f"emp_{n}", f"ap_{n}"]]
    ownl = wl.reindex(idx)[[f"est_{n}", f"emp_{n}", f"ap_{n}"]]
    own3 = w3.reindex(idx)[[f"est_{n}", f"emp_{n}", f"ap_{n}"]]
    f["own_est_per_100k"] = own0[f"est_{n}"].fillna(0) / pop * 1e5
    f["own_est_change_lag"] = own0[f"est_{n}"].fillna(1) - ownl[f"est_{n}"].fillna(1)
    pers = pd.DataFrame(index=idx)
    pers["own_emp_per_est"] = own0[f"emp_{n}"] / own0[f"est_{n}"]
    pers["own_ap_per_est"] = own0[f"ap_{n}"] / own0[f"est_{n}"]
    lab = pd.DataFrame(index=idx)
    lab["present0"] = own0[f"est_{n}"].notna()
    lab["present3"] = own3[f"est_{n}"].notna()
    lab["emp_per_est"] = own3[f"emp_{n}"] / own3[f"est_{n}"]
    lab["ap_per_est"] = own3[f"ap_{n}"] / own3[f"est_{n}"]  # $1,000s
    lab = lab.replace(0, np.nan)  # 2017 'S' (suppressed) cells carry 0
    pers = pers.replace(0, np.nan)
    return f, pers, lab

def model():
    return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=300, max_leaf_nodes=15,
                                         min_samples_leaf=20, l2_regularization=1.0, random_state=0)

def evaluate(score, y):
    score = np.asarray(score, float); y = np.asarray(y, float)
    k = max(1, int(round(len(y) * 0.1)))
    top = y[np.argsort(-score, kind="mergesort")[:k]]
    return {"n": int(len(y)), "spearman": float(spearmanr(score, y).correlation),
            "top10_mean": float(top.mean()), "median": float(np.median(y)),
            "lift_top10_vs_median": float(top.mean() / np.median(y))}

states = sorted(pe.STATE.unique()); rng = np.random.default_rng(3); rng.shuffle(states)
fold_of = {s: i % 5 for i, s in enumerate(states)}
results = {}
for n, name in TARGETS.items():
    fA, pA, lA = build(2017, 2017, 2020, n)
    fB, pB, lB = build(2020, 2017, 2023, n)
    # 2014 county file not downloaded -> lag for train window uses 2017 itself; drop lag feats there
    for c in ["own_est_change_lag", "estab_growth_lag"]:
        fA = fA.drop(columns=c); fB = fB.drop(columns=c)
    fA["pop_growth_lag"] = pe.loc[fA.index, "POPESTIMATE2017"] / pe.loc[fA.index, "POPESTIMATE2014"] - 1
    foldA = fA.index.str[:2].map(fold_of).values; foldB = fB.index.str[:2].map(fold_of).values
    res = {}
    for outcome in ["emp_per_est", "ap_per_est"]:
        pers_col = "own_" + outcome
        # existing-market task
        trA = (lA.present0 & lA.present3 & lA[outcome].notna()).values
        teB = (lB.present0 & lB.present3 & lB[outcome].notna()).values
        XA = fA.join(pA); XB = fB.join(pB)
        pred = np.full(len(XB), np.nan)
        for k in range(5):
            m = model().fit(XA[trA & (foldA != k)], np.log(lA[outcome][trA & (foldA != k)]))
            sel = teB & (foldB == k)
            pred[sel] = m.predict(XB[sel])
        y = lB[outcome][teB].values
        r = {"model": evaluate(pred[teB], y), "persistence": evaluate(pB[pers_col][teB].values, y),
             "population": evaluate(fB["pop"][teB].values, y), "local_wage": evaluate(fB["payroll_per_job"][teB].values, y)}
        res[f"existing_{outcome}"] = r
        # cold-start task: no own-industry unit economics as features
        trA2 = (lA.present3 & lA[outcome].notna()).values  # any county where outcome observed in 2020
        teB2 = ((~lB.present0) & lB.present3 & lB[outcome].notna()).values
        pred2 = np.full(len(fB), np.nan)
        for k in range(5):
            m = model().fit(fA[trA2 & (foldA != k)], np.log(lA[outcome][trA2 & (foldA != k)]))
            sel = teB2 & (foldB == k)
            if sel.any():
                pred2[sel] = m.predict(fB[sel])
        y2 = lB[outcome][teB2].values
        res[f"cold_{outcome}"] = {"model": evaluate(pred2[teB2], y2), "population": evaluate(fB["pop"][teB2].values, y2),
                                  "local_wage": evaluate(fB["payroll_per_job"][teB2].values, y2)}
    results[name] = res
    print(name, json.dumps(res, indent=1))
json.dump(results, open(os.path.join(out_dir, "county_results.json"), "w"), indent=1)
