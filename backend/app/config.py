from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://ai_badge:ai_badge_dev@localhost:5432/ai_badge"
    database_url_sync: str = "postgresql://ai_badge:ai_badge_dev@localhost:5432/ai_badge"

    # Auth
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 60

    # LLM Provider
    openai_api_key: str = "sk-placeholder"
    openai_base_url: str = "https://api.openai.com/v1"

    # Audio
    audio_storage_path: str = "/data/audio"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
