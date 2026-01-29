from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "GM Core"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "gm.infra.db"

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
    def STATE_SERVICE_URL(self) -> str:
        return f"http://{self.STATE_MANAGER_HOST}:{self.STATE_MANAGER_PORT}"

    @computed_field
    @property
    def SCENARIO_SERVICE_URL(self) -> str:
        return f"http://{self.SCENARIO_SERVICE_HOST}:{self.SCENARIO_SERVICE_PORT}"

    @computed_field
    @property
    def RULE_SERVICE_URL(self) -> str:
        return f"http://{self.RULE_ENGINE_HOST}:{self.RULE_ENGINE_PORT}"

    @computed_field
    @property
    def LLM_GATEWAY_URL(self) -> str:
        return f"http://{self.LLM_GATEWAY_HOST}:{self.LLM_GATEWAY_PORT}"

    @property
    def database_dsn(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = Settings()
