import pytest


@pytest.mark.asyncio
async def test_process_turn_success(client):
    payload = {"session_id": "test_session_1", "content": "나는 문을 발로 찬다."}
    response = await client.post("/api/v1/game/turn", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "turn_id" in data
    assert "narrative" in data
    assert "commit_id" in data
    assert data["turn_id"].startswith("test_session_1:")
    print(f"\nTurn Response: {data}")
