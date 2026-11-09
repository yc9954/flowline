"""D1 — BPI Challenge 2020, Domestic Declarations (TU/e, CC BY-NC 4.0).

Download from 4TU (dataset 6a0a26d2-82d0-4018-b1cd-89afb0e8627f), parse the XES with lxml streaming
(no entity resolution, no network, untrusted data), extract the approval chain with per-step waits and
rejection loops, fit a semi-Markov simulator on 2017 cases, simulate 2018 and compare cycle-time median and
P80 with the real 2018 cases.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
from lxml import etree

DATASET_ID = "6a0a26d2-82d0-4018-b1cd-89afb0e8627f"
FILE_UUID = "6eeb0328-f991-48c7-95f2-35033504036e"  # DomesticDeclarations.xes.gz (from the 4TU v2 API file list)
FILE_MD5 = "6a78c39491498363ce4788e0e8ca75ef"
FILE_NAME = "DomesticDeclarations.xes.gz"
URLS = [
    f"https://data.4tu.nl/file/{DATASET_ID}/{FILE_UUID}",
    f"https://data.4tu.nl/ndownloader/files/24031811",
]
XES_NS = "{http://www.xes-standard.org/}"

CHAIN = [
    "Declaration SUBMITTED by EMPLOYEE",
    "Declaration APPROVED by ADMINISTRATION",
    "Declaration APPROVED by BUDGET OWNER",
    "Declaration APPROVED by PRE_APPROVER",
    "Declaration FINAL_APPROVED by SUPERVISOR",
    "Declaration FINAL_APPROVED by DIRECTOR",
    "Request Payment",
    "Payment Handled",
]


def download(raw_dir: str) -> str | None:
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, FILE_NAME)
    if os.path.exists(path) and _md5(path) == FILE_MD5:
        return path
    for url in URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "flowline1/0.1 (research demo)"})
            with urllib.request.urlopen(req, timeout=120) as r, open(path + ".part", "wb") as f:
                while True:
                    b = r.read(1 << 16)
                    if not b:
                        break
                    f.write(b)
            if _md5(path + ".part") == FILE_MD5:
                os.replace(path + ".part", path)
                return path
        except Exception:
            continue
    if os.path.exists(path + ".part"):
        os.remove(path + ".part")
    return None


def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse(path: str) -> tuple[list[dict], dict]:
    """Streaming parse: traces -> {id, amount, events:[(name, role, ts)]}. Entities and DTD are disabled."""
    traces = []
    has_amount = False
    n_events = 0
    with gzip.open(path, "rb") as f:
        for _, trace in etree.iterparse(f, events=("end",), tag=(XES_NS + "trace", "trace"), resolve_entities=False,
                                        no_network=True, load_dtd=False, huge_tree=False):
            t = {"id": None, "amount": None, "events": []}
            for child in trace:
                tag = etree.QName(child).localname
                key = child.get("key")
                if tag in ("string", "float", "int", "date", "boolean") and key:
                    if key == "concept:name":
                        t["id"] = child.get("value")
                    elif key == "Amount":
                        has_amount = True
                        try:
                            t["amount"] = float(child.get("value"))
                        except (TypeError, ValueError):
                            pass
                elif tag == "event":
                    name = role = ts = None
                    for a in child:
                        k = a.get("key")
                        if k == "concept:name":
                            name = a.get("value")
                        elif k == "org:role":
                            role = a.get("value")
                        elif k == "time:timestamp":
                            ts = a.get("value")
                    if name and ts:
                        t["events"].append((name, role or "", datetime.fromisoformat(ts)))
                        n_events += 1
            t["events"].sort(key=lambda e: e[2])
            traces.append(t)
            trace.clear()
            parent = trace.getparent()
            while parent is not None and trace.getprevious() is not None:
                del parent[0]
    return traces, {"cases": len(traces), "events": n_events, "amount_attr": has_amount}


def _year(t: dict) -> int:
    return t["events"][0][2].year


def chain_stats(traces: list[dict]) -> dict:
    """Per-step waits (hours) along the approval chain and rejection-loop rate."""
    waits = defaultdict(list)
    rejected = 0
    acts = Counter()
    for t in traces:
        ev = t["events"]
        names = [e[0] for e in ev]
        acts.update(names)
        if any("REJECTED" in n for n in names):
            rejected += 1
        for (a, _, ta), (b, _, tb) in zip(ev, ev[1:]):
            waits[(a, b)].append((tb - ta).total_seconds() / 3600)
    step_waits = {}
    for (a, b), w in waits.items():
        if len(w) >= 30:
            step_waits[f"{a} -> {b}"] = {"n": len(w), "median_h": round(float(np.median(w)), 1), "p80_h": round(float(np.percentile(w, 80)), 1)}
    top = sorted(step_waits.items(), key=lambda kv: -kv[1]["median_h"] * kv[1]["n"])
    return {"transitions": step_waits, "largest_wait": top[0][0] if top else None,
            "rejection_loop_share": rejected / max(len(traces), 1), "activities": dict(acts.most_common(30))}


class SemiMarkov:
    """Activity -> next-activity routing with lognormal waits per transition, fitted on one year."""

    def __init__(self):
        self.next: dict[str, tuple[list[str], np.ndarray]] = {}
        self.wait: dict[tuple[str, str], tuple[float, float]] = {}
        self.start = Counter()

    def fit(self, traces: list[dict]) -> "SemiMarkov":
        trans = defaultdict(Counter)
        waits = defaultdict(list)
        for t in traces:
            ev = t["events"]
            self.start[ev[0][0]] += 1
            for (a, _, ta), (b, _, tb) in zip(ev, ev[1:]):
                trans[a][b] += 1
                waits[(a, b)].append(max((tb - ta).total_seconds() / 3600, 1 / 60))
            trans[ev[-1][0]]["<end>"] += 1
        for a, c in trans.items():
            names = list(c)
            p = np.array([c[n] for n in names], float)
            self.next[a] = (names, p / p.sum())
        for k, w in waits.items():
            lw = np.log(np.array(w))
            self.wait[k] = (float(lw.mean()), float(lw.std(ddof=1)) if len(w) > 2 else 0.5)
        return self

    def simulate(self, n: int, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        starts = list(self.start)
        sp = np.array([self.start[s] for s in starts], float)
        sp /= sp.sum()
        out = np.empty(n)
        for i in range(n):
            a = starts[rng.choice(len(starts), p=sp)]
            total = 0.0
            for _ in range(60):
                names, p = self.next.get(a, (["<end>"], np.array([1.0])))
                b = names[rng.choice(len(names), p=p)]
                if b == "<end>":
                    break
                mu, sg = self.wait.get((a, b), (math.log(24.0), 1.0))
                total += math.exp(mu + sg * rng.standard_normal())
                a = b
            out[i] = total
        return out


def cycle_hours(traces: list[dict]) -> np.ndarray:
    return np.array([(t["events"][-1][2] - t["events"][0][2]).total_seconds() / 3600 for t in traces if len(t["events"]) > 1])


def run(raw_dir: str, seed: int = 15) -> dict:
    """Returns {"d1": ModelCheck.d1 | None-filled, "detail": {...}}."""
    path = download(raw_dir)
    if path is None:
        return {"d1": {"dataset": "BPI Challenge 2020 Domestic Declarations", "fit_year": 2017, "test_year": 2018,
                       "median_error": None, "p80_error": None, "cases": None, "events": None, "amount_attr": None},
                "detail": {"error": "download failed"}, "source": "measured"}
    traces, info = parse(path)
    traces = [t for t in traces if t["events"]]
    fit_tr = [t for t in traces if _year(t) == 2017]
    test_tr = [t for t in traces if _year(t) == 2018]
    model = SemiMarkov().fit(fit_tr)
    real = cycle_hours(test_tr)
    sim = model.simulate(len(test_tr), seed)
    med_err = abs(np.median(sim) - np.median(real)) / np.median(real)
    p80_err = abs(np.percentile(sim, 80) - np.percentile(real, 80)) / np.percentile(real, 80)
    stats = chain_stats(fit_tr)
    amounts = [t["amount"] for t in traces if t["amount"] is not None]
    detail = {
        "fit_cases": len(fit_tr), "test_cases": len(test_tr),
        "real_2018_median_h": round(float(np.median(real)), 1), "real_2018_p80_h": round(float(np.percentile(real, 80)), 1),
        "sim_2018_median_h": round(float(np.median(sim)), 1), "sim_2018_p80_h": round(float(np.percentile(sim, 80)), 1),
        "largest_wait_transition_2017": stats["largest_wait"],
        "rejection_loop_share_2017": round(stats["rejection_loop_share"], 3),
        "chain_transitions_2017": {k: v for k, v in stats["transitions"].items()
                                   if any(k.startswith(c) for c in CHAIN) and any(k.endswith(c) for c in CHAIN)},
        "amount_median": round(float(np.median(amounts)), 2) if amounts else None,
        "amount_share_under_100": round(float(np.mean(np.array(amounts) < 100)), 3) if amounts else None,
        "activities": stats["activities"],
        "license": "CC BY-NC 4.0 (TU/e); demo use only, not for training a product",
        "file_md5": FILE_MD5,
    }
    d1 = {"dataset": "BPI Challenge 2020 Domestic Declarations", "fit_year": 2017, "test_year": 2018,
          "median_error": round(float(med_err), 4), "p80_error": round(float(p80_err), 4),
          "cases": info["cases"], "events": info["events"], "amount_attr": bool(info["amount_attr"])}
    return {"d1": d1, "detail": detail, "source": "measured"}


if __name__ == "__main__":  # manual check: python -I -m flowline1.bpic <raw_dir>
    import sys

    print(json.dumps(run(sys.argv[1]), indent=1, default=str))
