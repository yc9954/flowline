"""board/dist served at / with SPA fallback; /api/* never falls through to index.html."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_spa_fallback(dirs, monkeypatch):
    dist = dirs["tmp"] / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root>board</div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("FLOWLINE_BOARD_DIST", str(dist))

    import api.main

    with TestClient(api.main.create_app()) as c:
        assert c.get("/").text.startswith("<!doctype html>")
        assert c.get("/plans").text.startswith("<!doctype html>")  # client-side route
        assert c.get("/boards/northwind/expansion").text.startswith("<!doctype html>")
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/api/nope").status_code == 404  # not index.html
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/boards/northwind/status").json()["board_dist_served"] is True
        # No path traversal out of dist.
        assert c.get("/../pyproject.toml").text.startswith("<!doctype html>")


def test_cors_allows_vite_dev_server(client):
    r = client.options(
        "/api/boards/northwind/status",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
