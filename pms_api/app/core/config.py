from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_SERVER: str = "localhost"
    DB_NAME: str = "lingsaa_pms"
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_TRUSTED_CONNECTION: bool = True
    DB_DRIVER: str = "ODBC Driver 17 for SQL Server"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def DATABASE_URL(self) -> str:
        driver = self.DB_DRIVER.replace(" ", "+")
        if self.DB_TRUSTED_CONNECTION:
            return f"mssql+pyodbc://@{self.DB_SERVER}/{self.DB_NAME}?driver={driver}&trusted_connection=yes"
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return f"mssql+pyodbc://{user}:{password}@{self.DB_SERVER}/{self.DB_NAME}?driver={driver}"


settings = Settings()
