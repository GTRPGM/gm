from typing import Any, Dict


class CombatChecker:
    @staticmethod
    def has_live_enemies(snapshot: Dict[str, Any]) -> bool:
        current_seq_id = str(snapshot.get("current_sequence_id") or "")
        enemies = snapshot.get("enemies", []) or []
        for enemy in enemies:
            if not isinstance(enemy, dict):
                continue
            if (
                current_seq_id
                and str(enemy.get("assigned_sequence_id") or "") != current_seq_id
            ):
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
    def count_live_enemies(snapshot: Dict[str, Any]) -> int:
        current_seq_id = str(snapshot.get("current_sequence_id") or "")
        count = 0
        for enemy in snapshot.get("enemies", []) or []:
            if not isinstance(enemy, dict):
                continue
            if (
                current_seq_id
                and str(enemy.get("assigned_sequence_id") or "") != current_seq_id
            ):
                continue
            if bool(enemy.get("is_defeated")):
                continue
            hp = enemy.get("current_hp") or (
                (enemy.get("state") or {}).get("numeric") or {}
            ).get("HP")
            try:
                if hp is None or int(hp) > 0:
                    count += 1
            except (TypeError, ValueError):
                count += 1
        return count

    @staticmethod
    def is_last_sequence(
        current_sequence_id: str | None, act_details: Dict[str, Any] | None
    ) -> bool:
        if not current_sequence_id or not isinstance(act_details, dict):
            return False
        sequence_ids = act_details.get("sequence_ids") or []
        return bool(sequence_ids and str(sequence_ids[-1]) == str(current_sequence_id))
