# State Manager API Interface

GM Core가 최종 확정된 세계 상태를 반영하기 위해 호출하는 인터페이스입니다.

## 1. Commit State

상태 변경 사항(Diff)을 원자적으로 반영합니다.

- **Endpoint**: `POST /api/v1/state/commit`
- **Request Body**:

```json
{
  "turn_id": "string (세션ID:턴순번)",
  "diffs": [
    {
      "entity_id": "string",
      "diff": { "field": "value" }
    }
  ]
}
```

- **Response Body**:

```json
{
  "commit_id": "string (상태 버전 식별자)",
  "status": "string (success/fail)"
}
```
