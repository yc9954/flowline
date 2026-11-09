"""The board block (board.py): role → address resolution, Northwind defaults without a block, labels, and
prepare() on a real desk without demo assets."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

import board as board_mod
from board import Board, doc_label, subject_label
from skills import _packet
from skills._packet import ALL_STEPS, EXPORT, FILL_DECK, HAND_OVER, READ_QUOTES, UPDATE_SHEET, SkillError, _mail_spec, resolve_inputs

ACME = {
    "id": "acme", "name": "Acme Tooling", "mail_domain": "acme.example",
    "people": [
        {"id": "p-1", "role": "PM", "email": "lee@acme.example", "name": "Lee"},
        {"id": "p-2", "role": "Finance", "email": "books@acme.example"},
        {"id": "p-3", "role": "CEO", "email": "ceo@acme.example"},
        {"id": "p-4", "role": "Ops", "email": "ops@acme.example"},
    ],
}


def test_roles_resolve_to_addresses_from_the_block():
    b = Board.from_block(ACME)
    assert not b.absent and b.name == "Acme Tooling" and b.mail_domain == "acme.example"
    assert b.email_for_role("Finance") == "books@acme.example" and b.email_for_role("finance") == "books@acme.example"
    assert b.email_for_role("Director") == "ceo@acme.example" and b.approver_email() == "ceo@acme.example"   # Director → CEO fallback
    assert b.pm_email() == "lee@acme.example" and b.email_for_role("Legal") is None
    assert b.sender_for("mac", "p-4") == "ops@acme.example" and b.role_of("ops@acme.example") == "Ops"
    assert b.sender_for("mac", "unknown-9") == "lee@acme.example"      # no match → the PM, never a desk-number guess
    assert b.mail_window_title == "Acme Tooling Mail :: Inbox"
    assert Board.from_block({**ACME, "mail_window_title": "Acme Webmail :: Inbox"}).mail_window_title == "Acme Webmail :: Inbox"
    assert b.inside("ceo@acme.example") and not b.inside("ceo@gmail.com")


def test_defaults_without_a_board_block_are_todays_northwind_values():
    b = Board.from_block(None)
    assert b.absent and b.id == "northwind" and b.mail_domain == "northwind.local"
    assert b.mail_window_title == "Northwind Mail :: Inbox"
    assert b.approver_email() == "director@northwind.local" and b.finance_email() == "finance@northwind.local"
    assert b.pm_email() == "pm@northwind.local"
    # senders: by person id (data/people.json ids), by a login-shaped id, else by desk number (demo only)
    assert b.sender_for("desk2", "fin-1") == "finance@northwind.local"
    assert b.sender_for("desk4", "finance-1") == "finance@northwind.local"
    assert [b.sender_for(f"desk{i}", None) for i in range(1, 7)] == [f"{l}@northwind.local" for l in board_mod.DEMO_LOGINS]
    assert b.sender_for("desk9", None) == "pm@northwind.local" and b.sender_for("mac", None) == "pm@northwind.local"
    assert b.role_of("ops@northwind.local") == "Ops" and b.role_of("studio@northwind.local") == "Studio"
    assert Board.from_run(None).absent


def test_mail_configured_needs_a_host_unless_it_is_the_demo(monkeypatch):
    monkeypatch.delenv("FLOWLINE_MAIL_HOST", raising=False)
    assert Board.from_block(None).mail_configured()                  # the demo keeps its localhost/tunnel default
    assert not Board.from_block(ACME).mail_configured()              # a real board needs an explicit mail server
    monkeypatch.setenv("FLOWLINE_MAIL_HOST", "mail.acme.example")
    assert Board.from_block(ACME).mail_configured()
    assert not Board.from_block({**ACME, "mail_domain": ""}).mail_configured() or Board.from_block({**ACME, "mail_domain": ""}).mail_domain == "acme.example"


def test_mail_spec_by_role_and_document_name():
    b = Board.from_block(ACME)
    inputs = {"deck": "/home/lee/Documents/Acme Q4.odp", "sender": "ops@acme.example", "role": "Ops"}
    spec = _mail_spec(ALL_STEPS, inputs, b)
    assert spec["to"] == "ceo@acme.example" and spec["cc"] == "books@acme.example"
    assert spec["subject"] == "Acme Q4 — for signature · Ops" and spec["attachment"] == "Acme Q4.pdf"
    assert spec["domain"] == "acme.example" and spec["window_title"] == "Acme Tooling Mail :: Inbox"
    rec = _mail_spec([READ_QUOTES, UPDATE_SHEET, HAND_OVER], inputs, b)
    assert rec["to"] == "lee@acme.example" and rec["cc"] is None and rec["subject"] == "Quotes reconciled — Acme Q4 · Ops"
    # the demo subjects are unchanged
    d = _mail_spec(ALL_STEPS, {"deck": "/config/Documents/proposal-172.odp", "proposal": 172, "sender": "ops@northwind.local", "role": "Ops"})
    assert d["subject"] == "Proposal 172 — for signature · Ops" and d["attachment"] == "proposal-172.pdf" and d["to"] == "director@northwind.local"
    # a sender who is also the cc does not cc themself; a board with nobody to hand over to is a clear error
    fin = _mail_spec(ALL_STEPS, {"deck": "/x/d.odp", "sender": "books@acme.example", "role": "Finance"}, b)
    assert fin["cc"] is None
    with pytest.raises(SkillError):
        _mail_spec(ALL_STEPS, inputs, Board.from_block({"id": "solo", "name": "Solo", "mail_domain": "solo.example",
                                                         "people": [{"id": "x", "role": "Ops", "email": "ops@solo.example"}]}))


def test_document_labels_no_longer_assume_proposal_172():
    assert doc_label("/config/Documents/proposal-172.odp") == "proposal #172"
    assert doc_label("/x/whatever.odp", proposal=171) == "proposal #171"
    assert doc_label("/home/lee/Acme Q4 pricing.odp") == "Acme Q4 pricing"
    assert subject_label("/home/lee/Acme Q4 pricing.odp") == "Acme Q4 pricing" and subject_label("/x/proposal-173.odp") == "Proposal 173"
    assert _packet.make_title("signature_packet", {"sheet": "/x/a.ods", "deck": "/x/Acme Q4.odp"}) == "Filling Acme Q4 and exporting it for signature"
    from skills import fill_deck_from_sheet as fd
    assert fd.title({}) == "Filling proposal #172 pricing from your sheet"
    assert fd.title({"deck": "/Users/lee/Decks/Board pack.odp", "sheet": "/Users/lee/a.ods"}) == "Filling Board pack pricing from your sheet"


def test_resolve_inputs_demo_gate():
    demo = resolve_inputs({})
    assert demo["demo_assets"] is True and demo["dress"] is True and demo["proposal"] == 172 and demo["client"] == "Halden Logistics"
    v = resolve_inputs({"proposal": 173})
    assert v["demo_assets"] is True and v["deck"].endswith("proposal-173.odp")
    real = resolve_inputs({"sheet": "/home/lee/Documents/prices.ods", "deck": "/home/lee/Documents/Acme Q4.odp", "client": "Acme"})
    assert real["demo_assets"] is False and real["dress"] is False and real["proposal"] is None and real["client"] == "Acme"
    assert real["label"] == "Acme Q4"
    forced = resolve_inputs({"sheet": "/x/a.ods", "deck": "/x/b.odp", "demo_assets": True, "dress": True})
    assert forced["demo_assets"] is True and forced["dress"] is True
    fd = __import__("skills.fill_deck_from_sheet", fromlist=["resolve_inputs"]).resolve_inputs
    assert fd({})["demo_assets"] is True and fd({"sheet": "/u/a.ods", "deck": "/u/b.odp"})["demo_assets"] is False


class FakeDesk:
    """A desk with files in a temp dir and no LibreOffice (not a DockerDesktop: the local-file helpers apply)."""
    name = "fake"

    def __init__(self, root: str):
        self.root = root
        self.calls: list[str] = []

    def sh(self, cmd: str, timeout: float = 60):
        self.calls.append(cmd)
        if cmd.startswith("mkdir -p"):
            os.makedirs(cmd.split("mkdir -p ", 1)[1].strip().strip("'"), exist_ok=True)
        return 0, ""

    def put_file(self, *a):  # never called on a real desk
        raise AssertionError("prepare() must not restore assets without demo_assets")

    def size(self):
        return (1920, 1080)


class FakeCtx:
    def __init__(self, runs_dir: str):
        from runs import Run
        self.run = Run(id="run-test-real", skill_id="signature_packet", target="desk7", person_id="p-4", board=ACME)
        self.runs_dir = runs_dir
        self.logs = []

    def log(self, kind, detail="", seconds=0.0, step=None):
        self.logs.append((kind, detail))


def _sheet_bytes() -> bytes:
    return open(os.path.join(_packet.ASSETS_DIR, "pricing-sheet.ods"), "rb").read()


def test_prepare_without_demo_assets_only_verifies_files_and_dresses_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        docs = os.path.join(tmp, "Documents")
        os.makedirs(docs)
        sheet, deck = os.path.join(docs, "prices.ods"), os.path.join(docs, "Acme Q4.odp")
        open(sheet, "wb").write(_sheet_bytes())
        open(deck, "wb").write(open(os.path.join(_packet.ASSETS_DIR, "proposal-172.odp"), "rb").read())
        desk, ctx = FakeDesk(tmp), FakeCtx(os.path.join(tmp, "runs"))
        inputs = resolve_inputs({"sheet": sheet, "deck": deck, "out_dir": os.path.join(docs, "Out"), "client": "Acme"})
        inputs["sender"], inputs["role"] = "ops@acme.example", "Ops"
        truth = _packet.prepare(ctx, desk, inputs, [FILL_DECK, EXPORT, HAND_OVER], Board.from_block(ACME))
        assert truth["demo_assets"] is False and truth["dressed"] is None and truth["uno"] is False
        assert truth["sheet_after"] == [("Memberships, 120 seats", 2600), ("Lunchtime classes, 8 / mo", 1150), ("Onboarding week", 540)]
        assert truth["expected_amounts"] == [2600, 1150, 540, 4290] and truth["changed"] is None
        assert truth["pdf"] == os.path.join(docs, "Out", "Acme Q4.pdf") and os.path.isdir(os.path.join(docs, "Out"))
        assert truth["mail"]["to"] == "ceo@acme.example" and truth["mail"]["subject"] == "Acme Q4 — for signature · Ops"
        assert truth["mail"]["window_title"] == "Acme Tooling Mail :: Inbox" and truth["board"]["id"] == "acme"
        assert json.load(open(os.path.join(ctx.runs_dir, "run-test-real", "truth.json")))["label"] == "Acme Q4"
        assert not any("wmctrl" in c or "pkill" in c or "rm -f" in c for c in desk.calls), desk.calls
        # a missing file is a clear error, not a restore
        with pytest.raises(SkillError):
            _packet.prepare(ctx, desk, {**inputs, "deck": os.path.join(docs, "nope.odp")}, [FILL_DECK, EXPORT, HAND_OVER], Board.from_block(ACME))
        # READ THE QUOTES on a real desk needs quote PDFs on the desk; with none the truth is unknown → error
        with pytest.raises(SkillError):
            _packet.prepare(ctx, desk, {**inputs, "quotes_dir": os.path.join(docs, "Quotes")}, ALL_STEPS, Board.from_block(ACME))
        # with our own quote layout on the desk the truth is derived from the PDFs
        from quotes import make_quotes
        qdir = os.path.join(docs, "Quotes")
        os.makedirs(qdir)
        q_truth, files = make_quotes(truth["sheet_after"], seed=7)
        for name, data in files.items():
            open(os.path.join(qdir, name), "wb").write(data)
        t2 = _packet.prepare(ctx, desk, {**inputs, "quotes_dir": qdir}, ALL_STEPS, Board.from_block(ACME))
        assert t2["derived_from"] == "quote PDFs on the desk" and t2["changed"]["to"] == q_truth["changed"]["to"]
        assert t2["expected_amounts"] == [a for _, a in q_truth["sheet_after"]] + [q_truth["total_after"]]
