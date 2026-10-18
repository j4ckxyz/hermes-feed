import importlib.util
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

API_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FEED_DB", str(tmp_path / "feed.db"))
    spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_feed", API_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = fastapi.FastAPI()
    app.include_router(module.router, prefix="/api/plugins/feed")
    return TestClient(app)


def test_interest_and_item_flow(client):
    r = client.post("/api/plugins/feed/interests", json={"label": "Formula 1", "keywords": ["F1"]})
    assert r.status_code == 200 and r.json()["state"] == "active"
    interest_id = r.json()["id"]

    from hermes_feed.store import open_store
    with open_store() as s:
        item_id = s.add_item(title="Race recap", summary_md="[Link](https://f1.com)", url="https://f1.com/r",
                             interest_labels=["Formula 1"])["id"]

    items = client.get("/api/plugins/feed/items").json()
    assert items["items"][0]["interests"][0]["label"] == "Formula 1"
    assert client.get(f"/api/plugins/feed/items?interest={interest_id}").json()["items"]

    assert client.post(f"/api/plugins/feed/items/{item_id}/react", json={"kind": "like"}).json()["liked"]
    assert client.post(f"/api/plugins/feed/items/{item_id}/react", json={"kind": "bogus"}).status_code == 400
    assert client.post("/api/plugins/feed/items/999/react", json={"kind": "like"}).status_code == 404

    assert client.patch(f"/api/plugins/feed/interests/{interest_id}", json={"muted": True}).json()["state"] == "muted"
    assert client.get("/api/plugins/feed/items?cursor=bad").status_code == 400

    status = client.get("/api/plugins/feed/status").json()
    assert status["counts"]["items"] == 1
    assert client.post("/api/plugins/feed/visit").json()["previous_visit_at"] == 0
    assert client.post(f"/api/plugins/feed/items/{item_id}/react", json={"kind": "dismiss"}).json()["dismissed"]
    assert client.get("/api/plugins/feed/items").json()["items"] == []
    assert not client.post(f"/api/plugins/feed/items/{item_id}/react", json={"kind": "undismiss"}).json()["dismissed"]

    pref = client.post("/api/plugins/feed/preferences", json={"text": "Prefer UK sources"}).json()
    assert client.get("/api/plugins/feed/preferences").json()["preferences"][0]["source"] == "dashboard"
    assert client.delete(f"/api/plugins/feed/preferences/{pref['id']}").json() == {"ok": True}
    assert client.post("/api/plugins/feed/preferences", json={"text": " "}).status_code == 400
    assert client.put("/api/plugins/feed/brief", json={"text": " Calm tone "}).json() == {"brief": "Calm tone"}
    assert client.get("/api/plugins/feed/brief").json() == {"brief": "Calm tone"}
    assert client.delete(f"/api/plugins/feed/interests/{interest_id}").json() == {"ok": True}
