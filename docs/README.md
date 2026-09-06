# mcp-work-agent 문서

수정일: 2026-09-06

제품을 이해할 때는 아래 제품 문서를 읽는다. 구현 위치·상태 전이·wire schema는 고정된 기술 계약을 확인한다. 문서에 기능이 정의되어 있다는 사실은 구현 또는 실제품 검증 완료를 뜻하지 않는다.

## 제품 문서 — 이 순서로 읽기

| 문서 | 답하는 질문 |
| --- | --- |
| [요구사항 · PRD](canonical/01-requirements-prd.md) | 어떤 문제를 해결하며 어디까지 출시하는가? |
| [기능 정의](canonical/01-a-functional-definition.md) | 사용자가 무엇을 할 수 있고 어떤 결과를 받아야 하는가? |
| [정책 정의](canonical/01-b-policy-definition.md) | 어떤 조건에서 허용·확인·승인·차단하는가? |
| [UI · UX](canonical/02-ui-ux-design.md) | 사용자가 어디서 보고 조작하며 진행과 결과를 어떻게 구분하는가? |
| [작업 현황 · 남은 검증](product-decisions/2026-09-06-product-document-realignment.md) | 무엇이 확인됐고 무엇을 다음에 검증해야 하는가? |

각 제품 문서에 설명과 상세 본문을 함께 둔다. 별도 설명본을 또 하나의 원본으로 관리하지 않는다. GitHub는 수정 원본, Notion은 선정한 원문의 읽기용 게시본이다.

## 기술 계약 — 이번 문서 작업의 읽기 전용 기준

전체 권위와 읽는 순서는 [Project Source Guide](canonical/00-project-source-guide.md)를 따른다. 아래 문서는 이번 제품 문서 정리에서 변경하지 않는다.

| 주제 | 문서 |
| --- | --- |
| 시스템 경계 | [시스템 아키텍처](canonical/03-system-architecture.md) |
| 영속 사실·상태 전이 | [Domain·DB](canonical/04-domain-database-design.md), [State Transition Contract](canonical/04-a-domain-state-transition-contract.md) |
| 검색·실행 흐름 | [Retrieval](canonical/05-context-retrieval.md), [Agent·Workflow](canonical/06-agent-workflow.md) |
| 인터페이스·순서 | [Tool·MCP·Interface](canonical/07-tool-mcp-internal-interface.md), [Sequence](canonical/08-sequence-design.md) |
| 보안·배포·관측 | [Security](canonical/09-security-auth.md), [Infrastructure](canonical/10-infrastructure-environment.md), [Observability](canonical/11-observability-logging-audit.md) |
| 검증·실험·운영 | [Test](canonical/12-test-design.md), [State Test Matrix](canonical/12-a-state-transition-test-matrix.md), [Evaluation](canonical/13-evaluation-experiment.md), [Operations](canonical/14-operations-troubleshooting.md) |
| Prompt·코드 규격 | [Prompt·Failure](canonical/15-agent-capability-failure-prompt-contract.md), [Repository Architecture](canonical/16-repository-architecture/16-repository-architecture-source.md) |

새 제품 요구가 보호 계약의 변경을 필요로 하면 미정합 사항을 작업 현황에 남긴다. 제품 문서나 README가 새 operation, schema, guard, 예외 허용을 대신 승인하지 않는다.

## 문서 관리

문서의 현재성은 각 문서의 수정일로 표시하고 상세 변경 이력은 Git에 남긴다. 다른 문서의 수정일·문서 버전에 의존하는 본문을 만들지 않는다. API·artifact·DB schema의 실제 계약 버전과 migration 이력은 이 원칙의 대상이 아니며 임의 삭제하거나 변경하지 않는다.

기능 ID·정책 ID는 각 문서 안의 안정적인 식별자다. 기능 문장을 정책에 복사하거나 기능 ID와 정책 ID를 일대일로 연결하지 않는다. 필요할 때만 문서의 책임 또는 안정적인 개념을 참조한다. 다른 문서의 표현만 바뀌고 자기 책임의 의미가 같으면 수정하지 않는다.

`product-decisions/`는 결정 배경과 검증 시점의 기록이다. 과거 보고의 PASS를 최신 제품의 PASS로 재사용하지 않는다. `artifacts/product-closure/`의 매핑표·검증 기록은 이력으로 보존한다. `database/migrations/`는 실행 migration의 문서 미러이며 [Database 안내](database/README.md)의 규칙을 따른다. 문서 작업만으로 SQL을 추가·재번호·수정하지 않는다.
