# GM (Game Master Orchestrator) 구현 계획

## 0. 목적과 현황

### 목적

- `global-plan.md`에 정의된 TRPG 시스템의 핵심 오케스트레이터인 GM 서비스를 구현한다.
- 플레이어/NPC의 입력을 받아 전체 파이프라인(Rule, Scenario, State, LLM)을 제어하고 상태를 확정한다.

### 현황

- 프로젝트 초기화 완료 (`src/gm/__init__.py`, `tests/conftest.py` 존재)
- 상세 설계 완료 (`global-plan.md`)
- 구현 시작 단계

---

## 1. 구현 단계별 계획

### 1단계: 프로젝트 기초 설정 및 인터페이스 정의

- [x] FastAPI 기반 기본 서버 구조 설정
- [x] 타 서비스(Rule, Scenario, State, LLM)와의 통신을 위한 인터페이스 및 데이터 모델(Pydantic) 정의
- [x] `PlayLog` DB 스키마 정의 및 asyncpg 설정 (PostgreSQL)

### 2단계: 핵심 파이프라인(플레이어 턴) 구현

- [x] 사용자 입력 수신 및 `turn_id` 생성 로직
- [x] Rule/Scenario Manager 호출 및 제안 객체 취합 로직
- [x] `Scenario > Rule` 우선순위 기반 최종 결정 및 상태 diff 생성 로직
- [x] State Manager 커밋 요청 및 결과 처리 (Mock 상태)
- [x] LLM Gateway를 통한 서술 생성 요청 (Mock 상태)
- [x] `PlayLog` 기록 기능 구현

### 3단계: NPC 턴 및 오케스트레이션 확장

- [x] State/Scenario 컨텍스트 수집 로직 (Stub 구현)
- [x] NPC 행동 생성 및 재귀적 파이프라인 호출 구현
- [x] NPC 턴 처리에 대한 단위 테스트 추가
- [x] 오류 처리 및 재시도 로직 강화 (커밋 실패, 서술 슬롯 불만족 등)
- [x] LangGraph 도입: 턴 처리 파이프라인을 그래프 구조로 리팩토링
- [x] LLM 연동 리팩토링: LangChain Custom Adapter 도입 및 OpenAI 호환 스키마 적용

### 4단계: 테스트 및 고도화

- [x] 기본 단위/통합 테스트 작성
- [ ] Mock 서비스를 이용한 파이프라인 정밀 검증
- [ ] 실제 외부 서비스 연동 테스트

---

## 2. 테스트 전략

- 각 기능 단위마다 `pytest`를 이용한 단위 테스트 수행
- 외부 서비스 호출은 Mock을 활용하여 독립적으로 검증
- 실제 PostgreSQL DB와의 연동 테스트 포함
