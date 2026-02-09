import functools
import hashlib
import json
import logging
import os
import re
import uuid
from typing import Any, Callable, Dict, List, TypeVar, cast

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

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
    def _resolve_actor_type(
        snapshot: Dict[str, Any], active_entity_id: str | None
    ) -> ActorType:
        actor = (active_entity_id or "").strip()
        actor_l = actor.lower()
        if actor_l == "player":
            return ActorType.PLAYER
        if actor_l == "narrator":
            return ActorType.NARRATOR

        for npc in snapshot.get("npcs", []) or []:
            if not isinstance(npc, dict):
                continue
            candidate_ids = [
                npc.get("scenario_entity_id"),
                npc.get("entity_id"),
                npc.get("scenario_npc_id"),
                npc.get("npc_id"),
                npc.get("id"),
            ]
            candidate_ids_l = {str(v).lower() for v in candidate_ids if v}
            if actor_l and actor_l in candidate_ids_l:
                return ActorType.NPC

        for enemy in snapshot.get("enemies", []) or []:
            if not isinstance(enemy, dict):
                continue
            candidate_ids = [
                enemy.get("scenario_entity_id"),
                enemy.get("entity_id"),
                enemy.get("scenario_enemy_id"),
                enemy.get("enemy_id"),
                enemy.get("id"),
            ]
            candidate_ids_l = {str(v).lower() for v in candidate_ids if v}
            if actor_l and actor_l in candidate_ids_l:
                return ActorType.ENEMY

        return ActorType.UNKNOWN

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
    def _normalize_match_text(value: str) -> str:
        return re.sub(r"[^0-9a-z가-힣]+", "", str(value).lower())

    @staticmethod
    def _extract_first_quoted_dialogue(text: str) -> str | None:
        """
        Best-effort dialogue extraction for fallback paths.
        Extract first quoted string using common quote styles.
        """
        if not text:
            return None
        src = str(text)
        patterns = [
            r"\"([^\"]{1,200})\"",
            r"“([^”]{1,200})”",
            r"‘([^’]{1,200})’",
            r"「([^」]{1,200})」",
            r"『([^』]{1,200})』",
        ]
        for pat in patterns:
            m = re.search(pat, src)
            if m:
                cand = (m.group(1) or "").strip()
                if cand:
                    return cand
        return None

    @staticmethod
    def _extract_first_json_object(text: str) -> dict[str, Any] | None:
        """Best-effort JSON object extraction from an LLM response."""
        if not text:
            return None
        src = str(text).strip()
        start = src.find("{")
        end = src.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return None
        snippet = src[start : end + 1]
        try:
            data = json.loads(snippet)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _resolve_entity_label_from_snapshot(
        entity_id: str, snapshot: Dict[str, Any]
    ) -> str:
        """Resolve a stable label for an entity_id using a state-manager snapshot."""
        eid = str(entity_id or "").strip()
        if not eid:
            return "unknown"

        player_id = str(snapshot.get("player_id") or "").strip()
        if player_id and eid == player_id:
            return "player"

        for npc in snapshot.get("npcs", []) or []:
            if not isinstance(npc, dict):
                continue
            sid = str(npc.get("id") or npc.get("npc_id") or "").strip()
            if sid and sid == eid:
                return str(npc.get("name") or "npc")

        for enemy in snapshot.get("enemies", []) or []:
            if not isinstance(enemy, dict):
                continue
            sid = str(enemy.get("id") or enemy.get("enemy_id") or "").strip()
            if sid and sid == eid:
                return str(enemy.get("name") or "enemy")

        return eid

    @classmethod
    def _build_delta_brief(
        cls,
        final_diffs: list[EntityDiff] | None,
        snapshot_before: Dict[str, Any] | None,
        snapshot_after: Dict[str, Any] | None,
        active_entity_id: str | None,
        selected_target_entity_id: str | None,
    ) -> str:
        """
        Build a compact, LLM-safe delta summary.
        Narrative is required to use ONLY this delta (plus the explicit input/outcome).
        """
        before = snapshot_before or {}
        after = snapshot_after or {}
        diffs = final_diffs or []

        actor_label = cls._resolve_entity_label_from_snapshot(
            str(active_entity_id or ""), after or before
        )
        target_label = ""
        if selected_target_entity_id:
            target_label = cls._resolve_entity_label_from_snapshot(
                str(selected_target_entity_id), after or before
            )

        lines: list[str] = []
        lines.append(f"- actor: {actor_label} (id={active_entity_id})")
        if selected_target_entity_id:
            lines.append(f"- target: {target_label} (id={selected_target_entity_id})")

        if not diffs:
            lines.append("- diffs: (none)")
            return "\n".join(lines)

        lines.append("- diffs:")
        for d in diffs:
            try:
                eid = str(d.entity_id)
                label = cls._resolve_entity_label_from_snapshot(eid, after or before)
                diff_map = d.diff or {}
            except Exception:
                continue

            if not isinstance(diff_map, dict) or not diff_map:
                lines.append(f"  - {label}(id={eid}): (no fields)")
                continue

            # Keep it short and structured. Prefer numeric deltas.
            parts: list[str] = []
            for k, v in diff_map.items():
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    sign = "+" if float(v) >= 0 else ""
                    parts.append(f"{k} {sign}{v}")
                elif isinstance(v, str):
                    parts.append(f"{k}={v[:40]}")
                else:
                    parts.append(f"{k}=(updated)")
            if not parts:
                parts = ["(updated)"]
            lines.append(f"  - {label}(id={eid}): " + ", ".join(parts[:6]))

        return "\n".join(lines)

    @staticmethod
    def _is_uuid_like(value: str) -> bool:
        try:
            uuid.UUID(str(value))
            return True
        except Exception:
            return False

    @classmethod
    def _pick_deterministic(cls, seed: str, pool: list[str]) -> str:
        if not pool:
            return "narrator"
        seed_hex = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        idx = int(seed_hex[:8], 16) % len(pool)
        return pool[idx]

    @classmethod
    def _build_actor_pool(
        cls, snapshot: Dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        npcs_raw = snapshot.get("npcs", []) or []
        enemies_raw = snapshot.get("enemies", []) or []

        npcs: list[dict[str, Any]] = []
        for n in npcs_raw:
            if not isinstance(n, dict):
                continue
            scenario_id = (
                n.get("scenario_entity_id")
                or n.get("scenario_npc_id")
                or n.get("npc_id")
                or n.get("id")
            )
            state_id = n.get("id") or n.get("npc_id")
            name = n.get("name")
            # NPC can "depart" in some schemas
            if bool(n.get("is_departed")):
                continue
            if scenario_id:
                npcs.append(
                    {
                        "scenario_id": str(scenario_id),
                        "state_id": str(state_id) if state_id else None,
                        "name": str(name) if name else None,
                        "alive": True,
                    }
                )

        enemies: list[dict[str, Any]] = []
        for e in enemies_raw:
            if not isinstance(e, dict):
                continue
            scenario_id = (
                e.get("scenario_entity_id")
                or e.get("scenario_enemy_id")
                or e.get("enemy_id")
                or e.get("id")
            )
            state_id = e.get("id") or e.get("enemy_id")
            name = e.get("name")
            is_defeated = bool(e.get("is_defeated"))
            hp = e.get("current_hp")
            if hp is None:
                hp = ((e.get("state") or {}).get("numeric") or {}).get("HP")
            alive = not is_defeated
            if hp is not None:
                try:
                    alive = alive and int(hp) > 0
                except (TypeError, ValueError):
                    pass

            if scenario_id:
                enemies.append(
                    {
                        "scenario_id": str(scenario_id),
                        "state_id": str(state_id) if state_id else None,
                        "name": str(name) if name else None,
                        "alive": bool(alive),
                    }
                )

        return {"npcs": npcs, "enemies": enemies}

    @classmethod
    def _select_turn_target(cls, state: TurnContext) -> tuple[str, str, str]:
        """
        Decide target for the current turn.
        Returns: (target_entity_id, target_name, mode)
        mode: explicit | random | none
        """
        sequence_type = str(state.get("sequence_type") or "").upper()
        if "COMBAT" not in sequence_type:
            return "", "", "none"

        snapshot = state.get("world_snapshot", {}) or {}
        enemies = [e for e in (snapshot.get("enemies") or []) if isinstance(e, dict)]
        if not enemies:
            return "", "", "none"

        actor_id = str(state.get("active_entity_id") or "")
        user_input = str(state.get("user_input") or "").strip()
        text_lower = user_input.lower()
        text_norm = cls._normalize_match_text(user_input)

        candidates: list[dict[str, str]] = []
        alive_candidates: list[dict[str, str]] = []

        for enemy in enemies:
            state_id = str(enemy.get("id") or enemy.get("enemy_id") or "").strip()
            scenario_id = str(
                enemy.get("scenario_entity_id") or enemy.get("scenario_enemy_id") or ""
            ).strip()
            name = str(enemy.get("name") or "").strip()
            target_id = state_id or scenario_id
            if not target_id or (actor_id and actor_id == target_id):
                continue

            aliases = [x for x in [target_id, scenario_id, name] if x]
            rec = {"id": target_id, "name": name, "aliases": aliases}
            candidates.append(rec)

            is_defeated = bool(enemy.get("is_defeated"))
            hp = enemy.get("current_hp")
            if hp is None:
                hp = ((enemy.get("state") or {}).get("numeric") or {}).get("HP")
            is_alive = not is_defeated
            if hp is not None:
                try:
                    is_alive = is_alive and int(hp) > 0
                except (TypeError, ValueError):
                    pass
            if is_alive:
                alive_candidates.append(rec)

        if not candidates:
            return "", "", "none"

        best: dict[str, str] | None = None
        best_score = 0
        for rec in candidates:
            rec_score = 0
            for alias in rec["aliases"]:
                alias_l = alias.lower()
                alias_n = cls._normalize_match_text(alias)
                if not alias_n:
                    continue
                score = 0
                if text_lower == alias_l or text_norm == alias_n:
                    score = max(score, 120 + len(alias_n))
                if alias_l and alias_l in text_lower:
                    score = max(score, 90 + len(alias_l))
                if alias_n and alias_n in text_norm:
                    score = max(score, 80 + len(alias_n))
                rec_score = max(rec_score, score)
            if rec_score > best_score:
                best = rec
                best_score = rec_score

        if best and best_score > 0:
            return best["id"], best["name"], "explicit"

        pool = alive_candidates if alive_candidates else candidates
        seed_src = (
            f"{state.get('session_id', '')}|{state.get('turn_id', '')}|{user_input}"
        )
        seed_hex = hashlib.sha256(seed_src.encode("utf-8")).hexdigest()
        idx = int(seed_hex[:8], 16) % len(pool)
        picked = pool[idx]
        return picked["id"], picked["name"], "random"

    @staticmethod
    def _select_enemy_default_target(snapshot: Dict[str, Any]) -> tuple[str, str, str]:
        """
        For ENEMY actor in COMBAT: default target should be the player.
        Returns: (target_entity_id, target_name, mode)
        """
        player_id = str(snapshot.get("player_id") or "").strip()
        player_name = str(snapshot.get("player_name") or "player").strip()
        if player_id:
            return player_id, player_name, "explicit"

        # Fallback: if player_id is missing, hit any NPC in the same sequence.
        for npc in snapshot.get("npcs", []) or []:
            if not isinstance(npc, dict):
                continue
            npc_id = str(npc.get("id") or npc.get("npc_id") or "").strip()
            npc_name = str(npc.get("name") or "npc").strip()
            if npc_id:
                return npc_id, npc_name, "explicit"

        return "", "", "none"

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
        pre_act_id: str | None = None
        pre_status: str | None = None
        try:
            before = await self.state_client.get_state(user_input.session_id)
            pre_sequence_id = (
                str(before.get("current_sequence_id"))
                if before.get("current_sequence_id")
                else None
            )
            pre_act_id = (
                str(before.get("current_act_id"))
                if before.get("current_act_id")
                else None
            )
            pre_status = str(before.get("status")) if before.get("status") else None
        except Exception:
            pre_sequence_id = None
            pre_act_id = None
            pre_status = None

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

        player_action = str(user_input.content)
        player_response = {
            "turn_id": player_result_state["turn_id"],
            "commit_id": player_result_state["commit_id"],
            "active_entity_id": player_result_state.get("active_entity_id", "player"),
            "active_entity_name": "player",
            "is_npc_turn": False,
            "segments": [
                {
                    "type": SegmentType.ACTION,
                    "role": "player",
                    "content": player_action,
                },
                {
                    "type": SegmentType.NARRATION,
                    "role": "narrator",
                    "content": player_result_state["narrative"],
                },
            ],
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

        # 3. Process NPC Turn if entities exist.
        # 이전에는 시퀀스 전이가 발생하면 NPC 턴을 스킵했는데,
        # 그 결과 적/ NPC가 "아예 행동하지 않는" 심각한 상태가 발생했다.
        # 전이가 발생한 경우에도, 전이 이후 시퀀스의 엔티티가 존재한다면
        # 해당 시퀀스 기준으로 NPC/적 턴을 1회 실행한다.
        if entities and not should_end and not sequence_transitioned:
            logger.info(f"Active entities found: {entities}. Proceeding to NPC turn.")
            npc_response = await self.process_npc_turn(user_input.session_id)
            player_response["npc_turn"] = npc_response
        elif entities and not should_end and sequence_transitioned:
            logger.info(
                (
                    "Sequence transitioned (%s -> %s). "
                    "Running NPC turn on the transitioned sequence."
                ),
                pre_sequence_id,
                post_sequence_id,
            )
            npc_response = await self.process_npc_turn(user_input.session_id)
            player_response["npc_turn"] = npc_response
        elif entities and should_end:
            logger.info("Session already ended. Skipping NPC turn.")
            player_response["npc_turn"] = None
        else:
            logger.info("No active entities found. Skipping NPC turn.")
            player_response["npc_turn"] = None

        # Attach progression/termination indicators after the full composite turn.
        try:
            after = await self.state_client.get_state(user_input.session_id)
        except Exception:
            after = latest or {}

        post_act_id = str(after.get("current_act_id") or "") or None
        post_seq_id = str(after.get("current_sequence_id") or "") or None
        post_status = str(after.get("status") or "") or None
        is_ended = (post_status or "").lower() == "ended"

        changed = bool(
            (pre_act_id and post_act_id and pre_act_id != post_act_id)
            or (pre_sequence_id and post_seq_id and pre_sequence_id != post_seq_id)
        )
        player_response["current_act_id"] = post_act_id
        player_response["current_sequence_id"] = post_seq_id
        player_response["session_status"] = post_status
        player_response["is_session_ended"] = bool(is_ended)
        player_response["transition"] = {
            "from_act_id": pre_act_id,
            "from_sequence_id": pre_sequence_id,
            "to_act_id": post_act_id,
            "to_sequence_id": post_seq_id,
            "from_status": pre_status,
            "to_status": post_status,
            "changed": bool(changed),
        }

        return player_response

    async def process_npc_turn(self, session_id: str) -> Dict[str, Any]:
        # NPC 턴인 경우 user_input은 그래프 내부의 generate_npc_input 노드에서 생성됨
        pre_act_id: str | None = None
        pre_seq_id: str | None = None
        pre_status: str | None = None
        try:
            before = await self.state_client.get_state(session_id)
            pre_act_id = str(before.get("current_act_id") or "") or None
            pre_seq_id = str(before.get("current_sequence_id") or "") or None
            pre_status = str(before.get("status") or "") or None
        except Exception:
            pre_act_id = None
            pre_seq_id = None
            pre_status = None

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

        try:
            after = await self.state_client.get_state(session_id)
        except Exception:
            after = {}

        post_act_id = str(after.get("current_act_id") or "") or None
        post_seq_id = str(after.get("current_sequence_id") or "") or None
        post_status = str(after.get("status") or "") or None
        changed = bool(
            (pre_act_id and post_act_id and pre_act_id != post_act_id)
            or (pre_seq_id and post_seq_id and pre_seq_id != post_seq_id)
        )

        active_entity_id = final_state.get("active_entity_id")
        active_entity_name = self._resolve_active_entity_name(
            final_state.get("world_snapshot", {}) or {},
            active_entity_id,
        )
        dialogue = final_state.get("npc_dialogue")
        action = str(final_state.get("user_input") or "").strip() or None
        if str(active_entity_id or "").lower() == "narrator":
            action = None

        segments: list[dict[str, Any]] = []
        if action:
            segments.append(
                {
                    "type": SegmentType.ACTION,
                    "role": active_entity_name,
                    "content": str(action),
                }
            )
        if dialogue:
            segments.append(
                {
                    "type": SegmentType.DIALOGUE,
                    "role": active_entity_name,
                    "content": str(dialogue),
                }
            )
        segments.append(
            {
                "type": SegmentType.NARRATION,
                "role": "narrator",
                "content": str(final_state["narrative"]),
            }
        )

        return {
            "turn_id": final_state["turn_id"],
            "commit_id": final_state["commit_id"],
            "active_entity_id": active_entity_id,
            "active_entity_name": active_entity_name,
            "segments": segments,
            "is_npc_turn": True,
            # Post state context for clients that want to
            # render transitions even on npc-turn calls.
            "current_act_id": post_act_id,
            "current_sequence_id": post_seq_id,
            "session_status": post_status,
            "is_session_ended": bool((post_status or "").lower() == "ended"),
            "transition": {
                "from_act_id": pre_act_id,
                "from_sequence_id": pre_seq_id,
                "to_act_id": post_act_id,
                "to_sequence_id": post_seq_id,
                "from_status": pre_status,
                "to_status": post_status,
                "changed": bool(changed),
            },
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
        """
        Decide active entity for the turn.
        Critical behavior:
        - In COMBAT, an enemy should act if any are alive (no LLM selection).
        - Outside COMBAT, prefer NPCs if present.
        - Fall back to narrator only when no non-player entities exist.
        """
        if not state.get("is_npc_turn"):
            return {"active_entity_id": "player"}

        snapshot = state.get("world_snapshot", {}) or {}
        seq_type = str(state.get("sequence_type") or "EXPLORATION").upper()

        pools = self._build_actor_pool(snapshot)
        npcs = pools["npcs"]
        enemies = pools["enemies"]

        alive_enemy_ids = [e["scenario_id"] for e in enemies if e.get("alive")]
        any_enemy_ids = [e["scenario_id"] for e in enemies]
        npc_ids = [n["scenario_id"] for n in npcs]

        # Prefer enemies in combat to ensure combat actually progresses.
        if "COMBAT" in seq_type:
            pool = alive_enemy_ids or any_enemy_ids or npc_ids
        else:
            pool = npc_ids or alive_enemy_ids or any_enemy_ids

        if not pool:
            logger.info("   -> No non-player entities. Selecting narrator.")
            return {"active_entity_id": "narrator"}

        seed = (
            f"{state.get('session_id', '')}|"
            f"{snapshot.get('current_turn', '')}|"
            f"{snapshot.get('current_sequence_id', '')}|npc_turn"
        )
        picked = self._pick_deterministic(seed, [str(x).lower() for x in pool])
        logger.info("   -> Selected Actor (deterministic): %s", picked)
        return {"active_entity_id": picked}

    @log_node_execution
    async def generate_npc_input(self, state: TurnContext) -> TurnContext:
        """Generate NPC action or Narrator guidance via LLM."""
        if not state.get("is_npc_turn"):
            return {}

        history = await self._fetch_history(state["session_id"])
        actor_id = state.get("active_entity_id", "narrator")
        snapshot = state.get("world_snapshot", {}) or {}
        actor_name = self._resolve_active_entity_name(snapshot, actor_id)
        actor_type = self._resolve_actor_type(snapshot, actor_id)

        # Additional context for Narrator
        sequence_info = snapshot.get(
            "sequence", {}
        )  # This comes from get_sequence_details
        exit_triggers = sequence_info.get("exit_triggers", [])
        goal = sequence_info.get("goal", "상황에 몰입하기")

        if str(actor_id).lower() == "narrator":
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

        # Narrator는 기존처럼 단일 텍스트를 생성한다.
        if str(actor_id).lower() == "narrator":
            chain = prompt | self.llm
            try:
                response_msg = await chain.ainvoke(
                    {
                        "history": history,
                        "goal": goal,
                        "exit_triggers": exit_triggers,
                        "actor": actor_name,
                        "sequence_type": state.get("sequence_type", "EXPLORATION"),
                        "actor_type": actor_type.value,
                    }
                )
                npc_action_text = response_msg.content
                logger.info(
                    "   -> Generated Narrator Guidance action_len=%s",
                    len(npc_action_text),
                )
            except Exception as e:
                logger.error(f"Failed to generate actor input: {e}")
                npc_action_text = (
                    "주변에 정적이 흐릅니다. 당신의 다음 결정을 기다리는 듯합니다."
                )
            return {"user_input": npc_action_text, "npc_dialogue": None}

        # NPC/적은 JSON(action/dialogue)을 생성하게 하고, 우리가 직접 파싱한다.
        try:
            chain = prompt | self.llm
            response_msg = await chain.ainvoke(
                {
                    "history": history,
                    "goal": goal,
                    "exit_triggers": exit_triggers,
                    "actor": actor_name,
                    "sequence_type": state.get("sequence_type", "EXPLORATION"),
                    "actor_type": actor_type.value,
                }
            )
            raw = response_msg.content
            data = self._extract_first_json_object(raw)
            if not data:
                raise ValueError("Invalid JSON output")

            npc_action_text = str(data.get("action") or "").strip()
            npc_dialogue_raw = data.get("dialogue")
            npc_dialogue = (
                str(npc_dialogue_raw).strip()
                if npc_dialogue_raw is not None and str(npc_dialogue_raw).strip()
                else None
            )
            if not npc_action_text:
                raise ValueError("Empty npc action")
            if not npc_dialogue:
                npc_dialogue = "..."
            logger.info(
                (
                    "   -> Generated NPC structured input "
                    "actor=%s action_len=%s dialogue=%s"
                ),
                actor_id,
                len(npc_action_text),
                "yes" if npc_dialogue else "no",
            )
            return {"user_input": npc_action_text, "npc_dialogue": npc_dialogue}
        except Exception as e:
            # Fallback: if structured output fails, keep backward-compatible behavior.
            logger.warning(
                "Failed to generate json npc input (fallback to plain text). "
                "actor=%s error=%s",
                actor_id,
                type(e).__name__,
            )
            chain = prompt | self.llm
            try:
                response_msg = await chain.ainvoke(
                    {
                        "history": history,
                        "goal": goal,
                        "exit_triggers": exit_triggers,
                        "actor": actor_name,
                        "sequence_type": state.get("sequence_type", "EXPLORATION"),
                        "actor_type": actor_type.value,
                    }
                )
                npc_action_text = response_msg.content
                extracted = self._extract_first_quoted_dialogue(npc_action_text)
                npc_dialogue = extracted or "..."
                # Remove the extracted dialogue from action text if present.
                if extracted:
                    npc_action_text = re.sub(
                        r"\"%s\"" % re.escape(extracted),
                        "",
                        npc_action_text,
                    ).strip()
                if not npc_action_text:
                    npc_action_text = "상대의 움직임을 관찰하고 다음 행동을 준비한다."
                logger.info(
                    "   -> Generated NPC fallback action actor=%s len=%s",
                    actor_id,
                    len(npc_action_text),
                )
            except Exception as inner:
                logger.error(f"Failed to generate actor input: {inner}")
                npc_action_text = (
                    "주변에 정적이 흐릅니다. 당신의 다음 결정을 기다리는 듯합니다."
                )
                npc_dialogue = None
            return {"user_input": npc_action_text, "npc_dialogue": npc_dialogue}

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
        return {
            "turn_seq": seq,
            "turn_id": turn_id,
            "selected_target_entity_id": "",
            "selected_target_name": "",
            "target_selection_mode": "none",
        }

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

        snapshot = state.get("world_snapshot", {}) or {}
        seq_type = str(state.get("sequence_type") or "").upper()
        actor_type = self._resolve_actor_type(snapshot, active_entity)

        # Target selection must respect actor type:
        # - PLAYER/NPC usually target enemies
        # - ENEMY defaults to player (otherwise enemies "act" but never hit anything)
        if "COMBAT" in seq_type and actor_type == ActorType.ENEMY:
            selected_target_id, selected_target_name, target_mode = (
                self._select_enemy_default_target(snapshot)
            )
        else:
            selected_target_id, selected_target_name, target_mode = (
                self._select_turn_target(state)
            )
        if selected_target_id:
            if target_mode == "random":
                logger.info(
                    "   -> Target not specified. Randomly selected target: %s (%s)",
                    selected_target_id,
                    selected_target_name or "unknown",
                )
            else:
                logger.info(
                    "   -> Explicit target inferred: %s (%s)",
                    selected_target_id,
                    selected_target_name or "unknown",
                )

        try:
            proposal_context = dict(state)
            if selected_target_id:
                proposal_context["selected_target_entity_id"] = selected_target_id
            proposal = await self.rule_client.get_proposal(proposal_context)
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
        return {
            "rule_outcome": proposal,
            "selected_target_entity_id": selected_target_id,
            "selected_target_name": selected_target_name,
            "target_selection_mode": target_mode,
        }

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
                    if not latest_snapshot.get(
                        "current_sequence_id"
                    ) and latest_sequence.get("sequence_id"):
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
                    if not latest_snapshot.get(
                        "current_sequence_id"
                    ) and latest_sequence.get("sequence_id"):
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
        actor_type = self._resolve_actor_type(
            state.get("world_snapshot", {}) or {}, active_entity
        )
        actor_name = self._resolve_active_entity_name(
            state.get("world_snapshot", {}) or {}, active_entity
        )

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
        structured_llm = None

        class _SegmentOut(BaseModel):
            type: str = Field(..., description="narration|dialogue")
            role: str = Field(..., description="speaker label")
            content: str = Field(..., description="text content")

        class _NarrativeOut(BaseModel):
            segments: list[_SegmentOut] = Field(default_factory=list)

        try:
            structured_llm = self.llm.with_structured_output(_NarrativeOut)
        except Exception:
            structured_llm = None

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
                if not snapshot.get("current_sequence_id") and latest_sequence.get(
                    "sequence_id"
                ):
                    snapshot["current_sequence_id"] = latest_sequence.get("sequence_id")
                if not snapshot.get("sequence_name") and latest_sequence.get(
                    "sequence_name"
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
        selected_target_name = str(state.get("selected_target_name") or "").strip()
        target_selection_mode = str(
            state.get("target_selection_mode") or "none"
        ).lower()

        # Fetch history for context
        history = await self._fetch_history(state["session_id"], limit=5)
        narrative = ""
        delta_brief = self._build_delta_brief(
            final_diffs=state.get("final_diffs", []),
            snapshot_before=state.get("world_snapshot", {}) or {},
            snapshot_after=snapshot,
            active_entity_id=active_entity,
            selected_target_entity_id=state.get("selected_target_entity_id"),
        )

        forbidden_narrative_instruction = ""
        if has_live_enemies:
            forbidden_narrative_instruction = (
                "\n[금지 표현]\n"
                "현재 시퀀스에 생존 적이 남아 있다. "
                "아래와 같은 종료/완료 선언은 절대 쓰지 마라:\n"
                "- 모험은 끝이 났다.\n"
                "- 작전이 성공적으로 마무리되었다.\n"
                "- 모든 적이 쓰러졌다.\n"
                "- 봉인이 완전히 안정화되었다.\n"
                "- 마지막 남은 적/핵심 적을 처치했다는 단정.\n"
                "- 승리를 확신하거나 전투 종료를 기정사실화하는 표현.\n"
            )
        required_narrative_instruction = ""
        if target_selection_mode == "random" and selected_target_name:
            required_narrative_instruction = (
                "\n[타겟 선택 메모]\n"
                f"이번 턴은 입력에 명시 대상이 없어 시스템이 임의로 대상을 선택했다. "
                f"행동 결과가 {selected_target_name}에게 적용된 것으로 서술하라.\n"
            )
        if state.get("is_npc_turn") and actor_type in (ActorType.NPC, ActorType.ENEMY):
            required_narrative_instruction += (
                "\n[행동 주체 고정]\n"
                f"이번 턴의 행동 주체는 '{actor_name}'이다. "
                "2인칭(당신)을 절대 사용하지 말고, 주어는 반드시 행동 주체로 서술하라. "
                "첫 문장은 가능하면 '{actor_name}는/은'으로 시작하라.\n"
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
                    "required_narrative_instruction": required_narrative_instruction,
                    "forbidden_narrative_instruction": forbidden_narrative_instruction,
                    "history": history,
                    "active_entity_id": active_entity,
                    "delta_brief": delta_brief,
                    "world_snapshot": json.dumps(snapshot_view, ensure_ascii=False),
                }
                segments: list[_SegmentOut] = []
                if structured_llm is not None:
                    try:
                        messages = prompt.format_messages(**context)
                        out: _NarrativeOut = await structured_llm.ainvoke(messages)
                        segments = out.segments or []
                    except Exception:
                        segments = []

                if not segments:
                    response_msg = await chain.ainvoke(context)
                    raw = str(response_msg.content or "")
                    parsed = self._extract_first_json_object(raw)
                    if isinstance(parsed, dict) and isinstance(
                        parsed.get("segments"), list
                    ):
                        for seg in parsed["segments"]:
                            if not isinstance(seg, dict):
                                continue
                            segments.append(
                                _SegmentOut(
                                    type=str(seg.get("type") or ""),
                                    role=str(seg.get("role") or ""),
                                    content=str(seg.get("content") or ""),
                                )
                            )
                    if not segments:
                        segments = [
                            _SegmentOut(type="narration", role="narrator", content=raw)
                        ]
            except Exception as e:
                logger.exception("Error during narrative generation ainvoke")
                raise e

            dialogue_candidate = None
            narration_texts: list[str] = []
            for seg in segments:
                seg_type = str(seg.type or "").strip().lower()
                seg_role = str(seg.role or "").strip() or "narrator"
                seg_content = str(seg.content or "").strip()
                if not seg_content:
                    continue
                if seg_type == "dialogue" and dialogue_candidate is None:
                    dialogue_candidate = (seg_role, seg_content)
                elif seg_type == "narration":
                    narration_texts.append(seg_content)

            if not narration_texts:
                narration_texts = ["(행동 결과가 확정되지 않았다.)"]
            narrative = "\n".join(narration_texts).strip()

            # NPC/ENEMY 턴인데 2인칭이 섞이면 재시도한다.
            if (
                state.get("is_npc_turn")
                and actor_type in (ActorType.NPC, ActorType.ENEMY)
                and "당신" in str(narrative)
            ):
                logger.warning(
                    "NPC narrative used 2nd-person pronoun. Retrying... attempt=%s/%s",
                    attempt_idx + 1,
                    max_retries,
                )
                if attempt_idx < max_retries - 1:
                    continue
                # Last resort: simple rewrite to avoid '당신' as the subject.
                narrative = narrative.replace("당신은", f"{actor_name}은").replace(
                    "당신", actor_name
                )

            if has_live_enemies and self._contains_terminal_claim(narrative):
                logger.warning(
                    "Narrative declared terminal/completion while live enemies remain. "
                    "Retrying... attempt=%s/%s",
                    attempt_idx + 1,
                    max_retries,
                )
                if attempt_idx < max_retries - 1:
                    continue
                live_enemy_count = self._count_live_enemies_in_current_sequence(
                    snapshot
                )
                narrative = (
                    "교전이 계속되고 있다. "
                    "현재 시퀀스에는 아직 쓰러지지 않은 적이 "
                    f"{live_enemy_count}명 남아 있다. "
                    "전투는 아직 끝나지 않았고 적의 위협이 남아 있다."
                )
                break

            break

        updates: dict[str, Any] = {"narrative": narrative}
        if (
            state.get("is_npc_turn")
            and dialogue_candidate
            and not state.get("npc_dialogue")
        ):
            _role, _content = dialogue_candidate
            updates["npc_dialogue"] = _content.strip() or None

        # Do not let LLM decide termination phrasing from transition hints.
        # Append terminal line only from committed state.
        if (
            session_ended
            and not has_live_enemies
            and "모험은 끝이 났다." not in narrative
        ):
            narrative = f"{narrative.strip()}\n\n모험은 끝이 났다."

        updates["narrative"] = narrative
        return updates

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

            # Entities (NPC + enemy). We keep a structured list for guardrails:
            # summary must mention every present entity by name.
            entity_items: list[dict[str, str]] = []
            for npc in snapshot.get("npcs", []):
                name = (npc.get("name") or "Unknown").strip()
                desc = (npc.get("description") or "").strip()
                entity_items.append(
                    {
                        "kind": "npc",
                        "name": name,
                        "description": desc[:80],
                    }
                )
            for enemy in snapshot.get("enemies", []):
                name = (enemy.get("name") or "Unknown").strip()
                desc = (enemy.get("description") or "").strip()
                entity_items.append(
                    {
                        "kind": "enemy",
                        "name": name,
                        "description": desc[:80],
                    }
                )

            entity_str = (
                ", ".join(
                    [
                        f"{it['name']}({(it['description'] or '')[:30]})"
                        for it in entity_items
                    ]
                )
                if entity_items
                else "없음"
            )
            entities_list_text = (
                "\n".join(
                    [
                        (
                            f"- [{it['kind']}] "
                            f"{it['name']}: {it['description'] or '(설명 없음)'}"
                        )
                        for it in entity_items
                    ]
                )
                if entity_items
                else "- (없음)"
            )

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
                    "entities_list": entities_list_text,
                    "player_hp": snapshot.get("player", {}).get("hp", "?"),
                    "history": history_text,
                }
            )
            summary = (response_msg.content or "").strip()

            # Guardrail: ensure all present entity names are
            # explicitly mentioned in the summary.
            # If the LLM omits some, we append a deterministic
            # "등장 NPC/적" section so the
            # player always gets a complete cast snapshot.
            if entity_items and summary:
                summary_lc = summary.lower()
                missing = [
                    it
                    for it in entity_items
                    if it["name"] and it["name"].lower() not in summary_lc
                ]
                if missing:
                    lines = ["", "등장 NPC/적:"]
                    for it in missing:
                        desc = it["description"] or "(설명 없음)"
                        lines.append(f"- {it['name']}: {desc}")
                    summary = summary + "\n" + "\n".join(lines).strip()

            return summary or "상황 요약을 생성하지 못했습니다."
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
