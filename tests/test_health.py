"""Bootstrap pytest — boots the FastAPI app and hits `/health` and the
static-files index at `/`.

The bootstrap ticket's `/` endpoint returned JSON; the FastAPI ticket
mounted the static-files directory at `/` instead. The placeholder
`static/index.html` ships with this map; the real frontend (from the
`build-single-page-html-js-frontend` ticket) will replace it.
"""

from fastapi.testclient import TestClient

from shopee_th.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_root_serves_placeholder_index_html() -> None:
    """The static mount at `/` serves `static/index.html` (placeholder)."""
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<title>shopee-th</title>" in resp.text
