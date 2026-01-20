import functools
import json
import logging

from langgraph.graph import END, StateGraph

from gm.db.database import db
from gm.schemas.context import TurnContext
from gm.schemas.state import EntityDiff
from gm.services.external import (
    LLMGatewayClient,
    RuleManagerClient,
    ScenarioManagerClient,
    StateManagerClient,
)

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
llm_client = LLMGatewayClient()


# --- Node Functions ---


@log_node_execution
async def generate_npc_input(state: TurnContext) -> TurnContext:
    """NPC 턴인 경우 LLM을 통해 NPC의 행동을 생성합니다."""
    if not state.get("is_npc_turn"):
        return {}

    # 컨텍스트 수집 (현재는 Mock)
    context = {"summary": "이전 턴 상황 요약..."}

    # NPC 행동 생성
    npc_action_text = await llm_client.generate_npc_action(state["session_id"], context)
    logger.info(f"   -> Generated NPC Action: {npc_action_text}")

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

    narrative = ""
    for _ in range(max_retries):
        narrative = await llm_client.generate_narrative(
            state["turn_id"],
            state["commit_id"],
            state["user_input"],
            state["rule_outcome"],
        )

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
            commit_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """
    diffs_json = json.dumps([d.model_dump() for d in state["final_diffs"]])

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
        )
    except Exception as e:
        logger.error(f"Failed to save log: {e}")
        # 로그 저장이 실패해도 흐름을 끊지 않음 (선택사항)

    return {}


# --- Graph Construction ---


def build_graph():
    workflow = StateGraph(TurnContext)

    # Add Nodes
    workflow.add_node("generate_npc_input", generate_npc_input)
    workflow.add_node("init_turn", init_turn)
    workflow.add_node("check_rule", check_rule)
    workflow.add_node("check_scenario", check_scenario)
    workflow.add_node("resolve_conflicts", resolve_conflicts)
    workflow.add_node("commit_state", commit_state)
    workflow.add_node("generate_narrative", generate_narrative)
    workflow.add_node("save_log", save_log)

    # Set Entry Point
    workflow.set_entry_point("generate_npc_input")

    # Add Edges
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
