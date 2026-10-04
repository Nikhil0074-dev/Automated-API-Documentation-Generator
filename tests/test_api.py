import pytest
from fastapi.testclient import TestClient

from app.main import app

AUTH = {"X-API-Key": "change-me"}
NEW = {"name": "Desk Lamp", "price": 19.99, "in_stock": True}


@pytest.fixture()
def client():
    return TestClient(app)


def test_list_and_filter(client):
    assert len(client.get("/products").json()) == 2
    assert [p["name"] for p in client.get("/products", params={"in_stock": False}).json()] == ["USB-C Hub"]
    assert len(client.get("/products", params={"limit": 1}).json()) == 1


def test_get_product_and_404(client):
    assert client.get("/products/1").json()["name"] == "Wireless Mouse"
    resp = client.get("/products/999")
    assert resp.status_code == 404 and resp.json() == {"detail": "Product not found"}


def test_write_requires_api_key(client):
    assert client.post("/products", json=NEW).status_code == 401
    assert client.post("/products", json=NEW, headers={"X-API-Key": "wrong"}).status_code == 401


def test_create_update_delete(client):
    created = client.post("/products", json=NEW, headers=AUTH)
    assert created.status_code == 201
    pid = created.json()["id"]
    updated = client.put(f"/products/{pid}", json={**NEW, "price": 25.0}, headers=AUTH)
    assert updated.status_code == 200 and updated.json()["price"] == 25.0
    assert client.delete(f"/products/{pid}", headers=AUTH).status_code == 204
    assert client.get(f"/products/{pid}").status_code == 404
    assert client.delete(f"/products/{pid}", headers=AUTH).status_code == 404


def test_validation_error(client):
    assert client.post("/products", json={"name": "", "price": -1}, headers=AUTH).status_code == 422
