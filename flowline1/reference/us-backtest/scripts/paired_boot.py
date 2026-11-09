"""Paired bootstrap: model vs population baseline on cold-start lift; metro summaries.
usage: python -I paired_boot.py <results_dir>"""
import sys, os, numpy as np, pandas as pd
from scipy.stats import spearmanr
rd = sys.argv[1]; rng = np.random.default_rng(1)
def top_hit(s, y):
    k = int(round(len(s) * .1)); o = np.argsort(-s, kind="mergesort")[:k]; return y[o].mean()
for name in ["fitness", "physicians", "coffee_snack"]:
    P = pd.read_csv(os.path.join(rd, f"oof_test_preds_{name}.csv"), dtype={"zip": str})
    C = P[P.hidden0 == 1]
    s1, s2, y = C.pred.values, C.f_pop.values, C.emerge.values
    d = []
    for _ in range(1000):
        i = rng.integers(0, len(y), len(y)); b = y[i].mean()
        d.append(top_hit(s1[i], y[i]) / b - top_hit(s2[i], y[i]) / b)
    print(name, "cold lift model-pop diff 95% CI", np.percentile(d, [2.5, 50, 97.5]).round(2), "P(diff<=0)=", np.mean(np.array(d) <= 0))
P = pd.read_csv(os.path.join(rd, "oof_test_preds_fitness.csv"), dtype={"zip": str})
for st, ctys, nm in [("TX", ["TRAVIS", "WILLIAMSON", "HAYS", "BASTROP", "CALDWELL"], "Austin")]:
    S = P[(P.stabbr == st) & P.cty_name.str.upper().isin(ctys)].sort_values("pred", ascending=False)
    print(nm, "n", len(S), "spearman pred vs actual net", round(spearmanr(S.pred, S.net).correlation, 3),
          "spearman pop vs net", round(spearmanr(S.f_pop, S.net).correlation, 3))
    print(" top5 mean net", S.net.iloc[:5].mean(), "| metro mean", round(S.net.mean(), 2), "median", S.net.median(),
          "| top5 by population mean net", S.sort_values("f_pop", ascending=False).net.iloc[:5].mean(),
          "| bottom half mean", round(S.net.iloc[len(S)//2:].mean(), 2))
    print(S[["zip", "city", "pred", "net", "e0", "e3", "f_pop"]].head(10).to_string())
