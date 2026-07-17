from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class DeploymentMode(str, Enum):
    DEVELOPMENT = "development"
    PRIVATE_SINGLE_USER = "private_single_user"
    PRODUCTION = "production"
    TEST = "test"


class ProcessMode(str, Enum):
    RUNTIME = "runtime"
    CANARY = "canary"


# Production authentication is deliberately an extension point. This build does
# not advertise a provider that it does not actually implement.
SUPPORTED_PRODUCTION_AUTH_PROVIDERS: frozenset[str] = frozenset()


class Settings(BaseSettings):
    deployment_mode: DeploymentMode
    process_mode: ProcessMode = ProcessMode.RUNTIME
    database_url: str
    usda_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("USDA_FDC_API_KEY", "NUTRITION_USDA_API_KEY"),
    )
    cors_origins: list[str] = ["http://localhost:8081"]

    private_auth_secret: SecretStr | None = None
    private_user_id: UUID | None = None
    private_user_email: str | None = None
    private_user_display_name: str = "Private User"
    private_user_create_if_missing: bool = False

    production_auth_provider: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NUTRITION_",
        hide_input_in_errors=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_release_configuration(self) -> Settings:
        try:
            url = make_url(self.database_url)
        except (ArgumentError, TypeError, ValueError) as exc:
            raise ValueError(
                "NUTRITION_DATABASE_URL must be a valid SQLAlchemy database URL"
            ) from exc
        if not url.drivername or (url.get_backend_name() != "sqlite" and not url.database):
            raise ValueError("NUTRITION_DATABASE_URL must identify a database")

        if self.deployment_mode is DeploymentMode.PRIVATE_SINGLE_USER:
            if (
                self.private_auth_secret is None
                or len(self.private_auth_secret.get_secret_value()) < 32
            ):
                raise ValueError(
                    "private_single_user mode requires NUTRITION_PRIVATE_AUTH_SECRET "
                    "with at least 32 characters"
                )
            if self.private_user_id is None or not self.private_user_email:
                raise ValueError(
                    "private_single_user mode requires NUTRITION_PRIVATE_USER_ID and "
                    "NUTRITION_PRIVATE_USER_EMAIL"
                )

        if self.deployment_mode is DeploymentMode.PRODUCTION:
            if self.production_auth_provider not in SUPPORTED_PRODUCTION_AUTH_PROVIDERS:
                raise ValueError(
                    "production mode requires a production authentication provider; "
                    "none is installed in this build"
                )

        if self.process_mode is ProcessMode.CANARY:
            if self.deployment_mode is not DeploymentMode.PRIVATE_SINGLE_USER:
                raise ValueError("canary process mode requires private_single_user deployment mode")
            if self.private_user_create_if_missing:
                raise ValueError(
                    "canary process mode requires NUTRITION_PRIVATE_USER_CREATE_IF_MISSING=false"
                )
        return self


def get_settings() -> Settings:
    return settings


settings = Settings()
