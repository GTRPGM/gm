import functools
import logging
import os
from typing import Any, Callable, Dict, List, TypeVar, cast

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from gm.core.engine.combat_checker import CombatChecker
from gm.core.engine.entity_resolver import EntityResolver
from gm.core.engine.narrative import NarrativeGenerator
from gm.core.engine.state_handler import StateHandler
from gm.core.engine.summary import SummaryGenerator
from gm.core.engine.text_parser import TextParser
from gm.core.engine.utils import EngineUtils
from gm.core.models import TurnContext
from gm.exceptions import PipelineError
from gm.infra.db.database import DatabaseHandler
from gm.interfaces.external import (
    RuleManagerPort,
    ScenarioManagerPort,
    StateManagerPort,
)
from gm.interfaces.llm import LLMPort
from gm.schemas.api import ActorType, SegmentType
from gm.schemas.common import EntityDiff, RelationDiff
from gm.schemas.rule_engine import RuleOutcome, RuleSuggestion

logger = logging.getLogger("uvicorn.error")


def log_node_execution(func: Callable) -> Callable:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"❌ Node Error [{func.__name__}]: {e}")
            raise PipelineError(
                node_name=func.__name__, message=str(e), original_error=e
            ) from e

    return wrapper


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

        self.state_handler = StateHandler(state_client, db)
        self.narrative_gen = NarrativeGenerator(llm, state_client)
        self.summary_gen = SummaryGenerator(llm, state_client)
        self.graph: CompiledStateGraph = self._build_graph()

    async def process_player_turn(self, user_input: Any) -> Dict[str, Any]:
        """플레이어 턴 실행 메인 진입점"""
        session_id = user_input.session_id
        # 1. 그래프 실행 (Player Turn)
        res = await self.graph.ainvoke(
            {
                "session_id": session_id,
                "user_input": user_input.content,
                "is_npc_turn": False,
                "active_entity_id": "player",
            }
        )

        # 2. 결과 구성
        resp = {
            "turn_id": res["turn_id"],
            "commit_id": res["commit_id"],
            "active_entity_id": "player",
            "active_entity_name": "player",
            "narrative": str(res.get("narrative", "")),
            "output_type": "narration",
            "is_npc_turn": False,
            "segments": [
                {
                    "type": SegmentType.ACTION,
                    "role": "player",
                    "content": str(user_input.content),
                },
                {
                    "type": SegmentType.NARRATION,
                    "role": "narrator",
                    "content": str(res.get("narrative", "")),
                },
            ],
            "npc_turn": None,
            "npc_turns": [],
        }

        # 3. NPC 턴 실행 여부 판단 및 실행
        after = await self.state_client.get_state(session_id)
        if after.get("entities") and str(after.get("status", "")).lower() != "ended":
            pools = EngineUtils.build_actor_pool(after)
            queue = [e["scenario_id"] for e in pools["enemies"] if e["alive"]] + [
                n["scenario_id"] for n in pools["npcs"]
            ]
            npc_turns = []
            for aid in queue:
                npc_res = await self.process_npc_turn(session_id, aid)
                npc_turns.append(npc_res)
                if npc_res.get("is_session_ended"):
                    break
            resp["npc_turns"] = npc_turns
            if npc_turns:
                resp["npc_turn"] = npc_turns[0]

        # 4. 최종 상태 동기화
        latest = await self.state_client.get_state(session_id)
        resp.update(
            {
                "current_act_id": latest.get("current_act_id"),
                "current_sequence_id": latest.get("current_sequence_id"),
                "session_status": latest.get("status"),
                "is_session_ended": str(latest.get("status", "")).lower() == "ended",
            }
        )
        return resp

    async def process_npc_turn(
        self, session_id: str, force_id: str | None = None
    ) -> Dict[str, Any]:
        """NPC/적 턴 실행 진입점"""
        res = await self.graph.ainvoke(
            {
                "session_id": session_id,
                "user_input": "",
                "is_npc_turn": True,
                "force_active_entity_id": force_id,
            }
        )
        name = EntityResolver.resolve_name(
            res.get("world_snapshot", {}), res.get("active_entity_id")
        )

        segments = [
            {
                "type": SegmentType.NARRATION,
                "role": "narrator",
                "content": str(res.get("narrative", "")),
            }
        ]
        if action := str(res.get("user_input", "")).strip():
            segments.insert(
                0, {"type": SegmentType.ACTION, "role": name, "content": action}
            )
        if diag := res.get("npc_dialogue"):
            segments.insert(
                1, {"type": SegmentType.DIALOGUE, "role": name, "content": diag}
            )

        return {
            "turn_id": res["turn_id"],
            "commit_id": res["commit_id"],
            "active_entity_id": res.get("active_entity_id"),
            "active_entity_name": name,
            "segments": segments,
            "narrative": str(res.get("narrative", "")),
            "is_npc_turn": True,
            "output_type": "npc",
            "is_session_ended": str(res.get("world_snapshot", {}).get("status", ""))
            .lower()
            == "ended",
        }

    # --- LangGraph Nodes ---

    @log_node_execution
    async def fetch_state(self, state: TurnContext) -> TurnContext:
        snap = await self.state_handler.fetch_world_state(
            state["session_id"], "act-1", "seq-1"
        )
        return {
            "world_snapshot": snap,
            "scenario_id": snap.get("scenario_id"),
            "act_id": snap.get("current_act_id"),
            "sequence_id": snap.get("current_sequence_id"),
            "sequence_type": self._resolve_seq_type(snap),
            "sequence_seq": snap.get("current_turn"),
        }

    @log_node_execution
    async def select_active_entity(self, state: TurnContext) -> TurnContext:
        if not state.get("is_npc_turn"):
            return {"active_entity_id": "player"}
        if fid := state.get("force_active_entity_id"):
            return {"active_entity_id": fid}

        # NPC 턴 주체 선정 (LLM 호출을 통한 지능적 선택)
        res = await (
            ChatPromptTemplate.from_template(
                "Select next active actor ID from available entities."
            )
            | self.llm
        ).ainvoke({})
        return {"active_entity_id": str(res.content).strip()}

    @log_node_execution
    async def generate_npc_input(self, state: TurnContext) -> TurnContext:
        if not state.get("is_npc_turn"):
            return {}
        actor_id, snap = (
            state.get("active_entity_id", "narrator"),
            state.get("world_snapshot", {}) or {},
        )

        sys_p = self._load_prompt(
            f"generate_npc_input/{'narrator' if actor_id.lower() == 'narrator' else 'npc'}_system.txt"
        )
        usr_p = self._load_prompt(
            f"generate_npc_input/{'narrator' if actor_id.lower() == 'narrator' else 'npc'}_user.txt"
        )

        res = await (
            ChatPromptTemplate.from_messages([("system", sys_p), ("user", usr_p)])
            | self.llm
        ).ainvoke(
            {
                "history": await self._fetch_history(state["session_id"]),
                "actor": EntityResolver.resolve_name(snap, actor_id),
                "actor_type": EntityResolver.resolve_type(snap, actor_id).value,
                "goal": snap.get("goal", "상황 몰입"),
                "sequence_type": state.get("sequence_type", "EXPLORATION"),
                "exit_triggers": (snap.get("sequence") or {}).get("exit_triggers", []),
            }
        )

        if actor_id.lower() == "narrator":
            return {"user_input": res.content, "npc_dialogue": None}

        data = TextParser.parse_json(res.content) or {
            "action": res.content,
            "dialogue": "...",
        }
        return {"user_input": data.get("action"), "npc_dialogue": data.get("dialogue")}

    @log_node_execution
    async def init_turn(self, state: TurnContext) -> TurnContext:
        seq = (
            await self.db.fetchval(
                self.db.get_query("get_next_turn_seq"), state["session_id"]
            )
            or 0
        ) + 1
        return {"turn_seq": seq, "turn_id": f"{state['session_id']}:{seq}"}

    @log_node_execution
    async def check_rule(self, state: TurnContext) -> TurnContext:
        if str(state.get("active_entity_id")).lower() == "narrator":
            return {
                "rule_outcome": RuleOutcome(
                    session_id=state["session_id"],
                    scenario_id=str(state.get("scenario_id") or ""),
                    success=True,
                    reason="나레이션",
                    suggested=RuleSuggestion(diffs=[], relations=[]),
                )
            }

        tid, tname, mode = EngineUtils.select_turn_target(state)
        try:
            proposal = await self.rule_client.get_proposal(
                {**state, "selected_target_entity_id": tid}
            )
        except Exception as e:
            logger.warning(f"Rule Engine failure (fallback applied): {e}")
            proposal = RuleOutcome(
                session_id=state["session_id"],
                scenario_id=str(state.get("scenario_id") or ""),
                success=True,
                reason="룰 엔진 일시 오류로 기본 판정을 적용합니다.",
                suggested=RuleSuggestion(diffs=[], relations=[]),
            )

        return {
            "rule_outcome": proposal,
            "selected_target_entity_id": tid,
            "selected_target_name": tname,
            "target_selection_mode": mode,
        }

    @log_node_execution
    async def check_scenario(self, state: TurnContext) -> TurnContext:
        return {"scenario_suggestion": await self.scenario_client.get_proposal(state)}

    @log_node_execution
    async def resolve_conflicts(self, state: TurnContext) -> TurnContext:
        rule, scenario = state["rule_outcome"], state["scenario_suggestion"]

        # 1. Diffs 병합 (RuleOutcome.suggested_diffs 프로퍼티는 List[Dict]를 반환함)
        diff_map = {str(d["entity_id"]): d["diff"].copy() for d in rule.suggested_diffs}

        for s_diff in scenario.correction_diffs or []:
            eid = str(s_diff.get("entity_id", ""))
            if not eid:
                continue

            val = s_diff.get("diff", {})
            if eid in diff_map:
                diff_map[eid].update(val)
            else:
                diff_map[eid] = val.copy()

        # 2. Relations 매핑
        final_rels = [
            RelationDiff(
                cause_entity_id=str(r.cause_entity_id),
                effect_entity_id=str(r.effect_entity_id),
                type=str(r.type),
                affinity_score=r.affinity_score,
                quantity=r.quantity,
            )
            for r in rule.suggested.relations
        ]

        return {
            "final_diffs": [
                EntityDiff(entity_id=eid, diff=d) for eid, d in diff_map.items()
            ],
            "final_relations": final_rels,
        }

    @log_node_execution
    async def commit_state(self, state: TurnContext) -> TurnContext:
        return {
            "commit_id": await self.state_handler.commit_changes(
                state["session_id"],
                state["turn_id"],
                state.get("final_diffs", []),
                state.get("final_relations", []),
                state.get("scenario_suggestion"),
            )
        }

    @log_node_execution
    async def generate_narrative(self, state: TurnContext) -> TurnContext:
        return await self.narrative_gen.generate(
            state, self._load_prompt, self._fetch_history
        )

    @log_node_execution
    async def save_log(self, state: TurnContext) -> TurnContext:
        await self.state_handler.save_play_log(state)
        return {}

    def _resolve_seq_type(self, snap: Dict) -> str:
        m = snap.get("metadata", {})
        h = str(
            m.get("sequence_type")
            or m.get("phase_type")
            or m.get("type")
            or snap.get("current_phase")
            or ""
        ).upper()
        return (
            "COMBAT"
            if any(k in h for k in ["COMBAT", "BATTLE", "BOSS"])
            else ("DIALOGUE" if "DIALOG" in h else "EXPLORATION")
        )

    def _load_prompt(self, p: str) -> str:
        import os

        with open(
            os.path.join(os.path.dirname(__file__), "prompts", p), "r", encoding="utf-8"
        ) as f:
            return f.read().strip()

    async def _fetch_history(self, sid: str, limit: int = 5) -> List:
        return [
            {"player": r["user_input"], "narrative": r["final_output"]}
            for r in reversed(
                await self.db.fetch(self.db.get_query("fetch_history_limit"), sid, limit)
            )
        ]

    async def generate_summary(self, sid: str) -> str:
        return await self.summary_gen.generate(
            sid, self._load_prompt, self._fetch_history
        )

    def _build_graph(self) -> CompiledStateGraph:
        wf = StateGraph(TurnContext)
        ns = [
            "fetch_state",
            "select_active_entity",
            "generate_npc_input",
            "init_turn",
            "check_rule",
            "check_scenario",
            "resolve_conflicts",
            "commit_state",
            "generate_narrative",
            "save_log",
        ]
        for n in ns:
            wf.add_node(n, getattr(self, n))
        wf.set_entry_point(ns[0])
        for i in range(len(ns) - 1):
            wf.add_edge(ns[i], ns[i + 1])
        wf.add_edge(ns[-1], END)
        return wf.compile()
