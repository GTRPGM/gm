from typing import Any, Dict, List

import pytest

from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)
from gm.schemas.common import EntityDiff


class MockRuleManager(RuleManagerPort):
    async def get_proposal(self, context: Dict[str, Any]):
        return None

    async def check_health(self) -> bool:
        return True


class MockScenarioManager(ScenarioManagerPort):
    async def get_proposal(self, context: Dict[str, Any]):
        return None

    async def check_health(self) -> bool:
        return True


class MockStateManager(StateManagerPort):
    async def commit(self, turn_id: str, diffs: List[EntityDiff]):
        return {}

    async def get_state(self, session_id: str):
        return {}

    async def get_act_details(self, session_id: str):
        return {}

    async def get_sequence_details(self, session_id: str):
        return {}

    async def update_act(self, session_id: str, act_id: str, seq_id: str):
        return {}

    async def update_sequence(self, session_id: str, seq_id: str):
        return {}

    async def end_session(self, session_id: str):
        return {}

    async def check_health(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_interfaces_instantiation():
    # 추상 메서드를 모두 구현한 클래스는 인스턴스화 가능해야 함
    rule_mgr = MockRuleManager()
    assert await rule_mgr.check_health() is True

    scen_mgr = MockScenarioManager()
    assert await scen_mgr.check_health() is True

    state_mgr = MockStateManager()
    assert await state_mgr.check_health() is True


def test_abstract_instantiation_error():
    # 추상 메서드를 구현하지 않으면 인스턴스화 실패
    with pytest.raises(TypeError):
        RuleManagerPort()
    with pytest.raises(TypeError):
        ScenarioManagerPort()
    with pytest.raises(TypeError):
        StateManagerPort()
