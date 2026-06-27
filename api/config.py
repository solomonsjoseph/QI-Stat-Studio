from pydantic_settings import BaseSettings
from cryptography.fernet import Fernet as _Fernet


class Settings(BaseSettings):
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4-6"
    secret_key: str = "dev-secret-change-in-prod"
    db_url: str = "sqlite:///./qi_stat_studio.db"
    fernet_key: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_email: str = "qi-stat-studio@example.com"

    @property
    def fernet(self) -> "_Fernet":
        if not self.fernet_key:
            raise RuntimeError(
                'FERNET_KEY is required in .env — generate with: '
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        return _Fernet(self.fernet_key.encode())

    class Config:
        env_file = ".env"


settings = Settings()
