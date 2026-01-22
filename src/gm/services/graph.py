import functools
import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph

from gm.db.database import db
from gm.schemas.context import TurnContext
from gm.schemas.state import EntityDiff
from gm.services.external import (
    RuleManagerClient,
    ScenarioManagerClient,
    StateManagerClient,
)
from gm.services.llm_adapter import NarrativeChatModel

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def log_node_execution(func):
    """그래프 노드 실행 전후를 로깅하는 데코레이터"""

    @functools.wraps(func)
    async def wrapper(state: TurnContext, *args, **kwargs):
        node_name = func.__name__
        logger.info(f"▶ START Node: [{node_name}]")

        try:
            result = await func(state, *args, **kwargs)

            logger.info(f"✔ END Node: [{node_name}]")
            if result:
                # 결과(변경된 상태)의 키만 출력하거나 내용을 요약 출력
                keys = list(result.keys())
                logger.info(f"   -> Updates: {keys}")

            return result
        except Exception as e:
            logger.error(f"ERROR in Node [{node_name}]: {e}")
            raise e

    return wrapper


# --- Clients ---
# 그래프 노드에서 사용할 클라이언트 인스턴스
rule_client = RuleManagerClient()
scenario_client = ScenarioManagerClient()
state_client = StateManagerClient()
narrative_model = NarrativeChatModel()


# --- Node Functions ---


async def _fetch_history(session_id: str, limit: int = 5) -> list:
    """Helper to fetch recent history."""
    query = """
        SELECT user_input, final_output
        FROM play_logs
        WHERE session_id = $1
        ORDER BY turn_seq DESC
        LIMIT $2
    """
    history = []
    try:
        rows = await db.fetch(query, session_id, limit)
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
async def select_active_entity(state: TurnContext) -> TurnContext:
    """
    현재 턴의 행동 주체(Active Entity)를 결정합니다.
    NPC 턴인 경우 World Snapshot과 History를 기반으로 LLM이 선택합니다.
    """
    # 1. Player Turn -> Always 'player'
    if not state.get("is_npc_turn"):
        return {"active_entity_id": "player"}

    # 2. Prepare Context for Selection
    history = await _fetch_history(state["session_id"], limit=5)
    snapshot = state.get("world_snapshot", {})
    logger.info(f"DEBUG: Snapshot in select_active_entity: {snapshot}")

    # If no snapshot info, default to generic NPC
    if not snapshot or not snapshot.get("entities"):
        logger.warning("No entities in world_snapshot. Defaulting to 'npc'.")
        return {"active_entity_id": "npc"}

    # 3. Prompt LLM to select actor
    entities = snapshot.get("entities", [])
    candidate_entities = [e for e in entities if str(e).lower() != "player"]

    if not candidate_entities:
        logger.warning("No NPC entities found in snapshot. Defaulting to 'npc'.")
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

    chain = prompt | narrative_model

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
            "active_entity_id": candidate_entities[0] if candidate_entities else "npc"
        }


@log_node_execution
async def generate_npc_input(state: TurnContext) -> TurnContext:
    """NPC 턴인 경우 DB에서 최근 이력을 조회하여 LLM을 통해 NPC의 행동을 생성합니다."""
    if not state.get("is_npc_turn"):
        return {}

    # 1. History (Reuse helper)
    history = await _fetch_history(state["session_id"])
    actor = state.get("active_entity_id", "npc")

    # 2. Prompt Construction for NPC Action
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

    chain = prompt | narrative_model

    # 3. Generate Action
    try:
        response_msg = await chain.ainvoke({"actor": actor, "history": history})
        npc_action_text = response_msg.content
        logger.info(f"   -> Generated NPC Action for [{actor}]: {npc_action_text}")
    except Exception as e:
        logger.error(f"Failed to generate NPC action: {e}")
        npc_action_text = f"{actor} acts mysteriously."

    return {"user_input": npc_action_text}


@log_node_execution
async def init_turn(state: TurnContext) -> TurnContext:
    """세션의 다음 Turn Seq를 조회하고 Turn ID를 생성합니다."""
    query = "SELECT COALESCE(MAX(turn_seq), 0) + 1 FROM play_logs WHERE session_id = $1"
    try:
        val = await db.fetchval(query, state["session_id"])
        seq = val if val else 1
    except Exception:
        seq = 1

    turn_id = f"{state['session_id']}:{seq}"
    logger.info(f"   -> New Turn ID: {turn_id}")
    return {"turn_seq": seq, "turn_id": turn_id}


@log_node_execution
async def check_rule(state: TurnContext) -> TurnContext:
    """Rule Manager에 판정을 요청합니다."""
    proposal = await rule_client.get_proposal(state["user_input"])
    return {"rule_outcome": proposal}


@log_node_execution
async def check_scenario(state: TurnContext) -> TurnContext:
    """Scenario Manager에 제안을 요청합니다."""
    # check_rule 노드가 선행되므로 rule_outcome은 반드시 존재한다고 가정
    proposal = await scenario_client.get_proposal(
        state["user_input"], state["rule_outcome"]
    )
    return {"scenario_suggestion": proposal}


@log_node_execution
async def resolve_conflicts(state: TurnContext) -> TurnContext:
    """Rule과 Scenario의 제안을 취합하여 최종 상태 변경(Diff)을 확정합니다."""
    rule = state["rule_outcome"]
    scenario = state["scenario_suggestion"]

    resolved_diffs_map = {}

    # 1. Rule 제안 적용
    for d in rule.suggested_diffs:
        eid = d["entity_id"]
        resolved_diffs_map[eid] = d["diff"].copy()

    # 2. Scenario 제안 적용 (Rule 봉투 준수)
    for s_diff in scenario.correction_diffs:
        eid = s_diff["entity_id"]
        s_data = s_diff["diff"]

        if eid not in resolved_diffs_map:
            resolved_diffs_map[eid] = s_data.copy()
            continue

        if rule.value_range:
            for field, s_val in s_data.items():
                if field in rule.value_range:
                    # TODO: 실제 범위 체크 로직 필요, 현재는 덮어쓰기
                    resolved_diffs_map[eid][field] = s_val
                else:
                    resolved_diffs_map[eid][field] = s_val
        else:
            resolved_diffs_map[eid].update(s_data)

    final_diffs = [
        EntityDiff(entity_id=eid, diff=diff) for eid, diff in resolved_diffs_map.items()
    ]

    return {"final_diffs": final_diffs}


@log_node_execution
async def commit_state(state: TurnContext) -> TurnContext:
    """State Manager에 변경사항을 커밋합니다."""
    result = await state_client.commit(state["turn_id"], state["final_diffs"])
    return {"commit_id": result["commit_id"]}


@log_node_execution
async def generate_narrative(state: TurnContext) -> TurnContext:
    """LLM Gateway를 통해 서술을 생성합니다."""
    max_retries = 3
    required_slot = state["scenario_suggestion"].narrative_slot

    active_entity = state.get("active_entity_id", "player")
    is_narrator = active_entity.lower() == "narrator"

    # 프롬프트 분기
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

    chain = prompt | narrative_model

    narrative = ""
    for _ in range(max_retries):
        response_msg = await chain.ainvoke(
            {
                "input_text": state["user_input"],
                "outcome": state["rule_outcome"].model_dump(),
            }
        )
        narrative = response_msg.content

        if required_slot and required_slot not in narrative:
            logger.warning(f"Narrative missing slot '{required_slot}'. Retrying...")
            continue
        break

    return {"narrative": narrative}


@log_node_execution
async def save_log(state: TurnContext) -> TurnContext:
    """Play Log를 DB에 저장합니다."""
    query = """
        INSERT INTO play_logs (
            turn_id,
            session_id,
            turn_seq,
            user_input,
            final_output,
            state_diff,
            commit_id,
            act_id,
            sequence_id,
            sequence_type,
            sequence_seq,
            active_entity_id,
            world_snapshot
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    """
    diffs_json = json.dumps([d.model_dump() for d in state["final_diffs"]])
    snapshot_json = json.dumps(state.get("world_snapshot", {}))

    try:
        await db.execute(
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
        # 로그 저장이 실패해도 흐름을 끊지 않음 (선택사항)

    return {}


# --- Graph Construction ---


def build_graph():
    workflow = StateGraph(TurnContext)

    # Add Nodes
    workflow.add_node("select_active_entity", select_active_entity)
    workflow.add_node("generate_npc_input", generate_npc_input)
    workflow.add_node("init_turn", init_turn)
    workflow.add_node("check_rule", check_rule)
    workflow.add_node("check_scenario", check_scenario)
    workflow.add_node("resolve_conflicts", resolve_conflicts)
    workflow.add_node("commit_state", commit_state)
    workflow.add_node("generate_narrative", generate_narrative)
    workflow.add_node("save_log", save_log)

    # Set Entry Point -> Now Select Active Entity first
    workflow.set_entry_point("select_active_entity")

    # Add Edges
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


turn_pipeline = build_graph()
