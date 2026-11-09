"""Shared singletons the routers pull in. The Database is created in main.create_app
so tests can swap FLOWLINE_DB before the app is built."""

from __future__ import annotations

from fastapi import Request

from .db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db
