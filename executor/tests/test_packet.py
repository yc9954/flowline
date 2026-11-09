"""Packet skills: quote generation, truth, and the pure verification helpers (no desktop needed)."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"))

from make_assets import ITEMS  # noqa: E402
from quotes import VENDORS, make_quotes, plan_quotes  # noqa: E402
from skills import _packet, load  # noqa: E402
from skills._packet import money_pattern, note_ok, parse_tree, pdf_has_amounts, pdf_text, tree_changes  # noqa: E402


def test_plan_exactly_one_quote_differs_by_a_plausible_delta():
    for seed in range(40):
        t = plan_quotes(ITEMS, seed=seed)
        diffs = [q for q in t["quotes"] if q["differs"]]
        assert len(diffs) == 1
        q = diffs[0]
        assert q["amount"] != q["sheet_amount"] and q["amount"] % 10 == 0
        assert 0.04 <= abs(q["amount"] - q["sheet_amount"]) / q["sheet_amount"] <= 0.22
        assert t["changed"]["vendor"] == q["vendor"] and t["changed"]["to"] == q["amount"]
        assert t["total_after"] == sum(a for _, a in t["sheet_after"])
        assert t["total_after"] != t["total_before"]
        for other in t["quotes"]:
            if other is not q:
                assert other["amount"] == other["sheet_amount"]


def test_plan_is_reproducible_with_a_seed_and_covers_all_vendors():
    assert plan_quotes(ITEMS, seed=7) == plan_quotes(ITEMS, seed=7)
    assert {plan_quotes(ITEMS, seed=s)["changed"]["index"] for s in range(30)} == {0, 1, 2}
    t = plan_quotes(ITEMS, seed=3, all_equal=True)
    assert t["changed"] is None and t["sheet_after"] == t["sheet_before"]


def test_quote_pdfs_render_and_carry_the_amount():
    truth, files = make_quotes(ITEMS, seed=11)
    assert len(files) == 3 and all(data.startswith(b"%PDF") for data in files.values())
    for q in truth["quotes"]:
        txt = pdf_text(files[q["file"]])
        assert q["vendor"] in txt and "Total quoted" in txt
        assert money_pattern(q["amount"]).search(txt), txt
        # the quote's item maps to a sheet row
        assert q["item"] in dict(ITEMS)


def test_money_pattern_variants():
    p = money_pattern(2860)
    for s in ("$2,860", "2,860", "2860", "$ 2 860", "Total: $2,860."):
        assert p.search(s), s
    for s in ("$12,860", "28600", "2,8600", "$2,86"):
        assert not p.search(s), s


def test_pdf_has_amounts_reports_missing():
    ok, detail = pdf_has_amounts("Memberships $2,600 Lunchtime $920 Onboarding $540 Total $4,060", [2600, 920, 540, 4060])
    assert ok and detail == "all amounts present"
    ok, detail = pdf_has_amounts("Memberships $2,600 Total $4,060", [2600, 920, 540, 4060])
    assert not ok and "$920" in detail and "$540" in detail


def test_note_ok_needs_vendor_and_total():
    text = "Changed Lunchtime classes from $1,150 to $920\nPer MoveWell Studio quote Q-2026-4421\nTotal: $4,060\n"
    assert note_ok(text, "MoveWell Studio", 4060)[0]
    assert note_ok(text.replace("MoveWell Studio", "the studio"), "MoveWell Studio", 4060)[0] is False
    assert note_ok(text, "MoveWell Studio", 4290)[0] is False
    assert note_ok("", "MoveWell Studio", 4060)[0] is False
    assert note_ok("Filled the deck\nExported proposal-172.pdf\nTotal: $4,290", None, 4290)[0]


def test_tree_changes_ignores_locks_and_allowed_paths():
    before = parse_tree("aaa  ./pricing-sheet.ods\nbbb  ./proposal-172.odp\nccc  ./Quotes/a quote.pdf\n")
    after = parse_tree("a2a  ./pricing-sheet.ods\nbbb  ./proposal-172.odp\nccc  ./Quotes/a quote.pdf\n"
                       "ddd  ./For signature/proposal-172.pdf\neee  ./For signature/NOTE.txt\nfff  ./.~lock.pricing-sheet.ods#\n")
    assert tree_changes(before, after, {"pricing-sheet.ods", "For signature/proposal-172.pdf", "For signature/NOTE.txt"}) == []
    assert tree_changes(before, after, {"For signature/proposal-172.pdf", "For signature/NOTE.txt"}) == ["changed pricing-sheet.ods"]
    gone = dict(after)
    del gone["Quotes/a quote.pdf"]
    gone["proposal-172.odp"] = "zzz"
    bad = tree_changes(before, gone, {"pricing-sheet.ods", "For signature/proposal-172.pdf", "For signature/NOTE.txt"})
    assert bad == ["removed Quotes/a quote.pdf", "changed proposal-172.odp"]


def test_skill_modules_follow_the_registry_contract():
    expected = {
        "proposal_packet": ["READ THE QUOTES", "UPDATE THE SHEET", "FILL THE DECK", "EXPORT FOR SIGNATURE", "HAND IT OVER"],
        "reconcile_quotes": ["READ THE QUOTES", "UPDATE THE SHEET", "HAND IT OVER"],
        "signature_packet": ["FILL THE DECK", "EXPORT FOR SIGNATURE", "HAND IT OVER"],
    }
    for sid, steps in expected.items():
        m = load(sid)
        assert m.SKILL["id"] == sid and m.SKILL["steps"] == steps
        assert m.SKILL["tools"] == ["computer", "report_step"]
        assert "#172" in m.title({}) and callable(m.run)
    assert load("fill_deck_from_sheet").SKILL["steps"] == ["READ THE SHEET", "FILL THE DECK", "CHECK THE TOTAL", "LEAVE IT FOR YOU"]


@pytest.mark.skipif(not os.path.exists(os.path.join(_packet.AGENT_DIR, "node_modules")), reason="agent-ts not installed")
def test_agent_prompts_match_the_python_steps():
    js = """
import('./skills.mjs').then(m => {
  const out = {};
  for (const id of ['fill_deck_from_sheet', 'proposal_packet', 'reconcile_quotes', 'signature_packet']) {
    const r = m.skillPrompt(id, {}, { view_w: 1280, view_h: 720 });
    out[id] = { steps: r.steps, tools: r.tools, has_view: r.instructions.includes('1280x720') };
  }
  console.log(JSON.stringify(out));
});
"""
    p = subprocess.run([os.environ.get("FLOWLINE_NODE", "node"), "-e", js], cwd=_packet.AGENT_DIR, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])
    for sid in ("proposal_packet", "reconcile_quotes", "signature_packet"):
        assert out[sid]["steps"] == load(sid).SKILL["steps"]
        assert out[sid]["tools"] == ["computer", "report_step"]
        assert out[sid]["has_view"]
    assert out["fill_deck_from_sheet"]["tools"] == ["computer", "bash", "read_sheet", "read_deck_cells", "report_step"]


def test_sender_and_mail_subject_are_per_desk_in_the_demo():
    from board import Board
    from skills._packet import ALL_STEPS, _mail_spec
    b = Board.from_block(None)   # no board block on the run → Northwind defaults
    assert [b.login(b.sender_for(f"desk{i}", None)) for i in range(1, 7)] == ["pm", "finance", "sales", "ops", "studio", "director"]
    assert b.sender_for("desk4", "finance-1") == "finance@northwind.local" and b.sender_for("desk9", None) == "pm@northwind.local"
    spec = _mail_spec(ALL_STEPS, {"sender": "ops@northwind.local", "role": b.role_of("ops@northwind.local"), "deck": "/config/Documents/proposal-172.odp"})
    assert spec["subject"] == "Proposal 172 — for signature · Ops" and spec["attachment"] == "proposal-172.pdf" and spec["cc"] == "finance@northwind.local"
    assert spec["to"] == "director@northwind.local" and spec["window_title"] == "Northwind Mail :: Inbox" and spec["domain"] == "northwind.local"
    rec = _mail_spec(["READ THE QUOTES", "UPDATE THE SHEET", "HAND IT OVER"], {"sender": "finance@northwind.local", "role": "Finance", "deck": "/config/Documents/proposal-172.odp"})
    assert rec["subject"] == "Quotes reconciled — Proposal 172 · Finance" and rec["attachment"] is None and rec["to"] == "pm@northwind.local"


def test_proposal_variants_resolve_files_quotes_and_subjects():
    from make_assets import VARIANTS, fods, variant
    from quotes import vendors_for
    from skills._packet import ALL_STEPS, _mail_spec, make_title, resolve_inputs
    assert resolve_inputs({})["sheet"].endswith("/pricing-sheet.ods") and resolve_inputs({})["deck"].endswith("/proposal-172.odp")
    for n in (171, 173):
        v = variant(n)
        i = resolve_inputs({"proposal": n})
        assert i["sheet"].endswith(f"/pricing-sheet-{n}.ods") and i["deck"].endswith(f"/proposal-{n}.odp") and i["client"] == v["client"]
        assert [lbl for lbl, _ in v["items"]] == [lbl for lbl, *_ in vendors_for(n)]
        assert f"#{n}" in make_title("proposal_packet", {"proposal": n})
        spec = _mail_spec(ALL_STEPS, {**i, "sender": "sales@northwind.local", "role": "Sales"})
        assert spec["subject"] == f"Proposal {n} — for signature · Sales" and spec["attachment"] == f"proposal-{n}.pdf"
        assert f"${v['total']:,}" in fods(v["items"])
    assert set(VARIANTS) == {171, 172, 173}
