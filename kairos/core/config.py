from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    # App
    KAIROS_ENV: str = "development"
    KAIROS_SECRET_KEY: str = "change-me-in-production"
    KAIROS_API_PORT: int = 8000

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://kairos:kairos@localhost:5432/kairos"

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    FRONTEND_URL: str = "http://localhost:3000/"

    # Optional
    LOG_LEVEL: str = "DEBUG"
    CORS_ORIGINS: str = "http://localhost:3000,https://kairos.clupai.com"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]


settings = Settings()
