"""Compiler segmentation on a synthetic 1 Hz event log."""
from datetime import datetime, timedelta

from compiler import approve, compile_draft, segment
from privacy import file_hint, mask_title, title_hash

T0 = datetime.fromisoformat("2026-11-09T09:00:00+09:00")


def ev(t, app, title, idle=0.0, private=None):
    e = {"ts": (T0 + timedelta(seconds=t)).isoformat(timespec="seconds"), "app": app, "idle_s": idle, "private": private}
    if private:
        e["title_hash"] = ""
        e["title_masked"] = ""
    else:
        e["title_hash"] = title_hash(title)
        e["title_masked"] = mask_title(title)
        fh = file_hint(title)
        if fh:
            e["file_hint"] = fh
    return e


def synthetic():
    events = []
    t = 0
    # 10 min in the pricing sheet
    for _ in range(600):
        events.append(ev(t, "calc", "pricing-sheet.ods — LibreOffice Calc")); t += 1
    # 30 s flicker on the desktop (fragment < 2 min → merged)
    for _ in range(30):
        events.append(ev(t, "desktop", "Desktop")); t += 1
    # 6 min mail
    for _ in range(360):
        events.append(ev(t, "writer", "Mail - proposal 172.odt — LibreOffice Writer")); t += 1
    # 2 min personal chat
    for _ in range(120):
        events.append(ev(t, "xmessage", "", private="personal_chat")); t += 1
    # 7 min idle in writer (idle_s climbs)
    for i in range(420):
        events.append(ev(t, "writer", "Mail - proposal 172.odt — LibreOffice Writer", idle=i)); t += 1
    # 90 s bank
    for _ in range(90):
        events.append(ev(t, "browser", "", private="banking")); t += 1
    # 12 min deck
    for _ in range(720):
        events.append(ev(t, "impress", "proposal-172.odp — LibreOffice Impress")); t += 1
    # 3 min contract with a name in the file name
    for _ in range(180):
        events.append(ev(t, "writer", "Kim Minji contract.odt — LibreOffice Writer")); t += 1
    return events


def test_segmentation_boundaries():
    segs = segment(synthetic())
    kinds = [(s.kind, s.app) for s in segs]
    # the 5 min of "not yet idle" writer time after the chat is carved into the waiting stretch and dropped
    assert kinds == [("hands_on", "calc"), ("hands_on", "writer"), ("away", "xmessage"),
                     ("waiting", "writer"), ("removed", "browser"), ("hands_on", "impress"), ("hands_on", "writer")]
    calc = segs[0]
    assert 10 * 60 <= calc.seconds <= 10 * 60 + 35  # absorbed the 30 s desktop flicker
    waiting = segs[3]
    assert waiting.seconds >= 5 * 60 - 5  # idle carved out of the writer segment


def test_draft_and_record_privacy():
    draft = compile_draft(synthetic(), "pm-1", "PM", use_model=False)
    names = [s["name"] for s in draft["steps"]]
    assert names[0] == "Prepare pricing sheet"
    assert "Away from desk" in names
    assert "Review contract" in names
    assert any(s.get("case_id") == "proposal #172" for s in draft["steps"])
    kinds = sorted(l["kind"] for l in draft["left_out"])
    assert kinds == ["banking", "name_in_filename", "personal_chat"]
    actions = {l["kind"]: l["action"] for l in draft["left_out"]}
    assert actions == {"personal_chat": "counted_as_away", "banking": "removed", "name_in_filename": "renamed"}
    rec = approve(draft)
    text = str(rec)
    for needle in ("Minji", "Mom", "Bank", "bank"):
        assert needle not in text
    assert rec["kept_private"] == 3
    assert rec["hands_on_min"] + rec["waiting_min"] > 0
    assert [s["idx"] for s in rec["steps"]] == list(range(1, len(rec["steps"]) + 1))


def test_mask_title():
    assert mask_title("Kim Minji contract.odt — LibreOffice Writer") == "[name] contract.odt — LibreOffice Writer"
    assert mask_title("proposal-172.odp — LibreOffice Impress") == "proposal-172.odp — LibreOffice Impress"
    assert mask_title("Meeting with John Smith") == "Meeting with [name]"
    assert file_hint("proposal-172.odp — LibreOffice Impress") == "proposal-172.odp"
    assert file_hint("Kim Minji contract.odt — LibreOffice Writer") == "[name] contract.odt"
