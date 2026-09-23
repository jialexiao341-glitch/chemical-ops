"""密码哈希和 JWT 令牌工具。"""

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets

import jwt

from app.core.config import get_settings


HASH_SCHEME = "pbkdf2_sha256"
HASH_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    """使用带随机盐的 PBKDF2-SHA256 生成密码哈希。"""

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, HASH_ITERATIONS)
    return "$".join(
        (
            HASH_SCHEME,
            str(HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """校验明文密码是否匹配数据库中的哈希。"""

    try:
        scheme, iterations_text, salt_text, digest_text = encoded_hash.split("$", 3)
        if scheme != HASH_SCHEME:
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    """为用户生成带过期时间的 JWT 访问令牌。"""

    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": str(user_id), "ver": token_version, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    """解码 JWT 并返回用户 ID；令牌非法或过期时抛出异常。"""

    user_id, _ = decode_access_token_claims(token)
    return user_id


def decode_access_token_claims(token: str) -> tuple[int, int]:
    """解码并校验令牌用户 ID 和会话版本；旧令牌按版本 0 兼容。"""

    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    subject = payload.get("sub")
    if not subject or not str(subject).isdigit():
        raise jwt.InvalidTokenError("令牌缺少有效用户 ID")
    token_version = payload.get("ver", 0)
    if isinstance(token_version, bool) or not isinstance(token_version, int) or token_version < 0:
        raise jwt.InvalidTokenError("令牌缺少有效会话版本")
    return int(subject), token_version
