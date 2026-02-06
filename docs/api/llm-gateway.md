# LLM Gateway API Interface

GM Core가 자연어 서술 및 NPC 행동 생성을 위해 호출하는 인터페이스입니다.

## 1. Generate Narrative

확정된 판정 결과를 바탕으로 사용자에게 보여줄 결과 서술을 생성합니다.

- **Endpoint**: `POST /api/v1/chat/completions`
- **Request Body**:

```json
{
  "model": "string",
  "messages": [
    {
      "role": "system",
      "content": "string",
      "tool_calls": [
        {
          "additionalProp1": {}
        }
      ],
      "tool_call_id": "string"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 0,
  "stream": false,
  "response_format": {
    "additionalProp1": {}
  },
  "tools": [
    {
      "additionalProp1": {}
    }
  ],
  "tool_choice": "string"
}
```

- **Response Body**:

```json
{
  "id": "string",
  "object": "chat.completion",
  "created": 0,
  "model": "string",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "system",
        "content": "string",
        "tool_calls": [
          {
            "additionalProp1": {}
          }
        ],
        "tool_call_id": "string"
      },
      "finish_reason": "string"
    }
  ]
}
```

## 2. Generate NPC Action

현재 상황 컨텍스트를 기반으로 NPC의 다음 행동을 결정합니다.

- **Endpoint**: `POST /api/v1/llm/npc-action`
- **Request Body**:

```json
{
  "session_id": "string",
  "context": {
    "summary": "string (상황 요약)",
    "history": "list (이전 기록)"
  }
}
```

- **Response Body**:

```json
{
  "action_text": "string (NPC의 자연어 행동)"
}
```
