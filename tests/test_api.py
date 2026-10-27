from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_building_not_found():
    response = client.get("/buildings/not_exists")

    assert response.status_code == 404


def test_invalid_nearby_radius():
    response = client.get(
        "/facilities/nearby",
        params={
            "longitude": 116.3006,
            "latitude": 39.9005,
            "radius_m": -1,
        },
    )

    assert response.status_code == 422