"""Create the initial administrator account.

Run once after migrations:  python -m app.bootstrap
Requires CERBERUS_ADMIN_PASSWORD (and optionally CERBERUS_ADMIN_USERNAME).
Idempotent: does nothing if any user already exists.
"""

import os

from sqlalchemy.orm import Session

from app.config import ConfigurationError
from app.database import SessionLocal
from app.models import Role
from app.services import user_service

MIN_ADMIN_PASSWORD_LENGTH = 12


def validate_admin_password(password: str | None) -> str:
    """Return the password if it is strong enough to create an administrator.

    The error never includes the password itself.
    """
    if not password:
        raise ConfigurationError(
            "CERBERUS_ADMIN_PASSWORD is not set. It is required to create the first administrator."
        )
    if "change-me" in password.lower():
        raise ConfigurationError(
            "CERBERUS_ADMIN_PASSWORD is a placeholder value. Replace it with a strong password."
        )
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        raise ConfigurationError(
            f"CERBERUS_ADMIN_PASSWORD must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters long."
        )
    return password


def create_initial_admin(db: Session, username: str, password: str | None) -> bool:
    """Create an administrator if the system has no users yet. Returns True if created.

    An existing system is left alone: no password is required and no account is changed.
    """
    if user_service.list_users(db):
        return False
    user_service.create_user(db, username, validate_admin_password(password), Role.administrator)
    db.commit()
    return True


def main() -> None:
    username = os.environ.get("CERBERUS_ADMIN_USERNAME", "admin")
    password = os.environ.get("CERBERUS_ADMIN_PASSWORD")

    db = SessionLocal()
    try:
        try:
            created = create_initial_admin(db, username, password)
        except ConfigurationError as exc:
            raise SystemExit(str(exc)) from None
        if created:
            print(f"created administrator {username!r}")
        else:
            print("users already exist; no admin created")
    finally:
        db.close()


if __name__ == "__main__":
    main()
