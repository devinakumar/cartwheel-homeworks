"""Offline authentication tests for the HW2 endpoints."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from server import app as server_app


@pytest.fixture
def client(world, tmp_path, monkeypatch):
    monkeypatch.setattr(server_app, "_SESSIONS", {})
    monkeypatch.setattr(server_app, "SESSIONS_DB", tmp_path / "sessions.db")
    # Without a context manager, TestClient does not start the Langfuse lifespan.
    return TestClient(server_app.app)


def test_session_rejects_role_different_from_database(client):
    response = client.post("/sessions", json={"user_id": 1, "role": "support"})

    assert response.status_code == 403
    assert response.json()["detail"] == "role does not match stored user role"
    assert server_app._SESSIONS == {}


def test_token_cannot_authorize_another_session(client, monkeypatch):
    runner = AsyncMock(side_effect=AssertionError("unauthorized request ran the agent"))
    monkeypatch.setattr(server_app.Runner, "run", runner)
    first = client.post("/sessions", json={"user_id": 1, "role": "shopper"})
    second = client.post("/sessions", json={"user_id": 2, "role": "shopper"})
    assert first.status_code == second.status_code == 200
    first_session, second_session = first.json(), second.json()

    response = client.post(
        f"/sessions/{second_session['session_id']}/messages",
        headers={"Authorization": f"Bearer {first_session['token']}"},
        json={"message": "Show my recent orders."},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "token is for another session"
    runner.assert_not_awaited()
