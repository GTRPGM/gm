# Scenario Manager API Interface

GM Core가 시나리오 정합성 확인 및 보정을 위해 호출하는 인터페이스입니다.

## 1. Scenario Check

룰 판정 결과가 시나리오 제약 조건에 위배되는지 확인하고 보정안을 제시합니다.

- **Endpoint**: `POST /api/v1/scenario/check`
- **Request Body**:

```json
{
  "input_text": "string (사용자 입력 문장)",
  "rule_outcome": {
    "description": "string",
    "success": "boolean",
    "suggested_diffs": "list",
    "value_range": "object"
  }
}
```

- **Response Body**:

```json
{
  "constraint_type": "string (mandatory/advisory)",
  "description": "string (시나리오 영향 설명)",
  "correction_diffs": [
    {
      "entity_id": "string",
      "diff": { "field": "value" }
    }
  ],
  "narrative_slot": "string (서술에 반드시 포함되어야 할 키워드나 문구)"
}
```
