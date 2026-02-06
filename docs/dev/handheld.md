# Handheld

<!-- PROJ_UNDERSTANDING_BEGIN -->
## Project Understanding
### What this project is
- TRPG 세션의 **Game Master(GM)** 역할을 수행하는 오케스트레이터 코어 서비스
- **LangGraph** 기반의 상태 머신으로 동작하며, 룰(Rule)·시나리오(Scenario)·상태(State)를 엄격하게 관리하면서 LLM 서사를 생성
- 핵심 파이프라인: `상태 조회` → `주체 선정` → `행동 생성` → `룰 판정` → `시나리오 검증` → `충돌 해결` → `상태 반영` → `서사 생성` → `로그 저장`

### Architecture link
- <!-- PROJ_ARCH_LINK -->docs/dev/architect/architecture_v0.0.0.md

### How to run
- 로컬 실행: `bin/project run` (localhost:8020)
- Docker Compose 실행: `bin/compose-start` 또는 `bin/project run-compose`

### How to test (unit)
- `uv run pytest tests`

### How to run e2e
- `bin/compose-start` 실행 후 통합 테스트 스크립트 활용 (e.g., `scripts/verify_gm_flow.py`)

### Conventions / gotchas
- **프롬프트 관리**: `src/gm/core/engine/prompts/`에서 상황별 텍스트 파일로 관리
- **DB 안정성**: 시작 시 자동 재시도 및 `/system/reconnect` 엔드포인트를 통한 수동 재연결 지원
- **도구**: `uv` 패키지 매니저, `ruff` 린터/포맷터 (`bin/project lint`)
- **설정**: 기본 포트 8020, API 버전 `/api/v1`
<!-- PROJ_UNDERSTANDING_END -->

<!-- PROJ_WORKNOTES_BEGIN -->
## Work Notes by Detail
<!-- PROJ_WORKNOTES_END -->
