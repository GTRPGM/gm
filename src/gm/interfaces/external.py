from abc import ABC, abstractmethod
from typing import Any, Dict

from gm.core.models.rule import RuleOutcome
from gm.core.models.scenario import ScenarioSuggestion
from gm.core.models.state import EntityDiff


class RuleManagerPort(ABC):
    @abstractmethod
    async def get_proposal(self, content: str) -> RuleOutcome:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass


class ScenarioManagerPort(ABC):
    @abstractmethod
    async def get_proposal(
        self, content: str, rule_outcome: RuleOutcome
    ) -> ScenarioSuggestion:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass


class StateManagerPort(ABC):
    @abstractmethod
    async def commit(self, turn_id: str, diffs: list[EntityDiff]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass
