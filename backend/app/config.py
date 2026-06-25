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
    jwt_secret: str = Field("change-me-in-production", alias="JWT_SECRET")
    access_token_expire_minutes: int = Field(480, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    license_control_url: str | None = Field(None, alias="LICENSE_CONTROL_URL")
    license_tenant_id: str | None = Field(None, alias="LICENSE_TENANT_ID")
    license_product: str = Field("easysales", alias="LICENSE_PRODUCT")
    license_installation_id: str | None = Field(None, alias="LICENSE_INSTALLATION_ID")
    license_gateway_fingerprint: str | None = Field(None, alias="LICENSE_GATEWAY_FINGERPRINT")
    license_environment: str = Field("production", alias="LICENSE_ENVIRONMENT")
    license_offline_grace_days: int = Field(7, alias="LICENSE_OFFLINE_GRACE_DAYS")

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
