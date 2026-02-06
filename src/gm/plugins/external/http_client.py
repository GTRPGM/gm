import logging
import re
from typing import Any, Dict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from gm.core.config import settings
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)
from gm.schemas.common import EntityDiff
from gm.schemas.rule_engine import (
    RuleOutcome,
    RuleRequestEntity,
)
from gm.schemas.scenario import ScenarioSuggestion

logger = logging.getLogger(__name__)
ACT_ID_RE = re.compile(r"^act-\d+(?:-\d+)*$")
SEQ_ID_RE = re.compile(r"^seq-\d+(?:-\d+)*$")


def _unwrap_response_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Support both wrapped({status,data}) and flat response bodies."""
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _normalize_hierarchy_id(raw: Any, pattern: re.Pattern[str], default: str) -> str:
    value = str(raw or "").strip()
    if pattern.match(value):
        return value
    return default


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

        # Scenario and Locale
        scenario_id = str(
            context.get("scenario_id") or snapshot.get("scenario_id") or "unknown"
        )
        locale_id = int(context.get("locale_id", 0))

        payload = {
            "session_id": session_id,
            "scenario_id": scenario_id,
            "locale_id": locale_id,
            "actor_id": active_entity_id,
            "entities": [e.model_dump() for e in req_entities],
            "relations": req_relations,
            "story": user_input,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=15.0)
                response.raise_for_status()
                data = _unwrap_response_data(response.json())
                return RuleOutcome(**data)
        except Exception as e:
            logger.error(
                "rule_client_error session_id=%s scenario_id=%s error=%s",
                session_id,
                scenario_id,
                type(e).__name__,
            )
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
        url = f"{settings.SCENARIO_SERVICE_URL}/api/v1/check/validate"

        rule_outcome = context.get("rule_outcome")
        if not rule_outcome:
            raise ValueError("Rule outcome missing in context")

        snapshot = context.get("world_snapshot", {})

        # Priority: Context > Snapshot (Real DB State) > Rule Outcome
        scenario_id = str(
            context.get("scenario_id")
            or snapshot.get("scenario_id")
            or rule_outcome.scenario_id
            or "unknown"
        )

        act_id = _normalize_hierarchy_id(
            snapshot.get("current_act_id") or context.get("act_id"),
            ACT_ID_RE,
            "act-1",
        )
        seq_id = _normalize_hierarchy_id(
            snapshot.get("current_sequence_id") or context.get("sequence_id"),
            SEQ_ID_RE,
            "seq-1",
        )

        user_input = context.get("user_input", "")

        payload = {
            "scenario_id": scenario_id,
            "act_id": act_id,
            "seq_id": seq_id,
            "user_input": user_input,
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=15.0)
                if response.status_code == 404:
                    try:
                        detail = response.json().get(
                            "detail", response.text or "Not Found"
                        )
                    except Exception:
                        detail = response.text or "Not Found"
                    raise ValueError(f"Scenario Context Missing: {detail}")
                response.raise_for_status()
                data = _unwrap_response_data(response.json())
            except Exception as e:
                logger.error(
                    "scenario_client_error scenario_id=%s act_id=%s seq_id=%s error=%s",
                    scenario_id,
                    act_id,
                    seq_id,
                    type(e).__name__,
                )
                raise e

            is_triggered = data.get("is_triggered", False)
            reason = data.get("reason", "No reason provided")
            narration = data.get("suggested_narration")
            next_act_id = data.get("next_act_id")
            next_seq_id = data.get("next_seq_id")
            if next_act_id and not ACT_ID_RE.match(str(next_act_id)):
                logger.warning(
                    "invalid_next_act_id_from_scenario_service id=%s", next_act_id
                )
                next_act_id = None
            if next_seq_id and not SEQ_ID_RE.match(str(next_seq_id)):
                logger.warning(
                    "invalid_next_seq_id_from_scenario_service id=%s", next_seq_id
                )
                next_seq_id = None

            from gm.schemas.scenario import ScenarioConstraintType

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

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if (
                isinstance(data, dict)
                and data.get("status") == "success"
                and "data" in data
            ):
                return data["data"]
            return data

    @retry_policy
    async def get_state(self, session_id: str) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/session/{session_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if (
                isinstance(data, dict)
                and data.get("status") == "success"
                and "data" in data
            ):
                return data["data"]
            return data

    @retry_policy
    async def get_act_details(self, session_id: str) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/session/{session_id}/act/details"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if (
                isinstance(data, dict)
                and data.get("status") == "success"
                and "data" in data
            ):
                return data["data"]
            return data

    @retry_policy
    async def get_sequence_details(self, session_id: str) -> Dict[str, Any]:
        url = (
            f"{settings.STATE_MANAGER_URL}/state/session/{session_id}/sequence/details"
        )
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if (
                isinstance(data, dict)
                and data.get("status") == "success"
                and "data" in data
            ):
                return data["data"]
            return data

    @retry_policy
    async def update_act(
        self, session_id: str, act_id: str, seq_id: str
    ) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/session/{session_id}/act"
        act_id = _normalize_hierarchy_id(act_id, ACT_ID_RE, "act-1")
        seq_id = _normalize_hierarchy_id(seq_id, SEQ_ID_RE, "seq-1")
        act_digits = "".join(filter(str.isdigit, str(act_id)))
        act_num = int(act_digits) if act_digits else 1
        payload = {
            "new_act": act_num,
            "new_act_id": str(act_id),
            "new_sequence_id": str(seq_id),
        }
        async with httpx.AsyncClient() as client:
            response = await client.put(url, json=payload, timeout=5.0)
            response.raise_for_status()
            return _unwrap_response_data(response.json())

    @retry_policy
    async def update_sequence(self, session_id: str, seq_id: str) -> Dict[str, Any]:
        url = f"{settings.STATE_MANAGER_URL}/state/session/{session_id}/sequence"
        seq_id = _normalize_hierarchy_id(seq_id, SEQ_ID_RE, "seq-1")
        digits = "".join(filter(str.isdigit, str(seq_id)))
        seq_num = int(digits) if digits else 1
        payload = {"new_sequence": seq_num, "new_sequence_id": str(seq_id)}
        async with httpx.AsyncClient() as client:
            response = await client.put(url, json=payload, timeout=5.0)
            response.raise_for_status()
            return _unwrap_response_data(response.json())

    async def check_health(self) -> bool:
        url = f"{settings.STATE_MANAGER_URL}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False
