from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,  # 앨리어스와 변수명 모두 지원
    )
    PROJECT_NAME: str = "GM Core"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "gm.infra.db"

    PORT: int = 8020

    BE_ROUTER_HOST: str = "be-router"
    BE_ROUTER_PORT: int = 8010

    STATE_MANAGER_HOST: str = "state-manager"
    STATE_MANAGER_PORT: int = 8030

    SCENARIO_SERVICE_HOST: str = "scenario-service"
    SCENARIO_SERVICE_PORT: int = 8040

    RULE_ENGINE_HOST: str = "rule-engine"
    RULE_ENGINE_PORT: int = 8050

    LLM_GATEWAY_HOST: str = "llm-gateway"
    LLM_GATEWAY_PORT: int = 8060

    WEB_HOST: str = "web"
    WEB_PORT: int = 8080

    LLM_MODEL_NAME: str = "gemini-2.0-flash-lite"

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    @computed_field
    @property
    def STATE_MANAGER_URL(self) -> str:
        return f"http://{self.STATE_MANAGER_HOST}:{self.STATE_MANAGER_PORT}"

    @computed_field
    @property
    def SCENARIO_SERVICE_URL(self) -> str:
        return f"http://{self.SCENARIO_SERVICE_HOST}:{self.SCENARIO_SERVICE_PORT}"

    @computed_field
    @property
    def RULE_ENGINE_URL(self) -> str:
        return f"http://{self.RULE_ENGINE_HOST}:{self.RULE_ENGINE_PORT}"

    @computed_field
    @property
    def LLM_GATEWAY_URL(self) -> str:
        return f"http://{self.LLM_GATEWAY_HOST}:{self.LLM_GATEWAY_PORT}"

    @property
    def database_dsn(self) -> str:
        return f"postgresql://{self.DB_USER}:****@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def real_database_dsn(self) -> str:
        """Actual DSN for connection pool."""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()
