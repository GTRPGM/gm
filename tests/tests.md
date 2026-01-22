# GM Service Test Plan & Status

## 1. Existing Tests Overview

### `tests/test_main.py`

- **Purpose**: 기본 서버 상태 및 DB 연결 확인
- **Tests**:
  - `test_root`: 루트 경로 (`/`) 응답 확인.
  - `test_health_check`: `/health` 엔드포인트 및 DB 연결 상태 확인.

### `tests/test_schemas.py`

- **Purpose**: Pydantic 모델 유효성 검사 (데이터 무결성)
- **Tests**:
  - `test_rule_outcome_validation`: Rule Manager 응답 모델 검증 (필수 필드, 타입 등).
  - `test_scenario_suggestion_validation`: Scenario Manager 응답 모델 검증 (Enum, 옵셔널 필드).
  - `test_state_commit_request_validation`: State Manager 요청 모델 검증 (EntityDiff 구조).

### `tests/test_game.py`

- **Purpose**: 전체 게임 턴 처리 통합 테스트 (Mocked External Services)
- **Tests**:
  - `test_process_turn_success`: 플레이어 턴 처리 엔드포인트 (`/api/v1/game/turn`) 호출 및 정상 응답 확인.
  - `test_process_npc_turn`: NPC 턴 처리 서비스 메서드 호출 및 결과 구조 확인.

---

## 2. New Test Plan: Pipeline Precision Verification

### Target File: `tests/test_pipeline_precision.py`

**Goal**: 외부 서비스의 개입을 배제한 상태에서, LangGraph 기반 파이프라인(`src/gm/services/graph.py`)의 **오케스트레이션 로직**을 정밀 검증합니다.

### Planned Test Cases

#### 1. Conflict Resolution (충돌 해결)

- **Scenario**: Rule Manager는 "공격 성공(HP -10)"을 제안하지만, Scenario Manager가 "방어 보정(HP -5)"을 제안하는 상황.
- **Verification**:
  - 파이프라인이 Scenario의 제안을 우선순위로 채택하여 최종 상태(`final_diffs`)가 HP -5로 계산되는지 확인.
  - 두 서비스의 Diff가 올바르게 병합되는지 검증.

#### 2. Narrative Retry Logic (서술 재시도)

- **Scenario**: Scenario Manager가 서술 생성 시 필수 포함 단어(Slot)를 지정했으나, LLM이 첫 번째 시도에서 이를 누락한 경우.
- **Verification**:
  - 파이프라인이 LLM 결과를 검사하고, 조건을 만족하지 못했을 때 자동으로 재시도(Retry)하는지 확인.
  - 재시도 횟수 제한 내에 성공하면 해당 결과를 반환하고, 외부 서비스 호출 횟수가 증가했는지 확인.

#### 3. Error Handling & Circuit Breaking (에러 처리)

- **Scenario**: State Manager(DB Commit) 단계에서 500 에러 또는 타임아웃 발생.
- **Verification**:
  - 파이프라인이 즉시 중단되고 예외를 적절히 전파하는지 확인.
  - 실패한 트랜잭션 이후에 불필요하게 LLM(Narrative Generation) 단계로 넘어가지 않는지(Side Effect 방지) 검증.

#### 4. NPC Turn Workflow (NPC 턴 흐름)

- **Scenario**: NPC 턴이 시작될 때 LLM을 통해 행동을 생성하는 과정.
- **Verification**:
  - `is_npc_turn` 플래그에 따라 `generate_npc_input` 노드가 실행되어 `user_input`이 자동으로 채워지는지 확인.
  - 이후 파이프라인(Rule -> Scenario -> State)이 플레이어 턴과 동일하게 이어지는지 검증.
