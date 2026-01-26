import pytest
from httpx import Response

from gm.core.config import settings


@pytest.mark.asyncio
async def test_rule_manager_integration(client, respx_mock):
    session_id = "rule_test_session"
    scenario_id = 101

    # 1. 룰 엔진의 새로운 응답 스키마 정의
    mock_response = {
        "status": "success",
        "data": {
            "session_id": session_id,
            "scenario_id": scenario_id,
            "phase_type": "전투",
            "reason": "테스트 판정 성공",
            "success": True,
            "suggested": {
                "diffs": [{"entity_id": "goblin_scout", "diff": {"hp": 5}}],
                "relations": [],
            },
            "value_range": {"damage": 10.0},
        },
        "message": "OK",
    }

    # 2. 기존 룰(conftest에서 설정된 것)을 덮어씌움
    rule_route = respx_mock.post(f"{settings.RULE_SERVICE_URL}/api/v1/rule/check").mock(
        return_value=Response(200, json=mock_response)
    )

    # 3. GM 서비스 API 호출
    payload = {"session_id": session_id, "content": "고블린에게 칼을 휘두른다."}

    response = await client.post("/api/v1/game/turn", json=payload)

    # 4. 검증
    assert response.status_code == 200

    # 룰 엔진으로 간 요청이 새로운 스키마를 따르는지 확인
    assert rule_route.called
    # 첫 번째 요청(플레이어 턴)을 검증
    player_request = rule_route.calls[0].request
    request_data = player_request.read().decode()
    import json

    req_json = json.loads(request_data)

    # 신규 스키마 필수 필드 확인
    assert req_json["session_id"] == session_id
    assert "entities" in req_json
    assert req_json["story"] == "고블린에게 칼을 휘두른다."

    # 응답 데이터 확인 (GameEngine이 narrative를 생성했는지)
    data = response.json()
    assert "narrative" in data
    assert "turn_id" in data
    assert "commit_id" in data
