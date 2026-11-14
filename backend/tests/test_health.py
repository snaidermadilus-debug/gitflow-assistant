def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_not_found(client):
    response = client.get("/not-a-route")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_cors_does_not_allow_credentials(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-credentials" not in response.headers
