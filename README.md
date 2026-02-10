# Game Master (GM) Service

## 📖 개요 (Overview)

**GM Service**는 게임의 메인 루프를 담당하는 핵심 엔진입니다. 플레이어와 NPC의 턴을 관리하고, 룰 엔진(Rule Engine)과 시나리오 서비스(Scenario Service)의 판정을 종합하여 최종적인 게임 상태(State)를 갱신하고 서사(Narrative)를 생성합니다.

## 🏗️ 아키텍처 및 기술 스택 (Architecture & Tech Stack)

### 기술 스택 (Tech Stack)

- **Language**: Python 3.11+
- **Framework**: FastAPI
- **LLM Orchestration**: LangGraph, LangChain
- **Database**: PostgreSQL (AsyncPG)
- **Logging**: PostgreSQL (Play Logs)

### 주요 아키텍처 (Core Architecture)

GM 서비스는 **LangGraph** 기반의 `GameEngine` 클래스를 통해 턴(Turn) 단위의 상태 머신을 실행합니다.

#### 상태 전이 (State Transitions in GameEngine)

게임 루프는 다음 노드들의 순차적 실행으로 이루어집니다:

1. **`fetch_state`**: State Manager로부터 현재 월드 스냅샷을 로드합니다.
2. **`init_turn`**: 턴 ID를 발급하고 초기화합니다.
3. **`select_active_entity`**: 이번 턴의 행동 주체를 결정합니다.
   - **Player Turn**: 플레이어 고정.
   - **NPC Turn**: 생존한 적(Enemy) > 활성 NPC > 나레이터 순으로 우선순위 기반 결정 (Deterministic).
4. **`generate_npc_input`** (NPC Turn Only): LLM을 사용하여 NPC나 적의 행동/대사를 생성합니다.
5. **`check_rule`**: Rule Engine에 행동에 대한 판정(성공/실패/효과)을 요청합니다.
6. **`check_scenario`**: Scenario Service에 시나리오 진행(이벤트 트리거 등)을 확인합니다.
7. **`resolve_conflicts`**: 룰 엔진의 결과와 시나리오의 강제 이벤트를 병합(Merge)하여 최종 상태 변경 사항(Diffs)을 도출합니다.
8. **`commit_state`**: State Manager에 최종 변경 사항을 반영하고, Act/Sequence 전환을 처리합니다.
9. **`generate_narrative`**: 변경된 상태와 행동 결과를 바탕으로 문학적인 서사(Narrative)를 생성합니다.
10. **`save_log`**: 턴 로그를 DB에 저장합니다.

## 💡 주요 로직 및 설계 중점 (Key Logic & Design Focus)

### 1. 턴 관리 및 주체 선정 (Turn Management)

- **전투(Combat) 우선순위**: 전투 시퀀스에서는 살아있는 적(Enemy)이 우선적으로 턴을 가져가도록 설계되어, 전투가 정체되지 않도록 합니다.
- **결정론적 선택**: 무작위성을 줄이기 위해 시드(Seed) 기반의 결정론적 로직으로 NPC 순서를 결정합니다.

### 2. 서사 가드레일 (Narrative Guardrails)

LLM이 생성하는 서사가 게임 상태와 모순되지 않도록 강력한 제어 로직이 포함되어 있습니다.

- **전투 종료 방지**: 시퀀스에 살아있는 적(HP > 0)이 남아있다면, LLM이 "전투가 끝났다", "승리했다" 등의 표현을 쓰지 못하도록 프롬프트 레벨과 후처리 로직에서 차단합니다.
- **2인칭 금지**: NPC 턴에서는 '당신'이라는 표현을 사용하지 못하게 하여 몰입감을 해치지 않도록 합니다.

### 3. 충돌 해결 (Conflict Resolution)

룰 엔진(시스템적 판정)과 시나리오 엔진(스토리적 강제)이 상충할 경우, 두 결과를 병합하여 처리합니다. 예를 들어, 공격은 성공(Rule)했으나 그로 인해 이벤트가 발생해 적이 도망(Scenario)가는 상황을 자연스럽게 처리합니다.
