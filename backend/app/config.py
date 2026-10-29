from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_LENGTH = 32
# Placeholder values from older defaults and examples. They must never sign tokens.
PLACEHOLDER_JWT_SECRETS = frozenset(
    {"dev-insecure-secret-change-me", "change-me-to-a-long-random-string"}
)
# The Fernet key that was hardcoded as a default. Samples encrypted with it stay readable only
# while it is configured, so it is rejected for new startups rather than silently reused.
PLACEHOLDER_STORAGE_KEYS = frozenset({"WRMAuPNGk41A8BPgvftkIdyOrveh1v8t33Jss2ZUDsM="})


class ConfigurationError(RuntimeError):
    """Raised at startup when required configuration is missing or unsafe.

    This is deliberately not a ValueError: pydantic wraps ValueError and would echo the
    rejected input, which here is a secret. A plain exception keeps the message clear and
    the value out of the traceback.
    """


class Settings(BaseSettings):
    """Application configuration, read from CERBERUS_-prefixed environment variables."""

    model_config = SettingsConfigDict(env_prefix="CERBERUS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./cerberus.db"
    # No default: the app refuses to start without an explicit, strong secret.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 14
    login_max_failures: int = 5
    lockout_minutes: int = 15
    reset_token_ttl_minutes: int = 30
    max_upload_bytes: int = 100 * 1024 * 1024
    sample_storage_dir: str = "./samples_store"
    # Fernet key for encrypting samples at rest. Required, no default. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    storage_key: str = ""
    allowed_file_types: str = "pe,elf,macho,zip,gzip,rar,7z,pdf,ole,script,text,binary"
    environment: str = "development"

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        if not self.jwt_secret:
            raise ConfigurationError(
                "CERBERUS_JWT_SECRET is not set. Set it to a long random value, for example: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if self.jwt_secret in PLACEHOLDER_JWT_SECRETS or "change-me" in self.jwt_secret.lower():
            raise ConfigurationError(
                "CERBERUS_JWT_SECRET is a placeholder value. Replace it with a random secret."
            )
        if len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            raise ConfigurationError(
                f"CERBERUS_JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters long."
            )
        return self

    @model_validator(mode="after")
    def _check_storage_key(self) -> "Settings":
        if not self.storage_key:
            raise ConfigurationError(
                "CERBERUS_STORAGE_KEY is not set. Set it to a Fernet key, for example: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        if self.storage_key in PLACEHOLDER_STORAGE_KEYS:
            raise ConfigurationError(
                "CERBERUS_STORAGE_KEY is a known placeholder value. Replace it with a newly "
                "generated Fernet key."
            )
        try:
            Fernet(self.storage_key.encode())
        except (ValueError, TypeError):
            # Fernet's own message can echo the key, so the error is replaced with a fixed one.
            raise ConfigurationError(
                "CERBERUS_STORAGE_KEY is not a valid Fernet key (32 url-safe base64 bytes)."
            ) from None
        return self

    @property
    def allowed_types(self) -> set[str]:
        return {t.strip() for t in self.allowed_file_types.split(",") if t.strip()}

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
