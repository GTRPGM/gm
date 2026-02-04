import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel

app = FastAPI(title="GTRPGM Integrated Mock Services")


# --- Helpers ---
def wrap_response(data: Any, message: str = "OK"):
    return {"status": "success", "data": data, "message": message}


# --- Schemas ---
class EntityUnit(BaseModel):
    state_entity_id: str
    entity_id: Optional[int] = None
    quantity: Optional[int] = None
    phase_id: int
    entity_name: str
    entity_type: str


class RulePlayResponse(BaseModel):
    session_id: int
    scenario_id: int
    phase_type: str
    reason: str
    success: bool
    suggested: Dict[str, Any]
    value_range: Optional[float] = None


class ValidationOutput(BaseModel):
    is_triggered: bool
    reason: str
    next_act_id: Optional[str] = None
    next_seq_id: Optional[str] = None
    suggested_narration: Optional[str] = None


class SessionInfo(BaseModel):
    session_id: str
    scenario_id: str
    current_act_id: str = "act-1"
    current_sequence_id: str = "seq-1"
    current_phase: str = "exploration"
    status: str = "active"


# --- Endpoints ---


@app.post("/play/scenario")
async def rule_play_scenario(request: Request):
    body = await request.json()
    print(f"[RuleEngine] Received request for story: {body.get('story')}")

    data = {
        "session_id": body.get("session_id", 1),
        "scenario_id": body.get("scenario_id", 1),
        "phase_type": "탐험",
        "reason": "행동이 규칙 내에서 가능합니다.",
        "success": True,
        "suggested": {
            "diffs": [{"entity_id": "player", "diff": {"hp_delta": -2}}],
            "relations": [],
        },
        "value_range": None,
    }
    return wrap_response(data)


@app.post("/api/v1/check/session")
async def scenario_check_session(request: Request):
    body = await request.json()
    print(f"[ScenarioService] Checking session {body.get('session_id')}")

    return {
        "is_triggered": False,
        "reason": "시나리오 전개상 특이사항 없음",
        "suggested_narration": "주변에는 차가운 정적만이 흐릅니다.",
    }


@app.get("/state/session/{session_id}")
async def state_get_session(session_id: str):
    print(f"[StateManager] Fetching state for {session_id}")
    data = {
        "entities": ["player", "goblin_scout", "ancient_chest"],
        "relations": [],
        "environment": "Dark Cave (Mocked)",
    }
    return wrap_response(data)


@app.post("/api/v1/state/commit")
async def state_commit(request: Request):
    body = await request.json()
    print(f"[StateManager] Committing diffs: {body.get('diffs')}")
    return {
        "commit_id": f"mock-commit-{uuid.uuid4().hex[:8]}",
        "status": "success",
        "timestamp": "2026-02-02T00:00:00Z",
    }


@app.post("/api/v1/chat/completions")
async def llm_chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    last_msg = messages[-1].get("content", "") if messages else ""
    print(f"[LLM] Processing prompt: {last_msg[:50]}...")

    content = "당신은 어둠 속으로 한 걸음 더 내딛습니다."
    if "행동할 주체" in last_msg:
        content = "goblin_scout"
    elif "행동을 짧고 간결하게" in last_msg:
        content = "고블린 정찰병이 어둠 속에서 당신을 지켜보며 칼을 갈고 있습니다."

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": 123456789,
        "model": "mock-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
