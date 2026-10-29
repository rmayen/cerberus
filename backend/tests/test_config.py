import secrets

import pytest

from app.config import ConfigurationError, Settings


def make_settings(**overrides: str) -> Settings:
    # Ignore any .env file so each test controls exactly what is configured.
    return Settings(_env_file=None, **overrides)


def test_missing_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CERBERUS_JWT_SECRET", raising=False)
    with pytest.raises(ConfigurationError, match="CERBERUS_JWT_SECRET is not set"):
        make_settings()


def test_empty_secret_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="is not set"):
        make_settings(jwt_secret="")


@pytest.mark.parametrize(
    "secret",
    [
        "dev-insecure-secret-change-me",
        "change-me-to-a-long-random-string",
        "CHANGE-ME-please-use-a-real-secret-value-here",
    ],
)
def test_placeholder_secret_is_rejected(secret: str) -> None:
    with pytest.raises(ConfigurationError, match="placeholder"):
        make_settings(jwt_secret=secret)


def test_short_secret_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="at least 32 characters"):
        make_settings(jwt_secret="x" * 31)


def test_rejection_message_does_not_echo_the_secret() -> None:
    secret = "short-but-private"
    with pytest.raises(ConfigurationError) as excinfo:
        make_settings(jwt_secret=secret)
    assert secret not in str(excinfo.value)


def test_strong_random_secret_is_accepted() -> None:
    secret = secrets.token_urlsafe(48)
    assert make_settings(jwt_secret=secret).jwt_secret == secret


def test_secret_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = secrets.token_urlsafe(48)
    monkeypatch.setenv("CERBERUS_JWT_SECRET", secret)
    assert Settings(_env_file=None).jwt_secret == secret


TEST_STORAGE_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


def test_missing_storage_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CERBERUS_STORAGE_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="CERBERUS_STORAGE_KEY is not set"):
        make_settings(jwt_secret=secrets.token_urlsafe(48))


def test_old_default_storage_key_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="known placeholder"):
        make_settings(
            jwt_secret=secrets.token_urlsafe(48),
            storage_key="WRMAuPNGk41A8BPgvftkIdyOrveh1v8t33Jss2ZUDsM=",
        )


@pytest.mark.parametrize("storage_key", ["not-a-fernet-key", "AAECAwQF", "A" * 44 + "!"])
def test_malformed_storage_key_is_rejected(storage_key: str) -> None:
    with pytest.raises(ConfigurationError, match="not a valid Fernet key"):
        make_settings(jwt_secret=secrets.token_urlsafe(48), storage_key=storage_key)


def test_malformed_storage_key_error_does_not_echo_the_key() -> None:
    storage_key = "not-a-fernet-key-but-private"
    with pytest.raises(ConfigurationError) as excinfo:
        make_settings(jwt_secret=secrets.token_urlsafe(48), storage_key=storage_key)
    assert storage_key not in str(excinfo.value)


def test_valid_storage_key_is_accepted() -> None:
    settings = make_settings(jwt_secret=secrets.token_urlsafe(48), storage_key=TEST_STORAGE_KEY)
    assert settings.storage_key == TEST_STORAGE_KEY
