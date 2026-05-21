from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = Field(
        "postgresql+psycopg2://easyfinance:easyfinance@localhost:5433/easyfinance",
        alias="DATABASE_URL",
    )
    frontend_origin: str = Field("http://127.0.0.1:5190", alias="FRONTEND_ORIGIN")
    customer_provider: str = Field("easyfinance", alias="CUSTOMER_PROVIDER")

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()

