import pytest
from app.models.user import User


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


@pytest.mark.asyncio
async def test_refresh_success(client):
    reg = await client.post("/api/v1/auth/register", json={
        "email": "refresh@example.com",
        "password": "SecurePass1"
    })
    refresh_token = reg.json()["refresh_token"]
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_invalid_token(client):
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": "not.a.valid.token"
    })
    assert response.status_code == 401
    assert "Invalid or expired" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_wrong_token_type(client):
    """Passing an access token to /refresh should be rejected."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "wrongtype@example.com",
        "password": "SecurePass1"
    })
    access_token = reg.json()["access_token"]
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": access_token
    })
    assert response.status_code == 401
    assert "Not a refresh token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_after_logout(client):
    """Refresh token should be invalid after logout."""
    reg = await client.post("/api/v1/auth/register", json={
        "email": "afterlogout@example.com",
        "password": "SecurePass1"
    })
    refresh_token = reg.json()["refresh_token"]
    await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_email(client):
    response = await client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com",
        "password": "SecurePass1"
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_no_uppercase(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "upper@example.com",
        "password": "weakpass1"  # 8+ chars, has number, no uppercase
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_no_number(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "number@example.com",
        "password": "Weakpassword"  # 8+ chars, has uppercase, no number
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_inactive_user(client, db_session):
    """Deactivated users should be rejected on login."""
    from sqlalchemy import select
    await client.post("/api/v1/auth/register", json={
        "email": "inactive@example.com",
        "password": "SecurePass1"
    })
    result = await db_session.execute(
        select(User).where(User.email == "inactive@example.com")
    )
    user = result.scalar_one()
    user.is_active = False
    await db_session.commit()

    response = await client.post("/api/v1/auth/login", json={
        "email": "inactive@example.com",
        "password": "SecurePass1"
    })
    assert response.status_code == 403

