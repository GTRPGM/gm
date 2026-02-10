from typing import Any, Dict, Optional
from gm.schemas.api import ActorType

class EntityResolver:
    @staticmethod
    def resolve_name(snapshot: Dict[str, Any], entity_id: str | None) -> str:
        actor = (entity_id or "").strip()
        actor_l = actor.lower()
        if actor_l == "player": return "player"
        if actor_l == "narrator": return "narrator"

        for key in ("npcs", "enemies"):
            for entity in snapshot.get(key, []) or []:
                name = entity.get("name")
                cands = [entity.get("scenario_entity_id"), entity.get("entity_id"), entity.get("scenario_npc_id"), entity.get("scenario_enemy_id")]
                if actor_l in [str(v).lower() for v in cands if v]: return name or actor
                if name and str(name).lower() == actor_l: return name
        return actor or "unknown"

    @staticmethod
    def resolve_type(snapshot: Dict[str, Any], entity_id: str | None) -> ActorType:
        actor = (entity_id or "").strip().lower()
        if actor == "player": return ActorType.PLAYER
        if actor == "narrator": return ActorType.NARRATOR

        for npc in snapshot.get("npcs", []) or []:
            cands = {str(v).lower() for v in [npc.get("scenario_entity_id"), npc.get("entity_id"), npc.get("scenario_npc_id"), npc.get("npc_id"), npc.get("id")] if v}
            if actor in cands: return ActorType.NPC

        for enemy in snapshot.get("enemies", []) or []:
            cands = {str(v).lower() for v in [enemy.get("scenario_entity_id"), enemy.get("entity_id"), enemy.get("scenario_enemy_id"), enemy.get("enemy_id"), enemy.get("id")] if v}
            if actor in cands: return ActorType.ENEMY
        return ActorType.UNKNOWN

    @staticmethod
    def resolve_label(entity_id: str, snapshot: Dict[str, Any]) -> str:
        eid = str(entity_id or "").strip()
        if not eid: return "unknown"
        if eid == str(snapshot.get("player_id") or "").strip(): return "player"
        
        for npc in snapshot.get("npcs", []) or []:
            if str(npc.get("id") or npc.get("npc_id") or "").strip() == eid:
                return str(npc.get("name") or "npc")
        for enemy in snapshot.get("enemies", []) or []:
            if str(enemy.get("id") or enemy.get("enemy_id") or "").strip() == eid:
                return str(enemy.get("name") or "enemy")
        return eid
