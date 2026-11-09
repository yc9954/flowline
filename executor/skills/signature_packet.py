"""Skill `signature_packet` v1 — Fill the deck from the sheet, export it for signature, hand it over by mail.

Thin wrapper over skills/_packet.py (one engine, three skill ids; see skills/README.md).
"""
from __future__ import annotations

from skills._packet import FILL_DECK, EXPORT, HAND_OVER, make_skill, make_title
from skills import _packet

SKILL = make_skill("signature_packet", [FILL_DECK, EXPORT, HAND_OVER])


def title(inputs: dict | None = None) -> str:
    return make_title(SKILL["id"], inputs)


def run(ctx, desktop, inputs: dict) -> None:
    _packet.run(ctx, desktop, inputs, SKILL)
