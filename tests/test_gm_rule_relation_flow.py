import json

import httpx
import pytest

from gm.core.config import settings
from gm.plugins.external.http_client import RuleManagerHTTPClient


@pytest.mark.asyncio
async def test_gm_passes_relations_to_rule_engine(respx_mock):
    """
    Test 2: GM이 State Manager로부터 받은 관계 정보를 룰엔진 요청 페이로드에 포함하는지 검증
    """
    client = RuleManagerHTTPClient()

    # Rule Engine 엔드포인트 모킹
    route = respx_mock.post(f"{settings.RULE_ENGINE_URL}/play/scenario").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "session_id": "session-1",
                    "scenario_id": "scenario-1",
                    "phase_type": "대화",
                    "reason": "OK",
                    "success": True,
                    "suggested": {"diffs": [], "relations": []},
                },
            },
        )
    )

    # 1. State Manager로부터 받았을 법한 world_snapshot 구성
    player_id = "p-123"
    npc_id = "n-456"

    context = {
        "session_id": "session-1",
        "scenario_id": "scenario-1",
        "user_input": "안녕하세요",
        "active_entity_id": "player",
        "world_snapshot": {
            "player_id": player_id,
            "player_name": "Hero",
            "npcs": [
                {
                    "id": npc_id,
                    "npc_id": npc_id,
                    "name": "Guard",
                    "scenario_npc_id": "npc-guard-1",
                    "rule_id": 10,
                }
            ],
            "enemies": [],
            # State Manager가 내려주는 관계 정보 형식
            "relations": [
                {
                    "from_id": player_id,
                    "to_id": npc_id,
                    "relation_type": "FRIENDLY",
                    "affinity": 80,
                    "quantity": None,
                }
            ],
        },
    }

    # 2. GM 클라이언트 호출 (Rule Engine으로 요청 보냄)
    await client.get_proposal(context)

    # 3. Rule Engine으로 전송된 페이로드 검증
    assert route.called
    request_payload = json.loads(route.calls.last.request.content)

    assert "relations" in request_payload
    sent_relations = request_payload["relations"]

    # 룰엔진이 기대하는 필드명(cause_entity_id, effect_entity_id, affinity_score) 확인
    found = False
    for rel in sent_relations:
        if rel["cause_entity_id"] == player_id and rel["effect_entity_id"] == npc_id:
            assert rel["type"] == "우호적"  # RELATION_MAP에 의해 변환됨
            assert rel["affinity_score"] == 80
            found = True
            break

    assert found, f"Relations not found in Rule Engine payload: {sent_relations}"
    print("\n[SUCCESS] GM correctly mapped and passed relations to Rule Engine.")
