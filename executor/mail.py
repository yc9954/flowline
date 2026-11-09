"""Flowline team mail — stdlib helper over the greenmail stack (see MAIL.md).

Reachability: on the mini the server is localhost:3025/3143; from the laptop open the tunnel first
    ssh -fN -L 3143:localhost:3143 -L 3025:localhost:3025 mini
and leave FLOWLINE_MAIL_HOST at its default (localhost). Inside a desk container the host is `mail`.

API (all return plain dicts / lists of dicts — {id, from, to, subject, date, attachments: [names], snippet}):
    send(from_, to, subject, body, attachments=[])      -> dict (id = Message-ID)
    list_inbox(user, since=None)                        -> [dict]  (newest first; since: datetime or ISO string)
    find(user, subject_contains, with_attachment=None)  -> [dict]  (with_attachment: None | True | "name-substring")
    fetch_attachment(user, msg_id, name)                -> bytes
    reset(user)                                         -> {"user":..., "deleted": n}   (every folder emptied)
    seed()                                              -> [dict]  (a couple of plausible older threads per inbox)

CLI:  uv run python mail.py list finance [--since 2026-11-09T10:00]
      uv run python mail.py send finance pm "Updated quote: lunchtime classes" --body "..." --attach quote.pdf
      uv run python mail.py find pm quote [--attachment any|quote.pdf]
      uv run python mail.py fetch pm <id> quote.pdf [--out /tmp/quote.pdf]
      uv run python mail.py reset finance|all
      uv run python mail.py seed
"""
from __future__ import annotations

import argparse
import email
import email.utils
import imaplib
import json
import mimetypes
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path

# Host, ports and domain come from the environment; the Northwind values are only defaults for the demo.
HOST = os.environ.get("FLOWLINE_MAIL_HOST", "localhost")
SMTP_PORT = int(os.environ.get("FLOWLINE_MAIL_SMTP_PORT", "3025"))
IMAP_PORT = int(os.environ.get("FLOWLINE_MAIL_IMAP_PORT", "3143"))
DOMAIN = os.environ.get("FLOWLINE_MAIL_DOMAIN", "northwind.local")
PASSWORD = os.environ.get("FLOWLINE_MAIL_PASSWORD", "flowline")  # shared test password (test environment)

# The six Northwind demo users (login -> (display name, desk)): used by `seed`, `users` and `reset all` only.
# Skills never look here — they take addresses from the run's board block (board.py).
DEMO_PEOPLE = {
    "pm": ("Priya Natarajan", "desk1"),
    "finance": ("Northwind Finance", "desk2"),
    "sales": ("Northwind Sales", "desk3"),
    "ops": ("Northwind Ops", "desk4"),
    "studio": ("Studio Manager", "desk5"),
    "director": ("Northwind Director", "desk6"),
}
PEOPLE = DEMO_PEOPLE  # backwards-compatible name


def configured() -> bool:
    """A mail server is configured: FLOWLINE_MAIL_HOST is set explicitly (skills otherwise report the mail
    check as skipped — except the Northwind demo, which keeps the localhost tunnel default; see board.py)."""
    return bool(os.environ.get("FLOWLINE_MAIL_HOST"))


def address(user: str) -> str:
    """'pm' -> 'pm@northwind.local'; full addresses pass through."""
    user = user.strip()
    return user if "@" in user else f"{user}@{DOMAIN}"


def display(user: str, name: str | None = None) -> str:
    """'pm' -> 'Priya Natarajan <pm@northwind.local>' (demo users); other addresses get their local part as the name."""
    local = address(user).split("@")[0]
    name = name or (DEMO_PEOPLE.get(local, (local.title(),))[0] if address(user).endswith("@" + DOMAIN) else local.title())
    return email.utils.formataddr((name, address(user)))


# ---------------------------------------------------------------- IMAP ----------------------------------------------
def _imap(user: str) -> imaplib.IMAP4:
    m = imaplib.IMAP4(HOST, IMAP_PORT)
    m.login(address(user), PASSWORD)
    return m


def _attachments(msg) -> list[str]:
    return [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]


def _snippet(msg, n: int = 160) -> str:
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    if body is not None and body.get_content_type() == "text/html":
        import re
        text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())[:n]


def _summary(uid: str, msg) -> dict:
    date = None
    if msg["Date"]:
        try:
            date = email.utils.parsedate_to_datetime(msg["Date"]).isoformat()
        except (TypeError, ValueError):
            date = str(msg["Date"])
    return {
        "id": uid,
        "from": str(msg["From"] or ""),
        "to": str(msg["To"] or ""),
        "subject": str(msg["Subject"] or ""),
        "date": date,
        "attachments": _attachments(msg),
        "snippet": _snippet(msg),
    }


def _fetch_all(m: imaplib.IMAP4, folder: str = "INBOX", since: datetime | None = None):
    m.select(folder, readonly=True)
    crit = "ALL" if since is None else f'(SINCE "{since.strftime("%d-%b-%Y")}")'
    typ, data = m.uid("SEARCH", None, crit)
    uids = data[0].split() if typ == "OK" and data and data[0] else []
    out = []
    for uid in uids:
        typ, parts = m.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not parts or not isinstance(parts[0], tuple):
            continue
        msg = email.message_from_bytes(parts[0][1], policy=default_policy)
        out.append((uid.decode(), msg))
    return out


def _parse_since(since) -> datetime | None:
    if since is None or since == "":
        return None
    if isinstance(since, datetime):
        return since if since.tzinfo else since.astimezone()
    dt = datetime.fromisoformat(str(since))
    return dt if dt.tzinfo else dt.astimezone()


def list_inbox(user: str, since=None) -> list[dict]:
    """Messages in the user's INBOX, newest first. `since` filters on the Date header (datetime or ISO string)."""
    since_dt = _parse_since(since)
    m = _imap(user)
    try:
        items = []
        for uid, msg in _fetch_all(m, "INBOX", since_dt):
            if since_dt is not None and msg["Date"]:
                try:
                    if email.utils.parsedate_to_datetime(msg["Date"]) < since_dt:
                        continue
                except (TypeError, ValueError):
                    pass
            items.append(_summary(uid, msg))
    finally:
        m.logout()
    items.sort(key=lambda d: (d["date"] or "", int(d["id"])), reverse=True)
    return items


def find(user: str, subject_contains: str, with_attachment=None) -> list[dict]:
    """INBOX messages whose subject contains the text (case-insensitive).
    with_attachment=True: only messages with an attachment; a string: only those with an attachment whose name
    contains it (case-insensitive); None: no attachment filter."""
    needle = subject_contains.lower()
    out = []
    for d in list_inbox(user):
        if needle not in d["subject"].lower():
            continue
        if with_attachment is True and not d["attachments"]:
            continue
        if isinstance(with_attachment, str) and not any(
            with_attachment.lower() in a.lower() for a in d["attachments"]
        ):
            continue
        out.append(d)
    return out


def fetch_attachment(user: str, msg_id: str, name: str) -> bytes:
    """Bytes of the named attachment of INBOX message `msg_id` (the `id` from list/find). Name match is
    case-insensitive; a substring is accepted when it is unambiguous."""
    m = _imap(user)
    try:
        m.select("INBOX", readonly=True)
        typ, parts = m.uid("FETCH", str(msg_id).encode(), "(BODY.PEEK[])")
        if typ != "OK" or not parts or not isinstance(parts[0], tuple):
            raise KeyError(f"no message {msg_id} in {address(user)} INBOX")
        msg = email.message_from_bytes(parts[0][1], policy=default_policy)
    finally:
        m.logout()
    parts = [p for p in msg.iter_attachments() if p.get_filename()]
    exact = [p for p in parts if p.get_filename().lower() == name.lower()]
    cands = exact or [p for p in parts if name.lower() in p.get_filename().lower()]
    if len(cands) != 1:
        raise KeyError(f"attachment {name!r} not found (have {[p.get_filename() for p in parts]})")
    return cands[0].get_payload(decode=True)


def reset(user: str) -> dict:
    """Delete every message in every folder of the mailbox."""
    m = _imap(user)
    deleted = 0
    try:
        typ, folders = m.list()
        names = []
        for line in folders or []:
            if not line:
                continue
            s = line.decode() if isinstance(line, bytes) else str(line)
            names.append(s.rsplit(" ", 1)[-1].strip('"'))
        for folder in names or ["INBOX"]:
            typ, _ = m.select(folder)
            if typ != "OK":
                continue
            typ, data = m.uid("SEARCH", None, "ALL")
            uids = data[0].split() if typ == "OK" and data and data[0] else []
            if uids:
                m.uid("STORE", b",".join(uids), "+FLAGS.SILENT", r"(\Deleted)")
                m.expunge()
                deleted += len(uids)
    finally:
        m.logout()
    return {"user": address(user), "deleted": deleted}


# ---------------------------------------------------------------- SMTP ----------------------------------------------
def send(from_: str, to, subject: str, body: str, attachments=(), date: datetime | None = None,
         cc=(), in_reply_to: str | None = None) -> dict:
    """Send a plain-text mail with optional file attachments (paths). `to`/`cc` may be a login, an address or a list."""
    tos = [to] if isinstance(to, str) else list(to)
    ccs = [cc] if isinstance(cc, str) else list(cc)
    msg = EmailMessage()
    msg["From"] = display(from_)
    msg["To"] = ", ".join(display(t) for t in tos)
    if ccs:
        msg["Cc"] = ", ".join(display(c) for c in ccs)
    msg["Subject"] = subject
    msg["Date"] = email.utils.format_datetime(date or datetime.now().astimezone())
    msg["Message-ID"] = email.utils.make_msgid(domain=DOMAIN)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    for a in attachments or ():
        p = Path(a)
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    with smtplib.SMTP(HOST, SMTP_PORT, timeout=20) as s:
        s.send_message(msg, from_addr=address(from_), to_addrs=[address(t) for t in tos + ccs])
    return {
        "id": msg["Message-ID"],
        "from": msg["From"],
        "to": msg["To"],
        "subject": subject,
        "date": msg["Date"],
        "attachments": [Path(a).name for a in attachments or ()],
        "snippet": " ".join(body.split())[:160],
    }


# ---------------------------------------------------------------- seed ----------------------------------------------
def _days_ago(n: int, hour: int = 10, minute: int = 0) -> datetime:
    d = datetime.now().astimezone() - timedelta(days=n)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


SEED = [
    # (days_ago, from, to, cc, subject, body)
    (7, "director", "pm", ["finance"], "Proposal #171 — signed",
     "Priya,\n\nSigned and sent back to Harbor Ridge this morning. Thanks for turning the pricing around so quickly.\n\n"
     "Let's keep the same template for #172.\n\n— M."),
    (6, "finance", "pm", [], "Re: Proposal #171 — signed",
     "Logged in the ledger, invoice goes out Friday. One thing for next time: the per-head line was rounded up on the "
     "deck but not on the sheet — the sheet is the source of truth.\n\nFinance"),
    (5, "sales", "finance", ["pm"], "Updated quote: lunchtime classes",
     "Hi both,\n\nThe vendor came back with a revised quote for the lunchtime class series (12 sessions, two instructors). "
     "It is about 6% below the first one. I will forward the PDF once they confirm the travel line.\n\nSales"),
    (4, "ops", "studio", ["pm"], "Studio B — floor sanded this weekend",
     "Studio B is closed Sat/Sun for floor work. Please move any trial classes to Studio A. Back to normal on Monday.\n\nOps"),
    (3, "studio", "ops", [], "Re: Studio B — floor sanded this weekend",
     "Moved the two Saturday trials to A, 10:00 and 11:30. Mirrors in B need a wipe after the dust settles.\n\nStudio"),
    (3, "pm", "director", [], "Harbor Ridge — kickoff recap",
     "Kickoff went well. They want the #172 proposal (3 line items + total) by Thursday; Finance is checking the sheet. "
     "Will send the PDF for signature as soon as it is ready.\n\nPriya"),
    (2, "finance", "director", [], "Q4 cash view (short)",
     "Receivables are healthy; two invoices > 30 days, both Harbor Ridge pilots. Detail at the Monday review.\n\nFinance"),
    (2, "sales", "pm", [], "Pipeline notes — week 45",
     "Three new inbound this week (two corporate wellness, one school). The school one wants lunchtime classes too — "
     "worth bundling with the vendor quote.\n\nSales"),
    (1, "ops", "finance", [], "Vendor invoice — mats and blocks",
     "Received 40 mats and 20 blocks, all good. Invoice attached to the PO in the shared folder; please pay net 30.\n\nOps"),
    (4, "pm", "sales", [], "Harbor Ridge — bundle the lunchtime classes?",
     "If the school inbound is real, can we price the lunchtime series as an add-on to #172 instead of a separate "
     "quote? Need the vendor number by Wednesday.\n\nPriya"),
    (1, "director", "sales", ["pm"], "Re: Pipeline notes — week 45",
     "Good week. Prioritise the two corporate ones; the school can wait until the Harbor Ridge pilot is signed.\n\n— M."),
    (1, "studio", "pm", [], "Instructor availability — November",
     "Two instructors free for lunchtime slots Tue/Thu; one asks for a 48 h notice for corporate bookings.\n\nStudio"),
]


def seed() -> list[dict]:
    """Put a couple of plausible older threads into every Northwind demo inbox (idempotent enough: skips a subject
    already present). Demo only: the six DEMO_PEOPLE at @DOMAIN."""
    sent = []
    for days, frm, to, cc, subject, body in SEED:
        if any(d["subject"] == subject for d in list_inbox(to)):
            continue
        sent.append(send(frm, to, subject, body, cc=cc, date=_days_ago(days, 9 + days % 7, (days * 17) % 60)))
    return sent


# ---------------------------------------------------------------- CLI -----------------------------------------------
def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("user"); p.add_argument("--since")
    p = sub.add_parser("send"); p.add_argument("from_"); p.add_argument("to"); p.add_argument("subject")
    p.add_argument("--body", default=""); p.add_argument("--attach", action="append", default=[])
    p.add_argument("--cc", action="append", default=[])
    p = sub.add_parser("find"); p.add_argument("user"); p.add_argument("subject"); p.add_argument("--attachment")
    p = sub.add_parser("fetch"); p.add_argument("user"); p.add_argument("id"); p.add_argument("name"); p.add_argument("--out")
    p = sub.add_parser("reset"); p.add_argument("user", help="login, address or 'all'")
    sub.add_parser("seed")
    sub.add_parser("users")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        out = list_inbox(a.user, a.since)
    elif a.cmd == "send":
        body = a.body if a.body != "-" else sys.stdin.read()
        out = send(a.from_, a.to.split(","), a.subject, body, a.attach, cc=a.cc)
    elif a.cmd == "find":
        wa = None if a.attachment is None else (True if a.attachment == "any" else a.attachment)
        out = find(a.user, a.subject, wa)
    elif a.cmd == "fetch":
        data = fetch_attachment(a.user, a.id, a.name)
        dest = Path(a.out or a.name)
        dest.write_bytes(data)
        out = {"written": str(dest), "bytes": len(data)}
    elif a.cmd == "reset":
        users = list(DEMO_PEOPLE) if a.user == "all" else [a.user]
        out = [reset(u) for u in users]
    elif a.cmd == "seed":
        out = seed()
    else:
        out = {u: {"address": address(u), "name": n, "desk": d} for u, (n, d) in DEMO_PEOPLE.items()}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
