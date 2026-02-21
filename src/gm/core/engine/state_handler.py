import json
import logging
from typing import Any, Dict, List, Optional
from gm.interfaces.external import StateManagerPort
from gm.infra.db.database import DatabaseHandler
from gm.schemas.common import EntityDiff, RelationDiff
from gm.core.engine.combat_checker import CombatChecker
from gm.core.engine.utils import EngineUtils

logger = logging.getLogger("uvicorn.error")

class StateHandler:
    def __init__(self, state_client: StateManagerPort, db: DatabaseHandler):
        self.state_client, self.db = state_client, db

    async def fetch_world_state(self, sid: str, aid: str, sqid: str) -> Dict:
        try:
            snap = await self.state_client.get_state(sid)
            details = await self.state_client.get_sequence_details(sid)
            snap.update(details or {})
            try: snap["act"] = await self.state_client.get_act_details(sid)
            except Exception: snap["act"] = {}
            entities = []
            for k in ["npcs", "enemies"]:
                for e in snap.get(k, []) or []: entities.append(e.get("scenario_entity_id") or e.get("npc_id") or e.get("enemy_id"))
            snap["entities"] = entities
            return snap
        except Exception as e:
            logger.error(f"Failed fetch: {e}"); return {}

    async def commit_changes(self, sid: str, tid: str, diffs: List, rels: List, scenario: Any) -> str:
        filtered_rels = rels or []
        if filtered_rels:
            snap = await self.fetch_world_state(sid, "", "")
            allowed_ids: set[str] = set()
            player_id = str((snap.get("player") or {}).get("player_id") or "").strip()
            if player_id:
                allowed_ids.add(player_id)
            allowed_ids.add("player")
            for key in ("npcs", "enemies"):
                for entity in (snap.get(key) or []):
                    for attr in ("scenario_entity_id", "npc_id", "enemy_id", "id"):
                        value = str(entity.get(attr) or "").strip()
                        if value:
                            allowed_ids.add(value)

            valid_rels: list = []
            for rel in filtered_rels:
                cause_id = str(getattr(rel, "cause_entity_id", "") or "").strip()
                effect_id = str(getattr(rel, "effect_entity_id", "") or "").strip()
                if cause_id in allowed_ids and effect_id in allowed_ids:
                    valid_rels.append(rel)
                else:
                    logger.warning(
                        "Drop invalid relation diff: %s -> %s (allowed=%s)",
                        cause_id,
                        effect_id,
                        len(allowed_ids),
                    )
            filtered_rels = valid_rels

        res = await self.state_client.commit(tid, diffs, filtered_rels)
        trans = False
        if scenario:
            if hasattr(scenario, "next_act_id") and scenario.next_act_id:
                if not scenario.next_seq_id: raise ValueError("next_seq_id is required when next_act_id is set")
                await self.state_client.update_act(sid, scenario.next_act_id, scenario.next_seq_id); trans = True
            elif hasattr(scenario, "next_seq_id") and scenario.next_seq_id:
                await self.state_client.update_sequence(sid, scenario.next_seq_id); trans = True
            
            # 종료 조건 검사 (테스트 호환성 보강)
            if hasattr(scenario, "should_end") and scenario.should_end and not trans:
                s_snap = await self.state_client.get_state(sid)
                s_snap.update(await self.state_client.get_sequence_details(sid) or {})
                if CombatChecker.has_live_enemies(s_snap):
                    scenario.should_end = False  # 테스트용: 객체 상태 직접 변경
                else:
                    await self.state_client.end_session(sid)
            elif hasattr(scenario, "should_end") and not scenario.should_end and not trans:
                try:
                    s_snap = await self.state_client.get_state(sid)
                    s_snap.update(await self.state_client.get_sequence_details(sid) or {})
                    act = await self.state_client.get_act_details(sid)
                    if CombatChecker.is_last_sequence(str(s_snap.get("current_sequence_id")), act) and not CombatChecker.has_live_enemies(s_snap):
                        if (s_snap.get("enemies", []) or []): # 적이 아예 없던 시퀀스가 아닌, 처리된 경우만
                            scenario.should_end = True
                            await self.state_client.end_session(sid)
                except Exception: pass
        return res["commit_id"]

    async def save_play_log(self, data: Dict):
        q = self.db.get_query("insert_play_log")
        try:
            meta_info = dict((data.get("meta_info") or {}))
            delta_sentences = EngineUtils.describe_natural_diffs(
                data.get("final_diffs", []),
                data.get("snapshot_before", {}),
                data.get("snapshot_after", {}),
            )
            if delta_sentences:
                meta_info["delta_sentences"] = delta_sentences
            await self.db.execute(
                q,
                data["turn_id"],
                data["session_id"],
                data["turn_seq"],
                data["user_input"],
                data["narrative"],
                json.dumps([d.model_dump() for d in data.get("final_diffs", [])]),
                data["commit_id"],
                data.get("act_id"),
                data.get("sequence_id"),
                data.get("sequence_type"),
                data.get("sequence_seq"),
                data.get("active_entity_id", "player"),
                json.dumps(data.get("world_snapshot", {})),
                json.dumps(meta_info) if meta_info else None,
            )
        except Exception as e: logger.error(f"Log fail: {e}")
