from abc import ABC, abstractmethod
from typing import Any, Dict, List

from gm.schemas.common import EntityDiff
from gm.schemas.rule_engine import RuleOutcome
from gm.schemas.scenario import ScenarioSuggestion


class RuleManagerPort(ABC):
    @abstractmethod
    async def get_proposal(self, context: Dict[str, Any]) -> RuleOutcome:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass


class ScenarioManagerPort(ABC):
    @abstractmethod
    async def get_proposal(self, context: Dict[str, Any]) -> ScenarioSuggestion:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass


class StateManagerPort(ABC):
    @abstractmethod
    async def commit(self, turn_id: str, diffs: List[EntityDiff]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_state(self, session_id: str) -> Dict[str, Any]:
        """Fetch current world state snapshot including entities and relations."""
        pass

    @abstractmethod
    async def get_act_details(self, session_id: str) -> Dict[str, Any]:
        """Fetch detailed act information."""
        pass

    @abstractmethod
    async def get_sequence_details(self, session_id: str) -> Dict[str, Any]:
        """Fetch detailed sequence information including NPCs and enemies."""
        pass

    @abstractmethod
    async def update_act(
        self, session_id: str, act_id: str, seq_id: str
    ) -> Dict[str, Any]:
        """Update session's current act."""
        pass

    @abstractmethod
    async def update_sequence(self, session_id: str, seq_id: str) -> Dict[str, Any]:
        """Update session's current sequence."""
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass
