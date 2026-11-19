import pytest
from conftest import AUTH

PROTECTED = [
    ("post", "/api/sensor_data"), ("post", "/api/sensor_data/batch"),
    ("get", "/api/current_status"), ("get", "/api/history"), ("get", "/api/aggregates"),
    ("get", "/api/forecast"), ("post", "/voice"), ("post", "/speak"),
    ("post", "/alert"), ("post", "/reset"),
]


def test_health_is_public_and_reveals_no_config(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert set(r.get_json()) == {"status", "service"}


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_routes_reject_missing_or_wrong_key(client, method, path):
    call = getattr(client, method)
    assert call(path).status_code == 401
    assert call(path, headers={"X-API-Key": "wrong"}).status_code == 401


def test_open_dev_mode_when_no_key_configured(app, client):
    app.config["API_KEY"] = ""
    assert client.get("/api/history").status_code == 200


def test_rate_limit_on_paid_endpoints(client):
    env = {"REMOTE_ADDR": "203.0.113.7"}
    codes = [client.post("/alert", json={}, headers=AUTH, environ_base=env).status_code
             for _ in range(8)]
    assert codes[:6] == [200] * 6 and codes[6:] == [429, 429]
    # another client is not affected
    assert client.post("/alert", json={}, headers=AUTH,
                       environ_base={"REMOTE_ADDR": "203.0.113.8"}).status_code == 200


@pytest.mark.parametrize("forwarded,expected", [
    ("172.17.0.1", None),            # Docker bridge
    ("10.0.0.2", None),
    ("192.168.1.20", None),
    ("127.0.0.1", None),
    ("172.217.1.1", "172.217.1.1"),  # public, despite the 172. prefix
    ("8.8.8.8, 10.0.0.1", "8.8.8.8"),
    ("not-an-ip", None),
])
def test_public_client_ip(app, forwarded, expected):
    from security import get_public_client_ip
    with app.test_request_context(headers={"X-Forwarded-For": forwarded}):
        assert get_public_client_ip() == expected


def test_device_id_is_truncated(app):
    from security import get_device_id
    with app.test_request_context(headers={"X-Device-Id": "x" * 200}):
        assert len(get_device_id()) == 64
    with app.test_request_context():
        assert get_device_id() == "default"
