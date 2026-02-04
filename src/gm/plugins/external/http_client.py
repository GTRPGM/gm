from typing import Any, Dict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from gm.core.config import settings
from gm.core.models.rule import (
    RuleOutcome,
    RuleRequestEntity,
)
from gm.core.models.scenario import ScenarioSuggestion
from gm.core.models.state import EntityDiff
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)

# 기본 재시도 설정: 예외 발생 시 최대 3회 시도, 지수 백오프 적용 (최소 0.1초, 최대 2초)
retry_policy = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
    retry=retry_if_exception_type(httpx.RequestError),
    reraise=True,
)


class RuleManagerHTTPClient(RuleManagerPort):
    # Rule Engine RelationType Enum mapping (State DB Value -> Rule Engine Enum Value)
    RELATION_MAP = {
        "HOSTILE": "적대적",
        "LITTLE_HOSTILE": "약간 적대적",
        "NEUTRAL": "중립적",
        "LITTLE_FRIENDLY": "약간 우호적",
        "FRIENDLY": "우호적",
        "OWNERSHIP": "소유",
        "CONSUME": "소비",
        "SELF": "본인",
        # Korean fallback
        "적대적": "적대적",
        "약간 적대적": "약간 적대적",
        "중립적": "중립적",
        "약간 우호적": "약간 우호적",
        "우호적": "우호적",
    }

    @retry_policy
    async def get_proposal(self, context: Dict[str, Any]) -> RuleOutcome:
        url = f"{settings.RULE_ENGINE_URL}/play/scenario"
        print(f"DEBUG: Requesting Rule Check at {url}")

        # Construct payload from context
        session_id = str(context.get("session_id", ""))
        user_input = context.get("user_input", "")
        snapshot = context.get("world_snapshot", {})
        phase_id = int(context.get("phase_id", 1))

        req_entities = []

        def parse_entity_id(raw_id: Any) -> int | None:
            if not raw_id:
                return None
            digits = "".join(filter(str.isdigit, str(raw_id)))
            return int(digits) if digits else None

        master_to_instance = {}

        player_id = snapshot.get("player_id")
        player_name = snapshot.get("player_name") or snapshot.get("name") or "Player"

        active_entity_id = context.get("active_entity_id")

        if player_id:
            req_entities.append(
                RuleRequestEntity(
                    state_entity_id=str(player_id),
                    entity_id=1,
                    entity_name=player_name,
                    entity_type="player",
                    phase_id=phase_id,
                )
            )
            master_to_instance["player"] = str(player_id)

        for npc in snapshot.get("npcs", []):
            m_id = npc.get("scenario_entity_id")
            s_id = str(npc.get("id"))
            entity_id = parse_entity_id(m_id)
            req_entities.append(
                RuleRequestEntity(
                    state_entity_id=s_id,
                    entity_id=entity_id,
                    entity_name=str(npc.get("name")),
                    entity_type="npc",
                    phase_id=phase_id,
                )
            )
            if m_id:
                master_to_instance[m_id] = s_id

        for enemy in snapshot.get("enemies", []):
            m_id = enemy.get("scenario_entity_id")
            s_id = str(enemy.get("id"))
            entity_id = parse_entity_id(m_id)
            req_entities.append(
                RuleRequestEntity(
                    state_entity_id=s_id,
                    entity_id=entity_id,
                    entity_name=str(enemy.get("name")),
                    entity_type="enemy",
                    phase_id=phase_id,
                )
            )
            if m_id:
                master_to_instance[m_id] = s_id

        if active_entity_id and active_entity_id != "player":
            actual_active_id = master_to_instance.get(
                active_entity_id, active_entity_id
            )
            if not any(
                e.state_entity_id == str(actual_active_id) for e in req_entities
            ):
                req_entities.append(
                    RuleRequestEntity(
                        state_entity_id=str(actual_active_id),
                        entity_name=str(actual_active_id),
                        entity_type="object",
                        phase_id=phase_id,
                    )
                )

        req_relations = []

        for rel in snapshot.get("entity_relations", []):
            r_type = rel.get("relation_type", "NEUTRAL")
            mapped_type = self.RELATION_MAP.get(r_type, "중립적")

            from_m_id = rel.get("from_id")
            to_m_id = rel.get("to_id")
            from_s_id = master_to_instance.get(from_m_id, from_m_id)
            to_s_id = master_to_instance.get(to_m_id, to_m_id)

            req_relations.append(
                {
                    "cause_entity_id": str(from_s_id),
                    "effect_entity_id": str(to_s_id),
                    "type": mapped_type,
                    "affinity_score": rel.get("affinity"),
                }
            )

        for rel in snapshot.get("player_npc_relations", []):
            if player_id:
                r_type = rel.get("relation_type", "NEUTRAL")
                mapped_type = self.RELATION_MAP.get(r_type, "중립적")
                npc_s_id = str(rel.get("npc_id"))

                req_relations.append(
                    {
                        "cause_entity_id": str(player_id),
                        "effect_entity_id": npc_s_id,
                        "type": mapped_type,
                        "affinity_score": rel.get("affinity_score"),
                    }
                )

                # Rule Engine might need bidirectional relations?
                # Usually affinity is mutual, stick to one for now.

        # Scenario and Locale
        scenario_id = str(snapshot.get("scenario_id", context.get("scenario_id", "1")))
        locale_id = int(context.get("locale_id", 0))

        payload = {
            "session_id": session_id,
            "scenario_id": scenario_id,
            "locale_id": locale_id,
            "entities": [e.model_dump() for e in req_entities],
            "relations": req_relations,
            "story": user_input,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                if response.status_code == 422:
                    print(f"DEBUG: 422 Detail: {response.text}")
                response.raise_for_status()

                # Rule Engine returns WrappedResponse[PlaySceneResponse]
                resp_json = response.json()
                data = resp_json.get("data", {})

                return RuleOutcome(**data)

        except Exception as e:
            print(f"DEBUG: Rule Check Failed: {e}")
            raise e

    async def check_health(self) -> bool:
        url = f"{settings.RULE_ENGINE_URL}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False


class ScenarioManagerHTTPClient(ScenarioManagerPort):
    @retry_policy
    async def get_proposal(self, context: Dict[str, Any]) -> ScenarioSuggestion:
        # Use validate endpoint to avoid 404 on session lookup
        url = f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"

        rule_outcome = context.get("rule_outcome")
        if not rule_outcome:
            raise ValueError("Rule outcome missing in context")

        # Snapshot or context should have current progress
        snapshot = context.get("world_snapshot", {})

        # Priority: Snapshot (Real DB State) > Context > Rule Outcome > Default
        scenario_id = str(
            snapshot.get("scenario_id")
            or context.get("scenario_id")
            or rule_outcome.scenario_id
        )
        act_id = str(snapshot.get("current_act_id") or context.get("act_id") or "act-1")
        seq_id = str(
            snapshot.get("current_sequence_id") or context.get("sequence_id") or "seq-1"
        )

        user_input = context.get("user_input", "")

        payload = {
            "scenario_id": scenario_id,
            "act_id": act_id,
            "seq_id": seq_id,
            "user_input": user_input,
        }

        print(f"DEBUG: [ScenarioManager] POST {url} | Payload: {payload}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload)
                if response.status_code != 200:
                    detail = (
                        response.json().get("detail", response.text)
                        if response.headers.get("content-type") == "application/json"
                        else response.text
                    )
                    print(f"DEBUG: [Scenario] {response.status_code}: {detail[:50]}")
                    # Raise a more descriptive error for domain issues
                    if response.status_code == 404:
                        raise ValueError(f"Scenario Context Missing: {detail}")
                response.raise_for_status()

                data = response.json()

            except Exception as e:
                print(f"DEBUG: [ScenarioManager] Request failed: {e}")
                raise e

            # Map ValidationOutput to ScenarioSuggestion
            is_triggered = data.get("is_triggered", False)
            reason = data.get("reason", "No reason provided")
            narration = data.get("suggested_narration")
            next_act_id = data.get("next_act_id")
            next_seq_id = data.get("next_seq_id")

            from gm.core.models.scenario import ScenarioConstraintType

            return ScenarioSuggestion(
                constraint_type=ScenarioConstraintType.MANDATORY
                if is_triggered
                else ScenarioConstraintType.ADVISORY,
                description=reason,
                correction_diffs=[],
                narrative_slot=narration,
                next_act_id=next_act_id,
                next_seq_id=next_seq_id,
            )

    async def check_health(self) -> bool:
        url = f"{settings.SCENARIO_SERVICE_URL}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False


class StateManagerHTTPClient(StateManagerPort):
    @retry_policy
    async def commit(self, turn_id: str, diffs: list[EntityDiff]) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/commit"
        payload = {"turn_id": turn_id, "diffs": [d.model_dump() for d in diffs]}

        print(f"DEBUG: [StateManager] POST {url} | Payload: {payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            print(
                f"DEBUG: [StateManager] {response.status_code} | {response.text[:100]}"
            )
            response.raise_for_status()

            data = response.json()
            if (
                isinstance(data, dict)
                and "data" in data
                and data.get("status") == "success"
            ):
                return data["data"]
            return data

    @retry_policy
    async def get_state(self, session_id: str) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/session/{session_id}"
        print(f"DEBUG: [StateManager] GET {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            print(
                f"DEBUG: [StateManager] {response.status_code} | {response.text[:100]}"
            )
            response.raise_for_status()
            # If the response is WrappedResponse, extract 'data'
            data = response.json()
            if (
                isinstance(data, dict)
                and "data" in data
                and data.get("status") == "success"
            ):
                return data["data"]
            return data

    @retry_policy
    async def get_sequence_details(self, session_id: str) -> Dict[str, Any]:
        url = (
            f"{settings.STATE_MANAGER_URL}/state/session/{session_id}/sequence/details"
        )
        print(f"DEBUG: [StateManager] GET {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            print(
                f"DEBUG: [StateManager] {response.status_code} | {response.text[:100]}"
            )
            response.raise_for_status()
            data = response.json()
            if (
                isinstance(data, dict)
                and "data" in data
                and data.get("status") == "success"
            ):
                return data["data"]
            return data

    @retry_policy
    async def update_act(self, session_id: str, act_id: str) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/session/{session_id}/act"
        # Extract integer from 'act-X'
        digits = "".join(filter(str.isdigit, str(act_id)))
        act_num = int(digits) if digits else 1

        print(f"DEBUG: [StateManager] PUT {url} | act_id: {act_id} (num: {act_num})")
        async with httpx.AsyncClient() as client:
            response = await client.put(url, json={"new_act": act_num})
            response.raise_for_status()
            return response.json()

    @retry_policy
    async def update_sequence(self, session_id: str, seq_id: str) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/session/{session_id}/sequence"
        # Extract integer from 'seq-X'
        digits = "".join(filter(str.isdigit, str(seq_id)))
        seq_num = int(digits) if digits else 1

        print(f"DEBUG: [StateManager] PUT {url} | seq_id: {seq_id} (num: {seq_num})")
        async with httpx.AsyncClient() as client:
            response = await client.put(url, json={"new_sequence": seq_num})
            response.raise_for_status()
            return response.json()

    async def check_health(self) -> bool:
        url = f"{settings.STATE_MANAGER_URL}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False
