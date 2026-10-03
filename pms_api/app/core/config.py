from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Values come from environment variables or the .env file next to app/."""

    APP_NAME: str = "LINGSAA PMS API"
    APP_VERSION: str = "1.0.0"
    # development | production. Production refuses to start with the local-dev auth shortcuts switched on.
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    DB_SERVER: str = "localhost"
    DB_NAME: str = "lingsaa_pms"
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_TRUSTED_CONNECTION: bool = True
    DB_DRIVER: str = "ODBC Driver 17 for SQL Server"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE_SECONDS: int = 1800

    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    # Local-dev shortcuts until the MASTER service's token secret and claim names are confirmed.
    JWT_ENFORCE_SIGNATURE: bool = False
    ALLOW_TENANT_FROM_QUERY: bool = True
    # The PMS's own email + password login (until the MASTER login is connected) and how long a login lasts.
    DEMO_LOGIN_ENABLED: bool = True
    LOGIN_HOURS: int = 12

    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    MASTER_SERVICE_API_URL: str = "http://127.0.0.1:8009"

    # Uploaded documents. Relative paths are inside backend/pms_api. In production point this at a backed-up disk/share.
    UPLOAD_DIR: str = "storage/uploads"
    MAX_UPLOAD_MB: int = 15

    # Email alerts (app/core/mailer.py). Without SMTP_HOST, emails are saved as files in MAIL_OUTBOX_DIR.
    EMAIL_ALERTS_ENABLED: bool = True
    EMAIL_ALERT_KINDS: str = "approval,message,mention,assigned,timesheet,expense,reminder"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    SMTP_FROM: str = "LINGSAA PMS <no-reply@lingsaa.com>"
    MAIL_OUTBOX_DIR: str = "storage/outbox"
    # Where links in emails point (the web app's address).
    APP_BASE_URL: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def DATABASE_URL(self) -> str:
        driver = self.DB_DRIVER.replace(" ", "+")
        if self.DB_TRUSTED_CONNECTION:
            return f"mssql+pyodbc://@{self.DB_SERVER}/{self.DB_NAME}?driver={driver}&trusted_connection=yes"
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return f"mssql+pyodbc://{user}:{password}@{self.DB_SERVER}/{self.DB_NAME}?driver={driver}"

    @model_validator(mode="after")
    def _safe_for_production(self):
        if self.is_production:
            problems = []
            if not self.JWT_SECRET:
                problems.append("JWT_SECRET must be set")
            if not self.JWT_ENFORCE_SIGNATURE:
                problems.append("JWT_ENFORCE_SIGNATURE must be true")
            if self.ALLOW_TENANT_FROM_QUERY:
                problems.append("ALLOW_TENANT_FROM_QUERY must be false")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS cannot be *")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


settings = Settings()
