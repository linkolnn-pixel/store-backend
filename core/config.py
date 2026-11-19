from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Store Backend"
    DATABASE_URL: str
    REDIS_URL: str

    WAREHOUSE_URL: str
    DEFAULT_WAREHOUSE_ID: int

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    SERVICE_API_KEY: str

    SECRET_KEY: str
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str

    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str
    EMBEDDING_MODEL: str
    CHAT_MODEL: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()