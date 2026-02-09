from __future__ import annotations

from urllib.parse import urlparse

from pydantic import Field, computed_field, model_validator
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

    DB_USER: str = Field("postgres", validation_alias="DB_USER")
    DB_PASSWORD: str = Field("postgres", validation_alias="DB_PASSWORD")
    DB_HOST: str = Field("localhost", validation_alias="DB_HOST")
    DB_PORT: int = Field(5432, validation_alias="DB_PORT")
    DB_NAME: str = Field("gtrpgm", validation_alias="DB_NAME")

    PORT: int = 8020

    # Service endpoints: prefer HOST/PORT, but also accept *_URL (common in deployments)
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

    # Optional URL overrides (read from env), used to derive *_HOST/*_PORT.
    BE_ROUTER_URL_IN: str | None = Field(default=None, validation_alias="BE_ROUTER_URL")
    STATE_MANAGER_URL_IN: str | None = Field(
        default=None, validation_alias="STATE_MANAGER_URL"
    )
    SCENARIO_SERVICE_URL_IN: str | None = Field(
        default=None, validation_alias="SCENARIO_SERVICE_URL"
    )
    RULE_ENGINE_URL_IN: str | None = Field(
        default=None, validation_alias="RULE_ENGINE_URL"
    )
    LLM_GATEWAY_URL_IN: str | None = Field(
        default=None, validation_alias="LLM_GATEWAY_URL"
    )
    WEB_URL_IN: str | None = Field(default=None, validation_alias="WEB_URL")

    LLM_MODEL_NAME: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    @staticmethod
    def _apply_url_override(
        data: dict,
        url_key: str,
        host_key: str,
        port_key: str,
    ) -> None:
        raw = data.get(url_key)
        if not raw:
            return
        try:
            parsed = urlparse(str(raw))
        except Exception:
            return
        if parsed.hostname:
            data[host_key] = parsed.hostname
        if parsed.port:
            data[port_key] = int(parsed.port)

    @model_validator(mode="before")
    @classmethod
    def _normalize_service_endpoints(cls, data):
        # BaseSettings passes a dict-like; normalize to a mutable dict.
        d = dict(data or {})

        cls._apply_url_override(
            d, "BE_ROUTER_URL_IN", "BE_ROUTER_HOST", "BE_ROUTER_PORT"
        )
        cls._apply_url_override(
            d, "STATE_MANAGER_URL_IN", "STATE_MANAGER_HOST", "STATE_MANAGER_PORT"
        )
        cls._apply_url_override(
            d,
            "SCENARIO_SERVICE_URL_IN",
            "SCENARIO_SERVICE_HOST",
            "SCENARIO_SERVICE_PORT",
        )
        cls._apply_url_override(
            d, "RULE_ENGINE_URL_IN", "RULE_ENGINE_HOST", "RULE_ENGINE_PORT"
        )
        cls._apply_url_override(
            d, "LLM_GATEWAY_URL_IN", "LLM_GATEWAY_HOST", "LLM_GATEWAY_PORT"
        )
        cls._apply_url_override(d, "WEB_URL_IN", "WEB_HOST", "WEB_PORT")

        return d

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
