from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "GM Core"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # PostgreSQL Database Settings
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "gm.infra.db"

    # External Services
    STATE_SERVICE_URL: str = "http://localhost:8030"
    SCENARIO_SERVICE_URL: str = "http://localhost:8040"
    RULE_SERVICE_URL: str = "http://localhost:8050"
    LLM_GATEWAY_URL: str = "http://localhost:8060"
    LLM_MODEL_NAME: str = "gemini-2.0-flash-lite"

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    @property
    def database_dsn(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = Settings()
