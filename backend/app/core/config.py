from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App
    APP_NAME: str = "NodeLinker"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://nodelinker:nodelinker@localhost:5432/nodelinker"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Cookie names
    ACCESS_TOKEN_COOKIE: str = "access_token"
    REFRESH_TOKEN_COOKIE: str = "refresh_token"

    # OIDC (optional – set to enable; used for web UI access authentication)
    OIDC_ENABLED: bool = False
    OIDC_PROVIDER_NAME: str = "oidc"
    OIDC_CLIENT_ID: Optional[str] = None
    OIDC_CLIENT_SECRET: Optional[str] = None
    OIDC_DISCOVERY_URL: Optional[str] = None  # e.g. https://accounts.google.com/.well-known/openid-configuration
    OIDC_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oidc/callback"
    OIDC_SCOPES: str = "openid email profile"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # HashiCorp Vault (used for Ansible SSH credential storage)
    VAULT_URL: str = "http://localhost:8200"
    VAULT_TOKEN: Optional[str] = None
    VAULT_MOUNT_PATH: str = "secret"  # KV v2 mount path

    # Job log storage (logs are streamed via Redis; persisted here after completion)
    # LOG_STORAGE_TYPE: "local" stores to local FS; "s3" stores to S3-compatible storage
    LOG_STORAGE_TYPE: str = "local"
    LOG_STORAGE_BASE_PATH: str = "/var/log/nodelinker"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()
