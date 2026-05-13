from pydantic_settings import BaseSettings
from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # PostgreSQL — individual fields
    postgres_user: str = "iga_user"
    postgres_password: str = "iga_password"
    postgres_db: str = "iga_db"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Database
    database_url: str | None = None

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "iga-access-review"

    @model_validator(mode="after")
    def assemble_db_url(self):
        if not self.database_url:
            self.database_url = (
                f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self

settings = Settings()