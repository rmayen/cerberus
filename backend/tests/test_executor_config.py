"""CERBERUS_EXECUTOR_MODULES is a test seam: production refuses it and only tests.* is accepted."""

import secrets

import pytest
from cryptography.fernet import Fernet

from app.config import ConfigurationError, Settings


def _settings(**overrides: str) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=secrets.token_urlsafe(48),
        storage_key=Fernet.generate_key().decode(),
        **overrides,
    )


def test_production_refuses_executor_modules() -> None:
    with pytest.raises(ConfigurationError, match="must not be set in production"):
        _settings(environment="production", executor_modules="tests.executor_fixtures")


@pytest.mark.parametrize(
    "value",
    ["os", "app.services.job_service", "tests", "tests.x;import os", "tests..x", "../tests.x"],
)
def test_only_tests_package_modules_are_accepted(value: str) -> None:
    with pytest.raises(ConfigurationError, match="only name modules in the tests package"):
        _settings(executor_modules=value)


def test_fixture_module_is_accepted_outside_production() -> None:
    settings = _settings(executor_modules="tests.executor_fixtures")
    assert settings.executor_module_names == ["tests.executor_fixtures"]


def test_production_without_the_seam_starts() -> None:
    assert _settings(environment="production", executor_modules="").executor_module_names == []
