"""Skill `reconcile_quotes` v1 — Read the three vendor quotes, fix the row that differs, hand it over by mail.

Thin wrapper over skills/_packet.py (one engine, three skill ids; see skills/README.md).
"""
from __future__ import annotations

from skills._packet import READ_QUOTES, UPDATE_SHEET, HAND_OVER, make_skill, make_title
from skills import _packet

SKILL = make_skill("reconcile_quotes", [READ_QUOTES, UPDATE_SHEET, HAND_OVER])


def title(inputs: dict | None = None) -> str:
    return make_title(SKILL["id"], inputs)


def run(ctx, desktop, inputs: dict) -> None:
    _packet.run(ctx, desktop, inputs, SKILL)
