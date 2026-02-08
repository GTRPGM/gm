import functools
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, TypeVar, cast

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from gm.core.models import TurnContext
from gm.exceptions import PipelineError
from gm.infra.db.database import DatabaseHandler
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)
from gm.interfaces.llm import LLMPort
from gm.schemas.api import TurnOutputType
from gm.schemas.common import EntityDiff

logger = logging.getLogger(__name__)

# Node to Service mapping for error reporting
NODE_SERVICE_MAP = {
    "fetch_state": "StateManager",
    "check_rule": "RuleEngine",
    "check_scenario": "ScenarioService",
    "commit_state": "StateManager",
    "generate_narrative": "LLMGateway",
    "select_active_entity": "LLMGateway",
    "generate_npc_input": "LLMGateway",
    "save_log": "PostgreSQL",
}

F = TypeVar("F", bound=Callable[..., Any])


def log_node_execution(func: F) -> F:
    """Decorator to log node execution."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        node_name = func.__name__
        logger.info(f"▶ START Node: [{node_name}]")
        try:
            result = await func(*args, **kwargs)
            logger.info(f"✔ END Node: [{node_name}]")
            if result:
                keys = list(result.keys())
                logger.info(f"   -> Updates: {keys}")
            return result
        except ValueError as e:
            # Domain/Logic errors (like 404/Context missing)
            logger.warning(f"⚠ Domain Error in Node [{node_name}]: {e}")
            service_name = NODE_SERVICE_MAP.get(node_name, "Internal")
            raise PipelineError(
                node_name=node_name,
                message=str(e),
                original_error=e,
                service_name=service_name,
            ) from e
        except Exception as e:
            # System/Network errors
            logger.error(f"❌ System Error in Node [{node_name}]: {e}")
            service_name = NODE_SERVICE_MAP.get(node_name, "Internal")
            raise PipelineError(
                node_name=node_name,
                message=str(e),
                original_error=e,
                service_name=service_name,
            ) from e

    return cast(F, wrapper)

    return cast(F, wrapper)


class GameEngine:
    _TERMINAL_CLAIM_PATTERNS = [
        r"모험은 끝이 났다",
        r"작전[이가은는 ]*성공적으로[ ]*마무리",
        r"작전[을를 ]*마무리",
        r"결전[을를 ]*마무리",
        r"전투[가은는 ]*끝났",
        r"전투[가은는 ]*끝나",
        r"모든[ ]*적[이가은는 ]*쓰러",
        r"마침내[ ].*쓰러",
        r"적의[ ]*위협[이가은는 ]*사라졌",
        r"봉인.*안정화",
        r"마지막[ ]*남은[ ]*.*적",
        r"핵심[ ]*적[을를 ]*처치",
        r"승리[를을 ]*확신",
        r"승리",
        r"고통[이가은는 ]*마침내[ ]*끝",
        r"전투의[ ]*긴장감[이가은는 ]*사라",
        r"평화로[ ]*가득",
    ]

    def __init__(
        self,
        rule_client: RuleManagerPort,
        scenario_client: ScenarioManagerPort,
        state_client: StateManagerPort,
        llm: LLMPort,
        db: DatabaseHandler,
    ):
        self.rule_client = rule_client
        self.scenario_client = scenario_client
        self.state_client = state_client
        self.llm = llm
        self.db = db
        self.graph: CompiledStateGraph = self._build_graph()

    def _resolve_active_entity_name(
        self, snapshot: Dict[str, Any], active_entity_id: str | None
    ) -> str:
        actor = (active_entity_id or "").strip()
        actor_l = actor.lower()
        if actor_l == "player":
            return "player"
        if actor_l == "narrator":
            return "narrator"

        for key in ("npcs", "enemies"):
            for entity in snapshot.get(key, []) or []:
                entity_name = entity.get("name")
                candidate_ids = [
                    entity.get("scenario_entity_id"),
                    entity.get("entity_id"),
                    entity.get("scenario_npc_id"),
                    entity.get("scenario_enemy_id"),
                ]
                candidate_ids_l = [str(v).lower() for v in candidate_ids if v]
                if actor_l in candidate_ids_l:
                    return entity_name or actor
                if entity_name and str(entity_name).lower() == actor_l:
                    return entity_name

        return actor or "unknown"

    @staticmethod
    def _has_live_enemies_in_current_sequence(snapshot: Dict[str, Any]) -> bool:
        current_seq_id = str(snapshot.get("current_sequence_id") or "")
        enemies = snapshot.get("enemies", []) or []

        for enemy in enemies:
            if not isinstance(enemy, dict):
                continue

            assigned_seq_id = str(enemy.get("assigned_sequence_id") or "")
            if current_seq_id and assigned_seq_id and assigned_seq_id != current_seq_id:
                continue

            if bool(enemy.get("is_defeated")):
                continue

            hp = enemy.get("current_hp")
            if hp is None:
                hp = ((enemy.get("state") or {}).get("numeric") or {}).get("HP")

            if hp is None:
                return True

            try:
                if int(hp) > 0:
                    return True
            except (TypeError, ValueError):
                return True

        return False

    @staticmethod
    def _count_enemies_in_current_sequence(snapshot: Dict[str, Any]) -> int:
        current_seq_id = str(snapshot.get("current_sequence_id") or "")
        enemies = snapshot.get("enemies", []) or []
        count = 0
        for enemy in enemies:
            if not isinstance(enemy, dict):
                continue
            assigned_seq_id = str(enemy.get("assigned_sequence_id") or "")
            if current_seq_id and assigned_seq_id and assigned_seq_id != current_seq_id:
                continue
            count += 1
        return count

    @staticmethod
    def _count_live_enemies_in_current_sequence(snapshot: Dict[str, Any]) -> int:
        current_seq_id = str(snapshot.get("current_sequence_id") or "")
        enemies = snapshot.get("enemies", []) or []
        count = 0
        for enemy in enemies:
            if not isinstance(enemy, dict):
                continue
            assigned_seq_id = str(enemy.get("assigned_sequence_id") or "")
            if current_seq_id and assigned_seq_id and assigned_seq_id != current_seq_id:
                continue
            if bool(enemy.get("is_defeated")):
                continue
            hp = enemy.get("current_hp")
            if hp is None:
                hp = ((enemy.get("state") or {}).get("numeric") or {}).get("HP")
            if hp is None:
                count += 1
                continue
            try:
                if int(hp) > 0:
                    count += 1
            except (TypeError, ValueError):
                count += 1
        return count

    @staticmethod
    def _is_last_sequence_in_act(
        current_sequence_id: str | None, act_details: Dict[str, Any] | None
    ) -> bool:
        if not current_sequence_id or not isinstance(act_details, dict):
            return False
        sequence_ids = act_details.get("sequence_ids") or []
        if not isinstance(sequence_ids, list) or not sequence_ids:
            return False
        return str(sequence_ids[-1]) == str(current_sequence_id)

    @classmethod
    def _contains_terminal_claim(cls, text: str | None) -> bool:
        if not text:
            return False
        src = str(text)
        return any(
            re.search(pattern, src, flags=re.IGNORECASE)
            for pattern in cls._TERMINAL_CLAIM_PATTERNS
        )

    @classmethod
    def _sanitize_terminal_claims(cls, text: str | None) -> str:
        src = str(text or "")
        out = src
        for pattern in cls._TERMINAL_CLAIM_PATTERNS:
            out = re.sub(pattern, "", out, flags=re.IGNORECASE)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        if not out:
            out = "전투는 아직 끝나지 않았고 적의 위협이 남아 있다."
        else:
            out = f"{out}\n\n전투는 아직 끝나지 않았고 적의 위협이 남아 있다."
        return out

    @staticmethod
    def _resolve_sequence_type(snapshot: Dict[str, Any], fallback: str | None) -> str:
        metadata = snapshot.get("metadata") or {}
        hint = ""
        if isinstance(metadata, dict):
            hint = str(
                metadata.get("sequence_type")
                or metadata.get("phase_type")
                or metadata.get("type")
                or ""
            )
        if not hint:
            hint = str(snapshot.get("current_phase") or fallback or "")

        norm = hint.strip().upper()
        if not norm:
            return "EXPLORATION"

        if any(k in norm for k in ["COMBAT", "BATTLE", "BOSS", "교전", "결전"]):
            return "COMBAT"
        if any(k in norm for k in ["DIALOG", "DIALOGUE", "대화"]):
            return "DIALOGUE"
        if any(k in norm for k in ["NEGO", "NEGOTIATION", "협상", "흥정"]):
            return "NEGO"
        if any(k in norm for k in ["REST", "휴식"]):
            return "REST"
        if any(k in norm for k in ["RECOVERY", "HEAL", "회복"]):
            return "RECOVERY"
        if any(k in norm for k in ["INFILTRATION", "STEALTH", "잠입"]):
            return "EXPLORATION"
        if any(k in norm for k in ["EXPLORATION", "EXPLORE", "탐색"]):
            return "EXPLORATION"
        return "EXPLORATION"

    async def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        query = self.db.get_query("get_session_history")
        rows = await self.db.fetch(query, session_id)
        history: List[Dict[str, Any]] = []
        for row in rows:
            history.append(
                {
                    "session_id": row["session_id"],
                    "act_id": row["act_id"],
                    "sequence_id": row["sequence_id"],
                    "sequence_type": row["sequence_type"],
                    "sequence_seq": row["sequence_seq"],
                    "turn_seq": row["turn_seq"],
                    "active_entity_id": row["active_entity_id"],
                    "user_input": row["user_input"],
                    "narrative": row["final_output"],
                    "created_at": (
                        row["created_at"].isoformat()
                        if row.get("created_at") is not None
                        else None
                    ),
                }
            )
        return history

    async def process_player_turn(self, user_input: Any) -> Dict[str, Any]:
        pre_sequence_id: str | None = None
        try:
            before = await self.state_client.get_state(user_input.session_id)
            pre_sequence_id = (
                str(before.get("current_sequence_id"))
                if before.get("current_sequence_id")
                else None
            )
        except Exception:
            pre_sequence_id = None

        player_state = {
            "session_id": user_input.session_id,
            "user_input": user_input.content,
            "is_npc_turn": False,
            # Context defaults
            "active_entity_id": "player",
            "act_id": "act-1",
            "sequence_id": "seq-1",
            "sequence_type": "EXPLORATION",
            "sequence_seq": 1,
            # world_snapshot will be loaded by fetch_state node
        }

        player_result_state = await self.graph.ainvoke(player_state)

        player_response = {
            "turn_id": player_result_state["turn_id"],
            "narrative": player_result_state["narrative"],
            "commit_id": player_result_state["commit_id"],
            "active_entity_id": player_result_state.get("active_entity_id", "player"),
            "active_entity_name": "player",
            "output_type": TurnOutputType.NARRATION,
            "is_npc_turn": False,
        }

        # 2. Check if there are active entities (NPCs/Enemies)
        snapshot = player_result_state.get("world_snapshot", {})
        entities = snapshot.get("entities", [])
        scenario = player_result_state.get("scenario_suggestion")

        should_end = bool(getattr(scenario, "should_end", False))
        latest = None
        if not should_end:
            try:
                latest = await self.state_client.get_state(user_input.session_id)
                should_end = str(latest.get("status", "")).lower() == "ended"
            except Exception:
                # 상태 조회 실패는 치명 에러로 올리지 않고 기존 흐름을 유지
                pass
        post_sequence_id = (
            str((latest or {}).get("current_sequence_id"))
            if isinstance(latest, dict) and (latest or {}).get("current_sequence_id")
            else None
        )
        sequence_transitioned = bool(
            pre_sequence_id and post_sequence_id and pre_sequence_id != post_sequence_id
        )

        # 3. Process NPC Turn only if entities exist
        if entities and not should_end and not sequence_transitioned:
            logger.info(f"Active entities found: {entities}. Proceeding to NPC turn.")
            npc_response = await self.process_npc_turn(user_input.session_id)
            player_response["npc_turn"] = npc_response
        elif entities and sequence_transitioned:
            logger.info(
                "Sequence transitioned (%s -> %s). Skipping NPC turn for this player turn.",
                pre_sequence_id,
                post_sequence_id,
            )
            player_response["npc_turn"] = None
        elif entities and should_end:
            logger.info("Session already ended. Skipping NPC turn.")
            player_response["npc_turn"] = None
        else:
            logger.info("No active entities found. Skipping NPC turn.")
            player_response["npc_turn"] = None

        return player_response

    async def process_npc_turn(self, session_id: str) -> Dict[str, Any]:
        # NPC 턴인 경우 user_input은 그래프 내부의 generate_npc_input 노드에서 생성됨
        initial_state = {
            "session_id": session_id,
            "user_input": "",  # 그래프 내부에서 생성될 예정
            "is_npc_turn": True,
            # Context defaults (will be overridden by fetch_state)
            "active_entity_id": "npc_pending",
            "sequence_type": "EXPLORATION",
        }

        # 그래프 비동기 실행
        final_state = await self.graph.ainvoke(initial_state)

        output_type = (
            TurnOutputType.NARRATION
            if str(final_state.get("active_entity_id", "")).lower() == "narrator"
            else TurnOutputType.NPC
        )
        active_entity_id = final_state.get("active_entity_id")
        active_entity_name = self._resolve_active_entity_name(
            final_state.get("world_snapshot", {}) or {},
            active_entity_id,
        )

        return {
            "turn_id": final_state["turn_id"],
            "narrative": final_state["narrative"],
            "commit_id": final_state["commit_id"],
            "active_entity_id": active_entity_id,  # Return who acted
            "active_entity_name": active_entity_name,
            "output_type": output_type,
            "is_npc_turn": True,
        }

    async def _fetch_history(
        self, session_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Helper to fetch recent history."""
        query = self.db.get_query("fetch_history_limit")
        history: List[Dict[str, Any]] = []
        try:
            rows = await self.db.fetch(query, session_id, limit)
            for row in reversed(rows):
                history.append(
                    {
                        "player": row["user_input"],
                        "narrative": row["final_output"],
                    }
                )
        except Exception as e:
            logger.error(f"Failed to fetch history: {e}")
        return history

    @log_node_execution
    async def fetch_state(self, state: TurnContext) -> TurnContext:
        """Fetch latest world state from State Manager."""
        session_id = state["session_id"]
        try:
            snapshot = await self.state_client.get_state(session_id)
        except Exception as e:
            logger.error(f"Failed to fetch base session state: {e}")
            return {}

        # sequence/details가 일시 실패해도 base session state는 유지한다.
        try:
            details = await self.state_client.get_sequence_details(session_id)
            snapshot.update(details)
        except Exception as e:
            logger.warning(f"Failed to fetch sequence details (continue): {e}")
            snapshot.setdefault("npcs", [])
            snapshot.setdefault("enemies", [])
            snapshot.setdefault("entity_relations", [])
            snapshot.setdefault("player_npc_relations", [])

        try:
            act_details = await self.state_client.get_act_details(session_id)
            snapshot["act"] = act_details
        except Exception as e:
            logger.warning(f"Failed to fetch act details (continue): {e}")
            snapshot.setdefault("act", {})

        entities = []
        for npc in snapshot.get("npcs", []):
            entities.append(
                npc.get("scenario_entity_id")
                or npc.get("scenario_npc_id")
                or npc.get("npc_id")
            )
        for enemy in snapshot.get("enemies", []):
            entities.append(
                enemy.get("scenario_entity_id")
                or enemy.get("scenario_enemy_id")
                or enemy.get("enemy_id")
            )
        snapshot["entities"] = entities

        logger.info(
            f"   -> Fetched Snapshot Scenario ID: {snapshot.get('scenario_id')}"
        )

        return {
            "world_snapshot": snapshot,
            "scenario_id": snapshot.get("scenario_id") or state.get("scenario_id"),
            "act_id": snapshot.get("current_act_id") or state.get("act_id"),
            "sequence_id": snapshot.get("current_sequence_id")
            or state.get("sequence_id"),
            "sequence_type": self._resolve_sequence_type(
                snapshot, state.get("sequence_type")
            ),
            "sequence_seq": snapshot.get("current_turn") or state.get("sequence_seq"),
        }

    def _load_prompt(self, relative_path: str) -> str:
        """Load a prompt template from a file."""
        base_dir = os.path.join(os.path.dirname(__file__), "prompts")
        file_path = os.path.join(base_dir, relative_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"Failed to load prompt from {file_path}: {e}")
            return ""

    @log_node_execution
    async def select_active_entity(self, state: TurnContext) -> TurnContext:
        """Decide active entity for the turn. Automatically falls back to 'narrator'."""
        if not state.get("is_npc_turn"):
            return {"active_entity_id": "player"}

        history = await self._fetch_history(state["session_id"], limit=5)
        snapshot = state.get("world_snapshot", {})

        # Gather NPCs and Enemies
        entities = snapshot.get("entities", [])
        candidate_entities = [e for e in entities if str(e).lower() != "player"]

        # If no NPCs or enemies, narrator MUST act
        if not candidate_entities:
            logger.info(
                "   -> No entities in sequence. Automatically selecting 'narrator'."
            )
            return {"active_entity_id": "narrator"}

        # If there are NPCs, let LLM decide between NPCs and Narrator
        candidate_entities.append("narrator")
        entity_list_str = ", ".join([str(e) for e in candidate_entities])

        system_instruction = self._load_prompt("select_active_entity/system.txt")
        user_prompt = self._load_prompt("select_active_entity/user.txt")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_instruction),
                ("user", user_prompt),
            ]
        )

        chain = prompt | self.llm

        try:
            response_msg = await chain.ainvoke(
                {
                    "entity_list": entity_list_str,
                    "history": history,
                    "sequence_type": state.get("sequence_type", "EXPLORATION"),
                }
            )
            selected_entity = response_msg.content.strip().lower()

            # Validation: ensure selected is in our candidate list
            if selected_entity not in [str(e).lower() for e in candidate_entities]:
                selected_entity = "narrator"

            logger.info(f"   -> Selected Actor: {selected_entity}")
            return {"active_entity_id": selected_entity}
        except Exception as e:
            logger.error(f"Actor selection failed: {e}. Defaulting to 'narrator'.")
            return {"active_entity_id": "narrator"}

    @log_node_execution
    async def generate_npc_input(self, state: TurnContext) -> TurnContext:
        """Generate NPC action or Narrator guidance via LLM."""
        if not state.get("is_npc_turn"):
            return {}

        history = await self._fetch_history(state["session_id"])
        actor = state.get("active_entity_id", "narrator")
        snapshot = state.get("world_snapshot", {})

        # Additional context for Narrator
        sequence_info = snapshot.get(
            "sequence", {}
        )  # This comes from get_sequence_details
        exit_triggers = sequence_info.get("exit_triggers", [])
        goal = sequence_info.get("goal", "상황에 몰입하기")

        if actor.lower() == "narrator":
            system_instruction = self._load_prompt(
                "generate_npc_input/narrator_system.txt"
            )
            user_prompt = self._load_prompt("generate_npc_input/narrator_user.txt")
        else:
            system_instruction = self._load_prompt("generate_npc_input/npc_system.txt")
            user_prompt = self._load_prompt("generate_npc_input/npc_user.txt")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_instruction),
                ("user", user_prompt),
            ]
        )

        chain = prompt | self.llm

        try:
            response_msg = await chain.ainvoke(
                {
                    "history": history,
                    "goal": goal,
                    "exit_triggers": exit_triggers,
                    "actor": actor,
                    "sequence_type": state.get("sequence_type", "EXPLORATION"),
                }
            )
            npc_action_text = response_msg.content
            logger.info(f"   -> Generated Action for [{actor}]: {npc_action_text}")
        except Exception as e:
            logger.error(f"Failed to generate actor input: {e}")
            npc_action_text = (
                "주변에 정적이 흐릅니다. 당신의 다음 결정을 기다리는 듯합니다."
            )

        return {"user_input": npc_action_text}

    @log_node_execution
    async def init_turn(self, state: TurnContext) -> TurnContext:
        """Init turn ID."""
        query = self.db.get_query("get_next_turn_seq")
        try:
            val = await self.db.fetchval(query, state["session_id"])
            seq = val if val else 1
        except Exception:
            seq = 1

        turn_id = f"{state['session_id']}:{seq}"
        logger.info(f"   -> New Turn ID: {turn_id}")
        return {"turn_seq": seq, "turn_id": turn_id}

    @log_node_execution
    async def check_rule(self, state: TurnContext) -> TurnContext:
        """Call Rule Manager. Skip for Narrator."""
        from gm.schemas.rule_engine import RuleOutcome

        active_entity = state.get("active_entity_id", "player")
        if active_entity.lower() == "narrator":
            logger.info("   -> Actor is Narrator. Skipping Rule Check.")
            # Return a default success outcome for narrator
            return {
                "rule_outcome": RuleOutcome(
                    session_id=state.get("session_id", "unknown"),
                    scenario_id=state.get("scenario_id") or "unknown",
                    success=True,
                    reason="나레이터의 서술입니다.",
                    suggested={"diffs": [], "relations": []},
                )
            }

        try:
            proposal = await self.rule_client.get_proposal(state)
        except Exception as e:
            logger.warning(
                "rule_engine_unavailable_fallback error=%s", type(e).__name__
            )
            proposal = RuleOutcome(
                session_id=state.get("session_id", "unknown"),
                scenario_id=state.get("scenario_id") or "unknown",
                success=True,
                reason="룰 엔진 오류로 기본 판정을 적용합니다.",
                suggested={"diffs": [], "relations": []},
            )
        return {"rule_outcome": proposal}

    @log_node_execution
    async def check_scenario(self, state: TurnContext) -> TurnContext:
        """Call Scenario Manager."""
        rule_outcome = state.get("rule_outcome")
        if not rule_outcome:
            logger.warning("Rule outcome is missing in check_scenario")
            raise ValueError("Rule outcome is required for scenario check")

        proposal = await self.scenario_client.get_proposal(state)
        return {"scenario_suggestion": proposal}

    @log_node_execution
    async def resolve_conflicts(self, state: TurnContext) -> TurnContext:
        """Resolve Rule vs Scenario conflicts."""
        rule = state.get("rule_outcome")
        scenario = state.get("scenario_suggestion")

        if not rule:
            raise ValueError("Rule outcome missing in resolve_conflicts")
        if not scenario:
            # If scenario is missing, maybe just use rule?
            # For now strict check
            raise ValueError("Scenario suggestion missing in resolve_conflicts")

        resolved_diffs_map = {}

        # 1. Rule Diffs
        for d in rule.suggested_diffs:
            eid = d["entity_id"]
            resolved_diffs_map[eid] = d["diff"].copy()

        # 2. Scenario Diffs
        for s_diff in scenario.correction_diffs:
            eid = s_diff["entity_id"]
            s_data = s_diff["diff"]

            if eid not in resolved_diffs_map:
                resolved_diffs_map[eid] = s_data.copy()
                continue

            # Check if value_range is a dict before using it for field checks
            # Currently the logic was redundant (same assignment),
            # so simplifying to direct update
            # unless we implement actual constraint clamping later.
            is_constrained = isinstance(rule.value_range, dict)

            for field, s_val in s_data.items():
                if is_constrained and field in rule.value_range:
                    # TODO: Implement actual clamping logic
                    # if needed using rule.value_range[field]
                    resolved_diffs_map[eid][field] = s_val
                else:
                    resolved_diffs_map[eid][field] = s_val

        final_diffs = [
            EntityDiff(entity_id=eid, diff=diff)
            for eid, diff in resolved_diffs_map.items()
        ]

        return {"final_diffs": final_diffs}

    @log_node_execution
    async def commit_state(self, state: TurnContext) -> TurnContext:
        """Commit to State Manager."""
        turn_id = state.get("turn_id")
        if not turn_id:
            raise ValueError("Turn ID is missing")
        logger.info(
            "   -> Commit turn_id=%s (state.session_id=%s)",
            turn_id,
            state.get("session_id"),
        )

        final_diffs = state.get("final_diffs", [])
        logger.info("   -> final_diffs count=%s", len(final_diffs))

        # 1. Commit entity diffs
        result = await self.state_client.commit(turn_id, final_diffs)

        # 2. Handle Location Transition (Act/Sequence Jump) from Scenario Service
        scenario = state.get("scenario_suggestion")
        transitioned = False
        if scenario:
            if scenario.next_act_id:
                if not scenario.next_seq_id:
                    raise ValueError(
                        "Scenario transition mismatch: "
                        "next_seq_id is required when next_act_id is set"
                    )
                logger.info(f"   -> Transitioning to ACT: {scenario.next_act_id}")
                await self.state_client.update_act(
                    state["session_id"], scenario.next_act_id, scenario.next_seq_id
                )
                transitioned = True
            elif scenario.next_seq_id:
                logger.info(f"   -> Transitioning to SEQUENCE: {scenario.next_seq_id}")
                await self.state_client.update_sequence(
                    state["session_id"], scenario.next_seq_id
                )
                transitioned = True

            # Explicit scenario completion signal from scenario-service.
            if scenario.should_end and not transitioned:
                session_id = state["session_id"]
                try:
                    latest_state = await self.state_client.get_state(session_id)
                    latest_sequence = await self.state_client.get_sequence_details(
                        session_id
                    )
                except Exception as e:
                    logger.warning(
                        "   -> Unable to verify terminal enemy state. "
                        "Deferring end_session. error=%s",
                        type(e).__name__,
                    )
                    scenario.should_end = False
                    latest_state = None
                    latest_sequence = None

                latest_snapshot = dict(latest_state or {})
                if isinstance(latest_sequence, dict):
                    if latest_sequence.get("enemies") is not None:
                        latest_snapshot["enemies"] = latest_sequence.get("enemies")
                    if (
                        not latest_snapshot.get("current_sequence_id")
                        and latest_sequence.get("sequence_id")
                    ):
                        latest_snapshot["current_sequence_id"] = latest_sequence.get(
                            "sequence_id"
                        )

                if latest_snapshot and self._has_live_enemies_in_current_sequence(
                    latest_snapshot
                ):
                    logger.info(
                        "   -> Terminal signal received but live enemies remain. "
                        "Deferring end_session."
                    )
                    scenario.should_end = False
                elif latest_snapshot:
                    logger.info("   -> Ending session by scenario completion signal")
                    await self.state_client.end_session(session_id)
            elif not scenario.should_end and not transitioned:
                # Fallback gate:
                # When scenario-service misses should_end on terminal sequence,
                # auto-close only if terminal sequence enemies are all defeated.
                session_id = state["session_id"]
                try:
                    latest_state = await self.state_client.get_state(session_id)
                    latest_sequence = await self.state_client.get_sequence_details(
                        session_id
                    )
                    act_details = await self.state_client.get_act_details(session_id)
                except Exception as e:
                    logger.debug(
                        "   -> Terminal fallback check skipped. error=%s",
                        type(e).__name__,
                    )
                    latest_state = None
                    latest_sequence = None
                    act_details = None

                latest_snapshot = dict(latest_state or {})
                if isinstance(latest_sequence, dict):
                    if latest_sequence.get("enemies") is not None:
                        latest_snapshot["enemies"] = latest_sequence.get("enemies")
                    if (
                        not latest_snapshot.get("current_sequence_id")
                        and latest_sequence.get("sequence_id")
                    ):
                        latest_snapshot["current_sequence_id"] = latest_sequence.get(
                            "sequence_id"
                        )

                current_seq_id = str(latest_snapshot.get("current_sequence_id") or "")
                is_terminal_seq = self._is_last_sequence_in_act(
                    current_seq_id, act_details
                )
                total_enemies = self._count_enemies_in_current_sequence(latest_snapshot)
                has_live_enemies = self._has_live_enemies_in_current_sequence(
                    latest_snapshot
                )
                if is_terminal_seq and total_enemies > 0 and not has_live_enemies:
                    logger.info(
                        "   -> Auto-ending session by terminal-state fallback "
                        "(seq=%s, enemies=%s)",
                        current_seq_id,
                        total_enemies,
                    )
                    scenario.should_end = True
                    await self.state_client.end_session(session_id)

        return {"commit_id": result["commit_id"]}

    @log_node_execution
    async def generate_narrative(self, state: TurnContext) -> TurnContext:
        """Generate narrative via LLM."""
        max_retries = 3
        scenario = state.get("scenario_suggestion")
        if not scenario:
            raise ValueError("Scenario suggestion missing")

        rule_outcome = state.get("rule_outcome")
        if not rule_outcome:
            raise ValueError("Rule outcome missing")

        active_entity = state.get("active_entity_id", "player")
        is_narrator = active_entity.lower() == "narrator"

        if is_narrator:
            system_instruction = self._load_prompt(
                "generate_narrative/narrator_system.txt"
            )
        else:
            system_instruction = self._load_prompt("generate_narrative/gm_system.txt")

        user_prompt = self._load_prompt("generate_narrative/user.txt")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_instruction),
                ("user", user_prompt),
            ]
        )

        chain = prompt | self.llm

        # Fetch post-commit snapshot for narrative guardrails.
        snapshot = dict(state.get("world_snapshot", {}) or {})
        try:
            latest_state = await self.state_client.get_state(state["session_id"])
            latest_sequence = await self.state_client.get_sequence_details(
                state["session_id"]
            )
            snapshot = dict(latest_state or {})
            if isinstance(latest_sequence, dict):
                if latest_sequence.get("enemies") is not None:
                    snapshot["enemies"] = latest_sequence.get("enemies")
                if latest_sequence.get("npcs") is not None:
                    snapshot["npcs"] = latest_sequence.get("npcs")
                if latest_sequence.get("items") is not None:
                    snapshot["items"] = latest_sequence.get("items")
                if (
                    not snapshot.get("current_sequence_id")
                    and latest_sequence.get("sequence_id")
                ):
                    snapshot["current_sequence_id"] = latest_sequence.get("sequence_id")
                if (
                    not snapshot.get("sequence_name")
                    and latest_sequence.get("sequence_name")
                ):
                    snapshot["sequence_name"] = latest_sequence.get("sequence_name")
                if latest_sequence.get("location_name"):
                    snapshot["location_name"] = latest_sequence.get("location_name")
                if latest_sequence.get("goal"):
                    snapshot["goal"] = latest_sequence.get("goal")
        except Exception as e:
            logger.debug(
                "narrative_guard_snapshot_refresh_failed error=%s",
                type(e).__name__,
            )

        has_live_enemies = self._has_live_enemies_in_current_sequence(snapshot)
        session_ended = str(snapshot.get("status", "")).lower() == "ended"

        # Fetch history for context
        history = await self._fetch_history(state["session_id"], limit=5)
        narrative = ""

        forbidden_narrative_instruction = ""
        if has_live_enemies:
            forbidden_narrative_instruction = (
                "\n[금지 표현]\n"
                "현재 시퀀스에 생존 적이 남아 있다. 아래와 같은 종료/완료 선언은 절대 쓰지 마라:\n"
                "- 모험은 끝이 났다.\n"
                "- 작전이 성공적으로 마무리되었다.\n"
                "- 모든 적이 쓰러졌다.\n"
                "- 봉인이 완전히 안정화되었다.\n"
                "- 마지막 남은 적/핵심 적을 처치했다는 단정.\n"
                "- 승리를 확신하거나 전투 종료를 기정사실화하는 표현.\n"
            )

        for attempt_idx in range(max_retries):
            try:
                snapshot_view = {
                    "scenario_id": snapshot.get("scenario_id"),
                    "current_act_id": snapshot.get("current_act_id"),
                    "current_sequence_id": snapshot.get("current_sequence_id"),
                    "sequence_name": snapshot.get("sequence_name"),
                    "location_name": snapshot.get("location_name"),
                    "goal": snapshot.get("goal"),
                    "npcs": [
                        {
                            "id": (
                                n.get("scenario_entity_id")
                                or n.get("scenario_npc_id")
                                or n.get("npc_id")
                            ),
                            "name": n.get("name"),
                        }
                        for n in snapshot.get("npcs", [])
                    ],
                    "enemies": [
                        {
                            "id": (
                                e.get("scenario_entity_id")
                                or e.get("scenario_enemy_id")
                                or e.get("enemy_id")
                            ),
                            "name": e.get("name"),
                            "hp": (
                                e.get("current_hp")
                                if e.get("current_hp") is not None
                                else ((e.get("state") or {}).get("numeric") or {}).get(
                                    "HP"
                                )
                            ),
                            "is_defeated": bool(e.get("is_defeated")),
                            "assigned_sequence_id": e.get("assigned_sequence_id"),
                        }
                        for e in snapshot.get("enemies", [])
                    ],
                    "items": [
                        {"id": i.get("scenario_item_id"), "name": i.get("name")}
                        for i in snapshot.get("items", [])
                    ],
                }
                context = {
                    "input_text": state["user_input"],
                    "outcome": rule_outcome.model_dump(),
                    "required_narrative_instruction": "",
                    "forbidden_narrative_instruction": forbidden_narrative_instruction,
                    "history": history,
                    "active_entity_id": active_entity,
                    "world_snapshot": json.dumps(snapshot_view, ensure_ascii=False),
                }
                response_msg = await chain.ainvoke(context)
            except Exception as e:
                logger.exception("Error during narrative generation ainvoke")
                raise e
            narrative = response_msg.content

            if has_live_enemies and self._contains_terminal_claim(narrative):
                logger.warning(
                    "Narrative declared terminal/completion while live enemies remain. "
                    "Retrying... attempt=%s/%s",
                    attempt_idx + 1,
                    max_retries,
                )
                if attempt_idx < max_retries - 1:
                    continue
                live_enemy_count = self._count_live_enemies_in_current_sequence(snapshot)
                narrative = (
                    "교전이 계속되고 있다. "
                    f"현재 시퀀스에는 아직 쓰러지지 않은 적이 {live_enemy_count}명 남아 있다. "
                    "전투는 아직 끝나지 않았고 적의 위협이 남아 있다."
                )
                break

            break

        # Do not let LLM decide termination phrasing from transition hints.
        # Append terminal line only from committed state.
        if session_ended and not has_live_enemies and "모험은 끝이 났다." not in narrative:
            narrative = f"{narrative.strip()}\n\n모험은 끝이 났다."

        return {"narrative": narrative}

    @log_node_execution
    async def save_log(self, state: TurnContext) -> TurnContext:
        """Save Play Log."""
        query = self.db.get_query("insert_play_log")
        diffs_json = json.dumps([d.model_dump() for d in state["final_diffs"]])
        snapshot_json = json.dumps(state.get("world_snapshot", {}))

        try:
            await self.db.execute(
                query,
                state["turn_id"],
                state["session_id"],
                state["turn_seq"],
                state["user_input"],
                state["narrative"],
                diffs_json,
                state["commit_id"],
                state.get("act_id"),
                state.get("sequence_id"),
                state.get("sequence_type"),
                state.get("sequence_seq"),
                state.get("active_entity_id", "player"),
                snapshot_json,
            )
        except Exception as e:
            logger.error(f"Failed to save log: {e}")

        return {}

    async def generate_summary(self, session_id: str) -> str:
        """
        Generates a situational briefing for the player
        based on current state and history.
        Used for opening scenes or session resumption.
        """
        # 1. Fetch State (Reuse logic manually or call client directly)
        try:
            snapshot = await self.state_client.get_state(session_id)
            details = await self.state_client.get_sequence_details(session_id)
            snapshot.update(details)

            # `act/details` can be unavailable depending on state-manager version.
            # Summary should still be generated from current session/sequence context.
            try:
                act_details = await self.state_client.get_act_details(session_id)
            except Exception:
                act_details = {}
            snapshot["act"] = act_details if isinstance(act_details, dict) else {}

            # Entities list string
            entities = []
            for npc in snapshot.get("npcs", []):
                name = npc.get("name", "Unknown")
                desc = npc.get("description", "")[:30]
                entities.append(f"{name}({desc})")
            for enemy in snapshot.get("enemies", []):
                name = enemy.get("name", "Unknown")
                desc = enemy.get("description", "")[:30]
                entities.append(f"{name}({desc})")

            entity_str = ", ".join(entities) if entities else "없음"

        except Exception as e:
            logger.error(f"Failed to fetch state for summary: {e}")
            return "현재 상황을 파악할 수 없습니다."

        # 2. Fetch History
        history = await self._fetch_history(session_id, limit=5)
        history_text = "\n".join(
            [f"- {h['player']} -> {h['narrative']}" for h in history]
        )
        if not history_text:
            history_text = "(기록 없음 - 게임 시작)"

        # 3. Load Prompts
        system_instruction = self._load_prompt("generate_summary/system.txt")
        user_prompt = self._load_prompt("generate_summary/user.txt")

        # 4. LLM Generation
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_instruction),
                ("user", user_prompt),
            ]
        )
        chain = prompt | self.llm

        try:
            response_msg = await chain.ainvoke(
                {
                    "act_name": (
                        snapshot.get("act", {}).get("act_name")
                        or snapshot.get("current_act_id")
                        or "Unknown"
                    ),
                    "sequence_name": snapshot.get("sequence_name", "Unknown"),
                    "goal": snapshot.get("goal", "생존"),
                    "entities": entity_str,
                    "player_hp": snapshot.get("player", {}).get("hp", "?"),
                    "history": history_text,
                }
            )
            return response_msg.content
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return "상황 요약을 생성하는 도중 오류가 발생했습니다."

    def _build_graph(self) -> CompiledStateGraph:
        workflow = StateGraph(TurnContext)

        # Add Nodes (bound to self)
        workflow.add_node("fetch_state", self.fetch_state)
        workflow.add_node("select_active_entity", self.select_active_entity)
        workflow.add_node("generate_npc_input", self.generate_npc_input)
        workflow.add_node("init_turn", self.init_turn)
        workflow.add_node("check_rule", self.check_rule)
        workflow.add_node("check_scenario", self.check_scenario)
        workflow.add_node("resolve_conflicts", self.resolve_conflicts)
        workflow.add_node("commit_state", self.commit_state)
        workflow.add_node("generate_narrative", self.generate_narrative)
        workflow.add_node("save_log", self.save_log)

        # Entry
        workflow.set_entry_point("fetch_state")

        # Edges
        workflow.add_edge("fetch_state", "select_active_entity")
        workflow.add_edge("select_active_entity", "generate_npc_input")
        workflow.add_edge("generate_npc_input", "init_turn")
        workflow.add_edge("init_turn", "check_rule")
        workflow.add_edge("check_rule", "check_scenario")
        workflow.add_edge("check_scenario", "resolve_conflicts")
        workflow.add_edge("resolve_conflicts", "commit_state")
        workflow.add_edge("commit_state", "generate_narrative")
        workflow.add_edge("generate_narrative", "save_log")
        workflow.add_edge("save_log", END)

        return workflow.compile()
