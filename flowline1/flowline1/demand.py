"""D2 — demand model (US Census ZBP/CBP 2014–2023, ACS 2015–19): Expansion (SCHEMA §9) for Austin, TX.

`backtest()` is the port of reference/us-backtest/scripts/backtest_zip.py (leak-free time + geography holdout).
A full recompute takes several minutes, so `build` loads the reference results computed on 2026-11-08 with the
same scripts unless `--recompute-demand` is passed; `expansion()` then assembles the Expansion objects for the
three industries with lat/lon from the 2020 Gazetteer and `why` tags from each ZIP's standout features.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd

TARGETS = {"713940": "fitness", "621111": "physicians", "722515": "coffee_snack"}
INDUSTRIES = [{"naics": "713940", "name": "Fitness centers"}, {"naics": "621111", "name": "Physician offices"},
              {"naics": "722515", "name": "Coffee and snack bars"}]
THING = {"713940": "gyms", "621111": "clinics", "722515": "coffee shops"}
SIX = ["713940", "621111", "722515", "722511", "722513", "445110", "812112", "812113", "611620",
       "713990", "621210", "621340", "446110", "448140", "451110", "531110", "541211", "561720", "812199"]
SECT = ["s23", "s31", "s42", "s44", "s48", "s51", "s52", "s53", "s54", "s55", "s56", "s61", "s62", "s71", "s72", "s81"]
# Place names for the Austin-metro demo; other ZIPs fall back to the Census city name.
PLACE_NAMES = {
    "78704": "South Austin", "78738": "Lakeway / Bee Cave", "78660": "Pflugerville", "78701": "Downtown", "78613": "Cedar Park",
    "78745": "South Austin", "78758": "North Austin", "78759": "Great Hills", "78746": "West Lake Hills", "78702": "East Austin",
    "78717": "Avery Ranch", "78750": "Anderson Mill", "78664": "Round Rock", "78681": "Round Rock West", "78641": "Leander",
    "78665": "Round Rock East",
}
WHY_LABELS = {
    "sector_s54": "dense office base", "sector_s53": "real-estate activity", "sector_s72": "restaurants and bars nearby",
    "sector_s62": "health-care cluster", "sector_s44": "retail corridor", "sector_s61": "schools and campuses",
    "sector_s51": "tech and media employers", "sh_age25_44": "young professionals", "sh_age20_34": "20s and 30s crowd",
    "median_hh_income": "high incomes", "sh_bachelor_plus": "college-educated", "pop_density": "dense housing",
    "jobs_per_resident": "jobs hub", "all_estab_growth_lag": "businesses growing", "jobs_growth_lag": "jobs growing",
    "pop": "large population", "sh_wfh": "work-from-home share", "sh_walk": "walkable", "sh_transit": "transit riders",
    "payroll_per_job": "well-paid jobs", "pop_within_5km": "people within 5 km", "jobs_within_5km": "jobs within 5 km",
}


def load_inputs(proc: str, gaz_path: str):
    acs = pd.read_csv(os.path.join(proc, "acs2019_zcta.csv"), dtype={"zip": str}).set_index("zip")
    gaz = pd.read_csv(gaz_path, sep="\t", dtype={"GEOID": str})
    gaz.columns = [c.strip() for c in gaz.columns]
    gaz = gaz.set_index("GEOID")[["ALAND_SQMI", "INTPTLAT", "INTPTLONG"]]
    Z = {y: pd.read_csv(os.path.join(proc, f"zbp{y}.csv"), dtype={"zip": str}).set_index("zip") for y in [2014, 2017, 2020, 2023]}
    return acs, gaz, Z


def coded(s):
    return s.fillna(1.0)


def build_features(acs, gaz, Z, y0, ylag, y3):
    from sklearn.neighbors import BallTree

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
        lab[n] = pd.DataFrame({"e0": coded(e0), "hidden0": e0.isna().astype(int), "e3": coded(e3),
                               "lag_change": coded(e0) - coded(el), "net": coded(e3) - coded(e0),
                               "emerge": (e0.isna() & (e3 >= 3)).astype(int)}, index=idx)
    meta = t0[["city", "stabbr", "cty_name"]] if "city" in t0 else pd.DataFrame(index=idx)
    return f, lab, meta, base


def industry_frame(f, lab, n):
    X = f.copy()
    L = lab[n]
    X["own_estab"] = L.e0
    X["own_hidden"] = L.hidden0
    X["own_change_lag"] = L.lag_change
    X["own_per_10k_pop"] = L.e0 / f["pop"] * 1e4
    X["own_within_5km_per_10k"] = f[f"n{n}_within_5km"] / f["pop_within_5km"] * 1e4
    return X, L


def _topdec(score, y):
    k = max(1, int(round(len(score) * 0.1)))
    order = np.argsort(-score)
    return y[order[:k]]


def _metrics(score, L):
    from sklearn.metrics import roc_auc_score

    score = np.asarray(score, float)
    score = np.where(np.isnan(score), np.nanmin(score) - 1, score)
    r = {}
    cs = L.hidden0.values == 1
    yc = L.emerge.values[cs]
    sc = score[cs]
    tc = _topdec(sc, yc)
    r["cold_n"] = int(cs.sum())
    r["cold_base_rate"] = float(yc.mean())
    r["cold_top10_hit_rate"] = float(tc.mean())
    r["cold_lift"] = float(tc.mean() / yc.mean()) if yc.mean() > 0 else None
    r["cold_auc"] = float(roc_auc_score(yc, sc)) if 0 < yc.sum() < len(yc) else None
    return r


def _boot_lift(score, L, rng, B=300):
    score = np.asarray(score, float)
    cs = L.hidden0.values == 1
    yc = L.emerge.values[cs]
    sc = score[cs]
    out = []
    n = len(yc)
    for _ in range(B):
        i = rng.integers(0, n, n)
        t = _topdec(sc[i], yc[i])
        out.append(t.mean() / max(yc[i].mean(), 1e-9))
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))]


def backtest(proc: str, gaz_path: str, out_dir: str, max_iter: int = 400) -> dict:
    """Full recompute of the reference backtest; writes zip_results.json and oof_test_preds_*.csv to out_dir."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(7)
    acs, gaz, Z = load_inputs(proc, gaz_path)
    fA, labA, _, _ = build_features(acs, gaz, Z, 2017, 2014, 2020)
    fB, labB, metaB, _ = build_features(acs, gaz, Z, 2020, 2017, 2023)
    allzip = fA.index.union(fB.index)
    pref = pd.Series(allzip.str[:3], index=allzip)
    groups = np.array(pref.unique(), dtype=object)
    rng.shuffle(groups)
    fold_of_prefix = {g: i % 5 for i, g in enumerate(groups)}
    foldA = pref.loc[fA.index].map(fold_of_prefix).values
    foldB = pref.loc[fB.index].map(fold_of_prefix).values

    def model():
        return HistGradientBoostingRegressor(loss="squared_error", learning_rate=0.05, max_iter=max_iter,
                                             max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0, random_state=0)

    results = {}
    XA_list, XB_list, LA_list, LB_list = [], [], [], []
    for n, name in TARGETS.items():
        XA, LA = industry_frame(fA, labA, n)
        XB, LB = industry_frame(fB, labB, n)
        pred = np.full(len(XB), np.nan)
        for k in range(5):
            m = model().fit(XA[foldA != k], LA.net[foldA != k])
            pred[foldB == k] = m.predict(XB[foldB == k])
        res = {"model": _metrics(pred, LB)}
        res["model"]["cold_lift_95ci"] = _boot_lift(pred, LB, rng)
        res["baseline_population"] = _metrics(XB["pop"].values, LB)
        results[name] = res
        pd.DataFrame({"pred": pred}, index=XB.index).join(LB).join(
            XB[["pop", "median_hh_income", "own_change_lag"]].rename(columns=lambda c: "f_" + c)).join(metaB) \
            .to_csv(os.path.join(out_dir, f"oof_test_preds_{name}.csv"))
        XA_list.append(XA.assign(**{f"ind_{v}": int(v == name) for v in TARGETS.values()}))
        XB_list.append(XB.assign(**{f"ind_{v}": int(v == name) for v in TARGETS.values()}))
        LA_list.append(LA)
        LB_list.append(LB)
    XA = pd.concat(XA_list)
    XB = pd.concat(XB_list)
    LA = pd.concat(LA_list)
    LB = pd.concat(LB_list)
    fA3 = np.tile(foldA, 3)
    fB3 = np.tile(foldB, 3)
    pred = np.full(len(XB), np.nan)
    for k in range(5):
        m = model().fit(XA[fA3 != k], LA.net[fA3 != k])
        pred[fB3 == k] = m.predict(XB[fB3 == k])
    res = {"model": _metrics(pred, LB)}
    res["model"]["cold_lift_95ci"] = _boot_lift(pred, LB, rng)
    res["baseline_population"] = _metrics(XB["pop"].values, LB)
    results["pooled"] = res
    results["_computed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(results, open(os.path.join(out_dir, "zip_results.json"), "w"), indent=1)
    return results


# ----------------------------------------------------------------------------- Expansion assembly
def _why_tags(feature_row: pd.Series, med: pd.Series, iqr: pd.Series, k: int = 3) -> list[str]:
    z = {}
    for c, label in WHY_LABELS.items():
        if c in feature_row and pd.notna(feature_row[c]) and iqr.get(c, 0) > 0:
            z[c] = (feature_row[c] - med[c]) / iqr[c]
    top = sorted(z.items(), key=lambda kv: -kv[1])[:k]
    return [WHY_LABELS[c] for c, v in top if v > 0.5]


def expansion(results_dir: str, proc: str, gaz_path: str, board_id: str, records: int, branches: int,
              opening: dict, computed_note: str, zip_prefixes=("786", "787")) -> dict:
    """One expansion.json with shared fields and by_industry[naics] = Expansion (SCHEMA §9)."""
    zr = json.load(open(os.path.join(results_dir, "zip_results.json")))
    acs, gaz, Z = load_inputs(proc, gaz_path)
    # 2020 features for why-tags (the same features the model used), national medians and IQRs
    f, lab, meta, base = build_features(acs, gaz, Z, 2020, 2017, 2023)
    med = f.median(numeric_only=True)
    iqr = f.quantile(0.75, numeric_only=True) - f.quantile(0.25, numeric_only=True)

    def verdict(lift, pop_lift, ci):
        return "better" if pop_lift < ci[0] else "tie"

    by_ind_bt = []
    for ind in INDUSTRIES:
        r = zr[TARGETS[ind["naics"]]]
        by_ind_bt.append({"naics": ind["naics"], "name": ind["name"], "lift": round(r["model"]["cold_lift"], 1),
                          "population_lift": round(r["baseline_population"]["cold_lift"], 1),
                          "ci": [round(x, 1) for x in r["model"]["cold_lift_95ci"]],
                          "verdict": verdict(r["model"]["cold_lift"], r["baseline_population"]["cold_lift"], r["model"]["cold_lift_95ci"])})
    pooled = {"lift": round(zr["pooled"]["model"]["cold_lift"], 1), "population_lift": round(zr["pooled"]["baseline_population"]["cold_lift"], 1)}

    by_industry = {}
    for ind in INDUSTRIES:
        naics = ind["naics"]
        preds = pd.read_csv(os.path.join(results_dir, f"oof_test_preds_{TARGETS[naics]}.csv"), dtype={"zip": str}).set_index("zip")
        sub = preds[preds.index.str[:3].isin(zip_prefixes)].copy()
        sub = sub.join(gaz, how="left")
        sub = sub.sort_values("pred", ascending=False)
        rows = []
        for rank, (z, r) in enumerate(sub.iterrows(), 1):
            why = _why_tags(f.loc[z], med, iqr) if z in f.index else []
            city = str(r.get("city", "")).title() if pd.notna(r.get("city", np.nan)) else ""
            county = str(r.get("cty_name", "")).title() if pd.notna(r.get("cty_name", np.nan)) else ""
            rows.append({"zip": z, "name": PLACE_NAMES.get(z, city or county or z),
                         "why": why or ["near the metro average on every driver"],
                         "predicted": round(float(r["pred"]), 2), "happened": float(r["net"]), "rank": rank, "pick": rank == 1,
                         "lat": round(float(r["INTPTLAT"]), 5) if pd.notna(r.get("INTPTLAT", np.nan)) else 0.0,
                         "lon": round(float(r["INTPTLONG"]), 5) if pd.notna(r.get("INTPTLONG", np.nan)) else 0.0})
        top = rows[0]
        r = zr[TARGETS[naics]]
        thing = THING[naics]
        headline = f"Branch {branches + 1} goes to {top['zip']}, {top['name']} — where demand for {thing} is growing fastest."
        why_txt = ", ".join(top["why"][:2]) if top["why"] else "its local mix"
        sub_txt = (f"{why_txt[0].upper() + why_txt[1:]} pull new {thing} in. Predicted from 2020 conditions; "
                   f"{int(sum(1 for x in rows if x['happened'] > 0))} of {len(rows)} ZIPs added {thing} by 2023. "
                   f"Source: US Census ZBP/CBP 2014–2023, ACS 2015–19.")
        by_industry[naics] = {
            "board_id": board_id, "city": "Austin, TX", "industries": INDUSTRIES, "industry": naics,
            "headline": headline, "sub": sub_txt, "zips_considered": len(rows), "branches": branches, "records": records,
            "rank_of": len(rows), "opening": opening, "zips": rows,
            "backtest": {"frozen_at": 2020, "scored_on": 2023, "n_zips": int(r["model"]["cold_n"]),
                         "lift": round(r["model"]["cold_lift"], 1), "ci": [round(x, 1) for x in r["model"]["cold_lift_95ci"]],
                         "by_industry": by_ind_bt, "pooled": pooled},
            "source": "measured",
        }
    return {
        "source": "measured",
        "board_id": board_id, "city": "Austin, TX", "industries": INDUSTRIES, "default": "713940",
        "records": records, "branches": branches,
        "note": computed_note,
        "by_industry": by_industry,
    }
