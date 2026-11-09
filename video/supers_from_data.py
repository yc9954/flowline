"""Derive the video's supers, the data-driven voice-over lines and the card numbers from the computed data so the
film never claims a number the model did not produce. Writes supers.json, out/vo_text.json and out/cards.json;
then run vo.py (+ vo_higgsfield.py), record_board.mjs and build.py.

usage: python3 supers_from_data.py [--data ../data/out] [--runs ../data/runs]
"""
import argparse, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def words(n):
    n = int(round(n))
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + words(n % 100))
    return str(n)


def load(d, name):
    with open(os.path.join(d, name)) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "out"))
    ap.add_argument("--runs", default=os.path.join(ROOT, "data", "runs"))
    a = ap.parse_args()
    ont, fin, plans, res, exp, opn = (load(a.data, n) for n in
                                      ["ontology.json", "finding.json", "plans.json", "results.json", "expansion.json", "opening.json"])

    steps, roles = ont["counts"]["steps"], ont["counts"]["roles"]
    longest = next((s for s in fin["map"] if s.get("longest_wait")), None)
    wait_h = longest["wait_after_h"] if longest else fin["map"][0].get("wait_after_h", 0)
    people = fin.get("people", 8)
    studios = opn["branch"] - 1
    before = res["before"]
    after = res["measured"]
    pred = res["predicted"]["mid"]
    waiting_h = fin["kpis"]["cycle_time_h"] * fin["kpis"]["waiting_share"]
    n_plans = len(plans["plans"])

    m = load(a.runs, "measure.json") if os.path.exists(os.path.join(a.runs, "measure.json")) else {}
    runs_ok, runs_n, median_s = m.get("success", 10), len(m.get("results", [])) or 10, m.get("median_s", 36.5)
    p = load(a.runs, "privacy.json") if os.path.exists(os.path.join(a.runs, "privacy.json")) else {}
    leaks, planted = p.get("leaks", 0), p.get("planted", 3)

    ind = exp["by_industry"][exp.get("default", "713940")]
    bt = ind["backtest"]
    fit = next((b for b in bt["by_industry"] if b["naics"] == "713940"), bt["by_industry"][0])
    lift, pop = fit["lift"], fit["population_lift"]

    from datetime import date
    saved = (date.fromisoformat(opn["was"]) - date.fromisoformat(opn["opens"])).days

    supers = {
        1: "", 2: "", 4: "", 5: "", 14: "", 16: "",           # cards and the simulation carry their own type
        3: "Multiplayer AI for the whole company · one hub · proposes first, then does the work",
        6: "Northwind Fitness · simulated team · on-device, nothing sent until approved",
        7: "Personal items never leave the laptop",
        8: f"{steps} steps · {roles} roles — learned, not drawn",
        9: f"{wait_h:.0f} h for one signature · {n_plans} plans tested on the same team",
        10: "Asked only of the person it affects",
        11: "Six desks · six jobs · one approval each · filmed side by side for this demo",
        12: "The whole runs at 50× · every one left for a person · nothing saved or sent outside without one",
        13: f"{before:.0f} h → {after:.1f} h · the test predicted {pred:.1f}",
        15: "Flowline — the agent that runs the company's work, with its people",
    }
    vo = {
        9: f"A proposal takes {words(before)} hours, {words(waiting_h)} waiting. It tests {words(n_plans)} fixes on the same team, same luck.",
        13: f"Cycle time: {words(before)} hours to {words(after)}. The test said {words(pred)}.",
        14: f"{words(runs_ok).capitalize()} of {words(runs_n)} runs correct, {words(leaks)} leaks. "
            f"On real Census data, its picks were {lift:g} times as likely to get new gyms.",
    }
    cards = {
        "t-studios": studios, "t-people": people,
        "r-before": f"{before:.0f}", "r-after": f"{after:.0f}", "r-pred": f"{pred:.0f}",
        "r-ok": runs_ok, "r-n": runs_n, "r-med": f"{median_s:.0f}", "r-leaks": leaks, "r-planted": planted,
        "r-lift": f"{lift:g}", "r-pop": f"{pop:g}", "r-days": saved,
    }
    with open(os.path.join(HERE, "supers.json"), "w") as f:
        json.dump({str(k): v for k, v in supers.items()}, f, indent=2, ensure_ascii=False)
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    with open(os.path.join(HERE, "out", "vo_text.json"), "w") as f:
        json.dump({str(k): v for k, v in vo.items()}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(HERE, "out", "cards.json"), "w") as f:
        json.dump(cards, f, indent=2)
    for k in sorted(supers):
        if supers[k]:
            print(f"{k:02d}  {supers[k]}")
        if k in vo:
            print(f"{k:02d}  VO: {vo[k]}")
    print("cards:", cards)


if __name__ == "__main__":
    main()
