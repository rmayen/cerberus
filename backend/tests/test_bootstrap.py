import pytest
from sqlalchemy.orm import Session

from app import bootstrap
from app.bootstrap import create_initial_admin
from app.config import ConfigurationError
from app.models import Role
from app.security import verify_password
from app.services import user_service


def test_creates_admin_when_empty(db_session: Session) -> None:
    created = create_initial_admin(db_session, "root", "root-password-1")
    assert created is True

    user = user_service.get_by_username(db_session, "root")
    assert user is not None
    assert user.role == Role.administrator


def test_is_idempotent(db_session: Session) -> None:
    assert create_initial_admin(db_session, "root", "root-password-1") is True
    # A second call is a no-op because a user now exists.
    assert create_initial_admin(db_session, "other", "other-password-1") is False
    assert user_service.get_by_username(db_session, "other") is None


# Test-only credentials. Never used outside the test suite.
TEST_ADMIN_PASSWORD = "Test-only-admin-pass-2026"


def test_missing_password_is_rejected_when_creating(db_session: Session) -> None:
    with pytest.raises(ConfigurationError, match="CERBERUS_ADMIN_PASSWORD is not set"):
        create_initial_admin(db_session, "root", None)
    assert user_service.list_users(db_session) == []


def test_empty_password_is_rejected(db_session: Session) -> None:
    with pytest.raises(ConfigurationError, match="is not set"):
        create_initial_admin(db_session, "root", "")
    assert user_service.list_users(db_session) == []


def test_placeholder_password_is_rejected(db_session: Session) -> None:
    with pytest.raises(ConfigurationError, match="placeholder"):
        create_initial_admin(db_session, "root", "change-me-admin-password")
    assert user_service.list_users(db_session) == []


def test_short_password_is_rejected(db_session: Session) -> None:
    with pytest.raises(ConfigurationError, match="at least 12 characters"):
        create_initial_admin(db_session, "root", "a" * 11)
    assert user_service.list_users(db_session) == []


def test_rejection_does_not_echo_the_password(db_session: Session) -> None:
    weak = "weak-priv"  # 9 characters: below the minimum, so it is rejected
    with pytest.raises(ConfigurationError) as excinfo:
        create_initial_admin(db_session, "root", weak)
    assert weak not in str(excinfo.value)


def test_strong_password_creates_admin_with_that_password(db_session: Session) -> None:
    assert create_initial_admin(db_session, "root", TEST_ADMIN_PASSWORD) is True
    user = user_service.get_by_username(db_session, "root")
    assert user is not None
    assert verify_password(user.hashed_password, TEST_ADMIN_PASSWORD)


def test_existing_system_needs_no_password_and_is_unchanged(db_session: Session) -> None:
    create_initial_admin(db_session, "root", TEST_ADMIN_PASSWORD)
    before = user_service.get_by_username(db_session, "root")
    assert before is not None
    original_hash = before.hashed_password

    # With users present, a missing or weak password is ignored, not validated or applied.
    assert create_initial_admin(db_session, "root", None) is False
    assert create_initial_admin(db_session, "root", "change-me-admin-password") is False

    after = user_service.get_by_username(db_session, "root")
    assert after is not None
    assert after.hashed_password == original_hash
    assert verify_password(after.hashed_password, TEST_ADMIN_PASSWORD)


def test_main_exits_without_creating_when_password_missing(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap, "SessionLocal", lambda: db_session)
    monkeypatch.delenv("CERBERUS_ADMIN_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="CERBERUS_ADMIN_PASSWORD is not set"):
        bootstrap.main()
    assert user_service.list_users(db_session) == []


def test_main_exits_on_weak_password_without_echoing_it(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    weak = "weak-pw"  # 7 characters: below the minimum, so it is rejected
    monkeypatch.setattr(bootstrap, "SessionLocal", lambda: db_session)
    monkeypatch.setenv("CERBERUS_ADMIN_PASSWORD", weak)
    with pytest.raises(SystemExit) as excinfo:
        bootstrap.main()
    assert weak not in str(excinfo.value)
    assert user_service.list_users(db_session) == []
