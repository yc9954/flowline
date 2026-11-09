"""CLI: python -m flowline1 build --out DIR [--seed 15] · check [--out DIR] · demand --recompute [--out DIR]
         · fit --records PATH --out DIR [--industry NAICS] [--process NAME] [--seeds 20] [--plans auto] [--since DATE] [--approvals JSON]"""
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


def cmd_fit(args) -> int:
    from . import fit as F

    records = F.load_records(args.records)
    approvals = None
    if args.approvals:
        with open(args.approvals, encoding="utf-8") as f:
            approvals = json.load(f)
        if isinstance(approvals, dict):
            approvals = approvals.get("approvals") or approvals.get("items") or []
    t0 = time.time()
    summary = F.fit(records, out=args.out, board_id=args.board_id, industry=args.industry, process=args.process, seeds=args.seeds,
                    plans=args.plans, since=args.since, approvals=approvals, start_step=args.start_step, end_step=args.end_step,
                    city=args.city, zips=args.zips, raw_dir=RAW, reference_dir=os.path.abspath(REFERENCE), bootstrap=args.bootstrap)
    print(f"fit done in {time.time() - t0:.1f}s -> {args.out}")
    for k, v in summary.items():
        print(f"  {k}: {v}")
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
    f = sub.add_parser("fit", help="the ten board files from a company's approved records alone (no world)")
    f.add_argument("--records", required=True, help="records as a JSON array, {records: [...]} or NDJSON (the API's GET /records export)")
    f.add_argument("--out", required=True)
    f.add_argument("--board-id", default=None, help="default: the records' board_id")
    f.add_argument("--industry", default=None, help="NAICS code for expansion.json (713940, 621111, 722515 are backtested)")
    f.add_argument("--process", default=None, help="case-id prefix of the process to fit (default: the most frequent prefix)")
    f.add_argument("--seeds", type=int, default=20, help="common-random-number reruns per plan")
    f.add_argument("--plans", default="auto", help="'auto' (templates from the mined bottleneck) or a JSON file of plans with rules")
    f.add_argument("--since", default=None, help="date the approved plan went live: cases started before = baseline, after = measured")
    f.add_argument("--approvals", default=None, help="JSON list of plan approvals (GET /api/boards/{id}/plans/approvals); the first one sets --since")
    f.add_argument("--start-step", default=None, help="step that opens the measured cycle (default: learned)")
    f.add_argument("--end-step", default=None, help="step that closes the measured cycle (default: learned)")
    f.add_argument("--city", default="Austin, TX", help="label for expansion.json")
    f.add_argument("--zips", default="786,787", help="ZIP prefixes to rank in expansion.json")
    f.add_argument("--bootstrap", type=int, default=20, help="miner-stability resamples (0 to skip)")
    f.set_defaults(fn=cmd_fit)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
