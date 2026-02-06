# Architecture v0.0.0

## Summary
- FastAPI와 LangChain/LangGraph를 기반으로 하는 GM 코어 서비스 아키텍처

## Context
- LLM을 활용한 게임 마스터링 로직을 서비스화하기 위함
- 비동기 DB 접근 및 외부 API 연동이 주요 요구사항

## System overview
- **Web Framework**: FastAPI
- **LLM Framework**: LangChain, LangGraph
- **Database**: PostgreSQL (asyncpg)
- **Infra**: Docker Compose를 통한 서비스 오케스트레이션 (GM Core, Mock Services, DB 등)

## Data flow
1. 클라이언트 요청이 API Endpoint (`src/gm/api/v1/`)로 유입
2. Game Engine (`src/gm/core/engine/`)에서 비즈니스 로직 및 LLM 워크플로우 처리
3. DB Handler (`src/gm/infra/db/`)를 통해 상태 저장 및 조회
4. 결과 반환

## Decisions
- Decision: `uv` 사용
- Reason: 빠른 패키지 설치 및 의존성 관리 최적화
- Impact: 개발 환경 구성 속도 향상

- Decision: LangGraph 도입
- Reason: 복잡한 상태 기반 LLM 에이전트 워크플로우 관리가 용이함
- Impact: 유연한 게임 시나리오 확장 가능

## Compatibility / migration notes
- 초기 버전으로 현재 마이그레이션 이슈 없음
