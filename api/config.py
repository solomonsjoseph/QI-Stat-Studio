from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet as _Fernet


class Settings(BaseSettings):
    ai_provider: str = "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    local_api_base: str = "http://localhost:11434"
    local_api_key: str = ""
    local_model: str = "llama3.1"
    secret_key: str = "dev-secret-change-in-prod"
    db_url: str = Field(
        default="sqlite:///./qi_stat_studio.db",
        validation_alias=AliasChoices("DB_URL", "DATABASE_URL", "db_url"),
    )
    fernet_key: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_email: str = "qi-stat-studio@example.com"
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173"
    environment: str = "development"

    @property
    def fernet(self) -> "_Fernet":
        if not self.fernet_key:
            raise RuntimeError(
                'FERNET_KEY is required in .env — generate with: '
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        return _Fernet(self.fernet_key.encode())

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
