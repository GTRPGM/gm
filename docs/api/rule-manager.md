# Rule Manager API Interface

GM Core가 판정 제안을 받기 위해 호출하는 인터페이스입니다.

## 1. Rule Check

사용자의 자연어 입력을 기반으로 시스템 룰에 따른 판정을 수행합니다.

- **Endpoint**: `POST /api/v1/rule/check`
- **Request Body**:

```json
{
  "input_text": "string (사용자 입력 문장)",
  "context": {
    "key": "value (현재 상태 정보 등)"
  }
}
```

- **Response Body**:

```json
{
  "description": "string (판정 결과에 대한 요약 설명)",
  "success": "boolean (성공/실패 여부)",
  "suggested_diffs": [
    {
      "entity_id": "string (대상 엔티티 ID)",
      "diff": { "field": "value (변경될 데이터)" }
    }
  ],
  "required_entities": ["string (추가 판정에 필요한 엔티티 ID 목록)"],
  "value_range": {
    "field_name": 10.0
  }
}
```
