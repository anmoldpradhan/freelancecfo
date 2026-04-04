from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> str:
    """Encrypt a plaintext string. Returns a URL-safe base64 token."""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    """Decrypt a Fernet token. Returns None if the token is invalid
    (e.g. legacy plaintext value stored before encryption was added)."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        return None
