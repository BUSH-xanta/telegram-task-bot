from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: SecretStr
    bot_owner_id: int
    allowed_chat_id: int
    database_url: str
    redis_url: str
    timezone: str = "Europe/Moscow"
    backup_retention_days: int = Field(default=14, ge=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if value != "Europe/Moscow":
            raise ValueError("Business timezone must be Europe/Moscow")
        ZoneInfo(value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
