# GM Core Service - Handheld Guide

## 1. 프로젝트 정체성

- **역할**: TRPG 세션의 **Game Master(GM)** 역할을 수행하는 백엔드 코어 서비스
- **목표**: 규칙(Rule), 시나리오(Scenario), 상태(State)를 엄격하게 관리하면서 LLM을 통해 몰입감 있는 서사를 생성
- **핵심 가치**: 단순한 챗봇이 아닌, 게임적 논리와 서사적 자유도를 결합한 **오케스트레이터**

## 2. 시스템 아키텍처

이 서비스는 **LangGraph**를 기반으로 한 상태 머신(State Machine)으로 동작하며, 여러 마이크로서비스와 협업합니다.

### 2.1 턴 처리 파이프라인 (Game Loop)

`User/NPC Input` → `Pipeline` → `State Update` → `Narrative Generation`

| 단계 | 노드명 (`Node`) | 역할 |
| :--- | :--- | :--- |
| **1. 상태 조회** | `fetch_state` | State Manager로부터 현재 월드 상태(위치, 엔티티 등) 로드 |
| **2. 주체 선정** | `select_active_entity` | 이번 턴의 행동 주체 결정 (플레이어, 특정 NPC, 또는 나레이터) |
| **3. 행동 생성** | `generate_npc_input` | (NPC 턴일 경우) LLM을 사용하여 문맥에 맞는 행동/대사 생성 |
| **4. 룰 판정** | `check_rule` | Rule Manager에 질의하여 행동의 성공/실패 및 스탯 변화 계산 |
| **5. 시나리오 검증** | `check_scenario` | Scenario Manager에 질의하여 스토리 흐름, 제약 조건, 이벤트 확인 |
| **6. 충돌 해결** | `resolve_conflicts` | 룰과 시나리오의 제안을 취합하여 최종 상태 변경분(Diff) 확정 |
| **7. 상태 반영** | `commit_state` | State Manager에 변경 사항 커밋 (Act/Sequence 전환 포함) |
| **8. 서사 생성** | `generate_narrative` | 확정된 결과(Outcome)를 바탕으로 LLM이 최종 묘사 텍스트 작성 |
| **9. 로그 저장** | `save_log` | DB에 턴 로그 저장 |

### 2.2 외부 의존성 (Microservices)

- **Rule Manager**: `POST /check` - 행동 판정
- **Scenario Manager**: `POST /check` - 스토리 흐름 제어
- **State Manager**: `POST /commit` - 게임 데이터 영속성 관리
- **LLM Gateway**: `POST /chat` - 텍스트 생성

## 3. 기술 스택 및 환경

- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Core Engine**: LangGraph (Workflow Orchestration)
- **Package Manager**: uv
- **Database**: PostgreSQL (Play Log 저장)
- **Infrastructure**: Docker, Docker Compose

## 4. 주요 개발 포인트

- **프롬프트 관리**: `src/gm/core/engine/prompts/` 디렉토리에서 상황별(NPC, 서술, 선택 등) 프롬프트 텍스트 파일로 관리
- **DB 안정성**: 서버 시작 시 자동 재시도(Retry) 및 런타임 수동 재연결(`/system/reconnect`) 지원
- **테스트 전략**: `pytest` 및 `pytest-mock`을 사용하여 외부 서비스 의존성을 격리한 상태에서 로직 검증

## 5. 디렉토리 구조 요약

- `src/gm/core/engine/`: 게임 로직, LangGraph 정의
- `src/gm/interfaces/`: 외부 서비스 통신을 위한 Port/Adapter 정의
- `src/gm/infra/db/`: DB 쿼리 및 연결 관리
- `tests/`: 통합 및 단위 테스트
