import pytest
from gm.core.engine.combat_checker import CombatChecker

def test_has_live_enemies_empty():
    assert CombatChecker.has_live_enemies({}) is False
    assert CombatChecker.has_live_enemies({"enemies": []}) is False

def test_has_live_enemies_basic():
    snapshot = {
        "current_sequence_id": "seq-1",
        "enemies": [
            {"id": "e1", "current_hp": 10, "assigned_sequence_id": "seq-1"},
            {"id": "e2", "current_hp": 0, "assigned_sequence_id": "seq-1"}
        ]
    }
    assert CombatChecker.has_live_enemies(snapshot) is True

def test_has_live_enemies_sequence_mismatch():
    snapshot = {
        "current_sequence_id": "seq-1",
        "enemies": [
            {"id": "e1", "current_hp": 10, "assigned_sequence_id": "seq-2"}
        ]
    }
    # Current sequence is seq-1, but enemy is for seq-2. Should be ignored.
    assert CombatChecker.has_live_enemies(snapshot) is False

def test_has_live_enemies_defeated_flag():
    snapshot = {
        "current_sequence_id": "seq-1",
        "enemies": [
            {"id": "e1", "current_hp": 10, "is_defeated": True, "assigned_sequence_id": "seq-1"}
        ]
    }
    assert CombatChecker.has_live_enemies(snapshot) is False

def test_has_live_enemies_nested_hp():
    snapshot = {
        "current_sequence_id": "seq-1",
        "enemies": [
            {
                "id": "e1", 
                "assigned_sequence_id": "seq-1",
                "state": {"numeric": {"HP": 5}}
            }
        ]
    }
    assert CombatChecker.has_live_enemies(snapshot) is True

def test_has_live_enemies_hp_none_is_live():
    snapshot = {
        "current_sequence_id": "seq-1",
        "enemies": [
            {"id": "e1", "current_hp": None, "assigned_sequence_id": "seq-1"}
        ]
    }
    # HP is None means we assume it's live (or at least not confirmed dead)
    assert CombatChecker.has_live_enemies(snapshot) is True

def test_count_live_enemies():
    snapshot = {
        "current_sequence_id": "seq-1",
        "enemies": [
            {"id": "e1", "current_hp": 10, "assigned_sequence_id": "seq-1"},
            {"id": "e2", "current_hp": 5, "assigned_sequence_id": "seq-1"},
            {"id": "e3", "is_defeated": True, "assigned_sequence_id": "seq-1"},
            {"id": "e4", "current_hp": 10, "assigned_sequence_id": "seq-other"}
        ]
    }
    assert CombatChecker.count_live_enemies(snapshot) == 2

def test_count_live_enemies_invalid_types():
    snapshot = {
        "enemies": ["not-a-dict", {"current_hp": 10}]
    }
    # "not-a-dict" should be skipped, {"current_hp": 10} is live
    assert CombatChecker.count_live_enemies(snapshot) == 1
    # Test has_live_enemies with invalid type as well
    assert CombatChecker.has_live_enemies(snapshot) is True

def test_hp_conversion_error():
    snapshot = {
        "current_sequence_id": "seq-1",
        "enemies": [
            {"id": "e1", "current_hp": "not-a-number", "assigned_sequence_id": "seq-1"}
        ]
    }
    # If HP conversion fails, we assume it's live (safety first)
    assert CombatChecker.has_live_enemies(snapshot) is True
    assert CombatChecker.count_live_enemies(snapshot) == 1

def test_is_last_sequence():
    act_details = {"sequence_ids": ["seq-1", "seq-2", "seq-3"]}
    
    assert CombatChecker.is_last_sequence("seq-3", act_details) is True
    assert CombatChecker.is_last_sequence("seq-1", act_details) is False
    assert CombatChecker.is_last_sequence(None, act_details) is False
    assert CombatChecker.is_last_sequence("seq-3", None) is False
    assert CombatChecker.is_last_sequence("seq-3", {}) is False
