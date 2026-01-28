import functools
import json
import logging
from typing import Any, Callable, Dict, List, TypeVar, cast

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from gm.core.models.context import TurnContext
from gm.core.models.state import EntityDiff
from gm.infra.db.database import DatabaseHandler
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)
from gm.interfaces.llm import LLMPort

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def log_node_execution(func: F) -> F:
    """Decorator to log node execution."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        node_name = func.__name__
        logger.info(f"▶ START Node: [{node_name}]")
        try:
            # Handle instance method call (self, state)
            if len(args) > 0 and hasattr(
                args[0], "rule_client"
            ):  # Check if it's the instance
                result = await func(*args, **kwargs)
            else:
                result = await func(*args, **kwargs)

            logger.info(f"✔ END Node: [{node_name}]")
            if result:
                keys = list(result.keys())
                logger.info(f"   -> Updates: {keys}")
            return result
        except Exception as e:
            logger.error(f"ERROR in Node [{node_name}]: {e}")
            raise e

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
            "act_id": "act_1",
            "sequence_id": "seq_1",
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
            "act_id": "act_1",
            "sequence_id": "seq_1",
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
            snapshot = await self.state_client.get_state(state["session_id"])
            logger.info(
                (
                    "   -> Fetched State Snapshot with "
                    f"{len(snapshot.get('entities', []))} entities"
                )
            )
            return {"world_snapshot": snapshot}
        except Exception as e:
            logger.error(f"Failed to fetch state: {e}")
            return {}

    @log_node_execution
    async def select_active_entity(self, state: TurnContext) -> TurnContext:
        """Decide active entity for the turn."""
        if not state.get("is_npc_turn"):
            return {"active_entity_id": "player"}

        history = await self._fetch_history(state["session_id"], limit=5)
        snapshot = state.get("world_snapshot", {})

        if not snapshot or not snapshot.get("entities"):
            logger.warning("No entities in world_snapshot. Defaulting to 'npc'.")
            return {"active_entity_id": "npc"}

        entities = snapshot.get("entities", [])
        candidate_entities = [e for e in entities if str(e).lower() != "player"]

        if not candidate_entities:
            logger.warning("No NPC entities found. Defaulting to 'npc'.")
            return {"active_entity_id": "npc"}

        entity_list_str = ", ".join([str(e) for e in candidate_entities])

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "당신은 게임 마스터(GM)입니다. "
                        "지금까지의 이력과 현재 활성화된 엔티티 목록을 바탕으로, "
                        "다음에 누가 행동할지 결정하십시오. "
                        "반드시 해당 엔티티의 ID(entity_id)만 답변하십시오."
                    ),
                ),
                (
                    "user",
                    (
                        f"활성 엔티티 목록: {entity_list_str}\n\n"
                        f"최근 이력:\n{history}\n\n다음에 행동할 주체는 누구입니까?"
                    ),
                ),
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
            selected_entity = response_msg.content.strip()
            logger.info(f"   -> Selected Actor: {selected_entity}")
            return {"active_entity_id": selected_entity}
        except Exception as e:
            logger.error(f"Actor selection failed: {e}. Defaulting to first entity.")
            return {
                "active_entity_id": candidate_entities[0]
                if candidate_entities
                else "npc"
            }

    @log_node_execution
    async def generate_npc_input(self, state: TurnContext) -> TurnContext:
        """Generate NPC action via LLM."""
        if not state.get("is_npc_turn"):
            return {}

        history = await self._fetch_history(state["session_id"])
        actor = state.get("active_entity_id", "npc")

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        f"당신은 TRPG 세션에서 '{actor}' 역할을 맡고 있습니다. "
                        "상황에 몰입하여 자연스럽게 행동하십시오."
                    ),
                ),
                (
                    "user",
                    (
                        f"최근 이력:\n{history}\n\n"
                        f"당신('{actor}')의 다음 행동을 짧고 간결하게 서술하십시오."
                    ),
                ),
            ]
        )

        chain = prompt | self.llm

        try:
            response_msg = await chain.ainvoke({"actor": actor, "history": history})
            npc_action_text = response_msg.content
            logger.info(f"   -> Generated NPC Action for [{actor}]: {npc_action_text}")
        except Exception as e:
            logger.error(f"Failed to generate NPC action: {e}")
            npc_action_text = f"{actor} acts mysteriously."

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
        """Call Rule Manager."""
        proposal = await self.rule_client.get_proposal(state)
        return {"rule_outcome": proposal}

    @log_node_execution
    async def check_scenario(self, state: TurnContext) -> TurnContext:
        """Call Scenario Manager."""
        rule_outcome = state.get("rule_outcome")
        if not rule_outcome:
            logger.warning("Rule outcome is missing in check_scenario")
            raise ValueError("Rule outcome is required for scenario check")

        proposal = await self.scenario_client.get_proposal(
            state["user_input"], rule_outcome
        )
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

        result = await self.state_client.commit(turn_id, final_diffs)
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
            system_instruction = (
                "당신은 TRPG의 게임 마스터(GM) 겸 나레이터입니다. "
                "현재 상황, 분위기, 감각적인 디테일을 생생하고 풍부하게 서술하십시오. "
                "플레이어의 선택을 유도하거나 상황을 정리하여 몰입감을 높이십시오."
            )
        else:
            system_instruction = (
                "당신은 TRPG의 게임 마스터(GM)입니다. "
                "행동에 대한 판정 결과를 바탕으로 결과를 "
                "**간결하고 명확하게** 서술하십시오."
                "성공/실패 여부와 그로 인한 즉각적인 변화에 집중하여 짧게 요약하십시오."
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_instruction),
                ("user", "입력: {input_text}\n판정 결과: {outcome}"),
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
