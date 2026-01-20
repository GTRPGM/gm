from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="GM Mock Services")

# --- Schemas (Simplified copies from src/gm/schemas) ---


class RuleCheckRequest(BaseModel):
    input_text: str
    context: Dict[str, Any]


class RuleOutcome(BaseModel):
    description: str
    success: bool
    suggested_diffs: List[Dict[str, Any]] = Field(default_factory=list)
    required_entities: List[str] = Field(default_factory=list)
    value_range: Optional[Dict[str, float]] = None


class ScenarioCheckRequest(BaseModel):
    input_text: str
    rule_outcome: Dict[str, Any]


class ScenarioSuggestion(BaseModel):
    constraint_type: str = "advisory"
    description: str
    correction_diffs: List[Dict[str, Any]] = Field(default_factory=list)
    narrative_slot: Optional[str] = None


class StateCommitRequest(BaseModel):
    turn_id: str
    diffs: List[Dict[str, Any]]


class NarrativeRequest(BaseModel):
    turn_id: str
    commit_id: str
    input_text: str
    rule_outcome: Dict[str, Any]


class NpcActionRequest(BaseModel):
    session_id: str
    context: Dict[str, Any]


# --- Endpoints ---


@app.post("/api/v1/rule/check", response_model=RuleOutcome)
async def check_rule(request: RuleCheckRequest):
    print(f"[Rule] Checking: {request.input_text}")
    return RuleOutcome(
        description="Action appears feasible within standard parameters.",
        success=True,
        suggested_diffs=[],
        required_entities=[],
    )


@app.post("/api/v1/scenario/check", response_model=ScenarioSuggestion)
async def check_scenario(request: ScenarioCheckRequest):
    print("[Scenario] Checking scenario constraints.")
    return ScenarioSuggestion(
        constraint_type="advisory",
        description="No major plot deviations detected.",
        correction_diffs=[],
        narrative_slot="Remember to mention the ominous fog.",
    )


@app.post("/api/v1/state/commit")
async def commit_state(request: StateCommitRequest):
    print(f"[State] Committing turn {request.turn_id} with {len(request.diffs)} diffs.")
    return {
        "status": "committed",
        "commit_id": "mock-commit-12345",
        "turn_id": request.turn_id,
    }


@app.post("/api/v1/llm/narrative")
async def generate_narrative(request: NarrativeRequest):
    print(f"[LLM] Generating narrative for turn {request.turn_id}")
    return {
        "narrative": (
            f"As you attempt to '{request.input_text}', "
            "the world reacts accordingly. The mock gods smile upon you."
        )
    }


@app.post("/api/v1/llm/npc-action")
async def generate_npc_action(request: NpcActionRequest):
    print(f"[LLM] Generating NPC action for session {request.session_id}")
    return {"action_text": "The shopkeeper nods slowly, 'I might have what you need.'"}


@app.get("/health")
async def health():
    return {"status": "ok"}
