from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app"
    usda_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("USDA_FDC_API_KEY", "NUTRITION_USDA_API_KEY"),
    )
    cors_origins: list[str] = ["http://localhost:8081"]

    model_config = SettingsConfigDict(env_file=".env", env_prefix="NUTRITION_")


settings = Settings()
