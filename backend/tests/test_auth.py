import pytest


@pytest.mark.asyncio
async def test_register_success(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "test@example.com",
        "password": "SecurePass1"
    })
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "SecurePass1"}
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_weak_password(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "weak@example.com",
        "password": "weak"
    })
    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_login_success(client):
    await client.post("/api/v1/auth/register", json={
        "email": "login@example.com",
        "password": "SecurePass1"
    })
    response = await client.post("/api/v1/auth/login", json={
        "email": "login@example.com",
        "password": "SecurePass1"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "email": "wrong@example.com",
        "password": "SecurePass1"
    })
    response = await client.post("/api/v1/auth/login", json={
        "email": "wrong@example.com",
        "password": "WrongPass1"
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "logout@example.com",
        "password": "SecurePass1"
    })
    refresh_token = reg.json()["refresh_token"]
    response = await client.post("/api/v1/auth/logout", json={
        "refresh_token": refresh_token
    })
    assert response.status_code == 204

