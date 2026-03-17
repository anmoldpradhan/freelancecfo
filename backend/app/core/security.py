from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.core.config import settings

# bcrypt context — handles hashing and verification
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str) -> str:
    """
    subject = user UUID as string.
    Short-lived — 30 minutes by default.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """
    Long-lived — 7 days by default.
    Stored in Redis so it can be invalidated on logout.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Raises JWTError if token is invalid or expired.
    Returns the full payload dict.
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise