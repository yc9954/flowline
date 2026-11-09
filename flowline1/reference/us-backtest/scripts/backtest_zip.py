"""Leak-free ZIP-level location backtest (time + geography holdout).

Train window: features from 2017 (lag 2014) -> outcome = net new establishments 2017->2020.
Test window : features from 2020 (lag 2017) -> outcome = net new establishments 2020->2023.
Geography   : 5-fold GroupKFold over 3-digit ZIP prefixes; a fold's ZIPs (and all ZIPs sharing
              its prefix) are never in training for that fold's model.
So every test prediction is made for a ZIP region the model never saw, about a period
(2020-2023) the model never saw.

usage: python -I backtest_zip.py <processed_dir> <gazetteer_txt> <out_dir>
"""
import sys, os, json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score
from sklearn.neighbors import BallTree

proc, gaz_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out_dir, exist_ok=True)
rng = np.random.default_rng(7)

TARGETS = {"713940": "fitness", "621111": "physicians", "722515": "coffee_snack"}
SIX = ["713940", "621111", "722515", "722511", "722513", "445110", "812112", "812113", "611620",
       "713990", "621210", "621340", "446110", "448140", "451110", "531110", "541211", "561720", "812199"]
SECT = ["s23", "s31", "s42", "s44", "s48", "s51", "s52", "s53", "s54", "s55", "s56", "s61", "s62",
        "s71", "s72", "s81"]

acs = pd.read_csv(os.path.join(proc, "acs2019_zcta.csv"), dtype={"zip": str}).set_index("zip")
gaz = pd.read_csv(gaz_path, sep="\t", dtype={"GEOID": str})
gaz.columns = [c.strip() for c in gaz.columns]
gaz = gaz.set_index("GEOID")[["ALAND_SQMI", "INTPTLAT", "INTPTLONG"]]
Z = {y: pd.read_csv(os.path.join(proc, f"zbp{y}.csv"), dtype={"zip": str}).set_index("zip") for y in [2014, 2017, 2020, 2023]}

def coded(s):  # ZBP hides cells <3 establishments; code hidden as 1 (midpoint of 0..2)
    return s.fillna(1.0)

def build(y0, ylag, y3):
    z0, zl, z3 = Z[y0], Z[ylag], Z[y3]
    idx = z0.index.intersection(z3.index).intersection(acs.index).intersection(gaz.index)
    base = acs.loc[idx].join(gaz.loc[idx])
    base = base[base["pop"] >= 500]
    idx = base.index
    f = pd.DataFrame(index=idx)
    for c in ["pop", "sh_age25_44", "sh_age20_34", "sh_drive_alone", "sh_transit", "sh_walk", "sh_wfh",
              "sh_bachelor_plus", "median_hh_income", "emp_pop_ratio"]:
        f[c] = base[c]
    f["pop_density"] = base["pop"] / base["ALAND_SQMI"].clip(lower=0.05)
    t0 = z0.loc[idx]
    tl = zl.reindex(idx)
    f["jobs"] = t0.tot_emp
    f["jobs_per_resident"] = t0.tot_emp / base["pop"]
    f["payroll_per_job"] = t0.tot_ap / t0.tot_emp.replace(0, np.nan)
    f["all_estab"] = t0.tot_est
    f["all_estab_growth_lag"] = (t0.tot_est - tl.tot_est) / tl.tot_est.replace(0, np.nan)
    f["jobs_growth_lag"] = (t0.tot_emp - tl.tot_emp) / tl.tot_emp.replace(0, np.nan)
    for s in SECT:
        f["sector_" + s] = t0[s].fillna(0) if s in t0 else 0
    for n in SIX:
        f["n" + n] = t0["n" + n].fillna(0)
    # spatial context: totals within 5 km / 10 km (including the ZIP itself)
    ll = np.radians(base[["INTPTLAT", "INTPTLONG"]].values)
    tree = BallTree(ll, metric="haversine")
    for km in [5, 10]:
        nb = tree.query_radius(ll, r=km / 6371.0)
        for col, src in [("pop", base["pop"].values), ("jobs", t0.tot_emp.values.astype(float))]:
            f[f"{col}_within_{km}km"] = [src[i].sum() for i in nb]
        for n in TARGETS:
            src = coded(t0["n" + n]).values
            f[f"n{n}_within_{km}km"] = [src[i].sum() for i in nb]
    lab = {}
    for n in TARGETS:
        e0, e3, el = t0["n" + n], z3.loc[idx, "n" + n], tl["n" + n]
        lab[n] = pd.DataFrame({
            "e0": coded(e0), "hidden0": e0.isna().astype(int), "e3": coded(e3),
            "lag_change": coded(e0) - coded(el),
            "net": coded(e3) - coded(e0),
            "emerge": (e0.isna() & (e3 >= 3)).astype(int),
        }, index=idx)
    meta = t0[["city", "stabbr", "cty_name"]] if "city" in t0 else pd.DataFrame(index=idx)
    return f, lab, meta

def industry_frame(f, lab, n):
    X = f.copy()
    L = lab[n]
    X["own_estab"] = L.e0
    X["own_hidden"] = L.hidden0
    X["own_change_lag"] = L.lag_change
    X["own_per_10k_pop"] = L.e0 / f["pop"] * 1e4
    X["own_within_5km_per_10k"] = f[f"n{n}_within_5km"] / f["pop_within_5km"] * 1e4
    return X, L

fA, labA, _ = build(2017, 2014, 2020)
fB, labB, metaB = build(2020, 2017, 2023)
allzip = fA.index.union(fB.index)
pref = pd.Series(allzip.str[:3], index=allzip)
groups = pref.unique(); rng.shuffle(groups)
fold_of_prefix = {g: i % 5 for i, g in enumerate(groups)}
foldA = pref.loc[fA.index].map(fold_of_prefix).values
foldB = pref.loc[fB.index].map(fold_of_prefix).values

def model():
    return HistGradientBoostingRegressor(loss="squared_error", learning_rate=0.05, max_iter=400,
                                         max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0,
                                         random_state=0)

def topdec(score, y, q=0.10):
    s = pd.Series(score).reset_index(drop=True); yy = pd.Series(y).reset_index(drop=True)
    k = max(1, int(round(len(s) * q)))
    top = s.sort_values(ascending=False, kind="mergesort").index[:k]
    return yy.iloc[top]

def metrics(score, L):
    score = np.asarray(score, float)
    score = np.where(np.isnan(score), np.nanmin(score) - 1, score)
    r = {}
    net = L.net.values
    t = topdec(score, net)
    r["all_n"] = int(len(net)); r["all_spearman"] = float(spearmanr(score, net).correlation)
    r["all_top10_mean_net"] = float(t.mean()); r["all_mean_net"] = float(net.mean()); r["all_median_net"] = float(np.median(net))
    r["all_lift_vs_mean"] = float(t.mean() / net.mean()) if net.mean() > 0 else None
    pos = np.clip(net, 0, None)
    k = len(t)
    r["all_top10_share_of_net_gains"] = float(np.clip(t, 0, None).sum() / pos.sum()) if pos.sum() > 0 else None
    cs = L.hidden0.values == 1
    if cs.sum() > 50:
        yc = L.emerge.values[cs]; sc = score[cs]
        tc = topdec(sc, yc)
        r["cold_n"] = int(cs.sum()); r["cold_base_rate"] = float(yc.mean())
        r["cold_top10_hit_rate"] = float(tc.mean())
        r["cold_lift"] = float(tc.mean() / yc.mean()) if yc.mean() > 0 else None
        r["cold_auc"] = float(roc_auc_score(yc, sc)) if 0 < yc.sum() < len(yc) else None
    es = ~cs
    if es.sum() > 50:
        ye = net[es]; se = score[es]
        te = topdec(se, ye)
        r["est_n"] = int(es.sum()); r["est_spearman"] = float(spearmanr(se, ye).correlation)
        r["est_top10_mean_net"] = float(te.mean()); r["est_median_net"] = float(np.median(ye)); r["est_mean_net"] = float(ye.mean())
    return r

def boot_lift(score, L, B=300):
    score = np.asarray(score, float); cs = L.hidden0.values == 1
    yc = L.emerge.values[cs]; sc = score[cs]
    out = []
    n = len(yc)
    for _ in range(B):
        i = rng.integers(0, n, n)
        t = topdec(sc[i], yc[i]); out.append(t.mean() / max(yc[i].mean(), 1e-9))
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))]

results, preds_all, models = {}, {}, {}
XA_list, XB_list, LA_list, LB_list = [], [], [], []
for n, name in TARGETS.items():
    XA, LA = industry_frame(fA, labA, n)
    XB, LB = industry_frame(fB, labB, n)
    feats = list(XA.columns)
    pred = np.full(len(XB), np.nan)
    ms = {}
    for k in range(5):
        m = model().fit(XA[foldA != k], LA.net[foldA != k])
        pred[foldB == k] = m.predict(XB[foldB == k]); ms[k] = m
    models[n] = (ms, feats)
    preds_all[n] = pd.DataFrame({"pred": pred}, index=XB.index).join(LB).join(XB[["pop", "median_hh_income", "own_change_lag"]].rename(columns=lambda c: "f_" + c))
    res = {"model": metrics(pred, LB)}
    res["model"]["cold_lift_95ci"] = boot_lift(pred, LB)
    base = {
        "population": XB["pop"].values,
        "median_income": XB["median_hh_income"].values,
        "pop_within_5km": XB["pop_within_5km"].values,
        "jobs": XB["jobs"].values,
        "persistence_lag_change": XB["own_change_lag"].values,
        "existing_count": XB["own_estab"].values + 1e-6 * XB["pop"].values,
    }
    for b, s in base.items():
        res["baseline_" + b] = metrics(s, LB)
    results[name] = res
    XA_list.append(XA.assign(**{f"ind_{v}": int(v == name) for v in TARGETS.values()}))
    XB_list.append(XB.assign(**{f"ind_{v}": int(v == name) for v in TARGETS.values()}))
    LA_list.append(LA); LB_list.append(LB)
    print(name, json.dumps(res["model"], indent=0)[:2000])

# pooled: one model over all three industries (industry indicator), same folds
XA = pd.concat(XA_list); XB = pd.concat(XB_list); LA = pd.concat(LA_list); LB = pd.concat(LB_list)
fA3 = np.tile(foldA, 3); fB3 = np.tile(foldB, 3)
pred = np.full(len(XB), np.nan)
for k in range(5):
    m = model().fit(XA[fA3 != k], LA.net[fA3 != k])
    pred[fB3 == k] = m.predict(XB[fB3 == k])
res = {"model": metrics(pred, LB)}
res["model"]["cold_lift_95ci"] = boot_lift(pred, LB)
for b, s in {"population": XB["pop"].values, "median_income": XB["median_hh_income"].values,
             "pop_within_5km": XB["pop_within_5km"].values, "jobs": XB["jobs"].values,
             "persistence_lag_change": XB["own_change_lag"].values,
             "existing_count": XB["own_estab"].values + 1e-6 * XB["pop"].values}.items():
    res["baseline_" + b] = metrics(s, LB)
results["pooled"] = res
json.dump(results, open(os.path.join(out_dir, "zip_results.json"), "w"), indent=1)

# ---- metro demo: out-of-fold, out-of-time fitness predictions + local drivers ----
METROS = {
    "Austin TX": ("TX", ["TRAVIS", "WILLIAMSON", "HAYS", "BASTROP", "CALDWELL"]),
    "Denver CO": ("CO", ["DENVER", "ARAPAHOE", "JEFFERSON", "ADAMS", "DOUGLAS", "BROOMFIELD"]),
    "Atlanta GA": ("GA", ["FULTON", "DEKALB", "COBB", "GWINNETT", "CLAYTON", "CHEROKEE", "FORSYTH", "HENRY"]),
}
n = "713940"
ms, feats = models[n]
XB, LB = industry_frame(fB, labB, n)
P = preds_all[n].join(metaB)
med = XB.median()
rows = []
for metro, (st, ctys) in METROS.items():
    sub = P[(P.stabbr == st) & (P.cty_name.str.upper().isin(ctys))].sort_values("pred", ascending=False)
    rho = spearmanr(sub.pred, sub.net).correlation
    k = max(1, int(round(len(sub) * 0.2)))
    print(f"\n{metro}: n={len(sub)} spearman={rho:.2f} top20% mean net={sub.net.iloc[:k].mean():.2f} metro mean net={sub.net.mean():.2f} median={sub.net.median():.1f}")
    for z in sub.index[:5]:
        x = XB.loc[[z]]
        m = ms[int(foldB[XB.index.get_loc(z)])]
        p0 = m.predict(x)[0]
        contrib = {}
        for c in feats:
            xa = x.copy(); xa[c] = med[c]
            contrib[c] = p0 - m.predict(xa)[0]
        top = sorted(contrib.items(), key=lambda kv: -kv[1])[:3]
        r = P.loc[z]
        rows.append({"metro": metro, "zip": z, "city": r.city, "county": r.cty_name, "pred_net_new_2020_23": round(p0, 2),
                     "actual_net_new_2020_23": r.net, "gyms_2020": "<3" if r.hidden0 else int(r.e0),
                     "gyms_2023": "<3" if r.e3 == 1 else int(r.e3),
                     "drivers": "; ".join(f"{c}={x[c].iloc[0]:.3g} (national median {med[c]:.3g}, +{v:.2f})" for c, v in top),
                     "metro_rank_of_actual": int((sub.net > r.net).sum() + 1), "metro_n": len(sub)})
        print(rows[-1])
pd.DataFrame(rows).to_csv(os.path.join(out_dir, "metro_top5_fitness.csv"), index=False)
for nn, name in TARGETS.items():
    preds_all[nn].join(metaB).to_csv(os.path.join(out_dir, f"oof_test_preds_{name}.csv"))
print(json.dumps({k: {kk: v["model"] for kk, v in [("m", results[k])]} for k in results}, indent=1))
