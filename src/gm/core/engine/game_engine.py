import functools
import json
import logging
import os
from typing import Any, Callable, Dict, List, TypeVar, cast

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from gm.core.models.context import TurnContext
from gm.core.models.state import EntityDiff
from gm.exceptions import PipelineError
from gm.infra.db.database import DatabaseHandler
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)
from gm.interfaces.llm import LLMPort

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

    async def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        query = self.db.get_query("get_session_history")
        rows = await self.db.fetch(query, session_id)
        return [dict(row) for row in rows]

    async def process_player_turn(self, user_input: Any) -> Dict[str, Any]:
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
        }

        # 2. Automatically Process NPC Turn
        npc_response = await self.process_npc_turn(user_input.session_id)

        # 3. Return Combined Result
        player_response["npc_turn"] = npc_response

        return player_response

    async def process_npc_turn(self, session_id: str) -> Dict[str, Any]:
        # NPC 턴인 경우 user_input은 그래프 내부의 generate_npc_input 노드에서 생성됨
        initial_state = {
            "session_id": session_id,
            "user_input": "",  # 그래프 내부에서 생성될 예정
            "is_npc_turn": True,
            # Context defaults
            "active_entity_id": "npc_pending",  # Will be decided in graph
            "act_id": "act-1",
            "sequence_id": "seq-1",
            "sequence_type": "COMBAT",
            "sequence_seq": 1,
            # world_snapshot will be loaded by fetch_state node
        }

        # 그래프 비동기 실행
        final_state = await self.graph.ainvoke(initial_state)

        return {
            "turn_id": final_state["turn_id"],
            "narrative": final_state["narrative"],
            "commit_id": final_state["commit_id"],
            "active_entity_id": final_state.get("active_entity_id"),  # Return who acted
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
        try:
            session_id = state["session_id"]
            # 1. Session Info (player_id, phase, turn 등)
            snapshot = await self.state_client.get_state(session_id)

            # 2. Sequence Details (NPCs, Enemies, Relations 등)
            details = await self.state_client.get_sequence_details(session_id)

            # 3. Fetch all sequences for the current act (for scenario jump logic)
            # This is currently missing in the Snapshot but important
            # for Scenario Service
            # For now, we assume Scenario Service has its own scenario DB,
            # but GM could provide 'available_sequences' if needed.

            snapshot.update(details)

            entities = []
            for npc in snapshot.get("npcs", []):
                entities.append(npc.get("scenario_entity_id"))
            for enemy in snapshot.get("enemies", []):
                entities.append(enemy.get("scenario_entity_id"))

            snapshot["entities"] = entities

            count = len(snapshot.get("npcs", [])) + len(snapshot.get("enemies", []))
            logger.info(f"   -> Fetched State Snapshot with {count} entities")
            return {
                "world_snapshot": snapshot,
                "act_id": snapshot.get("current_act_id") or state.get("act_id"),
                "sequence_id": snapshot.get("current_sequence_id")
                or state.get("sequence_id"),
                "sequence_type": snapshot.get("current_phase")
                or state.get("sequence_type"),
                "sequence_seq": snapshot.get("current_turn")
                or state.get("sequence_seq"),
            }
        except Exception as e:
            logger.error(f"Failed to fetch state: {e}")
            return {}

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
        active_entity = state.get("active_entity_id", "player")
        if active_entity.lower() == "narrator":
            from gm.core.models.rule import RuleOutcome

            logger.info("   -> Actor is Narrator. Skipping Rule Check.")
            # Return a default success outcome for narrator
            return {
                "rule_outcome": RuleOutcome(
                    session_id=state.get("session_id", "unknown"),
                    scenario_id=state.get("scenario_id", "1"),
                    success=True,
                    reason="나레이터의 서술입니다.",
                    suggested={"diffs": [], "relations": []},
                )
            }

        proposal = await self.rule_client.get_proposal(state)
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

        final_diffs = state.get("final_diffs", [])

        # 1. Commit entity diffs
        result = await self.state_client.commit(turn_id, final_diffs)

        # 2. Handle Location Transition (Act/Sequence Jump) from Scenario Service
        scenario = state.get("scenario_suggestion")
        if scenario:
            if scenario.next_act_id:
                logger.info(f"   -> Transitioning to ACT: {scenario.next_act_id}")
                await self.state_client.update_act(
                    state["session_id"], scenario.next_act_id
                )
            elif scenario.next_seq_id:
                logger.info(f"   -> Transitioning to SEQUENCE: {scenario.next_seq_id}")
                await self.state_client.update_sequence(
                    state["session_id"], scenario.next_seq_id
                )

        return {"commit_id": result["commit_id"]}

    @log_node_execution
    async def generate_narrative(self, state: TurnContext) -> TurnContext:
        """Generate narrative via LLM."""
        max_retries = 3
        scenario = state.get("scenario_suggestion")
        if not scenario:
            raise ValueError("Scenario suggestion missing")

        required_slot = scenario.narrative_slot

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

        narrative = ""
        for _ in range(max_retries):
            response_msg = await chain.ainvoke(
                {
                    "input_text": state["user_input"],
                    "outcome": rule_outcome.model_dump(),
                }
            )
            narrative = response_msg.content

            if required_slot and required_slot not in narrative:
                logger.warning(f"Narrative missing slot '{required_slot}'. Retrying...")
                continue
            break

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
