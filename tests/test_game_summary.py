from unittest.mock import AsyncMock, MagicMock

import pytest

from gm.core.engine.game_engine import GameEngine


# LangChain 파이프라인 Mock을 위한 헬퍼 클래스
class MockRunnable:
    def __init__(self, return_value=None, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect

    def __or__(self, other):
        # 파이프라인 연산자(|) 지원
        return self

    async def ainvoke(self, *args, **kwargs):
        if self.side_effect:
            raise self.side_effect
        return self.return_value


@pytest.mark.asyncio
async def test_generate_summary_success(mock_dependencies):
    rule_client, scenario_client, state_client, llm, db = mock_dependencies

    # LLM이 파이프라인 연산자를 지원하도록 설정
    mock_response = MagicMock()
    mock_response.content = "Summary of current situation"

    # GameEngine 내부에서 'prompt | llm' 형태로 사용되므로
    # llm 자체가 아니라, prompt가 파이프의 시작점임.
    # 하지만 여기서는 GameEngine 코드를 수정하지 않고 테스트하기 위해
    # llm을 모킹하는 것보다 GameEngine._load_prompt 내부에서
    # ChatPromptTemplate을 생성하는 부분을 제어하는 것이 복잡함.

    # 대신 GameEngine의 코드를 보면:
    # prompt = ChatPromptTemplate.from_messages(...)
    # chain = prompt | self.llm
    # response = await chain.ainvoke(...)

    # 따라서 ChatPromptTemplate.from_messages를 패치하여
    # __or__ 연산을 가로채는 Mock 객체를 리턴하게 하면 됨.

    from unittest.mock import patch

    with patch(
        "gm.core.engine.game_engine.ChatPromptTemplate.from_messages"
    ) as mock_prompt_cls:
        # prompt | llm -> chain
        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = mock_response

        mock_prompt = MagicMock()
        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_cls.return_value = mock_prompt

        engine = GameEngine(rule_client, scenario_client, state_client, llm, db)

        # Mock State Manager responses
        state_client.get_state.return_value = {
            "session": {"scenario_id": "scen-1"},
            "player": {"hp": 100},
            "npcs": [{"name": "Guard", "description": "Standing watch"}],
            "enemies": [{"name": "Rat", "description": "Small pest"}],
            "act": {"act_name": "Act 1"},
            "sequence_name": "Entrance",
        }
        state_client.get_sequence_details.return_value = {}
        state_client.get_act_details.return_value = {}

        # Mock DB history
        db.get_query.return_value = "SELECT ..."
        db.fetch.return_value = [{"user_input": "Hello", "final_output": "Hi there"}]

        summary = await engine.generate_summary("session-123")

        assert summary == "Summary of current situation"
        mock_chain.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_summary_state_failure(mock_dependencies):
    rule_client, scenario_client, state_client, llm, db = mock_dependencies
    engine = GameEngine(rule_client, scenario_client, state_client, llm, db)

    # Mock State Manager failure
    state_client.get_state.side_effect = Exception("DB Connection Error")

    summary = await engine.generate_summary("session-123")

    assert summary == "현재 상황을 파악할 수 없습니다."


@pytest.mark.asyncio
async def test_generate_summary_llm_failure(mock_dependencies):
    rule_client, scenario_client, state_client, llm, db = mock_dependencies

    from unittest.mock import patch

    with patch(
        "gm.core.engine.game_engine.ChatPromptTemplate.from_messages"
    ) as mock_prompt_cls:
        mock_chain = AsyncMock()
        mock_chain.ainvoke.side_effect = Exception("LLM Error")

        mock_prompt = MagicMock()
        mock_prompt.__or__.return_value = mock_chain
        mock_prompt_cls.return_value = mock_prompt

        engine = GameEngine(rule_client, scenario_client, state_client, llm, db)

        # Mock State Manager success
        state_client.get_state.return_value = {}
        state_client.get_sequence_details.return_value = {}
        state_client.get_act_details.return_value = {}

        # Mock DB success
        db.fetch.return_value = []

        summary = await engine.generate_summary("session-123")

        assert summary == "상황 요약을 생성하는 도중 오류가 발생했습니다."


@pytest.fixture
def mock_dependencies():
    rule_client = AsyncMock()
    scenario_client = AsyncMock()
    state_client = AsyncMock()
    llm = AsyncMock()
    db = AsyncMock()
    return rule_client, scenario_client, state_client, llm, db
