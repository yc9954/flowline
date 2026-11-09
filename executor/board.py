"""The board block a run carries (track G1 adds it to `POST /runs`):

    board: { id, name, mail_domain, mail_window_title?, people: [{id, role, email, name?}] }

Skills resolve mail recipients by ROLE from this block (the approver, finance, the person
the run works for) and take the mail domain, the "send only inside @<mail_domain>" rule and
the webmail window title from it.  When the block is absent the Northwind demo values apply,
so every demo command keeps working unchanged.

    b = Board.from_run(run)                 # run.board may be None → DEFAULT (Northwind)
    b.email_for_role("Director")            # 'director@northwind.local' (None when no such role)
    b.approver_email()                      # Director, else CEO, else Owner
    b.sender_for(run.target, run.person_id) # the person's own address (by id, else demo desk number, else the PM)
    b.role_of(email)                        # 'Ops' — the label for the mail subject tail
    b.mail_window_title                     # 'Northwind Mail :: Inbox'
    b.mail_configured()                     # IMAP checks possible? (mail_domain + FLOWLINE_MAIL_HOST)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

DEFAULT_DOMAIN = os.environ.get("FLOWLINE_MAIL_DOMAIN", "northwind.local")

# The Northwind demo (MAIL.md people, data/people.json ids): login ↔ desk ↔ role.
DEMO_LOGINS = ["pm", "finance", "sales", "ops", "studio", "director"]            # index i ↔ desk i+1
DEMO_ROLE = {"pm": "PM", "finance": "Finance", "sales": "Sales", "ops": "Ops", "studio": "Studio", "director": "Director"}
DEMO_PERSON_IDS = {"pm": "pm-1", "finance": "fin-1", "sales": "sales-1", "ops": "ops-1", "studio": "studio-1", "director": "asst-1"}
DEMO_NAMES = {"pm": "Dana Whitfield", "finance": "Marcus Reyes", "sales": "Priya Natarajan", "ops": "Tomás Herrera",
              "studio": "Studio Manager", "director": "Northwind Director"}

DEFAULT = {
    "id": "northwind",
    "name": "Northwind",
    "mail_domain": DEFAULT_DOMAIN,
    "mail_window_title": "Northwind Mail :: Inbox",
    "people": [{"id": DEMO_PERSON_IDS[l], "role": DEMO_ROLE[l], "email": f"{l}@{DEFAULT_DOMAIN}", "name": DEMO_NAMES[l]}
               for l in DEMO_LOGINS],
}

# role aliases the skills ask for → the roles a board may carry (SCHEMA Role enum + a few labels boards use)
ROLE_ALIASES = {
    "approver": ["Director", "CEO", "Owner"],
    "director": ["Director", "CEO", "Owner"],
    "finance": ["Finance", "Accounting", "Controller"],
    "pm": ["PM", "Project Manager"],
}


@dataclass
class Board:
    id: str
    name: str
    mail_domain: str
    people: list[dict] = field(default_factory=list)
    window_title: str | None = None
    absent: bool = False          # True when the run carried no board block (demo defaults in use)

    # ---------------------------------------------------------------- construction
    @classmethod
    def from_block(cls, block: dict | None) -> "Board":
        if not block or not isinstance(block, dict):
            d = DEFAULT
            return cls(id=d["id"], name=d["name"], mail_domain=d["mail_domain"], people=list(d["people"]),
                       window_title=d["mail_window_title"], absent=True)
        people = []
        for p in block.get("people") or []:
            if not isinstance(p, dict) or not p.get("email"):
                continue
            people.append({"id": str(p.get("id") or ""), "role": str(p.get("role") or ""), "email": str(p["email"]).strip(),
                           "name": str(p.get("name") or "")})
        domain = str(block.get("mail_domain") or "").strip().lstrip("@")
        if not domain and people:  # a board that names people but no domain: take it from their addresses
            domain = people[0]["email"].rsplit("@", 1)[-1]
        return cls(id=str(block.get("id") or ""), name=str(block.get("name") or block.get("id") or "").strip(),
                   mail_domain=domain, people=people, window_title=block.get("mail_window_title") or None)

    @classmethod
    def from_run(cls, run) -> "Board":
        return cls.from_block(getattr(run, "board", None) if run is not None else None)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "mail_domain": self.mail_domain, "mail_window_title": self.mail_window_title,
                "people": list(self.people), "absent": self.absent}

    # ---------------------------------------------------------------- people
    def person(self, person_id: str | None) -> dict | None:
        if not person_id:
            return None
        pid = str(person_id).strip().lower()
        return next((p for p in self.people if p["id"].lower() == pid), None)

    def by_email(self, email: str | None) -> dict | None:
        if not email:
            return None
        e = email.strip().lower()
        return next((p for p in self.people if p["email"].lower() == e), None)

    def email_for_role(self, role: str) -> str | None:
        """First person holding `role` (case-insensitive; aliases such as 'approver' → Director/CEO/Owner)."""
        wanted = ROLE_ALIASES.get(role.strip().lower(), [role])
        for w in wanted:
            for p in self.people:
                if p["role"].lower() == w.lower():
                    return p["email"]
        return None

    def approver_email(self) -> str | None:
        return self.email_for_role("approver")

    def finance_email(self) -> str | None:
        return self.email_for_role("finance")

    def pm_email(self) -> str | None:
        return self.email_for_role("pm")

    def sender_for(self, target: str | None, person_id: str | None) -> str | None:
        """The address a run sends from: the person's own (by id), else — demo desks only — the desk's login,
        else the PM's, else the first person's."""
        p = self.person(person_id)
        if p:
            return p["email"]
        if person_id:  # a person id that names a demo login ("finance-1", "ops@…")
            low = str(person_id).lower()
            for login in DEMO_LOGINS:
                if low == login or low.startswith(login + "-") or low.startswith(login + "@"):
                    e = f"{login}@{self.mail_domain}"
                    if self.absent or self.by_email(e):
                        return e
        if self.absent:
            m = re.search(r"(\d+)", target or "")
            n = int(m.group(1)) if m else 0
            if 1 <= n <= len(DEMO_LOGINS):
                return f"{DEMO_LOGINS[n - 1]}@{self.mail_domain}"
        return self.pm_email() or (self.people[0]["email"] if self.people else None)

    def role_of(self, email: str | None) -> str:
        """The role label for an address ('Ops'); demo logins resolve even without a people entry."""
        p = self.by_email(email)
        if p and p["role"]:
            return p["role"]
        local = (email or "").split("@")[0].lower()
        return DEMO_ROLE.get(local, local.title() or "PM")

    def login(self, email: str | None) -> str:
        return (email or "").split("@")[0]

    def inside(self, email: str | None) -> bool:
        return bool(email) and email.rsplit("@", 1)[-1].lower() == self.mail_domain.lower()

    # ---------------------------------------------------------------- mail
    @property
    def mail_window_title(self) -> str:
        return self.window_title or f"{self.name} Mail :: Inbox"

    def mail_configured(self) -> bool:
        """IMAP verification is possible: a mail domain, and a mail server — FLOWLINE_MAIL_HOST set explicitly, or the
        Northwind demo (block absent: localhost/tunnel as before, see MAIL.md)."""
        if not self.mail_domain:
            return False
        return bool(os.environ.get("FLOWLINE_MAIL_HOST")) or self.absent


def doc_label(deck: str | None, proposal=None) -> str:
    """How a run names the document in titles: 'proposal #172' for the demo decks (inputs.proposal or a
    proposal-<n> basename), otherwise the deck's basename without extension."""
    if proposal:
        return f"proposal #{int(proposal)}"
    base = (deck or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = re.fullmatch(r"proposal[-_ ]?(\d+)", base, re.I)
    if m:
        return f"proposal #{m.group(1)}"
    return base or "the deck"


def subject_label(deck: str | None, proposal=None) -> str:
    """The document in a mail subject: 'Proposal 172' for the demo decks, else the basename."""
    lab = doc_label(deck, proposal)
    m = re.fullmatch(r"proposal #(\d+)", lab)
    return f"Proposal {m.group(1)}" if m else lab
