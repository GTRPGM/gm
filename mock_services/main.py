from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="GM Mock Services")

# --- Schemas (Simplified copies from src/gm/schemas) ---


class RuleRequestEntity(BaseModel):
    entity_id: Any
    entity_name: str


class RuleRequestRelation(BaseModel):
    cause_entity_id: Any
    effect_entity_id: Any
    type: str


class RuleCheckRequest(BaseModel):
    session_id: Any
    scenario_id: Any
    entities: List[RuleRequestEntity]
    relations: List[RuleRequestRelation]
    story: str


class RulesuggestedDiff(BaseModel):
    entity_id: Any
    diff: Any


class RuleSuggestion(BaseModel):
    diffs: List[RulesuggestedDiff] = []
    relations: List[Any] = []


class RuleOutcomeData(BaseModel):
    session_id: Any
    scenario_id: Any
    phase_type: str = "탐험"
    reason: str
    success: bool
    suggested: RuleSuggestion
    value_range: Optional[Any] = None


class RuleCheckResponse(BaseModel):
    status: str = "success"
    data: RuleOutcomeData
    message: str = "OK"


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


@app.post("/play/scenario", response_model=RuleCheckResponse)
async def check_rule(request: RuleCheckRequest):
    print(f"[Rule] Checking story: {request.story}")
    return RuleCheckResponse(
        data=RuleOutcomeData(
            session_id=request.session_id,
            scenario_id=request.scenario_id,
            reason="Action appears feasible within standard parameters.",
            success=True,
            suggested=RuleSuggestion(diffs=[]),
        )
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


@app.post("/api/v1/chat/completions")
async def generate_narrative(request: Dict[str, Any]):
    print(f"[LLM] Generating narrative. Messages: {request.get('messages')}")
    content = "As you attempt your action, the mock gods smile upon you."

    return {
        "id": "chatcmpl-mock-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
    }


@app.post("/api/v1/llm/npc-action")
async def generate_npc_action(request: NpcActionRequest):
    print(f"[LLM] Generating NPC action for session {request.session_id}")
    return {"action_text": "The shopkeeper nods slowly, 'I might have what you need.'"}


@app.get("/health")
async def health():
    return {"status": "ok"}
