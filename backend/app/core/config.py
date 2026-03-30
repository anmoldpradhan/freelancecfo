from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str
    
    # Redis
    redis_url: str
    
    # Auth
    secret_key: str
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # App
    environment: str = "development"
    
    # External APIs (optional at startup)
    gemini_api_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    frontend_url: str = "http://localhost:3000"
    sendgrid_api_key: str = ""
    aws_s3_bucket: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    telegram_bot_token: str = ""

    model_config = SettingsConfigDict(env_file="../.env", case_sensitive=False,extra="ignore")


# Single instance — import this everywhere
settings = Settings()