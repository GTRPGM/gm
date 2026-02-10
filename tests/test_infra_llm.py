import httpx
import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from gm.plugins.llm.adapter import NarrativeChatModel


@pytest_asyncio.fixture
async def llm_adapter():
    adapter = NarrativeChatModel()
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient()
    yield adapter
    await adapter.client.aclose()


@pytest.mark.asyncio
async def test_convert_message_to_schema(llm_adapter):
    msg_human = HumanMessage(content="hello")
    schema_human = llm_adapter._convert_message_to_schema(msg_human)
    assert schema_human.role == "user"
    assert schema_human.content == "hello"

    msg_ai = AIMessage(content="hi")
    schema_ai = llm_adapter._convert_message_to_schema(msg_ai)
    assert schema_ai.role == "assistant"
    assert schema_ai.content == "hi"

    msg_system = SystemMessage(content="system prompt")
    schema_system = llm_adapter._convert_message_to_schema(msg_system)
    assert schema_system.role == "system"
    assert schema_system.content == "system prompt"


@pytest.mark.asyncio
async def test_agenerate_success(llm_adapter, respx_mock):
    respx_mock.post("http://llm-gateway:8060/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "test_id",
                "object": "chat.completion",
                "created": 123456789,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello world"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
    )

    result = await llm_adapter._agenerate([HumanMessage(content="Hi")])
    assert len(result.generations) == 1
    assert result.generations[0].text == "Hello world"
    assert result.generations[0].generation_info["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_agenerate_no_choices(llm_adapter, respx_mock):
    respx_mock.post("http://llm-gateway:8060/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "test_id",
                "object": "chat.completion",
                "created": 123456789,
                "model": "test-model",
                "choices": [],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            },
        )
    )

    result = await llm_adapter._agenerate([HumanMessage(content="Hi")])
    assert len(result.generations) == 0


@pytest.mark.asyncio
async def test_agenerate_structured_output(llm_adapter, respx_mock):
    respx_mock.post("http://llm-gateway:8060/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "test_id",
                "object": "chat.completion",
                "created": 123456789,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"key": "value"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
    )

    result = await llm_adapter._agenerate(
        [HumanMessage(content="Hi")], response_format={"type": "json_object"}
    )
    assert result.generations[0].message.content == [{"key": "value"}]


@pytest.mark.asyncio
async def test_check_health(llm_adapter, respx_mock):
    respx_mock.get("http://llm-gateway:8060/health").mock(
        return_value=httpx.Response(200)
    )
    assert await llm_adapter.check_health() is True

    respx_mock.get("http://llm-gateway:8060/health").mock(
        return_value=httpx.Response(500)
    )
    assert await llm_adapter.check_health() is False

    respx_mock.get("http://llm-gateway:8060/health").mock(
        side_effect=httpx.ConnectError("Connection failed")
    )
    assert await llm_adapter.check_health() is False


@pytest.mark.asyncio
async def test_with_structured_output(llm_adapter, respx_mock):
    from pydantic import BaseModel

    class TestSchema(BaseModel):
        name: str

    respx_mock.post("http://llm-gateway:8060/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "test_id",
                "object": "chat.completion",
                "created": 123456789,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"name": "tester"}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
    )

    runnable = llm_adapter.with_structured_output(TestSchema)
    result = await runnable.ainvoke([HumanMessage(content="Hi")])
    assert isinstance(result, TestSchema)
    assert result.name == "tester"


@pytest.mark.asyncio
async def test_generate_raises_not_implemented(llm_adapter):
    with pytest.raises(NotImplementedError):
        llm_adapter._generate([HumanMessage(content="Hi")])
