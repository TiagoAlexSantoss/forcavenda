from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_version: str = Field("0.1.0-beta.4", alias="APP_VERSION")
    release_channel: str = Field("pilot", alias="RELEASE_CHANNEL")
    build_sha: str = Field("development", alias="BUILD_SHA")
    database_url: str = Field(
        "postgresql+psycopg2://easyfinance:easyfinance@localhost:5433/easyfinance",
        alias="DATABASE_URL",
    )
    frontend_origin: str = Field("http://127.0.0.1:5190", alias="FRONTEND_ORIGIN")
    customer_provider: str = Field("easyfinance", alias="CUSTOMER_PROVIDER")
    jwt_secret: str = Field("change-me-in-production", alias="JWT_SECRET")
    app_encryption_key: str = Field("change-me-app-encryption", alias="APP_ENCRYPTION_KEY")
    access_token_expire_minutes: int = Field(480, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    license_control_url: str | None = Field(None, alias="LICENSE_CONTROL_URL")
    license_tenant_id: str | None = Field(None, alias="LICENSE_TENANT_ID")
    license_product: str = Field("easysales", alias="LICENSE_PRODUCT")
    license_installation_id: str | None = Field(None, alias="LICENSE_INSTALLATION_ID")
    license_gateway_fingerprint: str | None = Field(None, alias="LICENSE_GATEWAY_FINGERPRINT")
    license_environment: str = Field("production", alias="LICENSE_ENVIRONMENT")
    license_offline_grace_days: int = Field(7, alias="LICENSE_OFFLINE_GRACE_DAYS")
    jsreport_url: str = Field("http://localhost:5488", alias="JSREPORT_URL")
    jsreport_username: str | None = Field(None, alias="JSREPORT_USERNAME")
    jsreport_password: str | None = Field(None, alias="JSREPORT_PASSWORD")
    evolution_base_url: str = Field("http://localhost:8081", alias="EVOLUTION_BASE_URL")
    evolution_api_key: str = Field("change-me-evolution-local", alias="EVOLUTION_API_KEY")

    class Config:
        env_file = str(BACKEND_DIR / ".env")
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
