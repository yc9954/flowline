"""Executor skills. Each module exposes SKILL (SCHEMA §11 Skill) and run(ctx, desktop, inputs)."""
from __future__ import annotations

import importlib


def load(skill_id: str):
    return importlib.import_module(f"skills.{skill_id}")
