"""CLI: python -m flowline1 build --out DIR [--seed 15] · check [--out DIR] · demand --recompute [--out DIR]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("FLOWLINE_ROOT") or os.path.abspath(os.path.join(HERE, "..", ".."))  # repo root (parent of the package dir)
DEFAULT_OUT = os.path.join(ROOT, "data", "out")
RAW = os.path.join(ROOT, "data", "raw")
REFERENCE = os.path.join(HERE, "..", "reference", "us-backtest", "results")


def cmd_build(args) -> int:
    from . import calibrate

    t0 = time.time()
    summary = calibrate.build(out=args.out, seed=args.seed, weeks_base=args.weeks, weeks_after=args.weeks_after,
                              raw_dir=RAW, reference_dir=os.path.abspath(REFERENCE), recompute_demand=args.recompute_demand)
    dt = time.time() - t0
    print(f"build done in {dt:.1f}s -> {args.out}")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


def cmd_check(args) -> int:
    from . import calibrate

    calibrate.check(args.out)
    return 0


def cmd_demand(args) -> int:
    from . import demand

    out_dir = os.path.join(args.out, "demand")
    t0 = time.time()
    res = demand.backtest(os.path.join(RAW, "census", "processed"), os.path.join(RAW, "census", "geo", "2020_Gaz_zcta_national.txt"),
                          out_dir, max_iter=args.max_iter)
    print(f"demand backtest recomputed in {time.time() - t0:.0f}s -> {out_dir}")
    for k, v in res.items():
        if isinstance(v, dict):
            print(k, json.dumps(v.get("model", {}))[:300])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="flowline1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="run the world, mine, fit, test plans, calibrate, write the ten output files")
    b.add_argument("--out", default=DEFAULT_OUT)
    b.add_argument("--seed", type=int, default=15)
    b.add_argument("--weeks", type=int, default=8, help="baseline weeks before the change")
    b.add_argument("--weeks-after", type=int, default=3, help="weeks of records after the change (cycles run ~4 working days, so 2 weeks censors most cases)")
    b.add_argument("--recompute-demand", action="store_true", help="recompute the US Census backtest (several minutes)")
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser("check", help="print the BUILD-PLAN section 4 metrics table from a build")
    c.add_argument("--out", default=DEFAULT_OUT)
    c.set_defaults(fn=cmd_check)
    d = sub.add_parser("demand", help="recompute the demand-model backtest into <out>/demand")
    d.add_argument("--out", default=DEFAULT_OUT)
    d.add_argument("--recompute", action="store_true")
    d.add_argument("--max-iter", type=int, default=400)
    d.set_defaults(fn=cmd_demand)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
