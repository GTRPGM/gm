import hashlib
import re
from typing import Any, Dict, List
from gm.schemas.common import EntityDiff
from gm.core.engine.entity_resolver import EntityResolver

class EngineUtils:
    @staticmethod
    def build_actor_pool(snapshot: Dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        npcs = []
        for n in (snapshot.get("npcs", []) or []):
            if bool(n.get("is_departed")): continue
            sid = n.get("scenario_entity_id") or n.get("npc_id") or n.get("id")
            if sid: npcs.append({"scenario_id": str(sid), "name": n.get("name"), "alive": True})
        
        enemies = []
        for e in (snapshot.get("enemies", []) or []):
            sid = e.get("scenario_entity_id") or e.get("enemy_id") or e.get("id")
            is_defeated = bool(e.get("is_defeated"))
            hp = e.get("current_hp") or ((e.get("state") or {}).get("numeric") or {}).get("HP")
            alive = not is_defeated and (hp is None or int(hp) > 0)
            if sid: enemies.append({"scenario_id": str(sid), "name": e.get("name"), "alive": bool(alive)})
        return {"npcs": npcs, "enemies": enemies}

    @classmethod
    def select_turn_target(cls, state: Dict[str, Any]) -> tuple[str, str, str]:
        if "COMBAT" not in str(state.get("sequence_type", "")).upper(): return "", "", "none"
        snapshot = state.get("world_snapshot", {}) or {}
        enemies = [e for e in (snapshot.get("enemies") or []) if isinstance(e, dict)]
        if not enemies: return "", "", "none"
        
        user_input = str(state.get("user_input") or "").strip()
        text_norm = re.sub(r"[^0-9a-z가-힣]+", "", user_input.lower())
        
        candidates, alive_candidates = [], []
        for enemy in enemies:
            tid = str(enemy.get("id") or enemy.get("enemy_id") or "").strip()
            name = str(enemy.get("name") or "").strip()
            if not tid: continue
            rec = {"id": tid, "name": name, "aliases": [tid, name]}
            candidates.append(rec)
            
            hp = enemy.get("current_hp") or ((enemy.get("state") or {}).get("numeric") or {}).get("HP")
            if not bool(enemy.get("is_defeated")) and (hp is None or int(hp) > 0):
                alive_candidates.append(rec)

        best, best_score = None, 0
        for rec in candidates:
            for alias in rec["aliases"]:
                alias_n = re.sub(r"[^0-9a-z가-힣]+", "", str(alias).lower())
                if not alias_n: continue
                score = 120 if text_norm == alias_n else (80 if alias_n in text_norm else 0)
                if score > best_score: best, best_score = rec, score

        if best and best_score > 0: return best["id"], best["name"], "explicit"
        pool = alive_candidates or candidates
        idx = int(hashlib.sha256(f"{state.get('session_id')}|{user_input}".encode()).hexdigest()[:8], 16) % len(pool)
        return pool[idx]["id"], pool[idx]["name"], "random"

    @staticmethod
    def pick_deterministic(seed: str, pool: list[str]) -> str:
        if not pool: return "narrator"
        idx = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % len(pool)
        return pool[idx]

    @classmethod
    def build_delta_brief(cls, final_diffs: list[EntityDiff] | None, before: Dict, after: Dict, actor_id: str | None, target_id: str | None) -> str:
        actor_label = EntityResolver.resolve_label(str(actor_id or ""), after or before)
        lines = [f"- actor: {actor_label} (id={actor_id})"]
        if target_id:
            lines.append(f"- target: {EntityResolver.resolve_label(str(target_id), after or before)} (id={target_id})")
        
        if not final_diffs:
            return "\n".join(lines + ["- diffs: (none)"])
        lines.append("- diffs:")
        for d in final_diffs:
            label = EntityResolver.resolve_label(str(d.entity_id), after or before)
            before_entity = cls._find_entity_snapshot(before, d.entity_id)
            after_entity = cls._find_entity_snapshot(after, d.entity_id)
            entries = []
            for key, value in (d.diff or {}).items():
                desc = cls._describe_diff(before, after, d.entity_id, before_entity, after_entity, key, value)
                if desc:
                    entries.append(desc)
            if not entries:
                diff_value = cls._format_diff_value(d.diff)
                entries.append(f"(updated) {diff_value}")
            lines.append(f"  - {label}(id={d.entity_id}): " + ", ".join(entries[:6]))
        return "\n".join(lines)

    ATTRIBUTE_LOOKUP = {
        "hp": {"label": "HP", "aliases": ["hp", "current_hp"]},
        "san": {"label": "SAN", "aliases": ["san"]},
        "affinity": {"label": "affinity", "aliases": ["affinity_score", "affinity"]},
    }

    @classmethod
    def _find_entity_snapshot(cls, snapshot: Dict[str, Any], entity_id: str | None) -> Dict[str, Any]:
        if not snapshot or not entity_id:
            return {}
        target = str(entity_id or "").strip()
        if not target:
            return {}
        target_lower = target.lower()
        player = snapshot.get("player") or {}
        if target_lower == "player":
            return player
        player_id = str(player.get("player_id") or "").strip().lower()
        if player_id and player_id == target_lower:
            return player
        for key in ("npcs", "enemies"):
            for entity in (snapshot.get(key) or []):
                for attr in ("id", "npc_id", "enemy_id", "scenario_entity_id", "scenario_npc_id", "scenario_enemy_id"):
                    value = entity.get(attr)
                    if value and str(value).strip().lower() == target_lower:
                        return entity
        return {}

    @classmethod
    def _describe_diff(cls, before_snap: Dict[str, Any], after_snap: Dict[str, Any], entity_id: str, before_entity: Dict[str, Any], after_entity: Dict[str, Any], attr_key: str, diff_value: Any) -> str:
        before_val = cls._extract_snapshot_value(before_snap, entity_id, before_entity, attr_key)
        after_val = cls._extract_snapshot_value(after_snap, entity_id, after_entity, attr_key)
        attr_label = cls.ATTRIBUTE_LOOKUP.get(attr_key, {}).get("label", attr_key.upper())
        computed_after = cls._apply_delta(before_val, diff_value)
        if after_val is None and computed_after is not None:
            after_val = computed_after
        if before_val is None and after_val is None:
            return f"{attr_label}: {cls._format_diff_value(diff_value)}"
        before_display = cls._format_value(before_val) if before_val is not None else "?"
        after_display = cls._format_value(after_val) if after_val is not None else cls._format_value(diff_value)
        return f"{attr_label} {before_display} → {after_display}"

    @classmethod
    def _extract_snapshot_value(cls, snapshot: Dict[str, Any], entity_id: str, entity: Dict[str, Any], attr_key: str) -> Any:
        if not snapshot or not entity_id:
            return None
        if attr_key == "affinity":
            relation = cls._find_player_relation(snapshot, entity_id)
            if relation:
                return relation.get("affinity_score") or relation.get("affinity")
        if entity:
            if attr_key in entity:
                return entity.get(attr_key)
            for alias in cls.ATTRIBUTE_LOOKUP.get(attr_key, {}).get("aliases", []):
                if alias in entity:
                    return entity.get(alias)
        return None

    @staticmethod
    def _find_player_relation(snapshot: Dict[str, Any], entity_id: str) -> Dict[str, Any] | None:
        for relation in (snapshot.get("player_relations") or []):
            npc_id = str(relation.get("npc_id") or relation.get("id") or "").strip()
            if npc_id and npc_id.lower() == str(entity_id or "").strip().lower():
                return relation
        return None

    @staticmethod
    def _apply_delta(before: Any, diff_value: Any) -> Any:
        if before is not None and isinstance(before, (int, float)) and isinstance(diff_value, (int, float)):
            return before + diff_value
        return None

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return "?"
        text = str(value)
        return text if len(text) <= 40 else text[:37] + "..."

    @staticmethod
    def _format_diff_value(value: Any) -> str:
        text = str(value)
        return text if len(text) <= 40 else text[:37] + "..."

    @classmethod
    def describe_natural_diffs(cls, final_diffs: list[EntityDiff] | None, before: Dict[str, Any] | None, after: Dict[str, Any] | None) -> list[str]:
        lines: list[str] = []
        if not final_diffs:
            return lines
        for diff in final_diffs:
            label = EntityResolver.resolve_label(str(diff.entity_id), after or before or {})
            before_snap = cls._find_entity_snapshot(before or {}, diff.entity_id)
            after_snap = cls._find_entity_snapshot(after or {}, diff.entity_id)
            for attr_key, value in (diff.diff or {}).items():
                attr_label = cls.ATTRIBUTE_LOOKUP.get(attr_key, {}).get("label", attr_key.upper())
                before_val = cls._extract_snapshot_value(before or {}, diff.entity_id, before_snap, attr_key)
                after_val = cls._extract_snapshot_value(after or {}, diff.entity_id, after_snap, attr_key)
                if before_val is not None and after_val is not None:
                    verb = "증가" if after_val > before_val else ("감소" if after_val < before_val else "변화")
                    lines.append(f"{label}의 {attr_label}이 {cls._format_value(before_val)}에서 {cls._format_value(after_val)}로 {verb}했습니다.")
                elif after_val is not None:
                    lines.append(f"{label}의 {attr_label}이 {cls._format_value(after_val)}로 변경되었습니다.")
                elif before_val is not None:
                    lines.append(f"{label}의 {attr_label}이 {cls._format_value(before_val)}에서 변경되었습니다.")
                else:
                    lines.append(f"{label}의 {attr_label} 값이 변경되었습니다.")
        return lines
