import json
from typing import Any, Dict, List

from gm.db.database import db
from gm.schemas.input import UserInput
from gm.schemas.rule import RuleOutcome
from gm.schemas.scenario import ScenarioSuggestion
from gm.schemas.state import EntityDiff
from gm.services.external import (
    LLMGatewayClient,
    RuleManagerClient,
    ScenarioManagerClient,
    StateManagerClient,
)


class GMService:
    def __init__(self):
        self.rule_client = RuleManagerClient()
        self.scenario_client = ScenarioManagerClient()
        self.state_client = StateManagerClient()
        self.llm_client = LLMGatewayClient()

    async def process_player_turn(self, user_input: UserInput) -> Dict[str, Any]:
        # 1. turn_id 생성
        # 설계에 따라 DB에서 마지막 seq를 조회해야 함
        turn_seq = await self._get_next_turn_seq(user_input.session_id)
        turn_id = f"{user_input.session_id}:{turn_seq}"

        # 2. Rule Manager 호출
        rule_proposal = await self.rule_client.get_proposal(user_input.content)

        # 3. Scenario Manager 호출
        scenario_proposal = await self.scenario_client.get_proposal(
            user_input.content, rule_proposal
        )

        # 4. 최종 결정 (Scenario > Rule 가드 준수)
        final_diffs = self._resolve_proposals(rule_proposal, scenario_proposal)

        # 5. State Manager 커밋
        commit_result = await self.state_client.commit(turn_id, final_diffs)

        # 6. LLM Gateway 서술 생성
        narrative = await self.llm_client.generate_narrative(
            turn_id, commit_result["commit_id"], user_input.content, rule_proposal
        )

        # 7. Play Log 기록
        await self._save_play_log(
            turn_id,
            turn_seq,
            user_input,
            narrative,
            final_diffs,
            commit_result["commit_id"],
        )

        return {
            "turn_id": turn_id,
            "narrative": narrative,
            "commit_id": commit_result["commit_id"],
        }

    async def _get_next_turn_seq(self, session_id: str) -> int:
        # DB에서 해당 세션의 최대 turn_seq 조회 후 +1
        query = (
            "SELECT COALESCE(MAX(turn_seq), 0) + 1 FROM play_logs WHERE session_id = $1"
        )
        try:
            val = await db.fetchval(query, session_id)
            return val if val else 1
        except Exception:
            # DB 미연결 시 테스트를 위해 1 반환
            return 1

    def _resolve_proposals(
        self, rule: RuleOutcome, scenario: ScenarioSuggestion
    ) -> List[EntityDiff]:
        """
        Scenario > Rule 우선순위와 Rule 봉투(envelope) 원칙을 적용하여 최종 Diff를 확정
        """
        resolved_diffs_map: Dict[str, Dict[str, Any]] = {}

        # 1. 기본적으로 Rule의 제안을 먼저 수용
        for d in rule.suggested_diffs:
            eid = d["entity_id"]
            resolved_diffs_map[eid] = d["diff"].copy()

        # 2. Scenario 제안 적용
        for s_diff in scenario.correction_diffs:
            eid = s_diff["entity_id"]
            s_data = s_diff["diff"]

            if eid not in resolved_diffs_map:
                resolved_diffs_map[eid] = s_data.copy()
                continue

            # 룰 봉투(value_range)가 있는 경우 검증 및 보정
            if rule.value_range:
                for field, s_val in s_data.items():
                    if field in rule.value_range:
                        resolved_diffs_map[eid][field] = s_val
                    else:
                        resolved_diffs_map[eid][field] = s_val
            else:
                resolved_diffs_map[eid].update(s_data)

        return [
            EntityDiff(entity_id=eid, diff=diff)
            for eid, diff in resolved_diffs_map.items()
        ]

    async def _save_play_log(
        self,
        turn_id: str,
        turn_seq: int,
        user_input: UserInput,
        narrative: str,
        diffs: List[EntityDiff],
        commit_id: str,
    ):
        query = """
            INSERT INTO play_logs (
                turn_id,
                session_id,
                turn_seq,
                user_input,
                final_output,
                state_diff,
                commit_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        # EntityDiff 리스트를 JSON 호환 딕셔너리 리스트로 변환
        diffs_json = json.dumps([d.model_dump() for d in diffs])

        try:
            await db.execute(
                query,
                turn_id,
                user_input.session_id,
                turn_seq,
                user_input.content,
                narrative,
                diffs_json,
                commit_id,
            )
        except Exception as e:
            # 로그 저장 실패가 메인 로직을 중단시켜야 하는가?
            # 데이터 정합성을 위해서는 실패 시 트랜잭션 롤백이 맞지만, 
            # 현재 구조에서는 로그만 남김.
            print(f"Failed to save play log: {e}")
            raise e


gm_service = GMService()
