from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PasswordResetToken, RefreshToken, User
from app.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from app.services import audit
from app.services.user_service import get_by_username


class AuthError(Exception):
    """Login failed for any reason (bad credentials, locked, inactive)."""


def _is_locked(user: User, now: datetime) -> bool:
    if user.locked_until is None:
        return False
    locked_until = user.locked_until
    if locked_until.tzinfo is None:  # SQLite returns naive datetimes; assume UTC
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > now


def authenticate(db: Session, username: str, password: str, ip: str | None) -> User:
    now = datetime.now(UTC)
    user = get_by_username(db, username)

    if user is None:
        audit.record(db, "login_failed", detail=f"unknown user {username!r}", ip=ip)
        db.commit()
        raise AuthError("invalid credentials")

    if not user.is_active:
        audit.record(db, "login_denied", actor_user_id=user.id, detail="inactive", ip=ip)
        db.commit()
        raise AuthError("account is inactive")

    if _is_locked(user, now):
        audit.record(db, "login_denied", actor_user_id=user.id, detail="locked", ip=ip)
        db.commit()
        raise AuthError("account is temporarily locked")

    if not verify_password(user.hashed_password, password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
            audit.record(db, "account_locked", actor_user_id=user.id, ip=ip)
        else:
            audit.record(db, "login_failed", actor_user_id=user.id, ip=ip)
        db.commit()
        raise AuthError("invalid credentials")

    # Success: clear failure state.
    user.failed_login_count = 0
    user.locked_until = None
    audit.record(db, "login_success", actor_user_id=user.id, ip=ip)
    db.commit()
    return user


def issue_tokens(db: Session, user: User) -> tuple[str, str]:
    access = create_access_token(user.id, user.role.value)
    raw_refresh = generate_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_opaque_token(raw_refresh),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    db.commit()
    return access, raw_refresh


def refresh_access(db: Session, raw_refresh: str) -> str:
    now = datetime.now(UTC)
    token = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_opaque_token(raw_refresh))
    ).scalar_one_or_none()

    if token is None or token.revoked or _expired(token.expires_at, now):
        raise AuthError("invalid refresh token")

    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AuthError("invalid refresh token")

    return create_access_token(user.id, user.role.value)


def logout(db: Session, raw_refresh: str, actor_user_id: int, ip: str | None) -> None:
    token = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_opaque_token(raw_refresh))
    ).scalar_one_or_none()
    if token is not None:
        token.revoked = True
    audit.record(db, "logout", actor_user_id=actor_user_id, ip=ip)
    db.commit()


def invalidate_sessions(db: Session, user_id: int) -> int:
    """Revoke all of a user's refresh tokens. Returns the number revoked."""
    result = cast(
        CursorResult[Any],
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        ),
    )
    db.commit()
    return result.rowcount or 0


def request_password_reset(db: Session, username: str) -> tuple[str, datetime] | None:
    """Issue a reset token for a user. Returns None if the user does not exist."""
    user = get_by_username(db, username)
    if user is None:
        return None
    raw = generate_opaque_token()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.reset_token_ttl_minutes)
    db.add(
        PasswordResetToken(
            user_id=user.id, token_hash=hash_opaque_token(raw), expires_at=expires_at
        )
    )
    audit.record(db, "password_reset_requested", actor_user_id=user.id)
    db.commit()
    return raw, expires_at


def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> None:
    now = datetime.now(UTC)
    token = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_opaque_token(raw_token)
        )
    ).scalar_one_or_none()

    if token is None or token.used or _expired(token.expires_at, now):
        raise AuthError("invalid or expired reset token")

    user = db.get(User, token.user_id)
    if user is None:
        raise AuthError("invalid or expired reset token")

    user.hashed_password = hash_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    token.used = True
    # Password change invalidates existing sessions.
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    audit.record(db, "password_reset_completed", actor_user_id=user.id)
    db.commit()


def _expired(expires_at: datetime, now: datetime) -> bool:
    # Stored timestamps may be naive (SQLite); assume UTC when so.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now
